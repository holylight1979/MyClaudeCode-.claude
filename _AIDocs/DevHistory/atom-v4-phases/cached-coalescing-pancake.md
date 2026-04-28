# Phase 4 — Role-filtered JIT Injection + Vector Layer 擴充

## Context

V4 Phase 1-3 已凍結 SPEC、建好路徑/角色基礎、擴充 atom_write schema。Phase 4 把「讀取/注入端」對齊：SessionStart 與 UserPromptSubmit 必須讀懂目前使用者的角色，依 SPEC §8.1 規則注入「shared + 我的 role + 我的 personal + global」，**不**讓使用者看到別人 personal 或別組 role 的 atom；向量服務也要在 metadata 端 filter，達到同樣可見性語意。

不在範圍：Phase 5（衝突偵測 / pending review queue 的實際裁決流程）、Phase 6（migration 工具）。本 Phase 對 atom_write 寫入路徑零修改。

---

## 設計總覽

### Layer 命名（Vector DB）

V3 用 `global` / `project:{slug}`。V4 改用更細的 layer label，向後相容：

| Layer label | 含意 | 對映目錄 |
|---|---|---|
| `global` | 全域 atoms | `~/.claude/memory/` |
| `shared:{slug}` | 專案 shared | `{proj}/.claude/memory/shared/` 與專案根的「無 scope」舊 atoms |
| `role:{slug}:{r}` | 專案 role-shared | `{proj}/.claude/memory/roles/{r}/` |
| `personal:{slug}:{user}` | 專案個人 | `{proj}/.claude/memory/personal/{user}/` |

舊的 `project:{slug}` label 整層**淘汰**：indexer 改為直接掛在新 label 下；專案根（mem_dir 直下、未進 shared/roles/personal）的 legacy atom 視為 `shared:{slug}`（對應 SPEC §10）。reindex 時舊 chunk 因 `mode="overwrite"` 自然清掉。

### Filter 規則（user U、roles R）

- 一般 user：`layer = 'global' OR layer LIKE 'shared:%' OR layer LIKE 'role:%:r1' OR ... OR layer LIKE 'personal:%:U'`
- 管理職：不加 filter（`layer=all`），額外取得 `_pending_review` 列表
- vector service 端組 SQL；UPS hook 只負責傳 `user` + `roles` 兩個 query 參數

---

## 變更檔案清單（依執行順序）

### 1. `hooks/wg_paths.py` — discover_memory_layers 重寫

當前 `discover_memory_layers(layer_filter, user, role)` 仍會 emit 舊 `project:{slug}` label，且不會自動 enumerate 所有 sub-layer（indexer 用）。改為：

- 新增 `discover_v4_sublayers(slug, mem_dir) -> List[(label, path)]`：列出 `shared:{slug}` / `role:{slug}:{r}` / `personal:{slug}:{u}` 所有實際存在的子目錄；若 mem_dir 直下還有 legacy `.md`，append 一筆 `("shared:{slug}", mem_dir, kind="flat-legacy")`（kind 透過第三元素標示，indexer 用來決定要不要遞迴）。
- 改寫 `discover_memory_layers`：
  - 預設行為（無 user/role/filter）= **enumerate 全部 sub-layer**（給 indexer 用）；不再 emit `project:{slug}`
  - 帶 `user="alice", role="art,programmer"` → 只回 `global` + `shared:{slug}` + `role:{slug}:art` + `role:{slug}:programmer` + `personal:{slug}:alice`
  - `layer_filter`（若有）按 prefix 過濾

### 2. `tools/memory-vector-service/indexer.py`

- `discover_layers()` 改用新版 `discover_memory_layers()`（已自動切 V4 sub-layer）
- `discover_atoms()` 處理 `flat-legacy` kind：只掃 mem_dir 直下 `.md`、跳 `shared/roles/personal/_*` 子目錄；shared/role/personal 子層則照舊遞迴
- `parse_and_chunk()` 解析 metadata 時擴抓 `Scope` / `Audience` / `Author` 三欄；隨 chunk 寫入：
  ```python
  "scope": ..., "audience": ..., "author": ...
  ```
- `build_index()` 寫 LanceDB record 加上對應欄位；舊 atom 缺 metadata → 預設 `scope="shared"` / `audience=""` / `author="unknown"`（SPEC §10）

