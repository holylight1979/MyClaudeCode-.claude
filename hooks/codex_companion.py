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


def _output_block(reason: str, session_id: str = "") -> None:
    # Phase 5 觀測：每次 BLOCK 累加 behavior_gap_blocks
    if session_id:
        try:
            import state as companion_state
            companion_state.increment_metric(session_id, "behavior_gap_blocks")
        except Exception:
            pass
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


_CONFIDENCE_LABEL = {
    "low": "低信心",
    "medium": "中信心",
    "high": "高信心",
}

_APPLIES_LABEL = {
    "next_prompt": "限本輪",
    "until_arch_change": "直到架構變動",
}


def _mark_injected(path: Path, data: Dict[str, Any]) -> None:
    try:
        data["injected"] = True
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def handle_user_prompt_submit(input_data: Dict[str, Any], config: Dict[str, Any]):
    """Inject pending per-turn Codex assessments as additionalContext.

    Phase 1.8：drain 掃 companion-assessment-{sid}-t*.json，依 turn_index 排序。
    Sprint 3 Phase 4.4：依 codex 回的 delivery 路由：
      delivery=ignore → 標 injected 略過注入（codex 自判此 turn 不打擾）
      delivery=inject → 注入文字並加 confidence + applies_until 標籤
    """
    session_id = input_data.get("session_id", "")
    if not session_id:
        _output_nothing()

    pattern = f"companion-assessment-{session_id}-t*.json"
    paths = sorted(WORKFLOW_DIR.glob(pattern))
    if not paths:
        _output_nothing()

    # 2026-04-28 改：靜默過濾門檻。預設 high；config 可調。
    # 只有同時滿足 (severity >= max_inject_severity) AND
    # (status in {error, needs_followup}) AND (corrective_prompt 非空)
    # 的 advisory 才浮上來。其他自動標 injected 落盤但不展示。
    max_inject_severity = str(config.get("max_inject_severity", "high")).lower()
    _SEV_ORDER = {"low": 0, "medium": 1, "high": 2}
    inject_threshold = _SEV_ORDER.get(max_inject_severity, 2)
    actionable_statuses = {"error", "needs_followup"}

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
            _mark_injected(path, data)  # 錯誤 assessment 標掉避免堆積
            continue

        # Sprint 3 Phase 4.4：delivery=ignore 直接標掉、不注入
        delivery = str(assessment.get("delivery", "inject")).lower()
        if delivery == "ignore":
            _mark_injected(path, data)
            continue

        # 2026-04-28：靜默過濾。低於門檻 / 非可行動狀態 / 無 corrective_prompt → 不注入
        sev = _SEV_ORDER.get(str(assessment.get("severity", "low")).lower(), 0)
        status = str(assessment.get("status", "ok")).lower()
        corrective = (assessment.get("corrective_prompt", "")
                      or assessment.get("recommended_action", ""))
        if (sev < inject_threshold
                or status not in actionable_statuses
                or not corrective):
            _mark_injected(path, data)
            try:
                import state as companion_state
                companion_state.increment_metric(session_id, "advisory_suppressed_silent")
            except Exception:
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
    notify_summaries: list[str] = []  # Phase 5.2：notify_next_turn 短訊收集
    for turn_index, atype, path, data in pending:
        assessment = data.get("assessment", {})
        type_label = type_label_map.get(atype, "Review")
        severity = assessment.get("severity", "low")
        status = assessment.get("status", "ok")
        confidence = str(assessment.get("confidence", "medium")).lower()
        conf_label = _CONFIDENCE_LABEL.get(confidence, "中信心")
        applies = str(assessment.get("applies_until", "next_prompt")).lower()
        applies_label = _APPLIES_LABEL.get(applies, "限本輪")

        summary = assessment.get("summary", "")
        evidence = assessment.get("evidence", "")
        corrective = assessment.get("corrective_prompt", "") or assessment.get("recommended_action", "")

        # Phase 5.2：assessor 在失敗回退時會帶 notify_next_turn=True
        if assessment.get("notify_next_turn"):
            notify_summaries.append(f"t{turn_index} {summary or status}")

        header = (
            f"[Codex Companion: {type_label} t{turn_index}] "
            f"status={status} severity={severity} "
            f"confidence={confidence}({conf_label}) applies={applies_label}"
        )
        lines = [header]
        if summary:
            lines.append(f"摘要：{summary}")
        if evidence:
            lines.append(f"事證：{evidence}")
        if corrective:
            lines.append(f"建議：{corrective}")
        blocks.append("\n".join(lines))

        _mark_injected(path, data)

    if not blocks:
        _output_nothing()

    # Phase 5.2：若任一 pending 帶 notify_next_turn，前置一段提醒短訊
    if notify_summaries:
        reminder = (
            "[Codex Companion 提醒] 上輪審查未取得有效回應，本輪暫退回 heuristics-only。"
            f"來源：{'; '.join(notify_summaries[:3])}"
        )
        blocks.insert(0, reminder)

    # Phase 5 觀測：累加注入次數（每實際送出 1 個 inject 即 +1）
    try:
        import state as companion_state
        companion_state.increment_metric(session_id, "quality_gap_advises", len(blocks))
    except Exception:
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
    """Run heuristic soft gate + score-gated async turn audit.

    Phase 1.3：last_assistant_tail 三層 fallback。
    Phase 1.4：tail 當 stop_text 傳入 triggered_results。
    Phase 1.5：trigger context 帶 user_goal_hint / last_assistant_tail。
    Sprint 3 Phase 3.2：
      (a) 算 score < score_threshold → 跳過 codex turn_audit
      (b) 同 turn_index + turn_audit 已落盤 assessment → dedup skip
      (c) max_audits_per_session 上限保護
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

    # ── 共用：讀 guardian + companion state，組 merged_state ─────────────
    guardian_state_path = WORKFLOW_DIR / f"state-{session_id}.json"
    try:
        guardian_state = json.loads(guardian_state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        guardian_state = {}

    comp_state_path = WORKFLOW_DIR / f"companion-state-{session_id}.json"
    try:
        comp_state = json.loads(comp_state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        comp_state = {}

    merged_state = {
        "modified_files": guardian_state.get("modified_files", []),
        "accessed_files": guardian_state.get("accessed_files", []),
        "tool_trace": comp_state.get("tool_trace", []),
        "last_assistant_tail": last_assistant_tail,
    }
    turn_index_post = int(comp_state.get("turn_index", 0))

    # ── Sprint 2：heuristic soft gate（BLOCK 權只屬 confident_completion）─
    # 2026-04-28 改：新增 silent_advisory 旗標。開啟時 heuristic 結果只計數 +
    # 落盤觀測，不 BLOCK，不打擾對話。BLOCK 路徑保留給未來「明確失敗訊號」用。
    soft_gate_config = config.get("soft_gate", {})
    silent_advisory = bool(config.get("silent_advisory", False))
    if soft_gate_config.get("completion_evidence", True):
        try:
            import heuristics
            results = heuristics.triggered_results(merged_state, stop_text=last_assistant_tail)
            if results:
                threshold = soft_gate_config.get("block_severity_threshold", "high")
                if heuristics.severity_at_or_above(results, threshold):
                    if silent_advisory:
                        # 靜默路徑：只增量 metric，不 BLOCK，不顯示給使用者
                        try:
                            import state as companion_state
                            companion_state.increment_metric(
                                session_id, "silent_advisory_suppressed"
                            )
                        except Exception:
                            pass
                    else:
                        detail = heuristics.format_for_context(results)
                        template = config.get(
                            "block_template",
                            "Codex Companion 軟閘：偵測到高風險缺漏。\n{detail}\n請補充驗證或修正後再收尾。",
                        )
                        try:
                            block_reason = template.format(detail=detail)
                        except (KeyError, IndexError):
                            block_reason = template + "\n" + detail
                        _output_block(block_reason, session_id=session_id)
        except Exception:
            pass  # Heuristics failure → degrade gracefully

    # ── Sprint 3 Phase 3.2：score gate / dedup / cap ─────────────────────
    score_threshold = int(config.get("score_threshold", 4))
    max_audits = int(config.get("max_audits_per_session", 30))

    try:
        sys.path.insert(0, str(COMPANION_DIR))
        import scorer
        score = scorer.compute_turn_score(merged_state, stop_text=last_assistant_tail)
    except Exception:
        score = 99  # 算分失敗安全預設：不抑制觸發，避免漏審查

    if score < score_threshold:
        # Phase 5 觀測
        try:
            import state as companion_state
            companion_state.increment_metric(session_id, "audits_skipped_by_score")
        except Exception:
            pass
        _output_nothing()

    # Dedup：同 turn_index + turn_audit 已落盤 → skip
    dedup_path = WORKFLOW_DIR / f"companion-assessment-{session_id}-t{turn_index_post}-turn_audit.json"
    if dedup_path.exists():
        _output_nothing()

    # max_audits_per_session cap：已落盤的 *.json 數量達上限 → skip
    existing = list(WORKFLOW_DIR.glob(f"companion-assessment-{session_id}-t*.json"))
    if len(existing) >= max_audits:
        _output_nothing()

    # ── trigger turn_audit ───────────────────────────────────────────────
    user_goal_hint = (guardian_state.get("user_goal_hint")
                      or guardian_state.get("user_intent") or "")[:500]

    # Sprint 5.5 B1：score gate 通過、所有 dedup/cap 也過、即將送 /trigger 前 +1
    # 此鍵作為 Phase 6 §四 C3「audits_skipped_by_score / audits_total_attempted > 0.7」
    # 的分母。語意：實際送出去的 codex audit 次數
    try:
        import state as companion_state
        companion_state.increment_metric(session_id, "audits_total_attempted")
    except Exception:
        pass

    _http_post(port, "/trigger", {
        "session_id": session_id,
        "type": "turn_audit",
        "context": {
            "user_goal_hint": user_goal_hint,
            "last_assistant_tail": last_assistant_tail,
            "turn_score": score,
            "verification_signals": {
                "stop_text_len": len(last_assistant_tail),
                "stop_text_source": "fallback_layered",
            },
        },
    })

    _output_nothing()


def _flush_metrics_to_reflection(session_id: str) -> None:
    """Phase 5 觀測：把本 session 的 codex_companion 計數附加到
    memory/wisdom/reflection_metrics.json 的 codex_companion.sessions 陣列。

    最多保留最近 100 筆，與 wisdom_engine 既有結構共存（top-level codex_companion
    為新欄位，wisdom_engine 不讀，不破壞 V4.1 P4 路徑）。
    全 zero 的 session 跳過避免噪音。
    """
    try:
        import state as companion_state
        metrics = companion_state.read_metrics(session_id)
    except Exception:
        return
    if not metrics or not any(metrics.values()):
        return

    metrics_path = CLAUDE_DIR / "memory" / "wisdom" / "reflection_metrics.json"
    try:
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return  # 既有檔不存在/壞檔不主動建立，避免覆寫風險

    section = data.setdefault("codex_companion", {})
    sessions = section.setdefault("sessions", [])
    from datetime import datetime, timezone
    sessions.append({
        "session_id": session_id,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **metrics,
    })
    if len(sessions) > 100:
        section["sessions"] = sessions[-100:]
    try:
        tmp = metrics_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(metrics_path)
    except OSError:
        pass


def handle_session_end(input_data: Dict[str, Any], config: Dict[str, Any]):
    port = config.get("service_port", 3850)
    session_id = input_data.get("session_id", "")

    _http_post(port, "/event", {
        "session_id": session_id,
        "type": "session_end",
    })

    if session_id:
        _flush_metrics_to_reflection(session_id)

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
