# REG-005 · atom 注入機制重構（2026-04 / Opus Melodic Comet）

> 收尾報告 · 2026-05-04 · verdict = **KEEP**
> 設計與 handoff：見本檔末尾「設計歸檔」節（原暫存檔 `memory/_staging/reg-005-atom-injection-refactor.md` 整檔搬入）
> 連動：[known-regressions.md REG-005 ✅](../known-regressions.md) / [vector-threshold-calibration-2026-04.md](vector-threshold-calibration-2026-04.md)（前置）

---

## 觀察期判定（自動）

| 指標 | 數值 | 標準 | 結果 |
|------|------|------|------|
| A. 累計 atom 注入數 | **290** | ≥ 150 | ✅ 193% |
| B. 累計 session 數 | **24** | ≥ 6 | ✅ 400% |
| C. 最低 wall clock | 5.43d | ≥ 2d | ✅ |
| D. 最高 wall clock | 5.43d | ≤ 7d | ✅（未強制期滿） |

判定：**KEEP** — 期滿且四標準達標。
止血條件：全部未觸發（hot_hits / hit_misses 為 placeholder；coverage_zero=空；cold 比率 0% 但樣本 n=15 < 40 min-sample 門檻 → 不觸發 ROLLBACK）。

判定來源：`tools/atom-injection-summary.py` 跑於 2026-05-04T22:xx UTC，log-based aggregation（Session 2 改為 append-only log 避免 metric race）。

---

## 「按需展開」假設驗證（C 層核心賭點）

> **誠實揭露：賭點未證實，但被 min-sample 門檻保護。**

| 指標 | 數值 |
|------|------|
| cold_active_reads | **0** |
| cold_injections | 15 |
| 比率 | **0.0%**（門檻 5%） |
| 是否觸發 ROLLBACK | ❌ 否（n=15 < 40 min-sample 門檻） |

### 解讀

賭點原文：「LLM 看到 cold atom 名後若需詳情會主動 Read」。

觀察期內：
- 15 次 cold 注入散佈 10 個 atom（feedback-fix-on-discovery x3 / feedback-end-to-end-smoke x2 / feedback-codex-companion-model x2 / feedback-codex-collaboration x2 / 其餘 6 個 atom 各 1 次）
- 在同 session 同 ts 之後 主動 Read 對應 `.md` 檔次數：**0**
- 跨檢驗：`memory_read` 共 43 筆，與 cold atom 名稱重疊的 2 個（electron-uia-automation, feedback-codex-collaboration）皆為「inject 之前的 read」（屬無關 read 巧合命名碰撞），自動腳本 `_count_cold_active_reads` 嚴格按「same session + read_ts ≥ inject_ts」比對 → 0 命中

### 為什麼仍 KEEP（不 ROLLBACK）

1. **樣本不足以否證**：n=15 cold 注入遠低於 40 min-sample 門檻，僅靠 5 個 distinct sessions 的 cold 路徑命中。設計時就預期此風險（min-sample 門檻就是保護「賭點假設未必能在小樣本下被推翻」）
2. **C/D 層的 token 節省與「按需展開」假設無關**：cold 1 行（~30 tokens）vs 全注入（200-500 tokens）的省量是「即時、確定」的；即使 LLM 從不 Read cold 提示，C/D 層仍對省 token 有貢獻
3. **「按需展開」失敗的代價是「漏知識」非「token 浪費」**：若某 cold 提示其實是關鍵知識而 LLM 沒展開，等同於沒注入；但這個風險也存在於 ROLLBACK 後的「cold atom 全部不注入」設計，且 ROLLBACK 反而會讓相同 atom 滿載注入消耗預算
4. **A+B 層獨立驗證 token 節省**：Session 1 baseline -62.5%，與 C/D 層的「按需展開」賭點無因果

### 留 follow-up（不 block KEEP）

- **3 個月後重審 cold 比率**：等 cold_inj 累積 ≥40，若仍 0% read rate → 重新評估 C/D 層
- **Wisdom Engine 整合 miss detection**：若某 cold atom 應 fire 但 LLM 沒 Read → Wisdom Engine 反思層應產 SessionEnd hint（目前 `hot_hits` / `miss_count` 為 placeholder=0）
- **追蹤條目**：known-regressions.md REG-005 resolved 段落附「3-month follow-up: cold-active-read rate revalidation」

---

## per-turn token 分布（before / after）

