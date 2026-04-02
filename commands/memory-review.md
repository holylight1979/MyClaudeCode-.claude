# /memory-review — 自我迭代檢閱

> 手動觸發記憶系統自我迭代：衰減掃描、晉升候選、震盪偵測、覆轍偵測、episodic 回顧。
> 有專案自治層時，優先檢閱專案層，再檢閱全域層。

---

## 使用方式

```
/memory-review
```

無參數。執行完整檢閱流程。

---

## Step 0: 偵測專案記憶目錄

用 Bash tool 執行：

```bash
python -c "
import sys, os
sys.path.insert(0, os.path.expanduser('~/.claude/hooks'))
try:
    from wg_paths import get_project_memory_dir, get_project_claude_dir
    d = get_project_memory_dir(os.getcwd())
    print(d or '')
except Exception:
    print('')
"
```

- 若輸出非空 → 記為 `PROJECT_MEM_DIR`（後續步驟納入此目錄）
- 若輸出為空 → 純全域模式

---

## Step 1: 收集基礎資訊

並行讀取以下檔案：

1. `~/.claude/workflow/config.json` — 取得 self_iteration 設定（decay_half_life_days、promote_min_confirmations、archive_score_threshold）
2. `~/.claude/workflow/last_review_marker.json` — 上次檢閱時間
3. `~/.claude/workflow/oscillation_state.json` — 現有震盪警告（可能不存在）

## Step 2: 衰減分數掃描

掃描目標：
1. **若有 PROJECT_MEM_DIR**：先掃 `$PROJECT_MEM_DIR/` + `$PROJECT_MEM_DIR/failures/`
2. 再掃 `~/.claude/memory/` + `~/.claude/memory/failures/`（全域層）

兩層均跳過 MEMORY.md、SPEC_*、_* 開頭的檔案。

對每個 atom 計算：
- 從 frontmatter 取 `Last-used` 和 `Confirmations`
- **Recency** = `exp(-ln2 × days_since / half_life)`（half_life 預設 30 天）
- **Usage** = `min(1.0, log10(confirmations + 1) / 2)`
- **Score** = `0.5 × recency + 0.5 × usage`

分類：
- Score < 0.3 → **封存候選**（建議淘汰或封存）
- Score 0.3~0.5 → **低活躍**（觀察中）
- Score > 0.5 → **健康**

## Step 3: 晉升候選

掃描同一批 atom，找出：
- Confirmations ≥ 20 且包含 `[臨]` 條目 → 建議 [臨]→[觀]
- Confirmations ≥ 40 且包含 `[觀]` 條目 → 建議 [觀]→[固]

列出候選，**不自動執行**，等使用者逐一確認。

## Step 4: 震盪偵測

掃描最近 3 個 episodic atom（**PROJECT_MEM_DIR/episodic/** 優先，再 `~/.claude/memory/episodic/`），找出：
- 同一 atom 在 2+ 個 session 中被修改 → 震盪警告

## Step 5: 覆轍偵測

掃描同批 episodic，找出：
- 含有「覆轍信號:」的行
- 同一信號在 2+ session 出現 → 覆轍警告

## Step 6: Episodic 回顧

列出最近 5 個 episodic atom 的摘要（**PROJECT_MEM_DIR/episodic/** 優先，不足再補全域）：
- 檔名（含日期）
- 工作區域
- 修改 atoms
- 關鍵知識點

用途：幫助使用者快速回顧近期 session 產出，判斷是否有知識需要收攏。

## Step 7: 綜合報告

整合所有結果，格式：

```
## 記憶自我迭代報告

**系統階段**：{learning/stable/mature}（N sessions）
**上次檢閱**：{日期}

### 衰減掃描
| Atom | Score | Last-used | Confirmations | 狀態 |
|------|-------|-----------|---------------|------|
{按 score 升序排列}

### 封存候選（Score < 0.3）
- {atom} — score={score}, 建議：封存 / 刪除 / 更新

### 晉升候選
- {atom} 中 N 個 [臨] 條目 → 建議晉升 [觀]（confirmations={N}）

### 震盪警告
- {atom} 在 {N} 個 session 中被修改，建議暫停

### 覆轍警告
- {signal} 跨 {N} session 重複出現

### 近期 Session 摘要
{最近 5 個 episodic 摘要}
```

## Step 8: 互動式處理

報告產出後，詢問使用者：

1. 封存候選 → 要封存/刪除嗎？
2. 晉升候選 → 要執行晉升嗎？（逐一確認）
3. 震盪 atom → 需要深入分析嗎？
4. 覆轍模式 → 要寫入 failures/ atom 防止再犯嗎？

## Step 9: 更新檢閱標記

所有處理完成後，用 Edit tool 更新 `~/.claude/workflow/last_review_marker.json`：

```json
{
  "session_count": {當前 episodic 總數},
  "reviewed_at": "{ISO 時間}"
}
```

確保下次檢閱計數從此刻重新起算。
