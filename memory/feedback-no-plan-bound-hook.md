# feedback no plan bound hook

- Scope: global
- Author: holylight
- Confidence: [臨]
- Trigger: SessionStart hook, 硬編碼 plan, phase6, wg_codex_companion_phase6, 寫死綁定, hook 反模式, plan 路徑寫死
- Last-used: 2026-04-28
- Confirmations: 0
- ReadHits: 0
- Created-at: 2026-04-28
- Related: decisions-architecture, feedback-fix-on-discovery, feedback-bg-subprocess-stderr, feedback-silent-failure-instrumentation

## 知識

- [臨] SessionStart 級別的 hook 嚴禁把特定 plan/階段路徑（例：plans/<某計畫>/、phaseN-only flag）寫死在程式裡。這類 hook 一旦該 plan 結案就變成永久 dead code，並且每次啟動都還在執行無意義邏輯（例：wg_codex_companion_phase6.py 在 phase6 結束後仍隨 SessionStart 跑）
- [臨] Why：2026-04 memory cleanup 發現 wg_codex_companion_phase6 在 phase 結束後沒人記得拆，hook 鏈拖一年沒清；plan 路徑寫死讓拆除成本高（要先確認沒有副作用），最後變成「不敢動」
- [臨] How：(a) 任何 SessionStart / Stop / PreCompact 等 always-on hook，trigger 條件不准包含「特定 plan 名稱、特定 phase 編號、特定 session ID」 (b) 若真的需要階段性行為，用 settings.json 旗標或 atom 條件式啟用，不要寫進 .py 邏輯 (c) plan 結束時的 collateral cleanup 必須含「拆 hook」清單

## 行動

- 新建 SessionStart 類 hook 前先自問：這段邏輯是否綁定特定 plan？是 → 改用條件式 trigger 或 settings.json 旗標
- review 既有 hook 鏈時，發現名字含 phaseN / plan-XXX / session-YYY 即列為待拆候選
