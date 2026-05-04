# feedback bg subprocess stderr

- Scope: global
- Author: holylight
- Confidence: [臨]
- Trigger: bg subprocess, fire-and-forget, DEVNULL, ready flag, subprocess Popen, stderr log, silent failure, background 子進程
- Last-used: 2026-04-29
- Confirmations: 0
- ReadHits: 1
- Created-at: 2026-04-28
- Related: feedback-no-plan-bound-hook, decisions-architecture, feedback-silent-failure-instrumentation

## 知識

- [臨] hook / tool 里任何 fire-and-forget 的 bg subprocess（Popen 不等 wait）都不可將 stderr 導向 DEVNULL 後無條件寫 ready flag。正確作法是：stderr 導向 ~/.claude/Logs/<subsystem>-startup.log，並且 ready flag 必須由子進程自己 health-check 成功後才寫入（不是父進程無條件寫）
- [臨] Why：2026-04 發現「vector silent failure 12 天」根因是 workflow-guardian.py:611 路徑寫错使 service 啟動即坍，stderr 被 DEVNULL 吞了，父進程又無條件寫 ready flag，後續 hook 全部依賴這個假陽性 flag 走 vector 路徑→全転 fallback 但無人知
- [臨] How：(a) 寫 subprocess.Popen 時只能 stdout=DEVNULL，stderr 一律導到檔案；stderr=DEVNULL 代碼 review 時直接退件 (b) ready flag 寫入點不能在 spawn 同一行，必須由子進程自己 health-check OK 後才寫 (c) 設計評審時問「如果這個 subprocess 在機器上完全起不來，使用者會看到什麼？」— 若答案是「什麼都看不到」就是設計錯誤

## 行動

- Popen kwargs review checklist：stderr 不可是 DEVNULL；ready flag 不可在父進程無條件寫
- code review 看到 subprocess.Popen + stderr=DEVNULL 模式直接要求修正
