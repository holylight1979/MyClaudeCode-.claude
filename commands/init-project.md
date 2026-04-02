# /init-project — 專案知識庫初始化

> 為當前專案建立 `_AIDocs/` 知識庫骨架與記憶工作流。
> 此 Skill 應在每次 session 開始時，偵測到專案**無 `_AIDocs/` 目錄**且**有足夠規模（50+ 檔案）**時自動執行。

---

## 使用方式

```
/init-project
```

無參數。自動偵測當前工作目錄，若已有 `_AIDocs/` 則改為完整性檢查。

### 錯誤處理

- **已有 `_AIDocs/`** → 跳過初始化，改為檢查完整性並補齊缺失
- **專案規模 < 50 檔案** → 告知使用者規模較小，建議有需要時再手動執行
- **無寫入權限** → 提示權限不足

---

## 執行流程

### Step 1: 環境偵測

1. 確認當前工作目錄下是否已存在 `_AIDocs/` 目錄
   - 若已存在 → 跳過初始化，直接讀取 `_AIDocs/_INDEX.md` 確認知識庫完整性
   - 若不存在 → 繼續 Step 2
2. 統計專案原始碼檔案數量（排除 `node_modules`、`bin`、`obj`、`.git`、`packages` 等）
   - 若 < 50 檔案 → 告知使用者「專案規模較小，建議有需要時再手動執行 `/init-project`」，結束
   - 若 >= 50 檔案 → 繼續 Step 2

### Step 2: 專案掃描

使用 Explore agent 並行收集以下資訊：

1. **專案結構**：資料夾樹狀圖、各目錄 .cs/.ts/.py 等原始碼檔案數量
2. **進入點**：找 `Program.cs` / `Main` / `index.ts` 等入口
3. **框架識別**：從 `.csproj` / `package.json` / `requirements.txt` / `Cargo.toml` 判斷技術棧
4. **設定檔**：找 `appsettings.json` / `set.xml` / `.env` / `config.*` 等
5. **資料庫**：找 ORM / 資料存取模式（EF / Dapper / MysqlxCache / Prisma / SQLAlchemy 等）

### Step 3: 建立骨架

建立以下檔案：

```
_AIDocs/
  _INDEX.md          — 文件索引（含追蹤用途速查）
  _CHANGELOG.md      — 變更記錄（初始條目：「知識庫建立」）
  Project_File_Tree.md — 專案結構摘要
```

`_INDEX.md` 模板：

```markdown
# [專案名稱] — AI 分析文件索引

> 本資料夾包含由 AI 輔助產出的專案分析文件。
> 最近更新：[日期]

---

## 文件清單

| # | 文件名稱 | 說明 |
|---|---------|------|
| 1 | Project_File_Tree.md | 專案資料夾結構摘要 |

---

## 架構一句話摘要

[根據掃描結果填入]
```

### Step 4: 建立專案 CLAUDE.md（若不存在）

在專案根目錄建立 `CLAUDE.md`，內容：

```markdown
# [專案名稱] — 專案導讀 (Claude Code)

> [一句話描述]

## 風險分級（專案特定）

> 通用分級框架見全域 `~/.claude/CLAUDE.md`。

| 風險等級 | 本專案操作類型 | 驗證要求 |
|---------|--------------|---------|
| **高** | [根據專案填入] | 必須先讀取 _AIDocs 相關文件 + 原始碼 |
| **極高** | [根據專案填入] | 必須向使用者確認後才執行 |

## 技術約束

- [根據掃描結果填入]
```

### Step 5: 建立決策記憶檔（若不存在）

檢查 `memory/Extra_Efficiently_TokenSafe.md` 是否存在：
- 若不存在 → 建立空白模板：

