---
name: misdiagnosis-verify-first
description: 大型/第三方專案診斷必須先 100% 驗證根因再規劃，不可靠假設展開計畫（LINE webhook 404 事件）
type: feedback
---

# AI 誤診事後報告：LINE Bot 不回應事件

> 2026-03-22 — 一次典型的「先射箭再畫靶」診斷失敗

## 使用者問題

「OpenClaw 的 LINE bot 在群組不回話了，一對一也完全沒反應。」

## AI 的錯誤診斷過程

### 第一步：看到 ngrok 就跳到結論

AI 看到系統使用 ngrok 做 tunnel，立刻假設：

> 「ngrok 免費版每次重啟 URL 會變 → LINE Developer Console 的 webhook URL 沒更新 → 收不到訊息」

**沒有做任何實際驗證**，就直接：
1. 啟動 3 個 Explore agent 研究程式碼
2. 啟動 1 個 Research agent 上網搜尋 LINE API
3. 進入 Plan Mode 設計「雙層防禦方案」
4. 寫了一份完整的實作計畫（Panel 改 ngrok 啟動參數 + OpenClaw 加 webhook 自動註冊）

### 使用者的質疑

使用者提出：
> 「我每次都透過 Panel 開啟 OpenClaw，而且過去 AI 你自己說過我的 URL 是固定不會變的。」

### 第二步：被質疑後才開始驗證

AI 終於執行了**本該在第一步就做的**三個測試：

```bash
# 測試 1：LINE API 查詢 webhook 狀態
curl https://api.line.me/v2/bot/channel/webhook/endpoint \
  -H "Authorization: Bearer {token}"
# → {"endpoint":"https://...ngrok.../line/webhook", "active":true}
#   ✅ URL 正確，webhook 啟用中

# 測試 2：直接 POST webhook endpoint
curl -X POST http://127.0.0.1:18789/line/webhook \
  -H "Content-Type: application/json" -d '{"events":[]}'
# → 404 Not Found
#   ❌ Gateway 根本沒有註冊這個路由！

# 測試 3：查看 gateway temp log
grep "starting LINE provider" $TEMP/openclaw/openclaw-2026-03-21.log
# → "[default] starting LINE provider (光仔AI)" ← 有啟動
# 但路由回 404 ← 啟動了卻沒有註冊成功，或註冊後消失
```

### 真正的問題

| 項目 | AI 假設 | 實際情況 |
|------|---------|----------|
| ngrok URL | 每次變，需要固定 | `.ngrok-free.dev` 是永久靜態域名，從未變過 |
| LINE webhook 設定 | 指向舊 URL | `active:true`，URL 完全正確 |
| 根因 | ngrok URL 不匹配 | **Gateway 的 /line/webhook 路由回傳 404** |

AI 設計的整套方案（Panel 加 `--url` 參數、OpenClaw 加 webhook 自動註冊、config schema 改動）**全部是在解決一個不存在的問題**。

## 正確的診斷流程（應該在開口前就完成）

```
使用者報告「LINE bot 不回應」
  │
  ├─ ① curl 測試 webhook endpoint → 200? 404? 503?
  │     └─ 404 → 路由未註冊，問題在 Gateway
  │     └─ 200 → 路由正常，問題在處理邏輯
  │
  ├─ ② 查詢 LINE API webhook 狀態
  │     └─ active:false → LINE 停用了 webhook
  │     └─ active:true + endpoint 錯誤 → URL 不匹配
  │     └─ active:true + endpoint 正確 → 問題不在 LINE 端
  │
  └─ ③ 查看當前 runtime 的 temp log（不是舊的 gateway.log）
        └─ provider 有啟動？有 error？有 crash？
```

**三個 curl 指令，30 秒內就能定位根因。**

## 教訓

1. **驗證完成前禁止規劃** — 再合理的假設都可能是錯的
2. **優先查 runtime 狀態** — process age、temp logs、route registration，而非 config 或程式碼
3. **第三方大型專案的問題有多層可能原因** — 不能靠直覺跳到「看起來最像」的那個
4. **使用者的質疑是重要信號** — 他們比 AI 更了解自己的環境

## 結果

使用者透過 Panel 重啟 Gateway 後，LINE bot 恢復正常。
整個問題只需要一次重啟就解決，而 AI 花了大量 context 在錯誤方向上。