# 原子記憶系統 Atomic Memory V4.1

原子記憶系統為 Claude Code 補上 INDEX 型長期記憶層，透過 hooks 自動注入歷史知識，讓 AI 具備按需接續 session 工作、且避免反覆犯同樣的錯。

---

## 安裝

### 1. 前置需求

| 必備 | 最低版本 | 確認指令 |
|------|---------|---------|
| Claude Code | 最新 | VS Code Extension 市集搜尋 "Claude" |
| Python | 3.10+ | `python --version` |
| Node.js | 任意 LTS | `node --version` |
| Ollama | 最新 | `ollama --version` |
| Git | 任意 | `git --version` |

### 2. 由 AI 全程代跑

先 clone 或下載 repo 到 `~/.claude/`，再開一個新的 Claude Code session（任何資料夾都行），把下面這段 prompt 整段貼進去就好：

```
請幫我把 原子記憶系統 Atomic Memory V4.1 合併安裝到我的 ~/.claude/ 目錄。
1. 先讀 ~/.claude/Install-forAI.md 完整流程；
2. 檢查我環境的必備套件是否齊全（Python / Node.js / Ollama / Git / 向量 DB 套件），列出缺項告訴我怎麼補；
3. 照 Install-forAI.md 的 AI 執行流程合併安裝（不覆蓋我現有的 settings.json permissions）；
4. 最後跑驗證 checklist 並回報「安裝完成 / 尚缺 X」。
```

AI 會自己走完檔案合併 + npm 套件 + MCP 設定 + Ollama 模型 + Vector Service + 驗證。缺套件會主動列給你去補，不會硬裝。

---

## 如何使用

### 0. 驗證安裝

開新 session，請 AI 自檢：

```
確認我電腦下 ~/.claude/ 的 原子記憶系統 已正確安裝（hooks、Vector Service、Ollama 模型）。
```

### 1. 在專案裡使用 — 3 步到底

- **STEP A**：在專案根目錄開啟 VS Code（或 Claude Code CLI 在專案目錄啟動）
- **STEP B**：首次執行 `/init-project` 建立原子記憶庫根；完成後上傳 GIT / SVN 讓團隊共享
- **STEP C**：其實到這就完成了，照你原本 Claude Code 的方式繼續使用就好 — 系統在背景自動運作

### 2. 更順手的補充

- **第一個使用者**想先讓 AI 預載某部分知識：`/read-project <目錄> <方向>` → 掃描並寫入知識庫，之後也記得上傳 GIT / SVN
- **接續使用者**：從版控 pull 專案的 `.claude/memory/` 即可直接接上團隊記憶
- 兩個重要縮寫：**「執P」**（分階段執行+驗證+上 GIT+給下階段 prompt）、**「上GIT」**（把當次異動一次推上 GIT / SVN）— 直接問 AI 會解釋，也會照規則執行

---

## 技術細節

想深入了解系統技能、MCP、具體運作流程、如何與 Claude Code 發酵 → [TECH.md](TECH.md)

---

## License

[GNU General Public License v3.0](LICENSE)
