# 增量式閉環開發（ICLD）

- Scope: global
- Confidence: [固]
- Type: procedural
- Trigger: ICLD, 閉環, Sprint, 功能拆解, 開發計畫, 大型新功能, 新系統規劃, 規格書
- Created: 2026-03-19
- Tags: workflow, icld, sprint
- Related: workflow-rules, icld-sprint-template

## 知識

> **ICLD** = Incremental Closed-Loop Development（增量式閉環開發）

**適用條件**（滿足 2 項以上 → AI 主動建議）：
1. 預估工期 ≥ 5 天
2. 跨 Client + Server 雙端
3. 涉及 ≥ 3 個獨立子系統
4. 需要新建 ≥ 3 個檔案

**不適用**：單 session 可完成的修改、探索性原型、純重構

**Sprint 結構要素**：
| 要素 | 說明 |
|------|------|
| 目標 | 一句話：這個 Sprint 完成後能做什麼 |
| 包含 Task | 哪些 Task 組進此 Sprint |
| 步驟 | 具體實作步驟（有順序） |
| 通過條件 | Checklist，全勾才算通過 |
| 依賴 | 必須在哪些 Sprint 之後才能開始 |

**Sprint 內流程**：`[拆解] → [實作] → [驗證] → [修 bug] → [確認通過]`，未通過則回到實作

**Sprint 間依賴圖**：允許平行線（如 Server 線 / Client 線），匯合點明確標注

**AI 主動建議規則**：
- [固] 使用者提出功能需求或請求拆解時，AI 評估上述 4 項指標
- [固] 滿足 2+ 項 → 主動建議：「這個功能規模較大（{理由}），建議用 ICLD 閉環模式拆解。要我按 Sprint 模式拆嗎？」
- [固] 使用者拒絕 → 退回 Phase 模式，本次不再提
- [固] 使用者同意 → 自動進入 Plan Mode 進行 Sprint 拆解 → 產出計畫文件（`_AIDocs/plan/Feature_XXX.md`）→ 使用者確認計畫後退出 Plan Mode → 開始 S1 實作
- [固] 每個 Sprint 結束時產出驗證報告 + 下一 Sprint prompt（與「執驗上P」銜接）

**Sprint prompt / 驗證報告模板**：`~/.claude/memory/templates/icld-sprint-template.md`

## 行動

- 功能需求 / 拆解請求 → 先評估規模 → 滿足 ICLD 條件則主動建議
- 使用者拒絕 → 退回 Phase 模式（見 workflow-rules.md）

