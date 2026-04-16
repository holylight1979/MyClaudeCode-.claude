# SPEC: 原子記憶系統 V4 — 多職務團隊共享

> **狀態**：規格定稿（Phase 1）。本文件為 V4 設計依據，後續 Phase 2-6 實作以本文件為唯一來源。
> **相關計畫**：[../plans/gentle-puzzling-kettle.md](../plans/gentle-puzzling-kettle.md)
> **位置**：`_AIDocs/`（長期參考知識，rules/core.md 第 3 條）— 非 atom；由 `_AIDocs/_INDEX.md` 索引，SessionStart 自動提示。

---

## 1. 背景與動機

V3.4 原子記憶只有 `global / project` 二層 scope，預設「單一使用者寫、單一使用者讀」。當未來推廣到 Unity 團隊（美術 / 程式 / 企劃，未來擴 PM / QA / 管理職），會出現三類問題：

1. **個人偏好污染團隊知識** — 「我習慣用 A 框架」混入 shared 後變成「團隊規範用 A 框架」
2. **跨職務雜訊** — 美術不需要看程式架構決議，反之亦然，但目前都被 JIT 一起注入
3. **衝突無解** — 多人同步寫 shared 時，事實衝突會被任一邊靜默覆蓋

V4 升級目標：擴成 **personal / project-shared / role-shared** 三層；atoms 跟 git/svn 走入版控；按角色 filter 注入；事實衝突強制管理職裁決。

---

## 2. 三層 Scope 定義

| Scope | 用途 | 位置 | 是否入版控 |
|---|---|---|---|
| `global` | 跨專案通用知識（不變動，沿用 V3） | `~/.claude/memory/` | 視 `~/.claude` 自身的 git 而定 |
| `shared`（project-shared） | 專案內全員共享 — 決議、架構、規範、踩坑 | `{proj}/.claude/memory/shared/` | **是** |
| `role:{name}`（role-shared） | 特定職務組內共享 | `{proj}/.claude/memory/roles/{name}/` | **是** |
| `personal:{user}`（personal-in-project） | 個人在該專案的偏好/筆記 | `{proj}/.claude/memory/personal/{user}/` | **否（.gitignore）** |

### Scope 對映（V3 → V4）

| V3 | V4 | 行為 |
|---|---|---|
| `global` | `global` | 完全不變 |
| `project` | `shared` | 自動遷移；舊呼叫透明轉換 |

---

## 3. 目錄結構（per project）

```
{project_root}/.claude/memory/
├── _ATOM_INDEX.md              # 機器索引（含 Scope 欄）
├── MEMORY.md                   # 人讀索引（依角色動態生成「我能看的」視圖）
├── _roles.md                   # 管理職白名單（shared，入版控）
├── shared/                     # project-shared
│   ├── {atom}.md
│   └── _pending_review/        # 待管理職裁決的衝突草稿
├── roles/                      # role-shared
│   ├── art/
│   ├── programmer/
│   ├── planner/
│   ├── pm/
│   ├── qa/
│   └── management/
├── personal/                   # personal-in-project（.gitignore）
│   └── {user}/
│       ├── role.md             # 角色自我宣告
│       └── {atom}.md
└── _merge_history.log          # append-only 稽核
```

### .gitignore 機制

`bootstrap_personal_dir()` 首次進專案時冪等 append 一行：
```
.claude/memory/personal/
```

---

## 4. Atom Metadata Schema

V3 既有欄位全保留，僅擴充 enum 與新增可選欄。

### V4 metadata（atom markdown list 擴充）
```markdown
# 標題
- Scope: shared | role:{role} | personal:{user} | global
- Audience: programmer, art            # 可選；多標 role；用於跨區索引
- Author: {os.getlogin()}              # MCP 端自動帶入
- Confidence: [固] | [觀] | [臨]
- Trigger: keyword1, keyword2
- Last-used: YYYY-MM-DD
- Confirmations: N
- Pending-review-by: management        # 可選；標記後寫入 _pending_review/
- Decided-by: {user}                   # 可選；管理職裁決後留痕
- Merge-strategy: ai-assist | git-only # 預設 ai-assist
- Created-at: YYYY-MM-DD
- Related: atom1, atom2
```

### 範例 atom — shared（程式）

