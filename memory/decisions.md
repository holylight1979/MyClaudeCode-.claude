# 全域決策

- Scope: global
- Confidence: [固]
- Trigger: 全域決策, 工具, 工作流, workflow, guardian, hooks, MCP, 記憶系統
- Last-used: 2026-03-13
- Confirmations: 35
- Type: decision

## 知識

### 核心架構
- [固] 原子記憶 V2.11：Hybrid RECALL + Ranked Search + 回應捕獲（僅 SessionEnd）+ 跨 Session 鞏固（簡化計數）+ Write Gate + 自我迭代（3 條精簡）+ Wisdom Engine（硬規則+反思校準）+ 檢索強化 + Context Budget + 衝突偵測 + Atom 健康度
- [固] 雙 LLM：Claude Code（雲端決策）+ Ollama qwen3（本地語意處理）
- [固] 6 hook 事件全由 workflow-guardian.py 統一處理（SessionStart/UserPromptSubmit/PostToolUse/PreCompact/Stop/SessionEnd）

### 記憶檢索管線（V2.3 起）
- [固] UserPromptSubmit: Intent 分類（qwen3:1.7b）→ Trigger 匹配 → Vector Search → Ranked Merge → additionalContext
- [固] 降級順序：Ollama 不可用 → 純 keyword | Vector Service 掛 → graceful fallback
- [固] 索引 2 層：global → project（向量發現），所有層統一 `**/*.md` 遞迴掃描 + `_` 前綴目錄跳過

### 回應捕獲（V2.4→V2.11）
- [固] V2.11: 廢除逐輪萃取（per_turn_enabled: false），僅保留 SessionEnd 全 transcript 萃取
- [固] V2.11: 情境感知萃取（依 session intent 調整 prompt：build/debug/design/recall）
- [固] V2.11: 跨 Session 觀察（vector search top_k=5, min_score=0.75 → 2+ sessions 命中生成觀察段落）
- [固] SessionEnd 萃取：同步掃描全 transcript（≤20000 chars, 5 items）
- [固] 萃取結果一律 [臨]，由 Confirmations 計數驅動後續晉升
- [固] V2.5: 萃取 prompt 可操作性標準、知識類型 6 種、format:json、Write Gate CJK-aware

### 跨 Session 鞏固（V2.4→V2.11 簡化）
- [固] V2.11: 廢除自動晉升 [臨]→[觀]，改為 Confirmations +1 簡單計數
- [固] 4+ sessions 命中 → 建議晉升（不自動執行），統一 dedup 閾值 0.80
- [固] 結果寫入 episodic atom「跨 Session 觀察」段落

### Episodic atom
- [固] SessionEnd 自動生成，TTL 24d，存放於 memory/episodic/（不進 git）
- [固] 門檻：modified_files ≥ 1 且 session 時長 ≥ 2 分鐘
- [固] 不列入 MEMORY.md index，靠 vector search 發現

### 基礎設施
- [固] Vector Service @ localhost:3849 | Dashboard @ localhost:3848
- [固] Ollama models: qwen3-embedding（embedding）+ qwen3:1.7b（萃取/分類）
- [固] Vector DB: LanceDB（此電腦支援 AVX2，LanceDB 效能穩定）
- [固] search_min_score: 0.65（完整版 embedding 精確度足夠）
- [固] MCP 傳輸格式：JSONL，protocolVersion 2025-11-25
- [固] _call_ollama_generate: num_predict=2048, timeout=120s（qwen3 thinking mode 需 ~30s on GTX 1050 Ti）
- [固] V2.4 萃取改用 extract-worker.py 獨立子 process（hook 有 3s timeout，萃取需 ~30s）

### 自我迭代（V2.6→V2.11）
- [固] V2.11: 精簡為 3 條核心原則：品質函數（Hook）、證據門檻（Claude）、震盪偵測（Hook）
- [固] 定期檢閱：SessionStart 檢查 episodic 計數 → 提醒掃描近期 patterns

### Wisdom Engine（V2.8→V2.11）
- [固] V2.11: 移除因果圖（CausalGraph class + causal_graph.json），冷啟動零邊，維護成本>收益
- [固] V2.11: 情境分類器改為 2 條硬規則（file_count+is_feature → confirm; touches_arch+file_count → plan）
- [固] V2.11: 反思引擎新增 over_engineering_rate（同檔 Edit 2+ 次）+ silence_accuracy（held_back 追蹤）
- [固] V2.11: Bayesian 權重校準（architecture 連續 3+ 失敗 → 提升 arch 敏感度）
- [固] guardian lazy import + graceful fallback，冷啟動零 token，注入上限 ≤90 tokens

