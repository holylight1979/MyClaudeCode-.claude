# Claude Code 全域設定 — 核心架構（Index）

> 本檔為**索引型**。穩定子系統細節放 `DevHistory/` 子檔；本檔只留現役、演化中 feature + 關鍵索引。
> 詳盡規範：`SPEC_ATOM_V4.md`（V4 原子記憶）、`rules/core.md`（行為規則）、`Project_File_Tree.md`（頂層目錄角色說明，30 行；完整檔樹用 `tree -L 3`）。

## Hooks 系統

8 個 hook 事件（含 async Stop），定義在 `settings.json`。主 dispatcher `workflow-guardian.py`（~1570 行）+ 模組化子檔：

| Hook | 觸發時機 | 用途 |
|------|---------|------|
| `UserPromptSubmit` | 使用者送出訊息 | RECALL 記憶檢索 + intent 分類（含 handoff）+ Context Budget 監控 + Wisdom 情境分類 + Failures 偵測 + Evasion 注入 |
| `PreToolUse` (Write/Edit) | Write/Edit 工具呼叫前 | (1) Atom Format Gate：阻擋 `/.claude/memory/*.md` 不符原子格式的寫入；(2) Atom Confidence Gate（2026-04-27）：新建 atom 的 frontmatter `Confidence:` 與內文 `- [固]/- [觀]` 標籤必須全為 `[臨]`，鏡射 MCP `atom_write` mode=create 規則（[server.js:1109-1117](../tools/workflow-guardian-mcp/server.js)）封堵 Write tool 繞過路徑；(3) **Memory Path Block（2026-04-28）**：阻擋寫入 `~/.claude/projects/{slug}/memory/`（原子記憶專案自治層覆寫此路徑），對應 atom `feedback-memory-path` |
| `PreToolUse` (Bash) | Bash 工具呼叫前 | **SVN Test Block（2026-04-28）**：阻擋 `svn commit/ci` 含 `tests?/` `__tests__/` 路徑或 `*Test.<ext>` 檔案（r10854 教訓），對應 atom `feedback-no-test-to-svn` |
| `PostToolUse` (Edit/Write/Bash) | 工具呼叫後 | 追蹤修改檔案 + 增量索引 + Read Tracking + Test-Fail 偵測（Bash）+ _CHANGELOG auto-roll |
| `PreCompact` | Context 壓縮前 | 快照 state |
| `Stop` | 對話結束前 | Sync 閘門 + Fix Escalation + TestFailGate（阻擋完成宣告）+ Evasion Detection |
| `Stop (async)` | 對話結束後 | V3 quick-extract：qwen3:1.7b 5s 快篩 → hot_cache.json |
| `SessionStart` | Session 開始 | 初始化 state + 去重 + Wisdom 盲點 + 定期檢閱 + 專案自治層 delegate |
| `SessionEnd` | Session 結束 | Episodic 生成 + 回應萃取 + 鞏固 + 衝突偵測 + Wisdom 反思 |

### Hook 模組拆分

