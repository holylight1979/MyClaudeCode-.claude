# /resume — 自動續接 Session

> 生成續接 prompt，依使用者選擇的方式開啟新 Claude Code session。
> 全域 Skill，適用任何專案。

---

## 使用方式

```
/resume [下一步指示]
```

### 參數

| 參數 | 必填 | 說明 | 範例 |
|------|------|------|------|
| 下一步指示 | 否 | 明確指定新 session 要做什麼（省略則自動從 todo/git/atoms 推斷） | `繼續實作 PackHandler 的 try-catch` |

### 使用範例

```
/resume
/resume 繼續實作 PackHandler 的 try-catch
/resume 接續上次的 UI 重構，從 HeroPanel 開始
```

> staging 檔名（`next-phase-{name}.md`）由任務名稱自動推導，Step 4.5 會顯示讓使用者確認。

### 錯誤處理

- **MCP 不可用**（無 MCPControl）→ 自動降級為手動模式：生成 prompt 並複製到剪貼簿，提示使用者手動開新 session 貼上
- **自動化步驟失敗** → 同上手動模式 fallback

---

## 輸入

$ARGUMENTS

## Step 1: 收集可續接的工作

掃描以下來源：

1. **進行中的工作單元**：掃描 atoms 中標記為 🔄 的工作單元
2. **Todo list**：檢查是否有未完成的 todo items
3. **最近的 git 變更**：`git status` + `git log --oneline -5`
4. **暫存區**：檢查 `{project_root}/.claude/memory/_staging/` 或 `projects/{slug}/memory/_staging/` 是否有續接 prompt

### 分流邏輯

- **有 $ARGUMENTS** → 直接以 $ARGUMENTS 為下一步指示，跳到 Step 2
- **無 $ARGUMENTS** → 列出所有找到的可續接工作，格式如下，等待使用者選擇後再繼續：

```
找到 N 個可續接的工作：
  1. [{工作名稱}] {摘要}（{日期}，🔄）
  2. [{工作名稱}] {摘要}（{日期}，🔄）
  3. [最近 commit] {commit message}（{hash}）

請選擇（數字），或輸入新的指示：
```

- **無 $ARGUMENTS 且無任何可續接工作** → 提示「找不到未完成的工作，請指定下一步」，結束

## Step 2: 彙整工作狀態

根據選定的工作（來自使用者選擇或 $ARGUMENTS），彙整：
- **已完成**：本 session 完成了什麼（1-3 句）
- **下一步**：接下來要做什麼（具體步驟）
- **關鍵上下文**：新 session 需要知道的檔案路徑、決策、注意事項

## Step 3: 生成續接 Prompt

根據 Step 2 的彙整，生成一個**自包含**的續接 prompt。格式：

```
[續接] {任務名稱}

## 背景
{1-3 句說明這個任務的來龍去脈}

## 已完成
{上一個 session 做完的事，條列}

## 本階段目標
{這個 session 要完成的具體步驟，條列}

## 關鍵上下文
- 相關檔案：{路徑列表}
- 注意事項：{任何新 session 需要知道的坑點或決策}

## 完成條件
{怎樣算完成，包括驗證方式}

完成後請執行：驗證 → 上 GIT → 如有下一階段則再次 /resume
```

**重要**：prompt 必須自包含——新 session 不會有當前 session 的 context，所以所有必要資訊都要寫進去。

## Step 4: 確認 + 選擇開啟方式

將生成的 prompt 顯示給使用者，並提供開啟方式選擇：

```
續接 prompt 已準備好。請選擇開啟方式：

  A. 新 VS Code 視窗（MCPControl 自動化：開新視窗 → 開 Claude Code panel → 貼上執行）
  B. 當前視窗新 Tab（MCPControl 自動化：在目前視窗開新 Claude Code tab → 貼上執行）
  C. 終端機 CLI（在 VS Code 終端執行 claude "prompt"，最可靠但為終端模式）
  D. 手動模式（prompt 複製到剪貼簿，你自己開 session 貼上）

請選擇（A/B/C/D），或直接 Enter 使用 D：
```

