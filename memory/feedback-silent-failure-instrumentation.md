# feedback silent failure instrumentation

- Scope: global
- Author: holylight
- Confidence: [臨]
- Trigger: silent failure, probe burst, log 採樣, observation log, hook 鏈觀察, always-loaded, fallback 未覺察, 灰色地帶
- Last-used: 2026-04-29
- Confirmations: 0
- ReadHits: 7
- Created-at: 2026-04-28
- Related: feedback-bg-subprocess-stderr, feedback-no-plan-bound-hook, feedback-end-to-end-smoke

## 知識

- [臨] 牍涉 silent-failure 風險的 stage（hook 鏈 / always-loaded 入口 / bg subprocess / 跨 session 才浮現的問題 / 觀察期 ≥ 4 天）動工前必須先鋪 log 採樣 + probe burst，不可依賴「使用者主訴」或「自然累積使用資料」
- [臨] log schema 至少含 {ts, session_id, fn, flag_state, result_count, fallback_used}，寫到 ~/.claude/Logs/<subsystem>-observation.log；必須轉 tools/<subsystem>-observation-summary.py 自動判定（修活 / 淘汰 / 灰色），灰色門檻 5–15% 才詢問使用者
- [臨] probe burst：遇到「4 天觀察期」或「使用者計畫量不足」的場景，寫一個同一 session 能立即跑完的 batch query 工具（50–100 個典型 query、分高/中/低機率三類），走完整管線而非直接打 service，以加速累積 log
- [臨] Why：2026-04 vector silent failure 12 天不被察覺並非偶然 — 計畫 v2.1 原本寫「D4 觀察 4 天」依賴使用者主訴，但 silent failure 本身不可觀察；Wave 3a 重設計為「probe burst + log 自動判定」才能邏輯上關閉這類 blind spot
- [臨] How：動工前 dry-run 必須明寫 (a) 這個 stage 是否牍涉 silent-failure 4 條件件？(b) log 鋪設點在哪？(c) summary 判定門檻？(d) probe burst 計畫？分類各樣本數？— 四項任何一項空白則不能進入「動工」階段

## 行動

- dry-run 表格必含「silent-failure 4 條件件」勾選 + log 鋪設計畫 + probe burst 計畫
- 動 hook 鏈或 always-loaded atom 裁剪前必須先出 observation log + summary tool
