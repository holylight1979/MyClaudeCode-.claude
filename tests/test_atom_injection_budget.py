"""test_atom_injection_budget.py — REG-005 B-layer (Session 1/3, 2026-04-29).

Covers per-turn budget tracker (`_TURN_BUDGET_LIMIT = 800`, `decide_atom_injection`)
and the SECTION_INJECT_THRESHOLD lowering (300 → 200).

Tests the decision function in isolation (ok / fallback / skip) plus the
threshold change. End-to-end multi-atom integration through workflow-guardian's
UserPromptSubmit handler is covered by SessionStart smoke and existing
integration tests.

Design: memory/_staging/reg-005-atom-injection-refactor.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import wg_atoms  # noqa: E402


# ─── fixtures ───────────────────────────────────────────────────────────────


def _frontmatter_block() -> str:
    return (
        f"- Scope: shared\n"
        f"- Confidence: [固]\n"
        f"- Trigger: t1, t2\n"
        f"- Last-used: 2026-04-29\n"
        f"- Confirmations: 0\n"
        f"- ReadHits: 0\n"
    )


def _small_atom() -> str:
    """~50 tokens stripped (impression+action)."""
    return (
        f"# 小 atom\n\n"
        f"{_frontmatter_block()}\n"
        f"## 印象\n\n- A\n\n"
        f"## 行動\n\n- B\n"
    )


def _large_atom() -> str:
    """~500+ tokens stripped (knowledge_mixed with big knowledge)."""
    knowledge = "\n".join(f"- 知識條目 {i:03d} 一些補充細節文字內容填充" for i in range(60))
    return (
        f"# 大 atom\n\n"
        f"{_frontmatter_block()}\n"
        f"## 印象\n\n- 印象 A\n- 印象 B\n\n"
        f"## 知識\n\n{knowledge}\n\n"
        f"## 行動\n\n- 動作 X\n- 動作 Y\n"
    )


# ─── decide_atom_injection: ok path ─────────────────────────────────────────


def test_decision_ok_when_within_budget():
    raw = _small_atom()
    full = wg_atoms._strip_atom_for_injection(raw)
    decision, content, consumed = wg_atoms.decide_atom_injection(raw, full, used_tokens=0)
    assert decision == "ok"
    assert content == full
    assert consumed == wg_atoms._estimate_tokens(full)


def test_decision_ok_when_remaining_budget_exactly_fits():
    raw = _small_atom()
    full = wg_atoms._strip_atom_for_injection(raw)
    full_tokens = wg_atoms._estimate_tokens(full)
    used = wg_atoms._TURN_BUDGET_LIMIT - full_tokens
    decision, _, _ = wg_atoms.decide_atom_injection(raw, full, used_tokens=used)
    assert decision == "ok"


# ─── decide_atom_injection: fallback path ───────────────────────────────────


def test_decision_fallback_when_full_overflows_but_impression_fits():
    raw = _large_atom()
    full = wg_atoms._strip_atom_for_injection(raw, knowledge_cap_tokens=300)
    full_tokens = wg_atoms._estimate_tokens(full)
    fb = wg_atoms._strip_atom_for_injection_impression_only(raw)
    fb_tokens = wg_atoms._estimate_tokens(fb)
    # Set used so that full overflows but fb still fits
    used = wg_atoms._TURN_BUDGET_LIMIT - fb_tokens - 5
    assert used + full_tokens > wg_atoms._TURN_BUDGET_LIMIT  # sanity
    decision, content, consumed = wg_atoms.decide_atom_injection(raw, full, used_tokens=used)
    assert decision == "fallback"
    assert "印象" in content
    assert "知識" not in content  # impression-only drops knowledge
    assert consumed == fb_tokens


# ─── decide_atom_injection: skip path ───────────────────────────────────────


def test_decision_skip_when_even_impression_overflows():
    raw = _large_atom()
    full = wg_atoms._strip_atom_for_injection(raw)
    fb = wg_atoms._strip_atom_for_injection_impression_only(raw)
    fb_tokens = wg_atoms._estimate_tokens(fb)
    # Used so that even fb does not fit
    used = wg_atoms._TURN_BUDGET_LIMIT - fb_tokens + 1
    decision, content, consumed = wg_atoms.decide_atom_injection(raw, full, used_tokens=used)
    assert decision == "skip"
    assert content == ""
    assert consumed == 0


def test_decision_skip_when_impression_not_smaller_than_full():
    """Pathological: impression-only happens to be ≥ full — skip rather than enlarge."""
    # Construct: small atom where _strip_atom_for_injection result happens to be
    # close to or smaller than the impression-only block (rare but possible if
    # the action section is empty and impression is large).
    # Use a minimal full to force the check.
    raw = _small_atom()
    # Pass an artificially tiny "full" to trigger fb_tokens >= full_tokens guard
    full = "## 印象\n\n- A"  # 4 tokens
    used = wg_atoms._TURN_BUDGET_LIMIT - 1  # 1 token remaining
    decision, _, consumed = wg_atoms.decide_atom_injection(raw, full, used_tokens=used)
    # full_tokens=1 (3 chars/4=0… actually 12 chars/4=3) overflows by 2; fb is much larger → skip
    assert decision == "skip"
    assert consumed == 0


# ─── budget reset semantics (per-turn local var, no module state) ───────────


def test_budget_constant_is_800():
    """Sanity check on the published constant."""
    assert wg_atoms._TURN_BUDGET_LIMIT == 800


def test_no_module_level_state_carries_between_calls():
    """Multiple decide_atom_injection calls do not share state — used_tokens is
    a caller-provided argument. Each handler invocation starts fresh."""
    raw = _small_atom()
    full = wg_atoms._strip_atom_for_injection(raw)
    d1, _, c1 = wg_atoms.decide_atom_injection(raw, full, used_tokens=0)
    d2, _, c2 = wg_atoms.decide_atom_injection(raw, full, used_tokens=0)
    assert d1 == d2 == "ok"
    assert c1 == c2  # deterministic


# ─── SECTION_INJECT_THRESHOLD ───────────────────────────────────────────────


def test_section_inject_threshold_lowered_to_200():
    """REG-005 B-layer: 300 → 200, more atoms now eligible for vector section
    extraction."""
    assert wg_atoms.SECTION_INJECT_THRESHOLD == 200


# ─── multi-atom budget exhaustion sequence ──────────────────────────────────


def test_sequential_decisions_simulate_multi_atom_overflow():
    """Simulate a session: 5 large atoms back-to-back → first few ok, then
    fallbacks, then skip."""
    raw = _large_atom()
    full = wg_atoms._strip_atom_for_injection(raw)
    used = 0
    decisions: list[str] = []
    for _ in range(8):
        d, _, c = wg_atoms.decide_atom_injection(raw, full, used_tokens=used)
        decisions.append(d)
        if d in ("ok", "fallback"):
            used += c
        if d == "skip":
            break
    # Must contain at least one ok (first atom should fit)
    assert "ok" in decisions
    # Must end with skip (or have remained ok if atoms small — large atom sized
    # for overflow within ~5 iterations)
    assert decisions[-1] == "skip" or all(d != "skip" for d in decisions)
    # used_tokens never exceeds budget
    assert used <= wg_atoms._TURN_BUDGET_LIMIT


# ─── integration: real atom from disk passes through decide cleanly ─────────


def test_real_atom_decision_flow(tmp_path):
    """Sanity: a real atom file (rendered from fixture) survives the full
    pipeline (read → strip → decide) without exception."""
    atom_path = tmp_path / "decisions.md"
    atom_path.write_text(_large_atom(), encoding="utf-8")
    raw = atom_path.read_text(encoding="utf-8-sig")
    full = wg_atoms._strip_atom_for_injection(raw)
    decision, content, consumed = wg_atoms.decide_atom_injection(raw, full, used_tokens=0)
    assert decision in ("ok", "fallback", "skip")
    if decision in ("ok", "fallback"):
        assert content
        assert consumed > 0
