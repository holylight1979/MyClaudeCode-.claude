# Claude Code 全域設定 — 核心架構

## Hooks 系統（V2.4）

6 個 hook 事件，定義在 `settings.json`，全部由 `workflow-guardian.py` 處理：

| Hook | 觸發時機 | 用途 |
|------|---------|------|
| `SessionStart` | Session 開始 | 初始化 session state |
| `UserPromptSubmit` | 使用者送出訊息 | RECALL 記憶檢索 + intent 分類 + 回應知識萃取（V2.4） |
| `PostToolUse` | Edit/Write 後 | 追蹤修改檔案 + 增量索引 |
| `PreCompact` | Context 壓縮前 | 快照 state（壓縮前保護） |
| `Stop` | 對話結束前 | 閘門：未同步則阻止結束 |
| `SessionEnd` | Session 結束 | Episodic atom 生成 + 回應補漏萃取 + 跨 Session 鞏固（V2.4） |

## Skills（/Slash Commands）

| Skill | 檔案 | 用途 |
|-------|------|------|
| `/init-project` | `commands/init-project.md` | 專案知識庫（_AIDocs）初始化 |

## 記憶系統（原子記憶 V2.4）

### 雙 LLM 架構

| 角色 | 引擎 | 職責 |
|------|------|------|
| 雲端 LLM | Claude Code | 記憶演進決策、分類判斷、晉升/淘汰 |
| 本地 LLM | Ollama qwen3 | embedding、query rewrite、re-ranking、intent 分類、回應知識萃取 |

### 資料層

1. **MEMORY.md**（always-loaded）: Atom 索引 + 高頻事實
2. **Atom 檔案**（按需載入）: 由 Trigger 欄位 + 向量搜尋發現
3. **Vector DB**: LanceDB（`memory/_vectordb/`）
4. **Episodic atoms**: 自動生成 session 摘要（`memory/episodic/`，TTL 24d，不進 git）

### 記憶檢索管線

```
使用者訊息 → UserPromptSubmit hook (workflow-guardian.py)
  ├─ Intent 分類 (rule-based ~1ms)
  ├─ MEMORY.md Trigger 匹配 (keyword ~10ms)
  ├─ Vector Search (LanceDB + qwen3-embedding ~200-500ms)
  └─ Ranked Merge → top atoms → additionalContext
```

降級: Ollama 不可用 → 純 keyword | Vector Service 掛 → graceful fallback

### 回應知識捕獲（V2.4）

| 層 | 時機 | 輸入 | 上限 |
|----|------|------|------|
| 逐輪萃取 | UserPromptSubmit（非同步 daemon thread） | 上一輪 assistant 回應 | 3000 chars, 2 items |
| SessionEnd 補漏 | SessionEnd（同步） | 全 transcript | 20000 chars, 5 items |

萃取結果一律 `[臨]`，由本地 qwen3:1.7b 處理，零雲端 token 開銷。

### 跨 Session 鞏固（V2.4 Phase 3）

SessionEnd 時對 knowledge_queue 做向量搜尋（min_score 0.75）：
- 2+ sessions 命中 → 自動晉升 `[臨]`→`[觀]`
- 4+ sessions 命中 → 建議晉升 `[觀]`→`[固]`（需使用者確認）
- 結果寫入 episodic atom「跨 Session 觀察」段落

### 索引來源（2 層）

| Layer | 路徑 | Atoms |
|-------|------|-------|
| global | `~/.claude/memory/` | 4 (preferences, decisions, excel-tools, spec) |
| episodic | `memory/episodic/` | 動態（TTL 24d，vector search 發現） |

### 工具鏈

| 工具 | 路徑 | 用途 |
|------|------|------|
| rag-engine.py | `tools/rag-engine.py` | CLI: search/index/status/health |
| memory-write-gate.py | `tools/memory-write-gate.py` | 寫入品質閘門 + 去重 |
| memory-audit.py | `tools/memory-audit.py` | 格式驗證、過期、晉升建議 |
| memory-conflict-detector.py | `tools/memory-conflict-detector.py` | 矛盾偵測 |
| eval-ranked-search.py | `tools/eval-ranked-search.py` | Ranked search 評估 |
| read-excel.py | `tools/read-excel.py` | Excel 讀取工具 |
| memory-vector-service/ | `tools/memory-vector-service/` | HTTP 服務 (port 3849) |

## MCP Servers

| Server | 傳輸 | 用途 |
|--------|------|------|
| workflow-guardian | stdio (Node.js) | session 管理 + Dashboard (port 3848) |

## 權限設定

`settings.json` 的 `permissions.allow` 列表：
- Bash: powershell, python, ls, wc, du, git, gh, ollama, curl, echo, grep, find
- Read: C:\Users\**, C:\OpenClawWorkspace\**
- MCP: workflow-guardian (workflow_signal, workflow_status)
