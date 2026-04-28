# 後續另開議題清單

> 由 memory cleanup 計畫衍生，使用者裁決另開 session 處理。
> Date: 2026-04-28

## 議題 #1：Vector DB 精密化用法

**緣由**：使用者提出「拆成更多組向量資料庫、把檔案分類並拆小」

**目前狀態**：單一 `atom_chunks.lance`（181MB，混合所有 atom + episodic）

**待研究面向**：
- 按 scope 拆庫：global / shared / role / personal 各自獨立 lance
- 按用途拆庫：atom（高頻檢索）/ episodic（低頻長尾）/ wisdom（特殊）各自獨立
- chunking 粒度：目前是檔案級 chunk，是否該降到段落級或句子級
- 每個 atom 的 chunk 上限 — 防止單檔污染整庫
- top_k 召回策略：跨庫 union vs 單庫獨立
- embedding 模型：目前用 nomic-embed-text，是否該替換為更輕量模型（單人環境）

**需先知道的事實**：當前實際 chunk 數、embedding 模型、單次查詢延遲、命中率（若有 metrics）

**建議入口檔**：`~/.claude/tools/memory-vector-service/indexer.py`、`searcher.py`、`config.py`

## 議題 #2：Vector DB 失效根因深挖（重要）

**緣由**：本次清理發現 `workflow-guardian.py:611` 寫死 `vs_script = tools/vector-service.py`（不存在），真檔在 `tools/memory-vector-service/service.py`。subprocess.Popen 必失敗但 line 632 無條件寫 `vector_ready.flag` → 12 天假陽性。

**需追的問題**：
1. **為什麼路徑會寫錯**：git log 找出哪個 commit 把 `tools/memory-vector-service/service.py` 改成 `tools/vector-service.py`，是 typo 還是計畫中要搬但沒搬完？
2. **為什麼 12 天沒人察覺**：
   - SessionStart 注入沒看到「vector service start failed」？無 stderr 報告？
   - `wg_intent.py` 的 fail-closed 太靜默？
   - 使用者實際工作流根本不依賴 vector search（如果是這個 → 印證激進派「沒人需要它」主張）
3. **缺乏告警機制**：`flag` 寫入應該檢查 health 200 才寫，目前無條件寫是設計缺陷
4. **bg subprocess error swallow**：line 595-662 的 bg subprocess 把 stdout/stderr 都導向 DEVNULL，啟動失敗無痕跡

**修補建議（深掘後再定）**：
- vector 啟動鏈加上「flag 寫入前必須 health 200」硬檢查
- bg subprocess stderr 改導 `~/.claude/Logs/vector-init.log`
- SessionStart 額外注入 `vector_ready` 狀態（顯示 ready / failed / disabled）
- 整套機制寫入 `_AIDocs/Failures/vectordb-silent-failure-2026-04.md` 防再犯

**處理優先級**：在本次清理 cleanup 完成 + 4 天觀察期結束後立即開新 session 處理。

## 議題 #3：atom 注入機制重構（從 plan v1 §二 矛盾 #4 帶過來）

**內容**：「摘要優先 + token budget + hot/cold 分級」改寫 `wg_atoms.py:_strip_atom_for_injection`，把 SECTION_INJECT_THRESHOLD 從 300 降至 200，並加入 activation-aware 的 Related 擴散過濾。

**前置條件**：vector service 修活（議題 #2）— 否則 section_hints 來源仍空。

## 議題 #4：hook 萃取管線重複疑慮（從考古學者 C3 帶過來）

**內容**：`quick-extract.py` vs `extract-worker.py` vs `user-extract-worker.py` 三條管線並存，疑似職責重複。需追完整 trace。

## 議題 #5（緊急，須在 Stage D 動工前處理）：自動觀察儀表，取代「使用者察覺」依賴

