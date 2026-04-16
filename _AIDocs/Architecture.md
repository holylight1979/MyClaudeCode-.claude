# Claude Code 全域設定 — 核心架構

## Hooks 系統

8 個 hook 事件（含 async Stop），定義在 `settings.json`。主 dispatcher `workflow-guardian.py`（~1530 行）+ 9 個模組化子檔：

| Hook | 觸發時機 | 用途 |
|------|---------|------|
| `UserPromptSubmit` | 使用者送出訊息 | RECALL 記憶檢索 + intent 分類（含 handoff）+ Context Budget 監控 + Wisdom 情境分類 + Failures 偵測 + Handoff 信號注入 |
| `PreToolUse` (Write) | Write 工具呼叫前 | Atom Format Gate：阻擋寫入 `{project}/.claude/memory/*.md` 但不符原子格式（Scope/Confidence/Trigger frontmatter）的內容 |
| `PostToolUse` | Edit/Write 後 | 追蹤修改檔案 + 增量索引 + Read Tracking + over_engineering 追蹤 |
| `PreCompact` | Context 壓縮前 | 快照 state（壓縮前保護） |
| `Stop` | 對話結束前 | 閘門：未同步則阻止結束 + Fix Escalation 信號注入 + 逐輪增量萃取 |
| `Stop (async)` | 對話結束後 | V3 quick-extract.py：qwen3:1.7b 5s 快篩 → hot_cache.json |
| `SessionStart` | Session 開始 | 初始化 session state + 去重（V3）+ Wisdom 盲點提醒 + 定期檢閱提醒 + 專案自治層 delegate |
| `SessionEnd` | Session 結束 | Episodic atom 生成 + 回應萃取（全量）+ 鞏固（簡化計數）+ 衝突偵測 + Wisdom 反思 |

### Hook 模組拆分

| 模組 | 行數 | 職責 |
|------|------|------|
| `workflow-guardian.py` | ~1540 | 瘦身 dispatcher：8 event handlers 編排（含 PreToolUse Format Gate + Handoff + Promotion Audit hint） |
| `wg_paths.py` | ~445 | 路徑唯一真相來源：slug/root/staging/registry；V4 新增 `get_scope_dir`、`discover_v4_sublayers(slug, mem_dir)`、`discover_memory_layers(user, role)`（user-aware filter mode + 預設 enumerate-all-sub-layer 給 indexer 用）；`get_project_memory_dir` V4 fallback（純 V4 layout 也視為合法 mem dir） |
| `wg_roles.py` | ~210 | V4 角色機制：`get_current_user`、`load_user_role`、`load_management_roster`、`is_management`（雙向認證）、`bootstrap_personal_dir`（冪等寫 .gitignore） |
| `wg_core.py` | ~370 | 共用常數/設定/state IO/output/debug（含 `log_promotion_audit`） |
| `wg_atoms.py` | ~559 | 索引解析/trigger 匹配/ACT-R/載入/budget/section-level 注入；`_parse_trigger_table` 容忍 4 欄（V4 Scope） |
| `wg_intent.py` | ~400 | 意圖分類/session context/MCP/vector service；`_semantic_search` 支援 user/roles 參數轉發到 vector service 端做 SPEC §8.1 role filter |
| `wg_extraction.py` | ~295 | per-turn 萃取/worker 管理/failure 偵測 |
| `wg_hot_cache.py` | ~139 | Hot Cache 讀寫/注入 |
| `wg_docdrift.py` | ~160 | DocDrift 偵測：src 改動→_AIDocs 映射→advisory 提醒 |
| `wg_episodic.py` | ~860 | episodic 生成/衝突偵測/品質回饋 |
| `wg_iteration.py` | ~450 | 自我迭代/震盪/衰減/晉升/覆轍偵測（含 atom header 與內部條目一致性對齊） |
| `extract-worker.py` | ~690 | SessionEnd/per-turn/failure 子程序：LLM 萃取 + dedup（共用核心移至 `lib/ollama_extract_core.py`） |
| `lib/ollama_extract_core.py` | ~190 | 萃取共用核心：`_call_ollama` / `_parse_llm_response` / `_dedup_items` / `_word_overlap_score` / debug log / `ack_then_clear` / `SessionBudgetTracker`。extract-worker + 未來 user-extract-worker 共用 |
| `quick-extract.py` | ~155 | Stop async 快篩：local qwen3:1.7b → hot_cache |
| `wisdom_engine.py` | ~177 | 反思引擎：硬規則 + 反思指標 |

