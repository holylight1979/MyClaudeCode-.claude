"""
service.py — Memory Vector Service HTTP Daemon

stdlib http.server 實作，port 3849。
提供語意搜尋、索引、健康檢查等 API。

啟動: pythonw service.py  (Windows 背景)
      python service.py   (前景, 看 log)
"""

import json
import os
import signal
import sys
import threading
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

# Add parent dir to path for imports
SERVICE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_DIR))
# V2.20: import wg_paths for centralized path resolution
sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))

from config import load_config, VECTORDB_DIR
from indexer import build_index, create_embedder, get_index_status
from searcher import search, search_raw, ranked_search, ranked_search_sections, episodic_search

# ─── Globals ─────────────────────────────────────────────────────────────────

_config: Dict[str, Any] = {}
_embedder = None
_start_time = 0.0
_request_count = 0
_index_lock = threading.Lock()
_index_status: Optional[Dict[str, Any]] = None  # None=idle, {"running":True,...} or result


def _init_service():
    """Initialize service: load config and embedder."""
    global _config, _embedder, _start_time
    _config = load_config()
    _start_time = time.time()

    try:
        _embedder = create_embedder(_config)
        print(f"[service] Embedder loaded: {_embedder.__class__.__name__}", file=sys.stderr)
    except Exception as e:
        print(f"[service] WARNING: No embedder available: {e}", file=sys.stderr)
        _embedder = None


# ─── Request Handler ─────────────────────────────────────────────────────────


class VectorServiceHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Memory Vector Service."""

    def log_message(self, format, *args):
        """Sanitized: strip query string from request line (議題 #6, 2026-04-28).

        log_request 路徑會以 format='"%s" %s %s', args=(request_line, code, size)
        呼叫；request_line 形如 'GET /search?q=<sensitive> HTTP/1.1'。此處將
        path 的 query string 截掉，其他 log 路徑（log_error / 直呼 log_message）
        不變。Parse 失敗 fail-open 保留原行為。
        """
        sanitized_args = args
        if format == '"%s" %s %s' and args:
            try:
                request_line = args[0]
                if isinstance(request_line, str):
                    parts = request_line.split(' ', 2)
                    if len(parts) >= 2:
                        method = parts[0]
                        path_clean = parts[1].split('?', 1)[0]
                        http_ver = parts[2] if len(parts) > 2 else 'HTTP/1.1'
                        sanitized_args = (f'{method} {path_clean} {http_ver}',) + tuple(args[1:])
            except Exception:
                sanitized_args = args  # fail-open
        try:
            msg = format % sanitized_args
        except Exception:
            msg = format  # fail-open: even formatting failure must not crash
        print(f"[service] {self.client_address[0]} - {msg}", file=sys.stderr)

    def handle_one_request(self):
        """Override to catch ConnectionAbortedError / BrokenPipeError."""
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # Client disconnected mid-response — safe to ignore
            pass

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, message: str):
        self._send_json({"error": message}, status)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b""

    def _parse_json_body(self) -> Optional[Dict]:
        try:
            body = self._read_body()
            return json.loads(body) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # ── Route dispatcher ──

    def do_GET(self):
        global _request_count
        _request_count += 1

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        routes = {
            "/search": self._handle_search,
            "/search/ranked": self._handle_search_ranked,
            "/search/ranked-sections": self._handle_search_ranked_sections,
            "/search/episodic": self._handle_search_episodic,
            "/health": self._handle_health,
            "/status": self._handle_status,
        }

        handler = routes.get(path)
        if handler:
            try:
                handler(params)
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                self._send_error(500, str(e))
        else:
            self._send_error(404, f"Not found: {path}")

    def do_POST(self):
        global _request_count
        _request_count += 1

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        routes = {
            "/index": self._handle_index,
            "/index/incremental": self._handle_index_incremental,
            "/reload": self._handle_reload,
            "/shutdown": self._handle_shutdown,
            # Phase 3 endpoints
            "/search/enhanced": self._handle_search_enhanced,
            "/rerank": self._handle_rerank,
            "/extract": self._handle_extract,
        }

        handler = routes.get(path)
        if handler:
            try:
                handler()
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                self._send_error(500, str(e))
        else:
            self._send_error(404, f"Not found: {path}")

    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── GET handlers ──

    def _handle_search(self, params: Dict):
        q = params.get("q", [""])[0]
        if not q:
            self._send_error(400, "Missing query parameter 'q'")
            return

        top_k = int(params.get("top_k", [str(_config.get("search_top_k", 5))])[0])
        min_score = float(params.get("min_score", [str(_config.get("search_min_score", 0.65))])[0])
        layer = params.get("layer", ["all"])[0]
        user = params.get("user", [""])[0] or None
        roles_raw = params.get("roles", [""])[0]
        roles = [r.strip() for r in roles_raw.split(",") if r.strip()] or None

        results = search(
            query=q,
            config=_config,
            top_k=top_k,
            min_score=min_score,
            layer_filter=layer if layer != "all" else None,
            embedder=_embedder,
            user=user,
            roles=roles,
        )
        self._send_json(results)

    def _handle_search_ranked(self, params: Dict):
        """GET /search/ranked?q=...&intent=general&top_k=5&min_score=0.50&user=&roles="""
        q = params.get("q", [""])[0]
        if not q:
            self._send_error(400, "Missing query parameter 'q'")
            return

        intent = params.get("intent", ["general"])[0]
        top_k = int(params.get("top_k", [str(_config.get("search_top_k", 5))])[0])
        min_score = float(params.get("min_score", ["0.50"])[0])
        layer = params.get("layer", ["all"])[0]
        user = params.get("user", [""])[0] or None
        roles_raw = params.get("roles", [""])[0]
        roles = [r.strip() for r in roles_raw.split(",") if r.strip()] or None

        results = ranked_search(
            query=q,
            config=_config,
            intent=intent,
            top_k=top_k,
            min_score=min_score,
            layer_filter=layer if layer != "all" else None,
            embedder=_embedder,
            user=user,
            roles=roles,
        )
        self._send_json(results)

    def _handle_search_ranked_sections(self, params: Dict):
        """GET /search/ranked-sections?q=...&intent=general&top_k=5&max_sections=3&user=&roles="""
        q = params.get("q", [""])[0]
        if not q:
            self._send_error(400, "Missing query parameter 'q'")
            return

        intent = params.get("intent", ["general"])[0]
        top_k = int(params.get("top_k", [str(_config.get("search_top_k", 5))])[0])
        max_sections = int(params.get("max_sections", ["3"])[0])
        min_score = float(params.get("min_score", ["0.50"])[0])
        layer = params.get("layer", ["all"])[0]
        user = params.get("user", [""])[0] or None
        roles_raw = params.get("roles", [""])[0]
        roles = [r.strip() for r in roles_raw.split(",") if r.strip()] or None

        results = ranked_search_sections(
            query=q,
            config=_config,
            intent=intent,
            top_k=top_k,
            max_sections=max_sections,
            min_score=min_score,
            layer_filter=layer if layer != "all" else None,
            embedder=_embedder,
            user=user,
            roles=roles,
        )
        self._send_json(results)

    def _handle_search_episodic(self, params: Dict):
        """GET /search/episodic?q=...&top_k=3&min_score=0.35

        Search only episodic atoms for session context injection.
        Enriches results with summary from atom files.
        """
        q = params.get("q", [""])[0]
        if not q:
            self._send_error(400, "Missing query parameter 'q'")
            return

        top_k = int(params.get("top_k", ["3"])[0])
        min_score = float(params.get("min_score", ["0.35"])[0])

        results = episodic_search(
            query=q,
            config=_config,
            top_k=top_k,
            min_score=min_score,
            embedder=_embedder,
        )

        # Enrich each result with summary + triggers from the atom file
        # V2.20: use wg_paths for path resolution
        from wg_paths import MEMORY_DIR as _mem_dir, discover_all_project_memory_dirs
        _proj_dir_map = {s: d for s, d in discover_all_project_memory_dirs()}
        for r in results:
            file_path = r.get("file_path", "")
            layer = r.get("layer", "global")
            if not file_path:
                continue
            if layer.startswith("project:"):
                slug = layer.split(":", 1)[1]
                abs_path = _proj_dir_map.get(slug, _mem_dir) / file_path
            else:
                abs_path = _mem_dir / file_path
            if not abs_path.exists():
                continue
            try:
                text = abs_path.read_text(encoding="utf-8-sig")
                # Extract ## 摘要 section (compact summary)
                import re
                summary_m = re.search(
                    r"^## 摘要\s*\n(.+?)(?=\n## |\Z)",
                    text, re.MULTILINE | re.DOTALL,
                )
                r["summary"] = summary_m.group(1).strip()[:200] if summary_m else ""
                # Extract triggers
                trigger_m = re.search(r"^- Trigger:\s*(.+)", text, re.MULTILINE)
                r["triggers"] = [t.strip() for t in trigger_m.group(1).split(",") if t.strip()] if trigger_m else []
                # Extract Created date
                created_m = re.search(r"^- Created:\s*(\S+)", text, re.MULTILINE)
                r["created"] = created_m.group(1) if created_m else r.get("last_used", "")
            except (OSError, UnicodeDecodeError):
                pass

        self._send_json(results)

    def _handle_health(self, params: Dict):
        self._send_json({
            "status": "ok",
            "embedder": _embedder.__class__.__name__ if _embedder else "none",
            "uptime_seconds": round(time.time() - _start_time, 1),
        })

    def _handle_status(self, params: Dict):
        index_status = get_index_status(_config)
        result = {
            "service": {
                "uptime_seconds": round(time.time() - _start_time, 1),
                "requests_served": _request_count,
                "embedder": _embedder.__class__.__name__ if _embedder else "none",
                "port": _config.get("service_port", 3849),
            },
            "index": index_status,
            "config": {
                "embedding_backend": _config.get("embedding_backend"),
                "embedding_model": _config.get("embedding_model"),
                "search_top_k": _config.get("search_top_k"),
                "search_min_score": _config.get("search_min_score"),
            },
        }
        if _index_status:
            result["index_job"] = _index_status
        self._send_json(result)

    # ── POST handlers ──

    def _handle_index(self):
        self._start_index_background(incremental=False)

    def _handle_index_incremental(self):
        self._start_index_background(incremental=True)

    def _start_index_background(self, incremental: bool):
        global _index_status
        if _index_lock.locked():
            self._send_json({"status": "already_running", "current": _index_status})
            return
        _index_status = {"running": True, "incremental": incremental, "started_at": time.time()}

        def _run():
            global _index_status
            with _index_lock:
                try:
                    stats = build_index(_config, incremental=incremental, verbose=True)
                    _index_status = {"running": False, "result": stats, "finished_at": time.time()}
                except Exception as e:
                    _index_status = {"running": False, "error": str(e), "finished_at": time.time()}

        threading.Thread(target=_run, daemon=True).start()
        self._send_json({"status": "started", "incremental": incremental})

    def _handle_reload(self):
        global _config, _embedder
        _config = load_config()
        # Clear ollama_client singleton so new config (e.g. rdchat backend) takes effect
        try:
            TOOLS_DIR = SERVICE_DIR.parent
            if str(TOOLS_DIR) not in sys.path:
                sys.path.insert(0, str(TOOLS_DIR))
            import ollama_client
            ollama_client._client_instance = None
        except Exception:
            pass
        try:
            _embedder = create_embedder(_config)
        except Exception as e:
            self._send_error(500, f"Failed to reload embedder: {e}")
            return
        self._send_json({"status": "reloaded", "embedder": _embedder.__class__.__name__})

    def _handle_shutdown(self):
        self._send_json({"status": "shutting_down"})
        threading.Timer(0.5, lambda: os._exit(0)).start()

    # ── Phase 3 placeholders ──

    def _handle_search_enhanced(self):
        body = self._parse_json_body()
        if not body or "q" not in body:
            self._send_error(400, "Missing 'q' in body")
            return
        try:
            from reranker import enhanced_search
            results = enhanced_search(body["q"], _config, _embedder, top_k=body.get("top_k", 5))
            self._send_json(results)
        except ImportError:
            self._send_error(501, "reranker module not available")
        except Exception as e:
            self._send_error(500, str(e))

    def _handle_rerank(self):
        body = self._parse_json_body()
        if not body or "q" not in body:
            self._send_error(400, "Missing 'q' in body")
            return
        try:
            from reranker import rerank
            results = rerank(body["q"], _config, _embedder, candidates=body.get("candidates"))
            self._send_json(results)
        except ImportError:
            self._send_error(501, "reranker module not available")
        except Exception as e:
            self._send_error(500, str(e))

    def _handle_extract(self):
        body = self._parse_json_body()
        if not body or "text" not in body:
            self._send_error(400, "Missing 'text' in body")
            return
        try:
            from reranker import extract_knowledge
            results = extract_knowledge(body["text"], _config, _embedder)
            self._send_json(results)
        except ImportError:
            self._send_error(501, "reranker module not available")
        except Exception as e:
            self._send_error(500, str(e))


# ─── Server Startup ──────────────────────────────────────────────────────────


def run_server(port: int = 3849):
    """Start the HTTP daemon."""
    _init_service()

    server = HTTPServer(("127.0.0.1", port), VectorServiceHandler)
    print(f"[service] Memory Vector Service listening on http://127.0.0.1:{port}", file=sys.stderr)

    # Write PID file for management
    pid_file = VECTORDB_DIR / "service.pid"
    VECTORDB_DIR.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))

    def cleanup(signum=None, frame=None):
        print(f"\n[service] Shutting down...", file=sys.stderr)
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass
        server.shutdown()

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    port = 3849
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    run_server(port)
