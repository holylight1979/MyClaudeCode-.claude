# 原子記憶系統規格 v2.11

> Atomic Memory System V2.11 Specification
> 適用於 Claude Code 跨 session 知識管理。
> V2：Hybrid RECALL — Keyword Trigger + Vector Semantic Search + Local LLM
> V2.1：Write Gate + Schema 擴展 + Intent Ranking + Conflict Detection + Audit Trail
> V2.4：回應知識捕獲（SessionEnd 萃取）+ 跨 Session 鞏固
> V2.9：Project-Aliases + Related-Edge Spreading + ACT-R Activation Scoring + Blind-Spot Reporter
> V2.11：精簡（砍逐輪萃取/因果圖/自動晉升）+ 品質（衝突偵測/反思校準）+ 模組化（.claude/rules/ + Context Budget）

---

## 一、系統概述

原子記憶系統將 AI 助手的跨 session 知識組織為**兩層結構**：

| 層 | 路徑 | 用途 |
|----|------|------|
| 全域層 | `~/.claude/memory/` | 跨專案共用知識（使用者偏好、通用決策） |
| 專案層 | `~/.claude/projects/{slug}/memory/` | 專案綁定知識（架構、坑點、待辦） |

每層包含：
- `MEMORY.md` — 索引表 + 高頻事實（≤30 行）
- 多個 atom 檔 — 獨立主題的知識單元（≤200 行/檔）
- `_distant/` — 遙遠記憶區（已淘汰但不刪除的 atom）

> ⚠️ 本文件為記憶系統的開發規格。文中的數字（行數上限、token 預算等）為預設建議值，可依使用場景調整，非硬限制。

---

## 二、決策記憶三層分類 [固]/[觀]/[臨]

### 2.1 分類定義

| 符號 | 名稱 | 定義 | 引用行為 |
|------|------|------|---------|
| `[固]` | 固定記憶 | 跨多次對談確認，長期有效 | 直接引用，不需確認 |
| `[觀]` | 觀察記憶 | 已決策但可能演化 | 簡短確認「X 仍適用？」 |
| `[臨]` | 臨時記憶 | 單次決策，下次觸及時應重新評估 | 明確確認「上次你決定 X，這次也這樣嗎？」 |

### 2.2 建立規則

| 觸發情境 | 初始等級 | 範例 |
|----------|---------|------|
| 使用者說「記住」「以後都這樣」「永遠不要」 | `[固]` | "Handler 以後都用傳統寫法" |
| 使用者做取捨（選 A 不選 B） | `[臨]` | "先不修 SQL injection" |
| 使用者糾正 AI 行為 | `[觀]` | "不要主動重構周圍程式碼" |
| AI 工作中發現陷阱/坑點 | `[觀]` | "AreaFacade 共享集合會重入" |
| 同 session 重複出現 3+ 次的模式 | `[觀]`（建議） | 使用者總是要求最小變動 |
| 預設（無法歸類） | `[臨]` | — |

### 2.3 晉升條件

| 路徑 | 條件 | 機制 |
|------|------|------|
| `[臨]`→`[觀]` | 2+ sessions 引用 或 使用者再次確認 | AI 主動問確認 |
| `[觀]`→`[固]` | 4+ sessions 未被推翻 或 使用者明確永久化 | 記錄演化日誌 |
| `[臨]`→`[固]` | 使用者對既有 `[臨]` 說「以後都這樣」 | 跳級晉升 |

晉升由 `Confirmations` 計數驅動：每次 session 引用且未被推翻時 +1。

### 2.4 降級與遙遠記憶

預設移入**遙遠記憶區**（`_distant/`），按 `年_月` 歸檔。`--purge` 永久刪除。

#### 觸發條件

| 條件 | 動作 | --enforce 行為 (v2.1) |
|------|------|----------------------|
| `[臨]` Last-used > 30 天 | 建議移至 `_distant/` | **自動移入** + 寫入演化日誌 |
| `[觀]` Last-used > 60 天 | 確認；無回應則移入 | 標記 `pending-review`，不自動移入 |
| `[固]` 被使用者推翻 | 降為 `[觀]` | 同左 |
| `[固]` Last-used > 90 天 | 報告提醒 | 同左（永不自動淘汰） |
| 使用者明確拒絕 | 移入遙遠記憶 | 同左 |
| TTL 設定且已過期 (v2.1) | 依 confidence 處理 | [臨] 自動移入；[觀][固] 標記 |

#### Type-based 淘汰調整（v2.1 Sprint 3）

`Type` 欄位會調整基礎閾值：`effective_threshold = base_threshold × type_multiplier`

| Type | Multiplier | 效果（以 [臨] 30d 為例） |
|------|-----------|------------------------|
| semantic | 1.0 | 30 天（不變） |
| episodic | 0.8 | 24 天（情節記憶較快淘汰） |
| procedural | 1.5 | 45 天（程序配方更長保留） |

#### 遙遠記憶區結構

```
memory/
  _distant/
    2026_01/
      old-pitfall.md
    2026_02/
      deprecated-decision.md
```

#### 拉回機制

