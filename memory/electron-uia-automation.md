# Electron app UI 自動化三層障礙

- Scope: global
- Confidence: [臨]
- Trigger: Electron 自動化, VS Code 自動點擊, UIA Invoke, EVENT_E_NO_SUBSCRIBERS, PostMessage Chromium 失效, SendInput 偷塞字, AttachThreadInput, SetForegroundWindow 失敗, focus swap, ghost button, Claude Code 彈窗, GUI 工具, exe 打包
- Last-used: 2026-04-29
- Confirmations: 0
- ReadHits: 0

## 印象

- VS Code (Electron) UI 自動化遇到的 3 層 root cause（依序撞牆）：
  1. UIA `Button.Invoke()` 拋 `EVENT_E_NO_SUBSCRIBERS` (HRESULT 0x80040201) — Electron 沒把 React click handler 訂閱到 UIA event
  2. PostMessage WM_KEYDOWN 在背景失效 — Chromium throttle 非 active 視窗的 keyboard event（拖出 floating window 也不解決，Chromium input router 看的是「focused」不是「OS-level top window」）
  3. SetForegroundWindow 在使用者活躍打字時失敗 — Win11 嚴格限制；API 回 True 但實際沒切前景，SendInput 會被當下 active app 吃掉（會偷塞「1」進別的編輯器）
- 工具實作：c:/Users/holylight/tools/vscode-yes-clicker/（含完整 root cause 紀錄與解決方案）

## 行動

- 寫類似 Electron app 自動化工具 → 預期撞此三層，直接套兩段降級：tier 1 PostMessage → tier 2 AttachThreadInput + SetForegroundWindow + SendInput + 還原前景
- 必須用 `GetLastInputInfo` 做 idle guard（< 1500ms 內有輸入跳過 fire）防偷塞字
- UIA tree 偵測 button 必須過濾 `IsOffscreen=True` + `BoundingRect 非零`，避免 React 卸載後 accessibility tree 殘留 ghost button 觸發誤 fire
- Worker thread 用 UIA 前先 `comtypes.CoInitialize()`；main thread 絕不碰 UIA（COM 競爭會凍結 GUI 5 秒）
- 完美無閃方案是 CDP（VS Code 啟動 `--remote-debugging-port=9222`），但要使用者改啟動方式 — 預設不採用，接受「閃 = 工具運作中」視覺回饋
