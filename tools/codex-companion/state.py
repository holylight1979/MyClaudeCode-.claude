"""state.py — Per-session state management for Codex Companion.

State files: ~/.claude/workflow/companion-state-{session_id}.json
Assessment files: ~/.claude/workflow/companion-assessment-{session_id}.json

Atomic writes: .tmp + rename (same pattern as wg_core).
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKFLOW_DIR = Path.home() / ".claude" / "workflow"

_TZ = timezone(timedelta(hours=8))

_state_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


def _state_path(session_id: str) -> Path:
    return WORKFLOW_DIR / f"companion-state-{session_id}.json"


def _assessment_path(session_id: str) -> Path:
    return WORKFLOW_DIR / f"companion-assessment-{session_id}.json"


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON atomically via .tmp + rename."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# --- Session state ---

def new_state(session_id: str, cwd: str) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "cwd": cwd,
        "started_at": _now_iso(),
        "tool_trace": [],
        "checkpoints_triggered": [],
        "assessments_requested": 0,
        "assessments_completed": 0,
        "last_updated": _now_iso(),
    }


def read_state(session_id: str) -> Optional[Dict[str, Any]]:
    path = _state_path(session_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_state(session_id: str, state: Dict[str, Any]) -> None:
    state["last_updated"] = _now_iso()
    _atomic_write(_state_path(session_id), state)


def ensure_state(session_id: str, cwd: str = "") -> Dict[str, Any]:
    """Read existing state or create new. Thread-safe via _state_lock."""
    with _state_lock:
        st = read_state(session_id)
        if st is None:
            st = new_state(session_id, cwd)
            write_state(session_id, st)
    return st


def append_event(session_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Append a tool/event record to session state. Thread-safe."""
    with _state_lock:
        st = read_state(session_id)
        if st is None:
            st = new_state(session_id, "")
        trace = st.setdefault("tool_trace", [])

        # Keep trace bounded to avoid unbounded growth
        MAX_TRACE = 200
        if len(trace) >= MAX_TRACE:
            trace[:] = trace[-(MAX_TRACE // 2):]

        event["timestamp"] = _now_iso()
        trace.append(event)
        write_state(session_id, st)
    return st


def record_checkpoint(session_id: str, checkpoint_type: str) -> None:
    """Record that a checkpoint was triggered. Thread-safe."""
    with _state_lock:
        st = read_state(session_id)
        if st is None:
            st = new_state(session_id, "")
        st.setdefault("checkpoints_triggered", []).append({
            "type": checkpoint_type,
            "at": _now_iso(),
        })
        st["assessments_requested"] = st.get("assessments_requested", 0) + 1
        write_state(session_id, st)


# --- Assessment cache ---

def write_assessment(session_id: str, assessment: Dict[str, Any]) -> None:
    """Write assessment result for pickup by UserPromptSubmit hook. Thread-safe."""
    with _state_lock:
        data = {
            "session_id": session_id,
            "assessment": assessment,
            "created_at": _now_iso(),
            "injected": False,
        }
        _atomic_write(_assessment_path(session_id), data)

        # Also update state counter (within same lock to prevent race with append_event)
        st = read_state(session_id)
        if st:
            st["assessments_completed"] = st.get("assessments_completed", 0) + 1
            write_state(session_id, st)


def read_assessment(session_id: str) -> Optional[Dict[str, Any]]:
    """Read pending assessment. Returns None if no assessment or already injected."""
    path = _assessment_path(session_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    if data.get("injected", False):
        return None

    return data.get("assessment")


def mark_assessment_injected(session_id: str) -> None:
    """Mark assessment as injected so it won't be re-injected."""
    path = _assessment_path(session_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["injected"] = True
        _atomic_write(path, data)
    except (json.JSONDecodeError, OSError):
        pass


def cleanup(session_id: str) -> None:
    """Remove state and assessment files for a session."""
    for path in [_state_path(session_id), _assessment_path(session_id)]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
