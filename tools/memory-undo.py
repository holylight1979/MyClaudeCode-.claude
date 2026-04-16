#!/usr/bin/env python3
"""
memory-undo.py — V4.1 /memory-undo backend

Revokes auto-extracted atoms: moves to _rejected/ with reason + timestamp.
Writes back to reflection_metrics.json v41_extraction block.

Supports: last, --since=<time>, --all-from-today, --list (dry-run).
"""

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional

HOOKS_DIR = Path.home() / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))
from wg_paths import find_project_root, CLAUDE_DIR, MEMORY_DIR  # noqa: E402
from wg_roles import get_current_user  # noqa: E402

REFLECTION_METRICS_PATH = MEMORY_DIR / "wisdom" / "reflection_metrics.json"

REJECT_REASONS = {
    "a": "emotion",       # 情緒誤抓
    "b": "ambiguous",     # 含蓄誤判
    "c": "privacy",       # 隱私越界
    "d": "scope",         # scope 錯
    "e": "other",         # 其他
    # Also accept full names
    "emotion": "emotion",
    "ambiguous": "ambiguous",
    "privacy": "privacy",
    "scope": "scope",
    "other": "other",
}


def _parse_duration(since_str: str) -> Optional[timedelta]:
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
    if not since_str:
        return None
    td = _parse_duration(since_str)
    if td:
        return datetime.now(timezone.utc) - td
    try:
        dt = datetime.strptime(since_str, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _resolve_auto_dirs(user: str, cwd: str) -> List[Path]:
    dirs = []
    project_root = find_project_root(cwd) if cwd else None
    if project_root:
        d = Path(project_root) / ".claude" / "memory" / "personal" / "auto" / user
        if d.is_dir():
            dirs.append(d)
    d = CLAUDE_DIR / "memory" / "personal" / "auto" / user
    if d.is_dir() and d not in dirs:
        dirs.append(d)
    return dirs


def _parse_atom_metadata(path: Path) -> Dict[str, Any]:
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
    src_match = re.search(r'<!--\s*src:\s*(.+?)\s*-->', text)
    if src_match:
        meta["source"] = src_match.group(1).strip()
    stmt_match = re.search(r'##\s*知識\s*\n+\s*-\s*\[.+?\]\s*(.+)', text)
    if stmt_match:
        meta["statement"] = stmt_match.group(1).strip()
    return meta


def _get_file_created_time(path: Path, meta: Dict) -> Optional[datetime]:
    created = meta.get("created", "")
    if created:
        try:
            dt = datetime.strptime(created, "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except OSError:
        return None


def _collect_candidates(
    user: str, cwd: str, mode: str, since_str: str,
) -> List[Dict[str, Any]]:
    """Collect atoms eligible for undo.

    mode: 'last' | 'since' | 'all-from-today'
    """
    all_atoms = []
    for auto_dir in _resolve_auto_dirs(user, cwd):
        for md_file in sorted(auto_dir.glob("*.md")):
            if md_file.name.startswith("_"):
                continue
            meta = _parse_atom_metadata(md_file)
            author = meta.get("author", "")
            if "auto-extracted-v4.1" not in author:
                continue
            created = _get_file_created_time(md_file, meta)
            all_atoms.append({
                "path": md_file,
                "filename": md_file.name,
                "statement": meta.get("statement", md_file.stem),
                "trigger": meta.get("trigger", ""),
                "created": created,
                "created_str": meta.get("created", ""),
                "auto_dir": auto_dir,
            })

    # Sort by created desc (newest first)
    all_atoms.sort(key=lambda x: x["created"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    if mode == "last":
        return all_atoms[:1]

    if mode == "all-from-today":
        today_str = date.today().isoformat()
        return [a for a in all_atoms if a.get("created_str", "") == today_str]

    if mode == "since":
        since_dt = _parse_since(since_str)
        if not since_dt:
            since_dt = datetime.now(timezone.utc) - timedelta(hours=24)
        return [a for a in all_atoms if a["created"] and a["created"] >= since_dt]

    return all_atoms[:1]  # default = last


def _execute_undo(candidates: List[Dict], reason_key: str) -> Dict[str, Any]:
    """Move atoms to _rejected/ and append reject footer."""
    reason = REJECT_REASONS.get(reason_key, "other")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    undone = []

    for atom in candidates:
        path: Path = atom["path"]
        auto_dir: Path = atom["auto_dir"]
        rejected_dir = auto_dir / "_rejected"
        rejected_dir.mkdir(parents=True, exist_ok=True)

        dest = rejected_dir / path.name
        # Handle name collision
        if dest.exists():
            for i in range(2, 100):
                alt = rejected_dir / f"{path.stem}-{i}{path.suffix}"
                if not alt.exists():
                    dest = alt
                    break

        # Append reject footer to file content before moving
        try:
            content = path.read_text(encoding="utf-8")
            content = content.rstrip() + f"\n<!-- rejected: {reason}, {now_str} -->\n"
            dest.write_text(content, encoding="utf-8")
            path.unlink()
            undone.append({
                "filename": path.name,
                "statement": atom.get("statement", ""),
                "moved_to": str(dest),
                "reason": reason,
            })
        except OSError as e:
            undone.append({
                "filename": path.name,
                "error": str(e),
            })

    return {"undone": undone, "count": len([u for u in undone if "error" not in u]), "reason": reason}


def _update_reflection_metrics(reason: str, undo_count: int) -> bool:
    """Update v41_extraction block in reflection_metrics.json."""
    try:
        if REFLECTION_METRICS_PATH.is_file():
            data = json.loads(REFLECTION_METRICS_PATH.read_text(encoding="utf-8"))
        else:
            data = {}

        v41 = data.setdefault("v41_extraction", {
            "total_written": 0,
            "total_rejected": 0,
            "reject_reasons": {
                "emotion": 0,
                "ambiguous": 0,
                "privacy": 0,
                "scope": 0,
                "other": 0,
            },
            "precision_observed": 1.0,
        })

        v41["total_rejected"] = v41.get("total_rejected", 0) + undo_count
        reasons = v41.setdefault("reject_reasons", {
            "emotion": 0, "ambiguous": 0, "privacy": 0, "scope": 0, "other": 0,
        })
        reasons[reason] = reasons.get(reason, 0) + undo_count

        # Recalculate precision
        total_w = v41.get("total_written", 0)
        total_r = v41.get("total_rejected", 0)
        if total_w > 0:
            v41["precision_observed"] = round((total_w - total_r) / total_w, 4)
        else:
            v41["precision_observed"] = 1.0

        tmp = REFLECTION_METRICS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(REFLECTION_METRICS_PATH)
        return True
    except (OSError, json.JSONDecodeError) as e:
        print(f"[memory-undo] reflection_metrics update failed: {e}", file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser(description="V4.1 /memory-undo backend")
    ap.add_argument("--user", default=None)
    ap.add_argument("--project-cwd", default="")
    ap.add_argument("--list", action="store_true", help="Dry-run: list candidates only")
    ap.add_argument("--execute", action="store_true", help="Actually perform undo")
    ap.add_argument("--reason", default="a",
                    help="Reject reason: a=emotion b=ambiguous c=privacy d=scope e=other")
    ap.add_argument("--since", default="",
                    help="Time filter: '24h', '48h', or date '2026-04-16'")
    ap.add_argument("--all-from-today", action="store_true")
    ap.add_argument("target", nargs="?", default="last",
                    help="'last' (default) or atom slug prefix")
    args = ap.parse_args()

    user = args.user or get_current_user()
    cwd = args.project_cwd or ""

    # Determine mode
    if args.all_from_today:
        mode = "all-from-today"
    elif args.since:
        mode = "since"
    else:
        mode = "last"

    candidates = _collect_candidates(user, cwd, mode, args.since)

    if args.list or not args.execute:
        # Dry-run output
        items = []
        for c in candidates:
            items.append({
                "filename": c["filename"],
                "statement": c.get("statement", ""),
                "trigger": c.get("trigger", ""),
                "created": c.get("created_str", ""),
            })
        print(json.dumps({
            "mode": mode,
            "candidates": items,
            "count": len(items),
            "hint": "Use --execute --reason=<a-e> to confirm undo.",
        }, ensure_ascii=False, indent=2))
        return

    if not candidates:
        print(json.dumps({
            "ok": True,
            "count": 0,
            "message": "沒有符合條件的自動萃取 atom 可撤銷。",
        }, ensure_ascii=False, indent=2))
        return

    # Execute undo
    result = _execute_undo(candidates, args.reason)
    reason = result["reason"]
    count = result["count"]

    # Update reflection_metrics
    metrics_ok = _update_reflection_metrics(reason, count) if count > 0 else True

    print(json.dumps({
        "ok": True,
        "count": count,
        "reason": reason,
        "undone": result["undone"],
        "reflection_metrics_updated": metrics_ok,
        "message": f"已撤銷 {count} 條。/memory-peek 查看剩餘。",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
