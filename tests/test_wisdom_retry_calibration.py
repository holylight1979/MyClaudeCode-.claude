#!/usr/bin/env python3
"""
test_wisdom_retry_calibration.py — V2.12 retry 信號重新校準

驗證：
  1. track_retry plan-mode threshold = 4（vs 預設 2）
  2. track_retry direct-mode 維持 threshold = 2（不變）
  3. track_retry plan iteration path 仍豁免（與 plan-mode threshold 互補）
  4. reflect architecture 容忍 1 retry（plan-mode iteration 是設計上要試錯）
  5. reflect architecture + fix_escalation_triggered → 真失敗（覆蓋容忍）
  6. reflect single_file / multi_file 維持嚴格規則 retry_count == 0

Background:
  V2.11 retry 邏輯對 architecture 任務系統性偏誤：plan-mode session 本質要
  iterate（同檔多次 Edit = 試錯探索），但被 V2.11 計入 retry_count，把
  architecture first-approach accuracy 拉到 13%。V2.12 透過：
    (a) plan-mode 提高同檔 Edit threshold 從 2 → 4
    (b) reflect() 對 architecture 容忍 1 retry，但 fix_escalation_triggered
        是真失敗信號（覆蓋容忍）
"""

import json
import sys
from pathlib import Path

import pytest

_HOOKS_DIR = Path.home() / ".claude" / "hooks"
sys.path.insert(0, str(_HOOKS_DIR))

import wisdom_engine as we  # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_reflection(tmp_path, monkeypatch):
    p = tmp_path / "reflection_metrics.json"
    monkeypatch.setattr(we, "REFLECTION_PATH", p)
    yield p


# ── track_retry: plan-mode threshold ────────────────────────────────────────


def test_plan_mode_3_edits_no_retry(_tmp_reflection):
    """plan approach + 同檔 3 次 Edit → 不計 retry（threshold=4）。"""
    state = {
        "wisdom_approach": "plan",
        "modified_files": [{"path": "src/a.py"}, {"path": "src/a.py"}, {"path": "src/a.py"}],
    }
    we.track_retry(state, "src/a.py")
    assert state.get("wisdom_retry_count", 0) == 0


def test_plan_mode_4_edits_counts_as_retry(_tmp_reflection):
    """plan approach + 同檔 4 次 Edit → 計 1 retry。"""
    state = {
        "wisdom_approach": "plan",
        "modified_files": [{"path": "src/a.py"}] * 4,
    }
    we.track_retry(state, "src/a.py")
    assert state["wisdom_retry_count"] == 1


def test_direct_mode_2_edits_counts_as_retry(_tmp_reflection):
    """direct approach + 同檔 2 次 Edit → 維持 V2.11 規則，計 1 retry。"""
    state = {
        "wisdom_approach": "direct",
        "modified_files": [{"path": "src/a.py"}, {"path": "src/a.py"}],
    }
    we.track_retry(state, "src/a.py")
    assert state["wisdom_retry_count"] == 1


def test_confirm_mode_uses_default_threshold(_tmp_reflection):
    """confirm approach 不適用 plan-mode 寬鬆規則，仍 threshold=2。"""
    state = {
        "wisdom_approach": "confirm",
        "modified_files": [{"path": "src/a.py"}, {"path": "src/a.py"}],
    }
    we.track_retry(state, "src/a.py")
    assert state["wisdom_retry_count"] == 1


def test_plan_path_excluded_regardless_of_approach(_tmp_reflection):
    """計畫檔（plans/）路徑豁免，與 wisdom_approach 無關。"""
    # _is_plan_iteration_path 用 "/plans/" 子串檢查 → 路徑需含 leading 區段
    plan_path = "C:/Users/holylight/.claude/plans/foo.md"
    state = {
        "wisdom_approach": "direct",
        "modified_files": [{"path": plan_path}] * 5,
    }
    we.track_retry(state, plan_path)
    assert state.get("wisdom_retry_count", 0) == 0


def test_unknown_approach_defaults_to_direct(_tmp_reflection):
    """未設 wisdom_approach → 預設視為 direct（threshold=2）。"""
    state = {"modified_files": [{"path": "src/a.py"}, {"path": "src/a.py"}]}
    we.track_retry(state, "src/a.py")
    assert state["wisdom_retry_count"] == 1


