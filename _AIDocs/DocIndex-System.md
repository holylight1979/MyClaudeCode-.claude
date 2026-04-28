# 原子記憶系統 — 全檔案索引

> 由 `/read-project` 產出，最近同步：2026-04-15（V4 Phase 6 收尾）。
> 目標：讓 Claude Code AI 能了解自己，以利後續升級、迭代、進化。

---

## 1. 啟動鏈（Session Lifecycle）

```
Claude Code 啟動
  ↓
settings.json（權限 + hooks 定義）
  ↓
[SessionStart hooks]
  ├─ user-init.sh → USER.template.md → USER-{username}.md → USER.md
  └─ workflow-guardian.py:handle_session_start()
       ├─ 解析 MEMORY.md atom 索引
       ├─ 掃描 _AIDocs/_INDEX.md
       ├─ register_project(cwd) → project-registry.json
       ├─ Wisdom Engine blind spots
       ├─ Long DIE check（Dual-Backend）
       ├─ 啟動 Vector Service（port 3849）
       └─ _call_project_hook("session_start") → delegate
  ↓
CLAUDE.md @import
  ├─ IDENTITY.md（AI 人格）
  ├─ USER.md（使用者偏好）
  ├─ MEMORY.md（atom 索引）
  └─ rules/*.md（4 模組自動載入）
  ↓
Session Ready
  ↓
[UserPromptSubmit] ×N → atom injection + sync remind
[PostToolUse] ×N → file tracking + vector index
[Stop] → sync gate + per-turn extraction
[SessionEnd] → LLM extraction + episodic + Wisdom reflect
```

## 2. 設定檔層

| 檔案 | 用途 | 載入方式 | 多人 |
|------|------|---------|------|
| CLAUDE.md | 全域入口，@import 3 檔 + 4 rules | 自動 | 共用 |
| IDENTITY.md | AI 人格（直球精準、最小變動） | @import | 共用 |
| USER.md | 使用者偏好（繁中、極簡） | @import（hook 生成，gitignore） | per-user |
| USER.template.md | 多人模板 | user-init.sh 複製 | 共用 |
| BOOTSTRAP.md | 首次設定引導 | 條件觸發 | 共用 |
| settings.json | Hook 事件 + 權限白名單 | Claude Code 讀取 | 共用 |
| .mcp.json | MCP server 定義（專案層） | Claude Code 讀取 | 共用 |
| workflow/config.json | Guardian/Vector/Decay/Capture 全參數 | Hook 每次讀取 | 共用 |

## 3. 規則模組（rules/）

| 模組 | 職責 |
|------|------|
| aidocs.md | _AIDocs 知識庫維護（啟動檢查 + 工作中 4 規則） |
| memory-system.md | 原子記憶：[固]/[觀]/[臨] 分類 + 寫入原則 + 演進規則 |
| session-management.md | 對話管理 + 續航 + 識流 + 自我迭代 |
| sync-workflow.md | 工作結束同步 + Workflow Guardian 閘門 |

## 4. Hook 系統（模組化架構）

| 檔案 | 行數 | 職責 |
|------|------|------|
| workflow-guardian.py | ~1259 | 瘦身 dispatcher：6 event handlers 編排 |
| wg_paths.py | ~314 | 路徑唯一真相來源：slug/root/staging/registry |
| wg_core.py | ~270 | 共用常數/設定/state IO/output/debug |
| wg_atoms.py | ~563 | 索引解析/trigger 匹配/ACT-R/載入/budget/section-level 注入 |
| wg_intent.py | ~357 | 意圖分類/session context/MCP/vector service |
| wg_extraction.py | ~285 | per-turn 萃取/worker 管理/failure 偵測 |
| wg_episodic.py | ~856 | episodic 生成/衝突偵測/品質回饋 |
| wg_iteration.py | ~431 | 自我迭代/震盪/衰減/晉升/覆轍偵測 |
| codex_companion.py | ~290 | Codex Companion hook：事件轉發/assessment 注入/heuristic 軟閘 |
| extract-worker.py | ~774 | SessionEnd/per-turn/failure 子程序：LLM 萃取 + dedup |
| wisdom_engine.py | ~199 | 2 硬規則 + 3 反思指標 + Bayesian arch sensitivity |
| user-init.sh | ~20 | 多人 USER.md 初始化（SessionStart） |
| ensure-mcp.py | — | MCP server 可用性確認 |
| webfetch-guard.sh | — | WebFetch 安全護欄 |

