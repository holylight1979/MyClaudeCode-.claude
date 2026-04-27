# Codex Companion 跟隨 codex CLI 預設 model

- Scope: global
- Confidence: [觀]
- Trigger: codex, codex companion, codex_binary, codex CLI, codex model, gpt-5, gpt-5-codex, gpt-5.4, gpt-5.5, model 升級, codex 升級, npm i codex
- Last-used: 2026-04-27
- Confirmations: 0
- ReadHits: 0
- Related: feedback-codex-collaboration, feedback-end-to-end-smoke

## 知識

### 主規則
- [觀] Codex Companion 的 `workflow/config.json:codex_companion.model` 必須維持空字串 `""`，禁止寫死具體 model 名稱（如 `o3`、`gpt-5.4`、`gpt-5.5`）
- [觀] **Why**: User 要求「永遠用最新版」。寫死 model 名會讓未來新版發佈時需要回頭改 companion config；空字串讓 [tools/codex-companion/assessor.py](tools/codex-companion/assessor.py) 跳過 `-m` 參數，由 `~/.codex/config.toml` 的 default model 決定，user 只要更新一處就能讓所有 codex 呼叫端跟著升級
- [觀] 已實證一次（2026-04-26 commit 5298e7c）

### How to apply
- [臨] 看到有人把 `codex_companion.model` 改成具體名稱 → 改回 `""` 並提醒原因
- [臨] 若新版 codex CLI 改變 default fallback 機制（例如 `-m` 變必填），需同步更新 [assessor.py](tools/codex-companion/assessor.py) 的條件邏輯
- [臨] 對應 doc：[_AIDocs/DocIndex-System.md:152](_AIDocs/DocIndex-System.md#L152) 已註明此契約

### 副作用 — CLI / model 版本鎖定踩坑（2026-04-27 觀察）
- [臨] 「永遠跟最新」策略副作用：user 升 `~/.codex/config.toml` model 但 codex CLI 沒同步升時踩 400「需要更新 CLI」
- [臨] 本案例：user 改 model = `gpt-5.5` 但 codex CLI 0.123.0 不認識 → assessment 全失敗（status=error，看似空回但實際是 400）
- [臨] **對策**：
  1. 升 model 時順手 `npm i -g @openai/codex` 升 CLI
  2. 或於 commit message 提示 CLI 版本前提
  3. 或 [assessor.py](tools/codex-companion/assessor.py) 偵測「requires a newer version of Codex」400 訊息給明確 escalation（v5 plan Phase 5.1 sandbox 失敗偵測可擴充含此 model-version 失敗）

## 行動

- 看到 codex_companion.model 被寫死具體名稱 → 立即改回 `""`
- 升級 user codex config model 後，提示順手升 codex CLI
- assessor.py 失敗訊號分類時，把「model not supported」當作獨立 category 而非泛 error