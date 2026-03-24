# 環境踩坑（Environment Trap）

- Scope: global
- Confidence: [固]
- Type: procedural
- Trigger: 環境, Windows, MSYS2, Node.js, npx, Ollama, thinking, port, MCP啟動, VSCode
- Last-used: 2026-03-23
- Created: 2026-03-10
- Confirmations: 43
- Tags: failure, environment, pitfall
- Related: toolchain

## 知識

（記錄格式：{觸發條件} → {錯誤行為} → {正確做法}（根因: {root cause}））

### Windows / MSYS2

- [固] Windows bash 的 `find` 輸出路徑含反斜線 → 管道到其他工具時路徑解析失敗 → 改用 Glob/Grep 工具或 `//` 正斜線（根因: MSYS2 路徑轉換不一致）
- [固] ChromaDB 在 i7-3770 上 import 失敗 → 誤以為安裝問題反覆重裝 → 確認 CPU 不支援 AVX2 後改用 SQLite backend（根因: LanceDB/ChromaDB 預設需要 AVX2 指令集）
- [固] Windows Node.js `rmSync()` 對 CJK 檔名靜默失敗（不報錯但不刪除）→ 以為刪除成功 → 改用 `unlinkSync()`（根因: rmSync 內部路徑處理與 NTFS CJK 字元不相容）

### VSCode / MCP

- [固] "Claude Code: Open in New Tab" 的 `Ctrl+Shift+Esc` 與 Windows Task Manager 衝突 + MCP 安全機制擋住 → 改用 Command Palette 輸入指令名稱（根因: VS Code 快捷鍵與 Windows 系統快捷鍵重疊）
- [固] VS Code "Open in New Tab" 開 Claude Code 會與側邊欄 CHAT 面板搶焦點 → 點擊/貼上操作進入錯誤面板 → 截圖確認焦點位置 + 點擊新 tab 標題切換焦點後重試（根因: 同視窗兩個 webview 輸入框座標重疊）
- [固] 舊 MCP server process 佔住 port 3848 → 新 Guardian routes/cleanup 全不生效 → 先殺舊 process，heartbeat 15s 內自動 rebind（根因: process 未正常退出時 port 不釋放）
- [固] MCP server 設定用 `npx.cmd` 在 VSCode 子進程中啟動失敗（`cmd /c npx` 也不行）→ 全域安裝套件後改用 `node.exe` 直接跑 `.js` 入口點（根因: VSCode extension 環境 spawn `.cmd` 批次檔失敗；解法: `npm install -g <pkg>` → 找 package.json `bin` 欄位對應的 .js → 用 `node.exe <path>.js` 替代 npx）

### Ollama / Open WebUI

- [固] qwen3/3.5 的 /api/generate thinking mode 會把所有 token 花在 thinking 欄位，response 永遠為空 → 改用 /api/chat + `think: false`（根因: Ollama 0.17+ 預設啟用 thinking mode，/api/generate 不支援 think 參數）
- [固] Ollama `format: "json"` 與 thinking mode 衝突 → constrained decoding 限制 thinking tokens 輸出格式，JSON 從未產生 → 移除 format，改用 prompt 引導 + regex 解析（根因: JSON constrained decoding 套用到 thinking output，不是 final response）
→ Open WebUI 踩坑（proxy/embed/LDAP/failover）詳見 `toolchain.md`

### Playwright + Google

→ 詳見 `gdoc-harvester.md` 踩坑記錄 #1-#4（Chromium 反自動化、cookie 隔離、CORS、download trigger）

## 行動

- 環境/工具問題 debug 時，優先查此 atom
- 遇到相似情境時，回應中簡短提醒已知陷阱

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-10 | 初始建立 | manual |
| 2026-03-19 | 從 failures.md 拆出為獨立 atom | 系統精修 |