**緣由**：使用者 2026-04-28 指出 plan v2.1 的「4 天觀察期 → 等使用者主訴 atom 沒命中」根本不可行 — silent failure 本身就是不可見的（vector 已 silent fail 12 天無人察覺即證據）。

**處理範圍**（session 2 進入 Stage D 前必須先做）：
1. **儀表 log**：`wg_intent.py` 的 vector 路徑進入點 → 寫 `~/.claude/Logs/vector-observation.log`，schema：`{ts, session_id, fn, flag_state, result_count, fallback_used}`
2. **SessionStart 主動探測**：每 session 1 次跑 known query 並比對 vector vs keyword fallback 結果
3. **自動判定腳本** `tools/vector-observation-summary.py`：4 天後讀 log 自動決定修活/淘汰，**不問使用者**
4. **灰色地帶（占比 5–15%）才問使用者**

**連帶修訂**：Stage E（hook 鏈）/ Stage F（atom）的觀察期也應改為「log 採樣 + 自動判定」，不依賴使用者察覺

**plan v2.1 §修訂 #4 需重寫**：移除「使用者主訴」字眼、加 D2.5「儀表注入」、D5 改為「讀 log 自動判定」

**protocol §六 監督執行模板需新增規則**：silent-failure 風險的 stage 必須加 log 採樣機制

**狀態 (2026-04-28)**：✅ Wave 3a + 3b 已完成全部處理範圍項目。儀表落盤 → probe burst → 自動判定 REVIVE（命中率 87.6%）。

## 議題 #6（Wave 3b 衍生）：vector ranked 閾值 + service.py 查詢字串寫 stderr

**緣由**：Wave 3b probe burst 過程兩個 follow-up：

1. **bucket-C 高命中**：30 個明顯 out-of-domain 查詢（莎士比亞、量子糾纏、Eiffel Tower 等）約半數仍返回 1–4 筆 ranked 結果。代表 `vector_search.search_min_score` (0.65) 與 ranked-sections 0.50 floor 偏寬鬆，注入時可能混入低相關 chunk。
2. **service.py log_message 寫 stderr**：`tools/memory-vector-service/service.py` 繼承 BaseHTTPRequestHandler，預設 `log_message` 將完整 HTTP path（含 `q=...` 查詢字串）寫 stderr。Wave 3a 起 stderr 導向 `memory/_vectordb/service.log` → 查詢字串會持續累積到本機檔案。

**待研究面向**：
- (1) 比對 ranked 命中分數分布；給 `min_score` 一個更嚴格的下限（例如：bucket-C 命中應該 < 0.55 才視為 keep；測 0.70 / 0.75 兩值）
- (2) override `log_message` 改寫 sanitized version（只記 method/path 不含 query string，或截斷 q）；或改 stderr 指向 DEVNULL
- (3) 既有 `service.log` 是否含敏感 query → 評估是否該 truncate 或 rotate

**處理優先級**：本次 cleanup 結束（Wave 6）之後另開 session 處理，**不影響 REVIVE 決策**。

## 議題 #8（Wave 4a 衍生）：codex_companion Silent Advisory Mode 重構後 10 測試需對齊

**緣由**：Wave 4a Stage E 收尾跑全 pytest 觸發 TestFailGate，10 失敗（drain_e2e ×5 / stop_e2e ×1 / heuristics ×4）— 已驗證為 commit `7794f65`「Silent Advisory Mode」引入的 pre-existing regression，與 Wave 4a 零相關（git stash 前後 pytest 結果完全相同）。

**詳情**：見 `_AIDocs/known-regressions.md` REG-002。

**為何不在 Wave 4a 修**：本 stage 邊界明確切割為「砍 phase6 dead code + Architecture.md 表格列」，主 codex_companion.py 不動。修這 10 測試需理解 Silent Advisory Mode 設計意圖、判斷「改測試對齊新行為 vs 改實作回滾」，屬獨立 design decision。

**處理優先級**：Wave 6 收尾後另開 session 處理。線上行為零影響（重構已實際運作 8 commits）。

