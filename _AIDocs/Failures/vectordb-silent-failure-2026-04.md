# VectorDB Silent Failure — 2026-04

> 12 天假陽性 → 根因 + 修補 + REVIVE 決策。
> Linked: `plans/memory-cleanup-2026-04-27/synthesis_and_plan_v2.md §修訂 #4`、`follow_up_issues.md §議題 #2/#5/#6`
> 沉澱於：Wave 3a (commit 2b3f7a3)、Wave 3b（本次）

## 觸因

清理 plan v2 機制驗證者於 2026-04-28 比對 `workflow-guardian.py` 的 vector subsystem 啟動鏈與真實檔案系統時發現：

- `vs_script = tools/vector-service.py`（寫死字面值）
- 真實檔案在 `tools/memory-vector-service/service.py`
- subprocess.Popen 必失敗 → vector service 從未真正啟動
- 即使如此，line 632 仍**無條件寫入** `vector_ready.flag` → 注入路徑誤判 vector 已就緒
- 12 天無人察覺：fail-closed 太靜默 + silent failure 不可觀察

## 根因兩層

| 層 | 缺陷 | 影響 |
|----|------|------|
| 1 路徑寫死 | 重構後 `vector-service.py` 改名 / 搬目錄但 hook 沒同步 | service 啟動 100% 失敗 |
| 2 flag 寫入無 gate | poll 失敗仍寫 ready flag | 注入路徑信任 flag → 假陽性 |

bg subprocess `stdout/stderr` 都導向 DEVNULL → 啟動失敗無痕跡，連 stderr log 都沒有。

## Wave 3a 修補（commit 2b3f7a3，2026-04-28）

1. **路徑修正**：`workflow-guardian.py:621` 改為 `CLAUDE_DIR / "tools" / "memory-vector-service" / "service.py"`
2. **Health-gate flag**：`workflow-guardian.py:663-667` poll loop 結束後僅在 health 200 成功時才 `flag_path.write_text("ready")`
3. **觀察儀表**：`wg_intent._log_vector_obs` + RotatingFileHandler 寫 `~/.claude/Logs/vector-observation.log`
   - schema：`{ts, session_id, fn, flag_state, result_count, fallback_used, [intent, use_sections, err]}`
   - 主 hook 出口 + SessionStart bg subprocess probe 兩處覆蓋
4. **bg subprocess 加 health 探測 + probe** 寫 sibling log `vector-observation-probe.log`

## Wave 3b 決策（2026-04-28，本次）

原計畫 D4 是「4 天觀察期 → 等使用者主訴 atom 沒命中」。使用者點出 silent failure 不可觀察 + 4 天太慢，改為 probe burst：

- 工具：`tools/vector-probe-burst.py`
- 設計：30 高命中查詢（與已有 atom/episodic 重疊）+ 30 中機率 + 30 低/邊界（莎士比亞、量子糾纏、Eiffel Tower 等）
- 路徑：每 query 透過 `wg_intent._search_episodic_context` 與 `_semantic_search` 各跑一次（180 calls）
- summary：`tools/vector-observation-summary.py` 讀全 log，閾值 REVIVE ≥ 50% / RETIRE ≤ 5% + fallback ≥ 80% / 其他 GRAY

**結果**：
- 總紀錄 193（含先前 SessionStart probe 累積）
- vector 命中 163 / vector miss 23 / fallback 7 / error 5
- **命中率 87.6%**（163 / (163+23) ready 記錄）
- fallback rate 3.6%
- **判定 REVIVE**

**大師席次**：
- CC 寫手（執行）
- CC 稽核 PASS（query 設計合理 / verdict 邏輯無 bug / bucket-C 高命中是 ranked min_score 偏寬鬆，非 verdict-validity 問題）
- Codex 紅隊 proceed-with-note：log 無 atom 內容洩漏（schema 純 metadata）；hot_cache 未污染（burst session_id 隔離）；ReadHits 未污染（burst 不走主 hook 注入路徑）；`service.py` HTTP log_message 將 `q=...` 全路徑寫入 stderr → service.log 是 pre-existing privacy footgun，**非本 wave 引入**，已記入 follow_up_issues.md §議題 #6

**未執行**：D5 RETIRE 分支（保留 lance / commands/vector.md / commands/conflict.md / wg_intent vector 路徑）

## 教訓沉澱（待 Stage H 寫成 atom）

1. **寫死綁定特定 plan 的 SessionStart hook 模式禁止** — phase6 hook 與 vs_script 路徑兩例
2. **bg subprocess 啟動失敗必須有 stderr log 出口、不可導向 DEVNULL 後寫 ready flag** — flag 寫入前必須有 health-200 gate
3. **silent-failure 風險的 stage 必須加 log 採樣 + probe burst 加速** — 不依賴使用者主訴；4 天觀察期一旦進入「等使用者察覺」即破功

## Follow-up 連帶

- 議題 #2（根因深挖）：本次已部分回答（路徑寫死 = 重構漏改、12 天無人察覺 = silent failure 本就不可見）。剩餘：git log 找出哪個 commit 引入路徑寫死。
- 議題 #6（新增）：ranked search min_score 偏寬鬆 + service.py 查詢字串寫 stderr 兩個 follow-up，待另開 session 處理。
