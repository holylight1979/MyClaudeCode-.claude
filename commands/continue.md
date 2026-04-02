# /continue — 續接暫存任務

> 讀取 staging 區的續接 prompt 並立即執行。輕量版續接，適合已備好下一步的場景。
> 全域 Skill，適用任何專案。支援多任務並存選擇。

---

## 使用方式

```
/continue
```

無需輸入參數。多個任務時自動列出選單，選數字即可。

---

## Step 1: 掃描暫存區

從系統 context 的 "Additional working directories" 或 CWD 找到 staging 區，用 **Glob tool** 掃描：

```
{project_root}/.claude/memory/_staging/next-phase*.md
```

> staging 在 `{project_root}/.claude/memory/_staging/`（專案自治層）。
> 未遷移的舊專案：`~/.claude/projects/{slug}/memory/_staging/next-phase*.md`
> 例：CWD `C:\Projects` → 優先掃描 `C:\Projects\.claude\memory\_staging\next-phase*.md`

每個專案有獨立的 staging 區，確保不同專案的續接互不干擾。

### 分流

- **掃描到 1 個檔案** → 自動選定該檔案，繼續 Step 2
- **掃描到多個檔案** → 列出清單讓使用者**選數字**：

```
_staging/ 下有 N 個待續任務：
  1. bundle-pipeline — [續接] AssetBundle 自建打包管線（Phase 1）
  2. token-diet — [續接] Token 瘦身計畫

請選擇（輸入數字）：
```

> 清單中的名稱取自檔名 `next-phase-{name}.md` 的 `{name}` 部分，摘要取自檔案第一行。

- **掃描到 0 個檔案** → 回覆「沒有待續任務。`_staging/` 目錄下無 `next-phase-*.md` 檔案。使用 `/resume` 可從 atoms/git/todo 推斷續接工作。」→ 結束

## Step 2: 讀取並刪除

1. 讀取選定檔案的全部內容，記住內容
2. **立即刪除**該檔案（防止重複執行）

## Step 3: 執行

將讀取到的內容視為**任務 prompt**，立即開始執行。不需要使用者確認，直接動工。

**注意**：如果任務的完成條件中包含「產出下一階段續接 prompt」，在任務完成時寫入新的 `next-phase-{name}.md`（保持原任務名稱）。
