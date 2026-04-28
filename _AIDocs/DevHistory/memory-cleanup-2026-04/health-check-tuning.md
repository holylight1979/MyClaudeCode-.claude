# Health Check Tuning — 指標型 atom 規則沉澱後的健檢調校

> 2026-04-28 · Stage F 重審後續

## 起因

Dashboard「健康檢查」頁顯示：
- 1 warning: `format @ memory/decisions-architecture.md`（缺少建議區段 `## 知識`）
- 3 缺反向參照：
  1. decisions-architecture → feedback-pointer-atom
  2. feedback-codex-companion-model → feedback-pointer-atom
  3. feedback-pointer-atom → feedback-memory-path

## 判定（a vs b）

### (a) 健檢規則牴觸新原則 — 工具改動

**memory-audit.py REQUIRED_SECTIONS 過嚴**

`feedback-pointer-atom` 規則沉澱後，atom 允許「指標型」變體：
`## 印象 + ## 行動` 取代傳統 `## 知識 + ## 行動`。

但 `tools/memory-audit.py:57` 仍寫死 `REQUIRED_SECTIONS = {"知識", "行動"}`，
凡使用 `## 印象` 的 atom 都會被誤報。本次只有 `decisions-architecture.md`
（top-level）被掃描到 — `feedback-pointer-atom.md` 在 `feedback/` 子目錄
而 audit 用 `glob("*.md")` 非 recursive，碰巧逃過。本質仍是同個規則 drift。

**修正**：拆成「行動必有 + 知識/印象 二選一」兩條規則。

```python
# 行動 always required; 知識 or 印象（指標型 atom 變體）二選一即可
REQUIRED_SECTIONS = {"行動"}
KNOWLEDGE_SECTIONS = {"知識", "印象"}
...
if not (atom.sections_found & KNOWLEDGE_SECTIONS):
    issues.append(Issue(rel, "warning", "format", "缺少建議區段: ## 知識 或 ## 印象"))
```

**atom-health-check.py CENTRAL_HUBS 缺 feedback-pointer-atom**

`feedback-pointer-atom` 是 meta-rule hub（被 `decisions-architecture` /
`feedback-codex-companion-model` / `feedback-memory-path` 等多個 atoms
引用作為 atom 設計依據），結構等同既有的 `decisions` / `decisions-architecture` /
`spec` — 中央 hub 不該被要求逐一 back-reference 細節 atom。

**修正**：加入 CENTRAL_HUBS 白名單。

```python
CENTRAL_HUBS = {"decisions", "decisions-architecture", "spec", "feedback-pointer-atom"}
```

### (b) atom 漏寫 — 無

3 條反向參照在磁碟上實際**已完整存在**（grep 全域 atoms 反向引用驗證）：
- `feedback-pointer-atom.md:9` Related 已含 decisions-architecture / feedback-codex-companion-model / feedback-memory-path
- `feedback-memory-path.md:9` Related 已含 feedback-pointer-atom

Dashboard 顯示為過時快照（先前 fix-refs 已補齊）。CENTRAL_HUBS 白名單
是防將來再有 atoms 引用 pointer-atom 時誤報，非當下 atom 漏寫修補。

## 驗證結果

修改前：1 warning + (dashboard 過時) 3 缺反向參照
修改後：
- `python tools/memory-audit.py --global-only` → `Errors: 0 | Warnings: 0`
- `python tools/atom-health-check.py --validate-refs` → `✅ All Related references valid. ✅ All reverse references OK.`

## 異動清單

| 檔案 | 改動 |
|------|------|
| tools/memory-audit.py | REQUIRED_SECTIONS 拆「行動必有 + 知識/印象 二選一」 |
| tools/atom-health-check.py | CENTRAL_HUBS 加入 feedback-pointer-atom |
| _AIDocs/DocIndex-System.md | 兩工具描述同步更新 |

不動：atom 「## 印象 / ## 行動」段內容、其他既有 warning 機制（confidence gate / format gate）。

---

## 追加：memory-audit recursive scan（2026-04-28 同日）

### 起因

本次調校時發現 `feedback/feedback-pointer-atom.md` 因在子目錄而 audit
`glob("*.md")` 漏掃 — 是它沒被「缺 ## 知識」誤報的真正原因。原本作為 (b)
follow-up 列入 handoff 候選，使用者要求直接執行（縮影偵測仍另開 session）。

### 改動

**memory-audit.py:**

1. 新增 `SKIP_DIRS` 常數 + `iter_atom_files()` helper：
   - 允許 atom 子目錄：`feedback/`（atoms 大本營）
   - 跳過：`_*`（_meta / _reference / _staging / _vectordb / _distant）/
     `personal/`（V4 user role 宣告，非 atom）/ `wisdom/`（Wisdom Engine
     設計文件 DESIGN.md，非 atom）/ `episodic/`（auto-generated 摘要，章節
     格式為 `## 摘要` 與 atom 不同）/ `templates/`
2. 4 處 `glob("*.md")` 改為 `iter_atom_files(mem_dir)` — 集中跳過邏輯：
   - `delete_atom` Related 清理
   - `enforce_decay` 衰減掃描
   - 主 `audit_layer` atom 解析
   - `compact_logs` 演化日誌壓縮
   - `search_distant` 不變（已是逐 year-month-dir 掃，非 top-level）

### 驗證對照

| | rglob 前 | rglob 後 |
|---|---|---|
| Active atoms 計數 | 13（漏掃 feedback/） | 29（含 feedback/ 16 atoms） |
| Errors | 0 | 0 |
| Warnings | 1（指標型 atom 規則調校前） / 0（調校後但漏掃） | 0 |

擴大掃描下未觸發任何新 warning — 證明 feedback/ 既有 atoms 格式合規，本次
recursive 變更無 regression 風險。

### 已知 pre-existing 失敗（非本任務引入）

`tests/test_codex_companion_drain_e2e.py::test_drain_delivery_inject_emits_with_confidence_label`
在 main HEAD `5dfa99b`（本任務改動前）即 FAIL，與 memory-audit / atom-health-check
無代碼路徑交集。git stash 驗證確認非本次引入。標記為已知 regression，不在本任務修補範圍。

### 仍另開 session（縮影偵測）

`atom-health-check.py` 加「縮影偵測」（atom 印象段 vs `_AIDocs/` md 字串相似度
≥ 0.7 標 warning）— 預告於 `feedback-pointer-atom.md:30`，需設計決策（比對範圍 /
演算法 / 報告層級 / 例外清單 / threshold 驗證），列入 handoff prompt。
