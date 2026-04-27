"""codex_companion.py — Thin hook for Codex Companion integration.

Dispatches Claude Code hook events to the companion HTTP service.
Fast path: config disabled → exit(0) immediately (< 1ms).

Events handled:
  SessionStart    → ensure service, POST /event
  UserPromptSubmit → read assessment file → inject additionalContext
  PostToolUse     → POST /event, checkpoint detection
  Stop            → POST /event, heuristic soft gate, trigger turn audit
  SessionEnd      → POST /event
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

CLAUDE_DIR = Path.home() / ".claude"
WORKFLOW_DIR = CLAUDE_DIR / "workflow"
CONFIG_PATH = WORKFLOW_DIR / "config.json"
COMPANION_DIR = CLAUDE_DIR / "tools" / "codex-companion"

# Add companion dir to path for heuristics import
sys.path.insert(0, str(COMPANION_DIR))
sys.path.insert(0, str(CLAUDE_DIR / "hooks"))


# ─── Config ──────────────────────────────────────────────────────────────────


def _load_config() -> Dict[str, Any]:
    try:
        full = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return full.get("codex_companion", {})
    except (json.JSONDecodeError, OSError):
        return {}


# ─── HTTP helpers ────────────────────────────────────────────────────────────


def _http_post(port: int, path: str, data: Dict[str, Any], timeout: float = 0.5) -> Optional[Dict]:
    """POST JSON to companion service. Returns parsed response or None on failure."""
    try:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _http_get(port: int, path: str, timeout: float = 0.5) -> Optional[Dict]:
    """GET from companion service. Returns parsed response or None on failure."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


# ─── Service lifecycle ───────────────────────────────────────────────────────


