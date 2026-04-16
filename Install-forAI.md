# Atomic Memory V4.1 — AI 安裝指南

> **目標讀者**：Claude / 相容 AI 助手，代替使用者執行原子記憶系統的合併安裝。
> **若你是人類**：建議不要逐步手作，直接在新 Claude Code session 貼 [README.md](README.md) 的「由 AI 全程代跑」prompt，讓 AI 照本指南執行。

---

## 0. AI 執行守則（開工前必讀）

1. **每一步驗證，每一步回報**。不要一次跑完再說，每個 Step 結束都告訴使用者「已做 X，接下來做 Y，你確認嗎」。
2. **不覆蓋使用者現有設定**：`settings.json` 的 `permissions`、`config.json` 使用者自訂值、`USER.md` 個人資料一律 merge，不 overwrite。
3. **缺套件不自行 pip install / npm i**：列出缺項 + 安裝指令給使用者，**等使用者確認再裝**。跨平台（Windows / Mac / Linux）指令要對。
4. **帳號密碼類（LDAP password / API token）絕不主動寫入**：需要時問使用者，或請使用者自己編輯 gitignored 檔。
5. **若發現與本指南不符的真源差異**（代碼已改、路徑異動），以當下代碼 / config.json 為準，同時回報使用者「指南需更新」。
6. **路徑符號**：Windows 使用者的 `~/.claude/` 實際是 `C:\Users\{user}\.claude\`。用 `pathlib.Path.home()` 或 bash `$HOME` 確保跨平台。

---

## 1. 必備套件自檢清單

**先全部跑過**再開始裝任何東西。把結果整理成表格回報給使用者，缺的項目**不要自己補**，給使用者具體補裝指令由他決定。

| 項目 | 自檢指令 | 通過標準 |
|------|---------|---------|
| Claude Code Extension | 問使用者「VS Code 的 Claude Code 面板能開嗎？」或檢查 `code --list-extensions \| grep claude` | 有 Anthropic 官方 Claude extension |
| Python | `python --version`（或 `python3 --version`）| ≥ 3.10 |
| Node.js | `node --version` | 有 LTS 版本即可 |
| Git | `git --version` | 任意 |
| Ollama | `ollama --version` | 有 |
| Ollama 模型 | `ollama list` | 含 `qwen3-embedding` + `qwen3:1.7b` + `gemma4:e4b`（V4.1 rdchat 主模型） |
| Python 套件 | `python -c "import lancedb; import sentence_transformers; print('ok')"` | 無 ImportError |
| VS Code hook 權限 | 檢查 `settings.json` 是否允許執行 `python` hook | 無 sandbox 阻擋 |

**若使用者在公司內網 + 有遠端 Ollama backend**（rdchat-direct / rdchat），補查：
- 遠端 base URL 連通性（`curl -s <base_url>/api/tags`）
- LDAP bearer token 可認證（可選）

**缺項回報格式範例**：
```
我檢查完了。以下必備項尚未就緒：
1. Python 3.9 → 需升級到 3.10+
   Windows: 從 python.org 下載安裝
2. Ollama 模型 gemma4:e4b 未下載
   執行: ollama pull gemma4:e4b
3. lancedb 套件未裝
   執行: pip install lancedb>=0.20

你補完後告訴我，我再繼續下一步。
```

---

## 2. 使用者常問問題樣板

讓使用者知道這些問題都可以問你（AI），別讓他以為必須自己研究：

- 「**你能幫我確認必備套件沒漏嗎？**」 → 跑第 1 節的自檢清單
- 「**我 Python 是 3.9 可以嗎？**」 → 答：不行，需 3.10+；給升級指令
- 「**我沒 GPU 會慢很多嗎？**」 → 答：Ollama 可 CPU fallback，`qwen3-embedding` 200-500 ms、`qwen3:1.7b` 1-3 s，能用但慢；建議設定遠端 rdchat-direct backend 享受 GPU 加速
- 「**我在公司電腦、沒 admin 權限能裝嗎？**」 → 大部分能（Python / Node.js / Ollama 有 user-local 安裝），pip 套件用 `--user`；但 Windows Ollama 裝在 `%LOCALAPPDATA%`
- 「**團隊協作（多職務）要怎麼啟用？**」 → V4 scope 分層（global / shared / role / personal）代碼就緒，在專案裡執行 `/init-roles` 建立 `memory/shared/_roles.md` 白名單與 `role/{name}/` 目錄
- 「**安裝完後沒看到 Guardian Active 訊息？**」 → 檢查 `settings.json` 的 hooks 區塊是否合併進來（Step 3）
- 「**我要整個移除怎麼辦？**」 → 刪 `settings.json` 的 hooks 區塊，其餘檔案刪掉即可；Claude Code 本體零修改

---

## 3. 安裝流程（合併安裝，不覆蓋既有設定）

### Step 0：備份現有設定

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.backup 2>/dev/null || true
```