1. `memory-audit.py --search-distant <keyword>` 搜尋遙遠記憶
2. `memory-audit.py --restore <path>` 移回活躍區
3. 拉回後 Confidence 重置為 `[臨]`，重新走晉升流程

### 2.5 演化日誌

每個 atom 底部附加，上限 10 筆。超出時 `--compact-logs` 自動合併最舊 N 筆為摘要行：
`| [合併] | N 筆歷史記錄 (earliest~latest) | auto-compact |`

`enforce_decay()` 新增演化記錄後亦自動觸發壓縮。

```markdown
## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-02-26 | 建立為 [臨] | session:健檢修復 |
| 2026-03-01 | [臨]→[觀] 第2次確認 | session:效能討論 |
| 2026-03-15 | [觀]→[固] 第4次確認 | session:重構評估 |
```

---

## 三、資料夾結構與命名

### 3.1 目錄佈局

```
~/.claude/
  memory/                              # 全域層
    MEMORY.md                          # 索引 (≤30 行)
    {atom-name}.md                     # 活躍 atom
    _distant/                          # 遙遠記憶
      {年}_{月}/
        {atom-name}.md
  tools/
    memory-audit.py                    # 健檢腳本

  projects/{project-slug}/
    memory/                            # 專案層
      MEMORY.md                        # 索引 (≤30 行)
      {atom-name}.md                   # 活躍 atom
      _distant/                        # 遙遠記憶
        {年}_{月}/
          {atom-name}.md
```

### 3.2 Atom 檔案命名慣例

- **小寫 kebab-case**：`architecture.md`, `sgi-pitfalls.md`
- **描述內容領域**，最長 40 字元
- **不加日期前綴**（日期在元資料）
- **可加類別前綴**：`risk-auth.md`, `decision-protobuf.md`

### 3.3 Atom 元資料標準格式

```markdown
# [Atom 標題]

- Scope: [global|project]
- Confidence: [固|觀|臨]
- Type: semantic                 ← v2.1（semantic/episodic/procedural，預設 semantic）
- Trigger: kw1, kw2, kw3
- Last-used: YYYY-MM-DD
- Confirmations: 0
- ReadHits: 5
- Created: YYYY-MM-DD            ← v2.1（首次建立日期）
- TTL: 30d                       ← v2.1 [DEPRECATED-unused] 可選，無 atom 使用
- Expires-at: YYYY-MM-DD         ← v2.1 [DEPRECATED-unused] 可選，無 atom 使用
- Privacy: public                ← v2.1 [DEPRECATED-unused] 可選，無程式讀取
- Tags: pitfall, architecture    ← v2.1（可選，分類標籤）
- Related: other-atom-name       ← v2.1（可選，關聯 atom）
- Supersedes: old-atom-name      ← v2.1 [DEPRECATED-unused] 可選，無 atom 使用
- Quality: 0.85                  ← v2.1（Write Gate 品質評分，0-1）

## 知識

- [固] 事實 1
- [觀] 事實 2

## 行動

- 觸及時的執行指引

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
```

**必要欄位**：Scope, Confidence, Trigger, Last-used
**v2.1 可選欄位**（不存在時使用預設值，既有 atom 零修改即可運作）：

| 欄位 | 預設值 | 說明 |
|------|--------|------|
| Type | semantic | semantic/episodic/procedural |
| Created | （空） | 首次建立日期 |
| Confirmations | 0 | session 引用且未推翻時自動 +1 |
| TTL | null | 自訂存活期，null = 由 confidence 閾值決定 |
| Expires-at | null | 自動計算或手動設定 |
| Privacy | public | public/internal/sensitive |
| Tags | （空） | 分類標籤 |
| Related | （空） | 關聯 atom 名稱 |
| Supersedes | （空） | 取代的舊 atom 名稱 |
| Quality | （空） | Write Gate 品質評分（0-1） |

**必要區段**：知識, 行動
**可選區段**：演化日誌

### 3.4 MEMORY.md 索引格式

```markdown
# Atom Index — {層名稱}

> Session 啟動時先讀此索引。比對 Trigger → Read 對應 atom。

| Atom | Path | Trigger | Confidence |
|------|------|---------|------------|
| {name} | memory/{name}.md | kw1, kw2 | [固] |

---

## 高頻事實

- [固] 事實 1（5~7 條最常用事實）
```

**硬限制**：≤30 行。超過時必須將細節移至 atom 檔。

### 3.5 Trigger 關鍵詞設計原則

- **中英混合**：中文操作語 + 英文技術術語
- **每 atom 3~8 個**：太少=永遠不觸發，太多=過度觸發
- **避免同層重疊**：兩 atom 共用關鍵字→合併或區分
- **含症狀詞**：`crash`, `失敗`, `找不到`（錯誤情境也能觸發）
- **含動作詞**：`建置`, `deploy`, `修復`（操作意圖觸發）

### 3.6 記憶路徑碎片化處理

Claude Code auto-memory 路徑由工作目錄自動生成。同一邏輯專案可能產生多份 memory。

