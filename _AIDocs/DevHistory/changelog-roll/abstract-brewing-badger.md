# Plan v2: _CHANGELOG AI 自動滾動 + Architecture 變 Index 型

## Context（v1 被退回的原因）

- **v1 A 問題**：用 skill + rules 是被動，使用者要的是 **AI 必須自動跑** — 程式碼層強制，不靠 LLM 自律。
- **v1 B 問題**：-35% 不夠激進。使用者原則：**「留著給人讀完全無意義 → 只保留 AI 不會變笨、原有功能不失效的最小集」**。主檔應接近 **Index 型**。
- 設計哲學與本 session 剛做的 Evasion Guard 一致：**不依賴模型自律，在 hook 層擋死**。

---

## Part A: _CHANGELOG AI 自動滾動

### 機制（程式碼強制，非 rules 自律）

**三層**：
1. **Tool `tools/changelog-roll.py`** — 純邏輯，CLI `--keep N` / `--dry-run` / `--quiet`
2. **Skill `/changelog-roll`** — 手動入口（debug / 強制 roll）
3. **PostToolUse hook 自動觸發** — `workflow-guardian.py::handle_post_tool_use` 在既有 Edit/Write 分支末端加 gate：
   - `file_path` endswith `_CHANGELOG.md` → `_count_changelog_rows()` → 超過 config 閾值 → **detached subprocess.Popen** 跑 `changelog-roll.py`
   - Detached 避免拖慢 PostToolUse；CREATE_NO_WINDOW on Win
   - Fail-open：任何錯誤 silent，不阻塞 user flow
   - Config 可停：`workflow/config.json` 加 `changelog_auto_roll: {enabled: true, threshold: 8}`

### 為什麼 PostToolUse 是對的 hook

- Edit/Write 本來就是 Claude 產生 _CHANGELOG 變動的唯一路徑
- matcher 目前已是 `Edit|Write|Bash`（本 session 剛加的 Bash），加這段不改 matcher
- 觸發時機即刻（下一個 Bash 或 user prompt 前已 roll 完）
- 對比 Stop hook：Stop 只在 session 結束才跑，一整場累積才 roll 一次，即時性差
- 對比 rules：rules 讓 LLM 自律 — 會忘、會漏、會錯。使用者明確否決。

### 必要的「自動觸發驗證」測試

**`tests/test_changelog_roll.py` 8 條**：

前 5 條純工具邏輯：
1. `test_roll_exceeds_keep_moves_oldest` — mock 12 條 → 留 8 → ARCHIVE +4
2. `test_roll_preserves_preamble` — header + V3.1 Token Diet 敘述原樣留
3. `test_roll_nothing_when_under_keep` — 5 條 → exit 0 檔案未動
4. `test_dry_run_writes_nothing` — mtime 不變
5. `test_archive_missing_creates_shell` — ARCHIVE 不存在 → 建殼

後 3 條自動觸發驗證（mock subprocess.Popen）：
6. `test_post_tool_use_spawns_roll_when_over_threshold` — 構造 input_data `{tool_name: "Edit", tool_input: {file_path: "..._CHANGELOG.md"}}`，tmp 裡放 9 條的檔 → 呼叫 `handle_post_tool_use` → 驗 Popen 被 call 且首 arg 含 `changelog-roll.py`
7. `test_post_tool_use_no_spawn_when_under_threshold` — 同上但 5 條 → Popen 未被 call
8. `test_post_tool_use_no_spawn_on_other_files` — file_path 不是 _CHANGELOG → Popen 未被 call

### changelog-roll.py 邏輯

~120 行，零依賴：
- 讀 `_AIDocs/_CHANGELOG.md`，保留 header + 非表格 preamble（V3.1 Token Diet 那段）
- 正規解析表格 header `| 日期 | 變更 | 涉及檔案 |` + 分隔行 + data rows
- 日期 DESC defensive sort → 前 N 留主檔 / 其餘搬 ARCHIVE
- ARCHIVE 有既有表格 → data rows append 到表格頂（近→舊時序）
- 失敗 → stderr + exit 2，不動檔

### 手動跑一次歸檔

