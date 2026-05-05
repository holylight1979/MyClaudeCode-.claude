# feedback clean before build

- Scope: global
- Author: holylight
- Confidence: [臨]
- Trigger: 重構, 清理, 殘骸, 先清後建, 基線, 等價測試
- Created-at: 2026-05-04

## 知識

- [臨] 重構任務遇到既有殘骸不清前不寫新東西。Why: 2026-05-04 Opus Melodic Comet S1 實踐顯示，projects/c--users-holylight--claude/memory/ 含 57 個 P1 雙層 bug 副本與 7 layer 殘骸；殘骸未清前 funnel 等價測試的 baseline 全是雜訊，跑通也沒意義。
- [臨] 「先清後建」順序：(1) dry-run 列殘骸清單給用戶 review (2) 歸檔到 _archive/{date}/ 而非直接 rm（保留 30 天冷儲、可 restore） (3) 跑乾淨 baseline 確認 0 noise (4) 再開始新功能/funnel 接線。
- [臨] 反例：先接 funnel 再清殘骸，funnel pytest 對拍 server.js 時殘骸把 enumerate 結果污染，難以判斷 byte-equivalence 失敗是 funnel 邏輯錯還是殘骸副作用。

## 行動

- 重構/清理任務開工前先 dry-run 列殘骸清單
- 歸檔到 _archive/{date}/ 而非 rm
- 跑乾淨 baseline 才接新邏輯
