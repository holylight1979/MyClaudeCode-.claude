# /memory-undo — V4.1 撤銷自動萃取

> 撤銷 `auto-extracted-v4.1` 寫入的 atom，搬到 `_rejected/` 並記錄原因 [F20][F23]。
> 對應 plan v2 §6 P3。

---

## 使用方式

```
/memory-undo              # 撤最近一條（= last）
/memory-undo last         # 同上
/memory-undo --since=24h  # 批撤最近 24h
/memory-undo --since=2026-04-16  # 批撤指定日期後
/memory-undo --all-from-today    # 當日全撤
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

## Step 1: 列出候選（dry-run）

```bash
python ~/.claude/tools/memory-undo.py --user={user} --project-cwd="$(pwd)" --list $ARGS
```

`$ARGS` = 使用者的 `last` / `--since=...` / `--all-from-today`。

呈現將被撤銷的 atom 清單，請使用者確認。

---

## Step 2: 收集 reject reason [F23]

**必須在撤銷前詢問使用者**，摩擦力 ≤ 2 次 enter：

```
請選擇撤銷原因：
(a) 情緒誤抓 — 情緒性發言被誤判為決策
(b) 含蓄誤判 — 試探/討論被當成決定
(c) 隱私越界 — 不應被記錄的個人資訊
(d) scope 錯 — 應歸 shared/role 但寫到 personal（或反之）
(e) 其他
```

使用者回覆字母即可（預設 a）。

---

## Step 3: 執行撤銷

```bash
python ~/.claude/tools/memory-undo.py --user={user} --project-cwd="$(pwd)" --execute --reason={reason} $ARGS
```

---

## Step 4: 回報

呈現 backend 回傳的結果：

```
已撤銷 N 條 atom。
原因：{reason_label}
reflection_metrics 已更新。
/memory-peek 查看剩餘。
```
