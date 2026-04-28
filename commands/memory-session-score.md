# /memory-session-score — V4.1 P4 Session 評分檢視

> 列出最近的 session 評價：5 維度加權（density / precision / novelty / cost / trust）→ weighted_total。
> 對應 plan `_AIDocs/DevHistory/atom-v4-phases/merry-riding-toucan.md` 子任務 A Deliverable 5。

---

## 使用方式

```
/memory-session-score              # 列全部（最近在下）
/memory-session-score --last       # 只看最近一筆
/memory-session-score --since=24h  # 最近 24 小時
/memory-session-score --since=7d   # 最近 7 天
/memory-session-score --top-n=10   # 按 weighted_total 排序 top-10
```

---

## Step 1: 呼叫 backend

```bash
python ~/.claude/tools/memory-session-score.py $ARGS
```

`$ARGS` 為使用者傳入的額外參數（`--last` / `--since=...` / `--top-n=...`）。

---

## Step 2: 呈現結果

backend 已格式化輸出，例如：

```
[V4.1 Session Scores — last (1 筆)]
[2026-04-16 15:42] session=abc123def456  weighted=0.72
  density=0.72  precision=0.89  novelty=0.71  cost=0.26  trust=1.00
  30 prompts | 8 triggered | 5 written | conf avg 0.89 | 178 tok
```

若回傳 `count=0` → 告知使用者「尚無 session_score 紀錄」。

---

## Step 3: 可選後續

- weighted_total **≥ 0.70** → 高價值 session（未來 V4.2 回填候選）
- weighted_total **≤ 0.40** → 低價值 session（可能表示 token 爆/conf 低/信任崩，檢視 trigger 原因）

提示可執行 `/memory-peek` 檢視萃取 atom 細節，或 `/memory-undo` 撤錯抓。
