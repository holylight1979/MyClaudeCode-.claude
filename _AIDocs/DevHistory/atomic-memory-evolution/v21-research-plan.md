# 原子記憶 v2.1 缺陷研究與修補計畫

> 研究型產出 — 不涉及程式碼修改，產出為完整分析報告與可落地方案設計

---

## J. 一頁版決策摘要（Executive Summary）

Atomic Memory v2 已成功建立 keyword + vector hybrid recall 的本地記憶系統核心，但在 **7 個面向** 存在結構性弱點：

| # | 缺陷 | 嚴重度 | v2.1 核心對策 | 參考系統 |
|---|------|--------|-------------|---------|
| 1 | Atom 碎片化，語意脈絡斷裂 | 高 | `Related` + `Supersedes` 關聯欄位 | Zep Graphiti, Mem0 Graph |
| 2 | TTL/Decay 無強制力 | 高 | `--enforce` 模式 + TTL 欄位 | Zep temporal validity, ACT-R |
| 3 | 衝突記憶無仲裁 | 高 | LLM 語意比對 + A.U.D.N. 決策流 | Mem0 A.U.D.N., Zep invalidation |
| 4 | 寫入門檻過低 | 中 | Write Gate（quality score + dedup） | Mem0 A.U.D.N., MemGPT self-edit |
| 5 | 檢索無任務意圖感知 | 中 | Intent 分類器 + 加權排序公式 | LlamaIndex priority, SK hybrid |
| 6 | 無多層記憶分工 | 中 | `Type`: semantic/episodic/procedural | LlamaIndex blocks, 認知科學 |
| 7 | 隱私刪除不完整 | 高 | Delete propagation + Privacy 強制 | Mem0 DELETE, LangGraph RemoveMessage |

**設計原則**：
- 所有新欄位 **optional**，既有 .md atom 零修改即可運作
- 維持 **local-first**（無雲端依賴）
- LLM 呼叫走 **非即時路徑**（session-end 同步），不增加 hook 延遲
- 在 GTX 1050 Ti + qwen3:1.7b 硬體限制下可執行

**目標**：系統平均評分從 2.0 提升至 3.5+（5 分制）

---

## A. 可行性簡報

### A.1 可用資料來源

| 來源 | 類型 | 已取得 |
|------|------|--------|
| 現有 codebase（6 個 Python 檔 + 4 atom + SPEC） | 第一手 | ✅ 完整讀取 |
| MemGPT/Letta GitHub + docs（agent-driven write gate） | 開源 | ✅ |
| Zep Graphiti 論文 arXiv:2501.13956 + docs | 開源+學術 | ✅ |
| Mem0 論文 arXiv:2504.19413 + GitHub（A.U.D.N.） | 開源+學術 | ✅ |
| LangGraph docs（Reducers, RemoveMessage） | 開源 | ✅ |
| LlamaIndex Memory docs（Blocks, Priority） | 開源 | ✅ |
| Semantic Kernel docs（Hybrid Search, RRF） | 開源 | ✅ |
| ACT-R 記憶衰退模型 + FadeMem/FOREVER 論文 | 學術 | ✅ |
| Vector DB 刪除模式（Pinecone/Weaviate/Qdrant） | 公開文件 | ✅ |
| Hybrid retrieval + reranking best practices（2025-2026） | 技術文章 | ✅ |

### A.2 可量化比較指標

| 指標 | 現況基準 | v2.1 目標 |
|------|---------|----------|
| Atom 觸發準確率（precision@5） | 未量測 | >0.7（50 query 手動測試集） |
| 寫入噪音率 | 估計 >30% | <15% |
| 衝突事實存活時間 | 無偵測（∞） | <1 session |
| 過期 [臨] atom 清理率 | 0%（純建議） | 90%（自動淘汰） |
| 檢索延遲 P99（hook 內） | ~500ms | <600ms（加入 intent 計算） |
| 隱私刪除完整性 | 部分（向量殘留） | 100% 全鏈清除 |

### A.3 風險與盲區