| 模組 | 行數 | 職責 |
|------|------|------|
| `workflow-guardian.py` | ~1640 | 瘦身 dispatcher：8 event handlers 編排（atom 注入點 line ~1106 起 2026-04-29 改用 `decide_atom_injection` 三態決策 + `[BUDGET]` debug log；trigger-matched 與 spread_related 兩段共享同一 `used_tokens` 計數，cap 800；**REG-005 C-layer Session 2/3 2026-04-29**：注入點加 `atom_source` dict 記錄 `trigger`/`vector`/`related` source；主迴圈每 atom 先 `classify_hot_cold` → cold 走 1 行 `format_cold_inject_line` 不消耗 budget；hot 走原 budget 流程；併呼叫 `wg_atom_observation.log_injection` 寫 append-only `atom-injection-injections-YYYY-MM-DD.log`；**Related 段 D-layer commit 5**：每個 rname 先 `classify_hot_cold(rpath, "related")` → cold 走 1 行 `format_cold_inject_line` 改 `(cold)` 為 `(related, cold)` 標記不 break、不消耗 budget；hot 走原 budget 流程；`spread_related(max_depth=1)` 既有 depth 限制天然滿足 D 層需求，不做 transitive 擴散；**Session 2 補完 commit 6 (2026-04-29)**：SessionStart handler 在 MCP health check 之後加 `_check_reg005_observation_status()`（subprocess 跑 `tools/atom-injection-summary.py --json`，timeout=5，fail-open）+ `_format_reg005_highlight(reg005)` 純函式 → `verdict ∈ {KEEP/ROLLBACK/GRAY}` 才 append 粗體 markdown 高亮訊息引導開 Session 3/3 收尾；`NOT_STARTED/INCOMPLETE` 完全靜默符合「不打擾」原則） |
| `wg_paths.py` | ~451 | 路徑唯一真相來源（V4 sublayer 發現；2026-05-04 S1.1 P1：cwd=~/.claude 自身時 `get_project_memory_dir` 短路返回 global MEMORY_DIR，杜絕雙層 `.claude/.claude/memory/` 污染） |
| `wg_roles.py` | ~210 | V4 角色機制（雙向認證、personal dir bootstrap） |
| `wg_core.py` | ~370 | config / state IO / output / debug / promotion audit |
| `wg_atoms.py` | ~800 | 索引解析 / trigger 匹配 / ACT-R / section 注入 / **A-layer 摘要優先 + B-layer per-turn budget（REG-005, 2026-04-29）**：`_strip_atom_for_injection` 由整檔剝離改為按 atom 類型路由（`impression_action` → frontmatter+印象+行動 / `knowledge_mixed` → frontmatter+印象+知識(cap 200 tokens)+行動 / `fallback` → 沿用 V2.14 legacy strip）。`decide_atom_injection(raw, full, used)` 對每 atom 回 ok/fallback/skip 三態，hard cap `_TURN_BUDGET_LIMIT=800`；超 budget 時 fallback 到 `_strip_atom_for_injection_impression_only`（frontmatter+印象 only），impression-only 仍超則 skip 加 summary 後 break。`SECTION_INJECT_THRESHOLD` 由 300 → 200（更多 atom 走 vector section 提取）。helpers：`_detect_atom_type`、`_extract_named_section(max_tokens)`、`_extract_title_and_frontmatter`（白名單保 Confidence/Trigger/Last-used）。**C-layer hot/cold 分級器（Session 2/3, 2026-04-29）**：`classify_hot_cold(atom_path, source, hot_recent_threshold=3)` — `source="trigger"` 直通 hot；其他依 `_recent_reads_7d({atom}.access.json)` 比門檻；`format_cold_inject_line(name, raw, rel_path)` 產 cold 注入 1 行（## 印象 首 bullet → # Title → name；80 char cap）。 |
| `wg_intent.py` | ~430 | intent 分類 / session context / MCP / vector（2026-04-28 Wave 3a：vector 進入點加觀察 log → `~/.claude/Logs/vector-observation.log`，schema `{ts, session_id, fn, flag_state, result_count, fallback_used}`，4 天採樣後由 `tools/vector-observation-summary.py` 自動判定 REVIVE/RETIRE/GRAY） |
| `wg_extraction.py` | ~295 | per-turn 萃取 / worker 管理 / failure 偵測 |
| `wg_hot_cache.py` | ~160 | Hot Cache 讀寫 / 注入（含 AUTO-DRAFT tag 硬規則） |
| `wg_docdrift.py` | ~260 | src → _AIDocs 映射 drift 偵測；`prune_committed_entries` 於 advisory 前以 `git status --porcelain` 自動清掉源檔已 commit/revert 的 stale 條目（避免跨 session 持久誤報；可由 `docdrift.auto_prune_committed=False` 關閉）；**2026-05-04 cca5883**：advisory 從 PostToolUse 移到 SessionEnd 一次性觸發（避免 mid-session nag 每 Edit/Bash 重複印同一份 doc-list 吃 ~150 tokens × N 次） |
| `wg_episodic.py` | ~860 | episodic 生成 / 衝突偵測 / 品質回饋 |
| `wg_iteration.py` | ~450 | 自我迭代 / 震盪 / 衰減 / 晉升 / 覆轍 |
| `wg_evasion.py` | ~177 | Evasion Guard + Test-Fail Gate + ScanReport Gate（2026-04-17/2026-04-23） |
| `wg_pretool_guards.py` | ~75 | PreToolUse 路徑/指令防呆（path-block + svn-test-block, 2026-04-28）— [固] 級規則程式碼化，純函式無 IO/state |
| `wg_atom_observation.py` | ~205 | **REG-005 atom 注入觀察採樣 hook（Session 2/3, 2026-04-29）**：flag-gated（`memory/_staging/reg-005-observation-start.flag`），flag 不存在 → 入口 `sys.exit(0)` 零開銷返回。獨立 hook（不走 workflow-guardian dispatcher），UserPromptSubmit / PostToolUse(Read) 各註冊一個 matcher。schema：log line JSON `{ts, session_id, event, details}` → `~/.claude/Logs/atom-injection-observation-YYYY-MM-DD.log`；metric → `reflection_metrics.json` 子鍵 `reg005_observation`（atomic write via `.tmp` rename）。Session 2 起新增公開 helper `log_injection(session_id, name, classification, source)`，由 workflow-guardian 注入端呼叫，寫 append-only `Logs/atom-injection-injections-YYYY-MM-DD.log`（避免兩 hook process 同時 atomic-write 同 metric 的 lost-update race） |
| `extract-worker.py` | ~690 | SessionEnd 萃取子程序（共用 `lib/ollama_extract_core.py`） |
| `lib/ollama_extract_core.py` | ~190 | 萃取共用核心（budget tracker / ack_then_clear） |
| `quick-extract.py` | ~155 | Stop async 快篩 |
| `wisdom_engine.py` | ~306 | 反思引擎 + Fix Escalation（V2.12, 2026-05-05：metrics.* sliding window of 10 + schema_version + legacy_cumulative migration；track_retry plan-mode threshold 從 2→4，reflect arch 容忍 1 retry 但 fix_escalation_triggered 覆蓋為真失敗信號。2026-04-27：路徑豁免 `/plans/`、`/_staging/`、`is_plan_filename` 規劃詞檔） |

