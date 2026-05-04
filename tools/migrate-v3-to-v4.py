#!/usr/bin/env python3
"""
migrate-v3-to-v4.py — 原子記憶 V3 → V4 metadata 遷移工具

SPEC_ATOM_V4.md §10 「遷移」：
- 只補 metadata（Scope / Author / Created-at）**不搬檔**。
- 漸進式分層：遷移完成後專案可用，後續可手動搬檔到 shared/roles/personal。
- 冪等：已有 Scope/Author/Created-at 的 atom 跳過。

掃描來源：
  1. ~/.claude/memory/ (global 層)
  2. 從 project-registry.json 取所有已知專案的 {proj}/.claude/memory/
  3. 專案內 shared/ / roles/{r}/ / personal/{u}/ 巢狀 atom 一併掃

用法：
  python migrate-v3-to-v4.py                    # 全掃 dry-run
  python migrate-v3-to-v4.py --apply            # 真的寫入
  python migrate-v3-to-v4.py --project PATH     # 限定單一專案（含 global）
  python migrate-v3-to-v4.py --global-only      # 只遷 ~/.claude/memory
  python migrate-v3-to-v4.py --author NAME      # 覆寫 Author 預設值（預設 unknown）
  python migrate-v3-to-v4.py --json             # JSON 輸出報告
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CLAUDE_DIR = Path.home() / ".claude"
GLOBAL_MEMORY = CLAUDE_DIR / "memory"
REGISTRY = GLOBAL_MEMORY / "project-registry.json"

# S3.1: route migration writes through atom_io funnel
if str(CLAUDE_DIR) not in sys.path:
    sys.path.insert(0, str(CLAUDE_DIR))
from lib.atom_io import write_raw  # noqa: E402

SKIP_FILES = {"MEMORY.md", "_ATOM_INDEX.md", "_CHANGELOG.md",
              "_CHANGELOG_ARCHIVE.md", "_roles.md"}
SKIP_PREFIXES = ("SPEC_",)

META_LINE_RE = re.compile(r"^-\s*([\w-]+)\s*:\s*(.*)$")


# ─── Layer Discovery ────────────────────────────────────────────────────────


def _load_registry() -> Dict[str, Any]:
    if REGISTRY.exists():
        try:
            return json.loads(REGISTRY.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"projects": {}}


def enumerate_memory_dirs(project_filter: Optional[Path],
                          global_only: bool) -> List[Tuple[str, Path]]:
    """Return [(scope_hint, mem_dir), ...]。
    scope_hint ∈ {"global", "project-root"} — scope_hint=project-root 時，
    atom 實際 scope 由子目錄（shared/roles/personal）或根層決定。
    """
    out: List[Tuple[str, Path]] = []
    if project_filter:
        pf = project_filter.resolve()
        if pf == GLOBAL_MEMORY.resolve() or pf == CLAUDE_DIR.resolve():
            out.append(("global", GLOBAL_MEMORY))
        else:
            mem = pf / ".claude" / "memory"
            if mem.is_dir():
                out.append(("project-root", mem))
            elif pf.is_dir() and (pf / "MEMORY.md").exists():
                out.append(("project-root", pf))
        return out

    if GLOBAL_MEMORY.is_dir():
        out.append(("global", GLOBAL_MEMORY))
    if global_only:
        return out

    reg = _load_registry()
    for slug, info in reg.get("projects", {}).items():
        root = Path(info.get("root", ""))
        if not root.is_dir():
            continue
        mem = root / ".claude" / "memory"
        if mem.is_dir():
            out.append(("project-root", mem))
    return out


def _is_atom_file(p: Path, base: Path) -> bool:
    if not (p.is_file() and p.suffix == ".md"):
        return False
    if p.name in SKIP_FILES:
        return False
    if p.name.startswith(SKIP_PREFIXES):
        return False
    if p.name.startswith("_"):
        return False
    rel = p.relative_to(base)
    for part in rel.parts[:-1]:
        if part.startswith("_"):
            return False
    return True


def _infer_scope_from_path(path: Path, mem_dir: Path, scope_hint: str) -> str:
    """Derive atom Scope from its path under mem_dir."""
    if scope_hint == "global":
        return "global"
    rel = path.relative_to(mem_dir).parts
    if len(rel) >= 2:
        top = rel[0]
        if top == "shared":
            return "shared"
        if top == "roles" and len(rel) >= 3:
            return f"role:{rel[1]}"
        if top == "personal" and len(rel) >= 3:
            return f"personal:{rel[1]}"
    return "shared"  # legacy flat 直下 atom 視為 shared（SPEC §10）


def discover_atoms(mem_dir: Path, scope_hint: str) -> List[Tuple[Path, str]]:
    out: List[Tuple[Path, str]] = []
    if not mem_dir.is_dir():
        return out
    for p in sorted(mem_dir.rglob("*.md")):
        if not _is_atom_file(p, mem_dir):
            continue
        scope = _infer_scope_from_path(p, mem_dir, scope_hint)
        out.append((p, scope))
    return out


# ─── Metadata Operations ────────────────────────────────────────────────────


def _first_added_date(path: Path) -> Optional[str]:
    """Return YYYY-MM-DD of file's first git commit, or None if no git / no history."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(path.parent), "log", "--follow",
             "--diff-filter=A", "--format=%ad", "--date=short",
             "--", path.name],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=10,
        )
        if proc.returncode != 0:
            return None
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        return lines[-1] if lines else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _mtime_date(path: Path) -> str:
    try:
        return date.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return date.today().isoformat()


