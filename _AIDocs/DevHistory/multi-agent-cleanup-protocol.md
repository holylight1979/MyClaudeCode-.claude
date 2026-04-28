# Multi-Agent Protocol — Memory Cleanup 計畫專用

> 後續 session 啟動時必讀。確保多 agent 協作模式不丟失。
> Date: 2026-04-28

## 一、為什麼用多大師（使用者明確要求）

使用者原話（不可曲解）：

> 2. 從多大師計劃開始、大師預測結果、也必須有多大師監督執行、多大師自檢驗證結果。
> 3. 你(ClaudeCode)與 Codex 的關係、"不是你派工給他，而是你要讓他具備與你一樣的閱讀知識量"，他主要負責擴展/補完你的思考與視野、並輔助決策，但最終由你來負責定案、以及推動整批執行；
> 4. 而且要以 codex 啟動扮演 agent 的不可以只有一位，至少要三位、分別扮演不同的角色（但是你要讓他們都能閱讀、或你告知、具備同樣量級的知識）。
> 5. 要注意 Codex 的幻覺、避免 ClaudeCode 你自己被他帶去錯誤的風向（因此大師的席次你應該要比他更多一些關鍵的）。

## 二、CC > Codex 席次設計

每個 phase 必須 CC 席次 ≥ Codex 席次（特別在「預測」「裁決」這類關鍵決策階段，CC 必須佔多數）。本計畫累計：

| Phase | CC 席次 | Codex 席次 | 用途 |
|-------|--------|-----------|------|
| 計劃 | 2（架構師、考古學者） | 3（極簡、保守、激進） | 五人共議 |
| 預測 | 2（風險預測、效益預測） | 0 | 預測階段刻意排除 Codex（避免幻覺帶風向） |
| 監督執行 | 1（CC 寫手） + 1（CC 稽核） | 1（Codex 稽核） | 每 Stage 動工前的 dry-run 驗證 |
| 驗證 | 2（功能驗證、token 驗證） | 1（紅隊） | 三方獨立 |
| **累計** | **8** | **5** | CC 多 3 席 |

## 三、Codex 啟動方式（**Windows sandbox 修復重要！**）

### 預設 sandbox 是壞的
使用者本機 `~/.codex/config.toml` 含 `[windows] sandbox = "elevated"`，CLI 旗標 `-s read-only` / `-s workspace-write` 在 Windows 下會觸發 `CreateProcessWithLogonW failed: 1385`（logon type not granted）→ Codex 無法執行任何 shell 指令、實質讀檔失敗。

### 修復方式
所有 codex exec 必須加 `-c 'windows.sandbox="unelevated"'`：

```bash
codex exec \
  -c 'windows.sandbox="unelevated"' \
  --skip-git-repo-check \
  -p zh-brief \
  --color never \
  "$PROMPT" > output.md 2>&1
```

`unelevated` 是 Codex Windows sandbox 唯二合法值之一（另一個是 elevated），仍有 sandbox 保護但不需提權。

### 並行派發（3 位 Codex）
用 Bash `run_in_background=true` 同時 spawn，timeout 300s：

```bash
codex exec ... > output1.md 2>&1 &  # role A
codex exec ... > output2.md 2>&1 &  # role B
codex exec ... > output3.md 2>&1 &  # role C
```

或用 Bash tool 三次 `run_in_background: true`。完成時系統會 task-notification 通知，不需 polling。

### Codex auth 確認
`codex login status` 應顯示 "Logged in using ChatGPT"。預設 model `gpt-5.5` reasoning `xhigh`，profile `zh-brief`。

## 四、給 Codex 的知識交付包（briefing）

使用者要求：「不是你派工給他，而是你要讓他具備與你一樣的閱讀知識量」

實作：每次派 Codex 必須先寫一份 briefing.md，含：
1. 任務目標（**逐字保留使用者原話**，不要轉述）
2. 角色說明（你是哪一位大師、立場、其他大師的存在）
3. 必讀檔案清單（含絕對路徑）
4. 已盤點事實（讓 Codex 不必重做、節省 token）
5. 輸出格式（固定章節，便於整合）
6. 邊界（禁瞎掰、禁寫檔、禁產 patch）

Codex 透過 cat/head/grep/wc 讀檔（**不要用 PowerShell**，sandbox 易出問題）。

## 五、Codex 幻覺防範

每次 prompt 結尾必須加：

