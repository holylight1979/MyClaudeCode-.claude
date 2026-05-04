"""test_audit_reconcile.py — audit-reconcile.py classifier 與 parser 驗證 (S4.D.2)

7 cases：
  parser:
    1. parse_since 接 30s/2h/1d
    2. parse_since 接 "2h ago" 容錯
    3. parse_since 拒絕 bad input
  classifier (classify_diff)：
    4. counter_only：只動 Last-used / Confirmations / ReadHits / Related
    5. counter_only：[臨]→[觀] 信心 tag promotion（content body 也變但只是 tag）
    6. knowledge：動到知識內容（新增 bullet 或文字改寫）
    7. unknown：non-git 路徑
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

CLAUDE_DIR = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "audit_reconcile", CLAUDE_DIR / "tools" / "audit-reconcile.py"
)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_parse_since_basic_units():
    assert MOD.parse_since("30s") == 30
    assert MOD.parse_since("2h") == 7200
    assert MOD.parse_since("1d") == 86400


def test_parse_since_ago_suffix():
    assert MOD.parse_since("2h ago") == 7200
    assert MOD.parse_since("30m ago") == 1800


def test_parse_since_rejects_bad():
    with pytest.raises(ValueError):
        MOD.parse_since("abc")
    with pytest.raises(ValueError):
        MOD.parse_since("2x")


def _init_git_with_atom(tmp_path: Path, content: str) -> Path:
    """Init a git repo with one atom file at HEAD."""
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(tmp_path), check=True)
    f = tmp_path / "atom.md"
    f.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "atom.md"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(tmp_path), check=True)
    return f


BASE_ATOM = (
    "# Test\n\n"
    "- Scope: global\n"
    "- Confidence: [臨]\n"
    "- Trigger: x, y\n"
    "- Last-used: 2026-04-01\n"
    "- Confirmations: 0\n"
    "- ReadHits: 5\n\n"
    "## 知識\n\n"
    "- [臨] body line\n"
)


def test_classify_diff_counter_only(tmp_path: Path):
    f = _init_git_with_atom(tmp_path, BASE_ATOM)
    bumped = BASE_ATOM.replace("Last-used: 2026-04-01", "Last-used: 2026-05-04")
    bumped = bumped.replace("ReadHits: 5", "ReadHits: 7")
    f.write_text(bumped, encoding="utf-8")
    assert MOD.classify_diff(f) == "counter_only"


def test_classify_diff_promotion_only(tmp_path: Path):
    f = _init_git_with_atom(tmp_path, BASE_ATOM)
    promoted = BASE_ATOM.replace("Confidence: [臨]", "Confidence: [觀]")
    promoted = promoted.replace("[臨] body line", "[觀] body line")
    f.write_text(promoted, encoding="utf-8")
    # Confidence is not in COUNTER_FIELDS but body diff is tag-only → counter_only
    # Note: Confidence frontmatter line is not in COUNTER_FIELDS, but the +/- lines
    # for it differ only by [臨]/[觀] tag, so all_tag_only catches it.
    assert MOD.classify_diff(f) == "counter_only"


def test_classify_diff_knowledge_change(tmp_path: Path):
    f = _init_git_with_atom(tmp_path, BASE_ATOM)
    changed = BASE_ATOM + "- [臨] new bullet added by bypass\n"
    f.write_text(changed, encoding="utf-8")
    assert MOD.classify_diff(f) == "knowledge"


def test_classify_diff_unknown_for_non_git(tmp_path: Path):
    # No git init → should fall back to "unknown"
    f = tmp_path / "atom.md"
    f.write_text(BASE_ATOM, encoding="utf-8")
    assert MOD.classify_diff(f) == "unknown"
