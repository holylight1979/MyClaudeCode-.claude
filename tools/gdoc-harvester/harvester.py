"""
Google Docs/Sheets Harvester — 邊瀏覽邊收割

使用方式：
  python harvester.py --workdir c:/tmp/harvester [--depth N] [--fresh]

1. 開啟 Chrome（帶你的登入狀態）
2. 瀏覽任何 Google Doc / Sheet 時自動擷取內容
3. 頁面內的 Google Doc/Sheet 連結會自動排入佇列背景爬取
4. 所有內容存為 Markdown / CSV 到 output 資料夾
5. 關閉瀏覽器視窗即結束
6. 結束後自動產生 _INDEX.md 總清單
"""

import asyncio
import argparse
import json
import re
import os
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.async_api import async_playwright, Page, BrowserContext
import aiohttp
import yarl
from markdownify import markdownify as md
from bs4 import BeautifulSoup

# --------------- Config ---------------

GOOGLE_DOC_PATTERN = re.compile(r'docs\.google\.com/document/d/([a-zA-Z0-9_-]+)')
GOOGLE_SHEET_PATTERN = re.compile(r'docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)')

TITLE_SUFFIXES = [
    ' - Google 文件', ' - Google 試算表',
    ' - Google Docs', ' - Google Sheets',
]

# --------------- State ---------------

visited: set[str] = set()
queue: asyncio.Queue = None
overflow_links: list[dict] = []
error_log: list[dict] = []
stats = {"docs": 0, "sheets": 0, "links_found": 0, "errors": 0, "overflow": 0}

output_dir: Path = None
max_depth: int = 1
http_session: aiohttp.ClientSession = None

# --------------- Helpers ---------------

def clean_title(raw: str) -> str:
    """去除 Google 文件標題後綴"""
    for suffix in TITLE_SUFFIXES:
        if raw.endswith(suffix):
            raw = raw[:-len(suffix)]
    return raw.strip()


def extract_doc_id(url: str) -> tuple[str, str] | None:
    m = GOOGLE_DOC_PATTERN.search(url)
    if m:
        return m.group(1), 'doc'
    m = GOOGLE_SHEET_PATTERN.search(url)
    if m:
        return m.group(1), 'sheet'
    return None


def extract_google_links(html: str) -> list[tuple[str, str, str]]:
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/url?' in href:
            parsed = parse_qs(urlparse(href).query)
            href = parsed.get('q', [href])[0]
        info = extract_doc_id(href)
        if info:
            doc_id, doc_type = info
            if doc_type == 'doc':
                clean_url = f'https://docs.google.com/document/d/{doc_id}'
            else:
                clean_url = f'https://docs.google.com/spreadsheets/d/{doc_id}'
            results.append((doc_id, doc_type, clean_url))
    return results


def sanitize_filename(title: str) -> str:
    title = re.sub(r'[<>:"/\\|?*]', '_', title)
    title = title.strip('. ')
    return title[:120] if title else 'untitled'


def safe_filepath(directory: Path, filename: str, ext: str) -> Path:
    filepath = directory / f'{filename}{ext}'
    counter = 1
    while filepath.exists():
        filepath = directory / f'{filename}_{counter}{ext}'
        counter += 1
    return filepath


def queue_links(html: str, depth: int, source_title: str, source_id: str):
    links = extract_google_links(html)
    for lid, ltype, lurl in links:
        if lid in visited:
            continue
        if depth + 1 <= max_depth:
            stats["links_found"] += 1
            queue.put_nowait((lid, ltype, lurl, depth + 1))
        else:
            stats["overflow"] += 1
            overflow_links.append({
                "url": lurl, "type": ltype,
                "found_in": source_title, "found_in_id": source_id,
                "would_be_depth": depth + 1,
            })