def _is_service_running(port: int) -> bool:
    """Quick check: is something listening on the companion port?"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def _ensure_service(config: Dict[str, Any]) -> None:
    """Start companion service if not running."""
    port = config.get("service_port", 3850)

    # Health check first
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health", method="GET")
        with urllib.request.urlopen(req, timeout=1):
            return  # Already running
    except Exception:
        pass

    # Port guard
    if _is_service_running(port):
        return  # Port occupied, likely starting up

    service_path = COMPANION_DIR / "service.py"
    if not service_path.exists():
        return

    try:
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        CREATE_BREAKAWAY_FROM_JOB = 0x01000000

        log_path = CLAUDE_DIR / "Logs" / "codex-companion.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(str(log_path), "a")

        try:
            kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": log_fh,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB

            subprocess.Popen([sys.executable, str(service_path)], **kwargs)
        except Exception:
            log_fh.close()
            raise
    except Exception:
        pass  # Fail silently — companion is optional


# ─── Output helpers (same protocol as workflow-guardian) ──────────────────────


def _output_json(data: Dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False))
    sys.exit(0)


def _output_context(event_name: str, text: str) -> None:
    _output_json({
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    })


def _output_block(reason: str) -> None:
    _output_json({"decision": "block", "reason": reason})


def _output_nothing() -> None:
    sys.exit(0)


# ─── Stop-text helpers (三層 fallback) ───────────────────────────────────────


def _get_last_assistant_tail(input_data: Dict[str, Any]) -> str:
    """Stop hook 文本三層 fallback：
    1. input_data["last_assistant_message"]（若 ClaudeCode 提供）
    2. 自寫 transcript jsonl tail parser（不過長度過濾，不放掉「已完成。」「Done.」短句）
    3. wg_evasion.get_last_assistant_text()（>30 字過濾）作兜底
    """
    # Layer 1
    direct = input_data.get("last_assistant_message", "")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()[:2000]

    transcript_path = input_data.get("transcript_path", "")
    if transcript_path:
        # Layer 2: own jsonl tail parser, no length filter
        try:
            last = ""
            with open(transcript_path, "r", encoding="utf-8") as f:
                for raw in f:
                    try:
                        obj = json.loads(raw)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if obj.get("type") != "assistant":
                        continue
                    content = obj.get("message", {}).get("content", [])
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            t = block.get("text", "")
                            if t:
                                last = t
            if last:
                return last[:2000]
        except (OSError, UnicodeDecodeError):
            pass

        # Layer 3: wg_evasion fallback (filters short text)
        try:
            import wg_evasion
            tail = wg_evasion.get_last_assistant_text(Path(transcript_path))
            if tail:
                return tail[:2000]
        except Exception:
            pass

    return ""


def _summarize_tool_response(tool_response: Any) -> tuple[str, bool]:
    """Phase 1.1+1.2：
    - 從 tool_response 取 stdout/stderr 截 300 字組摘要
    - 偵測失敗訊號 (error / exit_code != 0 / stderr / is_error) → prefix [FAILED]
    回傳 (summary, failed)
    """
    if not isinstance(tool_response, dict):
        text = str(tool_response or "")
        return text[:300], False

    stdout = tool_response.get("stdout", "") or tool_response.get("output", "")
    stderr = tool_response.get("stderr", "")
    error = tool_response.get("error", "")
    exit_code = tool_response.get("exit_code", tool_response.get("returncode", 0))
    is_error = bool(tool_response.get("is_error", False))

    failed = (
        bool(error)
        or bool(stderr and str(stderr).strip())
        or (isinstance(exit_code, int) and exit_code != 0)
        or is_error
    )

    parts: list[str] = []
    if stdout:
        parts.append(f"stdout: {str(stdout)[:200]}")
    if stderr:
        parts.append(f"stderr: {str(stderr)[:200]}")
    if error:
        parts.append(f"error: {str(error)[:200]}")
    summary = " | ".join(parts)[:300] if parts else ""

    if failed and summary:
        summary = f"[FAILED] {summary}"
    elif failed:
        summary = "[FAILED] (no detail)"

    return summary, failed


def _build_verification_signals(input_data: Dict[str, Any], tool_response: Any) -> Dict[str, Any]:
    """Phase 1.5：給 codex 的最小化 verification_signals 包。"""
    sig: Dict[str, Any] = {
        "tool_name": input_data.get("tool_name", ""),
    }
    if isinstance(tool_response, dict):
        for k in ("exit_code", "returncode", "is_error"):
            if k in tool_response:
                sig[k] = tool_response[k]
    return sig


# ─── Event handlers ──────────────────────────────────────────────────────────


def handle_session_start(input_data: Dict[str, Any], config: Dict[str, Any]):
    port = config.get("service_port", 3850)
    session_id = input_data.get("session_id", "")

    _ensure_service(config)

    # Give service a moment to start, then post event
    _http_post(port, "/event", {
        "session_id": session_id,
        "type": "session_start",
        "cwd": input_data.get("cwd", ""),
    }, timeout=1.0)

    _output_nothing()


def handle_user_prompt_submit(input_data: Dict[str, Any], config: Dict[str, Any]):
    """Inject pending per-turn Codex assessments as additionalContext.

    Phase 1.8：drain 改成掃 companion-assessment-{sid}-t*.json glob，
    依 turn_index 排序，未 inject 的依序合併注入（最多 3 件以控 token）。
    """
    session_id = input_data.get("session_id", "")
    if not session_id:
        _output_nothing()

    pattern = f"companion-assessment-{session_id}-t*.json"
    paths = sorted(WORKFLOW_DIR.glob(pattern))
    if not paths:
        _output_nothing()

    pending: list[tuple[int, str, Path, Dict[str, Any]]] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("injected", False):
            continue
        assessment = data.get("assessment") or {}
        if not assessment or assessment.get("status") == "error":
            # Mark error assessments injected so they don't pile up forever
            try:
                data["injected"] = True
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                tmp.replace(path)
            except OSError:
                pass
            continue
        turn_index = int(data.get("turn_index", 0))
        atype = data.get("type", assessment.get("_assessment_type", "review"))
        pending.append((turn_index, atype, path, data))

    if not pending:
        _output_nothing()

    pending.sort(key=lambda x: (x[0], x[1]))
    pending = pending[:3]

    type_label_map = {
        "plan_review": "Plan Review",
        "turn_audit": "Turn Audit",
        "architecture_review": "Architecture Review",
    }

    blocks: list[str] = []
    for turn_index, atype, path, data in pending:
        assessment = data.get("assessment", {})
        type_label = type_label_map.get(atype, "Review")
        severity = assessment.get("severity", "low")
        status = assessment.get("status", "ok")
        summary = assessment.get("summary", "")
        action = assessment.get("recommended_action", "")
        corrective = assessment.get("corrective_prompt", "")

        lines = [
            f"[Codex Companion: {type_label} t{turn_index}] status={status} severity={severity}"
        ]
        if summary:
            lines.append(f"摘要：{summary}")
        if action:
            lines.append(f"建議：{action}")
        if corrective:
            lines.append(f"修正提示：{corrective}")
        blocks.append("\n".join(lines))

        # Mark injected
        try:
            data["injected"] = True
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    context_text = "\n\n".join(blocks)
    # Token budget guard: ~600 chars Chinese ≈ 300 tokens per block，整體 cap 1800
    if len(context_text) > 1800:
        context_text = context_text[:1800] + "…(截斷)"

    _output_context("UserPromptSubmit", context_text)


def handle_post_tool_use(input_data: Dict[str, Any], config: Dict[str, Any]):
    """Accumulate events + delegate checkpoint detection to service.

    Phase 0.4：不再 hook 端讀 state，信任 service /event response 的
    should_trigger_checkpoint 旗標。
    Phase 1.1+1.2：tool_response 抽 stdout/stderr + 失敗訊號偵測。
    """
    port = config.get("service_port", 3850)
    session_id = input_data.get("session_id", "")
    tool_name = input_data.get("tool_name", "")

    if not session_id:
        _output_nothing()

    # Extract tool info
    tool_input = input_data.get("tool_input", "")
    if isinstance(tool_input, dict):
        file_path = tool_input.get("file_path", "")
        input_summary = file_path or json.dumps(tool_input, ensure_ascii=False)[:200]
    elif isinstance(tool_input, str):
        file_path = ""
        input_summary = tool_input[:200]
    else:
        file_path = ""
        input_summary = str(tool_input)[:200]

    tool_response = input_data.get("tool_response", "")
    output_summary, failed = _summarize_tool_response(tool_response)

    event_data = {
        "session_id": session_id,
        "type": "tool_use",
        "tool_name": tool_name,
        "tool_input_summary": input_summary,
        "tool_output_summary": output_summary,
        "file_path": file_path,
    }
    result = _http_post(port, "/event", event_data)

    if result:
        checkpoint = result.get("should_trigger_checkpoint")
        if checkpoint:
            verification = _build_verification_signals(input_data, tool_response)
            _http_post(port, "/trigger", {
                "session_id": session_id,
                "type": checkpoint,
                "context": {
                    "trigger_tool": tool_name,
                    "trigger_file": file_path,
                    "tool_failed": failed,
                    "verification_signals": verification,
                },
            })

    _output_nothing()


def handle_stop(input_data: Dict[str, Any], config: Dict[str, Any]):
    """Run heuristic soft gate + trigger async turn audit.

    Phase 1.3：last_assistant_tail 三層 fallback。
    Phase 1.4：tail 當 stop_text 傳入 triggered_results。
    Phase 1.5：trigger context 改送 {user_goal_hint, last_assistant_tail, verification_signals}。
    """
    port = config.get("service_port", 3850)
    session_id = input_data.get("session_id", "")

    if not session_id:
        _output_nothing()

    last_assistant_tail = _get_last_assistant_tail(input_data)

    # POST stop event with tail (service 端會 increment turn_index 並更新 state)
    _http_post(port, "/event", {
        "session_id": session_id,
        "type": "stop",
        "last_assistant_tail": last_assistant_tail,
    })

    # Run synchronous heuristic checks (no LLM, < 10ms)
    soft_gate_config = config.get("soft_gate", {})

    if soft_gate_config.get("completion_evidence", True):
        try:
            import heuristics

            guardian_state_path = WORKFLOW_DIR / f"state-{session_id}.json"
            try:
                guardian_state = json.loads(guardian_state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                guardian_state = {}

            try:
                comp_state_path = WORKFLOW_DIR / f"companion-state-{session_id}.json"
                comp_state = json.loads(comp_state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                comp_state = {}

            merged_state = {
                "modified_files": guardian_state.get("modified_files", []),
                "accessed_files": guardian_state.get("accessed_files", []),
                "tool_trace": comp_state.get("tool_trace", []),
            }

            # Phase 1.4：把 stop_text 傳入 triggered_results
            results = heuristics.triggered_results(merged_state, stop_text=last_assistant_tail)

            if results:
                max_sev = heuristics.max_severity(results)
                if max_sev == "high":
                    detail = heuristics.format_for_context(results)
                    _output_block(
                        f"Codex Companion 軟閘：偵測到高風險缺漏。\n{detail}\n"
                        "請補充驗證或修正後再收尾。"
                    )

        except Exception:
            pass  # Heuristics failure → degrade gracefully

    # Phase 1.5: trigger context 帶上下文
    user_goal_hint = ""
    try:
        guardian_state_path = WORKFLOW_DIR / f"state-{session_id}.json"
        guardian_state = json.loads(guardian_state_path.read_text(encoding="utf-8"))
        user_goal_hint = (guardian_state.get("user_goal_hint") or guardian_state.get("user_intent") or "")[:500]
    except (json.JSONDecodeError, OSError):
        pass

    _http_post(port, "/trigger", {
        "session_id": session_id,
        "type": "turn_audit",
        "context": {
            "user_goal_hint": user_goal_hint,
            "last_assistant_tail": last_assistant_tail,
            "verification_signals": {
                "stop_text_len": len(last_assistant_tail),
                "stop_text_source": "fallback_layered",
            },
        },
    })

    _output_nothing()


def handle_session_end(input_data: Dict[str, Any], config: Dict[str, Any]):
    port = config.get("service_port", 3850)
    session_id = input_data.get("session_id", "")

    _http_post(port, "/event", {
        "session_id": session_id,
        "type": "session_end",
    })

    _output_nothing()


# ─── Main dispatcher ─────────────────────────────────────────────────────────

HANDLERS = {
    "SessionStart": handle_session_start,
    "UserPromptSubmit": handle_user_prompt_submit,
    "PostToolUse": handle_post_tool_use,
    "Stop": handle_stop,
    "SessionEnd": handle_session_end,
}


def main():
    # Force UTF-8 on Windows
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")

    # Fast path: read config, check enabled
    config = _load_config()
    if not config.get("enabled", False):
        sys.exit(0)

    # Read stdin
    try:
        raw = sys.stdin.buffer.read()
        input_data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    event = input_data.get("hook_event_name", "")
    handler = HANDLERS.get(event)
    if handler is None:
        sys.exit(0)

    try:
        handler(input_data, config)
    except SystemExit:
        raise
    except Exception as e:
        # Never crash — log to stderr and exit cleanly
        print(f"[codex_companion] Error in {event}: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
