#!/usr/bin/env python3
"""check-bypass.py — 掃描 ~/.claude 內所有寫入 memory/ 的程式碼點 (S3.3)

目的：funnel 收束完成後，反向證明「沒有任何 caller 繞過 lib.atom_io」。
找出疑似直接 write_text/open(..., "w")/fs.writeFileSync 落在 memory/** 的程式碼。

白名單（合法繞過）：
  - lib/atom_io.py        — funnel 本身（_atomic_write）
  - lib/atom_io_cli.py    — CLI bridge
  - tests/                — 測試 fixture 可直寫
  - hooks/wg_paths.py     — 純路徑解析，不寫
  - tools/check-bypass.py — 本工具自己

非 0 違反 → exit code 1（CI 用）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"

WHITELIST = {
    "lib/atom_io.py",
    "lib/atom_io_cli.py",
    "tools/check-bypass.py",
    # 非 atom 的 audit log / metadata / 測試腳本：
    "hooks/wg_core.py",            # _promotion_audit.jsonl append（非 atom）
    "tools/snapshot-v4-atoms.py",  # 寫到 tests/fixtures/，非 atom
    "tools/test-memory-v21.py",    # 測試腳本本身（位置在 tools/ 而非 tests/）
    # tests/ 全部白名單（測試會直寫 fixture）
}
WHITELIST_DIR_PREFIXES = ("tests/", "_archive/", "projects/_archive/")
SCAN_EXTS = (".py", ".js")
SKIP_DIRS = {".git", "node_modules", "_archive", "__pycache__",
             "_vectordb", "_staging"}

# 偵測寫檔指令（保守：含 memory/ 或 \.claude/memory/ 的同行/前後幾行才算疑似）
WRITE_PATTERNS = [
    re.compile(r"\.write_text\s*\("),
    re.compile(r"\bopen\s*\([^)]*['\"]\s*[wax]"),  # open(..., "w"/"a"/"x")
    re.compile(r"fs\.writeFileSync\s*\("),
    re.compile(r"fs\.appendFileSync\s*\("),
]
# 路徑提示（含這些字樣才視為「寫到 memory」）
MEMORY_HINTS = [
    re.compile(r"memory[/\\]"),
    re.compile(r"MEMORY_DIR\b"),
    re.compile(r"MEMORY[A-Z_]*PATH\b"),
    re.compile(r"GLOBAL_MEMORY"),
    re.compile(r"\.claude[/\\]memory"),
    re.compile(r"failures_dir|episodic_dir|atom_path"),
]


def is_whitelisted(rel_path: str) -> bool:
    if rel_path in WHITELIST:
        return True
    if any(rel_path.startswith(p) for p in WHITELIST_DIR_PREFIXES):
        return True
    return False


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return list of (line_no, line, why) suspected bypasses."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    findings = []
    for i, line in enumerate(lines, 1):
        if not any(p.search(line) for p in WRITE_PATTERNS):
            continue
        # 找 ±5 行內是否提到 memory 路徑線索
        ctx_start = max(0, i - 6)
        ctx_end = min(len(lines), i + 5)
        ctx = "\n".join(lines[ctx_start:ctx_end])
        if not any(h.search(ctx) for h in MEMORY_HINTS):
            continue
        findings.append((i, line.strip()[:120], "write+memory hint"))
    return findings


def main() -> int:
    violations = 0
    print(f"[check-bypass] scanning {CLAUDE_DIR}/{{hooks,tools,lib,plugins}}/...\n")
    for sub in ("hooks", "tools", "lib", "plugins"):
        root = CLAUDE_DIR / sub
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SCAN_EXTS:
                continue
            try:
                rel = path.relative_to(CLAUDE_DIR).as_posix()
            except ValueError:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if is_whitelisted(rel):
                continue
            findings = scan_file(path)
            if findings:
                violations += len(findings)
                print(f"⚠ {rel}:")
                for n, l, why in findings:
                    print(f"    L{n}: {l}")
                    print(f"           ↑ {why}")
                print()
    if violations:
        print(f"\n[check-bypass] {violations} suspected bypass(es).")
        print("If false positive (e.g. writes to _meta/ logs, hot_cache.json,")
        print("or non-atom data files), add path to WHITELIST or refactor caller.")
        return 1
    print("[check-bypass] 0 violations. Funnel收束完整 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
