# 全域決策

- Scope: global
- Confidence: [固]
- Trigger: 全域決策, workflow, guardian, hooks, MCP, 記憶系統決策, 記憶系統架構
- Last-used: 2026-03-24
- Confirmations: 74
- Type: decision
- Related: decisions-architecture

## 知識

### 核心架構
- [固] 原子記憶 V2.17：Hybrid RECALL + Ranked Search + 回應捕獲（全量+逐輪） + 跨 Session 鞏固 + Write Gate + 自我迭代自動化 + Wisdom Engine + 檢索強化 + Context Budget + 衝突偵測 + Fix Escalation + Failures 自動化 + Token Diet + 覆轍偵測
- [固] 雙 LLM：Claude Code（雲端決策）+ Ollama（本地語意處理）
- [固] 6 hook 事件全由 workflow-guardian.py 統一處理

### 記憶檢索
- [固] UserPromptSubmit: Intent 分類 → Trigger 匹配 → Vector Search → Ranked Merge → additionalContext
- [固] 降級順序：Ollama 不可用 → 純 keyword | Vector Service 掛 → graceful fallback
- [固] 索引 2 層：global → project，`**/*.md` 遞迴掃描 + `_` 前綴目錄跳過

### 回應捕獲
- [固] SessionEnd 全量掃描 + Stop hook 逐輪增量萃取，共用 _spawn_extract_worker()
- [固] 萃取結果一律 [臨]，由 Confirmations 計數驅動後續晉升
- [固] SessionEnd 萃取由 extract-worker.py detached subprocess 執行（hook timeout 不足）

### 跨 Session 鞏固
- [固] 廢除自動晉升 [臨]→[觀]，改為 Confirmations +1 簡單計數
- [固] 4+ sessions 命中 → 建議晉升（不自動執行）

### Episodic
- [固] SessionEnd 自動生成，TTL 24d，靠 vector search 發現（不列入 MEMORY.md）
- [固] 門檻：modified_files ≥ 1 且 session ≥ 2 分鐘；純閱讀 ≥ 5 檔也生成

### 品質機制
- [固] Context Budget：additionalContext 硬上限 3000 tokens，超額按 ACT-R activation truncate
- [固] Write Gate：品質閘門，dedup 0.80，使用者明確指示時跳過
- [固] 衝突偵測：SessionEnd 對修改 atoms 做向量搜尋，寫入 episodic 警告
- [固] 自我迭代精簡為 3 條：品質函數（Hook）、證據門檻（Claude）、震盪偵測（Hook）
- [固] V2.16 自我迭代自動化：SessionEnd 衰減分數掃描 + [臨]→[觀] 自動晉升（Confirmations ≥ 20）+ 震盪狀態跨 Session 持久化
- [固] V2.17 覆轍偵測：episodic 寫入覆轍信號（same_file_3x / retry_escalation）→ SessionStart 掃描跨 session 重複 → 注入 [Guardian:覆轍] 警告
- [固] AIDocs 內容閘門：PostToolUse 偵測 _AIDocs/ 下暫時性檔名（Plan/TODO/Roadmap/Draft 等）→ additionalContext 警告（不硬擋）

### Wisdom Engine
- [固] 2 硬規則（file_count+is_feature → confirm; touches_arch+file_count → plan）
- [固] 冷啟動零 token，注入上限 ≤90 tokens，lazy import + graceful fallback

### Fix Escalation
- [固] 同一問題修正第 2 次起 → 6 Agent 精確修正會議
- [固] Guardian 自動偵測 retry_count ≥ 2 → 注入信號

### 歷史決策
- [固] 記憶檢索統一用 Python（Node.js memory-v2 已於 2026-03-05 退役）
- [固] Stop hook 只保留 Guardian 閘門

## 行動

- 記憶寫入走 write-gate 品質閘門
- 向量搜尋 fallback：Ollama → sentence-transformers → keyword
- Guardian 閘門最多阻止 2 次，第 3 次強制放行

## 演化日誌

> 詳細版本演進：`_reference/decisions-history.md`

- 2026-03-19: 精修拆分 — 技術細節移至 decisions-architecture，歷史移至 _reference
- 2026-03-22: V2.16 自我迭代自動化決策記錄
- 2026-03-22: V2.17 覆轍偵測 — 寄生式跨 session 重複失敗模式偵測
- 2026-03-23: V2.17 合併升級至公司電腦
