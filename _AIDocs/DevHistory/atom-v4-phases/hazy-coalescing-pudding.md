# Phase 5 — 三時段衝突偵測 + Pending Review Queue

## Context

V4 Phase 1-4 已建好三層 scope（shared / role / personal）、role-filter JIT、atom_write schema。但 shared 同步寫入仍會靜默覆蓋 — 兩個 user 寫互斥內容到同 trigger，後者直接覆寫前者；git pull 也不會察覺事實衝突。

Phase 5 補上 SPEC §7「三時段衝突偵測」這一防線：
- **Write-time**：`atom_write scope=shared` 寫入前，向量找相似 + LLM 分類 → CONTRADICT/EXTEND-overlap 進 `_pending_review/`
- **Pull-time**：`git pull` 後背景 audit 增量 commit → 衝突進 pending
- **Git-conflict-time**：硬碰硬走 `git mergetool`，Claude 只給建議不動檔（純文件約定，無程式工作）

並提供 `/conflict-review` 給管理職裁決 pending queue（雙向認證），所有合併動作寫 `_merge_history.log` 可追溯。

不在範圍：JIT 注入路徑（Phase 4 已處理，本 Phase 不動）、migration 工具（Phase 6）、SVN hook（SPEC §9 預設第一版只做 git）。

---

## 設計決策

### 1. LLM 呼叫集中於 `memory-conflict-detector.py`
不擴 write-gate.py 的 LLM 邏輯（保持 v2.1 純規則 + 向量 dedup 不變），改在 detector 加 `--mode=write-check`。server.js 在 `toolAtomWrite` shared 路徑上對 detector 多打一次 RPC（已有 execWriteGate pattern 可仿）。

**理由**：write-gate 是「品質/去重」職責；conflict-detector 是「語意衝突」職責。職責分離 → 將來換 LLM 後端只動一處。

### 2. Pending 草稿用「兩種檔型」
| 場景 | 檔名 | 格式 |
|------|------|------|
| EXTEND 補充 | `_pending_review/{slug}.draft.md` | 完整 atom 格式 + `Pending-review-by: management` |
| CONTRADICT | `_pending_review/{slug}.conflict.md` | **報告型** md（非 atom）：標題 + 雙方引文 + similarity + detector model + 等待裁決 |

**理由**：SPEC §7.2 明文「CONTRADICT 不生草稿只列差異」。EXTEND 草稿須 approve 後落地，所以保留 atom 格式好搬。

### 3. EXTEND 純新增 vs 補充 判定
- LLM 回 `EXTEND` + vector top-1 score < 0.85 → 純新增（自動寫入 + log）
- LLM 回 `EXTEND` + vector top-1 score ≥ 0.85 → 補充（pending draft）
- LLM 回 `AGREE` + cosine ≥ 0.95 → 拒絕（dedup duplicate，已有）
- LLM 回 `CONTRADICT` → 強制 pending（contradict report）

### 4. is_management() 雙向認證
新增 `hooks/wg_roles.py`，純讀檔：
1. 讀 `{proj}/.claude/memory/personal/{user}/role.md` → 解析 `Role: ...` + `Management: true`
2. 讀 `{proj}/.claude/memory/shared/_roles.md` → 解析 `## Management 白名單` 區塊清單
3. **兩者皆通過 → True**

### 5. _merge_history.log 格式（TSV append-only）
```
{ISO8601_ts}\t{action}\t{atom_slug}\t{scope}\t{by_user}\t{detail}
```
action ∈ {`auto-merge`, `pending-create`, `approve`, `reject`, `pull-audit-flag`}

### 6. Service-down fallback
- Vector service down → write-time conflict check skip（fallback to write-gate dedup only），audit log 標記
- LLM 失敗/timeout → conservative pending（漏判好過誤判，符合 SPEC §7.3）
- Pull-audit hook 失敗 → 不阻擋 pull，stderr 警告 + 寫 audit log

### 7. `Merge-strategy: git-only` 跳過所有 AI 合併
讀既有 atom 時 metadata 含此標 → write-check 直接 pass-through、pull-audit 跳過該 atom。

---

## 實作步驟

### Step 1 — `hooks/wg_roles.py`（新；~80 行）

