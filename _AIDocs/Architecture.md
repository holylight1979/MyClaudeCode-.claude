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
| `workflow-guardian.py` | ~1570 | 瘦身 dispatcher：8 event handlers 編排 |
| `wg_paths.py` | ~445 | 路徑唯一真相來源（V4 sublayer 發現） |
| `wg_roles.py` | ~210 | V4 角色機制（雙向認證、personal dir bootstrap） |
| `wg_core.py` | ~370 | config / state IO / output / debug / promotion audit |
| `wg_atoms.py` | ~559 | 索引解析 / trigger 匹配 / ACT-R / section 注入 |
| `wg_intent.py` | ~430 | intent 分類 / session context / MCP / vector（2026-04-28 Wave 3a：vector 進入點加觀察 log → `~/.claude/Logs/vector-observation.log`，schema `{ts, session_id, fn, flag_state, result_count, fallback_used}`，4 天採樣後由 `tools/vector-observation-summary.py` 自動判定 REVIVE/RETIRE/GRAY） |
| `wg_extraction.py` | ~295 | per-turn 萃取 / worker 管理 / failure 偵測 |
| `wg_hot_cache.py` | ~160 | Hot Cache 讀寫 / 注入（含 AUTO-DRAFT tag 硬規則） |
| `wg_docdrift.py` | ~260 | src → _AIDocs 映射 drift 偵測；`prune_committed_entries` 於 advisory 前以 `git status --porcelain` 自動清掉源檔已 commit/revert 的 stale 條目（避免跨 session 持久誤報；可由 `docdrift.auto_prune_committed=False` 關閉） |
| `wg_episodic.py` | ~860 | episodic 生成 / 衝突偵測 / 品質回饋 |
| `wg_iteration.py` | ~450 | 自我迭代 / 震盪 / 衰減 / 晉升 / 覆轍 |
| `wg_evasion.py` | ~177 | Evasion Guard + Test-Fail Gate + ScanReport Gate（2026-04-17/2026-04-23） |
| `wg_pretool_guards.py` | ~75 | PreToolUse 路徑/指令防呆（path-block + svn-test-block, 2026-04-28）— [固] 級規則程式碼化，純函式無 IO/state |
| `extract-worker.py` | ~690 | SessionEnd 萃取子程序（共用 `lib/ollama_extract_core.py`） |
| `lib/ollama_extract_core.py` | ~190 | 萃取共用核心（budget tracker / ack_then_clear） |
| `quick-extract.py` | ~155 | Stop async 快篩 |
| `wisdom_engine.py` | ~190 | 反思引擎 + Fix Escalation（2026-04-27：`track_retry` 對 `/plans/`、`/_staging/`、檔名命中 `is_plan_filename` 規劃詞的路徑豁免，計畫迭代不誤計入 retry_count） |

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