### 3. `tools/memory-vector-service/searcher.py`

- 新增 helper `_build_v4_layer_clause(user, roles)` → 回傳 SQL WHERE 字串（含 sanitize：只允許 `[\w\-]+`，不合就丟）
- `search_vectors(query_vec, top_k, layer_filter=None, layer_clause=None)` 加新參數 `layer_clause`：若有就 `q.where(layer_clause)`，蓋過 `layer_filter`
- `search` / `ranked_search` / `ranked_search_sections` 三個入口加 `user`/`roles` 參數，傳給 `search_vectors` 時優先用 clause；保留 `layer_filter` 給管理職顯式查單一 layer

### 4. `tools/memory-vector-service/service.py`

- `_handle_search` / `_handle_search_ranked` / `_handle_search_ranked_sections` 解析 query 字串：
  - `user`（單值）
  - `roles`（逗號分隔 → list）
  - 三個都是可選；皆缺 → 走舊行為（不 filter）
- 將 `user, roles` 傳給 searcher

### 5. `hooks/wg_intent.py` — `_semantic_search` 加 user/roles

- signature 改為 `_semantic_search(prompt, config, intent, user=None, roles=None)`
- 把 `user` / `roles`（list, 用 `,`.join）一併塞進 urlencode 參數
- 退回 `/search/ranked` fallback 路徑同步處理

### 6. `hooks/workflow-guardian.py` — SessionStart + UPS

#### 6a. SessionStart（`handle_session_start`，~163-349）

新流程（在 `state["atom_index"]` 建立後、context lines 拼裝前插入）：

```python
from wg_roles import (
    get_current_user, load_user_role, is_management, bootstrap_personal_dir,
)

user = get_current_user()
bootstrap_personal_dir(cwd, user)        # 冪等：建 personal/{user}/ + .gitignore
role_info = load_user_role(cwd, user)    # {"roles": [...], "management": bool}
roles = role_info["roles"] or ["programmer"]   # SPEC: role.md 樣板預設 programmer
mgmt = is_management(cwd, user)          # 雙向認證

state["user_identity"] = {
    "user": user,
    "roles": roles,
    "management": mgmt,
}
```

- 把 user/role 寫進 `[Workflow Guardian]` 起始那行下方一條：`[Role] user={user} roles={','.join(roles)} mgmt={mgmt}`
- 若 `mgmt`：呼叫 `list((proj_mem/'shared'/'_pending_review').glob('*.md'))`，>0 時加一行 `[Pending Review] N 件待裁決`（不展開內容）
- `parse_memory_index(project_mem_dir)`：保留現行（讀 MEMORY.md），但**額外**走 `discover_memory_layers(user=user, role=','.join(roles))` 對應 sub-layer 目錄，把每個目錄下的 `.md`（解 metadata 取 trigger）合進 `state["atom_index"]["project"]`，去重以 atom_name 為 key。同時記錄每筆的 layer label，供 UPS 注入時 filter 用。
- 若該專案有 V4 layout（`shared/` 或 `roles/` 或 `personal/` 任一存在）→ 呼叫新函式 `regenerate_role_filtered_memory_index(project_mem_dir, user, roles, mgmt)`：
  - 寫到 `{proj}/.claude/memory/MEMORY.md`，加 `<!-- AUTO-GENERATED: V4 role filter -->` 標頭
  - 若檔案首行不是該標頭、且檔案已存在 → **跳過**（保護人手編輯的 V3 MEMORY.md）
  - 內容：表格列出 layer / atom / trigger，依角色 filter 過

#### 6b. UPS atom 注入（~565-700）

- 從 `state["user_identity"]` 讀 user/roles
- `_semantic_search(prompt, config, intent=intent, user=user, roles=roles)` 改用新 signature
- trigger 比對端：`state["atom_index"]["project"]` 已是 filter 過的清單，沿用既有比對邏輯，不需額外動

### 7. `memory/_ATOM_INDEX.md` — 表頭加 Scope 欄

```markdown
| Atom | Path | Trigger | Scope |
```

