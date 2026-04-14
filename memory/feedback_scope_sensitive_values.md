# 範圍敏感值不寫入 atom

- Trigger: GUID, 硬編碼, 環境相依, 範圍敏感, hash, fileID, 端口, 絕對路徑
- Scope: global
- Confidence: [固]
- Last-used: 2026-04-11
- Confirmations: 4
- Related:

## 知識

- [固] 記憶文件（atom md）中不應包含可能因環境/專案/機器不同而改變的硬編碼值
- [固] 這類值看似「事實」但其實是「當下環境的快照」，環境一變就變成錯誤資訊
- [固] 辨識「範圍敏感」值的特徵：由工具自動生成（GUID、hash、fileID）、綁定特定機器/路徑（絕對路徑、端口號）、來自外部系統且可能更新（API endpoint、版本號）

## 行動

- atom 記錄「查什麼、怎麼查」（查找方法/grep pattern）
- 硬編碼值放獨立查閱檔（json/txt），附上來源、時間、驗證方法
