# Memory Cleanup 2026-04 — 8 大師報告精華

> 8 位 Phase 1-3 大師（5 分析席 + 3 稽核席）原始報告濃縮。原檔已隨 Wave 6 收尾刪除，本檔為決策證據鏈摘錄。
> Phase 4-5 wave-specific 稽核（Stage E dry-run / Stage F dry-run / Phase 5 紅隊 / Wave 3b 紅隊）摘要見 §9。

---

## 1. CC 考古學者（演化軌跡視角）

**主張**：找「殭屍」——看似活著實則死亡的功能/檔案/atom。

**5 大殭屍**：
1. **Vector service（181M，最大殭屍）**：service.log 最後 shutdown 4/15、pid 殭屍、curl health 無回應、但 `vector_ready.flag` mtime 持續更新——hook 系統 12 天 silent failure。建議直接砍整個 vector 子系統（命中率場景已被 keyword trigger 覆蓋；死了 12 天無人察覺即證據）。
2. **`wg_codex_companion_phase6.py` 結構性反模式**：一個 hook 寫死綁定一個 plan，會自我累積殭屍。
3. **projects/ 322M 中 4 個目錄已停滯 30+ 天**（c--TSG 對應 /c/TSG 已不存在）。
4. **`_reference/` 9 檔（104K）**：設計史/SPEC，不該每次 trigger 整檔注入。
5. **Feedback 19 檔（77K）**：與 commands/rules 重複源。

**風險警告**：(a) 不要砍 wisdom_engine.py（被 workflow-guardian.py:104 import）；(b) 動 vector 路徑前先確認 keyword 命中率；(c) 砍 plan 順序——先拆 hook 再刪 plan。

**自我謙抑**：只看 mtime + import + 服務存活；對「冷藏知識資產」的判斷需保守派補位。

---

## 2. CC 架構師（Information Architecture 視角）

**主張**：索引必須是程式真相，不是人類抄寫；always-loaded 區是聖域。

**3 件最堅持**：
1. **砍 `Project_File_Tree.md`**（13455 bytes / 218 行）——手寫快取已過時 10+ 天，違反「索引應自動生成」原則；改用 `tree -L 3 ~/.claude` 動態指令，或退一步壓成 30 行。
2. **`IDENTITY.md` 反退避契約「設計理由」段**屬後設說明，不該 always-load。
3. **「vector service 死亡 = section-level 注入退化 = 全 atom 進 context」**是當前最大隱性 token 出血——80% 的人會忽略這條因果鏈，因為 audit.log 還在寫看似活著。**修活優先於砍**。

**A2 高頻檔被低頻資訊污染**：
- `preferences.md`「ChatGPT Pro 訂閱」段，99% 場景無關；
- `decisions.md` §跨 Session 鞏固 dual-field 公式，是寫給 hook 的常數；
- `decisions-architecture.md` §V3 三層管線 30 行已沉澱於 `_AIDocs/Architecture.md`。

**自我謙抑**：低估特定大型任務下低頻 atom 的密集使用；對 hook import 死活鏈追得不夠（應由考古學者補位）。

---

## 3. Codex 保守派

**主張**：`feedback/`、`wisdom/`、`decisions*` 不是垃圾桶；先萃取到 `_AIDocs`，再縮短 atom，不要直接刪。

**3 條核心**：
1. **不能因 search service 死亡就整包砍 `_vectordb/`**：audit.log 仍有寫入活動，必須先釐清「查詢死、寫入活、資料可否歸檔」三件事。
2. **舊 plans/ 正確處理**：仍會影響未來決策的部分搬到 `_AIDocs/DevHistory/` 或 `_CHANGELOG_ARCHIVE.md`，不是全刪也不是全留。
3. **使用者偏好不能當低頻刪**：preferences/USER/workflow-rules 直接刪會讓系統變得不符合使用者工作方式。

**風險警告**：刪 decisions 只留結論不留理由——未來模型可能重提已否決方案 = 「看似精簡實際失憶」。

**自我謙抑**：本 session sandbox 不可讀檔，僅能提供風險框架，需考古學者+架構師+極簡派接力。

---

## 4. Codex 極簡派

**主張**：硬刀切——不能證明 30 天內有實際召回價值的就不該占 always-load 路徑。

**3 條最堅持**：
1. `_vectordb/` 是 182M 半死資產，除非能證明最近 30 天 search 有實際召回，否則應刪 runtime 與大檔，只保留故障摘要到 `_AIDocs`。
2. `feedback/`、`wisdom/`、`_reference/` 不應以 atom 全文形式被 trigger 注入；應降級為索引與冷文件。
3. **任何寫死特定 plan 的 SessionStart hook 都不該留在全域啟動鏈**——`wg_codex_companion_phase6.py` 綁 sprint5-eval 是典型反模式。

