# 工作流規則（全域）

- Scope: global
- Confidence: [固]
- Type: procedural
- Trigger: 工作流程, 大型任務, 分階段, SOP, 任務拆分, 上版, GIT, svn, svn-update, 版本控制, 同步, vcs
- Last-used: 2026-03-13
- Created: 2026-03-06
- Confirmations: 22
- Tags: workflow, svn, vcs
- Related: decisions

## 知識

### 大型計畫執行
- 分階段 session 執行
- 每階段：完成 → 驗證 → 上傳 GIT → 提供下一階段 prompt 給使用者
- **「執驗上P」**：階段收尾口令，等同 執行 → 驗證 → 上 GIT → 產 Prompt（四步都做完）
- 有順序依賴的任務（分析→計畫→執行）應在同一對話完成
- 獨立子任務可安全新開對話（MEMORY.md 會自動載入）

### GIT 流程
- 「上 GIT」= git add + commit + push（三步都做完）
- 上版前先做秘密洩漏檢查

### 工作結束同步判斷
→ 詳見 `rules/sync-workflow.md`（同步條件表 + Guardian 閘門）

### SVN 更新優先規則

- [固] 每個 session 中，AI 首次修改程式碼（Edit/Write .cs/.xml/.proto 等原始碼）之前，若該 session 尚未執行過 SVN update，必須先詢問使用者
- [固] 適用條件：專案根目錄存在 `.svn/`（SVN 工作副本）
- [固] 非 SVN 專案（如 Git）跳過此規則
- [固] 使用者拒絕後，本 session 不再重複詢問（每 session 最多問一次）
- [固] 使用者同意 → 執行 `/svn-update` skill

### SVN 工具優先順序

- [固] 優先 TortoiseSVN GUI（`TortoiseProc.exe`，非阻塞啟動）
- [固] 降級 svn.exe CLI（加 `--non-interactive` 防掛住）
- [固] 都沒有 → 引導安裝 TortoiseSVN

### 衝突處理策略

- [固] 混合模式：AI 分析衝突內容、提出合併建議，使用者逐一確認才套用
- [固] 生成檔衝突（Proto/Binding/Design）→ 建議接受遠端版本後重新生成
- [固] 二進位檔衝突 → 建議用 TortoiseSVN 或選擇版本
- [固] Pre-update 必做 `svn status` 檢查本地 .cs 修改

## 行動

- 大型任務主動拆分多個 session 階段，每階段結束提供延續 prompt
- 批量修改先確認 1-2 個模式正確，再批量執行
- Token 節省：有 _AIDocs 文件的不重新掃描原始碼，直接引用文件
- 首次 Edit/Write 原始碼前，檢查 `.svn/` 存在 + session 內未 update → 簡短詢問
- 詢問格式簡潔：「要先 svn update 嗎？」
- 使用者拒絕 → 記錄已詢問，不再重複
- 衝突不自動解決，AI 分析 + 使用者確認

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-06 | 建立為 [固]（使用者明確要求） | session:SVN 工作流規則建立 |
| 2026-03-13 | 合併來源 V2.10 的大型計畫/GIT/同步判斷段落 + 擴展 Trigger | session:選擇性 cherry-pick |