**原則**：
1. 每個邏輯專案指定唯一**主記憶路徑**
2. 其他路徑的 MEMORY.md 開頭加 pointer：
   ```markdown
   > ⚠️ 此專案主記憶位於 `~/.claude/projects/{主路徑}/memory/`，本路徑為副本。
   ```
3. 健檢腳本偵測重複（比對標題 + Trigger），報告疑似重複並建議合併

---

## 四、落地運作流程

### 4.1 Session 啟動（載入）

```
1. Read 全域 MEMORY.md
   └→ 取得 Atom Index 表 + 高頻事實

2. Read 專案 MEMORY.md
   └→ 取得 Atom Index 表 + 高頻事實

3. 比對使用者第一個訊息 vs 兩層 Trigger 關鍵詞
   └→ 命中 → Read 對應 atom 檔
   └→ 未命中 → 不載入（省 token）

4. Supersedes 過濾 (v2.1 Sprint 3)
   └→ 若 atom A 的 Supersedes 含 B，且兩者同時命中，僅載入 A
   └→ B 不重複載入，避免過時知識干擾
```

### 4.2 對話中（觸發與累積）

```
每次使用者訊息：

  1. 掃描訊息 vs 未載入 atom 的 Trigger
     └→ 新命中 → Read 該 atom

  2. 引用已載入 atom 知識時：
     └→ [固] → 直接引用
     └→ [觀] → 簡短確認
     └→ [臨] → 明確確認

  3. 產生新知識時：
     └→ 暫存在 session context
     └→ 記錄：內容 + 分類依據 + 觸發情境
```

### 4.3 Session 結束（同步寫入）

```
完成有意義修改後，主動提出同步建議：

1. 彙整 session 新知識
   └→ 歸類到既有 atom 或建立新 atom
   └→ 標記 [固]/[觀]/[臨]

2. 更新 atom 檔
   └→ 新知識 → 加入知識段落
   └→ 已引用 atom → Last-used + Confirmations +1
   └→ 演化日誌 → 追加記錄

3. 更新 MEMORY.md 索引（若有新增/移除 atom）

4. 檢查淘汰條件 → 超期 atom 提醒移入遙遠記憶

5. 版控提交
```

### 4.4 定期健檢（手動觸發）

```
python memory-audit.py
  → 格式合規檢查
  → 過期分析 + 晉升/降級建議
  → 索引一致性驗證
  → 重複偵測（碎片化）
  → 遙遠記憶掃描
  → 產出報告
```

---

## 五、健檢腳本規格

### 5.1 檔案

`~/.claude/tools/memory-audit.py` — Python 3.8+，零外部依賴。

### 5.2 CLI

```
python memory-audit.py [OPTIONS]

掃描與報告：
  (預設)                    掃描全部層，產出 Markdown 報告
  --global-only             只掃描全域層
  --project PATH            指定專案 memory 目錄
  --json                    JSON 格式輸出
  --verbose                 含逐 atom 詳細資訊

自動淘汰（v2.1）：
  --enforce                 自動執行淘汰：[臨]>30d 移入 _distant/，[觀]>60d 標記 pending-review
                           （閾值依 Type multiplier 調整：semantic×1.0, episodic×0.8, procedural×1.5）
  --dry-run                 搭配 --enforce/--compact-logs/--delete，只報告不執行

刪除傳播（v2.1 Sprint 2）：
  --delete <name>           刪除 atom（移入 _distant/），全鏈清除 LanceDB + Related 引用 + MEMORY.md
  --purge <name>            永久刪除 atom（不移入 _distant/），全鏈清除
  --layer <name>            搭配 --delete/--purge 指定層（default: global）

演化日誌壓縮（v2.1 Sprint 3）：
  --compact-logs            壓縮演化日誌：超過 10 筆合併為摘要

遙遠記憶操作：
  --search-distant <kw>     搜尋遙遠記憶區
  --restore <path>          從遙遠記憶拉回活躍區
  --move-distant <path>     手動移入遙遠記憶
```

### 5.3 檢查項目

| 類別 | 檢查 | 閾值 |
|------|------|------|
| 格式合規 | 必要元資料（Scope/Confidence/Trigger/Last-used） | 缺一報錯 |
| 格式合規 | 必要區段（知識/行動） | 缺一報錯 |
| 格式合規 | Confidence 值合法 | 必須為 [固]/[觀]/[臨] |
| 格式合規 | MEMORY.md 行數 | ≤30 行 |
| 格式合規 | Atom 檔行數 | ≤200 行 |
| 格式合規 | Trigger 數量 | 3~8 個 |
| 過期分析 | [臨] Last-used | >30 天建議移入遙遠記憶 |
| 過期分析 | [觀] Last-used | >60 天建議確認 |
| 過期分析 | [固] Last-used | >90 天列入提醒 |
| 晉升建議 | [臨] Confirmations | ≥2 建議晉升為 [觀] |
| 晉升建議 | [觀] Confirmations | ≥4 建議晉升為 [固] |
| 索引一致 | 索引 ↔ 檔案交叉比對 | 零 mismatch |
| 碎片偵測 | 跨路徑 atom 標題+Trigger 相似度 | 報告疑似重複 |

