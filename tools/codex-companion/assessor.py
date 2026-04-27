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
import re
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
    """Extract structural files from trace.

    Sprint 3：共用 heuristics._ARCH_FILE_RE 避免 service / assessor / heuristics
    三處 regex drift。
    """
    import heuristics as _heur
    paths = set()
    for t in trace:
        p = t.get("path", "")
        if p and _heur._ARCH_FILE_RE.search(p):
            paths.add(p)
    if not paths:
        return "(none)"
    return "\n".join(f"- {p}" for p in sorted(paths))


def _extract_verification_evidence(trace: List[Dict[str, Any]]) -> str:
    """Sprint 3 Phase 4.3：從 tool_trace 抽 verify cmd 事證給 codex prompt。

    撈取 Bash + 命中 heuristics._VERIFY_CMD_RE 的 input 行。
    若出現過 `[FAILED] ` prefix（hook 端 failure 偵測），保留以提示 codex。
    """
    try:
        import heuristics
        verify_re = heuristics._VERIFY_CMD_RE
    except Exception:
        return "(none found)"

    hits: List[str] = []
    for i, t in enumerate(trace, 1):
        if t.get("tool") != "Bash":
            continue
        cmd = t.get("input", "") or ""
        if not verify_re.search(cmd):
            continue
        out = t.get("output_summary", "") or ""
        outcome = "FAILED" if out.startswith("[FAILED]") else "ok"
        hits.append(f"#{i} [{outcome}] {cmd[:120]}")

    if not hits:
        return "(none found)"
    return "\n".join(hits[-5:])  # 最近 5 條足夠


def _run_codex(prompt_text: str, cwd: str, config: Dict[str, Any]) -> tuple[str, str]:
    """Run `codex exec` and return (stdout_text, stderr_text).

    Sprint 4 Phase 5.1：stderr 回傳給上層做 sandbox 失敗識別。
    無論成功失敗都把 stderr（含 timeout/spawn 錯誤的合成訊息）一併送出。
    """
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
        stderr_text = (result.stderr or "")

        # Prefer -o output file
        if os.path.exists(output_file):
            text = Path(output_file).read_text(encoding="utf-8").strip()
            if text:
                return text, stderr_text

        # Fallback to stdout
        return result.stdout.strip(), stderr_text

    except subprocess.TimeoutExpired:
        _log(f"codex exec timed out after {timeout}s")
        return "", f"[assessor] timeout after {timeout}s"
    except FileNotFoundError:
        _log(f"codex binary not found: {codex_bin}")
        return "", f"[assessor] codex binary not found: {codex_bin}"
    except Exception as e:
        _log(f"codex exec error: {e}")
        return "", f"[assessor] exception: {e}"
    finally:
        # Cleanup temp files
        for f in (prompt_file, output_file):
            try:
                os.unlink(f)
            except OSError:
                pass


_SANDBOX_FAILURE_RE = re.compile(r"CreateProcessWithLogon|sandbox", re.IGNORECASE)


def _run_codex_with_retry(
    prompt_text: str, cwd: str, config: Dict[str, Any]
) -> tuple[str, str, int]:
    """Sprint 4 Phase 5.1：空字串/非 JSON → 退 300-500ms 重試 1 次。

    回傳 (stdout, stderr_combined, attempts)。
    第一次 stdout 不空且能 JSON 解析 → 直接返回 attempts=1。
    否則 sleep 0.4s 再跑一次，stderr 串接讓上層做 sandbox 識別。
    """
    stdout1, stderr1 = _run_codex(prompt_text, cwd, config)

    if stdout1 and _try_parse_json(stdout1) is not None:
        return stdout1, stderr1, 1

    _log("First codex call returned empty/non-JSON; retry once in 400ms")
    time.sleep(0.4)
    stdout2, stderr2 = _run_codex(prompt_text, cwd, config)

    final_stdout = stdout2 or stdout1
    combined_stderr = "\n".join(s for s in (stderr1, stderr2) if s)
    return final_stdout, combined_stderr, 2


def _classify_failure(stderr: str) -> Dict[str, Any]:
    """Sprint 4 Phase 5.1：依 stderr 內容把 codex 失敗分類成 assessment。

    sandbox 命中（CreateProcessWithLogon|sandbox）→ system 高嚴重度，
      防 R2-5 級 bug 再被吞掉。
    其他失敗 → warning + delivery=inject + notify_next_turn=True，
      下一輪 drain 端會加注短訊提醒。
    """
    stderr_excerpt = (stderr or "")[-300:]
    if _SANDBOX_FAILURE_RE.search(stderr or ""):
        return _apply_defaults({
            "status": "error",
            "severity": "high",
            "category": "system",
            "summary": "Codex sandbox 失敗，請檢查 -s 設定",
            "evidence": stderr_excerpt,
            "delivery": "inject",
            "confidence": "high",
            "applies_until": "next_prompt",
            "notify_next_turn": True,
        })
    return _apply_defaults({
        "status": "warning",
        "severity": "low",
        "category": "system",
        "summary": "退回 heuristics-only",
        "evidence": stderr_excerpt,
        "delivery": "inject",
        "confidence": "low",
        "applies_until": "next_prompt",
        "notify_next_turn": True,
    })


