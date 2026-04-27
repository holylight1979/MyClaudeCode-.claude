"""test_assessor_retry.py — Sprint 4 Phase 5.1 單測。

涵蓋三件事：
  1. _run_codex_with_retry：第一次空回 → 退 0.4s 重試 → 第二次成功解析
  2. _classify_failure：stderr 含 CreateProcessWithLogon → category=system 且
     summary 提到 sandbox（防 R2-5 級 bug 再被吞掉）
  3. _classify_failure：其他失敗（timeout / 一般 error）→ status=warning,
     delivery=inject, summary="退回 heuristics-only", notify_next_turn=True

不實際呼叫 codex；以 monkeypatch 替代 _run_codex 與 time.sleep。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

CLAUDE_DIR = Path.home() / ".claude"
COMPANION_DIR = CLAUDE_DIR / "tools" / "codex-companion"
sys.path.insert(0, str(COMPANION_DIR))

import assessor  # noqa: E402


# ─── retry 行為 ──────────────────────────────────────────────────────


def test_retry_on_empty_then_parses(monkeypatch):
    """第一次回空字串、第二次回合法 JSON → 走 retry 路徑、attempts=2、解析成功。"""
    calls = {"n": 0}

    def fake_run(prompt, cwd, cfg):
        calls["n"] += 1
        if calls["n"] == 1:
            return "", "first call empty"
        return (
            '{"status":"ok","severity":"low","category":"completion_risk",'
            '"summary":"sprint4 retry pass","delivery":"ignore",'
            '"confidence":"medium","applies_until":"next_prompt","turn_index":0}',
            "",
        )

    sleeps: list[float] = []
    monkeypatch.setattr(assessor, "_run_codex", fake_run)
    monkeypatch.setattr(assessor.time, "sleep", lambda s: sleeps.append(s))

    result = assessor.run_assessment(
        assessment_type="turn_audit",
        session_id="sid-retry",
        tool_trace=[],
        cwd="",
        extra_context={"turn_index": 1},
        config={"codex_binary": "x"},
    )

    assert calls["n"] == 2, "expected one retry"
    assert result.get("_attempts") == 2
    assert result.get("status") == "ok"
    assert result.get("summary") == "sprint4 retry pass"
    # 重試前必須 sleep 一次（300-500ms 區間，實作為 0.4）
    assert sleeps and 0.3 <= sleeps[0] <= 0.5, f"unexpected sleep series: {sleeps}"


def test_first_attempt_succeeds_no_retry(monkeypatch):
    """第一次回成功 JSON → attempts=1、_run_codex 只被呼叫一次。"""
    calls = {"n": 0}

    def fake_run(prompt, cwd, cfg):
        calls["n"] += 1
        return (
            '{"status":"ok","severity":"low","category":"completion_risk",'
            '"summary":"first try","delivery":"ignore",'
            '"confidence":"high"}',
            "",
        )

    monkeypatch.setattr(assessor, "_run_codex", fake_run)
    monkeypatch.setattr(assessor.time, "sleep", lambda s: None)

    result = assessor.run_assessment(
        assessment_type="turn_audit",
        session_id="sid-no-retry",
        tool_trace=[],
        cwd="",
        extra_context={"turn_index": 2},
        config={},
    )

    assert calls["n"] == 1, "should not retry on first-success"
    assert result.get("_attempts") == 1
    assert result.get("summary") == "first try"


# ─── _classify_failure：sandbox 識別（R2-5 防退化） ─────────────────


@pytest.mark.parametrize("stderr_excerpt", [
    "error: CreateProcessWithLogonW failed 1385",
    "spawn failed: sandbox exec error",
    "createprocesswithlogon",  # case-insensitive
])
def test_classify_failure_sandbox_category_system(stderr_excerpt):
    result = assessor._classify_failure(stderr_excerpt)
    assert result["category"] == "system"
    assert "sandbox" in result["summary"]
    assert result["delivery"] == "inject"
    assert result["severity"] == "high"
    assert result.get("notify_next_turn") is True
    # 證據要保留 stderr（讓人 debug 用）
    assert stderr_excerpt[:80] in result["evidence"]


def test_classify_failure_other_warning_with_notify():
    """非 sandbox 的失敗（timeout / 一般 error）→ warning + notify_next_turn=True。"""
    result = assessor._classify_failure("[assessor] timeout after 60s")
    assert result["status"] == "warning"
    assert result["delivery"] == "inject"
    assert result["category"] == "system"
    assert "heuristics-only" in result["summary"]
    assert result.get("notify_next_turn") is True
    assert result["confidence"] == "low"


# ─── 整合：retry 兩次都失敗 → classify_failure 介入 ────────────────


def test_both_attempts_fail_invokes_classify(monkeypatch):
    """兩次都回空 + sandbox 訊息 → 走 _classify_failure 路徑。"""
    def fake_run(prompt, cwd, cfg):
        return "", "CreateProcessWithLogonW spawn failure"

    monkeypatch.setattr(assessor, "_run_codex", fake_run)
    monkeypatch.setattr(assessor.time, "sleep", lambda s: None)

    result = assessor.run_assessment(
        assessment_type="turn_audit",
        session_id="sid-double-fail",
        tool_trace=[],
        cwd="",
        extra_context={"turn_index": 3},
        config={},
    )

    assert result.get("_attempts") == 2
    assert result.get("category") == "system"
    assert "sandbox" in result.get("summary", "")
    assert result.get("notify_next_turn") is True


def test_both_attempts_fail_generic_error(monkeypatch):
    """兩次都回空 + 非 sandbox stderr → warning + notify_next_turn。"""
    def fake_run(prompt, cwd, cfg):
        return "", "[assessor] codex binary not found: codex"

    monkeypatch.setattr(assessor, "_run_codex", fake_run)
    monkeypatch.setattr(assessor.time, "sleep", lambda s: None)

    result = assessor.run_assessment(
        assessment_type="turn_audit",
        session_id="sid-bin-missing",
        tool_trace=[],
        cwd="",
        extra_context={"turn_index": 4},
        config={},
    )

    assert result.get("status") == "warning"
    assert result.get("notify_next_turn") is True
    # 一般錯誤不應被誤判為 sandbox
    assert "sandbox" not in result.get("summary", "")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
