# Claude Code Hook System

- Scope: global
- Confidence: [固]
- Trigger: hook system, hooks.json, pre_tool_use, post_tool_use, session_start, session_end, hook event, hook 事件, lifecycle hook, 生命週期, hook 開發, permission_request, PromptRequest, hook timeout, updatedInput
- Last-used: 2026-04-01
- Confirmations: 1
- Related: cc-harness-overview, cc-tool-system, cc-permission-system, cc-skills-plugins

## 知識

### Hook 事件類型（14 種）
- [固] setup, session_start, session_end
- [固] pre_tool_use, post_tool_use
- [固] pre_compact, post_compact
- [固] permission_denied, stop_failure
- [固] subagent_start, subagent_stop
- [固] task_created, task_completed

### Hook 定義格式（.claude/hooks.json）
- [固] 條件觸發：`if: { tool: "BashTool", input_contains: "npm publish" }`
- [固] 執行：`run: "node scripts/check.js"`, `shell: "bash"`, `env: {...}`

### 執行架構
- [固] 三層序列：Harness 匹配 → 子程序執行（JSON over stdout/stdin）→ 結果聚合
- [固] executeHooks 是 async generator，逐步 yield 結果（不等全部完成）
- [固] 子程序完成由三路 Promise.race：childClosePromise / childErrorPromise / childIsAsyncPromise

### 環境變數注入
- [固] CLAUDE_TOOL_NAME, CLAUDE_TOOL_INPUT, TOOL_INPUT_FILE_PATH, TOOL_INPUT_COMMAND
- [固] CLAUDE_SESSION_ID, CLAUDE_PROJECT_DIR

### Hook 來源與優先級（5 層）
- [固] 使用者全域 → 專案 → Plugin hooks → Skill hooks → MDM/Managed

### Hook 修改工具輸入（updatedInput）
- [固] Hook 可回傳 updatedInput 改寫工具輸入（如 `--force` → `--force-with-lease`）
- [固] 透明度代價：Claude 不知道實際執行與其意圖的差異

### PromptRequest 協議（Hook 向使用者提問）
- [固] Hook 輸出 PromptRequest JSON → Claude Code 呈現選項 → 使用者選擇 → PromptResponse 寫回 stdin
- [固] 多個請求必須序列化（promptChain），無法並行

### permission_request Hook 特殊語義
- [固] 在權限決定過程中執行（與 InteractiveHandler / BashClassifier 競爭）
- [固] 原子性 claim() 機制：Hook claim 成功 → 使用者對話框被取消
- [固] 企業 MDM hook 可完全繞過人工審批

### 超時與錯誤隔離
- [固] TOOL_HOOK_EXECUTION_TIMEOUT_MS = 10 分鐘
- [固] Hook 崩潰/超時 → 結果被忽略，工具照常執行（建議性而非強制性）
- [固] Memoized Hook Loading：檔案變更驅動快取失效

### Hook 輸出能力差異（additionalContext 可用性）
- [固] PostToolUse 的 additionalContext 是**即時生效**的（同一 turn 內 Claude 可見，不需等下一輪）
- [固] Async hook 完成後 systemMessage 自動注入下一輪（additionalContext 同理，但 Stop 不適用）
- [固] Stop hook 不支援 additionalContext，只有 block + reason + systemMessage

## 行動

- 開發 hook 腳本：用 JSON stdout/stdin 協議，任何語言都可
- pre_tool_use 用於攔截/修改工具輸入；post_tool_use 用於觀察記錄
- permission_request 用於自動化權限決策（但需注意監督空間消失）
- 來源：https://claude-code-harness-blog.vercel.app/chapters/05-hook-system/