> ❌ 不要假設不存在的檔案/功能 — 如果你不確定某個東西是否存在，列入 C3 不確定區，**不要瞎掰**（這是 Codex 幻覺最常見的失敗模式，ClaudeCode 在防你這點）。

整合 Codex 報告時：
- 若三位 Codex **意見矛盾** → CC 用實際讀檔仲裁，不直接採用任一方
- 若 Codex **單獨提出** 某個事實主張（其他大師沒提）→ CC 必須親自驗證再採用
- 若 Codex **與 CC 大師矛盾** → 預設信 CC（CC 有實際讀檔基礎），除非 Codex 給出明確新證據

## 六、Per-Stage 監督執行模板

每個 Stage 動工前：

1. **CC 寫手（你）**：列出本 Stage 將執行的具體 bash/Edit/Write 動作（**dry-run 列表**，不真執行）
2. **CC 稽核 + Codex 稽核 並行**：派 Plan agent + codex exec，輸入 dry-run 列表 → 各自驗證
3. **整合稽核反饋** → 修正 dry-run 列表
4. **執行**：照修正後列表動工
5. **post-check**：跑 smoke test（hook import / 引用驗證 / 結構檢查）
6. **scan report**：輸出順手修補清單

### Silent-failure 風險的 Stage 必須加 log 採樣（Wave 3a 新增規則 2026-04-28）

> 觸因：Wave 3a 發現 plan v2.1 的 D4「4 天觀察期 → 等使用者主訴 atom 沒命中」根本不可行 — silent failure 本身不可見（vector silent fail 12 天無人察覺即證據）。

**規則**：任何 Stage 牽涉以下任一條件，**必須在動工前先鋪 log 採樣機制**，不依賴使用者察覺：

- (a) hook 鏈或 always-loaded 入口（fail 後使用者只看到「東西怪怪的」而無錯誤訊息）
- (b) 觀察期 ≥ 4 天的 stage（人類記憶會淡化）
- (c) 跨 session 才會浮現的問題（單 session 看不出 regression）
- (d) bg subprocess / fire-and-forget 程式碼（stderr 多半被 DEVNULL 吞）

**鋪設要求**：
1. 結構化 JSON log，schema 至少含 `{ts, session_id, fn, flag_state, result_count, fallback_used}`
2. 寫到 `~/.claude/Logs/<subsystem>-observation.log`（與 atom-debug-*.log 區隔）
3. 對應的 `tools/<subsystem>-observation-summary.py` 自動判定（修活 / 淘汰 / 灰色）
4. 觀察期結束後**先讀 log 自動判定**，灰色地帶才詢問使用者
5. 灰色地帶閾值：命中率 5–15%（依 stage 風險可調，需在 dry-run 寫明）

**已套用 stages**：
- Stage D（vector subsystem）— 由 Wave 3a 鋪設，4 天後讀 log 決定 REVIVE/RETIRE/GRAY
- Stage E（hook 鏈精簡）— 動工前須鋪同型儀表（codex_companion.py trigger 命中率 log）
- Stage F（atom 內容裁剪）— 動工前須鋪 always-loaded baseline diff sampling（atom-health-check.py 已有，補 4 天滾動採樣）

## 七、計畫剩餘 Stage 的多大師建議分工

| Stage | 風險 | CC 寫手 | CC 稽核 | Codex 稽核 | 必跑 smoke |
|-------|------|--------|--------|-----------|----------|
| B（plans 過時） | 低 | 直接做 | 抽樣驗 | 抽樣驗 | git status 檢查 |
| C（projects 已棄） | 低 | 直接做 | grep 引用 | — | 對應 work dir 是否真不存 |
| D（vector subsystem） | 中 | dry-run | 必派 | 必派紅隊 | SessionStart smoke + curl health |
| E（hook 鏈） | 中-高 | dry-run | 必派 | 必派 | hook import smoke + SessionStart smoke |
| F（atom 內容裁剪） | 高 | dry-run | 必派 architect | 必派 conservative | always-loaded baseline diff |
| H（規則沉澱） | 低 | 直接寫 | 抽樣 | — | atom_write 驗證 |

## 八、必讀檔案清單（給新 session）

啟動時請依序讀：