### V2.11 新增機制
- [固] Context Budget：additionalContext 硬上限 3000 tokens，超額按 ACT-R activation 由低到高 truncate
- [固] 衝突偵測自動化：SessionEnd 對修改 atoms 做向量搜尋（score 0.60-0.95），寫入 episodic 衝突警告
- [固] PostToolUse 品質追蹤：同檔 Edit 2+ 次 → reverted_count，SessionEnd 寫入 reflection_metrics
- [固] Atom 健康度工具：atom-health-check.py（Related 完整性 + 懸空引用清除 + 過期掃描）
- [固] .claude/rules/ 模組化：CLAUDE.md 瘦身至 ~50 行，4 個規則檔自動載入
- [固] 環境清理：shell-snapshots/debug/workflow 300+ 垃圾檔案清除 + cleanup-old-files.py 定期工具

### 記憶檢索強化（V2.9）
- [固] Project-Aliases：MEMORY.md 加 `> Project-Aliases:` 行，跨專案掃描先比對 aliases → 注入全文
- [固] Related-Edge Spreading：`spread_related()` BFS depth=1，沿 Related 邊帶出相關 atoms
- [固] ACT-R Activation Scoring：`B_i = ln(Σ t_k^{-0.5})`，access.json 保留最近 50 筆，高分優先注入
- [固] Blind-Spot Reporter：三重空判斷（matched + injected + alias 全空）→ 注入 `[Guardian:BlindSpot]`

### Session 全軌跡追蹤（V2.10）
- [固] Read Tracking：PostToolUse 攔截 Read tool，去重記錄 accessed_files（同檔只記首次）
- [固] VCS Query Capture：PostToolUse 攔截 Bash tool，regex 匹配 git/svn log/blame/show/diff
- [固] Episodic 閱讀軌跡：`_build_read_tracking_section()` 生成 `## 閱讀軌跡` section（最多 30 檔 + 10 筆版控查詢）
- [固] 純閱讀 Session：accessed_files ≥ 5 且無修改時也生成 episodic atom
- [固] 暫存區管理：`memory/_staging/` 存放續接 prompt 等臨時檔案，.gitignore 排除，SessionEnd 提醒清理

### 歷史決策
- [固] 記憶檢索統一用 Python，已移除 Node.js memory-v2（2026-03-05 退役）
- [固] Stop hook 只保留 Guardian 閘門，移除 Discord 通知

## 行動

- 記憶寫入走 write-gate 品質閘門
- 向量搜尋 fallback 順序：Ollama → sentence-transformers → keyword
- Guardian 閘門最多阻止 2 次，第 3 次強制放行

## 演化日誌

- 2026-03-05: 合併自家中 V2.4 — 帶入回應捕獲、跨 Session 鞏固、episodic 改進
- 2026-03-05: Vector DB 保留 LanceDB（此電腦支援 AVX2），embedding 保留 qwen3-embedding 完整版
- 2026-03-05: search_min_score 保持 0.65（完整版 embedding 不需降低）
- 2026-03-05: 6 hook 事件（不含 PreToolUse），indexer.py 加入 additional_atom_dirs + episodic/ 子目錄掃描
- 2026-03-05: fix: workflow-guardian stdout/stderr 強制 UTF-8（Windows cp950 導致中文亂碼）
- 2026-03-05: feat: 專案級 episodic（CWD 對應 project 層時，episodic 存到該 project memory）
- 2026-03-05: fix: _call_ollama_generate num_predict 500→2048, timeout 3→120s（qwen3 thinking mode 修復）
- 2026-03-06: fix: V2.4 萃取改用 detached subprocess（extract-worker.py），解決 sys.exit + hook 3s timeout 雙殺問題，萃取首次成功
- 2026-03-06: feat: V2.5 寫入品質強化 — 萃取 prompt 重寫（可操作性標準）、6 知識類型、150 chars 上限、format:json、Write Gate 可操作性評分、CJK patterns
- 2026-03-11: feat: V2.8 升級完成（3 sessions）— Wisdom Engine + 自我迭代 V2.6 + 品質回饋 V2.7 + Guardian 增量合併 + SPEC/文件全面更新
- 2026-03-11: feat: V2.9 S2 — Related-Edge Spreading（多跳檢索 depth=1）+ ACT-R Activation Scoring（時間加權排序 + .access.json）
- 2026-03-11: feat: V2.9 S3 完成 — 整合測試通過 + SPEC §十四 + 版號升級 V2.8→V2.9
- 2026-03-11: feat: V2.10 — Session 全軌跡追蹤（Read Tracking + VCS Query Capture + 閱讀軌跡 section + 純閱讀 episodic + _staging 暫存區管理）
- 2026-03-13: feat: 引入同事改進 — indexer.py 遞迴掃描所有層（子目錄 atom 可被索引）+ /upgrade skill（環境升級比對工具）
- 2026-03-13: feat: V2.11 全面升級（4 波 10 sessions）— 精簡（砍逐輪萃取/因果圖/自動晉升/自我迭代8→3）+ 品質（衝突偵測/反思校準/Atom健康度）+ 模組化（rules/+Context Budget）+ 環境清理
