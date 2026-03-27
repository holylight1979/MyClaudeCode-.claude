# 變更記錄

> 保留最近 ~8 筆。舊條目移至 `_CHANGELOG_ARCHIVE.md`。

---

| 日期 | 變更 | 涉及檔案 |
|------|------|---------|
| 2026-03-27 | **V2.20 Phase 0.3 C2 修復**：`_truncate_context_by_activation` 加 `source_dirs: Dict[str, Path]` 參數，activation 計算從 atom 實際所在目錄查 `.access.json`（原硬編 `MEMORY_DIR` 導致專案層 atom ACT-R score 永遠 -10.0）。workflow-guardian 載入迴圈記錄每個 atom 的 source dir | `hooks/wg_atoms.py`, `hooks/workflow-guardian.py` |
| 2026-03-24 | **V2.18 Phase 2 Section-Level 注入**：向量服務新增 `ranked_search_sections()` + `/search/ranked-sections` endpoint。`_semantic_search()` 回傳帶 sections。注入迴圈新增 section 提取（`_extract_sections()`），大 atom 省 69-87% tokens。安全防護：0 匹配/70% 閾值/服務不可用皆 fallback 全量注入 | `searcher.py`, `service.py`, `wg_intent.py`, `wg_atoms.py`, `workflow-guardian.py` |
| 2026-03-23 | **V2.18 Phase 0+1**：環境清理（LanceDB 289→25MB、刪 7 死檔）+ 9 atom Trigger 精準化 + misdiagnosis/harvester 內容精簡 | `memory/*.md`, `MEMORY.md`, `workflow/config.json` |
| 2026-03-23 | **V2.17 合併升級**：V2.16 自我迭代自動化（SessionEnd 衰減掃描 + 自動晉升 + 震盪持久化）+ V2.17 覆轍偵測（寄生式 episodic 信號 + 跨 session 掃描）+ AIDocs 內容閘門 + WebFetch Guard + PreToolUse hooks + scripts/ 目錄 + misdiagnosis-verify-first atom | `hooks/workflow-guardian.py`, `settings.json`, `rules/aidocs.md`, `memory/decisions*.md`, `CLAUDE.md`, `README.md`, `Install-forAI.md`, `_AIDocs/*.md` |
| 2026-03-19 | **V2.15 定義版本**：全文件版本號 V2.12→V2.15 統一。移除內嵌版本標註（已是標準功能的 V2.x 標籤）。README 版本歷史補 V2.13/V2.14/V2.15。Architecture/DocIndex/Project_File_Tree 版本清理。CHANGELOG 補完 V2.12~V2.14 間缺漏變更 | `CLAUDE.md`, `README.md`, `Install-forAI.md`, `_AIDocs/*.md`, `memory/decisions*.md`, `rules/session-management.md` |
| 2026-03-19 | **V2.14 Token Diet**：`_strip_atom_for_injection()` 注入前 strip 9 種 metadata + 行動/演化日誌。SessionEnd 從 byte_offset 跳已萃取段。cross-session lazy search 預篩。省 ~1550 tok/session | `hooks/workflow-guardian.py`, `hooks/extract-worker.py`, `memory/MEMORY.md`, `workflow/config.json` |
| 2026-03-19 | **V2.13 Failures 自動化系統**：Guardian 偵測失敗關鍵字 → detached extract-worker 萃取失敗模式 → 三維路由自動寫入對應 failure atom | `hooks/extract-worker.py`, `hooks/workflow-guardian.py`, `workflow/config.json`, `memory/failures/` |
| 2026-03-19 | **atom 精準拆分+設定精修**：toolchain-ollama 獨立拆分 + workflow-icld 拆分 + trigger 瘦身 + failures 拆分子 atoms + GIT 流程去重 + 設定檔去重/瘦身/統一管理 | `memory/*.md`, `workflow/config.json` |
_(舊條目已移至 `_CHANGELOG_ARCHIVE.md`。最近移入：2026-03-19 vector service timeout + V2.12 逐輪增量萃取)_
