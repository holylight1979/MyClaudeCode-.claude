# 變更記錄

> 保留最近 ~8 筆。舊條目移至 `_CHANGELOG_ARCHIVE.md`。

---

| 日期 | 變更 | 涉及檔案 |
|------|------|---------|
| 2026-03-13 | **README/Install 文件補完 V2.11**：版本號更新、新增「初步建議使用方式」區塊、Skills 表格上移並補 `/harvest` `/upgrade`、架構樹補 `rules/`、Install 補安裝後使用指引 | `README.md`, `Install-forAI.md` |
| 2026-03-13 | **V2.11 全面升級（4 波 10 sessions）**：精簡（砍逐輪萃取/因果圖/自動晉升/自我迭代 8→3 條）+ 品質（衝突偵測自動化/反思校準 over_engineering+silence_accuracy/Atom 健康度）+ 模組化（.claude/rules/ 4 模組 + Context Budget 3000t + CLAUDE.md 瘦身）+ 環境清理 300+ 檔 + Episodic 品質升級（17→0，1 條晉升） | `hooks/{workflow-guardian,extract-worker,wisdom_engine}.py`, `memory/wisdom/*`, `memory/{self-iteration,SPEC,decisions,MEMORY}.md`, `rules/*.md`, `CLAUDE.md`, `tools/{atom-health-check,cleanup-old-files}.py`, `_AIDocs/*` |
| 2026-03-13 | **引入同事改進**：indexer.py 遞迴掃描 + `/upgrade` skill | `tools/memory-vector-service/indexer.py`, `commands/upgrade.md`, `tools/memory-audit.py` |
| 2026-03-11 | **_AIDocs Bridge (v2.10)**：hook 掃描 `_AIDocs/_INDEX.md` 注入精簡索引 + `/read-project` DocIndex 同步 | `hooks/workflow-guardian.py`, `commands/read-project.md` |
| 2026-03-11 | **V2.8 升級完成（S1+S2+S3）**：Wisdom Engine + 自我迭代 V2.6 + 品質回饋 V2.7 + Guardian 增量合併 + SPEC/文件更新 | `hooks/{workflow-guardian,wisdom_engine}.py`, `memory/wisdom/*`, `memory/*.md`, `CLAUDE.md`, `_AIDocs/*` |
| 2026-03-05 | **V2.4 合併**：回應捕獲+跨Session鞏固+episodic改進 | `hooks/workflow-guardian.py`, `tools/memory-vector-service/*`, `memory/*.md`, `_AIDocs/*` |
| 2026-03-04 | **V2.1 Sprint 1-3**：Schema 擴展、Write Gate、Intent Ranking、Conflict Detection、Type Decay、Audit Trail | `hooks/workflow-guardian.py`, `tools/*.py`, `memory/SPEC_Atomic_Memory_System.md` |
| 2026-03-04 | **V2.1 研究計畫**：7 大缺陷 + 6 系統比較 + 3 階段路線圖 | `_AIDocs/AtomicMemory-v2.1-Plan.md` |
_(舊條目已移至 `_CHANGELOG_ARCHIVE.md`)_
