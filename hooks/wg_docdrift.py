"""
wg_docdrift.py — DocDrift Detection Module (V3.3)

Detects when source files are modified without updating corresponding _AIDocs.
Integrates into PostToolUse handler via check_source_drift / resolve_doc_update.

Inspired by PR #1 (@wellstseng).
"""

import fnmatch
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Ensure hooks/ in path ──────────────────────────────────────────────────
_HOOKS_DIR = str(Path(__file__).resolve().parent)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from wg_core import _now_iso

# ─── Defaults ───────────────────────────────────────────────────────────────

_DEFAULT_EXCLUDES = [
    "_aidocs/", "memory/", "_staging/", ".git/",
    "node_modules/", "__pycache__/", ".claude/workflow/",
]


# ─── Private helpers ────────────────────────────────────────────────────────

def _normalize(path: str) -> str:
    return path.replace("\\", "/").lower()


def _is_aidocs_path(normalized: str) -> bool:
    return "/_aidocs/" in normalized or normalized.endswith("/_aidocs")


def _is_excluded(normalized: str, config: dict) -> bool:
    dd_cfg = config.get("docdrift", {})
    excludes = dd_cfg.get("exclude_patterns", _DEFAULT_EXCLUDES)
    for pat in excludes:
        if pat in normalized:
            return True
    return False


def _relative_path(file_path: str, state: dict) -> Optional[str]:
    """Compute path relative to project root (or ~/.claude/)."""
    normalized = _normalize(file_path)
    project_root = state.get("aidocs", {}).get("project_root", "")
    if project_root:
        root_norm = _normalize(project_root).rstrip("/") + "/"
        if normalized.startswith(root_norm):
            return normalized[len(root_norm):]
    # Fallback: strip up to .claude/
    idx = normalized.find("/.claude/")
    if idx >= 0:
        return normalized[idx + len("/.claude/"):]
    return None


def _drift_key(source: str, doc: str) -> str:
    return f"{source}\u2192{doc}"


def _tokenize_path(rel_path: str) -> set:
    """Decompose a relative path into matchable tokens."""
    # Split on / then on _ - .
    parts = rel_path.replace("\\", "/").lower().split("/")
    tokens = set()
    for part in parts:
        # Remove extension
        stem = part.rsplit(".", 1)[0] if "." in part else part
        tokens.add(stem)
        # Further split on _ and -
        for sub in re.split(r"[_\-]", stem):
            if len(sub) > 1:
                tokens.add(sub)
    return tokens


def _match_source_to_docs(rel_path: str, state: dict, config: dict) -> List[str]:
    """Map a source file to corresponding _AIDocs entries.

    Tier 1: config explicit path_mappings (fnmatch).
    Tier 2: keyword fallback from state["aidocs"]["keywords"].
    """
    dd_cfg = config.get("docdrift", {})

    # Tier 1: explicit mappings
    mappings = dd_cfg.get("path_mappings", {})
    for pattern, docs in mappings.items():
        if fnmatch.fnmatch(rel_path, pattern):
            return docs if isinstance(docs, list) else [docs]

    # Tier 2: keyword fallback
    keywords_map = state.get("aidocs", {}).get("keywords", {})
    if not keywords_map:
        return []

    threshold = dd_cfg.get("keyword_match_threshold", 2)
    path_tokens = _tokenize_path(rel_path)
    matches = []

    for doc_name, kw_list in keywords_map.items():
        hit = 0
        for kw in kw_list:
            kw_lower = kw.lower()
            if kw_lower in path_tokens or any(kw_lower in t for t in path_tokens):
                hit += 1
                if hit >= threshold:
                    matches.append(doc_name)
                    break

    return matches


# ─── Stale-entry pruning (committed/reverted source files) ──────────────────

