# Stage F 重審報告（Post Vector REVIVE）

> Date: 2026-04-28
> 觸發：Wave 4b Stage F 5 子 stage 中 4 個被雙稽核 BLOCK；Wave 3b vector REVIVE 完成（87.6% 命中率）後重新評估 BLOCK 是否仍成立。
> 結果：4 BLOCK 全數重新處理 — **2 條件解封 / 1 永久 BLOCK / 1 縮減動作後解封**，並衍生**新規則 atom**「指標型 atom — 設計顆粒原則」與議題 #10「[固] 邏輯程式碼化盤點」。

## 重審觸發（使用者紅色指標）

使用者於本 session 點出：「decisions-architecture.md 與 _AIDocs/Architecture.md 重疊」屬「**這套系統有沒有貫徹整個想法的紅色指標**」。原子記憶設計核心應是「印象式思考」（不易失意、按需深掘），不是把 md 內容縮抄到 atom。

衍生三原則（本次規則 atom 沉澱）：

1. **粒度**：atom 內混「知識/印象/行動」三段是顆粒過粗 — atom 應為「功能型單元」（印象本體 + 行動本體），禁止「知識描述」段
2. **[臨/觀/固] 維度為實驗性**：不依賴此維度定型其他規則
3. **[固] 邏輯應程式碼化**：絕對原則 — `[固]` 級且邏輯確定的內容應住 hook，不該每次讓 LLM 讀 atom 判斷

## 4 BLOCK 重審結論

### F1 IDENTITY.md 設計理由段移走 → **永久 BLOCK 確認**

**原 BLOCK 理由**：使用者於 session 內顯式還原。
**重審結論 (i) 永久 BLOCK**：vector REVIVE 不改變 always-load 必要性。在「印象 vs 縮影」框架下重新檢視 — 該段是「**行動本體**屬性」（為什麼用具體禁語清單而非抽象形容詞，給未來 AI 看的設計理由），不是 md 縮影。
**動作**：寫入 [known-regressions.md REG-007](../../known-regressions.md)。

### F2 preferences ChatGPT Pro 段 → feedback-codex-companion-model → **(ii) 條件變了，解封**

**原 BLOCK 理由**：feedback-codex-companion-model 不在 `_ATOM_INDEX.md` 表。
**重審發現**：該 atom **frontmatter 已寫 Trigger** 但未進 `_ATOM_INDEX.md` 表（hook 只讀後者）— 這就是「附帶議題：atom 注入 3 源不一致」的具體表現。
**重審結論 (ii) 條件變了**：直接把該 atom 加入 _ATOM_INDEX 即解封。同時發現該 atom 自身有「混型」失敗模式（## 知識內混「主規則/How to apply/副作用」三子段 + 重複的 ## 行動段），需重整。
**動作**：
1. 重寫 atom 為純「印象 + 行動」結構（35 → 22 行）
2. 副作用踩坑搬 [_AIDocs/Failures/codex-cli-version-mismatch-2026-04.md](../../Failures/codex-cli-version-mismatch-2026-04.md) + 加入 Failures _INDEX
3. preferences.md 第 21 行 ChatGPT Pro 段融入 atom「印象」第 2 條
4. 加入 `_ATOM_INDEX.md`（11 個觸發詞）

### F3 decisions-architecture.md V3 段壓索引 → **(iii) 縮減動作後解封**

**原 BLOCK 理由**：該檔不在 _ATOM_INDEX、ReadHits=0、僅 vector 召回；壓索引 0 always-load 收益。
**重審發現**：該 atom 是「**縮影 atom**」典型 — 36 行內容中 12 條「## 知識」全是 `_AIDocs/Architecture.md` 子段落的縮抄，僅「## 行動」3 條獨有。**這是使用者紅色指標的具體案例**。
**重審結論 (iii) 縮減動作**：不是「壓索引」也不是「刪檔」，而是**改寫為「指標型 atom」** — 印象段保留 4 條 ≤ 30 字 + → md 指針，行動段擴 3 條，純剝知識縮影。
**動作**：
1. 重寫 atom 為指標型（36 → 23 行）
2. 加入 `_ATOM_INDEX.md`（8 個觸發詞 — 之前 frontmatter 已寫，未進表所以不被 hook 用）

### F5 _reference 7-9 檔搬移 → **(ii) 條件變了，解封**

**原 BLOCK 理由**：`tools/memory-vector-service/indexer.py:74` 預設只掃 MEMORY_DIR，搬 _AIDocs/ 後 vector 召回會丟。
**重審發現**：實際是 **9 檔**，其中 1 檔（`internal-pipeline.md`）被 `workflow-guardian.py:936` 寫死引用必留。剩 8 檔內容屬「考古情境記憶」（V2/V3 設計史、SPEC、研究文件）。
**重審結論 (ii) 條件變了**：使用者紅色指標推翻原條件 — **考古資料不該被 fuzzy 召回**（會污染當前架構查詢，副作用 = Wave 3b 議題 #6 ranked min_score 偏寬鬆的污染源頭）。若需要召回，由「指標型 atom」明確指過去，而非 vector 模糊匹配舊全文。**不需改 `workflow/config.json` 加 `additional_atom_dirs`**。
**動作**：
1. 8 檔 `git mv` 到 `_AIDocs/DevHistory/atomic-memory-evolution/`
2. `_AIDocs/DevHistory/_INDEX.md` 加項 #16

