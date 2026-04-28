#!/usr/bin/env python3
"""Atom Health Check — 原子記憶依賴健康度檢查工具

Usage:
  python atom-health-check.py --validate-refs   檢查 Related 完整性
  python atom-health-check.py --fix-refs        自動修復缺失的反向參照
  python atom-health-check.py --stale-check     列出 Last-used > 60 天的 atoms
  python atom-health-check.py --report          生成完整健康報告
  python atom-health-check.py --report --json   JSON 格式輸出
"""

import sys, io
# Force UTF-8 stdout on Windows (cp950 codepage causes mojibake in JSON output)
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import argparse
import json
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

MEMORY_ROOT = Path.home() / ".claude" / "memory"
GLOBAL_MEMORY_ROOT = Path.home() / ".claude" / "memory"
AIDOCS_ROOT = Path.home() / ".claude" / "_AIDocs"
EXTRA_SCAN_ROOTS: list[Path] = []  # populated from CLI; searched as fallback for ref resolution
SKIP_FILES = {"MEMORY.md", "SPEC_Atomic_Memory_System.md", "_ATOM_INDEX.md"}
SKIP_DIRS = {"_distant", "_staging", "_vectordb", "episodic", "_reference", "templates"}
# Central hub atoms — skip reverse-link warnings for these
# (hub docs don't back-reference every detail doc that points to them)
# - decisions / decisions-architecture / spec：全域決策與規範 hub
# - feedback-pointer-atom：指標型 atom 設計原則 meta-rule，被多個 atoms 引用作為設計依據
CENTRAL_HUBS = {"decisions", "decisions-architecture", "spec", "feedback-pointer-atom"}

# Shadow detection: atom 段落抄 _AIDocs md 子段落 → warning
SHADOW_THRESHOLD_DEFAULT = 0.7
SHADOW_SECTIONS = ("印象", "知識")
SHADOW_MIN_LEN = 80  # 太短的段落比對結果不可信 (e.g. "(none)" 或單句)
NOISE_LINE_PATTERNS = [
    re.compile(r'^\s*[-*]?\s*.*?→\s*_AIDocs/[^\s]+\.md.*$'),  # pointer 行
    re.compile(r'^\s*@_AIDocs/.*$'),                           # @import 行
    re.compile(r'^\s*_AIDocs/[^\s]+\.md\s*$'),                 # 純路徑行
    re.compile(r'^\s*>\s*$'),                                  # 空 blockquote
]


def parse_memory_index(root: Path) -> dict[str, str]:
    """Parse MEMORY.md to build alias→stem mapping (e.g. spec→SPEC_Atomic_Memory_System)."""
    index_path = root / "MEMORY.md"
    aliases = {}
    if not index_path.exists():
        return aliases
    text = index_path.read_text(encoding="utf-8")
    # Match table rows: | alias | path | ...
    for m in re.finditer(r"\|\s*(\S+)\s*\|\s*([\w/.-]+\.md)\s*\|", text):
        alias = m.group(1).strip()
        filepath = m.group(2).strip()
        stem = Path(filepath).stem
        if alias != stem:
            aliases[alias] = stem
    return aliases


def find_atoms(root: Path) -> dict[str, Path]:
    """Recursively find all .md atom files, return {name: path}."""
    atoms = {}
    for md in root.rglob("*.md"):
        if md.name in SKIP_FILES:
            continue
        # Skip underscore-prefixed files (_ATOM_INDEX, _reference docs, etc.)
        if md.name.startswith("_"):
            continue
        if any(part in SKIP_DIRS for part in md.relative_to(root).parts):
            continue
        name = md.stem
        atoms[name] = md
    return atoms


