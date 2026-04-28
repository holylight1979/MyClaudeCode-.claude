# Session I — Dashboard 更新：入 repo 記憶 + Skills + MCP 顯示

> **模式**：不用 Plan Mode。Permission 建議 yolo 或 auto-accept。
> **CWD**：`~/.claude`
> **GIT**：完成即 commit + push（中文 log per `memory/feedback-git-log-chinese.md`）。
> **前置條件**：V4.1 GA 已完工（含 `dd466c2` / `8625b45` / `c65b99b` 三個補漏 commit）。
> **可與 Session H（README/TECH 拆檔）並行**：兩者檔案零重疊（H 動 README.md / TECH.md / _AIDocs/_INDEX.md；I 動 tools/workflow-guardian-mcp/*）。

---

## ⚠️ 首要規則：**等使用者補概略內容才動手**

開工第一步**不要直接改檔**。必須：

1. 讀完本 handoff
2. 盤點 dashboard 現況（只讀不改）：
   - `tools/workflow-guardian-mcp/` 目錄內容（server.js / public/ / static/ 等）
   - 搜 `DASHBOARD_PORT` / 3848 相關啟動點
   - 現有 dashboard 有哪些 endpoint / 顯示什麼
3. 對使用者回報「目前 dashboard 支援的顯示項 + 我打算新增什麼（具體選項題）」
4. **等使用者確認範圍** → 才動手
5. 若使用者回覆模糊 → 給具體選項題（符合 `memory/feedback-no-outsource-rigor.md`：不開放式問「還有什麼」）

未等使用者確認就自己加顯示項 → **一律視為超出授權**。

---

## 核心概念（使用者的 requirement）

**「不耗 token」的精確語意**：
- Dashboard 是 HTTP 端（port 3848），前端瀏覽器直接訪問
- 資料來自檔案系統掃描（atoms / commands / settings.json）+ 既有 MCP state
- 所有運算在 Node.js process / 瀏覽器端，**不走 Claude context、不呼叫任何 LLM**
- 使用者看 dashboard 時 Claude 完全沒被啟動 → 零 token

**「人員的記憶、會上傳 repo 的部分」語意**：
- 按 V4 SPEC：`personal/` 目錄在專案 `.gitignore`，**不入版控**
- **入版控 = `shared/` + `roles/{r}/`**（V4 SPEC §2 三層 scope 表）
- 全域 `~/.claude/memory/` 入不入版控看使用者自己的 git 決定（目前有推 gitlab + github，所以算入）
- Dashboard 要顯示的 = shared + role:{r} + 全域 atoms 三類（標明 scope 別）

---

## 任務範圍

### 新增顯示區塊（三塊）

#### 1. 「團隊共享記憶」區塊（入 repo）

列出所有會進 git 的 atoms，分三個子分類：

- **全域 (`~/.claude/memory/`)**：scope=global 的 atoms，不含 `personal/`、不含 `episodic/`（TTL）、不含 `_*` 前綴目錄
- **專案 shared (`{proj}/.claude/memory/shared/`)**：跨 role 共享
- **專案 role (`{proj}/.claude/memory/roles/{r}/`)**：role 限定

每條顯示：
- Atom 名稱（檔名）
- Scope（shared / role:art / role:programmer / global）
- Audience（含哪些角色可見）
- Author
- Confidence（[固] / [觀] / [臨]）
- Confirmations
- 最後更新時間（Last-used 或 file mtime）
- 點擊可展開看 Trigger + Related + 內容前 200 字

**排序**：預設按 scope 分組 → 按 Confidence 降序（[固]→[觀]→[臨]）→ 按 Confirmations 降序

**過濾器**：
- Scope（全域 / shared / role:X）
- Confidence（固/觀/臨）
- Text search（檔名 / trigger / author）

#### 2. 「Skills 清單」區塊

掃 `commands/*.md`，讀每份 frontmatter（argument-hint / description 等）。

顯示每條 skill：
- `/指令名稱`
- 一行描述（從 md 第一行 `> ...` 或 H1 之後的第一段取）
- 分類標籤（根據內容分：V4/V4.1 / 記憶維運 / 開發協作 / 工具 / 互動）
- 點擊可看該 .md 內容（Markdown render）

**排序**：按分類分組，組內按英文字母序

**來源**：`~/.claude/commands/*.md` + 各專案 `{proj}/.claude/commands/*.md`（若有）

#### 3. 「MCP Servers」區塊

讀 `settings.json` 的 `mcpServers`（若有）+ `~/.claude/.mcp.json`（若存在）+ 各專案 `{proj}/.mcp.json`。

每個 MCP server 顯示：
- 名稱
- type（stdio / sse / http）
- command / url
- 狀態（啟用 / 停用，根據 settings.json `enabledMcpjsonServers` 判斷）
- 暴露的 tool 數（如可從 server 查詢，否則顯示「呼叫後可見」）

**不列實際 tools schema**（太大且會變動）。

---

## 不耗 token 的實作確認

本次所有新功能**都是檔案系統掃描 + HTTP render**，具體：

| 動作 | 成本 |
|---|---|
| 掃 memory/*.md | fs.readdir + parse frontmatter，Node.js ms 級 |
| 掃 commands/*.md | fs.readdir + 讀首段，ms 級 |
| 讀 settings.json / .mcp.json | fs.readFile + JSON.parse，ms 級 |
| Render HTML | 純前端 |

**不做的事**（明確列出避免 scope creep）：
- ❌ 用 LLM 摘要 atom 內容
- ❌ 呼叫 vector service 排序
- ❌ Server-side render with Claude
- ❌ 預載所有 atom 全文（點擊才 fetch）
- ❌ 跟 Claude session 互動

---

## 工作流程

**Phase 1（零改動）**：盤點 + 問使用者概略
1. `git pull`
2. 讀 `tools/workflow-guardian-mcp/` 全部檔案（server.js / public/ 若存在 / package.json）
3. 找出現有 dashboard HTML entry point
4. `glob` 當前 memory/ 結構（`memory/*.md` / `memory/roles/*/*.md` / `memory/shared/*.md`）
5. 看 settings.json 的 `mcpServers` 結構
6. **對使用者列「現有功能 + 計畫新增」然後問具體確認**（不開放式）

**Phase 2（等使用者 OK 才動）**：
1. 擴充 server.js：新增 3 個 HTTP endpoint
   - `GET /atoms` → 回入 repo atoms JSON（三分類）
   - `GET /skills` → 回 commands/*.md 掃描結果
   - `GET /mcp` → 回 mcpServers 組合
2. 加前端：
   - 新三個 tab / section（根據現有 dashboard layout 決定）
   - 純 vanilla JS + 既有 CSS（不引入框架）
3. 自測：`curl localhost:3848/atoms`、瀏覽器訪問 dashboard

**Phase 3（驗收）**：
1. 瀏覽器打開 `http://localhost:3848/`（或現有路徑）
2. 確認三新區塊正常顯示
3. 點擊 atom 展開正常
4. 過濾器/搜尋正常
5. 重啟 dashboard 看資料會動態更新（或明確標註「手動 reload」）

**Phase 4（commit + push）**：
1. 中文 log，prefix `feat(dashboard):` 或 `feat(mcp):`
2. Push 雙 remote

---

## 絕不碰

- `hooks/` 任何 .py
- `workflow/config.json` / `settings.json`（只讀）
- V4 atoms（memory/*.md）— 只讀不改
- `tests/`
- 其他 `tools/*.py`
- README.md / TECH.md（Session H 的範圍）

---

## Context 連結

- MCP Server 程式碼：`tools/workflow-guardian-mcp/server.js`
- V4 SPEC（scope 分類 + 入 repo 規則）：`_AIDocs/SPEC_ATOM_V4.md`
- 現有 skill 清單：`commands/*.md`（21+ 檔）
- V4.1 journey：`_AIDocs/DevHistory/v41-journey.md`
- Architecture：`_AIDocs/Architecture.md`（V4.1 pipeline 段）

讀這些檔可以快速進入脈絡，但**還是要等使用者的概略確認**才動手。

---

## 結束標準

- Dashboard 新增三區塊：團隊共享記憶 / Skills / MCP Servers
- 純檔案掃描 + HTTP，零 Claude token 消耗
- commit + push 完成
- 回報使用者：dashboard URL + 三區塊截圖（如可）或文字描述
