# 原子記憶系統 — 全檔案索引

- Scope: global
- Confidence: [固]
- Type: semantic
- Trigger: 記憶系統架構, 檔案結構, hook, skill, tool, 記憶升級, 記憶迭代, 目錄結構
- Last-used: 2026-03-24
- Updated: 2026-03-23
- Created: 2026-03-13
- Confirmations: 47
- Tags: doc-index, system-overview
- Related: decisions, decisions-architecture, toolchain

## 知識

### 啟動鏈

1. `settings.json` — 權限 + hook 事件 + MCP
2. `hooks/user-init.sh` — USER.md 生成
3. `hooks/workflow-guardian.py:handle_session_start()` — Guardian 初始化
4. `CLAUDE.md` @import → IDENTITY.md + USER.md + MEMORY.md + rules/*

### 設定檔

| 檔案 | 用途 |
|------|------|
| `CLAUDE.md` | 全域入口（@import 3 檔 + rules/ 4 模組） |
| `IDENTITY.md` | AI 人格（團隊共用） |
| `USER.md` | 使用者偏好（per-user，hook 生成） |
| `USER.template.md` | 多人使用模板（git 追蹤） |
| `BOOTSTRAP.md` | 首次設定引導 |
| `settings.json` | Hook 綁定 + 權限 + MCP |
| `.mcp.json` | MCP server 定義 |
| `workflow/config.json` | Guardian/Vector/WriteGate/Capture 參數 |

### 規則模組（rules/）

| 檔案 | 用途 |
|------|------|
| `aidocs.md` | _AIDocs 維護規則 |
| `memory-system.md` | 原子記憶分類/寫入/演進/引用 |
| `session-management.md` | 對話管理 + 續航 + 識流 + 自我迭代 |
| `sync-workflow.md` | 同步 checklist + Guardian 閘門 |

### Hook 系統（hooks/）

| 檔案 | 行數 | 用途 |
|------|------|------|
| `workflow-guardian.py` | ~1130 | 瘦身 dispatcher：6 event handlers 編排 |
| `wg_core.py` | ~266 | 共用常數/設定/state IO/output/debug |
| `wg_atoms.py` | ~403 | 索引解析/trigger 匹配/ACT-R/載入/budget |
| `wg_intent.py` | ~340 | 意圖分類/session context/MCP/vector service |
| `wg_extraction.py` | ~257 | per-turn 萃取/worker 管理/failure 偵測 |
| `wg_episodic.py` | ~863 | episodic 生成/衝突偵測/品質回饋 |
| `wg_iteration.py` | ~415 | 自我迭代/震盪/衰減/晉升/覆轍 |
| `extract-worker.py` | ~530 | SessionEnd/per-turn/failure 子程序：LLM 萃取 + dedup |
| `wisdom_engine.py` | ~195 | 反思引擎：硬規則 + 反思指標 |
| `user-init.sh` | ~20 | 多人 USER.md 初始化 |

### Skills（commands/）

| Skill | 用途 | 外部依賴 |
|-------|------|---------|
| `/atom-debug` | Debug log 開關 | 無 |
| `/conflict` | 記憶衝突偵測（向量比對 + LLM 判定） | Vector Service + Ollama |
| `/consciousness-stream` | 高風險跨系統任務 | 無 |
| `/continue` | 續接暫存任務 | 無 |
| `/extract` | 手動知識萃取（不等 SessionEnd） | Ollama |
| `/fix-escalation` | 精確修正升級（6 Agent） | 無 |
| `/harvest` | 網頁收割 → Markdown | Playwright |
| `/init-project` | 專案知識庫初始化 | 無 |
| `/memory-health` | 記憶品質診斷（audit + health-check 合併） | 無 |
| `/memory-review` | 自我迭代檢閱（衰減/晉升/震盪/覆轍/episodic） | 無 |
| `/read-project` | 系統性讀取 → doc-index | 無 |
| `/resume` | 續接 + 自動開新 session | MCPControl |
| `/svn-update` | SVN 更新 + 衝突處理 | TortoiseSVN |
| `/unity-yaml` | Unity YAML 操作 | unity-yaml-tool.py |
| `/upgrade` | 環境升級 | 無 |
| `/vector` | 向量服務管理（啟停/索引/搜尋） | Vector Service |

### 工具（tools/）

| 檔案/目錄 | 用途 |
|-----------|------|
| `memory-vector-service/` | 向量服務 @ port 3849 |
| `ollama_client.py` | Ollama 雙 Backend singleton |
| `memory-audit.py` | atom 格式驗證 + staleness |
| `memory-write-gate.py` | 寫入品質閘門 |
| `memory-conflict-detector.py` | 向量衝突偵測 |
| `atom-health-check.py` | 參照完整性驗證 |
| `read-excel.py` | Excel 讀取 |
| `unity-yaml-tool.py` | Unity YAML 解析/生成 |
| `rag-engine.py` | Vector Service CLI |
| `cleanup-old-files.py` | 舊檔清理 |
| `gdoc-harvester/` | Google Docs/Sheets 收割 |
| `workflow-guardian-mcp/server.js` | MCP server + dashboard @ port 3848 |

### 記憶層（memory/）

| 路徑 | 用途 |
|------|------|
| `MEMORY.md` | Atom 索引（always loaded） |
| `*.md` (13 atoms) | 全域原子記憶 |
| `_reference/` | 參考文件：SPEC, self-iteration, v3-design, v3-research, decisions-history |
| `episodic/` | 自動生成，TTL 24d（gitignore） |
| `_vectordb/` | LanceDB 資料（gitignore） |
| `_staging/` | 暫存區（gitignore） |

### 對外文件

| 檔案 | 用途 |
|------|------|
| `README.md` | GitHub 入口 |
| `Install-forAI.md` | 安裝 SOP |
| `_AIDocs/` | 專案知識庫 |
| `LICENSE` | GPLv3 |

## 行動

- 需要了解某模組細節時，直接 Read 對應檔案
- 升級/迭代時，從此索引定位影響範圍
- 新增檔案後更新此索引
- 開發記憶系統時讀 `_reference/` 下的 SPEC、self-iteration、v3-design、v3-research

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-13 | 初始建立 | /read-project |
| 2026-03-19 | 精修：純索引化，移除架構描述，去重 decisions | 系統精修 |
| 2026-03-19 | 更新 extract-worker/guardian 行數+功能（v2.13 failure mode） | failures 自動化 |
| 2026-03-23 | Guardian 模組化：1 monolith → 7 模組（wg_core/atoms/intent/extraction/episodic/iteration） | 重構 Phase 1-6 |
