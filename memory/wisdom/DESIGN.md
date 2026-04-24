# Wisdom Engine 設計文件（V2.11）

- Scope: global
- Confidence: [固]
- Trigger: wisdom engine, DESIGN, 情境分類, silence_accuracy, over_engineering, Bayesian, reflection, arch_sensitivity
- Last-used: 2026-03-13
- Confirmations: 0
- ReadHits: 0
- Related: decisions-architecture, decisions
- Status: ✅ V2.11 重構完成
- Created: 2026-03-10
- Updated: 2026-03-13
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
  "window_size": 10,
  "metrics": {
    "first_approach_accuracy": {
      "single_file": {"correct": 0, "total": 0},
      "multi_file": {"correct": 0, "total": 0},
      "architecture": {"correct": 0, "total": 0}
    },
    "over_engineering_rate": {
      "user_reverted_or_simplified": 0,
      "total_suggestions": 0
    },
    "silence_accuracy": {
      "held_back_ok": 0,
      "held_back_missed": 0
    }
  },
  "arch_sensitivity_elevated": false,
  "blind_spots": [],
  "last_reflection": null
}
```

### first_approach_accuracy（V2.8 延續）

SessionEnd 時根據 `modified_files` 數量分類為 single_file / multi_file / architecture，`wisdom_retry_count == 0` 則 correct +1。

盲點偵測：total ≥ 3 且正確率 < 70% → 寫入 `blind_spots`，SessionStart 注入 `[自知]` 提醒。

### [V2.11 新增] over_engineering_rate

- **PostToolUse**：同一檔案被 Edit 2+ 次 → `user_reverted_or_simplified +1`（revert 信號）
- **SessionEnd**：`total_suggestions +1`（每 session 計一次）
- 用途：未來可在 rate > 30% 時注入「簡化建議」提醒

### [V2.11 新增] silence_accuracy

- 依據 `_last_approach`（module-level 暫存）判斷本 session 是否「未注入」
- `_last_approach == "direct"` AND `retry_count == 0` → `held_back_ok +1`（沉默正確）
- `_last_approach == "direct"` AND `retry_count > 0` → `held_back_missed +1`（該說沒說）
- 用途：追蹤「沉默的智慧」是否真的智慧

### [V2.11 新增] Bayesian arch sensitivity 校準

在 `reflect()` 末尾：
- architecture 正確率 < 34%（total ≥ 3） → `arch_sensitivity_elevated = True`
- architecture 正確率 ≥ 50% → `arch_sensitivity_elevated = False`
- 效果：情境分類器的 plan 閾值動態調整

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
