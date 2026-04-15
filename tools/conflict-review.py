#!/usr/bin/env python3
"""
conflict-review.py — V4 Phase 5 backend for /conflict-review.

列 _pending_review/ 草稿與報告；依 is_management() 雙向認證核可 approve/reject。
所有動作寫 _merge_history.log，approve 後觸發 vector reindex。

JSON over stdout；非零 exit code 代表操作失敗（不是 missing pending）。
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HOOKS_DIR = Path.home() / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))
from wg_paths import find_project_root  # noqa: E402
from wg_roles import is_management, get_current_user  # noqa: E402


# ─── Helpers ────────────────────────────────────────────────────────────────

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proj_mem(proj_cwd: str) -> Optional[Path]:
    root = find_project_root(proj_cwd)
    if not root:
        return None
    mem = root / ".claude" / "memory"
    if not mem.is_dir():
        return None
    return mem


def _pending_dir(mem: Path) -> Path:
    return mem / "shared" / "_pending_review"


def _shared_dir(mem: Path) -> Path:
    return mem / "shared"


def _append_merge_history(mem: Path, action: str, atom: str, scope: str,
                          by: str, detail: str) -> None:
    log_path = mem / "_merge_history.log"
    safe = lambda s: str(s or "-").replace("\t", " ").replace("\n", " ").strip() or "-"
    line = "\t".join([_utcnow_iso(), safe(action), safe(atom), safe(scope),
                      safe(by), safe(detail)]) + "\n"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        print(f"[conflict-review] merge_history write failed: {e}", file=sys.stderr)


def _trigger_reindex() -> bool:
    try:
        req = urllib.request.Request("http://127.0.0.1:3849/index/incremental", method="POST")
        with urllib.request.urlopen(req, timeout=5) as _:
            return True
    except Exception:
        return False


def _preview_text(path: Path, max_len: int = 120) -> str:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""
    m = re.search(r"##\s*知識\s*\n+(.+?)(?=\n##\s|\Z)", text, re.DOTALL)
    body = (m.group(1) if m else text).strip()
    body = re.sub(r"\s+", " ", body)
    return body[:max_len]


def _parse_metadata(path: Path) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return meta
    for line in text.splitlines():
        m = re.match(r"^-\s*([\w-]+):\s*(.+)\s*$", line)
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
    return meta


# ─── Classify pending file kind ─────────────────────────────────────────────

def _classify_file(name: str) -> str:
    if name.endswith(".pull-conflict.md"):
        return "pull-conflict"
    if name.endswith(".conflict.md"):
        return "conflict"
    if name.endswith(".resolved.md"):
        return "resolved"
    if name.endswith(".md"):
        return "draft"
    return "unknown"


def _target_stem(name: str) -> str:
    """Strip .md / .conflict.md / .pull-conflict.md / .resolved.md suffix."""
    for suf in (".pull-conflict.md", ".conflict.md", ".resolved.md", ".md"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


# ─── list action ────────────────────────────────────────────────────────────

def action_list(proj_cwd: str) -> Dict[str, Any]:
    mem = _proj_mem(proj_cwd)
    if not mem:
        return {"error": "no V4 project memory at cwd", "cwd": proj_cwd}

    pdir = _pending_dir(mem)
    if not pdir.is_dir():
        return {"pending": [], "total": 0, "project_root": str(mem.parent.parent)}

    items: List[Dict[str, Any]] = []
    for p in sorted(pdir.glob("*.md")):
        kind = _classify_file(p.name)
        if kind == "unknown":
            continue
        stem = _target_stem(p.name)
        meta = _parse_metadata(p)
        items.append({
            "kind": kind,
            "target": stem,
            "file": p.name,
            "path": str(p),
            "author": meta.get("author") or meta.get("incoming-author", ""),
            "detected_at": meta.get("detected-at", ""),
            "pending_review_by": meta.get("pending-review-by", ""),
            "preview": _preview_text(p),
        })
    return {"pending": items, "total": len(items),
            "project_root": str(mem.parent.parent)}


# ─── approve ────────────────────────────────────────────────────────────────

def _strip_pending_marker(text: str, user: str) -> str:
    """Remove `- Pending-review-by:` line, append `- Decided-by:` + bump Last-used.

    Idempotent: if Decided-by already present, replace it.
    """
    today = date.today().isoformat()
    # Remove Pending-review-by line(s)
    text = re.sub(r"^-\s*Pending-review-by:.*\n", "", text, flags=re.MULTILINE)
    # Update Last-used
    if re.search(r"^-\s*Last-used:", text, flags=re.MULTILINE):
        text = re.sub(r"^-\s*Last-used:.*$", f"- Last-used: {today}",
                      text, count=1, flags=re.MULTILINE)
    # Decided-by
    if re.search(r"^-\s*Decided-by:", text, flags=re.MULTILINE):
        text = re.sub(r"^-\s*Decided-by:.*$", f"- Decided-by: {user}",
                      text, count=1, flags=re.MULTILINE)
    else:
        # Insert after Confirmations line if present, else after first metadata block
        if re.search(r"^-\s*Confirmations:", text, flags=re.MULTILINE):
            text = re.sub(r"^(-\s*Confirmations:.*)$",
                          r"\1\n- Decided-by: " + user,
                          text, count=1, flags=re.MULTILINE)
        else:
            # Fallback: add before first blank line after title
            lines = text.splitlines(keepends=True)
            for i, ln in enumerate(lines):
                if ln.strip() == "" and i > 0:
                    lines.insert(i, f"- Decided-by: {user}\n")
                    break
            text = "".join(lines)
    return text


def action_approve(proj_cwd: str, target: str, user: str) -> Dict[str, Any]:
    mem = _proj_mem(proj_cwd)
    if not mem:
        return {"error": "no V4 project memory at cwd"}

    if not is_management(proj_cwd, user):
        return {"error": "not authorized as management",
                "hint": "check personal role.md + shared _roles.md Management 白名單"}

    pdir = _pending_dir(mem)
    sdir = _shared_dir(mem)

    # Allow target with or without suffix
    candidates = [
        pdir / f"{target}.md",
        pdir / f"{target}.resolved.md",
        pdir / target,  # full filename with suffix
    ]
    src: Optional[Path] = next((c for c in candidates if c.is_file()), None)
    if not src:
        return {"error": f"pending target not found: {target}",
                "searched": [str(c) for c in candidates]}

    kind = _classify_file(src.name)
    if kind == "conflict" or kind == "pull-conflict":
        return {"error": "cannot approve a raw conflict report",
                "hint": "先編輯並另存為 {name}.resolved.md，再 approve {name}.resolved"}

    try:
        text = src.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        return {"error": f"read failed: {e}"}

    patched = _strip_pending_marker(text, user)

    # Destination filename: always the stripped stem
    stem = _target_stem(src.name)
    dest = sdir / f"{stem}.md"
    if dest.exists():
        return {"error": f"shared target already exists: {dest.name}",
                "hint": "先處理既有 atom（rename / merge / replace）再 approve"}

    sdir.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".md.tmp")
    tmp.write_text(patched, encoding="utf-8")
    tmp.replace(dest)

    # Remove companion .conflict.md if exists (approval implies conflict was resolved)
    conflict_file = pdir / f"{stem}.conflict.md"
    extras_removed = []
    if conflict_file.is_file():
        try:
            conflict_file.unlink()
            extras_removed.append(conflict_file.name)
        except OSError:
            pass

    try:
        src.unlink()
    except OSError as e:
        return {"error": f"approve wrote {dest} but failed to remove pending src: {e}"}

    _append_merge_history(mem, "approve", stem, "shared", user,
                          f"from={src.name} to=shared/{dest.name}")
    reindexed = _trigger_reindex()

    return {
        "ok": True,
        "target": stem,
        "dest": str(dest),
        "extras_removed": extras_removed,
        "reindex_triggered": reindexed,
        "decided_by": user,
    }


# ─── reject ─────────────────────────────────────────────────────────────────

def action_reject(proj_cwd: str, target: str, user: str, reason: str) -> Dict[str, Any]:
    mem = _proj_mem(proj_cwd)
    if not mem:
        return {"error": "no V4 project memory at cwd"}

    if not is_management(proj_cwd, user):
        return {"error": "not authorized as management"}

    pdir = _pending_dir(mem)
    candidates = [
        pdir / f"{target}.md",
        pdir / f"{target}.conflict.md",
        pdir / f"{target}.pull-conflict.md",
        pdir / f"{target}.resolved.md",
        pdir / target,
    ]
    removed: List[str] = []
    for c in candidates:
        if c.is_file():
            try:
                c.unlink()
                removed.append(c.name)
            except OSError:
                pass

    if not removed:
        return {"error": f"pending target not found: {target}"}

    stem = _target_stem(removed[0])
    _append_merge_history(mem, "reject", stem, "shared", user,
                          f"files={','.join(removed)} reason={reason or '-'}")

    return {"ok": True, "target": stem, "removed": removed, "reason": reason}


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="V4 Phase 5 pending-review backend")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--action", choices=["approve", "reject"])
    ap.add_argument("--target", type=str)
    ap.add_argument("--by", type=str, default=None,
                    help="user doing the action; defaults to CLAUDE_USER/os login")
    ap.add_argument("--project-cwd", type=str, required=True)
    ap.add_argument("--reason", type=str, default="")
    args = ap.parse_args()

    proj_cwd = args.project_cwd
    user = args.by or get_current_user()

    if args.list:
        print(json.dumps(action_list(proj_cwd), ensure_ascii=False, indent=2))
        return

    if args.action == "approve":
        if not args.target:
            print(json.dumps({"error": "--target required"}))
            sys.exit(2)
        result = action_approve(proj_cwd, args.target, user)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("ok") else 1)

    if args.action == "reject":
        if not args.target:
            print(json.dumps({"error": "--target required"}))
            sys.exit(2)
        result = action_reject(proj_cwd, args.target, user, args.reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("ok") else 1)

    print(json.dumps({"error": "no action specified (use --list or --action=approve/reject)"}))
    sys.exit(2)


if __name__ == "__main__":
    main()
