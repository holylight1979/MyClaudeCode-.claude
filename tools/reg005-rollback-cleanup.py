#!/usr/bin/env python3
"""REG-005 觀察期儀表清理工具（ROLLBACK / KEEP 收尾後執行）。

動作：
1. 從 ~/.claude/settings.json 移除引用 wg_atom_observation.py 的 hook
   matcher（UserPromptSubmit + PostToolUse(Read) 兩處）
2. 刪除 ~/.claude/memory/_staging/reg-005-observation-start.flag

預設 dry-run；需 --apply 才實際動。
保留 hooks/wg_atom_observation.py 檔案本身（未來重用）。

設計：memory/_staging/reg-005-atom-injection-refactor.md (Session 2 補完 commit 7)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _is_atom_obs_hook(hook: Any) -> bool:
    """單一 hook entry 是否引用 wg_atom_observation.py。"""
    if not isinstance(hook, dict):
        return False
    return "wg_atom_observation" in hook.get("command", "")


def _strip_obs_from_event(event_entries: List[Any]) -> Tuple[List[Any], int]:
    """從某 event 的 list 中移除引用 wg_atom_observation 的 hook。

    若某 matcher block 內所有 hooks 都被移除，整個 matcher block 也丟棄
    （避免遺留空 matcher → settings.json schema 噪音）。
    回傳 (新 list, 已移除的 hook 筆數)。
    """
    removed = 0
    new_entries: List[Any] = []
    for entry in event_entries:
        if not isinstance(entry, dict):
            new_entries.append(entry)
            continue
        hooks_arr = entry.get("hooks", [])
        if not isinstance(hooks_arr, list):
            new_entries.append(entry)
            continue
        kept_hooks = [h for h in hooks_arr if not _is_atom_obs_hook(h)]
        removed += len(hooks_arr) - len(kept_hooks)
        if kept_hooks:
            new_entry = dict(entry)
            new_entry["hooks"] = kept_hooks
            new_entries.append(new_entry)
        # else: 整 matcher block 變空 → 不 append（丟棄）
    return new_entries, removed


def cleanup(home: Path, apply: bool) -> Dict[str, Any]:
    """Plan / execute REG-005 observation cleanup against settings.json + flag."""
    settings_path = home / ".claude" / "settings.json"
    flag_path = home / ".claude" / "memory" / "_staging" / "reg-005-observation-start.flag"
    report: Dict[str, Any] = {
        "settings_path": str(settings_path),
        "flag_path": str(flag_path),
        "removed_hooks": 0,
        "events_touched": [],
        "flag_existed": False,
        "apply": apply,
    }

    if not settings_path.exists():
        report["error"] = "settings.json not found"
        return report

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report["error"] = f"settings.json parse error: {e}"
        return report

    hooks_section = settings.get("hooks", {})
    if not isinstance(hooks_section, dict):
        report["error"] = "settings.json has no 'hooks' object"
        return report

    total_removed = 0
    new_hooks_section: Dict[str, Any] = {}
    for event_name, event_entries in hooks_section.items():
        if not isinstance(event_entries, list):
            new_hooks_section[event_name] = event_entries
            continue
        new_entries, removed = _strip_obs_from_event(event_entries)
        if removed > 0:
            total_removed += removed
            report["events_touched"].append({"event": event_name, "removed": removed})
        new_hooks_section[event_name] = new_entries
    report["removed_hooks"] = total_removed

    if flag_path.exists():
        report["flag_existed"] = True

    if apply:
        if total_removed > 0:
            settings["hooks"] = new_hooks_section
            settings_path.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if flag_path.exists():
            flag_path.unlink()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="REG-005 觀察期儀表清理（dry-run 預設；--apply 才動）",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="實際執行（預設 dry-run 只報告不動）",
    )
    parser.add_argument(
        "--home", default=str(Path.home()),
        help="home dir override（給 test 用）",
    )
    args = parser.parse_args()
    report = cleanup(Path(args.home), apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
