"""
vector-observation-summary.py — Wave 3a 4-day observation analyzer

讀 ~/.claude/Logs/vector-observation*.log（含 rotated backups + probe sibling），
統計 vector 命中率 / fallback 比例 / per-fn 分布，自動判定：
  - 修活（vector 命中率 ≥ 50%）
  - 淘汰（命中率 ≤ 5% 且 fallback ≥ 80%）
  - 灰色（5–15%）→ 列代表樣本給使用者裁決

用法：
  python tools/vector-observation-summary.py [--days 4] [--verbose]

不依賴使用者主訴；純 log 採樣自動判定。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterator, List, Optional

CLAUDE_DIR = Path.home() / ".claude"
LOGS_DIR = CLAUDE_DIR / "Logs"
MAIN_LOG_GLOB = "vector-observation.log*"   # main + rotated .1 .2 .3
PROBE_LOG_GLOB = "vector-observation-probe.log"


def _iter_records(days: int) -> Iterator[Dict]:
    """Yield JSON records from main + probe logs newer than `days` days."""
    cutoff = time.time() - days * 86400
    files: List[Path] = []
    if LOGS_DIR.exists():
        files.extend(sorted(LOGS_DIR.glob(MAIN_LOG_GLOB)))
        files.extend(sorted(LOGS_DIR.glob(PROBE_LOG_GLOB)))
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    ts = rec.get("ts", 0)
                    try:
                        if float(ts) < cutoff:
                            continue
                    except (TypeError, ValueError):
                        continue
                    yield rec
        except OSError:
            continue


def analyze(days: int) -> Dict:
    total = 0
    by_fn: Counter = Counter()
    by_flag: Counter = Counter()
    vec_hit = 0          # ready + result_count > 0 + not fallback
    vec_miss = 0         # ready + result_count == 0
    fallback_total = 0   # fallback_used == True OR flag_state != ready
    error_count = 0
    probe_records: List[Dict] = []
    fn_flag: Dict[str, Counter] = defaultdict(Counter)
    sample_zero: List[Dict] = []  # ready but 0 results — gray-zone samples

    for rec in _iter_records(days):
        total += 1
        fn = rec.get("fn", "?")
        flag = rec.get("flag_state", "?")
        rc = rec.get("result_count", 0)
        fb = bool(rec.get("fallback_used", False))
        try:
            rc = int(rc)
        except (TypeError, ValueError):
            rc = 0
        by_fn[fn] += 1
        by_flag[flag] += 1
        fn_flag[fn][flag] += 1
        if fn == "session_start_probe":
            probe_records.append(rec)

        if flag == "error":
            error_count += 1
            fallback_total += 1
            continue
        if flag != "ready" or fb:
            fallback_total += 1
            continue
        if fn == "session_start_probe":
            if rc > 0:
                vec_hit += 1
            else:
                vec_miss += 1
                if len(sample_zero) < 5:
                    sample_zero.append(rec)
        else:
            if rc > 0:
                vec_hit += 1
            else:
                vec_miss += 1
                if len(sample_zero) < 5:
                    sample_zero.append(rec)

    denom = max(vec_hit + vec_miss, 1)
    hit_rate = vec_hit / denom
    fallback_rate = fallback_total / max(total, 1)

    if hit_rate >= 0.50:
        verdict = "REVIVE"
        rationale = f"vector hit rate {hit_rate:.1%} ≥ 50% → vector subsystem 有實質價值，建議修活"
    elif hit_rate <= 0.05 and fallback_rate >= 0.80:
        verdict = "RETIRE"
        rationale = (
            f"vector hit rate {hit_rate:.1%} ≤ 5% 且 fallback rate {fallback_rate:.1%} ≥ 80% "
            f"→ 12 天 silent fail 期間使用者實際工作流不依賴 vector，建議淘汰"
        )
    elif 0.05 < hit_rate < 0.15:
        verdict = "GRAY"
        rationale = (
            f"vector hit rate {hit_rate:.1%}（5–15% 灰色地帶）→ 需使用者裁決："
            f"修活 ROI 邊際 vs 淘汰減少 hook 複雜度"
        )
    else:
        verdict = "GRAY"
        rationale = (
            f"hit rate {hit_rate:.1%}, fallback {fallback_rate:.1%} 不在明確閾值區間"
            f" → 需使用者參考樣本後決定"
        )

    return {
        "days": days,
        "total_records": total,
        "by_fn": dict(by_fn),
        "by_flag": dict(by_flag),
        "fn_x_flag": {k: dict(v) for k, v in fn_flag.items()},
        "vector_hit": vec_hit,
        "vector_miss": vec_miss,
        "fallback_total": fallback_total,
        "error_count": error_count,
        "hit_rate": round(hit_rate, 4),
        "fallback_rate": round(fallback_rate, 4),
        "probe_count": len(probe_records),
        "verdict": verdict,
        "rationale": rationale,
        "sample_zero_results": sample_zero,
    }


def fmt_human(report: Dict) -> str:
    lines: List[str] = []
    lines.append(f"# Vector Observation Summary (last {report['days']} days)")
    lines.append("")
    lines.append(f"- 總紀錄：{report['total_records']}")
    lines.append(f"- vector 命中：{report['vector_hit']}")
    lines.append(f"- vector miss（ready 但 0 結果）：{report['vector_miss']}")
    lines.append(f"- fallback 總數：{report['fallback_total']}")
    lines.append(f"- error：{report['error_count']}")
    lines.append(f"- **命中率：{report['hit_rate']:.1%}** | fallback rate：{report['fallback_rate']:.1%}")
    lines.append(f"- session_start_probe 次數：{report['probe_count']}")
    lines.append("")
    lines.append("## per-fn 分布")
    for fn, n in sorted(report["by_fn"].items(), key=lambda x: -x[1]):
        lines.append(f"- {fn}: {n}")
    lines.append("")
    lines.append("## per-flag 分布")
    for flag, n in sorted(report["by_flag"].items(), key=lambda x: -x[1]):
        lines.append(f"- {flag}: {n}")
    lines.append("")
    lines.append(f"## 自動判定：**{report['verdict']}**")
    lines.append(f"{report['rationale']}")
    if report["verdict"] == "GRAY" and report["sample_zero_results"]:
        lines.append("")
        lines.append("### 灰色地帶樣本（前 5 筆 ready 但 0 結果）")
        for s in report["sample_zero_results"]:
            extra = {k: v for k, v in s.items() if k not in ("ts", "session_id", "fn", "flag_state", "result_count", "fallback_used")}
            lines.append(f"- fn={s.get('fn')} extra={extra}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=4)
    p.add_argument("--json", action="store_true", help="output raw JSON")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    if not LOGS_DIR.exists():
        sys.stderr.write(f"[warn] {LOGS_DIR} not found — no observations yet\n")
        report = analyze(args.days)  # will yield empty
    else:
        report = analyze(args.days)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(fmt_human(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
