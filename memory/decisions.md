# 全域決策

- Scope: global
- Confidence: [固]
- Trigger: 決策, 記憶系統, 原子記憶, MCP, context budget, 晉升, 品質機制, fix escalation
- Last-used: 2026-04-28
- Confirmations: 0
- ReadHits: 192
- Related: decisions-architecture, toolchain, toolchain-ollama

## 知識

> 架構細節（核心架構 / V3 管線 / SessionStart 風暴修復）已移至 `decisions-architecture.md`

### 跨 Session 鞏固（v3 雙欄位）
- [固] 晉升門檻（雙軌）：
  - Primary: Confirmations（跨 session 萃取命中）[臨]→[觀] ≥4, [觀]→[固] ≥10
  - Auxiliary: ReadHits（注入讀取）[臨]→[觀] ≥20, [觀]→[固] ≥50
  - 7 天豁免：migration 後 Confirmations 未達標時，ReadHits/5 ≥ 門檻可 fallback

### 品質機制
- [固] 自我迭代精簡為 3 條：品質函數（Hook）、證據門檻（Claude）、震盪偵測（Hook）

### Fix Escalation
- [固] 同一問題修正第 2 次起 → 6 Agent 精確修正會議
- [固] Guardian 自動偵測 retry_count ≥ 2 → 注入信號

## 行動

- 記憶寫入走 write-gate 品質閘門
- 向量搜尋 fallback：Ollama → sentence-transformers → keyword
- Guardian 閘門最多阻止 2 次，第 3 次強制放行

