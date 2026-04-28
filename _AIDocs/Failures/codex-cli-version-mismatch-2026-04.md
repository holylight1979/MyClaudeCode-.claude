# Codex CLI / Model 版本鎖定不一致

> Date: 2026-04-27 觀察 / 2026-04-28 整理進 _AIDocs

## 現象

User 升 `~/.codex/config.toml` 的 `model = "gpt-5.5"`，但 codex CLI 還停在 0.123.0（不認識 gpt-5.5）→ 所有 `codex exec` assessment 全失敗，`status=error`、看似空回但實際是 HTTP 400「requires a newer version of Codex」。

## 根因

「永遠用最新版」策略（[memory/feedback/feedback-codex-companion-model.md](../../memory/feedback/feedback-codex-companion-model.md)）的副作用：升 model 名稱與升 CLI 二進位是**兩個獨立動作**，沒有連動機制。

## 對策（任一即可，建議全做）

1. **流程**：升 `~/.codex/config.toml` model 後立刻 `npm i -g @openai/codex`，作為單一 routine
2. **commit message**：升 model 配置時在 commit message 提示「需 codex CLI ≥ X」
3. **程式偵測**：[tools/codex-companion/assessor.py](../../tools/codex-companion/assessor.py) 偵測「requires a newer version of Codex」400 訊息 → 給明確 escalation（不再吞為泛 error）

## 連動

- atom：[memory/feedback/feedback-codex-companion-model.md](../../memory/feedback/feedback-codex-companion-model.md)
- 鄰近失敗：[codex-windows-sandbox-1385.md](codex-windows-sandbox-1385.md)（Codex 另一類啟動失敗）
