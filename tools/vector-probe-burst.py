"""
vector-probe-burst.py — Wave 3b probe burst (accelerate 4-day observation)

Fires ~90 queries through the full wg_intent vector path
(_search_episodic_context + _semantic_search) so each invocation writes a
record to ~/.claude/Logs/vector-observation.log via the in-process logger.

Three query buckets (~30 each):
  A  high-probability hits     — terms tied to existing atoms/episodics
  B  mid-probability           — broad technical terms
  C  low-probability / boundary — nonsense / out-of-domain (should miss)

Privacy: queries are short generic strings, no atom file content is logged
(the existing log schema only stores result counts + flags + session_id, see
wg_intent._log_vector_obs).

Exit: prints summary { total, hits, fallback_or_error, elapsed }.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import List

CLAUDE_DIR = Path.home() / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"
WORKFLOW_DIR = CLAUDE_DIR / "workflow"
CONFIG_PATH = WORKFLOW_DIR / "config.json"
SERVICE_PATH = CLAUDE_DIR / "tools" / "memory-vector-service" / "service.py"
LOG_PATH = CLAUDE_DIR / "Logs" / "vector-observation.log"

# Inject hooks dir so we can import wg_intent (the goal: trigger its log writes)
sys.path.insert(0, str(HOOKS_DIR))


QUERIES_A_HIGH = [
    "workflow guardian SessionStart 機制",
    "atom 注入 trigger 匹配",
    "memory cleanup wave 3 vector",
    "Codex sandbox unelevated 1385",
    "hot cache session_id timestamp",
    "episodic atom 跨 session 鞏固",
    "vector service ollama embedding",
    "hook 鏈 SessionStart UserPromptSubmit",
    "atom_chunks lance 索引",
    "wg_intent _semantic_search ranked",
    "fix escalation 6 agent",
    "晉升門檻 confirmations readhits",
    "atom_write MCP 自動驗證",
    "Project_File_Tree 索引化",
    "codex_companion phase6 hook",
    "_AIDocs DocIndex 知識庫",
    "wg_codex_companion_phase6 移除",
    "vector_ready flag silent failure",
    "原子記憶 V4.1 SPEC",
    "manage role personal scope",
    "ChatGPT Pro 使用者偏好",
    "workflow signal sync_completed",
    "rules core 知識庫查閱",
    "feedback handoff fix on discovery",
    "atom_debug log 開關",
    "extract worker 萃取管線",
    "wisdom engine reflection",
    "session merge_into 去重",
    "trigger 詞表注入命中",
    "workflow_guardian fast mode",
]

QUERIES_B_MID = [
    "hook 鏈",
    "ReadHits 計數器",
    "session merge",
    "git commit message",
    "JSON schema 驗證",
    "subprocess Popen Windows",
    "Python pathlib mkdir",
    "logging RotatingFileHandler",
    "urllib request urlopen timeout",
    "vector embedding 模型",
    "ranked search top_k",
    "atom frontmatter",
    "MCP server health",
    "signal handler 訊號",
    "config json 設定檔",
    "trigger 觸發 keyword",
    "intent classification",
    "topic tracker",
    "proactive classify",
    "cross session pattern",
    "_strip_atom for injection",
    "section inject threshold",
    "hot cold 分級",
    "fail closed graceful",
    "DEVNULL stderr swallow",
    "always loaded token",
    "drift 偵測",
    "regression 防止",
    "smoke test post check",
    "rollback manifest",
]

QUERIES_C_LOW = [
    "量子糾纏 貝爾不等式",
    "莎士比亞十四行詩第十八",
    "foo bar baz qux",
    "臺北 101 高度",
    "lorem ipsum dolor sit amet",
    "mitochondria powerhouse cell",
    "蝴蝶效應 混沌理論",
    "Beethoven 第九號交響曲",
    "Eiffel Tower height meters",
    "asdf jkl semicolon",
    "唐詩三百首 李白",
    "prime number sieve eratosthenes",
    "玫瑰花 香水 香奈兒",
    "Nile river length",
    "kangaroo pouch joey",
    "blockchain bitcoin halving",
    "Pythagoras 畢達哥拉斯",
    "天龍八部 金庸",
    "tiramisu mascarpone recipe",
    "鋼琴奏鳴曲 莫札特",
    "dwarf planet pluto",
    "海洋深溝 馬里亞納",
    "origami crane fold",
    "qwerty keyboard layout",
    "貓咪呼嚕 頻率",
    "Riemann hypothesis zeta",
    "彩虹七色 折射",
    "espresso double shot ratio",
    "tundra biome permafrost",
    "玄武岩 火山岩",
]


def ensure_service(port: int, log_lines: List[str]) -> bool:
    """Return True iff /health returns 200 within ~6s after a possible spawn."""
    base = f"http://127.0.0.1:{port}"

    def health() -> bool:
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    if health():
        log_lines.append(f"[burst] service already healthy on :{port}")
        return True

    log_lines.append(f"[burst] service unreachable, attempting spawn: {SERVICE_PATH}")
    if not SERVICE_PATH.exists():
        log_lines.append(f"[burst] ERROR service script missing: {SERVICE_PATH}")
        return False

    # Port guard
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            sock.bind(("127.0.0.1", port))
            sock.close()
            kw = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            else:
                kw["start_new_session"] = True
            subprocess.Popen([sys.executable, str(SERVICE_PATH)], **kw)
        except OSError:
            sock.close()  # already in use → race with another start
    except Exception as e:
        log_lines.append(f"[burst] spawn error: {e}")

    # Poll up to 6s
    for _ in range(12):
        time.sleep(0.5)
        if health():
            log_lines.append("[burst] service became healthy after spawn")
            return True
    log_lines.append("[burst] service still unhealthy after 6s wait")
    return False


def main() -> int:
    if not CONFIG_PATH.exists():
        print(f"[burst] config missing: {CONFIG_PATH}", file=sys.stderr)
        return 2
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[burst] config parse error: {e}", file=sys.stderr)
        return 2

    port = config.get("vector_search", {}).get("service_port", 3849)

    notes: List[str] = []
    service_up = ensure_service(port, notes)
    for n in notes:
        print(n)

    # Import wg_intent AFTER service is (possibly) up — module reads no global state.
    try:
        import wg_intent  # type: ignore
    except Exception as e:
        print(f"[burst] wg_intent import failed: {e}", file=sys.stderr)
        return 3

    # Even if service down, still run — fail-closed path will write fallback records.
    if not service_up:
        # Header marker so summary readers can see service was unavailable mid-burst.
        try:
            wg_intent._log_vector_obs(  # type: ignore[attr-defined]
                "burst-marker", "burst_start", "service_unavailable", 0, True,
                extra={"note": "vector service unreachable at burst start"},
            )
        except Exception:
            pass

    queries = (
        [(q, "A") for q in QUERIES_A_HIGH]
        + [(q, "B") for q in QUERIES_B_MID]
        + [(q, "C") for q in QUERIES_C_LOW]
    )

    session_id = f"burst-{uuid.uuid4()}"
    intents = {"A": "design", "B": "general", "C": "general"}

    t0 = time.time()
    hit_total = 0
    fallback_total = 0
    error_total = 0

    for idx, (q, bucket) in enumerate(queries, 1):
        intent = intents[bucket]
        # Path 1: episodic context (first-prompt-style)
        try:
            ep_results = wg_intent._search_episodic_context(  # type: ignore[attr-defined]
                q, config, session_id=session_id
            )
            if isinstance(ep_results, list) and ep_results:
                hit_total += 1
            else:
                # Determine via flag presence — fallback_used implied if no results
                fallback_total += 1
        except Exception:
            error_total += 1

        # Path 2: ranked semantic search (general path)
        try:
            sem = wg_intent._semantic_search(  # type: ignore[attr-defined]
                q, config, intent=intent, user=None, roles=None,
                session_id=session_id,
            )
            if isinstance(sem, list) and sem:
                hit_total += 1
            else:
                fallback_total += 1
        except Exception:
            error_total += 1

        if idx % 15 == 0:
            print(f"[burst] progress {idx}/{len(queries)} bucket={bucket}")

    elapsed = time.time() - t0
    total_calls = len(queries) * 2

    summary = {
        "session_id": session_id,
        "queries": len(queries),
        "calls": total_calls,
        "hits": hit_total,
        "fallback_or_zero": fallback_total,
        "errors": error_total,
        "elapsed_seconds": round(elapsed, 2),
        "service_up_at_start": service_up,
    }
    print("=" * 60)
    print("BURST SUMMARY")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("=" * 60)
    print(f"Log appended at: {LOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
