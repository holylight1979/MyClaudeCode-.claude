"""test_reg005_session_start_highlight.py — REG-005 Session 2 補完 (2026-04-29).

Covers `_check_reg005_observation_status` (subprocess wrapper around
tools/atom-injection-summary.py --json) and `_format_reg005_highlight`
(verdict → markdown-bold message formatter) in workflow-guardian.py.

Design: memory/_staging/reg-005-atom-injection-refactor.md (commit 6).
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest  # noqa: F401

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

wg = importlib.import_module("workflow-guardian")  # type: ignore[attr-defined]


# ─── _format_reg005_highlight: pure formatter ──────────────────────────────


def test_format_none_returns_none() -> None:
    assert wg._format_reg005_highlight(None) is None


def test_format_empty_dict_returns_none() -> None:
    assert wg._format_reg005_highlight({}) is None


def test_format_not_started_silent() -> None:
    assert wg._format_reg005_highlight({"verdict": "NOT_STARTED", "details": {}}) is None


def test_format_incomplete_silent() -> None:
    assert wg._format_reg005_highlight({"verdict": "INCOMPLETE", "details": {}}) is None


def test_format_keep_emits_highlight() -> None:
    msg = wg._format_reg005_highlight({
        "verdict": "KEEP",
        "details": {"A_injections": 160, "B_sessions": 7, "wall_clock_days": 3.5},
    })
    assert msg is not None
    assert msg.startswith("**[REG-005]")
    assert msg.endswith("**")
    assert "KEEP" in msg
    assert "A=160" in msg
    assert "B=7" in msg
    assert "wall=3.5d" in msg
    assert "Session 3/3" in msg


def test_format_rollback_emits_highlight() -> None:
    msg = wg._format_reg005_highlight({
        "verdict": "ROLLBACK",
        "details": {"A_injections": 80, "B_sessions": 4, "wall_clock_days": 2.1},
    })
    assert msg is not None
    assert "ROLLBACK" in msg


def test_format_gray_emits_highlight() -> None:
    msg = wg._format_reg005_highlight({
        "verdict": "GRAY",
        "details": {"A_injections": 100, "B_sessions": 5, "wall_clock_days": 7.0},
    })
    assert msg is not None
    assert "GRAY" in msg


def test_format_missing_details_uses_zero_defaults() -> None:
    msg = wg._format_reg005_highlight({"verdict": "KEEP"})
    assert msg is not None
    assert "A=0" in msg
    assert "B=0" in msg
    assert "wall=0d" in msg


def test_format_unknown_verdict_silent() -> None:
    assert wg._format_reg005_highlight({"verdict": "WAT", "details": {}}) is None


# ─── _check_reg005_observation_status: subprocess wrapper ──────────────────


def test_check_no_flag_returns_none(tmp_path: Path) -> None:
    """Flag missing → no subprocess invocation."""
    fake_claude = tmp_path / "claude"
    fake_claude.mkdir()
    with patch.object(wg, "CLAUDE_DIR", fake_claude), \
         patch.object(subprocess, "run") as mock_run:
        assert wg._check_reg005_observation_status() is None
        mock_run.assert_not_called()


def test_check_no_summary_script_returns_none(tmp_path: Path) -> None:
    """Flag exists but summary script missing → fail-open None."""
    fake_claude = tmp_path / "claude"
    (fake_claude / "memory" / "_staging").mkdir(parents=True)
    (fake_claude / "memory" / "_staging" / "reg-005-observation-start.flag").write_text("2026-04-29T00:00:00Z")
    with patch.object(wg, "CLAUDE_DIR", fake_claude), \
         patch.object(subprocess, "run") as mock_run:
        assert wg._check_reg005_observation_status() is None
        mock_run.assert_not_called()


def _setup_observation_state(tmp_path: Path) -> Path:
    """Create flag + dummy summary script under tmp_path/claude."""
    fake_claude = tmp_path / "claude"
    (fake_claude / "memory" / "_staging").mkdir(parents=True)
    (fake_claude / "memory" / "_staging" / "reg-005-observation-start.flag").write_text("2026-04-29T00:00:00Z")
    (fake_claude / "tools").mkdir(parents=True)
    (fake_claude / "tools" / "atom-injection-summary.py").write_text("# stub\n")
    return fake_claude


def test_check_keep_returns_parsed_dict(tmp_path: Path) -> None:
    fake_claude = _setup_observation_state(tmp_path)
    payload = {
        "verdict": "KEEP",
        "details": {"A_injections": 160, "B_sessions": 7, "wall_clock_days": 3},
    }
    fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr="")
    with patch.object(wg, "CLAUDE_DIR", fake_claude), \
         patch.object(subprocess, "run", return_value=fake_result):
        result = wg._check_reg005_observation_status()
    assert result is not None
    assert result["verdict"] == "KEEP"
    assert result["details"]["A_injections"] == 160


def test_check_subprocess_nonzero_returns_none(tmp_path: Path) -> None:
    fake_claude = _setup_observation_state(tmp_path)
    fake_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
    with patch.object(wg, "CLAUDE_DIR", fake_claude), \
         patch.object(subprocess, "run", return_value=fake_result):
        assert wg._check_reg005_observation_status() is None


def test_check_subprocess_timeout_returns_none(tmp_path: Path) -> None:
    fake_claude = _setup_observation_state(tmp_path)
    with patch.object(wg, "CLAUDE_DIR", fake_claude), \
         patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)):
        # Fail-open: should not raise
        assert wg._check_reg005_observation_status() is None


def test_check_invalid_json_returns_none(tmp_path: Path) -> None:
    fake_claude = _setup_observation_state(tmp_path)
    fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="not json {{{", stderr="")
    with patch.object(wg, "CLAUDE_DIR", fake_claude), \
         patch.object(subprocess, "run", return_value=fake_result):
        assert wg._check_reg005_observation_status() is None


def test_check_subprocess_oserror_returns_none(tmp_path: Path) -> None:
    """e.g. python interpreter unavailable → OSError caught → None."""
    fake_claude = _setup_observation_state(tmp_path)
    with patch.object(wg, "CLAUDE_DIR", fake_claude), \
         patch.object(subprocess, "run", side_effect=OSError("exec failed")):
        assert wg._check_reg005_observation_status() is None