### 輔助 Hook 腳本

| 檔案 | 用途 |
|------|------|
| `user-init.sh` | 多人 USER.md 初始化（SessionStart） |
| `ensure-mcp.py` | MCP server 可用性確認 |
| `webfetch-guard.sh` | WebFetch 安全護欄 |

## Skills（/Slash Commands）

| Skill | 檔案 | 用途 |
|-------|------|------|
| `/init-project` | `commands/init-project.md` | 專案知識庫（_AIDocs）+ 專案自治層初始化 |
| `/resume` | `commands/resume.md` | 自動續接 Session（MCP 桌面自動化） |
| `/continue` | `commands/continue.md` | 讀取 _staging/next-phase.md 續接任務 |
| `/consciousness-stream` | `commands/consciousness-stream.md` | 識流處理（高風險跨系統任務） |
| `/svn-update` | `commands/svn-update.md` | SVN 更新工作目錄 |
| `/unity-yaml` | `commands/unity-yaml.md` | Unity YAML Asset 操作 |
| `/upgrade` | `commands/upgrade.md` | 環境升級比對工具 |
| `/fix-escalation` | `commands/fix-escalation.md` | 精確修正升級（6 Agent 會議：蒐集→辯論 2 輪→決策→驗證） |
| `/extract` | `commands/extract.md` | 手動知識萃取（不等 SessionEnd） |
| `/conflict` | `commands/conflict.md` | 記憶衝突偵測（向量比對 + LLM 判定） |
| `/conflict-review` | `commands/conflict-review.md` | V4 管理職裁決 Pending Queue（雙向認證） |
| `/memory-health` | `commands/memory-health.md` | 記憶品質診斷（audit + health-check） |
| `/memory-review` | `commands/memory-review.md` | 自我迭代檢閱（衰減/晉升/震盪/覆轍） |
| `/atom-debug` | `commands/atom-debug.md` | Debug log 開關 |
| `/harvest` | `commands/harvest.md` | 網頁收割→Markdown（Playwright） |
| `/read-project` | `commands/read-project.md` | 系統性閱讀→doc-index atom |
| `/vector` | `commands/vector.md` | 向量服務管理（啟停/索引/搜尋） |

## 規則模組

`.claude/rules/` 下的 `.md` 檔案由 Claude Code 自動載入，CLAUDE.md 瘦身至 ~50 行：

| 模組 | 說明 |
|------|------|
| `rules/memory-system.md` | 原子記憶系統規則 |
| `rules/aidocs.md` | _AIDocs 知識庫維護 |
| `rules/session-management.md` | 對話管理 + 續航 + 自我迭代 + 精確修正升級 |
| `rules/sync-workflow.md` | 工作結束同步 + Guardian 閘門 |

## 記憶系統（原子記憶 V3.4）

### 雙 LLM 架構 + Dual-Backend

| 角色 | 引擎 | 職責 |
|------|------|------|
| 雲端 LLM | Claude Code | 記憶演進決策、分類判斷、晉升/淘汰 |
| 本地 LLM | Ollama (Dual-Backend) | embedding、query rewrite、re-ranking、intent 分類、回應知識萃取 |

#### Dual-Backend Ollama

統一 Ollama 呼叫入口 `tools/ollama_client.py`，支援多 backend 自動切換：

```
config.json → ollama_backends:
  rdchat-direct (priority=1, RTX 3090, gemma4:e4b) → rdchat proxy (priority=2) → local (priority=3, GTX 1050 Ti, qwen3:1.7b)
```

三階段退避：
- **正常** → 連續 2 次失敗 → **短DIE**（60s 冷卻，跳過此 backend）
- 10 分鐘內 2 次短DIE → **長DIE**（等到下個 6h 時段: 00/06/12/18 點）
- 長DIE 觸發 → SessionStart hook 詢問使用者「停用」或「保持」
- **靜態停用旗標**：`enabled: false` 永久跳過，不做 health check
- 認證：LDAP bearer token，帳號自動 `os.getlogin()`，密碼檔 `workflow/.rdchat_password`

