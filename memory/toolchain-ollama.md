# Ollama Dual-Backend 實戰記憶

- Scope: global
- Confidence: [固]
- Trigger: ollama, dual-backend, rdchat, qwen3, embedding, 萃取品質, thinking, failover, Open WebUI
- Last-used: 2026-03-23
- Created: 2026-03-19
- Confirmations: 59
- Type: procedural
- Tags: ollama, dual-backend, extraction
- Related: toolchain, decisions-architecture

## 知識

### Dual-Backend 機制

- [觀] ollama_client.py: singleton pattern，generate()/chat()/embed() 三個 API，自動 primary→fallback
- [觀] generate() 支援 think 參數（預設 False）。chat() 固定 think:false（reranker/conflict-detector 用短 prompt，不需 thinking）
- [觀] failover 時 model 名稱要跟著切換（rdchat 用 qwen3.5:latest，local 用 qwen3:1.7b），否則 fallback backend 回 404
- [觀] 三階段退避：連續 2 次失敗→短DIE(60s)→10 分鐘內 2 次短DIE→長DIE(等 6h 邊界 00/06/12/18)
- [觀] config 中 password_file 指向獨立檔案（.gitignore 排除），支援 os.getlogin() 多使用者

### Open WebUI Proxy

- [觀] Open WebUI proxy 不轉發 Ollama 原生 /api/embed — 改走 OpenAI-compatible /api/v1/embeddings（在根路徑，非 /ollama/ 下）
- [觀] Open WebUI /api/v1/embeddings 要求完整 model tag（如 `model:latest`），省略 tag 會 500
- [觀] LDAP 認證端點是 /api/v1/auths/ldap，payload 用 `user` 欄位（非 `email`）。token expires_at: null（永不過期）

### 萃取品質實測（2026-03-13）

A/B 對比：2 段真實 transcript（Redmine debug + NuGet build），各 4000 字送入萃取 prompt。

| 維度 | rdchat qwen3.5 (think=T, 8192) | local qwen3:1.7b (think=F, 2048) |
|------|------|------|
| JSON 格式 | OK | OK |
| 回應時間 | 38-43s | 6-13s |
| 萃取項目數 | 2-4 項（精簡） | 4-6 項（較多但淺） |
| 平均 content 長度 | 83-89 字 | 38-49 字 |
| type 多樣性 | factual+architectural+decision+procedural | 幾乎全 factual |
| 具體性 | 高（含路徑+數值+決策理由） | 中（偏短，缺細節） |
| 噪音 | 極低 | 低（偶有淺層重複） |

**關鍵發現**：
- [觀] qwen3.5 + think=false + 長 prompt → 秒回空 `[]`（退化），必須 think=true 才能正確萃取
- [觀] qwen3.5 thinking 約消耗 10K-13K 字元（~3K tokens），num_predict 需 ≥4096（設 8192 留餘量）
- [觀] qwen3:1.7b 不支援 think 參數（自動忽略），think=false 正常運作
- [觀] 結論：extract-worker 統一用 think=true + num_predict=8192，rdchat 品質高但慢，local 品質中但快，failover 機制不受影響

### 硬體限制

- [固] Local fallback（GTX 1050 Ti 4GB）同時只能跑一個模型，embedding 和推論需輪替；rdchat（RTX 3090）無此限制

## 行動

- debug Ollama/萃取品質時載入此 atom
- 修改 ollama_client.py 或 extract-worker.py 前先查此處參數
- failover 問題排查時確認 model name 是否跟著 backend 切換

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-19 | 從 toolchain.md 拆出 Ollama 區段 | atom-debug 精準化 |
| 2026-03-13 | 原始 A/B 實測數據 | ab-extract-test |