### Step 1：Clone repo 到暫存位置

```bash
git clone <repo-URL> /tmp/atomic-memory
```

### Step 2：複製系統檔案（不動使用者個人資料）

```bash
# ── 核心指令 + 身份檔案 ──
cp /tmp/atomic-memory/CLAUDE.md ~/.claude/CLAUDE.md
cp /tmp/atomic-memory/IDENTITY.md ~/.claude/IDENTITY.md
# USER.md 只在不存在時複製（使用者自己的資料優先）
[ ! -f ~/.claude/USER.md ] && cp /tmp/atomic-memory/USER.md ~/.claude/USER.md

# ── Hooks（15 個 Python 模組）──
mkdir -p ~/.claude/hooks
cp /tmp/atomic-memory/hooks/workflow-guardian.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_paths.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_core.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_atoms.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_intent.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_extraction.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_episodic.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_iteration.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_hot_cache.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_docdrift.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wg_roles.py ~/.claude/hooks/              # V4 角色白名單
cp /tmp/atomic-memory/hooks/wg_user_extract.py ~/.claude/hooks/       # V4.1 L0 detector
cp /tmp/atomic-memory/hooks/wg_session_evaluator.py ~/.claude/hooks/  # V4.1 評分
cp /tmp/atomic-memory/hooks/user-extract-worker.py ~/.claude/hooks/   # V4.1 L1/L2
cp /tmp/atomic-memory/hooks/extract-worker.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/quick-extract.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/wisdom_engine.py ~/.claude/hooks/
cp /tmp/atomic-memory/hooks/user-init.sh ~/.claude/hooks/

# ── V4.1 共享萃取核心 ──
mkdir -p ~/.claude/lib
cp /tmp/atomic-memory/lib/ollama_extract_core.py ~/.claude/lib/

# ── 規則模組 ──
mkdir -p ~/.claude/rules
cp /tmp/atomic-memory/rules/core.md ~/.claude/rules/

# ── Tools ──
mkdir -p ~/.claude/tools/memory-vector-service
mkdir -p ~/.claude/tools/workflow-guardian-mcp
cp /tmp/atomic-memory/tools/ollama_client.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/memory-audit.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/memory-write-gate.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/memory-conflict-detector.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/memory-peek.py ~/.claude/tools/           # V4.1
cp /tmp/atomic-memory/tools/memory-undo.py ~/.claude/tools/           # V4.1
cp /tmp/atomic-memory/tools/memory-session-score.py ~/.claude/tools/  # V4.1
cp /tmp/atomic-memory/tools/conflict-review.py ~/.claude/tools/       # V4 裁決
cp /tmp/atomic-memory/tools/init-roles.py ~/.claude/tools/            # V4 多職務
cp /tmp/atomic-memory/tools/rag-engine.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/read-excel.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/unity-yaml-tool.py ~/.claude/tools/
cp /tmp/atomic-memory/tools/memory-vector-service/* ~/.claude/tools/memory-vector-service/
cp /tmp/atomic-memory/tools/workflow-guardian-mcp/server.js ~/.claude/tools/workflow-guardian-mcp/

# ── 記憶規格 + 領域知識 ──
mkdir -p ~/.claude/memory/unity ~/.claude/memory/_reference
cp /tmp/atomic-memory/memory/_reference/*.md ~/.claude/memory/_reference/
cp /tmp/atomic-memory/memory/unity/*.md ~/.claude/memory/unity/

# ── Workflow 設定 ──
mkdir -p ~/.claude/workflow
[ ! -f ~/.claude/workflow/config.json ] && cp /tmp/atomic-memory/workflow/config.json ~/.claude/workflow/
# 若已存在，改執行 JSON merge（不覆蓋使用者值）

# ── Slash commands (24 個) ──
mkdir -p ~/.claude/commands
cp /tmp/atomic-memory/commands/*.md ~/.claude/commands/

# ── MCP server template + ensure-mcp hook ──
cp /tmp/atomic-memory/mcp-servers.template.json ~/.claude/
[ -f /tmp/atomic-memory/hooks/ensure-mcp.py ] && cp /tmp/atomic-memory/hooks/ensure-mcp.py ~/.claude/hooks/
```

