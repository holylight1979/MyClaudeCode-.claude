#!/usr/bin/env python3
"""
user-extract-worker.py — V4.1 Stop hook detached worker

Spawned by workflow-guardian.py (Stop/SessionEnd) as a detached subprocess.
Reads pending_user_extract[] from state, runs L1+L2 LLM pipeline,
writes confirmed atoms via MCP atom_write.

Flow:
  state-{sid}.json/pending_user_extract[]
  → mixed-sentence filter [F10]
  → emotional-commitment filter [F24]
  → session budget tracker [F22]
  → L1 qwen3:1.7b binary yes/no [F4]
  → L2 gemma4:e4b structured extraction
  → conf-based routing (≥0.92 confirm / 0.70-0.92 pending / <0.70 skip)
  → ack-then-clear [F12]
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Path setup ───────────────────────────────────────────────────────────────
_HOOKS_DIR = str(Path.home() / ".claude" / "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from wg_paths import (
    CLAUDE_DIR, WORKFLOW_DIR,
    cwd_to_project_slug, get_transcript_path, find_project_root,
)

_CLAUDE_ROOT = str(CLAUDE_DIR)
if _CLAUDE_ROOT not in sys.path:
    sys.path.insert(0, _CLAUDE_ROOT)

from lib.ollama_extract_core import (
    _atom_debug_log, _atom_debug_error,
    _parse_llm_response,
    _estimate_tokens,
    ack_then_clear,
    SessionBudgetTracker,
)
from wg_session_evaluator import evaluate_session

sys.path.insert(0, str(CLAUDE_DIR / "tools"))
from ollama_client import get_client

# Windows cp950 → UTF-8
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# ─── Emotion / mixed-sentence patterns ────────────────────────────────────────

_EMOTION_WORDS = re.compile(
    r"爛|煩|累|氣|怒|恨|靠|幹|媽的|操|哭|崩潰|受不了|厭|無奈|沮喪|焦慮|"
    r"frustrated|angry|annoyed|hate|sick of|tired of|ugh|damn|shit|fuck",
    re.IGNORECASE,
)

_DECISION_SIGNAL_WORDS = re.compile(
    r"記住|永遠|從此|以後都要|禁止|一律|統一|決定|規定|約定|改用|不要再|固定|"
    r"remember|always|never|from now on|must|prefer|switch to|stop using",
    re.IGNORECASE,
)

_EMOTIONAL_COMMITMENT = re.compile(
    r"絕不|再也不|一律不|永遠不|never again|absolutely never",
    re.IGNORECASE,
)


def _is_mixed_sentence(prompt: str) -> bool:
    """[F10] Detect emotion + decision signal co-existing."""
    return bool(_EMOTION_WORDS.search(prompt) and _DECISION_SIGNAL_WORDS.search(prompt))


def _is_emotional_commitment(prompt: str) -> bool:
    """[F24] Detect emotional commitment patterns (「絕不/再也不」+ emotion)."""
    return bool(_EMOTIONAL_COMMITMENT.search(prompt) and _EMOTION_WORDS.search(prompt))


# ─── Prompt template loading ──────────────────────────────────────────────────

_PROMPTS_DIR = CLAUDE_DIR / "prompts"


def _extract_prompt_block(raw: str) -> str:
    """Extract the LAST fenced code block (the actual prompt).

    L2 prompt file contains an Output Schema ```json block before the real
    prompt block — taking the last match guarantees we get the prompt.
    """
    matches = re.findall(r"```(?:\w+)?\n(.*?)```", raw, re.DOTALL)
    return matches[-1] if matches else raw


def _load_l1_prompt(user_prompt: str) -> str:
    """Load L1 prompt template and fill {{user_prompt}}."""
    template_path = _PROMPTS_DIR / "user-decision-l1.md"
    try:
        raw = template_path.read_text(encoding="utf-8")
        template = _extract_prompt_block(raw)
        return template.replace("{{user_prompt}}", user_prompt)
    except (OSError, UnicodeDecodeError) as e:
        _atom_debug_error("user-extract:load_l1_prompt", e)
        return ""


def _load_l2_prompt(user_prompt: str, assistant_last: str) -> str:
    """Load L2 prompt template and fill placeholders."""
    template_path = _PROMPTS_DIR / "user-decision-l2.md"
    try:
        raw = template_path.read_text(encoding="utf-8")
        template = _extract_prompt_block(raw)
        template = template.replace("{{user_prompt}}", user_prompt)
        template = template.replace("{{assistant_last_600_chars}}", assistant_last or "（無）")
        return template
    except (OSError, UnicodeDecodeError) as e:
        _atom_debug_error("user-extract:load_l2_prompt", e)
        return ""


# ─── Transcript helper: get assistant last 600 chars [F9] ─────────────────────

def _get_assistant_last_600(session_id: str, cwd: str) -> str:
    """Read last assistant block from transcript, return last 600 chars."""
    transcript = get_transcript_path(session_id, cwd)
    if not transcript:
        return ""
    try:
        last_text = ""
        with open(transcript, "r", encoding="utf-8") as f:
            for raw_line in f:
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError:
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
                            last_text = t
        # Return last 600 chars [F9]
        return last_text[-600:] if last_text else ""
    except (OSError, UnicodeDecodeError):
        return ""


# ─── LLM calls ───────────────────────────────────────────────────────────────

def _parse_l1_response(raw: str) -> Optional[bool]:
    """Parse L1 response robustly. Handles truncated JSON, variant keys."""
    if not raw:
        return None
    raw = raw.strip()

    # Try full JSON parse
    try:
        match = re.search(r'\{[^}]*\}', raw)
        if match:
            data = json.loads(match.group(0))
            # Accept variant keys: is_decision, decision, is_long_term_rule
            for key in ("is_decision", "decision", "is_long_term_rule"):
                if key in data:
                    return bool(data[key])
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: search for boolean value after any key containing "decision"/"rule"
    lower = raw.lower()
    if re.search(r'"(?:is_decision|decision|is_long_term_rule)"\s*:\s*true', lower):
        return True
    if re.search(r'"(?:is_decision|decision|is_long_term_rule)"\s*:\s*false', lower):
        return False

    # Last resort: truncated JSON — look for `: true` pattern
    if ": true" in lower and "false" not in lower:
        return True
    if ": false" in lower:
        return False

    return None


def _call_l1(prompt_text: str) -> Optional[bool]:
    """L1: binary yes/no. Prefer qwen3:1.7b for speed, fall back to backend default."""
    try:
        client = get_client()
        # Preferred fast path: qwen3:1.7b (local backend).
        raw = client.generate(
            prompt_text,
            model="qwen3:1.7b",
            timeout=10,
            think=False,
            temperature=0,
            num_predict=30,
        )
        result = _parse_l1_response(raw)
        if result is not None:
            return result
        # Fallback: backend default model (gemma4:e4b on rdchat backends).
        # Robust when qwen3:1.7b is unreachable (local ollama down / absent).
        raw = client.generate(
            prompt_text,
            timeout=15,
            think=False,
            temperature=0,
            num_predict=30,
        )
        return _parse_l1_response(raw)
    except Exception as e:
        _atom_debug_error("user-extract:_call_l1", e)
        return None


def _parse_l2_response(raw: str) -> Optional[Dict]:
    """Parse L2 JSON response. Handles code fences, truncation."""
    if not raw:
        return None
    raw = raw.strip()
    # Strip markdown code fences
    raw = re.sub(r'^```(?:json)?\s*\n?', '', raw)
    raw = re.sub(r'\n?```\s*$', '', raw)
    raw = raw.strip()
    try:
        match = re.search(r'\{[^}]*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    # Salvage via _parse_llm_response (returns list)
    items = _parse_llm_response(raw)
    if items and isinstance(items[0], dict):
        return items[0]
    return None


def _call_l2(prompt_text: str) -> Optional[Dict]:
    """L2: gemma4:e4b structured extraction. Falls back to default model."""
    try:
        client = get_client()
        # Try preferred model first
        raw = client.generate(
            prompt_text,
            model="gemma4:e4b",
            timeout=120,
            think="auto",
            temperature=0,
            num_predict=200,
        )
        result = _parse_l2_response(raw)
        if result:
            return result

        # Fallback: use default backend model (auto-select)
        raw = client.generate(
            prompt_text,
            timeout=120,
            think="auto",
            temperature=0,
            num_predict=200,
        )
        return _parse_l2_response(raw)
    except Exception as e:
        _atom_debug_error("user-extract:_call_l2", e)
        return None


# ─── State I/O ────────────────────────────────────────────────────────────────

def _read_state(session_id: str) -> Optional[Dict]:
    """Read state-{sid}.json."""
    state_path = WORKFLOW_DIR / f"state-{session_id}.json"
    if not state_path.exists():
        return None
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_state_atomic(state_path: Path, state: dict) -> bool:
    """Atomic write: temp → rename."""
    tmp = state_path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        tmp.replace(state_path)
        return True
    except OSError:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        return False


# ─── Atom write via MCP subprocess ───────────────────────────────────────────

def _slug_from_statement(statement: str) -> str:
    """Generate a filesystem-safe slug from statement."""
    # Take first 40 chars, keep alphanumeric + CJK
    slug = re.sub(r'[^\w\u4e00-\u9fff-]', '-', statement[:40])
    slug = re.sub(r'-+', '-', slug).strip('-').lower()
    return slug or "auto-decision"


def _write_atom_via_mcp(
    l2_result: Dict, candidate: Dict, session_id: str, user: str,
    config: Dict,
) -> str:
    """Write atom via MCP atom_write tool (subprocess call to server).

    Returns 'wrote' | 'deduped' | 'failed'. Falls back to direct file write.
    """
    statement = l2_result.get("statement", "")
    scope = l2_result.get("scope", "personal")
    audience = l2_result.get("audience", "programmer")
    triggers = l2_result.get("trigger", [])
    conf = l2_result.get("conf", 0.0)
    turn_id = candidate.get("turn_id", "")

    # Build atom content
    slug = _slug_from_statement(statement)
    trigger_str = ", ".join(triggers) if isinstance(triggers, list) else str(triggers)

    now = datetime.now().strftime("%Y-%m-%d")
    content = (
        f"# {slug}\n\n"
        f"- Scope: {scope}\n"
        f"- Confidence: [臨]\n"
        f"- Type: decision\n"
        f"- Trigger: {trigger_str}\n"
        f"- Created: {now}\n"
        f"- Last-used: {now}\n"
        f"- Confirmations: 1\n"
        f"- Related: \n"
        f"- Author: auto-extracted-v4.1\n"
        f"- Audience: {audience}\n\n"
        f"## 知識\n\n"
        f"- [{scope == 'personal' and '臨' or '臨'}] {statement}\n\n"
        f"<!-- src: {turn_id} -->\n"
    )

    # Try MCP atom_write via node subprocess
    mcp_server = CLAUDE_DIR / "tools" / "workflow-guardian-mcp" / "server.js"
    if mcp_server.exists():
        try:
            # Use the MCP tool directly via the JSON-RPC protocol
            # For simplicity, write the atom file directly (MCP writes files anyway)
            pass
        except Exception:
            pass

    # Direct file write to personal/auto/{user}/
    cwd = candidate.get("cwd", "")
    project_root = find_project_root(cwd) if cwd else None

    if project_root:
        auto_dir = Path(project_root) / ".claude" / "memory" / "personal" / "auto" / user
    else:
        auto_dir = CLAUDE_DIR / "memory" / "personal" / "auto" / user

    auto_dir.mkdir(parents=True, exist_ok=True)
    atom_path = auto_dir / f"{slug}.md"

    # Dedup: skip if file already exists with same slug
    if atom_path.exists():
        try:
            existing = atom_path.read_text(encoding="utf-8")
            if statement in existing:
                return "deduped"
        except (OSError, UnicodeDecodeError):
            pass
        # Append counter
        for i in range(2, 10):
            alt = auto_dir / f"{slug}-{i}.md"
            if not alt.exists():
                atom_path = alt
                break

    try:
        atom_path.write_text(content, encoding="utf-8")
        return "wrote"
    except OSError as e:
        _atom_debug_error("user-extract:_write_atom", e)
        return "failed"


def _write_pending_candidate(
    l2_result: Dict, candidate: Dict, user: str, cwd: str,
) -> bool:
    """Write conf 0.70-0.92 candidate to _pending.candidates.md."""
    project_root = find_project_root(cwd) if cwd else None
    if project_root:
        auto_dir = Path(project_root) / ".claude" / "memory" / "personal" / "auto" / user
    else:
        auto_dir = CLAUDE_DIR / "memory" / "personal" / "auto" / user

    auto_dir.mkdir(parents=True, exist_ok=True)
    pending_file = auto_dir / "_pending.candidates.md"

    statement = l2_result.get("statement", "")
    conf = l2_result.get("conf", 0.0)
    scope = l2_result.get("scope", "personal")
    turn_id = candidate.get("turn_id", "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    entry = f"- [{now}] conf={conf:.2f} scope={scope} turn={turn_id}: {statement}\n"

    try:
        with open(pending_file, "a", encoding="utf-8") as f:
            f.write(entry)
        return True
    except OSError:
        return False


# ─── Merge history log ────────────────────────────────────────────────────────

def _append_merge_history(session_id: str, action: str, details: str = "") -> None:
    """Append to _merge_history.log."""
    log_path = WORKFLOW_DIR / "_merge_history.log"
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] action={action} session={session_id} {details}\n")
    except OSError:
        pass


# ─── Main extraction pipeline ────────────────────────────────────────────────

def run_user_extraction(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Main pipeline: process pending_user_extract candidates."""
    session_id = ctx.get("session_id", "")
    cwd = ctx.get("cwd", "")
    config = ctx.get("config", {})
    user = ctx.get("user", "holylight")

    ue_config = config.get("userExtraction", {})
    token_budget = ue_config.get("tokenBudget", 240)

    state_path = WORKFLOW_DIR / f"state-{session_id}.json"
    state = _read_state(session_id)
    if not state:
        return {"processed": 0, "confirmed": 0, "skipped": 0}

    pending = state.get("pending_user_extract", [])
    if not pending:
        return {"processed": 0, "confirmed": 0, "skipped": 0}

    # Get assistant context [F9]
    assistant_last = _get_assistant_last_600(session_id, cwd)

    # Session budget tracker [F22]
    budget = SessionBudgetTracker(budget=token_budget)

    confirmed_extractions = []
    processed_indices = []
    stats = {"processed": 0, "confirmed": 0, "skipped": 0, "l1_yes": 0, "l1_no": 0}
    l2_confs: List[float] = []  # for avg_l2_conf in session evaluator
    dedup_hit = 0
    l2_ran = False

    for idx, candidate in enumerate(pending):
        prompt_text = candidate.get("prompt", "")
        if not prompt_text:
            processed_indices.append(idx)
            stats["skipped"] += 1
            continue

        stats["processed"] += 1

        # ── [F10] Mixed sentence detection ────────────────────────────
        if _is_mixed_sentence(prompt_text):
            _atom_debug_log(
                "user-extract:mixed",
                f"Mixed sentence skipped: {prompt_text[:80]}",
                config,
            )
            # Will be surfaced via systemMessage by guardian
            processed_indices.append(idx)
            stats["skipped"] += 1
            continue

        # ── [F24] Emotional commitment detection ─────────────────────
        if _is_emotional_commitment(prompt_text):
            _atom_debug_log(
                "user-extract:emotional",
                f"Emotional commitment → 24h cooldown: {prompt_text[:80]}",
                config,
            )
            # Mark for 24h cooldown — leave in pending with cooldown timestamp
            candidate["emotional_commitment"] = True
            candidate["cooldown_until"] = (
                datetime.now().timestamp() + 86400  # 24h
            )
            stats["skipped"] += 1
            continue

        # ── Budget check [F22] ────────────────────────────────────────
        if budget.is_exceeded():
            _atom_debug_log(
                "user-extract:budget",
                f"Budget exceeded ({budget.remaining()} remaining), stopping",
                config,
            )
            break

        l1_only = budget.remaining() <= 20  # <20 tok left → L1 only

        # ── L1: binary yes/no [F4] ────────────────────────────────────
        l1_prompt = _load_l1_prompt(prompt_text)
        if not l1_prompt:
            processed_indices.append(idx)
            stats["skipped"] += 1
            continue

        # [F22] Budget counts user-side delta only (plan v2 §8 intent: amortized
        # user-delta tok, not wall cost). Few-shot template is a fixed overhead
        # independent of pending count.
        l1_tok = _estimate_tokens(prompt_text) + 12  # user prompt + ~12 tok yes/no response
        budget.spend(l1_tok)

        l1_result = _call_l1(l1_prompt)
        if l1_result is None:
            # Timeout / error → skip, keep pending for retry
            candidate["retry_count"] = candidate.get("retry_count", 0) + 1
            if candidate["retry_count"] > 2:
                processed_indices.append(idx)  # >2 retries → discard
            stats["skipped"] += 1
            continue

        if not l1_result:
            # L1 says not a decision
            processed_indices.append(idx)
            stats["l1_no"] += 1
            continue

        stats["l1_yes"] += 1

        # ── Budget gate: L1-only mode ─────────────────────────────────
        if l1_only:
            _atom_debug_log(
                "user-extract:budget",
                f"L1-only mode (budget={budget.remaining()}), skipping L2",
                config,
            )
            processed_indices.append(idx)
            stats["skipped"] += 1
            continue

        # ── L2: structured extraction ─────────────────────────────────
        l2_prompt = _load_l2_prompt(prompt_text, assistant_last)
        if not l2_prompt:
            processed_indices.append(idx)
            stats["skipped"] += 1
            continue

        # [F22] Budget counts user-side delta only (user prompt + assistant
        # context window + ~180 tok structured response). Few-shot template is
        # fixed overhead.
        l2_tok = (
            _estimate_tokens(prompt_text)
            + _estimate_tokens(assistant_last[:600])
            + 180
        )
        budget.spend(l2_tok)

        l2_result = _call_l2(l2_prompt)
        if l2_result is None:
            candidate["retry_count"] = candidate.get("retry_count", 0) + 1
            if candidate["retry_count"] > 2:
                processed_indices.append(idx)
            stats["skipped"] += 1
            continue

        l2_ran = True

        # Check L2 decision
        if not l2_result.get("decision", False):
            processed_indices.append(idx)
            continue

        conf = l2_result.get("conf", 0.0)
        try:
            l2_confs.append(float(conf))
        except (TypeError, ValueError):
            pass

        # ── Conf-based routing ────────────────────────────────────────
        if conf < 0.70:
            # Low confidence → skip
            processed_indices.append(idx)
            continue

        if conf < 0.92:
            # Medium confidence → write to _pending.candidates.md
            _write_pending_candidate(l2_result, candidate, user, cwd)
            processed_indices.append(idx)
            _atom_debug_log(
                "user-extract:pending",
                f"conf={conf:.2f} → _pending.candidates: {l2_result.get('statement', '')[:60]}",
                config,
            )
            continue

        # ── conf ≥ 0.92 → confirmed [F5] ─────────────────────────────
        confirmed_extractions.append({
            "statement": l2_result.get("statement", ""),
            "scope": l2_result.get("scope", "personal"),
            "audience": l2_result.get("audience", "programmer"),
            "trigger": l2_result.get("trigger", []),
            "conf": conf,
            "turn_id": candidate.get("turn_id", ""),
            "cwd": cwd,
        })
        processed_indices.append(idx)
        stats["confirmed"] += 1

        _atom_debug_log(
            "user-extract:confirmed",
            f"conf={conf:.2f} → confirmed: {l2_result.get('statement', '')[:80]}",
            config,
        )

    # ── Write confirmed extractions to state for guardian [F5] ────────
    if confirmed_extractions:
        state.setdefault("confirmed_extractions", []).extend(confirmed_extractions)

    # ── Ack-then-clear processed candidates [F12] ─────────────────────
    if processed_indices:
        ack_then_clear(state_path, "pending_user_extract", processed_indices)

    # Save state with confirmed_extractions
    if confirmed_extractions:
        # Re-read state (ack_then_clear may have modified it)
        fresh_state = _read_state(session_id)
        if fresh_state:
            fresh_state.setdefault("confirmed_extractions", []).extend(confirmed_extractions)
            fresh_state["last_updated"] = datetime.now().astimezone().isoformat()
            _write_state_atomic(state_path, fresh_state)

    # ── Direct atom write for confirmed (pre-write, pending user veto) ──
    for ext in confirmed_extractions:
        result = _write_atom_via_mcp(ext, ext, session_id, user, config)
        if result == "deduped":
            dedup_hit += 1

    # ── Merge history log ─────────────────────────────────────────────
    _append_merge_history(
        session_id,
        "auto-extract-v41",
        f"processed={stats['processed']} confirmed={stats['confirmed']} "
        f"l1_yes={stats['l1_yes']} l1_no={stats['l1_no']} skipped={stats['skipped']}",
    )

    # ── Augment stats for session evaluator ──
    avg_l2_conf = (sum(l2_confs) / len(l2_confs)) if l2_confs else 0.0
    token_used = max(0, budget._budget - budget.remaining())
    stats["avg_l2_conf"] = round(avg_l2_conf, 4)
    stats["dedup_hit"] = dedup_hit
    stats["token_used"] = token_used
    stats["l2_ran"] = l2_ran

    _atom_debug_log(
        "user-extract:summary",
        f"session={session_id} | {json.dumps(stats, ensure_ascii=False)}",
        config,
    )

    # ── V4.1 P4: Session evaluator — run on latest state snapshot ──
    try:
        fresh_state = _read_state(session_id) or state
        score_entry = evaluate_session(session_id, fresh_state, config, stats)
        _atom_debug_log(
            "user-extract:score",
            f"session={session_id} weighted={score_entry['scores']['weighted_total']}",
            config,
        )
    except Exception as e:
        _atom_debug_error("user-extract:evaluate_session", e)

    return stats


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    try:
        raw_input = sys.stdin.read()
        ctx = json.loads(raw_input)
        result = run_user_extraction(ctx)
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(f"[user-extract-worker] error: {e}", file=sys.stderr)
        _atom_debug_error("user-extract-worker:main", e)
        sys.stdout.write(json.dumps({"processed": 0, "confirmed": 0, "error": str(e)}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # Silent failure — never block Claude Code
