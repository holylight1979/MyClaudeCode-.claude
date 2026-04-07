# 全域決策

- Scope: global
- Confidence: [固]
- Trigger: 決策, 記憶系統, 原子記憶, guardian, hooks, MCP, 架構細節, vector service, context budget
- Last-used: 2026-04-07
- Confirmations: 135
- Related: toolchain, toolchain-ollama

## 知識

### 核心架構
- [固] 雙 LLM：Claude Code（雲端決策）+ Ollama（本地語意處理）
- [固] 專案自治層：每專案 `{project_root}/.claude/memory/` + project_hooks.py delegate
- [固] 管線概覽：Intent→Trigger→Vector→Section→Budget→注入（詳見 _reference/internal-pipeline.md）
- [固] Project-Aliases：MEMORY.md `> Project-Aliases:` 行，跨專案掃描

### V3 三層即時管線
- [觀] Stop async hook（quick-extract.py）→ qwen3:1.7b 快篩 5s → hot_cache.json → systemMessage
- [觀] PostToolUse mid-turn injection: 讀 hot cache → additionalContext 即時注入（同 turn 內可見）
- [觀] UserPromptSubmit hot cache 快速路徑: 優先讀 hot cache → 命中則減少 vector search 依賴
- [觀] deep extract（extract-worker.py）完成後覆寫 hot cache，重置 injected=False

### SessionStart 風暴修復
- [觀] SessionStart 去重: 同 cwd 60s 內 active state → 複用（resume 合併，startup 跳過 vector init）
- [觀] 孤兒清理分層 TTL: prompt_count=0 working→10m, prompt_count>0 working→30m, done+已同步→1h, done+待同步→4h
- [觀] 清理觸發點: SessionStart + SessionEnd 雙觸發（避免非正常結束時殘留累積）
- [觀] Vector service 非阻塞: fire-and-forget subprocess + vector_ready.flag

### 跨 Session 鞏固
- [固] [觀]→[固] 晉升：4+ sessions 命中 → 建議晉升（不自動執行，需使用者同意）

### 品質機制
- [固] 自我迭代精簡為 3 條：品質函數（Hook）、證據門檻（Claude）、震盪偵測（Hook）

### Fix Escalation
- [固] 同一問題修正第 2 次起 → 6 Agent 精確修正會議
- [固] Guardian 自動偵測 retry_count ≥ 2 → 注入信號

## 行動

- 記憶寫入走 write-gate 品質閘門
- 向量搜尋 fallback：Ollama → sentence-transformers → keyword
- Guardian 閘門最多阻止 2 次，第 3 次強制放行

