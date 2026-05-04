#!/usr/bin/env python3
"""audit-reconcile.py — 反向證明：列近期 mtime atom × 對拍 audit log

用途：funnel 收束後，反向確認「最近寫入的 atom 都有 audit log entry」。
若 atom mtime 比所有 audit entry 都新 → 繞過 funnel 寫入。

Usage:
    python audit-reconcile.py                   # 過去 1 hour
    python audit-reconcile.py --since 2h        # 過去 2 hours
    python audit-reconcile.py --since 1d        # 過去 1 day
    python audit-reconcile.py --json            # JSON 輸出

Exit: 0=ok / 1=unmatched found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

CLAUDE_DIR = Path.home() / ".claude"
GLOBAL_MEM = CLAUDE_DIR / "memory"
AUDIT_LOG = GLOBAL_MEM / "_meta" / "atom_io_audit.jsonl"

if str(CLAUDE_DIR) not in sys.path:
    sys.path.insert(0, str(CLAUDE_DIR))
from lib.atom_spec import is_atom_file, iter_atom_files  # noqa: E402

# tolerance: audit log timestamp may lag mtime by up to N seconds (atomic write
# is mtime first then jsonl append; usually < 100ms but allow 5s safety margin).
TOLERANCE_SEC = 5


def parse_since(s: str) -> int:
    m = re.match(r"^(\d+)\s*([smhd])$", s.strip().lower())
    if not m:
        raise ValueError(f"bad --since: {s} (use e.g. 30s/2h/1d)")
    val, unit = int(m.group(1)), m.group(2)
    return val * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def load_audit_entries(since_ts: float):
    """Yield audit entries with ts >= since_ts."""
    if not AUDIT_LOG.exists():
        return
    for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts_str = entry.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_str).timestamp()
        except (ValueError, TypeError):
            continue
        if ts >= since_ts - TOLERANCE_SEC:
            entry["_ts"] = ts
            entry["_path_lower"] = (entry.get("path") or "").lower()
            yield entry


def find_recent_atoms(since_ts: float) -> List[Path]:
    """All .md atom files (global + project layers) with mtime >= since_ts."""
    out = []
    # 1. global
    for p in iter_atom_files(GLOBAL_MEM):
        try:
            if p.stat().st_mtime >= since_ts:
                out.append(p)
        except OSError:
            pass
    # 2. project layers via project-registry.json
    reg = GLOBAL_MEM / "project-registry.json"
    if reg.exists():
        try:
            data = json.loads(reg.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        for slug, info in (data.get("projects") or {}).items():
            root = Path(info.get("root", ""))
            mem = root / ".claude" / "memory"
            if mem.is_dir():
                for p in iter_atom_files(mem):
                    try:
                        if p.stat().st_mtime >= since_ts:
                            out.append(p)
                    except OSError:
                        pass
    return out


def reconcile(since_seconds: int):
    now = time.time()
    since_ts = now - since_seconds

    audit_paths = {}  # path_lower → latest ts
    for e in load_audit_entries(since_ts):
        pl = e["_path_lower"]
        audit_paths[pl] = max(audit_paths.get(pl, 0), e["_ts"])

    recent = find_recent_atoms(since_ts)
    matched, unmatched = [], []
    for p in recent:
        pl = str(p).lower()
        mtime = p.stat().st_mtime
        audit_ts = audit_paths.get(pl)
        if audit_ts is not None and audit_ts + TOLERANCE_SEC >= mtime:
            matched.append((p, mtime, audit_ts))
        else:
            unmatched.append((p, mtime, audit_ts))
    return {
        "since_seconds": since_seconds,
        "since_iso": datetime.fromtimestamp(since_ts, tz=timezone.utc).isoformat(),
        "audit_entries_count": len(audit_paths),
        "atoms_changed_count": len(recent),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "unmatched": [
            {
                "path": str(p),
                "mtime": datetime.fromtimestamp(m, tz=timezone.utc).isoformat(),
                "audit_ts": (datetime.fromtimestamp(a, tz=timezone.utc).isoformat()
                             if a else None),
            }
            for p, m, a in unmatched
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="1h", help="time window (30s/2h/1d)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    since_seconds = parse_since(args.since)
    report = reconcile(since_seconds)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"[audit-reconcile] window: --since {args.since}")
        print(f"  audit entries: {report['audit_entries_count']}")
        print(f"  atoms changed: {report['atoms_changed_count']}")
        print(f"  matched: {report['matched_count']}")
        print(f"  unmatched: {report['unmatched_count']}")
        if report["unmatched"]:
            print("\n⚠ Atoms with no matching audit entry (suspect bypass):")
            for u in report["unmatched"]:
                print(f"  - {u['path']}")
                print(f"      mtime={u['mtime']}, audit_ts={u['audit_ts']}")

    return 1 if report["unmatched_count"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
