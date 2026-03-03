# 變更記錄

> 保留最近 ~8 筆。舊條目移至 `_CHANGELOG_ARCHIVE.md`。

---

| 日期 | 變更 | 涉及檔案 |
|------|------|---------|
| 2026-03-03 | **MCP 傳輸格式修正**：Content-Length header → JSONL（Claude Code v2.x 實際使用的格式）。protocolVersion 更新至 2025-11-25。Dashboard port heartbeat recovery（多實例自動接管）。同步修復 openclaw-notify-mcp。 | `tools/workflow-guardian-mcp/server.js`, `C:\OpenClawWorkspace\scripts\openclaw-notify-mcp.js` |
| 2026-03-02 | Dashboard 改進：session 名稱顯示、Windows 路徑修正、Mute 按鈕、ended session 1 分鐘自動清理 | `tools/workflow-guardian-mcp/server.js` |
| 2026-03-02 | 修復 4 項缺陷：Stop 訊息 context-aware、min_files_to_block 門檻、max_reminders 上限、mute 靜音機制 | `hooks/workflow-guardian.py`, `tools/workflow-guardian-mcp/server.js`, `workflow/config.json` |
| 2026-03-02 | Workflow Guardian 系統建立：hooks 驅動的工作流監督 + MCP server + Dashboard | `hooks/workflow-guardian.py`, `tools/workflow-guardian-mcp/server.js`, `settings.json`, `workflow/config.json` |
| 2026-03-02 | CLAUDE.md 工作結束同步改為 context-aware 情境判斷表 | `CLAUDE.md` |
| 2026-03-02 | 原子記憶系統設計完成：SPEC v1.0 + CLAUDE.md 整合 | `memory/SPEC_Atomic_Memory_System.md`, `CLAUDE.md` |
| 2026-03-02 | 知識庫初始化 + GitHub 上傳準備 | `_AIDocs/*`, `Install-forAI.md`, `.gitignore` |
