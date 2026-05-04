#!/usr/bin/env python3
"""audit-reconcile.py — 反向證明：列近期 mtime atom × 對拍 audit log

用途：funnel 收束後，反向確認「最近寫入的 atom 都有 audit log entry」。
若 atom mtime 比所有 audit entry 都新 → 可能繞過 funnel 寫入。

unmatched 分兩類：
  - counter_only: diff 只動 frontmatter 欄位 (Last-used / Confirmations / ReadHits / Related)
                  → 來源是 hook 注入時 ReadHits/Last-used bump（設計上輕量直寫，非 bypass）
  - knowledge:    diff 動到 ## 知識內容區或新增/刪除 atom
                  → 真實 funnel bypass，必須修

Exit: 0 = no knowledge bypass / 1 = knowledge bypass found

Usage:
    python audit-reconcile.py                   # 過去 1 hour
    python audit-reconcile.py --since 2h        # 過去 2 hours（也接 "2h ago"）
    python audit-reconcile.py --since 1d        # 過去 1 day
    python audit-reconcile.py --json            # JSON 輸出
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

# Windows: suppress flashing console windows when spawning git subprocesses.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW

CLAUDE_DIR = Path.home() / ".claude"
GLOBAL_MEM = CLAUDE_DIR / "memory"
AUDIT_LOG = GLOBAL_MEM / "_meta" / "atom_io_audit.jsonl"

if str(CLAUDE_DIR) not in sys.path:
    sys.path.insert(0, str(CLAUDE_DIR))
from lib.atom_spec import is_atom_file, iter_atom_files  # noqa: E402

# tolerance: audit log timestamp may lag mtime by up to N seconds (atomic write
# is mtime first then jsonl append; usually < 100ms but allow 5s safety margin).
TOLERANCE_SEC = 5

# Frontmatter fields that hook:read-counter (workflow-guardian.py:1325) bumps
# directly without funnel; their diffs are by-design and not real bypass.
COUNTER_FIELDS = ("Last-used", "Confirmations", "ReadHits", "Related")


def parse_since(s: str) -> int:
    # Accept "2h ago" by stripping trailing "ago" / whitespace.
    cleaned = re.sub(r"\s*ago\s*$", "", s.strip().lower())
    m = re.match(r"^(\d+)\s*([smhd])$", cleaned)
    if not m:
        raise ValueError(f"bad --since: {s!r} (use e.g. 30s / 2h / 1d / '2h ago')")
    val, unit = int(m.group(1)), m.group(2)
    return val * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def classify_diff(path: Path) -> str:
    """Return 'counter_only' / 'knowledge' / 'unknown' (no git or untracked).

    counter_only: diff 只動 frontmatter 欄位 (COUNTER_FIELDS)
    knowledge: diff 動到非 counter 欄位 / 知識內容區 / atom 新增刪除
    unknown: 不在 git 倉 / git 不可用 → 保守歸為 knowledge（避免遺漏）
    """
    try:
        # Find git root by walking up
        git_root = path.parent
        while git_root != git_root.parent:
            if (git_root / ".git").exists():
                break
            git_root = git_root.parent
        else:
            return "unknown"
        rel = path.relative_to(git_root)
        result = subprocess.run(
            ["git", "diff", "--no-color", "--", str(rel)],
            cwd=str(git_root),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, creationflags=_NO_WINDOW,
        )
        if result.returncode != 0:
            return "unknown"
        diff = result.stdout
        if not diff.strip():
            # No working-tree diff; might be staged or fresh write
            staged = subprocess.run(
                ["git", "diff", "--cached", "--no-color", "--", str(rel)],
                cwd=str(git_root),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=5, creationflags=_NO_WINDOW,
            )
            diff = staged.stdout
        if not diff.strip():
            # Untracked or no diff — treat as unknown (might be brand-new atom)
            return "unknown"
        # Pair +/- lines to detect promotion-only diffs (e.g. body [臨]→[觀])
        plus_lines, minus_lines = [], []
        for line in diff.splitlines():
            if not line:
                continue
            if line.startswith(("diff ", "index ", "--- ", "+++ ", "@@", "\\ No newline")):
                continue
            if line[0] not in "+-":
                continue
            content = line[1:]
            stripped = content.strip()
            if not stripped:
                # Pure whitespace / blank-line addition or removal — ignore
                continue
            # Frontmatter field line: "- Field: value"
            fm_match = re.match(r"^-\s*([A-Za-z][A-Za-z0-9_-]*?):", stripped)
            if fm_match and fm_match.group(1) in COUNTER_FIELDS:
                continue
            if line[0] == "+":
                plus_lines.append(stripped)
            else:
                minus_lines.append(stripped)
        # If +/- pair only differ by [臨]/[觀]/[固] tag — confidence promotion (hook auto-promote, not bypass)
        if len(plus_lines) == len(minus_lines) and plus_lines:
            tag_re = re.compile(r"\[(臨|觀|固)\]")
            all_tag_only = all(
                tag_re.sub("", p) == tag_re.sub("", m)
                for p, m in zip(plus_lines, minus_lines)
            )
            if all_tag_only:
                return "counter_only"
            return "knowledge"
        if not plus_lines and not minus_lines:
            return "counter_only"
        return "knowledge"
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return "unknown"


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
    matched, unmatched_counter, unmatched_knowledge, unmatched_unknown = [], [], [], []
    for p in recent:
        pl = str(p).lower()
        mtime = p.stat().st_mtime
        audit_ts = audit_paths.get(pl)
        if audit_ts is not None and audit_ts + TOLERANCE_SEC >= mtime:
            matched.append((p, mtime, audit_ts))
            continue
        cls = classify_diff(p)
        if cls == "counter_only":
            unmatched_counter.append((p, mtime, audit_ts))
        elif cls == "knowledge":
            unmatched_knowledge.append((p, mtime, audit_ts))
        else:
            unmatched_unknown.append((p, mtime, audit_ts))

    def _serialize(items):
        return [
            {
                "path": str(p),
                "mtime": datetime.fromtimestamp(m, tz=timezone.utc).isoformat(),
                "audit_ts": (datetime.fromtimestamp(a, tz=timezone.utc).isoformat()
                             if a else None),
            }
            for p, m, a in items
        ]

    return {
        "since_seconds": since_seconds,
        "since_iso": datetime.fromtimestamp(since_ts, tz=timezone.utc).isoformat(),
        "audit_entries_count": len(audit_paths),
        "atoms_changed_count": len(recent),
        "matched_count": len(matched),
        "unmatched_counter_count": len(unmatched_counter),
        "unmatched_knowledge_count": len(unmatched_knowledge),
        "unmatched_unknown_count": len(unmatched_unknown),
        "unmatched_counter": _serialize(unmatched_counter),
        "unmatched_knowledge": _serialize(unmatched_knowledge),
        "unmatched_unknown": _serialize(unmatched_unknown),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="1h", help="time window (30s/2h/1d, also accepts '2h ago')")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="treat unknown diffs as knowledge bypass (exit 1)")
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
        print(f"  unmatched (counter-only): {report['unmatched_counter_count']}  [hook:read-counter, OK]")
        print(f"  unmatched (knowledge):    {report['unmatched_knowledge_count']}  [REAL BYPASS]")
        print(f"  unmatched (unknown):      {report['unmatched_unknown_count']}  [no git / new file]")
        if report["unmatched_knowledge"]:
            print("\n⚠ KNOWLEDGE BYPASS — diff 動到非 counter 欄位 / 知識區：")
            for u in report["unmatched_knowledge"]:
                print(f"  - {u['path']}")
                print(f"      mtime={u['mtime']}, audit_ts={u['audit_ts']}")
        if report["unmatched_unknown"] and args.strict:
            print("\n⚠ UNKNOWN — 無法用 git 判定（--strict）：")
            for u in report["unmatched_unknown"]:
                print(f"  - {u['path']}")

    if report["unmatched_knowledge_count"] > 0:
        return 1
    if args.strict and report["unmatched_unknown_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
