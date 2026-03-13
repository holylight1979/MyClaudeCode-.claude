# Claude Code 全域設定 — 核心架構

## Hooks 系統（V2.11）

6 個 hook 事件，定義在 `settings.json`，全部由 `workflow-guardian.py`（~2770 行）處理：

| Hook | 觸發時機 | 用途 |
|------|---------|------|
| `UserPromptSubmit` | 使用者送出訊息 | RECALL 記憶檢索 + intent 分類 + Context Budget 監控 + Wisdom 情境分類（V2.11） |
| `PostToolUse` | Edit/Write 後 | 追蹤修改檔案 + 增量索引 + Read Tracking + over_engineering 追蹤（V2.11） |
| `PreCompact` | Context 壓縮前 | 快照 state（壓縮前保護） |
| `Stop` | 對話結束前 | 閘門：未同步則阻止結束 |
| `SessionStart` | Session 開始 | 初始化 session state + Wisdom 盲點提醒 + 定期檢閱提醒 |
| `SessionEnd` | Session 結束 | Episodic atom 生成 + 回應萃取（僅 SessionEnd）+ 鞏固（簡化計數）+ 衝突偵測 + Wisdom 反思（V2.11） |

## Skills（/Slash Commands）

| Skill | 檔案 | 用途 |
|-------|------|------|
| `/init-project` | `commands/init-project.md` | 專案知識庫（_AIDocs）初始化 |
| `/resume` | `commands/resume.md` | 自動續接 Session（MCP 桌面自動化） |
| `/consciousness-stream` | `commands/consciousness-stream.md` | 識流處理（高風險跨系統任務） |
| `/svn-update` | `commands/svn-update.md` | SVN 更新工作目錄 |
| `/unity-yaml` | `commands/unity-yaml.md` | Unity YAML Asset 操作 |
| `/upgrade` | `commands/upgrade.md` | 環境升級比對工具 |

## 規則模組（V2.11 新增）

`.claude/rules/` 下的 `.md` 檔案由 Claude Code 自動載入，CLAUDE.md 瘦身至 ~50 行：

| 模組 | 說明 |
|------|------|
| `rules/memory-system.md` | 原子記憶系統規則 |
| `rules/aidocs.md` | _AIDocs 知識庫維護 |
| `rules/session-management.md` | 對話管理 + 續航 + 自我迭代 |
| `rules/sync-workflow.md` | 工作結束同步 + Guardian 閘門 |

## 記憶系統（原子記憶 V2.11）

### 雙 LLM 架構 + Dual-Backend

| 角色 | 引擎 | 職責 |
|------|------|------|
| 雲端 LLM | Claude Code | 記憶演進決策、分類判斷、晉升/淘汰 |
| 本地 LLM | Ollama (Dual-Backend) | embedding、query rewrite、re-ranking、intent 分類、回應知識萃取 |

#### Dual-Backend Ollama（V2.11）

統一 Ollama 呼叫入口 `tools/ollama_client.py`，支援多 backend 自動切換：

```
config.json → ollama_backends:
  primary (priority=1, 遠端 GPU) → fallback (priority=2, 本地)
```

三階段退避：
- **正常** → 連續 2 次失敗 → **短DIE**（60s 冷卻，跳過此 backend）
- 10 分鐘內 2 次短DIE → **長DIE**（等到下個 6h 時段: 00/06/12/18 點）
- 長DIE 觸發 → SessionStart hook 詢問使用者「停用」或「保持」
- **靜態停用旗標**：`enabled: false` 永久跳過，不做 health check
- 認證：LDAP bearer token，帳號自動 `os.getlogin()`，密碼檔 `workflow/.rdchat_password`

### 資料層

1. **MEMORY.md**（always-loaded）: Atom 索引 + 高頻事實
2. **Atom 檔案**（按需載入）: 由 Trigger 欄位 + 向量搜尋發現
3. **Vector DB**: LanceDB（`memory/_vectordb/`）
4. **Episodic atoms**: 自動生成 session 摘要（`memory/episodic/`，TTL 24d，不進 git）
5. **Wisdom Engine**: 反思統計（`memory/wisdom/`）— V2.11 移除因果圖

### 記憶檢索管線

```
使用者訊息 → UserPromptSubmit hook (workflow-guardian.py)
  ├─ Intent 分類 (rule-based ~1ms)
  ├─ MEMORY.md Trigger 匹配 (keyword ~10ms)
  ├─ Vector Search (LanceDB + qwen3-embedding ~200-500ms)
  ├─ Ranked Merge → top atoms
  ├─ Context Budget: 3000 tokens 上限，ACT-R truncate (V2.11)
  └─ additionalContext 注入
```

降級: primary 不可用 → fallback (Dual-Backend) | 全 Ollama 不可用 → 純 keyword | Vector Service 掛 → graceful fallback

### 回應知識捕獲（V2.11）

| 時機 | 輸入 | 上限 |
|------|------|------|
| SessionEnd（同步） | 全 transcript | 20000 chars, 5 items |

V2.11 廢除逐輪萃取，僅 SessionEnd 全 transcript 掃描。情境感知萃取（依 intent 調整 prompt）。萃取結果一律 `[臨]`，由本地 qwen3:1.7b 處理。

### 跨 Session 鞏固（V2.11 簡化）

- 廢除自動晉升，改為 Confirmations +1 簡單計數
- 4+ sessions → 建議晉升（不自動執行）
- 統一 dedup 閾值 0.80
- SessionEnd 衝突偵測：向量搜尋 score 0.60-0.95 → 寫入 episodic 衝突警告

### Wisdom Engine（V2.11）

- **情境分類器**：2 條硬規則取代 5 信號加權（file_count/is_feature → confirm; touches_arch → plan）
- **反思引擎**：first_approach_accuracy + over_engineering_rate + silence_accuracy + Bayesian 校準
- V2.11 移除：因果圖（CausalGraph + causal_graph.json）

### 工具鏈

| 工具 | 路徑 | 用途 |
|------|------|------|
| ollama_client.py | `tools/ollama_client.py` | Dual-Backend Ollama Client（三階段退避+auth+failover） |
| rag-engine.py | `tools/rag-engine.py` | CLI: search/index/status/health |
| memory-write-gate.py | `tools/memory-write-gate.py` | 寫入品質閘門 + 去重 |
| memory-audit.py | `tools/memory-audit.py` | 格式驗證、過期、晉升建議 |
| memory-conflict-detector.py | `tools/memory-conflict-detector.py` | 矛盾偵測 |
| atom-health-check.py | `tools/atom-health-check.py` | Atom 健康度（Related 完整性，V2.11） |
| cleanup-old-files.py | `tools/cleanup-old-files.py` | 環境清理（V2.11） |
| read-excel.py | `tools/read-excel.py` | Excel 讀取工具 |
| memory-vector-service/ | `tools/memory-vector-service/` | HTTP 服務 (port 3849) |
| wisdom_engine.py | `hooks/wisdom_engine.py` | Wisdom Engine（情境分類+反思） |

## MCP Servers

| Server | 傳輸 | 用途 |
|--------|------|------|
| workflow-guardian | stdio (Node.js) | session 管理 + Dashboard (port 3848) |

## 權限設定

`settings.json` 的 `permissions.allow` 列表：
- Bash: powershell, python, ls, wc, du, git, gh, ollama, curl, echo, grep, find
- Read: C:\Users\**, C:\OpenClawWorkspace\**
- MCP: workflow-guardian (workflow_signal, workflow_status)