實作完後立刻 `python tools/changelog-roll.py`，主檔 26 → 8，ARCHIVE +18。

---

## Part B: Architecture.md 變 Index 型

### 保留準則（使用者原則）

**判准二擇一**：
- (a) 此段知識是否可能「讓 Claude 變笨」—— 即某 hook 或 user prompt 場景，沒看到這段就會做錯決策？
- (b) 此段是否對應仍在演化、近 7 天有改動的 feature？

**都否 → 搬 DevHistory，主檔只留 1 行索引 + keywords**（給 AI 的 trigger match 用）

### 行級清單（主檔 413 行 → 目標 ~115 行）

| 主檔行 | 內容 | 動作 | 去處 |
|---|---|---|---|
| L1-16 | Title + Hooks 事件表（8 行） | **全留** | — |
| L18-37 | Hook 模組拆分表（14 列） | **全留** | — |
| L39-45 | 輔助 Hook 腳本 | **全留**（短） | — |
| L47-67 | Skills 表（17 個） | **全留** | — |
| L69-82 | Evasion Guard 表 | **全留**（本 session 最新） | — |
| L84-93 | 規則模組表 | **精簡 3 行** + 指 `rules/core.md` | rules/ 已是事實來源 |
| L95-103 | 記憶系統概述 + 雙 LLM 表 | **精簡 5 行** | — |
| L104-118 | Dual-Backend Ollama 退避細節 | **搬** | `DevHistory/ollama-backend.md`（新） |
| L120-127 | 資料層 6 點 | **搬** | `Project_File_Tree.md` 已含 → 刪除 |
| L129-144 | 記憶檢索管線 ASCII 圖 | **搬** | `DevHistory/memory-pipeline.md`（新） |
| L146-153 | 回應知識捕獲 | **搬** | `DevHistory/memory-pipeline.md` |
| L155-179 | V4.1 使用者決策萃取 | **搬** | `DevHistory/v41-journey.md`（擴充） |
| L181-197 | V4.1 P4 Session 評價 | **搬** | `DevHistory/v41-journey.md` |
| L199-207 | V3 三層即時管線 ASCII | **搬** | `DevHistory/memory-pipeline.md` |
| L209-214 | SessionStart 去重（5 點含 merge self-heal） | **搬** | `DevHistory/session-mgmt.md`（新） |
| L216-221 | 專案自治層 | **搬** | `DevHistory/v4-layers.md`（新） |
| L223-231 | V4 三層 Scope + JIT（6 點） | **搬** | `DevHistory/v4-layers.md` |
| L233-249 | V4 三時段衝突偵測 | **搬** | `DevHistory/v4-conflict.md`（新） |
| L252-324 | 衝突偵測 ASCII（3 box，73 行） | **搬** | `DevHistory/v4-conflict.md` |
| L326-334 | V4.1 萃取 Pipeline（重複） | **搬** | `DevHistory/v41-journey.md`（合併消重） |
| L336-341 | 跨 Session 鞏固 | **留 2 行** + 指 `memory/decisions.md` | — |
| L343-347 | Wisdom Engine | **搬** | `DevHistory/wisdom-engine.md`（新） |
| L349-369 | 工具鏈表（19 列） | **搬** | `Project_File_Tree.md` 已含 → 刪 |
| L371-400 | MCP Servers + atom_write/promote 詳細表 | **精簡**：保留 atom_write 參數表（AI 直接呼叫要用）+ atom_promote 一行 + UPS Guard 一行 → 詳情指 [SPEC_ATOM_V4.md](SPEC_ATOM_V4.md) | — |
| L402-404 | UPS Atom-Write Guard 敘述 | **留 2 行** | — |
| L408-413 | 權限設定 5 點 | **搬** | `DevHistory/settings-config.md`（新） |

### 主檔最終結構（目標 ~115 行）

