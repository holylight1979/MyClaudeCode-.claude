"""wg_evasion.py — Evasion Guard + Test-Fail Gate helpers.

PostToolUse(Bash): 偵測測試/語法檢查失敗 → state["failing_tests"]
Stop: 偵測完成宣告 + failing_tests 非空 → output_block（硬阻擋）
Stop: 偵測退避詞彙 → state["evasion_flag"]
UPS: 讀 evasion_flag → 注入舉證要求，清旗標
UPS: 使用者放行關鍵字 → 清 failing_tests
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional


_TEST_CMD_RE = re.compile(
    r"(?:^|\s)(?:pytest|python\s+-m\s+pytest|npm\s+(?:run\s+)?test|jest|node\s+--check|tsc|go\s+test|cargo\s+test)(?:\s|$)"
)

_FAILURE_PATTERNS = [
    re.compile(r"^=+.*\b\d+\s+failed", re.MULTILINE),
    re.compile(r"\b\d+\s+failed[,\s]"),
    re.compile(r"^FAILED\s", re.MULTILINE),
    re.compile(r"\bSyntaxError\b"),
    re.compile(r"\berror\s+TS\d+:"),
    re.compile(r"Tests:\s+\d+\s+failed"),
    re.compile(r"^---\s+FAIL:", re.MULTILINE),
    re.compile(r"test result:\s+FAILED"),
]

_COMPLETION_CLAIM_RE = re.compile(
    r"(完成|已解決|全部做完|總結|收尾|done|finished|all\s+set|wrapped\s+up|大功告成|搞定)",
    re.IGNORECASE,
)

_EVASION_RE = re.compile(
    r"("
    r"不在本[^，。\s]{0,6}範圍|範圍外|"
    r"既有[^，。\s]{0,6}drift|既有[^，。\s]{0,6}問題|pre-?existing|"
    r"留給[^，。\s]{0,4}未來|超出[^，。\s]{0,4}能力|"
    r"非本次|先跳過|不影響[^，。\s]{0,4}主線|非本次改動|"
    # 時間性延後語
    r"(?:下次|下回|下一次|之後|晚點|稍後|有空|有時間)\s*再\s*(?:處理|修|補|做|看|弄)?|"
    r"未來[^，。\s]{0,3}處理|待後續|另行處理|另外處理|"
    # 「留給使用者…」自己搬鍋
    r"留給使用者"
    r")"
)

_DISMISS_RE = re.compile(
    r"(先這樣|留著|不用管|不要管|跳過|先跳過|known\s+regression|confirmed\s+regression)",
    re.IGNORECASE,
)

# 掃描報告標記：合規完成報告必須出現下列其一
_SCAN_REPORT_RE = re.compile(
    r"("
    r"順手修補|順手修|附帶修補|發現[^，。\n]{0,6}drift|"
    r"本次[^，。\n]{0,3}(?:無|沒有)[^，。\n]{0,6}drift|"
    r"無發現\s*drift|無\s*drift|no\s+drift|"
    r"掃描報告|drift\s+(?:check|report)|"
    r"需另開\s*session|列入\s*handoff"
    r")",
    re.IGNORECASE,
)


def is_test_command(cmd: str) -> bool:
    return bool(_TEST_CMD_RE.search(cmd or ""))


def tail_lines(s: str, n: int) -> str:
    lines = [l for l in (s or "").splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def detect_test_failure(
    stdout: str, stderr: str, interrupted: bool
) -> Optional[str]:
    """Return last-20-lines summary if failure detected, else None."""
    combined = (stdout or "") + "\n" + (stderr or "")
    if interrupted:
        return tail_lines(combined, 20) or "(interrupted, no output)"
    for pat in _FAILURE_PATTERNS:
        if pat.search(combined):
            return tail_lines(combined, 20)
    return None


def claims_completion(text: str) -> bool:
    if not text:
        return False
    return bool(_COMPLETION_CLAIM_RE.search(text[-2000:]))


def detect_evasion(text: str, recent_user_prompts: List[str]) -> Optional[Dict[str, str]]:
    """Return {phrase, context_excerpt} or None.

    Escape hatch: 若近 3 則 user prompt 有明確豁免關鍵字 → 不標記。
    """
    if not text:
        return None
    m = _EVASION_RE.search(text)
    if not m:
        return None
    for p in (recent_user_prompts or [])[-3:]:
        if _DISMISS_RE.search(p or ""):
            return None
    phrase = m.group(0)
    idx = m.start()
    excerpt = text[max(0, idx - 80): idx + len(phrase) + 80]
    return {"phrase": phrase, "context_excerpt": excerpt}


def is_dismiss_prompt(prompt: str) -> bool:
    return bool(_DISMISS_RE.search(prompt or ""))


def has_scan_report(text: str) -> bool:
    """回報尾端是否含『順手修補清單/無 drift 宣告/另開 session』之一。"""
    if not text:
        return False
    return bool(_SCAN_REPORT_RE.search(text))


def detect_missing_scan_report(
    text: str,
    modified_file_count: int,
    recent_user_prompts: List[str],
) -> bool:
    """宣告完成但缺掃描報告 → 違約。

    觸發條件（全部成立）：
      1. text 含完成宣告詞
      2. modified_file_count > 0（有實際動工才要求掃描）
      3. text 不含任何 _SCAN_REPORT_RE 標記
      4. 近 3 則 user prompt 無豁免關鍵字
    """
    if not text or modified_file_count <= 0:
        return False
    if not claims_completion(text):
        return False
    if has_scan_report(text):
        return False
    for p in (recent_user_prompts or [])[-3:]:
        if _DISMISS_RE.search(p or ""):
            return False
    return True


def get_last_assistant_text(transcript_path: Optional[Path]) -> str:
    """Read JSONL transcript, return last assistant text block (or empty)."""
    if not transcript_path:
        return ""
    try:
        last = ""
        with open(transcript_path, "r", encoding="utf-8") as f:
            for raw in f:
                try:
                    obj = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if obj.get("type") != "assistant":
                    continue
                content = obj.get("message", {}).get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text", "")
                        if t and len(t) > 30:
                            last = t
        return last
    except (OSError, UnicodeDecodeError):
        return ""