def _git_dirty_files(project_root: str) -> Optional[set]:
    """Return set of normalized rel paths that are dirty (modified/staged/untracked).
    Returns None if not in a git repo or git unavailable — caller treats as 'don't prune'.
    """
    if not project_root:
        return None
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    dirty = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        # Format: "XY path" or "XY orig -> path" (rename)
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        # Strip surrounding quotes if path contains spaces (git may quote)
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        dirty.add(_normalize(path))
    return dirty


def prune_committed_entries(state: dict, config: dict) -> int:
    """Remove pending entries whose source file is no longer dirty in git.
    Auto-resolves drift entries from prior sessions where the source was
    committed/reverted but no _AIDocs edit fired resolve_doc_update.
    Returns count of entries pruned.
    """
    pending = state.get("docdrift_pending")
    if not pending:
        return 0
    if not config.get("docdrift", {}).get("auto_prune_committed", True):
        return 0
    project_root = state.get("aidocs", {}).get("project_root", "")
    dirty = _git_dirty_files(project_root)
    if dirty is None:
        return 0
    pruned = 0
    for k in list(pending.keys()):
        src_norm = _normalize(pending[k]["source"])
        if src_norm not in dirty:
            del pending[k]
            print(f"[v3.3] DocDrift auto-pruned (not dirty): {k}", file=sys.stderr)
            pruned += 1
    return pruned


# ─── Public API ─────────────────────────────────────────────────────────────

def check_source_drift(file_path: str, state: dict, config: dict) -> None:
    """Called on Edit/Write of non-AIDocs files. Adds drift entries if mapped."""
    if not config.get("docdrift", {}).get("enabled", True):
        return

    normalized = _normalize(file_path)
    if _is_aidocs_path(normalized) or _is_excluded(normalized, config):
        return

    rel = _relative_path(file_path, state)
    if not rel:
        return

    docs = _match_source_to_docs(rel, state, config)
    if not docs:
        return

    pending = state.setdefault("docdrift_pending", {})
    for doc in docs:
        key = _drift_key(rel, doc)
        if key not in pending:
            pending[key] = {
                "source": rel,
                "doc": doc,
                "added_at": _now_iso(),
            }
            print(f"[v3.3] DocDrift: {rel} \u2192 {doc}", file=sys.stderr)


def resolve_doc_update(file_path: str, state: dict, config: dict) -> None:
    """Called on Edit/Write of _AIDocs files. Resolves matching drift entries."""
    pending = state.get("docdrift_pending")
    if not pending:
        return

    normalized = _normalize(file_path)
    # Extract the doc filename (handle subdirectories like ClaudeCodeInternals/foo.md)
    # Match against the last 1 or 2 path components after _aidocs/
    aidocs_idx = normalized.find("/_aidocs/")
    if aidocs_idx < 0:
        return
    doc_rel = normalized[aidocs_idx + len("/_aidocs/"):]

    # Resolve: match both full relative path and just the filename
    doc_filename = doc_rel.rsplit("/", 1)[-1]
    keys_to_remove = [
        k for k, v in pending.items()
        if v["doc"].lower() == doc_filename or v["doc"].lower() == doc_rel
    ]
    for k in keys_to_remove:
        del pending[k]
        print(f"[v3.3] DocDrift resolved: {k}", file=sys.stderr)


def build_drift_advisory(state: dict, config: dict) -> Optional[str]:
    """Build advisory string from pending drift entries. Returns None if empty."""
    pending = state.get("docdrift_pending", {})
    if not pending:
        return None

    max_display = config.get("docdrift", {}).get("max_pending_display", 5)

    lines = []
    for i, (_, v) in enumerate(pending.items()):
        if i >= max_display:
            lines.append(f"  ...and {len(pending) - max_display} more")
            break
        lines.append(f"  {v['source']} \u2192 {v['doc']}")

    return (
        "Source files changed without updating corresponding _AIDocs:\n"
        + "\n".join(lines)
        + "\nConsider updating these docs before ending the session."
    )
