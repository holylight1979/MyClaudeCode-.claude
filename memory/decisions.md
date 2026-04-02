# 全域決策

- Scope: global
- Confidence: [固]
- Trigger: 全域決策, workflow, guardian, hooks, MCP, 記憶系統決策, 記憶系統架構, 記憶系統, 原子記憶, atom memory, 決策
- Last-used: 2026-04-02
- Confirmations: 120
- Related: decisions-architecture

## 知識

### 核心架構
- [固] 雙 LLM：Claude Code（雲端決策）+ Ollama（本地語意處理）
- [固] 6 hook 事件全由 workflow-guardian.py 統一處理
- [固] 專案自治層：每專案 `{project_root}/.claude/memory/` + project_hooks.py delegate
- [固] Project Registry：SessionStart 自動註冊，跨專案發現

### 記憶檢索
- [固] UserPromptSubmit: Intent 分類 → Trigger 匹配 → Vector Search → Ranked Merge → additionalContext
- [固] 降級順序：Ollama 不可用 → 純 keyword | Vector Service 掛 → graceful fallback
- [固] 索引 2 層：global → project，`**/*.md` 遞迴掃描 + `_` 前綴目錄跳過

### 回應捕獲
- [固] SessionEnd 全量掃描 + Stop hook 逐輪增量萃取，共用 _spawn_extract_worker()
- [固] 萃取結果一律 [臨]，由 Confirmations 計數驅動後續晉升
- [固] SessionEnd 萃取由 extract-worker.py detached subprocess 執行（hook timeout 不足）

### V3 三層即時管線
- [觀] Stop async hook（quick-extract.py）→ qwen3:1.7b 快篩 5s → hot_cache.json → systemMessage
- [觀] PostToolUse mid-turn injection: 讀 hot cache → additionalContext 即時注入（同 turn 內可見）
- [觀] UserPromptSubmit hot cache 快速路徑: 優先讀 hot cache → 命中則減少 vector search 依賴
- [觀] deep extract（extract-worker.py）完成後覆寫 hot cache，重置 injected=False

### SessionStart 風暴修復
- [觀] SessionStart 去重: 同 cwd 60s 內 active state → 複用（resume 合併，startup 跳過 vector init）
- [觀] 孤兒清理分層 TTL: prompt_count=0 working→10m, prompt_count>0 working→30m, done→24h
- [觀] Vector service 非阻塞: fire-and-forget subprocess + vector_ready.flag

### 跨 Session 鞏固
- [固] 自動晉升 [臨]→[觀]：Confirmations ≥ 20 時 SessionEnd 自動執行
- [固] [觀]→[固] 晉升：4+ sessions 命中 → 建議晉升（不自動執行，需使用者同意）

### Episodic
- [固] SessionEnd 自動生成，TTL 24d，靠 vector search 發現（不列入 MEMORY.md）
- [固] 門檻：modified_files ≥ 1 且 session ≥ 2 分鐘；純閱讀 ≥ 5 檔也生成

### 品質機制
- [固] Context Budget：additionalContext 硬上限 3000 tokens，超額按 ACT-R activation truncate
- [固] Write Gate：品質閘門，dedup 0.80，使用者明確指示時跳過
- [固] 衝突偵測：SessionEnd 對修改 atoms 做向量搜尋，寫入 episodic 警告
- [固] 自我迭代精簡為 3 條：品質函數（Hook）、證據門檻（Claude）、震盪偵測（Hook）
- [固] 自我迭代自動化：SessionEnd 衰減分數掃描 + [臨]→[觀] 自動晉升（Confirmations ≥ 20）+ 震盪狀態跨 Session 持久化
- [固] 覆轍偵測：episodic 寫入覆轍信號（same_file_3x / retry_escalation）→ SessionStart 掃描跨 session 重複 → 注入 [Guardian:覆轍] 警告
- [固] AIDocs 內容閘門：PostToolUse 偵測 _AIDocs/ 下暫時性檔名（Plan/TODO/Roadmap/Draft 等）→ additionalContext 警告（不硬擋）
- [固] 反向參照自動修復：SessionEnd 呼叫 `atom-health-check.py --fix-refs`（全域+專案層），冪等去重，10s timeout

### Wisdom Engine
- [固] 2 硬規則（touches_arch OR file_count>threshold → plan; file_count>2 AND is_feature → confirm）
- [固] 冷啟動零 token，注入上限 ≤90 tokens，lazy import + graceful fallback

### Fix Escalation
- [固] 同一問題修正第 2 次起 → 6 Agent 精確修正會議
- [固] Guardian 自動偵測 retry_count ≥ 2 → 注入信號

## 行動

- 記憶寫入走 write-gate 品質閘門
- 向量搜尋 fallback：Ollama → sentence-transformers → keyword
- Guardian 閘門最多阻止 2 次，第 3 次強制放行