> 直接量測 before/after 同 prompt token 數不可靠（Session 2 baseline test 結論：state 持久化導致重複呼叫被去重）。改採 log-derived 真實使用情境分布。

### After（觀察期內，4 層全上）

| 統計量 | 值 |
|--------|-----|
| 總 turn 數 | 51（依 session_id+ts 去重） |
| atom/turn 平均 | **5.69** |
| atom/turn 中位 | 6 |
| atom/turn 標準差 | 2.87 |
| atom/turn 最小 | 1 |
| atom/turn 最大 | 11 |

分布直方：

```
atoms/turn   turns
   1         ████  (4)
   2         ████  (4)
   3         ██████  (6)
   4         ████████  (8)
   5         █  (1)
   6         ████  (4)
   7         ████████  (8)
   8         █████████  (9)
   9         █  (1)
  10         ████  (4)
  11         ██  (2)
```

### Before（推估，無 4 層）

無 baseline log 可直接比對（觀察儀表是隨 4 層一起上線，不是先採前期 baseline）。但可由架構推算上限：

- 若無 A 層摘要剝段：每 atom 平均 200-500 tokens（feedback-* 約 200-300, decisions 約 400, workflow-rules 約 500）
- 若無 B 層 budget cap：5.69 atom/turn × 平均 350 tokens/atom = **~1990 tokens/turn 平均**；max 11 atoms × 350 = ~3850 tokens/turn 上限
- 若無 C/D 層 hot/cold 分級：related 擴散會把 91+10=101 個 related 都全注入

### After（實際）

`_TURN_BUDGET_LIMIT = 800` tokens hard cap（atom 注入 budget），任何超出即 fallback 為摘要或 skip。實測本 session SessionStart 訊息 `[Context budget: 951/5000 tokens]` 為**外層 V2.11 additionalContext budget**（5000 deep mode），與 atom 注入 800 budget 為兩層獨立預算。

**估算節省（observation period 加總）**：

| 項目 | 推估節省 |
|------|---------|
| A 層摘要剝段（## 知識 / ## 演化日誌） | ~30-50% / 大型 atom × 觀察期 290 inj |
| B 層 budget cap fallback | 跨 turn 上限 800 tokens 強制保護 |
| C 層 hot/cold（cold 1 行）| (350 - 30) × 15 cold = **~4800 tokens** |
| D 層 Related cold 過濾 | (350 - 30) × 10 related-cold = **~3200 tokens** |

合計估算節省 ≥ 8000 tokens 跨整個觀察期（保守估算，A+B 跨層收益重疊未獨立計）。Session 1 同 trigger A+B 對 toolchain atom 的 baseline 量測為 **-62.5%**。

---

## 每 atom 觸發覆蓋率

觀察期內 30 distinct atoms 觸發注入，全部覆蓋率 ≥ 1：

| atom | 注入次數 | 分類分布 |
|------|---------|---------|
| decisions | 28 | hot×28 |
| workflow-rules | 25 | hot×25 |
| feedback-git-log-chinese | 22 | hot×22 |
| decisions-architecture | 20 | hot×20 |
| feedback-humanist-decision-framing | 18 | hot×18 |
| feedback-memory-path | 16 | hot×16 |
| toolchain | 15 | hot×15 |
| workflow-svn | 15 | hot×15 |
| preferences | 15 | hot×15 |
| toolchain-ollama | 12 | hot×12 |
| feedback-handoff | 12 | hot×12 |
| feedback-fix-on-discovery | 11 | hot×8 cold×3 |
| feedback-pre-completion-test-discipline | 10 | hot×10 |
| feedback-global-install | 9 | hot×9 |
| feedback-end-to-end-smoke | 8 | hot×6 cold×2 |
| feedback-decision-no-tech-menu | 7 | hot×6 cold×1 |
| feedback-no-test-to-svn | 7 | hot×7 |
| feedback-no-plan-bound-hook | 6 | hot×5 cold×1 |
| feedback-pointer-atom | 5 | hot×5 |
| feedback-no-outsource-rigor | 5 | hot×5 |
| feedback-silent-failure-instrumentation | 5 | hot×5 |
| feedback-codex-companion-model | 4 | hot×2 cold×2 |
| feedback-codex-collaboration | 4 | hot×2 cold×2 |
| workflow-icld | 4 | hot×4 |
| architecture | 2 | hot×2 |
| gdoc-harvester | 1 | cold×1 |
| feedback-bg-subprocess-stderr | 1 | cold×1 |
| fix-escalation | 1 | hot×1 |
| electron-uia-automation | 1 | cold×1 |
| feedback-handoff-self-sufficient | 1 | cold×1 |

