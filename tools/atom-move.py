#!/usr/bin/env python3
"""atom-move.py — 原子搬遷工具（含 inbound refs / _ATOM_INDEX / Scope 同步）

子命令：
  move      — 從 source root 搬到 target root，完整同步
  reconcile — atom 已在 target（例如被手動 mv），掃其他層清除 stale 狀態

層序規則：
  global (最高) > project (子層)
  - up-ref  (project → global): 合法保留
  - down-ref (global  → project): 違規移除
  - sibling  (projectA → projectB): 警告回報，不自動處理
"""

import argparse
import json
import re
import sys
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
GLOBAL_MEMORY = CLAUDE_DIR / "memory"
REGISTRY_PATH = GLOBAL_MEMORY / "project-registry.json"
ATOM_INDEX = "_ATOM_INDEX.md"
MEMORY_INDEX = "MEMORY.md"
SKIP_NAMES = {ATOM_INDEX, MEMORY_INDEX}

# S3.1: route atom-move writes through atom_io funnel
if str(CLAUDE_DIR) not in sys.path:
    sys.path.insert(0, str(CLAUDE_DIR))
from lib.atom_io import write_raw, write_index_full  # noqa: E402

_ATOM_MOVE_SOURCE = "tool:atom-move"


def find_atom_file(root: Path, slug: str):
    if not root.is_dir():
        return None
    for p in root.rglob(f"{slug}.md"):
        return p
    return None


