# 清理計畫 v2.1 — 使用者裁決後修訂版

> Date: 2026-04-27 → 2026-04-28（v2.1 修訂）
> 修訂自 v2，含使用者 4 項裁決 + Codex 機制驗證者新發現（vector 失效真根因）
> 累計大師席次：CC 4 + Codex 6 = CC ≥4 票

## ⚠️ 新 session 必讀：[multi_agent_protocol.md](multi_agent_protocol.md)
> 多大師協作模式、Codex sandbox 修復、CC > Codex 席次設計、防 Codex 幻覺方法 — 全在那檔。
> 使用者明確要求每個 phase 都要 ≥3 位 Codex + CC 多數席次，新 session 不能漏。

## 使用者裁決調整（v2 → v2.1）

1. **取消 backup 機制** — A0 改為「manifest only」（路徑/mtime/引用點清單），無 git snapshot、無檔案備份
2. **觀察期縮短**：D4「7 天 → **4 天**」、D5「30 天 → **10 天**」；其他 7 天觀察期同步調為 4 天
3. **vector 精密化議題另開** — 詳見 [follow_up_issues.md](follow_up_issues.md)：(a) 拆分多組向量資料庫 / 檔案分類拆小 (b) **vector 失效根因追蹤**
4. **新增：vector 失效真根因（機制驗證者揭露）** — `workflow-guardian.py:611` 寫死 `vs_script = tools/vector-service.py`（**該檔不存在**，真檔在 `tools/memory-vector-service/service.py`）；line 632 無條件寫 ready flag → 12 天假陽性。**Stage D2 修正：改 vs_script 路徑**（不只是停 flag 寫入）

## 一、v1→v2 主要修訂（10 條）

### 修訂 #1 — Stage A2 不刪整個 `memory/personal/`
**v1**：刪 `memory/personal/`（1K 幾近空）
**v2**：**保留** `memory/personal/holylight/role.md`（V4 role 機制活躍引用點）；只刪 `memory/personal/auto/`（若空）與 `_distant/`
**證據**：3 位 Codex（skeptic/mechanic/redteam）一致警告，`wg_paths.py:116`、`wg_roles.py:7-170` 對 personal/{user}/ 路徑大量讀寫。CC 風險預測席同方向警告

### 修訂 #2 — Stage E 拆分，不誤砍主 codex_companion
**v1**：E3 寫「移除 settings.json codex_companion.py 鏈如該 hook 整體可砍」（語意模糊）
**v2**：
- **E1**：砍 `hooks/wg_codex_companion_phase6.py`
- **E2**：移除 `workflow-guardian.py:574-584` 對 phase6 的引用
- **E3**：**保留** settings.json 的 `codex_companion.py` 主 hook（5 處引用 line 108/128/180/217/237）— 列入「觀察 7 天 trigger 命中率」TODO
**證據**：3 位 Codex 一致 + CC 風險預測席同方向

### 修訂 #3 — Stage A0：Manifest Only（使用者裁決：取消 backup）
**v2.1 規範**：所有清理開始前先建 manifest 文件（**無 backup**）：
- `~/.claude/plans/memory-cleanup-2026-04-27/rollback_manifest.txt`：含每個將被異動檔案的 path / mtime / wc -l / 行數 / 引用點（grep 結果）
- 用途：documentation + 出問題時可參照 git 還原（git 本身已是 git repo）
- ❌ 不做 git snapshot（git 本身已可 reset）
- ❌ 不備份 lance（使用者裁決：直接動，10 天觀察期未撤回則永久刪）
**理由**：Codex 紅隊「先凍結刪除 + rollback anchor」、skeptic「不可逆動作」要求由「使用者願意承擔」覆蓋

### 修訂 #4 — Stage D Vector 修正路徑（v2.1：使用者裁決 4/10 觀察期）
**已驗證新事實（2026-04-28）**：
- `tools/vector-service.py` 確認不存在
- 真檔在 `tools/memory-vector-service/service.py`
- `workflow-guardian.py:611` 寫死錯誤路徑 → subprocess.Popen 必失敗
- `workflow-guardian.py:632-637` 無條件寫 `vector_ready.flag` → 12 天假陽性根因

**v2.1 執行步驟**：
- **D1**：✅ 已驗（路徑確認錯誤）
- **D2-修路徑（不只停 flag）**：兩擇一
  - (a) **修活**：將 `vs_script = tools/vector-service.py` 改為 `tools/memory-vector-service/service.py`，並在 poll 失敗時 **不寫 flag**（line 632 加 try/except 健康檢查）
  - (b) **正式淘汰**：`vector_search.auto_start_service = false`（config.json）+ 移除 line 593-662 整段 bg subprocess + ready flag 機制
  - **建議路線 (a)**：根因明確、修起來成本低、保留 SECTION_INJECT_THRESHOLD 設計能力（架構師主張）

#### Wave 3a 已執行（2026-04-28）— 觀察儀表先於決策

> Stage D 本身**未動**；先建儀表 4 天後再決定 (a)/(b)。
> 引入儀表的同時順手修了 D2 路線 (a) 的 path 修正 + flag gate（讓觀察期能拿到真實 vector ready 數據而非 12 天假陽性垃圾）。
> 詳見 git commit `wave-3a: vector observation instrumentation + workflow-guardian path fix`。

