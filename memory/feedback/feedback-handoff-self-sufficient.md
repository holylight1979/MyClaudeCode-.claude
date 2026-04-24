# 跨 Session Handoff 自足性

- Scope: global
- Confidence: [固]
- Trigger: 下 session, 續接, 交接, 下次繼續, next-phase, handoff, 下個 claude, resume prompt
- Last-used: 2026-04-17
- Confirmations: 0
- ReadHits: 3
- Related: workflow-rules, feedback-fix-on-discovery

## 知識

- [固] 寫給下 session 的 prompt，讀者是無當前對話脈絡的 Claude
- [固] 必含 6 區塊：【前置脈絡】【已完成+commit】【權威來源(路徑:行號)】【產出位置】【做法】【決策依據】
- [固] 反例：「繼續 X Phase 2」一句話 prompt（FcgiHandler 事件）

**Why:** 一句話 prompt 讓下個 Claude 重做或誤判。
**How:** 主動建議 /handoff；徒手寫時對照 6 區塊補齊。

## 行動

- 偵測 handoff → 建議 /handoff
- 徒手寫 → 對照 6 區塊缺項補齊
