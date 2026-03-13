#!/usr/bin/env python3
"""
workflow-guardian.py — Workflow Guardian Hook Script

Claude Code hooks 的統一入口，從 stdin 讀取 JSON，
根據 hook_event_name 分派到對應 handler。

Handles: SessionStart, UserPromptSubmit, PostToolUse,
         PreCompact, Stop, SessionEnd

Requirements: Python 3.8+, zero external dependencies.
"""

import json
import math
import os
import sys
import re
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path.home() / ".claude" / "tools"))
from ollama_client import get_client, check_long_die_status, disable_backend, OllamaClient

# ─── V2.8: Wisdom Engine (lazy import, graceful fallback) ────────────────────
try:
    from wisdom_engine import (
        classify_situation,
        get_reflection_summary,
        reflect as wisdom_reflect,
        track_retry as wisdom_track_retry,
    )
    WISDOM_AVAILABLE = True
except ImportError:
    WISDOM_AVAILABLE = False

# ─── Constants ───────────────────────────────────────────────────────────────

CLAUDE_DIR = Path.home() / ".claude"
WORKFLOW_DIR = CLAUDE_DIR / "workflow"
MEMORY_DIR = CLAUDE_DIR / "memory"
EPISODIC_DIR = MEMORY_DIR / "episodic"
CONFIG_PATH = WORKFLOW_DIR / "config.json"
MEMORY_INDEX = "MEMORY.md"
CONTEXT_BUDGET_DEFAULT = 3000  # V2.11: default token cap (overridden by compute_token_budget)

# Defaults (overridable via config.json)
DEFAULTS = {
    "enabled": True,
    "stop_gate_max_blocks": 2,
    "min_files_to_block": 2,
    "remind_after_turns": 3,
    "max_reminders": 3,
    "stale_threshold_hours": 24,
    "sync_keywords": ["同步", "sync", "commit", "提交", "結束", "收工"],
    "completion_indicators": ["已同步", "同步完成", "已更新", "已提交", "committed"],
    # v2.2 Sprint 2: Session context injection
    "session_context": {
        "enabled": True,
        "max_episodic": 3,
        "reserved_tokens": 200,
        "min_score": 0.35,
        "search_timeout_ms": 1500,
    },
    # v2.10: _AIDocs Bridge
    "aidocs": {
        "enabled": True,
        "max_session_start_entries": 15,
        "max_prompt_matches": 3,
    },
    # v2.2 Sprint 2: Proactive classification
    "proactive": {
        "pattern_threshold": 2,     # N episodic sessions before suggesting dedicated atom
        "migration_hint_threshold": 3,  # N session references before migration hint
    },
}

# ─── Config ──────────────────────────────────────────────────────────────────


def load_config() -> Dict[str, Any]:
    """Load config with defaults fallback."""
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            config.update(user_config)
        except (json.JSONDecodeError, OSError):
            pass
    return config


# ─── State File I/O ──────────────────────────────────────────────────────────


def state_path(session_id: str) -> Path:
    return WORKFLOW_DIR / f"state-{session_id}.json"