### 5.4 閾值常數

```python
STALENESS_THRESHOLDS = {'[固]': 90, '[觀]': 60, '[臨]': 30}
TYPE_DECAY_MULTIPLIER = {'semantic': 1.0, 'episodic': 0.8, 'procedural': 1.5}  # Sprint 3
PROMOTION_THRESHOLDS = {'[臨]': 2, '[觀]': 4}
INDEX_MAX_LINES = 30
ATOM_MAX_LINES = 200
TRIGGER_RANGE = (3, 8)
```

---

## 六、Write Gate（v2.1 新增）

### 6.1 概述

Write Gate 在新知識寫入前進行品質評估與去重檢查，降低噪音累積。

### 6.2 決策流

```
新知寫入決策流：
┌─ 使用者說「記住」「以後都這樣」
│  └→ 直接 Add，[固]，quality=1.0
│
├─ AI 偵測到坑點/陷阱
│  └→ Add，[觀]，quality=0.7
│
└─ 其他新知識
   │
   ├─ Dedup 檢查：embed → search existing (score>0.80)
   │  ├─ >0.95 → Skip（完全重複）
   │  ├─ 0.80-0.95 → 建議 Update 既有 atom
   │  └─ <0.80 → 進入品質評分
   │
   └─ Quality Score（rule-based）：
      ├─ ≥0.5 → Add
      ├─ 0.3-0.5 → Ask User 確認
      └─ <0.3 → Skip（log to audit trail）
```

### 6.3 Quality Score 計算

| 條件 | 分數 |
|------|------|
| 長度 >20 chars | +0.15 |
| 長度 >50 chars | +0.10 |
| 技術術語 ≥2 | +0.15 |
| 使用者明確觸發 | +0.35 |
| 含具體值（版本號/路徑/設定值） | +0.15 |
| 非暫時性（不含 timeout/retry/暫時） | +0.10 |

### 6.4 工具

`~/.claude/tools/memory-write-gate.py` — CLI 入口，搭配 session-end 同步使用。

```
python memory-write-gate.py --content "知識文字" [--classification "[觀]"] [--trigger-context "..."]
  → 輸出 JSON：{action, quality_score, reason, dedup_match?}
```

### 6.5 設定

`~/.claude/workflow/config.json` 的 `write_gate` 區塊：

```json
{
  "enabled": true,
  "auto_threshold": 0.5,
  "ask_threshold": 0.3,
  "dedup_score": 0.80,
  "skip_on_explicit_user": true
}
```

---

## 七、向量搜尋層（RAG）

### 7.1 概述

向量搜尋作為 keyword trigger 的**補充層**（非替換），提升語意相關但用詞不同的 atom 觸發率。

架構：**Hybrid RECALL** — keyword matching（確定性、10ms）+ semantic search（概率性、200-500ms）並行。

### 7.2 元件

| 元件 | 位置 | 用途 |
|------|------|------|
| Memory Vector Service | `tools/memory-vector-service/service.py` | HTTP daemon @ port 3849 |
| indexer.py | 同目錄 | 段落級 atom chunking + embedding + LanceDB |
| searcher.py | 同目錄 | 語意搜尋 + ranked search (v2.1) |
| reranker.py | 同目錄 | LLM re-ranking / query rewrite / 知識萃取 |
| rag-engine.py | `tools/rag-engine.py` | CLI 入口 |
| LanceDB | `memory/_vectordb/` | 向量持久化存儲 |

### 7.3 Embedding 模型（雙軌）

| 後端 | 模型 | 用途 |
|------|------|------|
| Ollama | `qwen3-embedding` | 主力（MTEB 多語言 #1） |
| sentence-transformers | `BAAI/bge-m3` | Fallback（Ollama 未啟動時） |

### 7.4 索引策略

- **段落級切割**：每個 `- ` bullet point 為一個 chunk（向量化單位）
- 元資料區（Scope/Confidence/Trigger）和演化日誌不索引
- 每個 chunk 攜帶 metadata：atom_name, section, confidence, layer, file_hash, last_used, confirmations, atom_type, tags
- 增量索引：比對 file_hash，只重新索引有變動的 atom
- PostToolUse hook 自動觸發增量索引
- SessionEnd hook 自動觸發增量索引（若 session 中有 atom 修改）(v2.1 Sprint 3)

### 7.5 搜尋流程

```
UserPromptSubmit (3s timeout)
├─ keyword match (existing, ~10ms)
├─ intent classification (rule-based, ~1ms) (v2.1 Sprint 2)
├─ HTTP → Vector Service /search/ranked (~200-500ms, timeout 2s) (v2.1 Sprint 2)
│   └─ FinalScore = 0.45×Semantic + 0.15×Recency + 0.20×IntentBoost
│                    + 0.10×Confidence + 0.10×(Confirmation + TypeBonus)
├─ Project-Aliases match: aliases 命中 → 注入專案 MEMORY.md 全文 (v2.9)
├─ merge & deduplicate (keyword 優先)
├─ Supersedes filter: 被取代的 atom 不載入 (v2.1 Sprint 3)
├─ ACT-R activation sort: 按 B_i = ln(Σ t_k^{-0.5}) 降序排列 (v2.9)
├─ load atoms within token budget
│   └─ Token budget: len(prompt)<50 → 1500t; <200 → 3000t; else → 5000t
│   └─ Per-atom cost: len(content) // 4 (char-to-token estimate) (v2.1 Sprint 3)
├─ Related-Edge Spreading: 沿 Related 邊擴散 depth=1，預算內載入 (v2.9)
└─ Blind-Spot Reporter: 三重空判斷 → 注入盲點提醒 (v2.9)
```

