# Session E — V4.1 P3：UX Commands + 每日推送 + 隱私體檢

> **模式**：不用 Plan Mode，plan 已定稿。Permission 建議 yolo 或 auto-accept。
> **CWD**：`~/.claude`
> **GIT**：完成即 commit + `git tag v4.1.0-rc1`。
> **前置條件**：P1 (alpha1) + P2 前置 + P2 整合 (beta1) 全部完成。

---

## 目標

使用者面向工具：查看自動萃取結果、一鍵撤銷、每日摘要推送、隱私安全體檢。對應 plan v2 §6 P3。

## 開工前必讀

- `plans/purring-percolating-glacier.md` §5 v2 架構 + §6 P3 驗收
- `_AIDocs/V4.1-design-roundtable.md`（UX 大師 + 人文大師相關段）
- `hooks/user-extract-worker.py`（P2 產出，看 confirmed_extractions / _rejected 寫入格式）
- `hooks/workflow-guardian.py`（看 SessionStart handler 目前邏輯 + state schema）
- `tools/conflict-review.py`（參考既有 command+tool 對偶 pattern）
- `commands/conflict-review.md`（參考 skill 文件格式）
- `memory/wisdom/reflection_metrics.json`（看現有 schema，要擴充 v41 欄位）

## Deliverable（新建 4 檔 + 修改 3 檔）

### 新建

#### 1. `commands/memory-peek.md` — Skill 定義

- 觸發：`/memory-peek`
- 功能：列最近 24h 自動萃取的 atom + pending candidates + trigger 原因 [F7]
- 呼叫 `tools/memory-peek.py`
- 輸出格式範例：
  ```
  [V4.1 最近 24h 萃取]
  ✓ 已寫入 (2 條)
    1. 「以後一律用 pnpm」 → personal/auto/holylight/pnpm-preference.md (trigger: 記住+一律)
    2. 「禁止在 hook 跑 git push」 → personal/auto/holylight/no-git-push-hook.md (trigger: 禁止)
  ⏳ 待確認 (1 條)
    3. 「就用方案 A」 → _pending.candidates (conf: 0.78, 待 review)
  ```

#### 2. `tools/memory-peek.py` — 後端

- 掃 `personal/auto/{user}/` 最近 24h 修改的 .md 檔
- 掃 `personal/auto/{user}/_pending.candidates.md`（如存在）
- 從 atom footer `<!-- src: {sid}-{turn_n} -->` 提取來源
- 從 atom metadata Trigger 欄提取 trigger 原因
- 輸出 JSON 或格式化文字（供 skill 呈現）

#### 3. `commands/memory-undo.md` — Skill 定義

- 觸發：`/memory-undo [id|last|--since=<time>|--all-from-today]` [F20]
- 功能：撤銷自動萃取的 atom
  - 無參數 = 撤最近一條
  - `last` = 同上
  - `--since=24h` / `--since=2026-04-16` = 批撤
  - `--all-from-today` = 當日全撤
- 撤銷動作：
  - 移到 `personal/auto/{user}/_rejected/` 目錄（不刪除，供 reflection 學習）
  - **強制分類 reject reason** [F23]：使用者必須選 (a) 情緒誤抓 (b) 含蓄誤判 (c) 隱私越界 (d) scope 錯 (e) 其他
  - 寫回 `memory/wisdom/reflection_metrics.json` 新欄位 `v41_extraction` [F23]
- 呼叫 `tools/memory-undo.py`

#### 4. `tools/memory-undo.py` — 後端

- 列出 `personal/auto/{user}/` 全部 `author: auto-extracted-v4.1` 的 atom
- 按 Created-at 排序
- 支援 id（前 8 字 slug hash）/ last / --since / --all-from-today 四種選擇
- 執行撤銷：
  - `mkdir -p personal/auto/{user}/_rejected/`
  - `mv {atom}.md _rejected/{atom}.md`
  - append reject reason 到 atom footer：`<!-- rejected: {reason}, {timestamp} -->`
