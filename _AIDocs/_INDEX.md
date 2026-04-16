# MyClaudeCode (.claude) — AI 分析文件索引

> 本資料夾記錄 `~/.claude` 自訂擴充系統的架構與演進。
> 最近更新：2026-04-16（V4.1 設計圓桌完成）

---

## 文件清單

| # | 文件名稱 | 說明 | keywords |
|---|---------|------|----------|
| 1 | Architecture.md | 系統架構總覽：原子記憶 V3.1 + Workflow Guardian + Wisdom Engine + 三層即時管線 + Hot Cache + SessionStart 去重 + 專案自治層 | 架構, hooks, skill, rules, 事件驅動, wisdom engine, 規則模組, guardian, 覆轍偵測, 自我迭代自動化, 專案自治, hot cache, quick extract, 即時管線 |
| 2 | Project_File_Tree.md | 完整目錄結構 | 目錄結構, 檔案位置, 資料夾, 在哪裡 |
| 3 | _CHANGELOG.md | 變更記錄（最近 ~8 筆） | 變更記錄, 最近更新, 改了什麼 |
| 4 | _CHANGELOG_ARCHIVE.md | 變更記錄封存 | 歷史變更, 舊版記錄 |
| 5 | ../README.md | 安裝 + 3 步上手（人類入門，80 行） | 安裝, 入門, 使用方式, 快速開始 |
| 5b | ../TECH.md | 技術深度文件：架構 / 流程圖 / 子系統 / V4 scope 分層 / V4.1 決策萃取（以代碼為真源） | 設計哲學, 流程圖, ACT-R, Write Gate, Hot Cache, V4 scope, V4.1 使用者決策, 核心子系統 |
| 6 | DocIndex-System.md | 全檔系統索引（啟動鏈 + Hook 模組 + 16 Skills + Tools + Memory 25 atoms） | 啟動鏈, lifecycle, 全檔索引, 檔案清單, 系統索引 |
| 7 | ClaudeCodeInternals/_INDEX.md | Claude Code 原生架構深度分析（14 章：Harness Engineering 全書） | claude code 架構, harness engineering, tool system, hook system, agent, permission, prompt, MCP, skill, plugin, feature flag, query loop, context, state |
| 8 | Tools/_INDEX.md | 工具與領域知識（Excel 操作、Unity YAML/Prefab、記憶系統檔案索引） | Excel, xlsx, openpyxl, Unity YAML, fileID, GUID, prefab, WndForm, 記憶系統架構, 檔案結構, 目錄結構 |
| 9 | Failures/_INDEX.md | 踩坑記錄與失敗模式（環境陷阱、假設錯誤、靜默失敗、認知偏差、誤診） | 環境陷阱, Windows, MSYS2, npx, Ollama, 假設錯誤, 靜默, 過度工程, 誤診, 驗證優先 |
| 10 | DevHistory/_INDEX.md | 開發紀錄（版本演進、遷移紀錄、A/B 實測數據、atom 演化日誌） | 演化, 版本, changelog, 遷移, migration, V2.18, V2.20, V2.21, A/B, 實測, benchmark |
| 11 | SPEC_ATOM_V4.md | 原子記憶 V4 規格 — 多職務團隊共享（personal / shared / role 三層 scope、衝突三時段偵測、管理職雙向認證、JIT 角色 filter、六大分類大類） | V4, scope 三層, role-shared, personal-in-project, 多職務, 團隊協作, 衝突偵測, 管理職, audience, 角色 filter, gentle-puzzling-kettle |
| 12 | V4.1-design-roundtable.md | V4.1 設計圓桌紀錄 — 8 大師 drafting + validation 雙 round + 2 資訊整合，Prior Art URL 清單 | V4.1, 圓桌, drafting, validation, prior art, Mem0, ChatGPT Memory, stance detection, 主動萃取, 使用者決策 |

---

## 架構一句話摘要

基於 Claude Code hooks 事件驅動的工作流監督系統，搭配雙 LLM（Claude + Ollama qwen3/qwen3.5）原子記憶管理跨 session 知識。V3.1：三層即時管線（quick-extract 5s → hot_cache → mid-turn inject）+ SessionStart 風暴修復（去重+非阻塞 vector）+ Hook 模組化拆分（12 模組 ~5966 行）+ 專案自治層 + 17 Skills。
