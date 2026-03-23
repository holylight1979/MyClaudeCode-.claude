# 假設錯誤（Wrong Assumption）

- Scope: global
- Confidence: [固]
- Type: procedural
- Trigger: 假設, 直覺, 調查, 為何沒生效, 空目錄, metrics異常, 功能沒反應
- Last-used: 2026-03-19
- Created: 2026-03-13
- Confirmations: 35
- Tags: failure, assumption, debugging
- Related: decisions

## 知識

（格式：觸發情境 → 直覺假設 → 正確做法）

- [觀] 調查某功能為何沒生效 → 直覺假設「獨立檔案一定有被呼叫」→ 正確做法：先 grep 呼叫端確認是否真的有 import/spawn，再看被呼叫端的邏輯（案例：extract-worker.py 存在但 guardian 從未呼叫它）
- [觀] 看到某目錄是空的 → 直覺假設「資料被清理了」→ 正確做法：先查資料的存放路徑邏輯，確認是存到別的位置還是真的沒生成（案例：episodic 依 CWD 存到 project 層，全域層空是正常的）
- [觀] 看到 metrics 數值異常 → 直覺假設「那個功能有問題」→ 正確做法：先驗證 metrics 的計算邏輯本身是否正確、是否真的有在跑（案例：architecture 0/6 的分類邏輯是「檔案 > 4 個就算」，跟真正架構無關）

## 行動

- 調查問題時，先確認「呼叫鏈是否真的連通」再看邏輯
- 遇到「空/異常」先查資料流向，不假設原因

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-13 | 初始建立 | 萃取管線診斷 session |
| 2026-03-19 | 從 failures.md 拆出為獨立 atom | 系統精修 |
