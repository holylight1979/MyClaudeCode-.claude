# 使用者偏好（補充）

- Scope: global
- Confidence: [固]
- Trigger: 偏好, 風格, 習慣, 語言, 回應, 執P, 執驗上P, 上GIT
- Last-used: 2026-04-16
- Confirmations: 138
- Type: preference

- Related: feedback-decision-no-tech-menu, feedback-no-outsource-rigor

## 知識

> 核心偏好已在 USER.md / IDENTITY.md 必載，此處僅放延伸補充。

- 框架觀: 薄框架，開發者要能理解底層運作
- 「執驗上P」/「執P」: 縮寫指令，等同「由 AI 考量拆分 session 接續處理，單一階段執行完畢，且驗證無誤後，上傳 GIT（如有可上傳的 repo），再給使用者下一階段接續用的 prompt；此規則延伸到本項目全數完成」
- 「上GIT」/「上傳GIT」: 縮寫指令，針對當次批量作業（單一或多 session）所異動的範圍內容執行 git add + commit + push。若沒有當次異動，須向使用者確認是否要查詢所有異動來執行。若專案屬於 SVN，則此縮寫也代表 commit 到 SVN repo，完成後主動向使用者報備「已上傳 SVN repo」。
- [固] 專案知識庫深度運用: 處理專案程式邏輯、架構、結構、踩坑經驗等，都要系統性記錄到專案 _AIDocs 內（不重複前提下）；同時確保寫入向量記憶庫供後續語意檢索。目標：專案知識被智慧儲存→精準注入→高效協助

## 行動

- 處理專案程式碼後，將邏輯/架構/結構/經驗寫入 _AIDocs（去重）+ 向量記憶庫，確保知識可被檢索與注入
