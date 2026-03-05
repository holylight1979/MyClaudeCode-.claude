# MyClaudeCode (.claude) — AI 分析文件索引

> 本資料夾記錄 `~/.claude` 自訂擴充系統的架構與演進。
> 最近更新：2026-03-05

---

## 文件清單

| # | 文件名稱 | 說明 |
|---|---------|------|
| 1 | Architecture.md | 系統架構總覽：原子記憶 V2.4 + Workflow Guardian + hooks |
| 2 | Project_File_Tree.md | 完整目錄結構 |
| 3 | AtomicMemory-v2.1-Plan.md | v2.1 缺陷研究與修補計畫（歷史文件） |
| 4 | _CHANGELOG.md | 變更記錄 |
| 5 | ../README.md | 完整運作知識庫 + 7 階段流程圖（GitHub 入口） |

---

## 架構一句話摘要

基於 Claude Code hooks 事件驅動的工作流監督系統，搭配雙 LLM（Claude + Ollama qwen3）原子記憶管理跨 session 知識，V2.4 支援回應知識捕獲與跨 Session 鞏固。