def extract_preview(filepath: Path, max_chars: int = 80) -> str:
    """讀取 .md 檔，跳過 frontmatter，取前 max_chars 字作為摘要"""
    try:
        text = filepath.read_text(encoding='utf-8')
        # 跳過 frontmatter
        if text.startswith('---'):
            end = text.find('---', 3)
            if end != -1:
                text = text[end + 3:]
        # 清理
        text = text.strip()
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[#*_\[\]()>]', '', text)  # 去 markdown 符號
        return text[:max_chars].strip()
    except Exception:
        return ''


# --------------- Core ---------------

async def sync_cookies_from_browser(context: BrowserContext) -> None:
    """Extract cookies from browser context and inject into aiohttp session."""
    global http_session
    cookies = await context.cookies()
    if http_session and not http_session.closed:
        await http_session.close()
    jar = aiohttp.CookieJar(unsafe=True)
    http_session = aiohttp.ClientSession(cookie_jar=jar)
    for c in cookies:
        jar.update_cookies(
            {c['name']: c['value']},
            response_url=yarl.URL(f"https://{c['domain'].lstrip('.')}/")
        )


async def http_fetch(url: str) -> tuple[int, str]:
    """Fetch URL using aiohttp with browser cookies."""
    async with http_session.get(url, allow_redirects=True) as resp:
        text = await resp.text(errors='replace')
        return resp.status, text


async def capture_doc(doc_id: str, depth: int = 0) -> None:
    if doc_id in visited:
        return
    visited.add(doc_id)

    export_url = f'https://docs.google.com/document/d/{doc_id}/export?format=html'
    try:
        status, html = await http_fetch(export_url)
        if status != 200 or not html:
            print(f'  ✗ Doc {doc_id[:20]}: HTTP {status}')
            error_log.append({"type": "doc", "doc_id": doc_id, "reason": f"HTTP {status}"})
            stats["errors"] += 1
            return
    except Exception as e:
        print(f'  ✗ Doc {doc_id[:20]}: {e}')
        error_log.append({"type": "doc", "doc_id": doc_id, "reason": str(e)})
        stats["errors"] += 1
        return

    # Title
    soup = BeautifulSoup(html, 'html.parser')
    title_tag = soup.find('title')
    title = title_tag.text.strip() if title_tag else doc_id
    title = clean_title(title)
    if title == doc_id:
        h = soup.find(['h1', 'h2', 'h3'])
        if h:
            title = clean_title(h.get_text(strip=True)[:120])

    markdown = md(html, heading_style="ATX", strip=['img'])
    filename = sanitize_filename(title)
    filepath = safe_filepath(output_dir, filename, '.md')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f'---\n')
        f.write(f'source: https://docs.google.com/document/d/{doc_id}\n')
        f.write(f'title: "{title}"\n')
        f.write(f'type: google-doc\n')
        f.write(f'harvested: "{time.strftime("%Y-%m-%d %H:%M:%S")}"\n')
        f.write(f'---\n\n')
        f.write(markdown)

    stats["docs"] += 1
    print(f'  ✓ Doc: {title} → {filepath.name}')
    queue_links(html, depth, title, doc_id)


async def capture_sheet(doc_id: str, depth: int = 0) -> None:
    if doc_id in visited:
        return
    visited.add(doc_id)

    # CSV export
    csv_data = None
    try:
        csv_url = f'https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv'
        status, csv_data = await http_fetch(csv_url)
        if status != 200:
            csv_data = None
    except Exception:
        csv_data = None

    # HTML export (for title, links, and markdown conversion)
    html = None
    try:
        html_url = f'https://docs.google.com/spreadsheets/d/{doc_id}/export?format=html'
        status, html = await http_fetch(html_url)
        if status != 200 or not html:
            print(f'  ✗ Sheet {doc_id[:20]}: HTTP {status}')
            error_log.append({"type": "sheet", "doc_id": doc_id, "reason": f"HTTP {status}"})
            stats["errors"] += 1
            return
    except Exception as e:
        print(f'  ✗ Sheet {doc_id[:20]}: {e}')
        error_log.append({"type": "sheet", "doc_id": doc_id, "reason": str(e)})
        stats["errors"] += 1
        return

    # Title
    soup = BeautifulSoup(html, 'html.parser')
    title_tag = soup.find('title')
    title = title_tag.text.strip() if title_tag else doc_id
    title = clean_title(title)
    filename = sanitize_filename(title)

    # Save CSV
    if csv_data:
        csv_path = safe_filepath(output_dir, filename, '.csv')
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write(csv_data)
        print(f'  ✓ Sheet (CSV): {title} → {csv_path.name}')

    # Save HTML→Markdown
    markdown = md(html, heading_style="ATX")
    md_path = safe_filepath(output_dir, filename, '.md')

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f'---\n')
        f.write(f'source: https://docs.google.com/spreadsheets/d/{doc_id}\n')
        f.write(f'title: "{title}"\n')
        f.write(f'type: google-sheet\n')
        f.write(f'harvested: "{time.strftime("%Y-%m-%d %H:%M:%S")}"\n')
        f.write(f'---\n\n')
        f.write(markdown)

    stats["sheets"] += 1
    print(f'  ✓ Sheet (MD): {title} → {md_path.name}')
    queue_links(html, depth, title, doc_id)


