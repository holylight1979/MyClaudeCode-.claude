# Atomic Memory V3.1 — 安裝指南

> **目標讀者**：使用 VS Code + Claude Code Extension，但完全不知道原子記憶是什麼的開發者。
> 本指南會幫你把原子記憶系統**合併安裝**到你現有的 `~/.claude/` 目錄中。

---

## 這是什麼？（30 秒版）

Claude Code 每次開新 session 都是白紙一張——上次的決策、踩過的坑、你的偏好全部歸零。

**原子記憶**為 Claude Code 加上長期記憶：
- 透過 Claude Code 的 **hooks** 機制，在每次對話前自動注入歷史知識
- 記住你的偏好、踩過的坑、架構決策，不再反覆犯同樣的錯
- 全部在本地運作，不修改 Claude Code 本體

詳細說明請見 [README.md](README.md)。

---

## 前置需求

### 必備軟體

| 軟體 | 最低版本 | 確認指令 | 安裝方式 |
|------|---------|---------|---------|
| **Claude Code** | 最新 | 在 VS Code 中可開啟 Claude Code 面板 | VS Code Extension 市集搜尋 "Claude" |
| **Python** | 3.8+ | `python --version` | [python.org](https://python.org) |
| **Ollama** | 最新 | `ollama --version` | [ollama.com](https://ollama.com) |
| **Git** | 任意 | `git --version` | 已有（你在看這個 repo） |

> **Windows 注意**：Claude Code 的 shell 是 bash（Git Bash），以下指令都用 Unix 語法。
> **Python 指令**：部分系統是 `python3` 而非 `python`，後續步驟需對應調整。

### 下載 Ollama 模型

安裝 Ollama 後，拉取兩個模型：

```bash
# Embedding 模型（語意搜尋用）
ollama pull qwen3-embedding            # 完整版，需 AVX2 CPU（2013 年後多數 CPU）
# 或 ollama pull qwen3-embedding:0.6b  # 小模型版（無 AVX2 限制，~400MB）

# 語意處理 LLM（知識萃取用）
ollama pull qwen3:1.7b                  # ~1.2GB
```

### 安裝 Python 套件

```bash
pip install lancedb>=0.20               # Vector DB（需 AVX2 CPU）
pip install sentence-transformers>=4.0  # Fallback embedding

# 無 AVX2 的舊 CPU？改用：
# pip install chromadb                  # 替代 lancedb（需改 config）
```

### 硬體需求

| 項目 | 最低 | 建議 |
|------|------|------|
| CPU | 任意 x86_64 | 有 AVX2（2013 年後） |
| RAM | 8 GB | 16 GB |
| GPU | 不需要 | NVIDIA GPU 加速 Ollama |
| 磁碟 | ~2 GB（模型+索引） | — |

---

## 安裝步驟

### 路徑 A：全新安裝（推薦）

適用：`~/.claude/` 是全新目錄，或準備完整重建。

```bash
# 1. Clone repo 直接到 ~/.claude
git clone <你的-repo-URL> ~/.claude

# 2. 一鍵安裝
python ~/.claude/install.py
```

`install.py` 自動完成（5 個步驟 + 驗證報告）：
- npm i -g 全域套件（MCPControl、Playwright）
- `~/.claude.json` MCP servers 合併（冪等，不覆蓋已有設定）
- `IDENTITY.md` / `USER.md` 從 template 初始化

完成後跳至 **[Step 5：安裝 Vector Service 依賴](#step-5-安裝-vector-service-依賴並建立索引)**（Python 套件 + 向量服務）。

---

### 路徑 B：手動 / 合併安裝（已有 ~/.claude 設定）

適用：已有 `~/.claude/` 設定需逐項合併，不想覆蓋現有內容。
路徑 B 完成 Step 0–3 後，可執行 `python ~/.claude/install.py` 一次補齊 npm 套件 + MCP 設定。

### Step 0: 備份你的現有設定

```bash
# 備份你的 settings.json（最重要！裡面有你的 permissions）
cp ~/.claude/settings.json ~/.claude/settings.json.backup
```

### Step 1: Clone repo 到暫存位置

```bash
git clone <你的-repo-URL> /tmp/atomic-memory
```

### Step 2: 複製系統檔案

以下是需要複製到你 `~/.claude/` 的檔案。**不會覆蓋你現有的個人設定**。

```bash
# ── 核心指令 + 身份檔案 ──
cp /tmp/atomic-memory/CLAUDE.md ~/.claude/CLAUDE.md
cp /tmp/atomic-memory/IDENTITY.md ~/.claude/IDENTITY.md
cp /tmp/atomic-memory/USER.md ~/.claude/USER.md
# ⚠ USER.md 需修改為你自己的資料（帳號、技術背景、偏好）

# ── Hook 腳本 ──
mkdir -p ~/.claude/hooks
cp /tmp/atomic-memory/hooks/workflow-guardian.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_paths.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_core.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_atoms.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_intent.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_extraction.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_episodic.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_iteration.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/extract-worker.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/quick-extract.py ~/.claude/hooks/      # async 快篩
cp /tmp/atomic-memory/hooks/wg_hot_cache.py ~/.claude/hooks/       # Hot Cache
cp /tmp/atomic-memory/hooks/wg_content_classify.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wisdom_engine.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/user-init.sh ~/.claude/hooks/

# ── 規則模組 ──
mkdir -p ~/.claude/rules
cp /tmp/atomic-memory/rules/aidocs.md ~/.claude/rules/
cp /tmp/atomic-memory/rules/memory-system.md ~/.claude/rules/
cp /tmp/atomic-memory/rules/sync-workflow.md ~/.claude/rules/
cp /tmp/atomic-memory/rules/session-management.md ~/.claude/rules/

# ── Ollama Client (Dual-Backend) ──
cp /tmp/atomic-memory/tools/ollama_client.py ~/.claude/tools/

# ── 工具鏈 ──
mkdir -p ~/.claude/tools/memory-vector-service
mkdir -p ~/.claude/tools/workflow-guardian-mcp
cp /tmp/atomic-memory/tools/memory-audit.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/memory-write-gate.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/memory-conflict-detector.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/rag-engine.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/read-excel.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/memory-vector-service/* ~/.claude/tools/memory-vector-service/
cp /tmp/atomic-memory/tools/workflow-guardian-mcp/server.js ~/.claude/tools/workflow-guardian-mcp/

# ── 記憶規格 + 領域知識 ──
mkdir -p ~/.claude/memory
mkdir -p ~/.claude/memory/unity
cp /tmp/atomic-memory/memory/SPEC_Atomic_Memory_System.md ~/.claude/memory/
cp /tmp/atomic-memory/memory/unity/unity-yaml.md ~/.claude/memory/unity/
cp /tmp/atomic-memory/memory/unity/unity-yaml-detail.md ~/.claude/memory/unity/

# ── Workflow 設定 ──
mkdir -p ~/.claude/workflow
cp /tmp/atomic-memory/workflow/config.json ~/.claude/workflow/

# ── Slash commands (Skills) ──
mkdir -p ~/.claude/commands
cp /tmp/atomic-memory/commands/init-project.md ~/.claude/commands/
cp /tmp/atomic-memory/commands/read-project.md ~/.claude/commands/
cp /tmp/atomic-memory/commands/resume.md ~/.claude/commands/
cp /tmp/atomic-memory/commands/consciousness-stream.md ~/.claude/commands/
cp /tmp/atomic-memory/commands/svn-update.md ~/.claude/commands/
cp /tmp/atomic-memory/commands/unity-yaml.md ~/.claude/commands/
cp /tmp/atomic-memory/commands/harvest.md ~/.claude/commands/
cp /tmp/atomic-memory/commands/upgrade.md ~/.claude/commands/

# ── Unity YAML 操作工具 ──
cp /tmp/atomic-memory/tools/unity-yaml-tool.py ~/.claude/tools/
```

### Step 3: 合併 settings.json（最關鍵的一步）

**不能直接覆蓋** `settings.json`——你的 `permissions` 區塊是你自己的，只需要加入 `hooks` 區塊。

打開你備份的 `settings.json.backup` 和 repo 的 `settings.json`，把 `hooks` 區塊合併進去。

你的 `settings.json` 最終應該長這樣（`permissions` 保留你自己的）：

```jsonc
{
  "permissions": {
    // ← 保留你原本的 permissions，不要動
  },
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"$HOME/.claude/hooks/workflow-guardian.py\"",
            "timeout": 5
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"$HOME/.claude/hooks/workflow-guardian.py\"",
            "timeout": 3
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write|Read|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python \"$HOME/.claude/hooks/workflow-guardian.py\"",
            "timeout": 3
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"$HOME/.claude/hooks/workflow-guardian.py\"",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"$HOME/.claude/hooks/workflow-guardian.py\"",
            "timeout": 5
          },
          {
            "type": "command",
            "command": "python \"$HOME/.claude/hooks/quick-extract.py\"",
            "async": true,
            "timeout": 30
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"$HOME/.claude/hooks/workflow-guardian.py\"",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

> **Python 指令確認**：如果你的系統用 `python3` 而非 `python`，把上面所有 `"python \"$HOME/..."` 改成 `"python3 \"$HOME/..."`。

### Step 4: 初始化你的全域記憶

建立你自己的 `MEMORY.md`（這是你的個人記憶索引，不是從 repo 複製的）：

```bash
cat > ~/.claude/memory/MEMORY.md << 'EOF'
# Atom Index — Global

> Session 啟動時先讀此索引。比對 Trigger → Read 對應 atom。

| Atom | Path | Trigger | Confidence |
|------|------|---------|------------|
| preferences | memory/preferences.md | 偏好, 風格, 習慣, style, preference | [固] |
| decisions | memory/decisions.md | 全域決策, 工具, 工作流, workflow, hooks | [固] |

---

## 高頻事實

- 原子記憶 V3.1
EOF
```

同時建立空白的個人 atom 檔案：

```bash
cat > ~/.claude/memory/preferences.md << 'EOF'
# Atom: preferences
- Scope: global
- Confidence: [固]
- Trigger: 偏好, 風格, 習慣, style, preference
- Type: preference
- Last-used: —
- Confirmations: 0

## 知識

（在此記錄你的偏好，例如語言、風格、工具選擇）

## 行動

- 引用這些偏好做決策

## 演化日誌

- 初始建立
EOF

cat > ~/.claude/memory/decisions.md << 'EOF'
# Atom: decisions
- Scope: global
- Confidence: [固]
- Trigger: 全域決策, 工具, 工作流, workflow, hooks
- Type: decision
- Last-used: —
- Confirmations: 0

## 知識

（在此記錄跨專案的決策）

## 行動

- 引用這些決策，確保一致性

## 演化日誌

- 初始建立
EOF
```

### Step 5: 安裝 Vector Service 依賴並建立索引

```bash
cd ~/.claude/tools/memory-vector-service
pip install -r requirements.txt
```

啟動 Vector Service 並驗證：

```bash
# 啟動（背景執行）
python ~/.claude/tools/memory-vector-service/service.py &

# 等幾秒後驗證
curl -s http://127.0.0.1:3849/health
# 預期回應: {"status":"ok", ...}

# 建立完整索引
curl -s http://127.0.0.1:3849/index/full
# 預期回應: {"indexed":N, "chunks":M}
```

> Vector Service 在每次 Claude Code session 啟動時會由 Guardian 自動啟動，不需要手動常駐。

### Step 5.5: （可選）設定遠端 Ollama Backend（Dual-Backend）

如果團隊有遠端 GPU 伺服器（例如搭載 Open WebUI + Ollama），可在 `config.json` 加入遠端 backend，享受 GPU 加速推論並自動 failover 到本地：

```bash
# 編輯設定
nano ~/.claude/workflow/config.json
```

在 `vector_search` 區塊中加入 `ollama_backends`：

```jsonc
"ollama_backends": {
  "remote-gpu": {
    "base_url": "https://your-ollama-server.example.com/ollama",
    "auth": {
      "type": "bearer_ldap",
      "login_url": "https://your-ollama-server.example.com/api/v1/auths/ldap",
      "password_file": "~/.claude/workflow/.rdchat_password"
    },
    "llm_model": "qwen3.5:latest",
    "embedding_model": "qwen3-embedding:latest",
    "priority": 1,
    "enabled": true
  },
  "local": {
    "base_url": "http://127.0.0.1:11434",
    "llm_model": "qwen3:1.7b",
    "embedding_model": "qwen3-embedding",
    "priority": 2
  }
}
```

建立密碼檔（已在 `.gitignore`，不會被上傳）：

```bash
# 寫入你的 LDAP 密碼（公司登入密碼）
echo "你的密碼" > ~/.claude/workflow/.rdchat_password
```

- **帳號**：自動取 `os.getlogin()`（Windows 登入帳號），無需設定
- **認證方式**：LDAP bearer token，自動登入、自動重新認證
- **Failover**：遠端不可用時自動切換到本地，三階段退避（正常→短DIE 60s→長DIE 等到下個 6h 時段）
- **靜態停用**：設 `"enabled": false` 可永久跳過某個 backend

> 不設定 `ollama_backends` 時，系統自動使用 legacy 模式（單一本地 Ollama :11434）。

### Step 6: （可選）註冊 Dashboard MCP Server

如果想在 Claude Code 中使用 `workflow_signal` / `workflow_status` 工具：

在你的專案根目錄或全域 `.mcp.json` 中加入：

```json
{
  "mcpServers": {
    "workflow-guardian": {
      "command": "node",
      "args": ["~/.claude/tools/workflow-guardian-mcp/server.js"],
      "disabled": false
    }
  }
}
```

Dashboard 網址：`http://127.0.0.1:3848`

---

## 驗證安裝

### 快速驗證（命令列）

```bash
# 0. 一鍵驗證（npm + MCP + bootstrap 部分）
python ~/.claude/install.py
# 全部 ✓ 即表示基礎環境就緒；項目失敗時腳本會提示修復指令

# 1. Python + 套件
python -c "import lancedb; print('lancedb OK')"
python -c "import sentence_transformers; print('sentence-transformers OK')"

# 2. Ollama 模型
ollama list | grep -E "qwen3-embedding|qwen3:1.7b"
# 應看到兩個模型

# 3. Hook 可執行
echo '{"hook_event_name":"SessionStart","session_id":"test","cwd":"/tmp"}' | \
  python ~/.claude/hooks/workflow-guardian.py
# 預期: JSON 含 "additionalContext"

# 4. Vector Service
curl -s http://127.0.0.1:3849/health
# 預期: {"status":"ok", ...}

# 5. 健檢工具
python ~/.claude/tools/memory-audit.py
# 預期: Markdown 報告，無 ERROR
```

### 整合驗證（在 VS Code 中）

1. **開新 Claude Code session** → 應看到 `[Workflow Guardian] Active.` 訊息
2. **輸入一段 prompt**（例如 "我的偏好是什麼"） → 應看到 atom 被載入到 context
3. **Edit 一個檔案後嘗試結束** → 應看到 Stop 閘門提醒你同步
4. **Session 結束後** → 檢查 `~/.claude/memory/episodic/` 是否有新的 `.md` 檔案

---

## 安裝後的初步使用

驗證完成後，按以下順序開始使用：

1. **重新載入 VS Code**：按 `Ctrl+Shift+P`，輸入 `Developer: Reload Window` 讓 hooks 和設定生效
2. **自檢系統**：開新 Claude Code session，輸入 `請確認原子記憶系統是否正確安裝` 讓 AI 自動檢查各子系統狀態
3. **專案初始化**：在專案資料夾開啟 VS Code，首次使用時執行 `/init-project`，建立 `_AIDocs/` 知識庫骨架
4. **匯入專案知識**：對想讓 AI 深度記憶的目錄，執行 `/read-project <目標資料夾>`（例如 `/read-project src/core`）

更多 Skills 和進階用法請參閱 [README.md](README.md)。

---

## 安裝後的目錄結構

安裝完成後，你的 `~/.claude/` 會多出這些（★ = 新增）：

```
~/.claude/
├── install.py                    ★ 一鍵安裝腳本（npm + MCP + bootstrap）
├── CLAUDE.md                     ★ 系統指令（每 session 自動載入）
├── IDENTITY.md                   ★ AI 身份與行為準則（@import 載入，團隊共用）
├── USER.md                       ★ 操作者個人資料（@import 載入，⚠ 需改為你的資料）
├── settings.json                   已合併 hooks 區塊
│
├── rules/                        ★ 模組化規則 (Claude Code 自動載入)
│   ├── aidocs.md                 ★ _AIDocs 知識庫維護
│   ├── memory-system.md          ★ 原子記憶系統規則
│   ├── sync-workflow.md          ★ 工作結束同步 + Guardian 閘門
│   └── session-management.md     ★ 對話管理 + 續航 + 識流
│
├── hooks/                        ★
│   ├── workflow-guardian.py       ★ 統一 Hook 入口
│   ├── wg_paths.py               ★ 路徑唯一真相來源
│   ├── wg_core.py                ★ 共用常數/設定/IO
│   ├── wg_atoms.py               ★ 索引解析/trigger/ACT-R/section 注入
│   ├── wg_intent.py              ★ 意圖分類/向量搜尋
│   ├── wg_extraction.py          ★ 回應萃取
│   ├── wg_hot_cache.py           ★ Hot Cache 讀寫/注入
│   ├── wg_episodic.py            ★ Episodic 管理
│   ├── wg_iteration.py           ★ 自我迭代/衰減/覆轍
│   ├── extract-worker.py         ★ LLM 萃取子程序 (detached)
│   ├── quick-extract.py          ★ Stop async 快篩
│   ├── wisdom_engine.py          ★ Wisdom Engine
│   └── user-init.sh              ★ 多人 USER.md 初始化
│
├── tools/                        ★
│   ├── ollama_client.py          ★ Dual-Backend Ollama Client
│   ├── memory-audit.py           ★ 健檢工具
│   ├── memory-write-gate.py      ★ 寫入品質閘門
│   ├── memory-conflict-detector.py ★ 衝突偵測
│   ├── rag-engine.py             ★ RAG CLI
│   ├── read-excel.py             ★ Excel 讀取
│   ├── unity-yaml-tool.py        ★ Unity YAML 操作工具
│   ├── memory-vector-service/    ★ HTTP Vector 搜尋服務 @ :3849
│   └── workflow-guardian-mcp/    ★ Dashboard MCP @ :3848
│
├── memory/                       ★
│   ├── MEMORY.md                 ★ 你的記憶索引
│   ├── preferences.md            ★ 你的偏好 atom
│   ├── decisions.md              ★ 你的決策 atom
│   ├── unity/                    ★ Unity YAML 領域知識
│   │   ├── unity-yaml.md         ★ 速查 atom (trigger 自動載入)
│   │   └── unity-yaml-detail.md  ★ 完整參考 (按需讀取)
│   ├── SPEC_Atomic_Memory_System.md ★ 規格參考
│   ├── _staging/                   （暫存區，臨時檔案用完即清）
│   ├── episodic/                   （自動生成 session 摘要）
│   └── _vectordb/                  （自動生成向量索引）
│
├── workflow/                     ★
│   ├── config.json               ★ 系統設定
│   ├── hot_cache.json              （自動生成，快篩知識快取）
│   └── vector_ready.flag           （自動生成，Vector service 就緒旗標）
│
├── commands/                     ★ Slash commands (Skills)
│   ├── init-project.md           ★ /init-project — 專案知識庫初始化
│   ├── read-project.md           ★ /read-project — 專案深度掃描
│   ├── resume.md                 ★ /resume — 自動續接 Session
│   ├── consciousness-stream.md   ★ /consciousness-stream — 識流決策流程
│   ├── svn-update.md             ★ /svn-update — SVN 工作目錄更新
│   ├── unity-yaml.md             ★ /unity-yaml — Unity YAML 資產操作
│   ├── harvest.md                ★ /harvest — 網頁收割工具
│   └── upgrade.md                ★ /upgrade — 原子記憶環境升級
│
└── (你原有的檔案保持不變)
```

---

## V2 → V3 升級

已安裝 V2.21 的使用者升級步驟：

```bash
# 1. 更新程式碼
cd ~/.claude && git pull

# 2. 確認新增的 hook 檔案
ls -la hooks/quick-extract.py hooks/wg_hot_cache.py hooks/wg_content_classify.py
```

### Checklist

- [ ] `settings.json` 的 Stop hook 有 async `quick-extract.py` entry（`install.py` 會自動處理）
- [ ] `workflow/config.json` 有 `hot_cache` section（git pull 已包含）
- [ ] Ollama `qwen3:1.7b` 模型可用（`ollama list | grep qwen3:1.7b`）
- [ ] 首次啟動 session 後，觀察 `workflow/hot_cache.json` 出現

> **新安裝者**：`install.py` 一鍵安裝已包含 V3 所有設定（settings.json 自動有 async hook），無需額外步驟。

---

## 常見問題

### Q: 安裝後 Claude Code 啟動變慢？
**A**: 正常。V3.1 已大幅改善：SessionStart 去重 + 非阻塞 vector 啟動，延遲降至 50-200ms。每次 prompt 增加 ~300-600ms（語意搜尋）。

### Q: Vector Service 啟動失敗？
**A**: 檢查 `pip install lancedb` 是否成功（需 AVX2 CPU）。檢查 port 3849 是否被佔用。無 AVX2 則改用 ChromaDB 並修改 `workflow/config.json` 的 `vector_search` 區塊。

### Q: Ollama embedding timeout？
**A**: 模型首次載入約 5-10 秒，之後常駐記憶體（~1-2GB RAM）。確認 `ollama list` 有顯示正確模型。

### Q: Hook 執行但 atom 沒被載入？
**A**: 確認 `MEMORY.md` 的 Trigger 欄位包含你 prompt 中的關鍵字。也確認 atom 檔案路徑正確（相對於 `~/.claude/`）。

### Q: 不想要某些功能？
**A**: 在 `workflow/config.json` 中可個別關閉：
- `"enabled": false` — 關閉整個 Guardian
- `"vector_search.enabled": false` — 關閉語意搜尋（僅用 keyword）
- `"response_capture.enabled": false` — 關閉回應知識萃取
- `"cross_session.enabled": false` — 關閉跨 session 鞏固

### Q: 想完全移除？
**A**: 刪除新增的檔案，從 `settings.json` 移除 `hooks` 區塊，恢復原本的 `CLAUDE.md`（或刪除）。系統完全不修改 Claude Code 本體，移除無殘留。

### Q: 沒有 GPU 能用嗎？
**A**: 可以。Ollama 自動 fallback 到 CPU。`qwen3-embedding` CPU 推論約 200-500ms，`qwen3:1.7b` 約 1-3s。體驗略慢但完全可用。

---

## 升級路徑

系統設計為漸進式啟用。你可以先從基礎開始，逐步開啟進階功能：

| 階段 | 額外需求 | 功能 |
|------|---------|------|
| **基礎** | 僅 Python | Keyword trigger 記憶注入 + Workflow Guardian 同步閘門 |
| **+ Vector** | + lancedb/chromadb | 語意搜尋，atom 多了也能精準召回 |
| **+ 本地 LLM** | + Ollama + 4GB RAM | 回應自動知識萃取 + intent 分類 + 跨 session 鞏固 |
| **+ 大模型** | + 16GB VRAM GPU | 升級 qwen3:8b/14b，萃取品質更好 |

---

## 清理暫存

```bash
rm -rf /tmp/atomic-memory
```
