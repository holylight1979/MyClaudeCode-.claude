# /upgrade — 原子記憶環境升級

> 將指定來源資料夾與 `~/.claude` 比對差異，產生升級計畫並執行。
> 全域 Skill，適用於原子記憶系統版本升級。

---

## 使用方式

```
/upgrade <source_folder>
```

### 參數

| 參數 | 必填 | 說明 | 範例 |
|------|------|------|------|
| source_folder | 是 | 升級來源資料夾路徑（含完整原子記憶環境） | `C:\Users\wellstseng\ClaudeCode-AtomMemory` |

### 使用範例

```
/upgrade C:\Users\wellstseng\ClaudeCode-AtomMemory
/upgrade D:\backup\claude-env-v3
```

### 錯誤處理

- **source_folder 不存在** → 提示路徑錯誤，結束
- **source_folder 無 CLAUDE.md** → 提示「來源不像是有效的原子記憶環境」，結束
- **~/.claude 不存在** → 提示「目標環境不存在」，結束

---

## 輸入

$ARGUMENTS

---

## Step 1: 環境驗證

1. 確認 `$ARGUMENTS`（source_folder）存在且包含 `CLAUDE.md`
2. 確認 `~/.claude/` 存在且包含 `CLAUDE.md`
3. 偵測來源帳號名稱：從 source_folder 路徑或檔案內容中提取使用者帳號（如 `holylight`）
4. 取得目前帳號名稱：`$USER` 或從 `~/.claude/USER.md` 提取（如 `wellstseng`）
5. 讀取雙方的 `memory/MEMORY.md` 以了解各自的 atom 結構

---

## Step 2: 全面差異比對

逐類別掃描，產出差異報告。使用 Agent(Explore) 並行掃描以下 8 個維度：

### 2.1 結構性檔案

比對以下核心檔案，判斷策略：

| 檔案 | 比對邏輯 | 可能策略 |
|------|---------|---------|
| `CLAUDE.md` | diff 行數 + 版本標記 | **替換**（新版通常更精簡） |
| `IDENTITY.md` | diff 內容差異 | **⚠ 個人化確認**（見下方流程） |
| `USER.md` | diff 內容差異 | **⚠ 個人化確認**（見下方流程） |
| `USER.template.md` | 有無 | 新增或替換 |
| `settings.json` | 逐欄比對 hooks/permissions/matcher | **手動合併**（最敏感） |
| `workflow/config.json` | 比對 decay + additional_atom_dirs | 一致則不動，差異則合併 |

#### ⚠ 個人化檔案確認流程

以下檔案屬於**使用者個人化內容**，有異動時必須停下來確認：
- `IDENTITY.md` — 使用者身份定義
- `USER.md` — 使用者個人資料
- `memory/preferences.md` — 使用者偏好（通常確認數很高）
- 其他 atom 中 Confirmations ≥ 10 且內容有實質差異的

**處理流程**（適用於上述每個檔案）：

1. 比對現有版本與來源版本的差異
2. 若**完全相同** → 跳過，不列入計畫
3. 若**有差異** → 在計畫中標記為 `🔶 需確認`，並：
   - 顯示差異摘要（哪些段落新增/修改/刪除）
   - 提供三個選項讓使用者選擇：
     - **A) 保留現有** — 不動
     - **B) 採用來源版本** — 整檔替換（適用於格式升級等情境）
     - **C) 手動合併** — 保留現有內容 + 採納來源的格式/結構改進
   - **必須等使用者回覆後才繼續**，不可自行決定

### 2.2 Hooks

掃描 `hooks/` 目錄：
- 比對 `workflow-guardian.py`：行數差異 = 版本跨度指標
- 偵測新增 hook 檔案（如 `wisdom_engine.py`, `user-init.sh`, `extract-worker.py`）
- 檢查現有 hook 是否有本地修改（與來源不同）

### 2.3 Commands (Skills)

掃描 `commands/` 目錄：
- 列出來源有但現有沒有的 → 新增
- 列出兩邊都有但不同的 → 比較版本，建議替換或合併
- 列出現有有但來源沒有的 → 保留（使用者自建）

### 2.4 Memory Atoms

**這是最關鍵的比對**，需要細緻處理：

1. 讀取雙方 `memory/MEMORY.md` 的 Atom Index
2. 對每個 atom 做以下判斷：

| 情境 | 判斷依據 | 策略 |
|------|---------|------|
| 來源有、現有無 | 檔案不存在 | **新增** |
| 現有有、來源無 | 檔案不在來源 | **保留**（使用者自建） |
| 兩邊都有、同名 | 比對 Confirmations 數量 + 內容差異 | **保留高確認數版本 + 合併缺失段落** |
| 疑似改名 | 名稱不同但 Trigger 重疊 >50% | **標記為改名，合併內容** |

3. 特別處理子目錄：
   - `memory/wisdom/` — 直接比對
   - `memory/episodic/` — 不比對（自動生成）
   - `memory/_staging/` — 確保目錄存在即可
   - `memory/_distant/` — 不比對（封存區）

