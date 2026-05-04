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
| 狀態 | **2026-04-28 已處置（砍過期測試）** |
| 處置方式 | 使用者裁決「測試 code 過期就砍」→ 整檔刪 `test_codex_companion_drain_e2e.py` + `test_codex_companion_stop_e2e.py`（silent mode 下 hook 全靜默，剩 2+2 pass test 屬 trivial pass 無覆蓋價值），`test_heuristics.py` 砍 4 個對齊舊 severity ceiling 的 test（保留 17 個 heuristic 函式單元測試） |
| 處置 commit | （見本 commit） |
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

## REG-005 · Atom 注入機制重構（議題 #3）✅ RESOLVED 2026-05-04

| 欄位 | 內容 |
|------|------|
| 首次提案 | 2026-04-28（memory cleanup follow_up #3，從 plan v1 §二 矛盾 #4 帶過來） |
| 範圍 | `wg_atoms.py:_strip_atom_for_injection` 改寫為「摘要優先 + token budget + hot/cold 分級」；`SECTION_INJECT_THRESHOLD` 從 300 降至 200；Related 擴散加 activation-aware 過濾 |
| 處理結果 | **KEEP**（觀察期 A=290 / B=24 / wall=5.43d，四標準達標；自動止血未觸發） |
| 收尾報告 | [_AIDocs/DevHistory/atom-injection-refactor-2026-04.md](DevHistory/atom-injection-refactor-2026-04.md) |

### 落地 commit

| commit | 內容 |
|--------|------|
| `540cc91` | A 層 — 摘要優先（`_strip_atom_for_injection` + atom 類型偵測 + 21 unit tests） |
| `3d03ba1` | B 層 — per-turn budget cap（`_TURN_BUDGET_LIMIT=800` + `SECTION_INJECT_THRESHOLD` 300→200 + 10 integration tests） |
| `0309c89` | 觀察儀表（`wg_atom_observation.py` flag-gated + `atom-injection-summary.py` 自動判定） |
| `a2e1a39` | C 層 — hot/cold 分級器（`classify_hot_cold` + cold 1 行注入 + 23 unit tests） |
| `5255c7b` | D 層 — Related 擴散 hot/cold 過濾 + max_depth=1（8 unit tests） |
| `49e4849` | SessionStart 高亮提醒（KEEP/ROLLBACK/GRAY 期滿自動推送 + 16 unit tests） |
| `d47b37a` | ROLLBACK cleanup helper（`reg005-rollback-cleanup.py` 冪等清掃 + 10 unit tests） |

### 觀察期關鍵發現

- **「按需展開」假設未證實**（cold_active_reads/cold_injections = 0/15 = 0%），但 n=15 < 40 min-sample 門檻 → 不觸發 ROLLBACK；C/D 層的 token 節省與此假設獨立成立
- **Hot 主導**：290 注入 = 275 hot (94.8%) + 15 cold (5.2%)
- **Per-turn 分布**：51 turns，平均 5.69 atoms/turn，max 11；B 層 800 budget 上限有效收斂高密度 turn

### 後續追蹤（不 block，不另開 session）

- 3 個月後重審 cold rate（待 cold_inj 累積 ≥40）
- Wisdom Engine 整合 `hot_hits` / `miss_count`（目前 placeholder=0）
- (5b) canary baseline drift 設計尚未實作

---

## REG-006 · Hook 萃取管線重複疑慮（議題 #4）

| 欄位 | 內容 |
|------|------|
| 首次提案 | 2026-04-28（memory cleanup follow_up #4，考古學者 C3 帶過來） |
| 範圍 | `quick-extract.py` vs `extract-worker.py` vs `user-extract-worker.py` 三條管線並存，疑似職責重複 |
| 不修風險 | **低**：三條管線目前各自運作，Mechanic 稽核已確認多數 hook 不是死檔而是 dispatcher 依賴或 worker；本項僅為「合併簡化」研究而非 broken behavior |

### 修補路徑

追完整 trace：`settings.json` 掛載點 → `workflow-guardian.py` import 鏈 → 各 worker spawn 點。判斷三者是否可合併為單一 worker + 旗標切換。

---

## REG-007 · IDENTITY.md 設計理由段永久 BLOCK（Wave 4b Stage F1 重審 2026-04-28）

| 欄位 | 內容 |
|------|------|
| 首次裁決 | 2026-04-28 Wave 4b：F1 dryrun 雙稽核 PASS、執行後**使用者於 session 內顯式還原** |
| 重審結論 | 2026-04-28 Stage F 重審：**永久 BLOCK 確認** — vector REVIVE 不改變 always-load 必要性 |
| 範圍 | `IDENTITY.md:62-65`「### 設計理由（給未來 AI 看）」段（4 行 + 標題） |
| Token 成本 | ~65 tokens/turn（always-load 入口） |

### BLOCK 理由（永久）

1. **不是縮影**：該段不在任何 `_AIDocs/` md 中（搜尋確認）；屬「給未來 AI 看的行動指引本體」，不是 md 知識的縮抄
2. **行動本體屬性**：內容為「為什麼用具體禁語清單而非抽象形容詞」的設計理由 — 這是**行動類 atom 的「為什麼」說明**，移走 always-load 後 AI 看不到 → 易違反硬規則
3. **使用者顯式裁決**：~65 tokens/turn 成本可接受（已驗證 path 3+ 「印象 vs 縮影」框架下，這段是印象本體不是縮影）
4. **Vector REVIVE 不影響**：本段 BLOCK 理由是「always-load 必要性」維度，與 vector 召回品質無關

### 不修的實際風險

- **零**：不是 drift / 不是 broken behavior，是顯式設計選擇

### 連動

- 設計原則：[memory/feedback/feedback-pointer-atom.md](../memory/feedback/feedback-pointer-atom.md)（指標型 atom — 行動本體 vs 縮影的判別）

