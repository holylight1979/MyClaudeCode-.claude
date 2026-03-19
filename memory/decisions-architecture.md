# 架構技術細節

- Scope: global
- Confidence: [固]
- Trigger: 架構細節, vector service, ollama backend, extraction, ACT-R, episodic tracking, context budget
- Last-used: 2026-03-19
- Confirmations: 62
- Type: decision
- Tags: architecture, infrastructure
- Related: decisions, toolchain

## 知識

### 回應捕獲技術細節
- [固] 逐輪增量：Stop hook 觸發，byte_offset 增量讀取，cooldown 120s + PID 併發保護 + min_new_chars 500
- [固] per_turn 模式：max_chars=4000, max_items=3, skip_cross_session=true，結果回寫 state knowledge_queue
- [固] SessionEnd 全量：≤20000 chars, 5 items，自然 dedup per-turn 已萃取項目
- [固] 情境感知萃取：依 session intent 調整 prompt（build/debug/design/recall）
- [固] 跨 Session 觀察：vector search top_k=5, min_score=0.75 → 2+ sessions 命中生成觀察段落
- [固] 萃取 prompt：可操作性標準、知識類型 6 種、format:json、Write Gate CJK-aware

### 基礎設施
- [固] Vector Service @ localhost:3849 | Dashboard @ localhost:3848
- [固] Ollama Dual-Backend: rdchat qwen3.5（主力萃取, pri=1）+ local qwen3:1.7b（fallback, pri=2）+ qwen3-embedding
- [固] LanceDB（AVX2 支援），search_min_score: 0.65
- [固] MCP 傳輸格式：JSONL，protocolVersion 2025-11-25
- [固] _call_ollama_generate: num_predict=2048, timeout=120s（qwen3 thinking ~30s on GTX 1050 Ti）
- [固] extract-worker think=true + num_predict=8192（rdchat），detached subprocess

### 檢索強化（V2.9）
- [固] Project-Aliases：MEMORY.md `> Project-Aliases:` 行，跨專案掃描
- [固] Related-Edge Spreading：BFS depth=1 沿 Related 邊帶出相關 atoms
- [固] ACT-R Activation：`B_i = ln(Σ t_k^{-0.5})`，access.json 最近 50 筆
- [固] Blind-Spot Reporter：matched + injected + alias 全空 → `[Guardian:BlindSpot]`

### Session 軌跡追蹤（V2.10）
- [固] Read Tracking：PostToolUse 攔截 Read，去重記錄（同檔只記首次，最多 30 檔）
- [固] VCS Query Capture：regex 匹配 git/svn log/blame/show/diff（最多 10 筆）
- [固] 純閱讀 Session：accessed_files ≥ 5 且無修改 → 也生成 episodic
- [固] 暫存區：`projects/{slug}/memory/_staging/`，每個專案獨立

### Token Diet（V2.14）
- [固] `_strip_atom_for_injection()`：注入前 regex strip 9 種 metadata（Scope/Type/Trigger/Last-used/Created/Confirmations/Tags/TTL/Expires-at）+ `## 行動` / `## 演化日誌` section。保留 Confidence + Related
- [固] Episodic 閱讀軌跡壓縮：`_build_read_tracking_section()` 改為摘要格式（`讀 N 檔: area (count)`），不列完整路徑
- [固] SessionEnd 從 state `byte_offset` 開始讀（overlap=1000），跳過 per-turn 已處理段
- [固] Cross-session lazy search：word_overlap ≥ 0.30 預篩，新 item 無匹配則跳過 vector search
- [固] 移除 extract-worker pre-filter dedup 注入（post-filter 0.65 已足夠）
- [固] failure weak_min_match 2→3（減少日常用語誤觸發）
- [固] 實測省量：注入側 ~350 tok/session + 萃取側 ~1200 tok/session

### Wisdom Engine 細節
- [固] 反思指標：over_engineering_rate（同檔 Edit 2+次）+ silence_accuracy（held_back 追蹤）
- [固] Bayesian 校準：architecture 連續 3+ 失敗 → 提升 arch 敏感度
- [固] PostToolUse 品質追蹤：同檔 Edit 2+ → reverted_count → reflection_metrics

### 環境維護
- [固] rules/ 模組化：CLAUDE.md ~50 行，4 規則檔自動載入
- [固] Atom 健康度：atom-health-check.py（Related 完整性 + 懸空引用 + 過期掃描）
- [固] 環境清理：cleanup-old-files.py 定期清除 shell-snapshots/debug/workflow

## 行動

- 開發/調修記憶系統時載入此 atom
- 修改 hook/tool 前確認此處記載的參數值
- 新增基礎設施時更新對應段落

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-19 | 從 decisions.md 拆出技術細節 | 系統精修 |
| 2026-03-19 | 新增 Token Diet V2.14 段落（7 條 [固]） | V2.14 驗證 |
