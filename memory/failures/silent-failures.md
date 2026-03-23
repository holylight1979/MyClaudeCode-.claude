# 靜默失敗（Silent Failure）

- Scope: global
- Confidence: [固]
- Type: procedural
- Trigger: 靜默, silent, 看似正常, setdefault, knowledge_queue為空, 沒報錯但沒動作, 吞掉錯誤
- Last-used: 2026-03-19
- Created: 2026-03-13
- Confirmations: 36
- Tags: failure, silent, debugging
- Related: decisions-architecture

## 知識

（格式：你以為正常的現象 → 該警覺的信號 → 驗證方式）

- [觀] 某個 JSON 結構升級後，用 `setdefault()` 讀取舊檔案 → **信號：舊檔的 key 與新 code 的 key 不一致，setdefault 拿到舊結構不報錯但後續 KeyError 被 try/except 吞掉** → 驗證：直接 `python -c` 單獨呼叫該函數，不經外層 try/except（案例：wisdom reflect() 的 silence_accuracy key 遷移漏了）
- [觀] episodic atom 有生成但「知識」段只有 metadata 沒有萃取項目 → **信號：knowledge_queue 永遠是空的** → 驗證：在 SessionEnd state JSON 裡檢查 knowledge_queue 長度，為 0 代表 LLM 萃取失敗或沒被正確呼叫

## 行動

- 功能「看起來有在跑」但結果不對時，優先查此 atom
- 驗證手段：繞過 try/except 直接呼叫、檢查中間狀態 JSON

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-13 | 初始建立 | 萃取管線診斷 session |
| 2026-03-19 | 從 failures.md 拆出為獨立 atom | 系統精修 |
