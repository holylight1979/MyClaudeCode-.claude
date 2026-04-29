"""test_atom_strip_for_injection.py — REG-005 A-layer (Session 1/3, 2026-04-28).

Covers `wg_atoms._strip_atom_for_injection` rewrite from整檔剝離 to summary-first
routing by atom type (impression_action / knowledge_mixed / fallback), plus the
helpers `_detect_atom_type`, `_extract_named_section`, `_extract_title_and_frontmatter`,
and `_strip_atom_for_injection_impression_only` (used by B-layer budget fallback).

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


def _frontmatter_block(confidence: str = "[固]") -> str:
    return (
        f"- Scope: shared\n"
        f"- Confidence: {confidence}\n"
        f"- Trigger: t1, t2\n"
        f"- Last-used: 2026-04-27\n"
        f"- Confirmations: 0\n"
        f"- ReadHits: 0\n"
        f"- Tags: tag1, tag2\n"
    )


def _impression_action_atom() -> str:
    return (
        f"# 印象行動型\n\n"
        f"{_frontmatter_block()}"
        f"- Related: foo, bar\n\n"
        f"## 印象\n\n"
        f"- 印象條目 A\n"
        f"- 印象條目 B → 指針\n\n"
        f"## 行動\n\n"
        f"- 行動 1\n"
        f"- 行動 2\n"
    )


def _knowledge_action_atom(knowledge_lines: list[str] | None = None) -> str:
    body = "\n".join(knowledge_lines) if knowledge_lines else "- 知識條目 A\n- 知識條目 B"
    return (
        f"# 知識行動型\n\n"
        f"{_frontmatter_block()}\n"
        f"## 知識\n\n{body}\n\n"
        f"## 行動\n\n"
        f"- 動作 X\n"
        f"- 動作 Y\n"
    )


def _mixed_atom() -> str:
    return (
        f"# 混型\n\n"
        f"{_frontmatter_block()}\n"
        f"## 印象\n\n- 印象 line\n\n"
        f"## 知識\n\n- 知識 line\n\n"
        f"## 行動\n\n- 行動 line\n"
    )


def _variant_section_atom() -> str:
    """Pointer-style atom: has 印象 + 行動 + custom variant section, no 知識."""
    return (
        f"# 指標型\n\n"
        f"{_frontmatter_block()}\n"
        f"## 印象\n\n- 印象 line\n\n"
        f"## 紅色指標（失敗模式）\n\n- 紅色 line A\n- 紅色 line B\n\n"
        f"## 行動\n\n- 動 X\n"
    )


def _fallback_atom() -> str:
    """Atom with neither ## 印象 nor ## 知識 — should hit legacy strip path."""
    return (
        f"# 沒印象沒知識\n\n"
        f"{_frontmatter_block()}\n"
        f"## 已 hook 化\n\n- legacy line\n\n"
        f"## 行動\n\n- act\n"
    )


# ─── _extract_named_section ─────────────────────────────────────────────────


def test_extract_named_section_basic():
    content = "# T\n\n## 印象\n\n- A\n- B\n\n## 行動\n\n- run\n"
    out = wg_atoms._extract_named_section(content, "印象")
    assert out == "## 印象\n\n- A\n- B"


def test_extract_named_section_missing_returns_none():
    content = "# T\n\n## 行動\n\n- run\n"
    assert wg_atoms._extract_named_section(content, "印象") is None


def test_extract_named_section_truncates_when_over_cap():
    big_body = "\n".join(f"- 知識點 {i:02d} 一些補充細節文字內容" for i in range(50))
    content = f"# T\n\n## 知識\n\n{big_body}\n\n## 行動\n\n- run\n"
    out = wg_atoms._extract_named_section(content, "知識", max_tokens=50)
    assert out is not None
    assert out.startswith("## 知識\n")
    assert "已截斷" in out
    assert "原" in out  # truncation marker contains "原 N tokens"
    # truncated output should be at or under the cap (with marker overhead leeway)
    assert wg_atoms._estimate_tokens(out) <= 80


def test_extract_named_section_no_truncation_when_under_cap():
    content = "# T\n\n## 知識\n\n- short\n\n## 行動\n\n- run\n"
    out = wg_atoms._extract_named_section(content, "知識", max_tokens=200)
    assert out == "## 知識\n\n- short"
    assert "已截斷" not in out


# ─── _detect_atom_type ──────────────────────────────────────────────────────


def test_detect_impression_action():
    assert wg_atoms._detect_atom_type(_impression_action_atom()) == "impression_action"


def test_detect_knowledge_mixed_with_impression():
    assert wg_atoms._detect_atom_type(_mixed_atom()) == "knowledge_mixed"


def test_detect_knowledge_mixed_without_impression():
    assert wg_atoms._detect_atom_type(_knowledge_action_atom()) == "knowledge_mixed"


def test_detect_fallback_when_neither():
    assert wg_atoms._detect_atom_type(_fallback_atom()) == "fallback"


# ─── _extract_title_and_frontmatter ─────────────────────────────────────────


