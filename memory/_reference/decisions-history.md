# 全域決策 — 版本演進歷史

從 decisions.md 拆出，僅供追溯參考。

## 演化日誌

- 2026-03-05: 初始建立 — V2.4 合併（回應捕獲/鞏固/episodic）+ LanceDB + Dual-Backend
- 2026-03-11: V2.8→V2.10 — Wisdom Engine + 檢索強化(ACT-R/Spreading) + Session 全軌跡追蹤
- 2026-03-13: V2.11 全面升級 — 精簡（砍逐輪萃取/因果圖/自動晉升/迭代8→3）+ 品質（衝突偵測/反思校準）+ 模組化（rules/+Context Budget）
- 2026-03-13: 自檢修復 — 清除因果圖殘留 + Context Budget 動態化 + 索引同步 + atom 去重 + extract-worker 啟用
- 2026-03-17: V2.12 精確修正計畫 — Fix Escalation Protocol（6 Agent 會議制）+ Guardian 自動偵測 + /fix-escalation skill
- 2026-03-18: V2.12 逐輪增量萃取 — Stop hook per-turn extraction（byte_offset + cooldown + PID guard）+ _spawn_extract_worker 共用化 + intent bug 修正
- 2026-03-19: V2.13 Failures 自動化 — 失敗關鍵字偵測 + detached 萃取 + 三維路由
- 2026-03-19: V2.14 Token Diet — 注入 strip + SessionEnd 跳段 + lazy search 預篩
- 2026-03-19: atom 精準拆分（toolchain-ollama + workflow-icld）+ 設定檔精修 + vector timeout 修正
- 2026-03-19: V2.15 定義版本 — 全文件版本號統一 + 內嵌版本標註清理 + CHANGELOG 補完
- 2026-03-22: V2.16 自我迭代自動化 — SessionEnd 衰減分數掃描 + [臨]→[觀] 自動晉升 + 震盪持久化
- 2026-03-22: V2.17 覆轍偵測 — 寄生式 episodic 信號 + 跨 session 掃描 + AIDocs 內容閘門
- 2026-03-23: V2.17 合併升級至公司電腦（從 C:\myHomeClaude 合併）