合計：~5308 行

## 5. Skills（commands/，20 個）

| 指令 | 用途 | 依賴 |
|------|------|------|
| /atom-debug | Debug log 開關 | 無 |
| /codex-companion | Codex Companion 開關（service 啟停 + config toggle） | codex CLI |
| /changelog-roll | 手動滾動 _CHANGELOG.md（PostToolUse 自動掛，通常不用手跑）`--keep N\|--dry-run` | 無 |
| /conflict | 記憶衝突偵測（向量比對 + LLM 判定） | Vector Service + Ollama |
| /conflict-review | V4 管理職裁決 Pending Queue（雙向認證） | wg_roles + Vector Service |
| /consciousness-stream | 高風險跨系統（唯識八識） | 無 |
| /continue | 讀 _staging/next-phase.md 續接 | 無 |
| /extract | 手動知識萃取（不等 SessionEnd） | Ollama |
| /fix-escalation | 精確修正升級（6 Agent 會議） | 無 |
| /handoff | 跨 Session Handoff Prompt Builder（6 區塊強制模板） | 無 |
| /harvest | Playwright 網頁收割→Markdown | Playwright |
| /init-project | 專案 _AIDocs + 自治層初始化 | 無 |
| /init-roles | V4 多職務模式啟用引導（建 personal/role.md + shared/_roles.md + 可選裝 post-merge hook + V4.1 隱私體檢 [F21]） | wg_roles + 可選 git |
| /memory-health | 記憶品質診斷（audit + health-check） | 無 |
| /memory-peek | V4.1 列最近 24h 自動萃取 atom + pending + trigger 原因 [F7] | 無 |
| /memory-review | 自我迭代檢閱（衰減/晉升/震盪/覆轍） | 無 |
| /memory-session-score | V4.1 P4 Session 5 維度加權評分（density/precision/novelty/cost/trust）`--last\|--since\|--top-n` | 無 |
| /memory-undo | V4.1 撤銷自動萃取（_rejected/ + reason 分類 + reflection_metrics）[F20][F23] | 無 |
| /read-project | 系統性閱讀→doc-index atom | 無 |
| /resume | 續接 prompt + 自動開新 session | MCPControl |
| /svn-update | SVN 更新 + 衝突處理 | TortoiseSVN |
| /unity-yaml | Unity YAML 解析/生成 | unity-yaml-tool.py |
| /upgrade | 環境升級（diff+merge+rebuild） | 無 |
| /vector | 向量服務管理（啟停/索引/搜尋） | Vector Service |

## 6. 工具鏈（tools/）

### 向量服務（port 3849）
- service.py — HTTP daemon
- config.py — config.json 讀寫
- indexer.py — atom→chunk→embed→LanceDB
- searcher.py — semantic + ranked + section-level（5-factor: semantic 0.45 + recency 0.15 + intent 0.20 + confidence 0.10 + confirmations 0.10）；排名用 Confirmations（高訊號），ReadHits 可選輕微加分
- reranker.py — LLM query rewrite + re-rank
- vector-observation-summary.py — Wave 3a 4 天觀察期分析器（2026-04-28）。讀 `~/.claude/Logs/vector-observation*.log`（main hook + SessionStart probe），統計 vector 命中率 / fallback 比例 / per-fn 分布，自動判定 **REVIVE**（命中率 ≥ 50%）/ **RETIRE**（≤ 5% 且 fallback ≥ 80%）/ **GRAY**（5–15% 灰色地帶詢使用者）。配合 plan v2.1 §修訂 #4 D3.5–D5；不依賴使用者察覺 silent failure。`workflow-guardian.py:617` 路徑修正（舊 `tools/vector-service.py` 不存在 → 真檔 `tools/memory-vector-service/service.py`）+ `vector_ready.flag` 改為「health 200 才寫」杜絕 12 天假陽性同期完成
- vector-probe-burst.py — Wave 3b probe burst（2026-04-28）。90 query × 2 path = 180 calls 透過 `wg_intent._search_episodic_context` / `_semantic_search` 跑完整 vector pipeline，加速 4 天觀察期至單 session。三 bucket：A 高機率命中（與已有 atom/episodic 重疊）/ B 中機率 / C 低機率（莎士比亞、量子糾纏等 out-of-domain）。Pre-flight 健康檢查 + 自動啟動 service。為 `vector-observation-summary.py` 提供統計樣本，本次跑出 **87.6% 命中率 → REVIVE 決策**。Log schema 純 metadata，不寫 query 內容（紅隊驗證通過）。

