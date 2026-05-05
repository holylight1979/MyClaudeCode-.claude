#!/usr/bin/env python3
"""
wisdom_engine.py — Wisdom Engine V2.12

Two forces: Situation Classifier (hard rules), Reflection Engine (sliding window).
Called by workflow-guardian.py. Cold start = zero tokens.

V2.12 changes:
  - reflection_metrics.json schema: cumulative {correct,total} → sliding window
    of last `window_size` (=10) outcomes per task_type. window_size now actually
    used (V2.11 dead schema field activated).
  - Migration shim _migrate_v211_to_v212() preserves V2.11 cumulative values
    in `legacy_cumulative` for historical reference.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

WISDOM_DIR = Path.home() / ".claude" / "memory" / "wisdom"
REFLECTION_PATH = WISDOM_DIR / "reflection_metrics.json"

ARCH_KEYWORDS = {"架構", "refactor", "重構", "migrate", "migration", "重寫"}

SCHEMA_VERSION = "2.12"
DEFAULT_WINDOW_SIZE = 10


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


# ── Schema migration (V2.11 → V2.12) ────────────────────────────────────────

def _is_v211_cumulative(faa_bucket: Any) -> bool:
    """V2.11 buckets are {"correct": int, "total": int}; V2.12 are {"recent": [...]}."""
    if not isinstance(faa_bucket, dict):
        return False
    return "correct" in faa_bucket or "total" in faa_bucket


def _migrate_v211_to_v212(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotent migration. Preserves V2.11 cumulative as `legacy_cumulative`."""
    if metrics.get("schema_version") == SCHEMA_VERSION:
        return metrics

    legacy: Dict[str, Any] = {}
    m = metrics.setdefault("metrics", {})

    faa = m.get("first_approach_accuracy", {})
    if any(_is_v211_cumulative(v) for v in faa.values() if isinstance(v, dict)):
        legacy["first_approach_accuracy"] = faa
        m["first_approach_accuracy"] = {
            "single_file":  {"recent": []},
            "multi_file":   {"recent": []},
            "architecture": {"recent": []},
        }

    oe = m.get("over_engineering_rate", {})
    if "total_suggestions" in oe or "user_reverted_or_simplified" in oe:
        legacy["over_engineering_rate"] = oe
        m["over_engineering_rate"] = {"recent": []}

    sa = m.get("silence_accuracy", {})
    if "held_back_ok" in sa or "held_back_missed" in sa:
        legacy["silence_accuracy"] = sa
        m["silence_accuracy"] = {"recent": []}

    if legacy:
        legacy["frozen_at"] = datetime.now(timezone.utc).isoformat()
        metrics["legacy_cumulative"] = legacy
        # Clear stale V2.11 blind_spots (derived from now-archived cumulative);
        # next reflect() will recompute from sliding window.
        metrics["blind_spots"] = []

    metrics["schema_version"] = SCHEMA_VERSION
    metrics.setdefault("window_size", DEFAULT_WINDOW_SIZE)
    metrics.setdefault("blind_spots", [])
    metrics.setdefault("arch_sensitivity_elevated", False)
    return metrics


def _load_metrics() -> Dict[str, Any]:
    """Load + migrate. Single funnel for all readers/writers."""
    raw = _load_json(REFLECTION_PATH, _empty_reflection())
    if not isinstance(raw, dict):
        raw = _empty_reflection()
    return _migrate_v211_to_v212(raw)


def _append_sliding(lst: List[Any], item: Any, cap: int) -> List[Any]:
    """Append + trim to last `cap`."""
    lst.append(item)
    if len(lst) > cap:
        del lst[: len(lst) - cap]
    return lst


# ── Force 1: Situation Classifier (V2.11 hard rules, unchanged) ─────────────

def classify_situation(prompt_analysis: Dict[str, Any]) -> Dict[str, str]:
    """Hard rules → approach (direct/confirm/plan) + inject string."""
    keywords = set(prompt_analysis.get("keywords", []))
    file_count = prompt_analysis.get("estimated_files", 1)
    is_feature = prompt_analysis.get("intent", "") == "feature"
    touches_arch = bool(keywords & ARCH_KEYWORDS)

    metrics = _load_metrics()
    arch_elevated = metrics.get("arch_sensitivity_elevated", False)
    plan_threshold = 2 if arch_elevated else 3

    if touches_arch or file_count > plan_threshold:
        result = {"approach": "plan", "inject": "[情境:規劃] 架構級變更。行動：先 EnterPlanMode 列出影響範圍再動手"}
    elif file_count > 2 and is_feature:
        result = {"approach": "confirm", "inject": "[情境:確認] 跨檔修改。行動：先列出要修改的完整檔案清單確認再開始"}
    else:
        result = {"approach": "direct", "inject": ""}

    return result


# ── Force 2: Reflection Engine (V2.12 sliding window) ───────────────────────

def _empty_reflection() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "window_size": DEFAULT_WINDOW_SIZE,
        "metrics": {
            "first_approach_accuracy": {
                "single_file":  {"recent": []},
                "multi_file":   {"recent": []},
                "architecture": {"recent": []},
            },
            "over_engineering_rate": {"recent": []},
            "silence_accuracy": {"recent": []},
        },
        "arch_sensitivity_elevated": False,
        "blind_spots": [],
        "last_reflection": None,
    }


_BLIND_SPOT_ACTIONS = {
    "single_file": "行動：修改前先確認理解正確，避免假設",
    "multi_file": "行動：修改 >2 檔時先列清單確認範圍",
    "architecture": "行動：架構級任務先用 Plan Mode",
}


