# Session D — V4.1 P2 整合：user-extract-worker.py + 整合測試

> **模式**：不用 Plan Mode，plan 已定稿。Permission 建議 yolo 或 auto-accept。
> **CWD**：`~/.claude`
> **GIT**：完成即 commit + `git tag v4.1.0-beta1`。
> **前置條件**：Session B (P1 alpha1) + Session C (P2 前置) 已完成並 commit。

---

## 目標

把 P1 的 L0 detector + P2 前置的 lib/prompts 整合成完整的 Stop hook async worker，跑通 50 條整合測試 P ≥ 0.92 / R ≥ 0.30。

## 開工前必讀

- `plans/purring-percolating-glacier.md` §5 v2 架構（完整流程圖）+ §6 P2 驗收
- `_AIDocs/V4.1-design-roundtable.md`（圓桌設計摘要）
- `hooks/wg_user_extract.py`（P1 產出，L0 detector API：`detect_signal(prompt) -> dict`）
- `lib/ollama_extract_core.py`（P2 前置產出，共用核心 + ack_then_clear + SessionBudgetTracker）
- `prompts/user-decision-l1.md` + `prompts/user-decision-l2.md`（P2 前置產出）
- `hooks/extract-worker.py`（已 refactor 成 thin wrapper，看 pattern）
- `hooks/workflow-guardian.py`（看 P1 加的 UserPromptSubmit gate + `pending_user_extract[]` schema）
- `workflow/config.json`（看 `userExtraction` 區塊 + ollama backend config）

## Deliverable（新建 2 檔 + 修改 2 檔）

### 新建

#### 1. `hooks/user-extract-worker.py` — Stop hook detached worker（核心交付）

仿 `extract-worker.py` pattern（但用 `lib/ollama_extract_core.py` 共用核心，不複製）：

**入口**：
- 從 stdin 讀 JSON context（同 extract-worker.py 新介面）
- 或 SessionEnd 觸發由 workflow-guardian.py spawn 為 detached subprocess

**主流程**：
```
讀 state-{sid}.json 的 pending_user_extract[] (P1 寫入的)
  ↓
session budget tracker 初始化 (budget=240 from config)
  ↓
for each candidate in pending_user_extract:
  ↓
  ├─ 混合句偵測 [F10]：情緒詞 ∧ 決策訊號共存
  │   → 寫 systemMessage "↑此句含情緒+決策，請拆分後重述" → skip
  │
  ├─ 情緒承諾偵測 [F24]：「絕不/再也不/一律」+ 情緒詞
  │   → emotional_commitment=true → 暫存 24h 冷卻 queue → skip
  │
  ├─ budget.spend() 檢查：超 220 → L1-only；超 240 → break
  │
  ├─ L1: 讀 prompts/user-decision-l1.md 模板
  │   qwen3:1.7b, think=false, T=0, num_predict=20, timeout=10s
  │   → is_decision=false → skip
  │   → is_decision=true → 進 L2
  │
  ├─ L2: 讀 prompts/user-decision-l2.md 模板
  │   gemma4:e4b, think=auto, T=0, num_predict=200
  │   填入 {{user_prompt}} + {{assistant_last_600_chars}}
  │   → parse JSON response (用 lib._parse_llm_response)
  │   → conf < 0.70 → skip
  │   → 0.70-0.92 → 寫 personal/auto/{user}/_pending.candidates.md
  │   → conf ≥ 0.92 → 顯式提示路徑（見下）
  │
  └─ 顯式提示 + 預設同意 [F5]：
      conf ≥ 0.92 的 candidate 暫存到 state 新欄位 `confirmed_extractions[]`
      下一 turn UserPromptSubmit hook 檢查：
        使用者回「否」→ pop + 寫 _rejected/ + reflection_metrics
        使用者沒回「否」→ ack_then_clear → MCP atom_write 寫入
```

**atom_write 呼叫規格**：
- scope: L2 輸出的 scope（預設 personal）
- author: "auto-extracted-v4.1"
- audience: L2 輸出的 audience
- trigger: L2 輸出的 trigger keywords
- confidence: [臨]
- knowledge: L2 輸出的 statement
- footer: `<!-- src: {sid}-{turn_n} -->`  [F1]
- 落點：`personal/auto/{user}/{slug}.md` [F17]
- 走既有 write-gate + conflict-detector（不 skip [F2]）
- Related: 單向 vector top-3 ≥ 0.65 [F15]
- dedup: 短句 fallback embedding ≥ 0.92 + 否定詞極性檢查 [F16]

**assistant_last_600_chars 取得**：
- 從 transcript JSONL 讀最後一個 `type=="assistant"` block 的 content
- 取 last 600 chars（不是前 600）[F9]
- 如果沒有 assistant block → 留空（L2 prompt 有 fallback）

