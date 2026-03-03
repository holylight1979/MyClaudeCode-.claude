# 系統架構總覽

> `~/.claude` 自訂擴充系統的完整架構描述。

---

## 目錄結構（僅自訂部分）

```
~/.claude/
  CLAUDE.md                              # 全域指令（6 大區塊）
  settings.json                          # 權限 + hooks 註冊
  hooks/
    workflow-guardian.py                  # Hook 事件處理腳本
  tools/
    workflow-guardian-mcp/
      server.js                          # MCP server + HTTP Dashboard
  workflow/
    config.json                          # Guardian 可調參數
    state-{session-id}.json              # 執行時狀態（auto-generated）
  memory/
    MEMORY.md                            # 全域原子記憶索引
    preferences.md                       # 使用者偏好 atom
    decisions.md                         # 全域決策 atom
    SPEC_Atomic_Memory_System.md         # 原子記憶系統規格 v1.0
  commands/
    init-project.md                      # /init-project skill 定義
  _AIDocs/
    _INDEX.md                            # 本知識庫索引
    _CHANGELOG.md                        # 變更記錄
    Architecture.md                      # 本文件
```

---

## 系統一：原子記憶

### 設計理念

跨 session 知識管理，解決 AI 無法記憶的問題。核心原則：
- **低 token、高精準**：索引式載入，不命中就不讀
- **強制分類**：所有記憶必須標記 [固]/[觀]/[臨]
- **永不刪除**：過期記憶沉降至 `_distant/`，可拉回

### 兩層架構

| 層 | 路徑 | 內容 |
|----|------|------|
| 全域層 | `~/.claude/memory/` | 使用者偏好、通用工具決策 |
| 專案層 | `~/.claude/projects/{slug}/memory/` | 專案架構、踩坑記錄 |

### 載入流程

```
Session 啟動
  → Read 全域 MEMORY.md（索引 + 高頻事實）
  → Read 專案 MEMORY.md
  → 比對使用者訊息 vs Trigger 關鍵詞
  → 命中 → Read 對應 atom 檔
  → 未命中 → 不載入（省 token）
```

### 三層分類

| 符號 | 引用行為 | 晉升條件 |
|------|---------|---------|
| [固] | 直接引用 | 4+ sessions 確認 |
| [觀] | 簡短確認 | 2+ sessions 確認 |
| [臨] | 明確確認 | 單次決策 |

詳細規格：`memory/SPEC_Atomic_Memory_System.md`

---

## 系統二：Workflow Guardian

### 設計理念

防止 AI 完成修改後忘記同步知識庫、CHANGELOG 和版控。用 Claude Code hooks 事件驅動，零背景進程。

### 核心元件

#### 1. Hook 腳本 (`hooks/workflow-guardian.py`)

處理 6 個生命週期事件：

| 事件 | 行為 |
|------|------|
| SessionStart | 建立/恢復 session 狀態，解析記憶索引 |
| PostToolUse | 靜默記錄 Edit/Write 修改的檔案 |
| UserPromptSubmit | 週期性提醒未同步修改（有上限） |
| PreCompact | context 壓縮前快照 |
| Stop | **閘門**：未同步修改 ≥ 門檻時阻止結束（exit code 2） |
| SessionEnd | 清理標記 |

#### 2. MCP Server (`tools/workflow-guardian-mcp/server.js`)

- 4 個 MCP tools：`workflow_status`, `workflow_signal`, `memory_queue_add`, `memory_queue_flush`
- HTTP Dashboard @ `http://127.0.0.1:3848`
- 生命週期綁定 Claude Code（不獨立常駐）
- **多實例 Dashboard**：port probe + 15 秒 heartbeat recovery，確保存活的 MCP instance 自動接管 port

#### ⚠ MCP 傳輸格式（重要踩坑）

Claude Code v2.x 的 MCP stdio 傳輸格式是 **換行分隔 JSON（JSONL）**：

```
接收: {"method":"initialize",...}\n
回應: {"jsonrpc":"2.0","id":0,"result":{...}}\n
```

**不是** LSP 風格的 Content-Length header 格式（`Content-Length: NNN\r\n\r\n{...}`）。自行開發 MCP server 時必須使用 JSONL，否則 Claude Code 會等 30 秒超時後標記 failed 並強制終止 process。

對應的 protocolVersion 為 `2025-11-25`。

#### 3. 可調參數 (`workflow/config.json`)

| 參數 | 預設 | 說明 |
|------|------|------|
| stop_gate_max_blocks | 2 | Stop 最多阻擋 N 次，第 N+1 次強制放行 |
| min_files_to_block | 2 | 修改檔案 < N 時不觸發閘門 |
| remind_after_turns | 3 | 每 N 輪提醒一次 |
| max_reminders | 3 | 整個 session 最多提醒 N 次 |
| dashboard_port | 3848 | Dashboard HTTP port |

### 狀態流轉

```
SessionStart → working
  ↓ (修改檔案)
working → working (PostToolUse 累積)
  ↓ (使用者要求同步 / Stop 閘門提醒)
working → syncing (workflow_signal: sync_started)
  ↓ (同步完成)
syncing → done (workflow_signal: sync_completed)
  ↓ (可隨時)
any → muted (workflow_signal: mute) → 所有提醒靜默
```

### Dashboard 功能

- Session 卡片：專案名稱（從 cwd 提取）、phase 徽章、檔案/知識計數
- 操作按鈕：Mark Synced、Reset、Mute、Delete
- 自動刷新（5 秒）
- 已結束 session 60 秒後自動清理

---

## 系統三：CLAUDE.md 全域指令

6 大區塊：

1. **_AIDocs 知識庫** — session 啟動檢查、工作中規則
2. **原子記憶** — 兩層載入、三層分類、晉升/沉降
3. **工作結束同步** — context-aware 情境判斷表 + Guardian 監督
4. **對話管理** — 新開 session 時機、已決策不重複分析
5. **外部服務存取** — Redmine REST API 模板
6. **使用者偏好** — 語言、風格、可讀性原則
