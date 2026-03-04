# Hybrid RAG 架構設計

- Scope: global
- Confidence: [固]
- Trigger: RAG, vector, 向量, embedding, 語意, semantic, LanceDB, Ollama, 本地LLM, local LLM, sentence-transformers, qwen3-embedding, bge-m3
- Last-used: 2026-03-04
- Confirmations: 5

## 知識

### 決策（已實作）

- [固] 採用 Hybrid 架構：keyword trigger（現有）優先 + vector semantic search 補充
- [固] 現有 atom trigger 系統保留不動，RAG 作為 RECALL 階段的第二層
- [固] 後端雙軌：Ollama `qwen3-embedding`（主力，MTEB 多語言 #1）+ sentence-transformers `BAAI/bge-m3`（fallback）
- [固] 向量 DB：**LanceDB**（ChromaDB 與 Python 3.14 不相容，已棄用）
- [固] 本地 LLM：`qwen3:1.7b`（qwen3:4b 在 GTX 1050 Ti 上過慢，部分 CPU offload）
- [固] Index endpoints 非同步：HTTP 立即回應，背景執行建索引

### 環境資訊

- GPU: NVIDIA GTX 1050 Ti (4GB VRAM, ~2577 MiB 可用, CUDA 6.1)
- Python: 3.14.2
- Ollama: 已安裝，qwen3-embedding + qwen3:1.7b 已拉取
- Hook timeout: UserPromptSubmit = 3 秒（vector search 必須在 ~2s 內完成）

### 架構設計

```
UserPromptSubmit (3s timeout)
├─ [1] Keyword matching (existing, ~10ms)
├─ [2] HTTP → Vector Service @ localhost:3849 (~200-400ms warm)
│       GET /search?q=<prompt>&top_k=5
│       → 返回 ranked atom names + similarity scores
├─ [3] Merge: keyword + semantic results (deduplicate)
├─ [4] Load atoms within token budget (existing)
└─ Output context
```

### Memory Vector Service（已實作）

- 位置：`~/.claude/tools/memory-vector-service/`
- 檔案：service.py, indexer.py, searcher.py, reranker.py, config.py
- 類型：Python HTTP daemon（非 MCP），port 3849
- 啟動時載入 embedding model（一次載入，warm search ~386ms）
- LanceDB 持久化存儲：`~/.claude/memory/_vectordb/`
- API: GET /search, /health, /status; POST /index, /index/incremental, /reload, /shutdown, /search/enhanced, /rerank, /extract
- 自動啟動：由 SessionStart hook 檢查並啟動
- CLI：`python tools/rag-engine.py {index|search|status|health|start|stop|extract}`

### 實測效能

| 指標 | 數值 |
|------|------|
| 全量索引（18 atoms → 377 chunks） | ~315s（首次） |
| Daemon warm search | ~386ms |
| Enhanced search（LLM query rewrite） | ~7-10s |
| Hook 內語意搜尋 | < 500ms（2s timeout） |

### 本地 LLM 功能（Phase 3，已實作）

1. **Query Rewriting** — LLM 改寫查詢擴展同義詞（`/search/enhanced`）
2. **Re-ranking** — 向量 top-10 → LLM 逐一評分 → 加權重排（`/rerank`）
3. **知識萃取** — 從文本自動萃取結構化 [固/觀/臨] 事實（`/extract`）

### 技術陷阱（已解決）

- [固] ChromaDB 依賴 pydantic v1，與 Python 3.14 不相容 → 改用 LanceDB
- [固] qwen3:4b 在 4GB VRAM GTX 1050 Ti 上 ~71% GPU / 29% CPU，推理超慢 → 改用 qwen3:1.7b
- [固] indexer.py 的 `to_pandas()` 需要 pandas → 改用 LanceDB `to_list()` / `count_rows()`
- [固] enhanced search min_score 0.65 太高（改寫查詢分數 ~0.4-0.54）→ 自動降為 min(config, 0.4)
- [固] pip 在 Git Bash 不直接可用 → 使用 `python -m pip install`

### v2.1 Sprint 1（已完成）

- [固] Schema v2.1：Type, TTL, Expires-at, Related, Supersedes, Privacy, Tags, Quality 欄位
- [固] Write Gate：quality score + dedup 檢查（`memory-write-gate.py`）
- [固] Decay --enforce：[臨]>30d 自動淘汰，[觀]>60d 標記 pending-review
- [固] Confirmations 自動遞增（guardian hook 更新 Last-used 時同步 ++）

### v2.1 Sprint 2（已完成）

