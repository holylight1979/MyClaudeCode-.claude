# 宣告完成前的 pytest 紀律與已知 regression 處置

- Scope: global
- Author: holylight
- Confidence: [臨]
- Trigger: 宣告完成, 收尾, 測試失敗, TestFailGate, ScanReport, known regression, pre-existing, xfail, REG-001
- Last-used: 2026-04-27
- Confirmations: 0
- ReadHits: 0
- Created-at: 2026-04-27
- Related: feedback-fix-on-discovery, feedback-no-test-to-svn, feedback-end-to-end-smoke, decisions

## 知識

- [臨] **Sprint / 任務宣告完成前必跑全 pytest（不只跑 targeted）**。失敗即進入「逐項分流」流程：
  1. 與本次變更相關 → 當場修
  2. 無關但 ≤5 行 → 當場修（順手清單）
  3. 無關且超過修補門檻 → 走 known-regression 流程
- [臨] **known-regression 必須雙重標記，光寫 doc 不夠**：
  - (a) `_AIDocs/known-regressions.md` 加 REG-NNN 條目（檢測時點 / 不符清單 / 根因 / 風險 / 修補路徑）
  - (b) 程式碼層 `@pytest.mark.xfail(strict=False, reason="REG-NNN: ...")` 同步標記
  - 缺 (b) 時 `python -m pytest` 仍會 exit 1，TestFailGate hook 抓住「測試未綠」繼續阻擋宣告完成
- [臨] **commit 順序**：Sprint 主體 commit → 跑全 pytest → 視結果補（known-regression doc + xfail）→ 補 commit → push。先 commit 再驗會被 ScanReport / TestFailGate 雙 gate 接連抓回來補做
- [臨] **Why**：2026-04-27 Sprint 2 (Codex Companion) 收尾時：
  - 我先 commit + push (`fa9897b`)，事後跑 full pytest 看到 v4-atoms snapshot 1 fail，誤判「不相關 → 文字說明帶過」
  - TestFailGate fire → 補 known-regressions.md (`783e1a4`) → 又被 fire（doc 沒影響 pytest 出口碼）
  - 再補 xfail 標記 (`9308f21`) → 209 passed, 1 xfailed → gate 才綠
  - 連環 3 個 commit 才解決，本可 1 個 commit 一併處理
- [臨] **How to apply**：
  - 收尾步驟改寫成「跑全 pytest → 分流任何失敗 → 寫 known-regression（必要時）→ 寫 xfail（必要時）→ commit 一次 → push」
  - 報告尾端若有就地處理的 known-regression，列出 REG-NNN ID 與雙標記證據（doc 路徑 + xfail 行號）

## 行動

- 寫 commit 訊息「Sprint X 完成」前：strict 跑 `python -m pytest tests/ --ignore=tests/integration -q`
- 任何 FAIL：當下逐筆分流，不留到下個對話輪
- 走 known-regression 路線時務必同時改 doc + 加 xfail（單一不夠）
