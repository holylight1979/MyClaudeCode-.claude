# /memory-peek — V4.1 自動萃取檢視

> 列最近 24h 自動萃取的 atom + pending candidates + trigger 原因 [F7]。
> 對應 plan v2 §6 P3。

---

## 使用方式

```
/memory-peek              # 列最近 24h（預設）
/memory-peek --since=48h  # 自訂時間窗
```

---

## Step 0: 偵測 user + project

```bash
python - <<'PY'
import os, sys, json
sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
from wg_paths import find_project_root, CLAUDE_DIR
from wg_roles import get_current_user
root = find_project_root(os.getcwd())
user = get_current_user()
print(json.dumps({
    "root": str(root) if root else "",
    "user": user,
    "claude_dir": str(CLAUDE_DIR),
}))
PY
```

---

## Step 1: 呼叫 backend

```bash
python ~/.claude/tools/memory-peek.py --user={user} --project-cwd="$(pwd)" $ARGS
```

`$ARGS` = 使用者傳入的額外參數（`--since=48h` 等）。

---

## Step 2: 呈現結果

將 backend JSON 輸出格式化呈現：

```
[V4.1 最近 24h 萃取]
✓ 已寫入 (N 條)
  1. 「{statement}」 → {path} (trigger: {triggers})
  2. ...
⏳ 待確認 (M 條)
  3. 「{statement}」 → _pending.candidates (conf: {conf}, 待 review)
  ...

提示：/memory-undo last 可撤銷最近一條
```

若 N=0 且 M=0 → 告知使用者「最近 24h 沒有自動萃取紀錄。」

---

## Step 3: 回報

列出統計：已寫入 N 條、待確認 M 條。提示可用 `/memory-undo` 撤銷。
