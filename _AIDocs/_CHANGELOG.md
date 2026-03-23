# 變更記錄

> 保留最近 ~8 筆。舊條目移至 `_CHANGELOG_ARCHIVE.md`。

---

| 日期 | 變更 | 涉及檔案 |
|------|------|---------|
| 2026-03-23 | **V2.17 合併升級**：V2.16 自我迭代自動化（SessionEnd 衰減掃描 + 自動晉升 + 震盪持久化）+ V2.17 覆轍偵測（寄生式 episodic 信號 + 跨 session 掃描）+ AIDocs 內容閘門 + WebFetch Guard + PreToolUse hooks + scripts/ 目錄 + misdiagnosis-verify-first atom | `hooks/workflow-guardian.py`, `settings.json`, `rules/aidocs.md`, `memory/decisions*.md`, `CLAUDE.md`, `README.md`, `Install-forAI.md`, `_AIDocs/*.md` |
| 2026-03-19 | **V2.15 定義版本**：全文件版本號 V2.12→V2.15 統一。移除內嵌版本標註（已是標準功能的 V2.x 標籤）。README 版本歷史補 V2.13/V2.14/V2.15。Architecture/DocIndex/Project_File_Tree 版本清理。CHANGELOG 補完 V2.12~V2.14 間缺漏變更 | `CLAUDE.md`, `README.md`, `Install-forAI.md`, `_AIDocs/*.md`, `memory/decisions*.md`, `rules/session-management.md` |
| 2026-03-19 | **V2.14 Token Diet**：`_strip_atom_for_injection()` 注入前 strip 9 種 metadata + 行動/演化日誌。SessionEnd 從 byte_offset 跳已萃取段。cross-session lazy search 預篩。省 ~1550 tok/session | `hooks/workflow-guardian.py`, `hooks/extract-worker.py`, `memory/MEMORY.md`, `workflow/config.json` |
| 2026-03-19 | **V2.13 Failures 自動化系統**：Guardian 偵測失敗關鍵字 → detached extract-worker 萃取失敗模式 → 三維路由自動寫入對應 failure atom | `hooks/extract-worker.py`, `hooks/workflow-guardian.py`, `workflow/config.json`, `memory/failures/` |
| 2026-03-19 | **atom 精準拆分+設定精修**：toolchain-ollama 獨立拆分 + workflow-icld 拆分 + trigger 瘦身 + failures 拆分子 atoms + GIT 流程去重 + 設定檔去重/瘦身/統一管理 | `memory/*.md`, `workflow/config.json` |
| 2026-03-19 | **vector service timeout 修正**：冷啟動 7.5s 但 caller timeout 2-5s，調整 timeout + 預熱 | `hooks/workflow-guardian.py`, `tools/memory-vector-service/` |
| 2026-03-18 | **V2.12 逐輪增量萃取**：Stop hook per-turn extraction（byte_offset + cooldown 120s + PID guard）+ 萃取 dedup 統一 0.65 + intent 選取 bug 修正 | `hooks/extract-worker.py`, `hooks/workflow-guardian.py`, `workflow/config.json` |
| 2026-03-18 | **注入精準化**：AIDocs keyword 重新設計 + IDE 標籤過濾 + keyword boundary 防誤匹配 + `/atom-debug` skill | `_AIDocs/_INDEX.md`, `hooks/workflow-guardian.py`, `commands/atom-debug.md` |
| 2026-03-17 | **V2.12 Fix Escalation Protocol**：同一問題修正第 2 次起 6 Agent 會議制 + Guardian hook 自動偵測 retry≥2 | `commands/fix-escalation.md`, `hooks/workflow-guardian.py`, `rules/session-management.md` |
_(舊條目已移至 `_CHANGELOG_ARCHIVE.md`。最近移入：2026-03-13 自檢修復 + Dual-Backend 文件)_