### 輔助 Hook 腳本

| 檔案 | 用途 |
|------|------|
| `user-init.sh` | 多人 USER.md 初始化（SessionStart） |
| `ensure-mcp.py` | MCP server 可用性確認 |
| `webfetch-guard.sh` | WebFetch 安全護欄 |

## Skills（/Slash Commands）

| Skill | 檔案 | 用途 |
|-------|------|------|
| `/init-project` | `commands/init-project.md` | 專案知識庫 + 自治層初始化 |
| `/init-roles` | `commands/init-roles.md` | V4 多職務模式啟用引導 |
| `/resume` | `commands/resume.md` | 自動續接 Session |
| `/continue` | `commands/continue.md` | 讀 _staging/next-phase.md 續接 |
| `/consciousness-stream` | `commands/consciousness-stream.md` | 識流處理 |
| `/handoff` | `commands/handoff.md` | 跨 Session Handoff Prompt Builder |
| `/journal` | `commands/journal.md` | 工作日誌產出 |
| `/svn-update` | `commands/svn-update.md` | SVN 更新 |
| `/unity-yaml` | `commands/unity-yaml.md` | Unity YAML 操作 |
| `/upgrade` | `commands/upgrade.md` | 環境升級 |
| `/fix-escalation` | `commands/fix-escalation.md` | 精確修正升級（6 Agent 會議） |
| `/extract` | `commands/extract.md` | 手動知識萃取 |
| `/generate-episodic` | `commands/generate-episodic.md` | 手動生成 episodic atom |
| `/conflict` | `commands/conflict.md` | 記憶衝突偵測 |
| `/conflict-review` | `commands/conflict-review.md` | V4 管理職裁決 Pending Queue |
| `/memory-health` | `commands/memory-health.md` | 記憶品質診斷 |
| `/memory-review` | `commands/memory-review.md` | 自我迭代檢閱 |
| `/memory-peek` | `commands/memory-peek.md` | V4.1 自動萃取檢視 |
| `/memory-undo` | `commands/memory-undo.md` | V4.1 撤銷自動萃取 |
| `/memory-session-score` | `commands/memory-session-score.md` | V4.1 P4 Session 評分檢視 |
| `/atom-debug` | `commands/atom-debug.md` | Debug log 開關 |
| `/harvest` | `commands/harvest.md` | 網頁收割→Markdown |
| `/read-project` | `commands/read-project.md` | 系統性閱讀→doc-index atom |
| `/vector` | `commands/vector.md` | 向量服務管理 |
| `/changelog-roll` | `commands/changelog-roll.md` | 手動滾動 _CHANGELOG（自動掛 PostToolUse） |
| `/browse-sprites` | `commands/browse-sprites.md` | 批次圖片預覽 |

## 演化中 feature（保留細節於主檔）

### Evasion Guard / Test-Fail Gate（`wg_evasion.py`，2026-04-17+）

