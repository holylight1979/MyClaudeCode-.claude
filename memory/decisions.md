# 全域決策

- Scope: global
- Confidence: [固]
- Trigger: 全域決策, 工具, 工作流, workflow, guardian, hooks, MCP, 記憶系統
- Last-used: 2026-03-11
- Confirmations: 30
- Type: decision

## 知識

### 核心架構
- [固] 原子記憶 V2.9：Hybrid RECALL + Ranked Search + 回應捕獲 + 跨 Session 鞏固 + Write Gate + 自我迭代 + Wisdom Engine + 檢索強化（Project-Aliases / Related-Edge Spreading / ACT-R Activation / Blind-Spot Reporter）
- [固] 雙 LLM：Claude Code（雲端決策）+ Ollama qwen3（本地語意處理）
- [固] 6 hook 事件全由 workflow-guardian.py 統一處理（SessionStart/UserPromptSubmit/PostToolUse/PreCompact/Stop/SessionEnd）

### 記憶檢索管線（V2.3 起）
- [固] UserPromptSubmit: Intent 分類（qwen3:1.7b）→ Trigger 匹配 → Vector Search → Ranked Merge → additionalContext
- [固] 降級順序：Ollama 不可用 → 純 keyword | Vector Service 掛 → graceful fallback
- [固] 索引 2 層：global → project（向量發現）

### 回應捕獲（V2.4→V2.5 強化）
- [固] 逐輪萃取：UserPromptSubmit 非同步讀取上一輪 assistant 回應，qwen3:1.7b 萃取知識（≤3000 chars, 2 items）
- [固] SessionEnd 補漏：同步掃描全 transcript（≤20000 chars, 5 items）
- [固] 萃取結果一律 [臨]，經跨 Session 鞏固後自動晉升
- [固] V2.5: 萃取 prompt 加入可操作性標準（actionable + specific + reusable）+ negative examples
- [固] V2.5: 知識類型 4→6（+decision, +preference），content 上限 80→150 chars
- [固] V2.5: Ollama API 加 format:json（減少 JSON 解析失敗），dedup 前綴 40→60 chars
- [固] V2.5: Write Gate 加入可操作性評分（+0.15），CJK-aware patterns（中文無空格）

### 跨 Session 鞏固（V2.4 Phase 3）
- [固] SessionEnd 時對 knowledge_queue 做向量搜尋（min_score 0.75）
- [固] 2+ sessions 命中 → 自動晉升 [臨]→[觀]；4+ sessions → 建議晉升 [觀]→[固]
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

### 自我迭代（V2.6）
- [固] 8 條核心規則：品質函數、收斂優先、證據門檻、淘汰勇氣、震盪偵測、成熟度感知、三維平衡、演進邊界
- [固] 定期檢閱：SessionStart 檢查 episodic 計數 → 提醒掃描近期 patterns → 收攏為 [觀]/[固]

### 品質回饋與成熟度（V2.7）
- [固] Output quality check（PostToolUse）、iteration metrics（SessionEnd）、oscillation detection、maturity phase
- [固] 成熟度三階段：learning(<15) → stable(15-50) → mature(>50)，依 episodic 數量判斷

### Wisdom Engine（V2.8）
- [固] 三力架構：因果圖（BFS depth=2）+ 情境分類器（加權評分）+ 反思引擎（滑動窗口統計）
- [固] wisdom_engine.py ~250 行，guardian lazy import + graceful fallback
- [固] 冷啟動零 token，注入上限 ≤90 tokens
- [固] 因果圖 Bayesian 更新：hit → ×0.9+0.1, miss → ×0.95, <0.3 自動移除

### 記憶檢索強化（V2.9）
- [固] Project-Aliases：MEMORY.md 加 `> Project-Aliases:` 行，跨專案掃描先比對 aliases → 注入全文
- [固] Related-Edge Spreading：`spread_related()` BFS depth=1，沿 Related 邊帶出相關 atoms
- [固] ACT-R Activation Scoring：`B_i = ln(Σ t_k^{-0.5})`，access.json 保留最近 50 筆，高分優先注入
- [固] Blind-Spot Reporter：三重空判斷（matched + injected + alias 全空）→ 注入 `[Guardian:BlindSpot]`

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