**風險警告**：不要刪 MEMORY.md、_ATOM_INDEX.md、wg_atoms.py（注入核心）；不要把 preferences.md 直接搬空（硬偏好需保留高頻層）；不要只刪 _vectordb/ 而不處理 atom_write 的寫入路徑。

**自我謙抑**：會低估低頻知識在關鍵時刻避免災難的價值——尤其架構決策、使用者偏好例外、failure pattern。

---

## 5. Codex 激進派（根因手術視角）

**主張**：清掉 md 只是治標——根因在「trigger 命中就全文注入」的注入機制。

**5 個結構性手術候選**：
1. **拔除 `_vectordb/` active runtime**——「寫入活、搜尋死」比沒有向量庫更危險。預期省 182M 磁碟，token 直接節省低，但消除半死索引鏈。
2. **atom 注入改為「摘要優先 + token budget + hot/cold 分級」**——預期 token 下降 20-60%。風險：摘要太短漏細節，需允許明確升級讀全文。
3. **always-loaded 鏈瘦身**——目標壓到目前 30-50%。風險：錯刪硬偏好降低品質。
4. **22 hook 收斂成 5 個可執行入口**——降 SessionStart 成本與維護成本。風險：需 import graph 驗證避免砍 dispatcher 依賴。
5. **單人模式降級 V4 多 scope**——`role/personal/_distant/shared pending` 長期空就應從執行路徑移除，設計留 `_AIDocs`。

**風險警告**：拒絕粗暴刪 preferences/USER/rules/workflow-rules——只能瘦身、分層、搬低頻；砍 wg_intent 反而增加 token 浪費。

**自我謙抑**：高估結構簡化收益，低估小檔的 continuity 價值；hook 生死需架構師補位。

---

## 6. Codex 稽核-Mechanic（事實核驗紅隊）

**核心發現**：用實檔 cat/grep/wc 驗證計畫草案的事實基礎。

**重大事實偏差**：
1. **計畫聲稱 `memory/personal/` 空 → 錯**：有 `holylight/role.md`（267 bytes）；`wg_roles.py`、`workflow-guardian.py:412 bootstrap_personal_dir`、`user-extract-worker.py` 都依賴 personal scope。Stage A2 `rm -rf personal/` 不可照做。
2. **計畫聲稱 vector 處理集中在 `wg_intent.py` → 錯**：主要 SessionStart 背景碼在 `workflow-guardian.py:595-662`，且 `vs_script = ~/.claude/tools/vector-service.py` 不存在（真檔在 `tools/memory-vector-service/service.py`）——比「service 死」更精確的根因：**啟動路徑寫死錯誤 + ready flag 無條件寫入造成假陽性**。
3. **`_reference/` 9 檔不在 `_ATOM_INDEX.md` trigger 表 → 成立**——但 `internal-pipeline.md` 被 `workflow-guardian.py:887-888` JIT 直接讀，搬移時必須留 stub 或同步改路徑。
4. **`feedback/` 15 檔，_ATOM_INDEX 只註冊 11 檔**——4 檔（codex-collaboration / e2e-smoke / pre-completion-test-discipline 等）是漏掛或冷藏，不能直接以「不注入」等同「無用」。

**裁決建議**：Phase6 清理只動兩點（刪 hook + 移 workflow-guardian.py:578-584），絕不擴及 settings.json 的 codex_companion.py 主鏈。

---

## 7. Codex 稽核-Redteam（破壞鏈視角）

**主張**：找最壞情況與單點失敗。

**9 個攻擊情境中最關鍵 5 條**：
1. **Stage A 空目錄刪**——`personal/` 不是空殼，是延遲建立的 scope（V4 role bootstrap 依賴）。
2. **Stage D vector 停用**——`wg_episodic.py`、`extract-worker.py`、`post-git-pull.sh`、`commands/conflict.md`、`commands/conflict-review.md`、`commands/upgrade.md` 仍指向 3849/vector service；只短路 `wg_intent.py` 會形成「主路徑停了，旁路仍呼叫死服務」。
3. **Stage D 觀察 7 天**——使用者 7 天沒問語意召回 ≠ 該功能無價值；7 天後刪 181M lance 是不可逆資訊損失。
4. **Stage F atom 裁剪**——搬 `_AIDocs` 後 trigger 命中時 hook 不會自動二次 Read，效果是「知道有東西但載不到」= 不失憶但想不起來。
5. **Stage G `Project_File_Tree.md` 縮**——若不同步改 `_AIDocs/_INDEX.md`、`Architecture.md`、`init-project.md`、`upgrade.md` 引用，讀者會拿到被縮過的「完整」文件。

