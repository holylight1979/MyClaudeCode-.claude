# gdoc-harvester — Web Harvester 收割工具經驗

- Scope: global
- Confidence: [固]
- Trigger: harvester, Google Docs, Sheets, 收割, Playwright, cookie, export
- Last-used: 2026-03-24
- Confirmations: 18

## 知識

### Web Harvester

**位置**: `~/.claude/tools/gdoc-harvester/`（技能本體，可上 GIT）
**Skill**: `/harvest`（`~/.claude/commands/harvest.md`）
**Runtime**: 使用者指定工作目錄（預設 `c:/tmp/harvester/`，含 browser-data + output，不進 GIT）

### 關鍵踩坑

1. **Google 偵測自動化** — 必須 `channel="chrome"` + `--disable-blink-features=AutomationControlled`
2. **Sheets export 401/400** — `sheet_download()` 先開編輯頁建 context，再 `page.evaluate` 觸發；端點優先 `gviz/tq?tqx=out:csv`
3. **framenavigated race** — `on_page_navigate` 第一個 await 前 `visited.add()` 佔位
4. **SPA 不觸發 framenavigated** — SPA URL poller 每 2 秒掃分頁 URL，與 framenavigated 並存
5. **Chrome profile lock** — 複製 Cookies 到獨立目錄（需先關 Chrome）

### 架構

```
classify_url(url) → (key, type) | None
  ├─ Google Docs/Sheets/Slides → 專用 export 邏輯
  ├─ GitLab (hostname 含 "gitlab" 或 /-/ 路徑) → capture_page + try_raw_content
  ├─ GitHub (github.com) → capture_page + try_raw_content
  ├─ SKIP_URL_PATTERNS 命中 → None（不收割）
  └─ 其他 → capture_page（通用 HTML→Markdown）
```

- **偵測引擎**: `framenavigated`（完整導航）+ SPA URL poller（pushState）
- **Google 專用**: `page_fetch()` / `sheet_download()` / `capture_slide()`
- **通用擷取**: `capture_page()` — 平台 CSS selector (`CONTENT_SELECTORS`) + noise 移除 + `markdownify`
- **Raw content**: `try_raw_content()` — GitLab wiki `.md` / blob `/-/raw/`、GitHub `raw.githubusercontent.com`
- **Dashboard**: `http://127.0.0.1:8787` — 即時進度（Docs/Sheets/Slides/Pages 統計 + type badge）
- **結束**: 關閉瀏覽器 → `_INDEX.md` 總清單

### 安全設計

- 技能本體零硬編碼路徑、零公司 URL
- browser-data（含所有網站 cookies）存在 runtime 工作目錄，不進 git
- Skill 流程提醒使用者事後清理敏感資料

## 行動

- 使用或改進 `/harvest` skill 時參考踩坑記錄
- 新增平台支援時，先確認 `classify_url()` + `CONTENT_SELECTORS` 涵蓋該平台
