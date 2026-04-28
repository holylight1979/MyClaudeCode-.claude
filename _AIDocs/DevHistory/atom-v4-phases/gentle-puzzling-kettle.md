# 原子記憶 V4：多職務團隊共享

## Context

現況：原子記憶系統只有 `global / project` 二層 scope，所有專案 atom 都假設「單一使用者寫、單一使用者讀」。當未來把這套系統推廣到 Unity 團隊（美術 / 程式 / 企劃，未來擴 PM / QA / 管理職），會出現三類問題：

1. **個人偏好污染團隊知識** — 「我習慣用 A 框架」混入 shared 後變成「團隊規範用 A 框架」
2. **跨職務雜訊** — 美術不需要看程式架構決議，反之亦然，但目前都會被 JIT 一起注入
3. **衝突無解** — 多人同步寫 shared 時，事實衝突（A 說用 X、B 說用 Y）會被任一邊覆蓋掉

升級目標：擴成 **personal / project-shared / role-shared** 三層，atoms 跟 git/svn 走入版控，按角色 filter 注入，事實衝突強制管理職裁決。期望結果：團隊任何角色加入專案 → 自動拿到「該角色該看的知識」+ 個人偏好不外洩 + 衝突可追溯可仲裁。

## 設計總覽

### 新目錄結構（per project）
```
{project_root}/.claude/memory/
├── _ATOM_INDEX.md              # 機器讀，新增 Scope 欄
├── MEMORY.md                   # 人讀，動態依角色顯示
├── _roles.md                   # 管理職白名單（shared，入版控）
├── shared/                     # project-shared
│   ├── {atom}.md
│   └── _pending_review/        # 待管理職裁決的衝突草稿
├── roles/                      # role-shared
│   ├── art/  programmer/  planner/  pm/  qa/  management/
├── personal/                   # personal-in-project（.gitignore）
│   └── {user}/
│       ├── role.md             # 角色自我宣告
│       └── {atom}.md
└── _merge_history.log          # append-only 稽核
```

### 新 metadata（atom markdown list 擴充）
```markdown
- Scope: shared | role:{role} | personal:{user}
- Audience: programmer, art          # 可選，多標 role
- Author: {os.getlogin()}
- Pending-review-by: management      # 可選
- Decided-by: {user}                 # 可選
- Merge-strategy: ai-assist | git-only   # 預設 ai-assist
- Created-at: YYYY-MM-DD
```

### 三層 scope 對映
| 舊 | 新 | 位置 |
|---|---|---|
| `global` | `global`（不變） | `~/.claude/memory/` |
| `project` | `shared`（自動遷移） | `{proj}/.claude/memory/shared/` |

### 預設決策（已為使用者拍板，可在 review 時推翻）
| 議題 | 預設 | 理由 |
|---|---|---|
| git/SVN 自動 add | **否** | 保守，避免靜默改動版控狀態 |
| Vector reindex 時機 | upgrade 時自動跑 | 對使用者透明 |
| 衝突 LLM | 沿用 `memory-conflict-detector.py` 既有配置（gemma4:e4b） | 不增基礎設施 |
| 敏感類別（強制 management review） | 第一版：`architecture`, `decision` | 後續可擴 |
| Claude 不確定 personal/shared 時 | **阻塞式即時詢問** | 確定優於延遲；可後續加 quiet mode |
| 角色變動（轉職） | 手動搬目錄 + 改 role.md | 罕見，不值得自動化 |
| SVN 支援 | 第一版只做 git；SVN hook 預留接口 | 使用者目前 git 為主 |

---

## Phase 拆分（6 phases，獨立可驗證可 commit）

### Phase 1：規格定稿（純文件）
**目標**：本計畫落成 SPEC，凍結 schema 與目錄結構。

**檔案**：
- 新增 [_AIDocs/SPEC_ATOM_V4.md](_AIDocs/SPEC_ATOM_V4.md) — 設計總覽 + 範例 atom（依 rules/core.md 第 3 條，長期參考知識應放 `_AIDocs/`）
- 更新 [_AIDocs/_INDEX.md](_AIDocs/_INDEX.md) — 登記 SPEC 為第 11 號文件
- 更新 [_AIDocs/_CHANGELOG.md](_AIDocs/_CHANGELOG.md) — 加 V4 SPEC freeze 條目
- README.md / memory/MEMORY.md 更新延後到實作完成的 Phase 6（避免文件先說、實作未落地）

**驗證**：使用者逐條確認 scope / metadata / 目錄結構

**commit**：`docs(atom-v4): freeze multi-role shared memory spec`

---

### Phase 2：路徑與角色基礎建設
**目標**：實作角色宣告、路徑解析、.gitignore 自動寫入。

