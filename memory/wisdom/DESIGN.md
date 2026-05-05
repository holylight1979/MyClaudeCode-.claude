# Wisdom Engine 設計文件（V2.12）

- Scope: global
- Confidence: [固]
- Last-used: 2026-05-05
- Confirmations: 0
- Related: decisions-architecture, decisions
- Status: ✅ V2.12 校準完成（Wave 4）
- Created: 2026-03-10
- Updated: 2026-05-05
- Work-Unit: 智慧引擎 Wisdom Engine

## 核心原則

code 預運算判斷 → 只注入結論（≤90 tokens）
小任務零注入。只在需要時才出聲 = 沉默的智慧。

## 架構總覽

```
wisdom_engine.py (~170行, ~/.claude/hooks/)
        │
  ┌─────┴─────────┐
  ▼               ▼
情境分類        反思引擎
(硬規則)       (強化版)
  │               │
  ▼               ▼
 0~20t          0~40t    → additionalContext ≤60 tokens
```

被 workflow-guardian.py 在 3 個 hook 點呼叫。

## [V2.11 移除] 力一：因果圖（Causal Graph）

**移除原因**：冷啟動零邊、維護成本 > 收益。實際使用中 3 條種子 edge 未產生有效警告。

**API 保留**：`get_causal_warnings()`、`add_causal_edge()`、`update_causal_confidence()` 保留為 no-op stub，確保 guardian.py import 不報錯。

`causal_graph.json` 已清空為 `{}`。

---

## [V2.11 改為硬規則] 力二：情境分類器（Situation Classifier）

### V2.8 原版（已移除）

5 信號加權評分函數 + calibrated_weights + 閾值 4/10。過度工程，權重校準需 10+ sessions 但從未真正校準。

### V2.11 硬規則

```python
def classify_situation(prompt_analysis):
    # Rule 1 (plan): touches_arch OR file_count > threshold
    # Rule 2 (confirm): file_count > 2 AND is_feature
    # Default: direct (零注入)
```

### Arch Sensitivity（Bayesian 校準）

`arch_sensitivity_elevated` 欄位存於 `reflection_metrics.json`：
- `True`：plan 閾值從 `file_count > 3` 降為 `> 2`（更敏感）
- 觸發條件：architecture 首次正確率 < 34%（total ≥ 3）
- 恢復條件：architecture 首次正確率 ≥ 50%

### Module-level state

`_last_approach`：暫存最近一次 classify 結果，供 `reflect()` 做 silence_accuracy 追蹤。同一 process 內有效。

---

## [V2.11 強化] 力三：反思引擎（Reflection Engine）

### 資料檔：`memory/wisdom/reflection_metrics.json`

```json
{
  "schema_version": "2.12",
  "window_size": 10,
  "metrics": {
    "first_approach_accuracy": {
      "single_file":  {"recent": [bool, ...]},
      "multi_file":   {"recent": [bool, ...]},
      "architecture": {"recent": [bool, ...]}
    },
    "over_engineering_rate": {"recent": [bool, ...]},
    "silence_accuracy": {"recent": [{"approach": "direct", "ok": bool}, ...]}
  },
  "legacy_cumulative": {
    "first_approach_accuracy": {...},
    "over_engineering_rate": {...},
    "silence_accuracy": {...},
    "frozen_at": "2026-05-05T..."
  },
  "arch_sensitivity_elevated": false,
  "blind_spots": [],
  "last_reflection": null
}
```

### first_approach_accuracy（V2.12 sliding window）

SessionEnd 時根據 `wisdom_approach` + `modified_files` 數量分類為 single_file / multi_file / architecture，依 task type 計算 correct：

- **architecture**：`(retry_count <= 1) AND (not fix_escalation_triggered)` 才 correct。容忍 1 次小重試，因 plan-mode 本質要 iterate；fix_escalation_triggered 是真失敗信號（覆蓋容忍）
- **single_file / multi_file**：嚴格 `retry_count == 0` 才 correct

寫法：每次 SessionEnd append True/False 到對應 task_type 的 `recent` list，list 維持 max len = `window_size`（10）。

盲點偵測：`len(recent) >= 3` 且正確率 `sum(recent)/len(recent) < 0.7` → 寫入 `blind_spots`，SessionStart 注入 `[自知]` 提醒。

### [V2.12 改] over_engineering_rate（sliding window）

- **SessionEnd**：append `(retry_count > 0)` 到 `recent`
- 維持 max len = `window_size`
- 用途：未來可在 rate > 30% 時注入「簡化建議」提醒

### [V2.12 改] silence_accuracy（sliding window）

- 依 state["wisdom_approach"]（跨 process 持久化於 state-{sid}.json）判斷本 session 是否「未注入」
- `approach == "direct"` 才 append：`{"approach": "direct", "ok": (retry_count == 0)}` 到 `recent`
- 維持 max len = `window_size`
- 用途：追蹤「沉默的智慧」是否真的智慧