**錯誤處理**：
- ollama timeout → skip 該 candidate，保留 pending（下次 session retry 1 次，>2 → 丟棄）
- invalid JSON → lib._parse_llm_response salvage；salvage 失敗 → skip
- MCP atom_write 失敗 → log 但不 crash；candidate 保留 pending
- 全程 fail-open：任何異常不阻塞 hook chain

**跨平台**：
- Windows: CREATE_NO_WINDOW | DETACHED_PROCESS（抄 extract-worker.py）
- cp950: sys.stdout/stderr reconfigure encoding='utf-8'
- file lock: 用 lib 的 atomic write pattern

**append _merge_history.log**：
- action=auto-extract-v41

#### 2. `tests/integration/test_e2e_user_extract.py` — 整合測試

- 50 條測試案例（25 正 + 15 負 + 10 邊緣）
- 正例覆蓋：強信號決策、中信號偏好、scope=shared 團隊規範、stance（assistant 提選項+user 回應）
- 負例覆蓋：問句、情緒、一次性任務、探索、閒聊、純程式碼
- 邊緣覆蓋：婉轉語（「就這樣」）、混合句（情緒+決策）、情緒承諾（「絕不再用 X」）、時間副詞（「這次先」）
- **需 `--ollama-live` flag**：真跑 ollama L1+L2（不 mock）
- 驗收紅線：P ≥ 0.92 / R ≥ 0.30
- 額外驗：token budget tracker 不超 240

### 修改

#### 3. `hooks/workflow-guardian.py`

- Stop hook handler 加 spawn `user-extract-worker.py` 邏輯（仿 extract-worker spawn pattern）
- 條件：`cfg.userExtraction.enabled == true` 且 `state.pending_user_extract` 非空
- detached subprocess，不阻塞 Stop hook return
- 顯式提示 [F5]：從 state 讀 `confirmed_extractions[]` → 產 systemMessage
  - 格式：`[V4.1] 偵測到決策語句：「{statement}」— 將記為 atom。回覆「否」可攔截。`
- drain 語義 [F26] 已在 P1 加入，確認整合

#### 4. `tests/regression/test_v4_atoms_unchanged.py`

- 讀 `tests/fixtures/v4_atoms_baseline.jsonl`
- 對每個 atom 重算 SHA256
- 任何 SHA256 不符 → FAIL
- 用途：確保 V4.1 整合過程沒動到任何 V4 atom

### 絕不碰

- `wg_user_extract.py`（P1 產出，已穩定）
- `lib/ollama_extract_core.py`（P2 前置產出，已穩定）
- `prompts/`（P2 前置產出，已穩定）
- `extract-worker.py`（已 refactor，不再動）
- `server.js`（零修改 [F2]）
- `SPEC_ATOM_V4.md`（零修改 [F1]）

## 驗收

```bash
# 回歸：V4 atoms 不變
pytest tests/regression/test_v4_atoms_unchanged.py -v

# 整合測（需 ollama 在線）
pytest tests/integration/test_e2e_user_extract.py --ollama-live -v
# 驗收：P ≥ 0.92 / R ≥ 0.30

# token budget
# 跑 30 prompts 模擬 session → amortized ≤ 240 tok

# flag=false 仍然 zero overhead
pytest tests/test_v41_disabled.py -v
```

**驗收紅線**：
- 50 條整合測 P ≥ 0.92 / R ≥ 0.30
- V4 atoms SHA256 全部不變
- token amortized ≤ 240
- flag=false zero overhead 不退化

## GIT

完成即 commit + `git tag v4.1.0-beta1`。

## 後續（P3 + P4）

P2 整合完成後，下一批：

**Session E — V4.1 P3：UX commands + 每日推送 + 隱私體檢**
- `commands/memory-peek.md` + `tools/memory-peek.py`（列最近 24h + trigger 原因 [F7]）
- `commands/memory-undo.md` + `tools/memory-undo.py`（`--since` + `--all-from-today` [F20] + reason 分類 [F23]）
- `workflow-guardian.py` SessionStart 每日推送 [F18]
- `/init-roles` 加隱私體檢 [F21]
- git tag `v4.1.0-rc1`

**Session F — V4.1 P4：歷史回填 + 試用 + 驗收**
- `tools/v41_backfill.py`（conf ≥ 0.92 高精準歷史回填 [F8]）
- holylight 試用 5-7 天 + 誘餌題明知協議 [F19]
- 100 條抽樣 P/R + token audit
- git tag `v4.1.0`

E 和 F 有 hard dependency（F 需 E 的 peek/undo），不可平行。
Session E 的 handoff 將在 P2 整合完成後產出。