| 風險 | 衝擊 | 緩解 |
|------|------|------|
| GTX 1050 Ti VRAM 不足跑 LLM write gate | 高 | write gate 用 qwen3:1.7b，僅在 session-end 同步時執行 |
| Atom 格式向後不相容 | 高 | 所有新欄位 optional，解析器 graceful fallback |
| 衝突偵測誤判（false positive） | 中 | 先 log 建議，不自動合併，需使用者確認 |
| Decay 自動淘汰誤刪重要記憶 | 高 | [固] 永不自動淘汰；[臨] 淘汰前寫入演化日誌 |
| 多 session 並行寫入衝突 | 低 | Claude Code 通常單 session，file lock + 日誌 |

### A.4 研究邊界

- **不做**：自建 knowledge graph DB（過度工程，用 markdown 欄位模擬）
- **不做**：分散式記憶同步（單機限定）
- **不做**：替換 LanceDB（已穩定運作）
- **做**：在現有 .md 格式 + LanceDB + qwen3 stack 上增量改善

---

## B. 詳細工作計畫（WBS）

### Phase 1: Foundation（Week 1-2）

| # | 工作項目 | 產出 | 估計 | 優先級 | 前置 |
|---|---------|------|------|--------|------|
| 1.1 | Schema v2.1 欄位定義 | SPEC 更新 | 2h | P0 | -- |
| 1.2 | Atom 解析器升級（memory-audit.py + workflow-guardian.py） | 程式碼 | 4h | P0 | 1.1 |
| 1.3 | MEMORY.md 索引格式擴展（新增 Type 欄位） | 格式文件 | 1h | P0 | 1.1 |
| 1.4 | Write Gate 實作（dedup + quality score） | memory-write-gate.py | 6h | P0 | 1.2 |
| 1.5 | Conflict Detection 模組 | conflict-detector.py | 4h | P1 | 1.4 |
| 1.6 | 向後相容測試（既有 4 global atom 不壞） | 測試報告 | 2h | P0 | 1.2 |

### Phase 2: Retrieval & Decay（Week 2-3）

| # | 工作項目 | 產出 | 估計 | 優先級 | 前置 |
|---|---------|------|------|--------|------|
| 2.1 | Task-Intent 分類器（rule-based） | intent-classifier | 3h | P1 | -- |
| 2.2 | Retrieval Ranking 公式實作 | searcher.py 升級 | 4h | P1 | 2.1 |
| 2.3 | Automated Decay `--enforce` 模式 | memory-audit.py | 3h | P1 | 1.2 |
| 2.4 | Confirmations 自動遞增 | workflow-guardian.py | 2h | P0 | 1.2 |
| 2.5 | Delete Propagation（atom + vector + index） | memory-audit.py | 3h | P1 | -- |

### Phase 3: Layering & Polish（Week 3-4）

| # | 工作項目 | 產出 | 估計 | 優先級 | 前置 |
|---|---------|------|------|--------|------|
| 3.1 | Three-layer type 系統 | 格式 + 解析 | 3h | P2 | 1.1 |
| 3.2 | Atom Cluster 關聯（supersedes + related） | 解析 + 載入邏輯 | 3h | P2 | 1.2 |
| 3.3 | Evolution log 自動合併 | memory-audit.py | 2h | P2 | 1.2 |
| 3.4 | Token budget 改為估算 | workflow-guardian.py | 2h | P2 | -- |
| 3.5 | Session-end vector index 重建 | workflow-guardian.py | 1h | P1 | -- |
| 3.6 | SPEC v2.1 文件完整更新 | SPEC md | 2h | P0 | all |
| 3.7 | Audit trail + 健檢報告升級 | memory-audit.py | 2h | P2 | 3.2 |

### 假設與決策點

| 決策點 | 建議 | 備註 |
|--------|------|------|
| Write Gate 全自動拒絕 vs 提示確認 | 提示確認 | 避免誤丟重要知識 |
| Conflict Detection 自動合併 vs 僅報告 | 僅報告+建議 | 降低 false positive 風險 |
| Decay 是否包含 [觀] 自動淘汰 | [臨] 自動，[觀] 提醒不自動 | 保護中期知識 |