純函式 helper，無副作用。介面：
```python
def get_user_roles(user: str, proj_root: Path) -> List[str]
def is_management(user: str, proj_root: Path) -> bool
def parse_role_md(path: Path) -> Dict[str, Any]
def parse_roles_registry(path: Path) -> Dict[str, Any]  # 回 {users: {...}, management: [...]}
```

`is_management(user, proj_root)`：
- `personal/{user}/role.md` 不存在 → False
- 解析 `Management: true` 或 `Role` 字串 split 後含 `management` → personal_ok
- `shared/_roles.md` 不存在 → False（沒白名單就視為團隊未啟管理職）
- `## Management 白名單` 區塊以 `- {user}` bullet 列出，user 命中 → registry_ok
- 兩者皆 True 才 return True

### Step 2 — 擴 `tools/memory-conflict-detector.py`（既有檔，+~150 行）

**新增 `--mode=write-check`**：CLI 參數
```
--mode {full-scan|pull-audit|write-check}
--content "新寫入的 knowledge 文字"
--scope shared
--project-cwd <path>
--threshold 0.85
```
流程：
1. embed content → vector top-3（min_score=0.60，超過則送 LLM）
2. 對每個 hit 跑 `ollama_classify(content, atom_a) → AGREE|EXTEND|CONTRADICT|UNRELATED`
3. **回傳 JSON**（單行）：
```json
{
  "verdict": "ok" | "extend_overlap" | "contradict" | "duplicate",
  "matches": [
    {"atom_name": "...", "layer": "...", "similarity": 0.89, "classification": "EXTEND", "fact_preview": "..."}
  ],
  "detector_model": "gemma4:e4b",
  "skipped": false,
  "skip_reason": null
}
```
verdict 規則：
- 任一 CONTRADICT → `contradict`（return 第一個）
- 任一 AGREE 且 sim ≥ 0.95 → `duplicate`
- 任一 EXTEND 且 sim ≥ 0.85 → `extend_overlap`
- 否則 → `ok`
- vector/LLM 失敗 → `verdict: ok, skipped: true`（write-time fallback）

**新增 `--mode=pull-audit`**：
```
--mode pull-audit
--project-cwd <path>
--since <ts|"last">  # "last" 讀 .last_pull_audit_ts
```
流程：
1. 讀 `{proj}/.claude/memory/shared/.last_pull_audit_ts`（無則用 epoch）
2. `git -C {proj} log --since={ts} --pretty=format:%H -- .claude/memory/shared/` 取 commit list
3. 對每個 commit 跑 `git show {commit} -- .claude/memory/shared/`，抽出新增/修改的 atom 內容
4. 對每個變動跑 `vector_search → ollama_classify`（同 write-check 邏輯）
5. CONTRADICT → 寫 `_pending_review/{slug}.pull-conflict.md`（報告型）
6. 寫 `_merge_history.log` 一行 `pull-audit-flag`
7. 更新 `.last_pull_audit_ts`

**復用既有**：`vector_search()`, `ollama_classify()`, `extract_facts()`, `parse_atom_meta()` 全部留用，不改既有 `scan_conflicts()`（full-scan）。

### Step 3 — 擴 `tools/workflow-guardian-mcp/server.js`（既有檔，+~120 行）

**新增 helper `execConflictDetector(content, scope, projectCwd)`**（仿 `execWriteGate` L800-821）：呼 Python detector，timeout 30s（LLM 較慢），fallback 回 `{verdict: "ok", skipped: true}`。

**改 `toolAtomWrite` L921-**：
在 L989 既有 write-gate check 之後、L1001 buildAtomContent 之前，插入：

```javascript
// SPEC §7.1 write-time conflict detection (shared scope only)
let conflictReport = null;
if (scope === "shared" && !args.skip_conflict_check) {
  conflictReport = await execConflictDetector(knowledge.join("\n"), scope, project_cwd);
  if (conflictReport.verdict === "contradict") {
    // Write conflict report (NOT an atom) to _pending_review/
    const reportPath = path.join(baseDir, "shared", "_pending_review", slug + ".conflict.md");
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(reportPath, buildConflictReport({...}), "utf-8");
    appendMergeHistory(baseDir, "pending-create", slug, scopeLabel, author, "contradict");
    return sendToolResult(id,
      `BLOCKED: contradict with ${conflictReport.matches[0].atom_name}. Report: ${reportPath}\n` +
      `Awaiting management review (/conflict-review).`,
      false  // not isError — pending is normal flow
    );
  }
  if (conflictReport.verdict === "extend_overlap") {
    // Reroute to _pending_review as draft atom
    memDir = path.join(baseDir, "shared", "_pending_review");
    fs.mkdirSync(memDir, { recursive: true });
    pendingReviewBy = "management";
    // ... reuse buildAtomContent, write to {slug}.draft.md
  }
  // verdict: ok or duplicate → write-gate already handled
}
```

