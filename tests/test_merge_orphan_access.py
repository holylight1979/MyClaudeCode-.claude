"""test_merge_orphan_access.py — 合併規則 + 冪等 + DELETE_UNCONDITIONAL 行為

涵蓋：
  - merge_access：max(read_hits/confirmations/last_used/last_promoted_at)
                  + min(first_seen) + timestamps 聯集去重取最新 50
                  + confirmation_events 時間排序聯集
  - _str_max / _str_min：None 處理
  - process_pair（dry-run）：merge / move / delete / skip 四種 action
  - 冪等：跑兩次 src 不存在 → 第二次 SKIP
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 載入帶連字號檔名的腳本
spec = importlib.util.spec_from_file_location(
    "merge_orphan_access", ROOT / "scripts" / "merge-orphan-access.py",
)
moa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(moa)


# ─── _str_max / _str_min ─────────────────────────────────────────────────────


def test_str_max_basic():
    assert moa._str_max("2026-04-01", "2026-05-01") == "2026-05-01"
    assert moa._str_max("2026-05-01", "2026-04-01") == "2026-05-01"


def test_str_max_none_handling():
    assert moa._str_max(None, "2026-05-01") == "2026-05-01"
    assert moa._str_max("2026-05-01", None) == "2026-05-01"
    assert moa._str_max(None, None) is None


def test_str_min_basic():
    assert moa._str_min("2026-04-01", "2026-05-01") == "2026-04-01"
    assert moa._str_min("2026-05-01", "2026-04-01") == "2026-04-01"


def test_str_min_none_treated_as_larger():
    assert moa._str_min(None, "2026-05-01") == "2026-05-01"
    assert moa._str_min("2026-04-01", None) == "2026-04-01"
    assert moa._str_min(None, None) is None


# ─── merge_access core rules ──────────────────────────────────────────────────


def _norm(d: Dict[str, Any]) -> Dict[str, Any]:
    """走 atom_access._normalize 補齊 default。"""
    from lib.atom_access import _normalize
    out, _ = _normalize(dict(d))
    return out


def test_merge_max_counters():
    src = _norm({"read_hits": 5, "confirmations": 2})
    dst = _norm({"read_hits": 10, "confirmations": 1})
    m = moa.merge_access(src, dst)
    assert m["read_hits"] == 10
    assert m["confirmations"] == 2


def test_merge_last_used_takes_newer():
    src = _norm({"last_used": "2026-04-15"})
    dst = _norm({"last_used": "2026-05-01"})
    assert moa.merge_access(src, dst)["last_used"] == "2026-05-01"


def test_merge_last_used_src_newer():
    src = _norm({"last_used": "2026-05-04"})
    dst = _norm({"last_used": "2026-04-01"})
    assert moa.merge_access(src, dst)["last_used"] == "2026-05-04"


def test_merge_first_seen_takes_older():
    src = _norm({"first_seen": "2026-01-15"})
    dst = _norm({"first_seen": "2026-03-20"})
    assert moa.merge_access(src, dst)["first_seen"] == "2026-01-15"


def test_merge_first_seen_none_loses():
    src = _norm({"first_seen": None})
    dst = _norm({"first_seen": "2026-03-20"})
    # None 視為較大 → 取 dst 的 2026-03-20
    assert moa.merge_access(src, dst)["first_seen"] == "2026-03-20"


def test_merge_timestamps_union_dedup_top50():
    # 同一 timestamp 在兩邊都有 → 去重；總數超 50 → 取最新 50
    overlap = [1700000000.0]
    src_ts = overlap + [float(1700000000 + i) for i in range(30)]
    dst_ts = overlap + [float(1700000100 + i) for i in range(30)]
    src = _norm({"timestamps": src_ts})
    dst = _norm({"timestamps": dst_ts})
    m = moa.merge_access(src, dst)
    # 期望去重後總數 = 30 + 30 (overlap 1 重 → 59 unique)，取最新 50
    assert len(m["timestamps"]) == 50
    # 應為單調遞增
    assert m["timestamps"] == sorted(m["timestamps"])
    # 最大值應是 dst 最後
    assert m["timestamps"][-1] == 1700000129.0


def test_merge_timestamps_under_50():
    src = _norm({"timestamps": [1.0, 2.0]})
    dst = _norm({"timestamps": [3.0, 4.0]})
    m = moa.merge_access(src, dst)
    assert m["timestamps"] == [1.0, 2.0, 3.0, 4.0]


def test_merge_legacy_src_no_schema():
    """src 是 pre-Wave-2 legacy 格式（只有 timestamps），dst 是 v2。"""
    src = _norm({"timestamps": [1700000000.0, 1700000001.0]})
    dst = _norm({
        "schema": "atom-access-v2",
        "read_hits": 10, "last_used": "2026-04-29",
        "timestamps": [1700000099.0],
    })
    m = moa.merge_access(src, dst)
    assert m["read_hits"] == 10
    assert m["last_used"] == "2026-04-29"
    assert m["timestamps"] == [1700000000.0, 1700000001.0, 1700000099.0]


def test_merge_confirmation_events_time_sorted_union():
    src_ev = [{"ts": "2026-04-10T00:00:00"}, {"ts": "2026-04-15T00:00:00"}]
    dst_ev = [{"ts": "2026-04-12T00:00:00"}]
    src = _norm({"confirmation_events": src_ev})
    dst = _norm({"confirmation_events": dst_ev})
    m = moa.merge_access(src, dst)
    out_ts = [e["ts"] for e in m["confirmation_events"]]
    assert out_ts == ["2026-04-10T00:00:00", "2026-04-12T00:00:00",
                      "2026-04-15T00:00:00"]


# ─── process_pair (dry-run only — no filesystem mutation) ─────────────────────


@pytest.fixture
def tmp_memory(tmp_path, monkeypatch):
    """把 scripts/merge-orphan-access.py 的 MEMORY_DIR 指向 tmp。"""
    mem = tmp_path / "memory"
    (mem / "feedback").mkdir(parents=True)
    monkeypatch.setattr(moa, "MEMORY_DIR", mem)
    return mem


def _write_json(p: Path, d: Dict[str, Any]) -> None:
    import json
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def test_process_pair_skip_when_src_missing(tmp_memory):
    s = moa.process_pair("missing.access.json", "feedback/x.access.json",
                         "misplaced", apply=False)
    assert s["action"] == "skip"
    assert "src missing" in s["reason"]


def test_process_pair_dry_run_merge(tmp_memory):
    src_path = tmp_memory / "feedback-x.access.json"
    dst_path = tmp_memory / "feedback" / "feedback-x.access.json"
    _write_json(src_path, {"timestamps": [1.0, 2.0]})
    _write_json(dst_path, {
        "schema": "atom-access-v2", "read_hits": 5, "timestamps": [3.0],
    })
    s = moa.process_pair("feedback-x.access.json",
                         "feedback/feedback-x.access.json",
                         "misplaced", apply=False)
    assert s["action"] == "merge"
    # dry-run 不改檔
    assert src_path.exists() and dst_path.exists()
    import json as _json
    assert _json.loads(dst_path.read_text())["read_hits"] == 5


def test_process_pair_dry_run_move_when_dst_absent(tmp_memory):
    src_path = tmp_memory / "feedback-y.access.json"
    _write_json(src_path, {"timestamps": [1.0]})
    s = moa.process_pair("feedback-y.access.json",
                         "feedback/feedback-y.access.json",
                         "rename", apply=False)
    assert s["action"] == "move"
    assert src_path.exists()
    assert not (tmp_memory / "feedback" / "feedback-y.access.json").exists()


def test_process_pair_dry_run_delete_unconditional(tmp_memory):
    src_path = tmp_memory / "mail-sorting.access.json"
    _write_json(src_path, {"timestamps": [1.0]})
    s = moa.process_pair("mail-sorting.access.json",
                         moa.DELETE_UNCONDITIONAL, "delete", apply=False)
    assert s["action"] == "delete"
    assert src_path.exists()  # dry-run 不刪


def test_idempotent_skip_when_src_already_gone(tmp_memory):
    """src 已不存在 → SKIP（模擬第二次 --apply 跑）。"""
    s = moa.process_pair("feedback-already-merged.access.json",
                         "feedback/feedback-already-merged.access.json",
                         "misplaced", apply=False)
    assert s["action"] == "skip"


# ─── MAPPING shape sanity ─────────────────────────────────────────────────────


def test_mapping_complete_10_entries():
    """10 entries: 5 misplaced + 4 rename + 1 delete."""
    assert len(moa.MAPPING) == 10
    kinds = [k for _, _, k in moa.MAPPING]
    assert kinds.count("misplaced") == 5
    assert kinds.count("rename") == 4
    assert kinds.count("delete") == 1


def test_mapping_delete_uses_sentinel():
    delete_entries = [(s, d, k) for s, d, k in moa.MAPPING if k == "delete"]
    assert len(delete_entries) == 1
    assert delete_entries[0][1] == moa.DELETE_UNCONDITIONAL
    assert delete_entries[0][0] == "mail-sorting.access.json"
