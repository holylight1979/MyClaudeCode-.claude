# Wisdom Engine + Fix Escalation Protocol

> 從 Architecture.md 移入（2026-04-17 索引化）。實作：`hooks/wisdom_engine.py`。
> keywords: wisdom, reflection, 反思, fix_escalation, 精確修正升級, situation classifier

## Wisdom Engine 組件

- **情境分類器**：2 條硬規則（file_count/is_feature → confirm；touches_arch → plan）
- **反思引擎**：first_approach_accuracy + over_engineering_rate + silence_accuracy + Bayesian 校準（V2.12 改 sliding window）
- **Fix Escalation Protocol**：同一問題修正第 2 次起強制 6 Agent 精確修正會議，Guardian 自動偵測 + `/fix-escalation` skill 介入

## 版本演進

### V2.12（2026-05-05，Memory 系統 Wave 4）

校準兩個觀察到的偏誤：

1. **Cumulative metrics 比率被歷史拉死** → 改為 sliding window of size 10。`window_size: 10` 從 V2.11 dead schema field 啟用為真實使用。舊累計值（single_file 402/420、architecture 4/32 等）保留至 `legacy_cumulative` 子鍵供查
2. **retry_count 對 architecture 系統性偏誤**（13% 失真低估）→ 兩處校準：
   - `track_retry()` plan-mode 同檔 Edit threshold 從 2 → 4（plan iteration 是設計行為）
   - `reflect()` architecture 容忍 1 retry，但 `fix_escalation_triggered` 是真失敗信號（覆蓋容忍）。`fix_escalation_triggered` 由 workflow-guardian.py 的 Fix Escalation Protocol 注入點 [L1391](../../hooks/workflow-guardian.py) 同步寫入 state

新增 `_migrate_v211_to_v212()` 冪等 migration shim，所有 reader/writer 透過統一通道 `_load_metrics()` 自動觸發。Schema 升 V2.12，`schema_version` 欄位辨識版本。

新增測試（共 36 cases）：
- `tests/test_wisdom_sliding_window.py`（11）
- `tests/test_wisdom_migration.py`（11）
- `tests/test_wisdom_retry_calibration.py`（14）

副作用：SessionStart `[自知]` blind_spot 提醒在 sliding window 累積 ≥3 條前暫不觸發；歷史 cumulative 數值存於 `legacy_cumulative`。

### V2.11（2026-03-13）

- 移除因果圖（CausalGraph + BFS + Bayesian update + causal_graph.json）
- 5 信號加權評分函數 → 改 2 條硬規則
- 新增 over_engineering_rate / silence_accuracy / Bayesian arch sensitivity

## Fix Escalation 觸發

- `wisdom_retry_count ≥ 2` → UserPromptSubmit 注入 `[Guardian:FixEscalation]` 提醒走 `/fix-escalation`
- 一次性旗標：`fix_escalation_warned` 避免重複注入
- 相關 feedback atom：`memory/feedback/feedback-fix-escalation.md`

## 跨 Session 鞏固

- 廢除自動晉升，改為 Confirmations +1 簡單計數
- 4+ sessions → 建議晉升（不自動執行，由 `atom_promote` MCP tool 執行）
- 統一 dedup 閾值 0.80
- SessionEnd 衝突偵測：向量搜尋 score 0.60-0.95 → 寫入 episodic 衝突警告

詳見 `memory/decisions.md`（晉升規則）、`memory/decisions-architecture.md`（核心架構決策）。