### Ollama 雙 Backend
- ollama_client.py — singleton，generate()/chat()/embed()
  - rdchat: qwen3.5:latest + qwen3-embedding:latest（RTX 3090，pri=1）
  - local: qwen3:1.7b + qwen3-embedding（GTX 1050 Ti，pri=2）
  - 三階段退避：normal → short_die(60s) → long_die(6h boundary)
  - Long DIE → workflow-guardian SessionStart 提示使用者確認停用/保持
  - `_request_with_failover` 在 `explicit_model` 與 backend `llm_model` 不符時直接 skip（不計 failure，避免毒化 health_cache 60s 使後續呼叫 silent return）

### 記憶品質
- memory-audit.py — 格式驗證 + staleness + 雙軌晉升建議（Conf≥4/10 or RH≥20/50）（支援 `--project-dir`、Claude-native YAML frontmatter、2 欄 MEMORY.md、wildcard 索引項、orphan memory dir 容忍；`## 印象` 為指標型 atom 變體，可取代 `## 知識` 滿足必要區段；recursive 掃描 atom 子目錄如 `feedback/`，跳過 `_*`/`personal/`/`wisdom/`/`episodic/`/`templates/` 等非 atom 目錄）
- memory-write-gate.py — 寫入閘門（6 規則 + 0.80 dedup；[固] 不再 fast-path，一律過品質檢查）
- memory-conflict-detector.py — 向量衝突 + LLM 分類；mode ∈ {full-scan / write-check / pull-audit}（V4 Phase 5 三時段衝突偵測核心）
- conflict-review.py — V4 Pending Queue 後端：list/approve/reject 三動作，is_management 雙向認證 guard，approve 寫 Decided-by + merge_history + 觸發 `/index/incremental`
- atom-health-check.py — 參照完整性（`_` 前綴檔案豁免、`decisions`/`decisions-architecture`/`spec`/`feedback-pointer-atom` 為 central hub 反向參照豁免；`--memory-root` 非全域時自動把全域加入 ref resolution fallback，支援 project→global up-ref 合法解析；`--auto-fix-broken` 自動從 source atom 移除真斷裂 ref）。`--shadow-check` 偵測 atom `## 印象` / `## 知識` 段 vs `_AIDocs/**/*.md` 子段落 SequenceMatcher.ratio ≥ 0.7 標 warning（與 staleness 同 warning 級，不影響 health 總計）；剝離 `→ _AIDocs/...` pointer / `@_AIDocs/...` import / 純路徑行；length-prefix early-exit 避免長度落差過大的 pair；`--shadow-threshold` 覆寫門檻、`--shadow-dry-run` 印 ratio 分布（5 分桶 + top 30），用於初次落地驗證或調 threshold（指標型 atom 設計依據：`memory/feedback/feedback-pointer-atom.md`）
- atom-move.py — 跨層原子搬遷工具。`move` 子命令：mv 檔案 + 更新 Scope + 同步兩層 `_ATOM_INDEX`/`MEMORY` + 按層序規則處理 inbound refs（down-ref 自動移除、up-ref 保留、sibling 回報警告）。`reconcile` 子命令：atom 已在 target（如手動 mv 之後）時跑完整清理。均支援 `--dry-run`。MCP 工具 `mcp__workflow-guardian__atom_move` 為對應 in-session 封裝
- sync-atom-index.py — atom frontmatter Trigger ↔ `_ATOM_INDEX.md` 一致性同步工具（選項 A 真相源規格；設計：`_AIDocs/DevHistory/atom-trigger-source-of-truth.md`）。配對 key 為 rel_path，避免 alias 短名與檔名不符的偽陽性。模式：default dry-run JSON 報告 / `--check` 安靜版（PreCommit hook 用）/ `--fix` 以 `_ATOM_INDEX` 覆蓋 frontmatter Trigger / `--add-from-frontmatter` 把 frontmatter 有 Trigger 但 `_ATOM_INDEX` 缺的 atom 補進索引尾部。排除：`_reference/_archived/_pending_review/_staging/templates/wisdom/_drafts/episodic/`
- sync-memory-index.py — 從 `_ATOM_INDEX.md` 自動生成 `MEMORY.md`（@import always-loaded 索引）。掃所有 atom 的 H1 第一行作為「說明」欄；`feedback-*` 與 `fix-escalation` 自動歸納為一行「行為校正（N 個含 ...）」帶實際計數；保留 `> **知識庫查閱**：` 標記後段落不變。模式：default 預覽 stdout / `--check` 比對現存（PreCommit）/ `--write` 覆寫

