# 靜默失敗（Silent Failure）

- Scope: global
- Confidence: [固]
- Type: procedural
- Trigger: 靜默, silent, 看似正常, setdefault, knowledge_queue為空, 沒報錯但沒動作, 吞掉錯誤
- Last-used: 2026-03-19
- Created: 2026-03-13
- Confirmations: 36
- Tags: failure, silent, debugging
- Related: decisions-architecture, _INDEX

## 知識

（格式：你以為正常的現象 → 該警覺的信號 → 驗證方式）

- [觀] 某個 JSON 結構升級後，用 `setdefault()` 讀取舊檔案 → **信號：舊檔的 key 與新 code 的 key 不一致，setdefault 拿到舊結構不報錯但後續 KeyError 被 try/except 吞掉** → 驗證：直接 `python -c` 單獨呼叫該函數，不經外層 try/except（案例：wisdom reflect() 的 silence_accuracy key 遷移漏了）
- [觀] episodic atom 有生成但「知識」段只有 metadata 沒有萃取項目 → **信號：knowledge_queue 永遠是空的** → 驗證：在 SessionEnd state JSON 裡檢查 knowledge_queue 長度，為 0 代表 LLM 萃取失敗或沒被正確呼叫
- [觀] 用 `mv` 手動搬 atom 檔案跨層（global ↔ project）→ **信號：原全域層的 `_ATOM_INDEX.md` 保留 stale row、其他 atom 的 `Related:` 可能保留失效名稱、dashboard 會回報「斷裂參照」；無報錯但 layer 完整性崩壞** → 驗證：用 `python tools/atom-move.py reconcile <slug> --at <target-memory-root>` 跑一次，有任何 `stale` 或 `down-ref` 輸出即證實殘留。**正確做法：一律用 `atom-move.py move`（自動 mv + 同步 `_ATOM_INDEX`/`MEMORY.md`/inbound refs + 套用 up/down-ref 層序規則），禁止手動 `mv`**（2026-04-23 踩過）

## 行動

- 功能「看起來有在跑」但結果不對時，優先查此 atom
- 驗證手段：繞過 try/except 直接呼叫、檢查中間狀態 JSON

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-13 | 初始建立 | 萃取管線診斷 session |
| 2026-03-19 | 從 failures.md 拆出為獨立 atom | 系統精修 |
| 2026-04-23 | 新增「手動 mv atom 跨層」靜默失敗條目 + atom-move.py 工具 | /memory-health 修復 session |
