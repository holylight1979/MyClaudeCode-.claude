# ICLD Sprint 模板

- Scope: global
- Confidence: [固]
- Trigger: Sprint template, ICLD template, Sprint 計畫模板, 驗證報告模板, Sprint Prompt
- Last-used: 2026-03-25
- Confirmations: 0
- ReadHits: 0
- Related: workflow-icld

> **ICLD** = Incremental Closed-Loop Development（增量式閉環開發）
> 每個 Sprint 是一個可獨立驗證的功能切片。通過閘門才往下走。

---

## A. Sprint 計畫模板（拆解時使用）

用於產出功能拆解文件（如 `_AIDocs/plan/Feature_XXX.md`）。

```markdown
## Sprint 總覽

| Sprint | 名稱 | 包含 Task | 驗證重點 | 預估 |
|--------|------|-----------|---------|------|
| S1 | {名稱} | {Task list} | {一句話驗證重點} | {天數} |
| S2 | ... | ... | ... | ... |

### Sprint 依賴關係

\```
S1 → S2 → S3    ({線名}，依序)
S4 → S5 → S6    ({線名})
       ↘
        S7       (匯合點)
\```

- {依賴說明}
```

---

## B. Sprint Prompt 模板（每個 Sprint 開始時給 AI）

```markdown
# Sprint S{N}：{Sprint 名稱}

## 上下文
- 專案：{專案名}
- 計畫文件：{_AIDocs/plan/Feature_XXX.md}
- 前置 Sprint 狀態：S{N-1} ✅ 已通過（{一句話驗證摘要}）

## 本 Sprint 目標
{一句話：完成後能做什麼}

## 包含 Task
- Task {X.Y} — {描述}
- Task {X.Z} — {描述}

## 必讀檔案
- `{path1}`（{行數}行，{重點}）
- `{path2}`

## 實作步驟
1. {步驟}
2. {步驟}

## 通過條件
- [ ] {條件 1}
- [ ] {條件 2}
- [ ] {條件 N}

## 注意事項
- {限制/陷阱/特殊規則}
```

---

## C. Sprint 驗證報告模板（每個 Sprint 結束時 AI 產出）

```markdown
## Sprint S{N} 驗證報告

### 通過條件
- [x] {條件 1} — {驗證方式與結果}
- [x] {條件 2} — {驗證方式與結果}
- [ ] {條件 3} — ❌ {失敗原因}

### 修改檔案
| 檔案 | 修改類型 | 說明 |
|------|---------|------|
| {path} | 新建/修改 | {說明} |

### 發現/阻塞
- {需要人工介入的問題}
- {新認知，寫入 _AIDocs}

### 結論
- ✅ 全部通過 → 可進入 S{N+1}
- ❌ 未通過 → 需修復：{列出項目}
```

---

## D. Sprint 單元結構（寫在計畫文件中，每個 Sprint 一段）

```markdown
### Sprint S{N}：{名稱}

**目標**：{一句話}

**包含 Task**：{Task list}

**步驟**
1. {具體步驟}
2. {具體步驟}

**通過條件** ✅
- [ ] {條件 1}
- [ ] {條件 2}
```