---

## C. 七大缺陷分析

### C1. Atoms 過度碎片化，Context 斷裂

**問題**：每個 atom 是獨立 .md 檔，無 `supersedes`/`related`/`parent` 關聯欄位。一個決策跨越多個 atom 時，只有 trigger 命中的那一個被載入，相關上下文丟失。

**失敗案例**：
1. 使用者問「向量搜尋為什麼不用 ChromaDB？」→ trigger 命中 `rag-vector-plan.md`（107 行），但若 token budget 不夠只載入摘要，「ChromaDB → pydantic v1 衝突 → 改 LanceDB」的完整決策鏈被截斷。
2. 使用者問「Guardian 的原子記憶整合怎麼做？」→ trigger 命中 `decisions.md`，但 atom injection 程式碼邏輯在 `rag-vector-plan.md` 的 Vector Service 段落，無關聯欄位引導。

**對照**：
- **Zep Graphiti**：temporal knowledge graph，每個 fact 是 node，edge 連接相關 facts。查詢沿 edge 展開鄰近知識。
- **Mem0**：Graph layer 建立 entity 間關係，Update 操作自動合併相關記憶。

**v2.1 方案**：新增 `Related` + `Supersedes` 可選欄位：
```markdown
- Related: rag-vector-plan, decisions
- Supersedes: old-chromadb-plan
```
載入 atom A 時，若 A.Related 含 B 且 B 未被載入，budget 允許下自動載入 B 摘要行。

---

### C2. TTL/Decay 無強制力

**問題**：`memory-audit.py` 只產出報告建議移入 `_distant/`，不自動執行。Spec 定義 [臨]30d/[觀]60d/[固]90d 閾值，實際過期 atom 永遠留在活躍區。

**失敗案例**：
1. 3 個月前的 [臨] `temp-fix-sql.md` 仍佔 MEMORY.md 索引，trigger 比對浪費計算，語意搜尋可能 false positive。
2. 累積 20 個 [臨] atom，使用者從不手動跑 audit。活躍池膨脹，trigger 精準度下降。

**對照**：
- **Zep**：`valid_at`/`invalid_at` 時間戳，過期 fact 自動標記 invalid，不再被檢索。
- **ACT-R**：記憶強度指數衰退 `S(t) = B - d·ln(t)`，低於閾值即「遺忘」。

**v2.1 方案**：
- `memory-audit.py --enforce`：[臨]>30d 自動移入 `_distant/`；[觀]>60d 標記 `pending-review`；[固] 永不自動淘汰
- 新增 `TTL` + `Expires-at` 可選欄位
- 建議搭配 Task Scheduler 每日自動執行

---

### C3. 衝突記憶無仲裁

**問題**：兩個 atom 記錄互相矛盾事實（atom A: "用 ChromaDB"，atom B: "ChromaDB 不相容改 LanceDB"），無偵測或解決機制。Last-write-wins 使舊事實永不被更正。

**失敗案例**：
1. Session 1 記錄「protobuf 用 v3 語法」。Session 5 另一 atom 記錄「改用 flatbuffers」。兩者都是 [觀]，trigger 都含 "序列化"，AI 隨機載入其一。
2. 全域層「所有專案用 4 spaces」vs 專案層「此專案用 tabs」。無機制標示優先。

**對照**：
- **Zep**：temporal invalidation — 新 fact 設舊 fact 的 `invalid_at`。
- **Mem0**：A.U.D.N. 操作 — LLM 判斷 Add/Update/Delete/No-op。

**v2.1 方案**：session-end 同步時 LLM 比對新舊知識，分類為 AGREE/CONTRADICT/EXTEND/UNRELATED。CONTRADICT → 報告衝突，建議使用者選擇。專案層 > 全域層；高 confidence > 低 confidence；新 > 舊。

---

### C4. 寫入門檻過低，噪音累積

**問題**：任何 session 可建立 atom，無品質門檻、dedup 檢查。`memory_queue_add` 直接寫入。Confirmations 從未被自動遞增（spec 2.3 說「引用且未被推翻時 +1」，但 guardian 只更新 Last-used）。