## 議題 #9（Wave 4b 衍生）：Stage F 5 子 stage BLOCK 重做 + F1 執行中被使用者還原

**Wave 4b 實際結果**：
- ✅ F4-drift（晉升門檻 4 處字串一致化）執行完成 + smoke 通過
- ❌ F1（IDENTITY.md 設計理由段移走）執行後被使用者於 session 內還原 — IDENTITY.md 保留原段，新建檔 `_AIDocs/DevHistory/IDENTITY-meta-rationale.md` 與對應 _INDEX 項目已清除。**判讀**：使用者認為「設計理由（給未來 AI 看）」對 future AI 行為對齊有 always-load 必要，~65 tokens/turn 的成本可接受。
- ❌ F2/F3/F5/F6/F7：dryrun §10 已 BLOCK，原因如下：

1. **F2 重做** — preferences ChatGPT Pro 段搬 feedback-codex-companion-model
   - 前提錯：feedback-codex-companion-model.md 不在 `_ATOM_INDEX.md`，搬過去 = 從高頻 trigger 注入降為僅 vector 召回
   - 重做條件：先把 feedback-codex-companion-model.md 加入 _ATOM_INDEX 並設 trigger（codex / gpt-5 / chatgpt pro / 訂閱）才談搬遷

2. **F3 重做** — decisions-architecture.md V3 段壓索引
   - 前提錯：本檔不在 _ATOM_INDEX、ReadHits=0、僅 vector 召回；壓索引 0 always-load 收益且暴露另一致性問題
   - 重做條件：先決策 decisions-architecture.md 是否回掛 trigger，再談裁剪

3. **F5 重做** — _reference 7 檔搬 _AIDocs/DevHistory/atom-evolution/
   - 前提錯：`tools/memory-vector-service/indexer.py:74` 預設只掃 `MEMORY_DIR`；雖支援 `additional_atom_dirs` 但 `workflow/config.json` 未設定 → `_AIDocs` 不在 vector 索引
   - 重做條件：先改 `workflow/config.json` 加 `additional_atom_dirs: ["_AIDocs/DevHistory"]` 並驗證 reindex 行為才談搬遷

4. **F6 重做** — feedback 3 檔搬 _AIDocs（codex-collaboration / e2e-smoke / pre-completion-test-discipline）
   - 前提錯：同 F5 — vector 召回會丟
   - 重做條件：同 F5

5. **F7 重做** — wisdom/DESIGN.md 與 _AIDocs/DevHistory/wisdom-engine.md 對比後處理
   - 前提錯：_AIDocs 版本僅 25 行摘要；DESIGN.md V2.11 詳細（因果圖移除原因 / arch_sensitivity / silence_accuracy / Bayesian 校準 / hook 整合表 / 變更紀錄）未覆蓋
   - 重做條件：先補完 _AIDocs/DevHistory/wisdom-engine.md 缺漏的 V2.11 細節再談 DESIGN.md 處理

**附帶議題**：atom 注入機制 3 源不一致 — atom frontmatter `Trigger` / `_ATOM_INDEX.md` 表格 / `MEMORY.md` 索引列表 → 應規定唯一真相源（建議 _ATOM_INDEX 為機器源，frontmatter Trigger 改註記，MEMORY.md 索引由 hook 自動生成）

**處理優先級**：Wave 6 收尾之後，先處理「附帶議題」（atom 注入真相源統一）才有合理基礎重做 F2/F3。F5/F6/F7 同步等 vector 索引範圍裁決。

## 議題 #10（Stage F 重審 2026-04-28 衍生）：「固」級邏輯程式碼化盤點與遷移

**緣由**：使用者於 Stage F 重審中提出「**非常固定的邏輯，就應該利用程式碼來更精簡 token 的消耗；且這點是絕對不變的原則**」。配合「指標型 atom」設計（[memory/feedback/feedback-pointer-atom.md](../../../memory/feedback/feedback-pointer-atom.md)），既有 atom 中所有 `[固]` 級邏輯需檢視能否搬到 hook 層、以避免每次讓 LLM 讀 atom 來判斷固定規則。

