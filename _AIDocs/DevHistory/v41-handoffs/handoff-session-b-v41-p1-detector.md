# Session B — V4.1 P1：L0 Detector + Feature Flag + V4 Baseline Fixture

> **模式**：不用 Plan Mode，plan 已定稿。Permission 建議 yolo 或 auto-accept。
> **CWD**：`~/.claude`
> **GIT**：完成即 commit + `git tag v4.1.0-alpha1`。不等其他 session。

---

## 目標

Phase 1 alpha 版：純規則 detector (≤5ms) + feature flag + V4 atoms snapshot baseline。

## 開工前必讀

- `plans/purring-percolating-glacier.md` §5 v2 架構（UserPromptSubmit 段）+ §6 P1 驗收
- `_AIDocs/V4.1-design-roundtable.md`（圓桌設計紀錄）
- `hooks/workflow-guardian.py`（UserPromptSubmit handler 目前邏輯）
- `settings.json`（看既有結構）

## Deliverable（新建 4 檔 + 修改 2 檔）

### 新建

#### 1. `hooks/wg_user_extract.py` — L0 規則 detector

- 信號詞表（中+英）：
  - 強 (w=1.0)：記住、永遠、從此、以後都要、禁止、一律、統一、決定、規定、約定、remember、always、never、from now on、must
  - 中 (w=0.6)：改用、不要再、下次、固定、偏好、我要、我不要、prefer、switch to、stop using
  - 負 (w=-0.8)：也許、可能、試試、好不好、maybe、perhaps、might
- 句法 pattern [F27]：
  - `[我/我們] + [情態詞(要/會/得/該/必須)] + V + O`
  - `[都/一律/固定/統一] + V`
  - 否定 `[不/禁/別/勿/停] + V`
- 排除 pattern：
  - 結尾 `?` / `？` / `嗎` / `呢` → skip
  - 長度 < 8 字 或 > 500 字 → skip
  - 純程式碼 block（含 ``` 或 4+ 空格開頭佔 > 80%）→ skip
- 輸出：`{"signal": bool, "score": float, "matched": ["keyword1", "pattern2"]}`
- 必須 ≤ 5ms（純 regex + dict lookup，無 I/O，無 import heavy modules）
- 暴露函式 `detect_signal(prompt: str) -> dict`

#### 2. `tools/snapshot-v4-atoms.py` [F13]

- 讀 `memory/project-registry.json` 掃所有專案 + global atoms
- 輸出 `tests/fixtures/v4_atoms_baseline.jsonl`
- 每行 JSON：`{"path": "abs_path", "sha256": "hex", "metadata_fields": ["Scope", "Author", ...]}`
- 用途：regression test 驗證 V4.1 不改動任何 V4 atom

#### 3. `tests/test_user_detector.py` — pytest

- ≥ 20 正例（強/中信號混合）
- ≥ 20 反例（問句/情緒句/短句/程式碼/英文閒聊）
- ≥ 10 邊緣例（「這次先用 X」「也行」「就這樣」「好不好」含混語）
- 驗收紅線：P ≥ 0.95 / R ≥ 0.55

#### 4. `tests/test_v41_disabled.py`

- flag=false 時整個 V4.1 路徑 zero overhead
- import wg_user_extract 不應有 side effect
- UserPromptSubmit handler 碰不到 detect_signal

### 修改

#### 5. `settings.json`

新增區塊（與既有結構平行）：
```json
"userExtraction": {
  "enabled": false,
  "mode": "shadow",
  "tokenBudget": 240
}
```

#### 6. `hooks/workflow-guardian.py`

UserPromptSubmit handler 加 gate：
- 讀 config `userExtraction.enabled`，false 時完全 skip
- true 時呼叫 `wg_user_extract.detect_signal(prompt)`
- signal=true → append `state["pending_user_extract"]`
  - schema：`{"turn_id": "{sid}-{n}", "prompt": "原文", "score": 0.7, "matched": ["記住"], "ts": "ISO8601"}`
- state GC 滑窗 cap 10 [F11]：超過丟最舊
- drain 語義 [F26]：flag 切 off → SessionEnd 清空 `pending_user_extract`

### 絕不碰

- `extract-worker.py`（Session C 處理 refactor）
- `server.js`（零修改 [F2]）
- `SPEC_ATOM_V4.md`（零修改 [F1]）
- 所有 V4 atoms

## 驗收

```bash
pytest tests/test_user_detector.py -v      # P ≥ 0.95 / R ≥ 0.55
pytest tests/test_v41_disabled.py -v       # flag=false zero side effect
python tools/snapshot-v4-atoms.py          # 產出 baseline fixture
```

- 手測 UserPromptSubmit latency +≤ 15ms（10 次取 p95）
- `git tag v4.1.0-alpha1`

## GIT

完成即 commit + tag。不等 Session A 或 C。
