# 整合系統上線前 E2E Smoke 強制

- Scope: global
- Confidence: [臨]
- Trigger: 上線, 部署, 整合測試, smoke test, 系統驗證, hook 系統, 子程序整合, codex 整合, ollama 整合, mcp 整合, daemon 啟動
- Last-used: 2026-04-26
- Confirmations: 0
- ReadHits: 0
- Related: feedback-codex-collaboration, feedback-research-first, feedback-fix-on-discovery, decisions, feedback-codex-companion-model, feedback-pre-completion-test-discipline, feedback-silent-failure-instrumentation

## 知識

> 由 2026-04-26 單次案例萃取（Codex Companion Phase 1 致命根因 R2-5）。**單次經驗，未經跨多 case 驗證**。

### 痛教訓案例（2026-04-26 Codex Companion Phase 1）
- [觀] Codex Companion Phase 1 commit 22d9d3b 上線後，從未真的成功跑過一次 codex assessment（已用 grep + log 驗證）
- [觀] 根因：[tools/codex-companion/assessor.py:110](tools/codex-companion/assessor.py#L110) 寫死 `-s read-only`，Windows 該模式經 `CreateProcessWithLogonW` 啟 sandbox 失敗（error 1385）
- [觀] 失敗訊號被吞：codex stdout 為空 → assessor 寫 `summary: "Codex returned empty response"` → 看起來像 LLM 偶發空回，沒人察覺是 spawn 失敗
- [觀] 識破過程：v4 多大師審查 grep 到 `-s read-only` 寫死 + 比對 user 手動 codex smoke test 行為差異 + 內部 log 出現 1385 錯誤

### 推測守則（待多案例驗證再晉升）
- [臨] 任何整合系統上線前手動 trigger 真實事件 + cat 結果檔 + 肉眼確認 status 不是 error/empty/含糊訊息
- [臨] 失敗訊號不可吞：catch exception 後寫具體 category + summary（如 `category: system, summary: "Codex sandbox 1385 失敗"`），禁止「empty response / unknown error / failed」這種讓人無法判斷的詞
- [臨] 上線基準必須記錄：修改前的成功率 / 平均回應時間 / token cost
- [臨] 適用範圍候選：codex / ollama / MCP server / daemon / hook 子程序 / 任何跨進程整合 — 待後續案例確認

### 適用場景判定（待驗證）
- [臨] 涉及 spawn 子程序、跨進程通訊、外部 binary 呼叫 → 必做 smoke
- [臨] 純 Python lib import / 純檔案讀寫 → 可省 smoke（單元測試足夠）
- [臨] 沙盒/權限/環境變數相關 → 必做 smoke（最容易踩平台特定坑）

### 真實根因分層現象（2026-04-27 Sprint 0 觀察）
- [臨] 「致命根因」常是分層失敗：第一層修了下一層才暴露。本案例 plan v5 假設根因是 sandbox 1385，Sprint 0 移除 `-s read-only` 後 log 才揭出更早的 PATH 失敗（npm global bin 不在 service 子程序 PATH 中）。**經驗**：根因修補後立即重跑 e2e + 看 log，不要假設一修就完；做 smoke 時要為「修了之後仍失敗」的 next 層失敗訊號做準備

## 行動

- 任何「上線」commit 前先做手動 smoke test，並把 smoke 步驟寫入 plan 的 Phase -1
- 失敗訊號要 escalate（assessment 寫具體錯誤）而非吞掉
- 修整合系統時優先檢查「失敗路徑」而非「成功路徑」
- Code review 時看到 `except: pass` 或籠統 error 訊息要立即標出