def parse_frontmatter(path: Path) -> dict:
    """Parse atom frontmatter fields into a dict."""
    text = path.read_text(encoding="utf-8")
    fm = {}

    # Detect Claude-native frontmatter (--- delimited YAML)
    yaml_match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if yaml_match:
        for line in yaml_match.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
        fm["_format"] = "claude-native"
        return fm

    # Detect atom-style frontmatter (- Key: Value lines at top)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^-\s+(.+?):\s+(.+)$", line)
        if m:
            fm[m.group(1)] = m.group(2)
        elif line.startswith("##"):
            break
    fm["_format"] = "atom"
    return fm


def parse_related(fm: dict) -> list[str]:
    """Extract Related atom names from frontmatter (handles both 'Related' and 'related')."""
    raw = fm.get("Related", "") or fm.get("related", "")
    if not raw or raw.strip() == "(none)":
        return []
    names = [n.strip().removesuffix(".md") for n in raw.split(",")]
    return [n for n in names if n]


def resolve_ref(ref: str, atoms: dict[str, Path], aliases: dict[str, str]) -> str | None:
    """Resolve a Related reference to an atom name. Returns atom name or None."""
    if ref in atoms:
        return ref
    # Check if ref is a MEMORY.md alias
    if ref in aliases:
        stem = aliases[ref]
        if stem in atoms:
            return stem
        # Alias target might be in SKIP_FILES but still valid on disk
        for md in MEMORY_ROOT.rglob(f"{stem}.md"):
            return stem
    # Check reverse alias (stem mentioned but alias is canonical)
    for alias, stem in aliases.items():
        if ref == stem and alias in atoms:
            return alias
    # Last resort: check if file exists on disk (covers SKIP_FILES entries)
    for md in MEMORY_ROOT.rglob(f"{ref}.md"):
        return ref
    # Cross-layer: fall back to extra roots (project → global up-ref is valid)
    for extra in EXTRA_SCAN_ROOTS:
        for md in extra.rglob(f"{ref}.md"):
            return ref
    return None


def validate_refs(atoms: dict[str, Path], aliases: dict[str, str] | None = None) -> list[dict]:
    """Check that all Related references point to existing atoms."""
    aliases = aliases or {}
    issues = []
    for name, path in sorted(atoms.items()):
        fm = parse_frontmatter(path)
        related = parse_related(fm)
        for ref in related:
            if resolve_ref(ref, atoms, aliases) is None:
                issues.append({
                    "atom": name,
                    "missing_ref": ref,
                    "file": str(path),
                })
    return issues


def auto_fix_broken_refs(broken: list[dict]) -> list[dict]:
    """Remove broken refs from their source atom's Related field.

    Returns list of applied fixes. A broken ref means the target doesn't exist
    in MEMORY_ROOT nor any EXTRA_SCAN_ROOTS, so removal is safe.
    """
    fixes = []
    for b in broken:
        path = Path(b["file"])
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        m = re.search(r"^- Related:\s*(.+)$", text, re.MULTILINE)
        if not m:
            continue
        items = [i.strip() for i in m.group(1).split(",") if i.strip()]
        missing = b["missing_ref"]
        new_items = [i for i in items if i != missing]
        if len(new_items) == len(items):
            continue
        new_line = f"- Related: {', '.join(new_items) if new_items else '(none)'}"
        path.write_text(text.replace(m.group(0), new_line, 1), encoding="utf-8")
        fixes.append({"atom": b["atom"], "removed_ref": missing, "file": str(path)})
    return fixes


def check_reverse_refs(atoms: dict[str, Path], aliases: dict[str, str] | None = None) -> list[dict]:
    """Check bidirectional Related consistency."""
    aliases = aliases or {}
    # Build adjacency with resolved names
    adj: dict[str, list[str]] = {}
    for name, path in atoms.items():
        fm = parse_frontmatter(path)
        raw_refs = parse_related(fm)
        resolved = []
        for ref in raw_refs:
            r = resolve_ref(ref, atoms, aliases)
            resolved.append(r if r else ref)
        adj[name] = resolved

    issues = []
    for name, refs in adj.items():
        for ref in refs:
            if ref in CENTRAL_HUBS:
                continue
            # Also check aliases of ref in CENTRAL_HUBS
            if ref in aliases and aliases[ref] in CENTRAL_HUBS:
                continue
            if ref in adj and name not in adj[ref]:
                # Check if name is reachable via alias
                name_aliases = [a for a, s in aliases.items() if s == name]
                if not any(a in adj.get(ref, []) for a in name_aliases):
                    issues.append({
                        "atom_a": name,
                        "atom_b": ref,
                        "direction": f"{name} → {ref} exists, but {ref} → {name} missing",
                    })
    return issues


