"""scorer.py — Sprint 3 turn-level risk scoring for token gating.

Plan v5 Phase 3.1：
  compute_turn_score(state) -> 0-10
  五因子加權：
    write_footprint    (0-2) — 修改檔數
    verification_gap   (0-3) — has state change AND no verify (cmd or narrative)
    structural_risk    (0-2) — 觸碰結構性檔案 (bridge/provider/adapter/...)
    completion_claim   (0-2) — last_assistant_tail 含完成宣告
    analysis_loop      (0-1) — 反覆讀同一檔但沒 Edit

回傳 int 0..10。Stop hook 算完 < threshold 即跳過 codex turn_audit，省互動干擾。

純啟發式、不打 LLM，目標 < 5ms。供 hook 端同步呼叫使用。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List

SERVICE_DIR = Path(__file__).resolve().parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

import heuristics  # 共用 _ARCH_FILE_RE / _STATE_CHANGE_TOOLS / verify 偵測


_STATE_CHANGE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _modified_paths(state: Dict[str, Any]) -> List[str]:
    """合併 modified_files 與 trace 中的 Edit/Write 路徑（去重）。"""
    paths: set[str] = set()
    for m in state.get("modified_files", []) or []:
        p = m.get("path", "") if isinstance(m, dict) else str(m)
        if p:
            paths.add(p)
    for t in state.get("tool_trace", []) or []:
        if t.get("tool") in _STATE_CHANGE_TOOLS:
            p = t.get("path", "")
            if p:
                paths.add(p)
    return sorted(paths)


def _score_write_footprint(paths: List[str]) -> int:
    n = len(paths)
    if n == 0:
        return 0
    if n <= 2:
        return 1
    return 2


def _score_verification_gap(state: Dict[str, Any], stop_text: str, has_change: bool) -> int:
    """0-3：
      0 = 無 state change（不適用）
      0 = 有 state change 但 trace 內見 verify cmd（pytest/build/...）
      1 = 有 state change，無 trace verify cmd，但 stop_text 有 verify narrative（弱證據）
      3 = 有 state change，trace 與 narrative 雙缺（最大 gap）
    """
    if not has_change:
        return 0
    if heuristics._has_verify_cmd(state):
        return 0
    if heuristics._has_verify_narrative(stop_text or ""):
        return 1
    return 3


def _score_structural_risk(paths: List[str]) -> int:
    arch = [p for p in paths if heuristics._ARCH_FILE_RE.search(p)]
    n = len(arch)
    if n == 0:
        return 0
    if n <= 2:
        return 1
    return 2


def _score_completion_claim(state: Dict[str, Any], stop_text: str) -> int:
    return 2 if heuristics._has_completion_claim(state, stop_text or "") else 0


def _score_analysis_loop(state: Dict[str, Any]) -> int:
    return 1 if heuristics.check_spinning(state).triggered else 0


def compute_turn_score(state: Dict[str, Any], stop_text: str = "") -> int:
    """主入口：聚合五因子，輸出 0-10 整數。

    state 形狀容忍度：可吃 hook 端 merged_state（modified_files / tool_trace），
    或 companion-state-{sid}.json 直接讀出 dict（含 last_assistant_tail）。
    若 stop_text 未顯式傳入，回退取 state["last_assistant_tail"]。
    """
    if not stop_text:
        stop_text = state.get("last_assistant_tail", "") or ""

    paths = _modified_paths(state)
    has_change = bool(paths) or any(
        t.get("tool") in _STATE_CHANGE_TOOLS for t in state.get("tool_trace", []) or []
    )

    score = (
        _score_write_footprint(paths)
        + _score_verification_gap(state, stop_text, has_change)
        + _score_structural_risk(paths)
        + _score_completion_claim(state, stop_text)
        + _score_analysis_loop(state)
    )
    return min(max(score, 0), 10)


def explain_score(state: Dict[str, Any], stop_text: str = "") -> Dict[str, Any]:
    """除錯/觀測用：拆出五因子個別貢獻 + 總分，供 reflection_metrics 落盤。"""
    if not stop_text:
        stop_text = state.get("last_assistant_tail", "") or ""

    paths = _modified_paths(state)
    has_change = bool(paths) or any(
        t.get("tool") in _STATE_CHANGE_TOOLS for t in state.get("tool_trace", []) or []
    )

    factors = {
        "write_footprint": _score_write_footprint(paths),
        "verification_gap": _score_verification_gap(state, stop_text, has_change),
        "structural_risk": _score_structural_risk(paths),
        "completion_claim": _score_completion_claim(state, stop_text),
        "analysis_loop": _score_analysis_loop(state),
    }
    total = min(max(sum(factors.values()), 0), 10)
    return {"total": total, "factors": factors, "modified_paths": paths}