程式碼強固 LLM「錯誤的迴避」行為——不依賴模型自律，兩層擋住。

| 觸發點 | 偵測 | 動作 |
|---|---|---|
| PostToolUse (Bash) | 測試指令（pytest/tsc/node --check/jest/go test/cargo test）→ 解析 stdout+stderr | 失敗最後 20 行寫 `state["failing_tests"][]`；同 cmd 重跑成功 → 清舊紀錄 |
| Stop | `failing_tests` 非空 + last assistant text 命中完成宣告 regex | `output_block` 硬阻擋，要求 (a)修復 (b)標為 regression (c)降級任務 |
| Stop | last assistant text 命中退避 regex（不在本範圍/既有 drift/pre-existing/留給未來/非本次；**時間性延後**：下次/下回/之後/晚點/稍後/有空/有時間 + 再 + 處理/修/補/做/看/弄；未來處理/待後續/另行處理/留給使用者） | 寫 `state["evasion_flag"]` |
| Stop | **ScanReport Gate（2026-04-23+）**：宣告完成 + `modified_files>0` + 缺掃描報告標記（順手修補/無drift/需另開session/列入handoff）+ 無使用者豁免 | `output_block` 硬阻擋，要求補 (a) 順手修補清單 或 (b) 需另開 session 列表；每 session 只觸發一次（`scan_report_warned`） |
| UserPromptSubmit | `evasion_flag` 非空 | 注入 `[Guardian:Evasion]` 舉證要求，注入後清旗 |
| UserPromptSubmit | prompt 命中放行詞（「先這樣/跳過/known regression」） | 清 `failing_tests`；近 3 則 user prompt 有放行詞 → skip evasion flag |

state 以 `setdefault` 增量，不升 schema_version。相關 atom：`memory/feedback/feedback-fix-on-discovery.md`；相關文件：`IDENTITY.md` 反退避契約節（針對 Opus 4.7 Effort=High「精準縮限範圍」傾向）。

### _CHANGELOG Auto-Roll（`tools/changelog-roll.py`，2026-04-17+）

PostToolUse hook 偵測 `_CHANGELOG.md` 寫入 → 行數 >`config.changelog_auto_roll.threshold`（預設 8）→ detached subprocess 跑 roll 工具 → 超額條目搬到 `_CHANGELOG_ARCHIVE.md`。Fail-open。手動入口 `/changelog-roll`。

## 規則模組

`.claude/rules/core.md`（合併版）由 Claude Code 自動載入；CLAUDE.md 瘦身至 ~50 行。Hook 自動執行可程式碼化的部分（同步、品質函數、震盪偵測）。

## 記憶系統（原子記憶 V4.1）— 子系統索引

雙 LLM 架構：Claude Code（雲端）= 決策/分類；Ollama Dual-Backend（本地）= embedding/萃取/re-ranking。

| 主題 | 詳情文件 | keywords |
|---|---|---|
| Dual-Backend Ollama 退避 | [DevHistory/ollama-backend.md](DevHistory/ollama-backend.md) | 退避, DIE, rdchat, failover |
| 記憶檢索管線 + 回應知識捕獲 | [DevHistory/memory-pipeline.md](DevHistory/memory-pipeline.md) | pipeline, JIT, vector, hot_cache |
| V3 三層即時管線 | [DevHistory/memory-pipeline.md](DevHistory/memory-pipeline.md) | V3, quick-extract, deep extract |
| V4.1 使用者決策萃取 + P4 Session 評價 | [DevHistory/v41-journey.md](DevHistory/v41-journey.md) §10 | user-extract, L0, L1, L2, gemma4, session_score |
| SessionStart 去重 + Merge self-heal | [DevHistory/session-mgmt.md](DevHistory/session-mgmt.md) | dedup, merge_into, orphan cleanup |
| 專案自治層 + V4 三層 Scope + JIT | [DevHistory/v4-layers.md](DevHistory/v4-layers.md) | scope, personal, shared, role, vector layer |
| V4 三時段衝突偵測（Phase 5+6） | [DevHistory/v4-conflict.md](DevHistory/v4-conflict.md) | conflict, pending_review, CONTRADICT, EXTEND |
| Wisdom Engine + Fix Escalation + 跨 Session 鞏固 | [DevHistory/wisdom-engine.md](DevHistory/wisdom-engine.md) | wisdom, reflection, fix_escalation |
| settings.json 權限 + 工具鏈 | [DevHistory/settings-config.md](DevHistory/settings-config.md) | permissions, 權限, tools |