def parse_frontmatter(path: Path):
    text = path.read_text(encoding="utf-8")
    fm = {}
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            for line in text[4:end].splitlines():
                m = re.match(r"([A-Za-z_-]+):\s*(.*)", line)
                if m:
                    fm[m.group(1)] = m.group(2).strip()
            return fm
    for line in text.splitlines():
        m = re.match(r"^- ([A-Za-z_-]+):\s*(.*)", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
        elif line.startswith("## "):
            break
    return fm


def get_related(fm):
    raw = fm.get("Related", "") or fm.get("related", "")
    if not raw or raw.strip() in ("(none)", "—", ""):
        return []
    return [r.strip() for r in raw.split(",") if r.strip()]


def iter_atoms(root: Path):
    if not root.is_dir():
        return
    for p in root.rglob("*.md"):
        if p.name in SKIP_NAMES or p.name.startswith("_"):
            continue
        yield p


def is_global(root: Path) -> bool:
    try:
        return root.resolve() == GLOBAL_MEMORY.resolve()
    except OSError:
        return False


def layer_label(root: Path) -> str:
    if is_global(root):
        return "global"
    return f"project({root.parent.parent.name})"


def discover_project_roots():
    roots = set()
    if REGISTRY_PATH.exists():
        try:
            reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            for _, info in reg.get("projects", {}).items():
                pr = Path(info.get("root", ""))
                if pr.is_dir():
                    new_mem = pr / ".claude" / "memory"
                    if new_mem.is_dir():
                        roots.add(new_mem.resolve())
        except (json.JSONDecodeError, OSError):
            pass
    legacy = CLAUDE_DIR / "projects"
    if legacy.is_dir():
        for pd in legacy.iterdir():
            mem = pd / "memory"
            if mem.is_dir():
                try:
                    roots.add(mem.resolve())
                except OSError:
                    pass
    return [Path(r) for r in roots]


def remove_atom_index_row(root: Path, slug: str):
    idx = root / ATOM_INDEX
    if not idx.exists():
        return False
    lines = idx.read_text(encoding="utf-8").splitlines(keepends=True)
    new = [l for l in lines if not re.match(rf"^\|\s*{re.escape(slug)}\s*\|", l)]
    if len(new) != len(lines):
        # S3.1: 走 atom_io.write_index_full funnel
        write_index_full(idx, "".join(new), source=_ATOM_MOVE_SOURCE)
        return True
    return False


def add_atom_index_row(root: Path, slug: str, trigger: str, scope: str):
    idx = root / ATOM_INDEX
    if not idx.exists():
        # S3.1: 首次建檔走 funnel
        write_index_full(
            idx,
            "# Atom Trigger Index\n\n"
            "> Machine-parsed by workflow-guardian hooks. Not @imported into context.\n\n"
            "| Atom | Path | Trigger | Scope |\n"
            "|------|------|---------|-------|\n",
            source=_ATOM_MOVE_SOURCE,
        )
    text = idx.read_text(encoding="utf-8")
    if re.search(rf"^\|\s*{re.escape(slug)}\s*\|", text, re.MULTILINE):
        return False
    atom_path = find_atom_file(root, slug)
    if not atom_path:
        return False
    rel = atom_path.relative_to(root).as_posix()
    # Global convention uses 'memory/' prefix
    display_path = f"memory/{rel}" if is_global(root) else rel
    row = f"| {slug} | {display_path} | {trigger} | {scope} |\n"
    if not text.endswith("\n"):
        text += "\n"
    text += row
    write_index_full(idx, text, source=_ATOM_MOVE_SOURCE)
    return True


def remove_memory_index_row(root: Path, slug: str):
    mem_idx = root / MEMORY_INDEX
    if not mem_idx.exists():
        return False
    text = mem_idx.read_text(encoding="utf-8")
    pattern = re.compile(rf"^\|\s*{re.escape(slug)}\s*\|.*$\n?", re.MULTILINE)
    new, n = pattern.subn("", text)
    if n:
        write_index_full(mem_idx, new, source=_ATOM_MOVE_SOURCE)
        return True
    return False


def remove_inbound_ref(atom_path: Path, slug: str):
    text = atom_path.read_text(encoding="utf-8")
    m = re.search(r"^- Related:\s*(.+)$", text, re.MULTILINE)
    if not m:
        return False
    items = [i.strip() for i in m.group(1).split(",") if i.strip()]
    new_items = [i for i in items if i != slug]
    if len(new_items) == len(items):
        return False
    new_line = f"- Related: {', '.join(new_items) if new_items else '(none)'}"
    text = text.replace(m.group(0), new_line, 1)
    write_raw(atom_path, text, source=_ATOM_MOVE_SOURCE, op="atom_move_related")
    return True


def update_scope_field(atom_path: Path, new_scope: str):
    text = atom_path.read_text(encoding="utf-8")
    m = re.search(r"^- Scope:\s*(.+)$", text, re.MULTILINE)
    if m and m.group(1).strip() == new_scope:
        return None
    if m:
        old = m.group(1).strip()
        text = text.replace(m.group(0), f"- Scope: {new_scope}", 1)
        write_raw(atom_path, text, source=_ATOM_MOVE_SOURCE, op="atom_move_scope")
        return f"{old} → {new_scope}"
    # No Scope field — insert after title
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if ln.startswith("# "):
            lines.insert(i + 2, f"- Scope: {new_scope}\n")
            write_raw(atom_path, "".join(lines), source=_ATOM_MOVE_SOURCE, op="atom_move_scope_insert")
            return f"(none) → {new_scope}"
    return None


def reconcile(slug: str, target_root: Path, extra_roots, dry_run=False):
    report = {
        "target": str(target_root),
        "scope_updated": None,
        "target_index_added": False,
        "stale_index_removed": [],
        "stale_memory_removed": [],
        "inbound_refs_removed": [],
        "inbound_refs_kept": [],
        "warnings": [],
    }

    atom_path = find_atom_file(target_root, slug)
    if not atom_path:
        print(f"ERROR atom '{slug}' not found under {target_root}", file=sys.stderr)
        sys.exit(1)

    fm = parse_frontmatter(atom_path)
    trigger = fm.get("Trigger", "").strip()
    target_scope = "global" if is_global(target_root) else "project"

    # Scope normalize
    if not dry_run:
        sc = update_scope_field(atom_path, target_scope)
        if sc:
            report["scope_updated"] = sc

    # Collect scan roots
    all_roots = {GLOBAL_MEMORY.resolve()}
    for r in discover_project_roots():
        all_roots.add(r.resolve())
    for r in extra_roots:
        try:
            all_roots.add(Path(r).resolve())
        except OSError:
            pass
    try:
        target_resolved = target_root.resolve()
    except OSError:
        target_resolved = target_root
    other_roots = [Path(r) for r in all_roots if r != target_resolved]

    target_is_global = is_global(target_root)

    for r in other_roots:
        if not r.is_dir():
            continue
        # Remove stale _ATOM_INDEX row
        idx_path = r / ATOM_INDEX
        if idx_path.exists():
            if dry_run:
                text = idx_path.read_text(encoding="utf-8")
                if re.search(rf"^\|\s*{re.escape(slug)}\s*\|", text, re.MULTILINE):
                    report["stale_index_removed"].append(str(idx_path))
            else:
                if remove_atom_index_row(r, slug):
                    report["stale_index_removed"].append(str(idx_path))

        # Remove stale MEMORY.md row (table style)
        if dry_run:
            mp = r / MEMORY_INDEX
            if mp.exists():
                if re.search(rf"^\|\s*{re.escape(slug)}\s*\|", mp.read_text(encoding="utf-8"), re.MULTILINE):
                    report["stale_memory_removed"].append(str(mp))
        else:
            if remove_memory_index_row(r, slug):
                report["stale_memory_removed"].append(str(r / MEMORY_INDEX))

        # Inbound ref handling per layering rule
        r_is_global = is_global(r)
        for hit in iter_atoms(r):
            fm_hit = parse_frontmatter(hit)
            if slug not in get_related(fm_hit):
                continue
            tag = f"{hit.relative_to(r) if r in hit.parents else hit.name}"
            if r_is_global and not target_is_global:
                # Down-ref: forbidden, remove
                if dry_run:
                    report["inbound_refs_removed"].append(f"{hit}  [down-ref]")
                else:
                    if remove_inbound_ref(hit, slug):
                        report["inbound_refs_removed"].append(f"{hit}  [down-ref removed]")
            elif not r_is_global and target_is_global:
                # Up-ref: keep
                report["inbound_refs_kept"].append(f"{hit}  [up-ref kept]")
            elif not r_is_global and not target_is_global:
                # Sibling cross-project: warn
                report["warnings"].append(f"sibling ref {hit} → {slug} (both project-layer; manual review)")
            else:
                # global→global: same layer, always kept
                report["inbound_refs_kept"].append(f"{hit}  [same-layer]")

    # Ensure target has _ATOM_INDEX entry
    if not dry_run:
        if add_atom_index_row(target_root, slug, trigger, target_scope):
            report["target_index_added"] = True
    else:
        idx = target_root / ATOM_INDEX
        text = idx.read_text(encoding="utf-8") if idx.exists() else ""
        if not re.search(rf"^\|\s*{re.escape(slug)}\s*\|", text, re.MULTILINE):
            report["target_index_added"] = True

    return report


def cmd_move(args):
    src = Path(args.src)
    target = Path(args.to)
    slug = args.atom
    src_file = find_atom_file(src, slug)
    if not src_file:
        print(f"ERROR atom '{slug}' not found in {src}", file=sys.stderr)
        sys.exit(1)
    target.mkdir(parents=True, exist_ok=True)
    dst_file = target / src_file.name
    if dst_file.exists():
        print(f"ERROR target already exists: {dst_file}", file=sys.stderr)
        sys.exit(1)
    if not args.dry_run:
        src_file.rename(dst_file)
    else:
        print(f"[dry-run] would move {src_file} → {dst_file}")
    report = reconcile(slug, target, extra_roots=[src], dry_run=args.dry_run)
    _print_report(slug, report, args.dry_run)


def cmd_reconcile(args):
    target = Path(args.at)
    report = reconcile(args.atom, target, extra_roots=[], dry_run=args.dry_run)
    _print_report(args.atom, report, args.dry_run)


def _print_report(slug, report, dry_run):
    mode = "DRY-RUN" if dry_run else "APPLIED"
    print(f"\n=== Reconcile '{slug}' ({mode}) → {report['target']} ===")
    if report["scope_updated"]:
        print(f"  Scope: {report['scope_updated']}")
    if report["target_index_added"]:
        print(f"  [target] _ATOM_INDEX row added")
    for path in report["stale_index_removed"]:
        print(f"  [stale] _ATOM_INDEX row removed: {path}")
    for path in report["stale_memory_removed"]:
        print(f"  [stale] MEMORY.md row removed: {path}")
    for ln in report["inbound_refs_removed"]:
        print(f"  [down-ref] {ln}")
    for ln in report["inbound_refs_kept"]:
        print(f"  [keep]     {ln}")
    for w in report["warnings"]:
        print(f"  WARN {w}")
    if not any((
        report["scope_updated"], report["target_index_added"],
        report["stale_index_removed"], report["stale_memory_removed"],
        report["inbound_refs_removed"], report["inbound_refs_kept"],
        report["warnings"],
    )):
        print("  (already consistent)")


def main():
    p = argparse.ArgumentParser(description="Atomic atom move across memory layers")
    sub = p.add_subparsers(dest="cmd", required=True)

    mv = sub.add_parser("move", help="Move atom from --from to --to and sync all state")
    mv.add_argument("atom")
    mv.add_argument("--from", dest="src", required=True)
    mv.add_argument("--to", required=True)
    mv.add_argument("--dry-run", action="store_true")
    mv.set_defaults(func=cmd_move)

    rc = sub.add_parser("reconcile", help="Sync stale refs/indexes for atom already at --at")
    rc.add_argument("atom")
    rc.add_argument("--at", required=True)
    rc.add_argument("--dry-run", action="store_true")
    rc.set_defaults(func=cmd_reconcile)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