**新增 helpers**：
- `buildConflictReport({ slug, newContent, match, similarity, model })` — 渲染報告型 md
- `appendMergeHistory(baseDir, action, atom, scope, by, detail)` — append `_merge_history.log` 一行 TSV
- `loadAtomMergeStrategy(filePath)` — 讀既有 atom 的 `Merge-strategy:` line（用於 git-only skip）

**append mode 也要過 detector**（既有 atom + 新 knowledge）：簡化 — 同 atom 內 append 不過 detector（用戶明確要加到此 atom，且既有檔 dedup 已被略過）。**只 create mode 過**。

### Step 4 — `hooks/post-git-pull.sh`（新；~30 行）

bash template，使用者複製到 `{proj}/.git/hooks/post-merge` 自行授權執行：

```bash
#!/usr/bin/env bash
# Atom V4 — post-merge audit. Copy to {proj}/.git/hooks/post-merge.
set -e
PROJ_ROOT="$(git rev-parse --show-toplevel)"
DETECTOR="$HOME/.claude/tools/memory-conflict-detector.py"
[ -f "$DETECTOR" ] || exit 0
[ -d "$PROJ_ROOT/.claude/memory/shared" ] || exit 0
python "$DETECTOR" --mode=pull-audit --project-cwd="$PROJ_ROOT" --since=last \
  >> "$PROJ_ROOT/.claude/memory/_merge_history.log" 2>&1 || \
  echo "[atom-v4] pull-audit failed (non-blocking)" >&2
```

**不**自動安裝（使用者偏好 SPEC §9：「git/SVN 自動 add：否」→ 不應主動裝 hook）。/init-roles 提示時複製。

### Step 5 — `skills/conflict-review/SKILL.md`（新）

Skill 自然語言指令，搭配 Python 後端 helper（建議放 `tools/conflict-review.py`，~150 行）：

`SKILL.md` 內容（本身是 prompt）：
- description: `/conflict-review — 列管理職待裁決的衝突 atom 並引導 approve/reject`
- 使用流程：
  1. 取 cwd → find_project_root → 呼 `python tools/conflict-review.py --list --project-cwd=...`
  2. 收到 JSON list（empty → 告知無 pending）
  3. 顯示給 user：每筆含 type (draft|conflict)、atom_name、author、similarity、preview
  4. user 選一筆 + 動作（approve / reject / edit）
  5. 呼 `python tools/conflict-review.py --action=approve --target=... --by=$USER`
  6. 後端驗 `is_management(user, proj_root)` → 不通過 → 報錯
  7. approve：搬 draft 到 shared/、寫 Decided-by + merge_history、觸發 vector reindex（POST 3849/reindex）
  8. reject：刪 pending 檔 + 寫 merge_history reject

`tools/conflict-review.py` 介面：
```
--list --project-cwd=PATH                              # 列 pending
--action=approve --target=NAME --by=USER --project-cwd=PATH
--action=reject  --target=NAME --by=USER --project-cwd=PATH --reason=TEXT
```
- import wg_roles.is_management
- 不通過認證 → exit 1，回 JSON `{error: "not authorized as management"}`
- approve `.draft.md` → 移到 `shared/{slug}.md`，移除 `Pending-review-by:` 行，加 `Decided-by: {user}` + 更新 `Last-used`
- approve `.conflict.md` → 不能直接 approve（contradict 沒草稿），只允許 reject 或 user 手動編輯後 approve；conflict.md 旁可放 user 編好的 `{slug}.resolved.md`，approve 此檔
- 觸發 reindex：`urllib POST http://127.0.0.1:3849/reindex`

### Step 6 — 文件 + commit
- 更新 `_AIDocs/Architecture.md`：新增「§4.X 衝突偵測流程」段
- 更新 `_AIDocs/_CHANGELOG.md`：Phase 5 entry
- commit msg: `feat(atom-v4): Phase 5 — three-timing conflict detection with management review`

---

## 驗證計畫