#### Intent 分類器（v2.1 Sprint 2）

```python
INTENT_PATTERNS = {
    "debug":  ["crash","error","bug","失敗","壞","exception","為什麼","why"],
    "build":  ["build","deploy","建置","部署","安裝","install","啟動","setup","config"],
    "design": ["設計","架構","design","architecture","重構","refactor","新增"],
    "recall": ["之前","上次","記得","決策","決定","為什麼選"],
}
```

#### Type 意圖加成（v2.1 Sprint 3）

| (atom_type, intent) | bonus |
|---------------------|-------|
| (procedural, build) | +0.05 |
| (procedural, recall) | +0.03 |
| (episodic, recall) | +0.05 |
| (episodic, debug) | +0.03 |

### 7.6 本地 LLM 功能（離線路徑）

| 功能 | 模型 | 觸發 | 延遲 |
|------|------|------|------|
| 查詢改寫 | qwen3:1.7b | `rag-engine.py search --enhanced` | ~2s |
| Re-ranking | qwen3:1.7b | `rag-engine.py search --rerank` | ~4s |
| 知識萃取 | qwen3:1.7b | session 結束同步 | ~3s |

### 7.7 設定

`~/.claude/workflow/config.json` 的 `vector_search` 區塊：

```json
{
  "enabled": true,
  "service_port": 3849,
  "embedding_backend": "ollama",
  "embedding_model": "qwen3-embedding",
  "fallback_backend": "sentence-transformers",
  "fallback_model": "BAAI/bge-m3",
  "ollama_llm_model": "qwen3:1.7b",
  "search_top_k": 5,
  "search_min_score": 0.65,
  "search_timeout_ms": 2000,
  "auto_start_service": true,
  "auto_index_on_change": true
}
```

---

## 八、衝突偵測（v2.1 Sprint 2）

### 8.1 概述

Session-end 同步時 LLM 語意比對新舊知識，偵測矛盾事實。

### 8.2 工具

`~/.claude/tools/memory-conflict-detector.py` — CLI 入口。

```
python memory-conflict-detector.py [--atom X] [--dry-run] [--json]
```

### 8.3 流程

1. 對每個 atom 的知識 bullet，向量搜尋相似度 0.60-0.95 的候選
2. LLM（qwen3:1.7b）分類：**AGREE** / **CONTRADICT** / **EXTEND** / **UNRELATED**
3. CONTRADICT → 報告衝突，建議使用者選擇：
   - 不同 scope → 專案層 override 全域層
   - 同 scope，不同 confidence → 高 confidence 勝
   - 同 scope，同 confidence → 較新 Last-used 勝
4. 所有結果寫入 audit.log

---

## 九、Audit Trail（v2.1 Sprint 3）

### 9.1 存儲

`~/.claude/memory/_vectordb/audit.log` — JSONL 格式。

### 9.2 記錄格式

```json
{"ts":"2026-03-04T10:00:00","action":"add","atom":"new-pitfall","confidence":"[觀]","quality":0.72}
{"ts":"2026-03-04T10:01:00","action":"conflict_scan","atom_a":"use-chromadb","atom_b":"use-lancedb","classification":"CONTRADICT"}
{"ts":"2026-03-04T10:02:00","action":"decay","atom":"temp-fix","layer":"global","confidence":"[臨]","days_stale":35,"type":"semantic"}
{"ts":"2026-03-04T10:03:00","action":"delete","atom":"sensitive-data","layer":"global"}
{"ts":"2026-03-04T10:04:00","action":"purge","atom":"old-key","layer":"global"}
```

### 9.3 Action 類型

| Action | 來源 | 說明 |
|--------|------|------|
| add | memory-write-gate.py | 新知識通過 Write Gate |
| skip | memory-write-gate.py | 低品質知識被拒絕 |
| decay | memory-audit.py --enforce | 自動淘汰（含 Type 調整資訊） |
| delete | memory-audit.py --delete | 移入 _distant/ + 全鏈清除 |
| purge | memory-audit.py --purge | 永久刪除 + 全鏈清除 |
| conflict_scan | memory-conflict-detector.py | 衝突偵測結果 |

### 9.4 健檢整合

`memory-audit.py` 健檢報告自動讀取 audit.log 並產出 **Audit Trail Summary** 段落：
- Total log entries
- Write Gate adds/skips
- Deletes/Purges
- Conflicts detected
- Decay actions

---

## 十、回應知識捕獲（V2.4→V2.11）

### 10.1 概述

回應知識捕獲管線讓 Claude 的分析產出系統性地轉化為持久記憶。
由本地 LLM（qwen3:1.7b）自動萃取，零雲端 token 開銷。

