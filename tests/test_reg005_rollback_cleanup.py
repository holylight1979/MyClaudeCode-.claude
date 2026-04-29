"""test_reg005_rollback_cleanup.py — REG-005 Session 2 補完 commit 7 (2026-04-29).

Covers tools/reg005-rollback-cleanup.py — settings.json hook removal +
flag deletion + dry-run safety.

Design: memory/_staging/reg-005-atom-injection-refactor.md (commit 7).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
SCRIPT_PATH = TOOLS_DIR / "reg005-rollback-cleanup.py"


def _load_module():
    """Load the cleanup script as a module (filename has hyphen → can't import)."""
    spec = importlib.util.spec_from_file_location("reg005_rollback_cleanup", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


cleanup_mod = _load_module()


# ─── fixtures ──────────────────────────────────────────────────────────────


def _settings_with_two_obs_matchers() -> Dict[str, Any]:
    """Mirrors the real shape: UPS + PostToolUse(Read) referencing wg_atom_observation."""
    return {
        "hooks": {
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python -c \"import runpy,pathlib;runpy.run_path(str(pathlib.Path.home()/'.claude/hooks/wg_atom_observation.py'),run_name='__main__')\"",
                            "timeout": 3,
                        }
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python -c \"import runpy,pathlib;runpy.run_path(str(pathlib.Path.home()/'.claude/hooks/wg_atom_observation.py'),run_name='__main__')\"",
                            "timeout": 3,
                        }
                    ],
                }
            ],
        }
    }


def _setup_home(tmp_path: Path, settings: Dict[str, Any], flag: bool = True) -> Path:
    home = tmp_path / "home"
    (home / ".claude" / "memory" / "_staging").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if flag:
        (home / ".claude" / "memory" / "_staging" / "reg-005-observation-start.flag").write_text(
            "2026-04-29T03:20:12Z", encoding="utf-8"
        )
    return home


# ─── core scenarios ────────────────────────────────────────────────────────


def test_dry_run_no_mutation(tmp_path: Path) -> None:
    settings = _settings_with_two_obs_matchers()
    home = _setup_home(tmp_path, settings)
    settings_before = (home / ".claude" / "settings.json").read_text(encoding="utf-8")

    report = cleanup_mod.cleanup(home, apply=False)

    assert report["removed_hooks"] == 2
    assert report["flag_existed"] is True
    assert report["apply"] is False
    events = {e["event"] for e in report["events_touched"]}
    assert events == {"UserPromptSubmit", "PostToolUse"}

    # nothing actually mutated
    assert (home / ".claude" / "settings.json").read_text(encoding="utf-8") == settings_before
    assert (home / ".claude" / "memory" / "_staging" / "reg-005-observation-start.flag").exists()


def test_apply_removes_two_matchers_and_flag(tmp_path: Path) -> None:
    home = _setup_home(tmp_path, _settings_with_two_obs_matchers())

    report = cleanup_mod.cleanup(home, apply=True)

    assert report["removed_hooks"] == 2
    settings_after = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))

    # both events become empty lists (matcher blocks dropped — not just hooks)
    assert settings_after["hooks"]["UserPromptSubmit"] == []
    assert settings_after["hooks"]["PostToolUse"] == []
    assert not (home / ".claude" / "memory" / "_staging" / "reg-005-observation-start.flag").exists()


