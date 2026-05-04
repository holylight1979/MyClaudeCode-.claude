# 架構決策

- Scope: global
- Confidence: [觀]
- Trigger: 架構, hooks, pipeline, guardian, SessionStart, hot cache, extract-worker, vector service
- Last-used: 2026-05-04
- Confirmations: 0
- ReadHits: 21
- Related: decisions, toolchain-ollama, feedback-pointer-atom

## 印象

- 雙 LLM 分工（CC 雲端決策 + Ollama 本地處理）→ _AIDocs/Architecture.md
- 三層即時管線（Stop async → quick-extract → hot_cache → PostToolUse 同 turn 注入）→ _AIDocs/DevHistory/memory-pipeline.md
- SessionStart 風暴修復（去重 + 分層 TTL 孤兒清理 + vector 非阻塞）→ _AIDocs/DevHistory/session-mgmt.md
- 專案自治層 + Project-Aliases 跨專案掃描 → _AIDocs/Architecture.md
- 管線概覽（Intent→Trigger→Vector→Section→Budget→注入）→ memory/_reference/internal-pipeline.md（hook 寫死引用）

## 行動

- 動到 hooks/pipeline/guardian/vector 前先讀 _AIDocs/Architecture.md 對照當前實況（避免照 atom 過時印象動手）
- SessionStart bug 排查 → 先看 session-mgmt.md 的去重 + 孤兒清理規則
- 重大架構決策（新增 hook 事件 / 改 dispatcher 邊界）→ 同步更新此 atom 印象 + Architecture.md 子節
