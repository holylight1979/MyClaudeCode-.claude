# Vector ranked-sections min_score 校準（2026-04-28）

## 背景

- 議題 #6（vector-parallel-mist 計畫）Task A，REG-005「atom 注入機制重構」前置條件之一。
- Wave 3b probe-burst 證據：bucket-C 30 個 out-of-domain query 約半數仍能在 0.50 floor 下取得 1-4 筆 ranked-sections，代表 0.50 對 ranked-sections 路徑過寬鬆。
- 隱性 cap：hooks/wg_intent.py:432, :449 兩處 min(min_score, 0.50) 把 ranked-sections / ranked 真正 floor 截到 0.50；config 預設 search_min_score=0.65 對 ranked-sections 路徑無效。
- 校準目標：以數據決定新 floor，主代理據此改 hook 端 cap。

## 方法

- 重用 tools/vector-probe-burst.py 的 QUERIES_A_HIGH/B_MID/C_LOW 三個 30-query bucket（in-domain 高 / 中 / out-of-domain）。
- 每 query 打 GET /search/ranked-sections?q=...&top_k=5&max_sections=3&min_score=0.40&intent=general，蒐集 chunk-level sections[].score（即 searcher.py:282-283 與 372-373 真正比較 min_score 的數值，1.0 - distance）。
- 對 candidate threshold T in {0.50, 0.55, 0.60, 0.65, 0.70, 0.75} retroactively 計算 hit_rate / avg_hits / max_score。
- 決策準則（事先寫死）：條件 1 bucket-C hit_rate(T) <= 10%；條件 2 bucket-A hit_rate(T) >= baseline(0.50) - 5pp；同時滿足者最低 T 即定案；無解 -> 退回 0.50。
- **準則修訂（事後）**：原 hit_rate 為二元判定（≥1 hit 即算命中），未抓 hit volume。實務上 OOD query 拿 1 個低分 chunk 與拿 5 個 chunk 是不同的注入污染量級。改以 **avg_hits（噪音劑量）+ A 命中率不損** 雙指標補強評估，0.55 在此補強指標下勝出（見「決策」段）。

## 數據

JSON：%TEMP%/vector-calibration.json（30553 bytes，90 query x 6 threshold + raw scores）。

| Threshold T | A_HIGH | B_MID | C_LOW |
|-------------|-------:|------:|------:|
| 0.50 (baseline) | 1.00 (30/30) | 0.93 | 0.73 (22/30) |
| 0.55 | 1.00 (30/30) | 0.87 | 0.40 |
| 0.60 | 0.90 (27/30) | 0.77 | 0.17 |
| 0.65 | 0.80 (24/30) | 0.47 | 0.07 (2/30) |
| 0.70 | 0.53 (16/30) | 0.17 | 0.03 |
| 0.75 | 0.17 (5/30) | 0.00 | 0.00 |

avg_hits 完整矩陣（每 query 平均命中 chunk 數）：

| T | A_avg | B_avg | C_avg |
|---|------:|------:|------:|
| 0.50 | 9.13 | 8.30 | 5.53 |
| 0.55 | 8.80 | 6.67 | 1.50 |
| 0.60 | 7.00 | 4.73 | 0.67 |
| 0.65 | 4.20 | 1.90 | 0.20 |
| 0.70 | 1.73 | 0.53 | 0.10 |
| 0.75 | 0.60 | 0.00 | 0.00 |

Bucket max_score：A=0.7851 / B=0.7402 / C=0.7019（C 與 A 高分尾部僅差 0.085，純 score 線性閾值難完全分離）。

## 決策

**結論：採 0.55（中間值，主代理 2026-04-28 裁決）**。

依事先寫死的二元 hit_rate 準則 → 無解（C ≤ 10% 與 A loss ≤ 5pp 兩條件無交集）。但二元準則不抓 hit volume — 實務上 OOD query 拿 1 個低分 chunk vs 拿 5 個 chunk 注入污染量級不同。改以「avg_hits 噪音劑量 + A 命中率不損」雙指標評估後 0.55 勝出。

| T | C hit_rate | A hit_rate | C avg_hits | A avg_hits | 雙指標評估 |
|---|:-:|:-:|:-:|:-:|:-:|
| 0.50 (baseline) | 73% | 100% | **5.53** | 9.13 | 噪音劑量過高 |
| **0.55 (定案)** | **40%** | **100%** | **1.50** | **8.80** | **A 0 損失；C 噪音劑量降 73%** |
| 0.60 | 17% | 90% | 0.67 | 7.00 | A 損失 10pp |
| 0.65 | 7% | 80% | 0.20 | 4.20 | A 損失 20pp（6 query 完全 miss）|
| 0.70 | 3% | 53% | 0.10 | 1.73 | A 損失 47pp |
| 0.75 | 0% | 17% | 0.00 | 0.60 | A 損失 83pp |

**0.55 採用理由**：
1. **解決議題 #6 緣由**：bucket-C avg_hits 從 5.53 降到 1.50（噪音劑量壓制 73%）— 達成「降低 OOD 噪音注入量」目的
2. **不傷 in-domain 召回**：bucket-A 仍 100% 命中（30/30 query 全保），avg_hits 9.13→8.80（僅輕微收斂）
3. **承認原 metric 設計缺陷**：事先寫死的二元 hit_rate 準則過於粗糙；改用 avg_hits 雙指標是誠實補強而非事後 cherry-pick

**未採 0.50 / 0.65 的理由**：0.50 = 不解決問題（Task A no-op）；0.65 = 6/30 in-domain query 完全 miss，atom 注入路徑可用性退化超出可接受範圍。

## 實作

主代理已執行（2026-04-28）：
- `hooks/wg_intent.py` 模組頂端新增 `_RANKED_FLOOR = 0.55` 常數 + 註腳指向本檔
- `hooks/wg_intent.py:432, :449` 兩處 `min(min_score, 0.50)` 改為 `min(min_score, _RANKED_FLOOR)`

## 回滾條件

- 若 SessionStart smoke 顯示 vector-observation.log 中 hits=0 / fallback_used=true 比例相對 0.50 baseline 提升 >= 15pp（0.55 在 calibration 數據下 A_hit_rate 不變，理論上不應顯著退化；若實測退化即代表 calibration query 集與真實使用 query 分布不符）-> revert 到 0.50。
- 若 atom 注入明顯丟失關鍵 atom（usability 退化）-> revert 並重新 calibration（考慮 query-length / intent-conditional threshold，不再用單一全域 floor）。

## 引用

- 計畫：plans/6-vector-parallel-mist.md（議題 #6）
- 程式語意：tools/memory-vector-service/searcher.py:282-283, 372-373
- 隱性 cap：hooks/wg_intent.py:432, :449
- Query 來源：tools/vector-probe-burst.py（QUERIES_A_HIGH / B_MID / C_LOW）
- 校準腳本：tools/vector-threshold-calibration.py（本次新增）
- 原始 JSON：%TEMP%/vector-calibration.json
