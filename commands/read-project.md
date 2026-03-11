# /read-project — 專案文件閱讀與知識截錄

> 系統性閱讀指定目錄或文件，產出 doc-index atom 供未來 session 檢索。
> 全域 Skill，適用任何專案。

---

## 使用方式

```
/read-project <目標路徑或關鍵詞> [選項]
```

### 參數

| 參數 | 必填 | 說明 | 範例 |
|------|------|------|------|
| 目標 | 是 | 目錄路徑、檔案路徑、或描述關鍵詞 | `C:\Projects\sgi_client\DesignDoc\` |

### 選項（自然語言附加在參數後）

- **深度**：「只看目錄結構」/「讀摘要」/「詳細閱讀」（預設：讀摘要）
- **範圍**：「前 20 份」/「只看 .cs」/「只看 .xls」（預設：全部）
- **輸出名稱**：「存為 xxx」（預設：自動從目錄名生成）

### 使用範例

```
/read-project C:\Projects\sgi_client\DesignDoc\
/read-project C:\Projects\sgi_server\MapServer\ 只看 .cs 詳細閱讀
/read-project C:\Projects\sgi_client\DesignDoc\ 前 10 份 存為 combat-specs
```

### 錯誤處理

- **未帶參數** → 顯示本使用說明，結束
- **路徑不存在** → 提示「路徑 X 不存在，請確認」，結束
- **目錄為空** → 提示「目錄 X 下無可讀取的文件」，結束

---

## 執行流程

### Step 1: 解析參數與確認目標

1. 解析 `$ARGUMENTS`，分離路徑和選項
2. 若未帶參數（`$ARGUMENTS` 為空）→ 顯示「使用方式」段落，結束
3. 驗證路徑存在（Bash `ls` 或 `test -e`）
4. 列出目標文件清單（依副檔名/範圍過濾），排除二進位檔（.dll, .bytes, .png, .jpg, .meta, .asset 等）
5. 向使用者確認：「找到 N 份文件，預計用 {深度} 模式閱讀。開始？」

### Step 2: 系統性閱讀

依深度設定逐一處理每份文件：

**目錄結構模式**（最快）：
- 只記錄路徑 + 從檔名推斷用途

**讀摘要模式**（預設）：
- Read 每份文件前 50-100 行
- 摘要要點（1-2 句）
- 記錄關鍵連結/依賴

**詳細閱讀模式**（最慢）：
- Read 完整文件
- 記錄：用途、核心邏輯、對外介面、依賴關係
- 標記特別重要的段落

**Excel 檔案**：使用 `python ~/.claude/tools/read-excel.py` 讀取（先 `--sheets` 列出 sheet，再依需要讀取內容）。

進度回報：每 10 份或每個子目錄完成時簡短回報進度。

### Step 3: 產出 doc-index atom

寫入專案層 memory（若無專案層則寫全域層）。

檔案路徑：`memory/doc-index-{名稱}.md`

格式範例：

```markdown
# {目錄名稱} 文件索引

- Scope: project
- Confidence: [臨]
- Type: semantic
- Trigger: {從內容萃取 3-8 個關鍵詞}
- Last-used: {今日日期}
- Created: {今日日期}
- Confirmations: 0

## 知識

### {分類 A}
- `路徑/檔案1.ext` — 摘要（1-2 句）
- `路徑/檔案2.ext` — 摘要（1-2 句）

### {分類 B}
- `路徑/檔案3.ext` — 摘要（1-2 句）

## 行動

- 需要詳細內容時 Read 原檔
- 開發相關工具時以此索引為起點
```

若內容超過 200 行 → 按分類拆分為 `doc-index-{名稱}-01.md`, `-02.md`...

### Step 3.5: 寫入 _AIDocs（若存在）

若專案根目錄有 `_AIDocs/`，同步產出人讀版文件：

1. **建立/更新** `_AIDocs/DocIndex-{名稱}.md`：
   - 標題：`# {目錄名稱} 文件索引`
   - **不含** atom metadata（無 Trigger/Confidence/Last-used 等）
   - 與 atom 相同的分類檔案列表，但使用完整描述
   - 底部加「速查」段落，將常見問題對應到檔案

2. **更新 `_AIDocs/_INDEX.md`**：在文件清單表格加一列
   `| N+1 | DocIndex-{名稱}.md | 文件索引 — {來源目錄簡述} |`

3. **追加 `_AIDocs/_CHANGELOG.md`**：
   `| {日期} | **read-project**: 新增 DocIndex-{名稱}.md（{N} 份文件索引） | DocIndex-{名稱}.md |`

若無 `_AIDocs/` → 跳過此步驟，僅寫 atom。

### Step 4: 更新索引

1. 將新 atom 加入對應層的 MEMORY.md 索引表
2. 向量索引由 PostToolUse hook 自動觸發，無需手動處理

### Step 5: 回報結果

向使用者彙報：
- 閱讀了多少份文件
- 產出了哪些 atom（含路徑）
- 關鍵發現摘要
- 建議後續可深入閱讀的方向

---

## 注意事項

- 不修改原始文件，只讀取和記錄
- 大型目錄（100+ 檔案）建議分批執行，或用「只看目錄結構」模式先總覽再挑重點
- 二進位檔案自動跳過
- 產出的 atom 為 [臨]，經後續 session 使用確認後依正常流程晉升
- 同一目錄重複執行時，更新既有 atom 而非建立新的（檢查是否已有同名 doc-index atom）
