# 變更記錄

> 保留最近 ~8 筆。舊條目移至 `_CHANGELOG_ARCHIVE.md`。

---

| 日期 | 變更 | 涉及檔案 |
|------|------|---------|
| 2026-03-13 | **對外文件更新 Dual-Backend**：README 補充 Dual-Backend 架構+三階段退避+靜態停用旗標；Install 補 rdchat 設定步驟+移除內部 URL+移除過時 extract-worker；Architecture 補 Dual-Backend+Long DIE+ollama_client 工具 | `README.md`, `Install-forAI.md`, `_AIDocs/Architecture.md` |
| 2026-03-13 | **/read-project**: 新增 DocIndex-System.md（76 檔系統索引）+ doc-index-system atom | `_AIDocs/DocIndex-System.md`, `memory/doc-index-system.md`, `memory/MEMORY.md` |
| 2026-03-13 | **選擇性 cherry-pick**：從來源 V2.10 合併 `/continue` skill + `/resume` staging 安全網 + `BOOTSTRAP.md` + `workflow-rules.md` 補回大型計畫/GIT/同步判斷段落 | `commands/continue.md`, `commands/resume.md`, `BOOTSTRAP.md`, `memory/workflow-rules.md` |
| 2026-03-13 | **Atom 整理**：SPEC(950行)/self-iteration/v3-design-spec/v3-research 移至 `memory/_reference/`，MEMORY.md 索引 13→8 筆，新增「參考文件」區塊（開發記憶系統時手動讀取） | `memory/MEMORY.md`, `memory/_reference/*` |
| 2026-03-13 | **README Token/延遲表校正**：CLAUDE.md Token 2500-3500→1500-2500、MEMORY.md Token 50-80→200-350、Prompt 延遲 300-600→200-500ms（V2.11 移除逐輪萃取）、總 Overhead 3000-5000→2000-5500 | `README.md` |
| 2026-03-13 | **README/Install 文件補完 V2.11**：版本號更新、新增「初步建議使用方式」區塊、Skills 表格上移並補 `/harvest` `/upgrade`、架構樹補 `rules/`、Install 補安裝後使用指引 | `README.md`, `Install-forAI.md` |
| 2026-03-13 | **V2.11 全面升級（4 波 10 sessions）**：精簡（砍逐輪萃取/因果圖/自動晉升/自我迭代 8→3 條）+ 品質（衝突偵測自動化/反思校準/Atom 健康度）+ 模組化（rules/ 4 模組 + Context Budget 3000t）+ 環境清理 300+ 檔 | `hooks/*.py`, `memory/*`, `rules/*.md`, `CLAUDE.md`, `tools/*`, `_AIDocs/*` |
| 2026-03-13 | **引入同事改進**：indexer.py 遞迴掃描 + `/upgrade` skill | `tools/memory-vector-service/indexer.py`, `commands/upgrade.md`, `tools/memory-audit.py` |
_(舊條目已移至 `_CHANGELOG_ARCHIVE.md`)_
