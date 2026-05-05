# 與 Codex 協作守則（高水準同步認知與互助）

- Scope: global
- Confidence: [臨]
- Trigger: codex, codex exec, gpt-5, codex companion, second opinion, 第二觀點, 雙 LLM, 大師會議, 異議審查
- Related: feedback-codex-companion-model, decisions, feedback-research-first, feedback-end-to-end-smoke

## 知識

> 由 2026-04-26 單次 v1→v2→v3→v4→v5 多大師會議實戰萃取（Codex Companion 重構計畫）。**單次經驗**，未經跨 session 驗證；多數條目暫列 [臨]/[觀]，待後續實戰驗證後再考慮晉升。

### 1. Sandbox 統一策略（致命教訓 R2-5 — 已實證一次）
- [觀] 任何 codex exec 呼叫（含 Companion 內部 + 人工 ad-hoc）建議**不傳 `-s` 旗標**，沿用 user `~/.codex/config.toml` 預設（`danger-full-access`）
- [觀] Windows `-s read-only` 觀察到踩 `CreateProcessWithLogonW failed: 1385` sandbox 啟動失敗（已實證 1 次）；`-s workspace-write` 是否同樣失敗未實測
- [臨] 約束靠 prompt 內紅線：「禁止 git/edit/write/rm/mv/mkdir/touch；只允許 cat/grep/rg/Get-Content」— 紅線有效性未長期觀察
- [觀] 案例：Codex Companion Phase 1 因 assessor.py 寫死 `-s read-only`，從上線到本次審查從未真的成功跑過 codex assessment（已用 grep 驗證且觀察 log 確認 1385 錯誤）

### 2. 同步資訊：每次 brief 必含 5 件事
- [固] codex 是 ephemeral 無記憶（規格事實，已知）
- [臨] 自包含 brief 模板：(1) 完整現況 (2) 明確要讀的檔案絕對路徑清單 (3) 角色限定 (4) 沙盒指引 (5) 輸出格式約束
- [臨] 各條的必要性與最佳實作待後續多次 codex 召開驗證

### 3. 防贅字三紅線
- [臨] **禁開場白**：「我會先讀…」「我來查一下…」→ prompt 寫「直接條列答案」
- [臨] **禁問題重述** → prompt 寫「不要重述問題」
- [臨] **禁客套** → prompt 寫「不要 praise / 鼓勵語」
- [觀] codex 即使有上述紅線仍會在 reasoning 階段冒出英文獨白「Considering / Evaluating / Planning」；目前無法禁止
- [臨] 紅線實際生效程度待長期觀察

### 4. 規則同步：摘要不全套
- [臨] 不塞 IDENTITY.md / CLAUDE.md 全文，只擷取相關硬規則摘要
- [臨] codex `~/.codex/config.toml` 已有 `developer_instructions` 包含通用約束，不必重複
- 待驗證：什麼程度的摘要算「夠用」、什麼算「過簡」

### 5. 質量 Gate：迭代審查直到收斂
- [觀] **第一階**：分角色 codex 大師會議（divergent，4 位視角）— 已實證 1 次有效
- [觀] **第二階**：codex 異議審查（convergent，把 plan 交回 codex 找漏洞）— 已實證 3 round 有效抓出真實 bug
- [臨] **第三階及之後**：再次審查直到 codex 回「無異議」或重大問題清空
- [臨] 每輪上限 2-3 round，超過 escalate user — 數字 2-3 為單次經驗，未驗證
- [觀] 異議審查能抓出 Claude 自己沒察覺的角色矛盾（v3 D4）與架構假設破洞（v4 R2-5）— 已實證
- [臨] 從 round N 起異議數遞減為「收斂判定」標準 — 單次經驗，未跨多計畫驗證

### 6. 何時用 codex / 何時不用
- [臨] **用**：設計決策、架構審查、跨領域第二觀點、Claude 易盲點區
- [臨] **不用**：純執行、規格已明確、改 < 5 行
- [臨] 成本估算：每次 codex exec ~0.5-2K tokens；4 場會議 ~10K — 待實際統計

### 7. 結果處理
- [觀] **永不直接採納**：codex 建議須通過 Claude 收斂審查才落地（codex 無 BLOCK 權，純 advisory）— 本次 plan 已落地此原則
- [臨] **記錄出處**：plan / commit / atom 內標 codex 建議來源
- [觀] **真實 bug 例外**：codex 指出真實 bug 且 Claude grep 驗證屬實 → 立即修 + 記入 failure atom（已實證 1 次：R2-5 致命根因）
- [觀] codex 引述 URL 通常準確但需 Claude 用內部知識庫交叉驗證（v5 R3 案例已實證）

### 8. End-to-End Smoke 強制（最痛教訓 R2-5）
- [觀] 詳見 `feedback-end-to-end-smoke.md`（獨立 atom）— 已實證一次案例

## 行動

- 召開 codex 大師會議：用 brief 模板 (5 件事) + 4 角色聚焦並行 + 守則 §3 三紅線
- 收斂審查：codex round → Claude 整合 → 再 codex round；達 diminishing return 才結束
- 整合系統上線：先 Phase -1 smoke + log 觀察 + 記錄基準，不可直接宣告上線
- 對 Codex Companion 後續修改：嚴守 advisory only，BLOCK 權只給同步 heuristics