舊行：補 `| global` 末欄。machine-only，無 backward compat 顧慮。
（注意：parser 在 `wg_atoms.py` `_parse_atom_index_file` / `TABLE_ROW_RE`，需確認新欄不會破解析 — 預期 ripley 是 `r"\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|"` 取前三欄；多一欄通常不影響，但實作前要 read 該 regex 確認。若 regex 限定欄位數則同步放寬 — 列為實作時必查項。）

### 8. 文件

- `_AIDocs/Architecture.md` — JIT 注入流程段補一節「V4 Role Filter」
- `_AIDocs/_CHANGELOG.md` — 新 entry：`[Phase 4] role-filtered JIT injection`

---

## 不做的事（明確界線）

- **不**動 atom_write 寫入路徑（Phase 3 已驗證）
- **不**做衝突偵測（Phase 5）
- **不** migrate 既有 atoms（Phase 6）
- **不**做管理職的「跨 role 索引列表」介面（SPEC §8.2 第二項）— Phase 4 只實作「不 filter」與 pending_review 列表計數；跨 role 索引介面延到 Phase 5 跟 conflict-review 一起做
- 不讀 audience metadata 做進階分流注入 — Phase 4 仍以 layer 為主軸，audience 留給 Phase 5 衝突偵測

---

## 驗證劇本

1. **環境準備**：在 `c:/tmp/v4-test/`（或現有有 `.git` 的測試專案）`mkdir .claude/memory/{shared,roles/art,roles/programmer,personal}`
2. **Bob 是程式**：
   - `set CLAUDE_USER=bob`，新開 session → 應自動建 `personal/bob/role.md`、append `.gitignore`、context 出現 `[Role] user=bob roles=programmer mgmt=False`
   - 寫 `roles/art/photoshop-naming.md`（含 Scope: role:art / Audience: art / Trigger: photoshop, 命名）
   - 重新觸發 indexer：`curl -X POST http://127.0.0.1:3849/index`
   - prompt 包含「photoshop 命名」→ atom 不應被注入（Bob 看不到 art role）
3. **切 Alice 是美術**：
   - 改 `personal/bob/role.md` 仿一份給 alice、`set CLAUDE_USER=alice`、編輯為 `Role: art`
   - 同 prompt → 應注入 photoshop 那筆
4. **管理職**：
   - `_roles.md` 寫 `## Management 白名單\n- holylight1979`
   - `personal/holylight1979/role.md` 寫 `Role: programmer, management`
   - 在 `shared/_pending_review/` 放一個假 `.md`
   - 啟 session → context 應出現 `[Pending Review] 1 件待裁決`
5. **vector 直查**：`curl "http://127.0.0.1:3849/search/ranked?q=photoshop&user=bob&roles=programmer"` → 不返回 art atom；改 `roles=art` → 返回
6. **MEMORY.md 動態生成**：alice/bob 的 `MEMORY.md` 內容應只列各自能看到的 atoms

---

## Critical Files

- `hooks/wg_paths.py` — discover_memory_layers 重寫
- `hooks/workflow-guardian.py` — SessionStart 注入點與 UPS atom_index 載入
- `hooks/wg_intent.py:308` — `_semantic_search`
- `hooks/wg_atoms.py` — `TABLE_ROW_RE` / `_parse_atom_index_file` 確認 Scope 欄不破解析
- `tools/memory-vector-service/{indexer,searcher,service}.py`
- `memory/_ATOM_INDEX.md`
- `_AIDocs/Architecture.md` + `_CHANGELOG.md`

## 已就緒 utilities（直接 reuse）

- `wg_roles.get_current_user / load_user_role / is_management / bootstrap_personal_dir`
- `wg_paths.find_project_root / discover_all_project_memory_dirs`
- `wg_intent._semantic_search`（擴 signature）
- `wg_atoms.parse_memory_index`（保留；V4 額外資料用新流程合併）

---

## 開實作前要再 read 的小項

1. `wg_atoms.py` — 確認 `TABLE_ROW_RE` 可接受 4 欄表格（必要時放寬）
2. `wg_atoms.parse_memory_index` 細節 — 確定 atom_name → path 對映方式，方便合併新 layer
3. UPS 565-700 完整邏輯 — 確認 `state["atom_index"]["project"]` 在 trigger 比對處的存取點，不會踩到隱藏假設

完成 → 上 git → 給 Phase 5 prompt（三時段衝突偵測 + Pending Review Queue 裁決介面）。