### 資料層

1. **MEMORY.md**（always-loaded）: Atom 索引（全域 25 atoms + 專案層各自索引）
2. **Atom 檔案**（按需載入）: 由 Trigger 欄位 + 向量搜尋發現
3. **Vector DB**: LanceDB（`memory/_vectordb/`）
4. **Episodic atoms**: 自動生成 session 摘要（`memory/episodic/`，TTL 24d，不進 git）
5. **Wisdom Engine**: 反思統計（`memory/wisdom/`）
6. **專案自治層**: `{project_root}/.claude/memory/` — 每專案獨立 atoms + episodic + failures

### 記憶檢索管線

```
使用者訊息 → UserPromptSubmit hook (workflow-guardian.py)
  ├─ [V3] Hot Cache 快速路徑 (injected=false? → 注入)
  ├─ Intent 分類 (rule-based ~1ms)
  ├─ MEMORY.md Trigger 匹配 (keyword ~10ms)
  ├─ Vector Search (LanceDB + qwen3-embedding ~200-500ms)
  ├─ Ranked Merge → top atoms
  ├─ Context Budget: 3000 tokens 上限，ACT-R truncate
  ├─ Fix Escalation: retry_count≥2 → 注入 [FixEscalation] 信號
  ├─ Handoff Protocol: intent=handoff → 注入 [Guardian:Handoff] 提醒走 /handoff
  └─ additionalContext 注入
```

降級: primary 不可用 → fallback (Dual-Backend) | 全 Ollama 不可用 → 純 keyword | Vector Service 掛 → graceful fallback

### 回應知識捕獲

| 時機 | 輸入 | 上限 |
|------|------|------|
| Stop hook（逐輪增量） | byte_offset 增量讀取 | 4000 chars, 3 items |
| SessionEnd（全量） | 全 transcript | 20000 chars, 5 items |

情境感知萃取（依 intent 調整 prompt）。萃取結果一律 `[臨]`。注入前 Token Diet strip 9 種 metadata + 行動/演化日誌。

#### V3 三層即時管線

```
Claude 回應結束 → [Stop async] quick-extract.py (local qwen3:1.7b, 5s)
                    → hot_cache.json (injected=false)
Claude 使用工具 → [PostToolUse] hot cache check → mid-turn 注入
使用者下一句   → [UserPromptSubmit] hot cache 快速路徑 + 完整 pipeline
Deep extract   → [detached] extract-worker.py (rdchat: gemma4:e4b) → 覆寫 hot cache → 正式 atom
```

### SessionStart 去重

- 同 cwd 60s 內 active state → 複用（resume 合併，startup 跳過 vector init）
- 分層孤兒清理：prompt_count=0 working→10m, prompt_count>0 working→30m, done→24h
- Vector service 非阻塞：fire-and-forget subprocess + `vector_ready.flag`

### 專案自治層

- **Project Registry**（`memory/project-registry.json`）：SessionStart 自動 `register_project(cwd)`，跨專案發現
- **路徑切換**：`get_project_memory_dir()` 新路徑 `{project_root}/.claude/memory/` 優先，舊路徑 fallback
- **專案 Delegate**：`{project_root}/.claude/hooks/project_hooks.py`（inject/extract/on_session_start），subprocess 隔離呼叫（5s timeout）
- **遷移工具**：`tools/migrate-v221.py`（_AIAtoms + 個人 memory → .claude/memory/）

### V4 三層 Scope + Role-filtered JIT 注入

