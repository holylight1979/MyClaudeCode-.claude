"""wg_codex_companion_phase6.py — Sprint 5.5 B2.

Phase 6 自適應 Gate 觸發條件檢查 hook。

由 Workflow Guardian SessionStart 呼叫；載入 reflection_metrics.json 與
companion-assessment-*.json，對 plans/sprint5-eval-2026-04-27.md §四 的
C1-C5 條件跑 if-check，命中且未在 dedup `last_fired` 集合內則返回 inject
字串給 SessionStart additionalContext。

Source of truth：plans/sprint5-eval-2026-04-27.md §四（machine-checkable
觸發條件）。本 hook 必須與該檔精確同步；若條件閾值改動須一併更新此檔。

Dedup 策略：
- last_fired_conditions：上次評估時命中的條件 ID 集合
- 本次命中且不在 last_fired → 觸發
- 命中已在 last_fired → 忽略（user 已看過）
- 上次命中、本次未命中 → 從 last_fired 移除（下次再 met 會重新觸發）

不依賴時間。完全由樣本累積/變化驅動 — 這是「user 不需主動記」的核心。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CLAUDE_DIR = Path.home() / ".claude"
WORKFLOW_DIR = CLAUDE_DIR / "workflow"
REFLECTION_PATH = CLAUDE_DIR / "memory" / "wisdom" / "reflection_metrics.json"


# ─── reflection_metrics.json IO ───────────────────────────────────────


def _load_reflection() -> Dict[str, Any]:
    try:
        return json.loads(REFLECTION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_reflection(data: Dict[str, Any]) -> None:
    """Atomic write；reflection_metrics.json 不存在時 silent skip 避免主動建檔。"""
    if not REFLECTION_PATH.exists():
        return
    try:
        tmp = REFLECTION_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(REFLECTION_PATH)
    except OSError:
        pass


# ─── Assessment glob — 過濾 test fixture ──────────────────────────────


def _glob_real_assessments() -> List[Path]:
    """過濾 test fixture：路徑含 'test-sprint' / 'smoke' 視為測試殘留。

    真實 session_id 為 UUID 形式（例 b0b4f9e6-27df-...），不會撞到 test- prefix。
    """
    paths = list(WORKFLOW_DIR.glob("companion-assessment-*.json"))
    return [
        p for p in paths
        if not any(tok in p.name for tok in ("test-sprint", "smoke"))
    ]


# ─── §四 C1-C5 條件評估 ────────────────────────────────────────────────


_CONDITION_ACTIONS: Dict[str, str] = {
    "C1": "觸發 Phase 6 ok_streak 完整評估（樣本量達統計可解讀下限）",
    "C2": "即刻修 — R2-5 級規格回歸，立即查 codex CLI / PATH 環境（不累積）",
    "C3": "調 workflow/config.json.codex_companion.score_threshold 從 4 → 3 重跑觀察期",
    "C4": "BLOCK 規則失靈或場景不需 BLOCK；考慮把 confident_completion_without_evidence 降為 advisory",
    "C5": "drain 失效；排查 hooks/codex_companion.py:226-275 UserPromptSubmit handler",
}


def _eval_conditions(
    sessions: List[Dict[str, Any]],
    assessments: List[Path],
) -> Dict[str, Tuple[bool, str]]:
    """跑 §四 C1-C5。回傳 {cond_id: (met, evidence_str)}。

    所有條件直接對映 plans/sprint5-eval-2026-04-27.md §四 表格 pseudo-code。
    """
    results: Dict[str, Tuple[bool, str]] = {}

    # C1: len(S) >= 10
    s_count = len(sessions)
    results["C1"] = (s_count >= 10, f"sessions={s_count} (need>=10)")

    # C2: any sandbox_failures > 0
    sandbox_total = sum(int(s.get("sandbox_failures", 0)) for s in sessions)
    results["C2"] = (sandbox_total > 0, f"sandbox_failures total={sandbox_total}")

    # C3: skipped / max(1, total_attempted) > 0.7
    skipped = sum(int(s.get("audits_skipped_by_score", 0)) for s in sessions)
    attempted = sum(int(s.get("audits_total_attempted", 0)) for s in sessions)
    ratio = skipped / max(1, attempted)
    results["C3"] = (
        ratio > 0.7,
        f"skipped={skipped} attempted={attempted} ratio={ratio:.2f} (need>0.7)",
    )

    # C4: len(S) >= 5 and last 5 all behavior_gap_blocks==0 and any quality_gap_advises>0
    if s_count >= 5:
        last5 = sessions[-5:]
        all_blocks_zero = all(int(s.get("behavior_gap_blocks", 0)) == 0 for s in last5)
        any_advise = any(int(s.get("quality_gap_advises", 0)) > 0 for s in last5)
        c4_met = all_blocks_zero and any_advise
        c4_ev = f"last5 all_blocks_zero={all_blocks_zero} any_advise={any_advise}"
    else:
        c4_met = False
        c4_ev = f"sessions={s_count} (need>=5)"
    results["C4"] = (c4_met, c4_ev)

    # C5: len(A) >= 20 and injected_ratio < 0.3
    a_count = len(assessments)
    if a_count >= 20:
        injected_count = 0
        for p in assessments:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("injected"):
                    injected_count += 1
            except (OSError, json.JSONDecodeError):
                pass
        injected_ratio = injected_count / a_count
        c5_met = injected_ratio < 0.3
        c5_ev = (
            f"assessments={a_count} injected={injected_count} "
            f"ratio={injected_ratio:.2f} (need<0.3)"
        )
    else:
        c5_met = False
        c5_ev = f"assessments={a_count} (need>=20)"
    results["C5"] = (c5_met, c5_ev)

    return results


# ─── Public API ──────────────────────────────────────────────────────


def get_session_start_inject() -> Optional[str]:
    """SessionStart 入口：返回 inject 字串給 additionalContext，
    若無條件命中或全部已 dedup 則返回 None。

    副作用：把當前 currently_met 寫回 reflection_metrics.json
    `codex_companion.phase6_trigger_state` 作為 dedup 來源。
    """
    data = _load_reflection()
    cc = data.get("codex_companion") or {}
    sessions = cc.get("sessions") or []
    assessments = _glob_real_assessments()

    cond_results = _eval_conditions(sessions, assessments)
    currently_met = [c for c, (met, _) in cond_results.items() if met]

    state = cc.get("phase6_trigger_state") or {}
    last_fired = set(state.get("last_fired") or [])
    new_fires = [c for c in currently_met if c not in last_fired]

    # 更新 dedup state — 即使無新觸發也要 sync currently_met，否則
    # 「上次命中、本次未命中 → 應從 last_fired 移除」語意失效
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_state = {
        "last_fired": currently_met,
        "last_check_S_count": len(sessions),
        "last_check_A_count": len(assessments),
        "last_check_ts": now,
        "last_trigger_ts": now if new_fires else state.get("last_trigger_ts"),
    }
    cc["phase6_trigger_state"] = new_state
    data["codex_companion"] = cc
    _save_reflection(data)

    if not new_fires:
        return None

    lines = ["[Phase6Trigger] Sprint 5 觀察期觸發條件達成，建議執行對應動作："]
    for cid in new_fires:
        _, evidence = cond_results[cid]
        action = _CONDITION_ACTIONS.get(cid, "(未定義動作)")
        lines.append(f"  • {cid} 命中（{evidence}）→ {action}")
    lines.append("詳：plans/sprint5-eval-2026-04-27.md §四")
    return "\n".join(lines)