def _ratio(recent: List[Any], key: str = None) -> float:
    """Compute correct ratio from sliding window. None-safe."""
    if not recent:
        return 0.0
    if key is None:
        # list of bool
        return sum(1 for x in recent if x) / len(recent)
    # list of dict; sum where x[key] is truthy
    return sum(1 for x in recent if x.get(key)) / len(recent)


def get_reflection_summary() -> List[str]:
    """SessionStart: inject blind spot reminders with actionable guidance."""
    metrics = _load_metrics()
    faa = metrics.get("metrics", {}).get("first_approach_accuracy", {})
    lines = []
    for tt, b in faa.items():
        recent = b.get("recent", [])
        if len(recent) >= 3:
            rate = _ratio(recent)
            if rate < 0.7:
                action = _BLIND_SPOT_ACTIONS.get(tt, "")
                lines.append(f"[自知] {tt} 首次正確率 {rate:.0%}。{action}")
    return lines[:2]


def reflect(state: Dict[str, Any]) -> None:
    """SessionEnd: append outcomes to sliding windows + Bayesian calibration."""
    metrics = _load_metrics()
    window = int(metrics.get("window_size", DEFAULT_WINDOW_SIZE))
    m = metrics.setdefault("metrics", _empty_reflection()["metrics"])

    # ── Determine task type from wisdom_approach + modified_files ──
    approach = state.get("wisdom_approach", "direct")
    mod_files = state.get("modified_files", [])
    file_count = len(set(mf.get("path", "") for mf in mod_files))
    if approach == "plan":
        task_type = "architecture"
    elif file_count <= 1:
        task_type = "single_file"
    else:
        task_type = "multi_file"

    retry_count = int(state.get("wisdom_retry_count", 0))
    fix_escalation = bool(state.get("fix_escalation_triggered", False))

    # V2.12 commit-2 retry calibration:
    #   - architecture tasks: tolerate 1 retry (plan-mode iteration is by design),
    #     but fix_escalation_triggered overrides → real failure
    #   - other tasks: strict, retry_count == 0 means correct
    if task_type == "architecture":
        correct = (retry_count <= 1) and (not fix_escalation)
    else:
        correct = retry_count == 0

    # ── first_approach_accuracy.recent ──
    faa = m.setdefault("first_approach_accuracy", {})
    bucket = faa.setdefault(task_type, {"recent": []})
    bucket.setdefault("recent", [])
    _append_sliding(bucket["recent"], bool(correct), window)

    # ── over_engineering_rate.recent: True = retry occurred this session ──
    oe = m.setdefault("over_engineering_rate", {"recent": []})
    oe.setdefault("recent", [])
    _append_sliding(oe["recent"], bool(retry_count > 0), window)

    # ── silence_accuracy.recent: only tracked when approach == direct ──
    sa = m.setdefault("silence_accuracy", {"recent": []})
    sa.setdefault("recent", [])
    if approach == "direct":
        _append_sliding(
            sa["recent"],
            {"approach": "direct", "ok": bool(correct)},
            window,
        )

    # ── Blind spot detection (sliding window) ──
    blind_spots = []
    for tt, b in faa.items():
        recent = b.get("recent", [])
        if len(recent) >= 3:
            rate = _ratio(recent)
            if rate < 0.7:
                blind_spots.append(f"{tt} 首次正確率 {rate:.0%}")
    metrics["blind_spots"] = blind_spots

    # ── Bayesian: arch sensitivity (sliding window) ──
    arch_recent = faa.get("architecture", {}).get("recent", [])
    if len(arch_recent) >= 3:
        rate = _ratio(arch_recent)
        if rate < 0.34:
            metrics["arch_sensitivity_elevated"] = True
        elif rate >= 0.5:
            metrics["arch_sensitivity_elevated"] = False

    metrics["last_reflection"] = datetime.now(timezone.utc).isoformat()
    _save_json(REFLECTION_PATH, metrics)


def _is_plan_iteration_path(norm_path: str) -> bool:
    """計畫迭代路徑：plans/、_staging/、檔名命中 plan/draft/roadmap/wip 等規劃詞。

    這些檔案的多次編輯是「計畫演化」而非「錯誤修復重試」，不應計入 retry。
    """
    if "/plans/" in norm_path or "/_staging/" in norm_path:
        return True
    try:
        from wg_content_classify import is_plan_filename
    except ImportError:
        return False
    fname = norm_path.rsplit("/", 1)[-1] if "/" in norm_path else norm_path
    return is_plan_filename(fname)


def track_retry(state: Dict[str, Any], file_path: str) -> None:
    """PostToolUse: count repeated edits to the same file as retries.

    Plan-type files are excluded — multiple edits to a plan are iteration,
    not error retry, and should not trigger Fix Escalation Protocol.

    V2.12: plan-mode sessions raise the threshold (4 same-file edits before
    counting as retry). Rationale: architecture-level work iterates on the
    same file by design; the V2.11 threshold of 2 systematically penalised
    arch tasks, dragging architecture first-approach accuracy to 13%.
    """
    norm = file_path.replace("\\", "/")
    if _is_plan_iteration_path(norm):
        return
    edits = state.get("modified_files", [])
    count = sum(1 for m in edits if m.get("path", "").replace("\\", "/") == norm)

    approach = state.get("wisdom_approach", "direct")
    threshold = 4 if approach == "plan" else 2

    if count >= threshold:
        state["wisdom_retry_count"] = state.get("wisdom_retry_count", 0) + 1
        # V2.11: 只更新 state 計數，由 SessionEnd reflect() 統一寫入 reflection_metrics
