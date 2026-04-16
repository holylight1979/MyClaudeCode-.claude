# V4.1 開發歷程 — 從「隔間空的」到 GA

> **期間**：2026-04-15（V4 Phase 6 完成）→ 2026-04-16（v4.1.0 GA）
> **規模**：1.5 天 / 7 個 session / 10 + 8 = 18 個 validation agent / 8 次 commit / 5 個 tag
> **核心交付**：使用者對話中的決策語句主動偵測 → 三層 gating → atom 自動寫入 → V4 既有 JIT 下次 session recall

---

## 1. 起因

V4 (2026-04-15 Phase 6 收尾) 蓋好了多人共享記憶的「分流 + 防護網」：`personal/shared/role` 三層 scope、三時段衝突偵測、管理職雙向認證、JIT 角色 filter 全部到位。

但實況：萃取流水線（`hooks/quick-extract.py` + `hooks/extract-worker.py`）只讀 transcript JSONL 的 `type=="assistant"` blocks。**對「使用者」輸入幾乎沒分析**。對話中真正的金礦 — 使用者的決策、偏好、反饋、設計選擇、規範拍板 — 常被當上下文丟掉，沒沉澱進 atom。`knowledge_queue` 也沒自動 flush，靠下個 session Claude 看到才有可能寫成 atom。

結果：alice/bob 各自的 role 隔間蓋好了，**但隔間裡是空的**，V4 角色 filter 變成「過濾空集合」，使用者體感 = V4 雞肋。

V4.1 的目的：補上「使用者輸入 → atom 自動寫入」這一環。注入部分沿用 V4 既有能力。

---

## 2. 方法論 — 10 大師圓桌（Phase A-D）

### 2.1 為什麼不用傳統 plan mode

傳統 plan mode 是「Claude 自己寫 plan → 使用者 approve」。對 V4.1 這種「邊界不清、Precision 0.92 是否可達都存疑、token 預算極緊」的任務，單 agent 思考會陷入 local optimum。

改為 **10 大師並行 drafting + 雙 round validation**：

| 大師（8 drafter）| 視角 | 對應 NFR |
|---|---|---|
| 人文專精 | 決策邊界、agency 紅線、文化差異 | 精準（避免錯記） |
| UX 學 | surface 策略、修復路徑、心智模型 | 不雞肋（使用者體感） |
| 程式專精 | 整合點、測試策略、可回滾性 | 實作可行性 |
| AI 專精 | 模型選擇、prompt 工程、推理 pipeline | 精準 + 低耗 token |
| 原子記憶專精 | metadata 完整性、scope/audience 推斷、dedup | 與 V4 相容 |
| 實作大師 | MVP 邊界、phase 切分、能砍清單 | 時程 |
| 精省 token 大師 | gating 層級、cache 策略、amortized cost | 低耗 token (≤ 200 tok/session) |
| 語意理解大師 | features、信號詞、stance detection | 精準 |

加 **2 資訊整合大師**（Prior Art + NLP Benchmark）— 做網路搜尋、提供「別人已失敗」的 evidence，防止 8 drafter 過度幻想。

### 2.2 Phase A drafting 重要發現

並行召集 10 個 `general-purpose` agent 獨立提案，平均每份 600-800 字：

- 精省 token 大師估 168 tok/session 達標（用 L0 過濾 88% + prompt cache 90% 命中）
- AI 大師建議三層級聯（rule → qwen3:1.7b → gemma4:e4b 仲裁）
- 原子記憶大師提 scope decision tree：「我」→ personal、「團隊」→ shared、「{role}組」→ role
- 人文大師列 20 組該抓/不抓對照（含 ✗「靠 剛才 atom 又寫歪」情緒+決策混合句）

**資訊整合 #2 量化反駁（關鍵洞察）**：
- Mem0 SOTA LOCOMO 66.9% — 短中文 subjective class 公開無 ≥ 0.85 Precision 數據
- small LLM (1-3B) zero-shot intent F1 最高約 0.65
- Mem0 production audit 10134 筆 **97.8% junk**
- 即使 two-stage rule+LLM 典型 P 0.85-0.90，難穩定 ≥ 0.92