等待使用者選擇。如果使用者要修改 prompt 內容，根據回饋調整後再次確認。

## Step 4.5: 存入 Staging（安全網）

使用者確認 prompt 後，決定檔案名稱並寫入**專案層** staging 路徑（確保目錄存在）：

### 檔案命名

```
~/.claude/projects/{slug}/memory/_staging/next-phase-{name}.md
```

`{name}` 的決定順序：
1. **有 `--name` 參數** → 直接使用
2. **無 `--name`** → 從 Step 3 生成的任務名稱自動推導短名（英文小寫、空格換 `-`、去除特殊字元、不超過 40 字元）
3. 推導後**顯示檔名讓使用者確認**：`「將存為 next-phase-{name}.md，OK？」`

> `{slug}` 從系統 context 的 project memory 路徑推算，與 `/continue` 讀取路徑一致。
> 例：工作目錄 `C:\Projects\MyApp` → slug `c--Projects-MyApp`、name `ui-refactor` → 寫入 `~/.claude/projects/c--Projects-MyApp/memory/_staging/next-phase-ui-refactor.md`

若同名檔案已存在，顯示舊內容第一行並詢問是否覆蓋。

這樣即使後續 MCP 自動化失敗，使用者仍可透過 `/clear` → `/continue {name}` 銜接。

## Step 5: 執行

### 5.0 前置準備

1. **MCP 可用性檢查**（選項 A/B 需要）：嘗試呼叫 `mcp__MCPControl__computer`（`action: "get_screenshot"`）。若失敗 → 告知使用者 MCPControl 不可用，自動降級為選項 D（手動模式）。
2. **將 prompt 寫入剪貼簿**（選項 A/B/D 需要）：

```bash
echo '續接 prompt 內容' | powershell -command "Set-Clipboard -Value ([Console]::In.ReadToEnd())"
```

> 注意：MCPControl 沒有 set_clipboard action，剪貼簿寫入一律透過 PowerShell。

---

### 選項 A: 新 VS Code 視窗

**原理**：透過 Command Palette 執行 "Claude Code: Open in New Window"，在獨立 VS Code 視窗開啟新 Claude Code session。

1. 開啟 Command Palette：
   `mcp__MCPControl__computer`（`action: "key", text: "ctrl+shift+p"`）
2. 輸入指令名稱：
   `mcp__MCPControl__computer`（`action: "type", text: "Claude Code: Open in New Window"`）
3. 等待 1 秒讓選單出現，按 Enter 執行：
   `mcp__MCPControl__computer`（`action: "key", text: "enter"`）
4. 等待 8 秒讓新視窗載入完成
5. 截圖確認新視窗狀態：
   `mcp__MCPControl__computer`（`action: "get_screenshot"`）
6. **辨識新視窗的 Claude Code 輸入框位置**（從截圖中找到輸入框，不使用硬編碼座標）
7. 點擊輸入框：
   `mcp__MCPControl__computer`（`action: "left_click", coordinate: [辨識到的 x, y]`）
8. 貼上 prompt：
   `mcp__MCPControl__computer`（`action: "key", text: "ctrl+v"`）
9. 截圖確認 prompt 已貼上：
   `mcp__MCPControl__computer`（`action: "get_screenshot"`）
   - 如果貼到了編輯器而非輸入框 → `Ctrl+Z` 撤銷 → 重新辨識輸入框位置 → 點擊 → 再貼上
10. 按 Enter 開始執行：
    `mcp__MCPControl__computer`（`action: "key", text: "enter"`）
11. 等待 5 秒後截圖，確認新 session 已開始處理

---

### 選項 B: 當前視窗新 Tab

**原理**：透過 Command Palette 執行 "Claude Code: Open in New Tab"，在當前 VS Code 視窗開新 tab。

**已知問題**：同視窗多個 Claude Code webview 可能有焦點衝突（輸入框座標重疊）。