**失敗案例**：
1. AI 遇到暫時性 error「pip install timeout」記為 [臨]。偶發問題不值得佔空間，但無門檻阻止。
2. 連續 3 session 觸發同一 [臨] atom，Confirmations 應從 0→3 並建議晉升 [觀]，實際一直是 0。

**對照**：
- **Mem0**：A.U.D.N. — 每次寫入前 LLM 決定。No-op 直接丟棄。
- **MemGPT**：LLM self-edit — agent 自行決定哪些值得寫入。

**v2.1 方案**：
- **Write Gate**：quality score ≥ 0.5 → Add；0.3-0.5 → Ask User；< 0.3 → Skip
- **Confirmations 自動遞增**：guardian hook 更新 Last-used 時同步 Confirmations++

---

### C5. 檢索缺乏任務意圖感知

**問題**：檢索只看語意相似度 + keyword trigger。不考慮使用者在做什麼。Debug 時應優先載入 pitfall atom；設計架構時應優先載入 decision atom。

**失敗案例**：
1. 「AreaFacade 的集合為什麼 crash？」→ 語意搜尋回傳「AreaFacade 架構設計」（高相似度），但使用者需要的是「共享集合會重入」pitfall atom。
2. 「設計新的 handler 架構」→ trigger 命中「Handler 禁止 lambda」，但使用者需要整體架構參考。

**對照**：
- **LlamaIndex**：Memory blocks 有 priority，不同場景載入不同 priority 的 blocks。
- **Semantic Kernel**：Hybrid search 用 RRF 融合多路排序。

**v2.1 方案**：rule-based Intent 分類器（zero LLM overhead）+ intent-aware 權重表，debug 場景 pitfall 權重 1.5x，design 場景 architecture 權重 1.5x。

---

### C6. 無多層記憶分工（短期/長期/程序性）

**問題**：所有 atom 只有 [固/觀/臨] 信心分級，但記憶有不同性質：事實性（「LanceDB 用在哪」）、情節性（「上週五 debug socket 的經過」）、程序性（「讀 Excel 要先 --sheets」）。全部混在一起，無法針對不同類型優化淘汰策略。

**失敗案例**：
1. 使用者想回憶「上次怎麼解決 protobuf 衝突？」→ atom 只記錄結論「用 proto3」，解決過程（episodic）丟失。
2. `excel-tools.md` 是 procedural 記憶，但和 `decisions.md` 用完全相同淘汰規則。操作配方低頻但高價值，不應 30 天就淘汰。

**對照**：
- **LlamaIndex**：StaticMemoryBlock / FactExtractionMemoryBlock / VectorMemoryBlock 明確區分。
- **認知科學**：Episodic / Semantic / Procedural 三者有不同編碼、儲存、提取機制。

**v2.1 方案**：新增 `Type` 欄位（semantic/episodic/procedural），不同 type 有差異化淘汰閾值（procedural 更慢淘汰）和檢索權重。

---

### C7. 隱私與刪除性不足

**問題**：Spec 聲明「記憶永不刪除」。刪除 atom 時 LanceDB chunks 仍在，語意搜尋仍可召回「已刪除」知識。其他 atom 引用文字也不清理。Privacy 欄位存在但從未強制。

**失敗案例**：
1. 「刪除含 API key 的 atom」→ atom 移入 `_distant/`，但向量搜尋仍召回含 key 的 chunk。
2. atom A 提到「根據 deprecated-tool.md 的結論...」。deprecated-tool 已 _distant/，但 A 引用仍在。

**對照**：
- **Mem0**：DELETE 同步清除所有存儲層（vector + graph + KV）。
- **LangGraph**：RemoveMessage 按 ID 精確刪除，state 無殘餘。

**v2.1 方案**：
- 完整刪除鏈：LanceDB DELETE → 掃描 Related 引用移除 → MEMORY.md 更新 → incremental re-index
- `--purge` flag 永久刪除（不移 _distant/）
- Privacy 欄位強制：`sensitive` level 不進向量索引全文，存檔時加密