1. `~/.claude/plans/memory-cleanup-2026-04-27/codex_briefing.md` — 任務原始定義
2. `~/.claude/plans/memory-cleanup-2026-04-27/synthesis_and_plan_v2.md` — 計畫 v2.1（含使用者裁決）
3. `~/.claude/plans/memory-cleanup-2026-04-27/multi_agent_protocol.md` — **本檔，多 agent 協議**
4. `~/.claude/plans/memory-cleanup-2026-04-27/follow_up_issues.md` — 另開議題清單（vector 精密化 + 失效根因）
5. `~/.claude/plans/memory-cleanup-2026-04-27/rollback_manifest.txt` — session 1 已動 manifest
6. `~/.claude/plans/memory-cleanup-2026-04-27/outputs/*.md` — 5 大師原始報告 + 3 稽核報告（按需讀，不必全讀）

## 九、版本與更新規則

- 本檔由 session 1 建立，新 session 若發現協議需修訂 → 在 §九 之後新增「v1→v2 修訂」段落，不要直接改前面內容（保留歷史）
- 使用者裁決調整（如再次調整觀察期、再次調整席次）必須記入此檔

## 十、Session 並行策略（使用者要求 2026-04-28）

### 衝突源（兩 session 同時動到 = race）

- `settings.json` — Claude Code 啟動會自動寫 allowlist / additionalDirectories
- `workflow/state.*.json` — SessionStart 去重的 merge_into 邏輯
- `memory/*.access.json` 或 atom frontmatter ReadHits — hook 自動 ++ counter
- 任何被兩 session 同時 Edit/Write 的同一檔

### 並行波次規劃

| Wave | 並行度 | 工作 | 衝突風險 |
|------|--------|------|---------|
| Wave 1 ✅ | 1 session | A0 + A + G1 | — |
| Wave 2 🟢 可並行 2 | (a) Stage B `plans/`<br>(b) Stage C `projects/` | settings.json 雙 auto-edit 結束後 git merge 一次 |
| Wave 3 🔴 序列 | Stage D（vector subsystem） | 動 hooks 核心 |
| D 觀察 4 天 🟡 可並行**準備** | (a) E dry-run（讀+規劃，不寫）<br>(b) F dry-run（讀+規劃，不寫） | dry-run 不寫檔，無衝突 |
| Wave 4 🔴 序列 | E → F（hook 鏈 → always-loaded 入口） | always-loaded 級風險 |
| Wave 5 🟡 可並行 | (a) Stage H 寫新 atom<br>(b) Phase 5 驗證 | H 寫新檔，驗證讀檔 |
| Wave 6 🔴 序列 | Phase 6 歸檔 + 刪 plans/ + _CHANGELOG | 動 `_AIDocs/DevHistory/` 集中操作 |

### 並行操作規則

1. **波次內並行允許 ≤ 2 session**（更多會增加 settings.json merge 成本）
2. **每個並行 session 啟動前必須寫 `plans/memory-cleanup-2026-04-27/_session_lock_<wave>_<id>.txt`** 含時間戳 + 預計動的檔案路徑清單；其他 session 啟動前 grep 此目錄確認無重疊路徑
3. **session 結束前必須**：
   - `git -C ~/.claude status` 列出實際變動
   - 刪除自己的 `_session_lock_` 檔
4. **會合點**：所有並行 session 完成後，啟動下一波之前先在 1 個 session 跑：
   ```
   git -C ~/.claude diff --stat
   git -C ~/.claude add -A && git -C ~/.claude commit -m "wave-N parallel cleanup"
   ```
5. **若兩 session 都改 settings.json**：手動 git merge 解（保留兩邊的 allowlist 條目）

### 不建議並行的場景

- Stage D / E / F：動 hook 鏈或 always-loaded 入口，單 session 較安全
- Phase 6 收尾：操作集中，單 session 容易掌控

## 十一、最終收尾 — 計畫檔案歸檔/清理（使用者要求 2026-04-28）

> 觸發條件：所有 Stage（A0-H）+ Phase 5 驗證 + Phase 6 收尾 全部完成 + git commit + git push 全部上完之後

### 10.1 知識資產判定（搬 `_AIDocs/`）

**判定原則**：「未來高度可能用到」就搬，不是看「現在還在用」。