```markdown
# 決策記憶 — 效率與 Token 節省

> 三層分類系統定義見全域 `~/.claude/CLAUDE.md`。

---

## 工程決策

（尚無記錄）

---

## 演化日誌

| 日期 | 記憶 | 變更 |
|------|------|------|
| [今日] | 知識庫建立 | 初始化 _AIDocs 與記憶工作流 |
```

### Step 6: 建立 .claude/ 自治層（若不存在）

建立專案自治目錄，讓專案記憶隨 repo 一起版控。

**目錄結構**：
```
.claude/
├── memory/
│   ├── MEMORY.md        ← 空索引模板
│   ├── episodic/
│   ├── failures/
│   └── _staging/
├── hooks/
│   └── project_hooks.py ← delegate 模板
└── .gitignore
```

**執行步驟**：

1. 若 `.claude/memory/MEMORY.md` 已存在 → 跳過（不覆蓋）

2. 建立上述所有目錄（`mkdir -p` 等價）

3. 建立 `.claude/memory/MEMORY.md`（若不存在）：
```markdown
# [專案名稱] — Atom Index

> 專案層原子記憶索引。Session 啟動時自動載入。

| Atom | Path | Trigger |
|------|------|---------|

> Project-Aliases:
```

4. 建立 `.claude/hooks/project_hooks.py`（若不存在）：
```python
"""project_hooks.py — 專案層 delegate hooks

由核心引擎 (workflow-guardian.py) 在 SessionStart 時載入。
透過 subprocess 呼叫，stdin/stdout JSON 通訊。
自訂邏輯寫在 on_session_start / inject / extract 內。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent  # .claude/hooks/ → project root
MEMORY_DIR = PROJECT_ROOT / ".claude" / "memory"


def inject(context: dict) -> list:
    """回傳要注入的 atom 檔案絕對路徑列表。"""
    paths = []
    for md in MEMORY_DIR.glob("*.md"):
        if md.name != "MEMORY.md":
            paths.append(str(md))
    return paths


def extract(knowledge: list, context: dict) -> None:
    """接收萃取出的知識項目，決定如何寫入專案記憶。
    knowledge 格式: [{"type": "fact|failure|decision", "content": "...", "confidence": "[臨]"}]
    """
    # 預設：由核心引擎處理寫入，此處可加自訂邏輯
    pass


def on_session_start(context: dict) -> dict:
    """Session 初始化時呼叫，可回傳補充 lines。
    回傳格式: {"lines": ["額外注入的文字行"]}
    """
    return {}


# ── CLI 入口（subprocess 呼叫）──
if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    ctx = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}

    if action == "inject":
        print(json.dumps(inject(ctx)))
    elif action == "extract":
        items = ctx.get("knowledge", [])
        extract(items, ctx)
        print(json.dumps({"status": "ok"}))
    elif action == "session_start":
        print(json.dumps(on_session_start(ctx)))
    else:
        print(json.dumps({"error": f"unknown action: {action}"}))
        sys.exit(1)
```

5. 建立 `.claude/.gitignore`（若不存在）：
```gitignore
# Ephemeral — 不版控
*.access.json
episodic/
_staging/
vector-db/

# 版控（明確保留）
!memory/MEMORY.md
!memory/*.md
!memory/failures/*.md
!hooks/
```

6. 檢查 `_AIAtoms/` 是否存在：
   - 若有 → 向使用者提示：「偵測到舊式 _AIAtoms/ 目錄，建議執行 `python ~/.claude/tools/migrate-v221.py` 遷移至新結構」
   - 若無 → 無需處理

### Step 7: 回報結果

向使用者彙報：
- 建立了哪些檔案
- 專案掃描摘要（技術棧、規模、關鍵發現）
- 建議後續可深入分析的方向

---

## 注意事項

- 不覆蓋已存在的檔案
- 不修改原始碼
- 所有產出為 Markdown 分析文件
- 若專案已有 `_AIDocs/`，改為檢查完整性（是否有 _INDEX.md、_CHANGELOG.md）並補齊缺失