def fix_reverse_refs(atoms: dict[str, Path], aliases: dict[str, str] | None = None) -> list[dict]:
    """Auto-fix missing reverse references. Returns list of fixes applied."""
    aliases = aliases or {}
    issues = check_reverse_refs(atoms, aliases)
    if not issues:
        return []

    fixes = []
    for issue in issues:
        atom_a = issue["atom_a"]  # A → B exists
        atom_b = issue["atom_b"]  # B → A missing, need to add A to B's Related

        if atom_b not in atoms:
            continue

        path_b = atoms[atom_b]
        text = path_b.read_text(encoding="utf-8")
        fm = parse_frontmatter(path_b)
        fmt = fm.get("_format", "atom")

        # Determine canonical name to add (use alias if B references A via alias)
        add_name = atom_a
        # Check if atom_a has an alias that atom_b might prefer
        for alias, stem in aliases.items():
            if stem == atom_a:
                add_name = alias
                break

        # Re-read file (may have been modified by earlier fix in this loop)
        text = path_b.read_text(encoding="utf-8")
        fm = parse_frontmatter(path_b)
        fmt = fm.get("_format", "atom")

        # Dedup check: skip if back-ref already present in current file
        existing_refs = parse_related(fm)
        existing_resolved = {r for ref in existing_refs for r in [resolve_ref(ref, atoms, aliases) or ref]}
        if atom_a in existing_resolved or add_name in existing_refs:
            continue

        if fmt == "claude-native":
            # YAML frontmatter: add or append 'related:' field
            existing_related = fm.get("related", "")
            if existing_related:
                new_related = f"{existing_related}, {add_name}"
                text = text.replace(f"related: {existing_related}", f"related: {new_related}", 1)
            else:
                # Insert before closing ---
                text = re.sub(r"\n---", f"\nrelated: {add_name}\n---", text, count=1)
        else:
            # Atom-style: add or append '- Related:' field
            related_match = re.search(r"^- Related:\s*(.+)$", text, re.MULTILINE)
            if related_match:
                old_line = related_match.group(0)
                new_line = f"{old_line}, {add_name}"
                text = text.replace(old_line, new_line, 1)
            else:
                # Insert Related line before first ## section
                section_match = re.search(r"^## ", text, re.MULTILINE)
                if section_match:
                    insert_pos = section_match.start()
                    text = text[:insert_pos] + f"- Related: {add_name}\n\n" + text[insert_pos:]
                else:
                    text += f"\n- Related: {add_name}\n"

        path_b.write_text(text, encoding="utf-8")
        fixes.append({
            "target": atom_b,
            "added_ref": add_name,
            "file": str(path_b),
        })

    return fixes


def stale_check(atoms: dict[str, Path], days: int = 60) -> list[dict]:
    """Find atoms with Last-used older than threshold."""
    cutoff = datetime.now() - timedelta(days=days)
    stale = []
    for name, path in sorted(atoms.items()):
        fm = parse_frontmatter(path)
        last_used = fm.get("Last-used", "")
        if not last_used:
            continue
        try:
            dt = datetime.strptime(last_used.strip(), "%Y-%m-%d")
            if dt < cutoff:
                age = (datetime.now() - dt).days
                stale.append({
                    "atom": name,
                    "last_used": last_used.strip(),
                    "days_ago": age,
                    "file": str(path),
                })
        except ValueError:
            pass
    return stale