1. 開啟 Command Palette：
   `mcp__MCPControl__computer`（`action: "key", text: "ctrl+shift+p"`）
2. 輸入指令名稱：
   `mcp__MCPControl__computer`（`action: "type", text: "Claude Code: Open in New Tab"`）

   > **注意**：不要用快捷鍵 `Ctrl+Shift+Esc`，此為 Windows Task Manager 快捷鍵，會被系統攔截。

3. 按 Enter 執行：
   `mcp__MCPControl__computer`（`action: "key", text: "enter"`）
4. 等待 3 秒讓新 tab 載入
5. 截圖確認新 tab 狀態：
   `mcp__MCPControl__computer`（`action: "get_screenshot"`）
6. **辨識新 tab 的 Claude Code 輸入框位置**（新 tab 應自動獲得焦點，但需截圖確認）
7. 點擊輸入框：
   `mcp__MCPControl__computer`（`action: "left_click", coordinate: [辨識到的 x, y]`）
8. 貼上 prompt：
   `mcp__MCPControl__computer`（`action: "key", text: "ctrl+v"`）
9. 截圖確認 prompt 已貼上到正確的 tab（而非舊的 Claude Code 面板）：
   `mcp__MCPControl__computer`（`action: "get_screenshot"`）
   - **焦點衝突處理**：如果 prompt 貼到了舊面板 → `Ctrl+Z` 撤銷 → 點擊新 tab 標題切換焦點 → 再次點擊輸入框 → 重新貼上
10. 按 Enter 開始執行：
    `mcp__MCPControl__computer`（`action: "key", text: "enter"`）
11. 等待 5 秒後截圖，確認新 session 已開始處理

---

### 選項 C: 終端機 CLI

**原理**：將 prompt 寫入暫存檔，在 VS Code 終端用 `claude` CLI 帶初始 prompt 啟動。最可靠，但為終端模式（非 VS Code panel）。

1. 將 prompt 寫入暫存檔：

```bash
# 將 prompt 寫入專案層 _staging 目錄（{slug} 同 Step 4.5）
cat > ~/.claude/projects/{slug}/memory/_staging/_resume_prompt.txt << 'PROMPT_EOF'
{續接 prompt 內容}
PROMPT_EOF
```

2. 在 VS Code 終端執行：

```bash
claude "$(cat ~/.claude/projects/{slug}/memory/_staging/_resume_prompt.txt)"
```

> 如果 prompt 過長（超過 shell 參數上限），改用管道：
> ```bash
> cat ~/.claude/projects/{slug}/memory/_staging/_resume_prompt.txt | claude -p
> ```
> 注意：`-p` 為非互動模式（print 完即退出）。若需互動，可先 `claude` 啟動後再手動貼上。

3. 清理暫存檔（新 session 確認開始後）：

```bash
rm ~/.claude/projects/{slug}/memory/_staging/_resume_prompt.txt
```

---

### 選項 D: 手動模式

**原理**：prompt 已透過 Step 5.0 複製到剪貼簿，使用者自行開啟新 session 貼上。

1. 確認 prompt 已在剪貼簿（Step 5.0 已完成）
2. 提示使用者：

> 「續接 prompt 已複製到剪貼簿。請自行開啟新 Claude Code session（Ctrl+Shift+P → Claude Code: Open in New Tab / New Window，或終端輸入 `claude`），然後 Ctrl+V 貼上執行。」

---

## Step 6: 回報

根據執行結果回報：

**自動化成功（A/B/C）**：
> 「✅ 新 session 已啟動。續接 prompt 也已存入 staging 備份。」

**自動化失敗，降級為手動**：
> 「⚠ 自動開啟失敗。續接 prompt 已存入 staging，請 `/clear` → `/continue` 銜接。」

**手動模式（D）**：
> 「📋 續接 prompt 已複製到剪貼簿，也已存入 staging。可 `/clear` → `/continue` 或手動貼上。」
