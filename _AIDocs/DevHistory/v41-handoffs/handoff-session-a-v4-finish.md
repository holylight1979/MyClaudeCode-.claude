# Session A — V4 收尾：漸進遷移 + Health Check + 文件

> **模式**：不用 Plan Mode，直接執行。Permission 建議 yolo 或 auto-accept。
> **CWD**：目標專案目錄（如 `c:\tmp\docs-progg`）
> **GIT**：各專案各自 commit，不等其他 session。

---

## 目標

在 1-2 個既有專案完成 V4 漸進啟用，驗證三層 scope + JIT + 衝突偵測正常運作。

## 開工前必讀

- `_AIDocs/Architecture.md` line 188+（三時段衝突流程圖）
- `_AIDocs/SPEC_ATOM_V4.md` §10（漸進遷移）
- `commands/init-roles.md`（互動引導步驟）

## 步驟

### 1. 挑 `c:\tmp\docs-progg` 跑 migration

```bash
python ~/.claude/tools/migrate-v3-to-v4.py --project="c:\tmp\docs-progg"
```

- 檢視 dry-run 報告（列需補的 Scope/Author/Created-at metadata）
- 沒問題加 `--apply` 真正寫入

### 2. 在 `c:\tmp\docs-progg` 跑 /init-roles

- 建 personal role.md（holylight, programmer）
- scaffold shared `_roles.md`
- 詢問裝 post-merge hook

### 3. 驗證

- 確認 SessionStart 輸出 `[Role] user=holylight roles=programmer mgmt=False`
- `/memory-health` 看 V4 atoms 格式合規
- `/vector` 確認索引含 layer 欄位（shared/role/personal/global）
- 模擬 CONTRADICT：對該專案 1 個 shared atom，用 atom_write MCP 寫語意相反內容 → 驗 `_pending_review/{slug}.conflict.md` 自動產生

### 4. 第二個專案（optional）

若時間夠，對 `c:\Projects`（sgi）跑同樣流程。

### 5. 文件

- README.md 是否需補 V4 段（多職務 + 衝突 + scope 三層）
- `_AIDocs/Project_File_Tree.md` 更新（personal/、shared/_pending_review/、_roles.md）

### 6. 上 GIT

各專案各自 commit。`~/.claude` repo 的 _AIDocs 變更也 commit。

## 完成標準

- ≥ 1 專案 V4 啟用 + SessionStart [Role] + JIT 正常
- CONTRADICT 模擬成功產出 .conflict.md
- 文件同步
- 已 commit

## 已知小坑（觀察用）

- USER.md 是 user-init.sh 自動 regen 的（從 USER-{username}.md），團隊新人要編 USER-{username}.md 才持久化 V4 段
- conflict-review.py approve 同 stem 有 .resolved 支線時，target 要傳 `{slug}.resolved`（不是 `{slug}`）
- post-git-pull.sh 的 reindex 12 秒上限，新增 atom 多時可能不夠 — 觀察 .last_pull_audit_ts 是否漏抓
