# Session C — V4.1 P2 前置：Prompts 撰寫 + lib/ollama_extract_core.py Refactor

> **模式**：不用 Plan Mode，plan 已定稿。Permission 建議 yolo 或 auto-accept。
> **CWD**：`~/.claude`
> **GIT**：Session B commit 後 → `git pull` → 再 commit。不需等 Session A。

---

## 目標

P2 的前置準備（不依賴 P1 的 detector output），為 Session B 完成後的整合 session 鋪路。

## 開工前必讀

- `plans/purring-percolating-glacier.md` §5 v2 架構（Stop worker 段）
- `_AIDocs/V4.1-design-roundtable.md`（AI 大師 + 語意大師 prompt 建議）
- `hooks/extract-worker.py`（~800 行，從中抽共用核心）
- `tools/ollama_client.py`（get_client / generate API）
- `hooks/quick-extract.py`（看 ollama 呼叫 pattern）

## Deliverable（新建 4 檔 + 修改 1 檔）

### 新建

#### 1. `prompts/user-decision-l1.md` — L1 qwen3:1.7b 二元 prompt

- 用途：L1 快篩，只判 yes/no，不輸出 confidence [F4]
- 參數：think=false, T=0, num_predict=20, timeout=10s
- 格式：

```
你是決策語句判斷器。判斷使用者的話是否表達一條「長期規則、偏好或決策」。
只輸出 JSON，不解釋。

正例：
  「以後一律用 pnpm，不要再 npm」→ {"is_decision": true}
  「記住：commit message 要寫中文」→ {"is_decision": true}
  「禁止在 hook 裡跑 git push」→ {"is_decision": true}
  「我偏好繁體中文回應」→ {"is_decision": true}
  「從現在起 port 改 3850」→ {"is_decision": true}

負例：
  「這樣做對嗎？」→ {"is_decision": false}
  「幫我改這個 bug」→ {"is_decision": false}（一次性任務）
  「也許可以試試 Redis？」→ {"is_decision": false}（探索）
  「靠 又壞了」→ {"is_decision": false}（情緒）
  「這次先用 tab」→ {"is_decision": false}（「這次」= 臨時）

使用者的話：{{user_prompt}}

JSON:
```

#### 2. `prompts/user-decision-l2.md` — L2 gemma4:e4b 結構化萃取 prompt

- 用途：對 L1 通過的候選做結構化萃取 + scope/audience/trigger 推斷
- 參數：think=auto, T=0, num_predict=200
- 輸入：`{{user_prompt}}` + `{{assistant_last_600_chars}}` [F9]
- 輸出 schema：
  ```json
  {
    "decision": true,
    "conf": 0.92,
    "scope": "personal|shared|role",
    "audience": "programmer",
    "trigger": ["pnpm", "npm", "套件管理"],
    "statement": "以後一律用 pnpm 取代 npm"
  }
  ```
- ≥ 8 few-shot 必含：
  - 時間副詞邊緣：「這次先用 X」(false) vs 「以後都用 X」(true)
  - 婉轉語 + context：「就這樣吧」在 assistant 提方案後 = true (conf 0.85)；在 debug 無解後 = false
  - 混合句：「這 API 爛死，改用 B」→ decision=true（抽「改用 B」忽略情緒）
  - scope 推斷：「我習慣用 vim」→ personal；「團隊規定 PR 要 2 reviewer」→ shared；「美術組用 PS」→ role
  - 輕量 stance [F9]：assistant 提「方案 A vs B」→ 使用者回「A」→ boost +0.3
- conf < 0.70 要輸出 `"decision": false`（不硬算 scope/trigger）

#### 3. `lib/ollama_extract_core.py` — 與 extract-worker.py 共用核心

從 `hooks/extract-worker.py` 抽出以下函式（保持原始 signature 不變）：

- `_call_ollama(prompt, model, timeout)` — line 150-163
- `_parse_llm_response(raw)` — line 252-265
- `_dedup_items(items, existing_queue, threshold)` — line 276-320
- `_word_overlap_score(a, b)` — line 268-273
- `_atom_debug_log(tag, content, config)` — line 77-93
- `_atom_debug_error(source, exc)` — line 96-102
- `_estimate_tokens(text)` — line 68-74

新增：
- `ack_then_clear(state_path, key, indices)` [F12]：原子讀 state → pop 指定 indices → 寫回
- `SessionBudgetTracker` class skeleton：`__init__(budget)`, `spend(tok)`, `remaining()`, `is_exceeded()`

#### 4. `lib/__init__.py` — 空檔

### 修改

#### 5. `hooks/extract-worker.py`

- 改 import：`from lib.ollama_extract_core import _call_ollama, _parse_llm_response, _dedup_items, _word_overlap_score, _atom_debug_log, _atom_debug_error, _estimate_tokens`
- `sys.path` 調整：加 `str(Path.home() / ".claude")` 確保 `lib/` 可 import
- 所有函式體移除（改用 import），邏輯 100% 不變
- `_per_turn_writeback` 中加入 ack-then-clear [F12]：寫入成功後 pop 該 item 從 knowledge_queue
- 跑 session_end / per_turn / failure 三 mode 行為必須完全不變

### 絕不碰

- `workflow-guardian.py`（Session B 處理）
- `settings.json`（Session B 處理）
- `server.js`（零修改 [F2]）
- `quick-extract.py`

## 驗收

```bash
# import 測試
python -c "from lib.ollama_extract_core import _call_ollama, _parse_llm_response; print('import ok')"

# 行為不變測試（如有既有 transcript 可用）
# 手動跑 extract-worker.py session_end mode 確認輸出與 refactor 前一致

# prompt 品質 review
# L1: 5 正例全 true、5 負例全 false
# L2: 8 few-shot 覆蓋所有邊緣 case
```

- extract-worker 既有行為 100% 不變
- `lib/` 可被未來 `user-extract-worker.py` 直接 import

## GIT

**重要**：commit 前先 `git pull`（Session B 可能已 commit 到同 repo）。
確認 pull 無衝突後 commit。

## 後續（整合 session，B+C 完成後才開）

Session B + C 都完成後，開第四個 session 整合：
- 新建 `hooks/user-extract-worker.py`（使用 `lib/` + 讀 state `pending_user_extract[]`）
- 整合測 50 條 P ≥ 0.92 / R ≥ 0.30
- git tag `v4.1.0-beta1`
- 整合 session 的 handoff prompt 將在 B+C 完成後產出
