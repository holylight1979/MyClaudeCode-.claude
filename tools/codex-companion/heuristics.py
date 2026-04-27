"""heuristics.py — Rule-based soft gate checks for Codex Companion.

Sprint 2 重構：BLOCK 權收斂到單一規則 `confident_completion_without_evidence`，
其餘規則一律降為 advisory (low)，只走 inject 不走 block。

三條件 BLOCK 模型：
  1. has_claim       — stop_text 或 trace tail 出現完成宣告
  2. state_change    — 真的有 Edit/Write 發生（trace 或 modified_files）
  3. no_verify_*     — trace 無 verify cmd 且 stop_text 無 verify 敘述
  三者皆中才會 BLOCK；任一缺席即放行。

Sprint 1 教訓（state 缺 trace 但 tail 含實證據）：
  Sprint 1 收尾被誤觸發過一次 — companion-state 被外力刪除導致 trace 清空，
  但當時實際做了 pytest 10/10 + commit，只是訊息留在 last_assistant_tail。
  本次重構把 stop_text 的「驗證敘述」也視為弱證據，避免 trace 單點失效誤判。

No LLM calls. All checks run < 10ms.
Input: dict with `modified_files`, `accessed_files`, `tool_trace` keys。
Output: list of HeuristicResult。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class HeuristicResult:
    name: str
    triggered: bool
    severity: str  # "low" | "medium" | "high"
    detail: str


# --- patterns ---

_VERIFY_CMD_RE = re.compile(
    r"(?:^|\s)(?:"
    r"pytest|python\s+-m\s+pytest|"
    r"npm\s+(?:run\s+)?test|jest|vitest|"
    r"node\s+--check|tsc|"
    r"go\s+test|cargo\s+test|"
    r"dotnet\s+test|"
    r"python\s+.*\.py|"
    r"make\s+(?:test|check|build)|"
    r"(?:npm|yarn|pnpm)\s+run\s+build"
    r")(?:\s|$)"
)

_COMPLETION_RE = re.compile(
    r"(完成|已解決|全部做完|done|finished|all\s+set|wrapped\s+up|大功告成|搞定|收尾|總結)",
    re.IGNORECASE,
)

_ARCH_FILE_RE = re.compile(
    r"(?:bridge|provider|adapter|factory|service|client|transport|middleware|gateway)"
    r"(?:\.py|\.ts|\.js|\.rs)$",
    re.IGNORECASE,
)

# Sprint 2：stop_text 內出現實際驗證敘述（弱證據，不走 BLOCK 路徑）
# - 「X/Y PASS」「10/10 通過」明確分數型
# - 「pytest 通過」「tests passed」「build 成功」近距離搭配
# - 「驗證通過」「測試綠燈」「all green」整體性敘述
_VERIFY_NARRATIVE_RE = re.compile(
    r"\d+\s*/\s*\d+\s*(?:PASS|pass|通過|綠燈|綠)"
    r"|"
    r"(?:pytest|tests?|單元測試|e2e|smoke|build|建置|verification|驗證)"
    r"[^\n]{0,30}?"
    r"(?:通過|passed?|succeeded|成功|PASS|綠燈|綠|ok\b)"
    r"|"
    r"(?:all\s+(?:tests?|green)|全部\s*通過|測試\s*綠燈|驗證\s*通過)",
    re.IGNORECASE,
)

_STATE_CHANGE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


# --- internal helpers ---

def _get_tool_trace(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return state.get("tool_trace", [])


def _get_modified_files(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return state.get("modified_files", [])


def _has_completion_claim(state: Dict[str, Any], stop_text: str) -> bool:
    if stop_text and _COMPLETION_RE.search(stop_text):
        return True
    trace = _get_tool_trace(state)
    for t in trace[-3:]:
        if _COMPLETION_RE.search(t.get("output_summary", "")):
            return True
    return False


def _has_state_change(state: Dict[str, Any]) -> bool:
    """真的有檔案被改 — modified_files 任一非空，或 trace 有 Edit/Write 事件。
    兩個來源任一命中即可，避免單點失效（state file 被擾動）誤判。
    """
    if _get_modified_files(state):
        return True
    for t in _get_tool_trace(state):
        if t.get("tool") in _STATE_CHANGE_TOOLS:
            return True
    return False


def _has_verify_cmd(state: Dict[str, Any]) -> bool:
    for t in _get_tool_trace(state):
        if t.get("tool") == "Bash" and _VERIFY_CMD_RE.search(t.get("input", "")):
            return True
    return False


def _has_verify_narrative(stop_text: str) -> bool:
    """Sprint 1 教訓 fallback：stop_text 含明確驗證敘述視為弱證據。"""
    if not stop_text:
        return False
    return bool(_VERIFY_NARRATIVE_RE.search(stop_text))


# --- individual heuristics ---

def check_confident_completion_without_evidence(
    state: Dict[str, Any], stop_text: str = ""
) -> HeuristicResult:
    """BLOCK 級規則 — 三條件全中才觸發 high。

    缺任一條件即放行（return triggered=False）；
    特別是 stop_text 含驗證敘述（弱證據）時也放行，避免 trace 單點失效誤判。
    """
    if not _has_completion_claim(state, stop_text):
        return HeuristicResult(
            "confident_completion_without_evidence", False, "low",
            "no completion claim",
        )
    if not _has_state_change(state):
        return HeuristicResult(
            "confident_completion_without_evidence", False, "low",
            "completion claimed but no state change — likely discussion-only turn",
        )
    if _has_verify_cmd(state):
        return HeuristicResult(
            "confident_completion_without_evidence", False, "low",
            "verify command found in trace",
        )
    if _has_verify_narrative(stop_text):
        return HeuristicResult(
            "confident_completion_without_evidence", False, "low",
            "verify narrative found in stop_text (weak evidence — trace may be wiped)",
        )

    modified = _get_modified_files(state)
    file_count = len(modified) if modified else sum(
        1 for t in _get_tool_trace(state) if t.get("tool") in _STATE_CHANGE_TOOLS
    )
    return HeuristicResult(
        "confident_completion_without_evidence",
        True,
        "high",
        f"Completion claimed AND {file_count} state change(s) AND no verification evidence "
        "(neither trace nor narrative). 請補驗證或改口風後再收尾。",
    )


# Sprint 2：保留舊名作為向下相容 alias（一律走新邏輯）
check_completion_without_evidence = check_confident_completion_without_evidence


def check_missing_verification(state: Dict[str, Any]) -> HeuristicResult:
    """改檔但沒測試指令 — advisory only (low)。

    Sprint 2：原 medium 降為 low；只 inject 不 block。
    BLOCK 權只屬 confident_completion_without_evidence。
    """
    modified = _get_modified_files(state)
    if not modified:
        return HeuristicResult("missing_verification", False, "low", "")

    if _has_verify_cmd(state):
        return HeuristicResult("missing_verification", False, "low", "")

    file_names = list({m.get("path", "").rsplit("/", 1)[-1] for m in modified})
    return HeuristicResult(
        "missing_verification",
        True,
        "low",
        f"Modified {len(modified)} file(s) ({', '.join(file_names[:5])}) but no test/build command. "
        "Advisory only — consider running tests.",
    )


def check_architecture_change(state: Dict[str, Any]) -> HeuristicResult:
    """新建 bridge/provider/adapter/service 等結構性檔案 — advisory only (low)。

    Sprint 2：原 medium 降為 low；只 inject 不 block。
    """
    modified = _get_modified_files(state)
    arch_files = [
        m.get("path", "")
        for m in modified
        if _ARCH_FILE_RE.search(m.get("path", ""))
    ]

    if not arch_files:
        return HeuristicResult("architecture_change", False, "low", "")

    names = [p.rsplit("/", 1)[-1] for p in arch_files]
    return HeuristicResult(
        "architecture_change",
        True,
        "low",
        f"Structural file(s) touched: {', '.join(names)}. Advisory — consider architecture review.",
    )


def check_spinning(state: Dict[str, Any]) -> HeuristicResult:
    """連續 ≥ 3 次 Read 同一檔案但沒有 Edit — advisory (low)，維持原行為。"""
    trace = _get_tool_trace(state)
    if len(trace) < 3:
        return HeuristicResult("spinning", False, "low", "")

    read_counts: Dict[str, int] = {}
    edited: set = set()

    for t in trace:
        tool = t.get("tool", "")
        path = t.get("path", "") or t.get("input", "")
        if tool == "Read" and path:
            read_counts[path] = read_counts.get(path, 0) + 1
        elif tool in _STATE_CHANGE_TOOLS and path:
            edited.add(path)

    spinning_files = [
        p for p, c in read_counts.items()
        if c >= 3 and p not in edited
    ]

    if not spinning_files:
        return HeuristicResult("spinning", False, "low", "")

    names = [p.rsplit("/", 1)[-1] for p in spinning_files[:3]]
    return HeuristicResult(
        "spinning",
        True,
        "low",
        f"Read {', '.join(names)} ≥3 times without editing. Possible analysis loop.",
    )


# --- aggregate ---

def run_all(
    state: Dict[str, Any], stop_text: str = ""
) -> List[HeuristicResult]:
    return [
        check_missing_verification(state),
        check_confident_completion_without_evidence(state, stop_text),
        check_architecture_change(state),
        check_spinning(state),
    ]


def triggered_results(
    state: Dict[str, Any], stop_text: str = ""
) -> List[HeuristicResult]:
    return [r for r in run_all(state, stop_text) if r.triggered]


_SEV_ORDER = {"low": 0, "medium": 1, "high": 2}


def max_severity(results: List[HeuristicResult]) -> str:
    if not results:
        return "low"
    return max(results, key=lambda r: _SEV_ORDER.get(r.severity, 0)).severity


def severity_at_or_above(results: List[HeuristicResult], threshold: str) -> bool:
    """Sprint 2：給 hook 端做門檻比較用。"""
    if not results:
        return False
    th = _SEV_ORDER.get(threshold, 2)
    return any(_SEV_ORDER.get(r.severity, 0) >= th for r in results)


def format_for_context(results: List[HeuristicResult]) -> str:
    triggered = [r for r in results if r.triggered]
    if not triggered:
        return ""
    lines = [f"[Codex Companion: Heuristic Gate] {len(triggered)} flag(s)"]
    for r in triggered:
        lines.append(f"  [{r.severity}] {r.name}: {r.detail}")
    return "\n".join(lines)