→ V4.1 Precision 0.92 在學術上屬激進目標，必須靠 **hybrid threshold routing**（0.92 直寫 / 0.70-0.92 review / < 0.70 丟）這第三道防線才能達成。

### 2.3 Phase B v1 整合

主 Claude 整合 10 份 draft，列出：
- **共識**（10 人都同意）：三層 gating、Stop hook 主萃取、走 V4 既有 chain、personal 預設、白名單 scope
- **衝突**（多派對立）：Precision 0.92 現實嗎 / token 200 tok 撐得住嗎 / hook 選擇 / stance 處理 / 盲測協議
- **盲區**（沒人提到我補）：既有 transcript 不回填、conflict-detector 接口、SVN 環境、敏感類別自動 pending

v1 寫入 `plans/purring-percolating-glacier.md`。

### 2.4 Phase C 視角調換 validation

同 8 大師用**最衝突的對立視角**檢查 v1（非傳統的「原視角再驗一次」）：

| 原視角 → 扮演視角 | 挖出的盲點 |
|---|---|
| 人文 → 精省 token | 婉轉語跨 turn token 翻倍 / state 膨脹 parse 稅 |
| UX → 程式 | Haiku 零實作基礎（無 SDK）/ regression fixture 不存在 |
| 程式 → AI | L1 conf 不可靠（小模型 ECE 0.15-0.25）/ cache 中文命中假設 |
| AI → 原子記憶 | Source-turn-id 進 metadata 破 SPEC = V4.2 breaking |
| 原子記憶 → UX | 首次發現延遲 → 信任崩盤 / 婉轉確認 = 偷記最差 UX |
| 實作 → 語意 | N=1/200 字切斷 stance / 歷史不回填首日雞肋 |
| 精省 → 人文 | 混合句無演算法 / personal 隱私外洩路徑 |
| 語意 → 實作 | 7d → 12-14d 低估 / extract-worker 仿坑 |

**驗收結果**：8/8 iterate，0 ship，0 reject → 方向對但多漏洞需補。

### 2.5 Phase D v2 裁決

合併 28 條 validation fix (F1-F28) 進 v2。關鍵調整：

- **F1/F2**：Source-turn-id 改 footer comment + server.js 零修改 → 維持 V4.1 minor 定位
- **F3/F4**：L2 保留 gemma4:e4b（原規劃 Claude Haiku，避免新外部依賴）+ L1 改二元 yes/no（避免不可靠 conf routing）
- **F5**：婉轉語改「明說 + 預設同意」（非靜默偷記）
- **F7**：砍 `/memory-explain`（peek 顯示 trigger 原因即可）
- **F22**：token 預算修正 200 → 240（含 session budget tracker overhead）

v2 approved → 動工。

---

## 3. 平行化實驗

### 3.1 三線並行開工（Session A/B/C）

V4.1 原始 phase 定義為線性 dependency（P1 → P2 → P3 → P4），但盤點後發現：

- **V4 收尾**（漸進遷移 + init-roles + CONTRADICT 模擬）操作的是**各專案 `.claude/`**（如 `c:\tmp\docs-progg`）
- **V4.1 P1**（L0 detector）碰 `hooks/wg_user_extract.py` + `settings.json` + `workflow-guardian.py`
- **V4.1 P2 前置**（prompts + lib refactor）碰 `prompts/` + `lib/ollama_extract_core.py` + `extract-worker.py`

三者**零檔案重疊**。於是設計三份 handoff 到 `memory/_staging/` 讓使用者並行開 3 個 session 跑。

### 3.2 結果

三線同日完成，git 無衝突：
- Session A (V4 收尾) → `c:\tmp\docs-progg` V4 啟用成功
- Session B (V4.1 P1) → tag `v4.1.0-alpha1`（81 pytest cases pass）
- Session C (V4.1 P2 前置) → lib refactor + prompts 產出

**經驗**：「phase dependency」未必等於「session dependency」。只要檔案邊界清、api 介面先定義（例如 P1 的 `pending_user_extract[]` schema），就能拆出平行 session。

---

## 4. P2 整合 → P3 → P4（線性）

這段必須單線（有 hard dependency）：

