# 測試/新手作業禁止上傳 SVN

- Scope: global
- Confidence: [固]
- Trigger: 上SVN, svn commit, 測試碼不上傳, 新手作業, 不可上傳
- Last-used: 2026-04-28
- Confirmations: 0
- ReadHits: 15

- Related: feedback-pre-completion-test-discipline

## 知識

- [固] 測試用、新手作業、練習用途的程式碼不可以上傳 SVN repo（除非使用者明確指示特定檔案、指定要上傳）
- [固] r10854 教訓：誤上傳 WndForm_UITutorial（新手作業 S2）+ ClaudeEditorHelper 後被使用者退版

**Why:** 使用者明確糾正，測試用檔案不應進入版控。

**How to apply:** 執行「上GIT」/「上SVN」前，判斷異動檔案是否屬於測試/練習/新手作業性質。如果是 → 不加入 svn add，或向使用者確認哪些可以上。ClaudeEditorHelper.cs 等工具類是否可上傳也需確認。

## 行動

- 執行同步前，檢查異動清單中是否有測試/練習/新手作業檔案
- 可疑檔案不自動加入，先向使用者確認

## 已 hook 化

- Hook: `hooks/wg_pretool_guards.py:check_svn_test_block` (PreToolUse Bash, 2026-04-28)
- 偵測條件：command 同時含 `svn (commit|ci)` 與（`tests?/`、`__tests__/`、或 `*Test.{cs,py,js,ts,tsx,jsx,go,java}`）
- 動作：deny + 訊息指回本檔；繞過方法（指定單檔不用 glob / 使用者明確指示）也寫在 deny 訊息內
- 本 atom 仍保留：r10854 教訓敘事 + LLM 提示錨點

