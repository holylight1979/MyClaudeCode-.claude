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