### 2.5 Tools

掃描 `tools/` 目錄：
- 新增的工具 → 複製
- 共有的工具 → 比對差異，若現有版本有本地改進則**保留現有**並標注
- 特別注意 `memory-vector-service/` 子目錄（indexer.py 等可能有本地改進）

### 2.6 _AIDocs

掃描 `_AIDocs/` 目錄：
- 比對 Architecture.md, Project_File_Tree.md, _INDEX.md, _CHANGELOG.md
- 新增的文件 → 複製
- 已有的文件 → 替換（但需做帳號名稱替換）

### 2.7 系統文件與說明文檔

掃描根目錄下的**非程式碼、非記憶**的文件（系統設計、安裝指南、專案說明）：

| 檔案 | 性質 | 比對邏輯 |
|------|------|---------|
| `README.md` | 系統說明（版本特性、架構圖、流程圖） | diff 版號 + 內容差異 → **替換** |
| `Install-forAI.md` | 安裝指南（安裝步驟、檔案清單） | diff 版號 + 步驟差異 → **替換** |
| `BOOTSTRAP.md` | 啟動引導（如有） | 有無比對 → 新增或替換 |
| `DC-share-post.md` | 社群分享文（如有） | 不動（使用者自建） |
| 其他根目錄 `.md` | 逐一判斷 | 來源有且現有無 → 新增；兩邊都有 → diff 比對 |

**原則**：這類文件跟隨系統版本走，版號/特性描述/安裝步驟必須與升級後的程式碼一致。
帳號名稱（如 git clone URL）若為來源 repo 的正確位址則保留，路徑引用則替換。

### 2.8 設定與配置

掃描非程式碼的設定檔：
- `.gitignore` — 比對差異，合併新增的忽略規則（不刪除現有規則）
- `.mcp.json` — 比對差異，做帳號名稱替換

---

## Step 3: 產出升級計畫

根據 Step 2 的比對結果，產出結構化計畫。格式如下：

```markdown
# ~/.claude 升級計畫：V{現有版本} → V{來源版本}

## Context
來源：{source_folder}（{來源帳號} 的環境）
目標：~/.claude（{目前帳號}，V{現有版本}）
帳號替換：{來源帳號} → {目前帳號}

## 差異總覽

### 🔶 需確認（{N} 個個人化檔案有異動）
{檔案名 + 差異摘要 + A/B/C 選項}

### 替換（{N} 個檔案）
{列表}

### 新增（{N} 個檔案）
{列表}

### 手動合併（{N} 個檔案）
{列表 + 具體合併點}

### Atom 改名（{N} 個）
{舊名 → 新名 + 合併策略}

### 保留不動（{N} 個檔案）
{列表 + 保留原因}

## 執行步驟

### Phase 0：備份
cp -r ~/.claude/ ~/.claude-backup-{版本}-{日期}/

### Phase 1：複製新增檔案（零風險）
{具體 cp 指令}

### Phase 2：Atom 改名與合併
{具體操作 + 編輯指引}

### Phase 3：替換檔案
{具體 cp 指令 — 包含以下類別}
- 程式碼/腳本（hooks/*.py, tools/*.py 等）
- 系統文件（README.md, Install-forAI.md）
- _AIDocs 文件（Architecture.md, Project_File_Tree.md 等）
- 設定檔（.gitignore 合併、.mcp.json）

### Phase 4：手動合併（settings.json 等）
{具體修改描述}

### Phase 5：更新 MEMORY.md
{索引更新內容}

### Phase 6：合併 decisions.md
{追加段落描述}

### Phase 7：帳號名稱替換
grep -r "{來源帳號}" ~/.claude/ → 逐檔替換為 {目前帳號}

### Phase 8：Vector DB 重建
{重建指令}

## 驗證清單
1. 新 session 啟動 → Guardian 正常激活
2. 觸發 atom 載入 → 輸入含 Trigger 關鍵字的 prompt
3. 新 commands 可用
4. grep -r "{來源帳號}" ~/.claude/ → 確認無殘留
5. python ~/.claude/tools/memory-audit.py → 格式驗證

## 回滾
rm -rf ~/.claude/ && cp -r ~/.claude-backup-{版本}-{日期}/ ~/.claude/
```

---

## Step 4: 使用者確認（兩階段）

### 4.1 個人化檔案確認（優先處理）

若計畫中有 `🔶 需確認` 的檔案，**必須先逐一解決**：

對每個標記 🔶 的檔案：
1. 顯示現有版本與來源版本的**關鍵差異**（不用全文 diff，摘要即可）
2. 說明差異性質（格式升級？內容新增？欄位變動？）
3. 提供選項：
   - **A) 保留現有** — 不動
   - **B) 採用來源版本** — 整檔替換
   - **C) 手動合併** — 說明要保留什麼、採納什麼
4. **等待使用者逐一回覆**，不可批量假設

所有 🔶 檔案都確認後，將結果寫入計畫對應的 Phase。

### 4.2 整體計畫確認

