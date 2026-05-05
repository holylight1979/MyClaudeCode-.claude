"""merge-orphan-access.py — 一次性合併 memory/ 根目錄的錯位/孤兒 access.json

背景：
  Wave 2 把 atom .md 搬入 memory/feedback/ 子資料夾、且在新位置建立了
  v2 schema 的 access.json，但根目錄留下了 legacy 副本（多半只有 timestamps
  欄位）。另有 4 個 atom 在某次重命名中換了名字、舊 access.json 變孤兒；
  以及 1 個 atom（mail-sorting）已完全刪除、access.json 純殘骸。

行為：
  - 讀預定義對映表（9 對合併 + 1 個 DELETE_UNCONDITIONAL）
  - 對每對：normalize src → 對 dst 套用 max(read_hits/confirmations/last_used/
    last_promoted_at) + min(first_seen) + timestamps 聯集去重取最新 50 +
    confirmation_events 時間排序聯集
  - --apply 才真寫；預設 dry-run 只列差異
  - 走 lib.atom_access._write_raw（原子寫 + cross-process 重試）+
    lib.atom_io._audit_log（op=access_merge / access_delete_orphan，
    source=tool:memory-cleanup）

冪等：
  - --apply 跑兩次：第二次每對的 src 已不存在，整支 SKIP

Active session guard：
  - 跑 --apply 前讀 memory/_workflow_state.json；phase != idle 拒跑

呼叫：
  python scripts/merge-orphan-access.py            # dry-run
  python scripts/merge-orphan-access.py --apply    # 實際合併 + git rm
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent  # ~/.claude
sys.path.insert(0, str(ROOT))

from lib.atom_access import (  # noqa: E402
    _normalize, _read_raw, _write_raw, TIMESTAMPS_MAX,
)
from lib.atom_io import _audit_log, _gen_audit_id  # noqa: E402

MEMORY_DIR = ROOT / "memory"

DELETE_UNCONDITIONAL = "__DELETE_UNCONDITIONAL__"

# (src_basename, dst_basename_or_DELETE_UNCONDITIONAL, kind)
MAPPING: List[Tuple[str, str, str]] = [
    # Phase A: 5 個錯位 access（atom .md 已在 feedback/，root access 是落單副本）
    ("feedback-decision-no-tech-menu.access.json",
     "feedback/feedback-decision-no-tech-menu.access.json", "misplaced"),
    ("feedback-git-log-chinese.access.json",
     "feedback/feedback-git-log-chinese.access.json", "misplaced"),
    ("feedback-memory-path.access.json",
     "feedback/feedback-memory-path.access.json", "misplaced"),
    ("feedback-no-outsource-rigor.access.json",
     "feedback/feedback-no-outsource-rigor.access.json", "misplaced"),
    ("feedback-no-test-to-svn.access.json",
     "feedback/feedback-no-test-to-svn.access.json", "misplaced"),
    # Phase B: 4 個重命名孤兒 + 1 個無對應 atom（mail-sorting）
    ("feedback-handoff.access.json",
     "feedback/feedback-handoff-self-sufficient.access.json", "rename"),
    ("feedback-research.access.json",
     "feedback/feedback-research-first.access.json", "rename"),
    ("feedback-scope-sensitive.access.json",
     "feedback/feedback-scope-sensitive-values.access.json", "rename"),
    ("fix-escalation.access.json",
     "feedback/feedback-fix-escalation.access.json", "rename"),
    ("mail-sorting.access.json", DELETE_UNCONDITIONAL, "delete"),
]


# ─── 合併規則 ────────────────────────────────────────────────────────────────


def _str_max(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """ISO 日期字串 max；None 視為較小。"""
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _str_min(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """ISO 日期字串 min；None 視為較大（讓非 None 勝出）。"""
    if a is None:
        return b
    if b is None:
        return a
    return a if a <= b else b


def merge_access(src: Dict[str, Any], dst: Dict[str, Any]) -> Dict[str, Any]:
    """合併 src + dst → 新 dst dict。src/dst 必須先 normalize。"""
    merged = dict(dst)  # base
    merged["read_hits"] = max(int(src.get("read_hits") or 0),
                              int(dst.get("read_hits") or 0))
    merged["confirmations"] = max(int(src.get("confirmations") or 0),
                                  int(dst.get("confirmations") or 0))
    merged["last_used"] = _str_max(src.get("last_used"), dst.get("last_used"))
    merged["last_promoted_at"] = _str_max(
        src.get("last_promoted_at"), dst.get("last_promoted_at"),
    )
    merged["first_seen"] = _str_min(
        src.get("first_seen"), dst.get("first_seen"),
    )
    src_ts = list(src.get("timestamps") or [])
    dst_ts = list(dst.get("timestamps") or [])
    union_ts = sorted(set(src_ts + dst_ts))[-TIMESTAMPS_MAX:]
    merged["timestamps"] = union_ts
    src_ev = list(src.get("confirmation_events") or [])
    dst_ev = list(dst.get("confirmation_events") or [])
    merged["confirmation_events"] = sorted(
        src_ev + dst_ev,
        key=lambda e: e.get("ts", "") if isinstance(e, dict) else "",
    )
    return merged


# ─── Active session guard（與 migrate-access-stats.py 同邏輯） ────────────────


def check_active_session() -> Tuple[bool, str]:
    state_file = MEMORY_DIR / "_workflow_state.json"
    if not state_file.exists():
        return False, ""
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        phase = data.get("phase")
        if phase and phase != "idle":
            sid = data.get("session_id", "")
            return True, f"phase={phase} session={sid}"
    except (OSError, json.JSONDecodeError):
        pass
    return False, ""


# ─── src 刪除 helper ────────────────────────────────────────────────────────
#
# 重要：memory/**/*.access.json 已被 .gitignore:55 排除，全部是 untracked
# 本機遙測檔；不需要（也無法）git rm。直接 unlink 即可。原計畫寫 git rm
# 是 plan defect，實作改用 filesystem unlink + audit log 標記 untracked。


def _unlink_src(path: Path) -> bool:
    """unlink <path>；回傳 True=成功，False=失敗。"""
    try:
        path.unlink()
        return True
    except OSError as e:
        print(f"  [WARN] unlink failed for {path}: {e}", file=sys.stderr)
        return False


# ─── Diff 摘要 ───────────────────────────────────────────────────────────────


def _diff_summary(src: Dict[str, Any], dst: Dict[str, Any],
                  merged: Dict[str, Any]) -> List[str]:
    out = []
    for f in ("read_hits", "confirmations", "last_used",
              "last_promoted_at", "first_seen"):
        s = src.get(f)
        d = dst.get(f)
        m = merged.get(f)
        if s != d or m != d:
            out.append(f"    {f}: src={s!r} dst={d!r} → {m!r}")
    s_ts = len(src.get("timestamps") or [])
    d_ts = len(dst.get("timestamps") or [])
    m_ts = len(merged.get("timestamps") or [])
    out.append(f"    timestamps: src={s_ts} dst={d_ts} → merged={m_ts}")
    s_ev = len(src.get("confirmation_events") or [])
    d_ev = len(dst.get("confirmation_events") or [])
    m_ev = len(merged.get("confirmation_events") or [])
    if s_ev or d_ev:
        out.append(f"    confirmation_events: src={s_ev} dst={d_ev} → merged={m_ev}")
    return out


# ─── 主流程 ──────────────────────────────────────────────────────────────────


def process_pair(src_rel: str, dst_rel: str, kind: str,
                 apply: bool) -> Dict[str, Any]:
    """處理一對（合併/搬遷/刪除）。回傳 stats dict。"""
    src_path = MEMORY_DIR / src_rel
    stats = {"src": src_rel, "dst": dst_rel, "kind": kind,
             "action": "skip", "reason": ""}

    if not src_path.exists():
        stats["reason"] = "src missing (idempotent skip)"
        return stats

    # Mode 1: DELETE_UNCONDITIONAL
    if dst_rel == DELETE_UNCONDITIONAL:
        stats["action"] = "delete"
        if apply:
            if _unlink_src(src_path):
                _audit_log({
                    "audit_id": _gen_audit_id(),
                    "op": "access_delete_orphan",
                    "source": "tool:memory-cleanup",
                    "path": str(src_path),
                    "kind": kind,
                })
            else:
                stats["reason"] = "unlink failed"
        return stats

    dst_path = MEMORY_DIR / dst_rel

    # Mode 2: dst 不存在 → 直接搬遷（normalize 後 _write_raw 到 dst）
    src_raw = _read_raw(src_path) or {}
    src_norm, _ = _normalize(src_raw)

    if not dst_path.exists():
        stats["action"] = "move"
        if apply:
            ok = _write_raw(dst_path, src_norm)
            if not ok:
                stats["reason"] = "_write_raw failed"
                return stats
            if _unlink_src(src_path):
                _audit_log({
                    "audit_id": _gen_audit_id(),
                    "op": "access_merge",
                    "source": "tool:memory-cleanup",
                    "src": str(src_path),
                    "dst": str(dst_path),
                    "kind": kind,
                    "mode": "move_no_dst",
                })
        return stats

    # Mode 3: 合併
    dst_raw = _read_raw(dst_path) or {}
    dst_norm, _ = _normalize(dst_raw)
    merged = merge_access(src_norm, dst_norm)
    stats["action"] = "merge"
    stats["diff"] = _diff_summary(src_norm, dst_norm, merged)
    if apply:
        ok = _write_raw(dst_path, merged)
        if not ok:
            stats["reason"] = "_write_raw failed"
            return stats
        if _unlink_src(src_path):
            _audit_log({
                "audit_id": _gen_audit_id(),
                "op": "access_merge",
                "source": "tool:memory-cleanup",
                "src": str(src_path),
                "dst": str(dst_path),
                "kind": kind,
                "mode": "merge",
            })
    return stats


def run(apply: bool) -> int:
    label = "(--apply)" if apply else "(dry-run)"
    print(f"=== merge-orphan-access {label} ===")
    print(f"memory root: {MEMORY_DIR}")

    if apply:
        active, info = check_active_session()
        if active:
            print(f"[ABORT] active session detected ({info});"
                  f" 等該 session 結束再 --apply", file=sys.stderr)
            return 2

    stats_all: List[Dict[str, Any]] = []
    for src_rel, dst_rel, kind in MAPPING:
        print(f"\n[{kind}] {src_rel} → {dst_rel}")
        s = process_pair(src_rel, dst_rel, kind, apply)
        print(f"  action: {s['action']}{' — ' + s['reason'] if s['reason'] else ''}")
        for line in s.get("diff", []):
            print(line)
        stats_all.append(s)

    n_merge = sum(1 for s in stats_all if s["action"] == "merge")
    n_move = sum(1 for s in stats_all if s["action"] == "move")
    n_delete = sum(1 for s in stats_all if s["action"] == "delete")
    n_skip = sum(1 for s in stats_all if s["action"] == "skip")

    print(f"\n=== summary: merge={n_merge} move={n_move}"
          f" delete={n_delete} skip={n_skip} ===")
    if not apply:
        print("(dry-run; pass --apply to execute)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="實際合併 + git rm；預設 dry-run")
    args = parser.parse_args()
    return run(args.apply)


if __name__ == "__main__":
    sys.exit(main())
