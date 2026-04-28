# Atom Trigger 三源真相規格化

> Date: 2026-04-28
> 衍生：Stage F 重審 §「附帶議題：atom 注入機制 3 源不一致」（[follow-up-issues.md §議題 #9 末段](memory-cleanup-2026-04/follow-up-issues.md)）
> 狀態：**設計文件 — 待使用者拍板方向後實作**

## 一、現況：三源各自為政

| 源 | 檔案 / 位置 | 寫入時機 | 讀取者 | 角色 |
|----|-----------|----------|--------|------|
| **A. frontmatter `Trigger:`** | 每 atom 開頭（如 `memory/decisions-architecture.md:5`） | atom_write MCP 建立時 / 使用者手動編輯 | **無程式碼讀取**（純展示給 AI 看） | 註記性質 |
| **B. `_ATOM_INDEX.md` 表格** | `memory/_ATOM_INDEX.md` | atom_write MCP 同步寫入（[server.js:828](../../tools/workflow-guardian-mcp/server.js#L828) `resolveMemoryIndex` 偏好此檔） | **`wg_atoms.py:36-43` 唯一機器讀取點** | **真相源（事實上）** |
| **C. `MEMORY.md` 索引列表** | `memory/MEMORY.md` | 純手寫維護 | `@import` always-loaded 進 LLM context（每 turn ~150 tokens） | 給 LLM 看的目錄（介紹性） |

### 1.1 hook 實際讀取路徑（[wg_atoms.py:27-63](../../hooks/wg_atoms.py#L27-L63)）

```
parse_memory_index(memory_dir):
    1. 優先讀 _ATOM_INDEX.md（V3.2）→ 解析 markdown table → return
    2. fallback 讀 MEMORY.md
       - 若 "Status: migrated-v2.21" → redirect 到 Root 指向新路徑
       - 否則解析 table → return
```

→ 結論：**frontmatter `Trigger:` 完全沒有任何 hook 讀取**。它只是給 AI 看的「自我宣告」，不會被注入機制使用。

### 1.2 atom_write MCP 寫入路徑（[server.js:952-1014](../../tools/workflow-guardian-mcp/server.js#L952-L1014)）

```
atom_write(triggers=[...], ...):
    1. 寫 atom 檔（含 frontmatter `Trigger:` 從 triggers 參數）
    2. appendToIndex(memDir, atomName, relPath, triggers):
       - resolveMemoryIndex 偏好 _ATOM_INDEX.md
       - 若 atom 已存在表中 → 更新該行
       - 否則插入新行
```

→ **建立時兩源同步寫入**；但**事後編輯（手動改 frontmatter / 手動改 _ATOM_INDEX）無同步**。MEMORY.md **完全不被 MCP 觸碰**。

## 二、Drift 盤點（2026-04-28 現場）

### 2.1 frontmatter Trigger ≠ _ATOM_INDEX trigger 列（≥ 12 atom）

從 `grep -n '^- Trigger:'` 對比 `_ATOM_INDEX.md` 觀察：

| Atom | frontmatter 多出 | _ATOM_INDEX 多出 |
|------|------------------|-------------------|
| decisions | 晉升, 品質機制, fix escalation | guardian, hooks, 架構細節 |
| toolchain-ollama | gemma4 | — |
| feedback-research-first | 不熟悉, research | — |
| feedback-fix-escalation | 失敗 | 再次失敗 |
| feedback-codex-companion-model | ChatGPT Pro, OpenAI 訂閱 | — |
| feedback-memory-path | 暫存, 寫檔案 | 記憶路徑 |
| feedback-no-test-to-svn | 測試碼, 練習 | 測試碼不上傳, 不可上傳 |
| feedback-decision-no-tech-menu | 選擇, 要不要, 白話 | 建議優選 |
| feedback-scope-sensitive | hash, 端口, 絕對路徑 | GUID硬編碼, fileID, 端口硬編碼, 硬編碼路徑 |
| feedback-git-log-chinese | git, log, message, 上版 | commit message, commit msg, git commit, git log, git push |
| feedback-fix-on-discovery | drift, 尾巴 | 順手發現, 不在本次範圍 |
| feedback-no-outsource-rigor | 規範, 角度, 自主, 還有什麼 | — |

**判讀**：使用者過去顯然有同時在兩處編輯的習慣，但編輯時間/範圍未對齊 → 各自漂移。

### 2.2 frontmatter 有 Trigger 但未進 _ATOM_INDEX（5 檔）

| 檔案 | 性質 | 應否入索引 |
|------|------|-----------|
| `feedback/feedback-codex-collaboration.md` | atom（Codex 異議審查規則） | **應該** |
| `feedback/feedback-end-to-end-smoke.md` | atom（整合測試規則） | **應該** |
| `feedback/feedback-pre-completion-test-discipline.md` | atom（TestFailGate / known regression 規則） | **應該** |
| `wisdom/DESIGN.md` | 設計文件，非 atom | 不應 |
| `templates/icld-sprint-template.md` | 模板，非 atom | 不應 |

→ 前 3 檔有 frontmatter Trigger 但 hook 不會注入 → 「裝飾性 Trigger」失效範例（與 Stage F 之前的 decisions-architecture / feedback-codex-companion-model 同模式）。

### 2.3 MEMORY.md 「feedback-* (19 個)」實際 17 個

`MEMORY.md:15` 寫 `feedback-* | 行為校正（19 個含 ...）` — 但 `_ATOM_INDEX.md` 中 feedback 系列只有 17 條（含 fix-escalation、feedback-pointer-atom）。**手動維護的計數已 drift**。

## 三、設計目標

1. **唯一機器真相源**：hook / vector / 任何工具讀取 trigger，只認一個地方
2. **Drift 偵測 + 修補可自動化**：避免再次手動兩處同步失敗
3. **MEMORY.md 不再手動維護計數**：由工具掃描生成
4. **frontmatter Trigger 的角色明確**：要嘛取消、要嘛降級為「人看的註記」
5. **atom_write MCP 仍是建立時的入口**：不打掉重練

## 四、選項分析

### 選項 A：`_ATOM_INDEX.md` 為唯一機器真相源（推薦）

**規則**：
- `_ATOM_INDEX.md` 是 hook 讀取的唯一機器源
- frontmatter `Trigger:` 改為**註記欄位**（值必須等於 _ATOM_INDEX 對應行；新增 `tools/sync-atom-index.py` 校驗 + `--fix` 同步）
- `MEMORY.md` 改為**自動生成**（從 `_ATOM_INDEX.md` 掃出 atom 名稱 + scope，產生人讀目錄；自動保留現有「知識庫查閱」段落）

**優點**：
- 改動最小（hook 已經以 _ATOM_INDEX 為主，符合既有設計）
- frontmatter Trigger 不必砍（仍對人類可讀有價值）
- 一鍵校驗 + 修補
- atom_write MCP 邏輯不必動

**缺點**：
- frontmatter Trigger 與 _ATOM_INDEX 仍有「兩處資料」，需校驗工具維持一致
- 校驗工具若不跑就會 drift（但有定期 hook 檢查可緩解）

### 選項 B：frontmatter Trigger 為唯一真相源 + 工具生成 _ATOM_INDEX.md

**規則**：
- 每 atom 的 frontmatter `Trigger:` 是真相
- `_ATOM_INDEX.md` 由 `tools/build-atom-index.py` 從掃描所有 atom frontmatter 生成（gitignore 或 generated marker）
- MEMORY.md 同樣自動生成

**優點**：
- 真相分散在 atom 檔本身，編輯 atom 即同步 trigger（不會忘記改另一處）
- 移除「兩處編輯漂移」的根本來源

**缺點**：
- hook 每 SessionStart 要不要重跑生成？快取或現場 walk dir？性能風險
- atom_write MCP 寫入後仍需觸發 build script 才能讓新 atom 被 hook 看到（一次延遲）
- 「哪些檔案算 atom（vs DESIGN/template）」需要明確規則（看 frontmatter `Scope:` 是否存在？看路徑？）

### 選項 C：取消 frontmatter Trigger 欄位

**規則**：
- 從所有 atom 移除 frontmatter `Trigger:`
- _ATOM_INDEX.md 為唯一源
- MEMORY.md 自動生成

**優點**：
- 真相唯一，零 drift 可能
- frontmatter 變短

**缺點**：
- 失去「atom 自己宣告自己 trigger」的人類可讀性（要查 trigger 必須看 _ATOM_INDEX）
- 既有 26 個 atom 要批次刪 frontmatter Trigger 欄位
- 與「印象式記憶」設計理念不符（atom 自己定義自己角色）

## 五、推薦：選項 A

**理由**：
1. **匹配既有實況**：hook 已經以 _ATOM_INDEX 為主源，atom_write MCP 也已雙寫
2. **保留 frontmatter Trigger 的人類可讀性**：對話中讀 atom 檔時直接看到觸發詞，不必跨檔查
3. **改動最輕**：新增 2 個 sync 工具 + 既有檔不必批次改
4. **drift 修補一次性**：跑 `--fix` 一鍵把現存 12+ 處對齊
5. **未來機制可擴**：sync-atom-index 跑 PreCommit 或 SessionStart 即可常態化校驗

**選項 A 確立後的子問題（需追加決策）**：
- (a) `feedback-codex-collaboration` / `feedback-end-to-end-smoke` / `feedback-pre-completion-test-discipline` 三個有 frontmatter Trigger 但未進 _ATOM_INDEX 的 atom — **要補進索引（從 frontmatter 同步），還是要刪除其 frontmatter Trigger（明確不入索引）**？建議補進，因為它們確實是行為校正 atom。
- (b) frontmatter Trigger 與 _ATOM_INDEX 不一致時，`--fix` 預設方向是哪邊？建議 **以 _ATOM_INDEX 為主**（hook 實際讀的），把 frontmatter 同步成 _ATOM_INDEX 內容；因為 _ATOM_INDEX 是被即時注入的，drift 時應信任「實際生效」那份。
- (c) `wisdom/DESIGN.md` / `templates/icld-sprint-template.md` 的 frontmatter Trigger — 它們不是 atom，要不要砍掉那行？建議**砍掉 DESIGN.md 的 Trigger**（它是設計文件，誤導）；template 保留（模板用 frontmatter 示範格式）。

## 六、實作步驟（待使用者拍板選項 A 後執行）

### Step 1：寫 `tools/sync-atom-index.py`

```
功能：
  - 預設模式（dry-run）：掃描 memory/ 下所有 .md，解析 frontmatter Trigger
    比對 _ATOM_INDEX.md，輸出 drift 報告：
      [MISSING_IN_INDEX] frontmatter 有 Trigger 但 _ATOM_INDEX 缺
      [MISSING_FRONTMATTER] _ATOM_INDEX 有但 atom 檔無 frontmatter Trigger
      [TRIGGER_DRIFT] 兩處 trigger 列不一致（diff）
      [ORPHAN_INDEX] _ATOM_INDEX 引用的 atom 檔不存在
  - --fix 模式：把 frontmatter Trigger 同步為 _ATOM_INDEX 表格內容（推薦方向）
    或 --fix=index-from-frontmatter：反向同步（用於某 atom 編輯了 frontmatter 想推到索引）
  - --add-from-frontmatter：把 [MISSING_IN_INDEX] 的 atom 自動補進 _ATOM_INDEX

輸出：
  stdout JSON 報告（給 hook / human 讀）
  exit code: 0=clean / 1=drift detected
```

### Step 2：寫 `tools/sync-memory-index.py`

```
功能：
  - 掃 _ATOM_INDEX.md → 按 scope 分組生成 MEMORY.md「Atom Index」表
  - 保留 MEMORY.md 中現有「知識庫查閱」段落（自動偵測標記分隔）
  - --check 模式：對比現存 MEMORY.md，drift 則 exit 1
  - --write 模式：覆寫 MEMORY.md

輸出格式：
  | Atom | 說明 |  ← 「說明」欄從 atom 第一行 H1 提取
  | feedback-* | 行為校正（17 個含 ...） |  ← 自動計數
```

### Step 3：選擇性 — atom_write MCP 整合

[server.js:1181](../../tools/workflow-guardian-mcp/server.js#L1181) `appendToIndex` 後追加呼叫 sync-memory-index.py --write，讓建立 atom 時 MEMORY.md 也自動更新。

### Step 4：選擇性 — PreCommit hook 校驗

`.git/hooks/pre-commit` 跑 `sync-atom-index.py`（dry-run），drift 時 fail commit；強制使用者跑 `--fix`。

### Step 5：跑全套校驗 + 修補

1. 跑 `sync-atom-index.py --add-from-frontmatter` → 補進 3 個 [MISSING_IN_INDEX]（feedback-codex-collaboration、feedback-end-to-end-smoke、feedback-pre-completion-test-discipline）
2. 跑 `sync-atom-index.py --fix` → 把 frontmatter Trigger 與 _ATOM_INDEX 對齊
3. 砍 `wisdom/DESIGN.md` 的 frontmatter Trigger 行（手動）
4. 跑 `sync-memory-index.py --write` → 重生 MEMORY.md
5. smoke：`python -c "from hooks.wg_atoms import parse_memory_index; ..."` 驗 26 atom 全 parse 成功
6. pytest 全跑

## 七、不動的範圍

- atom 內容本身（只動索引機制）
- always-loaded 入口（`CLAUDE.md` / `IDENTITY.md` / `USER.md` / `MEMORY.md` 結構不換 — MEMORY.md 內容由工具生成但 @import 路徑不變）
- atom_write MCP 寫入主流程（最多在尾端追加同步呼叫）
- hook 讀取邏輯（仍走 `parse_memory_index` 偏好 _ATOM_INDEX）

## 八、待使用者裁決點

1. **選 A / B / C 哪個方向？**（推薦 A）
2. **選項 A §五 子問題 (a)**：3 個 frontmatter-only atom 補進索引 OK？
3. **選項 A §五 子問題 (b)**：`--fix` 預設方向 _ATOM_INDEX → frontmatter？
4. **選項 A §五 子問題 (c)**：砍 wisdom/DESIGN.md 的 frontmatter Trigger？
5. **PreCommit hook 整合要不要做**（Step 4，若不做就靠手動跑 sync）
6. **atom_write MCP 整合要不要做**（Step 3，若不做新 atom 不會自動同步 MEMORY.md）
