# 測試/新手作業禁止上傳 SVN

- Scope: global
- Confidence: [固]
- Trigger: 上SVN, svn commit, 測試碼, 新手作業, 練習, 不可上傳
- Last-used: 2026-04-02
- Confirmations: 6

## 知識

- [固] 測試用、新手作業、練習用途的程式碼不可以上傳 SVN repo（除非使用者明確指示特定檔案、指定要上傳）
- [固] r10854 教訓：誤上傳 WndForm_UITutorial（新手作業 S2）+ ClaudeEditorHelper 後被使用者退版

**Why:** 使用者明確糾正，測試用檔案不應進入版控。

**How to apply:** 執行「上GIT」/「上SVN」前，判斷異動檔案是否屬於測試/練習/新手作業性質。如果是 → 不加入 svn add，或向使用者確認哪些可以上。ClaudeEditorHelper.cs 等工具類是否可上傳也需確認。

## 行動

- 執行同步前，檢查異動清單中是否有測試/練習/新手作業檔案
- 可疑檔案不自動加入，先向使用者確認

