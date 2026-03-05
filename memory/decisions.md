# 全域決策

- Scope: global
- Confidence: [固]
- Trigger: 全域決策, 工具, 工作流, workflow, guardian, hooks, MCP, 記憶系統
- Last-used: 2026-03-05
- Confirmations: 12
- Type: decision

## 知識

### 核心架構
- [固] 原子記憶 V2.4：Hybrid RECALL + Ranked Search + 回應捕獲 + 跨 Session 鞏固 + Workflow Guardian
- [固] 雙 LLM：Claude Code（雲端決策）+ Ollama qwen3（本地語意處理）
- [固] 6 hook 事件全由 workflow-guardian.py 統一處理（SessionStart/UserPromptSubmit/PostToolUse/PreCompact/Stop/SessionEnd）

### 記憶檢索管線（V2.3 起）
- [固] UserPromptSubmit: Intent 分類（qwen3:1.7b）→ Trigger 匹配 → Vector Search → Ranked Merge → additionalContext
- [固] 降級順序：Ollama 不可用 → 純 keyword | Vector Service 掛 → graceful fallback
- [固] 索引 2 層：global → project（向量發現）

### 回應捕獲（V2.4）
- [固] 逐輪萃取：UserPromptSubmit 非同步讀取上一輪 assistant 回應，qwen3:1.7b 萃取知識（≤3000 chars, 2 items）
- [固] SessionEnd 補漏：同步掃描全 transcript（≤20000 chars, 5 items）
- [固] 萃取結果一律 [臨]，經跨 Session 鞏固後自動晉升

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
