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

---

## REG-002 · `codex_companion` Silent Advisory Mode 重構後 10 測試失敗

| 欄位 | 內容 |
|------|------|
| 首次偵測 | 2026-04-28 Wave 4a Stage E 收尾跑全 pytest 時觸發 TestFailGate |
| 引入 commit | `7794f65` `refactor(companion): Silent Advisory Mode — 軟閘改後台觀測，不打擾對話` |
| 失敗範圍 | 10 項：`tests/test_codex_companion_drain_e2e.py`（5）+ `tests/test_codex_companion_stop_e2e.py`（1）+ `tests/test_heuristics.py`（4） |
| 與 Wave 4a 因果 | **無**。已用 `git stash` 在 Wave 4a 改動前後跑同樣 pytest 子集合，10 failures 完全相同（前後皆 10 failed / 21 passed）|

### 失敗清單

```
tests/test_codex_companion_drain_e2e.py::test_drain_delivery_inject_emits_with_confidence_label
tests/test_codex_companion_drain_e2e.py::test_drain_orders_by_turn_index_when_multiple_pending
tests/test_codex_companion_drain_e2e.py::test_stop_hook_dedups_when_assessment_for_turn_already_exists
tests/test_codex_companion_drain_e2e.py::test_drain_notify_next_turn_prepends_reminder
tests/test_codex_companion_drain_e2e.py::test_drain_no_reminder_when_notify_absent
tests/test_codex_companion_stop_e2e.py::test_stop_hook_blocks_on_confident_completion_without_evidence
tests/test_heuristics.py::test_sprint1_lesson_tail_has_verify_narrative_no_block
tests/test_heuristics.py::test_state_change_via_modified_files_when_trace_empty
tests/test_heuristics.py::test_missing_verification_is_low_only
tests/test_heuristics.py::test_max_severity_high_only_from_confident_completion
```

### 根因（待修補時驗證）

- `7794f65` 為 codex_companion 行為重構（軟閘改後台觀測，不打擾對話）
- 既有 e2e/heuristic 測試的期望（drain 行為、Stop hook 阻擋、heuristics severity）未同步更新
- 屬「重構未同步測試」類別，非邏輯回歸

### 不修的實際風險

- **線上行為零影響**：codex_companion runtime 由 commit 7794f65 起運作於新模式（Silent Advisory），未被測試覆蓋的新行為已實際使用 8 commits（截至 Wave 4a）
- **漏洞風險低**：失敗測試驗的是「舊行為仍存在」，新行為的正確性需新測試補足，但功能性 smoke（SessionStart payload、targeted gate test）皆 PASS
- **風險限於 TestFailGate 噪音 + 真正回歸時失去快速偵測能力**

### 為何超出 Wave 4a 範圍

- Wave 4a Stage E 經 plan v2.1 §修訂 #2 收斂為「砍 phase6 hook + 移除 workflow-guardian.py 引用」，**主 codex_companion.py 完全不動**
- 修這 10 測試需理解 Silent Advisory Mode 重構意圖、判斷是改測試對齊新行為 / 改實作回滾 / 兩者混合，屬獨立 design decision
- 本 stage 邊界明確切割：Wave 4a 只動 phase6 死代碼 + Architecture.md 表格列；不應藉測試修補擴大範圍

### 修補路徑（待另開 session）

1. 跑 single failure with `pytest -xvs` 取完整 traceback，分類：(a) 純 assertion 對齊新 schema (b) 邏輯期望不符
2. 比對 `7794f65` diff 與測試期望，決定 fixture / mock / assertion 同步方向
3. 若 Silent Advisory Mode 為定案，則更新測試對齊；若為可逆設計，則重新評估
4. 估時：~1 session（含跑通 + 邊界 smoke）

### 加入 follow_up_issues.md

本項追加為議題 #8（codex_companion-silent-mode-test-realign）。

---

## REG-003 · Vector DB 精密化用法（拆庫 + chunking 粒度）