- **D3（fail-closed 保留）**：`wg_intent.py` 現有 graceful no-op 不動 ✓
- **D3.5（Wave 3a 新增）**：log 採樣儀表
  - `wg_intent._search_episodic_context` / `_semantic_search` 三個出口都寫 `~/.claude/Logs/vector-observation.log`（schema：ts/session_id/fn/flag_state/result_count/fallback_used）
  - SessionStart bg subprocess 加 known query probe（`workflow guardian SessionStart 機制`），比對 vector 命中數 vs keyword grep 命中數，寫 `~/.claude/Logs/vector-observation-probe.log`
- **D4 觀察 4 天**：log 採樣自動進行，**不依賴使用者察覺**
  - 觀察起算：本 commit（2026-04-28）
  - 4 天截止：~2026-05-02
- **D5（讀 log 自動判定）**：跑 `python tools/vector-observation-summary.py --days 4` 取得自動判定：
  - **REVIVE**（命中率 ≥ 50%）：保留 vector subsystem，繼續使用
  - **RETIRE**（命中率 ≤ 5% 且 fallback ≥ 80%）：淘汰 — 設 `auto_start_service=false` + 刪 lance + 移除 vector subsystem + 對應 commands
  - **GRAY**（5–15%）：列代表樣本詢問使用者裁決
  - **不再依賴**「使用者主訴 atom 沒命中」（silent fail 本就不可見）
- **D6**：若 REVIVE → service.log + audit.log 留作參考；若 RETIRE → 摘要搬 `_AIDocs/Failures/vectordb-silent-failure-2026-04.md`
- **D7**：若 RETIRE → 移除 `commands/vector.md` + `commands/conflict.md`（後者依賴 vector）；若 REVIVE → 兩檔保留
**vector 精密化（拆組/分類拆小） + 失效根因深挖** 移到 [follow_up_issues.md](follow_up_issues.md) 另開議題

#### Wave 3b 已執行（2026-04-28）— probe burst + 自動決策

> 取代 D4 的 4 天等待。實際做法：90 query × 2 path = 180 calls 透過 `wg_intent._search_episodic_context` / `_semantic_search` 跑完整 vector pipeline，summary tool 自動判定。

- **決策：REVIVE**，命中率 **87.6%**（163/186 ready 記錄），fallback rate 3.6%
- 依 Wave 3a 修補後保留 vector subsystem：
  - `vs_script` 路徑修正（line 621：`tools/memory-vector-service/service.py`）✓
  - `vector_ready.flag` 寫入 health-200 gate（line 663–667）✓
  - 觀察儀表 `wg_intent._log_vector_obs` 保留作為日後監控入口 ✓
- 不執行 D5 RETIRE 分支：lance 不刪 / commands/vector.md + conflict.md 保留 / wg_intent vector 路徑保留
- 大師席次紀錄：CC 寫手（執行）+ CC 稽核 PASS + Codex 紅隊 proceed-with-note（service.log 查詢字串潛在洩漏，非本次新增，已記入 follow_up_issues.md §議題 #6）
- 後續調整建議（不在本 wave 執行，加入 follow_up #6）：
  - bucket-C 高命中率顯示 `min_score` 偏寬鬆 → 注入品質疑慮，需另開 session 調 ranked 閾值
  - service.py log_message 將 `q=` 完整路徑寫入 stderr → service.log；Wave 3a 主 hook 路徑用 `stderr=log_fh`，舊的 `_ensure_vector_service` 也是 → 任何啟動方式都會留下查詢字串
- git commit：`wave-3b: vector probe burst + decision REVIVE`（hit_rate 87.6%）

### 修訂 #5 — Stage B 補做 `memory/_staging/` 內兩個實檔
**v1 漏項**：briefing §4 寫 `_staging/ 0 檔`，但實際有 `phase-0-retrospective.md` + `Phase_1_MkDocs_Skeleton.md`
**v2**：B0 — review `_staging/` 兩檔，搬 `_AIDocs/DevHistory/` 或刪
**證據**：skeptic 直接指出

### 修訂 #6 — Stage F5 _reference 搬移加保護
**v1**：F5 評估搬 `_reference/` 9 檔到 `_AIDocs/DevHistory/atomic-memory-evolution/`
**v2**：F5 改為：
- **F5a**：先 grep 全 `~/.claude/` 對 `_reference/` 路徑的硬引用
- **F5b**：`internal-pipeline.md` 確認被 `workflow-guardian.py:936` 引用（Wave 3a/3b 改動後行號偏移：888 → 948 → 936）→ 留 stub 或同步改 hook 路徑
- **F5c**：其他 8 檔（不在 trigger 表）整批搬，純無痛優化（CC 效益預測席：token 收益=0、磁碟收益 104K）
**證據**：mechanic 找到引用點（以實際 grep 為準）

