# feedback-research — 試錯門檻與搜尋策略

- Scope: global
- Confidence: [固]
- Trigger: 試錯, trial-and-error, 不熟悉, API試錯, 框架不熟, 搜尋策略, research
- Last-used: 2026-04-10
- Confirmations: 22

## 知識

- [固] 修復同一技術問題連續失敗時，必須主動搜尋網路知識來驗證/推翻推論
- [固] 有使用者共同開發/測試：修復失敗 ≥2 次 → 主動詢問是否搜尋網路
- [固] 獨立作業（無即時測試回饋）：修復失敗 ≥3 次 → 直接搜尋，不需再問
- [固] 搜尋策略：多角度（≥3 個不同 query），查官方文件 + GitHub issues + Stack Overflow
- [固] 查到後再決定方案，不靠猜測寫 code → 跑 → 失敗 → 改的循環

## 行動

- 修復失敗計數器：每次 fix 後測試仍失敗 → +1，成功 → 歸零
- 達門檻 → 多角度搜尋（≥3 query），特別是第三方工具的邊界行為
- 碰到框架/API 行為不如預期 → 先 WebSearch 再動手
