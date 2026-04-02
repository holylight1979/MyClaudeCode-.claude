# /conflict — 記憶衝突偵測

> 手動觸發向量衝突偵測，找出語意相似但內容矛盾的 atom 條目。
> 有專案自治層時，自動納入專案層一起掃描。

---

## 使用方式

```
/conflict              # 全量掃描
/conflict atom名稱     # 只掃描指定 atom 的衝突
/conflict --dry-run    # 只列出候選對，不呼叫 LLM 判定
```

---

## 參數解析

從 `$ARGUMENTS` 取得：
- 空 → 全量掃描
- atom 名稱 → `--atom {名稱}`
- `--dry-run` → 只列候選不判定

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

若輸出非空 → 記為 `PROJECT_MEM_DIR`，後續加 `--project-dir $PROJECT_MEM_DIR`。

---

## Step 1: 確認前置條件

並行檢查：

1. 向量服務是否運行：
```bash
curl -s http://127.0.0.1:3849/health 2>/dev/null
```

2. Ollama 是否可用（LLM 判定需要）：
```bash
curl -s http://127.0.0.1:11434/api/tags 2>/dev/null | head -1
```

- 向量服務未運行 → 建議先 `/vector start`
- Ollama 未運行 → 可用 `--dry-run` 模式（只列候選，不做 LLM 判定）

## Step 2: 執行衝突偵測

用 Bash tool 執行：

```bash
python ~/.claude/tools/memory-conflict-detector.py [--atom X] [--dry-run] [--project-dir $PROJECT_MEM_DIR] --json
```

捕獲 JSON 輸出。

## Step 3: 解讀結果

解析衝突偵測結果，每組衝突包含：
- **atom_a** / **atom_b**：衝突的兩個 atom
- **item_a** / **item_b**：具體條目內容
- **relationship**：AGREE / CONTRADICT / EXTEND / UNRELATED
- **similarity**：向量相似度分數
- **verdict**：LLM 判定說明

過濾出 `CONTRADICT` 和值得關注的 `EXTEND` 結果。

## Step 4: 報告

格式：

```
## 衝突偵測報告

掃描 N 個 atoms，找到 M 組衝突候選，K 組確認矛盾。

### 矛盾（CONTRADICT）
1. **{atom_a}** vs **{atom_b}**
   - A: {item_a 摘要}
   - B: {item_b 摘要}
   - 相似度: {score}
   - 判定: {verdict}

### 延伸（EXTEND）
{同格式}

### 一致（AGREE）— 可能重複
{同格式}
```

## Step 5: 互動處理

對每組矛盾，詢問使用者：
- **CONTRADICT** → 哪個是正確的？要修正/刪除哪一方？
- **EXTEND** → 要合併到同一條目嗎？
- **AGREE（疑似重複）** → 要合併或刪除其一嗎？

確認後執行修正。
