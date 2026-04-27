"""test_scorer.py — Sprint 3 scorer 五因子覆蓋測試。

Plan v5 Phase 3.1 完成標準：6 種典型 turn 預期分數覆蓋。
五因子：write_footprint(0-2) + verification_gap(0-3) + structural_risk(0-2)
       + completion_claim(0-2) + analysis_loop(0-1)，總分 cap 10。

設計原則：每一條 case 鎖定不同因子組合，確保因子之間沒有
silent 重疊或被遺漏。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

COMP_DIR = Path(__file__).resolve().parent.parent / "tools" / "codex-companion"
sys.path.insert(0, str(COMP_DIR))

import scorer  # noqa: E402


def _state(modified=None, trace=None, tail=""):
    return {
        "modified_files": [{"path": p} for p in (modified or [])],
        "tool_trace": trace or [],
        "last_assistant_tail": tail,
    }


# ─── 1. 純對話 turn（無寫入無宣告）→ 0 分 ───────────────────────────────


def test_pure_discussion_turn_scores_zero():
    """無 modified、無 Edit trace、無 completion claim → 全 0。"""
    st = _state(trace=[{"tool": "Read", "path": "a.py"}], tail="這個架構我建議改 X 而不是 Y。")
    assert scorer.compute_turn_score(st) == 0


# ─── 2. 改 1 檔但跑了 pytest 並宣告完成 → 低分（驗證齊備）─────────────


def test_small_edit_with_verification_and_claim_low_score():
    """1 檔 edit + pytest + 完成宣告 → write(1) + gap(0) + struct(0) + claim(2) + loop(0) = 3。
    低於 threshold=4 應跳過 codex。
    """
    trace = [
        {"tool": "Edit", "path": "a.py"},
        {"tool": "Bash", "input": "pytest tests/"},
    ]
    st = _state(modified=["a.py"], trace=trace, tail="完成。")
    score = scorer.compute_turn_score(st)
    assert score == 3, f"expected 3 (write=1, gap=0, claim=2), got {score}"


# ─── 3. 改 1 檔宣告完成但無驗證 → 高分 BLOCK 級 ────────────────────────


def test_small_edit_claim_no_verification_high_score():
    """1 檔 edit + 完成宣告 + 無 verify → write(1) + gap(3) + struct(0) + claim(2) + loop(0) = 6。"""
    trace = [{"tool": "Edit", "path": "a.py"}]
    st = _state(modified=["a.py"], trace=trace, tail="搞定，全部完成。")
    score = scorer.compute_turn_score(st)
    assert score == 6, f"expected 6 (write=1, gap=3, claim=2), got {score}"


# ─── 4. 大改架構檔無驗證無宣告 → 中高分（結構 + gap）────────────────


def test_large_arch_change_no_verify_mid_high():
    """5 檔 edit（含 2 結構）+ 無 verify + 無 claim → write(2) + gap(3) + struct(1) + claim(0) = 6。"""
    modified = [
        "src/payment_provider.py",
        "src/api_service.py",
        "src/utils.py",
        "src/main.py",
        "src/helper.py",
    ]
    trace = [{"tool": "Edit", "path": p} for p in modified]
    st = _state(modified=modified, trace=trace, tail="持續調整中…")
    score = scorer.compute_turn_score(st)
    assert score == 6, f"expected 6 (write=2, gap=3, struct=1), got {score}"


# ─── 5. 弱證據敘述（tail 含 pytest 通過但 trace 沒 Bash）→ 中分 ─────


def test_weak_narrative_evidence_mid_score():
    """1 檔 edit + tail 含「pytest 10/10 通過」+ 完成宣告 →
    write(1) + gap(1 弱證據) + struct(0) + claim(2) + loop(0) = 4。
    剛好 = threshold 應該觸發 codex。
    """
    trace = [{"tool": "Edit", "path": "a.py"}]
    st = _state(
        modified=["a.py"],
        trace=trace,
        tail="完成。pytest 10/10 通過，已 push。",
    )
    score = scorer.compute_turn_score(st)
    assert score == 4, f"expected 4 (write=1, gap=1 weak, claim=2), got {score}"


# ─── 6. analysis loop（反覆讀同一檔不 edit）→ loop 因子 = 1 ──────────


def test_analysis_loop_adds_one():
    """無寫入但反覆讀同檔 → write(0) + gap(0) + struct(0) + claim(0) + loop(1) = 1。"""
    trace = [
        {"tool": "Read", "path": "x.py"},
        {"tool": "Read", "path": "x.py"},
        {"tool": "Read", "path": "x.py"},
        {"tool": "Read", "path": "x.py"},
    ]
    st = _state(trace=trace, tail="還在分析…")
    score = scorer.compute_turn_score(st)
    assert score == 1, f"expected 1 (loop only), got {score}"


# ─── 邊界：score cap 10 ────────────────────────────────────────────────


def test_score_caps_at_ten():
    """全因子最大化 → cap 10。
    檔名須以 (bridge|provider|adapter|...)\\.(py|ts|...)$ 結尾才命中
    _ARCH_FILE_RE，所以用 payment_provider.py / api_service.py 等。
    """
    modified = [
        "src/payment_provider.py",
        "src/auth_provider.py",
        "src/api_service.py",
        "src/cache_service.py",
        "src/db_adapter.py",
    ]
    trace = (
        [{"tool": "Edit", "path": p} for p in modified]
        + [{"tool": "Read", "path": "x.py"}] * 4  # loop +1
    )
    st = _state(modified=modified, trace=trace, tail="全部完成。")
    score = scorer.compute_turn_score(st)
    # write(2) + gap(3) + struct(2) + claim(2) + loop(1) = 10
    assert score == 10, f"expected cap 10, got {score}"


# ─── explain_score 結構驗證 ──────────────────────────────────────────


def test_explain_score_returns_breakdown():
    trace = [{"tool": "Edit", "path": "a.py"}]
    st = _state(modified=["a.py"], trace=trace, tail="完成")
    out = scorer.explain_score(st)
    assert "total" in out and "factors" in out and "modified_paths" in out
    assert set(out["factors"].keys()) == {
        "write_footprint",
        "verification_gap",
        "structural_risk",
        "completion_claim",
        "analysis_loop",
    }
    assert out["total"] == sum(out["factors"].values())
    assert out["modified_paths"] == ["a.py"]


# ─── stop_text fallback 從 state["last_assistant_tail"] 讀 ────────────


def test_stop_text_falls_back_to_state_tail():
    """compute_turn_score 不傳 stop_text 時應從 state['last_assistant_tail'] 取。"""
    trace = [{"tool": "Edit", "path": "a.py"}]
    st = _state(modified=["a.py"], trace=trace, tail="完成")  # tail 觸發 claim
    score_implicit = scorer.compute_turn_score(st)
    score_explicit = scorer.compute_turn_score(st, stop_text="完成")
    assert score_implicit == score_explicit


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
