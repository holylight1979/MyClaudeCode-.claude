# 使用者偏好（補充）

- Scope: global
- Confidence: [固]
- Trigger: 偏好, 風格, 習慣, 語言, 回應, 執P, 執驗上P, 上GIT
- Last-used: 2026-04-27
- Confirmations: 0
- ReadHits: 157
- Type: preference

- Related: feedback-decision-no-tech-menu, feedback-no-outsource-rigor, feedback-git-log-chinese, feedback-fix-on-discovery, feedback-humanist-decision-framing

## 知識

> 核心偏好已在 USER.md / IDENTITY.md 必載，此處僅放延伸補充。

- 框架觀: 薄框架，開發者要能理解底層運作
- 「執驗上P」/「執P」: 縮寫指令，等同「由 AI 考量拆分 session 接續處理，單一階段執行完畢，且驗證無誤後，上傳 GIT（如有可上傳的 repo），再給使用者下一階段接續用的 prompt；此規則延伸到本項目全數完成」
- 「上GIT」/「上傳GIT」: 縮寫指令，針對當次批量作業（單一或多 session）所異動的範圍內容執行 git add + commit + push。若沒有當次異動，須向使用者確認是否要查詢所有異動來執行。若專案屬於 SVN，則此縮寫也代表 commit 到 SVN repo，完成後主動向使用者報備「已上傳 SVN repo」。
- [固] 專案知識庫深度運用: 處理專案程式邏輯、架構、結構、踩坑經驗等，都要系統性記錄到專案 _AIDocs 內（不重複前提下）；同時確保寫入向量記憶庫供後續語意檢索。目標：專案知識被智慧儲存→精準注入→高效協助
- [固] OpenAI 訂閱方案: ChatGPT Pro（截圖 2026-04-27 確認：Plus 20 倍用量、Codex 最大存取權、前沿 Pro 模型）。**Codex/Codex Companion 相關設計決策不需考量 token 帳單成本維度**，只考量干擾度（advisory inject 打斷）、漏審查風險、執行時延。Score gate / dedup 等機制傾向「多打不會少打」優先收集數據。

## 行動

- 處理專案程式碼後，將邏輯/架構/結構/經驗寫入 _AIDocs（去重）+ 向量記憶庫，確保知識可被檢索與注入