### 遷移/測試
- migrate-v221.py — V2.21 遷移（_AIAtoms + 個人記憶 → .claude/memory/）
- migrate-v3-to-v4.py — V3 → V4 遷移（補 Scope/Author/Created-at metadata；不搬檔，漸進分層；dry-run 預設）
- init-roles.py — /init-roles 後端（bootstrap-personal / scaffold-roles / add-member / promote-mgmt / install-hook / privacy-check [F21]，全冪等）
- memory-peek.py — V4.1 /memory-peek 後端：掃 personal/auto/{user}/ 列最近 atom + _pending.candidates
- memory-session-score.py — V4.1 P4 /memory-session-score 後端：讀 reflection_metrics.v41_extraction.session_scores[]，`--last/--since/--top-n` 三種過濾 + JSON 輸出
- memory-undo.py — V4.1 /memory-undo 後端：撤銷到 _rejected/ + reason 分類 + 寫 reflection_metrics
- changelog-roll.py — _CHANGELOG.md 自動滾動（保留最新 N 條，超額搬 _CHANGELOG_ARCHIVE.md）；由 PostToolUse hook 偵測 _CHANGELOG 寫入後自動觸發 detached subprocess
- test-memory-v21.py — E2E 測試
- migrate-confirmations.py — v3 雙欄位拆分 migration（Confirmations→ReadHits+Confirmations 歸零，支援 --dry-run）
- eval-ranked-search.py — 50 query benchmark
- cleanup-old-files.py — 環境清理

