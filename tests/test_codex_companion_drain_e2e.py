"""test_codex_companion_drain_e2e.py — Sprint 3 e2e for drain + score gate.

涵蓋三個 Phase 3+4 的關鍵行為：
  1. delivery=ignore  → UserPromptSubmit drain 不注入文字（標 injected）
  2. delivery=inject  → 注入文字含 confidence + applies_until 標籤
  3. score_threshold gate → Stop hook 對低分 turn 不送 /trigger
                            （無法直接觀察 trigger，改驗 dedup 行為等價：
                             低分 turn 不應因為「重跑」就建出新 assessment）

採子程序方式呼叫 codex_companion.py，pipe event JSON 到 stdin，檢查
stdout JSON。HTTP 呼叫在 service 未起時 silent timeout，不阻塞。
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

CLAUDE_DIR = Path.home() / ".claude"
HOOK_SCRIPT = CLAUDE_DIR / "hooks" / "codex_companion.py"
WORKFLOW_DIR = CLAUDE_DIR / "workflow"


def _write_assessment_file(
    session_id: str,
    turn_index: int,
    atype: str,
    assessment: dict,
    injected: bool = False,
) -> Path:
    path = WORKFLOW_DIR / f"companion-assessment-{session_id}-t{turn_index}-{atype}.json"
    data = {
        "session_id": session_id,
        "turn_index": turn_index,
        "type": atype,
        "assessment": assessment,
        "injected": injected,
        "created_at": "2026-04-27T00:00:00+08:00",
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _run_hook(input_data: dict) -> tuple[str, str, int]:
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(input_data, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    return proc.stdout, proc.stderr, proc.returncode


@pytest.fixture
def cleanup_session():
    sid = f"test-sprint3-{uuid.uuid4().hex[:8]}"
    yield sid
    for pat in (
        f"state-{sid}.json",
        f"companion-state-{sid}.json",
    ):
        p = WORKFLOW_DIR / pat
        if p.exists():
            p.unlink()
    for p in WORKFLOW_DIR.glob(f"companion-assessment-{sid}-*.json"):
        p.unlink(missing_ok=True)
    for p in WORKFLOW_DIR.glob(f"companion-assessment-{sid}-*.tmp"):
        p.unlink(missing_ok=True)


# ─── Phase 4.4：delivery 路由 ──────────────────────────────────────────


@pytest.mark.skipif(not HOOK_SCRIPT.exists(), reason="codex_companion.py not present")
def test_drain_delivery_ignore_does_not_inject(cleanup_session):
    """codex 回 delivery=ignore → drain 不輸出 additionalContext，只標 injected。"""
    sid = cleanup_session
    path = _write_assessment_file(
        sid, turn_index=1, atype="turn_audit",
        assessment={
            "status": "ok",
            "severity": "low",
            "category": "completion_risk",
            "summary": "代理人本輪 work 與 trace 一致，無需打擾。",
            "delivery": "ignore",
            "confidence": "high",
            "applies_until": "next_prompt",
        },
    )

    stdout, stderr, rc = _run_hook({
        "hook_event_name": "UserPromptSubmit",
        "session_id": sid,
        "prompt": "next user message",
    })

    assert rc == 0, f"hook crashed: {stderr}"
    # delivery=ignore 應該不注入任何 additionalContext，hook 走 _output_nothing()
    assert "additionalContext" not in stdout, (
        f"delivery=ignore should NOT inject context, got stdout={stdout!r}"
    )
    # 但 assessment 應被標 injected（避免之後又被掃到）
    data_after = json.loads(path.read_text(encoding="utf-8"))
    assert data_after.get("injected") is True, (
        "ignored assessment must still be marked injected to avoid re-scan loop"
    )


@pytest.mark.skipif(not HOOK_SCRIPT.exists(), reason="codex_companion.py not present")
def test_drain_delivery_inject_emits_with_confidence_label(cleanup_session):
    """codex 回 delivery=inject + confidence=high → 注入文字含信心 + 事證 + 建議。"""
    sid = cleanup_session
    _write_assessment_file(
        sid, turn_index=2, atype="turn_audit",
        assessment={
            "status": "needs_followup",
            "severity": "medium",
            "category": "missing_evidence",
            "summary": "改了 a.py 但沒跑 pytest，宣告完成證據不足。",
            "evidence": "tool_trace 未見 Bash/pytest；modified=[a.py]。",
            "delivery": "inject",
            "confidence": "high",
            "applies_until": "next_prompt",
            "corrective_prompt": "請補跑 pytest tests/test_a.py 並貼結果。",
        },
    )

    stdout, stderr, rc = _run_hook({
        "hook_event_name": "UserPromptSubmit",
        "session_id": sid,
        "prompt": "next user message",
    })

    assert rc == 0, f"hook crashed: {stderr}"
    assert "additionalContext" in stdout, (
        f"delivery=inject should produce additionalContext, got {stdout!r}"
    )
    parsed = json.loads(stdout.strip().splitlines()[-1])
    ctx = parsed["hookSpecificOutput"]["additionalContext"]

    # Header 含 confidence 標籤
    assert "confidence=high" in ctx, f"missing confidence label: {ctx!r}"
    assert "高信心" in ctx, f"missing zh-TW confidence label: {ctx!r}"
    # 含 turn_index 標記
    assert "t2" in ctx, f"missing turn_index marker: {ctx!r}"
    # 各欄位都進去了
    assert "改了 a.py 但沒跑 pytest" in ctx
    assert "tool_trace 未見 Bash/pytest" in ctx  # evidence
    assert "請補跑 pytest" in ctx                # corrective


@pytest.mark.skipif(not HOOK_SCRIPT.exists(), reason="codex_companion.py not present")
def test_drain_orders_by_turn_index_when_multiple_pending(cleanup_session):
    """多筆 pending 應依 turn_index 排序合併（避免新 turn 比舊 turn 先注入）。"""
    sid = cleanup_session
    _write_assessment_file(
        sid, turn_index=5, atype="turn_audit",
        assessment={
            "status": "warning", "severity": "medium",
            "summary": "FIVE", "delivery": "inject",
            "confidence": "medium",
        },
    )
    _write_assessment_file(
        sid, turn_index=3, atype="turn_audit",
        assessment={
            "status": "warning", "severity": "medium",
            "summary": "THREE", "delivery": "inject",
            "confidence": "medium",
        },
    )

    stdout, _, rc = _run_hook({
        "hook_event_name": "UserPromptSubmit",
        "session_id": sid,
        "prompt": "x",
    })

    assert rc == 0
    parsed = json.loads(stdout.strip().splitlines()[-1])
    ctx = parsed["hookSpecificOutput"]["additionalContext"]
    pos_three = ctx.find("THREE")
    pos_five = ctx.find("FIVE")
    assert 0 <= pos_three < pos_five, (
        f"expected THREE before FIVE in turn order, got ctx={ctx!r}"
    )


# ─── Phase 3.2：score gate（低分 turn 不應建立 assessment 檔）──────────


@pytest.mark.skipif(not HOOK_SCRIPT.exists(), reason="codex_companion.py not present")
def test_stop_hook_runs_clean_on_low_score_turn(cleanup_session):
    """低分 turn（純對話、無寫入、無宣告）→ Stop hook 不應 BLOCK 也不應 crash。

    無法直接觀察 /trigger 是否被送出（service 沒起、HTTP 是 silent fail），
    但可確認：(a) 不 BLOCK (b) 不 crash (c) stdout 乾淨。
    score gate 路徑被走過的證明：handle_stop 沒走到 BLOCK 分支。
    """
    sid = cleanup_session
    # 純對話：無 modified、無 trace
    (WORKFLOW_DIR / f"state-{sid}.json").write_text(
        json.dumps({"modified_files": [], "accessed_files": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (WORKFLOW_DIR / f"companion-state-{sid}.json").write_text(
        json.dumps({"tool_trace": [], "turn_index": 1}, ensure_ascii=False),
        encoding="utf-8",
    )

    stdout, stderr, rc = _run_hook({
        "hook_event_name": "Stop",
        "session_id": sid,
        "last_assistant_message": "我建議用方案 A 而不是 B。",
    })

    assert rc == 0, f"hook crashed: {stderr}"
    assert '"block"' not in stdout, f"low-score turn should not BLOCK; got {stdout!r}"


@pytest.mark.skipif(not HOOK_SCRIPT.exists(), reason="codex_companion.py not present")
def test_stop_hook_dedups_when_assessment_for_turn_already_exists(cleanup_session):
    """同 turn_index + turn_audit 已落盤 → Stop hook dedup skip，不 BLOCK 也不 crash。"""
    sid = cleanup_session
    # 高分 turn：改 1 檔 + 完成宣告 + 無 verify → score=6 ≥ threshold=4
    (WORKFLOW_DIR / f"state-{sid}.json").write_text(
        json.dumps({"modified_files": [{"path": "a.py"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (WORKFLOW_DIR / f"companion-state-{sid}.json").write_text(
        json.dumps({
            "tool_trace": [{"tool": "Edit", "path": "a.py"}],
            "turn_index": 7,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    # 預先放一份「該 turn 已經有 assessment」的檔案
    _write_assessment_file(
        sid, turn_index=7, atype="turn_audit",
        assessment={
            "status": "ok", "severity": "low",
            "summary": "earlier audit", "delivery": "ignore",
        },
        injected=True,
    )

    # 應該會走進 BLOCK 分支（confident_completion 三條件齊備：tail=完成 + Edit + no verify）
    # 這條 case 的目的不是 dedup 與否的直接觀察（無法）；而是確認 dedup 邏輯不會
    # 干擾既有 BLOCK gate — Sprint 2 的 BLOCK 路徑必須仍正常運作。
    stdout, stderr, rc = _run_hook({
        "hook_event_name": "Stop",
        "session_id": sid,
        "last_assistant_message": "完成。",
    })

    assert rc == 0, f"hook crashed: {stderr}"
    # heuristic BLOCK 仍應觸發（dedup 只壓 codex trigger，不影響 BLOCK）
    assert '"block"' in stdout, (
        "heuristic BLOCK should still fire even when dedup would skip codex trigger"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
