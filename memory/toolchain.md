# 工具鏈實戰記憶

- Scope: global
- Confidence: [固]
- Trigger: 工具, 環境, 指令, command, path, 路徑, bash, git, python, npm, ollama
- Last-used: 2026-03-11
- Confirmations: 19
- Type: procedural
- Tags: toolchain, environment, commands
- Related: hardware

## 知識

### Windows 環境差異

- [固] Claude Code 的 bash 環境是 MSYS2，路徑格式 `/c/Users/` 而非 `C:\Users\`，但 Python Path 物件自動轉換
- [固] Windows 上 bash 指令的 `/dev/null` 有效（MSYS2 模擬），不需改成 `NUL`
- [固] `timeout` 指令在 MSYS2 bash 不可用，需用 Python 的 subprocess timeout 或其他替代
- [觀] Windows 環境變數用 `$env:VAR`（PowerShell）或 `$VAR`（bash），混用易出錯

### 已驗證的指令組合

- [固] Ollama 啟動: `ollama serve`（背景）→ `ollama list`（驗證模型可用）
- [固] 向量服務啟動: `python ~/.claude/tools/memory-vector-service/service.py`（port 3849）
- [固] 向量健康檢查: `curl http://127.0.0.1:3849/health`
- [固] 記憶格式檢查: `python ~/.claude/tools/memory-audit.py`

### 路徑與版本

- [觀] Python: Windows 預設路徑 — 需確認具體 session 中的 `which python` 結果
- [觀] Node.js: 用於 inbox-check.js hook — 需確認版本
- [固] Ollama models 位置: 預設 `~/.ollama/models/`
- [固] ChromaDB 資料: `~/.claude/memory/_vectordb/`

### 環境特殊配置

- [固] ChromaDB 用 SQLite backend（i7-3770 不支援 AVX2，預設 HNSW backend 會 crash）
- [固] Ollama 同時只能跑一個模型（GTX 1650 4GB VRAM 限制），embedding 和推論模型需輪替
- [固] workflow-guardian.py stdout/stderr 強制 UTF-8（Windows 預設 cp950 會導致中文亂碼）

## 行動

- build/setup/config intent 時自動載入
- 成功執行新工具指令後，評估是否值得記錄（跨 session 重用性 ≥ 2 次預期）
- 環境問題 debug 時，優先查此 atom 再嘗試盲目探索
- 版本資訊在確認後更新，不猜測

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-10 | 初始建立：從 hardware.md + decisions.md 整理已知工具鏈知識，4 大分類 | manual |
| 2026-03-10 | [觀]→[固] 定期檢閱晉升，Confirmations=4 | periodic-review |