### [V2.12 改] Bayesian arch sensitivity 校準（sliding window）

在 `reflect()` 末尾，用 architecture.recent 計算近期正確率：
- 正確率 < 34%（len ≥ 3） → `arch_sensitivity_elevated = True`
- 正確率 ≥ 50% → `arch_sensitivity_elevated = False`
- 效果：情境分類器的 plan 閾值動態調整

### [V2.12 新] retry 校準（plan-mode threshold + fix_escalation 真失敗）

V2.11 retry 邏輯對 architecture 系統性偏誤：plan-mode session 同檔多次 Edit = 試錯探索而非錯誤修復，但被計入 retry → architecture 正確率被壓到 13%。

**校準兩處**：

- `track_retry()` 提高 plan-mode 同檔 Edit threshold：approach="plan" 時 4 次才算 retry（其他 approach 維持 2 次）
- `reflect()` 對 architecture 容忍 1 retry，由 `fix_escalation_triggered` 覆蓋（真失敗信號由 workflow-guardian.py:1390 的 [Guardian:FixEscalation] 注入點同步寫入）

### [V2.12 新] schema migration

`_migrate_v211_to_v212(metrics)`（冪等）：

- 偵測 V2.11 cumulative 結構（`{correct, total}`、`{user_reverted_or_simplified, total_suggestions}`、`{held_back_ok, held_back_missed}`）
- 搬到 `legacy_cumulative.{first_approach_accuracy, over_engineering_rate, silence_accuracy}`，附 `frozen_at` 時間戳
- 重建空 `recent: []` 結構
- 寫 `schema_version: "2.12"`
- `arch_sensitivity_elevated` 透傳保留（不重置；下次 sliding window 累積 ≥3 條後重新評估）
- 統一通道：所有 reader/writer 透過 `_load_metrics()` 自動觸發 migration

---

## 整合點（workflow-guardian.py）

| Hook | 呼叫 | 作用 |
|------|------|------|
| UserPromptSubmit | `wisdom.get_causal_warnings()` | [V2.11] stub, 返回 [] |
| UserPromptSubmit | `wisdom.classify_situation()` | 硬規則情境建議 |
| SessionStart | `wisdom.get_reflection_summary()` | 盲點提醒注入 |
| SessionEnd | `wisdom.reflect(state)` | 更新統計 + silence + Bayesian |
| PostToolUse | `wisdom.track_retry(state, path)` | 追蹤重試 + over_engineering |

## 哲學基礎

- Phronesis（實踐智慧）：情境分類器 = 正確感知特殊情境的能力
- 蘇格拉底 γνῶθι σεαυτόν：反思引擎 = 可行動的精確自我校準
- 核心：Wisdom ≠ 知道更多（WHAT），= 判斷時機（WHEN）+ 認識自己（SELF）

---

## 變更記錄

### V2.12（2026-05-05，Wave 4）

- **改 schema**：metrics.* 從 cumulative `{correct, total}` 改為 sliding window `{recent: [...]}`，window_size=10 真實使用（V2.11 dead schema field 啟用）
- **新增 schema_version: "2.12"** 辨識
- **新增 legacy_cumulative**：保留 V2.11 累計值（single 402/420、arch 4/32 等）作歷史快照
- **新增 _migrate_v211_to_v212()**：冪等 migration，所有 reader/writer 透過 `_load_metrics()` 自動觸發
- **改 retry 校準**：track_retry plan-mode threshold 從 2 → 4；reflect architecture 容忍 1 retry 但 fix_escalation_triggered 覆蓋
- **新增 fix_escalation_triggered**：workflow-guardian.py 的 Fix Escalation Protocol 注入點同步寫 state，給 reflect() 用為真失敗信號
- **副作用**：SessionStart 的 `[自知]` blind_spot 提醒在 sliding window 累積 ≥3 條前暫不觸發；歷史累計表現存於 legacy_cumulative
- **行數**：~213（V2.11 ~170 → V2.12 +43，主要為 migration shim）

### V2.11（2026-03-13）

- **移除**：因果圖（CausalGraph class + BFS + Bayesian update + causal_graph.json）
- **移除**：5 信號加權評分函數 + DEFAULT_WEIGHTS + QUICK/THOROUGH_KEYWORDS + calibrated_weights
- **改為硬規則**：2 條規則（plan: arch/file_count、confirm: feature/file_count、default: direct）
- **新增**：over_engineering_rate 追蹤（PostToolUse revert 信號 + SessionEnd 計數）
- **新增**：silence_accuracy 追蹤（_last_approach module-level state）
- **新增**：Bayesian arch sensitivity 校準（architecture 連續失敗 → 降低 plan 閾值）
- **行數**：251 → ~170

### V2.8（2026-03-10 ~ 2026-03-11）

- 初版三力架構（因果圖 + 情境分類 + 反思引擎）
- 因果圖種子資料 3 edges
- BFS dedup 修復、情境閾值調校 4/10
- track_retry() PostToolUse 追蹤