# ── reflect(): architecture tolerance ───────────────────────────────────────


def test_arch_correct_with_zero_retry(_tmp_reflection):
    """architecture + retry_count=0 → correct=True（顯然成功）。"""
    we.reflect({
        "wisdom_approach": "plan",
        "wisdom_retry_count": 0,
        "modified_files": [{"path": "a.py"}],
    })
    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert data["metrics"]["first_approach_accuracy"]["architecture"]["recent"] == [True]


def test_arch_correct_with_one_retry_tolerance(_tmp_reflection):
    """architecture + retry_count=1 + no fix_esc → correct=True（容忍 1 次小重試）。"""
    we.reflect({
        "wisdom_approach": "plan",
        "wisdom_retry_count": 1,
        "fix_escalation_triggered": False,
        "modified_files": [{"path": "a.py"}],
    })
    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert data["metrics"]["first_approach_accuracy"]["architecture"]["recent"] == [True]


def test_arch_incorrect_with_two_retries(_tmp_reflection):
    """architecture + retry_count=2 → 超過容忍門檻 → correct=False。"""
    we.reflect({
        "wisdom_approach": "plan",
        "wisdom_retry_count": 2,
        "modified_files": [{"path": "a.py"}],
    })
    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert data["metrics"]["first_approach_accuracy"]["architecture"]["recent"] == [False]


def test_arch_incorrect_when_fix_escalated(_tmp_reflection):
    """architecture + retry_count=0 + fix_escalation_triggered=True → 真失敗信號覆蓋容忍。"""
    we.reflect({
        "wisdom_approach": "plan",
        "wisdom_retry_count": 0,
        "fix_escalation_triggered": True,
        "modified_files": [{"path": "a.py"}],
    })
    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert data["metrics"]["first_approach_accuracy"]["architecture"]["recent"] == [False]


def test_arch_incorrect_when_fix_escalated_with_one_retry(_tmp_reflection):
    """architecture + retry_count=1 + fix_esc=True → fix_esc 覆蓋容忍 → False。"""
    we.reflect({
        "wisdom_approach": "plan",
        "wisdom_retry_count": 1,
        "fix_escalation_triggered": True,
        "modified_files": [{"path": "a.py"}],
    })
    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert data["metrics"]["first_approach_accuracy"]["architecture"]["recent"] == [False]


# ── reflect(): non-architecture strict rule unchanged ───────────────────────


def test_single_file_strict_no_tolerance(_tmp_reflection):
    """single_file + retry_count=1 → correct=False（非 arch，仍嚴格）。"""
    we.reflect({
        "wisdom_approach": "direct",
        "wisdom_retry_count": 1,
        "modified_files": [{"path": "a.py"}],
    })
    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert data["metrics"]["first_approach_accuracy"]["single_file"]["recent"] == [False]


def test_multi_file_strict_no_tolerance(_tmp_reflection):
    """multi_file + retry_count=1 → correct=False（非 arch，仍嚴格）。"""
    we.reflect({
        "wisdom_approach": "direct",
        "wisdom_retry_count": 1,
        "modified_files": [{"path": "a.py"}, {"path": "b.py"}],
    })
    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert data["metrics"]["first_approach_accuracy"]["multi_file"]["recent"] == [False]


def test_simulation_arch_calibration_lifts_rate(_tmp_reflection):
    """模擬：3 sessions plan + retry=1 + no fix_esc。

    V2.11 邏輯下：3 fails → arch sensitivity elevated
    V2.12 邏輯下：3 successes → arch sensitivity 不會 elevate（合理校準）
    """
    for _ in range(3):
        we.reflect({
            "wisdom_approach": "plan",
            "wisdom_retry_count": 1,
            "fix_escalation_triggered": False,
            "modified_files": [{"path": "a.py"}],
        })

    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    arch_recent = data["metrics"]["first_approach_accuracy"]["architecture"]["recent"]
    assert arch_recent == [True, True, True]
    assert data["arch_sensitivity_elevated"] is False
    # blind_spot should NOT trigger because rate = 100%
    assert not any("architecture" in s for s in data["blind_spots"])
