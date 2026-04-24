# 實作參數參考（從 decisions-architecture 拆出）

- Scope: global
- Confidence: [固]
- Trigger: 實作參數, SPEC_impl_params, per_turn, byte_offset, Token Diet, extract-worker, cooldown
- Last-used: 2026-03-19
- Confirmations: 0
- ReadHits: 0
- Related: decisions-architecture

> 開發/調修記憶系統時參考。`_` 前綴不被 hook 掃描，零誤注入。

## 回應捕獲技術細節
- [固] 逐輪增量：Stop hook 觸發，byte_offset 增量讀取，cooldown 120s + PID 併發保護 + min_new_chars 500
- [固] per_turn 模式：max_chars=4000, max_items=3, skip_cross_session=true，結果回寫 state knowledge_queue
- [固] SessionEnd 全量：≤20000 chars, 5 items，自然 dedup per-turn 已萃取項目
- [固] 情境感知萃取：依 session intent 調整 prompt（build/debug/design/recall）
- [固] 跨 Session 觀察：vector search top_k=5, min_score=0.75 → 2+ sessions 命中生成觀察段落
- [固] 萃取 prompt：可操作性標準、知識類型 6 種、format:json、Write Gate CJK-aware

## Token Diet
- [固] `_strip_atom_for_injection()`：注入前 regex strip 9 種 metadata（Scope/Type/Trigger/Last-used/Created/Confirmations/Tags/TTL/Expires-at）+ `## 行動` / `## 演化日誌` section。保留 Confidence + Related
- [固] Episodic 閱讀軌跡壓縮：`_build_read_tracking_section()` 改為摘要格式（`讀 N 檔: area (count)`），不列完整路徑
- [固] SessionEnd 從 state `byte_offset` 開始讀（overlap=1000），跳過 per-turn 已處理段
- [固] Cross-session lazy search：word_overlap ≥ 0.30 預篩，新 item 無匹配則跳過 vector search
- [固] 移除 extract-worker pre-filter dedup 注入（post-filter 0.65 已足夠）
- [固] failure weak_min_match 2→3（減少日常用語誤觸發）
- [固] 實測省量：注入側 ~350 tok/session + 萃取側 ~1200 tok/session

## Wisdom Engine 細節
- [固] 反思指標：over_engineering_rate（同檔 Edit 2+次）+ silence_accuracy（held_back 追蹤）
- [固] Bayesian 校準：architecture 連續 3+ 失敗 → 提升 arch 敏感度
- [固] PostToolUse 品質追蹤：同檔 Edit 2+ → reverted_count → reflection_metrics

## 自我迭代自動化（V2.16）
- [固] 衰減分數公式：`score = 0.5 * recency + 0.5 * usage`，recency = `exp(-ln2 * days / half_life)`，usage = `min(1, log10(confirmations+1) / 2)`
- [固] half_life=30d, archive_threshold=0.3（config.json `self_iteration` 區塊可調）
- [固] SessionEnd 掃描 `memory/*.md` + `memory/failures/*.md`，跳過 MEMORY.md / SPEC / `_` 前綴
- [固] [臨]→[觀] 自動晉升條件：atom Confirmations ≥ 20（promote_min_confirmations），行首 `- [臨]` → `- [固]` 直接覆寫
- [固] Archive candidates：score < 0.3 的 atoms 寫入 `_staging/archive-candidates.md`
- [固] 震盪持久化：`_save_oscillation_state()` SessionEnd 寫 `workflow/oscillation_state.json`；`_load_oscillation_warnings()` SessionStart 讀取注入 `[Guardian:Oscillation]` 警告
- [固] config.json `self_iteration` 欄位：decay_half_life_days, promote_min_confirmations, archive_score_threshold, oscillation_window, oscillation_threshold, review_interval

## 覆轍偵測（V2.17）
- [固] 寄生式設計：不新增檔案/參數/子系統，附著在 episodic atom 上
- [固] SessionEnd：`edit_counts ≥ 3` → `same_file_3x:{filename}` 信號；`retry_count ≥ 2` → `retry_escalation` 信號，寫入 episodic 的「覆轍信號:」欄位
- [固] SessionStart：`_detect_rut_patterns()` 掃描最近 N 個 episodic（共用 oscillation_window），同一信號出現 ≥ 2 sessions → 注入 `[Guardian:覆轍]`
- [固] 職責切分：session 內重試 → fix-escalation；atom 反覆修改 → 震盪偵測；跨 session 行為模式 → 覆轍偵測
