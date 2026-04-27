"""test_guardian_atom_write_gate.py — PreToolUse Write→memory/*.md 雙閘門。

議題 A 修補：Claude 用 Write tool 直接寫 memory/**/*.md 必須走兩道檢查：
1. 格式閘門（既有）：原子格式 frontmatter ≥3 鍵命中
2. Confidence 閘門（新）：新建 atom 的 Confidence 與內文標籤必須是 [臨]

Mirrors MCP server.js:1109-1117 的硬規則，補上 Write tool 路徑漏洞。
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import importlib  # noqa: E402

wg = importlib.import_module("workflow-guardian")  # type: ignore[attr-defined]


# ─── helpers ─────────────────────────────────────────────────────────

def _atom_content(confidence: str, knowledge_lines: list[str]) -> str:
    body = "\n".join(knowledge_lines)
    return (
        f"# 測試 atom\n\n"
        f"- Scope: shared\n"
        f"- Confidence: {confidence}\n"
        f"- Trigger: t1, t2\n"
        f"- Last-used: 2026-04-27\n"
        f"- Confirmations: 0\n"
        f"- ReadHits: 0\n\n"
        f"## 知識\n\n{body}\n\n## 行動\n\n- run\n"
    )


def _run_pretool(file_path: str, content: str) -> dict:
    """Invoke handle_pre_tool_use with a Write input; return parsed JSON output.

    handle_pre_tool_use exits via sys.exit(0) regardless of decision; capture
    stdout and ignore the SystemExit.
    """
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }
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


# ─── 議題 A 主測試 ───────────────────────────────────────────────────

def test_new_atom_with_solid_confidence_blocked(tmp_path):
    """正向：新建 memory/feedback/*.md 含 Confidence: [固] → block。"""
    fp = tmp_path / ".claude" / "memory" / "feedback" / "feedback-test-new.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    # 不寫檔，模擬「新建」
    content = _atom_content("[固]", ["- [固] 跨 session 已驗證"])
    out = _run_pretool(str(fp), content)
    deny = out.get("hookSpecificOutput", {})
    assert deny.get("permissionDecision") == "deny", out
    assert "[Guardian:AtomConfidence]" in deny.get("permissionDecisionReason", "")


def test_new_atom_with_observed_confidence_blocked(tmp_path):
    """新建含 [觀] 也要擋（不能只擋 [固]，否則低於 server.js 保護水準）。"""
    fp = tmp_path / ".claude" / "memory" / "feedback" / "feedback-test-obs.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    content = _atom_content("[觀]", ["- [觀] 部分驗證"])
    out = _run_pretool(str(fp), content)
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out


def test_new_atom_with_solid_inline_tag_blocked(tmp_path):
    """frontmatter 為 [臨] 但內文知識行含 - [固] → 仍 block（內文也須 [臨]）。"""
    fp = tmp_path / ".claude" / "memory" / "feedback" / "feedback-mixed.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    content = _atom_content("[臨]", ["- [固] 偷渡升級"])
    out = _run_pretool(str(fp), content)
    deny = out.get("hookSpecificOutput", {})
    assert deny.get("permissionDecision") == "deny", out
    assert "[固]" in deny.get("permissionDecisionReason", "")


def test_new_atom_with_temp_confidence_allowed(tmp_path):
    """反向 1：新建 atom Confidence: [臨] + 內文全 [臨] → 放行。"""
    fp = tmp_path / ".claude" / "memory" / "feedback" / "feedback-temp.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    content = _atom_content("[臨]", ["- [臨] 第一次觀察", "- [臨] 待驗證"])
    out = _run_pretool(str(fp), content)
    assert out == {}, out  # output_nothing → 空輸出


def test_existing_atom_overwrite_with_solid_confidence_allowed(tmp_path):
    """反向 2：對既有 atom（已存在路徑）整檔覆寫保留 [固] → 放行。

    Write 對已存在檔案的場景對應 MCP mode=replace 路徑（保留 confirmations
    + readhits 的合法晉升狀態），不應 block。
    """
    fp = tmp_path / ".claude" / "memory" / "feedback" / "feedback-existing.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text("placeholder existing", encoding="utf-8")
    content = _atom_content("[固]", ["- [固] 已晉升條目"])
    out = _run_pretool(str(fp), content)
    assert out == {}, out


# ─── 邊界測試 ────────────────────────────────────────────────────────

def test_staging_path_exempt(tmp_path):
    """_staging/ 自由格式區即使含 [固] 也豁免（規則明確劃定）。"""
    fp = tmp_path / ".claude" / "memory" / "_staging" / "draft.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    content = _atom_content("[固]", ["- [固] random"])
    out = _run_pretool(str(fp), content)
    assert out == {}, out


def test_index_file_exempt(tmp_path):
    """_ 開頭的索引檔豁免（既有規則）。"""
    fp = tmp_path / ".claude" / "memory" / "_INDEX.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    out = _run_pretool(str(fp), "# index\n\n- item")
    assert out == {}, out


def test_non_memory_path_unaffected(tmp_path):
    """非 memory/ 路徑（如 plans/）完全不受此 hook 干擾。"""
    fp = tmp_path / "plans" / "foo.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    content = _atom_content("[固]", ["- [固] anywhere"])
    out = _run_pretool(str(fp), content)
    assert out == {}, out


def test_format_gate_still_works(tmp_path):
    """格式不對的新 memory 寫入仍由 AtomFormat 擋（confidence gate 不前置）。"""
    fp = tmp_path / ".claude" / "memory" / "feedback" / "feedback-bad.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    out = _run_pretool(str(fp), "just some random text without atom frontmatter")
    deny = out.get("hookSpecificOutput", {})
    assert deny.get("permissionDecision") == "deny", out
    assert "[Guardian:AtomFormat]" in deny.get("permissionDecisionReason", "")
