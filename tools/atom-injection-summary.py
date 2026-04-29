"""atom-injection-summary.py — REG-005 觀察期自動判定工具（Session 1 skeleton, 2026-04-29）.

讀 `~/.claude/Logs/atom-injection-observation-*.log` 與
`memory/wisdom/reflection_metrics.json` 的 `reg005_observation` 子鍵，
依「事件驅動四重標準」與自動止血條件決定 KEEP / ROLLBACK / GRAY / 未滿期。

事件驅動四重標準（期滿條件）：
  A. 累計 atom 注入數 ≥ 150
  B. 累計 session 數 ≥ 6
  C. 最低 wall clock 下限 ≥ 2 天
  D. 最高 wall clock 上限 ≤ 7 天（強制期滿）

自動止血條件（最低樣本門檻）：
  - hot 命中率 < 50%（hot 注入 ≥ 40）
  - cold 主動讀比率 < 5%（cold 注入 ≥ 40）
  - 命中錯失率 > 10%（總注入 ≥ 75）
  - 任一 atom 覆蓋率 0（wall_clock ≥ 5 天）

Session 1 skeleton：注入端 instrumentation 留待 Session 2 補（C-layer hot/cold
分級 + workflow-guardian 注入點寫 reg005_observation.injections 計數），
本工具骨架對缺資料情境輸出「未滿期 / 樣本不足」並指明缺哪段。

設計：memory/_staging/reg-005-atom-injection-refactor.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


CLAUDE_DIR = Path.home() / ".claude"
FLAG_PATH = CLAUDE_DIR / "memory" / "_staging" / "reg-005-observation-start.flag"
LOG_DIR = CLAUDE_DIR / "Logs"
METRIC_PATH = CLAUDE_DIR / "memory" / "wisdom" / "reflection_metrics.json"


# ─── thresholds ─────────────────────────────────────────────────────────────

A_INJECTIONS_REQ = 150
B_SESSIONS_REQ = 6
WALL_CLOCK_MIN_DAYS = 2.0
WALL_CLOCK_MAX_DAYS = 7.0

STOP_HOT_HIT_RATE = 0.50
STOP_COLD_READ_RATE = 0.05
STOP_MISS_RATE = 0.10
STOP_HOT_INJ_MIN = 40
STOP_COLD_INJ_MIN = 40
STOP_TOTAL_INJ_MIN = 75
STOP_COVERAGE_DAYS = 5.0


# ─── data loading ───────────────────────────────────────────────────────────


def _read_metric() -> Dict[str, Any]:
    try:
        with open(METRIC_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _read_log_records() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not LOG_DIR.exists():
        return records
    for log_path in sorted(LOG_DIR.glob("atom-injection-observation-*.log")):
        try:
            with open(log_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return records


# ─── decision logic ─────────────────────────────────────────────────────────


def _wall_clock_days(started_at: str) -> Optional[float]:
    if not started_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    delta = datetime.now() - start
    return delta.total_seconds() / 86400.0


def _decide(obs: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Return (verdict, details).

    verdict ∈ {"NOT_STARTED", "INCOMPLETE", "KEEP", "ROLLBACK", "GRAY"}
    """
    if not obs:
        return ("NOT_STARTED", {"reason": "metric reg005_observation 缺；觀察期未啟動"})

    started_at = str(obs.get("started_at") or "")
    wall_days = _wall_clock_days(started_at)
    injections = int(obs.get("injections", 0) or 0)
    sessions = int(obs.get("sessions", 0) or 0)
    reads_in_memory = int(obs.get("reads_in_memory", 0) or 0)
    cold_active_reads = int(obs.get("cold_active_reads", 0) or 0)
    hot_inj = int(obs.get("hot_injections", 0) or 0)
    cold_inj = int(obs.get("cold_injections", 0) or 0)
    hot_hits = int(obs.get("hot_hits", 0) or 0)
    miss_count = int(obs.get("hit_misses", 0) or 0)
    coverage_zero_atoms = list(obs.get("coverage_zero_atoms", []) or [])

    details: Dict[str, Any] = {
        "started_at": started_at,
        "wall_clock_days": round(wall_days, 2) if wall_days is not None else None,
        "A_injections": injections,
        "B_sessions": sessions,
        "reads_in_memory": reads_in_memory,
        "cold_active_reads": cold_active_reads,
        "hot_injections": hot_inj,
        "cold_injections": cold_inj,
        "hot_hits": hot_hits,
        "hit_misses": miss_count,
    }

    # ── auto-stop checks (with min sample gates) ─────────────────────────
    stops: List[str] = []
    if hot_inj >= STOP_HOT_INJ_MIN:
        rate = hot_hits / hot_inj
        if rate < STOP_HOT_HIT_RATE:
            stops.append(f"hot 命中率 {rate:.1%} < 50% (hot_inj={hot_inj})")
    if cold_inj >= STOP_COLD_INJ_MIN:
        rate = cold_active_reads / cold_inj
        if rate < STOP_COLD_READ_RATE:
            stops.append(f"cold 主動讀比率 {rate:.1%} < 5% (cold_inj={cold_inj})")
    if injections >= STOP_TOTAL_INJ_MIN and (miss_count / max(injections, 1)) > STOP_MISS_RATE:
        rate = miss_count / max(injections, 1)
        stops.append(f"命中錯失率 {rate:.1%} > 10% (total_inj={injections})")
    if wall_days is not None and wall_days >= STOP_COVERAGE_DAYS and coverage_zero_atoms:
        stops.append(f"零覆蓋 atoms：{coverage_zero_atoms[:5]}…（wall={wall_days:.1f}d）")

    if stops:
        details["stops"] = stops
        return ("ROLLBACK", details)

    # ── period-end gate ──────────────────────────────────────────────────
    if wall_days is None:
        return ("INCOMPLETE", {**details, "reason": "started_at 未設"})

    if wall_days >= WALL_CLOCK_MAX_DAYS:
        # 強制期滿
        if injections < A_INJECTIONS_REQ:
            details["note"] = f"樣本不足 (A={injections} < {A_INJECTIONS_REQ})；強制期滿，建議保守 KEEP 或延長觀察"
            return ("GRAY", details)
        return ("KEEP", details)

    if (
        injections >= A_INJECTIONS_REQ
        and sessions >= B_SESSIONS_REQ
        and wall_days >= WALL_CLOCK_MIN_DAYS
    ):
        return ("KEEP", details)

    # 未滿期
    needed: List[str] = []
    if injections < A_INJECTIONS_REQ:
        needed.append(f"A: {injections}/{A_INJECTIONS_REQ}")
    if sessions < B_SESSIONS_REQ:
        needed.append(f"B: {sessions}/{B_SESSIONS_REQ}")
    if wall_days < WALL_CLOCK_MIN_DAYS:
        needed.append(f"C: wall={wall_days:.2f}d/{WALL_CLOCK_MIN_DAYS}d")
    details["needed"] = needed
    return ("INCOMPLETE", details)


