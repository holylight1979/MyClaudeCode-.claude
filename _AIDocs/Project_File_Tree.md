# Claude Code 全域設定 — 目錄角色說明
> 路徑 `~/.claude/`；2026-04-28 瘦身 218→30 行；詳細跑 `tree -L 3` 或查各子目錄 `_INDEX.md`

## 頂層目錄角色
| 路徑 | 角色 | 維護來源 |
|------|------|---------|
| `CLAUDE.md` / `IDENTITY.md` / `USER.md` / `rules/core.md` | always-loaded 入口 | 手寫 |
| `settings.json` / `.mcp.json` | Hook 鏈 + 權限 + MCP server | 手寫 |
| `memory/` | 原子記憶資料層（`_ATOM_INDEX` + atom md + `_vectordb/` + `feedback/` + `wisdom/` + `_reference/` + `_staging/` + `personal/{user}/` + `shared/` + `roles/{role}/`） | hook auto + atom_write |
| `hooks/` | Hook 腳本（`workflow-guardian.py` + `wg_*.py` + `wisdom_engine.py` + lib） | 手寫 |
| `commands/` | 自訂 slash commands | 手寫 |
| `tools/` `scripts/` | 工具腳本 / 一次性遷移 | 手寫 |
| `_AIDocs/` | 長期參考知識（架構/踩坑/演進史） | 手寫 + auto-roll |
| `plans/` | 進行中規劃；完成搬 `_AIDocs/DevHistory/` | 手寫 |
| `prompts/` `templates/` | Prompt / atom 模板 | 手寫 |
| `journals/` `Logs/` | 工作日誌 / 執行日誌 | hook |
| `projects/` | per-project session jsonl + 專案層記憶 | Claude Code |
| `sessions/` `session-env/` `file-history/` `cache/` `ide/` | Claude Code 內部狀態 | 系統 |

## 結構性規則
- always-loaded 入口聖域：不放後設、版本沿革、hook 常數
- 記憶分層：global / shared / role / personal/{user}
- 規劃 vs 知識：`plans/` 短期；完成搬 `_AIDocs/DevHistory/{topic}/`
- 子目錄詳細：`hooks/` → `Architecture.md`；`memory/` → `SPEC_ATOM_V4.md`
