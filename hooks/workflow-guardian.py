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
import os
import sys
import re
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── Constants ───────────────────────────────────────────────────────────────

CLAUDE_DIR = Path.home() / ".claude"
WORKFLOW_DIR = CLAUDE_DIR / "workflow"
MEMORY_DIR = CLAUDE_DIR / "memory"
EPISODIC_DIR = MEMORY_DIR / "episodic"
CONFIG_PATH = WORKFLOW_DIR / "config.json"
MEMORY_INDEX = "MEMORY.md"

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
    # v2.2 Sprint 2: Proactive classification
    "proactive": {
        "auto_promote_lin": True,   # [臨]→[觀] auto-promote
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

        g_names = [n for n, _, _ in global_atoms]
        p_names = [n for n, _, _ in project_atoms]
        lines = [
            "[Workflow Guardian] Active.",
            f"Global atoms: {', '.join(g_names) if g_names else 'none'}.",
        ]
        if p_names:
            lines.append(f"Project atoms: {', '.join(p_names)}.")
        lines.append("I will track file modifications and remind you to sync before ending.")

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
    lines: List[str] = []

    # ─── V2.4: Collect pending extraction from last turn ──────────────
    pending = state.pop("pending_extraction", [])
    if pending:
        state.setdefault("knowledge_queue", []).extend(pending)
        lines.append(
            f"[V2.4] {len(pending)} knowledge items captured from last response: "
            + "; ".join(f"[{p.get('knowledge_type','?')}] {p['content'][:50]}" for p in pending)
        )

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

        # ── Related atom auto-loading (v2.1 Sprint 2) ─────────────
        RELATED_RE = re.compile(r"^- Related:\s*(.+)", re.MULTILINE)
        for (name, rel_path, triggers), base_dir in list(matched_with_dir):
            atom_path = (base_dir / rel_path) if rel_path else (base_dir / "memory" / f"{name}.md")
            if not atom_path.exists():
                continue
            try:
                atom_text = atom_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            rm = RELATED_RE.search(atom_text)
            if not rm:
                continue
            related_names = [r.strip() for r in rm.group(1).split(",") if r.strip()]
            for rn in related_names:
                if rn in already_injected or rn in newly_injected:
                    continue
                # Find related atom in all_atoms
                for (aname, arel, atrig), abase in all_atoms:
                    if aname == rn:
                        rpath = (abase / arel) if arel else (abase / "memory" / f"{rn}.md")
                        if rpath.exists():
                            try:
                                first_line = rpath.read_text(encoding="utf-8-sig").split("\n", 1)[0].strip("# ").strip()
                            except (OSError, UnicodeDecodeError):
                                break
                            atom_lines.append(f"[Atom:{rn}] (related\u2192{name}) {first_line}")
                            newly_injected.append(rn)
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
                        # Promotion logic (v2.2) — auto-promote [臨]→[觀], hint [觀]→[固]
                        if new_count is not None:
                            conf_m = confidence_re.search(text)
                            if conf_m:
                                cur = conf_m.group(1)
                                threshold = PROMOTION_THRESHOLDS.get(cur)
                                if threshold and new_count >= threshold:
                                    target = PROMOTION_TARGETS[cur]
                                    pro_config = config.get("proactive", {})
                                    if cur == "[臨]" and pro_config.get("auto_promote_lin", True):
                                        # Auto-promote [臨]→[觀]: low risk
                                        text = text.replace(
                                            f"- Confidence: {cur}",
                                            f"- Confidence: {target}",
                                            1,
                                        )
                                        apath.write_text(text, encoding="utf-8")
                                        lines.append(
                                            f"✅ [{inj_name}] 已自動晉升 {cur}→{target}"
                                            f"（Confirmations={new_count}）"
                                        )
                                    else:
                                        # [觀]→[固]: high-confidence change, ask user
                                        lines.append(
                                            f"⚡ [{inj_name}] Confirmations={new_count}, "
                                            f"目前{cur}, 已達{target}門檻，"
                                            f"觸及相關行為時請主動確認是否晉升"
                                        )
                    except (OSError, UnicodeDecodeError):
                        pass
                    break

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
        output_json({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "\n".join(lines),
            }
        })
    else:
        output_nothing()

    # ─── V2.4: Launch background extraction of last assistant response ──
    rc = config.get("response_capture", {})
    if rc.get("enabled", True) and rc.get("per_turn_enabled", True):
        cwd = state.get("session", {}).get("cwd", "")
        if cwd and state.get("session_context_injected", False):
            # Only after first prompt (there's no previous response on first prompt)
            t = threading.Thread(
                target=_async_extract_last_response,
                args=(session_id, cwd, config),
                daemon=True,
            )
            t.start()


