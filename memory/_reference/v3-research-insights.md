# V3 跨領域研究洞見

- Scope: global
- Confidence: [觀]
- Type: reference
- Trigger: V3, 研究, 認知科學, 佛學, 唯識, ACT-R, spreading activation
- Last-used: 2026-03-11
- Created: 2026-03-11
- Confirmations: 0
- ReadHits: 1
- Tags: research, theory, v3-design
- Related: decisions, v3-design-spec

## 起源

使用者描述了自己聽到 "sgi" 時的認知流程（6 步），要求從數學/佛學/AI 三領域搜尋可用於改善記憶檢索的理論框架。

## 認知科學 — 可直接實作

### ACT-R 基礎激活（Anderson）
```
B_i = ln( Σ_{k=1}^{n} t_k^{-d} )    # d=0.5 (default)
```
- n = 存取次數, t_k = 距第 k 次的時間
- 頻率+近期效應：近期高頻 >> 遠期低頻
- 已決定用於 V3 取代 Confirmations 計數

### 擴散激活（Collins & Loftus）
```
A[j](t+1) = A[j](t) + Σ_i ( A[i](t) × W[i,j] × D )
```
- D = 衰減因子, 每跳遞減
- 啟發 V3 的 Related-edge spreading（depth=1, decay per hop）

### 顯著性評分
```
Salience = w_r×Recency + w_f×Frequency + w_e×EmotionalWeight + w_u×Urgency
```
- 留作未來參考，V3 先用 ACT-R B_i 即可涵蓋 recency + frequency

## 佛學（唯識學）— 設計啟發

### 三個落地的洞見

1. **薰習（vāsanā）→ 每次讀取即寫入**
   - 種子生現行、現行薰種子 = 讀寫不分離
   - 落地：access_log 自動記錄，觸發即強化

2. **受先於想 → 過濾先於辨識**
   - vedanā（價值判斷）在 saṃjñā（辨識）之前
   - 落地：domain relevance check 在 content analysis 之前

3. **末那識 → 承認偏差存在**
   - 末那識是扭曲者（我見、我癡、我慢、我愛），不是有用的過濾器
   - 落地：Blind-spot reporter（報告盲點，不假裝全知）

### 四緣（啟動條件，未落地但留作參考）

| 緣 | 含義 | 軟體對應 |
|----|------|---------|
| 因緣 | 種子本身存在且成熟 | atom 存在 + confidence ≥ threshold |
| 等無間緣 | 對話脈絡允許 | conversation topic coherence（V3 不做） |
| 所緣緣 | 查詢匹配 | semantic/keyword match |
| 增上緣 | 環境條件支持 | project scope, workspace context |

### 重要提醒
- 佛學是設計過程的透鏡，不是產品的一部分
- 用佛學思考，用工程語言寫碼和文件
- 唯識學描述「心」，不是軟體；比喻有延伸限度

## AI/CS — 實作工具箱

### 最值得參考的模式（按 effort/value 排序）

1. **HyDE**（假設文件嵌入）：LLM 生成理想答案 → 用它做 embedding search。~20 行。未來可用。
2. **Hybrid search**（BM25 + vector + rerank）：現有系統已部分實作。
3. **Multi-hop retrieval**（retrieve → expand → re-retrieve）：V3 Related spreading 是簡化版。
4. **MemGPT pattern**（LLM 管理自己的記憶層級）：現有系統已是此模式的手工版。
5. **GraphRAG**（知識圖譜 + 社群摘要）：工程量大，留待未來。

### Graphiti/Zep 的 hybrid scoring（參考）
```
Score = α×cos_sim + β×BM25 + γ×graph_proximity
```
- 三軸融合比任何單一方法都好
- 現有系統：keyword + vector 雙軸，V3 加 graph proximity（Related edges）= 三軸

## 未來方向

### 閱讀 Session 模式（V2.11+ 候選）

使用者需求：開專門的「閱讀 session」讓 AI 大量閱讀專案文件，產出結構化知識，長期保存供未來工具開發（如「綜合文件入口」網頁）。

現狀（V2.10）：
- Read Tracking 記錄閱讀路徑 → episodic atom（TTL 24d）
- extract-worker 用 qwen3:1.7b 萃取知識（品質有限）
- 需要 Claude 手動寫 semantic atom 才能長期保存深度摘要

可能的實作方向：
- 「閱讀模式」flag：session 結束時 Claude 自動把分析整理成 semantic atom（非 episodic）
- 閱讀完成時自動產出結構化索引（類似 `_AIDocs/_INDEX.md` 但覆蓋更廣）
- 可指定目標 atom：「這次閱讀的知識存到 doc-inventory atom」

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-11 | 建立，三領域研究完成 | session:V3 設計討論 |
| 2026-03-11 | +閱讀 Session 模式構想 | session:V2.10 討論 |
