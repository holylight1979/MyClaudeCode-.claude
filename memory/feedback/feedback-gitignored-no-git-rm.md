# feedback-gitignored-no-git-rm

- Scope: global
- Author: holylight
- Confidence: [臨]
- Trigger: git rm failed, gitignored 檔, access.json 清理, 一次性清理, memory cleanup, untracked telemetry, Path.unlink, fs unlink
- Created-at: 2026-05-05
- Related: feedback-memory-path, decisions-architecture

## 知識

- [臨] memory/**/*.access.json 在 .gitignore:55 排除 → 是 untracked telemetry 檔，不在版控
- [臨] 一次性清理 telemetry 旁路檔：用 Path.unlink() + audit log（lib.atom_io._audit_log op=...）而非 git rm（後者必失敗，且本來就無版控軌跡可保留）
- [臨] plan 文件若指定 git ops（git rm / git mv），執行前先 grep .gitignore + git ls-files 驗證 tracked status；ignored 檔走 fs 操作（unlink/rename）

## 行動

- 寫一次性清理腳本前：grep .gitignore + git ls-files 確認檔案 tracked 狀態
- telemetry / access.json / state.json 等本機檔通常 gitignored → 走 Path.unlink/rename + audit log
- atom .md 是 tracked → 走 git rm/git mv 保留版控歷史