### Step 3：合併 settings.json hooks 區塊（最關鍵）

**不能直接覆蓋**。AI 讀使用者 `settings.json.backup`，只合併 `hooks` 區塊，保留 `permissions`。

目標結構（`permissions` 保留使用者原有）：

```jsonc
{
  "permissions": { /* 保留使用者原本的 */ },
  "hooks": {
    "SessionStart": [{"hooks": [{"type":"command", "command":"python \"$HOME/.claude/hooks/workflow-guardian.py\"", "timeout":5}]}],
    "UserPromptSubmit": [{"hooks": [{"type":"command", "command":"python \"$HOME/.claude/hooks/workflow-guardian.py\"", "timeout":3}]}],
    "PostToolUse": [{"matcher":"Edit|Write|Read|Bash", "hooks":[{"type":"command", "command":"python \"$HOME/.claude/hooks/workflow-guardian.py\"", "timeout":3}]}],
    "PreCompact": [{"hooks": [{"type":"command", "command":"python \"$HOME/.claude/hooks/workflow-guardian.py\"", "timeout":5}]}],
    "Stop": [{"hooks":[
        {"type":"command", "command":"python \"$HOME/.claude/hooks/workflow-guardian.py\"", "timeout":5},
        {"type":"command", "command":"python \"$HOME/.claude/hooks/quick-extract.py\"", "async":true, "timeout":30}
    ]}],
    "SessionEnd": [{"hooks": [{"type":"command", "command":"python \"$HOME/.claude/hooks/workflow-guardian.py\"", "timeout":30}]}]
  }
}
```

> **Python 指令**：若使用者系統是 `python3` 而非 `python`，AI 要全部改成 `python3 ...`。先跑 `python --version` 確認。

### Step 4：npm 全域套件 + `~/.claude.json` MCP 合併

讀 `~/.claude/mcp-servers.template.json` 的 `servers` 清單，把有 `npm_package` 的用 `npm i -g` 裝起來：

```bash
# 當前清單（template 內容為真源，以 template 為準；範例）：
npm i -g computer-use-mcp     # MCPControl：螢幕/滑鼠/鍵盤
npm i -g @playwright/mcp      # playwright：瀏覽器自動化
```

合併 `~/.claude.json` 的 `mcpServers` 欄位（冪等，不覆蓋使用者已有 server）：

```
讀 ~/.claude/mcp-servers.template.json 的每個 server
→ 找出對應 npm 全域套件位置（Windows: %APPDATA%/npm/node_modules/{pkg}，Unix: $(npm root -g)/{pkg}）
→ 在 ~/.claude.json.mcpServers 加入 entry：
    {
      "<name>": {
        "command": "node",           // Windows 用 node.exe 絕對路徑更穩
        "args": ["<絕對路徑>/dist/main.js"],   // entry_relative 來自 template
        "type": "stdio"
      }
    }
→ 對於 npm_package=null 的 server（如 workflow-guardian），用 entry_absolute 並把 {claude_dir} 展開為 $HOME/.claude
```

關鍵規則：
- **全域安裝 + 絕對路徑**，不要用 `cmd /c npx`（VSCode 擴充環境不穩）
- Windows: `C:\\Program Files\\nodejs\\node.exe` + `C:\\Users\\{user}\\AppData\\Roaming\\npm\\node_modules\\{pkg}\\...`
- 若 `~/.claude.json` 已有同名 server，**不覆蓋**，跳過並回報使用者

### Step 5：初始化個人記憶層

若 `~/.claude/memory/MEMORY.md` 不存在才建。已存在**不動**（使用者可能已有累積）。