| 來源 | 判定 | 目標 |
|------|------|------|
| `multi_agent_protocol.md` | **歸檔** — 多 agent 協作協議是可重複使用的方法論 | `_AIDocs/DevHistory/multi-agent-cleanup-protocol.md`（重命名為通用名） |
| `synthesis_and_plan_v2.md`（最終版） | **歸檔** — 完整決策史 + 矛盾仲裁 + Codex/CC 5 大師 + 3 稽核 + 2 預測席意見 | `_AIDocs/DevHistory/memory-cleanup-2026-04/synthesis.md` |
| `follow_up_issues.md` | **歸檔** — vector 失效根因 + 精密化議題 + atom 注入重構 + hook 萃取重複，全是後續 session 起點 | `_AIDocs/DevHistory/memory-cleanup-2026-04/follow-up-issues.md`（同步加入 `_AIDocs/known-regressions.md` 索引） |
| `outputs/cc-architect.md` `outputs/cc-archaeologist.md` `outputs/codex-auditor-*.md` | **濃縮歸檔** — 8 份報告壓縮成 1 份「大師意見摘要」（每位 200-300 字精華） | `_AIDocs/DevHistory/memory-cleanup-2026-04/master-review-digest.md` |
| `codex_briefing.md` | **不歸檔** — briefing 對未來無價值（任務已完成） | 刪除 |
| `synthesis_and_plan_draft.md`（v1） | **不歸檔** — 已被 v2.1 完全取代 | 刪除 |
| `outputs/codex-minimalist/conservative/radical.md`（sandbox 故障的 5 大師） | **不歸檔** — 因 sandbox 故障無實證，立場主張已被 audit 階段重做覆蓋 | 刪除 |
| `rollback_manifest.txt` | **不歸檔** — manifest 是執行期暫存 | 刪除 |
| `outputs/` 整個目錄 | 提取「大師意見摘要」後 → 整目錄 | 刪除 |

### 10.2 失敗教訓寫入 `_AIDocs/Failures/`

本次過程踩到的坑必須沉澱：

- `_AIDocs/Failures/codex-windows-sandbox-1385.md` — Codex `read-only` 在 Windows 因 `[windows] sandbox = "elevated"` 觸發 `CreateProcessWithLogonW failed: 1385`，修復 = `unelevated`
- `_AIDocs/Failures/vectordb-silent-failure-2026-04.md` — `workflow-guardian.py:611` 路徑寫死錯（`tools/vector-service.py` vs 真檔 `tools/memory-vector-service/service.py`）+ line 632 無條件寫 ready flag → 12 天假陽性
- 兩檔加入 `_AIDocs/Failures/_INDEX.md` 索引

### 10.3 規則沉澱寫入 atom（Stage H 連動）

- 規則：「寫死綁定特定 plan 的 SessionStart hook 模式禁止」（`wg_codex_companion_phase6.py` 的反模式教訓）
- 規則：「bg subprocess 啟動失敗必須有 stderr log 出口、不可導向 DEVNULL 後寫 ready flag」
- 用 `mcp__workflow-guardian__atom_write` 寫入 `memory/feedback/`（必為 [臨]，後續晉升靠機制）

### 10.4 plans/ 目錄完整刪除

歸檔 + 失敗教訓 + atom 寫入皆完成後：

```bash
rm -rf ~/.claude/plans/memory-cleanup-2026-04-27/
```

理由：
- 本目錄整個 gitignore，無歷史保留價值
- 知識資產已搬至 `_AIDocs/DevHistory/`（git 追蹤）
- 留著只會讓未來 cleanup 計畫的命名空間衝突

### 10.5 _CHANGELOG.md 收錄

最終加入 `_AIDocs/_CHANGELOG.md` 一行：

```
2026-04-XX: memory cleanup — _vectordb 修活/淘汰、Project_File_Tree 索引化、22 hook 鏈確認、_reference 搬遷、token per-session 節省 ~20K。詳見 _AIDocs/DevHistory/memory-cleanup-2026-04/。
```

由 `tools/changelog-roll.py` PostToolUse 自動 archive 機制處理。

### 10.6 收尾 checklist（最後 session 必須核對）

- [ ] 所有 Stage A0-H 完成且 smoke test 通過
- [ ] 4 天 / 10 天觀察期已過或被 user 顯式跳過
- [ ] git commit 含明確 message + push 完成
- [ ] 知識資產已搬 `_AIDocs/DevHistory/memory-cleanup-2026-04/`
- [ ] 失敗教訓已寫 `_AIDocs/Failures/` + 加 _INDEX
- [ ] 規則 atom 已寫入 `memory/feedback/`
- [ ] `_CHANGELOG.md` 加一行
- [ ] `plans/memory-cleanup-2026-04-27/` 整目錄刪除
- [ ] 跑一次 SessionStart smoke test 確認新狀態無 import error
- [ ] 通知使用者「本計畫全部完成，歸檔 X、刪除 Y、token 節省實測 Z」
