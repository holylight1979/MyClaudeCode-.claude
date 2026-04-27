"""service.py — Codex Companion HTTP Daemon.

stdlib http.server, port 3850 (configurable).
Receives hook events, manages per-session state, triggers async Codex assessments.

啟動: pythonw service.py  (Windows 背景)
      python service.py   (前景, 看 log)
"""

from __future__ import annotations

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

# Path setup
SERVICE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_DIR))
sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))

import state as companion_state
import heuristics as _heur  # 共用 _ARCH_FILE_RE，避免三處 regex drift

# Service-side checkpoint detection (Phase 0.5: hook trusts response.should_trigger_checkpoint)
_PLAN_TOOLS = {"ExitPlanMode", "EnterPlanMode"}
_WRITE_TOOLS = {"Edit", "Write"}


def _detect_checkpoint(tool_name: str, file_path: str) -> Optional[str]:
    """Determine if this tool use triggers a checkpoint.

    Phase 1.5: 砍 quick_plan 啟發式（連續 read-only 後首次 Edit）。
    只保留：(1) 顯式 ExitPlanMode/EnterPlanMode → plan_review
            (2) 結構性檔案 Edit/Write → architecture_review，
                **且** `_config.soft_gate.architecture_review` 為 true 才觸發
                （Sprint 3 fix：原本忽略 config 開關，導致 architecture_review=false
                時仍會打 codex）
    """
    if tool_name in _PLAN_TOOLS:
        return "plan_review"
    if (tool_name in _WRITE_TOOLS and file_path
            and _heur._ARCH_FILE_RE.search(file_path)
            and _config.get("soft_gate", {}).get("architecture_review", False)):
        return "architecture_review"
    return None

# Lazy import assessor (may not exist during early development)
_assessor = None


def _get_assessor():
    global _assessor
    if _assessor is None:
        try:
            import assessor as _mod
            _assessor = _mod
        except ImportError:
            pass
    return _assessor


# ─── Globals ─────────────────────────────────────────────────────────────────

_start_time = 0.0
_request_count = 0
_pending_assessments: Dict[str, threading.Thread] = {}
_shutdown_event = threading.Event()
_config: Dict[str, Any] = {}

WORKFLOW_DIR = Path.home() / ".claude" / "workflow"
PID_FILE = WORKFLOW_DIR / "companion.pid"


def _load_config() -> Dict[str, Any]:
    """Load codex_companion section from workflow config."""
    config_path = WORKFLOW_DIR / "config.json"
    try:
        full = json.loads(config_path.read_text(encoding="utf-8"))
        return full.get("codex_companion", {})
    except (json.JSONDecodeError, OSError):
        return {}


def _write_pid():
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def _remove_pid():
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# ─── Assessment Worker ───────────────────────────────────────────────────────


def _run_assessment(
    session_id: str,
    turn_index: int,
    assessment_type: str,
    context: Dict[str, Any],
):
    """Run Codex assessment in background thread. Result written to per-turn file.

    Sprint 3 Phase 4.3：state 內已有的 last_assistant_tail / turn_index 由 service
    端注入 extra_context，避免 assessor 再次 IO 讀 state（已被 daemon thread 隔離）。
    """
    try:
        mod = _get_assessor()
        if mod is None:
            companion_state.write_assessment(session_id, turn_index, assessment_type, {
                "status": "error",
                "severity": "low",
                "category": "system",
                "summary": "Assessor module not available.",
            })
            return

        # Read companion state for context
        st = companion_state.read_state(session_id) or {}
        cwd = st.get("cwd", context.get("cwd", ""))

        # Sprint 3：合併 service-side state 已知欄位到 extra_context
        # context 內已有的鍵不覆蓋（hook 端可能傳更新版）
        merged_context = dict(context or {})
        merged_context.setdefault("turn_index", turn_index)
        if "last_assistant_tail" not in merged_context:
            merged_context["last_assistant_tail"] = st.get("last_assistant_tail", "")

        result = mod.run_assessment(
            assessment_type=assessment_type,
            session_id=session_id,
            tool_trace=st.get("tool_trace", []),
            cwd=cwd,
            extra_context=merged_context,
            config=_config,
        )
        result["_turn_index"] = turn_index

        # Phase 5 觀測：依分類結果累加計數
        category = str(result.get("category", "")).lower()
        summary = str(result.get("summary", ""))
        if category == "system" and "sandbox" in summary:
            companion_state.increment_metric(session_id, "sandbox_failures")
        elif result.get("notify_next_turn"):
            # 非 sandbox 的失敗回退（含 timeout / FileNotFoundError）皆視為 empty_returns
            companion_state.increment_metric(session_id, "empty_returns")

        companion_state.write_assessment(session_id, turn_index, assessment_type, result)
        _log(
            f"Assessment completed: {session_id[:8]} t{turn_index} "
            f"type={assessment_type} status={result.get('status')} attempts={result.get('_attempts', 1)}"
        )

    except Exception as e:
        _log(f"Assessment error: {e}")
        companion_state.write_assessment(session_id, turn_index, assessment_type, {
            "status": "error",
            "severity": "low",
            "category": "system",
            "summary": f"Assessment failed: {e}",
        })


