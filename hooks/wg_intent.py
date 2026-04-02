"""
wg_intent.py — 意圖分類、Session Context、基礎設施檢查

Intent Classification、Topic Tracker、Episodic Search、
Cross-Session Pattern Detection、Proactive Classification、
MCP Health Check、Vector Service Management。
"""

import json
import re
import sys
import urllib.request
import urllib.error
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from wg_paths import CLAUDE_DIR, WORKFLOW_DIR
from wg_core import _atom_debug_error

# ─── Intent Classifier (v2.1 Sprint 2) ───────────────────────────────────────

INTENT_PATTERNS = {
    "debug": ["crash", "error", "bug", "失敗", "壞", "exception", "為什麼",
              "why", "問題", "traceback", "報錯", "修復", "fix"],
    "build": ["build", "deploy", "建置", "部署", "安裝", "install", "啟動",
              "setup", "config", "設定", "配置", "環境"],
    "design": ["設計", "架構", "design", "architecture", "重構", "refactor",
               "新增", "planning", "實作", "implement", "方案"],
    "recall": ["之前", "上次", "記得", "決策", "決定", "為什麼選",
               "remember", "previous", "history"],
}


def classify_intent(prompt: str) -> str:
    """Rule-based intent classifier. Zero LLM overhead (~1ms)."""
    prompt_lower = prompt.lower()
    scores = {}
    for intent, keywords in INTENT_PATTERNS.items():
        scores[intent] = sum(1 for kw in keywords if kw in prompt_lower)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


# ─── Topic Tracker (v2.2) ────────────────────────────────────────────────────

_TOPIC_STOP_WORDS = frozenset({
    "this", "that", "with", "from", "have", "been", "will", "what", "when",
    "which", "where", "about", "into", "also", "should", "could", "would",
    "these", "those", "them", "your", "make", "just", "only", "some", "very",
    "here", "there", "then", "than", "more", "most", "like", "each", "want",
    "need", "keep", "does", "done", "doing", "help", "sure", "good", "well",
    "okay", "know", "think", "look", "take", "give", "come", "back", "over",
    "after", "before", "other", "file", "line", "code", "true", "false",
})


def _update_topic_tracker(
    state: Dict[str, Any], prompt: str, intent: str, newly_injected: List[str]
) -> None:
    """Accumulate topic signals in state. Pure CPU, < 1ms, zero network."""
    tracker = state.setdefault("topic_tracker", {
        "intent_distribution": {},
        "prompt_count": 0,
        "first_prompt_summary": "",
        "keyword_signals": [],
        "related_episodic": [],
    })

    dist = tracker["intent_distribution"]
    dist[intent] = dist.get(intent, 0) + 1
    tracker["prompt_count"] = tracker.get("prompt_count", 0) + 1

    if not tracker.get("first_prompt_summary"):
        tracker["first_prompt_summary"] = prompt[:200]

    existing_kw = set(tracker.get("keyword_signals", []))
    words = re.findall(r"[a-zA-Z\u4e00-\u9fff]{4,}", prompt)
    for w in words:
        wl = w.lower()
        if wl not in _TOPIC_STOP_WORDS and wl not in existing_kw:
            existing_kw.add(wl)
    sa_config = state.get("_sa_config", {})
    max_kw = sa_config.get("max_keyword_signals", 20)
    tracker["keyword_signals"] = sorted(existing_kw)[:max_kw]

    related = tracker.get("related_episodic", [])
    for name in newly_injected:
        if name.startswith("episodic-") and name not in related:
            related.append(name)
    tracker["related_episodic"] = related


# ─── Session Context + Proactive Classification (v2.2 Sprint 2) ──────────────


