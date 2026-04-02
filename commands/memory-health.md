# /memory-health — 記憶品質診斷

> 合併執行 `memory-audit.py` + `atom-health-check.py`，一次產出完整健康報告。
> 有專案自治層（`{project_root}/.claude/memory/`）時，優先診斷專案層。

---

## 使用方式

```
/memory-health
/memory-health --json
```

- 無參數：人類可讀報告
- `--json`：JSON 格式輸出（供程式處理）

---

## 參數解析

從 `$ARGUMENTS` 取得參數：
- 若包含 `--json` → 兩個工具都加 `--json` flag
- 否則 → 正常文字輸出

---

## Step 0: 偵測專案記憶目錄

用 Bash tool 執行：

```bash
python -c "
import sys, os
sys.path.insert(0, os.path.expanduser('~/.claude/hooks'))
try:
    from wg_paths import get_project_memory_dir
    d = get_project_memory_dir(os.getcwd())
    print(d or '')
except Exception:
    print('')
"
```

- 若輸出非空 → 記為 `PROJECT_MEM_DIR`，後續工具加 `--project-dir $PROJECT_MEM_DIR`
- 若輸出為空 → 純全域模式，不加 `--project-dir`

---

## Step 1: 執行 memory-audit

用 Bash tool 執行：

```bash
python ~/.claude/tools/memory-audit.py [--project-dir $PROJECT_MEM_DIR] [--json]
```

捕獲完整輸出。此工具檢查：
- Atom 格式驗證（frontmatter、必要欄位）
- 過期 atom 偵測（依 Confidence 層級）
- 晉升/降級建議（依 Confirmations 計數）
- 重複偵測
- MEMORY.md 索引一致性
- 若有 `--project-dir`：**專案層排在全域層之前**

## Step 2: 執行 atom-health-check

**若有 PROJECT_MEM_DIR**，先診斷專案層，再診斷全域層（並行執行）：

```bash
# 專案層
python ~/.claude/tools/atom-health-check.py --report [--json] --memory-root $PROJECT_MEM_DIR

# 全域層
python ~/.claude/tools/atom-health-check.py --report [--json]
```

**若無 PROJECT_MEM_DIR**，只診斷全域層：

```bash
python ~/.claude/tools/atom-health-check.py --report [--json]
```

捕獲輸出。此工具檢查：
- Related 欄位參照完整性（斷裂參照）
- Staleness 偵測（Last-used > 60 天）
- 整體健康報告

## Step 3: 綜合報告

將所有工具輸出整合，格式：

```
## 記憶健康報告

{若有 PROJECT_MEM_DIR → 標記 📁 專案層：{PROJECT_MEM_DIR}}

### 格式驗證
{memory-audit 格式檢查結果（專案層 + 全域層分開標示）}

### 過期 / Staleness
{memory-audit 過期 + atom-health-check staleness 合併}

### 參照完整性
{atom-health-check Related 檢查結果（若有專案層則兩層分開）}

### 晉升/降級建議
{memory-audit 建議}

### 重複偵測
{memory-audit 重複檢查結果}

### 索引一致性
{memory-audit MEMORY.md 一致性}
```

- 每個區塊：有問題列出、無問題標記 ✓
- 末尾加總結：N 個問題需處理 / 全部健康

## Step 4: 互動

如果發現問題，詢問使用者是否要立即修正：
- 格式錯誤 → 提供修正方案
- 斷裂參照 → 建議移除或補上
- 過期 atom → 建議封存或更新 Last-used
- 索引不一致 → 提供 MEMORY.md 修正
