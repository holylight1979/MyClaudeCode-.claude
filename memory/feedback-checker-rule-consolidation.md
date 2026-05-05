# feedback checker rule consolidation

- Scope: global
- Author: holylight
- Confidence: [臨]
- Trigger: 檢查器, 規則漂移, SKIP_DIRS, 唯一規則來源, 一致性, audit
- Created-at: 2026-05-04

## 知識

- [臨] 同概念規則散在多處 = 必然漂移。Why: 2026-05-04 Opus Melodic Comet S1.2 實踐：4 個檢查器（memory-audit / atom-health-check / write-gate / 各自 SKIP_DIRS）各自定義「哪些目錄是 atom」，導致 7 個假陽性告警（DESIGN.md / role.md / _* prefix）— 修一個漏一個，最終抽到 lib/atom_spec.py 唯一規則來源消滅。
- [臨] 寫檢查/驗證類工具前先 grep 既存規則來源（SKIP_DIRS, REQUIRED_METADATA, VALID_* 常數），不重複定義。若沒有共用模組，先建一個（如 atom_spec），其他工具 import 它，然後刪原檔本地常數。
- [臨] 規則修改：永遠只動共用模組一處，禁止「順手」在 caller 端 patch 一行特殊豁免（會在另一個 caller 漏掉）。

## 行動

- 寫檢查工具前先查 lib/atom_spec.py 既有常數
- 若需新增規則，集中到共用模組單一定義
- 禁止 caller 端豁免 patch
