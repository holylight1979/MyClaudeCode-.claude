#!/usr/bin/env python3
"""
test_wisdom_migration.py — V2.11 → V2.12 schema migration

驗證：
  1. V2.11 cumulative {correct, total} 搬到 legacy_cumulative.first_approach_accuracy
  2. V2.11 over_engineering_rate {user_reverted_or_simplified, total_suggestions} 搬遷
  3. V2.11 silence_accuracy {held_back_ok, held_back_missed} 搬遷
  4. schema_version="2.12" + window_size=10 落地
  5. 已是 V2.12 的檔案不再變動（idempotent）
  6. 空檔 / 不存在檔案 → 直接給 V2.12 schema
  7. arch_sensitivity_elevated 保留不重置
"""

import json
import sys
from pathlib import Path

import pytest

_HOOKS_DIR = Path.home() / ".claude" / "hooks"
sys.path.insert(0, str(_HOOKS_DIR))

import wisdom_engine as we  # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_reflection(tmp_path, monkeypatch):
    p = tmp_path / "reflection_metrics.json"
    monkeypatch.setattr(we, "REFLECTION_PATH", p)
    yield p


V211_FIXTURE = {
    "window_size": 10,
    "metrics": {
        "first_approach_accuracy": {
            "single_file":  {"correct": 402, "total": 420},
            "multi_file":   {"correct": 6,   "total": 19},
            "architecture": {"correct": 4,   "total": 32},
        },
        "over_engineering_rate": {
            "user_reverted_or_simplified": 0,
            "total_suggestions": 500,
        },
        "silence_accuracy": {
            "held_back_ok": 408,
            "held_back_missed": 31,
        },
    },
    "blind_spots": ["multi_file 首次正確率 32%"],
    "arch_sensitivity_elevated": True,
    "last_reflection": "2026-05-05T03:46:47.639931+00:00",
}


def test_v211_first_approach_moved_to_legacy(_tmp_reflection):
    _tmp_reflection.write_text(json.dumps(V211_FIXTURE), encoding="utf-8")
    metrics = we._load_metrics()

    assert metrics["schema_version"] == "2.12"
    assert metrics["legacy_cumulative"]["first_approach_accuracy"] == \
        V211_FIXTURE["metrics"]["first_approach_accuracy"]
    assert "frozen_at" in metrics["legacy_cumulative"]


def test_v211_first_approach_replaced_with_recent_lists(_tmp_reflection):
    _tmp_reflection.write_text(json.dumps(V211_FIXTURE), encoding="utf-8")
    metrics = we._load_metrics()

    faa = metrics["metrics"]["first_approach_accuracy"]
    assert faa["single_file"] == {"recent": []}
    assert faa["multi_file"] == {"recent": []}
    assert faa["architecture"] == {"recent": []}


def test_v211_over_engineering_migrated(_tmp_reflection):
    _tmp_reflection.write_text(json.dumps(V211_FIXTURE), encoding="utf-8")
    metrics = we._load_metrics()

    assert metrics["legacy_cumulative"]["over_engineering_rate"] == {
        "user_reverted_or_simplified": 0,
        "total_suggestions": 500,
    }
    assert metrics["metrics"]["over_engineering_rate"] == {"recent": []}


def test_v211_silence_accuracy_migrated(_tmp_reflection):
    _tmp_reflection.write_text(json.dumps(V211_FIXTURE), encoding="utf-8")
    metrics = we._load_metrics()

    assert metrics["legacy_cumulative"]["silence_accuracy"] == {
        "held_back_ok": 408,
        "held_back_missed": 31,
    }
    assert metrics["metrics"]["silence_accuracy"] == {"recent": []}


def test_arch_sensitivity_preserved_through_migration(_tmp_reflection):
    _tmp_reflection.write_text(json.dumps(V211_FIXTURE), encoding="utf-8")
    metrics = we._load_metrics()

    assert metrics["arch_sensitivity_elevated"] is True


def test_window_size_set_to_default_when_missing(_tmp_reflection):
    fixture = {k: v for k, v in V211_FIXTURE.items() if k != "window_size"}
    _tmp_reflection.write_text(json.dumps(fixture), encoding="utf-8")
    metrics = we._load_metrics()

    assert metrics["window_size"] == 10


def test_v212_idempotent(_tmp_reflection):
    # First migration
    _tmp_reflection.write_text(json.dumps(V211_FIXTURE), encoding="utf-8")
    first = we._load_metrics()
    we._save_json(_tmp_reflection, first)

    # Re-read should be no-op (no double-migration)
    second = we._load_metrics()
    assert second["schema_version"] == "2.12"
    assert second["legacy_cumulative"] == first["legacy_cumulative"]
    # frozen_at should not be overwritten on re-load
    assert second["legacy_cumulative"]["frozen_at"] == first["legacy_cumulative"]["frozen_at"]


def test_empty_file_yields_v212_schema(_tmp_reflection):
    # File doesn't exist
    metrics = we._load_metrics()
    assert metrics["schema_version"] == "2.12"
    assert metrics["window_size"] == 10
    assert metrics["metrics"]["first_approach_accuracy"]["single_file"] == {"recent": []}
    assert "legacy_cumulative" not in metrics  # nothing to migrate


def test_corrupt_file_yields_v212_schema(_tmp_reflection):
    _tmp_reflection.write_text("{ bad json", encoding="utf-8")
    metrics = we._load_metrics()
    assert metrics["schema_version"] == "2.12"


def test_v212_passthrough_no_legacy_added(_tmp_reflection):
    # File already V2.12 — no migration should occur
    v212_fixture = {
        "schema_version": "2.12",
        "window_size": 10,
        "metrics": {
            "first_approach_accuracy": {
                "single_file":  {"recent": [True, False]},
                "multi_file":   {"recent": []},
                "architecture": {"recent": []},
            },
            "over_engineering_rate": {"recent": [True]},
            "silence_accuracy": {"recent": []},
        },
        "blind_spots": [],
        "arch_sensitivity_elevated": False,
    }
    _tmp_reflection.write_text(json.dumps(v212_fixture), encoding="utf-8")
    metrics = we._load_metrics()

    assert metrics["schema_version"] == "2.12"
    assert "legacy_cumulative" not in metrics
    assert metrics["metrics"]["first_approach_accuracy"]["single_file"]["recent"] == [True, False]


def test_post_migration_reflect_appends_to_recent(_tmp_reflection):
    _tmp_reflection.write_text(json.dumps(V211_FIXTURE), encoding="utf-8")
    # Trigger migration via reflect
    we.reflect({
        "wisdom_approach": "direct",
        "wisdom_retry_count": 0,
        "modified_files": [{"path": "a.py"}],
    })

    metrics = json.loads(_tmp_reflection.read_text(encoding="utf-8"))
    assert metrics["schema_version"] == "2.12"
    assert "legacy_cumulative" in metrics
    assert metrics["metrics"]["first_approach_accuracy"]["single_file"]["recent"] == [True]
