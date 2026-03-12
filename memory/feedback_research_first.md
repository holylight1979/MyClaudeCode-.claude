---
name: feedback_research_first
description: 遇到不熟悉的技術問題時，先搜尋網路再動手，減少 trial-and-error
type: feedback
---

遇到不熟悉的 API / 框架行為時，先用 WebSearch 查網路資料再寫程式碼，不要盲目嘗試。

**Why:** Playwright download handling 反覆試錯 4 輪才搞定，浪費大量 token 和使用者時間。網路上其實有現成的解法（asyncio.wait race、context.request.get()、Content-Type 判斷等）。

**How to apply:**
- 碰到框架/API 行為不如預期 → 先 WebSearch 查官方文件 + GitHub issues + Stack Overflow
- 特別是第三方工具（Playwright、Selenium、各種 SDK）的邊界行為
- 查到後再決定方案，不要靠猜測寫 code → 跑 → 失敗 → 改 → 再跑的循環
