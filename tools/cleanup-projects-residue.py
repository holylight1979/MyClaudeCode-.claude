#!/usr/bin/env python3
"""cleanup-projects-residue.py — 清理 ~/.claude/projects/{slug}/memory/ 殘骸 (S1.1.2)

V2.21 之後，專案層 memory 統一住在 {project_root}/.claude/memory/，
~/.claude/projects/{slug}/memory/ 變成 migration stub 或空殼，會污染：
  - audit 跨層 duplicate 偵測
  - 雙層 .claude (P1 漏洞觸發點)
  - vector indexer 的 layer enumeration

策略：歸檔（mv 到 _archive/），不刪除，可隨時 mv 回。

Usage:
    python cleanup-projects-residue.py              # dry-run，只列計畫
    python cleanup-projects-residue.py --apply      # 實際歸檔
    python cleanup-projects-residue.py --restore    # 從最近一次歸檔還原（緊急用）
"""

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
ARCHIVE_ROOT = PROJECTS_DIR / "_archive" / "projects-residue"


def _claude_dir_slug() -> str:
    """~/.claude 自身投影成 project slug 的形式（P1 雙層殘骸鑑別用）。"""
    raw = str(CLAUDE_DIR).replace(":", "-").replace("\\", "-").replace("/", "-").replace(".", "-")
    return raw.lower()


def is_migration_stub(slug: str, mem_dir: Path) -> tuple[bool, str]:
    """判斷 memory dir 是否為可歸檔的殘骸。

    回傳 (is_stub, reason)。判定為殘骸的條件（任一成立）：
      - slug 是 ~/.claude 自身（雙層 .claude P1 bug 殘骸 — 內含的 atoms 全部
        是當 cwd=~/.claude 誤觸發 episodic/extract 寫進去的副本）
      - 含 "migrated-v2.21" / "Project Pointer" 標記（V2.21 migration stub）
      - 子目錄無 atom（含遞迴掃描，但排除 MEMORY.md / `_*` 系統檔）
    """
    if slug == _claude_dir_slug():
        atoms = [
            f for f in mem_dir.rglob("*.md")
            if f.name != "MEMORY.md" and not f.name.startswith("_")
        ]
        return True, f"P1 雙層 .claude 殘骸 ({len(atoms)} 個 bug 副本)"

    index = mem_dir / "MEMORY.md"
    if not index.exists():
        return True, "no MEMORY.md (orphan)"

    try:
        text = index.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False, "MEMORY.md unreadable"

    if "migrated-v2.21" in text or "Project Pointer" in text:
        return True, "migration stub (migrated-v2.21)"

    atoms = [
        f for f in mem_dir.rglob("*.md")
        if f.name != "MEMORY.md" and not f.name.startswith("_")
    ]
    if not atoms:
        return True, "no atom files"

    return False, f"active layer ({len(atoms)} atoms)"


def discover_residue() -> list[tuple[str, Path, str]]:
    """掃描 ~/.claude/projects/*/memory/，回傳殘骸清單 [(slug, mem_dir, reason)]。"""
    residue: list[tuple[str, Path, str]] = []
    if not PROJECTS_DIR.is_dir():
        return residue

    for slug_dir in sorted(PROJECTS_DIR.iterdir()):
        if not slug_dir.is_dir() or slug_dir.name.startswith("_"):
            continue
        mem_dir = slug_dir / "memory"
        if not mem_dir.is_dir():
            continue
        is_stub, reason = is_migration_stub(slug_dir.name, mem_dir)
        if is_stub:
            residue.append((slug_dir.name, mem_dir, reason))
    return residue


def archive_one(slug: str, mem_dir: Path, archive_dir: Path) -> tuple[bool, str]:
    """mv mem_dir → archive_dir/{slug}/memory/。"""
    target = archive_dir / slug / "memory"
    if target.exists():
        return False, f"target exists: {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(mem_dir), str(target))
        return True, f"{slug} → {target.relative_to(CLAUDE_DIR)}"
    except OSError as e:
        return False, f"{slug}: {e}"


def restore_latest(archive_root: Path) -> int:
    """還原最近一次歸檔。"""
    if not archive_root.is_dir():
        print("no archive to restore", file=sys.stderr)
        return 1
    snapshots = sorted([d for d in archive_root.iterdir() if d.is_dir()])
    if not snapshots:
        print("no archive snapshots", file=sys.stderr)
        return 1
    latest = snapshots[-1]
    restored = 0
    for slug_dir in latest.iterdir():
        mem = slug_dir / "memory"
        if not mem.is_dir():
            continue
        target = PROJECTS_DIR / slug_dir.name / "memory"
        if target.exists():
            print(f"SKIP {slug_dir.name}: target exists")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(mem), str(target))
        print(f"RESTORED {slug_dir.name}")
        restored += 1
    print(f"\nRestored {restored} layer(s) from {latest.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="實際歸檔（預設 dry-run）")
    parser.add_argument("--restore", action="store_true", help="從最近一次歸檔還原")
    args = parser.parse_args()

    if args.restore:
        return restore_latest(ARCHIVE_ROOT)

    residue = discover_residue()
    if not residue:
        print("無殘骸 layer 需清理 ✅")
        return 0

    today = date.today().isoformat()
    archive_dir = ARCHIVE_ROOT / today

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] {len(residue)} 個殘骸 layer 將歸檔到 {archive_dir.relative_to(CLAUDE_DIR)}/\n")
    for slug, mem_dir, reason in residue:
        print(f"  - {slug}/memory  [{reason}]")

    if not args.apply:
        print("\n（未實際執行；加 --apply 才會 mv）")
        return 0

    print()
    failures = 0
    for slug, mem_dir, _reason in residue:
        ok, msg = archive_one(slug, mem_dir, archive_dir)
        print(f"{'OK  ' if ok else 'FAIL'}: {msg}")
        if not ok:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
