"""
ollama_extract_core.py — Shared extraction utilities for extract-worker.py and user-extract-worker.py.

Refactored from hooks/extract-worker.py (V2.13).
Functions preserve original signatures for backward compatibility.
"""

import json
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# ─── sys.path for ollama_client ─────────────────────────────────────────────
_CLAUDE_DIR = Path.home() / ".claude"
_TOOLS_DIR = str(_CLAUDE_DIR / "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from ollama_client import get_client

VALID_TYPES = ("factual", "procedural", "architectural", "pitfall", "decision")


# ─── Token estimation ──────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """CJK-aware token estimation. Chinese ~1.5 tok/char, ASCII ~0.25 tok/word."""
    if not text:
        return 0
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f')
    ascii_part = len(text) - cjk
    return int(cjk * 1.5 + ascii_part * 0.25)


# ─── Atom Debug Log ────────────────────────────────────────────────────────

def _atom_debug_log(tag: str, content: str, config: Dict[str, Any] = None) -> None:
    """Write to atom-debug.log when atom_debug flag is on.
    For ERROR tag, always write regardless of flag.
    Skips empty/NONE entries to reduce noise."""
    if tag != "ERROR" and not (config or {}).get("atom_debug", False):
        return
    if not content or not content.strip():
        return  # suppress empty entries
    try:
        log_dir = Path.home() / ".claude" / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"atom-debug-{datetime.now().strftime('%Y-%m-%d_%H')}.log"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}][{tag}] {content.strip()}\n\n")
    except Exception:
        pass


def _atom_debug_error(source: str, exc: Exception) -> None:
    """Log error with source context and stack trace."""
    tb = traceback.format_exc()
    if "NoneType" in tb:
        tb = f"{type(exc).__name__}: {exc}"
    _atom_debug_log("ERROR", f"[{source}] {tb}", {"atom_debug": True})


# ─── Ollama ────────────────────────────────────────────────────────────────

def _call_ollama(prompt: str, model: str = None, timeout: int = 120) -> str:
    try:
        client = get_client()
        # think="auto": rdchat(gemma4:e4b)=True, local(qwen3:1.7b)=False — 由 backend config 控制
        # temperature=0.0: A/B 測試 Round 2 結論，一致性最佳
        # num_predict: 由 backend config 的 llm_num_predict 控制（rdchat=4096, local=2048）
        return client.generate(
            prompt, model=model, timeout=timeout,
            think="auto", temperature=0.0,
        )
    except Exception as e:
        _atom_debug_error("萃取:_call_ollama", e)
        return ""


# ─── Parse + Dedup ─────────────────────────────────────────────────────────

def _parse_llm_response(raw: str) -> List[dict]:
    if not raw:
        return []
    items = []
    try:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            # Filter: only keep dict items (LLM may emit strings/ints in array)
            items = [x for x in parsed if isinstance(x, dict)]
    except (json.JSONDecodeError, ValueError):
        for m in re.finditer(r'"content"\s*:\s*"([^"]{10,150})"', raw):
            items.append({"content": m.group(1), "type": "factual"})
    return items


def _word_overlap_score(a: str, b: str) -> float:
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def _dedup_items(
    items: List[dict], existing_queue: List[dict], threshold: float = 0.80
) -> List[dict]:
    """Validate, deduplicate, and format extracted items."""
    existing_contents = [q.get("content", "") for q in existing_queue if q.get("content")]
    results = []
    now = datetime.now().astimezone().isoformat()

    for item in items[:5]:
        content = item.get("content", "").strip()
        if not content or len(content) < 10:
            continue

        # Check overlap against existing queue
        skip = False
        for ec in existing_contents:
            if _word_overlap_score(content, ec) >= threshold:
                skip = True
                break
        if skip:
            continue

        # Check overlap against already-accepted results
        for r in results:
            if _word_overlap_score(content, r["content"]) >= threshold:
                skip = True
                break
        if skip:
            continue

        kt = item.get("type", "factual")
        if kt not in VALID_TYPES:
            kt = "factual"

        results.append({
            "content": content[:150],
            "classification": "[臨]",
            "knowledge_type": kt,
            "source": "session-end",
            "confirmations": 1,
            "at": now,
        })
        existing_contents.append(content)

    return results


# ─── Ack-then-clear [F12] ──────────────────────────────────────────────────

def ack_then_clear(state_path: Path, key: str, indices: List[int]) -> bool:
    """Atomically read state → pop specified indices from state[key] → write back.

    Used to clear successfully-written items from knowledge_queue / pending_user_extract
    without losing items added concurrently by other hooks.

    Returns True on success, False on any error.
    """
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    queue = state.get(key, [])
    if not queue or not indices:
        return True  # nothing to clear

    # Pop indices in reverse order to maintain correctness
    for idx in sorted(indices, reverse=True):
        if 0 <= idx < len(queue):
            queue.pop(idx)

    state[key] = queue
    state["last_updated"] = datetime.now().astimezone().isoformat()

    # Atomic write: temp file → rename
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


# ─── Session Budget Tracker [F22] ──────────────────────────────────────────

class SessionBudgetTracker:
    """Track token budget consumption within a session.

    Budget defaults to 240 tok (V4.1 NFR).
    When exceeded, callers should degrade to L1-only or skip extraction entirely.
    """

    def __init__(self, budget: int = 240):
        self._budget = budget
        self._spent = 0

    def spend(self, tok: int) -> None:
        """Record token expenditure."""
        self._spent += tok

    def remaining(self) -> int:
        """Return remaining budget (may be negative if overspent)."""
        return self._budget - self._spent

    def is_exceeded(self) -> bool:
        """Return True if budget is fully consumed."""
        return self._spent >= self._budget
