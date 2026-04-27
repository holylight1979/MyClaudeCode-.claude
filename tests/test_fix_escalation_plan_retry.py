"""test_fix_escalation_plan_retry.py — FixEscalation 計畫迭代豁免。

議題 B 修補：track_retry 對「計畫類檔」（plans/、_staging/、檔名命中
plan/draft/roadmap/wip）多次編輯不再累計 retry_count，因此不會在下一輪
UserPromptSubmit 注入 [Guardian:FixEscalation]。

真錯誤修復（同 .py / .js 反覆 edit）仍正常觸發。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

from wisdom_engine import track_retry  # noqa: E402


# ─── helper ──────────────────────────────────────────────────────────

def _state_with_edits(file_path: str, n: int) -> dict:
    """建構含 n 次同檔 edit 紀錄的 state（模擬 PostToolUse 已累積 N-1 次 +
    這一次馬上要呼 track_retry）。"""
    return {
        "modified_files": [
            {"path": file_path, "tool": "Edit", "at": f"t{i}"} for i in range(n)
        ],
    }


# ─── 議題 B 主測試 ───────────────────────────────────────────────────

def test_plan_dir_repeated_edits_not_counted_as_retry(tmp_path):
    """正向 1：plans/*.md 連續 5 次 edit → wisdom_retry_count 仍為 0。"""
    plan_path = "C:/Users/x/.claude/plans/whimsical-zooming-sedgewick.md"
    state = {"modified_files": []}
    for _ in range(5):
        state["modified_files"].append({"path": plan_path, "tool": "Edit", "at": "t"})
        track_retry(state, plan_path)
    assert state.get("wisdom_retry_count", 0) == 0


def test_plan_filename_keyword_not_counted_as_retry():
    """正向 2：路徑不在 plans/ 但檔名含 'roadmap' / 'todo' / 'draft' 也豁免。"""
    for fname in ["roadmap-2026.md", "todo-list.md", "draft-spec.md"]:
        path = f"/some/random/dir/{fname}"
        state = _state_with_edits(path, 3)
        track_retry(state, path)
        assert state.get("wisdom_retry_count", 0) == 0, fname


def test_staging_dir_not_counted_as_retry():
    """_staging/ 暫存區也豁免（自由格式區，本就不是 atom 也不是 fix target）。"""
    path = "/proj/.claude/memory/_staging/scratch.md"
    state = _state_with_edits(path, 4)
    track_retry(state, path)
    assert state.get("wisdom_retry_count", 0) == 0


# ─── 反向：真錯誤修復仍觸發 ──────────────────────────────────────────

def test_real_code_repeated_edits_still_count():
    """反向 1：對 hooks/foo.py 反覆 edit → wisdom_retry_count 累加。"""
    path = "/proj/hooks/foo.py"
    state = {"modified_files": []}
    for _ in range(3):
        state["modified_files"].append({"path": path, "tool": "Edit", "at": "t"})
        track_retry(state, path)
    # 第一次 count=1（不 ++），第二次 count=2（++ 至 1），第三次 count=3（++ 至 2）
    assert state.get("wisdom_retry_count", 0) >= 2


def test_real_test_file_repeated_edits_still_count():
    """反向 2：tests/test_foo.py 反覆 edit 也屬於修復重試（除錯場景）。"""
    path = "/proj/tests/test_foo.py"
    state = {"modified_files": []}
    for _ in range(3):
        state["modified_files"].append({"path": path, "tool": "Edit", "at": "t"})
        track_retry(state, path)
    assert state.get("wisdom_retry_count", 0) >= 2


def test_first_edit_no_retry_increment():
    """單次 edit 任何檔（含 .py）→ 不算 retry。"""
    path = "/proj/foo.py"
    state = {"modified_files": [{"path": path, "tool": "Edit", "at": "t0"}]}
    track_retry(state, path)
    assert state.get("wisdom_retry_count", 0) == 0


# ─── 整合：FixEscalation 注入流程 ─────────────────────────────────────
# 直接驗證 retry_count gate（>=2 觸發）的核心邏輯不被 plan 路徑誤觸。

def test_fix_escalation_threshold_not_reached_for_plan():
    """FixEscalation 閾值 retry_count >=2 對 plan 永不到達。"""
    plan_path = "/proj/plans/sprint-eval.md"
    state = {"modified_files": []}
    for _ in range(10):
        state["modified_files"].append({"path": plan_path, "tool": "Edit", "at": "t"})
        track_retry(state, plan_path)
    assert state.get("wisdom_retry_count", 0) < 2  # 永不觸發 FixEscalation