- [固] Task-Intent 分類器：rule-based zero LLM，debug/build/design/recall/general
- [固] Retrieval Ranking：`/search/ranked` API，FinalScore = 0.45×Semantic + 0.15×Recency + 0.20×IntentBoost + 0.10×Confidence + 0.10×Confirmation
- [固] indexer.py 擴充 metadata：last_used, confirmations, atom_type, tags 欄位進 LanceDB
- [固] Related/Supersedes 關聯載入：觸發 atom A 時自動拉 A.Related 的摘要
- [固] Conflict Detection：`memory-conflict-detector.py`，LLM 語意比對 AGREE/CONTRADICT/EXTEND/UNRELATED（session-end 離線路徑）
- [固] Delete Propagation：`--delete`/`--purge` 全鏈清除（LanceDB + Related 引用 + MEMORY.md + 增量 re-index）

### v2.1 Sprint 3（已完成）

- [固] Three-layer type 系統：TYPE_DECAY_MULTIPLIER（semantic=1.0, episodic=0.8, procedural=1.5）
- [固] Supersedes 載入邏輯：被取代的舊 atom 不重複載入
- [固] Evolution log 壓縮：`--compact-logs`，>10 筆自動合併為摘要
- [固] Token budget 改為 char-to-token 估算：`len(content) // 4`
- [固] Session-end 增量索引：atom 修改時 handle_session_end() 觸發 re-index
- [固] Audit trail 升級：parse_audit_log() + 健檢報告 Audit Trail Summary
- [固] TYPE_INTENT_BONUS：procedural+build=+0.05, episodic+recall=+0.05
- [固] SPEC v2.1 完整更新：新增 §八 衝突偵測 + §九 Audit Trail
- 完整計畫：`_AIDocs/AtomicMemory-v2.1-Plan.md`

### v2.1 品質驗證（已完成）

- [固] 50-query 測試集：`~/.claude/tools/eval-ranked-search.py`（10 queries × 5 intents）
- [固] 覆蓋類型：direct_keyword(27), semantic_only(10), cross_language(8), negative(5)
- [固] 測試範圍：15 atoms across 3 layers (global + OpenClaw + SGI)
- [固] **Hybrid 評測結果（keyword 優先 + ranked 補充）**：
  - R@5 = 0.96（relevant 召回率）
  - Hit@5 = 0.90（至少一筆相關結果命中率）
  - MRR = 0.80（首筆相關結果排名倒數）
- [固] **語意搜尋增量**：semantic-only 類別 R@5 從 0.05 → 0.85（+0.80 delta）
- [固] P@5 結構上限：avg GT 1.4 atoms / top_k=5 → max ≈ 0.28（改用 R@5/Hit@5/MRR 為主要指標）
- [固] Intent 分類器準確率：72%（36/50 與人工標註一致）
- 評測結果 JSON：`~/.claude/memory/_vectordb/eval-results-*.json`

## 行動

- 系統已實作完畢，日常使用時自動運作
- 品質評測：`python ~/.claude/tools/eval-ranked-search.py [--top-k 5] [--min-score 0.50]`
- 修改 atom 後會自動觸發增量索引（PostToolUse hook）
- 手動全量重建：`python ~/.claude/tools/rag-engine.py index`
- 手動搜尋：`python ~/.claude/tools/rag-engine.py search "查詢"`
- 增強搜尋：`python ~/.claude/tools/rag-engine.py search "查詢" --enhanced`
- 演化日誌壓縮：`python ~/.claude/tools/memory-audit.py --compact-logs [--dry-run]`
- 衝突掃描：`python ~/.claude/tools/memory-conflict-detector.py [--dry-run] [--atom X]`
- 刪除 atom：`python ~/.claude/tools/memory-audit.py --delete <name> [--layer L] [--dry-run]`
- 永久刪除：`python ~/.claude/tools/memory-audit.py --purge <name> [--layer L]`

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-04 | v2.1 品質驗證完成：50-query 測試集，Hybrid R@5=0.96, Hit@5=0.90, MRR=0.80，語意增量 +0.80 | session 實作 |
| 2026-03-04 | v2.1 Sprint 3 完成：Type Decay + Supersedes + Log Compaction + Token Budget + Session-end Index + Audit Trail | session 實作 |
| 2026-03-04 | v2.1 Sprint 2 完成：Intent 分類器 + Ranked Search + Related 載入 + Conflict Detector + Delete Propagation | session 實作 |
| 2026-03-04 | v2.1 Sprint 1 完成：Schema + Write Gate + Decay --enforce + Confirmations++ | session 實作 |
| 2026-03-04 | v2.1 缺陷研究完成：7 缺陷 + 6 系統比較 + schema + 路線圖，標為 [觀] 待實作 | session 研究 |
| 2026-03-03 | 研究完成，建立為 [觀] | session 研究分析 |
| 2026-03-03 | 全系統實作完成，晉升 [固]；ChromaDB→LanceDB、qwen3:4b→1.7b | session 實作測試 |