async def background_worker(context: BrowserContext) -> None:
    """Background worker: processes queued links via aiohttp."""
    while True:
        try:
            doc_id, doc_type, url, depth = await asyncio.wait_for(queue.get(), timeout=3.0)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break

        if doc_id in visited:
            queue.task_done()
            continue

        print(f'  ⟳ Background (depth {depth}): {url}')
        if doc_type == 'doc':
            await capture_doc(doc_id, depth)
        else:
            await capture_sheet(doc_id, depth)
        queue.task_done()
        await asyncio.sleep(0.5)


async def on_page_navigate(page: Page) -> None:
    url = page.url
    info = extract_doc_id(url)
    if not info:
        return

    doc_id, doc_type = info
    if doc_id in visited:
        return
    visited.add(doc_id)  # 立即佔位，防 race condition（在 await 之前）

    print(f'\n📄 偵測到: {url}')
    await sync_cookies_from_browser(page.context)

    if doc_type == 'doc':
        await capture_doc(doc_id, depth=0)
    else:
        await capture_sheet(doc_id, depth=0)

    print(f'  📊 已收割: {stats["docs"]} docs, {stats["sheets"]} sheets | '
          f'佇列: {stats["links_found"]} | 錯誤: {stats["errors"]}')


def generate_index(out_dir: Path) -> None:
    """掃描 output 目錄，產生 _INDEX.md 總清單"""
    docs = []
    sheets = []

    for f in sorted(out_dir.glob('*.md')):
        if f.name.startswith('_'):
            continue
        try:
            text = f.read_text(encoding='utf-8')
            meta = {"filename": f.name, "title": f.stem, "source": "", "type": "", "harvested": ""}
            # Parse frontmatter
            if text.startswith('---'):
                end = text.find('---', 3)
                if end != -1:
                    for line in text[3:end].strip().split('\n'):
                        if ':' in line:
                            key, val = line.split(':', 1)
                            key = key.strip()
                            val = val.strip().strip('"')
                            if key in meta:
                                meta[key] = val
            meta["preview"] = extract_preview(f)

            if 'sheet' in meta["type"]:
                sheets.append(meta)
            else:
                docs.append(meta)
        except Exception:
            pass

    lines = []
    lines.append('# 收割總清單\n')
    lines.append(f'> 收割時間：{time.strftime("%Y-%m-%d %H:%M")} | '
                 f'共 {len(docs) + len(sheets)} 份文件'
                 f'（{len(docs)} Docs + {len(sheets)} Sheets）\n')

    if docs:
        lines.append('\n## Google Docs\n')
        lines.append('| # | 標題 | 摘要 | 來源 |')
        lines.append('|---|------|------|------|')
        for i, d in enumerate(docs, 1):
            src = f'[開啟]({d["source"]})' if d["source"] else ''
            lines.append(f'| {i} | {d["title"]} | {d["preview"]} | {src} |')

    if sheets:
        lines.append('\n## Google Sheets\n')
        lines.append('| # | 標題 | 摘要 | 來源 |')
        lines.append('|---|------|------|------|')
        for i, d in enumerate(sheets, 1):
            src = f'[開啟]({d["source"]})' if d["source"] else ''
            lines.append(f'| {i} | {d["title"]} | {d["preview"]} | {src} |')

    if error_log:
        lines.append('\n## 收割失敗\n')
        lines.append('| # | 類型 | doc_id | 原因 |')
        lines.append('|---|------|--------|------|')
        for i, e in enumerate(error_log, 1):
            lines.append(f'| {i} | {e["type"]} | {e["doc_id"][:12]}... | {e["reason"]} |')

    if overflow_links:
        lines.append(f'\n## 超出深度限制（未追蹤）\n')
        lines.append(f'共 {len(overflow_links)} 個連結，詳見 _overflow_links.md')

    index_path = out_dir / '_INDEX.md'
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'  📋 總清單: {index_path}')