資料層：`MEMORY.md` 索引（always-loaded）+ atom 檔（按需）+ LanceDB vector + episodic + wisdom + 專案自治層。

### Atom 寫入單點收束（funnel，S1–S4，2026-05-04）

> 全系統所有 atom 寫入經過 `lib/atom_io.py` 唯一入口；違者由 PreToolUse 強制門禁攔截。

**架構：**

- `lib/atom_spec.py` — atom 格式規則純函式（slugify / build_atom_content / validate / SKIP_DIRS / VALID_SCOPES），audit/health/atom_io 共用 import 避免規則漂移
- `lib/atom_io.py` — knowledge funnel 入口：`write_atom()` (build+validate+atomic write+index+audit log) / `write_raw()` (escape hatch for failures/episodic 子族) / `write_index_full()` (整檔重組 sync 用)。Wave 2（2026-05-05）：`update_atom_field()` 已移除，計數類欄位（read_hits / last_used / confirmations）改走 `lib/atom_access.py`
- `lib/atom_access.py` — telemetry funnel 入口（Wave 2）：`<atom>.access.json` 旁路檔讀寫單一通道；`init_access` / `increment_read_hits` / `increment_confirmation` / `record_promotion` / `read_access` / `bulk_read`；CLI 入口 `python -m lib.atom_access` 給 MCP server.js spawn 用
- `lib/atom_io_cli.py` — stdin JSON → write_* → stdout JSON，供 MCP server.js spawn

**Caller 接線（contract: source 必填，記入 `_meta/atom_io_audit.jsonl`）：**

| Caller | source 名稱 | 切入點 |
|---|---|---|
| MCP server.js (toolAtomWrite/Promote) | `mcp` | `funnelWriteRaw()` + `funnelWriteIndexFull()` + `spawnAtomAccess()` |
| hooks/workflow-guardian.py (atom 注入計數) | `hook:atom-inject` | `atom_access.increment_read_hits` |
| hooks/extract-worker.py (failure atom) | `hook:extract-worker` | `_failure_writeback` + `_create_failure_atom` |
| hooks/wg_episodic.py (cross-session confirm) | `hook:episodic-confirm` | `atom_access.increment_confirmation` |
| hooks/wg_episodic.py (episodic atom) | `hook:episodic` | `write_raw` + `atom_access.init_access` |
| hooks/quick-extract / user-extract | `hook:user-extract` | (S2 接) |
| tools/migrate-v3-to-v4.py | `tool:migrate` | `write_raw` migration patch |
| tools/memory-undo.py | `tool:undo` | `write_raw` reject footer |
| tools/atom-move.py | `tool:atom-move` | `write_raw` (atom) + `write_index_full` (index) |
| tools/memory-audit.py | `tool:memory-audit` | demote / compact / log_evolution `write_raw` + `atom_access.write_access_field` |
| tools/sync-atom-index / sync-memory-index | `tool:sync-*` | `write_index_full` |

**Atom 知識／遙測切分（Wave 2 落地）：**

- atom `.md` 檔頭只放知識性 metadata：`Scope` / `Confidence` / `Trigger` / `Type` / `Author` / `Tags` / `Related` / `Created` / `description` / `name`
- `<atom>.access.json` 旁路檔（schema `atom-access-v2`）放運行期遙測：`read_hits` / `last_used` / `confirmations` / `last_promoted_at` / `first_seen` / `timestamps`（最多 50 筆）/ `confirmation_events`
- 1:1 對應 atom；刪 atom 自然連帶刪遙測；無集中檔競態風險
- 任何 atom .md 出現在 `git status` modified 都必然是知識內容變更（語意改動），便於 review

**強制門禁（PreToolUse）：**

- `hooks/wg_pretool_guards.py:check_memory_path_block`
  - (a) `~/.claude/projects/{slug}/memory/` 殘骸 → deny [P1]
  - (b) `~/.claude/.claude/memory/` 雙層路徑 → deny [P6]
  - (c) 任何 atom .md 直 Write/Edit 不走 funnel → deny [S3.3]
- 白名單：`MEMORY.md` / `_ATOM_INDEX.md` / `_` 前綴檔 / `_meta`/`_staging`/`episodic`/`wisdom`/`personal` 子目錄
- 緊急 bypass：env `WG_DISABLE_ATOM_GUARD=1`

