# 記憶寫入路徑規則

- Scope: global
- Confidence: [固]
- Trigger: 寫入記憶, _staging, memory path, 寫atom, Write memory, 記憶路徑
- Related: decisions, feedback-pointer-atom

## 知識

- [固] **專案層記憶一律寫入 `{project_root}/.claude/memory/`**，不寫 `~/.claude/projects/{slug}/memory/`
- [固] **暫存檔一律寫入 `{project_root}/.claude/memory/_staging/`**，不寫個人層的 `_staging/`
- [固] 全域層記憶寫 `~/.claude/memory/`（這是正確的）
- [固] Claude Code 內建 auto memory 系統定義的路徑 `~/.claude/projects/{slug}/memory/` 已被原子記憶專案自治層覆寫，**禁止使用**
- [固] 判斷依據：檔案屬於哪個專案 → 寫到該專案根目錄的 `.claude/memory/`；屬於全域偏好/工具鏈 → 寫到 `~/.claude/memory/`

## 行動

- 寫入任何 memory/atom/_staging 檔案前，先確認目標路徑符合上述規則
- 內建 auto memory 的 YAML frontmatter 格式也已被覆寫（改用原子記憶格式），見 `rules/memory-system.md`

## 已 hook 化

- Hook: `hooks/wg_pretool_guards.py:check_memory_path_block` (PreToolUse Write/Edit, 2026-04-28)
- 偵測條件：file_path 命中 `[/\\]\.claude[/\\]projects[/\\][^/\\]+[/\\]memory[/\\]`（precise scope: `projects/{slug}/memory/` 單層；archived 多層路徑不擋）
- 動作：deny + 訊息指回本檔
- 本 atom 仍保留：作 LLM 提示來源 + hook 訊息錨點（hook 不取代 atom）