async def main():
    global queue, output_dir, max_depth, http_session

    parser = argparse.ArgumentParser(description='Google Docs/Sheets Harvester')
    parser.add_argument('--workdir', '-w', default='c:/tmp/harvester',
                        help='工作目錄（預設 c:/tmp/harvester）')
    parser.add_argument('--output', '-o', default=None,
                        help='輸出目錄（預設 {workdir}/output）')
    parser.add_argument('--depth', '-d', type=int, default=1,
                        help='連結追蹤深度（預設 1）')
    parser.add_argument('--fresh', action='store_true',
                        help='重新複製 Chrome 登入狀態（需先關閉 Chrome）')
    args = parser.parse_args()

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    output_dir = Path(args.output) if args.output else workdir / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)

    max_depth = args.depth
    queue = asyncio.Queue()

    browser_data = workdir / 'browser-data'

    print('=' * 60)
    print(' Google Docs/Sheets Harvester')
    print('=' * 60)
    print(f' 工作目錄:  {workdir.resolve()}')
    print(f' 輸出目錄:  {output_dir.resolve()}')
    print(f' 連結深度:  {max_depth}')
    print(f' 操作方式:  瀏覽器開啟後正常瀏覽文件')
    print(f'            工具會自動擷取，關閉視窗即結束')
    print('=' * 60)

    # Copy Chrome profile
    chrome_src = Path(os.environ.get('LOCALAPPDATA', '')) / 'Google/Chrome/User Data'
    if not chrome_src.exists():
        print(f' ✗ 找不到 Chrome 使用者資料: {chrome_src}')
        return

    dst_default = browser_data / 'Default'

    if args.fresh and browser_data.exists():
        shutil.rmtree(browser_data)

    if not dst_default.exists():
        print(' ⟳ 複製 Chrome 登入狀態...')
        browser_data.mkdir(parents=True, exist_ok=True)
        src_default = chrome_src / 'Default'
        dst_default.mkdir(parents=True, exist_ok=True)
        for fname in ['Cookies', 'Login Data', 'Web Data', 'Preferences',
                       'Secure Preferences', 'Local State']:
            src_file = src_default / fname
            if src_file.exists():
                shutil.copy2(src_file, dst_default / fname)
        local_state = chrome_src / 'Local State'
        if local_state.exists():
            shutil.copy2(local_state, browser_data / 'Local State')
        print(' ✓ 完成')

    # Import dashboard from same directory
    import importlib.util
    dashboard_path = Path(__file__).parent / 'dashboard.py'
    spec = importlib.util.spec_from_file_location("dashboard", dashboard_path)
    dashboard_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard_mod)
    dashboard_mod.start_dashboard(stats, visited, output_dir, overflow_links)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(browser_data),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale='zh-TW',
            accept_downloads=True,
            args=['--disable-blink-features=AutomationControlled'],
        )

        # Initial cookie sync
        init_page = context.pages[0] if context.pages else await context.new_page()
        await init_page.goto('https://docs.google.com', wait_until='domcontentloaded')
        await sync_cookies_from_browser(context)

        # Background worker
        worker_task = asyncio.create_task(background_worker(context))

        # Listen for navigation
        def setup_page(page: Page):
            page.on('framenavigated', lambda frame: (
                asyncio.create_task(on_page_navigate(page))
                if frame == page.main_frame else None
            ))

        for pg in context.pages:
            setup_page(pg)
        context.on('page', setup_page)

        # Open dashboard tab
        dash_page = await context.new_page()
        await dash_page.goto('http://127.0.0.1:8787')

        # Open Google Docs home if needed
        user_pages = [pg for pg in context.pages if pg != dash_page]
        if len(user_pages) <= 1:
            pg = await context.new_page()
            setup_page(pg)
            await pg.goto('https://docs.google.com')

        # Wait until browser closed
        try:
            while True:
                user_pages = [pg for pg in context.pages if pg != dash_page]
                if not user_pages:
                    break
                await asyncio.sleep(1)
        except Exception:
            pass

        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    # Cleanup HTTP session
    if http_session and not http_session.closed:
        await http_session.close()

    # Generate index
    generate_index(output_dir)

    # Report
    print('\n' + '=' * 60)
    print(' 收割完成！')
    print(f' Docs:     {stats["docs"]}')
    print(f' Sheets:   {stats["sheets"]}')
    print(f' Overflow: {stats["overflow"]}')
    print(f' Errors:   {stats["errors"]}')
    print(f' Output:   {output_dir.resolve()}')
    print(f' 總清單:   {(output_dir / "_INDEX.md").resolve()}')
    print('=' * 60)

    # Save manifest
    manifest = {
        "harvested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats": stats,
        "doc_ids": list(visited),
        "errors": error_log,
    }
    with open(output_dir / '_manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Save overflow links
    if overflow_links:
        overflow_path = output_dir / '_overflow_links.md'
        with open(overflow_path, 'w', encoding='utf-8') as f:
            f.write(f'# 超出深度限制的連結\n\n')
            f.write(f'> 深度限制: {max_depth} | 共 {len(overflow_links)} 個\n\n')
            f.write(f'| # | 類型 | 連結 | 來源文件 | 深度 |\n')
            f.write(f'|---|------|------|---------|------|\n')
            for i, link in enumerate(overflow_links, 1):
                f.write(f'| {i} | {link["type"]} | {link["url"]} | {link["found_in"]} | {link["would_be_depth"]} |\n')
        print(f' 📋 Overflow: {overflow_path.resolve()}')


if __name__ == '__main__':
    asyncio.run(main())