def _trigger_assessment(session_id: str, assessment_type: str, context: Dict[str, Any]):
    """Spawn background thread for assessment. Non-blocking.

    Dedup key: session_id:turn_index:type — same turn+type already running → skip.
    """
    st = companion_state.read_state(session_id) or {}
    turn_index = int(st.get("turn_index", 0))

    key = f"{session_id}:{turn_index}:{assessment_type}"

    existing = _pending_assessments.get(key)
    if existing and existing.is_alive():
        _log(f"Assessment already running: {key}")
        return

    companion_state.record_checkpoint(session_id, assessment_type)

    t = threading.Thread(
        target=_run_assessment,
        args=(session_id, turn_index, assessment_type, context),
        daemon=True,
        name=f"assessment-{key}",
    )
    _pending_assessments[key] = t
    t.start()


# ─── Logging ─────────────────────────────────────────────────────────────────


def _log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[companion {ts}] {msg}", file=sys.stderr, flush=True)


# ─── Request Handler ─────────────────────────────────────────────────────────


class CompanionHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        _log(format % args)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}

    # ─── GET ──────────────────────────────────────────────────────────

    def do_GET(self):
        global _request_count
        _request_count += 1

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        if path == "/health":
            self._handle_health()
        elif path == "/assessment":
            sid = (params.get("session_id") or [""])[0]
            self._handle_get_assessment(sid)
        elif path == "/status":
            self._handle_status()
        else:
            self._send_json({"error": "not found"}, 404)

    def _handle_health(self):
        uptime = time.time() - _start_time
        self._send_json({
            "status": "ok",
            "uptime_seconds": round(uptime),
            "requests": _request_count,
            "pending_assessments": sum(1 for t in _pending_assessments.values() if t.is_alive()),
        })

    def _handle_get_assessment(self, session_id: str):
        if not session_id:
            self._send_json({"error": "session_id required"}, 400)
            return

        pending = companion_state.list_pending_assessments(session_id)
        if not pending:
            self._send_json({"status": "none"})
            return

        # Return earliest pending (lowest turn_index) — debugging helper only
        first = pending[0]
        self._send_json({
            "status": "available",
            "turn_index": first["turn_index"],
            "type": first["type"],
            "assessment": first["data"].get("assessment"),
            "pending_count": len(pending),
        })

    def _handle_status(self):
        self._send_json({
            "enabled": _config.get("enabled", False),
            "model": _config.get("model", "o3"),
            "uptime_seconds": round(time.time() - _start_time),
            "requests": _request_count,
            "active_threads": sum(1 for t in _pending_assessments.values() if t.is_alive()),
        })

    # ─── POST ─────────────────────────────────────────────────────────

    def do_POST(self):
        global _request_count
        _request_count += 1

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/event":
            self._handle_event()
        elif path == "/trigger":
            self._handle_trigger()
        elif path == "/shutdown":
            self._handle_shutdown()
        else:
            self._send_json({"error": "not found"}, 404)

    def _handle_event(self):
        """Accept hook event — fire-and-forget accumulation.

        Phase 0.5: 對 tool_use 事件，回傳 should_trigger_checkpoint 給 hook，
        避免 hook 端再讀 state file 做檢測。
        """
        body = self._read_body()
        session_id = body.get("session_id", "")
        if not session_id:
            self._send_json({"error": "session_id required"}, 400)
            return

        event_type = body.get("type", "unknown")
        should_trigger: Optional[str] = None

        if event_type == "session_start":
            companion_state.ensure_state(session_id, body.get("cwd", ""))
        elif event_type == "session_end":
            # Don't cleanup immediately — assessment might still be writing
            pass
        elif event_type == "stop":
            # Stop event：turn_index +1，並紀錄 last_assistant_tail（hook 已透三層 fallback 取得）
            tail = body.get("last_assistant_tail", "")
            if tail:
                companion_state.update_last_assistant_tail(session_id, tail)
            companion_state.increment_turn(session_id)
        else:
            tool_name = body.get("tool_name", "")
            file_path = body.get("file_path", "")
            companion_state.append_event(session_id, {
                "type": event_type,
                "tool": tool_name,
                "input": body.get("tool_input_summary", ""),
                "output_summary": body.get("tool_output_summary", ""),
                "path": file_path,
            })
            should_trigger = _detect_checkpoint(tool_name, file_path)

        self._send_json({"ok": True, "should_trigger_checkpoint": should_trigger})

    def _handle_trigger(self):
        """Trigger async Codex assessment."""
        body = self._read_body()
        session_id = body.get("session_id", "")
        assessment_type = body.get("type", "turn_audit")

        if not session_id:
            self._send_json({"error": "session_id required"}, 400)
            return

        context = body.get("context", {})
        _trigger_assessment(session_id, assessment_type, context)
        self._send_json({"ok": True, "type": assessment_type})

    def _handle_shutdown(self):
        self._send_json({"ok": True, "message": "shutting down"})
        _shutdown_event.set()


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    global _config, _start_time

    # Force UTF-8 on Windows
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")

    _config = _load_config()
    port = _config.get("service_port", 3850)
    _start_time = time.time()

    # PID management
    _write_pid()

    # Graceful shutdown on signal
    def _signal_handler(sig, frame):
        _log(f"Signal {sig} received, shutting down.")
        _shutdown_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    server = HTTPServer(("127.0.0.1", port), CompanionHandler)
    server.timeout = 1.0  # Allow checking shutdown_event every second

    _log(f"Codex Companion service started on port {port} (pid={os.getpid()})")

    try:
        while not _shutdown_event.is_set():
            server.handle_request()
    except Exception as e:
        _log(f"Server error: {e}")
    finally:
        server.server_close()
        _remove_pid()
        _log("Service stopped.")


if __name__ == "__main__":
    main()
