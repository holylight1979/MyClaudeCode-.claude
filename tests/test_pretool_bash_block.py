"""test_pretool_bash_block.py — PreToolUse SVN Test Block (2026-04-28)

對應 atom: memory/feedback/feedback-no-test-to-svn.md ([固] 規則程式碼化)
對應 hook: hooks/wg_pretool_guards.py:check_svn_test_block

阻擋 svn commit 含 test 路徑或 *Test.<ext> 檔（r10854 教訓）。
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest  # noqa: F401

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import importlib  # noqa: E402

wg = importlib.import_module("workflow-guardian")  # type: ignore[attr-defined]


def _run_pretool(tool_name: str, tool_input: dict) -> dict:
    payload = {"tool_name": tool_name, "tool_input": tool_input}
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            wg.handle_pre_tool_use(payload, {})
        except SystemExit:
            pass
    raw = buf.getvalue().strip()
    if not raw:
        return {}
    return json.loads(raw)


# ─── 命中（應 deny）─────────────────────────────────────────────────

def test_svn_commit_tests_dir_blocked():
    """svn commit -m 'add' tests/foo.cs → deny。"""
    out = _run_pretool("Bash", {"command": 'svn commit -m "add" tests/foo.cs'})
    deny = out.get("hookSpecificOutput", {})
    assert deny.get("permissionDecision") == "deny", out
    assert "SvnTestBlock" in deny.get("permissionDecisionReason", "")


def test_svn_ci_tests_blocked():
    """svn ci tests/ → deny（ci 是 commit 別名）。"""
    out = _run_pretool("Bash", {"command": "svn ci tests/"})
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out


def test_svn_commit_double_underscore_tests_blocked():
    """svn commit __tests__/x.spec.ts → deny。"""
    out = _run_pretool("Bash", {"command": "svn commit __tests__/x.spec.ts"})
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out


def test_svn_commit_test_singular_blocked():
    """svn commit test/ (單數) → deny。"""
    out = _run_pretool("Bash", {"command": "svn commit test/foo.cs"})
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out


def test_svn_commit_filename_test_suffix_blocked():
    """svn commit FooTest.cs → deny（後綴匹配）。"""
    out = _run_pretool("Bash", {"command": "svn commit src/FooTest.cs"})
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out


def test_svn_commit_test_suffix_python_blocked():
    """svn commit module/foo_Test.py → deny。"""
    out = _run_pretool("Bash", {"command": "svn commit module/fooTest.py"})
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out


# ─── 放行（應 allow）────────────────────────────────────────────────

def test_svn_commit_normal_src_allowed():
    """svn commit src/Foo.cs（無 test 路徑）→ allow。"""
    out = _run_pretool("Bash", {"command": "svn commit -m msg src/Foo.cs"})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "SvnTestBlock" not in reason, out


def test_svn_log_tests_allowed():
    """svn log tests/ → allow（不是 commit）。"""
    out = _run_pretool("Bash", {"command": "svn log tests/"})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "SvnTestBlock" not in reason, out


def test_svn_diff_tests_allowed():
    """svn diff tests/ → allow（不是 commit）。"""
    out = _run_pretool("Bash", {"command": "svn diff tests/foo.cs"})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "SvnTestBlock" not in reason, out


def test_git_commit_tests_allowed():
    """git commit tests/ → allow（git 不在規則內，走另條規則）。"""
    out = _run_pretool("Bash", {"command": "git commit tests/foo.py -m msg"})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "SvnTestBlock" not in reason, out


def test_svn_commit_manifest_xml_allowed():
    """svn commit Manifest.xml → allow（後綴限縮 *Test.<ext> 不誤殺 *fest.xml）。"""
    out = _run_pretool("Bash", {"command": "svn commit Manifest.xml"})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "SvnTestBlock" not in reason, out


def test_svn_commit_test_dot_unknown_ext_allowed():
    """svn commit foo/SomeTest.unknown → allow（副檔名不在白名單）。"""
    out = _run_pretool("Bash", {"command": "svn commit foo/SomeTest.unknown"})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "SvnTestBlock" not in reason, out


def test_write_tool_unaffected():
    """工具非 Bash → SvnTestBlock 不作用。"""
    out = _run_pretool("Write", {"file_path": "/tmp/x.txt", "content": "svn commit tests/"})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "SvnTestBlock" not in reason, out


def test_empty_bash_command_allowed():
    """空 command → allow。"""
    out = _run_pretool("Bash", {"command": ""})
    assert out == {}, out
