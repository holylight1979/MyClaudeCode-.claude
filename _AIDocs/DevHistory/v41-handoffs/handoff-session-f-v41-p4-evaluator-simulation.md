# Session F — V4.1 P4：Session 評價機制 + Agent 多 Role 模擬 + 驗收發布

> **模式**：Session 評價機制屬架構新增，Phase 1 建議進 Plan Mode 確認設計；Phase 2-4 直接執行。Permission 建議 yolo 或 auto-accept。
> **CWD**：`~/.claude`（開發）+ `C:\Projects`（模擬試用）
> **GIT**：完成即 commit + `git tag v4.1.0`。
> **前置條件**：P1 (alpha1) + P2 整合 (beta1) + P3 (rc1) 全部完成。

---

## 目標

最終 session。兩條主線 + 一條收尾：

1. **新增 Session 重點評價機制**（使用者 Q3(d) 拍板，V4.1 originally 未規劃的設計擴充）
2. **Agent 多 Role 模擬試用**（使用者 Q2(d) 拍板，取代真人試用）
3. **驗收 + 正式發布** tag `v4.1.0`

## 使用者開放議題拍板

- **Q2**：第二位中性使用者 → **(d) Agent 扮演 programmer + planner 兩 role，專案 `C:\Projects`（sgi）**
- **Q3**：歷史回填範圍 → **(d) 先做 session 評價機制，未來再依 score 決定 3-10 天範圍**（本 session 不做回填）

## 開工前必讀

- `plans/purring-percolating-glacier.md` §2 NFR、§5 架構、§6 P4 驗收、§10 開放議題
- `_AIDocs/V4.1-design-roundtable.md`（UX + 人文大師關於盲測、誘餌題部分）
- `hooks/wisdom_engine.py` line 102-150（reflect_metrics 現有 schema，要擴 v41_extraction.session_scores[]）
- `hooks/user-extract-worker.py`（P2 產出）
- `tools/memory-undo.py`（P3 產出，看 reflection_metrics 寫入格式）
- `memory/wisdom/reflection_metrics.json`（schema 要擴充）
- `tests/integration/test_e2e_user_extract.py`（P2 產出，50 條作為抽樣對照組）

## 三大子任務

---

### 子任務 A — Session 評價機制（新增架構模組，~1.5d）

#### 設計要求

**何時跑**：SessionEnd hook（async detached，不阻塞）

**評價維度（5 項，各 0-1 分，加權平均成 session_score）**：

| 維度 | 權重 | 計算方式 |
|---|---|---|
| **萃取密度** | 0.15 | `pending_user_extract` 觸發數 / session prompt 數，tanh 標準化 |
| **Precision 估計** | 0.35 | L2 conf 分布 → 平均 conf 作 precision proxy |
| **新穎性** | 0.20 | 新寫 atom 數 / (新寫 + dedup 命中)，高 = 新穎 |
| **成本效率** | 0.15 | 1 - (token_used / 240)，剩餘 budget 比例 |
| **使用者信任** | 0.15 | 1 - (reject 數 / 24h 內寫入數)，高 = 信任 |

**輸出**：
```json
{
  "session_id": "...",
  "ts": "2026-04-16T...",
  "prompt_count": 30,
  "extract_triggered": 8,
  "extract_written": 5,
  "dedup_hit": 2,
  "rejected_24h": 0,
  "avg_l2_conf": 0.89,
  "token_used": 178,
  "scores": {
    "density": 0.72,
    "precision_proxy": 0.89,
    "novelty": 0.71,
    "cost_efficiency": 0.26,
    "trust": 1.00,
    "weighted_total": 0.72
  }
}
```

寫入 `memory/wisdom/reflection_metrics.json` 新區塊 `v41_extraction.session_scores[]`（cap 100，FIFO）。

#### Deliverable

1. **`hooks/wg_session_evaluator.py`** — Session 評價模組
   - `evaluate_session(session_id, state, config) -> dict`
   - 從 state-{sid}.json + atom-debug log + reflection_metrics 算分
   - 純 Python 無 I/O 外部呼叫（速度 < 100ms）

