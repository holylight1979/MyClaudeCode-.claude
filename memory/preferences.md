# 使用者偏好

- Scope: global
- Confidence: [固]
- Trigger: 偏好, 風格, 習慣, style, preference, 語言, 回應
- Last-used: 2026-03-11
- Confirmations: 29
- Type: preference

## 知識

- 回應語言: 繁體中文，技術術語可英文
- 程式風格: 輕量極簡，不做多餘抽象，三行重複優於過早抽象
- 可讀性: 一個檔案看完相關邏輯，減少跨檔跳轉
- 框架觀: 薄框架，開發者要能理解底層運作
- 文件: 不主動產生 README/文件，除非明確要求
- Prompt 輸出: 給使用者複製貼上的 prompt 一律包在 code block 裡
- 「上 GIT」: 等同 git add + commit + push（三步都做完）
- 大型計畫執行: 分階段 session 執行，每階段完成+驗證+上傳GIT後，提供下一階段的 prompt 給使用者

## 行動

- 回應用繁體中文
- 程式碼修改保持最小變動範圍
- 不加多餘 docstring / type annotation / 註解
- 不主動重構周圍程式碼
- 大型任務自動拆分為多個 session 階段，每階段結束提供延續 prompt
