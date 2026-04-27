"""test_phase6_trigger.py — Sprint 5.5 B2 單測。

涵蓋 wg_codex_companion_phase6.py 三大行為：
  1. 條件 matcher：C1-C5 各自的 met / not-met 邊界
  2. trigger / no-trigger：fixture 餵不同 sessions[] 形狀，驗 inject 字串
  3. dedup：同條件不重複觸發；條件 drop 後再 met 應重觸發

不啟動 Workflow Guardian 子程序，只測 hook 模組函式 + 透過 monkeypatch 改
REFLECTION_PATH 與 WORKFLOW_DIR 指向 tmp_path，避免污染真實環境。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

CLAUDE_DIR = Path.home() / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import wg_codex_companion_phase6 as p6  # noqa: E402


# ─── Fixture 工具 ────────────────────────────────────────────────────


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    """把 REFLECTION_PATH 與 WORKFLOW_DIR 重指到 tmp，避免污染。"""
    refl = tmp_path / "reflection_metrics.json"
    workflow = tmp_path / "workflow"
    workflow.mkdir()

    monkeypatch.setattr(p6, "REFLECTION_PATH", refl)
    monkeypatch.setattr(p6, "WORKFLOW_DIR", workflow)
    return refl, workflow


def _write_reflection(refl_path: Path, codex_companion_block: dict):
    refl_path.write_text(
        json.dumps({"codex_companion": codex_companion_block}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _make_session(**kwargs) -> dict:
    """產生一個 codex_companion session 紀錄。預設全 zero。"""
    base = {
        "session_id": "fake",
        "ts": "2026-04-28T01:00:00+00:00",
        "audits_skipped_by_score": 0,
        "audits_total_attempted": 0,
        "empty_returns": 0,
        "sandbox_failures": 0,
        "behavior_gap_blocks": 0,
        "quality_gap_advises": 0,
    }
    base.update(kwargs)
    return base


# ─── 條件 matcher：每條 C 的邊界 ──────────────────────────────────────


def test_eval_c1_threshold_at_10(tmp_env):
    """C1: len(S) >= 10。9 筆未達、10 筆達。"""
    sessions_9 = [_make_session() for _ in range(9)]
    sessions_10 = [_make_session() for _ in range(10)]

    r9 = p6._eval_conditions(sessions_9, [])
    r10 = p6._eval_conditions(sessions_10, [])
    assert r9["C1"][0] is False
    assert r10["C1"][0] is True


def test_eval_c2_any_sandbox_failure(tmp_env):
    """C2: any sandbox_failures > 0。一筆即觸發。"""
    sessions = [_make_session(), _make_session(sandbox_failures=1)]
    r = p6._eval_conditions(sessions, [])
    assert r["C2"][0] is True


def test_eval_c2_no_sandbox_failure(tmp_env):
    sessions = [_make_session() for _ in range(5)]
    r = p6._eval_conditions(sessions, [])
    assert r["C2"][0] is False


def test_eval_c3_ratio_threshold(tmp_env):
    """C3: skipped/max(1,attempted) > 0.7。0.71 應觸發、0.5 不觸發。"""
    # 71/100 = 0.71 → 觸發
    sessions_hit = [_make_session(audits_skipped_by_score=71, audits_total_attempted=100)]
    # 50/100 = 0.5 → 不觸發
    sessions_miss = [_make_session(audits_skipped_by_score=50, audits_total_attempted=100)]

    r_hit = p6._eval_conditions(sessions_hit, [])
    r_miss = p6._eval_conditions(sessions_miss, [])
    assert r_hit["C3"][0] is True
    assert r_miss["C3"][0] is False


def test_eval_c3_zero_attempted_safe(tmp_env):
    """C3 分母 attempted=0 時 max(1,0)=1，避免 div-by-zero；ratio = skipped。
    skipped=1 → ratio=1.0 > 0.7 → 觸發（這也是為何 C3 需要 attempted 鍵 — 否則在
    觀察初期會因為「skipped=1, attempted=0」誤觸）。
    """
    sessions = [_make_session(audits_skipped_by_score=1, audits_total_attempted=0)]
    r = p6._eval_conditions(sessions, [])
    assert r["C3"][0] is True, "early observation 期會誤觸是已知行為，需 B1 補 attempted"


def test_eval_c4_requires_5_sessions_all_blocks_zero_any_advise(tmp_env):
    """C4: len>=5 + last 5 全 blocks=0 + 任一 advise>0。"""
    # 5 筆 + 全 blocks=0 + 有 advise → 觸發
    sessions = [_make_session(quality_gap_advises=1)] + [_make_session() for _ in range(4)]
    r = p6._eval_conditions(sessions, [])
    assert r["C4"][0] is True

    # 4 筆 → 樣本不足
    r4 = p6._eval_conditions(sessions[:4], [])
    assert r4["C4"][0] is False

    # 5 筆但有 block → 不觸發
    sessions_with_block = (
        [_make_session(quality_gap_advises=1)]
        + [_make_session() for _ in range(3)]
        + [_make_session(behavior_gap_blocks=1)]
    )
    r_blocked = p6._eval_conditions(sessions_with_block, [])
    assert r_blocked["C4"][0] is False


def test_eval_c5_assessment_glob_threshold(tmp_env):
    """C5: len(A)>=20 + injected_ratio<0.3。"""
    refl, wf = tmp_env

    # < 20 → 樣本不足
    for i in range(15):
        (wf / f"companion-assessment-uuid-real-t{i}-turn_audit.json").write_text(
            json.dumps({"injected": False}), encoding="utf-8"
        )
    r_few = p6._eval_conditions([], p6._glob_real_assessments())
    assert r_few["C5"][0] is False

    # 補到 20 + 全 not-injected → ratio=0.0<0.3 → 觸發
    for i in range(15, 20):
        (wf / f"companion-assessment-uuid-real-t{i}-turn_audit.json").write_text(
            json.dumps({"injected": False}), encoding="utf-8"
        )
    r_hit = p6._eval_conditions([], p6._glob_real_assessments())
    assert r_hit["C5"][0] is True

    # 20 個全 injected → ratio=1.0 → 不觸發
    for i in range(20):
        (wf / f"companion-assessment-uuid-real-t{i}-turn_audit.json").write_text(
            json.dumps({"injected": True}), encoding="utf-8"
        )
    r_all_injected = p6._eval_conditions([], p6._glob_real_assessments())
    assert r_all_injected["C5"][0] is False


def test_glob_filters_test_fixtures(tmp_env):
    """real session 用 UUID 形式不應被過濾；test-sprint* 應被過濾。"""
    _, wf = tmp_env
    (wf / "companion-assessment-test-sprint3-abc-t1-turn_audit.json").write_text("{}")
    (wf / "companion-assessment-smoke-t1-turn_audit.json").write_text("{}")
    (wf / "companion-assessment-b0b4f9e6-27df-403f-a709-7cf2d4d56344-t1-turn_audit.json").write_text("{}")

    paths = p6._glob_real_assessments()
    names = [p.name for p in paths]
    assert any("b0b4f9e6" in n for n in names)
    assert not any("test-sprint" in n for n in names)
    assert not any("smoke" in n for n in names)


# ─── trigger / no-trigger / dedup ─────────────────────────────────────


def test_inject_returns_none_when_no_condition_met(tmp_env):
    """全 zero session → 全條件 not met → 返回 None，不打擾 user。"""
    refl, _ = tmp_env
    _write_reflection(refl, {"sessions": [_make_session() for _ in range(3)]})
    assert p6.get_session_start_inject() is None


def test_inject_returns_string_when_c2_meets(tmp_env):
    """單一 sandbox_failures=1 即觸發 C2。"""
    refl, _ = tmp_env
    _write_reflection(refl, {"sessions": [_make_session(sandbox_failures=1)]})

    inject = p6.get_session_start_inject()
    assert inject is not None
    assert "[Phase6Trigger]" in inject
    assert "C2" in inject
    assert "sandbox_failures" in inject


def test_dedup_same_condition_does_not_refire_consecutively(tmp_env):
    """同條件第一次觸發後、第二次（相同 sessions）應不重觸發。"""
    refl, _ = tmp_env
    _write_reflection(refl, {"sessions": [_make_session(sandbox_failures=1)]})

    first = p6.get_session_start_inject()
    second = p6.get_session_start_inject()  # 相同數據再跑

    assert first is not None and "C2" in first
    assert second is None, "dedup 應壓住二次同樣觸發，避免每次 SessionStart 都嗶"


def test_condition_drops_then_remeets_refires(tmp_env):
    """條件 drop（sandbox_failures 變 0）後再 met 應重觸發。"""
    refl, _ = tmp_env

    # 第一輪：C2 met
    _write_reflection(refl, {"sessions": [_make_session(sandbox_failures=1)]})
    first = p6.get_session_start_inject()
    assert first is not None and "C2" in first

    # 第二輪：sandbox 已修，all zero
    _write_reflection(refl, {
        "sessions": [_make_session(sandbox_failures=1)],
        "phase6_trigger_state": json.loads(refl.read_text(encoding="utf-8"))
            ["codex_companion"]["phase6_trigger_state"],
    })
    # 重寫整份；sandbox=0 模擬問題已修
    data = json.loads(refl.read_text(encoding="utf-8"))
    data["codex_companion"]["sessions"] = [_make_session()]  # all zero
    refl.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    second = p6.get_session_start_inject()
    assert second is None, "問題已修、條件不再 met → 不觸發"

    # 第三輪：又出現 sandbox_failures → 應重觸發
    data = json.loads(refl.read_text(encoding="utf-8"))
    data["codex_companion"]["sessions"] = [_make_session(sandbox_failures=2)]
    refl.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    third = p6.get_session_start_inject()
    assert third is not None and "C2" in third, "drop 後再 met 應重觸發"


def test_dedup_state_written_back_to_reflection(tmp_env):
    """副作用：phase6_trigger_state 應寫回 reflection_metrics.json。"""
    refl, _ = tmp_env
    _write_reflection(refl, {"sessions": [_make_session(sandbox_failures=1)]})

    p6.get_session_start_inject()
    data = json.loads(refl.read_text(encoding="utf-8"))
    state = data["codex_companion"]["phase6_trigger_state"]
    assert "C2" in state["last_fired"]
    assert state["last_check_S_count"] == 1
    assert state["last_trigger_ts"]


def test_reflection_file_missing_skips_gracefully(tmp_env):
    """reflection_metrics.json 不存在 → 不主動建檔、不 crash、返回 None。"""
    refl, _ = tmp_env
    # 不寫 refl
    assert not refl.exists()
    result = p6.get_session_start_inject()
    assert result is None
    # 不應被建立（避免污染真實環境）
    assert not refl.exists()


def test_multiple_conditions_reported_in_single_inject(tmp_env):
    """C2 + C3 同時 met → 一次 inject 列兩條。"""
    refl, _ = tmp_env
    sessions = [
        _make_session(sandbox_failures=1, audits_skipped_by_score=80, audits_total_attempted=10),
    ]
    _write_reflection(refl, {"sessions": sessions})

    inject = p6.get_session_start_inject()
    assert inject is not None
    assert "C2" in inject and "C3" in inject


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