**V2.11 變更**：廢除逐輪萃取（per-turn extraction），僅保留 SessionEnd 萃取。原因：逐輪萃取延遲 ~1.5s/turn 但品質低，大部分有價值知識在 SessionEnd 全 transcript 掃描時才能捕獲。

### 10.2 SessionEnd 萃取（V2.11）

| 時機 | 輸入 | 上限 | Timeout |
|------|------|------|---------|
| SessionEnd hook（同步） | 全 transcript assistant texts | 20000 chars, 5 items | 10s |

- 去重：前 60 字元匹配（V2.5 起）
- 所有萃取結果一律 `[臨]`

### 10.3 情境感知萃取（V2.11 新增）

根據 session intent 調整萃取 prompt template：

| Intent | 萃取重點 |
|--------|---------|
| build | 建置步驟、配置要點、環境依賴 |
| debug | 錯誤原因、修復方法、陷阱 |
| design | 架構決策、取捨分析、設計模式 |
| recall | 不萃取（純回憶 session） |

### 10.4 跨 Session 觀察（V2.11 新增）

SessionEnd 時對 knowledge_queue 每個 item 做向量搜尋（top_k=5, min_score=0.75），若命中 2+ 不同 session 的 episodic，生成「跨 Session 觀察」段落寫入 episodic atom。

### 10.5 跨 Session 鞏固（V2.11 簡化）

廢除自動晉升 `[臨]`→`[觀]`。改為：
- 命中的 atom 做 `Confirmations +1`（簡單計數）
- 4+ sessions 時在 episodic 中標記「建議晉升」（不自動執行）
- 統一 dedup 閾值為 0.80

### 10.6 兩層分類（Scope × Type）

| 維度 | 值 | 說明 |
|------|-----|------|
| Scope | global / project | 知識適用範圍 |
| Type | factual / procedural / architectural / pitfall / decision / preference | 知識類型（V2.5: 4→6） |

MCP tool `memory_queue_add` 支援 `scope`、`knowledge_type`、`tags` 參數。

### 10.7 設定

`~/.claude/workflow/config.json`：

```json
{
  "response_capture": {
    "enabled": true,
    "per_turn_enabled": false,
    "session_end_max_chars": 20000,
    "session_end_max_items": 5,
    "session_end_timeout_seconds": 10,
    "classification_default": "[臨]"
  },
  "cross_session": {
    "enabled": true,
    "min_score": 0.75,
    "suggest_threshold": 4,
    "timeout_seconds": 5
  }
}
```

---

## 十一、自我迭代（V2.6→V2.11）

### 11.1 概述

記憶系統隨使用演進。**V2.11 精簡**：從 8 條砍到 3 條有實作支撐的核心原則，刪除無法驗證的理論背書。

### 11.2 三條核心原則

1. **品質函數**（執行主體：Hook 自動化）
   確認(+) → Confirmations+1；糾正(−) → 更新規則；無回饋 → 不動作

2. **證據門檻**（執行主體：Claude 決策）
   ≥2 次獨立 session 觀察才建立正式規則，單次只記 [臨]

3. **震盪偵測**（執行主體：Hook 自動化）
   同一 atom 3 session 內改 2+ 次 → 暫停修改，等更多證據

### 11.3 定期檢閱

`_check_periodic_review_due(config)` — SessionStart 檢查 `workflow/last_review_marker.json`。差距 ≥ review_interval（預設 6）則注入提醒。Claude 掃描近期 episodic atoms，收攏重複模式。

### 11.4 分類演進（Claude 責任）

- **觸及 [臨] 決策**：簡短確認 → Confirmations +1
- **Confirmations ≥ 2 的 [臨]**：建議晉升 → [觀]
- **Confirmations ≥ 4 的 [觀]**：建議晉升 → [固]（需使用者確認）
- **使用者推翻**：更新 atom，降級或標記 Supersedes

---

## 十二、Wisdom Engine（V2.8→V2.11）

### 12.1 概述

Wisdom Engine 將知識注入從「Claude 每次重讀 markdown 規則」轉為「code 預運算 → 只注入結論（≤90 tokens）」。小任務零注入，只在需要時出聲。

實作：`hooks/wisdom_engine.py`，由 `workflow-guardian.py` 以 lazy import + graceful fallback 呼叫。

**V2.11 變更**：移除因果圖（冷啟動零邊，維護成本>收益）；情境分類器改為硬規則；反思引擎新增 over_engineering_rate + silence_accuracy。

### 12.2 元件

| 元件 | 路徑 | 用途 |
|------|------|------|
| wisdom_engine.py | `hooks/wisdom_engine.py` | 主引擎 |
| reflection_metrics.json | `memory/wisdom/reflection_metrics.json` | 反思統計（滑動窗口） |
| DESIGN.md | `memory/wisdom/DESIGN.md` | 設計文件 |

### 12.3 情境分類器（硬規則，V2.11）

`classify_situation(prompt_analysis)` — UserPromptSubmit 呼叫。

**2 條硬規則**取代舊版 5 信號加權函數：

