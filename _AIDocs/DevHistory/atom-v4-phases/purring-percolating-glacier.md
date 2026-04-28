# V4.1 Plan v2 — 主動萃取使用者決策原子化

> **狀態**：Phase D 整合產出（v2，已收 Phase C 8 份 validation）。等使用者 approve → ExitPlanMode → 動工。
> **方法論**：8 大師圓桌（人文/UX/程式/AI/原子記憶/實作/精省 token/語意）× drafting + validation 雙 round + 2 資訊整合大師（Prior Art / NLP Benchmark）。
> **Phase A 10 份 + Phase C 8 份 verdict 統計**：8/8 `iterate`、0 `ship`、0 `reject` — 共識「方向對、多漏洞需補」。
> **命名**：原 V5，使用者拍板 V4.1（minor）— 流程不變、深度不變、僅命名修正。

---

## 1. Context（為什麼有這次）

V4 (commit dc81d50, 2026-04-16) 把多人共享記憶的「分流 + 防護網」做完了 — `personal/shared/role` 三層 scope、三時段衝突偵測、管理職雙向認證、JIT 角色 filter 全部到位。

但實況：萃取流水線（[hooks/quick-extract.py](hooks/quick-extract.py) + [hooks/extract-worker.py](hooks/extract-worker.py:108)）只讀 transcript JSONL 的 `type=="assistant"` blocks。**對「使用者」輸入幾乎沒分析**。對話中真正的金礦 — 使用者的決策、偏好、反饋、設計選擇、規範拍板 — 常被當上下文丟掉，沒沉澱進 atom。`knowledge_queue` 也沒自動 flush，靠下個 session Claude 看到才有可能寫成 atom。

結果：alice/bob 各自的 role 隔間蓋好了，**但隔間裡是空的**，V4 角色 filter 變成「過濾空集合」，使用者體感 = V4 雞肋。

V4.1 把 V4 從「基礎設施」升級成「真正會替使用者長記憶的系統」。

---

## 2. 三大不可妥協 NFR

| # | NFR | 驗證方式 |
|---|---|---|
| 1 | **不雞肋** — 系統能在合適時機 recall 使用者過去拍板的事 | (a) 誘餌 5 題命中 ≥ 3 (b) 使用者具體回報 ≥ 2 case (c) **歷史回填一輪**確保試用首日就有「啊它記得」 |
| 2 | **絕對精準** — 寧漏不錯 | 抽 100 條人工標 P/R，**Precision ≥ 0.92** + **Recall ≥ 0.30** 雙紅線 |
| 3 | **低耗 token** — 每 session 增量 ≤ 200 tokens（amortized） | baseline V4 vs V4.1 同 50 task 對比實驗 + session budget tracker 強制執行 |

任何違反三條的設計 → reject。

---

## 3. v1 → v2 變更摘要（Phase C 修正合併）

