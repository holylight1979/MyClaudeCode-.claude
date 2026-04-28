# Dual-Backend Ollama — 退避機制

> 從 Architecture.md 移入（2026-04-17 索引化）。實作：`tools/ollama_client.py`。
> keywords: ollama, 退避, DIE, rdchat, gemma4, qwen3, backend, failover

統一 Ollama 呼叫入口 `tools/ollama_client.py`，支援多 backend 自動切換：

```
config.json → ollama_backends:
  rdchat-direct (priority=1, RTX 3090, gemma4:e4b)
    → rdchat proxy (priority=2)
    → local (priority=3, GTX 1050 Ti, qwen3:1.7b)
```

## 三階段退避

- **正常** → 連續 2 次失敗 → **短 DIE**（60s 冷卻，跳過此 backend）
- 10 分鐘內 2 次短 DIE → **長 DIE**（等到下個 6h 時段：00/06/12/18 點）
- 長 DIE 觸發 → SessionStart hook 詢問使用者「停用」或「保持」
- **靜態停用旗標**：`enabled: false` 永久跳過，不做 health check

## 降級鏈

primary 不可用 → fallback (Dual-Backend) → 全 Ollama 不可用 → 純 keyword
Vector Service 掛 → graceful fallback（不阻塞）
