# 架構決策

- Scope: global
- Confidence: [固]
- Trigger: 架構, hooks, pipeline, guardian, SessionStart, hot cache, extract-worker, vector service
- Last-used: 2026-04-10
- Confirmations: 0
- Related: decisions, toolchain-ollama

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

## 行動

- 動到 hooks/pipeline/guardian/vector service 前載入此 atom
- 修改 workflow-guardian.py、quick-extract.py、extract-worker.py 前對照此處設計
- SessionStart 相關 bug 排查先檢查這裡的去重 + 孤兒清理規則
