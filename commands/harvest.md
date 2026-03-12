# /harvest — Google Docs/Sheets/Slides 收割工具

> 啟動 Playwright Chrome 瀏覽器，邊瀏覽邊自動收割 Google Docs/Sheets/Slides 為 Markdown/CSV/PDF。
> 工具位於 `~/.claude/tools/gdoc-harvester/`。

---

## 參數

- `$ARGUMENTS` 可傳入：
  - `start` — 開始收割（必填，無此關鍵字則顯示說明）
  - `--workdir DIR` — 工作目錄（預設 `c:/tmp/harvester`）
  - `--depth N` — 連結追蹤深度（預設 1）
  - `--fresh` — 清空 browser-data 重新開始（需在瀏覽器內重新登入）
  - `--copy-chrome` — 從 Chrome 複製登入狀態（需先關閉 Chrome，可選）

---

## 執行流程

### Step 1: 參數檢查

檢查 `$ARGUMENTS` 是否包含 `start`。

如果**沒有** `start`（空白或其他），直接向使用者顯示以下說明後結束，不做其他事：

```
/harvest — Google Docs/Sheets 收割工具

使用方式：
  /harvest                ← 顯示此說明
  /harvest start          ← 開始收割（互動確認路徑）
  /harvest start --workdir D:/my-harvest
  /harvest start --depth 2
  /harvest start --fresh       ← 清空登入資料重新開始
  /harvest start --copy-chrome ← 從 Chrome 複製登入（需關 Chrome）

功能：
  啟動 Chrome 瀏覽器，邊瀏覽邊自動收割 Google Docs/Sheets/Slides。
  - Google Docs → Markdown (.md)
  - Google Sheets → CSV + Markdown
  - Google Slides → PDF + Markdown（索引）
  - 文件內連結自動追蹤（可設深度）
  - 結束後自動產生 _INDEX.md 總清單

工作目錄（預設 c:/tmp/harvester/）：
  browser-data/  — 瀏覽器登入資料（含敏感資料，用完建議刪除）
  output/        — 收割結果

注意：
  - 首次使用需在收割瀏覽器內登入 Google（登入狀態自動保留）
  - 不需關閉你正在使用的 Chrome
  - 完成後請自行評估是否清理 browser-data/
```

如果有 `start` → 繼續。

### Step 2: 確認工作目錄

從 `$ARGUMENTS` 解析 `--workdir`，若無則預設 `c:/tmp/harvester`。

用 AskUserQuestion 向使用者確認：

> **工作目錄確認**
>
> 收割工具將使用以下工作目錄：`{workdir}`
>
> 目錄內容：
> - `browser-data/` — Chrome 登入狀態副本（含所有網站 cookies，屬敏感資料）
> - `output/` — 收割結果（Markdown / CSV）
>
> 收割完成後，請自行評估是否刪除 `browser-data/` 下的敏感資料。
>
> 選項：使用此路徑 / 自訂路徑

### Step 3: 認證準備

檢查 `{workdir}/browser-data/` 是否存在：

**不存在**：
- 告知使用者：「首次使用，瀏覽器啟動後請先登入 Google 帳號。登入狀態會自動保留到下次。」
- **不需要關閉 Chrome。**

**已存在（非 --fresh）**：
- 直接使用，不需詢問。

**--fresh**：
- 告知使用者：「將清空現有登入資料，瀏覽器啟動後需重新登入。」

**--copy-chrome**：
- 需要使用者先關閉 Chrome。用 AskUserQuestion 確認。

### Step 4: 環境檢查

確認 Python 依賴：
```bash
python -c "import playwright, markdownify, bs4" 2>&1
```
- 若失敗 → `python -m pip install playwright markdownify beautifulsoup4`

確認 Playwright Chrome：
```bash
python -m playwright install chrome 2>&1
```

### Step 5: 以 Agent 背景啟動

**重要：使用 Agent 工具以 `run_in_background: true` 啟動**，讓使用者可以繼續對話。

Agent 的任務：
```bash
cd ~/.claude/tools/gdoc-harvester && python harvester.py --workdir {workdir} {其他參數} 2>&1
```

啟動後告知使用者：

> 收割瀏覽器已啟動！
> - **Dashboard**: http://127.0.0.1:8787（瀏覽器內的第一個 tab）
> - 正常瀏覽 Google Docs/Sheets，工具會自動擷取
> - 關閉所有瀏覽分頁（保留 Dashboard）即結束收割
>
> 你可以繼續跟我對話，收割結束後我會回報結果。

### Step 6: 結束後報告

Agent 回報結果後：

1. 讀取 `{workdir}/output/_INDEX.md`，向使用者呈現總清單內容
2. 告知：
   - 📁 收割結果在 `{workdir}/output/`，總清單見 `_INDEX.md`
   - ⚠️ `{workdir}/browser-data/` 含有瀏覽器登入資料（所有網站 cookies），如不再需要請手動刪除。

---

## 內部網站登入

如需存取 GitLab 等內部網站，首次請在收割瀏覽器中手動登入。
Playwright persistent context 會記住登入狀態，下次啟動（不加 `--fresh`）無需重新登入。

## 已知限制

- 首次使用需在收割瀏覽器裡登入 Google（之後自動保留）
- `--copy-chrome` 需關閉 Chrome（可選功能，非必要）
- 部分 Google Workspace 文件可能因帳號權限不同而匯出失敗
- 同一 doc_id 只會收割一次（跨 URL fragment 去重）
- Sheet export 目前只匯出第一個 tab（後續改善項目）
- Slides 匯出為 PDF（無 HTML export），不會提取頁面內連結
