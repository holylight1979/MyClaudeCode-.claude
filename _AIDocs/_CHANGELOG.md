# 變更記錄

> 保留最近 ~8 筆。舊條目移至 `_CHANGELOG_ARCHIVE.md`。

---

## 2026-04-02 V3.0 三層即時管線 + 文件全面升級
- 新增 hot_cache.json 快篩快取機制（quick-extract.py → PostToolUse/UPS 即時注入）
- 新增 SessionStart 去重（同 cwd 60s 內複用 state）
- 新增分層孤兒清理（10m/30m/24h TTL）
- 新增 vector_ready.flag 非阻塞啟動
- 文件全面升級 V2.21 → V3.0（README, Install-forAI, Architecture, _INDEX, Project_File_Tree, 7 commands, CLAUDE.md）

| 日期 | 變更 | 涉及檔案 |
|------|------|---------|
| 2026-04-02 | **V3.0 文件全面升級**：README V3.0（標題+三欄Token表+速度效率表+架構+流程圖+Skills 17個+V3子系統+版本歷史）+ Install-forAI V3升級section + Architecture/Project_File_Tree/DocIndex/INDEX 更新 + 7 commands 移除版號標記 | `README.md`, `Install-forAI.md`, `_AIDocs/*.md`, `commands/*.md`, `CLAUDE.md` |
| 2026-04-02 | **V3 Phase1 實作：Hot Cache + Quick Extract**：新建 wg_hot_cache.py（lock+原子寫入 3 API）、quick-extract.py（Stop async hook, qwen3:1.7b 快篩→hot cache）、decisions-architecture.md Hot Cache 段落 [臨]→[觀] | `hooks/wg_hot_cache.py`(新), `hooks/quick-extract.py`(新), `memory/decisions-architecture.md` |
| 2026-04-02 | **V3 三層即時管線升級**：decisions.md 新增 V3 管線+SessionStart 風暴修復決策、decisions-architecture.md 新增 Hot Cache/Async Hook/去重技術細節、cc-hook-system.md 補充 additionalContext 可用性差異 | `memory/decisions.md`, `memory/decisions-architecture.md`, `_AIDocs/ClaudeCodeInternals/cc-hook-system.md` |
| 2026-04-01 | **atom 全面精簡 — 經歷敘述型內容歸檔**：10 個 atom 移除演化日誌段落、decisions.md 移除 5 條版本遷移敘述（V2.18~V2.21）改為 2 條現狀事實、toolchain-ollama.md A/B 完整表格改為 3 條結論、移除各處版本標籤前綴。歸檔至 `_AIDocs/DevHistory/`（3 檔）。估計省 ~1100 tok/session | `memory/*.md`（10 atoms）, `_AIDocs/DevHistory/*`（3 新檔） |
| 2026-04-01 | **原子記憶系統全面驗證 + 修正**：decisions.md 修正 4 處 + architecture 計數器歸零 + Vector DB full reindex | `memory/decisions.md`, `memory/wisdom/reflection_metrics.json` |
| 2026-03-30 | **_AIDocs V2.21 全面同步**：Architecture.md V2.17→V2.21 + Project_File_Tree 重寫 + DocIndex 更新 | `_AIDocs/Architecture.md`, `_AIDocs/Project_File_Tree.md`, `_AIDocs/DocIndex-System.md`, `_AIDocs/_INDEX.md` |
| 2026-03-30 | **全面清理 + V2.21 自治修正**：修復 2 處硬編碼 + 刪除 backups/Logs/debug + 清理孤兒 slugs | `hooks/workflow-guardian.py`, `settings.json`, `_AIDocs/`, `memory/_reference/` |
| 2026-03-30 | **Dashboard 4 修復 + 版本集中化** | `tools/workflow-guardian-mcp/server.js`, `version.json` |
| 2026-03-27 | **V2.21 Phase 7 Skills/Tools 專案層支援** | `tools/memory-audit.py`, `tools/memory-conflict-detector.py`, `commands/*.md`, `server.js` |
| 2026-03-27 | **文件版本同步 V2.21** | `README.md`, `Install-forAI.md`, `memory/_reference/*`, `memory/MEMORY.md` |
_(舊條目已移至 `_CHANGELOG_ARCHIVE.md`。最近移入：2026-03-27 V2.20/V2.21 Phase 2-3)_
