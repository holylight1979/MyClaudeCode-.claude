# 核心規則

## 知識庫
- 開工前查 _AIDocs/_INDEX.md 確認已有文件；禁止憑記憶改碼
- 修改核心結構/新認知/踩坑 → 更新 _AIDocs + _CHANGELOG.md；新增時同步 _INDEX.md
- _AIDocs 只放長期參考知識；規劃/TODO/進行中 → memory/_staging/

## 記憶
- 分類：「記住」→[固]、反覆模式→[觀]、做取捨→[臨]；不寫臨時嘗試/未確認猜測
- 寫入用 atom_write MCP（自動驗證去重索引晉升）；已記錄事實直接引用

## 同步
完成修改後主動提出：_AIDocs→_CHANGELOG | 新知識→atom | .git→commit+push | .svn→commit
全部完成後呼叫 workflow_signal: sync_completed

## 對話
- 「用識流…」→ /consciousness-stream
- 獨立子任務可新開對話；拆分前確保知識已存入
- 段落完成即存；Token 快上限時優先存檔；/resume → /continue
- Context 壓縮/任務告段落 → 提醒開新 session
- 不衝突的執行階段可開多 agents 分頭進行