AI 把下列 template 寫入（若缺）：
- `memory/MEMORY.md` — atom 索引骨架
- `memory/preferences.md` — 使用者偏好初始空殼
- `memory/decisions.md` — 全域決策初始空殼

---

## 4. Ollama + Vector Service

### 4.1 Ollama 模型

```bash
# Embedding（語意搜尋）
ollama pull qwen3-embedding            # 需 AVX2 CPU（2013 後多數 CPU）
# 或 ollama pull qwen3-embedding:0.6b  # 小模型，無 AVX2 限制

# 本地 LLM（快篩）
ollama pull qwen3:1.7b                 # ~1.2 GB

# V4.1 rdchat 主萃取 LLM（深度萃取 + L2 決策結構化）
ollama pull gemma4:e4b                 # ~5 GB
```

### 4.2 Python 套件

```bash
pip install lancedb>=0.20                # Vector DB（需 AVX2）
pip install sentence-transformers>=4.0   # Fallback embedding
# 無 AVX2: pip install chromadb 並改 config.json 的 vector_search.fallback_backend
```

### 4.3 Vector Service 啟動

```bash
cd ~/.claude/tools/memory-vector-service
pip install -r requirements.txt

# 啟動（背景）
python ~/.claude/tools/memory-vector-service/service.py &

# 驗證
curl -s http://127.0.0.1:3849/health
# 預期: {"status":"ok", ...}

# 建立完整索引
curl -s http://127.0.0.1:3849/index/full
# 預期: {"indexed":N, "chunks":M}
```

> Vector Service 在每次 session 啟動時由 Guardian 自動檢查 + spawn，不需常駐。

### 4.4 （可選）遠端 Ollama Backend

若使用者團隊有 GPU 伺服器（Open WebUI + Ollama），編輯 `~/.claude/workflow/config.json` 的 `vector_search.ollama_backends`：

```jsonc
"ollama_backends": {
  "rdchat-direct": {
    "base_url": "http://<your-gpu-server>:11434",
    "llm_model": "gemma4:e4b",
    "embedding_model": "qwen3-embedding:latest",
    "priority": 1,
    "enabled": true
  },
  "rdchat": {
    "base_url": "https://<your-rdchat-proxy>/ollama",
    "auth": {
      "type": "bearer_ldap",
      "login_url": "https://<your-proxy>/api/v1/auths/ldap",
      "password_file": "~/.claude/workflow/.rdchat_password"
    },
    "llm_model": "gemma4:e4b",
    "embedding_model": "qwen3-embedding:latest",
    "priority": 2,
    "enabled": true
  },
  "local": { "base_url": "http://127.0.0.1:11434", "llm_model": "qwen3:1.7b", "priority": 3 }
}
```

**密碼檔**（gitignored，絕不 commit）：

```bash
echo "你的 LDAP 密碼" > ~/.claude/workflow/.rdchat_password
```

帳號自動取 `os.getlogin()`。三階段退避：正常 → Short DIE 60s → Long DIE 等下個 6h 邊界（0/6/12/18）。

---

## 5. 驗證 Checklist（AI 逐項確認）

跑完下面每條，把結果表格化回報給使用者：

| # | 驗證項 | 指令 / 方法 | 通過標準 |
|---|--------|------------|---------|
| 1 | Python 套件 | `python -c "import lancedb; import sentence_transformers"` | 無 ImportError |
| 2 | Ollama 模型 | `ollama list` | `qwen3-embedding` + `qwen3:1.7b` + `gemma4:e4b` 全在 |
| 3 | Hook 可執行 | `echo '{"hook_event_name":"SessionStart","session_id":"test","cwd":"/tmp"}' \| python ~/.claude/hooks/workflow-guardian.py` | 輸出 JSON 含 `additionalContext` |
| 4 | Vector Service | `curl -s http://127.0.0.1:3849/health` | `{"status":"ok"}` |
| 5 | Memory 健檢 | `python ~/.claude/tools/memory-audit.py` | 無 ERROR |
| 6 | V4 `_roles.md` | `ls ~/.claude/memory/_roles.md 2>/dev/null` | 單人環境**可不存在**（多職務未啟用）；團隊模式應存在 |
| 7 | V4.1 commands | VS Code 中按 `/` 能看到 `/memory-peek` `/memory-undo` `/memory-session-score` | 三個 skill 皆出現 |
| 8 | MCP servers | 檢查 `~/.claude.json` 的 `mcpServers` 含 template 內 server | MCPControl + playwright + workflow-guardian 至少有 |
| 9 | 整合驗證 | 開新 Claude Code session | 看到 `[Workflow Guardian] Active` |

