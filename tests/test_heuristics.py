"""test_heuristics.py — Codex Companion heuristics 單元測試 (Sprint 2 重構)。

Sprint 2 驗證面：
  * BLOCK 權收斂：唯有 confident_completion_without_evidence 可 high
  * 三條件齊備模型：claim + state_change + no_verify_evidence
  * Sprint 1 教訓 case：state 缺 trace 但 last_assistant_tail 含實證據 → 放行
  * 其他規則（missing_verification / architecture_change / spinning）一律 low
  * severity_at_or_above 門檻 API
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

COMP_DIR = Path(__file__).resolve().parent.parent / "tools" / "codex-companion"
sys.path.insert(0, str(COMP_DIR))

import heuristics  # noqa: E402


def _state(modified=None, trace=None, accessed=None):
    return {
        "modified_files": [{"path": p} for p in (modified or [])],
        "tool_trace": trace or [],
        "accessed_files": accessed or [],
    }


# ─── 三條件 BLOCK 模型 ─────────────────────────────────────────────────────


def test_three_conditions_all_met_blocks_high():
    """has_claim + state_change + no_verify_anywhere → BLOCK high。"""
    trace = [{"tool": "Edit", "path": "a.py"}]
    st = _state(modified=["a.py"], trace=trace)
    r = heuristics.check_confident_completion_without_evidence(st, stop_text="搞定，全部完成")
    assert r.triggered is True
    assert r.severity == "high"


def test_missing_claim_does_not_block():
    """三條件缺 has_claim → 放行。"""
    trace = [{"tool": "Edit", "path": "a.py"}]
    st = _state(modified=["a.py"], trace=trace)
    r = heuristics.check_confident_completion_without_evidence(st, stop_text="繼續處理中…")
    assert r.triggered is False


def test_missing_state_change_does_not_block():
    """三條件缺 state_change → 放行（純討論 turn）。"""
    st = _state()  # no modified, no Edit trace
    r = heuristics.check_confident_completion_without_evidence(st, stop_text="完成了，沒問題")
    assert r.triggered is False
    assert "no state change" in r.detail or "discussion" in r.detail.lower()


def test_verify_cmd_in_trace_does_not_block():
    """三條件缺 no_verify（trace 有 pytest）→ 放行。"""
    trace = [
        {"tool": "Edit", "path": "a.py"},
        {"tool": "Bash", "input": "pytest tests/"},
    ]
    st = _state(modified=["a.py"], trace=trace)
    r = heuristics.check_confident_completion_without_evidence(st, stop_text="done")
    assert r.triggered is False


# ─── Sprint 1 教訓：state 缺 trace 但 tail 有實證據 ────────────────────────


def test_sprint1_lesson_tail_has_verify_narrative_no_block():
    """state file 被擾動 trace 缺，但 last_assistant_tail 明確說「pytest 10/10 通過」。
    應視為弱證據放行，避免 trace 單點失效誤判 BLOCK。
    這正是 Sprint 1 收尾時的真實踩坑案例。
    """
    # 模擬：guardian 仍記得 modified_files（state-{sid}.json 由 guardian 寫，
    # 與 companion-state-{sid}.json 是兩個檔），但 companion 的 tool_trace 被清掉
    st = _state(modified=["a.py", "b.py"], trace=[])
    tail = "Sprint 1 完成。pytest 10/10 通過、e2e smoke 已跑、commit 已 push。"
    r = heuristics.check_confident_completion_without_evidence(st, stop_text=tail)
    assert r.triggered is False
    assert "narrative" in r.detail or "weak evidence" in r.detail


def test_verify_narrative_x_over_y_pass_format():
    """X/Y PASS 分數型也算驗證敘述。"""
    st = _state(modified=["a.py"], trace=[])
    r = heuristics.check_confident_completion_without_evidence(
        st, stop_text="done. 28/28 PASS"
    )
    assert r.triggered is False


def test_verify_narrative_build_succeeded():
    """build 成功也算驗證敘述。"""
    st = _state(modified=["a.py"], trace=[])
    r = heuristics.check_confident_completion_without_evidence(
        st, stop_text="完成。build 成功，已 push。"
    )
    assert r.triggered is False


def test_verify_narrative_must_be_real_not_just_completion():
    """光說「完成」不算驗證敘述；必須含 pytest/build/tests/驗證 等證據詞。"""
    st = _state(modified=["a.py"], trace=[{"tool": "Edit", "path": "a.py"}])
    r = heuristics.check_confident_completion_without_evidence(
        st, stop_text="完成了。"
    )
    # 三條件齊：has_claim + state_change + no_verify → BLOCK
    assert r.triggered is True
    assert r.severity == "high"


# ─── state_change 雙來源（modified_files / trace Edit-Write）────────────


def test_state_change_via_trace_edit_when_modified_empty():
    """modified_files 空但 trace 有 Edit → 仍視為 state_change。"""
    trace = [{"tool": "Edit", "path": "x.py"}]
    st = _state(modified=[], trace=trace)
    r = heuristics.check_confident_completion_without_evidence(st, stop_text="完成")
    # claim + state_change(via trace) + no verify → BLOCK
    assert r.triggered is True


def test_state_change_via_modified_files_when_trace_empty():
    """trace 空但 modified_files 有檔 → 仍視為 state_change。"""
    st = _state(modified=["x.py"], trace=[])
    r = heuristics.check_confident_completion_without_evidence(st, stop_text="完成")
    assert r.triggered is True


# ─── 其他規則一律 advisory (low) ────────────────────────────────────────


def test_missing_verification_is_low_only():
    """改檔沒測 → 觸發但 severity=low，不應 BLOCK。"""
    st = _state(modified=["a.py", "b.py"], trace=[
        {"tool": "Edit", "path": "a.py"},
        {"tool": "Bash", "input": "git status"},
    ])
    r = heuristics.check_missing_verification(st)
    assert r.triggered is True
    assert r.severity == "low"


def test_missing_verification_not_triggered_when_has_test():
    st = _state(modified=["a.py"], trace=[
        {"tool": "Edit", "path": "a.py"},
        {"tool": "Bash", "input": "pytest tests/"},
    ])
    r = heuristics.check_missing_verification(st)
    assert r.triggered is False


def test_missing_verification_not_triggered_when_no_modify():
    st = _state(modified=[], trace=[{"tool": "Read", "path": "a.py"}])
    r = heuristics.check_missing_verification(st)
    assert r.triggered is False


def test_architecture_change_is_low_only():
    """改架構檔 → 觸發但 severity=low，advisory only。"""
    st = _state(modified=["src/payment_provider.py"])
    r = heuristics.check_architecture_change(st)
    assert r.triggered is True
    assert r.severity == "low"


def test_architecture_change_not_triggered_for_normal_files():
    st = _state(modified=["utils.py", "main.py"])
    r = heuristics.check_architecture_change(st)
    assert r.triggered is False


def test_spinning_low_only():
    trace = [
        {"tool": "Read", "path": "a.py"},
        {"tool": "Read", "path": "a.py"},
        {"tool": "Read", "path": "a.py"},
    ]
    st = _state(trace=trace)
    r = heuristics.check_spinning(st)
    assert r.triggered is True
    assert r.severity == "low"


# ─── max_severity / severity_at_or_above / triggered_results ───────────


def test_max_severity_high_only_from_confident_completion():
    """只有三條件齊備時 max_severity 才會是 high；其他規則最高 low。"""
    trace = [{"tool": "Edit", "path": "a.py"}]
    st = _state(modified=["a.py", "src/payment_provider.py"], trace=trace)
    results = heuristics.triggered_results(st, stop_text="搞定")
    # 此 case：missing_verification(low) + architecture_change(low) + confident_completion(high)
    assert heuristics.max_severity(results) == "high"


def test_max_severity_low_when_no_completion_claim():
    """改檔 + 改架構檔但沒宣稱完成 → max 應是 low。"""
    st = _state(modified=["src/payment_provider.py", "a.py"])
    results = heuristics.triggered_results(st, stop_text="continuing work")
    assert heuristics.max_severity(results) == "low"


def test_severity_at_or_above_high_threshold():
    """門檻=high：只有 confident_completion 命中才算過。"""
    # case A: 純 advisory → 不過門檻
    st = _state(modified=["a.py", "src/api_service.py"])
    results = heuristics.triggered_results(st, stop_text="continuing")
    assert heuristics.severity_at_or_above(results, "high") is False

    # case B: 三條件齊 → 過門檻
    trace = [{"tool": "Edit", "path": "a.py"}]
    st2 = _state(modified=["a.py"], trace=trace)
    results2 = heuristics.triggered_results(st2, stop_text="完成")
    assert heuristics.severity_at_or_above(results2, "high") is True


def test_severity_at_or_above_empty_returns_false():
    assert heuristics.severity_at_or_above([], "high") is False
    assert heuristics.severity_at_or_above([], "low") is False


# ─── 向下相容 alias ─────────────────────────────────────────────────────


def test_legacy_alias_maps_to_new_logic():
    """check_completion_without_evidence 應為新 confident 版的 alias。"""
    assert (
        heuristics.check_completion_without_evidence
        is heuristics.check_confident_completion_without_evidence
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
