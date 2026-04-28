# 指標型 atom — 設計顆粒原則

- Scope: global
- Confidence: [臨]
- Trigger: 寫 atom, atom 設計, 縮影, atom 顆粒, 指標型, atom 重構, atom 規則
- Last-used: 2026-04-28
- Confirmations: 0
- ReadHits: 5
- Related: feedback-memory-path, decisions, decisions-architecture, feedback-codex-companion-model

## 印象

- atom 不是 md 縮影；內容若 `_AIDocs/` md 已有 → 必改寫「印象 + → md anchor」格式
- atom 是**功能型單元**：印象（為什麼/何時激活）+ 行動（命中後做什麼）；禁止「知識描述」段（那是 md 職責）
- 「固」級邏輯 → 程式碼化（hook），不該每次讓 LLM 讀 atom 判斷 → _AIDocs/Architecture.md hook 表
- 「臨/觀/固」穩定度維度屬實驗性想法，本規則不依賴此維度定型其他規則

## 紅色指標（失敗模式）

- **縮影 atom**：抄 _AIDocs/ md 子段落 → 雙重維護 + 過時即 drift + ReadHits 通常 0（系統需要詳情會直接讀 md）
- **混型 atom**：同檔混「知識/印象/行動」三段 → 顆粒過粗，命中時注入冗餘
- **代 hook atom**：「固」級邏輯寫成 atom 規則 → 應 hook 化
  - 已落地範例（2026-04-28）：feedback-memory-path / feedback-no-test-to-svn → `hooks/wg_pretool_guards.py`
  - hook 化後 atom 仍保留作 LLM 提示錨點（hook 訊息指回 atom）— 不是「刪 atom 改 hook」二選一

## 行動

- 寫 atom 前自問：(1) `_AIDocs/` 已有？→ 改指標；(2) 行動段能否寫 ≥ 3 條？否 → 這個 atom 不該存在；(3) 邏輯是「固」嗎？→ 評估 hook 化
- 印象段每條 ≤ 30 字 + → 指針；超過代表該住 md
- 整檔 ≤ 20 行（含 frontmatter，行動段例外可放寬）；超過拆或剝知識
- 既有 atom 改寫：先剝「知識描述」段（搬 _AIDocs/ 或刪）→ 保留印象 + 行動
- 健康度檢測：`atom-health-check.py --shadow-check` 已落地（2026-04-28）— 比對 atom `## 印象` / `## 知識` 段 vs `_AIDocs/**/*.md` 子段落 SequenceMatcher.ratio ≥ 0.7 標 warning（不影響 health 總計）。dry-run 全 31 atoms：top 0.333、buffer 充足，0.7 default 確認合理；偵測器以 deliberate copy 驗證 ratio=1.000 命中