| Session | Tag | 關鍵交付 |
|---|---|---|
| D | `v4.1.0-beta1` | `user-extract-worker.py` + Stop spawn + 整合測 framework |
| E | `v4.1.0-rc1` | `/memory-peek` + `/memory-undo` + 每日推送 + 隱私體檢 |
| F | `v4.1.0-rc2` | session evaluator (5 維度加權) + agent 多 role 模擬（sgi 專案） |

### 4.1 Session F 的 scope 擴大

原 plan v2 §6 P4 = 「歷史回填 + 試用 + 驗收」。使用者在 P4 拍板階段丟了兩個創新選項：

- **Q2 (d)**：用 Agent 扮演 programmer + planner 雙 role 試用（取代真人盲測）— sgi 專案已有程式碼 + 企劃規格文件，agent 可基於真實內容模擬
- **Q3 (d)**：先做 **Session 重點評價機制** 再決定回填範圍

Q3(d) 是意外好設計 — 原本只是「跑個試用 + 抽樣 P/R」，現在多了**可量化的 session 價值**作為：
1. 未來回填決策依據（score ≥ threshold 才回填）
2. Wisdom Engine meta-learning 基石

5 維度加權評分：
- density (0.15) — 萃取密度
- precision proxy (0.35) — L2 平均 conf
- novelty (0.20) — 新 atom / (新 + dedup)
- cost efficiency (0.15) — 1 - token/240
- trust (0.15) — 1 - reject/written

P4 dev day 從原估 1d 放大到 2.5d，值得。

---

## 5. rc2 → GA 的三層根因（關鍵教訓）

### 5.1 症狀

Session F 報 GA blocker：整合測 `TestPrecisionRecall` aggregate `P=1.00 R=0.00`。Session F 當時推測是「rdchat 後端 HTTP 404/400 + gemma4:e4b 未安裝本地 Ollama」。

### 5.2 主 Claude 診斷（本 session 做）

快速排除外部因素：
1. `curl http://192.168.199.130:11434/api/tags` → 200 + 25 models 列表
2. Model list 含 `gemma4:e4b`（非 Session F 以為的「未安裝」）
3. `ollama_client.get_client()._pick_backend('llm')` → 正確選 rdchat-direct
4. smoke test：client.generate("say hi", model="gemma4:e4b") → 3.4s 回 "Hello, how are you?"
5. L2 prompt + gemma4:e4b → 3.4s 回 valid JSON {conf: 0.92}
6. L0 detector 直測 16/16 正例 signal=True

→ rdchat / gemma4 / L0 全 OK。但整合測 2.86s 跑完 40 cases = **pipeline 在 L1 或 L2 早期 silent return None**。

### 5.3 Session G 修復的三層根因

下游 session G 按主 Claude 給的具體起點（跳過重驗 ollama/gemma4/L0，打 `_call_l1/_call_l2/_load_prompt`）診斷出**三層根因**：

1. **L1 prompt 載入 regex bug**：parse few-shot 邊界的 regex 吞掉實際用戶 prompt 欄位，L1 拿到空 prompt → ollama 回空 → early return
2. **ollama_client.generate() `explicit_model` 參數未被替換到 payload**：傳 `model="gemma4:e4b"` 但實際送出的 payload 仍用 backend default
3. **`_call_l1` 無 fallback 機制**：L1 invalid JSON 直接 return None，不 retry 也不降級，導致短暫性錯誤 = 永久失敗

修復後整合測 **P=1.000 / R=0.480** 過紅線（target P≥0.92, R≥0.30）。

### 5.4 教訓

這個 blocker 暴露三個系統性問題：

1. **Session 間 handoff 的診斷精度**：Session F 沒做 smoke test 就下結論「rdchat down」— 主 Claude 花 5 分鐘排除就知道是 pipeline 內部問題。**handoff 應該要求下游先做 minimal reproducer 而不是跳到結論**。
2. **Silent fail + early return 是最難 debug 的 pattern**：`_call_l1/_call_l2` 吞 exception 回 None 是「fail-open」哲學，但配合 test 框架跑 = `P=1 R=0` 看起來像 feature 而非 bug。**fail-open 必須配合 telemetry（log 吞掉的 exception），否則是 silent death**。
3. **Integration test 不能只看 aggregate**：若每個 case 都看得到 pipeline 各層結果（L0 signal / L1 result / L2 conf），`tp=0` 就會立刻暴露「L1 全 None」而不是卡在 aggregate 層。

