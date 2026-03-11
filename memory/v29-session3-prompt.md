[續接] V2.9 記憶檢索強化 — Session 3/3

## 背景
V2.9 共 4 項功能，分 3 個 session 實作：
- S1 (995d2d7): Project-Aliases ✅ + Blind-Spot Reporter ✅ + 刪除冗餘 sgi-server memory ✅
- S2 (b1cebbb): Related-Edge Spreading ✅ + ACT-R Activation Scoring ✅
- S3 (本次): 整合測試 + SPEC/文件更新 + 版號升級

## 本階段目標

請先進入 Plan Mode (Shift+Tab)，確認工作範圍後再開始。

**1. 整合測試**
- 啟動新 session，觸發包含多個 atom 的 prompt，確認：
  - [x 驗證項] ACT-R 排序：高頻 atom 排在前面
  - [x 驗證項] Related spreading：命中 atom 後沿 Related 邊帶出相關 atom 完整內容
  - [x 驗證項] Project-Aliases：非 sgi CWD 下問 sgi 相關問題，c--Projects atoms 被注入
  - [x 驗證項] Blind-Spot Reporter：問一個完全無 atom 的主題，[Guardian:BlindSpot] 出現
  - [x 驗證項] 回歸：keyword match、vector search、Supersedes filtering、token budget 正常
  - [x 驗證項] 效能：hook 回應 < 3s

**2. SPEC 更新**
- 更新 `~/.claude/memory/SPEC_Atomic_Memory_System.md`：
  - § Related-Edge Spreading：說明 spread_related() depth=1 行為
  - § ACT-R Activation Scoring：說明公式、.access.json 格式、排序邏輯
  - § Project-Aliases：已在 S1 加入，確認完整
  - § Blind-Spot Reporter：已在 S1 加入，確認完整
  - 版號：V2.8 → V2.9

**3. CLAUDE.md 更新**
- `~/.claude/CLAUDE.md` 高頻事實中的版號 V2.8 → V2.9
- 如有新增功能描述需要在 CLAUDE.md 體現，一併更新

**4. MEMORY.md + decisions atom 更新**
- MEMORY.md: V2.9 進度改為「完成」
- decisions.md: 加入 S3 完成記錄

**5. Changelog**
- 更新 `~/.claude/memory/_CHANGELOG.md`（如存在），記錄 V2.9 完整功能清單

## 關鍵上下文
- 設計規格：`~/.claude/memory/v3-design-spec.md`
- 現行 SPEC：`~/.claude/memory/SPEC_Atomic_Memory_System.md`
- Hook 實作：`~/.claude/hooks/workflow-guardian.py`
  - spread_related(): ~L217
  - compute_activation(): ~L260
  - ACT-R sorting: ~L973（"ACT-R Activation Sorting (v2.9)"）
  - Related-Edge Spreading injection: ~L1002（"Related-Edge Spreading (v2.9)"）
  - Access log writing: ~L1080（"ACT-R access log (v2.9)"）
  - Blind-Spot Reporter: ~L1113（"Blind-Spot Reporter (v2.9)"）
- CLAUDE.md：`~/.claude/CLAUDE.md`

## 完成條件
1. 所有 6 項驗證通過
2. SPEC 文件完整反映 V2.9 所有功能
3. 版號 V2.8 → V2.9 在 SPEC、CLAUDE.md、MEMORY.md 中一致
4. Git commit + push 完成

完成後：V2.9 升級完成，不需再 /resume。