2. **`hooks/workflow-guardian.py` 修改** — SessionEnd 觸發
   - 條件：`cfg.userExtraction.enabled == true`
   - 呼叫 `wg_session_evaluator.evaluate_session()` → append reflection_metrics
   - detached subprocess（同 extract-worker pattern）

3. **`tests/test_session_evaluator.py`** — 單元測試
   - 5 個模擬 state fixture（低/中/高 score 各別）
   - 驗證加權算分正確

4. **`commands/memory-session-score.md` + `tools/memory-session-score.py`** — 使用者查閱
   - `/memory-session-score [--last|--since=<time>|--top-N]`
   - 列 session 評分 + 細分維度
   - 未來可作為 `/v41-backfill --score-threshold=0.5` 的篩選依據（V4.2）

**可驗收標準**：
- 跑 10 個歷史 session（手動指定 session_id），全部產出 score
- 5 個單元測試 pass
- session_score 分布合理（非全 0 或全 1）

---

### 子任務 B — Agent 多 Role 模擬試用（~0.5d + 觀察）

#### 前置

1. 在 `C:\Projects`（sgi）先跑 `/init-roles`（若未跑）
   - 建兩個 personal role：`holylight-programmer/role.md` 和 `holylight-planner/role.md`
     - 用 `{user}-{role}` 命名區分（或看 init-roles 支援度）
   - 在 `_roles.md` 登記兩個 role
2. 啟用 `userExtraction.enabled=true`
3. 確認 V4 vector service 運作（`/vector`）

#### 模擬流程

**Round 1 — programmer role 模擬**：

用 Agent（subagent_type=general-purpose）扮演 sgi 程式設計師，prompt：
> 你扮演 sgi 專案的 programmer（使用者 holylight）。參考 `C:\Projects` 的實際 .cs / .py / .js 程式碼，進行一輪**真實技術討論**（5-10 turn），內容必須包含：
> - 至少 3 個「長期技術決策」（例：「以後 null-check 一律用 C# 8 NRT」「禁止在 Update 裡 GC.Alloc」）
> - 至少 2 個「個人偏好」（例：「我偏好 LINQ 寫 query 不用 for」）
> - 至少 1 個「一次性問題」（例：「這個 bug 怎麼修」— 非決策）
> - 1 個情緒混合句（例：「這 API 爛死，改用 B」）
>
> 不要造假，從真實程式碼上下文衍生。

跑完觀察：
- V4.1 是否抓到 ≥ 3 個技術決策 + 2 個偏好
- 是否**沒抓**一次性問題 + 情緒句（或情緒句強制 interactive confirm [F10]）
- scope 推斷：個人偏好 → `personal/auto/`；技術決策 → `role:programmer/` 或 `shared/`？

**Round 2 — planner role 模擬**：

用 Agent 扮演 sgi 企劃，prompt：
> 你扮演 sgi 專案的 planner（使用者 holylight）。參考 `C:\Projects` 的實際企劃規格文件（.md/.docx），進行一輪**真實設計討論**（5-10 turn），內容必須包含：
> - 至少 2 個「設計規範拍板」（例：「所有 boss 血量上限 1M」）
> - 至少 1 個「跨職能規範」（例：「所有 UI 字串走 L10n」— 影響 programmer + planner）
> - 至少 1 個婉轉決策（例：「就這樣吧」+ context 支撐）
>
> 不要造假。

跑完觀察：
- V4.1 是否正確分流（role:planner 的設計 vs shared 的跨職能規範）
- 婉轉決策是否走「明說+預設同意」[F5] 流程
- JIT role-filter 驗證：重開 programmer session，**不該看到** planner role 的 atom

**Round 3 — 混合檢查**：

