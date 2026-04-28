"""wg_pretool_guards.py — PreToolUse 路徑/指令防呆（2026-04-28）

阻擋兩條 [固] 級規則的違反動作（兜底；atom 留作 LLM 提示）：
  1. check_memory_path_block: 寫入 ~/.claude/projects/{slug}/memory/ → deny
     - 對應 atom: memory/feedback/feedback-memory-path.md
  2. check_svn_test_block: svn commit 含 test 路徑 → deny
     - 對應 atom: memory/feedback/feedback-no-test-to-svn.md

設計：純函式輸入 (tool_name, tool_input) → Optional[deny_reason_str]。
None 表放行；str 表 deny + 該訊息直接給使用者看（內含 atom 路徑指引）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


# (a) projects/<slug>/memory/  含正反斜線兩種寫法（Windows 路徑大小寫不敏感）
_PROJECT_MEMORY_PATH_RE = re.compile(
    r"[/\\]\.claude[/\\]projects[/\\][^/\\]+[/\\]memory[/\\]",
    re.IGNORECASE,
)

# (b) svn commit / svn ci
_SVN_COMMIT_RE = re.compile(r"\bsvn\s+(?:ci|commit)\b", re.IGNORECASE)

# 測試路徑：tests/ tests\ __tests__/ 或檔名以 Test.<ext> 結尾（限縮副檔名避免誤殺）
_TEST_PATH_RE = re.compile(
    r"(?:^|[/\\\s])(?:tests?|__tests__)(?:[/\\\s]|$)"
    r"|[/\\][^/\\\s]*Test\.(?:cs|py|js|ts|tsx|jsx|go|java)\b",
    re.IGNORECASE,
)


def check_memory_path_block(
    tool_name: str, tool_input: Dict[str, Any]
) -> Optional[str]:
    """阻擋寫入 ~/.claude/projects/{slug}/memory/。

    僅作用於 Write/Edit；其他工具放行。
    """
    if tool_name not in ("Write", "Edit"):
        return None
    fp = tool_input.get("file_path", "") or ""
    if not _PROJECT_MEMORY_PATH_RE.search(fp):
        return None
    return (
        "[Guardian:MemoryPathBlock] 禁止寫入 `~/.claude/projects/{slug}/memory/`。"
        "原子記憶專案自治層已覆寫此路徑。\n"
        "正確做法：(1) 全域記憶 → 用 MCP `atom_write` (scope=global) 寫到 "
        "~/.claude/memory/；(2) 專案記憶 → 用 MCP `atom_write` "
        "(scope=shared/role/personal) 寫到 {project_root}/.claude/memory/。\n"
        "詳見 memory/feedback/feedback-memory-path.md。"
    )


def check_svn_test_block(
    tool_name: str, tool_input: Dict[str, Any]
) -> Optional[str]:
    """阻擋 svn commit 含 test/ tests/ __tests__/ 路徑或 *Test.<ext> 檔。

    僅作用於 Bash；其他工具放行。git commit 不在規則內（走另條規則）。
    """
    if tool_name != "Bash":
        return None
    cmd = tool_input.get("command", "") or ""
    if not _SVN_COMMIT_RE.search(cmd):
        return None
    if not _TEST_PATH_RE.search(cmd):
        return None
    return (
        "[Guardian:SvnTestBlock] svn commit 命令含 test/tests/__tests__ 路徑或 "
        "*Test.<ext> 檔案。測試/練習/新手作業檔不可上 SVN（r10854 教訓）。\n"
        "若確實要上，請 (1) 將指定檔案逐一列入命令、不用 glob；或 "
        "(2) 由使用者明確指示後再執行。\n"
        "詳見 memory/feedback/feedback-no-test-to-svn.md。"
    )
