"""test_metric_audits_total.py — Sprint 5.5 B1 單測。

驗證 audits_total_attempted（Phase 6 §四 C3 條件分母）：
  1. _METRIC_KEYS 白名單包含此鍵
  2. increment_metric 累加正確、預設 0
  3. read_metrics 回傳 dict 含此鍵
  4. C3 ratio 公式（pseudo-code）在新鍵存在時為可計算（非 0/0）

不啟動 service / 不呼叫 hook 子程序，只測 state.py API 與 _METRIC_KEYS schema。
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

CLAUDE_DIR = Path.home() / ".claude"
COMPANION_DIR = CLAUDE_DIR / "tools" / "codex-companion"
sys.path.insert(0, str(COMPANION_DIR))

import state as companion_state  # noqa: E402


@pytest.fixture
def cleanup_session(tmp_path, monkeypatch):
    """Isolate test metrics file to tmp_path（避免與系統 hook 子程序對 ~/.claude/workflow/
    並發 fs I/O，導致偶發 metric 計數錯亂）。"""
    monkeypatch.setattr(companion_state, "WORKFLOW_DIR", tmp_path)
    sid = f"test-sprint5_5-{uuid.uuid4().hex[:8]}"
    yield sid
    p = companion_state._metrics_path(sid)
    if p.exists():
        p.unlink()


def test_audits_total_attempted_in_white_list():
    """Sprint 5.5 B1：新鍵必須在白名單，否則 increment_metric 會 silent drop。"""
    assert "audits_total_attempted" in companion_state._METRIC_KEYS, (
        "audits_total_attempted 必須在 _METRIC_KEYS 白名單中"
    )


def test_increment_audits_total_attempted_persists(cleanup_session):
    """increment_metric 三次後 read_metrics 應回 3。"""
    sid = cleanup_session
    for _ in range(3):
        companion_state.increment_metric(sid, "audits_total_attempted")

    metrics = companion_state.read_metrics(sid)
    assert metrics["audits_total_attempted"] == 3, (
        f"expected 3, got {metrics}"
    )


def test_read_metrics_includes_audits_total_attempted_default_zero(cleanup_session):
    """新 session 沒任何累加 → read_metrics 應含此鍵，值為 0。"""
    sid = cleanup_session
    metrics = companion_state.read_metrics(sid)
    assert "audits_total_attempted" in metrics
    assert metrics["audits_total_attempted"] == 0


def test_c3_ratio_is_computable_with_new_key(cleanup_session):
    """Phase 6 §四 C3 條件 pseudo-code 在新鍵存在時可正常算出 ratio，
    不再永遠是 0/max(1,0) = 0 的死條件。
    """
    sid = cleanup_session
    # 模擬 8 turns 中 6 次 score gate skip、2 次實際 trigger
    for _ in range(6):
        companion_state.increment_metric(sid, "audits_skipped_by_score")
    for _ in range(2):
        companion_state.increment_metric(sid, "audits_total_attempted")

    metrics = companion_state.read_metrics(sid)
    skipped = metrics["audits_skipped_by_score"]
    total = metrics["audits_total_attempted"]
    ratio = skipped / max(1, total)
    # 6 / max(1, 2) = 3.0 — Phase 6 C3 閾值 0.7，此值會觸發
    assert ratio == 3.0, f"expected ratio 3.0, got {ratio}"
    assert ratio > 0.7, "C3 條件應被觸發"


def test_unknown_metric_key_silently_dropped(cleanup_session):
    """白名單外的鍵應被 silent drop，不污染 metrics 檔。"""
    sid = cleanup_session
    companion_state.increment_metric(sid, "audits_total_attempted")
    companion_state.increment_metric(sid, "not_a_real_metric")  # should be ignored

    path = companion_state._metrics_path(sid)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "not_a_real_metric" not in data, (
            f"白名單外的鍵不應被寫入：{data}"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
