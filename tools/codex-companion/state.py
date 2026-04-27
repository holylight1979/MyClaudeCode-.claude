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
        "turn_index": 0,
        "last_assistant_tail": "",
        "last_updated": _now_iso(),
    }


def increment_turn(session_id: str) -> int:
    """Increment turn_index and return new value. Thread-safe."""
    with _state_lock:
        st = read_state(session_id)
        if st is None:
            st = new_state(session_id, "")
        st["turn_index"] = int(st.get("turn_index", 0)) + 1
        write_state(session_id, st)
        return st["turn_index"]


def update_last_assistant_tail(session_id: str, text: str) -> None:
    """Persist last assistant tail for assessor context. Thread-safe."""
    with _state_lock:
        st = read_state(session_id)
        if st is None:
            st = new_state(session_id, "")
        st["last_assistant_tail"] = (text or "")[:2000]
        write_state(session_id, st)


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


# --- Assessment cache (per-turn-id) ---

def _assessment_turn_path(session_id: str, turn_index: int, assessment_type: str) -> Path:
    return WORKFLOW_DIR / f"companion-assessment-{session_id}-t{turn_index}-{assessment_type}.json"


def write_assessment(
    session_id: str,
    turn_index: int,
    assessment_type: str,
    assessment: Dict[str, Any],
) -> None:
    """Write assessment result for pickup by UserPromptSubmit hook. Thread-safe.

    Per-turn-id naming: companion-assessment-{sid}-t{N}-{type}.json
    """
    with _state_lock:
        data = {
            "session_id": session_id,
            "turn_index": turn_index,
            "type": assessment_type,
            "assessment": assessment,
            "created_at": _now_iso(),
            "injected": False,
        }
        _atomic_write(_assessment_turn_path(session_id, turn_index, assessment_type), data)

        # Also update state counter (within same lock to prevent race with append_event)
        st = read_state(session_id)
        if st:
            st["assessments_completed"] = st.get("assessments_completed", 0) + 1
            write_state(session_id, st)


def list_pending_assessments(session_id: str) -> List[Dict[str, Any]]:
    """List all not-yet-injected assessments for a session, sorted by turn_index ASC.

    Each entry: {"path": Path, "turn_index": int, "type": str, "data": dict}
    """
    pending = []
    pattern = f"companion-assessment-{session_id}-t*.json"
    for path in WORKFLOW_DIR.glob(pattern):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("injected", False):
            continue
        assessment = data.get("assessment", {})
        if not assessment or assessment.get("status") == "error":
            continue
        pending.append({
            "path": path,
            "turn_index": int(data.get("turn_index", 0)),
            "type": data.get("type", assessment.get("_assessment_type", "review")),
            "data": data,
        })
    pending.sort(key=lambda x: (x["turn_index"], x["type"]))
    return pending


def mark_assessment_path_injected(path: Path) -> None:
    """Mark a specific assessment file as injected."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["injected"] = True
        _atomic_write(path, data)
    except (json.JSONDecodeError, OSError):
        pass


def cleanup(session_id: str) -> None:
    """Remove state, metrics and per-turn assessment files for a session."""
    paths: List[Path] = [_state_path(session_id), _metrics_path(session_id)]
    paths.extend(WORKFLOW_DIR.glob(f"companion-assessment-{session_id}-t*.json"))
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# --- Sprint 4 Phase 5：observability metrics（獨立檔避免與 state 競爭寫入）---

def _metrics_path(session_id: str) -> Path:
    return WORKFLOW_DIR / f"companion-metrics-{session_id}.json"


_METRIC_KEYS = (
    "audits_skipped_by_score",
    "empty_returns",
    "sandbox_failures",
    "behavior_gap_blocks",
    "quality_gap_advises",
)


def increment_metric(session_id: str, name: str, delta: int = 1) -> None:
    """Increment a per-session counter. Best-effort, fail-silent.

    跨 process（hook + service）有微小 race window，但對觀測指標來說
    遺失 1-2 次累加可接受。獨立檔 companion-metrics-{sid}.json 避免污染
    主 state（service 主寫入路徑）。
    """
    if name not in _METRIC_KEYS:
        return
    path = _metrics_path(session_id)
    with _state_lock:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        data[name] = int(data.get(name, 0)) + delta
        try:
            _atomic_write(path, data)
        except OSError:
            pass


def read_metrics(session_id: str) -> Dict[str, int]:
    """Read all metric counters for a session (zero defaults for未累加項)。"""
    path = _metrics_path(session_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return {k: int(data.get(k, 0)) for k in _METRIC_KEYS}