---

## D. 系統對照矩陣

| 維度 | Atomic Memory v2 | MemGPT/Letta | Zep (Graphiti) | Mem0 | LangGraph |
|------|:-----------------|:-------------|:---------------|:-----|:----------|
| **Granularity** | 段落級 chunk，atom ≤200 行，trigger 3-8 kw | Core blocks（定長槽）+ Archival（無限） | Entity→Relation→Fact 三級 | User/Session/Agent 三層，fact 粒度 | Message-level state |
| **Write Gate** | 無。任何 session 自由建立 | Agent 自行決定（LLM 驅動） | 自動萃取 + NER | A.U.D.N.（LLM 分類每筆新資訊） | Reducer 函數 merge |
| **Conflict Resolution** | 無。Last-write-wins | Agent 覆寫（隱式） | Temporal invalidation | DELETE 移除矛盾 + LLM 判斷 | RemoveMessage by ID |
| **TTL/Decay** | 僅報告，不執行。[臨]30/[觀]60/[固]90d | 無文件記載 | valid_at/invalid_at 時間戳 | 依靠 DELETE 清理 | 無 TTL |
| **Retrieval Strategy** | Keyword ~10ms + Vector ~386ms，無 intent | Embedding + core always-in-context | Graph BFS + embedding，<200ms | Graph + Vector + KV hybrid | Thread state query |
| **Layering** | [固/觀/臨] 信心 + 全域/專案兩層 | Core + Archival（2 層） | Entity + Episodic，graph edges 區分 | User/Session/Agent（3 層） | Thread + Checkpoint（2 層） |
| **Privacy/Delete** | 「永不刪除」，_distant/ 歸檔。向量不同步 | 基本刪除 | Entity CRUD，graph+index 同步 | DELETE 全鏈清除 | RemoveMessage，無跨 checkpoint |
| **Observability** | memory-audit.py 手動 + Guardian Dashboard | Agent step 日誌 | Neo4j 查詢 + audit trail | A.U.D.N. logs | LangSmith tracing |

---

## E. 評分表（1-5 分）

| 維度 | Atomic v2 | MemGPT | Zep | Mem0 | LangGraph | **v2.1 目標** |
|------|:---------:|:------:|:---:|:----:|:---------:|:------------:|
| Granularity | 3 | 2 | 5 | 4 | 2 | **4** |
| Write Gate | 1 | 3 | 4 | 5 | 3 | **3** |
| Conflict Resolution | 1 | 2 | 5 | 4 | 3 | **3** |
| TTL/Decay | 2 | 1 | 4 | 2 | 1 | **4** |
| Retrieval Strategy | 3 | 3 | 5 | 4 | 2 | **4** |
| Layering | 2 | 3 | 4 | 4 | 2 | **3** |
| Privacy/Delete | 1 | 2 | 4 | 5 | 3 | **3** |
| Observability | 3 | 2 | 3 | 3 | 5 | **4** |
| **平均** | **2.0** | **2.25** | **4.25** | **3.88** | **2.63** | **3.5** |

---

## F. v2.1 最小可行 Schema（JSON）

