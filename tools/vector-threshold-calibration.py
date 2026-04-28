"""
vector-threshold-calibration.py — 議題 #6 Task A1 (Wave 3b 後續)

針對 /search/ranked-sections 的 chunk-level score 採樣，
跑 90 個 query（重用 vector-probe-burst.py 的 A_HIGH/B_MID/C_LOW 三 bucket），
以 min_score=0.40 取最寬鬆 candidate，retrospectively 評估在
threshold ∈ {0.50, 0.55, 0.60, 0.65, 0.70, 0.75} 各值的：
  - bucket-A in-domain 命中率
  - bucket-B 中間 命中率
  - bucket-C out-of-domain 噪音率
  - 平均 hit 數、最高 score

決策準則（事先寫死，避免事後憑感覺）：
  條件 1: bucket-C hit_rate(T) <= 10%
  條件 2: bucket-A hit_rate(T) >= baseline(0.50) - 5%
  兩條件同時滿足的最低 T 即定案；若無解 -> 退回 0.50。

語意對齊：searcher.py:282-283 與 372-373 兩處皆以 score = 1.0 - distance
與 min_score 比較，故本腳本以 sections[].score 為計算來源（不是 final_score）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
import importlib.util

_burst_path = THIS_DIR / "vector-probe-burst.py"
_spec = importlib.util.spec_from_file_location("vector_probe_burst", _burst_path)
_burst = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_burst)  # type: ignore[union-attr]

QUERIES_A_HIGH: List[str] = _burst.QUERIES_A_HIGH
QUERIES_B_MID: List[str] = _burst.QUERIES_B_MID
QUERIES_C_LOW: List[str] = _burst.QUERIES_C_LOW

ENDPOINT_BASE = "http://127.0.0.1:3849"
ENDPOINT_PATH = "/search/ranked-sections"
THRESHOLDS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
SLEEP_SEC = 0.20
TIMEOUT_SEC = 8.0


def fetch_section_scores(query: str) -> Dict[str, object]:
    qs = urllib.parse.urlencode({
        "q": query,
        "top_k": "5",
        "max_sections": "3",
        "min_score": "0.40",
        "intent": "general",
    })
    url = f"{ENDPOINT_BASE}{ENDPOINT_PATH}?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "section_scores": []}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "section_scores": []}

    scores: List[float] = []
    if isinstance(data, list):
        for atom in data:
            for sec in atom.get("sections", []) or []:
                sc = sec.get("score")
                if isinstance(sc, (int, float)):
                    scores.append(float(sc))
    return {"section_scores": scores, "atom_count": len(data) if isinstance(data, list) else 0}


def compute_bucket_stats(per_query: List[Dict]) -> Dict:
    size = len(per_query)
    zero_at_floor = sum(1 for r in per_query if not r.get("section_scores"))
    all_scores: List[float] = []
    for r in per_query:
        all_scores.extend(r.get("section_scores", []))
    max_score_overall = max(all_scores) if all_scores else 0.0

    thresholds_stats: Dict[str, Dict] = {}
    for t in THRESHOLDS:
        hits_per_query = []
        queries_with_any_hit = 0
        max_score_at_t = 0.0
        for r in per_query:
            scores = r.get("section_scores", [])
            n_hits = sum(1 for s in scores if s >= t)
            hits_per_query.append(n_hits)
            if n_hits > 0:
                queries_with_any_hit += 1
                m = max(s for s in scores if s >= t)
                if m > max_score_at_t:
                    max_score_at_t = m
        hit_rate = queries_with_any_hit / size if size else 0.0
        avg_hits = sum(hits_per_query) / size if size else 0.0
        thresholds_stats[f"{t:.2f}"] = {
            "hit_rate": round(hit_rate, 4),
            "avg_hits": round(avg_hits, 4),
            "max_score": round(max_score_at_t, 4),
            "queries_with_hits": queries_with_any_hit,
        }
    return {
        "size": size,
        "queries_with_zero_hits_at_0.40": zero_at_floor,
        "max_score_in_bucket": round(max_score_overall, 4),
        "thresholds": thresholds_stats,
    }


def run_bucket(label: str, queries: List[str], raw_out: List[Dict]) -> List[Dict]:
    print(f"[calib] bucket {label}: {len(queries)} queries", file=sys.stderr)
    per_query: List[Dict] = []
    for i, q in enumerate(queries, 1):
        result = fetch_section_scores(q)
        rec = {
            "bucket": label,
            "query": q,
            "section_scores": result.get("section_scores", []),
            "atom_count": result.get("atom_count", 0),
        }
        if "error" in result:
            rec["error"] = result["error"]
            print(f"[calib] {label}#{i} error: {result['error']} q={q!r}", file=sys.stderr)
        per_query.append(rec)
        raw_out.append(rec)
        if i % 10 == 0:
            print(f"[calib]   {label} progress {i}/{len(queries)}", file=sys.stderr)
        time.sleep(SLEEP_SEC)
    return per_query


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="/tmp/vector-calibration.json")
    args = ap.parse_args()

    try:
        with urllib.request.urlopen(f"{ENDPOINT_BASE}/health", timeout=3) as r:
            if r.status != 200:
                print(f"[calib] /health returned {r.status}", file=sys.stderr)
                return 2
    except Exception as e:  # noqa: BLE001
        print(f"[calib] service /health unreachable: {e}", file=sys.stderr)
        return 2

    raw_per_query: List[Dict] = []
    bucket_a = run_bucket("A_HIGH", QUERIES_A_HIGH, raw_per_query)
    bucket_b = run_bucket("B_MID", QUERIES_B_MID, raw_per_query)
    bucket_c = run_bucket("C_LOW", QUERIES_C_LOW, raw_per_query)

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "endpoint": ENDPOINT_PATH,
        "endpoint_params": {
            "top_k": 5,
            "max_sections": 3,
            "min_score_floor_used": 0.40,
            "intent": "general",
        },
        "thresholds_evaluated": THRESHOLDS,
        "buckets": {
            "A_HIGH": compute_bucket_stats(bucket_a),
            "B_MID": compute_bucket_stats(bucket_b),
            "C_LOW": compute_bucket_stats(bucket_c),
        },
        "raw_per_query": raw_per_query,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[calib] wrote {out} ({out.stat().st_size} bytes)")

    print("=" * 64)
    print("CALIBRATION SUMMARY (hit_rate per threshold)")
    print(f"  thresholds: {THRESHOLDS}")
    for name in ("A_HIGH", "B_MID", "C_LOW"):
        b = payload["buckets"][name]
        line = " ".join(
            f"{t}={b['thresholds'][t]['hit_rate']:.2f}"
            for t in (f"{x:.2f}" for x in THRESHOLDS)
        )
        print(f"  {name} (n={b['size']}, max={b['max_score_in_bucket']}): {line}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