- **三層 scope**（per project）：`shared/` / `roles/{r}/` / `personal/{user}/`，加上 `global`（`~/.claude/memory/`）共四層
- **SessionStart 流程**：`get_current_user()` → `bootstrap_personal_dir()`（冪等建 `personal/{user}/role.md` + `.gitignore`）→ `load_user_role()`（多角色逗號分隔）→ `is_management()`（雙向認證：personal `role.md` 宣告 + shared `_roles.md` 白名單）→ 寫入 `state["user_identity"]`
- **atom_index 載入**：V4 layout 偵測（shared/roles/personal 任一存在）→ 直接用 `_collect_v4_role_atoms` 結果（避免 V3 MEMORY.md 自我循環）；非 V4 → V3 MEMORY.md/_ATOM_INDEX.md fallback + V4 entries union
- **動態 MEMORY.md**：`_regenerate_role_filtered_memory_index` 寫 `<!-- AUTO-GENERATED: V4 role filter -->` header；護寫保護：檔案存在且首行不是 header → 跳過（不覆寫 V3 人手版本）
- **JIT vector filter**（SPEC §8.1）：UPS 從 `state["user_identity"]` 取 user/roles，呼叫 `_semantic_search(user, roles)`；vector service 端 `_build_v4_layer_clause` 組 `(layer = 'global' OR layer LIKE 'shared:%' OR layer LIKE 'role:%:r1' OR ... OR layer LIKE 'personal:%:user')`，sanitize `[\w-]+` 防注入；管理職 → 不傳 user/roles → 全量
- **Vector layer schema**：indexer 把 project 拆 `shared:{slug}` / `role:{slug}:{r}` / `personal:{slug}:{user}` 三類；`flat-legacy` kind 處理 mem_dir 直下舊 atom（視為 shared）；chunk metadata 新增 `Scope`/`Audience`/`Author` 三欄
- **管理職額外**：`_count_pending_review` 計 `shared/_pending_review/*.md` → context line `[Pending Review] N 件`

### V4 三時段衝突偵測（Phase 5，SPEC §7）

shared 寫入的事實衝突防線，由 `memory-conflict-detector.py` 承擔 LLM 分類（gemma4:e4b），`server.js`/git hook/skill 分別對接三個時段：

