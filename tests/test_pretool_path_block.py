"""test_pretool_path_block.py — PreToolUse Memory Path Block (2026-04-28)

對應 atom: memory/feedback/feedback-memory-path.md ([固] 規則程式碼化)
對應 hook: hooks/wg_pretool_guards.py:check_memory_path_block

阻擋寫入 ~/.claude/projects/{slug}/memory/（原子記憶專案自治層覆寫此路徑）。
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

def test_write_to_projects_slug_memory_blocked():
    """寫入 ~/.claude/projects/{slug}/memory/ → deny。"""
    fp = "/c/Users/holylight/.claude/projects/c--users-holylight--claude/memory/foo.md"
    out = _run_pretool("Write", {"file_path": fp, "content": "x"})
    deny = out.get("hookSpecificOutput", {})
    assert deny.get("permissionDecision") == "deny", out
    assert "MemoryPathBlock" in deny.get("permissionDecisionReason", "")


def test_write_with_backslash_path_blocked():
    """Windows 反斜線路徑也擋（regex 兼容）。"""
    fp = r"C:\Users\holylight\.claude\projects\c--tmp\memory\bar.md"
    out = _run_pretool("Write", {"file_path": fp, "content": "x"})
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out


def test_edit_to_projects_slug_memory_blocked():
    """Edit tool 命中也擋（不只 Write）。"""
    fp = "/c/Users/holylight/.claude/projects/c--xxx/memory/foo.md"
    out = _run_pretool("Edit", {"file_path": fp})
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out


def test_staging_under_blocked_path_still_blocked():
    """_staging/ 在被擋路徑下仍擋（_staging 在這層已是禁區）。"""
    fp = "/c/Users/holylight/.claude/projects/c--xxx/memory/_staging/wip.md"
    out = _run_pretool("Write", {"file_path": fp, "content": "x"})
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out


def test_archived_projects_outside_rule_scope():
    """archived 路徑（projects/_archived/{slug}/memory/）多一層，不在規則精確 scope。

    規則精確劃定「projects/{slug}/memory/」單層，archived 已退役非 active 寫入路徑。
    擴 regex 以涵蓋 archived 會誤殺其他多層情境，故 archived 不擋。
    """
    fp = "/c/Users/holylight/.claude/projects/_archived/c--TSG/memory/foo.md"
    out = _run_pretool("Write", {"file_path": fp, "content": "x"})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "MemoryPathBlock" not in reason, out


def test_uppercase_path_blocked():
    """路徑大小寫不敏感（IGNORECASE）。"""
    fp = "C:/Users/Holylight/.CLAUDE/PROJECTS/foo/MEMORY/x.md"
    out = _run_pretool("Write", {"file_path": fp, "content": "x"})
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out


# ─── 放行（應 allow / output_nothing）─────────────────────────────

def test_write_to_global_memory_allowed():
    """正路徑 1：~/.claude/memory/global-x.md → allow。"""
    fp = "/c/Users/holylight/.claude/memory/global-x.md"
    out = _run_pretool("Write", {"file_path": fp, "content": "x"})
    # 注意：可能被 _check_memory_atom_format 擋（缺 frontmatter）— 那是別的閘門。
    # 此處只確認「不是被 MemoryPathBlock 擋」。
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "MemoryPathBlock" not in reason, out


def test_write_to_project_root_memory_allowed():
    """正路徑 2：{project_root}/.claude/memory/shared/x.md → 不被 MemoryPathBlock 擋。"""
    fp = "/c/tmp/docs-progg/.claude/memory/shared/x.md"
    out = _run_pretool("Write", {"file_path": fp, "content": "x"})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "MemoryPathBlock" not in reason, out


def test_bash_tool_unaffected():
    """工具非 Write/Edit（Bash）→ MemoryPathBlock 不作用。"""
    out = _run_pretool("Bash", {"command": "echo hello"})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "MemoryPathBlock" not in reason, out


def test_read_tool_unaffected():
    """工具非 Write/Edit（Read）→ 不作用，即使路徑命中。"""
    fp = "/c/Users/holylight/.claude/projects/c--xxx/memory/foo.md"
    out = _run_pretool("Read", {"file_path": fp})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "MemoryPathBlock" not in reason, out


def test_unrelated_path_allowed():
    """完全不相關路徑（plans/）→ 不擋。"""
    fp = "/c/Users/holylight/.claude/plans/foo.md"
    out = _run_pretool("Write", {"file_path": fp, "content": "x"})
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    assert "MemoryPathBlock" not in reason, out
