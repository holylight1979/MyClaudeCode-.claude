# 架構技術細節

- Scope: global
- Confidence: [固]
- Trigger: 架構細節, vector service, ollama backend, extraction, ACT-R, episodic tracking, context budget
- Last-used: 2026-04-02
- Confirmations: 113
- Type: decision
- Tags: architecture, infrastructure
- Related: decisions, toolchain, toolchain-ollama, DESIGN, SPEC_impl_params

## 知識

### Hot Cache 機制
- [觀] hot_cache.json: session_id + timestamp + source + injected flag + knowledge[] + summary
- [觀] File lock: sidecar .lock + msvcrt.locking()（Win）/ fcntl.flock()（Unix），失敗時 best-effort
- [觀] 注入順序: quick_extract 5s → PostToolUse/UPS 讀取 → deep_extract 30s 覆寫
- [觀] wg_hot_cache.py API: write_hot_cache(data) / read_hot_cache(sid) / mark_injected(sid)

### Async Hook 行為
- [觀] Stop async hook: systemMessage 自動注入下一輪；不支援 additionalContext
- [觀] quick-extract.py: str.format() prompt 內的 JSON 範例需 {{ }} 跳脫
- [觀] PostToolUse additionalContext 即時生效（同一 turn 內 Claude 可見）

### SessionStart 去重
- [觀] _find_active_sibling_state(): 掃描同 cwd + phase=working + 60s 內 → 複用 state
- [觀] merged_into redirect: _ensure_state() 自動跟隨，後續 hook 透明使用目標 state
- [觀] vector_ready.flag: SessionStart 清除 → 背景 subprocess 寫入 → _semantic_search 檢查

### 檢索強化
- [固] Project-Aliases：MEMORY.md `> Project-Aliases:` 行，跨專案掃描

## 行動

- 開發/調修記憶系統時載入此 atom
- 修改 hook/tool 前確認此處記載的參數值
- 新增基礎設施時更新對應段落

