# 失敗模式記憶

- Scope: global
- Confidence: [固]
- Trigger: 失敗, 錯誤, debug, 踩坑, pitfall, crash, 重試, retry, workaround
- Last-used: 2026-03-13
- Confirmations: 15
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

### Ollama / Open WebUI 踩坑

- [觀] qwen3/3.5 的 /api/generate thinking mode 會把所有 token 花在 thinking 欄位，response 永遠為空 → 改用 /api/chat + `think: false`（根因: Ollama 0.17+ 預設啟用 thinking mode，/api/generate 不支援 think 參數）
- [觀] Ollama `format: "json"` 與 thinking mode 衝突 → constrained decoding 限制 thinking tokens 輸出格式，JSON 從未產生 → 移除 format，改用 prompt 引導 + regex 解析（根因: JSON constrained decoding 套用到 thinking output，不是 final response）
- [觀] Open WebUI proxy 不轉發 /api/embed → "Model not found" → 改走 OpenAI-compatible /api/v1/embeddings（根路徑，不經 /ollama/ proxy）（根因: OWU proxy 只轉 generate/chat/tags 等端點）
- [觀] Open WebUI /api/v1/embeddings 的 model 名稱須含完整 tag（`:latest`）→ 省略 tag 回 500 Internal Server Error → config 中寫完整 tag（根因: OWU OpenAI-compat 層 model routing 嚴格匹配）
- [觀] LDAP 認證端點誤用 /api/v1/auths/signin（帳密登入）→ 400 → 正確端點是 /api/v1/auths/ldap，payload 用 `user` 欄位非 `email`（根因: Open WebUI 帳密登入和 LDAP 登入是不同端點）
- [觀] failover 時 payload 的 model 名稱沒跟著切換 → 用 rdchat 的 model 打 local → 404 → _request_with_failover 需按 backend 動態換 model（根因: payload 在首次 backend 選定時建立，failover 重用同一 payload）

### 假設錯誤（Wrong Assumption）

（格式：觸發情境 → 直覺假設 → 正確做法）

- [臨] 調查某功能為何沒生效 → 直覺假設「獨立檔案一定有被呼叫」→ 正確做法：先 grep 呼叫端確認是否真的有 import/spawn，再看被呼叫端的邏輯（案例：extract-worker.py 存在但 guardian 從未呼叫它）
- [臨] 看到某目錄是空的 → 直覺假設「資料被清理了」→ 正確做法：先查資料的存放路徑邏輯，確認是存到別的位置還是真的沒生成（案例：episodic 依 CWD 存到 project 層，全域層空是正常的）
- [臨] 看到 metrics 數值異常 → 直覺假設「那個功能有問題」→ 正確做法：先驗證 metrics 的計算邏輯本身是否正確、是否真的有在跑（案例：architecture 0/6 的分類邏輯是「檔案 > 4 個就算」，跟真正架構無關）

### 靜默失敗（Silent Failure）

（格式：你以為正常的現象 → 該警覺的信號 → 驗證方式）

- [臨] 某個 JSON 結構升級後，用 `setdefault()` 讀取舊檔案 → **信號：舊檔的 key 與新 code 的 key 不一致，setdefault 拿到舊結構不報錯但後續 KeyError 被 try/except 吞掉** → 驗證：直接 `python -c` 單獨呼叫該函數，不經外層 try/except（案例：wisdom reflect() 的 silence_accuracy key 遷移漏了）
- [臨] episodic atom 有生成但「知識」段只有 metadata 沒有萃取項目 → **信號：knowledge_queue 永遠是空的** → 驗證：在 SessionEnd state JSON 裡檢查 knowledge_queue 長度，為 0 代表 LLM 萃取失敗或沒被正確呼叫

### 模式誤用（Pattern Misapplication）

（格式：想測量 X → 錯誤代理指標 → 更好的指標）

- [臨] 想測量「任務複雜度」→ 用修改檔案數量當 proxy → 應改用語意層判斷（如 Wisdom classify_situation 的 approach 結果），因為數量不反映複雜度（重命名跨 6 檔 ≠ 架構任務）

### 生成品質回饋（Output Quality Feedback）

（格式：使用者的反應 → AI 做錯了什麼 → 下次該怎麼做）

- [臨] 使用者說「看不懂」「在打轉」→ AI 反覆陳述結論（think=False 會失敗）卻沒交代因果鏈（為什麼是 False、誰在呼叫、哪個檔案才是真正在跑的）→ 下次診斷問題時，先用一句話說清「誰呼叫誰」的完整路徑，再說結論

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
| 2026-03-13 | 新增：假設錯誤 3 條 + 靜默失敗 2 條 + 模式誤用 1 條 + 品質回饋 1 條 | 萃取管線診斷 session |
