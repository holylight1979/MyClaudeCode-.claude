"""
即時收割儀表板 — 嵌入式 HTTP server，在瀏覽器 tab 顯示收割進度
改善版：摘要預覽、即時提示、收割時間
"""

import json
import re
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

_stats = None
_visited = None
_output_dir = None
_overflow = None
_server = None

DASHBOARD_PORT = 8787


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/status':
            self._json_response({
                "stats": _stats,
                "visited": list(_visited) if _visited else [],
                "overflow": len(_overflow) if _overflow else 0,
            })
        elif self.path == '/api/files':
            files = []
            if _output_dir and _output_dir.exists():
                for f in sorted(_output_dir.glob('*.md'), key=lambda x: x.stat().st_mtime, reverse=True):
                    if f.name.startswith('_'):
                        continue
                    try:
                        text = f.read_text(encoding='utf-8')
                        title = f.stem
                        source = ''
                        doc_type = ''
                        harvested = ''
                        preview = ''
                        # Parse frontmatter
                        if text.startswith('---'):
                            end = text.find('---', 3)
                            if end != -1:
                                for line in text[3:end].strip().split('\n'):
                                    if ':' in line:
                                        key, val = line.split(':', 1)
                                        key = key.strip()
                                        val = val.strip().strip('"')
                                        if key == 'title':
                                            title = val
                                        elif key == 'source':
                                            source = val
                                        elif key == 'type':
                                            doc_type = val
                                        elif key == 'harvested':
                                            harvested = val
                                # Extract preview (after frontmatter)
                                body = text[end + 3:].strip()
                                body = re.sub(r'\n+', ' ', body)
                                body = re.sub(r'\s+', ' ', body)
                                body = re.sub(r'[#*_\[\]()>|]', '', body)
                                preview = body[:100].strip()
                        files.append({
                            "filename": f.name,
                            "title": title,
                            "source": source,
                            "type": doc_type,
                            "size": f.stat().st_size,
                            "harvested": harvested,
                            "preview": preview,
                        })
                    except Exception:
                        files.append({
                            "filename": f.name, "title": f.stem,
                            "source": "", "type": "", "size": 0,
                            "harvested": "", "preview": "",
                        })
            self._json_response(files)
        else:
            self._html_response()

    def _json_response(self, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _html_response(self):
        html = """<!DOCTYPE html>
<html lang="zh-TW"><head><meta charset="utf-8">
<title>Harvester Dashboard</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; margin: 0; padding: 20px; }
  h1 { color: #e94560; margin-bottom: 5px; font-size: 1.4em; }
  .status-bar {
    background: #16213e; border-radius: 8px; padding: 12px 18px; margin: 10px 0;
    display: flex; align-items: center; gap: 12px;
  }
  .status-dot { width: 10px; height: 10px; border-radius: 50%; background: #4ecca3; animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
  .status-text { color: #aaa; font-size: 0.9em; }
  .latest { color: #4ecca3; font-weight: bold; }
  .stats { display: flex; gap: 15px; margin: 12px 0; flex-wrap: wrap; }
  .stat-card {
    background: #16213e; border-radius: 10px; padding: 12px 20px;
    min-width: 90px; text-align: center; flex: 1;
  }
  .stat-card .num { font-size: 1.8em; font-weight: bold; }
  .stat-card .num.docs { color: #4ecca3; }
  .stat-card .num.sheets { color: #4e9fcc; }
  .stat-card .num.err { color: #e94560; }
  .stat-card .label { font-size: 0.8em; color: #888; margin-top: 3px; }
  .file-list { margin-top: 15px; }
  .file-card {
    background: #16213e; border-radius: 8px; padding: 14px 18px; margin-bottom: 8px;
    display: flex; gap: 15px; align-items: flex-start;
    transition: background 0.2s;
  }
  .file-card:hover { background: #1a2744; }
  .file-card.new { animation: slideIn 0.5s ease-out; }
  @keyframes slideIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }
  .file-num { color: #555; font-size: 0.85em; min-width: 24px; padding-top: 2px; }
  .file-info { flex: 1; min-width: 0; }
  .file-title { font-weight: bold; font-size: 1em; margin-bottom: 4px; }
  .file-preview { color: #888; font-size: 0.85em; line-height: 1.4; overflow: hidden;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .file-meta { display: flex; gap: 12px; margin-top: 6px; font-size: 0.75em; color: #666; }
  .file-meta a { color: #4ecca3; text-decoration: none; }
  .file-meta a:hover { text-decoration: underline; }
  .type-badge {
    padding: 2px 8px; border-radius: 4px; font-size: 0.75em; font-weight: bold;
    white-space: nowrap;
  }
  .type-badge.doc { background: #4ecca322; color: #4ecca3; }
  .type-badge.sheet { background: #4e9fcc22; color: #4e9fcc; }
  .empty-state { text-align: center; padding: 60px 20px; color: #555; }
  .empty-state .icon { font-size: 3em; margin-bottom: 10px; }
  .empty-state p { font-size: 0.95em; }
  .refresh-info { color: #444; font-size: 0.7em; text-align: right; margin-top: 8px; }
</style>
</head><body>
<h1>Harvester Dashboard</h1>
<div class="status-bar">
  <div class="status-dot"></div>
  <span class="status-text" id="statusText">正在監聽... 瀏覽 Google Docs/Sheets 即自動收割</span>
</div>
<div class="stats" id="stats"></div>
<div class="file-list" id="fileList"></div>
<div class="refresh-info" id="refreshInfo"></div>
<script>
let prevCount = 0;
let latestTitle = '';

async function update() {
  try {
    const [sr, fr] = await Promise.all([fetch('/api/status'), fetch('/api/files')]);
    const s = await sr.json();
    const files = await fr.json();
    const total = (s.stats?.docs ?? 0) + (s.stats?.sheets ?? 0);

    // Stats
    document.getElementById('stats').innerHTML = `
      <div class="stat-card"><div class="num docs">${s.stats?.docs ?? 0}</div><div class="label">Docs</div></div>
      <div class="stat-card"><div class="num sheets">${s.stats?.sheets ?? 0}</div><div class="label">Sheets</div></div>
      <div class="stat-card"><div class="num">${s.stats?.links_found ?? 0}</div><div class="label">連結追蹤</div></div>
      <div class="stat-card"><div class="num err">${s.stats?.errors ?? 0}</div><div class="label">錯誤</div></div>
    `;

    // Status bar
    const statusEl = document.getElementById('statusText');
    if (files.length > 0 && files.length !== prevCount) {
      latestTitle = files[0].title;
      statusEl.innerHTML = '正在監聽... 最新收割：<span class="latest">《' + latestTitle + '》</span>';
    } else if (files.length === 0) {
      statusEl.textContent = '正在監聽... 瀏覽 Google Docs/Sheets 即自動收割';
    }
    prevCount = files.length;

    // File list
    const fileList = document.getElementById('fileList');
    if (files.length === 0) {
      fileList.innerHTML = `
        <div class="empty-state">
          <div class="icon">📡</div>
          <p>等待收割... 請在其他分頁瀏覽 Google Docs 或 Sheets</p>
        </div>`;
    } else {
      fileList.innerHTML = files.map((f, i) => {
        const isSheet = f.type?.includes('sheet');
        const typeBadge = isSheet
          ? '<span class="type-badge sheet">Sheet</span>'
          : '<span class="type-badge doc">Doc</span>';
        const sizeKB = (f.size / 1024).toFixed(1);
        const shortSource = f.source ? f.source.split('/d/')[1]?.substring(0, 8) || '' : '';
        return `
          <div class="file-card">
            <div class="file-num">${i + 1}</div>
            <div class="file-info">
              <div class="file-title">${f.title} ${typeBadge}</div>
              <div class="file-preview">${f.preview || '（無摘要）'}</div>
              <div class="file-meta">
                <span>${sizeKB} KB</span>
                <span>${f.harvested || ''}</span>
                ${f.source ? '<a href="' + f.source + '" target="_blank">開啟原文 (' + shortSource + '...)</a>' : ''}
              </div>
            </div>
          </div>`;
      }).join('');
    }

    document.getElementById('refreshInfo').textContent =
      `更新於 ${new Date().toLocaleTimeString()} — 每 3 秒自動更新`;
  } catch(e) { console.error(e); }
}
update();
setInterval(update, 3000);
</script>
</body></html>"""
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def start_dashboard(stats_ref, visited_ref, output_dir_ref, overflow_ref):
    global _stats, _visited, _output_dir, _overflow, _server
    _stats = stats_ref
    _visited = visited_ref
    _output_dir = output_dir_ref
    _overflow = overflow_ref

    _server = HTTPServer(('127.0.0.1', DASHBOARD_PORT), DashboardHandler)
    thread = Thread(target=_server.serve_forever, daemon=True)
    thread.start()
    print(f' 📊 Dashboard: http://127.0.0.1:{DASHBOARD_PORT}')
    return _server
