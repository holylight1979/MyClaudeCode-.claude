"""test_atom_health_audit.py — Atom 體質審視工具邏輯測試（Wave 3）

驗證 classify() 7 種分類規則與 add_missing_confidence。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "atom_health_audit", ROOT / "tools" / "atom-health-audit.py",
)
aha = importlib.util.module_from_spec(spec)
sys.modules["atom_health_audit"] = aha  # 必先註冊；@dataclass 需從 sys.modules 取 module dict
spec.loader.exec_module(aha)


def make_atom(**kw):
    """便利函式 — 建一個 AtomHealth 實例供 classify 用。"""
    defaults = dict(
        md_path=Path("/fake/atom.md"),
        rel_path="atom.md",
        confidence="[臨]",
        trigger="x, y",
        atom_type="",
        is_episodic=False,
        read_hits=0,
        confirmations=0,
        last_used=None,
        first_seen=None,
    )
    defaults.update(kw)
    return aha.AtomHealth(**defaults)


def days_ago_iso(days: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()


# ─── 分類規則 ────────────────────────────────────────────────────────────────


def test_episodic_ttl_archive():
    a = make_atom(is_episodic=True, last_used=days_ago_iso(30))
    aha.classify(a)
    assert a.category == "歸檔候選（episodic 過期）"
    assert a.suggested_action == "git_mv_to_distant_episodic"


def test_episodic_within_ttl():
    a = make_atom(is_episodic=True, last_used=days_ago_iso(10),
                  first_seen=days_ago_iso(10))
    aha.classify(a)
    # episodic 內、未到 TTL，read_hits=0、first_seen 10 天 → trigger 補強
    assert a.category == "trigger 補強候選"


def test_missing_confidence():
    a = make_atom(confidence=None, first_seen=days_ago_iso(5))
    aha.classify(a)
    assert a.category == "缺欄補齊"
    assert a.suggested_action == "add_confidence_temp"


def test_promote_temp_to_obs_via_confirmations():
    a = make_atom(confidence="[臨]", confirmations=5)
    aha.classify(a)
    assert a.category == "晉升候選 [臨]→[觀]"


def test_promote_temp_to_obs_via_readhits():
    a = make_atom(confidence="[臨]", read_hits=25)
    aha.classify(a)
    assert a.category == "晉升候選 [臨]→[觀]"


def test_promote_obs_to_fix_via_confirmations():
    a = make_atom(confidence="[觀]", confirmations=15)
    aha.classify(a)
    assert a.category == "晉升候選 [觀]→[固]"


def test_promote_obs_to_fix_via_readhits():
    a = make_atom(confidence="[觀]", read_hits=60)
    aha.classify(a)
    assert a.category == "晉升候選 [觀]→[固]"


def test_obs_below_threshold_kept():
    a = make_atom(confidence="[觀]", confirmations=5, read_hits=10)
    aha.classify(a)
    assert a.category == "保留"


def test_cold_archive():
    a = make_atom(confidence="[臨]", read_hits=0,
                  first_seen=days_ago_iso(60))
    aha.classify(a)
    assert a.category == "冷凍候選"
    assert a.suggested_action == "git_mv_to_distant_cold"


def test_recent_unhit_trigger_review():
    a = make_atom(confidence="[臨]", read_hits=0,
                  first_seen=days_ago_iso(5))
    aha.classify(a)
    assert a.category == "trigger 補強候選"
    assert a.suggested_action == "review_trigger"


def test_keep_normal_atom():
    a = make_atom(confidence="[觀]", read_hits=15, confirmations=2,
                  first_seen=days_ago_iso(60))
    aha.classify(a)
    assert a.category == "保留"


def test_fixed_confidence_below_promotion_kept():
    a = make_atom(confidence="[固]", read_hits=100, confirmations=20,
                  first_seen=days_ago_iso(60))
    aha.classify(a)
    # [固] 是頂級，不再升 → 保留
    assert a.category == "保留"


# ─── add_missing_confidence ─────────────────────────────────────────────────


def test_add_missing_confidence_writes(tmp_path):
    p = tmp_path / "atom.md"
    p.write_text("""# A
- Scope: global
- Trigger: x, y

## 知識
""", encoding="utf-8")
    assert aha.add_missing_confidence(p) is True
    text = p.read_text(encoding="utf-8")
    assert "- Confidence: [臨]" in text
    # 應插在 Trigger 後
    assert text.index("- Confidence:") > text.index("- Trigger:")


def test_add_missing_confidence_skips_existing(tmp_path):
    p = tmp_path / "atom.md"
    p.write_text("""# A
- Scope: global
- Confidence: [固]
- Trigger: x

## 知識
""", encoding="utf-8")
    assert aha.add_missing_confidence(p) is False


def test_add_missing_confidence_skips_no_trigger(tmp_path):
    p = tmp_path / "atom.md"
    p.write_text("# A\n\n## 知識\n", encoding="utf-8")
    assert aha.add_missing_confidence(p) is False