| 規則 | 條件 | 結果 |
|------|------|------|
| Rule 1 | `file_count > 2 AND is_feature` | `confirm`（建議先列範圍） |
| Rule 2 | `touches_arch OR file_count > 3` | `plan`（建議 Plan Mode） |
| 其餘 | — | `direct`（零注入） |

### 12.4 反思引擎（強化，V2.11）

滑動窗口統計 + 盲點偵測（accuracy < 70% 且 total ≥ 3）。

**公開函數**：

| 函數 | 呼叫時機 | 說明 |
|------|---------|------|
| `get_reflection_summary()` | SessionStart | 注入盲點提醒（≤2 條） |
| `reflect(state)` | SessionEnd | 更新 first_approach_accuracy 統計 |
| `track_retry(state, file_path)` | PostToolUse | 追蹤同一檔案重複 Edit（retry 信號） |

統計指標：
- `first_approach_accuracy`：分 single_file / multi_file / architecture 三類
- `over_engineering_rate`（V2.11）：追蹤同檔被 Edit 2+ 次的次數（revert 信號）
- `silence_accuracy`（V2.11）：wisdom 未注入時使用者是否糾正（held_back_ok / held_back_missed）
- Bayesian 權重校準（V2.11）：architecture 連續 3+ 失敗 → 提升 arch 敏感度

注入格式：`[自知] multi_file 首次正確率 64% — 跨檔修改建議先確認影響範圍`

### 12.5 品質回饋與成熟度

- **Output Quality Check**（PostToolUse）：偵測同檔跨 session 修改頻率
- **Iteration Metrics**（SessionEnd）：injected_atoms + modified_atoms
- **Oscillation Detection**：同 atom 3 session 改 2+ 次 → 暫停建議
- **Maturity Phase**：learning(<15) → stable(15-50) → mature(>50)

### 12.6 整合點

| Hook | 函數呼叫 | 作用 |
|------|---------|------|
| SessionStart | `get_reflection_summary()` | 盲點提醒注入 |
| UserPromptSubmit | `classify_situation(prompt_analysis)` | 情境建議注入 |
| PostToolUse | `track_retry(state, file_path)` | 追蹤重試次數 + over_engineering_rate |
| SessionEnd | `reflect(state)` | 更新統計 + silence_accuracy |

所有呼叫均有 `if WISDOM_AVAILABLE:` + `try-except` 保護，import 失敗時靜默降級。

---

## 十三、Context Budget（V2.11 新增）

### 13.1 概述

additionalContext 注入量硬上限，防止 atom 膨脹導致 context 爆炸。

### 13.2 機制

- **硬上限**：3000 tokens（以 `len(text) // 4` 估算）
- **觸發點**：`handle_user_prompt_submit()` 組裝 additionalContext 時
- **超額處理**：按 ACT-R activation score 由低到高 truncate atoms
- **標記**：注入末尾附 `[Context budget: {used}/{limit} tokens]`

---

## 十四、衝突偵測（V2.11 新增）

### 14.1 概述

SessionEnd 時對本 session 新寫入/修改的 atoms 做向量搜尋，自動發現潛在知識矛盾。

### 14.2 機制

1. 對修改的 atoms 做向量搜尋，score 0.60-0.95 範圍標記為「潛在衝突」
2. 寫入 episodic atom 的「⚠ 衝突警告」段落
3. 不自動解決，由 Claude 或使用者在後續 session 處理

### 14.3 與 §八 的關係

§八（v2.1 衝突偵測）為獨立 CLI 工具，需手動觸發。§十四 為 hook 自動化，每個 SessionEnd 自動執行。兩者互補。

---

## 十五、Atom 健康度（V2.11 新增）

### 15.1 概述

Atom 間的 Related 引用完整性檢查 + Write Gate 品質基線評估。

### 15.2 檢查項目

- **Related 完整性**：A.Related 含 B → B.Related 必須含 A（雙向一致）
- **懸空引用清除**：Related 指向不存在的 atom → 自動移除
- **Write Gate 基線**：全部活躍 atoms 的 Quality 分數統計

### 15.3 工具

`~/.claude/tools/atom-health-check.py`：

```
python atom-health-check.py --validate-refs    # 檢查 Related 完整性
python atom-health-check.py --stale-check      # 列出 Last-used > 60 天的 atoms
python atom-health-check.py --report           # 生成完整健康報告
```

---

## 十六、記憶檢索強化（V2.9）

### 14.1 Project-Aliases（跨專案身份辨識）

跨專案掃描時，MEMORY.md 的 atom triggers 可能不含專案別名（如 "sgi"）。Project-Aliases 讓專案可定義別名，hook 比對到時注入該專案的 MEMORY.md 全文。

**格式**：在專案層 MEMORY.md 的 header 區加入：

```markdown
# Atom Index — SGI Project
> Project-Aliases: sgi, sgi_server, sgi-server, sgi_client, 遊戲後端
```

**行為**：
- `parse_memory_index()` 額外解析 `> Project-Aliases:` 行
- 跨專案掃描時先比對 aliases → 命中則注入 MEMORY.md 全文 + 逐 atom 比對 triggers
- 注入標記：`[Guardian:AliasMatch] {project} matched via alias`

