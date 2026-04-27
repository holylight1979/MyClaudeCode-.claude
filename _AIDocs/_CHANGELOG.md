# 變更記錄

> 保留最近 ~8 筆（PostToolUse hook 自動滾動到 `_CHANGELOG_ARCHIVE.md`）。
> 每條僅留「標題 + 一句摘要 + 詳情 log 連結」。實作細節見 `DevHistory/session-logs/{date}-{slug}.md`。

---

## 2026-04-02 V3.1 Token Diet — 原子記憶精簡
- Phase 1 直刪：移除 31 條 Claude 不使用的自動化描述條目
- Phase 2 信號自描述化：5 個 Guardian 信號加入行動指令，移除冗餘 atom 條目
- Phase 3 JIT 按需注入：記憶系統開發知識移到 `_reference/internal-pipeline.md`，複合條件觸發
- Phase 4 MCP atom_write/promote tools：程式化 atom 寫入，rules/memory-system.md 精簡
- **成果**：decisions+arch+memory-system 從 1,841→631 tok（**-65.7%, -1,210 tok**），超越計畫目標 36%

| 日期 | 變更 | 涉及檔案 |
|------|------|---------|
| 2026-04-27 | **Codex Companion Sprint 2** — heuristic 規則重構與 BLOCK 權收斂。BLOCK 權限縮到單一 `confident_completion_without_evidence`（high）；其餘規則一律降為 `low` advisory。三條件齊備才 BLOCK：`has_claim` + `state_change` + `no_verify_evidence`。新增 Sprint 1 教訓 fallback：`last_assistant_tail` 含驗證敘述（pytest 通過 / X/Y PASS / build 成功）視為弱證據放行，避免 companion-state 被擾動誤觸 BLOCK。新增 `severity_at_or_above` API + config `block_severity_threshold`。21 unit + 3 e2e 測試全綠。 | `tools/codex-companion/heuristics.py`(rewrite), `hooks/codex_companion.py`, `workflow/config.json`, `tests/test_heuristics.py`(rewrite), `tests/test_codex_companion_stop_e2e.py`(新), `_AIDocs/DocIndex-System.md` |
| 2026-04-26 | **Codex Companion Phase 1** — Codex (GPT) 驅動的第二觀點監督系統。確定性 hook 觸發 → HTTP service 累積事件 → `codex exec` 非同步審閱 → 下一輪 additionalContext 注入。含 4 條 heuristic 軟閘（缺驗證/完成缺證據/架構變更/空轉）、plan review / turn audit / architecture review 三種 Codex 評估、`/codex-companion` 開關 skill。 | `tools/codex-companion/`(新: service.py, assessor.py, prompts.py, heuristics.py, state.py), `hooks/codex_companion.py`(新), `commands/codex-companion.md`(新), `workflow/config.json`, `settings.json`, `_AIDocs/DocIndex-System.md` |
| 2026-04-24 | **v3 雙欄位拆分 (ReadHits + Confirmations)** — Confirmations 混合訊號拆為 ReadHits（注入讀取）+ Confirmations（跨 session 萃取），晉升門檻重校 4/10+20/50 雙軌，correlation_id 追蹤，16 檔 + migration script，24 E2E 測試全綠。 | `hooks/workflow-guardian.py`, `hooks/wg_episodic.py`, `hooks/wg_atoms.py`, `hooks/user-extract-worker.py`, `hooks/wg_iteration.py`, `tools/workflow-guardian-mcp/server.js`, `tools/memory-audit.py`, `tools/atom-health-check.py`, `tools/memory-vector-service/indexer.py`, `scripts/migrate-confirmations.py`(新), `tests/test_dual_field_e2e.py`(新), `memory/decisions.md` |
| 2026-04-23 | **ScanReport Gate + 反退避契約** — 針對 Opus 4.7 Effort=High 偷懶傾向：IDENTITY.md 加可觀測條款（禁語/成本門檻/收尾格式），Stop hook 新增「缺掃描報告 = 違約」硬阻擋。 | `IDENTITY.md`, `hooks/wg_evasion.py`, `hooks/workflow-guardian.py`, `_AIDocs/Architecture.md` |
| 2026-04-17 | **_CHANGELOG 短格式化 + session-logs 子目錄** — 每條 ~2KB 單行敘事拆為「標題 + log 連結」，8 條遷入 `DevHistory/session-logs/`。[log](DevHistory/session-logs/2026-04-17-changelog-short-form.md) | `_AIDocs/_CHANGELOG.md`, `_AIDocs/DevHistory/session-logs/*`(8 新) |
| 2026-04-17 | **_CHANGELOG 自動滾動 + Architecture 索引化** — PostToolUse auto-roll + 8 pytest；Architecture 413→150 行（-64%），7 DevHistory 子檔。[log](DevHistory/session-logs/2026-04-17-changelog-and-architecture.md) | `tools/changelog-roll.py`(新), `commands/changelog-roll.md`(新), `tests/test_changelog_roll.py`(新), `workflow/config.json`, `hooks/workflow-guardian.py`, `_AIDocs/Architecture.md`(rewrite), `_AIDocs/DevHistory/*`(7 新+1 擴) |
| 2026-04-17 | **Evasion Guard + Test-Fail Gate** — Bash 測試失敗偵測 + Stop 完成宣告攔截 + UPS 退避舉證要求，51 pytest。[log](DevHistory/session-logs/2026-04-17-evasion-guard.md) | `hooks/wg_evasion.py`(新), `hooks/workflow-guardian.py`, `settings.json`, `tests/test_evasion_guard.py`(新) |
| 2026-04-17 | **Atom 寫入防呆 + feedback 目錄整理 + atom_promote 合併** — AUTO-DRAFT tag / Atom-Write Guard / feedback/ 子資料夾 / merge_to_preferences。[log](DevHistory/session-logs/2026-04-17-atom-write-guards.md) | `hooks/wg_hot_cache.py`, `hooks/workflow-guardian.py`, `hooks/wg_iteration.py`, `tools/workflow-guardian-mcp/server.js`, `memory/feedback/` |