```json
{
  "$id": "atomic-memory-v2.1",
  "type": "object",
  "required": ["memory_id", "type", "content", "confidence", "created_at", "last_verified_at", "scope"],
  "properties": {
    "memory_id": {
      "type": "string",
      "description": "全局唯一 ID: {scope}:{atom_name}:{chunk_index}",
      "pattern": "^(global|project:[a-z0-9-]+):[a-z0-9-]+:\\d+$"
    },
    "user_id": {
      "type": "string",
      "default": "local",
      "description": "使用者標識，單機固定 'local'"
    },
    "type": {
      "enum": ["semantic", "episodic", "procedural"],
      "default": "semantic",
      "description": "語意事實 / 情節事件 / 程序配方"
    },
    "content": {
      "type": "object",
      "required": ["text"],
      "properties": {
        "text": { "type": "string" },
        "section": { "type": "string", "description": "知識/行動/陷阱" },
        "action_guidance": { "type": "string" }
      }
    },
    "source": {
      "type": "object",
      "properties": {
        "session_id": { "type": "string" },
        "trigger_context": { "type": "string" },
        "file_path": { "type": "string" },
        "line_number": { "type": "integer" }
      }
    },
    "confidence": {
      "enum": ["[固]", "[觀]", "[臨]"]
    },
    "confirmations": {
      "type": "integer", "minimum": 0, "default": 0
    },
    "created_at": {
      "type": "string", "format": "date"
    },
    "last_verified_at": {
      "type": "string", "format": "date",
      "description": "= Last-used"
    },
    "ttl": {
      "type": ["string", "null"],
      "pattern": "^\\d+[dhm]$",
      "description": "30d / 14d / 60d。null = 由 confidence 決定"
    },
    "expires_at": {
      "type": ["string", "null"],
      "format": "date",
      "default": null
    },
    "supersedes": {
      "type": "array",
      "items": { "type": "string" },
      "default": [],
      "description": "此記憶取代的舊 memory_id"
    },
    "related": {
      "type": "array",
      "items": { "type": "string" },
      "default": [],
      "description": "關聯 atom 名稱（雙向提示）"
    },
    "privacy_level": {
      "enum": ["public", "internal", "sensitive"],
      "default": "public",
      "description": "public=無限制, internal=不索引全文, sensitive=不索引+加密"
    },
    "tags": {
      "type": "array",
      "items": { "type": "string" },
      "default": [],
      "description": "分類標籤（pitfall, architecture, performance…）"
    },
    "scope": {
      "type": "string",
      "pattern": "^(global|project:[a-z0-9-]+)$"
    },
    "quality_score": {
      "type": "number", "minimum": 0, "maximum": 1,
      "description": "Write Gate 品質評分"
    },
    "evolution_log": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "date": { "type": "string", "format": "date" },
          "change": { "type": "string" },
          "source": { "type": "string" }
        }
      },
      "description": "上限 10 筆，超出合併為摘要"
    }
  }
}
```

### Markdown 格式映射（向後相容）

```markdown
# [Atom 標題]

- Scope: global
- Confidence: [固]
- Type: semantic              ← 新增（預設 semantic）
- Trigger: kw1, kw2, kw3
- Last-used: 2026-03-04
- Created: 2026-03-01         ← 新增
- Confirmations: 0
- ReadHits: 3
- TTL: 30d                    ← 新增（可選）
- Expires-at: 2026-04-03      ← 新增（可選）
- Privacy: public              ← 強制化
- Tags: pitfall, architecture  ← 新增（可選）
- Related: rag-vector-plan     ← 新增（可選）
- Supersedes: old-plan         ← 新增（可選）
- Quality: 0.85                ← 新增（Write Gate 寫入）

## 知識
...
## 行動
...
## 演化日誌
...
```

**解析規則**：所有新增欄位若不存在，使用 JSON schema 中的 default 值。**既有 atom 零修改即可運作**。

---

## G. 檢索排序公式

### 綜合公式

```
FinalScore(atom, query) =
    0.45 × SemanticScore
  + 0.15 × RecencyScore
  + 0.20 × IntentBoost
  + 0.10 × ConfidenceScore
  + 0.10 × ConfirmationScore
```

### 各分量

| 分量 | 範圍 | 計算方式 |
|------|------|---------|
| **SemanticScore** | 0–1 | `1.0 - cosine_distance(query_vec, chunk_vec)` |
| **RecencyScore** | 0–1 | `max(0, 1.0 - days_since_last_used / 90)` |
| **IntentBoost** | 0.5–1.5 | rule-based intent → 權重表查表 |
| **ConfidenceScore** | 0–1 | [固]=1.0, [觀]=0.7, [臨]=0.4 |
| **ConfirmationScore** | 0–0.2 | `min(0.2, confirmations × 0.05)` |

### Intent 分類器（rule-based，zero LLM overhead）

