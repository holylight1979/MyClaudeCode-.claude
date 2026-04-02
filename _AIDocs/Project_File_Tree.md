# Claude Code 全域設定 — 目錄結構

> 路徑：`C:\Users\holylight\.claude\`

```
~/.claude/
├── CLAUDE.md                    ← 全域工作流引擎指令（always-loaded）
├── IDENTITY.md                  ← AI 人格（團隊共用）
├── USER.md                      ← 使用者偏好（per-user，hook 生成，gitignore）
├── USER.template.md             ← 多人使用模板（git 追蹤）
├── BOOTSTRAP.md                 ← 首次設定引導
├── README.md                    ← 對外說明（設計哲學、流程圖、Token 對比）
├── Install-forAI.md             ← AI 可讀安裝指南
├── settings.json                ← Hooks + 權限設定（7 hook events, 含 async Stop）
├── .mcp.json                    ← MCP server 設定（專案層）
├── .gitignore                   ← Git 排除規則
│
├── hooks/                       ← Hook 腳本（模組化）
│   ├── workflow-guardian.py     ← 瘦身 dispatcher（~1447 行，7 events 編排）
│   ├── wg_paths.py             ← 路徑真相來源（slug/root/staging/registry）
│   ├── wg_core.py              ← 共用常數/設定/state IO/output/debug
│   ├── wg_atoms.py             ← 索引解析/trigger 匹配/ACT-R/載入/budget
│   ├── wg_intent.py            ← 意圖分類/session context/MCP/vector
│   ├── wg_extraction.py        ← per-turn 萃取/worker 管理/failure 偵測
│   ├── wg_hot_cache.py         ← Hot Cache 讀寫/注入
│   ├── wg_episodic.py          ← episodic 生成/衝突偵測/品質回饋
│   ├── wg_iteration.py         ← 自我迭代/震盪/衰減/晉升/覆轍偵測
│   ├── extract-worker.py       ← LLM 萃取子程序（SessionEnd/per-turn/failure）
│   ├── quick-extract.py        ← Stop async 快篩（qwen3:1.7b → hot_cache）
│   ├── wg_content_classify.py  ← 內容分類
│   ├── wisdom_engine.py        ← Wisdom Engine（情境分類+反思指標）
│   ├── user-init.sh            ← 多人 USER.md 初始化
│   ├── ensure-mcp.py           ← MCP server 可用性確認
│   └── webfetch-guard.sh       ← WebFetch 安全護欄
│
├── commands/                    ← 自訂 Skills（/slash commands，17 個）
│   ├── init-project.md          ← /init-project 知識庫 + 自治層初始化
│   ├── resume.md                ← /resume 自動續接 Session
│   ├── continue.md              ← /continue 讀取 _staging 續接
│   ├── consciousness-stream.md  ← /consciousness-stream 識流處理
│   ├── svn-update.md            ← /svn-update SVN 更新
│   ├── unity-yaml.md            ← /unity-yaml Unity YAML 操作
│   ├── upgrade.md               ← /upgrade 環境升級
│   ├── fix-escalation.md        ← /fix-escalation 精確修正升級
│   ├── extract.md               ← /extract 手動知識萃取
│   ├── conflict.md              ← /conflict 記憶衝突偵測
│   ├── memory-health.md         ← /memory-health 記憶品質診斷
│   ├── memory-review.md         ← /memory-review 自我迭代檢閱
│   ├── atom-debug.md            ← /atom-debug Debug log 開關
│   ├── harvest.md               ← /harvest 網頁收割
│   ├── read-project.md          ← /read-project 系統性閱讀
│   └── vector.md                ← /vector 向量服務管理
│
├── rules/                       ← 規則模組（Claude Code 自動載入）
│   ├── aidocs.md                ← _AIDocs 知識庫維護
│   ├── memory-system.md         ← 原子記憶分類/寫入/演進/引用
│   ├── session-management.md    ← 對話管理 + 續航 + 自我迭代
│   └── sync-workflow.md         ← 工作結束同步 + Guardian 閘門
│
├── memory/                      ← 全域記憶層（25 atoms）
│   ├── MEMORY.md                ← Atom 索引（≤30 行，always-loaded）
│   ├── project-registry.json    ← 專案根路徑索引（跨專案發現）
│   ├── preferences.md           ← [固] 使用者偏好
│   ├── decisions.md             ← [固] 全域決策
│   ├── decisions-architecture.md ← [固] 架構技術細節
│   ├── excel-tools.md           ← [固] Excel 工具知識
│   ├── workflow-rules.md        ← [固] 版本控制工作流規則
│   ├── workflow-icld.md         ← [固] ICLD 閉環開發流程
│   ├── workflow-svn.md          ← [固] SVN 工作流規則
│   ├── toolchain.md             ← [固] 工具鏈知識
│   ├── toolchain-ollama.md      ← [固] Ollama Dual-Backend
│   ├── doc-index-system.md      ← [固] 全檔索引
│   ├── gdoc-harvester.md        ← [固] Google Docs 收割
│   ├── mail-sorting.md          ← [固] 信箱整理
│   ├── feedback_fix_escalation.md ← [固] 修正升級回饋
│   ├── feedback_research_first.md ← [固] 研究優先回饋
│   ├── feedback_global_install.md ← [固] 全域安裝回饋
│   ├── feedback_no_test_to_svn.md ← [固] 禁止測試碼上 SVN
│   ├── failures/                ← 失敗/陷阱知識
│   │   ├── _INDEX.md
│   │   ├── env-traps.md         ← Win 環境陷阱
│   │   ├── wrong-assumptions.md ← 假設錯誤
│   │   ├── silent-failures.md   ← 靜默失敗
│   │   ├── cognitive-patterns.md ← 認知偏差
│   │   └── misdiagnosis-verify-first.md ← 驗證優先
│   ├── unity/                   ← Unity 專屬知識
│   │   ├── unity-yaml.md
│   │   ├── unity-yaml-detail.md
│   │   ├── unity-prefab-component-guids.md
│   │   ├── unity-prefab-workflow.md
│   │   └── unity-wndform-yaml-template.md
│   ├── templates/               ← 模板
│   │   └── icld-sprint-template.md
│   ├── _reference/              ← 參考文件（手動讀取）
│   │   ├── SPEC_Atomic_Memory_System.md
│   │   ├── SPEC_impl_params.md
│   │   ├── self-iteration.md
│   │   ├── decisions-history.md
│   │   ├── v3-design-spec.md
│   │   └── v3-research-insights.md
│   ├── wisdom/                  ← Wisdom Engine 資料
│   │   ├── DESIGN.md
│   │   ├── causal_graph.json
│   │   └── reflection_metrics.json
│   ├── episodic/                ← 自動生成 session 摘要（TTL 24d，不進 git）
│   ├── _vectordb/               ← LanceDB 向量索引（不進 git）
│   ├── _staging/                ← 暫存區（不進 git）
│   └── _distant/                ← 遙遠記憶（已淘汰 atoms，不進 git）
│
├── tools/
│   ├── ollama_client.py         ← Dual-Backend Ollama singleton
│   ├── rag-engine.py            ← RAG CLI 入口
│   ├── memory-audit.py          ← 健檢工具（支援 --project-dir）
│   ├── memory-write-gate.py     ← 寫入品質閘門
│   ├── memory-conflict-detector.py ← 衝突偵測（支援 --project-dir）
│   ├── atom-health-check.py     ← 參照完整性
│   ├── migrate-v221.py          ← V2.21 遷移工具
│   ├── read-excel.py            ← Excel 讀取
│   ├── unity-yaml-tool.py       ← Unity YAML 解析/生成
│   ├── eval-ranked-search.py    ← Ranked search 評估
│   ├── test-memory-v21.py       ← 記憶系統 E2E 測試
│   ├── cleanup-old-files.py     ← 環境清理
│   ├── memory-vector-service/   ← HTTP Vector 搜尋服務
│   │   ├── service.py           ← HTTP daemon @ :3849
│   │   ├── indexer.py           ← 段落級索引器 (LanceDB)
│   │   ├── searcher.py          ← 語意搜尋 + ranked search + section-level
│   │   ├── reranker.py          ← LLM re-ranking
│   │   ├── config.py            ← 設定管理
│   │   └── requirements.txt
│   ├── gdoc-harvester/          ← Google Docs/Sheets 收割 + dashboard
│   └── workflow-guardian-mcp/   ← Dashboard MCP server
│       └── server.js            ← Node.js MCP @ :3848（含「已知專案」分頁）
│
├── workflow/
│   ├── config.json              ← 統一設定檔（vector_search, write_gate, response_capture, cross_session, hot_cache）
│   ├── hot_cache.json           ← V3 快篩知識快取（ephemeral）
│   ├── vector_ready.flag        ← V3 Vector service 就緒旗標（ephemeral）
│   └── state-{session-id}.json  ← Session 狀態追蹤（ephemeral，不進 git）
│
├── projects/                    ← 各專案的 auto-memory（Claude Code 內建）
│   └── (各專案 auto-memory 目錄)
│
├── _AIDocs/                     ← 知識庫（本目錄）
│   ├── _INDEX.md                ← 文件索引
│   ├── _CHANGELOG.md            ← 變更記錄（最近 ~8 筆）
│   ├── _CHANGELOG_ARCHIVE.md    ← 變更記錄封存
│   ├── Architecture.md          ← 核心架構分析
│   ├── DocIndex-System.md       ← 全檔系統索引
│   ├── Project_File_Tree.md     ← 目錄結構（本檔案）
│   └── plan/                    ← 規劃文件
│
└── [系統目錄 — git 排除]
    ├── cache/                   ├── backups/
    ├── debug/                   ├── plans/
    ├── file-history/            ├── ide/
    ├── downloads/               ├── plugins/
    ├── shell-snapshots/         ├── session-env/
    ├── sessions/                ├── telemetry/
    └── todos/
```

## 專案自治層

每個已註冊專案的 `.claude/` 目錄結構：

```
{project_root}/.claude/
├── memory/
│   ├── MEMORY.md        ← 專案 atom 索引
│   ├── *.md             ← 專案 atoms
│   ├── episodic/        ← 自動生成（gitignore）
│   ├── failures/        ← 踩坑記錄（版控）
│   └── _staging/        ← 暫存（gitignore）
├── hooks/
│   └── project_hooks.py ← 專案 delegate（inject/extract/session_start）
└── .gitignore
```

## 關鍵數據

- **Git 追蹤檔案**: ~60 個（CLAUDE.md + settings + hooks + commands + memory atoms + tools + workflow）
- **排除**: credentials、cache、session transcripts（.jsonl）、episodic/、_vectordb/、系統目錄
- **Vector DB**: LanceDB（此電腦支援 AVX2）
- **全域 Atoms**: 25 個（含 failures/5 + unity/5 + templates/1）
