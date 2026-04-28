# V4.2 候選議題（非當前 session 範圍）

> 來源：Session F Sub-task B Agent 多 Role 模擬（20 條 role-grounded prompts）
> L0 Precision=1.00 / Recall=0.40 — 五類中文決策語氣有系統性漏抓

## L0 補強候選

| 類別 | 樣例 | 現狀 | 建議 |
|------|------|------|------|
| 習慣類 | 「我習慣用 X」「我一直都是…」 | 未觸發 L0 | 補「習慣」關鍵詞 + 人稱代詞 pattern |
| 只能類 | 「只能用 X」「不得不用…」 | 未觸發 | 補「只能／不得不／必須」combo |
| 數值邊界 | 「至少 N」「至多 M」「不超過 K」 | 未觸發 | 數值邊界短語表 |
| 程序性 | 「每次…」「每個…」「每當…」 | 未觸發 | 頻率副詞 pattern |
| 婉轉類 | 「盡量」「基本上」「原則上」 | 未觸發 | 語氣副詞 pattern（注意避免 false positive） |

## 其他候選

- session_scores[] 回填機制：用 score ≥ threshold 篩選歷史 session 二次萃取
- `/memory-session-score --stats` 彙總維度分布

## 優先序建議

建議 V4.2 至少完成 L0 五類補強 + precision 驗證（新增負例測試避免 FP 飆升）。