| 時段 | 觸發點 | 落點 | 關鍵行為 |
|------|--------|------|---------|
| Write-time | `atom_write scope=shared` create 分支 | MCP server.js | vector top-3 ≥ 0.60 → ollama_classify → CONTRADICT 寫 `_pending_review/{slug}.conflict.md`（非 atom、阻擋寫入）；EXTEND + sim ≥ 0.85 reroute 為 `_pending_review/{slug}.md` 草稿 |
| Pull-time | `git pull` 後 `.git/hooks/post-merge` | `hooks/post-git-pull.sh` → detector `--mode=pull-audit` | 讀 `.last_pull_audit_ts` → `git log --since` 抓 shared/*.md 變動 → classify → CONTRADICT 寫 `_pending_review/{slug}.pull-conflict.md` |
| Git-conflict-time | 硬碰硬 merge conflict | `git mergetool` | 純文件約定：Claude 只給合併建議，**不動檔**；整份走 git tool |

- **Fail-open**：vector/LLM 服務 down → verdict=ok + skipped=true（不阻塞所有寫入）
- **Conservative pending**：LLM 分類失敗但 sim ≥ 0.85 → 當作 CONTRADICT 進 pending（漏判好過誤判）
- **`Merge-strategy: git-only`**：標此欄位的 atom 跳過所有 AI 合併（write-check + pull-audit 雙方都跳）
- **敏感類別自動 pending**（Phase 3 既有）：Audience 含 `architecture`/`decision` 強制進 `_pending_review/`（與衝突偵測獨立，互為 AND）
- **管理職 `/conflict-review`**：`commands/conflict-review.md` + `tools/conflict-review.py` 後端，list/approve/reject 三動作；`is_management(cwd, user)` 雙向認證（personal role.md + shared _roles.md 白名單）未通過一律拒絕
- **_merge_history.log**：per-project `{proj}/.claude/memory/_merge_history.log`，TSV append-only 6 欄 `ts, action, atom, scope, by, detail`；action ∈ {auto-merge, pending-create, approve, reject, pull-audit-flag}
- **Approve 流程**：搬 `_pending_review/{slug}.md` → `shared/{slug}.md`、移除 `Pending-review-by:` 行、加 `Decided-by:` + 更新 `Last-used`、刪同名 .conflict.md、POST `/index/incremental` 重索引
- **阻擋寫入但不 isError**：CONTRADICT 回傳 sendToolResult(false)，讓使用者知道 pending 是正常流程

#### 完整衝突偵測流程圖（Phase 6 收尾補）

```
┌──────────────────────── Write-time (MCP atom_write) ────────────────────────┐
│                                                                              │
│  caller → server.js → normalize_scope                                        │
│    │                                                                         │
│    ├─ scope=role|personal → 寫 {proj}/memory/{layer}/ ──── END（不檢查衝突） │
│    │                                                                         │
│    └─ scope=shared                                                           │
│        │                                                                     │
│        ├─ skip_gate=false → memory-write-gate（去重 cosine ≥ 0.80） ──→ dedup │
│        │                                                                     │
│        ├─ skip_conflict_check=false → memory-conflict-detector               │
│        │   --mode=write-check（vector top-3 ≥ 0.60 → gemma4:e4b classify）   │
│        │     │                                                               │
│        │     ├─ verdict=CONTRADICT → 寫 shared/_pending_review/              │
│        │     │     {slug}.conflict.md  + merge_history: pending-create       │
│        │     │     回傳 BLOCKED ── END                                       │
│        │     │                                                               │
│        │     └─ verdict=EXTEND sim ≥ 0.85 → reroute 為                       │
│        │         shared/_pending_review/{slug}.md                            │
│        │         +Pending-review-by: management                              │
│        │                                                                     │
│        └─ audience ∈ {architecture, decision}                                │
│            → 強制 reroute 為 shared/_pending_review/{slug}.md                │
│            +Pending-review-by: management  （與衝突檢查獨立 AND）            │
│                                                                              │
│        最終落點：shared/{slug}.md OR shared/_pending_review/{slug}[.conflict].md│
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────── Pull-time (post-merge hook) ────────────────────────┐
│                                                                              │
│  git pull/merge → .git/hooks/post-merge (hooks/post-git-pull.sh)             │
│    │                                                                         │
│    ├─ curl POST /index/incremental → 等 indexing=False 最多 12s              │
│    │   （避免 race：新進 atom 還沒被 vector indexer 看到）                   │
│    │                                                                         │
│    └─ python memory-conflict-detector --mode=pull-audit                      │
│        │                                                                     │
│        ├─ 讀 .last_pull_audit_ts → git log --since 抓 shared/*.md 變動       │
│        ├─ 對每個新 atom 跑 classify                                          │
│        │   CONTRADICT → 寫 shared/_pending_review/{slug}.pull-conflict.md    │
│        │              + merge_history: pull-audit-flag                       │
│        └─ 更新 .last_pull_audit_ts                                           │
│                                                                              │
│  Fail-open：任何步驟掛掉 → warning stderr，不阻擋 pull                       │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────── Review-time (/conflict-review skill) ───────────────────┐
│                                                                              │
│  mgmt_user → conflict-review.py --action=approve|reject                      │
│    │                                                                         │
│    ├─ is_management(cwd, user) 雙向認證（personal role.md + shared 白名單）  │
│    │   失敗 → {"error": "not authorized as management"} ── END               │
│    │                                                                         │
│    ├─ approve {slug} 或 {slug}.resolved                                      │
│    │   │                                                                     │
│    │   ├─ strip Pending-review-by: / append Decided-by: / bump Last-used     │
│    │   ├─ 搬到 shared/{slug}.md（與 resolved 支線共用 stem）                 │
│    │   ├─ 刪同名 .conflict.md（若存在）                                      │
│    │   ├─ 刪 source （_pending_review/{slug}[.resolved].md）                 │
│    │   └─ merge_history: approve + POST /index/incremental                   │
│    │                                                                         │
│    └─ reject {slug}                                                          │
│        ├─ 刪 _pending_review/{slug}*.{md,.conflict.md,.pull-conflict.md}     │
│        └─ merge_history: reject                                              │
└──────────────────────────────────────────────────────────────────────────────┘

JIT 保護：_collect_v4_role_atoms 以 rel_parts[:-1] startswith("_") 過濾
  → shared/_pending_review/* 不會被注入任何 user 的 additionalContext
  → 管理職改從 SessionStart [Pending Review] N 件 提示得知有待裁決項
```

### 跨 Session 鞏固

- 廢除自動晉升，改為 Confirmations +1 簡單計數
- 4+ sessions → 建議晉升（不自動執行）
- 統一 dedup 閾值 0.80
- SessionEnd 衝突偵測：向量搜尋 score 0.60-0.95 → 寫入 episodic 衝突警告

### Wisdom Engine

- **情境分類器**：2 條硬規則（file_count/is_feature → confirm; touches_arch → plan）
- **反思引擎**：first_approach_accuracy + over_engineering_rate + silence_accuracy + Bayesian 校準
- **Fix Escalation Protocol**：同一問題修正第 2 次起強制 6 Agent 精確修正會議，Guardian 自動偵測 + /fix-escalation skill

### 工具鏈

| 工具 | 路徑 | 用途 |
|------|------|------|
| ollama_client.py | `tools/ollama_client.py` | Dual-Backend Ollama Client（三階段退避+auth+failover） |
| rag-engine.py | `tools/rag-engine.py` | CLI: search/index/status/health |
| memory-write-gate.py | `tools/memory-write-gate.py` | 寫入品質閘門 + 去重 |
| memory-audit.py | `tools/memory-audit.py` | 格式驗證、過期、晉升建議（支援 `--project-dir`） |
| memory-conflict-detector.py | `tools/memory-conflict-detector.py` | 矛盾偵測（full-scan / write-check / pull-audit 三 mode） |
| conflict-review.py | `tools/conflict-review.py` | V4 Pending Queue 後端（list/approve/reject，管理職雙向認證 guard） |
| atom-health-check.py | `tools/atom-health-check.py` | Atom 健康度（Related 完整性） |
| migrate-v221.py | `tools/migrate-v221.py` | V2.21 遷移（_AIAtoms + 個人記憶 → .claude/memory/） |
| cleanup-old-files.py | `tools/cleanup-old-files.py` | 環境清理 |
| read-excel.py | `tools/read-excel.py` | Excel 讀取工具 |
| unity-yaml-tool.py | `tools/unity-yaml-tool.py` | Unity YAML 解析/生成 |
| memory-vector-service/ | `tools/memory-vector-service/` | HTTP 服務 (port 3849) |
| gdoc-harvester/ | `tools/gdoc-harvester/` | Google Docs/Sheets 收割 + dashboard |
| workflow-guardian-mcp/ | `tools/workflow-guardian-mcp/` | MCP server + Dashboard (port 3848) |
| wisdom_engine.py | `hooks/wisdom_engine.py` | Wisdom Engine（情境分類+反思） |

## MCP Servers

| Server | 傳輸 | 用途 |
|--------|------|------|
| workflow-guardian | stdio (Node.js) | session 管理 + Dashboard (port 3848) |

### atom_write 工具（V4 三層 scope，2026-04-15+）

| 參數 | 行為 |
|------|------|
| `scope=global` | 寫 `~/.claude/memory/`（不變） |
| `scope=shared`（預設） | 寫 `{proj}/.claude/memory/shared/` |
| `scope=role` + `role=art\|programmer\|...` | 寫 `roles/{role}/`，metadata `Scope: role:{role}` |
| `scope=personal` + `user=...`（缺則當前使用者） | 寫 `personal/{user}/`，metadata `Scope: personal:{user}` |
| `scope=project`（legacy） | 透明轉 `shared` + stderr deprecation hint |
| 不傳 scope | 預設 `shared`（舊 caller 相容） |

新 metadata 自動帶入：`Author`（server 端 env/OS user，不接受 caller 傳）、`Created-at`（今日）、`Audience`/`Pending-review-by`/`Merge-strategy`（caller optional）。

**SPEC 7.4 敏感類別自動 pending**：`scope=shared` 且 `audience` 含 `architecture` 或 `decision` → 改寫到 `shared/_pending_review/`，自動補 `Pending-review-by: management`。

詳見 [SPEC_ATOM_V4.md](SPEC_ATOM_V4.md) §4 / §7.4 / §10。

## 權限設定

`settings.json` 的 `permissions.allow` 列表：
- Bash: powershell, python, ls, wc, du, git, gh, ollama, curl, echo, grep, find
- Read: C:\Users\**, C:\OpenClawWorkspace\**
- MCP: workflow-guardian (workflow_signal, workflow_status)