```markdown
# Unity Addressable 載入規範

- Scope: shared
- Audience: programmer
- Author: holylight1979
- Confidence: [臨]
- Trigger: addressable, 載入, async, prefab
- Created-at: 2026-04-15
- Related: unity-build-pipeline

## 知識
- [臨] Addressable 預設用 LoadAssetAsync，禁用同步 Load — 避免主執行緒卡頓
- [臨] Group 命名規則：{module}_{category}，例 `combat_vfx`
```

### 範例 atom — role:art

```markdown
# Photoshop 素材命名規則

- Scope: role:art
- Audience: art
- Author: alice
- Confidence: [臨]
- Trigger: photoshop, 命名, 素材, psd
- Created-at: 2026-04-15

## 知識
- [臨] PSD 圖層命名：`{部位}_{狀態}`，例 `face_smile`
- [臨] 輸出 PNG 用 `Export As`，不用 `Save for Web`（後者已棄用）
```

### 範例 atom — personal

```markdown
# 我的 IDE 偏好

- Scope: personal:holylight1979
- Author: holylight1979
- Confidence: [臨]
- Trigger: vscode, 偏好
- Created-at: 2026-04-15

## 知識
- [臨] VSCode 字體偏好 JetBrains Mono 14
- [臨] 慣用 Ctrl+Shift+F 全域搜尋
```

---

## 5. 六大分類大類（Audience / Role 合法值）

> **不列「涵蓋例」**，避免列舉造成限制想像。改用「判定原則」描述歸屬條件。

| 大類值 | 對映 V4 scope | 判定原則 |
|---|---|---|
| `programmer`（程式） | `role:programmer` | 服務於程式人員工作場景的一切知識 — 含程式邏輯細節、架構、API、語言/框架、debug、效能、資料結構（如雙向索引記憶）、自動化等，不限類型 |
| `planner`（企劃） | `role:planner` | 服務於企劃工作場景 — 設計規格、流程、需求、平衡 |
| `art`（美術） | `role:art` | 服務於美術工作場景 — asset、shader、素材處理、圖像工作流 |
| `environment`（環境） | `shared` | 跨角色共用的「執行/運作環境」知識 — OS、shell、工具鏈安裝、跨平台差異 |
| `ai`（AI） | `shared` | AI 工具與系統本身 — Claude Code、Anthropic API、Ollama、原子記憶系統 |
| `other`（其他） | `shared` 或保留 `global` | 暫不易歸類者，先放 shared 留待二次分類 |

### 跨區重疊（多 audience）

`Audience: a, b, c` 多標 — 同一段知識若同時服務「程式」與「環境」，標兩個 audience，索引時兩邊都查得到。預期跨區案例為小比例（例：toolchain-ollama 的安裝部分屬「環境」、調用 API 部分屬「程式 + AI」）。

### 額外保留角色

`pm`（專案管理）、`qa`（測試）、`management`（管理職） — 預設未啟用，team 需要時在 `_roles.md` 開通。

---

## 6. 角色機制

### 6.1 角色宣告（personal `role.md`）

每個使用者在每個專案宣告自己的角色：

```markdown
# Role Declaration
- User: holylight1979
- Role: programmer
- Management: false
```

允許多角色：`Role: programmer, management`（逗號分隔）。

### 6.2 管理職雙向認證

`is_management(user)` 必須**同時**通過：
1. **personal `role.md`** 自我宣告含 `management`
2. **shared `_roles.md`** 白名單列出該 user

任一缺失 → 視為非管理職。**目的**：防止任何使用者自封管理職而改動事實衝突的仲裁。

### 6.3 `_roles.md` 範例（shared）

```markdown
# Project Role Registry

## 成員

| User | Roles |
|---|---|
| holylight1979 | programmer, management |
| alice | art |
| bob | programmer |
| carol | planner, pm |

## Management 白名單
- holylight1979

## 角色說明
- programmer: ...
- art: ...
```

---

## 7. 衝突偵測（三時段）

### 7.1 時段對映

