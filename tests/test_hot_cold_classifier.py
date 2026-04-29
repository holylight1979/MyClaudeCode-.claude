"""test_hot_cold_classifier.py — REG-005 C-layer (Session 2/3, 2026-04-29).

Covers `_recent_reads_7d`, `classify_hot_cold`, `format_cold_inject_line`.

Design: memory/_staging/reg-005-atom-injection-refactor.md §C 層
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import wg_atoms  # noqa: E402


# ─── _recent_reads_7d ───────────────────────────────────────────────────────


def _write_access(path: Path, ages_days: list[float]) -> None:
    """Write access.json with timestamps at the given ages (days ago)."""
    now = time.time()
    payload = {"timestamps": [now - d * 86400 for d in ages_days]}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_recent_reads_missing_file(tmp_path: Path) -> None:
    assert wg_atoms._recent_reads_7d(tmp_path / "nope.access.json") == 0


def test_recent_reads_empty_timestamps(tmp_path: Path) -> None:
    p = tmp_path / "empty.access.json"
    p.write_text(json.dumps({"timestamps": []}), encoding="utf-8")
    assert wg_atoms._recent_reads_7d(p) == 0


def test_recent_reads_all_within_7d(tmp_path: Path) -> None:
    p = tmp_path / "fresh.access.json"
    _write_access(p, [0.1, 1.0, 3.0, 5.5, 6.9])
    assert wg_atoms._recent_reads_7d(p) == 5


def test_recent_reads_mixed(tmp_path: Path) -> None:
    p = tmp_path / "mixed.access.json"
    _write_access(p, [0.5, 2.0, 6.0, 10.0, 30.0])
    assert wg_atoms._recent_reads_7d(p) == 3


def test_recent_reads_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.access.json"
    p.write_text("not json {{", encoding="utf-8")
    assert wg_atoms._recent_reads_7d(p) == 0


def test_recent_reads_non_list(tmp_path: Path) -> None:
    p = tmp_path / "weird.access.json"
    p.write_text(json.dumps({"timestamps": "huh"}), encoding="utf-8")
    assert wg_atoms._recent_reads_7d(p) == 0


def test_recent_reads_skips_garbage_entries(tmp_path: Path) -> None:
    p = tmp_path / "messy.access.json"
    now = time.time()
    payload = {"timestamps": [now - 86400, "not-a-float", None, now - 86400 * 2]}
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert wg_atoms._recent_reads_7d(p) == 2


# ─── classify_hot_cold ──────────────────────────────────────────────────────


def test_classify_trigger_no_access(tmp_path: Path) -> None:
    atom = tmp_path / "atom.md"
    atom.write_text("# Atom\n", encoding="utf-8")
    assert wg_atoms.classify_hot_cold(atom, "trigger") == "hot"


def test_classify_vector_no_access(tmp_path: Path) -> None:
    atom = tmp_path / "atom.md"
    atom.write_text("# Atom\n", encoding="utf-8")
    assert wg_atoms.classify_hot_cold(atom, "vector") == "cold"


def test_classify_vector_above_threshold(tmp_path: Path) -> None:
    atom = tmp_path / "atom.md"
    atom.write_text("# Atom\n", encoding="utf-8")
    _write_access(tmp_path / "atom.access.json", [0.5, 1.0, 2.0, 3.0, 5.0])
    assert wg_atoms.classify_hot_cold(atom, "vector") == "hot"


def test_classify_vector_below_threshold(tmp_path: Path) -> None:
    atom = tmp_path / "atom.md"
    atom.write_text("# Atom\n", encoding="utf-8")
    _write_access(tmp_path / "atom.access.json", [0.5, 2.0])
    assert wg_atoms.classify_hot_cold(atom, "vector") == "cold"


def test_classify_related_zero_recent(tmp_path: Path) -> None:
    atom = tmp_path / "atom.md"
    atom.write_text("# Atom\n", encoding="utf-8")
    _write_access(tmp_path / "atom.access.json", [30.0, 60.0])
    assert wg_atoms.classify_hot_cold(atom, "related") == "cold"


def test_classify_related_high_recent(tmp_path: Path) -> None:
    atom = tmp_path / "atom.md"
    atom.write_text("# Atom\n", encoding="utf-8")
    _write_access(tmp_path / "atom.access.json", [0.1, 1.0, 2.0, 3.0, 5.0])
    assert wg_atoms.classify_hot_cold(atom, "related") == "hot"


def test_classify_unknown_source_treated_as_vector(tmp_path: Path) -> None:
    atom = tmp_path / "atom.md"
    atom.write_text("# Atom\n", encoding="utf-8")
    assert wg_atoms.classify_hot_cold(atom, "foo") == "cold"


def test_classify_custom_threshold(tmp_path: Path) -> None:
    atom = tmp_path / "atom.md"
    atom.write_text("# Atom\n", encoding="utf-8")
    _write_access(tmp_path / "atom.access.json", [1.0, 2.0])
    # Threshold 2 → 2 reads count as hot
    assert wg_atoms.classify_hot_cold(atom, "vector", hot_recent_threshold=2) == "hot"
    # Threshold 5 → not enough
    assert wg_atoms.classify_hot_cold(atom, "vector", hot_recent_threshold=5) == "cold"


# ─── format_cold_inject_line ────────────────────────────────────────────────


def test_format_cold_impression_action_atom() -> None:
    raw = (
        "# Title Atom\n"
        "- Confidence: [固]\n"
        "\n"
        "## 印象\n"
        "\n"
        "- 雙 LLM 分工（CC 雲端 + Ollama 本地）\n"
        "- 三層即時管線\n"
        "\n"
        "## 行動\n"
        "- 動到 hooks 前先讀\n"
    )
    out = wg_atoms.format_cold_inject_line("decisions", raw, "decisions.md")
    assert "雙 LLM 分工" in out
    assert "(cold)" in out
    assert "(full: Read decisions.md)" in out
    assert out.startswith("[Atom:decisions]")
    assert "\n" not in out


def test_format_cold_knowledge_mixed_atom() -> None:
    raw = (
        "# Mixed\n"
        "- Confidence: [固]\n"
        "\n"
        "## 印象\n"
        "- 第一印象 bullet\n"
        "\n"
        "## 知識\n"
        "- 知識內容不該被選\n"
    )
    out = wg_atoms.format_cold_inject_line("mixed", raw, "")
    assert "第一印象 bullet" in out
    assert "知識內容" not in out
    assert "(full: Read mixed.md)" in out


def test_format_cold_title_only() -> None:
    raw = "# Just a Title\n\nSome paragraph without 印象 section.\n"
    out = wg_atoms.format_cold_inject_line("titled", raw, "titled.md")
    assert "Just a Title" in out


def test_format_cold_empty_atom() -> None:
    out = wg_atoms.format_cold_inject_line("empty", "", "empty.md")
    assert "[Atom:empty]" in out
    assert "empty" in out
    assert "(cold)" in out


def test_format_cold_truncates_long_summary() -> None:
    long_bullet = "x" * 200
    raw = f"# T\n\n## 印象\n- {long_bullet}\n"
    out = wg_atoms.format_cold_inject_line("long", raw, "long.md")
    assert out.endswith("(full: Read long.md)")
    assert "…" in out
    assert "\n" not in out


def test_format_cold_empty_rel_path_falls_back_to_name() -> None:
    raw = "# T\n\n## 印象\n- summary\n"
    out = wg_atoms.format_cold_inject_line("foo", raw, "")
    assert "(full: Read foo.md)" in out


def test_format_cold_no_newline_in_output() -> None:
    raw = (
        "# T\n\n## 印象\n"
        "- line one\n- line two\n"
    )
    out = wg_atoms.format_cold_inject_line("multi", raw, "multi.md")
    assert "\n" not in out


def test_format_cold_skips_blockquote_in_impression() -> None:
    raw = (
        "# T\n\n## 印象\n"
        "> 架構細節已搬移\n\n"
        "- real bullet\n"
    )
    out = wg_atoms.format_cold_inject_line("decisions", raw, "decisions.md")
    assert "real bullet" in out
    assert "架構細節已搬移" not in out
