# Codex Companion model 與 ChatGPT Pro 成本框架

- Scope: global
- Confidence: [臨]
- Trigger: codex, codex companion, codex_binary, codex CLI, codex model, gpt-5, gpt-5-codex, gpt-5.4, gpt-5.5, model 升級, codex 升級, npm i codex, ChatGPT Pro, OpenAI 訂閱
- Last-used: 2026-04-28
- Confirmations: 0
- ReadHits: 0
- Related: feedback-codex-collaboration, feedback-end-to-end-smoke, feedback-pointer-atom

## 印象

- `workflow/config.json:codex_companion.model` 必須維持空字串 `""`（由 `~/.codex/config.toml` default 決定）→ user 升一處全部跟著升 → 契約 _AIDocs/DocIndex-System.md:152
- ChatGPT Pro 訂閱（2026-04-27 確認 Plus 20× / Codex 最大存取 / 前沿 Pro）→ Codex/Companion 設計**不算 token 帳單成本**，只看干擾度 / 漏審查 / 時延
- CLI 版本鎖定踩坑：model 升 CLI 沒升 → 400「needs newer Codex」→ _AIDocs/Failures/codex-cli-version-mismatch-2026-04.md

## 行動

- 看到 `codex_companion.model` 被寫死具體名稱 → 立即改回 `""` 並提醒原因
- 升級 user `~/.codex/config.toml` model 後 → 提示順手 `npm i -g @openai/codex` 升 CLI
- Codex Companion 機制設計決策時不必算 token 帳，**Score gate / dedup 傾向「多打不少打」優先收集數據**
- assessor.py 失敗訊號分類時，「model not supported」設為獨立 category 而非泛 error
