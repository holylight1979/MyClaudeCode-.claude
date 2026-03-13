# 變更記錄 — 封存

> 從 `_CHANGELOG.md` 滾動淘汰的歷史記錄。

---

| 日期 | 變更 | 涉及檔案 |
|------|------|---------|
| 2026-03-11 | **V2.8 升級完成（S1+S2+S3）**：Wisdom Engine + 自我迭代 V2.6 + 品質回饋 V2.7 + Guardian 增量合併 + SPEC/文件更新 | `hooks/{workflow-guardian,wisdom_engine}.py`, `memory/wisdom/*`, `memory/*.md`, `CLAUDE.md`, `_AIDocs/*` |
| 2026-03-05 | **V2.4 合併**：回應捕獲+跨Session鞏固+episodic改進 | `hooks/workflow-guardian.py`, `tools/memory-vector-service/*`, `memory/*.md`, `_AIDocs/*` |
| 2026-03-04 | **V2.1 研究計畫**：7 大缺陷 + 6 系統比較 + 3 階段路線圖 | `_AIDocs/AtomicMemory-v2.1-Plan.md` |
| 2026-03-04 | **V2.1 Sprint 1-3**：Schema 擴展、Write Gate、Intent Ranking、Conflict Detection、Type Decay、Audit Trail | `hooks/workflow-guardian.py`, `tools/*.py`, `memory/SPEC_Atomic_Memory_System.md` |
| 2026-03-03 | **MCP 傳輸格式修正**：Content-Length header → JSONL。protocolVersion 更新至 2025-11-25。Dashboard heartbeat recovery。 | `tools/workflow-guardian-mcp/server.js` |
| 2026-03-03 | **工作流完善**：session ID prefix match、resume 後 atoms 重注入、Atom Last-used 自動刷新、sync_completed 清空 queue+files、computer-use MCP 修正 | `server.js`, `workflow-guardian.py`, `README.md`, `Install-forAI.md` |
| 2026-03-02 | Dashboard 改進 + 4 項缺陷修復 + Workflow Guardian 建立 + CLAUDE.md 情境判斷表 | 多檔案 |
| 2026-03-02 | 原子記憶系統設計完成 + 知識庫初始化 + GitHub 上傳準備 | `memory/SPEC_*`, `CLAUDE.md`, `_AIDocs/*` |
