# MyClaudeCode (.claude) — AI 分析文件索引

> 本資料夾記錄 `~/.claude` 自訂擴充系統的架構與演進。
> 最近更新：2026-03-23

---

## 文件清單

| # | 文件名稱 | 說明 | keywords |
|---|---------|------|----------|
| 1 | Architecture.md | 系統架構總覽：原子記憶 V2.17 + Workflow Guardian + Wisdom Engine + hooks | 架構, hooks, skill, rules, 事件驅動, wisdom engine, 規則模組, guardian, 覆轍偵測, 自我迭代自動化 |
| 2 | Project_File_Tree.md | 完整目錄結構 | 目錄結構, 檔案位置, 資料夾, 在哪裡 |
| 3 | _CHANGELOG.md | 變更記錄（最近 ~8 筆） | 變更記錄, 最近更新, 改了什麼 |
| 4 | _CHANGELOG_ARCHIVE.md | 變更記錄封存 | 歷史變更, 舊版記錄 |
| 5 | ../README.md | 完整運作知識庫 + 7 階段流程圖（GitHub 入口） | 設計哲學, 安裝, 入門, 流程圖, 使用方式 |
| 6 | DocIndex-System.md | 全 76 檔系統索引（啟動鏈 + Hook + Skill + Tool + Memory） | 啟動鏈, lifecycle, 全檔索引, 檔案清單, 系統索引 |

---

## 架構一句話摘要

基於 Claude Code hooks 事件驅動的工作流監督系統，搭配雙 LLM（Claude + Ollama qwen3/qwen3.5）原子記憶管理跨 session 知識。V2.17：Dual-Backend、Wisdom Engine、衝突偵測、rules/ 模組化、Fix Escalation、Failures 自動化、Token Diet、自我迭代自動化、覆轍偵測。