def parse_metadata_block(lines: List[str]) -> Tuple[int, int, Dict[str, str]]:
    """Locate the metadata bullet block. Returns (start, end_exclusive, {key_lower: value}).

    Block starts at first `- Key:` line after title, ends when a blank line
    or non-metadata line appears. If none found, returns (-1, -1, {}).
    """
    keys: Dict[str, str] = {}
    start = -1
    end = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if start == -1:
            # look for first metadata bullet (after title). Skip title + blank lines.
            if stripped.startswith("# "):
                continue
            m = META_LINE_RE.match(stripped)
            if m:
                start = i
                keys[m.group(1).lower()] = m.group(2).strip()
                end = i + 1
            elif stripped == "":
                continue
            elif stripped.startswith("##"):
                break  # block body began w/o metadata
            else:
                continue
        else:
            m = META_LINE_RE.match(stripped)
            if m:
                keys[m.group(1).lower()] = m.group(2).strip()
                end = i + 1
            elif stripped == "":
                break  # end of block
            else:
                break
    return start, end, keys


def build_patch(path: Path, scope: str, author: str) -> Optional[Tuple[str, List[str]]]:
    """Return (new_text, added_fields) or None if nothing to add."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    lines = text.splitlines()
    start, end, existing = parse_metadata_block(lines)

    needed: Dict[str, str] = {}
    if "scope" not in existing:
        needed["Scope"] = scope
    if "author" not in existing:
        needed["Author"] = author
    if "created-at" not in existing:
        created = _first_added_date(path) or _mtime_date(path)
        needed["Created-at"] = created

    if not needed:
        return None

    if start == -1:
        # 沒有任何 metadata block — 建立在第一個空行後 / 標題後
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith("# "):
                insert_at = i + 1
                break
        if insert_at < len(lines) and lines[insert_at].strip() == "":
            insert_at += 1
        inserted = [f"- {k}: {v}" for k, v in needed.items()]
        new_lines = lines[:insert_at] + inserted + [""] + lines[insert_at:]
    else:
        # 插入到現有 block 末尾（保留原順序、最小 diff）
        # 放順序：Scope 在最前、Author 次、Created-at 最後
        priority = {"Scope": 0, "Author": 1, "Created-at": 2}
        extras = sorted(needed.items(), key=lambda kv: priority.get(kv[0], 99))
        inserted = [f"- {k}: {v}" for k, v in extras]
        new_lines = lines[:end] + inserted + lines[end:]

    new_text = "\n".join(new_lines)
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    return new_text, list(needed.keys())


# ─── Driver ─────────────────────────────────────────────────────────────────


def run(project_filter: Optional[Path], global_only: bool,
        author_default: str, apply: bool) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "apply": apply,
        "layers": [],
        "total_scanned": 0,
        "total_patched": 0,
        "total_skipped": 0,
    }

    for scope_hint, mem_dir in enumerate_memory_dirs(project_filter, global_only):
        layer_info: Dict[str, Any] = {
            "mem_dir": str(mem_dir),
            "scope_hint": scope_hint,
            "patched": [],
            "skipped": [],
        }
        atoms = discover_atoms(mem_dir, scope_hint)
        for path, scope in atoms:
            report["total_scanned"] += 1
            result = build_patch(path, scope, author_default)
            if not result:
                layer_info["skipped"].append({
                    "file": str(path.relative_to(mem_dir)),
                    "reason": "already has all V4 metadata",
                })
                report["total_skipped"] += 1
                continue
            new_text, added = result
            entry = {
                "file": str(path.relative_to(mem_dir)),
                "scope": scope,
                "added_fields": added,
            }
            if apply:
                # S3.1: 走 atom_io.write_raw funnel（migration patch 是修補既有
                # atom 而非建新，不適用 build_atom_content；走 raw escape hatch）
                res = write_raw(path, new_text, source="tool:migrate", op="migrate_patch")
                if res.ok:
                    entry["applied"] = True
                else:
                    entry["applied"] = False
                    entry["error"] = res.error
            else:
                entry["applied"] = False
            layer_info["patched"].append(entry)
            report["total_patched"] += 1
        report["layers"].append(layer_info)

    return report


def print_report(report: Dict[str, Any]) -> None:
    mode = "APPLY" if report["apply"] else "DRY-RUN"
    print(f"\n=== migrate-v3-to-v4 [{mode}] ===")
    print(f"scanned={report['total_scanned']}  "
          f"patched={report['total_patched']}  "
          f"skipped={report['total_skipped']}\n")
    for layer in report["layers"]:
        print(f"--- layer: {layer['mem_dir']}  ({layer['scope_hint']}) ---")
        patched = layer["patched"]
        if not patched:
            print(f"  [no patches needed — {len(layer['skipped'])} files already V4]")
            continue
        for e in patched:
            mark = "✓" if e.get("applied") else "∙"
            added = ", ".join(e["added_fields"])
            print(f"  {mark} {e['file']}  scope={e['scope']}  +[{added}]")
            if e.get("error"):
                print(f"      ERROR: {e['error']}")
        print()


def main() -> None:
    ap = argparse.ArgumentParser(description="Atom V3 → V4 metadata migration")
    ap.add_argument("--project", type=str, default=None,
                    help="限定單一專案根目錄（或 ~/.claude 處理 global）")
    ap.add_argument("--global-only", action="store_true",
                    help="只遷 ~/.claude/memory，不掃 registry 中的專案")
    ap.add_argument("--author", type=str, default="unknown",
                    help="無 Author 時補寫的預設值（預設 unknown）")
    ap.add_argument("--apply", action="store_true",
                    help="實際寫入（預設 dry-run）")
    ap.add_argument("--json", action="store_true",
                    help="輸出 JSON 報告而非文字")
    args = ap.parse_args()

    pf = Path(args.project).resolve() if args.project else None
    report = run(pf, args.global_only, args.author, args.apply)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)

    sys.exit(0)


if __name__ == "__main__":
    main()
