# feedback fix on discovery

- Scope: global
- Author: holylight
- Confidence: [臨]
- Trigger: 不在範圍, 範圍外, 未來處理, 另開 session, out of scope, 順手發現, 不在本次範圍
- Last-used: 2026-05-04
- Confirmations: 0
- ReadHits: 8
- Created-at: 2026-04-16
- Related: feedback-handoff-self-sufficient, workflow-rules, preferences, feedback-end-to-end-smoke, feedback-pre-completion-test-discipline, feedback-no-plan-bound-hook

## 知識

- [臨] 任務途中發現的不一致/錯誤/drift（版本號殘留、章節標題過時、文件與代碼不符），1-3 行能修就**當場立刻修**，不寫「不在本 handoff 範圍 → 留給未來 session」的退避說法
- [臨] 預設「沒有其他 handoff 會被記下來處理」。使用者很可能不會另開 session 處理這條尾巴；丟到未來等於丟掉
- [臨] 真的超出能力範圍（要動架構/要改 .py/影響面大）才另開 handoff prompt + `_staging/` 留檔；只是「文字修正/標題對齊/路徑更新」這類不要逃避
- [臨] Why：使用者 2026-04-16 README/TECH refactor session 明確指正「請記住呀，發現了就要立即改正，你要預設沒有其他 handoff 會被記下來處理呀」。起因是把 Architecture.md L79 標題仍寫 V3.4 列為「不在本 handoff 範圍」想留給未來
- [臨] How：每完成 task 段落收尾前複检「順手發現但未處理」項目；報告不講「不在本 handoff 範圍」當推卸理由，講「已順手修補：A、B」或「以下需另開 session：X（理由：超出能力 Y）」

## 行動

- 新發現 drift 先判斷修補成本：≤5 行 / 不影響架構 → 當場修
- 需另開 session 的明確列理由，不只是「不在範圍」