### Codex Companion（port 3850）
- service.py — HTTP daemon。`/event` 內建 checkpoint 偵測（Phase 0.5：response 帶回 `should_trigger_checkpoint` 給 hook，避免 hook 再讀 state file）；`stop` 事件 +turn_index 並寫 `last_assistant_tail`；Sprint 3：`_run_assessment` 把 `turn_index` + state 內 `last_assistant_tail` 注入 extra_context 給 assessor，避免 daemon thread 重複 IO；Sprint 4：`_run_assessment` 完成後依 `category=system+summary 含 sandbox` → `sandbox_failures++`、`notify_next_turn=True` → `empty_returns++`，log 行加 `attempts=N`
- assessor.py — 組 prompt → `codex exec` → parse JSON 結果（model 為空時不傳 `-m`，由 `~/.codex/config.toml` 決定；**不傳 `-s`** 沿用 user config 預設沙盒，避免 Windows `CreateProcessWithLogonW` 1385 失敗）；Sprint 3：`_extract_verification_evidence` 從 trace 抽 verify cmd 摘要（含 `[FAILED]` 標記）+ `_parse_assessment` 對新 schema 欄位（delivery / confidence / evidence / applies_until / turn_index）補預設值並相容舊 `recommended_action`；Sprint 4 Phase 5.1：`_run_codex` 改回 `(stdout, stderr)` 把 stderr 帶上來；新增 `_run_codex_with_retry` 在空字串/非 JSON 時 sleep 0.4s 重試 1 次；新增 `_classify_failure` 用 `_SANDBOX_FAILURE_RE = CreateProcessWithLogon|sandbox`（i 旗標）識別 R2-5 級錯誤，命中→`category: system, summary: "Codex sandbox 失敗，請檢查 -s 設定"`，否則→`status: warning, summary: "退回 heuristics-only", delivery: inject, notify_next_turn: True`；result 加 `_attempts` metadata
- prompts.py — plan review / turn audit / architecture review 模板，含 `SANDBOX_CONSTRAINT` 紅線（禁 git/edit/write/rm；只允許讀取）；Sprint 3 OUTPUT_SCHEMA v2 砍 `recommended_action`、改 `delivery: ignore\|inject` + `confidence` + `evidence` + `applies_until` + `turn_index`；TURN_AUDIT 模板新增 Last Assistant Reply Tail / Verification Evidence Found / Heuristic Triggered (Reference Only) 三段；codex 徹底失去 BLOCK 權（advisory only）
- state.py — per-session 狀態 + per-turn assessment cache（Phase 1.6/1.7：schema 加 `turn_index`、`last_assistant_tail`；assessment 改 `companion-assessment-{sid}-t{N}-{type}.json`），**module-level `threading.Lock`** 包覆所有 read-modify-write，防 service main thread 與 assessment worker thread 並發 race；Sprint 4：新增 `companion-metrics-{sid}.json` 獨立檔 + `increment_metric` / `read_metrics` API（白名單）；Sprint 5.5：metric 白名單擴 6 鍵（加 `audits_total_attempted` — Phase 6 §四 C3 ratio 分母；hook handle_stop 在 score gate 通過、所有 dedup/cap 也過、即將送 `/trigger` 前 +1，語意為「實際送出 codex audit 次數」）
- heuristics.py — 規則式軟閘（缺驗證/完成缺證據/架構變更/空轉，< 10ms，無 LLM）；**HOTFIX 2026-04-28**：`_has_state_change` 改為 turn-scoped（只看 `tool_trace` 最近 10 條），不再讀 session-cumulative 的 `modified_files`，修復「session 早期某 turn 寫過檔，之後每個含完成口風的 turn 都被 BLOCK」的無限循環
- scorer.py — Sprint 3 turn-level risk scoring（五因子加權 0-10：`write_footprint(0-2)` + `verification_gap(0-3)` + `structural_risk(0-2)` + `completion_claim(0-2)` + `analysis_loop(0-1)`）；Stop hook 觸發 codex turn_audit 前算分，< `score_threshold` 即跳過以省互動干擾；純啟發式重用 heuristics 的判斷函數，< 5ms

**Silent Advisory Mode 2026-04-28（hooks/codex_companion.py + tools/codex-companion/heuristics.py + workflow/config.json）**：
- 設計原則：Codex Companion 的軟閘屬「背景品質觀測」性質，不該干擾使用者對話流。除非偵測到明確失敗訊號，否則所有 advisory 走「靜默落盤 + metric 計數」路徑，使用者不會看到 BLOCK reason 或 inject 文字
- `heuristics._VERIFY_CMD_RE` 擴白名單：加入 `git check-ignore|status|diff|log|ls-files|merge-base` / `python -m json.tool` / `jq`（無內建 `\s` 後綴，沿用外層 `(?:\s|$)` 規則一致）/ `grep -[lLnEric]+` / `xargs grep` / `json.load(s)`，讓 doc/security/config 類驗證指令也算「有驗證」，不再僅認 pytest/npm test 等測試框架
- `heuristics._VERIFY_NARRATIVE_RE` 擴：加「N 項 PASS」「掃描通過」「無殘留」「乾淨/clean」「工作樹乾淨」「無 untracked」等敘述體弱證據
- `heuristics._COMPLETION_RE` 縮：移除過廣的敘事詞「收尾/總結/搞定/wrapped up」，只保留明確結束動詞（完成/已解決/全部做完/done/finished/all set/大功告成），避免報告體裁誤判
- `handle_stop` 新增 `silent_advisory` 旗標路徑：開啟時 heuristic 結果只 `increment_metric("silent_advisory_suppressed")`，不 `_output_block`，使用者不會看到「Codex Companion 軟閘：偵測到高風險缺漏」訊息
- `handle_user_prompt_submit` 新增 inject 三條件過濾：必須同時滿足 `severity >= max_inject_severity`（預設 high）AND `status in {error, needs_followup}` AND `corrective_prompt` 非空，才會浮上來。其他自動標 `injected=true` 落盤但不展示，metric 計入 `advisory_suppressed_silent`
- `workflow/config.json codex_companion` 區新增 `silent_advisory: true` + `max_inject_severity: "high"`，並把 `score_threshold` 由 4 拉高到 7（per-turn audit 觸發門檻提高，避免 LLM-driven assessment 過度被觸發）

