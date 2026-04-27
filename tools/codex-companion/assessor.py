"""assessor.py — Codex assessment runner.

Builds review prompts from accumulated events, invokes `codex exec`,
parses structured JSON output.

Sandbox: 不傳 -s 旗標，沿用 ~/.codex/config.toml 預設（通常 danger-full-access）。
Windows 上 -s read-only 會踩 CreateProcessWithLogonW 1385 spawn 失敗導致 stdout 為空。
寫入限制改靠 prompts.py 模板開頭的紅線約束。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SERVICE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_DIR))

import prompts


def _log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[assessor {ts}] {msg}", file=sys.stderr, flush=True)


def _summarize_tool_trace(trace: List[Dict[str, Any]], max_items: int = 30) -> str:
    """Format tool trace into a compact string for prompt injection."""
    if not trace:
        return "(empty)"

    recent = trace[-max_items:]
    lines = []
    for i, t in enumerate(recent, 1):
        tool = t.get("tool", t.get("type", "?"))
        inp = t.get("input", "")
        out = t.get("output_summary", "")
        path = t.get("path", "")

        # Truncate long fields
        if len(inp) > 200:
            inp = inp[:200] + "..."
        if len(out) > 150:
            out = out[:150] + "..."

        parts = [f"{i}. [{tool}]"]
        if path:
            parts.append(path)
        if inp:
            parts.append(f"input: {inp}")
        if out:
            parts.append(f"→ {out}")
        lines.append(" ".join(parts))

    return "\n".join(lines)


def _summarize_modified_files(trace: List[Dict[str, Any]]) -> str:
    """Extract unique modified file paths from trace."""
    paths = set()
    for t in trace:
        if t.get("tool") in ("Edit", "Write") and t.get("path"):
            paths.add(t["path"])
    if not paths:
        return "(none)"
    return "\n".join(f"- {p}" for p in sorted(paths))


def _extract_arch_files(trace: List[Dict[str, Any]]) -> str:
    """Extract structural files from trace."""
    import re
    arch_re = re.compile(
        r"(?:bridge|provider|adapter|factory|service|client|transport|middleware|gateway)"
        r"(?:\.py|\.ts|\.js|\.rs)$",
        re.IGNORECASE,
    )
    paths = set()
    for t in trace:
        p = t.get("path", "")
        if p and arch_re.search(p):
            paths.add(p)
    if not paths:
        return "(none)"
    return "\n".join(f"- {p}" for p in sorted(paths))


def _run_codex(prompt_text: str, cwd: str, config: Dict[str, Any]) -> str:
    """Run `codex exec` and return stdout text."""
    codex_bin = config.get("codex_binary", "codex")
    model = config.get("model", "")
    timeout = config.get("assessment_timeout", 60)

    # Write prompt to temp file to avoid shell escaping issues
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(prompt_text)
        prompt_file = f.name

    # Write output to temp file
    output_file = prompt_file + ".out"

    try:
        cmd = [codex_bin, "exec"]
        if model:
            cmd += ["-m", model]
        cmd += [
            "--ephemeral",
            "--ignore-rules",
            "--skip-git-repo-check",
            "-o", output_file,
        ]

        # Read prompt from stdin (via file)
        _log(f"Running: {' '.join(cmd[:6])}... (timeout={timeout}s)")

        with open(prompt_file, "r", encoding="utf-8") as pf:
            result = subprocess.run(
                cmd,
                stdin=pf,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd if cwd and os.path.isdir(cwd) else None,
                env={**os.environ, "NO_COLOR": "1"},
            )

        _log(f"codex exec exit code: {result.returncode}")

        # Prefer -o output file
        if os.path.exists(output_file):
            text = Path(output_file).read_text(encoding="utf-8").strip()
            if text:
                return text

        # Fallback to stdout
        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        _log(f"codex exec timed out after {timeout}s")
        return ""
    except FileNotFoundError:
        _log(f"codex binary not found: {codex_bin}")
        return ""
    except Exception as e:
        _log(f"codex exec error: {e}")
        return ""
    finally:
        # Cleanup temp files
        for f in (prompt_file, output_file):
            try:
                os.unlink(f)
            except OSError:
                pass


def _parse_assessment(raw: str) -> Dict[str, Any]:
    """Parse Codex output into structured assessment dict."""
    if not raw:
        return {
            "status": "error",
            "severity": "low",
            "category": "system",
            "summary": "Codex returned empty response.",
        }

    # Try to extract JSON from response
    # Codex might wrap it in markdown fences
    text = raw.strip()

    # Remove markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Find first and last fence
        start = 0
        end = len(lines)
        for i, line in enumerate(lines):
            if line.strip().startswith("```") and i == 0:
                start = i + 1
                # Skip language tag like ```json
                continue
            if line.strip() == "```" and i > 0:
                end = i
                break
        text = "\n".join(lines[start:end]).strip()

    # Try JSON parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            # Validate required fields
            parsed.setdefault("status", "ok")
            parsed.setdefault("severity", "low")
            parsed.setdefault("category", "unknown")
            parsed.setdefault("summary", "")
            return parsed
    except json.JSONDecodeError:
        pass

    # Try to find JSON object anywhere in text
    import re
    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            if isinstance(parsed, dict) and "status" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    # Fallback: wrap raw text as summary
    return {
        "status": "ok",
        "severity": "low",
        "category": "unknown",
        "summary": text[:500],
    }


# ─── Public API ──────────────────────────────────────────────────────────────


def run_assessment(
    assessment_type: str,
    session_id: str,
    tool_trace: List[Dict[str, Any]],
    cwd: str,
    extra_context: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Run a Codex assessment and return structured result.

    assessment_type: "plan_review" | "turn_audit" | "architecture_review"
    """
    trace_str = _summarize_tool_trace(tool_trace)
    modified_str = _summarize_modified_files(tool_trace)

    # Import heuristics for flag context
    try:
        import heuristics
        # Build a pseudo guardian-compatible state for heuristics
        heur_state = {
            "tool_trace": tool_trace,
            "modified_files": [
                {"path": t.get("path", "")}
                for t in tool_trace
                if t.get("tool") in ("Edit", "Write") and t.get("path")
            ],
        }
        flags = heuristics.triggered_results(heur_state)
        flags_str = heuristics.format_for_context(flags) if flags else "None"
    except Exception:
        flags_str = "None"

    # Build prompt based on type
    if assessment_type == "plan_review":
        prompt = prompts.build_plan_review_prompt(
            user_goal=extra_context.get("user_goal", ""),
            plan_content=extra_context.get("plan_content", trace_str),
            files_examined=extra_context.get("files_examined", ""),
            heuristic_flags=flags_str,
        )
    elif assessment_type == "architecture_review":
        prompt = prompts.build_architecture_review_prompt(
            cwd=cwd,
            arch_files=_extract_arch_files(tool_trace),
            tool_trace=trace_str,
        )
    else:
        # Default: turn_audit
        prompt = prompts.build_turn_audit_prompt(
            cwd=cwd,
            tool_trace=trace_str,
            modified_files=modified_str,
            heuristic_flags=flags_str,
        )

    _log(f"Prompt built for {assessment_type}: {len(prompt)} chars")

    raw = _run_codex(prompt, cwd, config)
    result = _parse_assessment(raw)

    # Tag with metadata
    result["_assessment_type"] = assessment_type
    result["_session_id"] = session_id

    return result