### 14.2 Related-Edge Spreading（多跳檢索）

atom 被觸發後，沿 `Related` 欄位擴散 1 跳（可配置 depth），帶出語意相關但未被 keyword/vector 直接命中的 atoms。

**函數**：`spread_related(matched_atoms, all_atoms, already_injected, max_depth=1)`

**行為**：
- BFS 搜尋，解析 `- Related: atom1, atom2` 欄位
- `visited` 集合避免重複（含已注入 + 已匹配的 atoms）
- 回傳 `(AtomEntry, Path)` 元組列表
- Token 控制：Related 帶出的 atoms 排在主匹配之後，受 token budget 限制
- 預算不足時降級為摘要（首行）
- 注入標記：atom 名稱後附 `(related)`

### 14.3 ACT-R Activation Scoring（時間加權排序）

以 ACT-R 基礎激活公式取代平面 Confirmations 排序，讓近期高頻使用的 atom 優先注入。

**公式**：

```
B_i = ln( Σ_{k=1}^{n} t_k^{-0.5} )
```

其中 `t_k` = 距離第 k 次存取的秒數。

**實作**：
- `compute_activation(atom_name, atom_dir)` — 讀取 `{atom_name}.access.json`
- Access log 格式：`{"timestamps": [1710000000.0, ...]}`，保留最近 50 筆
- atom 被注入時自動追加 timestamp（`time.time()`）
- 無 access log 時回傳 `-10.0`（最低優先）
- 匹配的 atoms 按 activation score 降序排列後載入

**Access log 管理**：
- 檔案位置：與 atom 同目錄，`{atom_name}.access.json`
- 滑動窗口：保留最近 50 筆 timestamps
- 不進 git（.gitignore）

### 14.4 Blind-Spot Reporter（盲點報告）

當 prompt 未命中任何 atom（keyword + vector + alias 全空）時，主動告知 LLM 存在知識盲點。

**觸發條件**：三重空判斷

```python
if not matched_with_dir and not newly_injected and not alias_injected_projects:
    # 觸發 BlindSpot 報告
```

**注入格式**：

```
[Guardian:BlindSpot] 未找到與 "{prompt前50字}" 相關的記憶 atom。建議 LLM 主動搜尋檔案或詢問使用者。
```

**設計理念**：承認偏差存在（末那識警示），不假裝全知。

---

## 十七、版本紀錄

| 版本 | 日期 | 變更 |
|------|------|------|
| 1.0 | 2026-03-02 | 初版：三層分類 + 資料夾結構 + 健檢腳本規格 |
| 1.1 | 2026-03-03 | 新增 §七 向量搜尋層（RAG）規格 |
| 2.0 | 2026-03-03 | **原子記憶 V2**：Hybrid RECALL 實作完成（keyword + vector + LLM） |
| 2.1 | 2026-03-04 | **V2.1 Sprint 1**：Schema 擴展（Type/TTL/Tags/Related/Supersedes/Quality）、Write Gate §六、--enforce 自動淘汰、Confirmations 自動遞增 |
| 2.1.2 | 2026-03-04 | **V2.1 Sprint 2**：Intent classifier、ranked search、conflict detection、delete propagation |
| 2.1.3 | 2026-03-04 | **V2.1 Sprint 3**：Type decay multipliers、Supersedes loading、evolution compaction、token budget、session-end index、audit trail |
| 2.4 | 2026-03-05 | **V2.4 Phase 1+2**：回應知識捕獲（逐輪+SessionEnd 本地 LLM 萃取）、兩層分類（Scope×Type） |
| 2.4.3 | 2026-03-05 | **V2.4 Phase 3**：跨 Session 鞏固（向量比對自動晉升 [臨]→[觀]、建議晉升 [觀]→[固]） |
| 2.6 | 2026-03-10 | **V2.6 自我迭代**：8 條核心規則 + 定期檢閱 + 分類演進（§十一） |
| 2.7 | 2026-03-10 | **V2.7 品質回饋**：output quality check + iteration metrics + oscillation detection + maturity phase（§十二） |
| 2.8 | 2026-03-11 | **V2.8 Wisdom Engine**：因果圖（BFS depth=2）+ 情境分類器（加權評分）+ 反思引擎（滑動窗口統計）（§十三） |
| 2.9 | 2026-03-11 | **V2.9 記憶檢索強化**：Project-Aliases + Related-Edge Spreading + ACT-R Activation Scoring + Blind-Spot Reporter（§十六） |
| 2.11 | 2026-03-13 | **V2.11 精簡+品質+模組化**：砍逐輪萃取→僅 SessionEnd（§十）、砍因果圖→硬規則情境分類（§十二）、自我迭代 8→3 條（§十一）、廢除自動晉升→簡單計數（§十）、Context Budget 3000t（§十三）、衝突偵測自動化（§十四）、反思校準 over_engineering+silence_accuracy（§十二）、Atom 健康度（§十五）、.claude/rules/ 模組化、環境清理 300+ 檔 |
