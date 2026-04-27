"""test_heuristics.py — Codex Companion heuristics 單元測試。

Phase 1 驗證面：
1. completion 三段式：stop_text 宣稱 / trace output 宣稱 / 都沒宣稱
2. 三態 verification：有測試指令 / 無測試指令 / 無修改檔案
3. state-change guard：completion claim 但沒改檔案應 block；改 ≥2 + 有驗證 應放行
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

COMP_DIR = Path(__file__).resolve().parent.parent / "tools" / "codex-companion"
sys.path.insert(0, str(COMP_DIR))

import heuristics  # noqa: E402


def _state(modified=None, trace=None):
    return {
        "modified_files": [{"path": p} for p in (modified or [])],
        "tool_trace": trace or [],
    }


# ─── completion 三段式 ───────────────────────────────────────────────────────


def test_completion_claim_via_stop_text():
    """stop_text 宣稱完成 + 沒驗證 + 改太少 → 觸發 high"""
    st = _state(modified=["a.py"])  # only 1 file
    r = heuristics.check_completion_without_evidence(st, stop_text="搞定，全部完成")
    assert r.triggered is True
    assert r.severity == "high"


def test_completion_claim_via_trace_output():
    """stop_text 為空，但 trace tail 有 'done' → 仍應觸發"""
    trace = [
        {"tool": "Edit", "path": "a.py"},
        {"tool": "Bash", "input": "echo hi", "output_summary": "all set: done"},
    ]
    st = _state(modified=["a.py"], trace=trace)
    r = heuristics.check_completion_without_evidence(st, stop_text="")
    assert r.triggered is True


def test_completion_no_claim_no_trigger():
    """都沒宣稱 → 不觸發"""
    st = _state(modified=["a.py"])
    r = heuristics.check_completion_without_evidence(st, stop_text="繼續中…")
    assert r.triggered is False


# ─── 三態 verification ──────────────────────────────────────────────────────


def test_missing_verification_triggered_when_no_test_cmd():
    """改了檔案但沒測試指令 → 觸發 medium"""
    st = _state(modified=["a.py", "b.py"], trace=[
        {"tool": "Edit", "path": "a.py"},
        {"tool": "Bash", "input": "git status"},
    ])
    r = heuristics.check_missing_verification(st)
    assert r.triggered is True
    assert r.severity == "medium"


def test_missing_verification_not_triggered_when_has_test():
    """改檔案 + 有 pytest → 不觸發"""
    st = _state(modified=["a.py"], trace=[
        {"tool": "Edit", "path": "a.py"},
        {"tool": "Bash", "input": "pytest tests/"},
    ])
    r = heuristics.check_missing_verification(st)
    assert r.triggered is False


def test_missing_verification_not_triggered_when_no_modify():
    """沒改檔案 → 不觸發"""
    st = _state(modified=[], trace=[{"tool": "Read", "path": "a.py"}])
    r = heuristics.check_missing_verification(st)
    assert r.triggered is False


# ─── state-change guard ─────────────────────────────────────────────────────


def test_completion_claim_no_state_change_blocks():
    """宣稱完成但沒改檔案 → 觸發 (state-change guard)"""
    st = _state(modified=[])
    r = heuristics.check_completion_without_evidence(st, stop_text="完成了")
    assert r.triggered is True
    assert "0 file" in r.detail or "only 0" in r.detail


def test_completion_claim_with_evidence_passes():
    """宣稱完成 + 改 ≥2 + 有驗證 → 放行"""
    trace = [
        {"tool": "Edit", "path": "a.py"},
        {"tool": "Edit", "path": "b.py"},
        {"tool": "Bash", "input": "pytest"},
    ]
    st = _state(modified=["a.py", "b.py"], trace=trace)
    r = heuristics.check_completion_without_evidence(st, stop_text="done")
    assert r.triggered is False


# ─── max_severity / triggered_results 集合行為 ──────────────────────────────


def test_triggered_results_filters_only_triggered():
    st = _state(modified=["a.py"])
    results = heuristics.triggered_results(st, stop_text="完成")
    # missing_verification + completion_without_evidence both triggered
    names = {r.name for r in results}
    assert "missing_verification" in names
    assert "completion_without_evidence" in names
    assert all(r.triggered for r in results)


def test_max_severity_picks_high():
    st = _state(modified=["a.py"])
    results = heuristics.triggered_results(st, stop_text="搞定")
    assert heuristics.max_severity(results) == "high"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
