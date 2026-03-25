# Excel 讀取能力（全域）

- Scope: global
- Confidence: [固]
- Type: procedural
- Trigger: Excel, xls, xlsx, 試算表, spreadsheet, openpyxl, xlrd
- Last-used: 2026-03-25
- Created: 2026-03-03
- Confirmations: 21
- Tags: tool, excel, python

## 知識

### 工具

- [固] 腳本: `~/.claude/tools/read-excel.py`
- [固] 依賴: Python 3.14 + openpyxl (.xlsx/.xlsm) + xlrd (.xls)
- [固] 呼叫: `python3 ~/.claude/tools/read-excel.py`（Bash tool）

### 操作配方

| 目的 | 指令 |
|------|------|
| 列出工作表 | `--sheets` |
| 搜尋文字 | `--search "關鍵字"` |
| 讀指定行列 | `--rows 1-50 --cols 1-10` |
| Excel 座標 | `--range A1:F20` |
| 指定工作表 | `--sheet "名稱"` 或 `--sheet 0` |
| 不截斷 | `--raw --max-rows 500` |
| TSV + grep | `--tsv --max-rows 999 \| grep "欄位"` |
| 檢查檔頭 | `--rows 1-5 --raw --max-cols 50` |

## 行動

- 讀任何 Excel 用 Bash tool 呼叫此腳本
- 三步定位: `--sheets` → `--search` → `--rows X-Y --raw`
- 大檔案先 `--max-rows` 限制

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-03 | 建立為 [固] | session:工具整理 |
| 2026-03-04 | v2.2 格式升級 | session:記憶刷新 |
