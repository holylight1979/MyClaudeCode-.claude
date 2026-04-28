# Atom V4 Phase 3 — atom_write schema 擴充 + 寫入路徑切換

## Context

V4 Phase 1（SPEC freeze, f90bc57）+ Phase 2（路徑/角色基礎建設, c12464c）已完成。Phase 2 在 `wg_paths.get_scope_dir()` 與 `wg_roles.*` 提供了寫入目標與角色查詢能力，但 MCP `atom_write` 仍走 V3 schema（scope enum 只有 `global|project`），所有 atom 都落到 `{proj}/.claude/memory/` 根目錄，無法分流到 `shared/ roles/{r}/ personal/{user}/`。

Phase 3 目標：擴 `atom_write` schema、改寫入路徑、注入新 metadata 欄位、實作 SPEC 7.4 敏感類別自動 pending。**範圍嚴格限定 atom_write 寫入路徑**，不動 JIT 注入 filter（Phase 4）、衝突偵測（Phase 5）。

---

## Files to Modify（共 3 檔）

| 檔案 | 變更類別 |
|---|---|
| `tools/workflow-guardian-mcp/server.js` | schema、resolveMemDir、buildAtomContent、toolAtomWrite handler、新增小工具 |
| `_AIDocs/Architecture.md` | atom_write 行為段落更新 |
| `_AIDocs/_CHANGELOG.md` | Phase 3 條目 |

> `wg_paths.py` / `wg_roles.py` 已在 Phase 2 就緒，**不動**。
> `toolAtomPromote` 共用 `resolveMemDir`，自動受益於擴充，**不需另改**。

---

## 設計決策

### D1. scope enum 策略
- 新 enum：`["global", "shared", "role", "personal", "project"]`
- `project`（legacy）→ server 端透明轉 `shared` + stderr 一行 deprecation hint，**不報錯**
- schema 中 `scope` 由 `required` 移除，預設 `shared`（保證舊 caller 不傳 scope 也可寫）

### D2. 新 schema 欄位
| 欄位 | 型別 | 必填條件 | 用途 |
|---|---|---|---|
| `role` | string | scope=role 時必填 | role 子層名（art/programmer/...） |
| `user` | string | scope=personal 時，缺則 fallback 當前使用者 | personal 子層 owner |
| `audience` | string[] | optional | metadata Audience（多標 role） |
| `pending_review_by` | string | optional | metadata Pending-review-by |
| `merge_strategy` | enum `[ai-assist, git-only]` | optional | metadata Merge-strategy |

`author` **不**開放給 caller 傳，server 端自動帶（防 LLM 亂填）。

### D3. Author 自動帶入（不 spawn python）
SPEC 範例顯示 `Author: holylight1979`。等價於 `wg_roles.get_current_user()` 邏輯，server.js 直接：
```js
process.env.CLAUDE_USER || require("os").userInfo().username
```
與 `wg_roles.get_current_user()` 行為一致；省一次 python spawn。

### D4. resolveMemDir 擴充策略
保留現有 `resolveMemDir(scope, projectCwd)` 簽名，內部分支處理新 scope。為相容 atom_promote，舊 `scope=project` 路徑（直接落根目錄）保留為「legacy 讀取」用，但 atom_write 內主動將 `scope=project` 轉為 `shared`。

新行為（atom_write 視角）：
- `global` → `~/.claude/memory/`（不變）
- `shared` / legacy `project` → `{proj}/.claude/memory/shared/`
- `role` → `{proj}/.claude/memory/roles/{role}/`（缺 role → 報錯）
- `personal` → `{proj}/.claude/memory/personal/{user}/`（user 缺則 fallback `os.userInfo().username`）

實作沿用 `wg_paths.get_scope_dir()` 的 marker 判定邏輯（`.claude/memory/MEMORY.md` || `_AIDocs/` || `.git` || `.svn`），但 server.js 端用既有 JS 邏輯實作（不 spawn python），保持薄框架。

