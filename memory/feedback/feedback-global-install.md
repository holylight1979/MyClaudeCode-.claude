# MCP / Skill 安裝一律全域

- Scope: global
- Confidence: [固]
- Trigger: 安裝MCP, 安裝skill, install MCP, install skill, add MCP, 新增MCP, 新增skill
- Related: toolchain

## 知識

### 核心規則：安裝任何 MCP 或 Skill 時，一律設定為全域可用

- [固] **MCP server 全域設定**：寫入 `~/.claude.json` 的 `mcpServers` 欄位（User scope）
- [固] **禁止寫入 `~/.claude/.mcp.json`**：該檔是專案層，只在 `~/.claude` 工作目錄生效，其他專案看不到
- [固] **禁止寫入 `{project}/.mcp.json`**：除非使用者明確要求「只給這個專案用」
- [固] **Skill 全域設定**：放 `~/.claude/commands/{name}.md`（已是全域）
- [固] **Rules 全域設定**：放 `~/.claude/rules/{name}.md`（已是全域）

### MCP 安裝 SOP（4 步）

1. **全域安裝套件**：`npm i -g {package}`
2. **找入口點**：讀 `package.json` 的 `bin` 欄位 → 對應 `.js` 檔案路徑
3. **寫入 `~/.claude.json`**：
   ```json
   "{name}": {
     "type": "stdio",
     "command": "C:\\Program Files\\nodejs\\node.exe",
     "args": ["C:\\Users\\holylight\\AppData\\Roaming\\npm\\node_modules\\{pkg}\\dist\\{entry}.js"],
     "env": {}
   }
   ```
4. **驗證**：Reload VSCode window → 確認 MCP servers 面板顯示為 "User" scope + "Connected"

### 禁止事項

- [固] **禁用 npx 啟動**：VSCode 擴充環境 spawn `.cmd` 批次檔失敗
- [固] **禁止相對路徑**：一律用絕對路徑
- [固] **安裝後必驗證**：不能只寫設定就結束，要確認 server 啟動成功

## 行動

- 收到「安裝 MCP」「新增 MCP」「加 skill」等請求 → 自動遵循本規則，不需使用者提醒
- 安裝完成後主動提醒使用者 reload window 驗證
- 若使用者指定「只給某專案用」→ 才寫入專案層 `.mcp.json`，否則一律全域
- 記錄新安裝的 MCP/Skill 到 toolchain atom

