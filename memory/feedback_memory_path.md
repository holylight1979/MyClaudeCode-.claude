# 記憶寫入路徑規則

- Scope: global
- Confidence: [固]
- Trigger: 寫入記憶, 暫存, _staging, memory path, 寫atom, 寫檔案, Write memory
- Last-used: 2026-04-02
- Confirmations: 17
- Related: decisions

## 知識

- [固] **專案層記憶一律寫入 `{project_root}/.claude/memory/`**，不寫 `~/.claude/projects/{slug}/memory/`
- [固] **暫存檔一律寫入 `{project_root}/.claude/memory/_staging/`**，不寫個人層的 `_staging/`
- [固] 全域層記憶寫 `~/.claude/memory/`（這是正確的）
- [固] Claude Code 內建 auto memory 系統定義的路徑 `~/.claude/projects/{slug}/memory/` 已被原子記憶專案自治層覆寫，**禁止使用**
- [固] 判斷依據：檔案屬於哪個專案 → 寫到該專案根目錄的 `.claude/memory/`；屬於全域偏好/工具鏈 → 寫到 `~/.claude/memory/`

## 行動

- 寫入任何 memory/atom/_staging 檔案前，先確認目標路徑符合上述規則
- 內建 auto memory 的 YAML frontmatter 格式也已被覆寫（改用原子記憶格式），見 `rules/memory-system.md`