### D5. metadata 欄位順序與輸出
依 SPEC §4 順序：
```
- Scope: ...
- Audience: ...        # 有才寫
- Author: ...
- Confidence: ...
- Trigger: ...
- Last-used: ...
- Confirmations: 0
- Pending-review-by: ... # 有才寫（含敏感類別自動觸發）
- Merge-strategy: ...    # 非預設才寫
- Created-at: YYYY-MM-DD
- Related: ...           # 有才寫
```
`Decided-by` 不在 atom_write 寫入時產生（屬 conflict review skill 範疇，Phase 5）。

對 `mode=append`：metadata 區段已存在，**只更新 Last-used**，不新增 Author/Created-at（避免覆蓋初寫者身份）。`mode=replace`：採用初寫者 metadata 模式（重建全部欄位，但保留 Confirmations，**不**保留原 Author — 因為 replace 等價於重新寫入；如使用者要保留 Author 應走 append）。

### D6. 敏感類別自動 Pending（SPEC 7.4 第一版）
觸發條件（`scope=shared` 寫入時）：
- `audience` 陣列含 `architecture` 或 `decision`（大小寫不敏感）

行為：
1. metadata 自動補 `Pending-review-by: management`（若 caller 未傳）
2. 寫入路徑改為 `{proj}/.claude/memory/shared/_pending_review/`
3. `relPath` 於 MEMORY.md 索引也改為 `memory/shared/_pending_review/{slug}.md`
4. 仍走 write-gate（敏感不代表跳過品質檢查）

`scope!=shared` 即使 audience 含敏感字也不觸發（個人或角色內筆記不需管理職裁決）。

### D7. 冪等保證
- `mode=create` 已有「檔案存在則拒絕」邏輯，新路徑下同樣有效
- `fs.mkdirSync(memDir, { recursive: true })` 既有，不重複建目錄
- buildAtomContent 確定性輸出 → 同輸入 → 同 metadata 行
- MEMORY.md 索引 `appendToIndex` 已有 existing-row 偵測 + replace 邏輯

### D8. relPath 計算
原本 `relPath = "memory/" + slug + ".md"` 假設根目錄。新版需依實際寫入子層：
- shared → `memory/shared/{slug}.md`
- role → `memory/roles/{role}/{slug}.md`
- personal → `memory/personal/{user}/{slug}.md`
- shared+pending → `memory/shared/_pending_review/{slug}.md`
- global → `memory/{slug}.md`（不變）

### D9. 驗證錯誤訊息
- `scope=role` 缺 `role` → `"scope=role requires 'role' parameter (e.g., 'art', 'programmer')"`
- `scope=personal` 缺 `user` → 自動 fallback 到當前 user（log 一行），**不報錯**（符合 SPEC 預設使用者）
- 專案類 scope 但 cwd 不在 marker → `"No project root found for scope=${scope} (need .git/.svn/_AIDocs/.claude/memory/MEMORY.md marker)"`

---

## 實作步驟

### S1. server.js — schema（line 382-423）
- `scope.enum` → `["global", "shared", "role", "personal", "project"]`，描述加 deprecation note for `project`
- `required` 陣列移除 `scope`（預設 shared）
- 新增 `role` / `user` / `audience` / `pending_review_by` / `merge_strategy` properties

### S2. server.js — buildAtomContent（line 607）
依 D5 順序輸出新欄位；接受 extra params（audience, author, pending_review_by, merge_strategy, created_at）。對 optional 欄位用 if-guard，不空標。

### S3. server.js — resolveMemDir（line 654）
擴出新分支：
```js
function resolveMemDir(scope, projectCwd, opts = {}) {
  // global / project(legacy) / shared / role / personal
}
```
新增 helper：
- `findProjectRoot(cwd)` — JS 版的 marker 偵測（4 層上溯）
- `isSensitiveAudience(audience)` — 含 architecture/decision check
- `getCurrentUser()` — env + os.userInfo()

