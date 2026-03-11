# 升級實況紀錄（V2.5→V2.8）

- Scope: global
- Confidence: [觀]
- Type: procedural
- Trigger: 升級, merge, V2.8, 合併
- Last-used: 2026-03-11
- Confirmations: 2
- Created: 2026-03-11

## 進度

| Session | 狀態 | 完成項目 | 遇到的問題 | Git commit |
|---------|------|---------|-----------|------------|
| S1 | ✅ 完成 | 備份 + 8 檔案新增 + 3 項驗證通過 | 無 | f916780 |
| S2 | ✅ 完成 | guardian 合併 + CLAUDE.md + MEMORY + SPEC | 無 | 21879e6 |
| S3 | ✅ 完成 | SPEC §十一~十三 + _CHANGELOG 滾動 + 文件版本對齊 + 全面驗證 | 無 | (pending) |

## S1 完成明細

### 新增檔案（8 個，全部成功）
1. `hooks/wisdom_engine.py` — V2.8 Wisdom Engine（251 行）
2. `memory/wisdom/DESIGN.md` — 設計文件
3. `memory/wisdom/causal_graph.json` — 7 nodes / 3 edges
4. `memory/wisdom/reflection_metrics.json` — 空初始值
5. `memory/failures.md` — V2.7 pitfall atom
6. `memory/toolchain.md` — V2.7 工具鏈 atom
7. `commands/resume.md` — V2.8 自動續接 skill
8. `commands/consciousness-stream.md` — V2.4 識流 skill

### S1 驗證結果
1. wisdom_engine.py 語法 + 7 函數 import — **PASS**
2. causal_graph.json JSON 結構 — **PASS**（7 nodes, 3 edges）
3. memory-audit 健檢 — **PASS**（0 errors，warnings 僅索引未更新，S2 處理）

## 關鍵上下文（供 S2 讀取）

### Guardian 插入行號（此機器 V2.5，1933 行）

**Import 區段**：L14-23（在 L23 `from typing` 之後插入 wisdom import）

**四個 handler 插入點**：

| Handler | 定義行 | 插入位置 | 說明 |
|---------|--------|---------|------|
| SessionStart | L628 | L684 前（`write_state` 前） | 加 periodic review + wisdom reflection |
| UserPromptSubmit | L694 | L989 前（`write_state` 前）的適當位置 | 加 causal warnings + situation classifier |
| PostToolUse | L1022 | L1113 前（最後一個 `write_state` 前） | 加 wisdom retry + output quality |
| SessionEnd | L1800 | L1867 前（`_generate_episodic_atom` 前） | 加 iteration metrics + wisdom reflect |

**底部追加位置**：L1933（檔案尾端），追加 6 個新函數

### Home 源碼位置（D:\tmp\myHomeClaudeCode\hooks\workflow-guardian.py）
- `_check_output_quality()`: L1876-1930
- `_collect_iteration_metrics()`: L1936-1958
- `_detect_oscillation()`: L1961-2030
- `_calculate_maturity_phase()`: L2033-2067
- `_check_periodic_review_due()`: L2070-2110
- `_save_review_marker()`: L2113-2124

### 不合併的 BUG
1. Home L1037-1048 extraction daemon thread（保留 extract-worker.py subprocess）
2. Home config search_min_score: 0.45（保留 0.65）
3. SPEC 重複 Confirmations 欄位（S2 修正）

## 升級過程決策/問題紀錄

| 時間 | 階段 | 紀錄 |
|------|------|------|
| S1 | 檔案複製 | 全部順利，無衝突 |
| S1 | 驗證 | memory-audit 回報 failures/toolchain 未在 MEMORY.md 索引 — 預期中，S2 處理 |
| S2 | guardian | 增量合併完成：wisdom import + 4 handler 插入 + 6 新函數 + V2.6 metrics/oscillation + V2.7 quality + V2.8 wisdom |
| S2 | CLAUDE.md | 替換為 Home 精簡版（145 行） |
| S2 | MEMORY.md | 新增 failures/toolchain 索引 + V2.8 版本 + Wisdom Engine 高頻事實 |
| S2 | SPEC | 移除重複 Confirmations 欄位 + 版本號 v2.4→v2.8 |
| S2 | 驗證 | py_compile PASS, SessionStart hook PASS, CLAUDE.md 145行 PASS, 索引完整性 PASS |
| S3 | SPEC | §十一 自我迭代 V2.6 + §十二 品質回饋 V2.7 + §十三 Wisdom Engine V2.8 + 版本表 3 行 |
| S3 | 文件更新 | _CHANGELOG 滾動（+1 條 V2.8, -2 條 → Archive）、_INDEX V2.8、Architecture V2.8（skills/atoms/wisdom）、File_Tree 全面更新、Install-forAI V2.8 |
| S3 | 驗證 | memory-audit 0 critical errors（1 預期中 upgrade-log 缺 Last-used → 已修）、wisdom 7 functions import PASS、4 hook events 無 exception |

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-11 | 建立為 [臨] | S1 |
| 2026-03-11 | [臨]→[觀] 跨 2 sessions 確認 | S3 |
