"""wg_atom_observation.py — REG-005 atom 注入觀察採樣 hook（Session 1/3, 2026-04-29）.

設計：memory/_staging/reg-005-atom-injection-refactor.md（觀察期事件驅動四重標準）

行為（flag-gated；先寫不啟動）：
- 入口檢查 `~/.claude/memory/_staging/reg-005-observation-start.flag` —
  不存在 → sys.exit(0) 立即返回（zero overhead）。
- flag 存在 → 按 hook_event_name 分派：
  - `UserPromptSubmit` → 記錄 session_id（用於四重標準 B：累計 session 數）。
    Session 1 skeleton：尚未 instrument workflow-guardian 的 atom 注入事件，
    所以 A 標準（atom 注入數）暫由 PostToolUse(Read) 路徑命中近似估算。
    Session 2 加 hot/cold 分級時補上注入端 instrumentation。
  - `PostToolUse(Read)` → 比對被讀檔路徑是否落在 `memory/**/*.md`，命中則
    視為「主動讀 atom」（cold atom 主動讀比率的近似前驅信號；C-layer 會精化）。

寫入：
- Log：`~/.claude/Logs/atom-injection-observation-YYYY-MM-DD.log`
  schema：每行 JSON `{"ts", "session_id", "event", "details"}`
- Metric：`memory/wisdom/reflection_metrics.json` 子鍵 `reg005_observation`
  schema：`{started_at, sessions, sessions_seen[], reads_in_memory, last_event_ts}`

為避免影響主管線：所有錯誤 swallow（fail-open），不寫 stderr，不阻擋。
"""

from __future__ import annotations

import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


# Windows console UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


CLAUDE_DIR = Path.home() / ".claude"
FLAG_PATH = CLAUDE_DIR / "memory" / "_staging" / "reg-005-observation-start.flag"
LOG_DIR = CLAUDE_DIR / "Logs"
METRIC_PATH = CLAUDE_DIR / "memory" / "wisdom" / "reflection_metrics.json"
MEMORY_ROOT = (CLAUDE_DIR / "memory").resolve()


def _flag_active() -> bool:
    try:
        return FLAG_PATH.exists()
    except OSError:
        return False


def _today_log_path() -> Path:
    return LOG_DIR / f"atom-injection-observation-{datetime.now().strftime('%Y-%m-%d')}.log"


def _append_log(record: Dict[str, Any]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_today_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _read_metric() -> Dict[str, Any]:
    try:
        with open(METRIC_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _write_metric_atomic(data: Dict[str, Any]) -> None:
    try:
        METRIC_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = METRIC_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(METRIC_PATH)
    except OSError:
        pass


def _ensure_obs_section(metric: Dict[str, Any]) -> Dict[str, Any]:
    obs = metric.get("reg005_observation")
    if not isinstance(obs, dict):
        obs = {}
        metric["reg005_observation"] = obs
    obs.setdefault("started_at", datetime.now().isoformat(timespec="seconds"))
    obs.setdefault("sessions", 0)
    obs.setdefault("sessions_seen", [])
    obs.setdefault("injections", 0)  # filled in Session 2 when workflow-guardian instruments
    obs.setdefault("reads_in_memory", 0)
    obs.setdefault("cold_active_reads", 0)  # filled in Session 2 with hot/cold classification
    obs.setdefault("last_event_ts", "")
    return obs


def _is_within_memory(path_str: str) -> bool:
    """Match memory/*.md robustly across Windows / MSYS2 / mixed path formats."""
    if not path_str:
        return False
    if not path_str.endswith(".md"):
        return False
    # Substring check tolerates both backslash, forward slash, and MSYS2 /c/ prefix.
    norm = path_str.replace("\\", "/").lower()
    if "/.claude/memory/" not in norm:
        return False
    # Best-effort resolve check (defensive against /memory/ false positives elsewhere)
    try:
        p = Path(path_str).resolve()
        p.relative_to(MEMORY_ROOT)
        return True
    except (OSError, ValueError):
        # Resolve failed (MSYS2 path on Windows Python) — substring already validated
        return True


def _handle_user_prompt_submit(payload: Dict[str, Any]) -> None:
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return
    metric = _read_metric()
    obs = _ensure_obs_section(metric)
    seen = obs.get("sessions_seen", [])
    if not isinstance(seen, list):
        seen = []
    if session_id not in seen:
        seen.append(session_id)
        obs["sessions_seen"] = seen
        obs["sessions"] = len(seen)
    obs["last_event_ts"] = datetime.now().isoformat(timespec="seconds")
    _write_metric_atomic(metric)
    _append_log({
        "ts": obs["last_event_ts"],
        "session_id": session_id,
        "event": "session_seen",
        "details": {"sessions": obs["sessions"]},
    })


def _handle_post_tool_use_read(payload: Dict[str, Any]) -> None:
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not _is_within_memory(file_path):
        return
    session_id = str(payload.get("session_id") or "")
    metric = _read_metric()
    obs = _ensure_obs_section(metric)
    obs["reads_in_memory"] = int(obs.get("reads_in_memory", 0)) + 1
    obs["last_event_ts"] = datetime.now().isoformat(timespec="seconds")
    _write_metric_atomic(metric)
    _append_log({
        "ts": obs["last_event_ts"],
        "session_id": session_id,
        "event": "memory_read",
        "details": {"path": file_path, "reads_in_memory": obs["reads_in_memory"]},
    })


def _today_injection_log_path() -> Path:
    return LOG_DIR / f"atom-injection-injections-{datetime.now().strftime('%Y-%m-%d')}.log"


def log_injection(
    session_id: str,
    name: str,
    classification: str,
    source: str,
) -> None:
    """Append injection record to atom-injection-injections-YYYY-MM-DD.log.

    Flag-gated（讀 FLAG_PATH 同既有 _flag_active()）。flag 不存在 → 立即 return。
    fail-open — 任何 OSError / encode error 不 raise，沉默吞掉。

    Schema (one JSON per line):
    {"ts": ISO8601_seconds, "session_id": str, "name": str,
     "classification": str, "source": str, "event": "atom_injected"}
    """
    if not _flag_active():
        return
    try:
        rec = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "session_id": session_id,
            "name": name,
            "classification": classification,
            "source": source,
            "event": "atom_injected",
        }
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_today_injection_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass


def main() -> None:
    # Flag-gate first — zero overhead when not active.
    if not _flag_active():
        sys.exit(0)

    try:
        raw = sys.stdin.buffer.read()
        if not raw:
            sys.exit(0)
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    event = payload.get("hook_event_name") or ""
    try:
        if event == "UserPromptSubmit":
            _handle_user_prompt_submit(payload)
        elif event == "PostToolUse":
            tool_name = (payload.get("tool_name") or "").strip()
            if tool_name == "Read":
                _handle_post_tool_use_read(payload)
    except Exception:
        # Fail-open — never break the hook chain.
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