---

## 6. 最終 GA 狀態

```
v4.1.0 GA
├─ commit 8cc851a — fix: L1/L2 silent-return GA blocker 清除
├─ 整合測 P=1.000 / R=0.480 ✓
├─ 回歸測 89 tests 全綠（baseline 刷新吸收 auto-memory metadata drift）
├─ userExtraction.enabled=true, mode=production
└─ tag push → gitlab.uj + github

V4.1 新增模組:
├─ hooks/wg_user_extract.py        # L0 規則 detector
├─ hooks/user-extract-worker.py    # Stop hook async worker
├─ hooks/wg_session_evaluator.py   # 5 維度加權評分
├─ lib/ollama_extract_core.py      # extract-worker 共用核心
├─ prompts/user-decision-l1.md     # L1 二元 yes/no
├─ prompts/user-decision-l2.md     # L2 結構化萃取
├─ commands/memory-peek.md         # UX
├─ commands/memory-undo.md         # UX
├─ commands/memory-session-score.md # UX
└─ tools/{memory-peek,memory-undo,memory-session-score,snapshot-v4-atoms}.py

V4.1 零修改（關鍵約束 — 維持 minor 定位）:
├─ _AIDocs/SPEC_ATOM_V4.md         # 零改
├─ tools/workflow-guardian-mcp/server.js  # 零改
├─ hooks/quick-extract.py          # 零改
└─ 所有 V4 atoms                   # SHA256 baseline 通過
```

---

## 7. V4.2 遺留（不做，只記錄）

Session F Sub-task B + Session G 修復過程累積的 V4.2 候選項在 `memory/_staging/v42-candidates.md`：

- L0 detector 對 5 類中文模式系統性漏抓：「習慣」/「只能」/「數值邊界」/「程序性」/「婉轉」
- L2 可升級 Claude Haiku 取代 gemma4:e4b（cache 友好 + 成本更低）
- 歷史 transcript 回填功能（按 session_score 篩選）
- team 真人試用（alice/bob 加入）
- Wisdom Engine 整合 session_score 做 meta-learning（V5 方向）

---

## 8. 關鍵數字

| 指標 | 值 |
|---|---|
| 開發時長 | 1.5 天（2026-04-15 晚 → 2026-04-16 晚） |
| Session 數 | 7（1 圓桌規劃 + 3 平行實作 + 3 線性收尾） |
| Agent 召集 | 10 drafting + 8 validation = **18 個視角** |
| commits (V4.1 專屬) | 8 |
| tags | 5 (alpha1, beta1, rc1, rc2, GA) |
| 新增檔 | 14 |
| 修改檔（不動 V4 核心） | 6 |
| pytest cases | 89 全綠 |
| Integration test P/R | 1.000 / 0.480 |
| Token NFR | amortized ≤ 240/session ✓ |
| V4 atoms SHA256 不變 | ✓ |

---

## 9. 圓桌方法論的啟示（給未來 V5+ 設計用）

這次 V4.1 的圓桌方法論**可複製**到未來「邊界不清、多重 NFR 取捨、一個人扛不動廣度」的任務：

1. **並行 drafting 前不給框架** — 10 大師各自獨立提案才會撞出設計空間；若事先擬好框架讓大家填，= 8 份大同小異的廢話
2. **資訊整合大師跑 web search 是防過度幻想的防線** — 小模型做 intent 宣稱 P 0.92 在 prior art 根本沒先例，沒人查就會定不合理紅線
3. **視角調換 validation 比「原視角再驗」有效 10 倍** — 讓人文大師扮精省 token、程式大師扮 AI，才會挖到每層盲區
4. **plan mode 的限制（只能改 plan 檔）配合暫存區（memory/_staging/）是好配對** — 正式檔不動、diff 看得清楚
5. **handoff prompt 是 session 間協作的關鍵介面** — 寫不好 = 下游重新發明輪子；寫得好 = 下游 1 hour 清掉 blocker（Session G 是活例子）

這個方法論本身值得單獨留檔供後續專案參考。
