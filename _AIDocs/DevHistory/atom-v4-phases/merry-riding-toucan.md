# Plan — V4.1 P4 Session 評價機制 + Agent 多 Role 模擬 + v4.1.0 GA

> Handoff: `memory/_staging/handoff-session-f-v41-p4-evaluator-simulation.md`
> Plan v2: `plans/purring-percolating-glacier.md` §6 P4

---

## Context（為什麼）

V4.1 P1-P3 已完成（alpha1 / beta1 / rc1）：L0 detector + L1/L2 worker pipeline + UX 指令 + 每日推送 + 隱私體檢。本 session 是 **最終收尾**：

1. **新增 Session 評價機制** — 使用者拍板 Q3(d)，原 plan v2 未規劃的架構擴充。每 session 結束後用 5 維度加權算出 `session_score`，寫進 `reflection_metrics.v41_extraction.session_scores[]`。未來 V4.2 以此分數決定歷史回填範圍，V5 Wisdom Engine 做 meta-learning。
2. **Agent 多 Role 模擬試用** — 使用者拍板 Q2(d)，取代真人試用（alice/bob 不適用）。讓 general-purpose agent 扮演 sgi 專案的 programmer 和 planner，在 `C:\Projects` 做 5-10 turn 真實討論，驗證 scope 分流 + JIT role-filter。
3. **抽樣 P/R + 正式發布** — 65 條抽樣驗證紅線，切 flag 預設啟用，tag `v4.1.0`。

**紅線**（任一不過 → 回對應 Phase 修）：
- Precision ≥ 0.92 / Recall ≥ 0.30（65 條抽樣）
- token amortized ≤ 240/session
- V4 atoms SHA256 不變（regression test）
- 兩 role agent 分流正確 + JIT 跨 role 無洩漏
- `session_score` 分布合理（非全 0 或全 1）

---

## Sub-task A — Session Evaluator（~1.5d）

### 架構決策：誰跑、何時跑

- **不是** SessionEnd 獨立 detached subprocess（handoff 第一稿寫法，但會跟 user-extract-worker race）
- **而是** 整合進 worker 的 main() 尾端 + SessionEnd 無 pending 的 fallback inline 呼叫
- 兩條路徑都保證 evaluator 看到 **最新 state + worker stats**，無 race condition

**路徑 A**（有 pending，worker 跑起來）：
```
SessionEnd → _maybe_spawn_user_extract_worker → worker.run_user_extraction() 完成後
  → worker 呼叫 wg_session_evaluator.evaluate_session(sid, state_after, config, worker_stats)
  → 寫 reflection_metrics.v41_extraction.session_scores[]
```

**路徑 B**（無 pending，worker 沒跑）：
```
SessionEnd → handle_session_end() 尾端 inline 呼叫
  → wg_session_evaluator.evaluate_session(sid, state, config, worker_stats=None)
  → 寫 reflection_metrics.v41_extraction.session_scores[]
```

### Deliverable 1：`hooks/wg_session_evaluator.py`（新增）

**介面**：
```python
def evaluate_session(
    session_id: str,
    state: Dict,
    config: Dict,
    worker_stats: Optional[Dict] = None,
) -> Dict:
    """Pure Python, no I/O outside reflection_metrics.json. <100ms."""
```

**5 維度計算**（handoff §A 表格）：
| 維度 | 權重 | 公式 |
|---|---|---|
| density | 0.15 | `tanh(extract_triggered / max(prompt_count, 1))` |
| precision_proxy | 0.35 | `avg_l2_conf` if L2 跑過 else 1.0（無樣本保守給滿）|
| novelty | 0.20 | `confirmed / max(confirmed + dedup_hit, 1)` |
| cost_efficiency | 0.15 | `max(0, 1 - token_used / 240)` |
| trust | 0.15 | `1 - (rejected_24h / max(total_written_24h, 1))` |