def full_report(atoms: dict[str, Path], aliases: dict[str, str] | None = None) -> dict:
    """Generate complete health report."""
    aliases = aliases or {}
    report = {
        "generated": datetime.now().isoformat(),
        "total_atoms": len(atoms),
        "aliases": aliases,
        "atoms": [],
        "broken_refs": validate_refs(atoms, aliases),
        "missing_reverse_refs": check_reverse_refs(atoms, aliases),
        "stale_atoms": stale_check(atoms),
    }

    for name, path in sorted(atoms.items()):
        fm = parse_frontmatter(path)
        related = parse_related(fm)
        entry = {
            "name": name,
            "file": str(path.relative_to(MEMORY_ROOT)),
            "format": fm.get("_format", "unknown"),
            "confidence": fm.get("Confidence", "—"),
            "last_used": fm.get("Last-used", "—"),
            "confirmations": fm.get("Confirmations", "—"),
            "readhits": fm.get("ReadHits", "—"),
            "related": related,
            "issues": [],
        }

        # Check for missing standard fields
        if fm.get("_format") == "atom":
            if not fm.get("Last-used"):
                entry["issues"].append("missing Last-used")
            if not fm.get("Confirmations"):
                entry["issues"].append("missing Confirmations")
            if not fm.get("ReadHits"):
                entry["issues"].append("missing ReadHits")
            if not fm.get("Trigger"):
                entry["issues"].append("missing Trigger")
        elif fm.get("_format") == "claude-native":
            entry["issues"].append("claude-native format (no Last-used/Confirmations/Related)")

        report["atoms"].append(entry)

    return report


def print_text_report(report: dict):
    """Pretty-print the report."""
    print(f"=== Atom Health Report ({report['generated'][:10]}) ===")
    print(f"Total atoms: {report['total_atoms']}\n")

    # Per-atom status
    print("── Atom Status ──")
    for a in report["atoms"]:
        status = "✅" if not a["issues"] else "⚠️"
        related_str = ", ".join(a["related"]) if a["related"] else "(none)"
        print(f"  {status} {a['name']}")
        print(f"     File: {a['file']} | Confidence: {a['confidence']}")
        print(f"     Last-used: {a['last_used']} | Confirmations: {a['confirmations']} | ReadHits: {a['readhits']}")
        print(f"     Related: {related_str}")
        if a["issues"]:
            print(f"     Issues: {', '.join(a['issues'])}")
        print()

    # Broken refs
    if report["broken_refs"]:
        print("── Broken References ──")
        for b in report["broken_refs"]:
            print(f"  ❌ {b['atom']} → {b['missing_ref']} (not found)")
        print()
    else:
        print("── Broken References: None ✅ ──\n")

    # Reverse refs
    if report["missing_reverse_refs"]:
        print("── Missing Reverse References ──")
        for r in report["missing_reverse_refs"]:
            print(f"  ⚠️ {r['direction']}")
        print()
    else:
        print("── Reverse References: All OK ✅ ──\n")

    # Stale
    if report["stale_atoms"]:
        print("── Stale Atoms (>60 days) ──")
        for s in report["stale_atoms"]:
            print(f"  🕐 {s['atom']} — last used {s['last_used']} ({s['days_ago']}d ago)")
        print()
    else:
        print("── Stale Atoms: None ✅ ──\n")

    # Summary
    issues_count = (
        len(report["broken_refs"])
        + len(report["missing_reverse_refs"])
        + len(report["stale_atoms"])
        + sum(1 for a in report["atoms"] if a["issues"])
    )
    if issues_count == 0:
        print("🎉 All atoms healthy!")
    else:
        print(f"⚠️ {issues_count} issue(s) found.")


