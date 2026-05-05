"""test_migrate_access_stats.py — 一次性遷移腳本邏輯測試

涵蓋：
  - parse_md_counters：13 種 atom .md 樣本（含缺欄、含全欄、legacy 格式）
  - merge_with_max：max 取較大、日期取較新／較舊
  - strip_md_counters：嚴格行首錨定，知識欄不誤傷
  - already_migrated：冪等判斷
  - add_missing_confidence：缺欄補預設
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 直接 import 腳本（scripts/migrate-access-stats.py 含連字號，需手動載入）
import importlib.util
spec = importlib.util.spec_from_file_location(
    "migrate_access_stats", ROOT / "scripts" / "migrate-access-stats.py",
)
mas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mas)


# ─── parse_md_counters ───────────────────────────────────────────────────────


def test_parse_full_atom():
    text = """# Some Atom

- Scope: global
- Confidence: [固]
- Trigger: foo, bar
- Last-used: 2026-05-01
- Confirmations: 7
- ReadHits: 42
- Created: 2026-01-15

## 知識
"""
    out = mas.parse_md_counters(text)
    assert out["read_hits"] == 42
    assert out["confirmations"] == 7
    assert out["last_used"] == "2026-05-01"
    assert out["first_seen"] == "2026-01-15"
    assert out["confidence"] == "[固]"


def test_parse_missing_counters():
    text = """# Empty
- Scope: global
- Confidence: [臨]
- Trigger: x
"""
    out = mas.parse_md_counters(text)
    assert "read_hits" not in out
    assert "confirmations" not in out
    assert "last_used" not in out
    assert out["confidence"] == "[臨]"


def test_parse_zero_counters():
    text = """# Zero
- Confidence: [臨]
- ReadHits: 0
- Confirmations: 0
- Last-used: 2026-04-01
"""
    out = mas.parse_md_counters(text)
    assert out["read_hits"] == 0
    assert out["confirmations"] == 0
    assert out["last_used"] == "2026-04-01"


def test_parse_created_at_alias():
    text = """# T
- Confidence: [臨]
- Created-at: 2026-03-10
"""
    out = mas.parse_md_counters(text)
    assert out["first_seen"] == "2026-03-10"


# ─── merge_with_max ─────────────────────────────────────────────────────────


def test_merge_max_int():
    access = {"read_hits": 5, "confirmations": 2}
    md = {"read_hits": 10, "confirmations": 1}
    out = mas.merge_with_max(access, md)
    assert out["read_hits"] == 10  # md 較大
    assert out["confirmations"] == 2  # access 較大


def test_merge_last_used_newer():
    access = {"last_used": "2026-04-01"}
    md = {"last_used": "2026-05-01"}
    out = mas.merge_with_max(access, md)
    assert out["last_used"] == "2026-05-01"


def test_merge_first_seen_older():
    access = {"first_seen": "2026-03-01"}
    md = {"first_seen": "2026-01-15"}
    out = mas.merge_with_max(access, md)
    assert out["first_seen"] == "2026-01-15"


def test_merge_empty_access():
    out = mas.merge_with_max({}, {"read_hits": 3})
    assert out["read_hits"] == 3


# ─── strip_md_counters ─────────────────────────────────────────────────────


def test_strip_removes_counter_lines():
    text = """# A
- Scope: global
- Confidence: [固]
- Trigger: x
- Last-used: 2026-05-01
- Confirmations: 5
- ReadHits: 20
- Created: 2026-01-01

## 知識
- 知識內容
"""
    out = mas.strip_md_counters(text)
    assert "Last-used" not in out
    assert "Confirmations" not in out
    assert "ReadHits" not in out
    # 保留
    assert "- Scope: global" in out
    assert "- Confidence: [固]" in out
    assert "- Trigger: x" in out
    assert "- Created: 2026-01-01" in out
    assert "## 知識" in out


def test_strip_preserves_knowledge_lines_with_keywords():
    """知識行如果包含「ReadHits」字串本身（非 frontmatter），不誤傷。"""
    text = """# A
- Confidence: [固]
- ReadHits: 5
- Last-used: 2026-05-01

## 知識
- 文件提到 ReadHits 是 atom 計數欄
- Last-used 是時間戳記
- 計數類欄位（Confirmations）已搬至 access.json
"""
    out = mas.strip_md_counters(text)
    # frontmatter 欄被剝
    assert "- ReadHits: 5" not in out
    assert "- Last-used: 2026-05-01" not in out
    # 知識行保留（即使含關鍵詞）
    assert "文件提到 ReadHits 是" in out
    assert "Last-used 是時間戳記" in out
    assert "計數類欄位（Confirmations）" in out


# ─── already_migrated ──────────────────────────────────────────────────────


def test_already_migrated_clean():
    access = {"schema": "atom-access-v2"}
    md = "# A\n- Confidence: [臨]\n## 知識\n"
    assert mas.already_migrated(access, md) is True


def test_not_migrated_old_schema():
    access = {"schema": "atom-access-v1"}
    md = "# A\n- Confidence: [臨]\n"
    assert mas.already_migrated(access, md) is False


def test_not_migrated_md_still_has_counters():
    access = {"schema": "atom-access-v2"}
    md = "# A\n- Confidence: [臨]\n- ReadHits: 5\n"
    assert mas.already_migrated(access, md) is False


# ─── add_missing_confidence ────────────────────────────────────────────────


def test_add_missing_confidence_inserts():
    text = """# A
- Scope: global
- Trigger: x

## 知識
"""
    out, added = mas.add_missing_confidence(text)
    assert added is True
    assert "- Confidence: [臨]" in out
    # 應插在 Trigger 之後
    assert out.index("- Confidence:") > out.index("- Trigger:")


def test_add_missing_confidence_already_present():
    text = "# A\n- Confidence: [固]\n- Trigger: x\n"
    out, added = mas.add_missing_confidence(text)
    assert added is False
    assert out == text


# ─── normalize_legacy ──────────────────────────────────────────────────────


def test_normalize_legacy_array_confirmations():
    data = {"timestamps": [1.0], "confirmations": [{"x": 1}, {"x": 2}]}
    out, upgraded = mas.normalize_legacy(data)
    assert upgraded is True
    assert out["confirmations"] == 2
    assert out["confirmation_events"] == [{"x": 1}, {"x": 2}]


def test_normalize_legacy_int_confirmations():
    data = {"confirmations": 5}
    out, upgraded = mas.normalize_legacy(data)
    assert upgraded is False
    assert out["confirmations"] == 5
