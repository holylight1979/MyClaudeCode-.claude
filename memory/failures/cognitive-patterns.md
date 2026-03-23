# 認知模式偏差（Cognitive Patterns）

- Scope: global
- Confidence: [固]
- Type: procedural
- Trigger: 過度工程, 代理指標, proxy metric, 看不懂, 在打轉, 口水, 品質回饋
- Last-used: 2026-03-19
- Created: 2026-03-13
- Confirmations: 36
- Tags: failure, cognitive, quality
- Related: decisions

## 知識

### 模式誤用（Pattern Misapplication）

（格式：想測量 X → 錯誤代理指標 → 更好的指標）

- [觀] 想測量「任務複雜度」→ 用修改檔案數量當 proxy → 應改用語意層判斷（如 Wisdom classify_situation 的 approach 結果），因為數量不反映複雜度（重命名跨 6 檔 ≠ 架構任務）

### 生成品質回饋（Output Quality Feedback）

（格式：使用者的反應 → AI 做錯了什麼 → 下次該怎麼做）

- [觀] 使用者說「看不懂」「在打轉」→ AI 反覆陳述結論（think=False 會失敗）卻沒交代因果鏈（為什麼是 False、誰在呼叫、哪個檔案才是真正在跑的）→ 下次診斷問題時，先用一句話說清「誰呼叫誰」的完整路徑，再說結論

## 行動

- 發現正在大幅修改前 session 生成的程式碼（>30% 變動）時，記錄到品質回饋
- 使用代理指標前，先確認它真的能代表要測量的東西

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-13 | 初始建立 | 萃取管線診斷 session |
| 2026-03-19 | 從 failures.md 合併模式誤用+品質回饋為獨立 atom | 系統精修 |