```python
INTENT_PATTERNS = {
    "debug":  ["crash","error","bug","失敗","壞","exception","為什麼","why","問題"],
    "build":  ["build","deploy","建置","部署","安裝","install","啟動","setup","config"],
    "design": ["設計","架構","design","architecture","重構","refactor","新增","planning"],
    "recall": ["之前","上次","記得","決策","決定","為什麼選"],
}
```

### Intent 權重表

| Atom section/type | debug | build | design | recall | general |
|-------------------|:-----:|:-----:|:------:|:------:|:-------:|
| 陷阱/pitfall | 1.5 | 1.0 | 0.8 | 1.0 | 1.0 |
| 決策/decision | 0.8 | 1.0 | 1.3 | 1.5 | 1.0 |
| 操作配方/procedural | 0.8 | 1.5 | 0.8 | 0.8 | 1.0 |
| 架構/architecture | 0.7 | 1.0 | 1.5 | 1.0 | 1.0 |
| 偏好/preference | 0.5 | 0.8 | 1.0 | 1.0 | 1.0 |

### 延遲預算（3s hook timeout 內）

| 步驟 | 延遲 | 累計 |
|------|------|------|
| Keyword trigger | ~10ms | 10ms |
| Vector search (warm) | ~386ms | 396ms |
| Intent classify (rule) | ~1ms | 397ms |
| Score computation | ~5ms | 402ms |
| Atom file I/O (5 files) | ~50ms | 452ms |
| **Total** | | **~450ms** ✅ |

---

## H. 治理機制設計

### H1. Write Gate（寫入門檻）

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
   │  ├─ 0.80-0.95 → LLM 判斷：DUPLICATE|EXTEND|CONTRADICT|UNRELATED
   │  └─ <0.80 → 進入品質評分
   │
   └─ Quality Score：
      ├─ ≥0.5 → Add
      ├─ 0.3-0.5 → Ask User 確認
      └─ <0.3 → Skip（log to audit trail）
```

**Quality Score**（rule-based）：
- 長度 >20 chars: +0.15；>50 chars: +0.10
- 技術術語 ≥2: +0.15
- 使用者明確觸發: +0.35
- 包含具體值（版本號/路徑/設定值）: +0.15
- 非暫時性（不含 timeout/retry/暫時）: +0.10

### H2. Dedup（去重）

寫入前向量搜尋 `score > 0.80`：
- 完全重複 (>0.95) → Skip
- 高度相似 (0.80-0.95) → LLM 判斷：DUPLICATE/EXTEND/CONTRADICT/UNRELATED
- 未命中 → Add 新 atom

### H3. Merge（合併）

Update 操作規則：
1. 新知追加到既有 atom 的 `## 知識` 段落末尾
2. Last-used 更新、Confirmations += 1
3. 新知 confidence 高於 atom → atom 晉升
4. atom 超過 200 行 → 拆分為 A + A-ext，Related 互指
5. 演化日誌追加合併記錄

### H4. Conflict Arbitration（衝突仲裁）

```
偵測到矛盾：
├─ 不同 scope → 專案層 override 全域層
├─ 同 scope，不同 confidence → 高 confidence 勝
├─ 同 scope，同 confidence → 較新 Last-used 勝
└─ 無法判斷 → 標記 [衝突待決]，下次觸發時 AI 詢問使用者

所有衝突解決寫入演化日誌 + Supersedes 欄位
```

### H5. Delete Propagation（刪除傳播）

```
刪除 atom X：
1. LanceDB: DELETE WHERE atom_name=X AND layer=L
2. 掃描所有 atom 的 Related → 移除 X 引用
3. 掃描 Supersedes → 若 X supersedes Z，Z 恢復活躍或標記 orphan
4. 更新 MEMORY.md 索引
5. 觸發 incremental re-index
6. 寫入 audit.log
```

`--purge` flag 永久刪除（不移 _distant/）。

### H6. Audit Trail

