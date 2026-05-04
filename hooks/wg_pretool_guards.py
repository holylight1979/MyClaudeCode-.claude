"""wg_pretool_guards.py — PreToolUse 路徑/指令防呆（2026-04-28，S3.3 強化）

阻擋三條 [固] 級規則的違反動作（兜底；atom 留作 LLM 提示）：
  1. check_memory_path_block:
     (a) ~/.claude/projects/{slug}/memory/ → deny（P1 既有）
     (b) ~/.claude/.claude/memory/ 雙層 → deny（P6 新增）
     (c) 任何 atom .md 直 Write/Edit 不走 funnel → deny（S3.3 新增）
         - 對應 atom: memory/feedback/feedback-memory-path.md
         - 緊急 bypass: env WG_DISABLE_ATOM_GUARD=1
  2. check_svn_test_block: svn commit 含 test 路徑 → deny
     - 對應 atom: memory/feedback/feedback-no-test-to-svn.md

設計：純函式輸入 (tool_name, tool_input) → Optional[deny_reason_str]。
None 表放行；str 表 deny + 該訊息直接給使用者看（內含 atom 路徑指引）。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional


# (a) projects/<slug>/memory/  含正反斜線兩種寫法（Windows 路徑大小寫不敏感）
# P6: 擋 active project memory 單層（slug 不能以 _ 開頭，排除 _archived/_archive 冷儲）
#     另用 _NESTED_PROJECTS_RE 擋雙層 projects/x/projects/y/memory 巢狀殘骸
_PROJECT_MEMORY_PATH_RE = re.compile(
    r"[/\\]\.claude[/\\]projects[/\\](?!_)[^/\\]+[/\\]memory[/\\]",
    re.IGNORECASE,
)
_NESTED_PROJECTS_RE = re.compile(
    r"[/\\]\.claude[/\\]projects[/\\][^/\\]+[/\\]projects[/\\][^/\\]+[/\\]memory[/\\]",
    re.IGNORECASE,
)

# P6: 雙層 .claude 路徑 — ~/.claude/.claude/memory/
_DOUBLE_CLAUDE_RE = re.compile(
    r"[/\\]\.claude[/\\]\.claude[/\\]memory[/\\]",
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


# ─── S3.3 atom funnel 白名單 ────────────────────────────────────────────────
# 白名單檔名（non-atom metadata / index files）
_WHITELIST_BASENAMES = frozenset({
    "MEMORY.md", "_ATOM_INDEX.md", "_CHANGELOG.md", "_CHANGELOG_ARCHIVE.md",
    "_roles.md", "hot_cache.json", "atom_io_audit.jsonl",
    "_promotion_audit.jsonl", "project-registry.json", "session_score.json",
    "DESIGN.md", "role.md",
})
# 白名單目錄 segment（路徑含此 segment 視為非 atom 區）
# 注意：episodic/ 在 SKIP_DIRS 內也被視為非標準 atom，允許手動編輯
_WHITELIST_DIR_SEGMENTS = frozenset({
    "_meta", "_staging", "_archived", "_distant", "_reference", "_pending_review",
    "_vectordb", "_rejected", "templates", "episodic", "wisdom",
    "personal",  # role.md 個人宣告
})


def _path_under_memory_dir(fp: Path) -> bool:
    """判斷 fp 是否落在 ~/.claude/memory/ 或某 project 的 .claude/memory/ 之下。"""
    parts = [p.lower() for p in fp.parts]
    for i in range(len(parts) - 1):
        if parts[i] == ".claude" and parts[i + 1] == "memory":
            return True
    return False


def _atom_path_whitelisted(fp: Path) -> bool:
    """檢查 fp 是否屬於 atom 寫入白名單（非 atom 的 metadata / 索引 / 設計文件）。

    判定順序：
      1. basename 在白名單清單
      2. `_` 前綴或 `SPEC_` 前綴檔名（同 atom_spec.SKIP_PREFIXES）
      3. 路徑含白名單目錄 segment
    """
    if fp.name in _WHITELIST_BASENAMES:
        return True
    # `_` / `SPEC_` 前綴：與 atom_spec.SKIP_PREFIXES 一致，視為非 atom
    if fp.name.startswith("_") or fp.name.startswith("SPEC_"):
        return True
    parts_lower = {p.lower() for p in fp.parts}
    if parts_lower & _WHITELIST_DIR_SEGMENTS:
        return True
    return False


def check_memory_path_block(
    tool_name: str, tool_input: Dict[str, Any]
) -> Optional[str]:
    """阻擋三類 memory 違規寫入：
    (a) ~/.claude/projects/{slug}/memory/（P1）
    (b) ~/.claude/.claude/memory/ 雙層（P6）
    (c) atom .md 直 Write/Edit 不走 funnel（S3.3）— bypass: WG_DISABLE_ATOM_GUARD=1

    僅作用於 Write/Edit；其他工具放行。
    """
    if tool_name not in ("Write", "Edit"):
        return None
    fp_str = tool_input.get("file_path", "") or ""
    if not fp_str:
        return None

    # (a) P1: projects/{slug}/memory/ 殘骸（含真巢狀；排除 _archive 冷儲）
    if _PROJECT_MEMORY_PATH_RE.search(fp_str) or _NESTED_PROJECTS_RE.search(fp_str):
        return (
            "[Guardian:MemoryPathBlock] 禁止寫入 `~/.claude/projects/{slug}/memory/`。"
            "原子記憶專案自治層已覆寫此路徑。\n"
            "正確做法：(1) 全域記憶 → 用 MCP `atom_write` (scope=global) 寫到 "
            "~/.claude/memory/；(2) 專案記憶 → 用 MCP `atom_write` "
            "(scope=shared/role/personal) 寫到 {project_root}/.claude/memory/。\n"
            "詳見 memory/feedback/feedback-memory-path.md。"
        )

    # (b) P6: ~/.claude/.claude/memory/ 雙層
    if _DOUBLE_CLAUDE_RE.search(fp_str):
        return (
            "[Guardian:DoubleClaudeBlock] 禁止寫入 `~/.claude/.claude/memory/` 雙層路徑。"
            "這是 P1 雙層 bug 的殘骸 — 應寫到 `~/.claude/memory/`。\n"
            "若這是 cwd 偵測誤判的結果，檢查 wg_paths.find_project_root + "
            "lib.atom_io._find_project_root 是否把 ~/.claude 當成 project root。"
        )

    # (c) S3.3 強制門禁：atom .md 直 Write/Edit 走 funnel
    if os.environ.get("WG_DISABLE_ATOM_GUARD") == "1":
        return None
    fp = Path(fp_str)
    if not _path_under_memory_dir(fp):
        return None  # 非 memory dir，放行
    if fp.suffix != ".md":
        return None  # 非 .md 放行（.json/.access.json 等）
    if _atom_path_whitelisted(fp):
        return None  # 白名單放行
    return (
        "[Guardian:AtomFunnelBlock] 直接 Write/Edit atom .md 不走 funnel 被禁止。\n"
        f"路徑：{fp_str}\n"
        "正確做法：\n"
        "  (1) 用 MCP `atom_write` / `atom_promote` / `atom_move` 工具\n"
        "  (2) 程式碼端用 lib.atom_io.write_atom() / write_raw() / "
        "update_atom_field()\n"
        "緊急 bypass：set 環境變數 `WG_DISABLE_ATOM_GUARD=1` 後重試。\n"
        "詳見 memory/decisions-architecture.md（funnel 收束章節）。"
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