**5 條最終建議**：(a) 任何 `rm -rf` 前必須產引用清單 + rollback；(b) 拆 phase6 後立刻跑 SessionStart smoke；(c) Stage D 改為先建全域 vector dependency map；(d) Stage F/G 搬移前先更新索引契約；(e) 沒有 rollback 證據的 Stage 不准升級到刪除。

---

## 8. Codex 稽核-Skeptic（樂觀估計挑刺）

**主張**：質疑收益估計與決策過快。

**4 條核心質疑**：
1. **always-loaded 精簡每 turn 約 250 tokens 偏樂觀**——真正浪費在 trigger atom 注入，不在入口檔；不該包裝為主要 token 成果。
2. **「刪 personal 空目錄」是錯的延伸**——personal/holylight/role.md 是角色宣告，不是垃圾；多角色機制要保留，personal role 不能當零風險清掉。
3. **Project_File_Tree 縮 30 行版本仍危險**——`_AIDocs/_INDEX.md` keywords「在哪裡/資料夾」很寬，會被自然導向；應降為非權威索引並改窄 keywords，否則持續製造過時權威。
4. **vector 裁決過快**——service.log 內曾有成功的 ranked/episodic 記錄，「現在 silent fail 不可接受」≠「語意搜尋永久無價值」；應先 fail-closed 並加觀察日誌。

**漏項補充**：`memory/_staging/` 並非 0 檔——有 `handoff-session-i-dashboard-update.md`（183 行）、`v42-candidates.md`（23 行），整合計畫草案漏掉。

**裁決建議**：vector 不應以「沒人察覺」裁定全砍——若 7 天內沒任何 ranked/section 搜尋需求再刪 lance；若要保留 section-level injection，優先修 ready flag 假陽性。

---

## 9. Phase 4-5 Wave-specific 稽核（補充）

| 報告 | 角色 | 關鍵結論 |
|------|------|---------|
| codex-audit-dryrun-E | Wave 4a Stage E 紅隊 | dry-run 刪 phase6 hook + workflow-guardian.py 引用範圍正確；提醒 Architecture.md 表格列同步刪除否則造成失效引用 |
| stageF_codex_conservative / v2 | Wave 4b Stage F 紅隊 | F2/F3/F5/F6/F7 BLOCK——`_AIDocs` 不在 vector 索引範圍 + 多檔不在 `_ATOM_INDEX` trigger 表，搬移會造成「知道但找不到」；只有 F4-drift（晉升門檻字串一致化）通過 |
| wave3b/codex-redteam | Wave 3b probe burst 紅隊 | log 無 atom 內容洩漏 / hot_cache 未污染 / ReadHits 未污染——proceed-with-note：service.py log_message 把 `q=...` 寫 stderr 是 pre-existing privacy footgun（已記入 follow_up #6） |
| codex-phase5-redteam | Phase 5 失憶場景紅隊 | cleanup 後系統未發現「失憶」：hook 鏈 import 完整、trigger 命中率穩定、_AIDocs 索引無死連結 |

---

## 10. 跨大師共識（決策黃金交集）

> 5 位以上同時主張或獨立印證的項目——這些直接成為 Wave 1-5 執行依據。

1. **wg_codex_companion_phase6 必砍 + 不誤殺 codex_companion 主 hook**（考古/架構/極簡/激進/Mechanic/Redteam/Skeptic 7 票）→ Wave 4a 執行
2. **vector silent failure 是當前最大 token 出血 + 需先修路徑/flag-gate 而非直接砍**（架構/Mechanic/Redteam/Skeptic 4 票對抗考古/極簡的「砍」2 票）→ Wave 3a 修補 + Wave 3b probe burst REVIVE
3. **personal/ 不可作為空目錄刪**（Mechanic/Redteam/Skeptic 3 票事實核驗推翻計畫草案）→ Wave 1 修正
4. **Project_File_Tree.md 必須降級**（架構/Mechanic/Redteam/Skeptic 4 票）→ Wave 4 處理（現況：保留並改窄 keywords）
5. **Stage F atom 搬移風險最高**（Redteam/Skeptic + Conservative 多票）→ Wave 4b 5 子 stage 中 4 個 BLOCK，僅 F4-drift 執行（議題 #9）