| 時段 | 觸發 | 策略 | 主要受益 |
|---|---|---|---|
| **Write-time** | `atom_write` 寫入 `scope=shared` 前 | 語意掃描（vector + 關鍵詞）→ 命中 → 分類處理 | 所有人 |
| **Pull-time** | `git pull` 後偵測 `memory/shared/` 變動 | 背景 audit 新進 atom vs 本地 → 衝突 → pending | 多人團隊 |
| **Git-conflict-time** | 真的硬碰硬同段編輯 | 走 `git mergetool`，Claude 提供合併建議但**不自動落地** | 罕見 fallback |

### 7.2 衝突分類

| 類型 | 判定 | 處理 |
|---|---|---|
| **純新增** | 新 atom 或同 atom 新增非重疊 bullet | 自動合 + 寫 `_merge_history.log` |
| **補充** | 同 trigger、知識互補 | 產草稿進 `_pending_review/`，須人工 approve |
| **事實衝突** | LLM 判 CONTRADICT | 強制 `pending_review_by: management`，**不生草稿**只列差異 |

### 7.3 閾值與保險

- 向量 cosine **≥ 0.85** 才送 LLM 分類器（避免噪音）
- LLM 判不出來 → conservative default：**一律 pending**（漏判好過誤判）
- atom 標 `Merge-strategy: git-only` → 完全跳過 AI 合併，整份走 git mergetool
- 所有合併動作（含自動）寫 `_merge_history.log`（append-only，可回溯）

### 7.4 敏感類別自動 Pending

`scope=shared` 寫入時，若 `Audience` 含敏感類別（第一版：`architecture`, `decision`） → 自動標 `Pending-review-by: management`，改寫到 `_pending_review/`。第一版白名單可後續擴。

---

## 8. JIT 注入規則（按角色 filter）

### 8.1 注入內容

對使用者 U（角色為 R）：
- ✅ `global/*`
- ✅ `shared/*`（不含 `_pending_review/`）
- ✅ `roles/{R}/*`（若 U 有多角色，全部載）
- ✅ `personal/{U}/*`
- ❌ `roles/{其他角色}/*`（不載）
- ❌ `personal/{其他 user}/*`(不載)

### 8.2 管理職額外

`is_management(U) == true` 時，額外可訪問：
- `shared/_pending_review/*` 列表（用於 `/conflict-review` 流程）
- 所有 role 目錄的「索引」（不含內容；用於跨組裁決參考）

### 8.3 向量服務 `layer` 參數

擴展為：
- `"global"`
- `"shared"`
- `"role:{name}"`
- `"personal:{user}"`
- `"all"`（管理職用）

Service 端依 metadata filter，**不重 index**。

---

## 9. 預設決策表（拍板）

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

## 10. 與舊系統相容性

- **讀**：無 `Scope:` 行的 atom → 依檔案位置決定（global 層 → `global`、project 層 → `shared`）
- **寫**：legacy `scope=project` → 自動轉 `shared` + 加 `Author` / `Audience` metadata
- **遷移**：Phase 6 migrate 腳本只補 metadata 不搬檔（避免大量 git diff）；漸進式分層
- **MCP 相容**：舊 schema 欄位全留，僅擴 `scope` enum + 新增 optional 欄位；舊 client 不升級仍可寫（預設 `shared`）
- **舊 hook 共存**：`workflow-guardian.py` 升級後自動兼容無 `Scope:` 行的 V3 atom

---
 
## 11. 後續工作（不在 V4 範圍）

### 既有知識庫文件分類（另開計畫）

對 `_AIDocs/`（Architecture / ClaudeCodeInternals / Tools / Failures / DevHistory）與既有全域 atoms 的重新分類整理，**獨立成下一個計畫**執行。

**核心原則**（已寫入計畫）：
- 分類粒度細到段落（不是純按檔案）
- 跨區重疊允許（用 `Audience: [...]` 多標）
- 不預設分布假設（內容驅動）
- 大檔（如 Architecture.md）若段落分類差異大 → 拆檔 vs 多標決策準則需另設計

**前置條件**：本 V4 完成 Phase 1-4（schema + 寫入 + 注入準備好），才有「分類目標」可分。

---

## 12. 變更紀錄

| 日期 | 版本 | 變更 |
|---|---|---|
| 2026-04-15 | V4 SPEC freeze (Phase 1) | 初版定稿，含三層 scope、目錄結構、metadata schema、六大分類值、衝突偵測規則、JIT filter |