def test_apply_preserves_unrelated_hooks(tmp_path: Path) -> None:
    """Unrelated hooks in same event/matcher block must be retained."""
    settings = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python /unrelated/other_hook.py",
                            "timeout": 5,
                        },
                        {
                            "type": "command",
                            "command": "python -c \"import runpy,pathlib;runpy.run_path(str(pathlib.Path.home()/'.claude/hooks/wg_atom_observation.py'),run_name='__main__')\"",
                            "timeout": 3,
                        },
                    ],
                },
                {
                    "matcher": "Write",
                    "hooks": [
                        {"type": "command", "command": "python /entirely/separate.py"}
                    ],
                },
            ]
        }
    }
    home = _setup_home(tmp_path, settings, flag=False)

    report = cleanup_mod.cleanup(home, apply=True)
    assert report["removed_hooks"] == 1
    after = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))

    post = after["hooks"]["PostToolUse"]
    assert len(post) == 2  # Read matcher kept (still has unrelated hook); Write untouched
    read_block = next(b for b in post if b.get("matcher") == "Read")
    assert len(read_block["hooks"]) == 1
    assert "wg_atom_observation" not in read_block["hooks"][0]["command"]
    assert "/unrelated/other_hook.py" in read_block["hooks"][0]["command"]
    write_block = next(b for b in post if b.get("matcher") == "Write")
    assert "/entirely/separate.py" in write_block["hooks"][0]["command"]


def test_empty_matcher_block_dropped(tmp_path: Path) -> None:
    """When a matcher block's only hook was the obs hook, drop the whole block."""
    settings = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [
                        {"type": "command", "command": "python ~/.claude/hooks/wg_atom_observation.py"},
                    ],
                },
                {
                    "matcher": "Write",
                    "hooks": [{"type": "command", "command": "python /keep_me.py"}],
                },
            ]
        }
    }
    home = _setup_home(tmp_path, settings, flag=False)
    cleanup_mod.cleanup(home, apply=True)
    after = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    post = after["hooks"]["PostToolUse"]
    assert len(post) == 1
    assert post[0]["matcher"] == "Write"


def test_no_flag_no_error(tmp_path: Path) -> None:
    home = _setup_home(tmp_path, _settings_with_two_obs_matchers(), flag=False)
    report = cleanup_mod.cleanup(home, apply=True)
    assert report["flag_existed"] is False
    assert report["removed_hooks"] == 2


def test_no_settings_returns_error(tmp_path: Path) -> None:
    home = tmp_path / "empty_home"
    (home / ".claude").mkdir(parents=True)
    report = cleanup_mod.cleanup(home, apply=True)
    assert "error" in report
    assert "not found" in report["error"]
    assert report["removed_hooks"] == 0


def test_idempotent(tmp_path: Path) -> None:
    """Running cleanup twice produces removed_hooks=0 on the second run."""
    home = _setup_home(tmp_path, _settings_with_two_obs_matchers())
    cleanup_mod.cleanup(home, apply=True)
    second = cleanup_mod.cleanup(home, apply=True)
    assert second["removed_hooks"] == 0
    assert second["flag_existed"] is False
    assert second.get("error") is None


def test_malformed_settings_returns_error(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text("not json {{{", encoding="utf-8")
    report = cleanup_mod.cleanup(home, apply=True)
    assert "error" in report
    assert "parse error" in report["error"]


def test_unrelated_settings_no_change(tmp_path: Path) -> None:
    """settings.json with no obs references → removed_hooks=0; no error."""
    settings = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "python /other.py"}]}
            ]
        }
    }
    home = _setup_home(tmp_path, settings, flag=False)
    before = (home / ".claude" / "settings.json").read_text(encoding="utf-8")
    report = cleanup_mod.cleanup(home, apply=True)
    assert report["removed_hooks"] == 0
    assert (home / ".claude" / "settings.json").read_text(encoding="utf-8") == before


def test_preserves_top_level_non_hooks_keys(tmp_path: Path) -> None:
    """settings.json keys outside 'hooks' (e.g. 'permissions') must be preserved on apply."""
    settings = _settings_with_two_obs_matchers()
    settings["permissions"] = {"allow": ["Read", "Write"]}
    settings["env"] = {"FOO": "bar"}
    home = _setup_home(tmp_path, settings, flag=False)
    cleanup_mod.cleanup(home, apply=True)
    after = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert after["permissions"] == {"allow": ["Read", "Write"]}
    assert after["env"] == {"FOO": "bar"}