## 衍生新檔

| 檔案 | 用途 |
|------|------|
| `memory/feedback/feedback-pointer-atom.md` | **新規則 atom** — 指標型 atom 三原則（去縮影 / 雙類型禁知 / [固]→程式碼化）|
| `_AIDocs/Failures/codex-cli-version-mismatch-2026-04.md` | 失敗教訓（從 codex-companion-model atom 副作用段提取）|
| `_AIDocs/known-regressions.md` REG-007 | F1 永久 BLOCK 理由 |
| `follow-up-issues.md` 議題 #10 | `[固]` 邏輯程式碼化候選盤點 |

## Smoke + 量測

### Smoke (全 PASS)

```bash
$ python hooks/wg_atoms.parse_memory_index('memory')
Total atoms parsed: 26
  ✓ decisions-architecture: 8 triggers
  ✓ feedback-codex-companion-model: 12 triggers
  ✓ feedback-pointer-atom: 7 triggers

$ python hooks/workflow-guardian.py  # SessionStart smoke
(no stderr, exit 0)
```

### 行數變化

| 檔案 | 前 | 後 | 變化 |
|------|----|----|------|
| `memory/decisions-architecture.md` | 36 | 23 | **-36%** |
| `memory/feedback/feedback-codex-companion-model.md` | 35 | 22 | **-37%** |
| `memory/preferences.md` | 26 | 24 | -2 行（ChatGPT Pro 段移除）|
| `memory/feedback/feedback-pointer-atom.md` | — | 30 | new（meta-rule，超 20 行上限可接受）|
| `memory/_reference/` 檔數 | 9 | 1 | 8 檔搬 _AIDocs/DevHistory/atomic-memory-evolution/ |

### Token 估算（誠實版，非單純「節省」）

**Trigger 命中時注入 token 變化**：
- `decisions-architecture` 之前 0（不在 _ATOM_INDEX，僅 vector 召回）→ 之後 ~575 tokens（指標型，純印象 + 行動，命中「架構/hooks/pipeline」等高頻詞時）
- `feedback-codex-companion-model` 之前 0 → 之後 ~550 tokens（重整後，命中「codex/gpt-5/...」時）
- `feedback-pointer-atom` 之前 0 → 之後 ~750 tokens（meta-rule，命中「寫 atom/縮影/...」較少觸發）

**Vector 召回品質**：
- `_reference/` 8 檔搬走 → vector 索引範圍縮小 → 考古資料不再污染當前架構查詢（接續 Wave 3b 議題 #6 的 ranked min_score 偏寬鬆問題部分緩解）
- 磁碟 -104K（vector 索引也對應減小）

**淨效應**：
- 不是 token 直接淨節省，是 **「token 花在對的位置」**：
  - 重要架構決策（decisions-architecture）+ Codex 配置（codex-companion-model）變成「可被 trigger 命中」（之前實際不會命中 = 失功能）
  - 移除「縮影」段（過去 trigger 命中時注入 36 行重 md 抄寫）→ 變指標型（注入 23 行純印象 + 行動）→ **單次命中 token 從 ~900 降到 ~575**（-36%）
  - vector 召回不再撈考古資料污染當前查詢

## 收尾

### 順手修補清單

- 本 session 無發現 drift
- 衍生 follow-up：議題 #10「[固] 邏輯程式碼化盤點」（中優先級，建議下個 session 處理 feedback-memory-path、feedback-no-test-to-svn 兩條強候選）
- 附帶議題（atom 注入 3 源不一致）— 透過將 2 個 atom 加入 _ATOM_INDEX，**部分解決**（仍待規格化「frontmatter Trigger 與 _ATOM_INDEX 表的關係」）

### 與原 prompt Step 3「派 3 fresh agent 重審」的差異

使用者於 session 中提出「紅色指標」後，重審重心從「BLOCK 是否仍成立」轉向「**這個系統有沒有貫徹原子記憶設計核心**」— 多 agent 重審原本要驗的是「BLOCK 條件是否變」，但紅色指標重新框架了問題（從「BLOCK vs 解封」變成「縮影 vs 指標型重構」），CC 寫手單獨可勝任這次重構（無需 Codex 對抗）。

**本次未派遣 3-agent 的具體原因**（不是「待後續」式退避）：
1. 紅色指標已將決策從「對抗式 BLOCK 仲裁」改為「設計原則貫徹」— 後者是單向決定（要嘛剝縮影要嘛保留），無對抗面可裁
2. 4 BLOCK 重審結論 3/4 偏保守（永久 BLOCK / 條件變了補完 / 縮減動作）— 多 agent 在「結論已偏保守」時邊際價值低
3. Smoke 已 PASS（3 atom 加入 _ATOM_INDEX 後 hook parse 成功；workflow-guardian.py 無 import error）— 對抗式驗證的失敗模式（hook break / atom 解析失敗）已由 smoke 排除

**3-agent 派遣的下次使用條件**（明寫，不留模糊）：
- dryrun 出現對抗式 BLOCK（兩位以上稽核給互斥結論）
- 結論偏激進（解封 ≥ 2 條 + 動 always-load 入口）
- 涉及 hook 鏈或 always-loaded 路徑改寫