def _search_episodic_context(
    prompt: str, config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Query /search/episodic for related past sessions. First-prompt only."""
    vs_config = config.get("vector_search", {})
    if not vs_config.get("enabled", True):
        return []
    sc_config = config.get("session_context", {})
    if not sc_config.get("enabled", True):
        return []
    # V3/1.5C: Quick flag check — skip expensive network call if vector not ready
    if not (WORKFLOW_DIR / "vector_ready.flag").exists():
        return []

    port = vs_config.get("service_port", 3849)
    top_k = sc_config.get("max_episodic", 3)
    min_score = sc_config.get("min_score", 0.35)
    timeout_s = sc_config.get("search_timeout_ms", 8000) / 1000.0

    try:
        import urllib.parse
        params = urllib.parse.urlencode({
            "q": prompt, "top_k": top_k, "min_score": min_score,
        })
        url = f"http://127.0.0.1:{port}/search/episodic?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read())
    except Exception as e:
        _atom_debug_error("注入:_search_episodic_context", e)
        return []


def _build_session_context(episodic_results: List[Dict[str, Any]]) -> List[str]:
    """Build compact [Session:Context] block from episodic search results."""
    if not episodic_results:
        return []

    context_lines = ["[Session:Context] Related past sessions:"]
    char_budget = 600

    for ep in episodic_results:
        name = ep.get("atom_name", "")
        created = ep.get("created", ep.get("last_used", ""))
        summary = ep.get("summary", "")

        slug = name
        if name.startswith("episodic-") and len(name) > 18:
            slug = name[18:]

        line = f"- [{created}] {slug}: {summary[:120]}"
        if len(line) > char_budget:
            break
        context_lines.append(line)
        char_budget -= len(line)

    return context_lines if len(context_lines) > 1 else []


def _detect_cross_session_patterns(
    episodic_results: List[Dict[str, Any]], prompt: str
) -> List[str]:
    """Detect recurring themes across episodic sessions."""
    if len(episodic_results) < 2:
        return []

    topic_counts: Counter = Counter()
    for ep in episodic_results:
        for kw in ep.get("triggers", []):
            if kw not in ("session", "episodic"):
                topic_counts[kw] += 1

    prompt_kw = set(
        w.lower() for w in re.findall(r"[a-zA-Z\u4e00-\u9fff]{4,}", prompt)
        if w.lower() not in _TOPIC_STOP_WORDS
    )

    recurring = [kw for kw in prompt_kw if topic_counts.get(kw, 0) >= 2]
    return recurring


def _proactive_classify(
    state: Dict[str, Any],
    episodic_results: List[Dict[str, Any]],
    prompt: str,
    config: Dict[str, Any],
) -> List[str]:
    """Proactive classification engine. Returns context lines for hints/questions."""
    pro_config = config.get("proactive", {})
    lines: List[str] = []

    recurring = _detect_cross_session_patterns(episodic_results, prompt)
    pattern_threshold = pro_config.get("pattern_threshold", 2)
    if recurring:
        atom_index = state.get("atom_index", {})
        existing_names = set()
        for entry in atom_index.get("global", []):
            existing_names.add(entry[0].lower())
        for entry in atom_index.get("project", []):
            existing_names.add(entry[0].lower())

        novel_themes = [kw for kw in recurring if kw not in existing_names]
        if novel_themes:
            themes_str = ", ".join(novel_themes[:3])
            ep_count = len(episodic_results)
            lines.append(
                f"💡 [Proactive] 主題 \"{themes_str}\" 在最近 {ep_count} 個 session 反覆出現。"
                " 建議建立專屬 semantic atom 來長期保存相關知識。"
            )

    migration_threshold = pro_config.get("migration_hint_threshold", 3)
    for ep in episodic_results:
        name = ep.get("atom_name", "")
        confirms = 0
        try:
            confirms = int(ep.get("confirmations", 0) if ep.get("confirmations") else 0)
        except (ValueError, TypeError):
            pass
        if confirms >= migration_threshold:
            lines.append(
                f"❓ {name} 已被 {confirms}+ 次 session 引用。"
                " 核心知識是否應遷移到專屬 atom？"
            )

    return lines


# ─── MCP Server Health Check ─────────────────────────────────────────────────


def _check_mcp_servers() -> List[str]:
    """Verify .mcp.json server entries: command + script must exist on disk."""
    import shutil
    issues: List[str] = []
    mcp_path = CLAUDE_DIR / ".mcp.json"
    if not mcp_path.exists():
        return []
    try:
        with open(mcp_path, "r", encoding="utf-8") as f:
            mcp_cfg = json.loads(f.read())
        servers = mcp_cfg.get("mcpServers", {})
        for name, srv in servers.items():
            cmd = srv.get("command", "")
            args = srv.get("args", [])
            # Commands may be bare names (e.g. "node") in PATH, not full paths
            if cmd and not Path(cmd).exists() and not shutil.which(cmd):
                issues.append(f"{name}: command not found ({cmd})")
            if args:
                script = args[0]
                if not Path(script).exists():
                    issues.append(f"{name}: script not found ({script})")
    except Exception as e:
        issues.append(f"parse error: {e}")
    return issues


# ─── Vector Service Helpers ───────────────────────────────────────────────────


def _ensure_vector_service(config: Dict[str, Any]) -> None:
    """Check if Memory Vector Service is running; start if not."""
    vs_config = config.get("vector_search", {})
    port = vs_config.get("service_port", 3849)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health", method="GET")
        with urllib.request.urlopen(req, timeout=1):
            return
    except Exception as e:
        _atom_debug_error("注入:_ensure_vector_service:health", e)
    # Port guard: 若 port 已被佔用（service 啟動中但 health 尚未就緒），不重複 spawn
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            return  # port occupied — service likely starting up
    finally:
        sock.close()
    service_path = CLAUDE_DIR / "tools" / "memory-vector-service" / "service.py"
    if not service_path.exists():
        return
    try:
        import subprocess
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        CREATE_BREAKAWAY_FROM_JOB = 0x01000000
        log_path = CLAUDE_DIR / "memory" / "_vectordb" / "service.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(str(log_path), "a")
        try:
            kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": log_fh,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB
            subprocess.Popen(
                [sys.executable, str(service_path)],
                **kwargs,
            )
            # Note: log_fh intentionally NOT closed here — the child process
            # inherits the fd and writes to it. Closing would truncate output.
            # The fd is released when the child exits or this process exits.
        except Exception:
            log_fh.close()
            raise
    except Exception as e:
        _atom_debug_error("注入:_ensure_vector_service:start", e)


def _semantic_search(
    prompt: str, config: Dict[str, Any], intent: str = "general"
) -> List[Tuple[str, str, List[str], List[Dict]]]:
    """Query Memory Vector Service with intent-aware ranked search (v2.18).

    Returns: [(atom_name, file_path, triggers[], sections[])]
    sections is list of {section, text, score, line_number} from ranked-sections endpoint.
    Empty sections list when falling back to ranked search.
    """
    vs_config = config.get("vector_search", {})
    if not vs_config.get("enabled", True):
        return []
    # V3/1.5C: Quick flag check — skip expensive network call if vector not ready
    if not (WORKFLOW_DIR / "vector_ready.flag").exists():
        return []
    port = vs_config.get("service_port", 3849)
    top_k = vs_config.get("search_top_k", 5)
    min_score = vs_config.get("search_min_score", 0.65)
    timeout_s = vs_config.get("search_timeout_ms", 8000) / 1000.0

    try:
        import urllib.parse

        # Try ranked-sections first (v2.18)
        use_sections = True
        params = urllib.parse.urlencode({
            "q": prompt, "top_k": top_k,
            "min_score": min(min_score, 0.50),
            "intent": intent,
            "max_sections": 3,
        })
        url = f"http://127.0.0.1:{port}/search/ranked-sections?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                results = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Fallback: ranked search (no sections)
                use_sections = False
                params = urllib.parse.urlencode({
                    "q": prompt, "top_k": top_k,
                    "min_score": min(min_score, 0.50),
                    "intent": intent,
                })
                url = f"http://127.0.0.1:{port}/search/ranked?{params}"
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    results = json.loads(resp.read())
            else:
                raise

        entries: List[Tuple[str, str, List[str], List[Dict]]] = []
        seen = set()
        for r in results:
            name = r.get("atom_name", "")
            if name and name not in seen:
                sections = r.get("sections", []) if use_sections else []
                entries.append((name, r.get("file_path", ""), [], sections))
                seen.add(name)
        return entries
    except Exception as e:
        _atom_debug_error("注入:_semantic_search", e)
        return []


def _trigger_incremental_index(config: Dict[str, Any]) -> None:
    """Non-blocking request to re-index changed atoms."""
    vs_config = config.get("vector_search", {})
    if not vs_config.get("auto_index_on_change", True):
        return
    port = vs_config.get("service_port", 3849)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/index/incremental",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=1)
    except Exception as e:
        _atom_debug_error("注入:_trigger_incremental_index", e)
