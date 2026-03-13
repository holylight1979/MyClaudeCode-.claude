# 失敗模式記憶

- Scope: global
- Confidence: [固]
- Trigger: 失敗, 錯誤, debug, 踩坑, pitfall, crash, 重試, retry, workaround
- Last-used: 2026-03-12
- Confirmations: 14
- Type: procedural
- Tags: failure, pitfall, debug, quality-feedback
- Related: decisions, toolchain

## 知識

### 環境踩坑（Environment Trap）

（記錄格式：{觸發條件} → {錯誤行為} → {正確做法}（根因: {root cause}））

- [固] Windows bash 的 `find` 輸出路徑含反斜線 → 管道到其他工具時路徑解析失敗 → 改用 Glob/Grep 工具或 `//` 正斜線（根因: MSYS2 路徑轉換不一致）
- [固] ChromaDB 在 i7-3770 上 import 失敗 → 誤以為安裝問題反覆重裝 → 確認 CPU 不支援 AVX2 後改用 SQLite backend（根因: LanceDB/ChromaDB 預設需要 AVX2 指令集）
- [觀] Windows Node.js `rmSync()` 對 CJK 檔名靜默失敗（不報錯但不刪除）→ 以為刪除成功 → 改用 `unlinkSync()`（根因: rmSync 內部路徑處理與 NTFS CJK 字元不相容）
- [臨] MCP `Ctrl+Shift+Escape` 被安全機制擋住（"dangerous key combination"）→ 改用 Command Palette 輸入指令名稱（根因: Ctrl+Shift+Escape 是 Windows Task Manager 快捷鍵，MCP 禁止觸發系統功能）
- [臨] VS Code "Open in New Tab" 開 Claude Code 會與側邊欄 CHAT 面板搶焦點 → 點擊/貼上操作進入錯誤面板 → 截圖確認焦點位置 + 點擊新 tab 標題切換焦點後重試（根因: 同視窗兩個 webview 輸入框座標重疊）
- [臨] "Claude Code: Open in New Tab" 的快捷鍵 `Ctrl+Shift+Esc` 與 Windows Task Manager 衝突 → 用 Command Palette 輸入指令名稱代替快捷鍵（根因: VS Code 預設快捷鍵與 Windows 系統快捷鍵重疊）
- [臨] 舊 MCP server process 佔住 port 3848 → 新 Guardian routes/cleanup 全不生效 → 先殺舊 process，heartbeat 15s 內自動 rebind（根因: process 未正常退出時 port 不釋放）
- [固] MCP server 設定用 `npx.cmd` 在 VSCode 子進程中啟動失敗（`cmd /c npx` 也不行）→ 全域安裝套件後改用 `node.exe` 直接跑 `.js` 入口點（根因: VSCode extension 環境 spawn `.cmd` 批次檔失敗；解法: `npm install -g <pkg>` → 找 package.json `bin` 欄位對應的 .js → 用 `node.exe <path>.js` 替代 npx）

### Playwright + Google 踩坑

- [觀] Playwright Chromium 無法登入 Google → Google 偵測 `--enable-automation` 旗標 → 用 `channel="chrome"` + `--disable-blink-features=AutomationControlled`（根因: Google 反自動化偵測）
- [觀] `context.request.get()` 不帶 browser cookies → export URL 回 401 → 改用 `context.cookies()` 同步到 aiohttp（根因: Playwright API request 獨立於 browser cookie store）
- [觀] `page.evaluate` + `fetch()` 對 Google export URL 被 CORS 擋 → export URL redirect 跨域 → 改用 aiohttp server-side 請求（根因: browser fetch 無法跨域 follow Google CDN redirect）
- [觀] `page.goto()` Google export URL 觸發 download 而非頁面渲染 → Playwright 報 "Download is starting" → 需 `accept_downloads=True` + `expect_download()`（根因: export URL 回 Content-Disposition: attachment）

### 假設錯誤（Wrong Assumption）

（記錄格式：{假設內容} → {實際情況}（發現於: {context}））

（尚無記錄，使用中累積）

### 模式誤用（Pattern Misapplication）

（記錄格式：{套用的模式} → {為什麼不適用}（應改用: {correct approach}））

（尚無記錄，使用中累積）

### 生成品質回饋（Output Quality Feedback）

（記錄格式：{生成內容描述} → {被重寫/修正的部分} → {重寫原因}（品質訊號: −））

（尚無記錄，使用中累積）

## 行動

- debug 超過 5 分鐘時，先檢查此 atom 是否有已知模式匹配，避免重複踩坑
- 使用者糾正行為時，記錄到對應分類（環境踩坑 / 假設錯誤 / 模式誤用）
- 工具呼叫失敗後重試成功時，評估是否值得記錄（可重現性 + 影響面）
- 發現正在大幅修改前 session 生成的程式碼（>30% 變動）時，記錄到「生成品質回饋」
- 新增記錄前，先向量搜尋是否有相似的既有記錄（dedup）
- 遇到相似情境時，回應中簡短提醒已知陷阱
- 每條記錄初始為 [臨]，跨 2+ sessions 確認後晉升 [觀]

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-10 | 初始建立：四大分類（環境踩坑/假設錯誤/模式誤用/品質回饋）+ 2 條已知踩坑 | manual |
| 2026-03-10 | [觀]→[固] 晉升（Confirmations=6）+ 新增 rmSync CJK 踩坑 | atomic-memory E2E |
