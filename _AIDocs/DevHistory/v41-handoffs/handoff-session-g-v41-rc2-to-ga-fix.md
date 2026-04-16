# Session G — V4.1 rc2 → GA：整合測 L1/L2 silent-return 修復

> **模式**：診斷 + bug fix。不用 Plan Mode。Permission 建議 yolo。
> **CWD**：`~/.claude`
> **GIT**：完成 + 整合測通過 → commit → `git tag v4.1.0` (GA) → push + push --tags。
> **前置條件**：rc2 已發（`v4.1.0-rc2`, commit `90d5008`）；整合測 R=0.00 是唯一 GA blocker。

---

## 目標

清掉 P4 GA blocker：整合測 `tests/integration/test_e2e_user_extract.py::TestPrecisionRecall` recall=0。根因**不是** ollama 連線問題（已排除），是 pipeline L1/L2 call 有 silent early-return。找到 → 修 → 整合測過紅線 → promote `v4.1.0`。

## Session F 報告摘要

```
最終狀態：tag v4.1.0-rc2 已推（gitlab + github），3 commits:
  740867d — feat: P4 session evaluator
  bc10e41 — test: agent multi-role simulation
  90d5008 — feat: 文件 + baseline + rc2

GA blocker:
  - 整合測 aggregate P=1.00、R=0.00
  - Session F 當時推測是 "rdchat 後端 HTTP 404/400 + gemma4:e4b 未安裝"

Sub-task B 發現（V4.2 項）:
  - L0 Precision=1.00 Recall=0.40 — 對「習慣/只能/數值邊界/程序性/婉轉」五類中文模式有系統性漏洞
  - JIT role-filter 為 code-enforced invariant，無洩漏可能
```

## 前一 session 已排除 + 已確認事實（**不要重複驗證**）

排除項 — 不是這些：
1. ❌ **rdchat-direct endpoint 問題**：`curl http://192.168.199.130:11434/api/tags` 回 200，列出 25+ models
2. ❌ **gemma4:e4b 不存在**：model list 明確有 `gemma4:e4b`（第 3 項）
3. ❌ **ollama_client backend selection 錯**：
   ```python
   client = get_client(); backend = client._pick_backend('llm')
   # → rdchat-direct, base_url=http://192.168.199.130:11434, llm_model=gemma4:e4b
   ```
4. ❌ **L2 prompt 有問題**：手測 L2 prompt + gemma4:e4b 直呼 → 3.4s 回 valid JSON `{"decision": true, "conf": 0.92, "scope": "personal", ...}`
5. ❌ **L0 detector 過嚴**：直測 16 條整合測正例，L0 全抓到 signal=True（recall=1.00）

已確認現象：
- `pytest tests/integration/test_e2e_user_extract.py --ollama-live -v` → **2.86 秒跑完 40 個 test case**
- 正例 tp=0 / fn=25；負例 tn=15 / fp=0
- 2.86s / 25 正例 = 114ms/case — 完全不可能有 L1 LLM 呼叫（每次 ≥ 3s）
- **所以 pipeline 在 L1 之前或 L1 _call_l1 內部 early-return None**

## 根因候選（照此順序診斷）

### 候選 1（最可能）：`_call_l1` / `_call_l2` / `_load_l1_prompt` / `_load_l2_prompt` 在 pytest 環境 exception 被吞

位置：`tests/integration/test_e2e_user_extract.py` 頂部約 70-136 行區域（`_call_l1` / `_call_l2`）。

檢查：
- 這 4 個函式是否有 `try/except` 吞了 exception 回 None
- `sys.path.insert` 是否在 pytest 環境漏了 `hooks/` 或 `tools/`
- `_load_l1_prompt` 讀 `prompts/user-decision-l1.md` 的路徑：用 `Path.home() / ".claude" / "prompts" / ...` 還是相對路徑？pytest 當前工作目錄可能不是 `~/.claude`

**快速診斷法**：
```python
# 在 _run_pipeline 加臨時 print
print(f"L0={l0}")
print(f"L1 prompt loaded: {len(l1_prompt) if l1_prompt else 'NONE'}")
print(f"L1 result: {l1_result}")
print(f"L2 prompt loaded: {len(l2_prompt) if l2_prompt else 'NONE'}")
print(f"L2 result: {l2_result}")
# 跑 1 個 case 看哪一步開始 None
pytest tests/integration/test_e2e_user_extract.py::TestPrecisionRecall -v -s
```

### 候選 2：`_call_l1` / `_call_l2` 內部檢查 flag `userExtraction.enabled == false` 就 skip

整合測時 `config.json` 的 `userExtraction.enabled` 仍是 **false**（shadow mode）。若 `_call_l1` 有讀 config gate，會全部 skip。

檢查：
- `_call_l1` / `_call_l2` 內部是否讀 config？
- 若有，整合測需要臨時 enable（用 monkeypatch fixture 或 env var）

### 候選 3：`_load_l1_prompt` / `_load_l2_prompt` 檔名或路徑錯

檢查：
- 實際檔名：`prompts/user-decision-l1.md` + `prompts/user-decision-l2.md`（確認存在）
- 函式內部 path 組法
- 讀不到檔 → `_load_l1_prompt` 回空字串 → `_call_l1(空)` → ollama 拒絕 → early return

## 修復後驗收

```bash
# 1. 整合測過紅線
pytest tests/integration/test_e2e_user_extract.py --ollama-live -v
# 必要：Precision ≥ 0.92 / Recall ≥ 0.30

# 2. 回歸未退化
pytest tests/regression/test_v4_atoms_unchanged.py -v
pytest tests/test_v41_disabled.py -v
pytest tests/test_user_detector.py -v
pytest tests/test_session_evaluator.py -v

# 3. 手測兩條真實 flow
/memory-peek
/memory-session-score --last
```

## Promote GA

修復通過後：

1. `settings.json` 把 `userExtraction.enabled` 從 **false → true**
2. `settings.json` `mode` 從 **shadow → production**
3. `_AIDocs/_CHANGELOG.md` 加 `v4.1.0` GA 發布紀錄（替換 rc2 段落或新增）
4. commit：
   ```
   fix(atom-v4.1): integration test L1/L2 silent-return root cause + 修復
   
   Session F rc2 blocker 清除：{具體根因}
   修復後 integration test P=X.XX / R=X.XX 通過紅線
   userExtraction flag enable → production
   ```
5. `git tag v4.1.0`
6. `git push && git push --tags`

## 絕不碰

- `wg_user_extract.py` / `lib/ollama_extract_core.py` / `prompts/`：P1/P2 前置已穩定
- `workflow/config.json` 的 ollama_backends 區塊（已驗證正確）
- V4 atoms / server.js / SPEC_ATOM_V4.md

## V4.2 待辦（**不做**，只記錄）

Session F Sub-task B 發現的 L0 五類中文漏洞 → 寫入 `_staging/v42-candidates.md`（本 session 順便建立）：
- 「習慣」類：「我習慣 X」未被 L0 抓
- 「只能」類：「只能用 X」未抓
- 「數值邊界」類：「至少 / 至多 / 不超過 N」未抓
- 「程序性」類：「每次 / 每個 / 每當」未抓
- 「婉轉」類：「盡量 / 基本上 / 原則上」未抓

## Context 提示

若修復 1-2 次未果，再試第 3 次前呼叫 `/fix-escalation` 走 6 Agent 精確修正會議（fix escalation rule）。
