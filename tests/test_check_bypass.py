"""test_check_bypass.py — check-bypass.py 規則驗證 (S4.D.2)

5 cases：
  1. WHITELIST 直接匹配
  2. WHITELIST_DIR_PREFIXES 前綴匹配
  3. scan_file 抓到 write_text + memory hint
  4. scan_file 忽略 write_text 但無 memory hint
  5. scan_file 忽略 memory hint 但無 write 動作
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

CLAUDE_DIR = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "check_bypass", CLAUDE_DIR / "tools" / "check-bypass.py"
)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_whitelist_exact_match():
    assert MOD.is_whitelisted("lib/atom_io.py")
    assert MOD.is_whitelisted("lib/atom_io_cli.py")
    assert MOD.is_whitelisted("tools/check-bypass.py")
    assert not MOD.is_whitelisted("hooks/wg_intent.py")


def test_whitelist_dir_prefix():
    assert MOD.is_whitelisted("tests/test_anything.py")
    assert MOD.is_whitelisted("_archive/old.py")
    assert MOD.is_whitelisted("projects/_archive/x/foo.py")
    assert not MOD.is_whitelisted("hooks/wg_atoms.py")


def test_scan_file_detects_write_with_memory_hint(tmp_path: Path):
    f = tmp_path / "fake_hook.py"
    f.write_text(
        "from pathlib import Path\n"
        "MEMORY_DIR = Path('memory/')\n"
        "p = MEMORY_DIR / 'x.md'\n"
        "p.write_text('content')\n",
        encoding="utf-8",
    )
    findings = MOD.scan_file(f)
    assert len(findings) == 1
    assert ".write_text" in findings[0][1]


def test_scan_file_ignores_write_without_memory_hint(tmp_path: Path):
    f = tmp_path / "fake_hook.py"
    f.write_text(
        "from pathlib import Path\n"
        "Path('/tmp/log.txt').write_text('x')\n",
        encoding="utf-8",
    )
    assert MOD.scan_file(f) == []


def test_scan_file_ignores_memory_hint_without_write(tmp_path: Path):
    f = tmp_path / "fake_hook.py"
    f.write_text(
        "MEMORY_DIR = '/tmp/memory/'\n"
        "print(MEMORY_DIR)\n",
        encoding="utf-8",
    )
    assert MOD.scan_file(f) == []