**Sprint 4 健壯性 + 觀測（hooks/codex_companion.py + tools/codex-companion/{assessor,state,service}.py + workflow/config.json）**：
- 失敗非靜默：assessor 失敗回退路徑必送 `delivery: inject` + `notify_next_turn: True`；hook drain 偵測到 `notify_next_turn` → 在所有 inject blocks 之前插入 `[Codex Companion 提醒] 上輪審查未取得有效回應，本輪暫退回 heuristics-only。來源：tN summary; …`
- block_template config 化：`config.codex_companion.block_template`（預設 `"Codex Companion 軟閘：偵測到高風險缺漏。\n{detail}\n請補充驗證或修正後再收尾。"`）；`{detail}` 為唯一 placeholder，format 失敗時 fallback append
- 觀測五鍵落盤：hook handle_stop（score gate skip → `audits_skipped_by_score`）、`_output_block`（→ `behavior_gap_blocks`）、handle_user_prompt_submit drain（→ `quality_gap_advises` += blocks 數）；service `_run_assessment`（→ `sandbox_failures` / `empty_returns`）；handle_session_end 把 metrics 附到 `memory/wisdom/reflection_metrics.json` 的 `codex_companion.sessions[]`（最多 100 筆，全 zero session 跳過，與 wisdom_engine V4.1 P4 既有結構共存不破壞）
- 對應 plan v5 Phase 5：`plans/whimsical-zooming-sedgewick.md`

**Sprint 3 Score Gate + Advisory Schema（hooks/codex_companion.py + tools/codex-companion/scorer.py）**：
- handle_stop 三閘門：(a) score < `config.codex_companion.score_threshold`（預設 4）→ skip codex；(b) 同 turn_index + turn_audit 已落盤 assessment → dedup skip；(c) 累積 assessment 數達 `max_audits_per_session`（預設 30）→ skip。算分失敗 fallback `score=99` 不抑制觸發，避免漏審查
- merged_state 在 Stop handler 內建一次給 heuristic gate 與 scorer 共用（不重複 IO）
- handle_user_prompt_submit drain 依 codex 回的 `delivery` 路由：`ignore` 標 injected 不打擾、`inject` 注入 header 含 `confidence=high(高信心) applies=限本輪` 標籤 + 事證行 + 建議行
- workflow/config.json `codex_companion` 區新增 `score_threshold: 4` / `max_audits_per_session: 30`
- 對應 plan v5 Phase 3 + Phase 4：`plans/whimsical-zooming-sedgewick.md`

**Sprint 2 規則重構與 BLOCK 收斂（tools/codex-companion/heuristics.py）**：
- BLOCK 權收斂到單一規則 `confident_completion_without_evidence`（high）；missing_verification / architecture_change / spinning 一律降為 `low` advisory，只走 inject 不走 block
- 三條件齊備才 BLOCK：`has_claim` + `state_change`（trace 有 Edit/Write 或 modified_files 非空）+ `no_verify_evidence`（trace 無 verify cmd 且 stop_text 無驗證敘述）；任一缺席即放行
- Sprint 1 教訓 fallback：trace 為空但 `last_assistant_tail` 含驗證敘述（pytest 通過 / X/Y PASS / build 成功 / 驗證通過）視為弱證據放行，避免 companion-state 被擾動時誤觸 BLOCK
- 新增 `severity_at_or_above(results, threshold)` API；hook 端讀 `config.codex_companion.soft_gate.block_severity_threshold`（預設 `"high"`）做門檻比較
- 舊名 `check_completion_without_evidence` 保留為新規則的 alias，不破壞既有呼叫