**0 觸發 atoms**：未確認（需比對 `_ATOM_INDEX.md` 全名單，但設計止血條件「任一 atom 覆蓋率 0」需 wall_clock ≥ 5d，已達 5.43d，腳本 `coverage_zero_atoms` 為空 → 觀察期內已注入 atoms 含蓋了 trigger fire 的所有 atoms）。低頻 atom（電子自動化、gdoc-harvester、fix-escalation）僅 1 次觸發，符合「特殊 trigger」屬性，不為異常。

---

## A / B / C / D 四層各自貢獻拆解

### A 層 — 摘要優先（commit `540cc91`）

**入口**：`hooks/wg_atoms.py:_strip_atom_for_injection`
**機制**：偵測 atom 類型（純印象+行動 vs 混型）→ 混型且 size > `SECTION_INJECT_THRESHOLD=200` tokens → 剝 `## 知識` + `## 演化日誌` 段，保留 frontmatter（Confidence/Trigger/Last-used）+ `## 印象` + `## 行動`
**證據**：290 次注入全走此 helper；`SECTION_INJECT_THRESHOLD` 從 300 → 200 落地（commit `3d03ba1`）
**估算貢獻**：每個 ≥200 tokens 大型 atom 省 30-50%（剝段比例）。觀察期約 60% 注入命中此路徑（trigger=139 全 hot，含 toolchain/decisions 等大型 atom）

### B 層 — per-turn budget cap（commit `3d03ba1`）

**入口**：`hooks/wg_atoms.py:decide_atom_injection`（ok / fallback / skip 三態）+ `hooks/workflow-guardian.py` 注入點 budget tracker
**機制**：`_TURN_BUDGET_LIMIT = 800` tokens；atom 全段注入若超預算 → fallback 摘要；fallback 仍超 → skip + 列名於 `(budget fallback)` 標記
**證據**：observation log 含 `decision=fallback` / `decision=skip` 條目；本 session 系統訊息亦見 `(budget fallback)` 標記
**估算貢獻**：保證任何 turn 上限不超 800 tokens；max 11 atoms 高密度 turn 由此從 ~3850 tokens 收斂到 ≤800 tokens，**單 turn 上限省 ~3000 tokens**

### C 層 — hot/cold 分級器（commit `a2e1a39`）

**入口**：`hooks/wg_atoms.py:classify_hot_cold` + `format_cold_inject_line` + `log_injection`；`hooks/workflow-guardian.py` 注入路由（hot 走 budget；cold 1 行不消耗 budget）
**機制**：近 7 天 ReadHits 增量高 + 直接 trigger 命中 → hot；vector ranked + Related → cold
**證據**：290 inj = 275 hot + 15 cold（5.2% cold 率）；trigger=139 全 hot；vector=50 中 45 hot / 5 cold；related=101 中 91 hot / 10 cold
**估算貢獻**：(350-30) × 15 cold = **~4800 tokens** 觀察期內節省
**未證實的賭點**：「按需展開」假設 0/15 = 0%（見上節）

### D 層 — Related 擴散 hot/cold 過濾（commit `5255c7b`）

**入口**：`hooks/wg_atoms.py:spread_related` 加 max_depth=1；workflow-guardian.py Related 段路由
**機制**：Related 中 hot atom 才擴散；cold Related 只列名 `(related, cold)` 標記不注入內容；depth ≤ 1（不做 transitive）
**證據**：related source 共 101 注入；其中 cold=10 走 1 行路徑
**估算貢獻**：(350-30) × 10 related-cold = **~3200 tokens** 觀察期內節省 + transitive depth=1 防止指數爆炸

### 補強（commit 6+7，Session 2 補完）

- **commit `49e4849`**：SessionStart 高亮提醒 helper（`_check_reg005_observation_status` + `_format_reg005_highlight`）— 期滿後自動推送高亮粗體訊息進 SessionStart context（觸發本次收尾 session 的高亮注入）
- **commit `d47b37a`**：ROLLBACK cleanup helper（`tools/reg005-rollback-cleanup.py`）— 冪等清掃 settings.json hooks 內 wg_atom_observation 引用 + 刪 flag；保留採樣 hook 檔案供未來重用

