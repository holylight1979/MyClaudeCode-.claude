# 工具鏈實戰記憶

- Scope: global
- Confidence: [固]
- Trigger: 工具鏈, 環境設定, MCPControl, MCP新增, npm全域, 螢幕截圖, Excel MCP, LanceDB, MSYS2, cp950, PowerShell截圖, 向量服務
- Last-used: 2026-04-14
- Confirmations: 167
- Type: procedural
- Tags: toolchain, environment, commands
- Related: toolchain-ollama, decisions, feedback_global_install

## 知識

### Windows 環境差異

- [固] Claude Code 的 bash 環境是 MSYS2，路徑格式 `/c/Users/` 而非 `C:\Users\`，但 Python Path 物件自動轉換
- [固] Windows 上 bash 指令的 `/dev/null` 有效（MSYS2 模擬），不需改成 `NUL`
- [固] `timeout` 指令在 MSYS2 bash 不可用，需用 Python 的 subprocess timeout 或其他替代
- [固] Windows 環境變數用 `$env:VAR`（PowerShell）或 `$VAR`（bash），混用易出錯

### 已驗證的指令組合

- [固] Ollama 啟動: `ollama serve`（背景）→ `ollama list`（驗證模型可用）
- [固] 向量服務啟動: `python ~/.claude/tools/memory-vector-service/service.py`（port 3849）
- [固] 向量健康檢查: `curl http://127.0.0.1:3849/health`
- [固] 記憶格式檢查: `python ~/.claude/tools/memory-audit.py`

### 路徑與版本

- [固] Ollama models 位置: 預設 `~/.ollama/models/`
- [固] LanceDB 資料: `~/.claude/memory/_vectordb/`

### Ollama Dual-Backend → 詳見 `toolchain-ollama.md`

### MCP Server：MCPControl（computer-use-mcp）

- [固] 全域安裝：`npm i -g computer-use-mcp`，目前版本 1.7.1
- [固] 功能：螢幕截圖、滑鼠點擊/拖曳、鍵盤輸入、捲動 — 可操控任何桌面應用程式
- [固] 工具名稱：`mcp__MCPControl__computer`（action: get_screenshot / left_click / type / key 等）
- [固] **跨專案可用**：不限於特定專案，任何 session 都能用來檢視畫面、操控 UI（包括 Unity Editor、瀏覽器、任意桌面 App）
- [固] 常見用途：Unity Editor UI 驗證、截圖比對、自動化 GUI 操作、協助使用者確認視覺結果
- [固] **使用者明確要求**：需要看畫面時優先用 MCPControl，不要說「看不到」。若 MCPControl 未連線，fallback 用 PowerShell 截圖：`CopyFromScreen` → 存 PNG → Read tool 讀取
- [固] PowerShell 截圖配方：`Add-Type System.Windows.Forms + System.Drawing` → `Bitmap` → `Graphics.CopyFromScreen` → `.Save()`；可 `Bitmap.Clone(Rectangle)` 裁切特定區域

### MCP Server：Excel（@negokaz/excel-mcp-server）

- [固] 全域安裝：`npm i -g @negokaz/excel-mcp-server`，目前版本 0.12.0
- [固] 功能：describe_sheets / read_sheet / write_to_sheet / create_table / format_range / screen_capture
- [固] 支援 xlsx/xlsm/xltx/xltm；**不支援舊版 .xls**（舊版用 `tools/read-excel.py` + xlrd）
- [固] 跨專案可用（`~/.claude.json` User scope）

### MCP 新增規則

- [固] **全域 MCP 設定位置**：`~/.claude.json`（注意不是 `~/.claude/.mcp.json`）的 `mcpServers` 欄位 → 所有專案顯示為 "User" scope
- [固] **`~/.claude/.mcp.json` 是專案層**：只在 `~/.claude` 作為工作目錄時生效，其他專案看不到
- [固] **一律全域安裝 + 絕對路徑**：`npm i -g {pkg}` → 用 `node.exe` + 絕對路徑指向 `AppData/Roaming/npm/node_modules/{pkg}/dist/{entry}.js`
- [固] **禁用 npx 啟動**：`cmd /c npx` 在 VSCode 擴充環境不穩定，MCP server 會無法啟動
- [固] 入口查找：`package.json` 的 `bin` 欄位確認 entry point
- [固] 範本：`"command": "C:\\Program Files\\nodejs\\node.exe", "args": ["C:\\Users\\holylight\\AppData\\Roaming\\npm\\node_modules\\{pkg}\\dist\\{entry}.js"]`

### 環境特殊配置

- [固] ChromaDB 已棄用，改用 LanceDB（i7-3770 不支援 AVX2）
- [固] workflow-guardian.py stdout/stderr 強制 UTF-8（Windows 預設 cp950 會導致中文亂碼）

## 行動

- build/setup/config intent 時自動載入
- 成功執行新工具指令後，評估是否值得記錄（跨 session 重用性 ≥ 2 次預期）
- 環境問題 debug 時，優先查此 atom 再嘗試盲目探索
- 版本資訊在確認後更新，不猜測