---

## 6. V2 / V3 → V4.1 升級

已安裝舊版使用者：

```bash
cd ~/.claude && git pull
```

補確認：

- [ ] `hooks/` 存在這些 V4 / V4.1 新模組：`wg_roles.py` / `wg_user_extract.py` / `wg_session_evaluator.py` / `user-extract-worker.py`
- [ ] `lib/ollama_extract_core.py` 存在
- [ ] `commands/` 含 `memory-peek.md` / `memory-undo.md` / `memory-session-score.md` / `conflict-review.md` / `init-roles.md`
- [ ] `workflow/config.json` 含 `userExtraction` / `docdrift` / `hot_cache` sections（若缺，補預設值，不覆蓋既有）
- [ ] `settings.json` 的 `Stop` hook 有 async `quick-extract.py` entry
- [ ] `mcp-servers.template.json` 在 `~/.claude/` 根目錄

> 多職務團隊若要啟用 V4 scope 分層：在專案裡執行 `/init-roles`，會建立 `memory/shared/_roles.md` + `role/{name}/` 目錄。

---

## 7. 常見問題 FAQ

### Q: 安裝後 Claude Code 啟動變慢？
**A**: V4.1 SessionStart 去重 + 非阻塞 vector 啟動，延遲 50-200 ms。每次 prompt 額外 200-500 ms（向量搜尋）。首次 prompt 較慢（500-1500 ms，episodic context search）。

### Q: Vector Service 啟動失敗？
**A**: 檢查 `pip install lancedb` 是否成功（需 AVX2）。Port 3849 被佔用時改 `config.json.vector_search.service_port`。無 AVX2 CPU 改用 ChromaDB 並設 `fallback_backend`。

### Q: Ollama embedding timeout？
**A**: 模型首次載入 5-10 秒，之後常駐 RAM（~1-2 GB）。確認 `ollama list` 有顯示正確模型；無反應檢查 Ollama daemon（`systemctl status ollama` 或 Windows 工作管理員）。

### Q: Hook 執行但 atom 沒載入？
**A**: 確認 `MEMORY.md` 的 Trigger 欄位含 prompt 中的關鍵字。Atom 檔案路徑正確（相對 `~/.claude/`）。可開 `/atom-debug` 打開注入 debug log。

### Q: V4.1 使用者決策萃取可以關嗎？
**A**: `workflow/config.json` 設 `"userExtraction.enabled": false`。只想降低負擔但保留偵測：設 `"userExtraction.tokenBudget"` 為更低（預設 240）。

### Q: V4 多人分層要怎麼設？
**A**: 先 `/init-roles` 建 `memory/shared/_roles.md` 白名單與 `role/{name}/` 目錄，管理職用 `/conflict-review` 裁決 `shared/_pending_review/` 敏感原子。

### Q: 不想要某些功能？
**A**: `config.json` 個別關：
- `"enabled": false` → 關整個 Guardian
- `"vector_search.enabled": false` → 關語意搜尋（僅 keyword）
- `"response_capture.enabled": false` → 關回應萃取
- `"cross_session.enabled": false` → 關跨 session 鞏固
- `"docdrift.enabled": false` → 關文件漂移偵測

### Q: 沒有 GPU 能用嗎？
**A**: 可以。Ollama CPU fallback 約 200-500 ms（embedding）、1-3 s（qwen3:1.7b）。想加速可設定遠端 rdchat-direct backend（第 4.4 節）。

### Q: 完全移除？
**A**: 刪 `settings.json` 的 hooks 區塊 → 刪 `~/.claude/hooks/` `~/.claude/tools/` `~/.claude/memory/` 等目錄。Claude Code 本體零修改，移除無殘留。

---

## 8. 清理暫存

```bash
rm -rf /tmp/atomic-memory
```
