"""
sync-atom-index.py — Atom frontmatter Trigger ↔ _ATOM_INDEX.md 同步工具

設計依據：_AIDocs/DevHistory/atom-trigger-source-of-truth.md（選項 A）
- _ATOM_INDEX.md 為機器真相源（hook 唯一讀取點 wg_atoms.py:36）
- frontmatter Trigger 為註記，drift 時以 _ATOM_INDEX 為主對齊
- 配對 key 為 rel_path，避免 _ATOM_INDEX 短名 alias 與 atom 檔名不符的偽陽性

模式：
  (default)              dry-run，輸出 drift JSON 報告，drift 則 exit 1
  --fix                  以 _ATOM_INDEX 內容覆蓋 atom 檔 frontmatter Trigger
  --add-from-frontmatter 把 frontmatter 有 Trigger 但 _ATOM_INDEX 缺的 atom 補進索引
  --check                同 default，僅報 exit code（PreCommit 用，輸出最小化）

範圍判定（哪些檔算 atom）：
  - 路徑在 memory/ 下且為 .md
  - 有 frontmatter Trigger 欄位
  - 排除：_reference/, _archived/, _pending_review/, _staging/, templates/, wisdom/, _drafts/, episodic/
  - 排除：MEMORY.md, _ATOM_INDEX.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MEMORY_DIR = Path.home() / ".claude" / "memory"
ATOM_INDEX_NAME = "_ATOM_INDEX.md"

EXCLUDED_DIR_PARTS = {"_reference", "_archived", "_pending_review", "_staging",
                      "templates", "wisdom", "_drafts", "episodic"}
EXCLUDED_FILE_NAMES = {"MEMORY.md", "_ATOM_INDEX.md"}

TRIGGER_LINE_RE = re.compile(r"^- Trigger:\s*(.+)$", re.MULTILINE)
SCOPE_LINE_RE = re.compile(r"^- Scope:\s*(.+)$", re.MULTILINE)


@dataclass
class IndexRow:
    name: str
    path: str  # relative to ~/.claude
    triggers: List[str]
    scope: str = "global"


@dataclass
class AtomFile:
    name: str  # slug from filename
    path: Path  # absolute
    rel_path: str  # relative to ~/.claude (forward slash)
    triggers: List[str]
    scope: str


@dataclass
class DriftReport:
    missing_in_index: List[Dict] = field(default_factory=list)  # atom not pointed to by any index row
    missing_frontmatter: List[str] = field(default_factory=list)  # index row's file has no frontmatter Trigger
    trigger_drift: List[Dict] = field(default_factory=list)
    orphan_index: List[str] = field(default_factory=list)  # index row file doesn't exist
    scope_drift: List[Dict] = field(default_factory=list)

    def has_drift(self) -> bool:
        return any([self.missing_in_index, self.missing_frontmatter,
                    self.trigger_drift, self.orphan_index, self.scope_drift])

    def to_dict(self) -> Dict:
        return {
            "missing_in_index": self.missing_in_index,
            "missing_frontmatter": self.missing_frontmatter,
            "trigger_drift": self.trigger_drift,
            "orphan_index": self.orphan_index,
            "scope_drift": self.scope_drift,
            "has_drift": self.has_drift(),
        }


def is_excluded(p: Path, memory_dir: Path) -> bool:
    if p.name in EXCLUDED_FILE_NAMES:
        return True
    rel = p.relative_to(memory_dir)
    for part in rel.parts:
        if part in EXCLUDED_DIR_PARTS:
            return True
    return False


def parse_frontmatter_triggers(text: str) -> Optional[List[str]]:
    m = TRIGGER_LINE_RE.search(text)
    if not m:
        return None
    return [t.strip() for t in m.group(1).split(",") if t.strip()]


def parse_frontmatter_scope(text: str) -> str:
    m = SCOPE_LINE_RE.search(text)
    return m.group(1).strip() if m else "global"


def scan_atom_files(memory_dir: Path, claude_root: Path) -> Dict[str, AtomFile]:
    """Return dict keyed by rel_path (forward-slash)."""
    out: Dict[str, AtomFile] = {}
    for md in memory_dir.rglob("*.md"):
        if is_excluded(md, memory_dir):
            continue
        try:
            text = md.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        triggers = parse_frontmatter_triggers(text)
        if triggers is None:
            continue
        scope = parse_frontmatter_scope(text)
        slug = md.stem
        rel = str(md.relative_to(claude_root)).replace("\\", "/")
        out[rel] = AtomFile(name=slug, path=md, rel_path=rel,
                            triggers=triggers, scope=scope)
    return out


def parse_atom_index(index_path: Path) -> Tuple[List[IndexRow], List[str]]:
    rows: List[IndexRow] = []
    if not index_path.exists():
        return rows, []
    text = index_path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    in_table = False
    for line in lines:
        s = line.strip()
        if not in_table:
            if s.startswith("| Atom") or s.startswith("|Atom"):
                in_table = True
            continue
        if s.startswith("|---") or s.startswith("| ---"):
            continue
        if not s.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in s.split("|")]
        cells = [c for c in cells if c != ""]
        if len(cells) < 3:
            continue
        name = cells[0]
        path = cells[1].replace("\\", "/")
        triggers = [t.strip() for t in cells[2].split(",") if t.strip()]
        scope = cells[3] if len(cells) >= 4 else "global"
        rows.append(IndexRow(name=name, path=path, triggers=triggers, scope=scope))
    return rows, lines


def detect_drift(atoms_by_path: Dict[str, AtomFile],
                 index_rows: List[IndexRow],
                 claude_root: Path) -> DriftReport:
    rep = DriftReport()
    index_paths = {r.path for r in index_rows}

    # 1. atoms with frontmatter Trigger but path not referenced by any index row
    for rel_path, atom in atoms_by_path.items():
        if rel_path not in index_paths:
            rep.missing_in_index.append({
                "atom": atom.name,
                "path": rel_path,
                "triggers": atom.triggers,
                "scope": atom.scope,
            })

    # 2 & 3 & 5. iterate index rows
    for row in index_rows:
        target = (claude_root / row.path) if row.path else None
        if not target or not target.exists():
            rep.orphan_index.append(row.name)
            continue
        atom = atoms_by_path.get(row.path)
        if atom is None:
            # file exists but in excluded dir (e.g., wisdom/) or no frontmatter Trigger
            rep.missing_frontmatter.append(row.name)
            continue
        if atom.triggers != row.triggers:
            rep.trigger_drift.append({
                "atom": row.name,
                "path": row.path,
                "frontmatter": atom.triggers,
                "index": row.triggers,
                "frontmatter_extra": [t for t in atom.triggers if t not in row.triggers],
                "index_extra": [t for t in row.triggers if t not in atom.triggers],
            })
        if atom.scope != row.scope:
            rep.scope_drift.append({
                "atom": row.name,
                "frontmatter": atom.scope,
                "index": row.scope,
            })

    return rep


def fix_frontmatter_from_index(atoms_by_path: Dict[str, AtomFile],
                               index_rows: List[IndexRow]) -> List[str]:
    changed: List[str] = []
    for row in index_rows:
        atom = atoms_by_path.get(row.path)
        if atom is None:
            continue
        if atom.triggers == row.triggers:
            continue
        new_line = f"- Trigger: {', '.join(row.triggers)}"
        text = atom.path.read_text(encoding="utf-8-sig")
        new_text, n = TRIGGER_LINE_RE.subn(new_line, text, count=1)
        if n == 1 and new_text != text:
            atom.path.write_text(new_text, encoding="utf-8")
            changed.append(atom.rel_path)
    return changed


def add_to_index_from_frontmatter(atoms_by_path: Dict[str, AtomFile],
                                  index_rows: List[IndexRow],
                                  index_lines: List[str],
                                  index_path: Path) -> List[str]:
    indexed = {r.path for r in index_rows}
    to_add = [a for p, a in atoms_by_path.items() if p not in indexed]
    if not to_add:
        return []

    sep_idx = -1
    for i, line in enumerate(index_lines):
        if line.strip().startswith("|---"):
            sep_idx = i
            break
    if sep_idx < 0:
        return []

    last_row_idx = sep_idx
    for i in range(sep_idx + 1, len(index_lines)):
        s = index_lines[i].strip()
        if s.startswith("|"):
            last_row_idx = i
        elif s == "":
            continue
        else:
            break

    new_rows = []
    added: List[str] = []
    for atom in to_add:
        triggers_str = ", ".join(atom.triggers)
        new_rows.append(f"| {atom.name} | {atom.rel_path} | {triggers_str} | {atom.scope} |")
        added.append(atom.name)

    new_lines = index_lines[:last_row_idx + 1] + new_rows + index_lines[last_row_idx + 1:]
    out = "\n".join(new_lines)
    if not out.endswith("\n"):
        out += "\n"
    index_path.write_text(out, encoding="utf-8")
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--fix", action="store_true",
                        help="overwrite frontmatter Trigger from _ATOM_INDEX")
    parser.add_argument("--add-from-frontmatter", action="store_true",
                        help="append atoms with frontmatter Trigger but missing from _ATOM_INDEX")
    parser.add_argument("--check", action="store_true",
                        help="quiet drift check (exit 1 if drift, for PreCommit)")
    parser.add_argument("--memory-dir", type=Path, default=MEMORY_DIR)
    args = parser.parse_args()

    memory_dir: Path = args.memory_dir
    claude_root = memory_dir.parent
    index_path = memory_dir / ATOM_INDEX_NAME

    atoms_by_path = scan_atom_files(memory_dir, claude_root)
    index_rows, index_lines = parse_atom_index(index_path)

    actions_taken: List[str] = []

    if args.add_from_frontmatter:
        added = add_to_index_from_frontmatter(atoms_by_path, index_rows, index_lines, index_path)
        if added:
            actions_taken.append(f"added to _ATOM_INDEX: {added}")
            index_rows, index_lines = parse_atom_index(index_path)

    if args.fix:
        changed = fix_frontmatter_from_index(atoms_by_path, index_rows)
        if changed:
            actions_taken.append(f"frontmatter rewritten: {changed}")
            atoms_by_path = scan_atom_files(memory_dir, claude_root)

    rep = detect_drift(atoms_by_path, index_rows, claude_root)

    if args.check:
        if rep.has_drift():
            print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
        return 0

    print(json.dumps({"actions": actions_taken, "drift": rep.to_dict()},
                     ensure_ascii=False, indent=2))
    return 1 if rep.has_drift() else 0


if __name__ == "__main__":
    sys.exit(main())
