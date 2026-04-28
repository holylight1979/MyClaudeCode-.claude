# DevHistory — 開發紀錄索引

> 從各 atom / Architecture.md 精簡移出的版本演進、遷移紀錄、實測數據、穩定子系統細節。
> 供需要查閱歷史脈絡時按需閱讀，不自動注入 session context。

| # | 文件名稱 | 說明 | keywords |
|---|---------|------|----------|
| 1 | atom-evolution.md | 各 atom 演化日誌彙整 | 演化, 版本, changelog, 日期, 變更記錄 |
| 2 | version-migrations.md | 原子記憶 V2.18~V2.21 版本遷移敘述 | V2.18, V2.19, V2.20, V2.21, 遷移, migration, Phase |
| 3 | ab-test-ollama.md | Ollama Dual-Backend A/B 萃取品質實測數據（qwen3.5 vs qwen3:1.7b） | A/B, 萃取品質, qwen3, rdchat, 實測, benchmark |
| 4 | ab-test-gemma4.md | Gemma 4 vs Qwen 3.5 三輪 A/B 測試（V3.4 模型切換決策依據） | gemma4, qwen3.5, A/B, 萃取, 溫度, format bug |
| 5 | v41-journey.md | V4.1 圓桌設計與 GA 歷程 + §10 Runtime 架構（user-extract + P4 評價） | V4.1, user-extract, L0, L1, L2, session_score, evaluator |
| 6 | ollama-backend.md | Dual-Backend Ollama 退避機制（三階段 DIE + failover） | ollama, 退避, DIE, rdchat, failover |
| 7 | memory-pipeline.md | 記憶檢索管線 + 回應知識捕獲 + V3 三層即時管線 | pipeline, JIT, vector, hot_cache, 萃取, V3 |
| 8 | session-mgmt.md | SessionStart 去重 + 孤兒清理 + Merge self-heal | sessionstart, dedup, merge_into, orphan, self-heal |
| 9 | v4-layers.md | V4 專案自治層 + 三層 scope + Role-filtered JIT | scope, personal, shared, role, project-registry, JIT |
| 10 | v4-conflict.md | V4 三時段衝突偵測完整流程（Phase 5+6） | conflict, pending_review, CONTRADICT, EXTEND, write-check, pull-audit |
| 11 | wisdom-engine.md | Wisdom Engine + Fix Escalation + 跨 Session 鞏固 | wisdom, reflection, fix_escalation, 鞏固 |
| 12 | settings-config.md | settings.json 權限 + 工具鏈總覽 | settings, permissions, 權限, 工具鏈, tools |
| 13 | session-logs/ | _CHANGELOG 每條 entry 對應的完整實作紀錄（`{date}-{slug}.md`） | session log, 變更記錄詳情 |
| 14 | multi-agent-cleanup-protocol.md | 多大師協作流程通用版（CC ≥ Codex 席次設計、防 Codex 幻覺、Windows sandbox 修復、Phase 4 audit 重派、收尾 checklist） | multi-agent, codex, 大師, 協作, sandbox, audit, 監督執行 |
| 15 | memory-cleanup-2026-04/ | Memory cleanup 計畫歸檔（synthesis / follow-up issues / 8 大師報告精華） | cleanup, vector, atom, token 浪費, silent failure, 2026-04 |
| 16 | atomic-memory-evolution/ | 原子記憶 V2/V3 設計史與研究文件（搬自 memory/_reference/，2026-04-28 Stage F5 重審後）：origin / decisions-history / self-iteration / SPEC × 2 / v21 research / v3 design + insights | atom 演化, V2, V3, SPEC, research, 設計史, atomic memory origin |
