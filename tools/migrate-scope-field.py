#!/usr/bin/env python3
"""migrate-scope-field.py — 把缺 Scope: 的 atom 補上由路徑推斷的 Scope (S2.1 P5)

路徑推斷規則：
- ~/.claude/memory/...                       → global
- {project}/.claude/memory/shared/...        → shared
- {project}/.claude/memory/roles/<role>/...  → role
（personal/ 在 atom_spec.SKIP_DIRS，iter_atom_files 不會掃到，無需處理）

插入位置：第一個 `- Confidence: ` 之前（SPEC §4 metadata 順序：Scope 必為第一行）。
預設 dry-run；--apply 才實際寫檔。
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.atom_spec import iter_atom_files, parse_frontmatter  # noqa: E402

DEFAULT_MEMORY_ROOT = Path.home() / ".claude" / "memory"

_META_LINE_RE = re.compile(r"^- [\w-]+:")


def infer_scope(atom_path: Path, memory_root: Path) -> str:
    try:
        rel = atom_path.relative_to(memory_root)
    except ValueError:
        return ""
    parts = rel.parts
    if parts and parts[0] == "shared":
        return "shared"
    if len(parts) >= 2 and parts[0] == "roles":
        return "role"
    if len(parts) >= 2 and parts[0] == "personal":
        return "personal"
    return "global"


def build_migrated(text: str, scope: str) -> str:
    """Insert `- Scope: <scope>` before first `- Key: ` line. Returns new content or ''.

    Preserves original line endings (LF / CRLF) — must read with newline='' to keep them intact.
    """
    sep = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if _META_LINE_RE.match(ln):
            return "".join(lines[:i] + [f"- Scope: {scope}{sep}"] + lines[i:])
    return ""  # structural anomaly — skip


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate missing Scope: field on atoms.")
    ap.add_argument("--apply", action="store_true", help="實際寫檔（預設 dry-run）")
    ap.add_argument(
        "--memory-root",
        type=Path,
        default=DEFAULT_MEMORY_ROOT,
        help="memory root（預設 ~/.claude/memory）",
    )
    args = ap.parse_args()

    root = args.memory_root.resolve()
    if not root.is_dir():
        print(f"ERROR: memory root not found: {root}", file=sys.stderr)
        return 1

    missing: list[tuple[Path, str]] = []
    migrated: list[Path] = []

    for atom in iter_atom_files(root):
        # bytes I/O to preserve original line endings (Windows write_text injects CRLF)
        text = atom.read_bytes().decode("utf-8")
        fm = parse_frontmatter(text)
        if "Scope" in fm:
            continue
        scope = infer_scope(atom, root)
        if not scope:
            print(f"WARN: cannot infer scope for {atom}", file=sys.stderr)
            continue
        missing.append((atom, scope))
        new_content = build_migrated(text, scope)
        if not new_content:
            print(f"WARN: no metadata block in {atom}, skipped", file=sys.stderr)
            continue
        rel = atom.relative_to(root)
        if args.apply:
            atom.write_bytes(new_content.encode("utf-8"))
            migrated.append(atom)
            print(f"[apply]   {rel}  ← Scope: {scope}")
        else:
            print(f"[dry-run] {rel}  ← Scope: {scope}")

    print()
    print(f"Total atoms missing Scope: {len(missing)}")
    if args.apply:
        print(f"Migrated: {len(migrated)}")
    else:
        print("(dry-run; 加 --apply 寫入)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
