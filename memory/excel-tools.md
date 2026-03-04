# Excel 讀取能力（全域）

- Scope: global
- Confidence: [固]
- Trigger: Excel, xls, xlsx, 讀取, 試算表, spreadsheet, openpyxl, xlrd
- Last-used: 2026-03-04
- Confirmations: 2

## 知識

### 工具位置與依賴

- 腳本: `C:\Users\holylight\.claude\tools\read-excel.py`
- 依賴: Python 3.14 + openpyxl (.xlsx/.xlsm) + xlrd (.xls)
- 呼叫: `python3 ~/.claude/tools/read-excel.py`（透過 Bash tool）

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

### 典型分析流程

1. `--sheets` 列出所有 sheet
2. `--search "關鍵字"` 定位行列位置
3. `--rows X-Y --cols A-B --raw` 精確讀取內容

## 行動

- 讀取任何 Excel 檔案時，用 Bash tool 呼叫此腳本
- 先 `--sheets` 再 `--search` 再精確範圍，三步定位
- 大檔案先用 `--max-rows` 限制輸出量
