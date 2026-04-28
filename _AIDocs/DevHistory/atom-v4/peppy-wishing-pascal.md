# Plan: Confidence Lifecycle 強化（原子記憶根本契約修補）

> 覆寫前一版 plan。前次任務（handoff + format gate）已完成並 push 至 commit f67c628。

## Context

**觸發**：使用者發現 `feedback-decision-no-tech-menu.md` 初次生成即全 [固]（Confidence + 6 內部條目），違反原子記憶的核心設計原則。

**根因**（三層）：
1. **寫入側無契約**（[server.js:392](tools/workflow-guardian-mcp/server.js#L392)）：`atom_write.confidence` 只 enum 限制三選一，**沒限制新 atom 必須 [臨]**。Claude 傳什麼就寫什麼。
2. **反向激勵**（[server.js:818](tools/workflow-guardian-mcp/server.js#L818) + [memory-write-gate.py:290](tools/memory-write-gate.py#L290)）：
   - **語意契約**：[固] = 高信心 → 品質要求**最嚴**
   - **實作卻是**：[固] 寫入 → **跳過 write-gate 品質檢查**
   - 結果：系統獎勵了它本該阻止的行為（Claude 寫 [固] 省事，違規反而順暢）
3. **既有缺陷：atom/條目不一致**（[wg_iteration.py:265](hooks/wg_iteration.py#L265)）：自動晉升只升 atom **內部知識條目**前綴（`- [臨]` → `- [觀]`），不升 atom header `- Confidence:`。會出現「atom=[臨] 但內部全 [觀]」的分裂。

**使用者選 C**：第一次寫入必須 [臨]，拒絕 [觀]/[固]。理由：一次使用者回饋只是**一次事件**，不是跨 session 驗證過的規則。[觀]/[固] 的資格必須透過後續 trigger 命中累積 confirmations 才能取得。

**晉升路徑已有**（不會讓 [臨] 死路）：
| 步驟 | 門檻 | 機制 | 位置 |
|------|------|------|------|
| Confirmations +1 | 每次 trigger 命中 | **全自動** | [wg_episodic.py:360](hooks/wg_episodic.py#L360) |
| 內部條目 [臨]→[觀] | ≥20 confirmations | **全自動** | [wg_iteration.py:265](hooks/wg_iteration.py#L265) |
| Atom header [臨]→[觀] | 內部全部 ≥ [觀] | **本計畫新增（自動）** | 待加 |
| Atom [觀]→[固] | ≥40 confirmations | **提示式，使用者同意** | [server.js:429](tools/workflow-guardian-mcp/server.js#L429) |

---

## Token 預算精算

| 變更 | 字元 | Token | 類別 |
|------|------|-------|------|
| server.js atom_write 拒絕邏輯 | +12 行 JS | 0 | 不進 context |
| server.js 移除 `confidence !== "[固]"` 條件 | -1 行 | 0 | 不進 context |
| memory-write-gate.py 移除 `[固]` 跳過分支 | -1 行 | 0 | 不進 context |
| wg_iteration.py atom header 同步升級 | +20 行 Python | 0 | 不進 context |
| feedback-decision-no-tech-menu.md [固]→[臨] | byte 不變（中文字元同寬） | 0 | 0 增量 |

**常駐增量：0 token**（純邏輯變更，零新 atom/索引）。
**條件增量：0 token**（沒有新的注入訊息）。

**刀口原則檢核**：
- ✅ 純後端契約修補，無任何 context 注入增量
- ✅ 修既有反向激勵，不加新規則
- ✅ atom 內容字元完全同寬（中文字 3 bytes × 相同數量）

---

## 變更清單（4 處）

### 1. [tools/workflow-guardian-mcp/server.js:812-828](tools/workflow-guardian-mcp/server.js#L812) — 新 atom 必須 [臨]

在 `mode === "create"` 分支的 existsSync 檢查後、write-gate 前插入：

```js
// ── 原子記憶語意契約：新 atom 必須 [臨] ──
// [觀]/[固] 反映跨 session 穩定性，初次寫入無資格主張。
// 路徑：trigger 命中累積 Confirmations → ≥20 升 [觀] → ≥40 提示升 [固]
if (confidence !== "[臨]") {
  return sendToolResult(id,
    `New atom must start at [臨] (confidence=${confidence} rejected).\n` +
    `Reason: [觀]/[固] reflect cross-session stability; first-write cannot assert that.\n` +
    `Knowledge items inside should also use [臨] prefix.\n` +
    `Promotion path: trigger hits auto-accumulate Confirmations → ≥20 auto-promote to [觀] → ≥40 user-approve [固]`,
    true);
}
```

### 2. [tools/workflow-guardian-mcp/server.js:818](tools/workflow-guardian-mcp/server.js#L818) — 移除 [固] 跳 gate

```js
// Before:
if (!skip_gate && confidence !== "[固]") {

// After:
if (!skip_gate) {
```

（配合 Step 1，create 路徑上 confidence 已保證 [臨]，但仍顯式清理反向激勵邏輯以防 replace 路徑或未來變更。）

### 3. [tools/memory-write-gate.py:290](tools/memory-write-gate.py#L290) — 移除 `[固]` 跳過分支

```python
# Before:
if explicit_user or classification == "[固]":
    write_audit_log("add", content, 1.0, classification=classification, reason="explicit_user")
    return {
        "action": "add",
        "quality_score": 1.0,
        "reason": "explicit user trigger or [固] classification",
    }

# After:
if explicit_user:
    write_audit_log("add", content, 1.0, classification=classification, reason="explicit_user")
    return {
        "action": "add",
        "quality_score": 1.0,
        "reason": "explicit user trigger",
    }
```

### 4. [hooks/wg_iteration.py:265-292](hooks/wg_iteration.py#L265) — atom header 自動對齊內部條目

在現有 `if confirmations >= promote_min_conf:` 區塊內，當內部條目升級完成、寫檔前，加入 header Confidence 對齊邏輯：

```python
if changed:
    # V3.5: 同步 atom header Confidence 與內部條目最低前綴對齊
    # 規則：
    #   - 若內部條目全 ≥ [觀]（不含 [臨]）且 header 仍 [臨] → 自動升 header 到 [觀]
    #   - [固] 不自動升 header（須使用者同意 atom_promote）
    #   - 只升不降（保守）
    prefixes = set()
    for L in lines:
        pm = re.match(r"^- \[([臨觀固])\]", L)
        if pm:
            prefixes.add(pm.group(1))

    if prefixes and "臨" not in prefixes and "固" not in prefixes:
        # 所有內部條目都 [觀]（無 [臨] 無 [固]）
        for i, line in enumerate(lines):
            hm = re.match(r"^(- Confidence:\s*)\[臨\]\s*$", line)
            if hm:
                lines[i] = f"{hm.group(1)}[觀]"
                break

    # 原有 atomic write（不變）
    tmp = md_file.with_suffix(".tmp")
    ...
```

### 5. [memory/feedback-decision-no-tech-menu.md](memory/feedback-decision-no-tech-menu.md) — 手動修補

- Line 4 `- Confidence: [固]` → `- Confidence: [臨]`
- Line 12-17 六條 `- [固]` → `- [臨]`
- Confirmations: 0 保持（等 trigger 命中自然累積）

---

## 驗證方案

### A. 單元驗證

1. **atom_write 拒絕 [固] 新 atom**：
   ```
   mcp__workflow-guardian__atom_write(
     title="test-foo", scope="global", confidence="[固]",
     triggers=["test"], knowledge=["- [固] test"], mode="create"
   )
   → 預期：error "New atom must start at [臨]"
   ```

2. **atom_write 拒絕 [觀] 新 atom**：
   同上，confidence="[觀]" → 預期同樣 error。

3. **atom_write 接受 [臨] 新 atom**：
   confidence="[臨]" → 預期成功建立。

4. **現存 atom replace 不受影響**：
   對已存在的 atom mode="replace" confidence="[固]" → 應放行（只擋 create）。

5. **write-gate 對 [固] 內容跑完整流程**：
   ```bash
   python tools/memory-write-gate.py --content "- [固] 測試" --classification "[固]"
   # 預期：跑 dedup 檢查、quality_score 計算，不是 fast-path pass
   ```

### B. 整合驗證

6. **wg_iteration atom header 對齊**：
   手動建一個 Confirmations=25 且內部全 [臨] 的測試 atom → 觸發 wg_iteration → 內部升 [觀] 且 header 升 [觀]。

7. **header 不升 [固]**：
   內部有 [固] 條目但 header 是 [觀]、Confirmations=45 → header 不自動升 [固]。

### C. 手動修補驗證

8. 修補後 `feedback-decision-no-tech-menu.md` 應：
   - header Confidence: [臨]
   - 6 條內部條目前綴 [臨]
   - 行 14 (Why 行) 保留，因 Why/How 不帶前綴
   - `atom-health-check.py --validate-refs` 通過

### D. 回歸掃描

9. 全域掃描：所有 Confirmations=0 + Confidence=[固] 的 orphan atom 清單
   ```bash
   python -c "
   import re, pathlib
   for md in pathlib.Path.home().joinpath('.claude/memory').glob('*.md'):
       t = md.read_text(encoding='utf-8')
       cm = re.search(r'Confidence:\s*\[固\]', t)
       fm = re.search(r'Confirmations:\s*0\b', t)
       if cm and fm:
           print(md.name)
   "
   ```
   若僅 feedback-decision-no-tech-menu.md → 修補完成。若多 → 列清單詢問使用者是否批量修補。

---

## 風險與緩解

| 風險 | 緩解 |
|------|------|
| 現有 atom 已為 [固] 但 Confirmations=0 | 回歸掃描（D9）列清單，逐一問使用者是否降回 [臨] |
| append/replace 場景被新規則誤殺 | 規則僅在 `mode === "create"` 分支內檢查，append/replace 不影響 |
| wg_iteration 邏輯動到關鍵鞏固路徑 | 只升不降、保守模式（有任一 [臨] 或 [固] 即不動 header） |
| [固] 不再跳 gate → 是否影響既有寫入流程 | 由於 Step 1 保證 create 必 [臨]，實務上 create 路徑不會走到 [固]；此改動防禦未來 replace 誤用 |
| wg_iteration 單次 atomic write 改兩處（內部條目 + header） | 已整合在同一個 tmp.write_text(lines)，不會部分寫入 |

---

## 不做的事

- ❌ 不動 `atom_promote` MCP 的手動晉升邏輯（使用者同意 [觀]→[固] 仍是正道）
- ❌ 不自動升 [觀]→[固]（必須保留使用者判斷關卡）
- ❌ 不改既有 atom 的 Confidence（除 feedback-decision-no-tech-menu.md 外，其他現存 [固] 保持，由回歸掃描列清單後由使用者決定）
- ❌ 不動 wg_episodic 的 Confirmations +1 自動累積（既有機制正確）
- ❌ 不加新 atom 說明這個規則（靠系統強制執行，不靠 Claude 自律）

---

## 執行順序（執P：執行 → 驗證 → 上 GIT → 下一階段）

### 執行
1. Edit [server.js:812-828](tools/workflow-guardian-mcp/server.js#L812)：新 atom 拒絕 [臨] 以外
2. Edit [server.js:818](tools/workflow-guardian-mcp/server.js#L818)：移除 `confidence !== "[固]"` 條件
3. Edit [memory-write-gate.py:290](tools/memory-write-gate.py#L290)：移除 `classification == "[固]"` 分支
4. Edit [wg_iteration.py:265-292](hooks/wg_iteration.py#L265)：加入 header 對齊邏輯
5. Edit [feedback-decision-no-tech-menu.md](memory/feedback-decision-no-tech-menu.md)：[固]→[臨]（header + 6 條目）

### 驗證
6. 跑驗證 A1-A5（單元）
7. 跑驗證 B6-B7（整合，用臨時 test atom）
8. 跑驗證 C8（health-check）
9. 跑驗證 D9（orphan 掃描）→ 若有其他 orphan，列清單問使用者（**不自動修**）

### 上 GIT
10. 本次任務 scope 的檔案 stage + commit + push
    - commit：`feat(memory): confidence lifecycle 契約 — 新 atom 強制 [臨] + 移除反向激勵 + atom/條目一致性`

### 下一階段
11. 若 D9 掃出多個 orphan atoms 需處理 → 產出下階段 prompt（列檔案 + 每個的降級方案）
12. 若 D9 清單只有 feedback-decision-no-tech-menu.md → 本任務完整結束，無下階段

---

## Co-Author 聲明

若上 GIT 時被 MCP restart 要求，需使用者 reload VSCode 讓 server.js 變更生效（MCP server 是 node 常駐，不會熱更新）。Hook（Python）無需重啟——下次 SessionStart 自動載入。