| 欄位 | 內容 |
|------|------|
| 首次提案 | 2026-04-28（memory cleanup follow_up #1） |
| 範圍 | 單一 `atom_chunks.lance`（181MB，混合所有 atom + episodic）改為按 scope/用途拆分 |
| 不修風險 | **低**：Wave 3b probe burst 已驗證命中率 87.6%，當前單庫設計可用；屬效能優化非功能 regression |

### 待研究面向

- 按 scope 拆庫：global / shared / role / personal 各自獨立 lance
- 按用途拆庫：atom（高頻檢索）/ episodic（低頻長尾）/ wisdom（特殊）各自獨立
- chunking 粒度：目前檔案級 chunk，是否該降到段落級或句子級
- 每個 atom 的 chunk 上限——防止單檔污染整庫
- top_k 召回策略：跨庫 union vs 單庫獨立
- embedding 模型：目前 nomic-embed-text，單人環境是否該替換為更輕量

### 需先知道的事實

當前實際 chunk 數、embedding 模型、單次查詢延遲、命中率（若有 metrics）。

### 修補路徑

入口檔：`tools/memory-vector-service/{indexer.py, searcher.py, config.py}`。需先寫 chunk-level metrics 採樣才能評估拆庫實質收益。

---

## REG-004 · Vector 路徑寫死根因 commit 追溯（議題 #2 殘留）

| 欄位 | 內容 |
|------|------|
| 首次提案 | 2026-04-28（memory cleanup follow_up #2） |
| 範圍 | `workflow-guardian.py` 的 `vs_script` 從何時起寫死為錯路徑 `tools/vector-service.py`（真檔在 `tools/memory-vector-service/service.py`） |
| 處理進度 | Wave 3a 已修補路徑 + 加 health-gate flag + 觀察儀表；Wave 3b probe burst 驗證 REVIVE。**剩餘**：未追完 commit 引入點 |
| 不修風險 | **零**：路徑已修，本項僅為防再犯文件溯源；屬考古研究非功能修補 |

### 修補路徑

`git log -- hooks/workflow-guardian.py` 加 `-S 'vector-service.py'` 找首次出現 commit。

---

## REG-005 · Atom 注入機制重構（議題 #3）

| 欄位 | 內容 |
|------|------|
| 首次提案 | 2026-04-28（memory cleanup follow_up #3，從 plan v1 §二 矛盾 #4 帶過來） |
| 範圍 | `wg_atoms.py:_strip_atom_for_injection` 改寫為「摘要優先 + token budget + hot/cold 分級」；`SECTION_INJECT_THRESHOLD` 從 300 降至 200；Related 擴散加 activation-aware 過濾 |
| 不修風險 | **中**：當前 trigger 命中即全文注入，特別是 vector 失能時降級到 atom 全注入；現況 vector 已 REVIVE 但 section_hints 召回品質仍受 ranked min_score 偏寬鬆影響（議題 #6） |

### 前置條件

(a) atom 注入機制 3 源不一致已先解決（atom frontmatter `Trigger` / `_ATOM_INDEX.md` / `MEMORY.md` 三者統一真相源）；(b) 議題 #6 ranked min_score 校準完成。

### 修補路徑

入口：`hooks/wg_atoms.py`、`hooks/wg_intent.py`、`memory/_ATOM_INDEX.md` 表格規格。

---

## REG-006 · Hook 萃取管線重複疑慮（議題 #4）

| 欄位 | 內容 |
|------|------|
| 首次提案 | 2026-04-28（memory cleanup follow_up #4，考古學者 C3 帶過來） |
| 範圍 | `quick-extract.py` vs `extract-worker.py` vs `user-extract-worker.py` 三條管線並存，疑似職責重複 |
| 不修風險 | **低**：三條管線目前各自運作，Mechanic 稽核已確認多數 hook 不是死檔而是 dispatcher 依賴或 worker；本項僅為「合併簡化」研究而非 broken behavior |

### 修補路徑

追完整 trace：`settings.json` 掛載點 → `workflow-guardian.py` import 鏈 → 各 worker spawn 點。判斷三者是否可合併為單一 worker + 旗標切換。

