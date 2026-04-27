"""test_codex_companion_stop_e2e.py — Sprint 2 e2e：Stop hook BLOCK 路徑驗證。

兩個場景：
  1. 「宣稱完成 + 改 1 檔 + 沒驗證」 → Stop hook 應 BLOCK（confident_completion 三條件齊備）
  2. 「改架構檔但沒宣稱完成」     → Stop hook 不應 BLOCK（缺 has_claim，arch 規則只 advisory）

採子程序方式呼叫 codex_companion.py，pipe Stop event JSON 到 stdin，
檢查 stdout 是否含 `"decision": "block"`。
HTTP 呼叫在 service 未起時會 silent timeout，不影響本測試。
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


def _setup_state_files(session_id: str, modified: list[str], trace: list[dict]) -> tuple[Path, Path]:
    """建 guardian state + companion state 兩檔。"""
    guardian_path = WORKFLOW_DIR / f"state-{session_id}.json"
    companion_path = WORKFLOW_DIR / f"companion-state-{session_id}.json"

    guardian_path.write_text(
        json.dumps({
            "modified_files": [{"path": p} for p in modified],
            "accessed_files": [],
            "user_goal_hint": "",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    companion_path.write_text(
        json.dumps({
            "tool_trace": trace,
            "turn_index": 1,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return guardian_path, companion_path


def _run_hook(input_data: dict) -> tuple[str, str, int]:
    """Pipe input JSON to codex_companion.py and return (stdout, stderr, returncode)."""
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
    """Yield a session_id and cleanup state files after test."""
    sid = f"test-sprint2-{uuid.uuid4().hex[:8]}"
    yield sid
    for pat in (
        f"state-{sid}.json",
        f"companion-state-{sid}.json",
    ):
        p = WORKFLOW_DIR / pat
        if p.exists():
            p.unlink()
    for p in WORKFLOW_DIR.glob(f"companion-assessment-{sid}-*.json"):
        p.unlink()


@pytest.mark.skipif(not HOOK_SCRIPT.exists(), reason="codex_companion.py not present")
def test_stop_hook_blocks_on_confident_completion_without_evidence(cleanup_session):
    """場景 1：宣稱完成 + 改 1 檔 + 無驗證 → BLOCK。"""
    sid = cleanup_session
    _setup_state_files(
        sid,
        modified=["a.py"],
        trace=[{"tool": "Edit", "path": "a.py"}],
    )

    stdout, stderr, rc = _run_hook({
        "hook_event_name": "Stop",
        "session_id": sid,
        "last_assistant_message": "搞定了，全部完成。",
    })

    assert rc == 0, f"hook crashed: {stderr}"
    # block decision JSON 應出現在 stdout
    assert '"decision"' in stdout and '"block"' in stdout, (
        f"expected BLOCK output, got stdout={stdout!r} stderr={stderr!r}"
    )
    parsed = json.loads(stdout.strip().splitlines()[-1])
    assert parsed.get("decision") == "block"
    assert "confident_completion_without_evidence" in parsed.get("reason", "")


@pytest.mark.skipif(not HOOK_SCRIPT.exists(), reason="codex_companion.py not present")
def test_stop_hook_does_not_block_on_arch_change_without_claim(cleanup_session):
    """場景 2：改架構檔但沒宣稱完成 → 不 BLOCK（advisory only）。"""
    sid = cleanup_session
    _setup_state_files(
        sid,
        modified=["src/payment_provider.py", "src/api_service.py"],
        trace=[{"tool": "Edit", "path": "src/payment_provider.py"}],
    )

    stdout, stderr, rc = _run_hook({
        "hook_event_name": "Stop",
        "session_id": sid,
        "last_assistant_message": "Still working on the provider integration; need more analysis.",
    })

    assert rc == 0, f"hook crashed: {stderr}"
    assert '"block"' not in stdout, (
        f"unexpected BLOCK; arch change without claim should be advisory. stdout={stdout!r}"
    )


@pytest.mark.skipif(not HOOK_SCRIPT.exists(), reason="codex_companion.py not present")
def test_stop_hook_does_not_block_when_tail_has_verify_narrative(cleanup_session):
    """Sprint 1 教訓 e2e：trace 為空但 tail 含「pytest 通過」→ 不 BLOCK。"""
    sid = cleanup_session
    _setup_state_files(
        sid,
        modified=["a.py", "b.py"],
        trace=[],  # trace 被擾動清空（模擬 Sprint 1 收尾踩坑情境）
    )

    stdout, stderr, rc = _run_hook({
        "hook_event_name": "Stop",
        "session_id": sid,
        "last_assistant_message": "Sprint 1 完成。pytest 10/10 通過、e2e smoke 已跑、commit 已 push。",
    })

    assert rc == 0, f"hook crashed: {stderr}"
    assert '"block"' not in stdout, (
        "Sprint 1 教訓 case 不應 BLOCK：tail 已有實證據敘述。"
        f"\nstdout={stdout!r}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