**MCP cwd-scope 雙向防護（server.js:resolveMemDir）：**

- P3：scope=global 配 project root cwd（非 `~/.claude`）→ reject（避免污染 global），可用 `force_global=true` escape
- P4：scope=shared/role/personal 配 cwd 在 `~/.claude` 下 → reject（V4 sub-scope 在專案層才有意義）

**反向證明工具：**

- `tools/check-bypass.py` — 靜態掃 hooks/tools/lib/plugins 內所有 `write_text`/`open(..., w)`/`fs.writeFileSync` 出現在 memory 路徑附近的點，white-list 之外 → 印警告（CI exit 1）
- `tools/audit-reconcile.py` — 動態對拍：列近期 mtime atom × audit log entries（`--since 30s/2h/1d`，也接 `2h ago`）。S4 強化分類：每筆 unmatched 走 `git diff` 判定 `counter_only`（diff 只動 Last-used / Confirmations / ReadHits / Related 欄位 + [臨]/[觀]/[固] 信心 tag promotion，hook:read-counter 設計直寫）/ `knowledge`（動到知識內容 → 真實 bypass）/ `unknown`（無 git / 未追蹤）。預設只在 knowledge 有 unmatched 時 exit 1；`--strict` 則 unknown 也視為 bypass

**測試：**

- `tests/test_atom_io_equivalence.py` — 11 cases 對拍 server.js byte-identical
- `tests/test_guardian_atom_write_gate.py` — 9 cases 含 S3.3 強制門禁攔截場景
- `tests/test_audit_reconcile.py` — 7 cases 驗 `--since` parser（含 `2h ago`）+ classifier（counter-only / knowledge / unknown）
- `tests/test_check_bypass.py` — 5 cases 驗 white-list 比對 + violation 偵測

**S4 收尾（2026-05-04）：**

- 知識 atom 入庫（走 funnel source=`mcp`）：`feedback-clean-before-build` / `feedback-checker-rule-consolidation` / `decisions-architecture` 加印象 bullet
- 殘骸清理：移除 `~/.claude/projects/c--users-holylight--claude/memory/` 空目錄（Layers 2→1）
- audit-reconcile classifier：counter_only/knowledge/unknown 三分類，53 unmatched → 0 knowledge bypass

## MCP Servers

| Server | 傳輸 | 用途 |
|--------|------|------|
| workflow-guardian | stdio (Node.js) | session 管理 + Dashboard (port 3848) |

### atom_write 工具（V4 三層 scope，2026-04-15+）

| 參數 | 行為 |
|------|------|
| `scope=global` | 寫 `~/.claude/memory/` |
| `scope=shared`（預設） | 寫 `{proj}/.claude/memory/shared/` |
| `scope=role` + `role=...` | 寫 `roles/{role}/`，metadata `Scope: role:{role}` |
| `scope=personal` + `user=...` | 寫 `personal/{user}/`，metadata `Scope: personal:{user}` |
| `scope=project`（legacy） | 透明轉 `shared` + stderr deprecation hint |

新 metadata 自動帶入：`Author`（server 端 env/OS user）、`Created-at`（今日）、`Audience`/`Pending-review-by`/`Merge-strategy`（optional）。
**SPEC 7.4 敏感類別自動 pending**：`scope=shared` 且 `audience ∈ {architecture, decision}` → `shared/_pending_review/` + `Pending-review-by: management`。

### atom_promote

雙軌門檻（v3 dual-field）：
- **Primary**: Confirmations（跨 session 萃取命中）[臨]→[觀] ≥4, [觀]→[固] ≥10
- **Auxiliary**: ReadHits（注入讀取）[臨]→[觀] ≥20, [觀]→[固] ≥50
- 7 天豁免期（migration 起算）：Confirmations 未達標時 ReadHits/5 ≥ 門檻可 fallback

`merge_to_preferences=true`（global only，[觀]→[固] 時）把「## 知識」合併到 `preferences.md` 並搬原 atom 到 `memory/_archived/`。

### UserPromptSubmit Atom-Write Guard

偵測「記住/存起來/寫 atom/存成 [固]」關鍵字 → 注入硬規則（新 atom 一律 [臨]、晉升走 `atom_promote`、更新既有走 `mode=append`），降低 Claude 建議錯誤的 retry 成本。

詳見 [SPEC_ATOM_V4.md](SPEC_ATOM_V4.md)。
