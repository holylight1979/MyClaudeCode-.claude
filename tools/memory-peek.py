#!/usr/bin/env python3
"""
memory-peek.py — V4.1 /memory-peek backend

Lists recent auto-extracted atoms + pending candidates + trigger reasons.
Scans personal/auto/{user}/ for atoms with author=auto-extracted-v4.1.

Output: JSON with written[] and pending[] arrays.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HOOKS_DIR = Path.home() / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))
from wg_paths import find_project_root, CLAUDE_DIR  # noqa: E402
from wg_roles import get_current_user  # noqa: E402


def _parse_duration(since_str: str) -> Optional[timedelta]:
    """Parse '24h', '48h', '7d' etc. into timedelta."""
    m = re.match(r'^(\d+)\s*([hHdD])$', since_str.strip())
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2).lower()
    if unit == 'h':
        return timedelta(hours=val)
    if unit == 'd':
        return timedelta(days=val)
    return None


def _parse_since(since_str: str) -> Optional[datetime]:
    """Parse --since value: duration ('24h') or date ('2026-04-16')."""
    if not since_str:
        return None
    # Try duration first
    td = _parse_duration(since_str)
    if td:
        return datetime.now(timezone.utc) - td
    # Try date
    try:
        dt = datetime.strptime(since_str, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _resolve_auto_dir(user: str, cwd: str) -> List[Path]:
    """Find all auto dirs: project-level + global-level."""
    dirs = []
    project_root = find_project_root(cwd) if cwd else None
    if project_root:
        d = Path(project_root) / ".claude" / "memory" / "personal" / "auto" / user
        if d.is_dir():
            dirs.append(d)
    # Global level
    d = CLAUDE_DIR / "memory" / "personal" / "auto" / user
    if d.is_dir() and d not in dirs:
        dirs.append(d)
    return dirs


def _parse_atom_metadata(path: Path) -> Dict[str, Any]:
    """Parse atom file metadata fields."""
    meta: Dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return meta

    meta["_raw"] = text
    for line in text.splitlines():
        m = re.match(r'^-\s*([\w-]+):\s*(.+)\s*$', line)
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()

    # Extract source from footer comment
    src_match = re.search(r'<!--\s*src:\s*(.+?)\s*-->', text)
    if src_match:
        meta["source"] = src_match.group(1).strip()

    # Extract statement from 知識 section
    stmt_match = re.search(r'##\s*知識\s*\n+\s*-\s*\[.+?\]\s*(.+)', text)
    if stmt_match:
        meta["statement"] = stmt_match.group(1).strip()

    return meta


def _get_file_created_time(path: Path, meta: Dict) -> Optional[datetime]:
    """Get atom creation time from metadata 'created' field or file mtime."""
    created = meta.get("created", "")
    if created:
        try:
            dt = datetime.strptime(created, "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    # Fallback: file mtime
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except OSError:
        return None


def _scan_written_atoms(user: str, cwd: str, since: datetime) -> List[Dict[str, Any]]:
    """Scan personal/auto/{user}/ for recently written atoms."""
    results = []
    for auto_dir in _resolve_auto_dir(user, cwd):
        for md_file in sorted(auto_dir.glob("*.md")):
            if md_file.name.startswith("_"):
                continue  # skip _pending.candidates.md, _rejected/
            meta = _parse_atom_metadata(md_file)
            author = meta.get("author", "")
            if "auto-extracted-v4.1" not in author:
                continue
            created = _get_file_created_time(md_file, meta)
            if created and created < since:
                continue
            results.append({
                "path": str(md_file),
                "filename": md_file.name,
                "statement": meta.get("statement", md_file.stem),
                "trigger": meta.get("trigger", ""),
                "scope": meta.get("scope", "personal"),
                "created": meta.get("created", ""),
                "source": meta.get("source", ""),
                "confidence": meta.get("confidence", ""),
            })
    # Sort by created desc
    results.sort(key=lambda x: x.get("created", ""), reverse=True)
    return results


def _scan_pending_candidates(user: str, cwd: str, since: datetime) -> List[Dict[str, Any]]:
    """Scan _pending.candidates.md for entries within time window."""
    results = []
    for auto_dir in _resolve_auto_dir(user, cwd):
        pending_file = auto_dir / "_pending.candidates.md"
        if not pending_file.is_file():
            continue
        try:
            text = pending_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("- ["):
                continue
            # Parse: - [2026-04-16 14:30] conf=0.78 scope=personal turn=xxx: statement
            m = re.match(
                r'^-\s*\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s*'
                r'conf=([\d.]+)\s+scope=(\S+)\s+turn=(\S*):\s*(.+)$',
                line,
            )
            if not m:
                continue
            ts_str, conf, scope, turn, statement = m.groups()
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if ts < since:
                continue
            results.append({
                "timestamp": ts_str,
                "conf": float(conf),
                "scope": scope,
                "turn_id": turn,
                "statement": statement.strip(),
                "source_file": str(pending_file),
            })
    results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return results


def main():
    ap = argparse.ArgumentParser(description="V4.1 /memory-peek backend")
    ap.add_argument("--user", default=None)
    ap.add_argument("--project-cwd", default="")
    ap.add_argument("--since", default="24h",
                    help="Time window: '24h', '48h', '7d', or date '2026-04-16'")
    args = ap.parse_args()

    user = args.user or get_current_user()
    cwd = args.project_cwd or ""

    since_dt = _parse_since(args.since)
    if not since_dt:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=24)

    written = _scan_written_atoms(user, cwd, since_dt)
    pending = _scan_pending_candidates(user, cwd, since_dt)

    result = {
        "user": user,
        "since": since_dt.strftime("%Y-%m-%d %H:%M UTC"),
        "written": written,
        "written_count": len(written),
        "pending": pending,
        "pending_count": len(pending),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