- 寫回 reflection_metrics.json：
  ```json
  "v41_extraction": {
    "total_written": N,
    "total_rejected": M,
    "reject_reasons": {"emotion": 0, "ambiguous": 0, "privacy": 0, "scope": 0, "other": 0},
    "precision_observed": (N-M)/N
  }
  ```
- 輸出確認訊息：「已撤銷 N 條。/memory-peek 查看剩餘。」

### 修改

#### 5. `hooks/workflow-guardian.py` — SessionStart 每日推送 [F18]

- SessionStart handler 新增：
  - 讀 `personal/auto/{user}/` 目錄，計算最近 24h 新建的 atom 數 (N)
  - N > 0 → additionalContext 注入：`[V4.1] 昨日新增 {N} 條自動萃取 atom，/memory-peek 檢視`
  - N = 0 → 靜默
  - 計算方式：比對 Created-at metadata 或檔案 mtime

#### 6. `tools/init-roles.py` — 隱私體檢 [F21]

- 在 init-roles 流程末尾新增一步「隱私體檢」：
  - 掃描常見雲端同步路徑：Dropbox、iCloud、OneDrive、Google Drive
  - 檢查 `personal/` 目錄是否落在這些路徑下
  - 若是 → 警告使用者「personal/ 可能被雲端同步，建議排除」
  - 檢查 `.gitignore` 是否已含 `personal/`（已有則 OK）
  - 檢查 SVN `svn:ignore`（若是 SVN repo）
- 純警告，不自動修改任何設定

#### 7. `memory/wisdom/reflection_metrics.json` — 擴充 schema

- 新增 `v41_extraction` 區塊（見上方 memory-undo.py 的寫入格式）
- 初始值全 0

### 絕不碰

- `user-extract-worker.py`（P2 產出，已穩定）
- `wg_user_extract.py`（P1 產出）
- `lib/ollama_extract_core.py`（P2 前置產出）
- `prompts/`（已穩定）
- `extract-worker.py`（已 refactor）
- `server.js`（零修改 [F2]）

## 驗收

```bash
# Skill 可呼叫
/memory-peek              # 列最近 24h（可能為空，正常）
/memory-undo last         # 撤最近一條（需先有 atom）

# 手測流程
# 1. 開 userExtraction.enabled=true
# 2. 對話幾輪含決策語
# 3. /memory-peek 看到萃取結果
# 4. /memory-undo last → 選 reason → 確認搬到 _rejected/
# 5. 檢查 reflection_metrics.json v41_extraction 欄位

# 隱私體檢
/init-roles              # 最後一步應顯示隱私掃描結果

# SessionStart 推送
# 重開 session → 若有 atom 應看到 systemMessage

# 回歸
pytest tests/test_v41_disabled.py -v         # flag=false 不退化
pytest tests/regression/test_v4_atoms_unchanged.py -v  # V4 atoms 不變
```

**驗收紅線**：
- `/memory-peek` 正確列出 + trigger 原因
- `/memory-undo` 摩擦力 ≤ 2 次 enter（含 reason 選擇）
- reject 寫回 reflection_metrics
- 隱私體檢至少標記 1 個雲端路徑（若存在）→ warn
- flag=false zero overhead 不退化
- V4 atoms 不變

## GIT

完成即 commit + `git tag v4.1.0-rc1`。

## 後續（P4 — 最終 session）

P3 完成後，最後一個 session：

**Session F — V4.1 P4：歷史回填 + 試用 + 驗收**
- `tools/v41_backfill.py`（conf ≥ 0.92 歷史回填 [F8]）
- holylight 試用 5-7 天
- 誘餌題明知協議 [F19]
- 100 條抽樣 P/R + token audit
- `tools/v41_audit.py`（抽樣工具）
- git tag `v4.1.0`

Session F 的 handoff 將在 P3 完成後產出。
