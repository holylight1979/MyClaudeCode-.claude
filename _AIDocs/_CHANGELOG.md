# 變更記錄

> 保留最近 ~8 筆。舊條目移至 `_CHANGELOG_ARCHIVE.md`。

---

| 日期 | 變更 | 涉及檔案 |
|------|------|---------|
| 2026-03-11 | **V2.8 升級完成（S1+S2+S3）**：Wisdom Engine（因果圖+情境分類+反思引擎）、自我迭代 V2.6（震盪偵測+成熟度+定期檢閱）、品質回饋 V2.7、failures/toolchain atoms、/resume + /consciousness-stream skills、Guardian 增量合併（~2285 行）、CLAUDE.md 精簡版（145 行）、SPEC v2.8 完整更新（§十一~十三新增）、Install-forAI 版本對齊 | `hooks/{workflow-guardian,wisdom_engine}.py`, `memory/wisdom/*`, `memory/{failures,toolchain,MEMORY,SPEC}.md`, `commands/{resume,consciousness-stream}.md`, `CLAUDE.md`, `Install-forAI.md`, `_AIDocs/*` |
| 2026-03-05 | **V2.4 合併自家中 repo**：workflow-guardian.py 升級（回應捕獲+跨Session鞏固+episodic改進，1437→1878行）、indexer.py 加入 additional_atom_dirs、config.py/test-memory-v21.py 更新、新增 preferences.md+decisions.md atoms、MEMORY.md 4欄索引、Architecture.md+Project_File_Tree.md 全面改寫、CLAUDE.md+SPEC+README+Install-forAI 已在 Session 1 完成 | `hooks/workflow-guardian.py`, `tools/memory-vector-service/{indexer,config}.py`, `tools/test-memory-v21.py`, `memory/{MEMORY,preferences,decisions}.md`, `_AIDocs/*` |
| 2026-03-04 | **原子記憶 v2.1 Sprint 3 實作完成**：Type Decay Multiplier（semantic/episodic/procedural 差異化淘汰）、Supersedes 載入邏輯（被取代 atom 不載入）、Evolution Log 壓縮（`--compact-logs`）、Token Budget char-to-token 估算、Session-end 增量索引、Audit Trail 升級（parse_audit_log + 健檢報告）、TYPE_INTENT_BONUS、SPEC v2.1 完整更新（新增 §八 衝突偵測 + §九 Audit Trail + §十 版本紀錄） | `tools/memory-audit.py`, `hooks/workflow-guardian.py`, `tools/memory-vector-service/searcher.py`, `memory/SPEC_Atomic_Memory_System.md` |
| 2026-03-04 | **原子記憶 v2.1 Sprint 2 實作完成**：Task-Intent 分類器（rule-based zero LLM）、Retrieval Ranking（5 因子加權排序 + `/search/ranked` API）、indexer metadata 擴充（last_used/confirmations/atom_type/tags）、Related 關聯載入、Conflict Detector（LLM 語意比對 AGREE/CONTRADICT/EXTEND/UNRELATED）、Delete Propagation（`--delete`/`--purge` 全鏈清除） | `hooks/workflow-guardian.py`, `tools/memory-vector-service/{indexer,searcher,service}.py`, `tools/memory-conflict-detector.py`(新), `tools/memory-audit.py` |
| 2026-03-04 | **原子記憶 v2.1 Sprint 1 實作完成**：Schema 擴展 10 欄位、解析器升級、`--enforce` 自動淘汰、Confirmations 自動遞增、Write Gate 新建 | `memory/SPEC_Atomic_Memory_System.md`, `tools/memory-audit.py`, `hooks/workflow-guardian.py`, `tools/memory-write-gate.py`(新), `workflow/config.json` |
| 2026-03-04 | **原子記憶 v2.1 研究計畫**：7 大缺陷 + 6 系統比較 + schema + 排序公式 + 治理機制 + 3 階段路線圖 | `_AIDocs/AtomicMemory-v2.1-Plan.md` |
| 2026-03-03 | **工作流完善**：session ID prefix match、resume 後 atoms 重注入、Atom Last-used 自動刷新、sync_completed 清空 queue+files、computer-use MCP 修正 | `server.js`, `workflow-guardian.py`, `README.md`, `Install-forAI.md` |
| 2026-03-03 | **MCP 傳輸格式修正**：Content-Length header → JSONL。protocolVersion 更新至 2025-11-25。Dashboard heartbeat recovery。 | `tools/workflow-guardian-mcp/server.js` |
_(舊條目已移至 `_CHANGELOG_ARCHIVE.md`)_