### 修訂 #7 — Stage G1 Project_File_Tree 砍同時改索引契約
**v1**：G1 砍至 30 行 + 「詳細請跑 tree」
**v2**：G1 加：
- 同步改 `_AIDocs/_INDEX.md` 第 13 行的 keywords（從寬泛「目錄結構, 檔案位置, 資料夾, 在哪裡」改為窄詞「目錄角色說明」），避免「在哪裡」問題誤觸發
- 同步檢查 `Architecture.md`、`Tools/_INDEX.md`、`commands/init-project.md`、`commands/upgrade.md` 對舊樹的引用，更新描述
- 改前先 `cp Project_File_Tree.md` 到 `backup/2026-04-27-pre-cleanup-tree.md`
**證據**：3 位 Codex 一致 + CC 風險預測席同方向

### 修訂 #8 — 提升 G1 為 ROI 最高 Stage
**v1**：G1 排在 Stage 後段
**v2**：**G1 提前到 Stage A 後立即執行**（在 B/C/D 之前）
**證據**：CC 效益預測席計算 G1 單一動作即省 60–80% 此類命中 tokens（Project_File_Tree 命中時注入 5500-6000 tokens，砍至 30 行省 4500-5500）；同時 G1 簡化後續 Stage（樹過時兩次的問題消失）

### 修訂 #9 — Stage F 加 baseline diff
**v1**：F1 IDENTITY.md 後設段移走（風險：always-loaded drift）
**v2**：F 系列改動 always-loaded 入口前必須跑 `tools/atom-health-check.py`（如存在）建立 baseline；改動後再跑驗證 diff 是否預期
**證據**：CC 風險預測席「移段會觸發 drift 警報」

### 修訂 #10 — 強化 Stage 順序
**v1**：A→B→C→D→E→F→G→H
**v2 強制順序**：
1. **A0 rollback anchor**（git snapshot + manifest + lance backup）
2. **A1-A6 零風險清理**（空目錄與 stale pid，含修訂 #1 的 personal 保留邏輯）
3. **G1 Project_File_Tree 砍**（提前，最高 ROI）
4. **B 過時 plans 清理**（含修訂 #5 的 _staging）
5. **C projects 已棄專案封存**
6. **D vector subsystem 三步驟**（含修訂 #4 的 D1-D7）
7. **E hook 鏈精簡**（含修訂 #2 的 E1-E3）
8. **F atom 內容裁剪**（最高風險，最後做，含修訂 #6/#9 保護）
9. **H 規則沉澱寫 atom**（最後寫新檔，避免 F 之前污染）

## 二、不變的決策（v1→v2 維持）

- 共識 #1 砍 `wg_codex_companion_phase6.py` ✓ 維持（修訂 #2 是收斂執行範圍，不是反對）
- 共識 #2 刪 `_distant/` ✓ 維持
- 共識 #3 vector subsystem 必須處理 ✓ 維持（修訂 #4 是執行細化）
- 共識 #4 plans 27 檔分類 ✓ 維持
- 共識 #5 feedback/wisdom/_reference 不應全文 trigger 注入 ✓ 維持
- 矛盾仲裁：always-loaded 大致保留（架構師方案）✓ 維持
- 矛盾仲裁：V4 multi-scope 不拔 ✓ 維持
- 矛盾仲裁：Project_File_Tree 折衷砍至 30 行 ✓ 維持
- 矛盾仲裁：atom 注入機制重構 → TODO ✓ 維持

## 三、Token 節省預估修訂

| Stage | v1 預估 | v2 修訂 | 修訂理由 |
|-------|--------|---------|---------|
| G1 Project_File_Tree | trigger 命中省 ~150 tokens | trigger 命中省 **4500-5500 tokens** | CC 效益預測席實算 13455 byte = ~6000 tokens 全文注入 |
| F5 _reference 搬走 | always-loaded 省 + trigger 省 | trigger 省 **0**（不在表）；磁碟省 104K | CC 效益預測席證實 |
| F1+F2+F3+F4 後設裁剪 | 250 tokens/turn | always-loaded 省 ~130 tokens/turn + 命中時 +200-300 | 重新實算 |
| **per-session（樂觀）** | 7K tokens | **20-25K tokens** | G1 提前 + trigger 詞修剪 |

## 四、Phase 4-Exec 執行流程

每個 Stage 動工前：
1. 我（CC 寫手）列出本 Stage 將執行的具體 bash/Edit/Write 動作（dry-run 列表）
2. 派 1 位 CC 稽核 + 1 位 Codex 稽核**並行**驗證 dry-run 列表
3. 兩位稽核 OK 後我執行
4. 執行後跑 baseline diff 或 smoke test（視 Stage 風險）

## 五、保留 ScanReport / 防退避

每個 Stage 完成後我必須輸出：
```
順手修補清單：
- 路徑:行 — 動作

(或) 本 Stage 無發現 drift
```

## 六、簽核清單

進入 Phase 4-Exec 前需使用者最終裁決：
- [ ] v2 計畫是否照此執行
- [ ] 是否需要分多個 session 執行（避免 context 滿）
- [ ] backup 目錄位置是否接受（`~/.claude/plans/memory-cleanup-2026-04-27/backup/`）
- [ ] 30 天觀察期是否接受（lance 檔不立即刪）
