#!/usr/bin/env python3
"""
test_wisdom_sliding_window.py — V2.12 sliding window 行為單元測試

驗證：
  1. first_approach_accuracy.recent: append + 維持 max len = window_size
  2. blind spot detection: len < 3 不啟用、≥3 且 rate < 70% 才寫入
  3. arch_sensitivity_elevated: <34% → True、≥50% → False
  4. silence_accuracy 僅 approach=direct 時 append
  5. over_engineering_rate.recent: retry_count>0 視為 revert 信號
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


def _state(approach="direct", retry_count=0, mod_files=None):
    return {
        "wisdom_approach": approach,
        "wisdom_retry_count": retry_count,
        "modified_files": mod_files or [],
    }


def test_first_approach_sliding_keeps_last_10(_tmp_reflection):
    # 12 single_file successes → recent should be last 10
    for _ in range(12):
        we.reflect(_state(approach="direct", retry_count=0, mod_files=[{"path": "a.py"}]))

    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    recent = data["metrics"]["first_approach_accuracy"]["single_file"]["recent"]
    assert len(recent) == 10
    assert all(recent), "all 12 sessions were successes; window of 10 should be all True"


def test_first_approach_mixes_retain_order(_tmp_reflection):
    # 3 single_file: True, False, True
    we.reflect(_state(retry_count=0, mod_files=[{"path": "a.py"}]))
    we.reflect(_state(retry_count=1, mod_files=[{"path": "a.py"}]))
    we.reflect(_state(retry_count=0, mod_files=[{"path": "a.py"}]))

    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    recent = data["metrics"]["first_approach_accuracy"]["single_file"]["recent"]
    assert recent == [True, False, True]


def test_blind_spot_below_threshold_not_active(_tmp_reflection):
    # 2 single_file failures → len=2 < 3, blind_spots should be empty
    we.reflect(_state(retry_count=1, mod_files=[{"path": "a.py"}]))
    we.reflect(_state(retry_count=1, mod_files=[{"path": "a.py"}]))

    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert data["blind_spots"] == []


def test_blind_spot_triggers_below_70pct(_tmp_reflection):
    # 3 single_file: True, False, False → 33% < 70% → blind_spot
    we.reflect(_state(retry_count=0, mod_files=[{"path": "a.py"}]))
    we.reflect(_state(retry_count=1, mod_files=[{"path": "a.py"}]))
    we.reflect(_state(retry_count=1, mod_files=[{"path": "a.py"}]))

    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert any("single_file" in s for s in data["blind_spots"])


def test_blind_spot_clears_when_rate_recovers(_tmp_reflection):
    # 3 fails → blind_spot present; then 7 successes → recent rate = 70% → just at threshold
    for _ in range(3):
        we.reflect(_state(retry_count=1, mod_files=[{"path": "a.py"}]))
    for _ in range(7):
        we.reflect(_state(retry_count=0, mod_files=[{"path": "a.py"}]))

    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    rate = sum(data["metrics"]["first_approach_accuracy"]["single_file"]["recent"]) / 10
    assert rate == 0.7
    # rate 0.7 == not < 0.7 → cleared
    assert not any("single_file" in s for s in data["blind_spots"])


def test_arch_sensitivity_elevates_below_34pct(_tmp_reflection):
    # 4 architecture sessions, 1 success → 25% < 34% → elevated
    # V2.12 commit-2: arch tolerates 1 retry, so use retry_count=2 for failure
    we.reflect(_state(approach="plan", retry_count=0, mod_files=[{"path": "a.py"}]))
    for _ in range(3):
        we.reflect(_state(approach="plan", retry_count=2, mod_files=[{"path": "a.py"}]))

    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert data["arch_sensitivity_elevated"] is True


def test_arch_sensitivity_clears_at_50pct(_tmp_reflection):
    # First fail to elevate, then enough successes to push rate ≥ 50%
    for _ in range(3):
        we.reflect(_state(approach="plan", retry_count=2, mod_files=[{"path": "a.py"}]))
    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert data["arch_sensitivity_elevated"] is True

    for _ in range(7):
        we.reflect(_state(approach="plan", retry_count=0, mod_files=[{"path": "a.py"}]))
    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    arch_recent = data["metrics"]["first_approach_accuracy"]["architecture"]["recent"]
    rate = sum(arch_recent) / len(arch_recent)
    assert rate >= 0.5
    assert data["arch_sensitivity_elevated"] is False


def test_silence_accuracy_only_tracks_direct(_tmp_reflection):
    # plan + confirm sessions should NOT append to silence_accuracy
    we.reflect(_state(approach="plan", retry_count=0, mod_files=[{"path": "a.py"}]))
    we.reflect(_state(approach="confirm", retry_count=0, mod_files=[{"path": "a.py"}]))
    we.reflect(_state(approach="direct", retry_count=0, mod_files=[{"path": "a.py"}]))
    we.reflect(_state(approach="direct", retry_count=1, mod_files=[{"path": "a.py"}]))

    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    sa_recent = data["metrics"]["silence_accuracy"]["recent"]
    assert len(sa_recent) == 2  # only the 2 direct sessions
    assert sa_recent[0]["ok"] is True
    assert sa_recent[1]["ok"] is False


def test_over_engineering_recent_tracks_retry(_tmp_reflection):
    # 2 retries, 1 clean → over_engineering.recent = [True, True, False]
    we.reflect(_state(retry_count=1, mod_files=[{"path": "a.py"}]))
    we.reflect(_state(retry_count=2, mod_files=[{"path": "a.py"}]))
    we.reflect(_state(retry_count=0, mod_files=[{"path": "a.py"}]))

    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    oe_recent = data["metrics"]["over_engineering_rate"]["recent"]
    assert oe_recent == [True, True, False]


def test_get_reflection_summary_returns_max_two_lines(_tmp_reflection):
    # Trigger blind spots in 3 task types (arch needs retry_count >= 2 to fail)
    for _ in range(3):
        we.reflect(_state(approach="direct", retry_count=1, mod_files=[{"path": "a.py"}]))
    for _ in range(3):
        we.reflect(_state(approach="direct", retry_count=1,
                          mod_files=[{"path": "a.py"}, {"path": "b.py"}]))
    for _ in range(3):
        we.reflect(_state(approach="plan", retry_count=2, mod_files=[{"path": "a.py"}]))

    lines = we.get_reflection_summary()
    assert len(lines) <= 2
    assert all(s.startswith("[自知]") for s in lines)


def test_task_type_from_wisdom_approach_takes_priority(_tmp_reflection):
    # plan approach should always be classified as architecture, regardless of file count
    we.reflect(_state(approach="plan", retry_count=0, mod_files=[{"path": "a.py"}]))

    data = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    arch = data["metrics"]["first_approach_accuracy"]["architecture"]["recent"]
    single = data["metrics"]["first_approach_accuracy"]["single_file"]["recent"]
    assert arch == [True]
    assert single == []