**檔案**：
- [hooks/wg_paths.py:76](hooks/wg_paths.py#L76) — 新增 `get_scope_dir(scope, cwd, user, role)`
- [hooks/wg_paths.py:290](hooks/wg_paths.py#L290) — `discover_memory_layers` 支援 `role_filter`，回傳 `[("global",p), ("shared",p), ("role:art",p), ("personal:{user}",p), ...]`
- 新增 [hooks/wg_roles.py](hooks/wg_roles.py) — `get_user_role()` / `is_management(user)` / `bootstrap_personal_dir(cwd)`

**關鍵設計**：
- `get_user_role()`: `os.environ.get("CLAUDE_USER") or os.getlogin()`，支援多帳號 / scheduled task fallback
- 雙向認證 management：personal `role.md` 宣告 + shared `_roles.md` 白名單，缺一不可（防自封）
- `bootstrap_personal_dir()`: 首次進專案自動建 `personal/{user}/`、寫 role.md 樣板、冪等 append `.claude/memory/personal/` 到 `.gitignore`

**驗證**：
- 單元：`python -c "from hooks.wg_roles import *; print(get_user_role('C:/some/proj'))"`
- 手動：刪除 personal/ → SessionStart → 自動重建 + .gitignore 生效

**commit**：`feat(atom-v4): role-based path resolution and bootstrap`

---

### Phase 3：atom_write schema 擴充 + 寫入路徑切換
**目標**：MCP 支援新 scope；舊呼叫透明遷移。

**檔案**：
- [tools/workflow-guardian-mcp/server.js:382](tools/workflow-guardian-mcp/server.js#L382) — schema 加 `scope` enum 擴展 (`"shared","role","personal"`)、新增 `role`/`audience`/`author`/`pending_review_by`/`merge_strategy` 欄位
- [tools/workflow-guardian-mcp/server.js:655](tools/workflow-guardian-mcp/server.js#L655) — `resolveMemDir()` 支援新 scope；legacy `scope=project` → 自動轉 `shared` + 注 metadata
- [tools/workflow-guardian-mcp/server.js:817](tools/workflow-guardian-mcp/server.js#L817) — atom body template 加新 metadata 欄
- [hooks/wg_content_classify.py:50](hooks/wg_content_classify.py#L50) — 新增 `classify_audience(content)`（關鍵字規則，命中 art/programmer/planner/...）

**關鍵設計**：
- schema 用 `scope` enum + 獨立 `role` 欄（不塞複合字串），JSONSchema 友善
- `author` MCP 端從 env 自動帶入，不讓 LLM 亂填
- 寫入時若 `scope=shared` 且 `audience` 含敏感類別 → 自動標 `pending_review_by: management`，改寫到 `shared/_pending_review/`

**驗證**：三種 scope 各寫一個 atom，確認落點 + metadata + legacy 寫法相容

**commit**：`feat(atom-v4): extend atom_write with role/audience/author schema`

---

### Phase 4：JIT 注入 role filter + 向量索引擴充
**目標**：SessionStart 只載「shared + 我的 role + 我的 personal」，別組 role 不載。

**檔案**：
- [hooks/workflow-guardian.py:210](hooks/workflow-guardian.py#L210) — 讀 user role，呼叫新版 `discover_memory_layers(user, role)`
- [hooks/wg_intent.py:308](hooks/wg_intent.py#L308) — `_semantic_search` 加 `role` 參數
- [tools/memory-vector-service/searcher.py](tools/memory-vector-service/searcher.py) / [indexer.py](tools/memory-vector-service/indexer.py) / [service.py](tools/memory-vector-service/service.py) — index 時記錄 `scope`/`role`/`author` metadata；search 時依 user 過濾
- [memory/_ATOM_INDEX.md](memory/_ATOM_INDEX.md) 表頭 — 新增 Scope 欄

**關鍵設計**：
- vector `layer` 參數擴為 `"shared" | "role:{role}" | "personal:{user}" | "global" | "all"`，service 端依 metadata filter，不重 index
- _ATOM_INDEX.md 全收（機器讀時 filter）；MEMORY.md 依角色動態生成「我能看的」視圖

**驗證**：
- 切 `CLAUDE_USER=alice`/`bob` 啟 session，確認 injected_atoms 依角色變化
- 查別組 role 關鍵字 → 查不到（除非 shared）

**commit**：`feat(atom-v4): role-filtered JIT injection and vector search`

---

### Phase 5：三時段衝突偵測 + Pending Review Queue
**目標**：write-time / pull-time / git-conflict-time 三入口，事實衝突絕不自動合。

**檔案**：
- [tools/workflow-guardian-mcp/server.js:676](tools/workflow-guardian-mcp/server.js#L676) — write-gate 前插入 shared 語意掃描
- [tools/memory-write-gate.py](tools/memory-write-gate.py) — 擴充 `scope=shared` 寫入時呼叫向量查 top-3 相似（cosine ≥ 0.85 才送分類器）
- [tools/memory-conflict-detector.py:43](tools/memory-conflict-detector.py#L43) — 新增 `--mode=pull-audit`，掃 `git log -p -- .claude/memory/shared/` 自上次 audit 增量
- 新增 [hooks/post-git-pull.sh](hooks/post-git-pull.sh) — git hook 樣板，使用者複製到專案 `.git/hooks/`
- 新增 [skills/conflict-review/SKILL.md](skills/conflict-review/SKILL.md) — `/conflict-review` 命令，列 pending queue、引導管理職裁決

**關鍵設計**：
- 衝突分類三類：
  - **純新增**（新 atom 或新增非重疊 bullet）→ 自動合 + log
  - **補充**（同 trigger、知識互補）→ 產草稿進 pending，須人工 approve
  - **事實衝突**（LLM 判 CONTRADICT）→ 強制 `pending_review_by: management`，**不生草稿**只列差異
- `merge-strategy: git-only` 標記繞過 AI 合併
- pending queue 進 `shared/_pending_review/{atom}.{ts}.md`，入版控（management 可在別台機器審）
- conservative default：LLM 判不出 → 一律 pending（漏判好過誤判）

**驗證**：
- 人為製造事實衝突（兩 user 寫互斥）→ 確認進 pending
- 純新增 case → 確認自動合 + log
- git mergetool case → 確認 Claude 只給建議不動檔

**commit**：`feat(atom-v4): three-timing conflict detection with management review`

---

### Phase 6：遷移 + 驗收 + 文件
**目標**：舊 atom migrate、`/init-roles` 上線、end-to-end 多帳號煙霧測試。

**檔案**：
- 新增 [tools/migrate-atom-v4.py](tools/migrate-atom-v4.py) — dry-run 預設；無 Scope 行的 project atom 補 `Scope: shared`、`Author: unknown`、`Audience: all`，**不搬檔案位置**（延後到實際分層需求出現）
- 新增 [skills/init-roles/SKILL.md](skills/init-roles/SKILL.md) — `/init-roles` 互動建立 `_roles.md` + 各成員 personal/ + .gitignore
- 更新 [skills/upgrade/SKILL.md](skills/upgrade/SKILL.md) — upgrade 流程加 V4 migration 步驟
- 更新 [_AIDocs/SPEC_ATOM_V4.md](_AIDocs/SPEC_ATOM_V4.md) — 補實作 learnings
- 更新 [memory/MEMORY.md](memory/MEMORY.md) — 三層 scope 使用說明

**驗證**：
- 既有專案跑 `migrate-atom-v4.py --dry-run` → 看 diff → `--apply`
- 多帳號模擬：`CLAUDE_USER=alice`（programmer）vs `bob`（art）各寫，確認可見性正確
- 衝突演練：alice + bob 對同一 trigger 寫互斥 → 攔截 → management 裁決

**commit**：`feat(atom-v4): migration tool and multi-user acceptance test`

---

## 與舊系統共存

- **讀**：無 `Scope:` 行的 atom → 依檔案位置決定 (global 層 → global、project 層 → shared)
- **寫**：legacy `scope=project` → 自動轉 shared + 加 author/audience
- **遷移**：Phase 6 只補 metadata 不搬檔，避免大量 git diff；漸進式分層
- **MCP 相容**：舊 schema 欄位全留，僅擴 enum + 新 optional 欄位，舊 client 不升級仍可寫

---

## 端到端驗證劇本（最終驗收）

1. 在乾淨 Unity 專案目錄執行 `/init-roles` → 建出 `_roles.md`、自己加入為 `programmer + management`
2. 切 `CLAUDE_USER=alice` 模擬美術，宣告 `role: art`，寫一個美術專屬 atom → 確認落 `roles/art/`
3. 切回自己 → SessionStart 注入結果：看到 shared + programmer + 自己的 personal，**沒有** alice 的美術 atom
4. alice 寫一個 shared atom 標 `architecture` → 自動進 `_pending_review/`
5. 自己（management）跑 `/conflict-review` → 列出 pending → approve → 進主索引 + reindex
6. alice 與我同時對 trigger `framework-choice` 寫互斥知識 → 第二次寫入被攔截 → pending → management 裁決後寫 `decided-by` + log
7. `git pull` 同事新版本 → post-git-pull hook 跑 audit → 若有衝突進 pending → 否則靜默通過

---

## Critical Files
- [tools/workflow-guardian-mcp/server.js](tools/workflow-guardian-mcp/server.js)
- [hooks/wg_paths.py](hooks/wg_paths.py)
- [hooks/workflow-guardian.py](hooks/workflow-guardian.py)
- [tools/memory-conflict-detector.py](tools/memory-conflict-detector.py)
- [tools/memory-vector-service/](tools/memory-vector-service/)
- [hooks/wg_content_classify.py](hooks/wg_content_classify.py)

---

## 後續工作：現存知識庫文件分類（另開計畫）

> **不在本 V4 計畫範圍內** — 本 V4 處理「未來新寫入 atom 的分層機制」；既有 `_AIDocs/` 與已存在 atoms 的重新分類整理，因工作量大且需逐檔人工 review，獨立成下一個計畫執行。

### 待分類範圍

**全域 `_AIDocs/`（C:\Users\holylight\.claude\_AIDocs\）**
- Architecture.md / Project_File_Tree.md / DocIndex-System.md
- ClaudeCodeInternals/ (harness / hook / MCP / skill 等)
- Tools/ (Excel / Unity YAML / GUID 等)
- Failures/ (環境陷阱 / 假設錯誤)
- DevHistory/ (A/B 測試、實驗紀錄)

**全域既有 atoms（C:\Users\holylight\.claude\memory\）**
- preferences / decisions / decisions-architecture / workflow-* / toolchain-* / feedback-* / gdoc-harvester ...

### 主分類大類（使用者拍板）

> **不列「涵蓋例」**，避免列舉反過來限制分類想像。改用「判定原則」描述歸屬條件 — 一切以「服務對象的工作場景」為準。

| 大類 | 對映 V4 scope | 判定原則 |
|---|---|---|
| **程式** | role:programmer | 服務於程式人員工作場景的一切知識 — 含程式邏輯細節、架構、API、語言 / 框架、debug、效能、資料結構（如雙向索引記憶）、自動化等，不限類型 |
| **企劃** | role:planner | 服務於企劃工作場景 — 設計規格、流程、需求、平衡 |
| **美術** | role:art | 服務於美術工作場景 — asset、shader、素材處理、圖像工作流 |
| **環境** | shared | 跨角色共用的「執行 / 運作環境」知識 — OS、shell、工具鏈安裝、跨平台差異 |
| **AI** | shared | AI 工具與系統本身 — Claude Code、Anthropic API、Ollama、原子記憶系統 |
| **其他** | shared 或保留 global | 暫不易歸類者，先放 shared 留待二次分類 |

### 分類粒度與跨區重疊

- **粒度細到段落**：分類判定不應以「檔案」為單位，而是逐段落（甚至逐 bullet）依「內容重點 / 該段形成的原因 / 解決的問題場景」決定。一個檔案內可能多段落各屬不同分類。
- **跨區重疊允許**：直接利用 V4 schema 既有的 `Audience: [...]` 多標欄位 — 同一段知識若同時服務「程式」與「環境」，標兩個 audience，索引時兩邊都查得到。預期跨區案例為小比例（例：toolchain-ollama 的安裝部分屬「環境」、調用 API 部分屬「程式」+「AI」）。
- **不預設分布假設**：實際分布由內容驅動，分類腳本不能寫死「期望大多數歸 X」這類假設；統計只在 dry-run 報告中事後呈現給使用者參考。
- **分類產出單位**：對 atoms 保持「一檔一 atom」；對 `_AIDocs/` 大檔（如 Architecture.md），若段落分類差異大，下一計畫需設計「拆檔 vs 多標」決策準則。

### 下一個計畫應涵蓋

1. **盤點工具**：寫 script 列出所有待分類檔案（含字數、最後修改日）→ 輸出 CSV 給使用者勾選
2. **分類 SOP**：定義「一檔多類」（如 toolchain-ollama 同時 環境 + AI）的處理規則 — 用 audience 多標還是放主類別 + cross-link
3. **重組執行**：分批搬檔 / 拆檔 / 合併（每批一次 commit，方便 revert）
4. **索引重建**：搬完後重跑 `_ATOM_INDEX.md` 生成 + 向量 reindex
5. **使用者 checkpoint**：每完成一個大類請使用者 review 後才動下一類（避免大規模誤分類）

### 與本 V4 計畫的接軌

- 本 V4 Phase 1 SPEC 中要明確列出這六大類為 `audience` 與 `role` 的合法值
- 本 V4 Phase 6 migration 腳本只補 `Scope: shared`，不動分類；分類交由「下一計畫」處理
- 下一計畫的前置條件：本 V4 完成 Phase 1-4（schema + 寫入 + 注入準備好），才有「分類目標」可分

### 預估規模

- _AIDocs 約 10 主檔 + 數十子檔，全域 atom 約 15 檔；總分類決策約 50-80 次
- 需 1-2 個 session 完成（取決於使用者 review 速度）
- 風險：誤分類會讓 JIT 注入錯角色 → 必須 dry-run + 使用者確認
