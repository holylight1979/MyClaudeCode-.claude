# Atom Index — Global

> Session 啟動時先讀此索引。比對 Trigger → Read 對應 atom。

| Atom | Path | Trigger | Confidence |
|------|------|---------|------------|
| preferences | memory/preferences.md | 偏好, 風格, 習慣, style, preference, 語言, 回應 | [固] |
| decisions | memory/decisions.md | 全域決策, 工具, 工作流, workflow, guardian, hooks, MCP, 記憶系統 | [固] |
| excel-tools | memory/excel-tools.md | Excel, xls, xlsx, 讀取, 試算表, spreadsheet, openpyxl, xlrd | [固] |
| spec | memory/SPEC_Atomic_Memory_System.md | SPEC, 規格, atom格式, 記憶規範, memory spec | [固] |
| workflow-rules | memory/workflow-rules.md | svn, svn-update, 版本控制, 同步, vcs | [固] |
| failures | memory/failures.md | 失敗, pitfall, 陷阱, bug, 踩坑, debug | [觀] |
| toolchain | memory/toolchain.md | 工具鏈, toolchain, Ollama, qwen3, vector, LanceDB | [觀] |
| v2.9-spec | memory/v3-design-spec.md | V2.9, V3, 設計, 檢索強化, project-alias, ACT-R, multi-hop, blind-spot | [固] |
| v3-research | memory/v3-research-insights.md | 研究, 認知科學, 佛學, 唯識, ACT-R, spreading activation | [觀] |
| unity-yaml | memory/unity/unity-yaml.md | Unity YAML, fileID, GUID, PrefabInstance, .prefab, .meta, 型別ID, 序列化, Missing Script | [固] |
| gdoc-harvester | memory/gdoc-harvester.md | harvester, Google Docs, Sheets, 收割, Playwright, cookie, export, aiohttp | [觀] |
| feedback-research | memory/feedback_research_first.md | 試錯, trial-and-error, 不熟悉, API, 框架, 搜尋, research | [固] |

---

## 高頻事實

- [固] 使用者: holylight | 平台: Windows 11 Pro
- [固] MCP 可用: playwright, openclaw-notify, workflow-guardian, computer-use
- [固] Guardian @ localhost:3848 | Vector @ localhost:3849
- [固] GPU: GTX 1050 Ti 4GB | qwen3-embedding + qwen3:1.7b
- [固] Vector DB: LanceDB | search_min_score: 0.65
- [固] 原子記憶 V2.10：回應捕獲 + 跨 Session 鞏固 + 自我迭代 + Wisdom Engine + 檢索強化(V2.9) + Read Tracking + VCS Query Capture + _staging 暫存區(V2.10)
- [固] Excel: `~/.claude/tools/read-excel.py`（Python3 + openpyxl + xlrd）
- [固] SVN 專案修改前必問 svn update（每 session 一次）| Skill: /svn-update
- [觀] Wisdom Engine: causal graph + reflection + situation classifier
