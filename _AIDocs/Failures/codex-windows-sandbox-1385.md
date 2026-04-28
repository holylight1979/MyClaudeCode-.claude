# Codex Windows Sandbox 1385 — `CreateProcessWithLogonW failed`

> 觸發時機：Windows 上跑 `codex exec` 派稽核大師，CLI sandbox 旗標觸發 logon-type-not-granted。
> 沉澱於：memory cleanup 2026-04 多大師協作（5 位 Codex 分析師同時受影響）。

## 症狀

- 指令：`codex exec -s read-only "$PROMPT"` 或 `-s workspace-write`
- 錯誤：`CreateProcessWithLogonW failed: 1385`（logon type not granted）
- 結果：Codex 無法 spawn 任何 shell 子程序 → cat/head/grep 全部失敗 → 實質讀檔不可能 → 報告基於 briefing 文字憑空推論（產出仍有立場主張，但缺少事實核驗能力）

## 根因

使用者本機 `~/.codex/config.toml` 含：

```toml
[windows]
sandbox = "elevated"
```

預設 `elevated` 在大多數 Windows 帳號下無 logon type 權限，CLI `-s` 旗標切換 sandbox 模式時會觸發 1385。

## 修補

啟動 codex 時用 `-c` 覆寫為 `unelevated`：

```bash
codex exec \
  -c 'windows.sandbox="unelevated"' \
  --skip-git-repo-check \
  -p zh-brief \
  --color never \
  "$PROMPT" > output.md 2>&1
```

`unelevated` 是 Codex Windows sandbox 唯二合法值之一（另一個是 `elevated`）。仍有 sandbox 保護但不需提權。

## 為何難察覺

- Codex 本體會吞 1385 → 報告仍正常產出（只是內容變成「基於 briefing 立場推論」而非「實際讀檔核驗」）
- 主控（ClaudeCode）若不比對「Codex 報告事實 vs 實檔」，無法察覺差異
- 5 位分析席 Codex 第一輪全部受影響，僅在 Phase 4 audit 重派時用 `-c` 覆寫才產出真正讀檔的報告

## 教訓

1. **派 Codex 大師前先驗 sandbox**：用 cheap 指令 `codex exec -c 'windows.sandbox="unelevated"' "ls ~/.claude" > /tmp/sandbox-probe.txt` 確認可讀檔
2. **保守值在主控側固定**：所有 codex exec 命令模板統一加 `-c 'windows.sandbox="unelevated"'`
3. **不要用 `-s read-only` / `-s workspace-write`**：在 Windows 觸發 1385，改用 config override 控制權限
4. **Codex 報告必須交叉驗證**：CC 主控用 grep/cat 對 Codex 報告中的事實聲稱實檔比對；矛盾時預設信實檔不信 Codex

## 連帶

- 5 位分析席 Codex 報告（minimalist/conservative/radical/...）只能當「立場主張參考」，不能當「事實核驗」
- Phase 4 audit 須重派 Codex 用正確 sandbox 旗標跑一次實際讀檔的稽核
- multi-agent-cleanup-protocol.md §三 已寫死 sandbox 修復段落 + §七 大師席次表規定 Codex 必須在 dangerous 高風險 stage 補實證