**Sprint 1 補資訊管道（hooks/codex_companion.py）**：
- PostToolUse 從 `tool_response` 取 stdout/stderr 截 300 字 → `tool_output_summary`，失敗訊號（`error`/`exit_code != 0`/`stderr`/`is_error`）→ `[FAILED]` prefix（不依賴 PostToolUseFailure 事件）
- Stop 文本三層 fallback：`input_data["last_assistant_message"]` → 自寫 jsonl tail parser（無長度過濾）→ `wg_evasion.get_last_assistant_text()` 兜底
- Stop 觸發 turn_audit context 帶 `{user_goal_hint, last_assistant_tail, verification_signals}`
- UserPromptSubmit drain 改 glob `companion-assessment-{sid}-t*.json`，依 turn_index 排序，最多注入 3 件
- 砍 quick_plan 啟發式：`_detect_checkpoint` 移到 service 內，只保留 `ExitPlanMode/EnterPlanMode → plan_review` 與結構性檔名 `→ architecture_review`

### 其他
- read-excel.py（openpyxl+xlrd）| unity-yaml-tool.py | rag-engine.py（CLI wrapper）
- gdoc-harvester/（Playwright 網頁收割 + dashboard）
- workflow-guardian-mcp/server.js（MCP stdio + dashboard port 3848，含「已知專案」分頁）

## 7. 記憶層

- **MEMORY.md**（always loaded）— 25 atoms 觸發表
- **全域 Atoms**（17 個 .md）— preferences, decisions, decisions-architecture, excel-tools, workflow-rules, workflow-icld, workflow-svn, toolchain, toolchain-ollama, doc-index-system, gdoc-harvester, mail-sorting, feedback×4
- **failures/**（5 個）— env-traps, wrong-assumptions, silent-failures, cognitive-patterns, misdiagnosis-verify-first
- **unity/**（5 個）— unity-yaml, unity-yaml-detail, unity-prefab-component-guids, unity-prefab-workflow, unity-wndform-yaml-template
- **templates/**（1 個）— icld-sprint-template
- **_reference/**（手動讀取）— SPEC(950行), SPEC_impl_params, self-iteration, decisions-history, v3-design, v3-research
- **wisdom/**（live state）— DESIGN.md + reflection_metrics.json + causal_graph.json
- **Runtime**（gitignore）— episodic/, _vectordb/, _staging/, _distant/, state-*.json, *.access.json

## 8. 專案自治層

每個已註冊專案的 `{project_root}/.claude/` 結構：

| 路徑 | 用途 |
|------|------|
| `.claude/memory/MEMORY.md` | 專案 atom 索引 |
| `.claude/memory/*.md` | 專案 atoms（共享 + 個人合併） |
| `.claude/memory/episodic/` | 自動生成（gitignore） |
| `.claude/memory/failures/` | 踩坑記錄（版控） |
| `.claude/memory/_staging/` | 暫存（gitignore） |
| `.claude/hooks/project_hooks.py` | 專案 delegate（inject/extract/session_start） |
| `.claude/.gitignore` | 排除 ephemeral 檔案 |

管理：`memory/project-registry.json` 索引所有已註冊專案根路徑。

## 9. 對外文件

- README.md — GitHub 入口（設計理念 + 架構 + Token 影響 + 安裝）
- Install-forAI.md — 6 步安裝 SOP + FAQ
- _AIDocs/ — 專案知識庫（6 文件）
- LICENSE — GPLv3

---

## 速查

| 問題 | 去看 |
|------|------|
| 啟動時載入了什麼？ | CLAUDE.md → settings.json → workflow-guardian.py:handle_session_start |
| Atom 怎麼被注入的？ | wg_atoms.py（trigger match + section-level）+ wg_intent.py（semantic search + ACT-R rank） |
| 記憶怎麼寫入？ | memory-write-gate.py → extract-worker.py → cross-session promote |
| 向量搜尋怎麼運作？ | indexer.py → searcher.py → reranker.py（via service.py） |
| Ollama 雙 Backend？ | ollama_client.py + workflow/config.json ollama_backends |
| 專案自治層？ | wg_paths.py（registry + 路徑切換）+ project_hooks.py delegate |
| 怎麼升級環境？ | /upgrade skill（diff + merge + rebuild vector） |