```
# Claude Code 全域設定 — 核心架構
（1-2 行 blurb：「索引 + 現役 feature，細節見 DevHistory」）

## Hooks 系統
### 事件表（全留）
### 模組拆分（全留）
### 輔助 Hook（全留）

## Skills（全留）

## 新增/演化中 feature
### Evasion Guard / Test-Fail Gate（2026-04-17+，wg_evasion.py）
（整段留，本 session 最新）

## 規則模組 → rules/core.md
（2 行指路）

## 記憶系統（原子記憶 V4.1）
### 概述 + 雙 LLM
（5-8 行）

### 子系統索引
| 主題 | 詳情文件 | keywords |
|---|---|---|
| Dual-Backend Ollama 退避 | DevHistory/ollama-backend.md | 退避, DIE, rdchat |
| 記憶檢索管線 | DevHistory/memory-pipeline.md | pipeline, JIT, vector, hot cache |
| 回應知識捕獲 | DevHistory/memory-pipeline.md | 萃取, extract, quick-extract |
| V4.1 使用者決策萃取 | DevHistory/v41-journey.md | user-extract, L0, L1, L2, gemma4 |
| V4.1 P4 Session 評價 | DevHistory/v41-journey.md | session_score, evaluator |
| V3 三層即時管線 | DevHistory/memory-pipeline.md | V3, hot_cache |
| SessionStart 去重 | DevHistory/session-mgmt.md | dedup, merge_into, self-heal |
| 專案自治層 + V4 三層 Scope | DevHistory/v4-layers.md | scope, personal, shared, role |
| V4 三時段衝突偵測 | DevHistory/v4-conflict.md | conflict, pending_review, 衝突 |
| Wisdom Engine | DevHistory/wisdom-engine.md | wisdom, reflection, 反思 |

### 跨 Session 鞏固
（2 行，指 memory/decisions.md）

## MCP Servers
| Server | 傳輸 | 用途 |
| workflow-guardian | stdio | ... |

### atom_write（V4 三層 scope）
（保留參數表 — AI 直接呼叫要用）

### atom_promote
（1 行 + merge_to_preferences 一句）

### UPS Atom-Write Guard
（2 行）

詳見 [SPEC_ATOM_V4.md](SPEC_ATOM_V4.md)。
```

**目標量化**：413 → ~115 行；32KB → ~8KB；~8k tok → ~2k tok（**-75%**）。

### 「AI 不會變笨」驗證方法

搬出後做以下檢查 — 確認核心場景仍有指路：

1. **keyword match 不失**：UPS hook 用 `memory/_ATOM_INDEX.md` + `_AIDocs/_INDEX.md` 做 trigger 匹配。搬到 DevHistory 的檔案若帶 keywords，當使用者問相關主題時仍能命中。主檔的子系統索引表格為每條列 keywords（上面表格第 3 欄），確保 AI 在主檔 grep 命中後跟著 follow 到子檔。
2. **SPEC_ATOM_V4.md 為 V4 真相來源**：原主檔的 V4 細節其實在 SPEC 裡已有。搬的動作是**去重複**。
3. **rules/core.md 為規則真相來源**：主檔原本的「規則模組」表已是指路，只是指路本身也可以更短。
4. **DevHistory/_INDEX.md 補登記**：每個新檔登記 + 3-5 keywords。使用者提 `/read-project` 或 Claude 搜 DevHistory 時都能命中。
5. **Claude-facing 簡單 smoke test**（非自動化）：改完後，新開一場 Claude session 問「V4 衝突偵測怎麼運作？」觀察 Claude 是否正確找到 `DevHistory/v4-conflict.md`。一次人工目測，用來驗架構沒斷。

---

## Part C: 執行順序 + 修改清單

| 步 | 動作 | 檔案 |
|---|---|---|
| 1 | 建 `tools/changelog-roll.py`（120 行） | 新 |
| 2 | 建 `commands/changelog-roll.md`（20 行 skill） | 新 |
| 3 | 建 `tests/test_changelog_roll.py`（8 條，含 PostToolUse 觸發驗證） | 新 |
| 4 | `workflow/config.json` 加 `changelog_auto_roll: {enabled: true, threshold: 8}` | Edit |
| 5 | `hooks/workflow-guardian.py::handle_post_tool_use` 加 _CHANGELOG gate（+ 15 行） | Edit |
| 6 | `pytest tests/` 全綠 + 手動驗 `python tools/changelog-roll.py --dry-run` | verify |
| 7 | 實跑 `python tools/changelog-roll.py` → 26→8 條，ARCHIVE +18 | run |
| 8 | 激進搬 Architecture → 5 個 DevHistory 新檔 | 多檔 |
| 9 | `DevHistory/_INDEX.md` 補 5 條登記 | Edit |
| 10 | 人工目測：主檔掃一遍，子系統索引表每條可指到檔 | verify |
| 11 | `_CHANGELOG.md` 加本次條目（一條精簡，≤5 行） — 自動 roll 會再踢一條最舊的出去，驗證自動機制 | verify |
| 12 | `pytest` + `node --check` + import check | 自我驗證 |