---

## 收尾動作（已執行）

1. ✅ `tools/atom-injection-summary.py --report` → KEEP 確認
2. ✅ 寫本檔（收尾報告）
3. ✅ `tools/reg005-rollback-cleanup.py --apply` → 移除 settings.json 內 wg_atom_observation hook + 刪 flag（採樣 hook 檔案保留）
4. ✅ 清理 `memory/wisdom/reflection_metrics.json` 的 `reg005_observation` 區塊（觀察期已結束）
5. ✅ `_AIDocs/known-regressions.md` REG-005 標 ✅ resolved
6. ✅ 暫存設計檔搬入本檔末尾「設計歸檔」節 + 刪除 `memory/_staging/reg-005-atom-injection-refactor.md`
7. ✅ 全 pytest 綠 + SessionStart smoke EXIT=0
8. ✅ git commit + push（兩個 commit：報告 / cleanup）

---

## 設計歸檔（原 `memory/_staging/reg-005-atom-injection-refactor.md` 主體）

> 為什麼搬入本檔：暫存設計檔在 KEEP 收尾後不再「進行中」，但設計細節（4 層機制、觀察期事件驅動四重標準、自動止血條件）對未來 atom-injection 議題（cold-rate 重審、Wisdom Engine 整合）仍有參考價值。歸檔保留，刪除原暫存檔避免雙寫。

### 為什麼做（原始動機）

atom trigger 命中時 `wg_atoms.py:_strip_atom_for_injection` 把整檔注入 prompt context。
- 整檔常 200–600 tokens，多 atom 同時命中可吃 1500+ tokens
- 多數命中只用到 atom 的某段（印象 or 行動），整檔注入有冗餘
- 目標：相同決策品質下 token 注入降 40–60%

### 設計（4 層）

#### A 層：摘要優先

- 命中時優先注入 frontmatter（Confidence / Trigger / Last-used）+ `## 印象` 段 + `## 行動` 段
- 跳過 `## 知識` 段（指標型 atom 已剝；混型 atom 暫保留但加 token cap）
- 偵測 atom 類型（純印象+行動 vs 混型）→ 走不同注入路徑

#### B 層：per-turn token budget

- 起手預算 800 tokens（含本 turn 所有 atom 注入）
- 多 atom 命中時優先序：直接 trigger 命中 > Related 擴散 > vector ranked-sections
- 預算耗盡 fallback：保留印象段、捨棄知識段
- `SECTION_INJECT_THRESHOLD` 從 300 → 200

#### C 層：hot/cold 分級

- **hot**：近 7 天 ReadHits 增量高 + 直接 trigger 命中 → 全段注入（仍受 budget cap）
- **cold**：vector ranked 召回 + Related 擴散 → 只給 1 行印象 + atom 名 + 「按需展開」hint
- 賭點：LLM 看到 cold atom 名後若需詳情會主動 Read（**觀察期未證實，n=15 不足以否證 — 見上節**）

#### D 層：activation-aware Related 擴散過濾

- 現況：Related 列出的 atom 全部擴散注入
- 改為：(1) Related 中 hot atom 才擴散；(2) cold Related 只列名不注入內容；(3) Related 深度上限 1（不做 transitive）

### 觀察期設計（CI + 觀察期分工）

> **核心原則（議題 #5 規則沉澱）**：使用者只看自動判定報告，不負責觀察本身。觀察是程式 + LLM 自察的工作。

#### CI（瞬時，不算觀察期）— 模擬可解的部分

| 指標 | 觀察方式 |
|------|---------|
| (1) per-turn token 分布 | unit test：給 atom set + trigger → 計算注入 token，PR 必過 |
| (2) 預算分配排序 | integration test：多 atom 命中 + budget 耗盡 fallback |
| (3) Hot/cold 分類正確性 | unit test：fixture 給 timeline → 驗分類 |

#### 觀察期（事件驅動，非 wall clock）— LLM 黑盒 + 使用者長尾