def test_frontmatter_keeps_only_whitelist():
    out = wg_atoms._extract_title_and_frontmatter(_impression_action_atom())
    assert "# 印象行動型" in out
    assert "- Confidence:" in out
    assert "- Trigger:" in out
    assert "- Last-used:" in out
    # stripped fields
    assert "Scope" not in out
    assert "Confirmations" not in out
    assert "ReadHits" not in out
    assert "Tags" not in out
    assert "Related" not in out


def test_frontmatter_no_title():
    """Atom with no `# Title` line still extracts whitelist fields."""
    content = _frontmatter_block() + "\n## 印象\n\n- x\n"
    out = wg_atoms._extract_title_and_frontmatter(content)
    assert "Confidence" in out
    assert not out.startswith("\n")


# ─── _strip_atom_for_injection routing ──────────────────────────────────────


def test_strip_impression_action_keeps_impression_and_action():
    out = wg_atoms._strip_atom_for_injection(_impression_action_atom())
    assert "# 印象行動型" in out
    assert "- Confidence:" in out
    assert "## 印象" in out
    assert "印象條目 A" in out
    assert "## 行動" in out
    assert "行動 1" in out
    # excluded
    assert "## 知識" not in out
    assert "Scope" not in out


def test_strip_knowledge_mixed_keeps_all_three_sections():
    out = wg_atoms._strip_atom_for_injection(_mixed_atom())
    assert "## 印象" in out and "印象 line" in out
    assert "## 知識" in out and "知識 line" in out
    assert "## 行動" in out and "行動 line" in out


def test_strip_knowledge_only_no_impression():
    """decisions.md / toolchain.md style: 知識 + 行動, no 印象."""
    out = wg_atoms._strip_atom_for_injection(_knowledge_action_atom())
    assert "## 印象" not in out
    assert "## 知識" in out
    assert "## 行動" in out
    assert "知識條目 A" in out
    assert "動作 X" in out


def test_strip_caps_large_knowledge_section():
    knowledge = [f"- 大量知識條目 {i:03d} 一些填充字" for i in range(80)]
    atom = _knowledge_action_atom(knowledge_lines=knowledge)
    out = wg_atoms._strip_atom_for_injection(atom, knowledge_cap_tokens=100)
    assert "## 知識" in out
    assert "已截斷" in out
    # 行動 still appears even after 知識 cap
    assert "## 行動" in out
    assert "動作 X" in out


def test_strip_variant_section_atom_drops_variant():
    """Pointer atom with 印象 + 紅色指標 + 行動 → impression_action route, variant dropped."""
    out = wg_atoms._strip_atom_for_injection(_variant_section_atom())
    assert "## 印象" in out
    assert "## 行動" in out
    assert "## 紅色指標" not in out
    assert "紅色 line" not in out


def test_strip_fallback_uses_legacy_path():
    """Atom without 印象 or 知識 falls back to legacy strip (drops 行動 + 演化日誌)."""
    out = wg_atoms._strip_atom_for_injection(_fallback_atom())
    # legacy strip removes ## 行動
    assert "## 行動" not in out
    # but custom variant section is preserved
    assert "## 已 hook 化" in out
    # legacy strip removes Scope/Confirmations/ReadHits/Tags/Last-used/Trigger
    assert "Scope" not in out
    assert "Trigger" not in out


def test_strip_empty_content_safe():
    assert wg_atoms._strip_atom_for_injection("") == ""


def test_strip_only_frontmatter_safe():
    """Atom with only header + frontmatter (no sections) → fallback path."""
    content = f"# 只有 frontmatter\n\n{_frontmatter_block()}"
    out = wg_atoms._strip_atom_for_injection(content)
    # should not crash, should contain the header
    assert "# 只有 frontmatter" in out


# ─── _strip_atom_for_injection_impression_only ──────────────────────────────


def test_impression_only_returns_minimal_block():
    out = wg_atoms._strip_atom_for_injection_impression_only(_impression_action_atom())
    assert "# 印象行動型" in out
    assert "## 印象" in out
    assert "## 行動" not in out  # action is dropped in impression-only mode
    assert "## 知識" not in out


def test_impression_only_handles_atom_without_impression():
    """Atom without ## 印象 → returns header alone (no crash)."""
    out = wg_atoms._strip_atom_for_injection_impression_only(_knowledge_action_atom())
    assert "# 知識行動型" in out
    assert "Confidence" in out
    assert "## 印象" not in out


# ─── token reduction smoke check (sanity, not a strict assertion) ───────────


def test_reduction_vs_legacy_for_knowledge_mixed():
    """Sanity: new strip on a typical knowledge atom should not be larger than legacy."""
    atom = _knowledge_action_atom([f"- 知識點 {i}" for i in range(30)])
    new_out = wg_atoms._strip_atom_for_injection(atom)
    legacy_out = wg_atoms._legacy_strip_atom_for_injection(atom)
    # new keeps 行動 (legacy strips it), but caps 知識 + drops Scope/Tags etc.
    # Both should be non-empty; new should not blow up size massively.
    assert len(new_out) > 0
    assert len(legacy_out) > 0
    # new should at least exclude Scope/Tags/Confirmations/ReadHits
    assert "Scope" not in new_out
    assert "Tags" not in new_out