def main():
    parser = argparse.ArgumentParser(description="Atom Health Check")
    parser.add_argument("--validate-refs", action="store_true", help="Check Related references exist")
    parser.add_argument("--fix-refs", action="store_true", help="Auto-fix missing reverse references")
    parser.add_argument("--auto-fix-broken", action="store_true", help="Auto-remove broken Related refs from source atoms (unresolvable targets)")
    parser.add_argument("--stale-check", action="store_true", help="List atoms with Last-used > 60 days")
    parser.add_argument("--stale-days", type=int, default=60, help="Stale threshold in days (default: 60)")
    parser.add_argument("--report", action="store_true", help="Full health report")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--memory-root", type=str, default=None, help="Override memory root path")
    args = parser.parse_args()

    global MEMORY_ROOT, EXTRA_SCAN_ROOTS
    if args.memory_root:
        MEMORY_ROOT = Path(args.memory_root)

    if not MEMORY_ROOT.exists():
        print(f"Error: {MEMORY_ROOT} does not exist", file=sys.stderr)
        sys.exit(1)

    # Auto-enable cross-layer ref resolution when scanning a non-global root:
    # project-layer atoms may legitimately reference global atoms (up-ref).
    # Does NOT affect down-ref detection (global→project refs still flagged when
    # scanning global, since MEMORY_ROOT will be global and project not in extras).
    try:
        if MEMORY_ROOT.resolve() != GLOBAL_MEMORY_ROOT.resolve():
            if GLOBAL_MEMORY_ROOT.is_dir():
                EXTRA_SCAN_ROOTS = [GLOBAL_MEMORY_ROOT]
    except OSError:
        pass

    atoms = find_atoms(MEMORY_ROOT)
    aliases = parse_memory_index(MEMORY_ROOT)

    if not any([args.validate_refs, args.fix_refs, args.auto_fix_broken, args.stale_check, args.report]):
        parser.print_help()
        sys.exit(0)

    if args.fix_refs:
        fixes = fix_reverse_refs(atoms, aliases)
        if args.json:
            print(json.dumps({"fixes": fixes, "count": len(fixes)}, indent=2, ensure_ascii=False))
        elif fixes:
            for f in fixes:
                print(f"✅ {f['target']} ← added back-ref to {f['added_ref']}")
            print(f"\nFixed {len(fixes)} missing reverse reference(s).")
        else:
            print("✅ No missing reverse references to fix.")
        sys.exit(0)

    if args.auto_fix_broken:
        broken = validate_refs(atoms, aliases)
        fixes = auto_fix_broken_refs(broken)
        if args.json:
            print(json.dumps({"fixes": fixes, "count": len(fixes)}, indent=2, ensure_ascii=False))
        elif fixes:
            for f in fixes:
                print(f"✅ {f['atom']} — removed broken ref: {f['removed_ref']}")
            print(f"\nRemoved {len(fixes)} broken reference(s).")
        else:
            print("✅ No broken references to fix.")
        sys.exit(0)

    if args.validate_refs:
        broken = validate_refs(atoms, aliases)
        reverse = check_reverse_refs(atoms, aliases)
        if args.json:
            print(json.dumps({"broken_refs": broken, "missing_reverse_refs": reverse}, indent=2, ensure_ascii=False))
        else:
            if broken:
                for b in broken:
                    print(f"❌ {b['atom']} → {b['missing_ref']} (not found)")
            else:
                print("✅ All Related references valid.")
            if reverse:
                print()
                for r in reverse:
                    print(f"⚠️ {r['direction']}")
            else:
                print("✅ All reverse references OK.")

    elif args.stale_check:
        stale = stale_check(atoms, args.stale_days)
        if args.json:
            print(json.dumps(stale, indent=2, ensure_ascii=False))
        elif stale:
            for s in stale:
                print(f"🕐 {s['atom']} — {s['last_used']} ({s['days_ago']}d ago)")
        else:
            print(f"✅ No atoms older than {args.stale_days} days.")

    elif args.report:
        report = full_report(atoms, aliases)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print_text_report(report)


if __name__ == "__main__":
    main()