所有操作記錄到 `~/.claude/memory/_vectordb/audit.log`（JSONL）：
```json
{"ts":"2026-03-04T10:00:00","action":"add","atom":"new-pitfall","confidence":"[觀]","quality":0.72}
{"ts":"2026-03-04T10:01:00","action":"conflict","atom_a":"use-chromadb","atom_b":"use-lancedb","resolution":"supersede"}
{"ts":"2026-03-04T10:02:00","action":"decay","atom":"temp-fix","destination":"_distant/2026_03/"}
{"ts":"2026-03-04T10:03:00","action":"delete","atom":"sensitive-data","purge":true}
```
Log rotation：>10MB 時 rotate，保留最近 3 份。

---

## I. 路線圖

### Sprint 1 — 2 週（Core Fix）

```
W1: Schema v2.1 定義 + 解析器升級 + 向後相容測試 + Confirmations 自動遞增
W2: Write Gate + Automated Decay --enforce
```
**交付**：新 atom 有品質門檻（#4）、[臨] 自動淘汰（#2）、Confirmations 正確追蹤

### Sprint 2 — 1 個月（Retrieval & Conflict）

```
W3: Intent 分類器 + Ranking 公式 + Related/Supersedes 載入
W4: Conflict Detection + Delete Propagation + Privacy 強制
```
**交付**：intent-aware 檢索（#5）、atom 關聯（#1）、衝突偵測（#3）、完整刪除鏈（#7）

### Sprint 3 — 1 季度（Layering & Polish）

```
W5-6:  Three-layer type 系統 + 差異化淘汰
W7-8:  Episodic memory 自動產生（session 摘要）
W9-10: Evolution log 合併 + Token budget 改善
W11-12: Audit trail 完善 + Dashboard + 全面測試
```
**交付**：完整三層記憶（#6）、所有 issue 收尾、SPEC v2.1 文件、50 query 測試驗證

### 里程碑

```
Week 0      Week 2       Week 4         Week 8         Week 12
  │           │            │              │               │
  ├─ Schema   ├─ Gate      ├─ Retrieval   ├─ Layering     ├─ v2.1
  │  v2.1     │  + Decay   │  + Conflict  │  + Episodic   │  Release
  v           v            v              v               v
 基礎定義    可用 MVP     核心改善       功能完整        品質達標
```

---

## 影響檔案清單

| 檔案 | 狀態 | 改造 |
|------|------|------|
| `~/.claude/memory/SPEC_Atomic_Memory_System.md` | 修改 | 升級 v2.1 規格 |
| `~/.claude/tools/memory-audit.py` | 修改 | --enforce, delete propagation, conflict report, 新欄位解析 |
| `~/.claude/hooks/workflow-guardian.py` | 修改 | Confirmations++, Related 載入, intent, session-end index |
| `~/.claude/tools/memory-vector-service/searcher.py` | 修改 | Ranking 公式, intent boost |
| `~/.claude/tools/memory-vector-service/indexer.py` | 修改 | 新欄位索引, privacy filter |
| `~/.claude/tools/memory-write-gate.py` | **新增** | Write Gate 主邏輯 |
| `~/.claude/tools/memory-conflict-detector.py` | **新增** | Conflict Detection |
| `~/.claude/workflow/config.json` | 修改 | 新增 write_gate, decay, ranking 設定 |
| `~/.claude/memory/MEMORY.md` | 修改 | 索引格式擴展 |
| `~/.claude/CLAUDE.md` | 修改 | 更新記憶系統描述 |

---

## 驗證方式

1. **向後相容**：既有 4 個 global atom 不修改即可被 v2.1 解析器正確讀取
2. **Write Gate**：模擬 10 筆低品質 + 10 筆高品質知識，驗證過濾率
3. **Conflict Detection**：構造 3 對矛盾事實，驗證偵測準確率
4. **Decay**：建立過期 [臨] atom，執行 `--enforce`，確認自動移入 _distant/
5. **Retrieval Ranking**：50 query 手動測試集，比較 v2 vs v2.1 的 precision@5
6. **Delete Propagation**：刪除一個被引用的 atom，確認 LanceDB + Related + MEMORY.md 全部清理
7. **檢索延遲**：確認 UserPromptSubmit hook 內 P99 < 600ms
