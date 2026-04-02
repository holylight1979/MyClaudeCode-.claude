# Claude Code 全域設定 — 核心架構

## Hooks 系統

7 個 hook 事件（含 async Stop），定義在 `settings.json`。主 dispatcher `workflow-guardian.py`（~1450 行）+ 8 個模組化子檔（合計 ~5966 行）：

| Hook | 觸發時機 | 用途 |
|------|---------|------|
| `UserPromptSubmit` | 使用者送出訊息 | RECALL 記憶檢索 + intent 分類 + Context Budget 監控 + Wisdom 情境分類 + Failures 偵測 |
| `PostToolUse` | Edit/Write 後 | 追蹤修改檔案 + 增量索引 + Read Tracking + over_engineering 追蹤 |
| `PreCompact` | Context 壓縮前 | 快照 state（壓縮前保護） |
| `Stop` | 對話結束前 | 閘門：未同步則阻止結束 + Fix Escalation 信號注入 + 逐輪增量萃取 |
| `Stop (async)` | 對話結束後 | V3 quick-extract.py：qwen3:1.7b 5s 快篩 → hot_cache.json |
| `SessionStart` | Session 開始 | 初始化 session state + 去重（V3）+ Wisdom 盲點提醒 + 定期檢閱提醒 + 專案自治層 delegate |
| `SessionEnd` | Session 結束 | Episodic atom 生成 + 回應萃取（全量）+ 鞏固（簡化計數）+ 衝突偵測 + Wisdom 反思 |

### Hook 模組拆分

| 模組 | 行數 | 職責 |
|------|------|------|
| `workflow-guardian.py` | ~1447 | 瘦身 dispatcher：7 event handlers 編排 |
| `wg_paths.py` | ~314 | 路徑唯一真相來源：slug/root/staging/registry |
| `wg_core.py` | ~333 | 共用常數/設定/state IO/output/debug |
| `wg_atoms.py` | ~559 | 索引解析/trigger 匹配/ACT-R/載入/budget/section-level 注入 |
| `wg_intent.py` | ~387 | 意圖分類/session context/MCP/vector service |
| `wg_extraction.py` | ~295 | per-turn 萃取/worker 管理/failure 偵測 |
| `wg_hot_cache.py` | ~139 | Hot Cache 讀寫/注入 |
| `wg_episodic.py` | ~860 | episodic 生成/衝突偵測/品質回饋 |
| `wg_iteration.py` | ~431 | 自我迭代/震盪/衰減/晉升/覆轍偵測 |
| `extract-worker.py` | ~806 | SessionEnd/per-turn/failure 子程序：LLM 萃取 + dedup |
| `quick-extract.py` | ~155 | Stop async 快篩：qwen3:1.7b → hot_cache |
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

## 記憶系統（原子記憶 V3.1）

### 雙 LLM 架構 + Dual-Backend

| 角色 | 引擎 | 職責 |
|------|------|------|
| 雲端 LLM | Claude Code | 記憶演進決策、分類判斷、晉升/淘汰 |
| 本地 LLM | Ollama (Dual-Backend) | embedding、query rewrite、re-ranking、intent 分類、回應知識萃取 |

#### Dual-Backend Ollama

統一 Ollama 呼叫入口 `tools/ollama_client.py`，支援多 backend 自動切換：

```
config.json → ollama_backends:
  primary (priority=1, 遠端 GPU) → fallback (priority=2, 本地)
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
Claude 回應結束 → [Stop async] quick-extract.py (qwen3:1.7b, 5s)
                    → hot_cache.json (injected=false)
Claude 使用工具 → [PostToolUse] hot cache check → mid-turn 注入
使用者下一句   → [UserPromptSubmit] hot cache 快速路徑 + 完整 pipeline
Deep extract   → [detached] extract-worker.py → 覆寫 hot cache → 正式 atom
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
| memory-conflict-detector.py | `tools/memory-conflict-detector.py` | 矛盾偵測（支援 `--project-dir`） |
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

## 權限設定

`settings.json` 的 `permissions.allow` 列表：
- Bash: powershell, python, ls, wc, du, git, gh, ollama, curl, echo, grep, find
- Read: C:\Users\**, C:\OpenClawWorkspace\**
- MCP: workflow-guardian (workflow_signal, workflow_status)