# ─── reporting ──────────────────────────────────────────────────────────────


def _fmt_text_report(verdict: str, details: Dict[str, Any], log_records: int) -> str:
    lines = [
        "═══ REG-005 atom-injection 觀察期自動判定 ═══",
        f"flag 存在：{FLAG_PATH.exists()}",
        f"log 紀錄總筆數：{log_records}",
        f"判定：{verdict}",
        "─── 細節 ───",
    ]
    for k, v in details.items():
        lines.append(f"  {k}: {v}")

    lines.append("")
    if verdict == "NOT_STARTED":
        lines.append("→ 觀察期尚未啟動。Session 2 收尾時 `touch reg-005-observation-start.flag` 開始。")
    elif verdict == "INCOMPLETE":
        lines.append("→ 觀察期進行中，未滿期。等四重標準達標後再判定。")
    elif verdict == "KEEP":
        lines.append("→ 期滿且四標準達標：保留 A+B+C+D 變更，REG-005 標 ✅ resolved。")
    elif verdict == "ROLLBACK":
        lines.append("→ 自動止血觸發：建議 git revert commit 1–4 + 寫失敗教訓進 _AIDocs/Failures/。")
    elif verdict == "GRAY":
        lines.append("→ 灰色地帶：諮詢使用者後再決定。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="REG-005 觀察期自動判定")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    ap.add_argument("--report", action="store_true", help="輸出文字報告（預設）")
    args = ap.parse_args()

    metric = _read_metric()
    obs = metric.get("reg005_observation") if isinstance(metric, dict) else None
    if not isinstance(obs, dict):
        obs = {}
    log_records = _read_log_records()
    verdict, details = _decide(obs)

    if args.json:
        print(json.dumps({
            "verdict": verdict,
            "details": details,
            "flag_active": FLAG_PATH.exists(),
            "log_records": len(log_records),
        }, ensure_ascii=False, indent=2))
    else:
        print(_fmt_text_report(verdict, details, len(log_records)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
