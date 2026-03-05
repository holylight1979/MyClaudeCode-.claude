# Claude Code 全域設定 — 目錄結構

> 路徑：`C:\Users\holylight\.claude\`

```
~/.claude/
├── CLAUDE.md                    ← 全域工作流引擎指令（always-loaded）
├── README.md                    ← 對外說明（設計哲學、流程圖、Token 對比）
├── Install-forAI.md             ← AI 可讀安裝指南
├── settings.json                ← Hooks + 權限設定（6 hook events）
├── .mcp.json                    ← MCP server 設定
├── .gitignore                   ← Git 排除規則
│
├── hooks/                       ← Hook 腳本
│   └── workflow-guardian.py     ← 統一 Hook 入口（~1878 行，處理 6 events）
│
├── commands/                    ← 自訂 Skills（/slash commands）
│   └── init-project.md          ← /init-project 知識庫初始化
│
├── memory/                      ← 全域記憶層
│   ├── MEMORY.md                ← Atom 索引（≤30 行，always-loaded）
│   ├── preferences.md           ← [固] 使用者偏好
│   ├── decisions.md             ← [固] 全域決策
│   ├── excel-tools.md           ← [固] Excel 工具知識
│   ├── SPEC_Atomic_Memory_System.md ← 原子記憶系統規格
│   ├── episodic/                ← 自動生成 session 摘要（TTL 24d，不進 git）
│   ├── _distant/                ← 遙遠記憶區（已淘汰 atoms，不進 git）
│   └── _vectordb/               ← LanceDB 向量索引（不進 git）
│
├── tools/
│   ├── rag-engine.py            ← RAG CLI 入口
│   ├── memory-audit.py          ← 健檢工具
│   ├── memory-write-gate.py     ← 寫入品質閘門
│   ├── memory-conflict-detector.py ← 衝突偵測
│   ├── eval-ranked-search.py    ← Ranked search 評估
│   ├── read-excel.py            ← Excel 讀取
│   ├── test-memory-v21.py       ← 記憶系統測試
│   ├── memory-vector-service/   ← HTTP Vector 搜尋服務
│   │   ├── service.py           ← HTTP daemon @ :3849
│   │   ├── indexer.py           ← 段落級索引器 (LanceDB)
│   │   ├── searcher.py          ← 語意搜尋 + ranked search
│   │   ├── reranker.py          ← LLM re-ranking
│   │   ├── config.py            ← 設定管理
│   │   └── requirements.txt
│   └── workflow-guardian-mcp/   ← Dashboard MCP server
│       └── server.js            ← Node.js MCP @ :3848
│
├── workflow/
│   ├── config.json              ← 統一設定檔（vector_search, write_gate, response_capture, cross_session）
│   └── state-{session-id}.json  ← Session 狀態追蹤（ephemeral，不進 git）
│
├── projects/                    ← 各專案的 auto-memory
│   └── (各專案 auto-memory 目錄)
│
├── _AIDocs/                     ← 知識庫（本目錄）
│   ├── _INDEX.md                ← 文件索引
│   ├── _CHANGELOG.md            ← 變更記錄
│   ├── Architecture.md          ← 核心架構分析
│   ├── Project_File_Tree.md     ← 目錄結構（本檔案）
│   └── AtomicMemory-v2.1-Plan.md ← v2.1 研究計畫（歷史文件）
│
└── [系統目錄 — git 排除]
    ├── cache/                   ├── backups/
    ├── debug/                   ├── plans/
    ├── file-history/            ├── ide/
    ├── downloads/               ├── plugins/
    ├── shell-snapshots/         ├── session-env/
    ├── telemetry/               └── todos/
```

## 關鍵數據

- **Git 追蹤檔案**: ~50 個（CLAUDE.md + settings + hooks + commands + memory atoms + tools + workflow）
- **排除**: credentials、cache、session transcripts（.jsonl）、episodic/、_vectordb/、系統目錄
- **Vector DB**: LanceDB（此電腦支援 AVX2）