### 判別準則

某條 `[固]` 規則是否該程式碼化，看三條件：
1. **可機器決斷**：規則的觸發條件可由檔案路徑 / 字串模式 / state 數值決定（不需 LLM 判斷上下文）
2. **執行路徑明確**：滿足條件時的動作可枚舉（阻擋 / 注入 / 告警 / 自動修補）
3. **跨 session 穩定**：規則本身不會因專案差異需要 case-by-case 調整

三條件全 yes → 應 hook 化；任一 no → 留在 atom 作為 LLM 提示。

### 候選清單（待後續 session 評估）

| Atom | 規則 | 判別 | 已 hook 化? | 建議動作 |
|------|------|------|-----------|---------|
| feedback-memory-path | 「禁止寫 `~/.claude/projects/{slug}/memory/`」 | yes/yes/yes | **已**（PreToolUse `wg_pretool_guards.check_memory_path_block`, 2026-04-28） | — |
| feedback-no-test-to-svn | 「測試碼不上 SVN」 | yes/yes/yes | **已**（PreToolUse `wg_pretool_guards.check_svn_test_block`, 2026-04-28） | — |
| feedback-global-install | 「MCP/skill 安裝路徑規則」 | yes/yes/可能 | **未** | 待評估具體規則 |
| feedback-fix-on-discovery | 「順手修補清單檢核」 | yes/yes/yes | **已**（ScanReport Gate `wg_evasion.py` 2026-04-23） | — |
| feedback-fix-escalation | Fix Escalation 6-agent 會議 | yes/yes/yes | **已**（`wisdom_engine.py:track_retry`） | — |
| preferences「上GIT」縮寫 | 「git add + commit + push (+ SVN commit + 報備)」 | yes/yes/no（SVN 與 git 分流需上下文） | **未** | UserPromptSubmit hook 偵測「上GIT」字眼 → 注入展開上下文（不直接執行）|
| workflow-rules「執驗上P」 | 「執行→驗證→上 GIT→產 prompt」流程 | yes/yes/no（拆分時機需 LLM 判斷） | **未** | 同上，純注入展開不直接執行 |

### 處理優先級

中。本項屬「降低 token 消耗的絕對原則」落實 — 收益隨 session 數累積。建議 Wave 6 收尾後新開 session 處理「強候選」（feedback-memory-path、feedback-no-test-to-svn）。

### 2026-04-28 處理紀錄

2 條強候選已落地（[plans/stage-f-transient-bachman.md](../../../plans/stage-f-transient-bachman.md)）：
- `feedback-memory-path` → `hooks/wg_pretool_guards.py:check_memory_path_block` (PreToolUse Write/Edit)
- `feedback-no-test-to-svn` → `hooks/wg_pretool_guards.py:check_svn_test_block` (PreToolUse Bash)
- 測試：`tests/test_pretool_path_block.py` + `tests/test_pretool_bash_block.py`（25/25 PASS）
- atom 補「## 已 hook 化」段；hook 訊息指回 atom 補語境（hook 不取代 atom）

**其餘 5 條由本議題後續評估**（不限制下個 session）：feedback-global-install / preferences「上GIT」/ workflow-rules「執驗上P」/ 已 hook 化的 fix-on-discovery + fix-escalation。

---

## 議題 #7（Wave 3b 待補）：probe burst 路徑寫死的根因 commit 追溯

**緣由**：議題 #2 列出「為什麼路徑會寫錯」未追完。需 `git log -- hooks/workflow-guardian.py` 加 `-S 'vector-service.py'` 找首次出現 commit，判斷是 typo 還是中間搬目錄漏改。

**處理優先級**：低，列入 Wave 6 收尾文件即可，不必另開 session。