| 指標 | 觀察者 | 採樣方式 |
|------|--------|---------|
| (4) Cold atom 主動讀比率 | **Hook 純機器**（最可靠） | `wg_intent.py` 注入 cold atom → 寫 log；`PostToolUse(Read)` → 比對路徑 → 命中 +1 |
| (5a) 命中錯失（已知） | **Wisdom Engine 自察** | SessionEnd 反思「該命中沒命中」 |
| (5b) 命中錯失（未知）| **SessionStart canary** | 每日跑 known-good query 比對 baseline 漂移 |
| (6a) Atom 覆蓋率 | **Hook 注入計數** | 每 atom 至少每 N 天觸發一次；0 觸發 = 異常 |
| (6b) Silent failure 早警 | 同 (5b) canary | baseline 漂移 = silent failure 訊號 |

#### 期滿條件（事件驅動四重標準）

| 維度 | 標準 | 角色 |
|------|------|------|
| **A. 累計 atom 注入數** | ≥ 150 | 主要標準（比率指標的分母） |
| **B. 累計 session 數** | ≥ 6 | 跨工作模式採樣（不同 session 涵蓋不同 topic 範圍） |
| **C. 最低 wall clock 下限** | ≥ 2 天 | 防止單日爆量後立刻判定 |
| **D. 最高 wall clock 上限** | ≤ 7 天 | 防止使用者長期不開 session 卡住 |

```
正常完成：A ≥ 150 AND B ≥ 6 AND wall_clock ≥ 2 → 期滿，跑自動判定
強制結束：wall_clock ≥ 7 → 強制期滿
  若 A < 150：判定報告附註「樣本不足 (A={n})，建議保守 KEEP 或延長」
```

#### 自動止血條件（不等期滿，但需最低樣本門檻）

| 止血條件 | 最低樣本門檻 |
|---------|------------|
| hot 命中率 < 50% | + hot 注入數 ≥ 40 |
| cold 主動讀比率 < 5% | + cold 注入數 ≥ 40 |
| 命中錯失率 > 10% | + 總注入數 ≥ 75 |
| 任一 atom 覆蓋率 0 | + wall_clock ≥ 5 天 |

任一觸發（含最低樣本門檻）→ 立即 ROLLBACK，**高亮粗體 SessionStart 注入**通知。

### Session 1/3 — A+B 兩層 + CI test + 部署觀察儀表

- commit `540cc91`：A 層 — `_strip_atom_for_injection` 改寫 + atom 類型偵測 + 21 unit tests
- commit `3d03ba1`：B 層 — `decide_atom_injection` ok/fallback/skip 三態 + `_TURN_BUDGET_LIMIT=800` + `SECTION_INJECT_THRESHOLD` 300→200 + 10 integration tests
- commit `0309c89`：觀察儀表 — `hooks/wg_atom_observation.py` flag-gated 採樣 + `tools/atom-injection-summary.py` 自動判定 + settings.json 註冊（PostToolUse(Read) + UserPromptSubmit）
- DocDrift：`Architecture.md` + `DocIndex-System.md` 隨 commit 同步
- 全 pytest：298 passed + 52 skipped

### Session 2/3 — C+D 兩層 + 啟動觀察期

- commit `a2e1a39`：C 層 — `classify_hot_cold` + `format_cold_inject_line` + `log_injection` helper + workflow-guardian.py 注入路由 + 23 unit tests
- commit `5255c7b`：D 層 — Related 段 hot/cold 路由（cold 1 行 `(related, cold)` 標記、不消耗 budget）+ spread_related max_depth=1 + 8 unit tests
- 觀察期啟動：2026-04-29T03:20:12Z（flag `memory/_staging/reg-005-observation-start.flag` 含起算時間戳）
- baseline 量測：直接 git worktree subprocess 量測不可靠（state 持久化導致重複呼叫被去重），改採驗證面替代量測 + 觀察期 log-derived 真實量測
- 全 pytest：345 passed + 52 skipped

### Session 2 補完（commit 6+7）

審查暫存檔聲稱「SessionStart 高亮提醒」但 grep `atom-injection-summary|reg005|reg-005` 在 `hooks/workflow-guardian.py` 無命中 → 確認 Session 2 漏實作此段。同 session 順便補上 ROLLBACK 路徑會用到的 cleanup helper。

