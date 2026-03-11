# V2.9 設計規格 — 記憶檢索強化

- Scope: global
- Confidence: [固]
- Type: design
- Trigger: V2.9, V3, 設計, 檢索強化, project-alias, ACT-R, multi-hop, blind-spot
- Last-used: 2026-03-11
- Created: 2026-03-11
- Confirmations: 0
- Tags: v2.9, design, retrieval, architecture
- Related: decisions, spec

## 背景

V2.8 的記憶檢索有 3 個已證實的缺陷：
1. **跨專案身份盲區**：prompt 含 "sgi" 但 c--Projects 的 atoms 無此 trigger → 找不到
2. **單跳檢索**：找到 architecture atom 後不會沿 Related 邊帶出 server_services
3. **平面計數**：Confirmations 是無時間權重的整數，3月和1月的 atom 同等重要

另有 1 個系統級問題：
4. **靜默失敗**：prompt 找不到任何 atom 時系統不報告，使用者和 LLM 都不知道有盲點

## 設計原則

來自跨領域研究的三個核心洞見（佛學啟發設計，工程語言實作）：
- **每次讀取即寫入**（薰習原則）：atom 被觸發時自動更新 activation metadata
- **過濾先於辨識**（受先於想）：先判斷領域相關性，再注入內容
- **承認偏差存在**（末那識警示）：系統應報告盲點，不假裝全知

## 改動項目

### 1. Project-Aliases（跨專案身份辨識）

**問題**：c--Projects/memory/MEMORY.md 的所有 atom triggers 是 port, path, 路徑... 無一含 "sgi"。
跨專案掃描用 `keyword in prompt` 比對 trigger → 全部 miss。

**方案**：在 MEMORY.md 加 Project-Aliases 行，hook 掃到時注入該專案的 MEMORY.md 全文。

```markdown
# Atom Index — SGI Project
> Project-Aliases: sgi, sgi_server, sgi-server, sgi_client, 遊戲後端
```

**Hook 改動**（workflow-guardian.py）：
- `parse_memory_index()` 額外解析 `> Project-Aliases:` 行
- 跨專案掃描時，先比對 aliases → 命中則注入 MEMORY.md 全文（而非逐 atom 比對）
- LLM 拿到 MEMORY.md 後自行決定讀哪些 atoms

**改動量**：~20 行

### 2. Related-Edge Spreading（多跳檢索）

**問題**：atom 有 `Related: server_services, client_main` 但 hook 不使用。
命中 architecture 後不會自動帶出相關 atoms。

**方案**：atom 被觸發後，解析 Related 欄位，沿邊再走 1 跳（可配置 depth）。

```python
def spread_related(matched_atoms, all_atoms_index, max_depth=1):
    """從已匹配 atoms 沿 Related 邊擴散"""
    spread_queue = list(matched_atoms)
    visited = {a.name for a in matched_atoms}
    for depth in range(max_depth):
        next_wave = []
        for atom in spread_queue:
            related_names = parse_related_field(atom)
            for rname in related_names:
                if rname not in visited:
                    visited.add(rname)
                    related_atom = find_atom_in_index(rname, all_atoms_index)
                    if related_atom:
                        next_wave.append(related_atom)
        spread_queue = next_wave
    return all matched + spread atoms
```

**Token 控制**：Related 邊帶出的 atoms 降低優先級（排在 keyword/vector match 之後），受 token budget 限制。

**改動量**：~40 行

### 3. ACT-R Activation Scoring（時間加權）

**問題**：Confirmations 是平面計數 (+1)，不反映時間衰減。
一個 3 月前觸發 10 次的 atom 和昨天觸發 10 次的 atom 分數相同。

**方案**：引入 access_log（獨立 JSON 檔），用 ACT-R 基礎激活公式排序。

```
B_i = ln( Σ_{k=1}^{n} t_k^{-0.5} )
```

其中 t_k = 距離第 k 次存取的秒數。

**實作**：
- hook 在 atom 被觸發時追加 timestamp 到 `{atom_name}.access.json`
- 排序時計算 B_i，高分優先注入
- access_log 只保留最近 50 筆（控制檔案大小）
- Confirmations 欄位保留但語意改為「累計觸發次數」（向後相容）
- 純 hook 計算，零 LLM token 消耗

**改動量**：~50 行 + 每個 atom 一個 .access.json 檔

### 4. Blind-Spot Reporter（盲點報告）

**問題**：prompt 找不到任何 atom 時系統靜默，LLM 不知道自己沒有相關記憶。

**方案**：當 keyword + vector + alias 全部找不到時，注入提示：

```
[Guardian:BlindSpot] 未找到與 "{prompt_keywords}" 相關的記憶 atom。
建議 LLM 主動搜尋檔案或詢問使用者。
```

**改動量**：~10 行

## 附帶清理

### 刪除 c--Projects-sgi-server/memory/

分析結果：c--Projects 已是 c--Projects-sgi-server 的完全超集。
sgi-server 的 decisions atom 自己寫「詳細版見 c--Projects 層的同名 atom」。

**動作**：刪除 `c--Projects-sgi-server/memory/` 目錄（保留 session logs）。

## 驗證計畫

1. **Project-Aliases**：從非 sgi CWD 問 "sgi 的架構"，確認 c--Projects atoms 被注入
2. **Related spreading**：觸發 architecture，確認 server_services 也被帶出
3. **ACT-R activation**：觸發同一 atom 多次，確認 .access.json 生成且排序正確
4. **Blind-spot**：問一個完全無 atom 的主題，確認報告出現
5. **回歸測試**：正常使用流程不受影響（trigger match、vector search、token budget）

## 排除項（有意不做）

以下項目經評估為過度工程或雞肋，不納入 V2.9（留待 V3 考慮）：
- 四緣閘門（增加 4 個檢查點，邊際改善不值得複雜度）
- 等無間緣 / 對話脈絡追蹤（誤壓制風險 > 收益）
- 五遍行 pipeline 重構（功能不變，只是換架構）
- 佛學術語入碼（增加認知負擔，用工程語言即可）
- 末那識命名層（實質只是 project scope，現有機制已足）

## 實施計畫

- **Session 1**：Project-Aliases + 刪除 sgi-server 冗餘 + Blind-Spot Reporter
- **Session 2**：Related-Edge Spreading + ACT-R Activation Scoring
- **Session 3**：整合測試 + SPEC/文件更新 + 版本號升級

## 理論參考

跨領域研究摘要存於 `memory/v3-research-insights.md`
