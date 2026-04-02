#!/usr/bin/env python3
"""
wisdom_engine.py — Wisdom Engine V2.11

Two forces: Situation Classifier (hard rules), Reflection Engine (enhanced).
Called by workflow-guardian.py. Cold start = zero tokens.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

WISDOM_DIR = Path.home() / ".claude" / "memory" / "wisdom"
REFLECTION_PATH = WISDOM_DIR / "reflection_metrics.json"

ARCH_KEYWORDS = {"架構", "refactor", "重構", "migrate", "migration", "重寫"}


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
    except OSError as e:
        print(f"[wisdom] save error {path.name}: {e}", file=sys.stderr)
        if tmp.exists():
            tmp.unlink()


# ── Force 1: Situation Classifier (V2.11 hard rules) ────────────────────────

def classify_situation(prompt_analysis: Dict[str, Any]) -> Dict[str, str]:
    """Hard rules → approach (direct/confirm/plan) + inject string."""
    keywords = set(prompt_analysis.get("keywords", []))
    file_count = prompt_analysis.get("estimated_files", 1)
    is_feature = prompt_analysis.get("intent", "") == "feature"
    touches_arch = bool(keywords & ARCH_KEYWORDS)

    # Bayesian: arch sensitivity elevation lowers plan threshold
    metrics = _load_json(REFLECTION_PATH, {})
    arch_elevated = metrics.get("arch_sensitivity_elevated", False)
    plan_threshold = 2 if arch_elevated else 3

    if touches_arch or file_count > plan_threshold:
        result = {"approach": "plan", "inject": "[情境:規劃] 架構級變更。行動：先 EnterPlanMode 列出影響範圍再動手"}
    elif file_count > 2 and is_feature:
        result = {"approach": "confirm", "inject": "[情境:確認] 跨檔修改。行動：先列出要修改的完整檔案清單確認再開始"}
    else:
        result = {"approach": "direct", "inject": ""}

    # V2.11: _last_approach removed — approach is now persisted in
    # state["wisdom_approach"] by the caller (workflow-guardian.py).
    return result


# ── Force 2: Reflection Engine (V2.11 enhanced) ─────────────────────────────

def _empty_reflection() -> Dict[str, Any]:
    return {
        "window_size": 10,
        "metrics": {
            "first_approach_accuracy": {
                "single_file": {"correct": 0, "total": 0},
                "multi_file": {"correct": 0, "total": 0},
                "architecture": {"correct": 0, "total": 0},
            },
            "over_engineering_rate": {
                "user_reverted_or_simplified": 0, "total_suggestions": 0,
            },
            "silence_accuracy": {
                "held_back_ok": 0,
                "held_back_missed": 0,
            },
        },
        "arch_sensitivity_elevated": False,
        "blind_spots": [],
        "last_reflection": None,
    }


# V3.1: 自描述行動指令，依 task_type 分支
_BLIND_SPOT_ACTIONS = {
    "single_file": "行動：修改前先確認理解正確，避免假設",
    "multi_file": "行動：修改 >2 檔時先列清單確認範圍",
    "architecture": "行動：架構級任務先用 Plan Mode",
}


def get_reflection_summary() -> List[str]:
    """SessionStart: inject blind spot reminders with actionable guidance."""
    metrics = _load_json(REFLECTION_PATH, {})
    faa = metrics.get("metrics", {}).get("first_approach_accuracy", {})
    lines = []
    for tt, b in faa.items():
        total = b.get("total", 0)
        correct = b.get("correct", 0)
        if total >= 3:
            rate = correct / total
            if rate < 0.7:
                action = _BLIND_SPOT_ACTIONS.get(tt, "")
                lines.append(f"[自知] {tt} 首次正確率 {rate:.0%}。{action}")
    return lines[:2]


def reflect(state: Dict[str, Any]) -> None:
    """SessionEnd: update accuracy stats, silence accuracy, Bayesian calibration."""
    metrics = _load_json(REFLECTION_PATH, _empty_reflection())
    m = metrics.setdefault("metrics", _empty_reflection()["metrics"])
    faa = m.setdefault("first_approach_accuracy", {})

    # ── first_approach_accuracy ──
    # 用 Wisdom classify_situation 的結果判定任務類型，而非純看檔案數
    approach = state.get("wisdom_approach", "direct")
    mod_files = state.get("modified_files", [])
    file_count = len(set(m_item.get("path", "") for m_item in mod_files))
    if approach == "plan":
        task_type = "architecture"
    elif file_count <= 1:
        task_type = "single_file"
    else:
        task_type = "multi_file"

    bucket = faa.setdefault(task_type, {"correct": 0, "total": 0})
    bucket["total"] += 1
    retry_count = state.get("wisdom_retry_count", 0)
    if retry_count == 0:
        bucket["correct"] += 1

    # ── over_engineering_rate: total_suggestions +1 per session ──
    oe = m.setdefault("over_engineering_rate",
         {"user_reverted_or_simplified": 0, "total_suggestions": 0})
    oe["total_suggestions"] += 1

    # ── silence_accuracy (V2.11) ──
    sa = m.setdefault("silence_accuracy", {"held_back_ok": 0, "held_back_missed": 0})
    # 遷移舊 key（held_back_and_user_didnt_ask → held_back_ok 等）
    if "held_back_ok" not in sa:
        sa["held_back_ok"] = sa.pop("held_back_and_user_didnt_ask", 0)
        sa["held_back_missed"] = sa.pop("held_back_but_user_needed", 0)
        sa.pop("spoke_but_user_ignored", None)
    # 用 state 保存的 approach（跨 process 持久），不用 module-level _last_approach
    session_approach = approach  # 已從 state["wisdom_approach"] 取得
    if session_approach == "direct":
        if retry_count == 0:
            sa["held_back_ok"] += 1
        else:
            sa["held_back_missed"] += 1

    # ── Blind spot detection ──
    blind_spots = []
    for tt, b in faa.items():
        total = b.get("total", 0)
        correct = b.get("correct", 0)
        if total >= 3:
            rate = correct / total
            if rate < 0.7:
                blind_spots.append(f"{tt} 首次正確率 {rate:.0%}")
    metrics["blind_spots"] = blind_spots

    # ── Bayesian: architecture sensitivity calibration (V2.11) ──
    arch = faa.get("architecture", {"correct": 0, "total": 0})
    if arch["total"] >= 3 and arch["correct"] / max(arch["total"], 1) < 0.34:
        metrics["arch_sensitivity_elevated"] = True
    elif arch["total"] >= 3 and arch["correct"] / max(arch["total"], 1) >= 0.5:
        metrics["arch_sensitivity_elevated"] = False

    metrics["last_reflection"] = datetime.now(timezone.utc).isoformat()
    _save_json(REFLECTION_PATH, metrics)


def track_retry(state: Dict[str, Any], file_path: str) -> None:
    """PostToolUse: count repeated edits to the same file as retries."""
    edits = state.get("modified_files", [])
    norm = file_path.replace("\\", "/")
    count = sum(1 for m in edits if m.get("path", "").replace("\\", "/") == norm)
    if count >= 2:
        state["wisdom_retry_count"] = state.get("wisdom_retry_count", 0) + 1
        # V2.11: 只更新 state 計數，由 SessionEnd reflect() 統一寫入 reflection_metrics
        # （避免 PostToolUse 與 SessionEnd 雙寫 JSON 競爭）