def handle_post_tool_use(input_data: Dict[str, Any], config: Dict[str, Any]) -> None:
    session_id = input_data.get("session_id", "")
    state = read_state(session_id)
    if not state:
        output_nothing()
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if file_path:
        state.setdefault("modified_files", []).append({
            "path": file_path,
            "tool": tool_name,
            "at": _now_iso(),
        })
        state["sync_pending"] = True
        write_state(session_id, state)

        # Trigger incremental vector index if an atom file was modified
        normalized = file_path.replace("\\", "/")
        if "/memory/" in normalized and normalized.endswith(".md"):
            _trigger_incremental_index(config)

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
    kq_count = len(state.get("knowledge_queue", []))
    min_files = ep_cfg.get("min_files", 1)

    if mod_count < min_files and kq_count == 0:
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


def _extract_last_assistant_text(transcript_path: Path, max_chars: int = 3000) -> str:
    """Extract the last assistant text response from a JSONL transcript.

    Reads from end, skips thinking/tool_use blocks, returns text only.
    """
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines_raw = f.readlines()
    except (OSError, UnicodeDecodeError):
        return ""

    # Scan from end to find last assistant message with text content
    for raw_line in reversed(lines_raw):
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        content = obj.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        texts = []
        total = 0
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "")
                if t:
                    texts.append(t)
                    total += len(t)
                    if total >= max_chars:
                        break
        if texts:
            combined = "\n".join(texts)
            return combined[:max_chars]
    return ""


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