- 執行 `/memory-peek` 看兩 role 萃取結果
- 執行 `/memory-session-score`（子任務 A 產出）看兩 session 評分
- 刻意 `/memory-undo` 一條錯抓（或若沒錯抓，選一條改 reason=other）
- 重新開 programmer session，驗 JIT 注入只含 role:programmer + shared + personal

#### 可驗收標準

- 兩 role atom 正確分流（role:programmer vs role:planner vs shared vs personal）
- JIT role-filter 跨 role 看不到對方
- 誘餌題（Round 3 重開 session 時）命中：提起 Round 1 決策 → AI 應 recall「上次拍板 X」
- `/memory-undo` 摩擦力 ≤ 2 enter（P3 驗收項順帶複測）

---

### 子任務 C — 抽樣驗收 + 正式發布（~0.5d）

#### 抽樣 P/R

P2 整合測的 50 條 + Round 1+2 新產生的 ~15 條 = 65 條
- 手工標記 ground truth（決策 yes/no + scope 分類）
- 比對 V4.1 實際萃取結果
- 計算：
  - Precision（V4.1 寫入的正確率）
  - Recall（該寫的抓到了多少）
  - scope 推斷準確率

**紅線**：
- Precision ≥ 0.92 ✓
- Recall ≥ 0.30 ✓
- token amortized ≤ 240 / session ✓

#### Token NFR 驗證

```bash
python tools/v41_token_budget_audit.py --sessions 30
# 輸出 amortized token / session + session_score 分布
```

#### 正式發布

- `_AIDocs/_CHANGELOG.md` 加 `v4.1.0` 發布紀錄
- `_AIDocs/Architecture.md` 補「V4.1 Session 評價機制」段（子任務 A 產物）
- `settings.json` 把 `userExtraction.enabled` 改為 **true**（預設開啟）
- `settings.json` `mode` 從 `shadow` 改為 **`production`**
- git commit + `git tag v4.1.0`
- git push

---

## 絕不碰

- V4 atoms（regression test 最後再跑一次驗）
- `server.js`（零修改 [F2]）
- `SPEC_ATOM_V4.md`（零修改 [F1]）
- P1/P2/P3 所有已發布 deliverable 的核心邏輯

## 最終驗收

```bash
# 回歸
pytest tests/regression/test_v4_atoms_unchanged.py -v
pytest tests/test_v41_disabled.py -v           # flag 可切回 false

# 新增
pytest tests/test_session_evaluator.py -v      # 5 單元測試

# 整合（真 ollama）
pytest tests/integration/test_e2e_user_extract.py --ollama-live -v  # 65 條 P≥0.92 R≥0.30

# Skill 全通
/memory-peek
/memory-undo last
/memory-session-score --last

# E2E
# 1. C:\Projects 跑完 Round 1+2+3
# 2. session_score 兩個都算出
# 3. JIT role-filter 驗證成功
```

**最終紅線**：
- 65 條 P ≥ 0.92 / R ≥ 0.30
- 兩 role agent 模擬分流正確
- JIT role-filter 無洩漏
- session_score 機制運作 + 寫入 reflection_metrics
- V4 atoms SHA256 全不變
- tag `v4.1.0` push 成功

## GIT

- 子任務 A 完成 → commit 1「feat(atom-v4.1): session evaluator — 5 維度加權評分 + reflection_metrics 擴充」
- 子任務 B 完成 → commit 2「test(atom-v4.1): P4 — agent multi-role simulation on sgi project」（含 Round 1+2+3 紀錄）
- 子任務 C 完成 → commit 3「feat(atom-v4.1): P4 GA — enable userExtraction by default, v4.1.0 release」
- `git tag v4.1.0` + `git push && git push --tags`

## 後續（V4.1 後，V4.2/V5 方向）

- 歷史回填功能（以 session_score ≥ threshold 作為篩選）
- team 真人試用（alice/bob 加入）
- Claude Haiku L2 升級（v4.1.1 標記項）
- Wisdom Engine 整合 session_score 做 meta-learning（V5）

V5 方向 handoff prompt 將在本 session 完成 + 觀察 1-2 週後產出。
