# USER.md - 操作者是誰

> 由 CLAUDE.md @import 自動載入。每位團隊成員維護自己的版本。

## 使用者的基本資料

* **帳號**：holylight
* **平台**：Windows 11 Pro；shell 環境：MSYS2 bash & POWERSHELL

## V4 多職務模式（團隊共享記憶）

* **當前職務**：programmer + management（雙重宣告：personal `role.md` + shared `_roles.md` 白名單）
* **記憶分層**：`global`（個人）/ `shared`（團隊全員可見）/ `role`（同職務可見）/ `personal/{user}`（只自己）
* **帳號切換**：`CLAUDE_USER` 環境變數（team collaborator 在同機測試用）
* **管理職特權**：裁決 `shared/_pending_review/` 的敏感原子（architecture/decision）與 pull-audit 衝突報告，其他 user 只能提交草稿

## 使用者的溝通偏好

* **回應語言**：繁體中文（技術術語可英文）
* **輕量極簡**：偏好直接、低抽象的解法，不用不需要的框架
* **高可讀性**：一個檔案看完相關邏輯，減少跨檔跳轉
* **不自動產生文件**：不主動建立 README / 文件，除非明確要求
* **Prompt 輸出**：給使用者複製貼上的 prompt，一律包在 code block 裡
* **縮寫指令**：「上GIT」「執P」等定義見 `memory/preferences.md`

## 使用者的決策偏好

* 需要決策時：**詳細綜觀 + 分析條列 + 建議優選**
* 大型計畫：分階段 session 執行，每階段完成 + 驗證 + 上傳 GIT 後，提供下一階段 prompt
