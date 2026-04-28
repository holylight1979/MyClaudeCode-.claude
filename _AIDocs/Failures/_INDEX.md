# Failures — 踩坑記錄與失敗模式

> 跨專案累積的環境陷阱、假設錯誤、靜默失敗、認知偏差、誤診案例
> 最近更新：2026-04-28

---

## 文件清單

| # | 文件 | 說明 | keywords |
|---|------|------|----------|
| 1 | env-traps.md | Windows/MSYS2/Node.js/Ollama/MCP/VSCode 環境踩坑 | Win環境陷阱, Windows, MSYS2, Node.js, npx, Ollama, port, MCP啟動, VSCode |
| 2 | wrong-assumptions.md | 假設錯誤案例（直覺偏差、空目錄、metrics 異常） | 假設錯誤, 直覺偏差, 為何沒生效, 空目錄, metrics異常, 功能沒反應 |
| 3 | silent-failures.md | 靜默失敗案例（看似正常實際沒生效） | 靜默, silent, 看似正常, setdefault, knowledge_queue為空, 吞掉錯誤 |
| 4 | cognitive-patterns.md | 認知偏差案例（過度工程、代理指標） | 過度工程, 代理指標, proxy metric, AI看不懂, AI在打轉, 品質回饋 |
| 5 | misdiagnosis-verify-first.md | 誤診案例 + 驗證優先原則 | 誤診, 驗證優先, verify first, 診斷失敗, 先射箭再畫靶, 假設錯誤就規劃, 過度規劃, 沒驗證就動手 |
| 6 | vectordb-silent-failure-2026-04.md | VectorDB 12 天假陽性 — 路徑寫死 + flag 無 gate；Wave 3a 修補 + Wave 3b REVIVE 決策 | vector, lance, silent failure, vector_ready, flag, 假陽性, bg subprocess, DEVNULL, probe burst |
| 7 | codex-windows-sandbox-1385.md | Codex `-s read-only` 在 Windows 因 `[windows] sandbox = "elevated"` 觸發 `CreateProcessWithLogonW failed: 1385`；修補 = `-c 'windows.sandbox="unelevated"'` | codex, sandbox, 1385, CreateProcessWithLogonW, windows, elevated, unelevated, logon type |
| 8 | codex-cli-version-mismatch-2026-04.md | model 升 (`gpt-5.5`) 但 codex CLI 沒升 → 400「needs newer Codex」；對策：升 model 同時 `npm i -g @openai/codex` + assessor.py 偵測 400 訊息獨立分類 | codex, CLI 版本, gpt-5.5, model 升級, npm i codex, 400 needs newer, version mismatch |