依任務 brief 6 項，每項對應一個手測：

1. **CONTRADICT 攔截**：cd 到測試 project，先用 `mcp__workflow-guardian__atom_write` 寫 atom A（scope=shared, trigger=test-conflict, knowledge="X 必須用 A 框架"），再 atom_write atom B（同 trigger, knowledge="X 必須用 B 框架"）→ 第二次回 BLOCKED + `_pending_review/{slug}.conflict.md` 存在
2. **純新增自動合**：append 不重疊 bullet 到 atom A → 直接寫入 + `_merge_history.log` 多一行 `auto-merge`
3. **EXTEND 補充進 pending**：寫 atom C（同 trigger=test-conflict, knowledge="X 框架的 cache 行為注意 ..."）→ vector 命中 ≥0.85 + LLM=EXTEND → `_pending_review/{slug}.draft.md` 存在
4. **pull-audit**：手動 `git commit -m a "v1"` + `git commit --amend -m "v2"` 模擬衝突歷史；複製 `post-git-pull.sh` 到 `.git/hooks/post-merge` 後 `git pull origin main`（或人造 `git merge`）→ `_merge_history.log` 出現 `pull-audit-flag` 行
5. **/conflict-review approve**：以管理職身份（personal/holylight/role.md 含 management + shared/_roles.md 列名）跑 `/conflict-review` → 列出 pending → 選 approve → 檔案搬到 shared/、Decided-by 寫入、merge_history 多一行 approve、vector 索引到新檔
6. **非管理職 reject**：另開 user（無 management 標記）→ approve 應回 `not authorized as management`

附加驗證（不在 brief 但重要）：
- vector service 停掉跑 write-check → fallback 回 verdict=ok skipped=true，不阻 atom_write
- atom 標 `Merge-strategy: git-only` → write-check 跳過 + pull-audit 跳過該 atom
- `_pending_review/` 不在 JIT 注入結果（驗證 Phase 4 已 exclude；若沒 → 回報但不修，超 Phase 5 範圍）

---

## 關聯檔案清單

**會改**：
- [tools/workflow-guardian-mcp/server.js](tools/workflow-guardian-mcp/server.js) +~120 行
- [tools/memory-conflict-detector.py](tools/memory-conflict-detector.py) +~150 行
- [_AIDocs/Architecture.md](_AIDocs/Architecture.md) 加段
- [_AIDocs/_CHANGELOG.md](_AIDocs/_CHANGELOG.md) 加 entry

**新增**：
- [hooks/wg_roles.py](hooks/wg_roles.py) ~80 行
- [hooks/post-git-pull.sh](hooks/post-git-pull.sh) ~30 行
- [skills/conflict-review/SKILL.md](skills/conflict-review/SKILL.md) ~80 行
- [tools/conflict-review.py](tools/conflict-review.py) ~150 行

**讀但不改**：
- [tools/memory-write-gate.py](tools/memory-write-gate.py)（職責不擴）
- [hooks/wg_paths.py](hooks/wg_paths.py)（既有 V4 函式直接用）
- [tools/memory-vector-service/searcher.py](tools/memory-vector-service/searcher.py)（既有 search 直接用）

合計 ~610 行新增 / 4 新檔 / 4 改檔。

---

## Phase 6 接續 prompt（完成後給使用者）

```
原子記憶 V4 — Phase 6：migration 工具 + /init-roles + end-to-end 多帳號驗收

Phase 1-5 已完成（SPEC + 路徑 + atom_write schema + role-filter JIT + 三時段衝突偵測 + /conflict-review）。
Phase 6 收尾：
1. tools/migrate-v3-to-v4.py — 掃既有專案 atom，補 Scope/Author/Audience/Created-at metadata（不搬檔，符合 SPEC §10）
2. skills/init-roles/SKILL.md — /init-roles 引導建立 personal/role.md + shared/_roles.md + .gitignore + post-merge hook
3. 完整 e2e：起 2 個測試 project + 3 個假 user（programmer/art/management），跑全套 atom_write/JIT/conflict-review 流程
4. 更新 USER.md / IDENTITY.md V4 段、Architecture.md 完整化、_AIDocs/_INDEX.md 收錄

開工前讀 _AIDocs/SPEC_ATOM_V4.md §10 + ~/.claude/plans/gentle-puzzling-kettle.md Phase 6 段落。
```
