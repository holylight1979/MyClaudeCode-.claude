# 原子記憶系統 — 全檔案索引

> 由 `/read-project` 產出，最近同步：2026-03-30。
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
| extract-worker.py | ~774 | SessionEnd/per-turn/failure 子程序：LLM 萃取 + dedup |
| wisdom_engine.py | ~199 | 2 硬規則 + 3 反思指標 + Bayesian arch sensitivity |
| user-init.sh | ~20 | 多人 USER.md 初始化（SessionStart） |
| ensure-mcp.py | — | MCP server 可用性確認 |
| webfetch-guard.sh | — | WebFetch 安全護欄 |

合計：~5308 行

## 5. Skills（commands/，16 個）

| 指令 | 用途 | 依賴 |
|------|------|------|
| /atom-debug | Debug log 開關 | 無 |
| /conflict | 記憶衝突偵測（向量比對 + LLM 判定） | Vector Service + Ollama |
| /consciousness-stream | 高風險跨系統（唯識八識） | 無 |
| /continue | 讀 _staging/next-phase.md 續接 | 無 |
| /extract | 手動知識萃取（不等 SessionEnd） | Ollama |
| /fix-escalation | 精確修正升級（6 Agent 會議） | 無 |
| /harvest | Playwright 網頁收割→Markdown | Playwright |
| /init-project | 專案 _AIDocs + 自治層初始化 | 無 |
| /memory-health | 記憶品質診斷（audit + health-check） | 無 |
| /memory-review | 自我迭代檢閱（衰減/晉升/震盪/覆轍） | 無 |
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
- searcher.py — semantic + ranked + section-level（5-factor: semantic 0.45 + recency 0.15 + intent 0.20 + confidence 0.10 + confirmations 0.10）
- reranker.py — LLM query rewrite + re-rank

### Ollama 雙 Backend
- ollama_client.py — singleton，generate()/chat()/embed()
  - rdchat: qwen3.5:latest + qwen3-embedding:latest（RTX 3090，pri=1）
  - local: qwen3:1.7b + qwen3-embedding（GTX 1050 Ti，pri=2）
  - 三階段退避：normal → short_die(60s) → long_die(6h boundary)
  - Long DIE → workflow-guardian SessionStart 提示使用者確認停用/保持

### 記憶品質
- memory-audit.py — 格式驗證 + staleness（支援 `--project-dir`）
- memory-write-gate.py — 寫入閘門（6 規則 + 0.80 dedup）
- memory-conflict-detector.py — 向量衝突 + LLM 分類（支援 `--project-dir`）
- atom-health-check.py — 參照完整性

### 遷移/測試
- migrate-v221.py — V2.21 遷移（_AIAtoms + 個人記憶 → .claude/memory/）
- test-memory-v21.py — E2E 測試
- eval-ranked-search.py — 50 query benchmark
- cleanup-old-files.py — 環境清理

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
