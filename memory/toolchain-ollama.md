# Ollama Dual-Backend 實戰記憶

- Scope: global
- Confidence: [固]
- Trigger: ollama, dual-backend, rdchat, qwen3, gemma4, embedding, 萃取品質, thinking, Open WebUI
- Last-used: 2026-04-16
- Created: 2026-03-19
- Confirmations: 0
- ReadHits: 87
- Type: procedural
- Tags: ollama, dual-backend, extraction
- Related: toolchain, decisions-architecture, decisions

## 知識

### Dual-Backend 機制

- [固] ollama_client.py: singleton pattern，generate()/chat()/embed() 三個 API，自動 primary→fallback
- [固] generate() 支援 think 參數（預設 False）。chat() 固定 think:false（reranker/conflict-detector 用短 prompt，不需 thinking）
- [固] failover 時 model 名稱要跟著切換（rdchat 用 gemma4:e4b，local 用 qwen3:1.7b），否則 fallback backend 回 404
- [固] 三階段退避：連續 2 次失敗→短DIE(60s)→10 分鐘內 2 次短DIE→長DIE(等 6h 邊界 00/06/12/18)
- [固] config 中 password_file 指向獨立檔案（.gitignore 排除），支援 os.getlogin() 多使用者

### Open WebUI Proxy

- [固] Open WebUI proxy 不轉發 Ollama 原生 /api/embed — 改走 OpenAI-compatible /api/v1/embeddings（在根路徑，非 /ollama/ 下）
- [固] Open WebUI /api/v1/embeddings 要求完整 model tag（如 `model:latest`），省略 tag 會 500
- [固] LDAP 認證端點是 /api/v1/auths/ldap，payload 用 `user` 欄位（非 `email`）。token expires_at: null（永不過期）

### 萃取品質結論（V3.4 — gemma4:e4b 取代 qwen3.5）
- [固] V3.4 起 rdchat LLM 改用 gemma4:e4b（三輪 A/B 測試驗證：100% 成功率、0 幻覺、速度快 3-15x）
- [固] gemma4:e4b think=true: 14s，100% grounded，平衡品質（deep extract 用）
- [固] gemma4:e4b think=false: 2.8s，temp=0.0 一致性 100%（高密度數據最強）
- [固] extract-worker 改用 think="auto" + temp=0.0（由 backend config 控制 think/num_predict）
- [固] qwen3:1.7b 不支援 think（自動忽略），think=false 正常運作（local fallback 維持）
- [固] Ollama 已知 bug: gemma4 think=false + format 參數 = JSON 輸出破壞 (ollama#15260)，本系統用 prompt instruction 不受影響
- → 舊 qwen3.5 數據：`_AIDocs/DevHistory/ab-test-ollama.md`
- → gemma4 完整數據：`_AIDocs/DevHistory/ab-test-gemma4.md`

### 硬體限制

- [固] Local fallback（GTX 1050 Ti 4GB）同時只能跑一個模型，embedding 和推論需輪替；rdchat（RTX 3090）無此限制

## 行動

- debug Ollama/萃取品質時載入此 atom
- 修改 ollama_client.py 或 extract-worker.py 前先查此處參數
- failover 問題排查時確認 model name 是否跟著 backend 切換