> 「升級計畫已產出（{N} 個新增、{N} 個替換、{N} 個合併、{N} 個個人化已確認、{N} 個保留）。要開始執行嗎？」

等待使用者確認。使用者可以：
- 確認 → 進入 Step 5
- 修改 → 調整計畫後再確認
- 取消 → 結束

---

## Step 5: 執行升級

按計畫的 Phase 0~8 順序執行。

### 執行原則

1. **Phase 0 備份必做**，不可跳過
2. **Phase 1 新增檔案**：直接 cp，零風險
3. **Phase 2 Atom 改名**：
   - cp 舊檔為新名 → 編輯更新 Trigger/元資料 → 從來源合併缺失段落
   - 舊檔移入 `memory/_distant/`（不刪除）
4. **Phase 3 替換**：直接 cp 覆蓋，涵蓋四類：
   - 程式碼/腳本：hooks、tools（有本地改進的保留現有，標注差異）
   - 系統文件：README.md、Install-forAI.md（版號/特性/安裝步驟須與程式碼一致）
   - _AIDocs 文件：Architecture.md、Project_File_Tree.md 等（帳號名需替換）
   - 設定檔：.gitignore（合併新增規則，不刪現有）、.mcp.json（帳號替換）
5. **Phase 4 手動合併 settings.json**：
   - 只做差異部分的 surgical edit（不整檔替換）
   - 保留使用者的 permissions、additionalDirectories、effortLevel
   - 重點：SessionStart hooks 順序、PostToolUse matcher 擴展
6. **Phase 5 更新 MEMORY.md**：
   - 更新 Atom Index 表格（新增/改名的條目）
   - 更新高頻事實的版本號
7. **Phase 6 合併 decisions.md**：
   - 保留現有內容（高確認數）
   - 追加來源有但現有缺少的知識段落
   - 更新核心架構行的版本號
   - 追加演化日誌條目
8. **Phase 7 帳號替換**：
   - `grep -r "{來源帳號}" ~/.claude/` 找出所有殘留
   - 逐檔判斷：路徑引用 → 替換；URL/來源備註 → 保留
9. **Phase 8 Vector DB 重建**：
   - 刪除舊 DB：`rm -rf ~/.claude/memory/_vectordb/atom_chunks.lance`
   - 重載 config：`curl -s -X POST http://127.0.0.1:3849/reload`
   - 全量索引：`curl -s -X POST http://127.0.0.1:3849/index/full`
   - 驗證：`curl -s http://127.0.0.1:3849/stats`（確認 atom 數量 + 層數）
   - 格式驗證：`python ~/.claude/tools/memory-audit.py`

---

## Step 6: 驗證

執行驗證清單：

1. **帳號殘留檢查**：`grep -r "{來源帳號}" ~/.claude/` → 判斷是否為合理殘留（URL）或需修正
2. **Vector DB 狀態**：確認 atom 數量、層數、chunk 數量合理
3. **memory-audit 格式驗證**：確認所有 atom 格式正確
4. **MEMORY.md 索引一致性**：索引的 atom 都有對應檔案存在

---

## Step 7: 回報結果

向使用者彙報：

```
升級完成：V{舊版} → V{新版}

- 新增 {N} 個檔案
- 替換 {N} 個檔案
- 合併 {N} 個檔案
- Atom 改名 {N} 個
- 保留 {N} 個（個人化/本地改進）
- 帳號替換 {N} 處（{來源帳號} → {目前帳號}）
- Vector DB：{atom_count} atoms, {layer_count} layers, {chunk_count} chunks

備份位於：~/.claude-backup-{版本}-{日期}/
建議穩定運行一週後清除備份。
```

---

## 注意事項（從實戰經驗總結）

### 個人化檔案（有異動必須停下確認）
- `IDENTITY.md` — 使用者身份定義
- `USER.md` — 使用者個人資料
- `memory/preferences.md` — 使用者偏好（通常確認數很高）
- 任何 Confirmations ≥ 10 且內容有實質差異的 atom

**原則**：不是「絕對不動」，而是「有差異就停下來問」。格式升級、結構改進等使用者可能想採納，但必須由使用者決定。

### 需特別小心的檔案
- `settings.json` — 只做 surgical edit，不整檔替換
- `memory/decisions.md` — 保留高確認數版本，追加缺失段落
- `tools/memory-vector-service/indexer.py` — 可能有本地改進（遞迴掃描、目錄跳過邏輯）
- `workflow/config.json` — 可能已有使用者新增的 `additional_atom_dirs`

### 帳號替換規則
- 路徑中的帳號名 → 替換
- URL / Git remote / 來源備註中的帳號名 → 保留（有意義的參考）
- 不確定時 → 列出讓使用者判斷

### Vector DB 重建陷阱
- Vector Service 啟動時快取 config.json，修改 config 後必須先 `/reload` 再 `/index`
- 若 service 未啟動，先啟動：`python ~/.claude/tools/memory-vector-service/service.py &`
- 驗證時確認所有 `additional_atom_dirs` 的專案層都有被索引