def read_state(session_id: str) -> Optional[Dict[str, Any]]:
    """Read state file. Returns None if not found or corrupt."""
    path = state_path(session_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_state(session_id: str, state: Dict[str, Any]) -> None:
    """Atomic write: write to temp then rename."""
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = _now_iso()
    path = state_path(session_id)
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        tmp_path.replace(path)
    except OSError:
        # Best effort; if write fails, continue silently
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def new_state(session_id: str, cwd: str, source: str) -> Dict[str, Any]:
    """Create a fresh state object."""
    return {
        "schema_version": "1.1",
        "session": {
            "id": session_id,
            "started_at": _now_iso(),
            "cwd": cwd,
            "source": source,
        },
        "phase": "init",
        "modified_files": [],
        "accessed_files": [],
        "vcs_queries": [],
        "knowledge_queue": [],
        "sync_pending": False,
        "stop_blocked_count": 0,
        "remind_count": 0,
        "topic_tracker": {
            "intent_distribution": {},
            "prompt_count": 0,
            "first_prompt_summary": "",
            "keyword_signals": [],
            "related_episodic": [],
        },
        "session_context_injected": False,
        "last_updated": _now_iso(),
    }


# ─── Memory Index Parsing ────────────────────────────────────────────────────

TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
ALIAS_RE = re.compile(r"^>\s*Project-Aliases:\s*(.+)", re.MULTILINE)  # v2.9

# Atom entry: (name, relative_path, trigger_keywords[])
AtomEntry = Tuple[str, str, List[str]]


def parse_memory_index(memory_dir: Path) -> List[AtomEntry]:
    """Parse MEMORY.md atom index, return list of (name, path, triggers)."""
    index_path = memory_dir / MEMORY_INDEX
    if not index_path.exists():
        return []
    try:
        text = index_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []

    atoms: List[AtomEntry] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_table:
            if stripped.startswith("| Atom") or stripped.startswith("|Atom"):
                in_table = True
                continue
        else:
            if stripped.startswith("|---") or stripped.startswith("| ---"):
                continue
            if not stripped.startswith("|"):
                break
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if len(cells) >= 3:
                name = cells[0]
                rel_path = cells[1]
                triggers = [t.strip().lower() for t in cells[2].split(",") if t.strip()]
                atoms.append((name, rel_path, triggers))
            elif cells:
                atoms.append((cells[0], "", []))
    return atoms


def parse_project_aliases(memory_dir: Path) -> List[str]:
    """Parse > Project-Aliases: line from MEMORY.md. Returns lowercase alias keywords."""
    index_path = memory_dir / MEMORY_INDEX
    if not index_path.exists():
        return []
    try:
        text = index_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []
    m = ALIAS_RE.search(text)
    if not m:
        return []
    return [a.strip().lower() for a in m.group(1).split(",") if a.strip()]


def _find_atom_path(name: str, all_atoms: List[Tuple[AtomEntry, Path]]) -> Optional[Path]:
    """Find the file path for a named atom from the all_atoms list."""
    for (aname, rel_path, _triggers), base_dir in all_atoms:
        if aname == name:
            return (base_dir / rel_path) if rel_path else (base_dir / "memory" / f"{name}.md")
    return None


def spread_related(
    matched_names: set,
    all_atoms: List[Tuple[AtomEntry, Path]],
    already_injected: List[str],
    max_depth: int = 1,
) -> List[Tuple[AtomEntry, Path]]:
    """沿 Related 邊擴散，回傳尚未匹配的相關 atoms (depth-limited BFS)."""
    _RELATED_RE = re.compile(r"^- Related:\s*(.+)", re.MULTILINE)
    visited = set(matched_names) | set(already_injected)
    wave = list(matched_names)
    result: List[Tuple[AtomEntry, Path]] = []

    for _depth in range(max_depth):
        next_wave: List[str] = []
        for name in wave:
            atom_path = _find_atom_path(name, all_atoms)
            if not atom_path or not atom_path.exists():
                continue
            try:
                text = atom_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            rm = _RELATED_RE.search(text)
            if not rm:
                continue
            for rn in (r.strip() for r in rm.group(1).split(",") if r.strip()):
                if rn not in visited:
                    visited.add(rn)
                    for entry_tuple in all_atoms:
                        if entry_tuple[0][0] == rn:
                            result.append(entry_tuple)
                            next_wave.append(rn)
                            break
        wave = next_wave
    return result


def compute_activation(atom_name: str, atom_dir: Path) -> float:
    """ACT-R base-level activation: B_i = ln(Σ t_k^{-0.5})."""
    access_file = atom_dir / f"{atom_name}.access.json"
    if not access_file.exists():
        return -10.0
    try:
        data = json.loads(access_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return -10.0
    timestamps = data.get("timestamps", [])
    if not timestamps:
        return -10.0
    now = time.time()
    total = 0.0
    for ts in timestamps:
        t_k = max(now - ts, 1.0)
        total += t_k ** -0.5
    return math.log(total) if total > 0 else -10.0


def cwd_to_project_slug(cwd: str) -> str:
    """Convert CWD to Claude Code project slug.
    C:\\Projects\\sgi-server → c--Projects-sgi-server
    """
    slug = cwd.replace(":", "-").replace("\\", "-").replace("/", "-").replace(".", "-")
    if slug:
        slug = slug[0].lower() + slug[1:]
    return slug


def get_project_memory_dir(cwd: str) -> Optional[Path]:
    """Get project-level memory dir from CWD. Returns None if not found."""
    if not cwd:
        return None
    slug = cwd_to_project_slug(cwd)
    project_mem = CLAUDE_DIR / "projects" / slug / "memory"
    if project_mem.exists():
        return project_mem
    return None


# ─── _AIDocs Bridge (v2.10) ──────────────────────────────────────────────

AiDocsEntry = Tuple[str, str]  # (filename, description)


def find_project_root(cwd: str) -> Optional[Path]:
    """Walk up from CWD to find project root (contains _AIDocs/ or .git/ or .svn/)."""
    if not cwd:
        return None
    p = Path(cwd)
    for _ in range(4):  # cwd itself + max 3 levels up
        if (p / "_AIDocs").is_dir():
            return p
        if (p / ".git").exists() or (p / ".svn").exists():
            return p
        parent = p.parent
        if parent == p:
            break
        p = parent
    return Path(cwd)  # fallback


def parse_aidocs_index(project_root: Path) -> List[AiDocsEntry]:
    """Parse _AIDocs/_INDEX.md table, return [(filename, description)]."""
    index_path = project_root / "_AIDocs" / "_INDEX.md"
    if not index_path.exists():
        return []
    try:
        text = index_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []

    entries: List[AiDocsEntry] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_table:
            if stripped.startswith("| #") or stripped.startswith("|#"):
                in_table = True
                continue
        else:
            if stripped.startswith("|---") or stripped.startswith("| ---"):
                continue
            if not stripped.startswith("|"):
                in_table = False
                continue
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if len(cells) >= 3:
                fname = cells[1].strip("[]() ")
                # Strip markdown links: [Name](./path) → Name
                link_match = re.match(r"\[([^\]]+)\]", cells[1])
                if link_match:
                    fname = link_match.group(1)
                desc = cells[2]
                # Skip deprecated (strikethrough) entries
                if fname.startswith("~~") or "淘汰" in desc:
                    continue
                entries.append((fname, desc))
    return entries


def extract_aidocs_keywords(entries: List[AiDocsEntry]) -> Dict[str, List[str]]:
    """Extract search keywords from _AIDocs descriptions."""
    STOP = {"的", "與", "和", "等", "個", "含", "—", "md", "分析", "說明", "文件", "專案"}
    result: Dict[str, List[str]] = {}
    for fname, desc in entries:
        words = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z_]{3,}", desc.lower())
        keywords = [w for w in words if w not in STOP]
        # Also include filename stem as keywords
        stem = Path(fname).stem.lower().replace("_", " ").replace("-", " ")
        keywords.extend(stem.split())
        result[fname] = list(set(keywords))[:10]
    return result


def match_triggers(prompt: str, atoms: List[AtomEntry]) -> List[AtomEntry]:
    """Match user prompt against atom Trigger keywords. Case-insensitive."""
    prompt_lower = prompt.lower()
    matched = []
    for name, rel_path, triggers in atoms:
        if any(kw in prompt_lower for kw in triggers):
            matched.append((name, rel_path, triggers))
    return matched


def compute_token_budget(prompt: str) -> int:
    """Auto-adjust injection budget (estimated tokens) based on prompt complexity.

    Uses len(content)//4 as char-to-token estimator (v2.1 Sprint 3).
    """
    plen = len(prompt)
    if plen < 50:
        return 1500       # Mode 1: light
    elif plen < 200:
        return 3000       # transitional
    else:
        return 5000       # Mode 2: deep


def load_atoms_within_budget(
    matched: List[AtomEntry],
    memory_dir: Path,
    budget_tokens: int,
    already_injected: List[str],
) -> Tuple[List[str], List[str], int]:
    """Load atom file contents up to budget. Returns (content_lines, injected_names, used_tokens)."""
    lines: List[str] = []
    injected: List[str] = []
    used = 0

    for name, rel_path, triggers in matched:
        if name in already_injected:
            continue
        # Resolve atom file path
        atom_path = (memory_dir / rel_path) if rel_path else (memory_dir / f"{name}.md")
        if not atom_path.exists():
            continue
        try:
            content = atom_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue

        content_tokens = len(content) // 4  # char-to-token estimate
        if used + content_tokens <= budget_tokens:
            lines.append(f"[Atom:{name}]\n{content}")
            injected.append(name)
            used += content_tokens
        else:
            # Over budget: inject summary only
            first_line = content.split("\n", 1)[0].strip("# ").strip()
            lines.append(f"[Atom:{name}] {first_line} (full: Read {rel_path or name + '.md'})")
            injected.append(name)  # still mark as "seen" to avoid re-summary
            break  # stop loading more

    return lines, injected, used


def _truncate_context_by_activation(
    lines: List[str], limit: int = CONTEXT_BUDGET_DEFAULT
) -> List[str]:
    """V2.11: Truncate additionalContext lines to fit within token budget.

    Identifies [Atom:xxx] blocks, scores them by ACT-R activation,
    and replaces lowest-scoring atoms with summary lines until under limit.
    """
    full_text = "\n".join(lines)
    used = len(full_text) // 4
    if used <= limit:
        lines.append(f"[Context budget: {used}/{limit} tokens]")
        return lines

    # Identify atom blocks: lines starting with [Atom:xxx]
    ATOM_LINE_RE = re.compile(r"^\[Atom:(\S+)\]")
    atom_blocks: List[dict] = []  # {index, name, start, end, tokens}
    i = 0
    while i < len(lines):
        m = ATOM_LINE_RE.match(lines[i])
        if m:
            name = m.group(1)
            # Find end of this atom block (next [Atom:...] or non-content line pattern)
            end = i + 1
            while end < len(lines) and not ATOM_LINE_RE.match(lines[end]):
                end += 1
            block_text = "\n".join(lines[i:end])
            atom_blocks.append({
                "name": name,
                "start": i,
                "end": end,
                "tokens": len(block_text) // 4,
                "first_line": lines[i].split("\n", 1)[0] if "\n" in lines[i] else lines[i],
            })
            i = end
        else:
            i += 1

    if not atom_blocks:
        # No atoms to truncate, just cap it
        lines.append(f"[Context budget: {used}/{limit} tokens (over)]")
        return lines

    # Score each atom by ACT-R activation (low = truncate first)
    for ab in atom_blocks:
        atom_name = ab["name"]
        # Try global memory dir first
        ab["activation"] = compute_activation(atom_name, MEMORY_DIR)
        if ab["activation"] <= -10.0:
            # Try episodic
            ab["activation"] = compute_activation(atom_name, EPISODIC_DIR)

    # Sort by activation ascending (lowest first = truncate first)
    atom_blocks.sort(key=lambda x: x["activation"])

    # Truncate lowest-activation atoms until under budget
    truncated_indices: set = set()
    for ab in atom_blocks:
        if used <= limit:
            break
        # Replace multi-line atom block with summary
        summary = f"[Atom:{ab['name']}] (truncated, activation={ab['activation']:.2f}) Read memory/{ab['name']}.md"
        saved = ab["tokens"] - (len(summary) // 4)
        if saved > 0:
            truncated_indices.add(ab["start"])
            # Mark for replacement
            ab["summary"] = summary
            used -= saved

    # Rebuild lines
    new_lines: List[str] = []
    skip_until = -1
    for idx, line in enumerate(lines):
        if idx < skip_until:
            continue
        found = False
        for ab in atom_blocks:
            if ab["start"] == idx and idx in truncated_indices:
                new_lines.append(ab["summary"])
                skip_until = ab["end"]
                found = True
                break
        if not found and idx >= skip_until:
            new_lines.append(line)

    new_lines.append(f"[Context budget: {used}/{limit} tokens]")
    return new_lines


# ─── Output Helpers ──────────────────────────────────────────────────────────


def output_json(data: Dict[str, Any]) -> None:
    """Print JSON to stdout and exit 0."""
    print(json.dumps(data, ensure_ascii=False))
    sys.exit(0)


def output_nothing() -> None:
    """Exit 0 with no output (fast path)."""
    sys.exit(0)


def output_block(reason: str) -> None:
    """Output a block decision (for Stop hook)."""
    output_json({"decision": "block", "reason": reason})


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ─── Intent Classifier (v2.1 Sprint 2) ───────────────────────────────────────

INTENT_PATTERNS = {
    "debug": ["crash", "error", "bug", "失敗", "壞", "exception", "為什麼",
              "why", "問題", "traceback", "報錯", "修復", "fix"],
    "build": ["build", "deploy", "建置", "部署", "安裝", "install", "啟動",
              "setup", "config", "設定", "配置", "環境"],
    "design": ["設計", "架構", "design", "architecture", "重構", "refactor",
               "新增", "planning", "實作", "implement", "方案"],
    "recall": ["之前", "上次", "記得", "決策", "決定", "為什麼選",
               "remember", "previous", "history"],
}


def classify_intent(prompt: str) -> str:
    """Rule-based intent classifier. Zero LLM overhead (~1ms)."""
    prompt_lower = prompt.lower()
    scores = {}
    for intent, keywords in INTENT_PATTERNS.items():
        scores[intent] = sum(1 for kw in keywords if kw in prompt_lower)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


# ─── Topic Tracker (v2.2) ────────────────────────────────────────────────────

_TOPIC_STOP_WORDS = frozenset({
    "this", "that", "with", "from", "have", "been", "will", "what", "when",
    "which", "where", "about", "into", "also", "should", "could", "would",
    "these", "those", "them", "your", "make", "just", "only", "some", "very",
    "here", "there", "then", "than", "more", "most", "like", "each", "want",
    "need", "keep", "does", "done", "doing", "help", "sure", "good", "well",
    "okay", "know", "think", "look", "take", "give", "come", "back", "over",
    "after", "before", "other", "file", "line", "code", "true", "false",
})


def _update_topic_tracker(
    state: Dict[str, Any], prompt: str, intent: str, newly_injected: List[str]
) -> None:
    """Accumulate topic signals in state. Pure CPU, < 1ms, zero network."""
    tracker = state.setdefault("topic_tracker", {
        "intent_distribution": {},
        "prompt_count": 0,
        "first_prompt_summary": "",
        "keyword_signals": [],
        "related_episodic": [],
    })

    # 1. Intent distribution
    dist = tracker["intent_distribution"]
    dist[intent] = dist.get(intent, 0) + 1
    tracker["prompt_count"] = tracker.get("prompt_count", 0) + 1

    # 2. First prompt summary (capture once)
    if not tracker.get("first_prompt_summary"):
        tracker["first_prompt_summary"] = prompt[:200]

    # 3. Keyword signal extraction
    existing_kw = set(tracker.get("keyword_signals", []))
    words = re.findall(r"[a-zA-Z\u4e00-\u9fff]{4,}", prompt)
    for w in words:
        wl = w.lower()
        if wl not in _TOPIC_STOP_WORDS and wl not in existing_kw:
            existing_kw.add(wl)
    sa_config = state.get("_sa_config", {})
    max_kw = sa_config.get("max_keyword_signals", 20)
    tracker["keyword_signals"] = sorted(existing_kw)[:max_kw]

    # 4. Track related episodic atoms
    related = tracker.get("related_episodic", [])
    for name in newly_injected:
        if name.startswith("episodic-") and name not in related:
            related.append(name)
    tracker["related_episodic"] = related


# ─── v2.2 Sprint 2: Session Context + Proactive Classification ──────────────

from collections import Counter


def _search_episodic_context(
    prompt: str, config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Query /search/episodic for related past sessions. First-prompt only.

    Returns list of episodic atom results with summary, triggers, etc.
    Timeout: 1.5s (reserve rest for Phase 1).
    """
    vs_config = config.get("vector_search", {})
    if not vs_config.get("enabled", True):
        return []
    sc_config = config.get("session_context", {})
    if not sc_config.get("enabled", True):
        return []

    port = vs_config.get("service_port", 3849)
    top_k = sc_config.get("max_episodic", 3)
    min_score = sc_config.get("min_score", 0.35)
    timeout_s = sc_config.get("search_timeout_ms", 1500) / 1000.0

    try:
        import urllib.parse
        params = urllib.parse.urlencode({
            "q": prompt, "top_k": top_k, "min_score": min_score,
        })
        url = f"http://127.0.0.1:{port}/search/episodic?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read())
    except Exception:
        return []


def _build_session_context(episodic_results: List[Dict[str, Any]]) -> List[str]:
    """Build compact [Session:Context] block from episodic search results.

    Returns list of context lines (max ~200 tokens).
    """
    if not episodic_results:
        return []

    context_lines = ["[Session:Context] Related past sessions:"]
    char_budget = 600  # ~150 tokens, leave room for header

    for ep in episodic_results:
        name = ep.get("atom_name", "")
        created = ep.get("created", ep.get("last_used", ""))
        summary = ep.get("summary", "")
        score = ep.get("score", 0)

        # Extract slug from name: episodic-20260304-memory-system → memory-system
        slug = name
        if name.startswith("episodic-") and len(name) > 18:
            slug = name[18:]  # skip "episodic-YYYYMMDD-"

        # Compact single-line format
        line = f"- [{created}] {slug}: {summary[:120]}"
        if len(line) > char_budget:
            break
        context_lines.append(line)
        char_budget -= len(line)

    return context_lines if len(context_lines) > 1 else []


def _detect_cross_session_patterns(
    episodic_results: List[Dict[str, Any]], prompt: str
) -> List[str]:
    """Detect recurring themes across episodic sessions.

    Returns list of recurring keywords found in 2+ episodic atoms AND the prompt.
    """
    if len(episodic_results) < 2:
        return []

    # Count keyword appearances across episodic atoms
    topic_counts: Counter = Counter()
    for ep in episodic_results:
        for kw in ep.get("triggers", []):
            if kw not in ("session", "episodic"):  # skip generic triggers
                topic_counts[kw] += 1

    # Extract keywords from prompt
    prompt_kw = set(
        w.lower() for w in re.findall(r"[a-zA-Z\u4e00-\u9fff]{4,}", prompt)
        if w.lower() not in _TOPIC_STOP_WORDS
    )

    # Intersection: keywords in prompt that appear in 2+ episodic atoms
    recurring = [kw for kw in prompt_kw if topic_counts.get(kw, 0) >= 2]
    return recurring


def _proactive_classify(
    state: Dict[str, Any],
    episodic_results: List[Dict[str, Any]],
    prompt: str,
    config: Dict[str, Any],
) -> List[str]:
    """Proactive classification engine. Returns context lines for hints/questions.

    Checks:
    1. Cross-session pattern → suggest dedicated atom
    2. Episodic migration → suggest migrating frequently-referenced episodic
    """
    pro_config = config.get("proactive", {})
    lines: List[str] = []

    # 1. Cross-session pattern detection
    recurring = _detect_cross_session_patterns(episodic_results, prompt)
    pattern_threshold = pro_config.get("pattern_threshold", 2)
    if recurring:
        # Check if any recurring keyword already has a dedicated semantic atom
        atom_index = state.get("atom_index", {})
        existing_names = set()
        for entry in atom_index.get("global", []):
            existing_names.add(entry[0].lower())
        for entry in atom_index.get("project", []):
            existing_names.add(entry[0].lower())

        # Only suggest if topic has no dedicated atom
        novel_themes = [kw for kw in recurring if kw not in existing_names]
        if novel_themes:
            themes_str = ", ".join(novel_themes[:3])
            ep_count = len(episodic_results)
            lines.append(
                f"💡 [Proactive] 主題 \"{themes_str}\" 在最近 {ep_count} 個 session 反覆出現。"
                " 建議建立專屬 semantic atom 來長期保存相關知識。"
            )

    # 2. Episodic migration hint
    migration_threshold = pro_config.get("migration_hint_threshold", 3)
    related_episodic = state.get("topic_tracker", {}).get("related_episodic", [])
    # Count how many times each episodic atom has been referenced (across sessions)
    for ep in episodic_results:
        name = ep.get("atom_name", "")
        confirms = 0
        try:
            confirms = int(ep.get("confirmations", 0) if ep.get("confirmations") else 0)
        except (ValueError, TypeError):
            pass
        if confirms >= migration_threshold:
            lines.append(
                f"❓ {name} 已被 {confirms}+ 次 session 引用。"
                " 核心知識是否應遷移到專屬 atom？"
            )

    return lines


# ─── Vector Service Helpers ───────────────────────────────────────────────────


def _ensure_vector_service(config: Dict[str, Any]) -> None:
    """Check if Memory Vector Service is running; start if not."""
    vs_config = config.get("vector_search", {})
    port = vs_config.get("service_port", 3849)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health", method="GET")
        with urllib.request.urlopen(req, timeout=1):
            return  # Already running
    except Exception:
        pass
    # Try to start
    service_path = CLAUDE_DIR / "tools" / "memory-vector-service" / "service.py"
    if not service_path.exists():
        return
    try:
        import subprocess
        CREATE_NO_WINDOW = 0x08000000
        log_path = CLAUDE_DIR / "memory" / "_vectordb" / "service.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [sys.executable, str(service_path)],
            creationflags=CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=open(str(log_path), "a"),
        )
    except Exception:
        pass  # Non-critical


def _semantic_search(
    prompt: str, config: Dict[str, Any], intent: str = "general"
) -> List[Tuple[str, str, List[str]]]:
    """Query Memory Vector Service with intent-aware ranked search (v2.1).

    Uses /search/ranked endpoint (multi-factor scoring). Falls back to /search
    if ranked endpoint is unavailable.
    Timeout: 2 seconds. Any error → graceful fallback to keyword-only.
    """
    vs_config = config.get("vector_search", {})
    if not vs_config.get("enabled", True):
        return []
    port = vs_config.get("service_port", 3849)
    top_k = vs_config.get("search_top_k", 5)
    min_score = vs_config.get("search_min_score", 0.65)
    timeout_s = vs_config.get("search_timeout_ms", 2000) / 1000.0

    try:
        import urllib.parse
        # Try ranked search first (v2.1)
        params = urllib.parse.urlencode({
            "q": prompt, "top_k": top_k,
            "min_score": min(min_score, 0.50),  # Lower threshold for ranked search
            "intent": intent,
        })
        url = f"http://127.0.0.1:{port}/search/ranked?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                results = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Fallback to basic search (old service version)
                params = urllib.parse.urlencode({"q": prompt, "top_k": top_k, "min_score": min_score})
                url = f"http://127.0.0.1:{port}/search?{params}"
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    results = json.loads(resp.read())
            else:
                raise
        # Convert to AtomEntry format: (name, file_path, [])
        entries: List[Tuple[str, str, List[str]]] = []
        seen = set()
        for r in results:
            name = r.get("atom_name", "")
            if name and name not in seen:
                entries.append((name, r.get("file_path", ""), []))
                seen.add(name)
        return entries
    except Exception:
        return []  # graceful fallback


def _trigger_incremental_index(config: Dict[str, Any]) -> None:
    """Non-blocking request to re-index changed atoms."""
    vs_config = config.get("vector_search", {})
    if not vs_config.get("auto_index_on_change", True):
        return
    port = vs_config.get("service_port", 3849)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/index/incremental",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass  # Non-critical


# ─── Event Handlers ──────────────────────────────────────────────────────────


def handle_session_start(input_data: Dict[str, Any], config: Dict[str, Any]) -> None:
    session_id = input_data.get("session_id", "unknown")
    cwd = input_data.get("cwd", "")
    source = input_data.get("source", "startup")

    # On compact/resume, reuse existing state
    existing = read_state(session_id)
    if existing and source in ("compact", "resume"):
        state = existing
        # Clear injected_atoms so atoms get re-injected after compact (context was truncated)
        state["injected_atoms"] = []
        # Re-inject full context after compaction
        mod_count = len(state.get("modified_files", []))
        kq_count = len(state.get("knowledge_queue", []))
        phase = state.get("phase", "working")
        lines = [
            f"[Workflow Guardian] Session resumed ({source}). Phase: {phase}.",
            f"Modified files: {mod_count}. Knowledge queue: {kq_count}.",
        ]
        if mod_count > 0:
            files = [m["path"].rsplit("/", 1)[-1] for m in state["modified_files"][-5:]]
            lines.append(f"Recent: {', '.join(files)}")
        if kq_count > 0:
            items = [q["content"][:40] for q in state["knowledge_queue"][:3]]
            lines.append(f"Pending knowledge: {'; '.join(items)}")
        lines.append("Remember: check CLAUDE.md sync rules before ending.")
    else:
        state = new_state(session_id, cwd, source)

        # Parse memory indices (store as serializable lists)
        global_atoms = parse_memory_index(MEMORY_DIR)
        project_mem_dir = get_project_memory_dir(cwd)
        project_atoms = parse_memory_index(project_mem_dir) if project_mem_dir else []

        state["atom_index"] = {
            "global": [(n, p, t) for n, p, t in global_atoms],
            "project": [(n, p, t) for n, p, t in project_atoms],
            "project_memory_dir": str(project_mem_dir) if project_mem_dir else "",
        }
        state["injected_atoms"] = []
        state["phase"] = "working"

        # ── v2.10: _AIDocs Bridge — scan project _AIDocs index ──────────
        project_root = find_project_root(cwd)
        aidocs_entries = parse_aidocs_index(project_root) if project_root else []
        aidocs_keywords = extract_aidocs_keywords(aidocs_entries) if aidocs_entries else {}
        state["aidocs"] = {
            "project_root": str(project_root) if project_root else "",
            "entries": [(f, d) for f, d in aidocs_entries],
            "keywords": aidocs_keywords,
        }

        g_names = [n for n, _, _ in global_atoms]
        p_names = [n for n, _, _ in project_atoms]
        lines = [
            "[Workflow Guardian] Active.",
            f"Global atoms: {', '.join(g_names) if g_names else 'none'}.",
        ]
        if p_names:
            lines.append(f"Project atoms: {', '.join(p_names)}.")
        lines.append("I will track file modifications and remind you to sync before ending.")

        # Inject compact _AIDocs index (v2.10)
        max_entries = config.get("aidocs", {}).get("max_session_start_entries", 15)
        if aidocs_entries:
            aidocs_lines = [f"[AIDocs] {len(aidocs_entries)} docs in _AIDocs/:"]
            for fname, desc in aidocs_entries[:max_entries]:
                clean = re.sub(r"[*~`]", "", desc).strip()
                aidocs_lines.append(f"  - {fname}: {clean[:80]}")
            lines.extend(aidocs_lines)

    # ── V2.6: Periodic review check ─────────────────────────────────────
    try:
        review_reminder = _check_periodic_review_due(config)
        if review_reminder:
            lines.append(review_reminder)
            state["review_due"] = True
    except Exception as e:
        print(f"[v2.6] Review check error: {e}", file=sys.stderr)

    # ── V2.8: Wisdom Engine — reflection blind spots ───────────────
    if WISDOM_AVAILABLE:
        try:
            wisdom_lines = get_reflection_summary()
            lines.extend(wisdom_lines)
        except Exception as e:
            print(f"[v2.8] Wisdom reflection error: {e}", file=sys.stderr)

    # ── Dual-Backend: long_die user confirmation ────────────────────────
    try:
        long_die = check_long_die_status()
        if long_die:
            backend_name = long_die.get("backend", "remote")
            until = long_die.get("until", "?")
            lines.append(
                f"[⚠ Long DIE] 遠端 Ollama backend '{backend_name}' 多次連線失敗，"
                f"已暫停至 {until}。請確認是否要永久停用此 backend？"
                f"（回覆「停用 {backend_name}」或「保持」）"
            )
    except Exception as e:
        print(f"[dual-backend] Long DIE check error: {e}", file=sys.stderr)

    # ── Vector Service auto-start ──────────────────────────────────────
    if config.get("vector_search", {}).get("auto_start_service", True):
        _ensure_vector_service(config)

    write_state(session_id, state)

    output_json({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    })


def handle_user_prompt_submit(
    input_data: Dict[str, Any], config: Dict[str, Any]
) -> None:
    session_id = input_data.get("session_id", "")
    state = read_state(session_id)
    if not state:
        output_nothing()
        return

    prompt = input_data.get("prompt", "")
    prompt_lower = prompt.lower().strip()
    lines: List[str] = []

    # ─── Dual-Backend: long_die user response ─────────────────────────
    try:
        long_die = check_long_die_status()
        if long_die:
            backend_name = long_die.get("backend", "")
            if any(kw in prompt_lower for kw in ("停用", "disable")):
                if disable_backend(backend_name):
                    OllamaClient._clear_long_die_marker()
                    lines.append(
                        f"[Dual-Backend] 已永久停用 '{backend_name}'。"
                        f"如需重新啟用，修改 config.json 中 enabled: true。"
                    )
                else:
                    lines.append(f"[Dual-Backend] 停用 '{backend_name}' 失敗，請手動修改 config.json。")
            elif any(kw in prompt_lower for kw in ("保持", "keep", "忽略")):
                OllamaClient._clear_long_die_marker()
                lines.append(f"[Dual-Backend] 保持 '{backend_name}'，long_die 將在時間段到期後自動恢復。")
    except Exception as e:
        print(f"[dual-backend] Long DIE response error: {e}", file=sys.stderr)

    # ─── Phase 0: Session Context Injection (first prompt only) ────────
    budget = compute_token_budget(prompt)
    if not state.get("session_context_injected", False):
        state["session_context_injected"] = True
        episodic_results = _search_episodic_context(prompt, config)
        if episodic_results:
            # Build compact context block
            ctx_lines = _build_session_context(episodic_results)
            if ctx_lines:
                lines.extend(ctx_lines)
                # Reserve tokens for episodic context
                sc_config = config.get("session_context", {})
                reserved = sc_config.get("reserved_tokens", 200)
                budget = max(budget - reserved, 500)
            # Proactive classification (cross-session patterns, migration hints)
            proactive_lines = _proactive_classify(state, episodic_results, prompt, config)
            lines.extend(proactive_lines)

    # ─── V2.8: Wisdom Engine — situation classification ──────────
    if WISDOM_AVAILABLE:
        try:
            mod_paths = [m["path"] for m in state.get("modified_files", [])]
            tracker = state.get("topic_tracker", {})
            prompt_analysis = {
                "intent": tracker.get("intent_distribution", {}).get("top", ""),
                "keywords": tracker.get("keyword_signals", []),
                "estimated_files": max(len(mod_paths), 1),
            }
            result = classify_situation(prompt_analysis)
            if result.get("inject"):
                lines.append(result["inject"])
            # 記錄最高 approach 供 SessionEnd reflect() 使用
            cur = result.get("approach", "direct")
            prev = state.get("wisdom_approach", "direct")
            rank = {"direct": 0, "confirm": 1, "plan": 2}
            if rank.get(cur, 0) > rank.get(prev, 0):
                state["wisdom_approach"] = cur
        except Exception as e:
            print(f"[v2.8] Wisdom prompt error: {e}", file=sys.stderr)

    # ─── Phase 0.5: _AIDocs keyword matching (v2.10) ──────────────────
    aidocs_state = state.get("aidocs", {})
    aidocs_kw_map = aidocs_state.get("keywords", {})
    max_matches = config.get("aidocs", {}).get("max_prompt_matches", 3)
    if aidocs_kw_map and prompt.strip():
        matched_docs: List[str] = []
        for fname, keywords in aidocs_kw_map.items():
            if any(kw in prompt_lower for kw in keywords):
                matched_docs.append(fname)
        if matched_docs and len(matched_docs) <= 5:
            aidocs_root = aidocs_state.get("project_root", "")
            pointer_lines = ["[Guardian:AIDocs] Relevant project docs:"]
            for doc in matched_docs[:max_matches]:
                desc = ""
                for f, d in aidocs_state.get("entries", []):
                    if f == doc:
                        desc = d
                        break
                doc_path = f"_AIDocs/{doc}" if aidocs_root else doc
                pointer_lines.append(f"  \u2192 Read `{doc_path}` \u2014 {desc[:80]}")
            lines.extend(pointer_lines)

    # ─── Phase 1: Atom auto-injection (Trigger matching) ─────────────
    atom_index = state.get("atom_index", {})
    already_injected = state.get("injected_atoms", [])
    # budget already computed above (possibly reduced by Phase 0)

    # Collect all atoms from both layers
    # rel_path is relative to the PARENT of memory dir (e.g. ~/.claude/ or ~/.claude/projects/slug/)
    all_atoms: List[Tuple[AtomEntry, Path]] = []
    for entry in atom_index.get("global", []):
        name, rel_path, triggers = entry
        all_atoms.append(((name, rel_path, triggers), MEMORY_DIR.parent))
    proj_dir_str = atom_index.get("project_memory_dir", "")
    if proj_dir_str:
        proj_parent = Path(proj_dir_str).parent  # projects/slug/memory → projects/slug/
        for entry in atom_index.get("project", []):
            name, rel_path, triggers = entry
            all_atoms.append(((name, rel_path, triggers), proj_parent))

    # Match prompt against triggers (keyword)
    matched_with_dir: List[Tuple[AtomEntry, Path]] = []
    prompt_lower = prompt.lower()
    alias_injected_projects: set = set()  # v2.9: track alias-injected projects

    # ── Cross-project atom discovery (v2.5) + alias matching (v2.9) ──
    # Scan ALL project memory dirs for trigger matches, not just CWD project.
    loaded_proj_names = set()
    if proj_dir_str:
        loaded_proj_names.add(Path(proj_dir_str).parent.name)
    projects_dir = CLAUDE_DIR / "projects"
    if projects_dir.is_dir():
        for proj_dir in projects_dir.iterdir():
            if not proj_dir.is_dir() or proj_dir.name in loaded_proj_names:
                continue
            cross_mem = proj_dir / "memory"
            if not cross_mem.exists():
                continue
            # v2.9: Check project aliases before trigger matching
            aliases = parse_project_aliases(cross_mem)
            if aliases and any(alias in prompt_lower for alias in aliases):
                try:
                    mem_text = (cross_mem / MEMORY_INDEX).read_text(encoding="utf-8-sig")
                    lines.append(f"[Guardian:AliasMatch] {proj_dir.name} matched via alias")
                    lines.append(f"[ProjectMemory:{proj_dir.name}]\n{mem_text}")
                    alias_injected_projects.add(proj_dir.name)
                except (OSError, UnicodeDecodeError):
                    pass
            # Existing trigger-based cross-atom discovery
            cross_atoms = parse_memory_index(cross_mem)
            if not cross_atoms:
                continue
            cross_parent = cross_mem.parent
            for name, rel_path, triggers in cross_atoms:
                if name not in already_injected and any(kw in prompt_lower for kw in triggers):
                    all_atoms.append(((name, rel_path, triggers), cross_parent))
                    lines.append(f"[Guardian:CrossProject] {proj_dir.name}/{name} matched")
    for (name, rel_path, triggers), base_dir in all_atoms:
        if name not in already_injected and any(kw in prompt_lower for kw in triggers):
            matched_with_dir.append(((name, rel_path, triggers), base_dir))

    # ── Intent classification (v2.1) ────────────────────────────────
    intent = classify_intent(prompt)

    # ── Semantic search (supplement, ranked by intent v2.1) ──────
    kw_matched_names = {e[0][0] for e in matched_with_dir}
    sem_atoms = _semantic_search(prompt, config, intent=intent)
    for sem_name, sem_path, _ in sem_atoms:
        if sem_name in kw_matched_names or sem_name in already_injected:
            continue
        # Find the base_dir for this atom from all_atoms
        for (name, rel_path, triggers), base_dir in all_atoms:
            if name == sem_name:
                matched_with_dir.append(((name, rel_path, triggers), base_dir))
                kw_matched_names.add(name)
                break

    # ── Supersedes filtering (v2.1 Sprint 3) ────────────────────
    # If atom A supersedes atom B, and both matched, drop B
    SUPERSEDES_RE = re.compile(r"^- Supersedes:\s*(.+)", re.MULTILINE)
    superseded_names: set = set()
    for (name, rel_path, triggers), base_dir in matched_with_dir:
        atom_path = (base_dir / rel_path) if rel_path else (base_dir / "memory" / f"{name}.md")
        if not atom_path.exists():
            continue
        try:
            text = atom_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        sm = SUPERSEDES_RE.search(text)
        if sm:
            for old in sm.group(1).split(","):
                old = old.strip()
                if old:
                    superseded_names.add(old)
    if superseded_names:
        matched_with_dir = [
            entry for entry in matched_with_dir
            if entry[0][0] not in superseded_names
        ]

    # ── ACT-R Activation Sorting (v2.9) ─────────────────────────
    # Sort matched atoms by time-weighted activation score (high → low)
    def _activation_key(entry):
        (name, rel_path, _triggers), base_dir = entry
        atom_dir = (base_dir / rel_path).parent if rel_path else (base_dir / "memory")
        return compute_activation(name, atom_dir)

    matched_with_dir.sort(key=_activation_key, reverse=True)

    # Load atoms within budget
    newly_injected: List[str] = []
    if matched_with_dir:
        atom_lines: List[str] = []
        used_tokens = 0

        for (name, rel_path, triggers), base_dir in matched_with_dir:
            atom_path = (base_dir / rel_path) if rel_path else (base_dir / "memory" / f"{name}.md")
            if not atom_path.exists():
                continue
            try:
                content = atom_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue

            content_tokens = len(content) // 4  # char-to-token estimate
            if used_tokens + content_tokens <= budget:
                atom_lines.append(f"[Atom:{name}]\n{content}")
                newly_injected.append(name)
                used_tokens += content_tokens
            else:
                # Over budget: summary only
                first_line = content.split("\n", 1)[0].strip("# ").strip()
                display_path = rel_path or f"{name}.md"
                atom_lines.append(f"[Atom:{name}] {first_line} (full: Read {display_path})")
                newly_injected.append(name)
                break

        # ── Related-Edge Spreading (v2.9) ─────────────────────────
        related_entries = spread_related(
            set(newly_injected), all_atoms, already_injected, max_depth=1,
        )
        for (rname, rel_path, _triggers), base_dir in related_entries:
            if rname in newly_injected:
                continue
            rpath = (base_dir / rel_path) if rel_path else (base_dir / "memory" / f"{rname}.md")
            if not rpath.exists():
                continue
            try:
                content = rpath.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            content_tokens = len(content) // 4
            if used_tokens + content_tokens <= budget:
                atom_lines.append(f"[Atom:{rname}] (related)\n{content}")
                newly_injected.append(rname)
                used_tokens += content_tokens
            else:
                first_line = content.split("\n", 1)[0].strip("# ").strip()
                atom_lines.append(f"[Atom:{rname}] (related) {first_line} (full: Read {rel_path or rname + '.md'})")
                newly_injected.append(rname)
                break

        if atom_lines:
            lines.append("[Guardian:Memory] Trigger-matched atoms loaded:")
            lines.extend(atom_lines)
            state["injected_atoms"] = already_injected + newly_injected

            # Auto-update Last-used timestamp + Confirmations++ in injected atom files (v2.1)
            today_str = datetime.now().strftime("%Y-%m-%d")
            last_used_re = re.compile(r"^(- Last-used:\s*)\d{4}-\d{2}-\d{2}", re.MULTILINE)
            confirmations_re = re.compile(r"^(- Confirmations:\s*)(\d+)", re.MULTILINE)
            confidence_re = re.compile(r"^- Confidence:\s*(\[(?:臨|觀|固)\])", re.MULTILINE)
            PROMOTION_THRESHOLDS = {"[臨]": 2, "[觀]": 4}
            PROMOTION_TARGETS = {"[臨]": "[觀]", "[觀]": "[固]"}
            for inj_name in newly_injected:
                for (name, rel_path, triggers), base_dir in matched_with_dir:
                    if name != inj_name:
                        continue
                    apath = (base_dir / rel_path) if rel_path else (base_dir / "memory" / f"{name}.md")
                    if not apath.exists():
                        break
                    try:
                        text = apath.read_text(encoding="utf-8-sig")
                        changed = False
                        new_count = None
                        # Update Last-used
                        if last_used_re.search(text):
                            new_text = last_used_re.sub(rf"\g<1>{today_str}", text)
                            if new_text != text:
                                text = new_text
                                changed = True
                        # Confirmations++ (v2.1)
                        cm = confirmations_re.search(text)
                        if cm:
                            new_count = int(cm.group(2)) + 1
                            text = confirmations_re.sub(rf"\g<1>{new_count}", text)
                            changed = True
                        elif "- Last-used:" in text:
                            # No Confirmations field yet — add it after Last-used
                            text = re.sub(
                                r"^(- Last-used:\s*.+)$",
                                r"\1\n- Confirmations: 1",
                                text, count=1, flags=re.MULTILINE,
                            )
                            new_count = 1
                            changed = True
                        if changed:
                            apath.write_text(text, encoding="utf-8")
                        # ACT-R access log (v2.9)
                        try:
                            access_file = apath.parent / f"{name}.access.json"
                            if access_file.exists():
                                adata = json.loads(access_file.read_text(encoding="utf-8"))
                            else:
                                adata = {"timestamps": []}
                            adata["timestamps"].append(time.time())
                            adata["timestamps"] = adata["timestamps"][-50:]
                            access_file.write_text(json.dumps(adata), encoding="utf-8")
                        except (OSError, json.JSONDecodeError):
                            pass
                        # Promotion hint (v2.11) — no auto-promote, hint only
                        if new_count is not None:
                            conf_m = confidence_re.search(text)
                            if conf_m:
                                cur = conf_m.group(1)
                                threshold = PROMOTION_THRESHOLDS.get(cur)
                                if threshold and new_count >= threshold:
                                    target = PROMOTION_TARGETS[cur]
                                    lines.append(
                                        f"⚡ [{inj_name}] Confirmations={new_count}, "
                                        f"目前{cur}, 已達{target}門檻，"
                                        f"觸及相關行為時請主動確認是否晉升"
                                    )
                    except (OSError, UnicodeDecodeError):
                        pass
                    break

    # ── Blind-Spot Reporter (v2.9) ──────────────────────────────────
    if not matched_with_dir and not newly_injected and not alias_injected_projects:
        prompt_preview = prompt[:50].strip()
        if len(prompt) > 50:
            prompt_preview += "..."
        lines.append(
            f'[Guardian:BlindSpot] 未找到與 "{prompt_preview}" '
            f'相關的記憶 atom。建議 LLM 主動搜尋檔案或詢問使用者。'
        )

    # ─── Topic tracking (v2.2) ─────────────────────────────────────
    _update_topic_tracker(state, prompt, intent, newly_injected)

    # ─── Phase 2: Sync reminders (existing logic) ────────────────────
    mod_count = len(state.get("modified_files", []))
    kq_count = len(state.get("knowledge_queue", []))
    sync_kw = config.get("sync_keywords", [])
    prompt_has_sync = any(kw in prompt for kw in sync_kw)

    if prompt_has_sync and (mod_count > 0 or kq_count > 0):
        lines.append(f"[Guardian] Sync context: {mod_count} files modified, {kq_count} knowledge items pending.")
        if mod_count > 0:
            files = list({m["path"] for m in state["modified_files"]})
            lines.append(f"Files: {', '.join(f.rsplit('/', 1)[-1] for f in files[:10])}")
        if kq_count > 0:
            for q in state["knowledge_queue"]:
                lines.append(f"  - {q.get('classification', '[臨]')} {q['content'][:60]}")
    elif mod_count > 0 or kq_count > 0:
        remind_after = config.get("remind_after_turns", 3)
        remind_count = state.get("remind_count", 0)
        if remind_count < remind_after:
            state["remind_count"] = remind_count + 1
        else:
            max_reminders = config.get("max_reminders", 3)
            total_reminds = state.get("total_reminds", 0)
            if total_reminds < max_reminders:
                lines.append(
                    f"[Guardian] Reminder: {mod_count} files modified, {kq_count} knowledge items pending. "
                    "Consider syncing when current task completes."
                )
                state["remind_count"] = 0
                state["total_reminds"] = total_reminds + 1

    write_state(session_id, state)

    if lines:
        # V2.11: Context budget hard cap
        lines = _truncate_context_by_activation(lines, budget)
        output_json({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "\n".join(lines),
            }
        })
    else:
        output_nothing()


def handle_post_tool_use(input_data: Dict[str, Any], config: Dict[str, Any]) -> None:
    session_id = input_data.get("session_id", "")
    state = read_state(session_id)
    if not state:
        output_nothing()
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if tool_name in ("Edit", "Write") and file_path:
        state.setdefault("modified_files", []).append({
            "path": file_path,
            "tool": tool_name,
            "at": _now_iso(),
        })
        state["sync_pending"] = True

        # V2.11: Track per-file edit counts for over-engineering detection
        edit_counts = state.setdefault("edit_counts", {})
        edit_counts[file_path] = edit_counts.get(file_path, 0) + 1

        # V2.8: Wisdom Engine retry tracking
        if WISDOM_AVAILABLE:
            try:
                wisdom_track_retry(state, file_path)
            except Exception as e:
                print(f"[v2.8] Wisdom retry track error: {e}", file=sys.stderr)

        # V2.7: Check if this file was modified in a previous session
        try:
            qf = _check_output_quality(file_path, session_id, config)
            if qf:
                state.setdefault("quality_feedback", {}).setdefault(
                    "rewritten_files", []
                ).append(qf)
                print(
                    f"[v2.7] Quality feedback: {file_path} was also modified "
                    f"in session {qf['original_session']}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[v2.7] Quality check error: {e}", file=sys.stderr)

        write_state(session_id, state)

        # Trigger incremental vector index if an atom file was modified
        normalized = file_path.replace("\\", "/")
        if "/memory/" in normalized and normalized.endswith(".md"):
            _trigger_incremental_index(config)

    elif tool_name == "Read" and file_path:
        # V2.10: Read Tracking — deduplicate, keep first occurrence only
        accessed = state.setdefault("accessed_files", [])
        if not any(a["path"] == file_path for a in accessed):
            accessed.append({"path": file_path, "at": _now_iso()})
            write_state(session_id, state)

    elif tool_name == "Bash":
        # V2.10: VCS query capture (git log/blame/show/diff, svn log/blame/diff)
        command = tool_input.get("command", "")
        if re.search(r"\b(git\s+(log|blame|show|diff)|svn\s+(log|blame|diff))\b", command):
            vcs = state.setdefault("vcs_queries", [])
            vcs.append({"command": command[:200], "at": _now_iso()})
            write_state(session_id, state)

    output_nothing()


def handle_pre_compact(input_data: Dict[str, Any], config: Dict[str, Any]) -> None:
    session_id = input_data.get("session_id", "")
    state = read_state(session_id)
    if not state:
        output_nothing()
        return

    # Mark snapshot for recovery after compaction
    state["pre_compact_snapshot"] = _now_iso()
    write_state(session_id, state)
    output_nothing()


def handle_stop(input_data: Dict[str, Any], config: Dict[str, Any]) -> None:
    session_id = input_data.get("session_id", "")
    state = read_state(session_id)
    if not state:
        output_nothing()
        return

    max_blocks = config.get("stop_gate_max_blocks", 2)
    stop_count = state.get("stop_blocked_count", 0)
    phase = state.get("phase", "working")

    # Anti-loop guard
    if stop_count >= max_blocks:
        state["phase"] = "done"
        write_state(session_id, state)
        output_nothing()
        return

    # Already synced or marked done
    if phase in ("done", "syncing"):
        output_nothing()
        return

    # Check if sync is needed
    mod_count = len(state.get("modified_files", []))
    kq_count = len(state.get("knowledge_queue", []))
    unique_files = list({m["path"] for m in state.get("modified_files", [])})
    min_files = config.get("min_files_to_block", 2)

    # Muted session — always allow
    if state.get("muted"):
        output_nothing()
        return

    # Nothing to sync
    if mod_count == 0 and kq_count == 0:
        state["phase"] = "done"
        write_state(session_id, state)
        output_nothing()
        return

    # Below threshold: soft reminder only (no block)
    if len(unique_files) < min_files and kq_count == 0:
        state["phase"] = "done"
        write_state(session_id, state)
        output_nothing()
        return

    # Block: meaningful sync needed
    state["stop_blocked_count"] = stop_count + 1
    write_state(session_id, state)

    file_names = ", ".join(f.rsplit("/", 1)[-1] for f in unique_files[:8])

    reason = (
        f"[Workflow Guardian] This session modified {len(unique_files)} file(s)"
        + (f" and has {kq_count} pending knowledge item(s)" if kq_count > 0 else "")
        + f". Files: {file_names}.\n"
        "Please check CLAUDE.md sync rules and ask the user which sync steps apply."
    )

    output_block(reason)


# ─── Episodic Memory Auto-Generation (v2.1 Task #2) ─────────────────────────


def _should_generate_episodic(state: Dict[str, Any], config: Dict[str, Any]) -> bool:
    """Check if this session warrants an episodic atom."""
    ep_cfg = config.get("episodic", {})
    if not ep_cfg.get("auto_generate", True):
        return False

    mod_count = len(state.get("modified_files", []))
    read_count = len(state.get("accessed_files", []))
    kq_count = len(state.get("knowledge_queue", []))
    min_files = ep_cfg.get("min_files", 1)

    # V2.10: Pure-read sessions (≥5 files) also warrant episodic atoms
    if mod_count < min_files and kq_count == 0 and read_count < 5:
        return False

    # Skip very short sessions (< 2 minutes)
    started = state.get("session", {}).get("started_at", "")
    ended = state.get("ended_at", "")
    if started and ended:
        try:
            t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(ended.replace("Z", "+00:00"))
            if (t1 - t0).total_seconds() < ep_cfg.get("min_duration_seconds", 120):
                return False
        except (ValueError, TypeError):
            pass

    return True


def _extract_area(path_str: str) -> str:
    """Extract a human-readable work area slug from a file path."""
    path = path_str.replace("\\", "/")

    # Known prefix mappings
    home = str(Path.home()).replace("\\", "/")
    claude_base = f"{home}/.claude/"
    if path.startswith(claude_base):
        rest = path[len(claude_base):]
        seg = rest.split("/")[0]
        area_map = {"memory": "memory-system", "tools": "memory-tools",
                     "hooks": "guardian", "workflow": "guardian", "plans": "planning"}
        return area_map.get(seg, seg)

    # Strip home prefix
    if path.startswith(home + "/"):
        path = path[len(home) + 1:]
    # Strip drive letter
    if len(path) > 2 and path[1] == ":":
        path = path[2:].lstrip("/")

    parts = [p for p in path.split("/") if p]
    # Take first 2 meaningful segments
    slug_parts = parts[:2] if len(parts) >= 2 else parts[:1]
    return "-".join(slug_parts).lower() if slug_parts else "misc"


# ─── V2.4: Response Knowledge Capture ─────────────────────────────────────

def _find_session_transcript(session_id: str, cwd: str) -> Optional[Path]:
    """Locate the JSONL transcript for this session.

    Path format: ~/.claude/projects/{slug}/{session_id}.jsonl
    """
    if not session_id or not cwd:
        return None
    slug = cwd_to_project_slug(cwd)
    candidate = CLAUDE_DIR / "projects" / slug / f"{session_id}.jsonl"
    if candidate.exists():
        return candidate
    return None


def _extract_all_assistant_texts(transcript_path: Path, max_chars: int = 20000) -> List[str]:
    """Extract all assistant text responses from a JSONL transcript (for SessionEnd)."""
    texts = []
    total = 0
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
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
                        if t and len(t) > 30:  # skip trivial responses
                            texts.append(t)
                            total += len(t)
                if total >= max_chars:
                    break
    except (OSError, UnicodeDecodeError):
        pass
    return texts


def _call_ollama_generate(prompt: str, model: str = None,
                          timeout: int = 120) -> str:
    """Call Ollama generate API via dual-backend client.

    Default timeout=120s: qwen3 thinking mode needs ~30s on GTX 1050 Ti.
    Background threads (extraction) can afford to wait.
    """
    try:
        client = get_client()
        # think="auto" → rdchat: think=True + 8192, local: think=False + 2048
        # 不用 format="json" — qwen3.5 thinking mode 與 JSON constrained decoding 衝突
        return client.generate(
            prompt, model=model, timeout=timeout,
            temperature=0.1, think="auto",
        )
    except Exception:
        return ""


_EXTRACT_PROMPT_TEMPLATE = (
    "你是「原子記憶系統」的知識萃取器。從 AI 回應中萃取可跨 session 重用的知識。\n"
    "輸出 JSON array: [{{\"content\": \"精簡事實，最多150字\", "
    "\"type\": \"factual|procedural|architectural|pitfall|decision\"}}]\n\n"
    "只萃取：根因分析、API 行為、架構限制、除錯模式、設定值、環境特有行為。\n"
    "不萃取：程式碼變更、通用程式知識、session 進度、問候語。\n"
    "沒有值得萃取的內容就輸出 []。直接輸出 JSON。\n\n"
    "回應文字:\n{text}\n\nJSON:"
)


def _llm_extract_knowledge(text: str, existing_queue: List[dict],
                           source: str = "session-end") -> List[dict]:
    """Use local LLM to extract knowledge from assistant text (SessionEnd only).

    Args:
        text: Assistant response text
        existing_queue: Already queued knowledge items (for dedup)
        source: extraction source label

    Returns:
        List of knowledge items: [{content, classification, knowledge_type, source, at}]
    """
    if not text or len(text) < 50:
        return []

    max_chars = 4000
    max_items = 5

    truncated = text[:max_chars]
    prompt = _EXTRACT_PROMPT_TEMPLATE.format(text=truncated)

    raw = _call_ollama_generate(prompt)
    if not raw:
        return []

    # Parse JSON (with fallback)
    items = []
    try:
        # Try to find JSON array in response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            items = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        # Regex fallback: try to extract content/type pairs
        for m in re.finditer(r'"content"\s*:\s*"([^"]{10,150})"', raw):
            items.append({"content": m.group(1), "type": "factual"})

    if not items:
        return []

    # Dedup against existing queue
    existing_fingerprints = {
        q.get("content", "")[:40].lower() for q in existing_queue
    }

    results = []
    now = _now_iso()
    for item in items[:max_items]:
        content = item.get("content", "").strip()
        if not content or len(content) < 10:
            continue
        # Skip if too similar to existing
        if content[:40].lower() in existing_fingerprints:
            continue
        knowledge_type = item.get("type", "factual")
        if knowledge_type not in ("factual", "procedural", "architectural", "pitfall", "decision"):
            knowledge_type = "factual"
        results.append({
            "content": content[:150],
            "classification": "[臨]",
            "knowledge_type": knowledge_type,
            "source": source,
            "at": now,
        })
        existing_fingerprints.add(content[:40].lower())

    return results


# ─── V2.4 Phase 3: Cross-Session Pattern Consolidation ────────────────────


def _check_cross_session_patterns(
    knowledge_items: List[dict], session_id: str, config: Dict[str, Any]
) -> List[dict]:
    """Check if knowledge items appeared in past sessions via vector search.

    For each item, query vector service top-3 (min_score: 0.75).
    Count distinct sessions that mention similar knowledge.
    - 2+ sessions → auto-promote [臨] → [觀]
    - 4+ sessions → mark suggestion to promote [觀] → [固] (not auto)

    Returns list of cross-session observation dicts for episodic atom.
    Also mutates knowledge_items in-place (classification upgrade).
    """
    vs_config = config.get("vector_search", {})
    if not vs_config.get("enabled", True):
        return []

    port = vs_config.get("service_port", 3849)
    cross_session_config = config.get("cross_session", {})
    min_score = cross_session_config.get("min_score", 0.75)
    promote_threshold = cross_session_config.get("promote_threshold", 2)
    suggest_threshold = cross_session_config.get("suggest_threshold", 4)
    timeout_s = cross_session_config.get("timeout_seconds", 5)

    observations: List[dict] = []
    current_session_prefix = session_id[:8] if session_id else ""

    for item in knowledge_items:
        content = item.get("content", "")
        if not content or len(content) < 20:
            continue

        # Query vector search for similar knowledge
        try:
            import urllib.parse
            params = urllib.parse.urlencode({
                "q": content[:200],
                "top_k": 5,
                "min_score": min_score,
            })
            url = f"http://127.0.0.1:{port}/search/ranked?{params}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    results = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    # Fallback to basic /search
                    params = urllib.parse.urlencode({
                        "q": content[:200], "top_k": 5, "min_score": min_score,
                    })
                    url = f"http://127.0.0.1:{port}/search?{params}"
                    req = urllib.request.Request(url, headers={"Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                        results = json.loads(resp.read())
                else:
                    continue

            # Count distinct sessions from results (episodic atoms encode session info)
            session_hits = set()
            for r in results:
                atom_name = r.get("atom_name", "")
                file_path = r.get("file_path", "")
                # Episodic atoms: "episodic-YYYYMMDD-slug" → each is a different session
                if "episodic" in atom_name.lower():
                    # Exclude current session's atom (prefix match)
                    if current_session_prefix and current_session_prefix in atom_name:
                        continue
                    session_hits.add(atom_name)
                else:
                    # Non-episodic atoms: check if they contain session references
                    # Count as 1 additional session reference if content matches
                    atom_text = r.get("text", r.get("content", ""))
                    if atom_text:
                        session_hits.add(f"atom:{atom_name}")

            hit_count = len(session_hits)
            if hit_count < promote_threshold:
                continue

            # V2.11: No auto-promote — Confirmations +1 only, hint at 4+
            current_class = item.get("classification", "[臨]")
            action = ""

            if hit_count >= suggest_threshold:
                action = f"建議晉升（{hit_count} sessions 命中，需使用者確認）"
            else:
                action = f"跨 session 命中 {hit_count} 次（Confirmations +1）"

            # Increment Confirmations in matched atom files
            for r in results:
                atom_file = r.get("file_path", "")
                if atom_file and os.path.isfile(atom_file):
                    try:
                        atom_text = Path(atom_file).read_text(encoding="utf-8-sig")
                        cm = re.search(r"^(- Confirmations:\s*)(\d+)", atom_text, re.MULTILINE)
                        if cm:
                            new_c = int(cm.group(2)) + 1
                            atom_text = re.sub(
                                r"^(- Confirmations:\s*)\d+", rf"\g<1>{new_c}",
                                atom_text, count=1, flags=re.MULTILINE,
                            )
                            Path(atom_file).write_text(atom_text, encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        pass

            observations.append({
                "content": content[:80],
                "classification": current_class,
                "sessions_hit": hit_count,
                "action": action,
                "matched_atoms": list(session_hits)[:5],
            })

            print(
                f"[v2.11] Cross-session: \"{content[:40]}...\" → {action}",
                file=sys.stderr,
            )

        except Exception as e:
            print(f"[v2.4] Cross-session check error: {e}", file=sys.stderr)
            continue

    return observations


# ─── V2.11: Conflict Detection ─────────────────────────────────────────────


def _detect_atom_conflicts(
    state: Dict[str, Any], config: Dict[str, Any]
) -> List[dict]:
    """Detect potential conflicts between session-modified atoms and existing atoms.

    For each modified atom file, query vector search (score 0.60-0.95).
    Results in that range suggest semantically similar but different content — potential conflicts.
    """
    vs_config = config.get("vector_search", {})
    if not vs_config.get("enabled", True):
        return []

    port = vs_config.get("service_port", 3849)
    timeout_s = 5
    conflicts: List[dict] = []

    modified = state.get("modified_files", [])
    atom_files = [
        m for m in modified
        if "/memory/" in m.get("path", "").replace("\\", "/")
        and m.get("path", "").endswith(".md")
    ]

    for m in atom_files:
        fpath = m["path"]
        try:
            content = Path(fpath).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue

        # Use first 200 chars as query
        query = content[:200].strip()
        if len(query) < 30:
            continue

        try:
            import urllib.parse
            params = urllib.parse.urlencode({
                "q": query, "top_k": 5, "min_score": 0.60,
            })
            url = f"http://127.0.0.1:{port}/search/ranked?{params}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    results = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    params = urllib.parse.urlencode({
                        "q": query, "top_k": 5, "min_score": 0.60,
                    })
                    url = f"http://127.0.0.1:{port}/search?{params}"
                    req = urllib.request.Request(url, headers={"Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                        results = json.loads(resp.read())
                else:
                    continue

            fname = Path(fpath).stem
            for r in results:
                score = r.get("score", 0)
                other_name = r.get("atom_name", "")
                other_path = r.get("file_path", "")
                # Skip self-match (same file or score > 0.95)
                if score > 0.95 or other_name == fname:
                    continue
                if other_path and os.path.normpath(other_path) == os.path.normpath(fpath):
                    continue
                conflicts.append({
                    "source": fname,
                    "target": other_name,
                    "score": round(score, 3),
                    "snippet": r.get("text", r.get("content", ""))[:80],
                })

        except Exception as e:
            print(f"[v2.11] Conflict detection error: {e}", file=sys.stderr)
            continue

    return conflicts


# ─── End V2.11 Conflict Detection ─────────────────────────────────────────


def _build_episodic_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    """Build structured session summary from state."""
    from collections import Counter

    modified = state.get("modified_files", [])
    area_counts: Counter = Counter()
    for m in modified:
        area = _extract_area(m.get("path", ""))
        area_counts[area] += 1

    work_areas = [{"area": a, "count": c} for a, c in area_counts.most_common()]
    primary_area = work_areas[0]["area"] if work_areas else "session-work"

    knowledge_items = []
    for kq in state.get("knowledge_queue", []):
        knowledge_items.append({
            "content": kq.get("content", "")[:80],
            "classification": kq.get("classification", "[臨]"),
        })

    atoms_referenced = list(state.get("injected_atoms", []))

    # V2.10: Read tracking
    accessed = state.get("accessed_files", [])
    accessed_areas: Counter = Counter()
    for a in accessed:
        area = _extract_area(a.get("path", ""))
        accessed_areas[area] += 1

    # Topic tracker enrichment (v2.2)
    tracker = state.get("topic_tracker", {})
    intent_dist = tracker.get("intent_distribution", {})
    dominant_intent = max(intent_dist, key=intent_dist.get) if intent_dist else "general"

    # V2.10: Use accessed areas as fallback for primary_area when no modifications
    if not work_areas and accessed_areas:
        acc_areas = [{"area": a, "count": c} for a, c in accessed_areas.most_common()]
        primary_area = acc_areas[0]["area"] if acc_areas else "session-work"

    return {
        "work_areas": work_areas,
        "knowledge_items": knowledge_items,
        "atoms_referenced": atoms_referenced,
        "files_modified": len(modified),
        "primary_area": primary_area,
        "dominant_intent": dominant_intent,
        "intent_distribution": intent_dist,
        "prompt_count": tracker.get("prompt_count", 0),
        "session_description": tracker.get("first_prompt_summary", ""),
        "keyword_topics": tracker.get("keyword_signals", []),
        "related_episodic": tracker.get("related_episodic", []),
        "accessed_files": accessed,
        "files_accessed": len(accessed),
        "accessed_areas": [{"area": a, "count": c} for a, c in accessed_areas.most_common()],
        "vcs_queries": state.get("vcs_queries", []),
    }


def _derive_short_summary(primary_area: str) -> str:
    """Generate a kebab-case slug for the episodic atom filename (<=30 chars, ASCII)."""
    slug = primary_area.lower()
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:30] or "session-work"


def _resolve_episodic_filename(memory_dir: Path, date_str: str, slug: str) -> Path:
    """Resolve unique filename, handling same-day dedup."""
    base = f"episodic-{date_str}-{slug}"
    candidate = memory_dir / f"{base}.md"
    if not candidate.exists():
        return candidate
    for i in range(2, 20):
        candidate = memory_dir / f"{base}-{i}.md"
        if not candidate.exists():
            return candidate
    return memory_dir / f"{base}-{int(datetime.now().timestamp()) % 10000}.md"


def _generate_triggers(state: Dict[str, Any], work_areas: list) -> list:
    """Auto-generate trigger keywords from session data."""
    triggers = {"session", "episodic"}

    for wa in work_areas:
        for word in wa["area"].split("-"):
            if len(word) >= 3:
                triggers.add(word.lower())

    for kq in state.get("knowledge_queue", []):
        words = re.findall(r"\b[a-zA-Z]{4,}\b", kq.get("content", ""))
        for w in words[:3]:
            triggers.add(w.lower())

    for atom_name in state.get("injected_atoms", []):
        triggers.add(atom_name.lower())

    # Keyword topics from topic tracker (v2.2)
    for kw in state.get("topic_tracker", {}).get("keyword_signals", [])[:5]:
        triggers.add(kw.lower())

    return sorted(triggers)[:12]


def _update_memory_index(memory_dir: Path, atom_name: str, triggers: list) -> None:
    """Append a row to MEMORY.md atom index table."""
    index_path = memory_dir / MEMORY_INDEX
    if not index_path.exists():
        return

    text = index_path.read_text(encoding="utf-8-sig")
    trigger_str = ", ".join(triggers)
    new_row = f"| {atom_name} | memory/{atom_name}.md | {trigger_str} |"

    lines = text.splitlines()
    insert_idx = None
    in_table = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("| Atom") or stripped.startswith("|Atom"):
            in_table = True
            continue
        if in_table:
            if stripped.startswith("|---"):
                continue
            if stripped.startswith("|"):
                insert_idx = i
            else:
                break

    if insert_idx is not None:
        lines.insert(insert_idx + 1, new_row)
    else:
        lines.append(new_row)

    index_path.write_text("\n".join(lines), encoding="utf-8")


def _build_read_tracking_section(summary: Dict[str, Any]) -> str:
    """Build '## 閱讀軌跡' section from accessed files and VCS queries (V2.10)."""
    accessed = summary.get("accessed_files", [])
    vcs = summary.get("vcs_queries", [])
    if not accessed and not vcs:
        return ""
    lines = ["## 閱讀軌跡\n"]
    for af in accessed[:30]:
        lines.append(f"- {af['path']}")
    if accessed:
        lines.append("")
    if vcs:
        lines.append("### 版控查詢")
        for v in vcs[:10]:
            lines.append(f"- `{v['command']}`")
        lines.append("")
    lines.append("")
    return "\n".join(lines)


def _build_cross_session_section(state: Dict[str, Any]) -> str:
    """Build '## 跨 Session 觀察' section from cross-session observations."""
    obs = state.get("cross_session_observations", [])
    if not obs:
        return ""
    lines = ["## 跨 Session 觀察\n"]
    for o in obs:
        cls = o.get("classification", "[觀]")
        content = o.get("content", "")
        action = o.get("action", "")
        hits = o.get("sessions_hit", 0)
        lines.append(f"- [{cls.strip('[]')}] \"{content}\" — {hits} sessions 出現，{action}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def _build_conflict_section(state: Dict[str, Any]) -> str:
    """V2.11: Build '## ⚠ 衝突警告' section from conflict detection results."""
    warnings = state.get("conflict_warnings", [])
    if not warnings:
        return ""
    lines = ["## ⚠ 衝突警告\n"]
    for w in warnings:
        lines.append(
            f"- {w['source']} ↔ {w['target']} (score={w['score']}) "
            f"— \"{w.get('snippet', '')[:60]}\""
        )
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def _resolve_episodic_dir(state: Dict[str, Any]) -> Tuple[Path, str]:
    """Resolve episodic directory: project-scoped if CWD maps to a project, else global.

    Returns (episodic_dir, scope_label).
    """
    cwd = state.get("session", {}).get("cwd", "")
    if cwd:
        project_mem = get_project_memory_dir(cwd)
        if project_mem:
            slug = cwd_to_project_slug(cwd)
            return project_mem / "episodic", f"project:{slug}"
    return EPISODIC_DIR, "global"


def _generate_episodic_atom(
    session_id: str, state: Dict[str, Any], config: Dict[str, Any]
) -> Optional[str]:
    """Auto-generate an episodic atom summarizing this session.

    Returns the filename of the generated atom, or None if skipped.
    Project-scoped: if CWD maps to a known project, episodic goes to project layer.
    """
    if not _should_generate_episodic(state, config):
        return None

    from datetime import timedelta

    summary = _build_episodic_summary(state)
    slug = _derive_short_summary(summary["primary_area"])
    today = datetime.now().strftime("%Y-%m-%d")
    date_compact = datetime.now().strftime("%Y%m%d")
    expires = (datetime.now() + timedelta(days=24)).strftime("%Y-%m-%d")
    triggers = _generate_triggers(state, summary["work_areas"])

    episodic_dir, scope_label = _resolve_episodic_dir(state)
    episodic_dir.mkdir(parents=True, exist_ok=True)
    atom_path = _resolve_episodic_filename(episodic_dir, date_compact, slug)
    atom_name = atom_path.stem

    # Build knowledge lines
    knowledge_lines = []
    if summary["work_areas"]:
        areas_str = ", ".join(
            f"{wa['area']} ({wa['count']} files)" for wa in summary["work_areas"]
        )
        knowledge_lines.append(f"- [臨] 工作區域: {areas_str}")
    knowledge_lines.append(f"- [臨] 修改 {summary['files_modified']} 個檔案")
    if summary["atoms_referenced"]:
        knowledge_lines.append(
            f"- [臨] 引用 atoms: {', '.join(summary['atoms_referenced'])}"
        )
    for ki in summary["knowledge_items"]:
        knowledge_lines.append(f"- [{ki['classification'].strip('[]')}] {ki['content']}")

    # V2.10: Read tracking summary
    if summary.get("files_accessed", 0) > 0:
        knowledge_lines.append(f"- [臨] 閱讀 {summary['files_accessed']} 個檔案")
        if summary.get("accessed_areas"):
            read_areas_str = ", ".join(
                f"{ra['area']} ({ra['count']})" for ra in summary["accessed_areas"][:5]
            )
            knowledge_lines.append(f"- [臨] 閱讀區域: {read_areas_str}")
    vcs = summary.get("vcs_queries", [])
    if vcs:
        knowledge_lines.append(f"- [臨] 版控查詢 {len(vcs)} 次")

    # Build 摘要 section (v2.2)
    desc = summary.get("session_description", "")
    dom_intent = summary.get("dominant_intent", "general")
    prompt_count = summary.get("prompt_count", 0)
    summary_line = f"{dom_intent.capitalize()}-focused session ({prompt_count} prompts)."
    if desc:
        summary_line += f" {desc}"

    # Build 關聯 section (v2.2)
    relation_lines = []
    intent_dist = summary.get("intent_distribution", {})
    if intent_dist:
        dist_str = ", ".join(f"{k} ({v})" for k, v in
                             sorted(intent_dist.items(), key=lambda x: -x[1]))
        relation_lines.append(f"- 意圖分布: {dist_str}")
    related_ep = summary.get("related_episodic", [])
    if related_ep:
        relation_lines.append(f"- Related sessions: {', '.join(related_ep)}")
    if summary["atoms_referenced"]:
        relation_lines.append(
            f"- Referenced atoms: {', '.join(summary['atoms_referenced'])}"
        )

    content = (
        f"# Session: {today} {summary['primary_area']}\n"
        f"\n"
        f"- Scope: {scope_label}\n"
        f"- Confidence: [臨]\n"
        f"- Type: episodic\n"
        f"- Trigger: {', '.join(triggers)}\n"
        f"- Last-used: {today}\n"
        f"- Created: {today}\n"
        f"- Confirmations: 0\n"
        f"- TTL: 24d\n"
        f"- Expires-at: {expires}\n"
        f"\n"
        f"## 摘要\n"
        f"\n"
        f"{summary_line}\n"
        f"\n"
        f"## 知識\n"
        f"\n"
        + "\n".join(knowledge_lines)
        + f"\n"
        f"\n"
        + (f"## 關聯\n\n" + "\n".join(relation_lines) + "\n\n" if relation_lines else "")
        + _build_read_tracking_section(summary)
        + _build_cross_session_section(state)
        + _build_conflict_section(state)
        + f"## 行動\n"
        f"\n"
        f"- session 自動摘要，TTL 24d 後自動淘汰\n"
        f"- 若需長期保留特定知識，應遷移至專屬 atom\n"
        f"\n"
        f"## 演化日誌\n"
        f"\n"
        f"| 日期 | 變更 | 來源 |\n"
        f"|------|------|------|\n"
        f"| {today} | 自動建立 episodic atom (v2.2) | session:{session_id[:8]} |\n"
    )

    atom_path.write_text(content, encoding="utf-8")
    # v2.2: Episodic atoms NOT listed in MEMORY.md index (TTL 24d, vector search discovers them)

    print(f"[episodic] Generated: {atom_path.name} (scope: {scope_label})", file=sys.stderr)
    return atom_name


def handle_session_end(input_data: Dict[str, Any], config: Dict[str, Any]) -> None:
    session_id = input_data.get("session_id", "")
    state = read_state(session_id)
    if not state:
        sys.exit(0)
        return

    state["ended_at"] = _now_iso()
    state["phase"] = "done"

    # ─── V2.11-fix: Spawn extract-worker.py as detached subprocess ──────
    # extract-worker handles: transcript reading, LLM extraction, cross-session
    # observation, and pattern aggregation — all independently of hook timeout.
    rc = config.get("response_capture", {})
    if rc.get("enabled", True):
        try:
            import subprocess
            cwd = state.get("session", {}).get("cwd", "")
            tracker = state.get("topic_tracker", {})
            intent = tracker.get("intent_distribution", {}).get("top", "build")
            worker_ctx = json.dumps({
                "session_id": session_id,
                "cwd": cwd,
                "config": config,
                "knowledge_queue": state.get("knowledge_queue", []),
                "session_intent": intent,
            }, ensure_ascii=False)
            worker_path = CLAUDE_DIR / "hooks" / "extract-worker.py"
            if worker_path.exists():
                # Detached subprocess: survives hook timeout
                kwargs = {}
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                else:
                    kwargs["start_new_session"] = True
                worker_log = CLAUDE_DIR / "workflow" / "extract-worker.log"
                worker_log_fh = open(worker_log, "a", encoding="utf-8")
                proc = subprocess.Popen(
                    [sys.executable, str(worker_path)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=worker_log_fh,
                    **kwargs,
                )
                worker_log_fh.close()  # fd inherited by child; parent can close
                proc.stdin.write(worker_ctx.encode("utf-8"))
                proc.stdin.close()
                print(
                    f"[v2.11] extract-worker spawned (pid={proc.pid}, intent={intent})",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[v2.11] extract-worker spawn error: {e}", file=sys.stderr)

    mod_count = len(state.get("modified_files", []))
    kq_count = len(state.get("knowledge_queue", []))
    if state.get("sync_pending") and (mod_count > 0 or kq_count > 0):
        print(
            f"Warning: Session ending with unsaved work. "
            f"{mod_count} modified files, {kq_count} knowledge items.",
            file=sys.stderr,
        )

    # ─── V2.6: Self-iteration metrics + oscillation detection ──────
    try:
        metrics = _collect_iteration_metrics(state)
        state["iteration_metrics"] = metrics

        oscillations = _detect_oscillation(state, config)
        if oscillations:
            state["iteration_metrics"]["oscillations"] = oscillations
            for osc in oscillations:
                print(
                    f"[v2.6] Oscillation detected: {osc['atom']} "
                    f"({osc['count']} sessions)",
                    file=sys.stderr,
                )
    except Exception as e:
        print(f"[v2.6] Self-iteration metrics error: {e}", file=sys.stderr)

    # ─── V2.8: Wisdom Engine — session reflection ────────────────────
    if WISDOM_AVAILABLE:
        try:
            wisdom_reflect(state)
        except Exception as e:
            print(f"[v2.8] Wisdom reflect error: {e}", file=sys.stderr)

    # ─── V2.11: over_engineering 統計已由 wisdom_reflect(state) 統一處理 ────
    # （track_retry 累計 wisdom_retry_count → reflect() 寫入 reflection_metrics）
    try:
        edit_counts = state.get("edit_counts", {})
        if edit_counts:
            reverted = sum(1 for c in edit_counts.values() if c >= 2)
            if reverted > 0:
                print(
                    f"[v2.11] Over-engineering: {reverted}/{len(edit_counts)} files "
                    f"edited 2+ times",
                    file=sys.stderr,
                )
    except Exception as e:
        print(f"[v2.11] Over-engineering metrics error: {e}", file=sys.stderr)

    # V2.10: Staging area reminder
    staging_dir = MEMORY_DIR / "_staging"
    if staging_dir.exists():
        staging_files = list(staging_dir.glob("*.md"))
        if staging_files:
            print(
                f"[v2.10] _staging/ 有 {len(staging_files)} 個暫存檔案待清理",
                file=sys.stderr,
            )

    # ─── V2.11: Conflict detection ──────────────────────────────────
    try:
        conflict_warnings = _detect_atom_conflicts(state, config)
        if conflict_warnings:
            state["conflict_warnings"] = conflict_warnings
            for cw in conflict_warnings:
                print(
                    f"[v2.11] Conflict: {cw['source']} ↔ {cw['target']} "
                    f"(score={cw['score']})",
                    file=sys.stderr,
                )
    except Exception as e:
        print(f"[v2.11] Conflict detection error: {e}", file=sys.stderr)

    # v2.1 Task #2: Auto-generate episodic atom
    episodic_generated = False
    if config.get("episodic", {}).get("auto_generate", True):
        try:
            _generate_episodic_atom(session_id, state, config)
            episodic_generated = True
        except Exception as e:
            print(f"[episodic] generation failed: {e}", file=sys.stderr)

    # V2.11-fix: Save review marker if review was due this session
    if state.get("review_due"):
        try:
            total = sum(1 for _ in EPISODIC_DIR.glob("episodic-*.md")) if EPISODIC_DIR.exists() else 0
            _save_review_marker(total)
            print(f"[v2.6] Review marker saved (total={total})", file=sys.stderr)
        except Exception as e:
            print(f"[v2.6] Review marker save error: {e}", file=sys.stderr)

    write_state(session_id, state)

    # v2.1 Sprint 3: Trigger incremental vector index if atoms were modified
    modified = state.get("modified_files", [])
    has_atom_changes = any(
        "/memory/" in m.get("path", "").replace("\\", "/")
        and m.get("path", "").endswith(".md")
        for m in modified
    )
    if has_atom_changes or episodic_generated:
        _trigger_incremental_index(config)

    sys.exit(0)


# ─── Dispatcher ──────────────────────────────────────────────────────────────

HANDLERS = {
    "SessionStart": handle_session_start,
    "UserPromptSubmit": handle_user_prompt_submit,
    "PostToolUse": handle_post_tool_use,
    "PreCompact": handle_pre_compact,
    "Stop": handle_stop,
    "SessionEnd": handle_session_end,
}


def main():
    # Force UTF-8 output on Windows
    if sys.platform == "win32":
        sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)
        sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', closefd=False)

    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)

    # Read JSON from stdin
    try:
        raw = sys.stdin.buffer.read()
        input_data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Can't parse input; exit silently (non-blocking)
        sys.exit(0)

    config = load_config()
    if not config.get("enabled", True):
        sys.exit(0)

    event = input_data.get("hook_event_name", "")
    handler = HANDLERS.get(event)
    if handler:
        try:
            handler(input_data, config)
        except Exception as e:
            # Never crash; log to stderr (verbose mode only) and continue
            print(f"[workflow-guardian] Error in {event}: {e}", file=sys.stderr)
            sys.exit(0)
    else:
        sys.exit(0)



# ─── V2.7: Output Quality Feedback ──────────────────────────────────────────


def _check_output_quality(
    file_path: str, session_id: str, config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Check if file_path was modified in a recent (different) session.

    Scans recent state files for ended sessions. If the same file was
    modified in a previous session, returns a quality feedback record.
    Returns None if no match or if the file is a memory/plan file.
    """
    normalized = file_path.replace("\\", "/").lower()

    # Skip memory atoms and plan files — they're expected to be updated often
    if "/memory/" in normalized or "/plans/" in normalized:
        return None

    scan_count = config.get("quality_feedback", {}).get("scan_recent_sessions", 5)

    try:
        state_files = sorted(
            WORKFLOW_DIR.glob("state-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return None

    for sf in state_files[:scan_count + 5]:  # scan extra to skip active sessions
        sid = sf.stem.replace("state-", "")
        if sid == session_id:
            continue

        try:
            with sf.open(encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            continue

        # Only check ended sessions
        if not prev.get("ended_at"):
            continue

        prev_files = {
            m.get("path", "").replace("\\", "/").lower()
            for m in prev.get("modified_files", [])
        }

        if normalized in prev_files:
            return {
                "path": file_path,
                "original_session": sid[:8],
                "original_ended": prev.get("ended_at", ""),
                "at": _now_iso(),
            }

    return None


# ─── V2.6: Self-Iteration Engine ────────────────────────────────────────────


def _collect_iteration_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    """Collect self-iteration metrics from session state.

    Gathers atoms referenced (injected_atoms) and atoms modified
    (modified_files matching memory/*.md) into iteration_metrics.
    """
    metrics = state.get("iteration_metrics", {})

    # Atoms referenced this session
    referenced = list(set(state.get("injected_atoms", [])))
    metrics["atoms_referenced"] = referenced

    # Atoms modified this session (extract atom names from modified file paths)
    modified_atoms = []
    for m in state.get("modified_files", []):
        p = m.get("path", "").replace("\\", "/")
        if "/memory/" in p and p.endswith(".md"):
            name = p.rsplit("/", 1)[-1].replace(".md", "")
            if name not in ("MEMORY", "_CHANGELOG", "_CHANGELOG_ARCHIVE"):
                modified_atoms.append(name)
    metrics["atoms_modified"] = list(set(modified_atoms))

    return metrics


def _detect_oscillation(
    state: Dict[str, Any], config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Detect atoms modified 2+ times across last 3 sessions (oscillation).

    Scans recent episodic atoms for overlapping atom modification patterns.
    Returns list of {atom, sessions, recommendation}.
    """
    oscillation_window = config.get("self_iteration", {}).get("oscillation_window", 3)
    oscillation_threshold = config.get("self_iteration", {}).get("oscillation_threshold", 2)

    # Find recent episodic atoms
    episodic_dirs = set()
    # Global episodic
    global_ep = MEMORY_DIR / "episodic"
    if global_ep.exists():
        episodic_dirs.add(global_ep)
    # Project episodic
    cwd = state.get("session", {}).get("cwd", "")
    proj_mem = get_project_memory_dir(cwd)
    if proj_mem:
        proj_ep = proj_mem / "episodic"
        if proj_ep.exists():
            episodic_dirs.add(proj_ep)

    # Collect recent episodic files (sorted by mtime, newest first)
    recent_files = []
    for ep_dir in episodic_dirs:
        for f in ep_dir.glob("episodic-*.md"):
            recent_files.append((f.stat().st_mtime, f))
    recent_files.sort(key=lambda x: -x[0])
    recent_files = recent_files[:oscillation_window]

    # Parse each episodic for MODIFIED atoms (not just referenced)
    atom_sessions = {}  # atom_name -> [session_dates]
    for _, ep_path in recent_files:
        try:
            text = ep_path.read_text(encoding="utf-8")
            date_match = re.search(r"Created:\s*(\d{4}-\d{2}-\d{2})", text)
            ep_date = date_match.group(1) if date_match else ep_path.stem[:15]
            for line in text.split("\n"):
                # Only look at "修改 atoms:" lines (written by V2.6+), NOT "引用 atoms:"
                if "修改 atoms:" in line:
                    atoms_part = line.split("修改 atoms:")[-1].strip()
                    for a in atoms_part.split(","):
                        a = a.strip()
                        if a:
                            atom_sessions.setdefault(a, []).append(ep_date)
        except (OSError, UnicodeDecodeError):
            continue

    # Also include current session's modified atoms
    current_modified = state.get("iteration_metrics", {}).get("atoms_modified", [])
    today = datetime.now().strftime("%Y-%m-%d")
    for a in current_modified:
        atom_sessions.setdefault(a, []).append(today)

    # Detect oscillation: same atom touched in N+ distinct sessions
    oscillations = []
    for atom_name, sessions in atom_sessions.items():
        unique_sessions = list(set(sessions))
        if len(unique_sessions) >= oscillation_threshold:
            oscillations.append({
                "atom": atom_name,
                "sessions": unique_sessions,
                "count": len(unique_sessions),
                "recommendation": "暫停修改此 atom，等待更多證據再決定方向"
            })

    return oscillations


def _calculate_maturity_phase(config: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate system maturity phase based on episodic atom count.

    Returns {phase, total_sessions, description}.
    Phases: learning (<15), stable (15-50), mature (>50)
    """
    thresholds = config.get("self_iteration", {}).get("maturity_thresholds", {})
    learning_max = thresholds.get("learning", 15)
    stable_max = thresholds.get("stable", 50)

    # Count all episodic atoms across all known directories
    total = 0
    for ep_dir in [MEMORY_DIR / "episodic"]:
        if ep_dir.exists():
            total += sum(1 for _ in ep_dir.glob("episodic-*.md"))

    # Also check project episodic dirs
    projects_dir = CLAUDE_DIR / "projects"
    if projects_dir.exists():
        for proj in projects_dir.iterdir():
            ep = proj / "memory" / "episodic"
            if ep.exists():
                total += sum(1 for _ in ep.glob("episodic-*.md"))

    if total < learning_max:
        phase = "learning"
        desc = f"學習期（{total}/{learning_max} sessions）— 積極學習新模式"
    elif total < stable_max:
        phase = "stable"
        desc = f"穩定期（{total}/{stable_max} sessions）— 收斂規則，減少新增"
    else:
        phase = "mature"
        desc = f"成熟期（{total} sessions）— 極少新增，專注精煉"

    return {"phase": phase, "total_sessions": total, "description": desc}


def _check_periodic_review_due(config: Dict[str, Any]) -> Optional[str]:
    """Check if periodic self-review is due.

    Counts episodic atoms since last review marker.
    Returns review reminder text if due, None otherwise.
    """
    review_interval = config.get("self_iteration", {}).get("review_interval", 6)
    marker_path = WORKFLOW_DIR / "last_review_marker.json"

    # Read last review marker
    last_review_session_count = 0
    if marker_path.exists():
        try:
            with open(marker_path, "r", encoding="utf-8") as f:
                marker = json.load(f)
            last_review_session_count = marker.get("session_count", 0)
        except (json.JSONDecodeError, OSError):
            pass

    # Count current total sessions
    total = 0
    for ep_dir in [MEMORY_DIR / "episodic"]:
        if ep_dir.exists():
            total += sum(1 for _ in ep_dir.glob("episodic-*.md"))
    projects_dir = CLAUDE_DIR / "projects"
    if projects_dir.exists():
        for proj in projects_dir.iterdir():
            ep = proj / "memory" / "episodic"
            if ep.exists():
                total += sum(1 for _ in ep.glob("episodic-*.md"))

    sessions_since_review = total - last_review_session_count
    if sessions_since_review >= review_interval:
        maturity = _calculate_maturity_phase(config)
        return (
            f"[自我迭代] 定期檢閱到期（距上次 {sessions_since_review} sessions）。"
            f"系統{maturity['description']}。"
            f"建議在適當時機進行近期 session 回顧：掃描 episodic atoms、"
            f"找出重複模式、收攏或晉升規則。"
        )
    return None


def _save_review_marker(total_sessions: int) -> None:
    """Save review marker after a periodic review is completed."""
    marker_path = WORKFLOW_DIR / "last_review_marker.json"
    marker = {
        "session_count": total_sessions,
        "reviewed_at": _now_iso(),
    }
    try:
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(marker, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


if __name__ == "__main__":
    main()