**input 取值對照**：
- `prompt_count` ← `state.topic_tracker.prompt_count`
- `extract_triggered` ← `worker_stats.processed` if 有，else `len(state.pending_user_extract)` 初始值（需於 spawn 前記錄）
- `confirmed` ← `worker_stats.confirmed`（conf ≥ 0.92 寫入數）
- `dedup_hit` ← `worker_stats.dedup` 或 0（worker 目前未追蹤，本 session 加）
- `avg_l2_conf` ← `worker_stats.avg_l2_conf`（目前未追蹤，本 session 加）
- `token_used` ← `worker_stats.token_used`（= 240 - tracker.remaining()，本 session 加）
- `total_written_24h` ← `reflection_metrics.v41_extraction.total_written`
- `rejected_24h` ← `reflection_metrics.v41_extraction.total_rejected`

**輸出 schema**（append 到 `v41_extraction.session_scores[]`，FIFO cap 100）：
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
    "density": 0.72, "precision_proxy": 0.89, "novelty": 0.71,
    "cost_efficiency": 0.26, "trust": 1.00, "weighted_total": 0.72
  }
}
```

**reflection_metrics.json 原子寫入**：tmp → rename（同 `memory-undo.py` pattern [tools/memory-undo.py:239-241](tools/memory-undo.py#L239)）。

### Deliverable 2：`hooks/user-extract-worker.py` 修改（~30 行）

- `run_user_extraction()` 新增 tracking：
  - `l2_confs: List[float]` — 每次 L2 成功後 append `l2_result["conf"]`
  - `dedup_hit` counter — `_write_atom_via_mcp()` 改回傳 `"wrote" | "deduped" | "failed"`，worker 計數
  - `token_used = 240 - budget.remaining()`
- return stats 新增：`avg_l2_conf`, `dedup_hit`, `token_used`
- main() 末尾：若 `config.userExtraction.enabled` → 呼叫 `wg_session_evaluator.evaluate_session(sid, fresh_state, config, stats)` → 寫 reflection_metrics

### Deliverable 3：`hooks/workflow-guardian.py` 修改（~10 行）

- [hooks/workflow-guardian.py:1739](hooks/workflow-guardian.py#L1739) `handle_session_end` 末端加：若 `userExtraction.enabled` AND 沒 spawn worker（pending 為空）→ inline 呼叫 evaluator（worker_stats=None，會算出 low-density session 的 baseline score）

### Deliverable 4：`tests/test_session_evaluator.py`（新增，5 個測試）

```python
1. test_high_score_session  # 20 prompts, 10 extract, 8 confirmed, avg_conf=0.95 → weighted ≥ 0.80
2. test_medium_score_session  # 30 prompts, 5 extract, 3 confirmed, avg_conf=0.80 → weighted 0.50-0.70
3. test_low_score_session   # 50 prompts, 1 extract, 0 confirmed → weighted ≤ 0.40
4. test_no_extraction_session  # worker_stats=None → precision_proxy=1.0, density=0, trust=1.0
5. test_fifo_cap_100  # append 105 次 → session_scores 長度 = 100，最舊被擠掉
```

無 LLM 呼叫，純 mock state + config，pytest 秒跑。

### Deliverable 5：`commands/memory-session-score.md` + `tools/memory-session-score.py`（新增）

- CLI：`/memory-session-score [--last|--since=24h|--top-N]`
- Backend：讀 `reflection_metrics.v41_extraction.session_scores[]`，格式化呈現：
  ```
  [V4.1 Session Scores]
  [2026-04-16 15:42] session=abc123  weighted=0.72
    density=0.72  precision=0.89  novelty=0.71  cost=0.26  trust=1.00
    30 prompts | 8 triggered | 5 written | conf avg 0.89 | 178 tok
  ```
- 未來 V4.2 `/v41-backfill --score-threshold=0.5` 以此作篩選依據

### 可驗收標準

- 5 個單元測試 pass
- 跑 10 個歷史 session（手動 session_id）全部算出 score
- 本 session 結束時自動寫入一筆（validation fresh run）
- `session_scores` 分布合理：新寫的 ≥ 3 筆，weighted 不全 0 也不全 1

---

## Sub-task B — Agent 多 Role 模擬試用（~0.5d）

### 前置

1. `cd C:\Projects`（sgi 專案）
2. 若沒跑過 `/init-roles` → 跑一次，建兩個 personal role 宣告
   - 命名：`holylight-programmer/role.md`（先看 init-roles 支援 `{user}-{role}` 還是單純 `role.md`，若後者則只能單 role，需分兩次切換）
   - 在 `_roles.md` 白名單登記
3. `settings.json` 確認 `userExtraction.enabled=true`（本 session 最後 commit 3 才整體切開，但試用階段可手動臨時 true）
4. `/vector` 確認向量服務運作

### Round 1 — programmer role（Agent subagent_type=general-purpose）

Prompt 詳見 handoff L122-130。重點：
- 至少 3 個「長期技術決策」
- 至少 2 個「個人偏好」
- 至少 1 個「一次性問題」（應**不被**萃取）
- 1 個情緒混合句（應強制 interactive confirm 或 skip）

**驗證**：`/memory-peek --since=1h` → 看 personal/auto/holylight/ 下新增 atom 是否 ≥ 3 決策 + 2 偏好，且不含一次性問題/情緒句。

### Round 2 — planner role

Prompt 詳見 handoff L138-144。重點：
- 2 個「設計規範拍板」
- 1 個「跨職能規範」（應入 shared/）
- 1 個婉轉決策（走 F5 顯式提示 + 預設同意）

**驗證**：scope 分流正確（role:planner vs shared），婉轉決策在下一 turn 無否決時被記入。

### Round 3 — 混合檢查 + JIT 驗證

1. `/memory-peek`：兩 role atom 並陳檢視
2. `/memory-session-score`：兩 session 評分都已寫入
3. 刻意 `/memory-undo last` 一條（測試摩擦力 ≤ 2 enter [F20][F23]）
4. 重開 programmer session → 驗 JIT 注入**不含** planner role atom（role filter 隔離）
5. 誘餌題：重開 session 後提「上次 Round 1 那個決策」→ AI 應 recall「上次拍板 X」

### 可驗收標準

- 兩 role atom 正確分流 + JIT 跨 role 無洩漏
- 誘餌 ≥ 3/5 命中
- `/memory-undo` ≤ 2 enter
- 兩 session_score 都寫入 reflection_metrics

---

## Sub-task C — 抽樣 P/R + v4.1.0 GA（~0.5d）

### 1. 抽樣 P/R（65 條 = P2 整合測 50 + Round 1+2 新產出 ~15）

- 手工標記 ground truth（決策 yes/no + scope 分類）
- 比對 V4.1 實際萃取
- 計算 Precision / Recall / scope 推斷準確率
- **紅線**：P ≥ 0.92 / R ≥ 0.30（不過 → 回 P1/P2 調 L0/L1/L2 prompt）

### 2. Token NFR 驗證

```bash
python tools/v41_token_budget_audit.py --sessions 30
# amortized ≤ 240 tok/session
```

若 `v41_token_budget_audit.py` 不存在（plan v2 §11 提及但未必已建），本 session 補建（簡易版：讀 reflection_metrics.session_scores 取最近 30 筆 token_used 平均）。

### 3. 正式發布

依序：
1. `_AIDocs/Architecture.md` 補「V4.1 Session 評價機制」段（子任務 A 產物）
2. `_AIDocs/_CHANGELOG.md` 加 `v4.1.0` 發布紀錄
3. `settings.json`：
   - `userExtraction.enabled` → **true**
   - `userExtraction.mode` → **`production`**（若 plan v2 有此欄）
4. git commit + `git tag v4.1.0`
5. `git push && git push --tags`

---

## 絕不碰

- V4 atoms（以 `pytest tests/regression/test_v4_atoms_unchanged.py` 最終守門）
- `tools/workflow-guardian-mcp/server.js` [F2]
- `_AIDocs/SPEC_ATOM_V4.md` [F1]
- P1/P2/P3 已發布的核心 deliverable 邏輯（`wg_user_extract.py`, `lib/ollama_extract_core.py` 核心 pipeline, `memory-peek.py`, `memory-undo.py`）— 本 session 只擴，不改邏輯

---

## 實作順序（單 session 線性）

| 步驟 | 動作 | 驗證 |
|---|---|---|
| 1 | 寫 `hooks/wg_session_evaluator.py` | 模組可 import 無 syntax err |
| 2 | 改 `user-extract-worker.py`（tracking + evaluator 呼叫） | 語法 OK |
| 3 | 改 `workflow-guardian.py handle_session_end`（fallback 路徑） | 語法 OK |
| 4 | 寫 `tests/test_session_evaluator.py` | 5 tests pass |
| 5 | 跑 regression：`pytest tests/regression/test_v4_atoms_unchanged.py` | SHA256 不變 |
| 6 | 跑 disabled test：`pytest tests/test_v41_disabled.py` | flag off 零影響 |
| 7 | 寫 `tools/memory-session-score.py` + `commands/memory-session-score.md` | `/memory-session-score --last` 可執行（dry run） |
| 8 | **commit 1** — feat(atom-v4.1): session evaluator |  |
| 9 | cd `C:\Projects`，跑 `/init-roles`（若需） + Round 1 programmer agent | peek 驗 ≥ 3 決策 + 2 偏好 |
| 10 | Round 2 planner agent | scope 分流正確 |
| 11 | Round 3 混合 + JIT + 誘餌 | 無跨 role 洩漏 |
| 12 | **commit 2** — test(atom-v4.1): P4 multi-role simulation |  |
| 13 | 65 條抽樣 P/R（csv 標 ground truth → python 比對） | P ≥ 0.92 / R ≥ 0.30 |
| 14 | token NFR audit（若 `v41_token_budget_audit.py` 缺，補簡易版） | amortized ≤ 240 |
| 15 | 改 `_AIDocs/Architecture.md` + `_CHANGELOG.md` + `settings.json` flag 切 true |  |
| 16 | 跑整合測 `pytest tests/integration/test_e2e_user_extract.py --ollama-live` | 65 條紅線通過 |
| 17 | **commit 3** + `git tag v4.1.0` + `git push && git push --tags` |  |

---

## 關鍵檔案清單

**新增（5 個）**：
- [hooks/wg_session_evaluator.py](hooks/wg_session_evaluator.py) — 5 維度評分核心
- [tests/test_session_evaluator.py](tests/test_session_evaluator.py) — 5 單元測試
- [commands/memory-session-score.md](commands/memory-session-score.md) — skill 定義
- [tools/memory-session-score.py](tools/memory-session-score.py) — skill backend
- [tools/v41_token_budget_audit.py](tools/v41_token_budget_audit.py) — 若不存在則補

**修改（4 個 + 1 schema）**：
- [hooks/user-extract-worker.py](hooks/user-extract-worker.py) — tracking + evaluator 呼叫（~30 行）
- [hooks/workflow-guardian.py](hooks/workflow-guardian.py) — handle_session_end fallback 路徑（~10 行）
- [memory/wisdom/reflection_metrics.json](memory/wisdom/reflection_metrics.json) — `v41_extraction.session_scores[]`（由 evaluator 動態寫）
- [settings.json](settings.json) — `userExtraction.enabled: true` + `mode: production`
- [_AIDocs/Architecture.md](../_AIDocs/Architecture.md) + [_AIDocs/_CHANGELOG.md](../_AIDocs/_CHANGELOG.md)

---

## Verification（最終紅線）

```bash
# 回歸
pytest tests/regression/test_v4_atoms_unchanged.py -v      # V4 atoms SHA256 不變
pytest tests/test_v41_disabled.py -v                       # flag 可切回 false

# 新增
pytest tests/test_session_evaluator.py -v                  # 5 單元測試 pass

# 整合（真 ollama）
pytest tests/integration/test_e2e_user_extract.py --ollama-live -v  # 65 條 P ≥ 0.92 / R ≥ 0.30

# Skill 手動
/memory-peek
/memory-undo last
/memory-session-score --last

# E2E in C:\Projects
# Round 1+2+3 → session_score 兩個都算出 → JIT role-filter 驗成功

# GA
git log --oneline | head -3   # 看到 3 個 v4.1 P4 commit
git tag -l v4.1.0               # tag 存在
```