**新建檔案總覽**：
- `tools/changelog-roll.py`
- `commands/changelog-roll.md`
- `tests/test_changelog_roll.py`
- `_AIDocs/DevHistory/ollama-backend.md`
- `_AIDocs/DevHistory/memory-pipeline.md`
- `_AIDocs/DevHistory/v41-journey.md`（已存在 → 擴充）
- `_AIDocs/DevHistory/session-mgmt.md`
- `_AIDocs/DevHistory/v4-layers.md`
- `_AIDocs/DevHistory/v4-conflict.md`
- `_AIDocs/DevHistory/wisdom-engine.md`
- `_AIDocs/DevHistory/settings-config.md`

8 個新 DevHistory 子檔（其中 1 個擴充既有）。每個 30-90 行。

**不動的檔案**：MCP server.js、feedback/、atom_promote（本 session 約束仍在）。

---

## 約束 / 風險

| 風險 | 緩解 |
|---|---|
| DevHistory 檔案爆炸（8 個新檔） | 都登 `_INDEX.md`，keyword 充分；可視情況後續合併 |
| 搬出去的某段其實 AI 很常用，砍掉後 AI 變笨 | 主檔每條留「子系統索引」指路 + keywords；keyword match 命中後 Claude 會 Read 子檔 |
| PostToolUse auto-roll subprocess 影響效能 | `subprocess.Popen` detached，不 wait，不阻塞 hook；fail-open |
| _CHANGELOG 本身格式異動會 break parser | parser 失敗 stderr + exit 2 不動檔；有 dry-run 預檢 |
| 本 session 本身留下很多紀錄（plans 檔、改動多），會讓最新 _CHANGELOG 又塞滿 | 本次條目必須**精簡 ≤ 5 行**（不像剛才那條 Evasion Guard 的 2KB 單行），並立刻測自動 roll |

---

## 自我驗證（巨任務收尾）

1. `pytest tests/test_changelog_roll.py -v` — 8 條全綠
2. `pytest tests/ -q --ignore=tests/integration` — 140+8=148 全綠（無回歸）
3. `node --check tools/workflow-guardian-mcp/server.js` — 未動但檢查
4. `python -c "import sys; sys.path.insert(0,'hooks'); import wg_core; import workflow_guardian"` — import 乾淨
5. **自動 roll 煙霧**：人工 Edit `_CHANGELOG.md` 加一條 → 等 1-2s → `wc -l` 驗證 roll 已跑（主檔回到 8 條）
6. `wc -l _AIDocs/Architecture.md` — 目標 ≤120 行
7. `du -h _AIDocs/Architecture.md` — 目標 ≤10KB
8. 人工新 session 問「V4 衝突偵測怎麼做？」— 驗 Claude 能找到 DevHistory 子檔
9. **baseline drift 若有 → 當場 `python tools/snapshot-v4-atoms.py` 刷新**（同本 session 教訓）

---

## 使用者仍需決策的點

1. **DevHistory 分檔粒度**：我切 8 個子檔，每個主題 1 檔。也可粗粒度切成 3 檔（記憶/V4/基礎建設）。建議 **8 個細粒度**：日後搜尋/更新好找，token 注入不會整檔帶入。
2. **主檔 MCP atom_write 參數表是否也搬**：我留著因為 AI 直接呼叫 atom_write 時要看。若 SPEC_ATOM_V4.md 已有同等內容 → 可搬（再省 15 行）。建議 **先留，動手時對 SPEC 若真的一致就搬**。
