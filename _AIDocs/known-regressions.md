# 已知 Regression 清單

> 用途：記錄已偵測但暫不修的 regression / 失效測試，附「檢測時點 + 根因 + 不修的實際風險 + 修補路徑」，避免每個 session 重新調查。

---

## REG-001 · `test_v4_atoms_unchanged` 基準漂移 ✅ RESOLVED 2026-04-27

| 欄位 | 內容 |
|------|------|
| 檔案 | ~~`tests/regression/test_v4_atoms_unchanged.py`~~（已刪除） |
| 首次偵測 | 2026-04-27（Sprint 2 收尾跑全套 pytest 時觸發 TestFailGate） |
| 範圍 | 9 atom 檔的 SHA256 與 `tests/fixtures/v4_atoms_baseline.jsonl` 不符 |
| 處理決策 | **選項 2 退役測試**（管理職 2026-04-27 拍板）——理由：V4.1 GA 整合期已結束、現有 `atom_write` MCP + write_gate + auto-pending + 三時段衝突偵測已涵蓋未授權漂移防護，多一層 SHA256 baseline 屬過度防禦 |
| 處理動作 | 刪除 `tests/regression/test_v4_atoms_unchanged.py` + `tests/fixtures/v4_atoms_baseline.jsonl`；保留 `tools/snapshot-v4-atoms.py`（未來若要重建 baseline 可用） |

### 不符清單

```
memory/decisions.md
memory/feedback/feedback-fix-on-discovery.md
memory/feedback/feedback-git-log-chinese.md
memory/feedback/feedback-research-first.md
memory/preferences.md
memory/workflow-icld.md
memory/workflow-rules.md
memory/workflow-svn.md
c:\Projects\.claude\memory\architecture.md
```

### 根因（已查證）

- 該測試從 V4.1 GA cut-over 時固化 baseline，目的是「確保 V4.1 整合過程不修改既有 V4 atom」
- V4.1 GA 完成後（commit `522dc6c0` 前後）atom 已合法演進：
  - `22d9d3b` (2026-04-26)：Codex Companion Phase 1 — atom 索引註冊更新
  - `82c4cfd` (2026-04-24)：v3 雙欄位拆分 — `decisions.md` 補晉升雙軌條目
  - 多次 atom 寫入流程（`atom_write` / `atom_promote` MCP 呼叫）持續累積未 commit 的合法修改
- gitStatus 於 Sprint 2 session 啟動時已顯示這 9 檔為 `M`（早於本 Sprint 任何動作）

### 不修的實際風險

- **零**：snapshot test 是一次性整合保護，V4.1 已 GA。本失敗不阻擋任何運行時功能、不影響 codex companion 行為、不影響 atom 系統正確性
- 風險僅限「TestFailGate 提示噪音」一條

### Sprint 2 是否觸發

- 否。Sprint 2 commit (`fa9897b`) 修改範圍：`tools/codex-companion/heuristics.py`、`hooks/codex_companion.py`、`workflow/config.json`、兩個 test 檔、`_AIDocs/DocIndex-System.md`、`_AIDocs/_CHANGELOG.md`
- 9 個漂移 atom 沒有任何一個被 Sprint 2 commit 觸碰，git diff 可驗證

### 修補路徑（已決議 2026-04-27）

~~擇一~~ → **採選項 2 退役**：

1. ~~重新固化基準~~ —— 缺點：每次合法演進這 9 個 atom 都要重簽 baseline，等同每次寫入 `decisions.md` / `preferences.md` 都要多一道 commit
2. **✅ 退役該測試** —— 已執行：刪 `test_v4_atoms_unchanged.py` + `v4_atoms_baseline.jsonl`
3. ~~xfail 標記~~ —— 缺點：每次 pytest 看到 `1 xfailed` 雜訊永遠在

備註：本檔由 Sprint 2 收尾時建立，於 Sprint 3 開頭由管理職拍板退役。