| # | v1 設計 | v2 修正 | 來源 validation |
|---|---|---|---|
| F1 | 新增 atom metadata 欄 `Source-turn-id` | **改 footer comment** `<!-- src: {sid}-{turn_n} -->`，三 audit 工具無感知；零 SPEC 修改 | V-原子記憶 / V-實作 |
| F2 | server.js 修改 ~20 行接受新 metadata | **零修改 server.js**：metadata 走既有 `description` / 自由欄；MCP 不需重啟 | V-實作 / V-程式 |
| F3 | L2 換 Claude Haiku（cache 友好假設） | **保留 gemma4:e4b**（已有 ollama 通道、零新外部依賴、零 API key 管理）；Haiku 列為 v4.1.1 升級項 | V-AI / V-程式 / V-精省 |
| F4 | L1 用 self-reported conf ≥ 0.7 routing | **L1 只輸 yes/no 二元**，全 yes 送 L2，**routing 唯一信號 = L2 conf** | V-AI |
| F5 | 婉轉語雙重確認靜默背景 commit | **明說 + 預設同意**：當 turn systemMessage「↑這段我打算記為 atom: 『…』，下輪回『否』可攔截」 | V-UX / V-人文 |
| F6 | 7 dev day | **8.5 dev day**（含補洞 + 平行壓縮） | V-實作 |
| F7 | `/memory-explain` 1.5d | **砍 explain，移投 peek 顯示 trigger 原因** | V-UX / V-實作 |
| F8 | 不回填歷史 transcript | **P4 前跑單次 conf ≥ 0.92 高精準歷史回填**（filter 嚴 = precision 不掉） | V-語意 |
| F9 | Stance detection 走純雙重確認 | **保留輕量 stance**：N=1 取 assistant **last 600 chars**（非前 200 字）+「方案 + 短回應 +0.3 boost」 | V-語意 |
| F10 | 混合句（情緒+決策）無解 | **interactive confirm**：偵測情緒詞 ∧ 決策訊號共存 → 強制使用者拆分，禁自動入庫任一側 | V-人文 |
| F11 | state-{sid}.json sibling merge 未定義 | **GC 滑窗**：`pending_user_extract[]` 保留最近 10 個 turn-id，sibling merge 走 `append + dedup(turn_id)` | V-精省 / V-程式 |
| F12 | knowledge_queue cleared 但 atom 沒寫（既存 silent loss） | **ack-then-clear**：worker 原子寫入成功 → pop pending；一次修兩支 worker（順帶修 [server.js:558,617,2845](tools/workflow-guardian-mcp/server.js#L558) 既存 bug） | V-程式 |
| F13 | regression fixture 不存在（空話） | **P1 末加 `tools/snapshot-v4-atoms.py`** 產 `tests/fixtures/v4_atoms_baseline.jsonl` | V-程式 / V-實作 |
| F14 | Confidence 永凍 [臨] | **JIT 注入後使用者未否決 N=4 次自動升 [觀]**（不靠 user 主動引用） | V-原子記憶 |
| F15 | Related 雙向自動連結 → 改 V4 既有 atom | **單向寫入**（新 → 舊），反向由 atom-health-check 離線批次補 | V-原子記憶 |
| F16 | Dedup embedding 0.88 對否定詞失效 | **加否定詞偵測**（不/禁/別/勿/停）→ 否定性不同強制新 atom；短句門檻提至 **0.92** | V-原子記憶 |
| F17 | 自動 atom 混入 personal/{user}/ 手寫 | **物理隔離 personal/auto/{user}/ 子目錄** | V-原子記憶 |
| F18 | 首次發現延遲 → 信任崩盤 | **每日首個 SessionStart 注入 systemMessage**「昨日新增 N 條 atom（M shared / K personal），/memory-peek」(N=0 靜默) | V-UX |
| F19 | 誘餌 Claude 自主埋（倫理） | **明知協議 + 干擾題**；自主埋方案否決 | V-UX / V-人文 |
| F20 | reject 摩擦力 ≤ 1 指令 | 加 **`/memory-undo --since=<time>`、`--all-from-today`** 批撤 | V-人文 |
| F21 | personal/ 隱私邊界（雲端同步路徑） | **`/init-roles` 加隱私體檢**：掃 Dropbox/iCloud/OneDrive/SVN/LSP cache；情緒類**即使 scope=personal 仍硬性不寫磁碟** | V-人文 |
| F22 | session budget tracker overhead 未算 | **tracker 自身 ~60 tok/session 算入 NFR**，預算分母改用 240 tok 鬆綁 | V-精省 |
| F23 | `/memory-undo` reject reason 無分類 | **強制分類**（情緒誤抓/含蓄誤判/隱私越界/scope 錯）寫回 reflection_metrics | V-人文 |
| F24 | 情緒+「絕不/再也不/一律」誤抓 | **24h 冷卻 + 二次確認**：標 `emotional_commitment=true` 暫存，24h 後問使用者 | V-人文 |
| F25 | mega decisions.md 風險 | **3-4 粗桶**：preferences / tools / workflow / architecture（不做完整 taxonomy） | V-語意 |
| F26 | flag=off 時 pending drain 未定義 | **drain 語義**：flag 切 off → SessionEnd 跑一次完整 worker 清空 pending，之後純 skip | V-程式 |
| F27 | L0 純規則 keyword 漏中文功能詞 | **加句法 pattern**：`[我/我們] + [情態詞] + V + O`、`[都/一律/固定] + V`、否定 `[不/禁/別] + V`，補 keyword 漏判 | V-語意 |
| F28 | 中信號詞 30% 走 L1 → token 表低估 | **token 表重算**（見 §8）：中信號詞流量 30% 後 amortized = 240 tok，需 budget tracker 緊管 | V-語意 / V-精省 |

---

## 4. 共識（10 大師都同意，不變）

- 三層 gating：L0 規則 → L1 qwen3:1.7b 二元篩 → L2 gemma4:e4b 結構化萃取（僅 L1 yes 流量）
- Stop hook async detached 為主萃取點；UserPromptSubmit 純規則 ≤ 5ms 標記
- 走既有 atom_write MCP + write-gate + conflict-detector，**絕不繞**
- 預設 scope=personal；author=auto-extracted-v4.1 統一標記
- feature flag `userExtraction.enabled: false` 預設關
- 白名單 scope（情緒/身體/人際永不入庫）
- **不做** SVN post-update hook、dashboard、盲測自動化、multi-model ensemble、promotion auto-tuning、UI feedback、即時提示

---

## 5. v2 架構

```
┌─ UserPromptSubmit (sync, ≤5ms) ────────────────────────────────┐
│  hooks/wg_user_extract.py                                       │
│   ├─ L0 規則 (信號詞 + 句法 pattern + 排除)                    │
│   │     [F27] 句法 pattern: [我/我們]+情態+V+O / [都|一律]+V    │
│   ├─ score ≥ 0.4 → append state-{sid}.json/pending_user_extract│
│   │     [F11] GC 滑窗 cap 10 turn-id                            │
│   └─ score < 0.4 → 丟棄                                         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─ Stop hook async detached (30s budget) ────────────────────────┐
│  hooks/user-extract-worker.py                                   │
│  (重構 lib/ollama_extract_core.py 與 extract-worker.py 共用)    │
│   ├─ session budget tracker (≤240 tok 強制 L1-only)            │
│   ├─ 混合句偵測 [F10] → 情緒詞 ∧ 決策訊號 → systemMessage       │
│   │   "↑此句含情緒+決策，請拆分後重述" → skip 該 turn          │
│   ├─ L1: qwen3:1.7b 二元 yes/no [F4]                           │
│   │     think=false, T=0, num_predict=20, timeout=10s          │
│   ├─ L1=yes → 全送 L2                                           │
│   ├─ L2: gemma4:e4b 結構化萃取 [F3]                            │
│   │     {decision, conf, scope, audience, trigger, statement}  │
│   │     few-shot 含時間副詞、婉轉語、混合句邊緣例                │
│   │     N=1 取當 turn assistant last 600 chars [F9]            │
│   ├─ Hybrid threshold (用 L2 conf):                            │
│   │   conf ≥ 0.92 → 顯式提示 + 預設同意 [F5]                    │
│   │     當 turn systemMessage "↑這段我打算記為 atom"            │
│   │     下 turn 使用者無「否」 → ack-then-clear [F12] → 寫入   │
│   │   0.70-0.92 → 寫 personal/auto/{user}/_pending.candidates  │
│   │   < 0.70 → 丟棄                                             │
│   ├─ 情緒承諾偵測 [F24]：「絕不/再也不/一律」+ 情緒詞           │
│   │   → emotional_commitment=true，24h 冷卻後問                │
│   └─ append _merge_history.log: action=auto-extract-v41         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─ V4 既有 chain（不修改） ───────────────────────────────────────┐
│  MCP atom_write [F2 零 server.js 修改]                          │
│   ├─ metadata: scope=personal, author=auto-extracted-v4.1       │
│   │            footer: <!-- src: {sid}-{turn_n} --> [F1]        │
│   ├─ trigger: L2 抽 noun/verb 3-5 個                            │
│   ├─ Related: 單向 vector top-3 ≥ 0.65 [F15]                   │
│   ├─ dedup: word-overlap 0.80 → 短句 fallback embedding ≥ 0.92 │
│   │         + 否定詞極性檢查 [F16]                              │
│   └─ atom 落 personal/auto/{user}/{slug}.md [F17]              │
│      或（罕見）_pending_review/{slug}.md（雙條件 audience=decision）│
└─────────────────────────────────────────────────────────────────┘
```

### 新增檔案（8 個 - 砍 explain）

| 檔案 | 用途 |
|---|---|
| [hooks/wg_user_extract.py](hooks/wg_user_extract.py) | L0 純規則 detector |
| [hooks/user-extract-worker.py](hooks/user-extract-worker.py) | Stop hook detached worker |
| [lib/ollama_extract_core.py](lib/ollama_extract_core.py) | 與 extract-worker.py 共用核心（refactor 抽出） |
| [prompts/user-decision-l1.md](prompts/user-decision-l1.md) + [l2.md](prompts/user-decision-l2.md) | 兩層 prompt（few-shot ≥ 5 含邊緣例） |
| [tools/cleanup-extracted.py](tools/cleanup-extracted.py) | bulk rollback CLI |
| [tools/snapshot-v4-atoms.py](tools/snapshot-v4-atoms.py) [F13] | 跑全量 V4 atoms snapshot 產 baseline fixture |
| [commands/memory-peek.md](commands/memory-peek.md) + [tools/memory-peek.py](tools/memory-peek.py) | 列最近 24h 寫入 + pending + **trigger 原因** [F7] |
| [commands/memory-undo.md](commands/memory-undo.md) + [tools/memory-undo.py](tools/memory-undo.py) | reject + `--since=<time>` + `--all-from-today` [F20] + reason 分類 [F23] |
| [tests/fixtures/v4_atoms_baseline.jsonl](tests/fixtures/v4_atoms_baseline.jsonl) | F13 產出 |
| [tests/test_user_detector.py](tests/test_user_detector.py) + [tests/integration/test_e2e_user_extract.py](tests/integration/test_e2e_user_extract.py) + [tests/regression/test_v4_atoms_unchanged.py](tests/regression/test_v4_atoms_unchanged.py) | pytest |

### 修改檔案（4 個，~95 行 — 比 v1 砍掉 server.js + SPEC）

| 檔案 | 變動 | diff |
|---|---|---|
| [settings.json](settings.json) | 新增 `userExtraction` 區塊 | ~15 行 |
| [hooks/workflow-guardian.py](hooks/workflow-guardian.py) | UserPromptSubmit dispatcher + SessionStart 每日推送 [F18] + drain 語義 [F26] | ~50 行 |
| [hooks/extract-worker.py](hooks/extract-worker.py) | refactor 抽 lib/ollama_extract_core.py | ~80 行（淨增 ~10） |
| [_AIDocs/Architecture.md](_AIDocs/Architecture.md) | 新增「V4.1 使用者決策萃取流程圖」段 | ~50 行 |

**絕不修改**：[tools/workflow-guardian-mcp/server.js](tools/workflow-guardian-mcp/server.js) [F2]、[_AIDocs/SPEC_ATOM_V4.md](_AIDocs/SPEC_ATOM_V4.md) [F1]、[hooks/quick-extract.py](hooks/quick-extract.py)、[tools/memory-write-gate.py](tools/memory-write-gate.py)、[tools/memory-conflict-detector.py](tools/memory-conflict-detector.py)、所有 V4 atoms。

---

## 6. v2 Phase 拆分

| Phase | Deliverable | 可驗證標準 | git tag | dev day |
|---|---|---|---|---|
| **P1 — L0 detector + flag + V4 baseline fixture** | `wg_user_extract.py` + flag + UserPromptSubmit gate + `snapshot-v4-atoms.py` 跑出 baseline | flag=false zero overhead；50 條 → L0 P ≥ 0.95/R ≥ 0.55；UserPromptSubmit p95 +≤ 15ms；baseline fixture 入 git | `v4.1.0-alpha1` | **2.5** |
| **P2 — Worker + L1+L2 + atom_write 整合**（與 P1 部分平行） | `lib/ollama_extract_core.py` refactor + `user-extract-worker.py` + 兩 prompt + ack-then-clear + drain 語義 | 50 條整合測 P ≥ 0.92 / R ≥ 0.30；token p50 ≤ 240（含 tracker）；regression test V4 atoms SHA256 不變；ack-clear 修舊 silent loss | `v4.1.0-beta1` | **3.5** |
| **P3 — UX commands + 每日推送 + 隱私體檢** | `memory-peek` (含 trigger 原因)、`memory-undo` (`--since`/`--all-from-today` + reason 分類)、SessionStart 推送、`/init-roles` 加隱私體檢 | reject 摩擦力 ≤ 2 enter；隱私體檢標記 ≥ 1 雲端路徑 → warn；reflection_metrics 寫回 schema 定義 | `v4.1.0-rc1` | **1.5** |
| **P4 — 歷史回填 + 試用 + 驗收 + 正式發布** | conf ≥ 0.92 高精準歷史回填一輪 → holylight + 1 中性使用者 5-7 天試用 → 100 條抽樣 P/R + 誘餌題明知協議 | 抽樣 P ≥ 0.92 / R ≥ 0.30；token NFR；誘餌 ≥ 3/5 命中；具體 case ≥ 2 | `v4.1.0` | **1 + 1 週試用** |

**Total dev day：~8.5 day**（v1 估 7d 經 V-實作驗證為嚴重低估，v2 修正 8.5d 含補洞 + P1/P2 部分平行）。超 11d = scope 爆，砍功能不延期。

---

## 7. v2 Risk Top 5

| # | Risk | 緩解 |
|---|---|---|
| 1 | **Precision 達不到 0.92**（資訊整合 #2 量化警告：短中文 subjective class 公開無 ≥ 0.85 數據） | (a) 三層 gating + ack-then-clear (b) Hybrid threshold + 顯式提示 + 預設同意 [F5] = 第三道防線（使用者 turn 內可攔） (c) 達不到則回 P1 改 schema/prompt，重跑 50 條 |
| 2 | **token 240 tok 仍緊** | session budget tracker 強制 L1-only 降級；emotional_commitment 冷卻機制延後 24h 攤銷 cost；混合句強制 interactive confirm 不跑 LLM |
| 3 | **Agency 反噬 + 隱私洩漏**（雲端同步、情緒承諾誤抓） | 白名單 scope 硬規則 + `/init-roles` 隱私體檢 [F21] + 情緒類 not write to disk + 24h 冷卻 [F24] + 顯式提示+預設同意 [F5] |
| 4 | **首日不雞肋**（試用首日「不記得任何過去」直接 NFR#1 失敗） | P4 前跑歷史回填 conf ≥ 0.92 [F8]（filter 嚴 = precision 不掉）+ SessionStart 每日推送 [F18] |
| 5 | **誤殺 V4 行為** | server.js 零修改 [F2] + Source-turn-id 走 footer [F1] + Related 單向 [F15] + regression test V4 baseline [F13] + 物理隔離 personal/auto/ [F17] |

---

## 8. v2 Token 預算表（amortized per session, 30 prompts, 中信號詞 30% 流量）

| 來源 | tok |
|---|---|
| L0 規則 detector | 0 |
| L1 qwen3:1.7b（30% prompts × 12 tok yes/no）+ prompt cache | ~70 |
| L2 gemma4:e4b（L1 yes 流量 ~10% × 180 tok）+ prompt cache 50% 命中 | ~95 |
| 混合句 interactive confirm（< 5%）systemMessage | ~10 |
| 顯式提示 + 預設同意（conf ≥ 0.92 命中）systemMessage [F5] | ~20 |
| atom metadata + footer src tag | ~20 |
| **session budget tracker overhead [F22]** | ~25 |
| **合計（amortized）** | **~240 tok** ⚠ |

**裁決**：v2 預算 **240 tok 上限**（v1 200 tok 經 V-精省驗證為樂觀）。tracker 超 220 強制 L1-only，超 240 完全 skip 後續萃取。

---

## 9. 能砍清單（V4.1 不做）

1. ❌ `/memory-explain`（投入 1.5d 改投 peek 顯示 trigger 原因 [F7]）
2. ❌ Pending review 7 天自動降級邏輯（簡化「人工 review 永遠 pending 直到 `/memory-promote`」）
3. ❌ Source-turn-id 進 metadata（改 footer comment [F1]）
4. ❌ server.js 修改（metadata 走既有 description / 自由欄 [F2]）
5. ❌ Claude Haiku 整合（v4.1.1 升級項 [F3]）
6. ❌ Decision taxonomy 完整分類學（v2 改 3-4 粗桶 [F25]）
7. ❌ 盲測自動化框架（手工 100 條抽樣）
8. ❌ Dashboard / SVN hook / multi-model / promotion auto-tuning / UI feedback
9. ❌ Stance detection 全自動 LLM（v2 走輕量規則 boost [F9]）
10. ❌ Confidence 升級靠 user 主動引用（改 JIT 注入未否決 N=4 升 [觀] [F14]）

---

## 10. 開放議題（請使用者拍板）

- **Q1**：L2 模型確定走 **gemma4:e4b（v2 預設）** vs Claude Haiku（v4.1.1 升級）？v2 已選前者（零新依賴），請確認。
- **Q2**：第二位「中性使用者」哪裡來？團隊內 alice/bob 適合？或先單人試用接受盲測效度受限？
- **Q3**：歷史回填 [F8] 的 transcript 範圍 — 全部歷史 session vs 最近 30 天？前者 cost 高、precision 對遠古 transcript 不穩；後者首日體感較弱。

---

## 11. 驗證（如何測 V4.1）

```bash
# Phase 1
pytest tests/test_user_detector.py              # 50 條 P ≥ 0.95 / R ≥ 0.55
pytest tests/test_v41_disabled.py               # flag=false zero overhead
python tools/snapshot-v4-atoms.py               # 產 baseline fixture

# Phase 2
pytest tests/integration/test_e2e_user_extract.py --ollama-live  # 50 條 P ≥ 0.92 / R ≥ 0.30
pytest tests/regression/test_v4_atoms_unchanged.py               # SHA256 diff vs baseline
python tools/v41_token_budget_audit.py --sessions 30             # amortized ≤ 240

# Phase 3
/memory-peek                          # 列最近 24h + trigger 原因
/memory-undo --since=24h              # 批撤
python tools/init-privacy-check.py    # 掃 Dropbox/iCloud/OneDrive

# Phase 4 (歷史回填 + 試用)
python tools/v41_backfill.py --conf-min=0.92 --dry-run
python tools/v41_backfill.py --conf-min=0.92 --apply
# → 1 週試用 → /memory-undo reasons audit
python tools/v41_audit.py --sample 100 --label-csv labels.csv
# 報告：Precision / Recall / amortized token / 誘餌命中率
```

**驗收紅線**（任一不過 → 回對應 Phase）：
- Precision ≥ 0.92
- Recall ≥ 0.30
- token amortized ≤ 240/session
- V4 既有 atoms snapshot SHA256 不變
- 誘餌 ≥ 3/5 + 具體 case ≥ 2

---

## 12. 圓桌過程留檔

> Plan Mode 限制下無法寫 [_AIDocs/V4.1-design-roundtable.md](_AIDocs/V4.1-design-roundtable.md)，approve 後動工首步補。內容含：
> - Phase A 10 份 drafting（人文/UX/程式/AI/原子記憶/實作/精省 token/語意 + 2 資訊整合）
> - Phase B v1 plan
> - Phase C 8 份 validation（視角調換）
> - Phase D v2 整合裁決（本檔）

---

> v2 結束。等使用者 approve → ExitPlanMode → 動工。