- commit `49e4849`：SessionStart 高亮提醒 — `_check_reg005_observation_status()`（subprocess 跑 `atom-injection-summary.py --json`，timeout=5，fail-open）+ `_format_reg005_highlight()` 純函式 → verdict ∈ {KEEP/ROLLBACK/GRAY} 才產粗體 markdown 訊息；INCOMPLETE/NOT_STARTED 完全靜默；16 unit tests（9 格式化 + 7 子程序失敗路徑）
- commit `d47b37a`：ROLLBACK cleanup helper — `tools/reg005-rollback-cleanup.py`，dry-run 預設 / `--apply` 才動。掃 settings.json 任意 event 內的 hooks，移除引用 `wg_atom_observation.py` 的 hook entry；matcher block 變空時整塊丟棄；同步刪 flag；保留 `hooks/wg_atom_observation.py` 檔案本身供未來重用。冪等。10 unit tests
- 全 pytest：355 passed + 52 skipped

### Session 3/3 — 觀察期裁決（本檔）

- ✅ 跑 `tools/atom-injection-summary.py --report` → KEEP
- ✅ 寫本檔
- ✅ `tools/reg005-rollback-cleanup.py --apply` → 清掃 + 刪 flag
- ✅ 清理 `reflection_metrics.json` reg005_observation 區塊
- ✅ known-regressions.md REG-005 標 ✅ resolved
- ✅ 歸檔暫存檔

### 不要動（劃界）

- vector indexer / embedding（REG-003）
- vector min_score 閾值（前置 2 已校準完，本任務不再動）
- atom_write MCP server.js
- atom 寫入流程（PreToolUse Confidence Gate）
- always-loaded 入口（IDENTITY.md / USER.md / CLAUDE.md / MEMORY.md）

### 入口檔速查

- 主改：`hooks/wg_atoms.py`、`hooks/wg_intent.py`、`hooks/workflow-guardian.py`
- 配置：`memory/_ATOM_INDEX.md`（trigger 機器真相源）
- 觀察 hook：`hooks/wg_atom_observation.py`
- 自動判定：`tools/atom-injection-summary.py`
- ROLLBACK 清理：`tools/reg005-rollback-cleanup.py`
- 設計依據：`_AIDocs/DevHistory/atom-trigger-source-of-truth.md`（前置 1）
- 校準紀錄：`_AIDocs/DevHistory/vector-threshold-calibration-2026-04.md`（前置 2）

---

## 順手修補清單

收尾期間發現並當場處理 2 項：

1. **`tools/reg005-rollback-cleanup.py` 寫 settings.json 用 CRLF**（≤5 行 / 1 檔 / 不動架構）
   - 問題：`settings_path.write_text(..., encoding="utf-8")` 在 Windows 預設 `newline=None` → `\n` 會被轉成 `\r\n`，但 settings.json 入庫為 LF；首次 `--apply` 後 git diff 變 615 行 churn（語義 diff 僅 22 行）
   - 修正：改用 `open(path, "wb")` + bytes write 強制 LF；10 unit tests 仍綠
   - 同時 oneshot 把當前 settings.json CRLF → LF 還原乾淨

2. **`memory/wisdom/reflection_metrics.json` lost-update race**（recovery via git restore HEAD）
   - 問題：本 session 期間，`wg_atom_observation` hook 與其他 reflection metric 寫者（Wisdom Engine reflect / extract-worker 等）有 lost-update race，導致原 2425 行 metric 在某個 PostToolUse(Read) tick 時被截斷至 11 行（只剩 reg005_observation 自己）
   - 恢復：`git checkout HEAD -- memory/wisdom/reflection_metrics.json` 取回 2401 行 HEAD 版（最近一次 commit 是同日，遺失增量很小：`reads_in_memory` 40→43 等微觀差異）
   - **race 在 cleanup --apply 移除 `wg_atom_observation` hook 後消失**，無需獨立 code fix
   - 結構性建議（不 block，留 follow-up）：未來若重啟採樣 hook，應改寫子鍵到獨立檔（如 `memory/wisdom/atom_injection_metrics.json`）避免與 wisdom_reflection_v2 共用入口

DocDrift 已隨 Session 1/2/3 各 commit 處理（Architecture.md / DocIndex-System.md / known-regressions.md 同步落地）。

## 後續追蹤（不 block，不另開 session）

- **3 個月後**：cold_inj 累積 ≥40 時重審「按需展開」假設。若仍 0% → 重新評估 C/D 層
- **Wisdom Engine 整合**：`hot_hits` / `miss_count` 由 placeholder=0 改為實際統計，觸發 (5a) 命中錯失止血條件
- **canary baseline drift**：(5b) 設計尚未實作（SessionStart 跑 known-good query 對比）
