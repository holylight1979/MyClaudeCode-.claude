# DocDrift Detection — Implementation Plan

## Context

PR #1 (@wellstseng) 提出 _AIDocs Drift Detection 概念：src 改了自動提醒更新對應文件。
概念有價值，但實作不符現有模組化架構，且假設了不存在的 `_AIDocs/modules/` 目錄。
重新實作為 `wg_docdrift.py` 獨立模組，嵌入現有 PostToolUse handler。

## 變更清單（4 檔案）

| 檔案 | 動作 | 變更量 |
|------|------|--------|
| `hooks/wg_docdrift.py` | **新建** | ~110 行 |
| `hooks/workflow-guardian.py` | 編輯 | +26 行（4 處插入） |
| `hooks/wg_core.py` | 編輯 | +7 行（DEFAULTS） |
| `workflow/config.json` | 編輯 | +15 行（docdrift section） |

## 設計決策

| 面向 | 決定 | 理由 |
|------|------|------|
| 映射策略 | Hybrid：config 顯式映射優先 + keyword fallback | 顯式精準、keyword 補漏；`_AIDocs` 只有 ~10 條目，成本極低 |
| Read 解除 | 不支援（只有 Edit/Write 解除） | settings.json matcher 是 `Edit\|Write`，擴充 Read 會讓每次讀檔都觸發 hook |
| 阻擋方式 | Advisory 警告 + Stop 提示（不硬擋） | 符合既有 advisory pattern，非侵入 |
| 觸發範圍 | 排除 `_aidocs/`, `memory/`, `.git/`, `workflow/` 等基礎設施 | 只偵測「專案原始碼」的變更 |

## 1. `hooks/wg_docdrift.py`（新建 ~110 行）

### Public API

```python
def check_source_drift(file_path: str, state: dict, config: dict) -> None
```
Edit/Write 原始碼時呼叫。比對 `state["aidocs"]["keywords"]` 找對應文件，加入 `state["docdrift_pending"]`。

```python
def resolve_doc_update(file_path: str, state: dict, config: dict) -> None
```
Edit/Write _AIDocs 檔案時呼叫。從 `state["docdrift_pending"]` 移除已解決項目。

```python
def build_drift_advisory(state: dict, config: dict) -> Optional[str]
```
產生 advisory 字串。空則回 None。

### 核心邏輯 — `_match_source_to_docs()`

**第 1 層（config 顯式映射）**：
```python
config["docdrift"]["path_mappings"] = {
    "hooks/wg_*.py": ["Architecture.md"],
    "commands/*.md": ["DocIndex-System.md"],
    ...
}
```
用 `fnmatch` 比對 relative path → 命中就回傳，不走 fallback。

**第 2 層（keyword fallback）**：
分解 file path 為 tokens（目錄名、檔名去副檔名、底線/連字號拆分）。
從 `state["aidocs"]["keywords"]`（SessionStart 建立）取每個 doc 的 keyword list。
匹配數 >= `keyword_match_threshold`（預設 2）→ 視為關聯。

### State Schema

```python
state["docdrift_pending"] = {
    "hooks/wg_hot_cache.py→Architecture.md": {
        "source": "hooks/wg_hot_cache.py",
        "doc": "Architecture.md",
        "added_at": "2026-04-08T10:30:00+08:00",
    }
}
```
Dict keyed by `{source}→{doc}` 自動去重。

## 2. `hooks/workflow-guardian.py`（4 處插入）

### 2a. Import（line ~108，hot cache import 之後）
```python
try:
    from wg_docdrift import check_source_drift, resolve_doc_update, build_drift_advisory
    DOCDRIFT_AVAILABLE = True
except ImportError:
    DOCDRIFT_AVAILABLE = False
```

### 2b. PostToolUse Edit/Write 分支（line ~986，write_state 之後）
```python
if DOCDRIFT_AVAILABLE and config.get("docdrift", {}).get("enabled", True):
    try:
        norm_dd = file_path.replace("\\", "/").lower()
        if "/_aidocs/" in norm_dd:
            resolve_doc_update(file_path, state, config)
        else:
            check_source_drift(file_path, state, config)
    except Exception as e:
        print(f"[v3.3] DocDrift error: {e}", file=sys.stderr)
```

### 2c. Advisory 生成（line ~1062，advisory loop 之前）
```python
if DOCDRIFT_AVAILABLE and config.get("docdrift", {}).get("enabled", True):
    try:
        drift_msg = build_drift_advisory(state, config)
        if drift_msg:
            state["_docdrift_advisory"] = drift_msg
    except Exception:
        pass
```

### 2d. Advisory loop（line ~1068）新增一條
```python
("_docdrift_advisory", "[Guardian:DocDrift]"),
```

### 2e. Stop hook（line ~1197，reason 字串之後）
```python
if DOCDRIFT_AVAILABLE:
    try:
        dp = state.get("docdrift_pending", {})
        if dp:
            docs = sorted(set(v["doc"] for v in dp.values()))
            reason += f"\n[DocDrift] {len(dp)} source change(s) → consider updating: {', '.join(docs[:5])}"
    except Exception:
        pass
```

## 3. `hooks/wg_core.py`（DEFAULTS，line ~57）

在 `"aidocs"` 區塊之後加：
```python
"docdrift": {
    "enabled": True,
    "path_mappings": {},
    "exclude_patterns": [
        "_aidocs/", "memory/", "_staging/", ".git/",
        "node_modules/", "__pycache__/", ".claude/workflow/",
    ],
    "keyword_match_threshold": 2,
    "max_pending_display": 5,
},
```

## 4. `workflow/config.json`（新增 docdrift section）

```json
"docdrift": {
    "enabled": true,
    "path_mappings": {
        "hooks/wg_*.py": ["Architecture.md"],
        "hooks/workflow-guardian.py": ["Architecture.md"],
        "hooks/extract-worker.py": ["Architecture.md"],
        "hooks/quick-extract.py": ["Architecture.md"],
        "hooks/wisdom_engine.py": ["Architecture.md"],
        "commands/*.md": ["DocIndex-System.md"],
        "rules/*.md": ["DocIndex-System.md"],
        "tools/*.py": ["DocIndex-System.md"]
    },
    "exclude_patterns": [
        "_aidocs/", "memory/", "_staging/", ".git/",
        "node_modules/", "__pycache__/", ".claude/workflow/",
        "backups/", "debug/", "Logs/"
    ],
    "keyword_match_threshold": 2,
    "max_pending_display": 5
}
```

## 5. 不改的部分

- **settings.json** — PostToolUse matcher 維持 `Edit|Write`，不擴充 Read
- **_AIDocs/Architecture.md** — 實作完成後再更新（sync 階段）

## 驗證方式

1. 編輯 `hooks/wg_hot_cache.py` → 預期出現 `[Guardian:DocDrift]` advisory
2. 編輯 `_AIDocs/Architecture.md` → 預期 drift 解除，advisory 消失
3. 編輯 `memory/` 下的 atom → 預期不觸發 drift（excluded）
4. 觸發 Stop hook → 預期 pending drift 顯示在 gate message
5. 全程無 ImportError（graceful fallback 測試：暫時 rename wg_docdrift.py → 確認不影響正常運作）
