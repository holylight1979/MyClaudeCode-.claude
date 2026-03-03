# 全域決策

- Scope: global
- Confidence: [固]
- Trigger: 全域決策, 工具, 工作流, workflow, 設定, config, 記住, guardian, hooks, MCP
- Last-used: 2026-03-03
- Confirmations: 2

## 知識

- [固] 版控同步支援 Git 和 SVN，自動偵測 .git/ 或 .svn/
- [固] MCP servers 實際可用: playwright, openclaw-notify, workflow-guardian
- [固] MCP servers 不存在（npm 404）: @anthropic-ai/computer-use, @anthropic-ai/browser-use — 可從 .claude.json 移除
- [固] OpenClaw 的 atoms/ 目錄僅歸屬 OpenClaw，不作為 Claude Code 全域 atom 來源
- [固] Workflow Guardian：hooks 事件驅動的工作流監督系統，自動追蹤修改、Stop 閘門阻止未同步結束
- [固] 工作結束同步須根據情境判斷適用步驟（有 _AIDocs 才更新 _CHANGELOG，有 .git/.svn 才版控）
- [固] **MCP stdio 傳輸格式**: Claude Code v2.x 使用 JSONL（`{...}\n`），不是 Content-Length header。自寫 MCP server 必須用 JSONL + protocolVersion `2025-11-25`，否則 30 秒超時 failed

## 行動

- 工作結束同步時，先判斷情境（_AIDocs? .git? .svn?），只提及適用的步驟
- 同步完成後透過 MCP `workflow_signal("sync_completed")` 通知 Guardian 解除閘門
- 自行開發 MCP server 時，用 JSONL 格式收發，不要用 Content-Length header