def _apply_defaults(d: Dict[str, Any]) -> Dict[str, Any]:
    """Sprint 3：補 schema v2 預設值；舊 codex 回 recommended_action 也吃。

    Sprint 4 提到模組級：給 _classify_failure / _try_parse_json 共用。
    """
    d.setdefault("status", "ok")
    d.setdefault("severity", "low")
    d.setdefault("category", "unknown")
    d.setdefault("summary", "")
    d.setdefault("evidence", "")
    # delivery 預設策略：嚴重度 medium 以上才 inject，否則 ignore（保守）
    if "delivery" not in d:
        sev = str(d.get("severity", "low")).lower()
        d["delivery"] = "inject" if sev in ("medium", "high") else "ignore"
    d.setdefault("confidence", "medium")
    d.setdefault("applies_until", "next_prompt")
    # turn_index 由 service 補 _turn_index，這裡先補 0 占位
    d.setdefault("turn_index", 0)
    # 舊欄位 recommended_action 視為 corrective_prompt 的別名
    if "corrective_prompt" not in d and d.get("recommended_action"):
        d["corrective_prompt"] = d["recommended_action"]
    d.setdefault("corrective_prompt", "")
    return d


def _try_parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """嘗試從 codex stdout 抽出 JSON dict。失敗回 None（讓 retry 路徑判斷）。

    Sprint 4：抽 module-level 給 _run_codex_with_retry 用。
    """
    if not raw:
        return None
    text = raw.strip()

    # Remove markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        start = 0
        end = len(lines)
        for i, line in enumerate(lines):
            if line.strip().startswith("```") and i == 0:
                start = i + 1
                continue
            if line.strip() == "```" and i > 0:
                end = i
                break
        text = "\n".join(lines[start:end]).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return _apply_defaults(parsed)
    except json.JSONDecodeError:
        pass

    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            if isinstance(parsed, dict) and "status" in parsed:
                return _apply_defaults(parsed)
        except json.JSONDecodeError:
            pass

    return None


def _parse_assessment(raw: str) -> Dict[str, Any]:
    """Parse Codex output into structured assessment dict.

    Sprint 4：失敗分類已搬到 _classify_failure；本函式只負責成功路徑與
    legacy fallback（unknown 文字當 summary）。
    """
    parsed = _try_parse_json(raw)
    if parsed is not None:
        return parsed
    # Fallback: wrap raw text as summary
    return _apply_defaults({
        "status": "ok",
        "severity": "low",
        "category": "unknown",
        "summary": (raw or "")[:500],
        "delivery": "ignore",
        "confidence": "low",
    })


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

    Sprint 3 Phase 4.3：turn_audit 額外傳 turn_index + last_assistant_tail
    + verification_evidence + heuristic_summary。前者由 service 從 state 讀並
    放進 extra_context；後兩者由 assessor 從 trace 即時抽取（避免 stale state）。
    """
    trace_str = _summarize_tool_trace(tool_trace)
    modified_str = _summarize_modified_files(tool_trace)

    turn_index = int(extra_context.get("turn_index", 0))
    last_assistant_tail = extra_context.get("last_assistant_tail", "") or ""
    if last_assistant_tail and len(last_assistant_tail) > 1500:
        last_assistant_tail = last_assistant_tail[:1500] + "…(截斷)"

    # Import heuristics for flag context
    flags_str = "None"
    heuristic_summary = "None"
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
        flags = heuristics.triggered_results(heur_state, stop_text=last_assistant_tail)
        if flags:
            heuristic_summary = heuristics.format_for_context(flags)
            flags_str = heuristic_summary
    except Exception:
        pass

    verification_evidence = _extract_verification_evidence(tool_trace)

    # Build prompt based on type
    if assessment_type == "plan_review":
        prompt = prompts.build_plan_review_prompt(
            user_goal=extra_context.get("user_goal", ""),
            plan_content=extra_context.get("plan_content", trace_str),
            files_examined=extra_context.get("files_examined", ""),
            heuristic_flags=flags_str,
            turn_index=turn_index,
        )
    elif assessment_type == "architecture_review":
        prompt = prompts.build_architecture_review_prompt(
            cwd=cwd,
            arch_files=_extract_arch_files(tool_trace),
            tool_trace=trace_str,
            turn_index=turn_index,
        )
    else:
        # Default: turn_audit
        prompt = prompts.build_turn_audit_prompt(
            cwd=cwd,
            tool_trace=trace_str,
            modified_files=modified_str,
            heuristic_flags=flags_str,
            turn_index=turn_index,
            last_assistant_tail=last_assistant_tail,
            verification_evidence=verification_evidence,
            heuristic_summary=heuristic_summary,
        )

    _log(f"Prompt built for {assessment_type} (t{turn_index}): {len(prompt)} chars")

    # Sprint 4 Phase 5.1：retry 1 次 + sandbox 失敗識別
    raw, stderr_combined, attempts = _run_codex_with_retry(prompt, cwd, config)
    parsed = _try_parse_json(raw) if raw else None
    if parsed is None:
        result = _classify_failure(stderr_combined)
    else:
        result = parsed

    # Tag with metadata
    result["_assessment_type"] = assessment_type
    result["_session_id"] = session_id
    result["_attempts"] = attempts

    return result
