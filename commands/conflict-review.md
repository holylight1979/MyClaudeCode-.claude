# /conflict-review — 管理職裁決 Pending Queue

> V4 Phase 5：列 `shared/_pending_review/` 的草稿與衝突報告，引導管理職 approve / reject。
> **雙向認證**（SPEC §6.2）：personal role.md 自宣告 + shared `_roles.md` 白名單，缺一不可。

---

## 使用方式

```
/conflict-review                # 列 pending + 互動選擇
/conflict-review list           # 只列、不互動
/conflict-review approve <target>
/conflict-review reject  <target>  [--reason=...]
```

`<target>` 為 pending 檔名（含或不含 `.md`），例：
- `addressable-loading` — 會找 `addressable-loading.md`（atom 草稿）
- `addressable-loading.conflict` — 會找 `.conflict.md`（CONTRADICT 報告）

---

## Step 0: 偵測 project root + 當前 user

用 Bash tool 執行：

```bash
python - <<'PY'
import os, sys, json
sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
from wg_paths import find_project_root
from wg_roles import get_current_user, is_management
root = find_project_root(os.getcwd())
user = get_current_user()
print(json.dumps({
    "root": str(root) if root else "",
    "user": user,
    "is_management": is_management(os.getcwd(), user) if root else False,
}))
PY
```

- `root` 為空 → 非 V4 專案 → 告知使用者並停止
- `is_management=false` → 繼續 **list**（唯讀），但 approve/reject 會被 backend 拒絕
- `is_management=true` → 全部動作可用

---

## Step 1: 列 pending 清單

```bash
python ~/.claude/tools/conflict-review.py --list --project-cwd="$(pwd)"
```

輸出 JSON：每筆含 `kind` (`draft` | `conflict` | `pull-conflict`)、`target`、`file`、`author`、`detected_at`、`preview`。

---

## Step 2: 呈現給使用者

```
## Pending Queue ({N} 筆)

### Drafts（可 approve 直接落地到 shared/）
1. {target}  by {author}  detected {ts}
   preview: {first bullet of 知識...}

### Conflicts（CONTRADICT 報告，需先人工解決再 approve）
2. {target}.conflict  detected {ts}
   衝突對象: {既有 atom}
   similarity: 0.89
   preview: {incoming 知識前 80 字}

### Pull-time flags（git pull 後偵測）
3. {target}.pull-conflict  detected {ts}
   ...
```

---

## Step 3: 互動

依使用者要求執行：

- **approve draft**：
  ```bash
  python ~/.claude/tools/conflict-review.py \
    --action=approve --target=<name> --project-cwd="$(pwd)"
  ```
  backend 會：
  1. 驗證 `is_management`
  2. 搬 `_pending_review/{name}.md` → `shared/{name}.md`
  3. 移除 `Pending-review-by:`、加 `Decided-by: {user}`、更新 `Last-used`
  4. 寫 `_merge_history.log`（action=approve）
  5. 觸發 vector reindex（POST 3849/reindex）

- **approve conflict**：
  CONTRADICT 報告本身無草稿可 approve。流程：
  1. 管理職手動編輯 `_pending_review/{name}.conflict.md` → 寫成解決版 atom `{name}.resolved.md`（atom 格式）
  2. 再跑 `approve --target={name}.resolved`，backend 搬 `.resolved.md` 為 `shared/{name}.md`，同時刪除 `.conflict.md`

- **reject**：
  ```bash
  python ~/.claude/tools/conflict-review.py \
    --action=reject --target=<name> --project-cwd="$(pwd)" \
    --reason="<短理由>"
  ```
  刪 pending 檔、寫 merge_history（action=reject）、既有 shared/ atom 不動。

---

## Step 4: 回報

列出做了什麼：搬了哪些檔、merge_history 新增幾行、reindex 是否成功。

若 backend 回 `{"error": "not authorized as management"}` → 告知使用者認證未通過，指引：
- 檢查 `{proj}/.claude/memory/personal/{user}/role.md` 是否含 `Management: true` 或 `Role: ..., management`
- 檢查 `{proj}/.claude/memory/_roles.md` 的 `## Management 白名單` 是否列 user
