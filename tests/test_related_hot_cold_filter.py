"""test_related_hot_cold_filter.py — REG-005 D-layer (Session 2/3 commit 5, 2026-04-29).

Covers Related-spread hot/cold routing in workflow-guardian.py:
- hot Related atoms → full content via decide_atom_injection (existing flow)
- cold Related atoms → 1-line summary (no budget consumption, no break)
- max_depth=1 enforced by spread_related (no transitive spread)

The integration is light-weight: rather than spinning up the full UPS pipeline,
the test exercises `classify_hot_cold` + `format_cold_inject_line` together with
`spread_related` to validate the moving parts behave as designed.

Design: memory/_staging/reg-005-atom-injection-refactor.md §D 層
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


def _write_access(path: Path, ages_days: list[float]) -> None:
    now = time.time()
    payload = {"timestamps": [now - d * 86400 for d in ages_days]}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_atom(dir: Path, name: str, related: list[str] = None,
               body: str = "## 印象\n- one bullet\n") -> Path:
    rel_line = f"- Related: {', '.join(related)}\n" if related else ""
    content = f"# {name}\n- Confidence: [固]\n{rel_line}\n{body}"
    p = dir / f"{name}.md"
    p.write_text(content, encoding="utf-8")
    return p


# ─── spread_related max_depth=1 ─────────────────────────────────────────────


def test_spread_related_depth_1_no_transitive(tmp_path: Path) -> None:
    """A → B → C: depth=1 only spreads A → B, not B → C."""
    _make_atom(tmp_path, "A", related=["B"])
    _make_atom(tmp_path, "B", related=["C"])
    _make_atom(tmp_path, "C")

    all_atoms = [
        (("A", "A.md", []), tmp_path),
        (("B", "B.md", []), tmp_path),
        (("C", "C.md", []), tmp_path),
    ]
    result = wg_atoms.spread_related({"A"}, all_atoms, [], max_depth=1)
    names = [entry[0][0] for entry in result]
    assert "B" in names
    assert "C" not in names


def test_spread_related_skips_already_injected(tmp_path: Path) -> None:
    _make_atom(tmp_path, "A", related=["B"])
    _make_atom(tmp_path, "B")
    all_atoms = [
        (("A", "A.md", []), tmp_path),
        (("B", "B.md", []), tmp_path),
    ]
    result = wg_atoms.spread_related({"A"}, all_atoms, ["B"], max_depth=1)
    names = [entry[0][0] for entry in result]
    assert "B" not in names


# ─── hot/cold classification of Related entries ─────────────────────────────


def test_related_hot_when_recent_reads(tmp_path: Path) -> None:
    atom = _make_atom(tmp_path, "hot_atom")
    _write_access(tmp_path / "hot_atom.access.json", [0.5, 1.0, 2.0, 3.0, 5.0])
    assert wg_atoms.classify_hot_cold(atom, "related") == "hot"


def test_related_cold_when_no_recent_reads(tmp_path: Path) -> None:
    atom = _make_atom(tmp_path, "cold_atom")
    assert wg_atoms.classify_hot_cold(atom, "related") == "cold"


def test_related_cold_below_threshold(tmp_path: Path) -> None:
    atom = _make_atom(tmp_path, "lukewarm")
    _write_access(tmp_path / "lukewarm.access.json", [1.0, 2.0])
    assert wg_atoms.classify_hot_cold(atom, "related") == "cold"


# ─── format_cold_inject_line for Related ─────────────────────────────────────


def test_related_cold_line_single_line(tmp_path: Path) -> None:
    raw = "# Related Atom\n\n## 印象\n- 第一條 bullet 描述\n- 第二條\n"
    line = wg_atoms.format_cold_inject_line("rel-atom", raw, "rel-atom.md")
    assert "\n" not in line
    assert "第一條 bullet 描述" in line
    assert "(cold)" in line
    assert "(full: Read rel-atom.md)" in line


def test_related_cold_line_marker_swap_pattern() -> None:
    """workflow-guardian.py replaces (cold) → (related, cold) for Related branch.
    Verify the format produced by format_cold_inject_line contains the (cold)
    marker that the swap targets."""
    raw = "# X\n\n## 印象\n- some bullet\n"
    line = wg_atoms.format_cold_inject_line("x", raw, "x.md")
    # The replace target the integrator uses
    assert f"[Atom:x] (cold)" in line
    swapped = line.replace("[Atom:x] (cold)", "[Atom:x] (related, cold)", 1)
    assert swapped.startswith("[Atom:x] (related, cold)")


# ─── End-to-end Related routing intent ──────────────────────────────────────


def test_related_routing_intent_hot_vs_cold(tmp_path: Path) -> None:
    """Simulate: A trigger-matched (hot); Related: B (recent reads → hot) +
    C (no access → cold). After classification, B should classify hot, C cold."""
    a = _make_atom(tmp_path, "A", related=["B", "C"])
    b = _make_atom(tmp_path, "B")
    c = _make_atom(tmp_path, "C")
    _write_access(tmp_path / "B.access.json", [0.1, 1.0, 2.0, 3.0, 5.0])
    # C has no access.json → cold

    all_atoms = [
        (("A", "A.md", []), tmp_path),
        (("B", "B.md", []), tmp_path),
        (("C", "C.md", []), tmp_path),
    ]
    related = wg_atoms.spread_related({"A"}, all_atoms, [], max_depth=1)
    classified = []
    for (rname, rel_path, _), base in related:
        rpath = base / rel_path
        cls = wg_atoms.classify_hot_cold(rpath, "related")
        classified.append((rname, cls))

    by_name = dict(classified)
    assert by_name.get("B") == "hot"
    assert by_name.get("C") == "cold"