def _call_ollama_generate(prompt: str, model: str = "qwen3:1.7b",
                          timeout: int = 3) -> str:
    """Call Ollama generate API. Returns raw response text."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 500}
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("response", "")
    except Exception:
        return ""


_EXTRACT_PROMPT_TEMPLATE = (
    "Extract reusable technical knowledge from this AI assistant response. "
    "Output a JSON array of objects, each with 'content' (max 80 chars, concise fact) "
    "and 'type' (one of: factual, procedural, architectural, pitfall). "
    "Only extract: root causes, API behaviors, architecture constraints, "
    "debugging patterns, configuration values, environment-specific behaviors. "
    "Skip: code changes, general programming knowledge, session-specific details, greetings. "
    "If nothing worth extracting, output empty array [].\n\n"
    "Response text:\n{text}\n\nJSON:"
)


def _llm_extract_knowledge(text: str, existing_queue: List[dict],
                           source: str = "per-turn") -> List[dict]:
    """Use local LLM (qwen3:1.7b) to extract knowledge from assistant text.

    Args:
        text: Assistant response text
        existing_queue: Already queued knowledge items (for dedup)
        source: "per-turn" or "session-end" (affects limits and timeout)

    Returns:
        List of knowledge items: [{content, classification, knowledge_type, source, at}]
    """
    if not text or len(text) < 50:
        return []

    # Source-dependent limits
    if source == "per-turn":
        max_chars = 3000
        max_items = 2
        timeout = 3
    else:  # session-end
        max_chars = 4000
        max_items = 5
        timeout = 10

    truncated = text[:max_chars]
    prompt = _EXTRACT_PROMPT_TEMPLATE.format(text=truncated)

    raw = _call_ollama_generate(prompt, timeout=timeout)
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
        for m in re.finditer(r'"content"\s*:\s*"([^"]{10,80})"', raw):
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
        if knowledge_type not in ("factual", "procedural", "architectural", "pitfall"):
            knowledge_type = "factual"
        results.append({
            "content": content[:80],
            "classification": "[臨]",
            "knowledge_type": knowledge_type,
            "source": source,
            "at": now,
        })
        existing_fingerprints.add(content[:40].lower())

    return results


def _async_extract_last_response(session_id: str, cwd: str, config: dict) -> None:
    """Background thread: extract knowledge from last assistant response → write to state."""
    try:
        transcript = _find_session_transcript(session_id, cwd)
        if not transcript:
            return

        rc = config.get("response_capture", {})
        max_chars = rc.get("per_turn_max_chars", 3000)
        min_chars = rc.get("per_turn_min_response_chars", 100)

        text = _extract_last_assistant_text(transcript, max_chars=max_chars)
        if not text or len(text) < min_chars:
            return

        state = read_state(session_id)
        if not state:
            return
        existing = state.get("knowledge_queue", [])
        items = _llm_extract_knowledge(text, existing, source="per-turn")
        if items:
            # Re-read state for freshness (avoid race condition)
            state = read_state(session_id)
            if not state:
                return
            state["pending_extraction"] = items
            write_state(session_id, state)
            print(f"[v2.4] Per-turn extraction: {len(items)} items", file=sys.stderr)
    except Exception as e:
        print(f"[v2.4] Per-turn extraction error: {e}", file=sys.stderr)


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

            current_class = item.get("classification", "[臨]")
            new_class = current_class
            action = ""

            if hit_count >= suggest_threshold and current_class in ("[觀]", "[臨]"):
                # 4+ sessions: suggest [觀] → [固] (don't auto-execute)
                if current_class == "[臨]":
                    item["classification"] = "[觀]"
                    new_class = "[觀]"
                action = f"建議晉升 → [固]（{hit_count} sessions 命中，需使用者確認）"
            elif hit_count >= promote_threshold and current_class == "[臨]":
                # 2+ sessions: auto-promote [臨] → [觀]
                item["classification"] = "[觀]"
                new_class = "[觀]"
                action = f"自動晉升 [臨] → [觀]（{hit_count} sessions 命中）"

            if action:
                observations.append({
                    "content": content[:80],
                    "classification": new_class,
                    "sessions_hit": hit_count,
                    "action": action,
                    "matched_atoms": list(session_hits)[:5],
                })
                # Annotate the item's trigger_context
                prev_ctx = item.get("trigger_context", "")
                item["trigger_context"] = (
                    f"{prev_ctx} | cross-session: {hit_count} hits, {action}"
                ).strip(" | ")

                print(
                    f"[v2.4] Cross-session: \"{content[:40]}...\" → {action}",
                    file=sys.stderr,
                )

        except Exception as e:
            print(f"[v2.4] Cross-session check error: {e}", file=sys.stderr)
            continue

    return observations


# ─── End V2.4 ─────────────────────────────────────────────────────────────


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

    # Topic tracker enrichment (v2.2)
    tracker = state.get("topic_tracker", {})
    intent_dist = tracker.get("intent_distribution", {})
    dominant_intent = max(intent_dist, key=intent_dist.get) if intent_dist else "general"

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
        + _build_cross_session_section(state)
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

    # ─── V2.4: Collect any pending per-turn extraction ──────────────
    pending = state.pop("pending_extraction", [])
    if pending:
        state.setdefault("knowledge_queue", []).extend(pending)

    # ─── V2.4: SessionEnd transcript extraction (补漏) ────────────────
    rc = config.get("response_capture", {})
    if rc.get("enabled", True):
        try:
            cwd = state.get("session", {}).get("cwd", "")
            transcript = _find_session_transcript(session_id, cwd)
            if transcript:
                se_max = rc.get("session_end_max_chars", 20000)
                texts = _extract_all_assistant_texts(transcript, max_chars=se_max)
                if texts:
                    combined = "\n---\n".join(texts)
                    existing = state.get("knowledge_queue", [])
                    new_items = _llm_extract_knowledge(
                        combined, existing, source="session-end"
                    )
                    if new_items:
                        state.setdefault("knowledge_queue", []).extend(new_items)
                        print(
                            f"[v2.4] SessionEnd extraction: {len(new_items)} items",
                            file=sys.stderr,
                        )
        except Exception as e:
            print(f"[v2.4] SessionEnd extraction error: {e}", file=sys.stderr)

    # ─── V2.4 Phase 3: Cross-session pattern consolidation ──────────
    cross_obs = []
    kq = state.get("knowledge_queue", [])
    if kq and config.get("vector_search", {}).get("enabled", True):
        try:
            cross_obs = _check_cross_session_patterns(kq, session_id, config)
            if cross_obs:
                state["cross_session_observations"] = cross_obs
                print(
                    f"[v2.4] Cross-session: {len(cross_obs)} patterns detected",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[v2.4] Cross-session check error: {e}", file=sys.stderr)

    mod_count = len(state.get("modified_files", []))
    kq_count = len(state.get("knowledge_queue", []))
    if state.get("sync_pending") and (mod_count > 0 or kq_count > 0):
        print(
            f"Warning: Session ending with unsaved work. "
            f"{mod_count} modified files, {kq_count} knowledge items.",
            file=sys.stderr,
        )

    # v2.1 Task #2: Auto-generate episodic atom
    if config.get("episodic", {}).get("auto_generate", True):
        try:
            _generate_episodic_atom(session_id, state, config)
        except Exception as e:
            print(f"[episodic] generation failed: {e}", file=sys.stderr)

    write_state(session_id, state)

    # v2.1 Sprint 3: Trigger incremental vector index if atoms were modified
    modified = state.get("modified_files", [])
    has_atom_changes = any(
        "/memory/" in m.get("path", "").replace("\\", "/")
        and m.get("path", "").endswith(".md")
        for m in modified
    )
    if has_atom_changes:
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


if __name__ == "__main__":
    main()
