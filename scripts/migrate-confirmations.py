#!/usr/bin/env python3
"""migrate_dual_field.py — Confirmations 雙欄位拆分 migration.

現有混合 Confirmations → ReadHits + Confirmations 歸零。

Usage:
    python scripts/migrate-confirmations.py memory/          # dry-run (default)
    python scripts/migrate-confirmations.py memory/ --execute
"""
import argparse
import json
import os
import re
import time
from pathlib import Path

SKIP_DIRS = {"_archived", "_pending_review", "_staging", "_vectordb"}
SKIP_FILES = {"MEMORY.md", "_ATOM_INDEX.md", "_CHANGELOG.md", "_CHANGELOG_ARCHIVE.md"}


def should_skip(file_path: Path) -> bool:
    for part in file_path.parts:
        if part in SKIP_DIRS:
            return True
    if file_path.name in SKIP_FILES or file_path.name.startswith("_"):
        return True
    return False


def migrate(memory_dir: Path, dry_run: bool = True):
    report = {"migrated": [], "skipped": [], "errors": []}
    migration_ts = time.time()

    for md_file in sorted(memory_dir.rglob("*.md")):
        if should_skip(md_file):
            report["skipped"].append(str(md_file.relative_to(memory_dir)))
            continue

        try:
            text = md_file.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            report["errors"].append({"file": str(md_file.relative_to(memory_dir)), "error": str(e)})
            continue

        cm = re.search(r"^- Confirmations:\s*(\d+)", text, re.MULTILINE)
        if not cm:
            report["skipped"].append(str(md_file.relative_to(memory_dir)))
            continue

        old_val = int(cm.group(1))

        # Already has ReadHits → idempotent, just check values
        rh = re.search(r"^- ReadHits:\s*(\d+)", text, re.MULTILINE)
        if rh:
            report["skipped"].append(str(md_file.relative_to(memory_dir)) + " (already has ReadHits)")
            continue

        # Rule: 現有混合值 → ReadHits, Confirmations 歸零
        new_text = re.sub(
            r"^(- Confirmations:\s*)\d+",
            r"\g<1>0",
            text, count=1, flags=re.MULTILINE,
        )

        # Insert ReadHits after Confirmations line
        new_text = re.sub(
            r"^(- Confirmations:\s*0)$",
            rf"\1\n- ReadHits: {old_val}",
            new_text, count=1, flags=re.MULTILINE,
        )

        record = {
            "file": str(md_file.relative_to(memory_dir)),
            "old_confirmations": old_val,
            "new_readhits": old_val,
            "new_confirmations": 0,
        }
        report["migrated"].append(record)

        if not dry_run:
            md_file.write_text(new_text, encoding="utf-8")

        # Migrate access.json: add empty confirmations array
        access_file = md_file.with_suffix(".access.json")
        if access_file.exists():
            try:
                adata = json.loads(access_file.read_text(encoding="utf-8"))
                if "confirmations" not in adata:
                    adata["confirmations"] = []
                    if not dry_run:
                        access_file.write_text(json.dumps(adata), encoding="utf-8")
            except (json.JSONDecodeError, OSError):
                pass

    # Write migration record
    if not dry_run:
        meta_dir = memory_dir / "_meta"
        meta_dir.mkdir(exist_ok=True)
        migration_record = {
            "version": "dual-field-v1",
            "timestamp": migration_ts,
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_migrated": len(report["migrated"]),
            "total_skipped": len(report["skipped"]),
            "total_errors": len(report["errors"]),
            "details": report["migrated"],
        }
        (meta_dir / "migration.json").write_text(
            json.dumps(migration_record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # Print report
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"{prefix}Migration complete:")
    print(f"  Migrated: {len(report['migrated'])}")
    print(f"  Skipped:  {len(report['skipped'])}")
    print(f"  Errors:   {len(report['errors'])}")
    for r in report["migrated"]:
        print(f"    {r['file']}: Confirmations {r['old_confirmations']} → ReadHits {r['new_readhits']}, Confirmations → 0")
    for e in report["errors"]:
        print(f"    ERROR {e['file']}: {e['error']}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Confirmations to dual-field (ReadHits + Confirmations)")
    parser.add_argument("memory_dir", type=Path, help="Path to memory directory")
    parser.add_argument("--execute", action="store_true", help="Actually write changes (default: dry-run)")
    args = parser.parse_args()
    migrate(args.memory_dir, dry_run=not args.execute)