### S4. server.js — toolAtomWrite handler（line 798）
流程：
1. 解析 args：取 scope（預設 shared）、role、user（缺則 currentUser）、audience、pending_review_by、merge_strategy
2. 若 scope=project → log deprecation + 改 scope=shared
3. 驗證：scope=role 必須有 role
4. resolveMemDir 取目錄，無則錯誤回報
5. 敏感類別偵測（D6）→ 改寫 memDir 為 `_pending_review/`，補 pending_review_by
6. slug、filePath、relPath 計算（依 D8）
7. 自動帶 author = getCurrentUser()、created_at = today
8. 走原有 mode=create / append / replace 路徑，buildAtomContent 帶新 params
9. mode=append：只更新 Last-used，不動 Author/Created-at（讀既有檔不覆蓋）
10. mode=replace：重建 metadata（保留 Confirmations）

### S5. _AIDocs/Architecture.md
找到 atom_write 行為段落（grep 「atom_write」），加一段「V4 scope 路由」說明 + 連結 SPEC §4/§7.4。

### S6. _AIDocs/_CHANGELOG.md
頂部加：
```
## 2026-04-15 — atom-v4 Phase 3
- atom_write MCP schema 擴 V4 三層 scope (shared/role/personal)
- 新 metadata: Author / Audience / Created-at / Pending-review-by / Merge-strategy
- 敏感類別 (architecture/decision) 寫 shared 自動進 _pending_review/
- legacy scope=project 透明遷移到 shared，舊 caller 相容
```

---

## Verification（端到端，手動觸發 MCP）

於 `c:\tmp\docs-progg\` 測試（已有 `.git` + `.claude/memory/`）：

1. **shared 預設**：`atom_write(scope="shared", title="Test1", confidence="[臨]", triggers=["t"], knowledge=["- [臨] x"], mode="create", project_cwd="c:/tmp/docs-progg")` → 確認落 `shared/test1.md`，metadata 含 `Scope: shared` / `Author: holylight` / `Created-at: 2026-04-15`
2. **role**：`scope="role", role="art", title="Test2"` → 落 `roles/art/test2.md`，`Scope: role:art`
3. **personal**：`scope="personal", title="Test3"`（user 省略）→ 落 `personal/holylight/test3.md`
4. **敏感觸發**：`scope="shared", audience=["architecture"], title="Test4"` → 落 `shared/_pending_review/test4.md`，metadata 含 `Pending-review-by: management`
5. **legacy**：`scope="project", project_cwd="..."` → 落 `shared/`，server stderr 出現 deprecation 一行
6. **舊 caller**（不傳 scope）→ 落 `shared/`，不報錯
7. **缺 role**：`scope="role"` 無 role → 錯誤回 `"scope=role requires 'role' parameter"`
8. **無 marker 專案**：`scope="shared"` 但 cwd 不在 marker → 錯誤回 marker 提示
9. **冪等**：步驟 1 再跑一次 → 拒絕 `Atom already exists`；改 mode=append → Last-used 更新但 Author 不變

驗收後：
- 更新 `_AIDocs/Architecture.md` + `_AIDocs/_CHANGELOG.md`
- commit msg：`feat(atom-v4): Phase 3 — atom_write schema and routing`
- 上 GIT
- 給 Phase 4 接續 prompt（JIT 注入 filter + MEMORY.md 角色視圖）

---

## Critical Files
- `tools/workflow-guardian-mcp/server.js`（lines 382-423 schema, 607-631 buildAtomContent, 654-667 resolveMemDir, 798-952 toolAtomWrite）
- `hooks/wg_paths.py`（read-only 參考 `get_scope_dir` 邏輯）
- `hooks/wg_roles.py`（read-only 參考 `get_current_user` 邏輯）
- `_AIDocs/SPEC_ATOM_V4.md` §4 / §7.4 / §10
