"""
wg_episodic.py — Episodic 記憶自動生成

Episodic atom 生成判斷、session 摘要建構、知識萃取（Ollama LLM）、
跨 session 模式偵測、衝突偵測、品質回饋。
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from wg_paths import (
    CLAUDE_DIR, MEMORY_DIR, EPISODIC_DIR, MEMORY_INDEX, ATOM_INDEX, WORKFLOW_DIR,
    cwd_to_project_slug, get_project_memory_dir,
    resolve_episodic_dir, get_transcript_path,
)
from wg_core import _now_iso, _atom_debug_log, _atom_debug_error
from wg_content_classify import is_plan_content

sys.path.insert(0, str(Path.home() / ".claude" / "tools"))
from ollama_client import get_client

# S3.0: route Confirmations counter update through atom_io funnel
_LIB_PARENT = str(Path.home() / ".claude")
if _LIB_PARENT not in sys.path:
    sys.path.insert(0, _LIB_PARENT)
from lib.atom_io import update_atom_field, write_raw  # noqa: E402


# ─── Episodic Gate ────────────────────────────────────────────────────────────


def _should_generate_episodic(state: Dict[str, Any], config: Dict[str, Any]) -> bool:
    """Check if this session warrants an episodic atom."""
    ep_cfg = config.get("episodic", {})
    if not ep_cfg.get("auto_generate", True):
        return False

    mod_count = len(state.get("modified_files", []))
    read_count = len(state.get("accessed_files", []))
    kq_count = len(state.get("knowledge_queue", []))
    min_files = ep_cfg.get("min_files", 1)

    # V2.10: Pure-read sessions (≥5 files) also warrant episodic atoms
    if mod_count < min_files and kq_count == 0 and read_count < 5:
        return False

    # Skip very short sessions (< 2 minutes)
    started = state.get("session", {}).get("started_at", "")
    ended = state.get("ended_at", "")
    if started and ended:
        try:
            t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(ended.replace("Z", "+00:00"))
            if (t1 - t0).total_seconds() < ep_cfg.get("min_duration_seconds", 120):
                return False
        except (ValueError, TypeError):
            pass

    return True


# ─── Path & Filename Helpers ─────────────────────────────────────────────────


def _extract_area(path_str: str) -> str:
    """Extract a human-readable work area slug from a file path."""
    path = path_str.replace("\\", "/")

    # Known prefix mappings
    home = str(Path.home()).replace("\\", "/")
    claude_base = f"{home}/.claude/"
    if path.startswith(claude_base):
        rest = path[len(claude_base):]
        seg = rest.split("/")[0]
        area_map = {"memory": "memory-system", "tools": "memory-tools",
                     "hooks": "guardian", "workflow": "guardian", "plans": "planning"}
        return area_map.get(seg, seg)

    # Strip home prefix
    if path.startswith(home + "/"):
        path = path[len(home) + 1:]
    # Strip drive letter
    if len(path) > 2 and path[1] == ":":
        path = path[2:].lstrip("/")

    parts = [p for p in path.split("/") if p]
    # Take first 2 meaningful segments
    slug_parts = parts[:2] if len(parts) >= 2 else parts[:1]
    return "-".join(slug_parts).lower() if slug_parts else "misc"


def _derive_short_summary(primary_area: str) -> str:
    """Generate a kebab-case slug for the episodic atom filename (<=30 chars, ASCII)."""
    slug = primary_area.lower()
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:30] or "session-work"


def _resolve_episodic_filename(memory_dir: Path, date_str: str, slug: str) -> Path:
    """Resolve unique filename, handling same-day dedup."""
    base = f"episodic-{date_str}-{slug}"
    candidate = memory_dir / f"{base}.md"
    if not candidate.exists():
        return candidate
    for i in range(2, 20):
        candidate = memory_dir / f"{base}-{i}.md"
        if not candidate.exists():
            return candidate
    return memory_dir / f"{base}-{int(datetime.now().timestamp()) % 10000}.md"


def _resolve_episodic_dir(state: Dict[str, Any]) -> Tuple[Path, str]:
    """Resolve episodic directory: project-scoped if CWD maps to a project, else global.

    Returns (episodic_dir, scope_label).
    """
    cwd = state.get("session", {}).get("cwd", "")
    return resolve_episodic_dir(cwd)


# ─── V2.4: Response Knowledge Capture (Ollama LLM) ──────────────────────────


def _find_session_transcript(session_id: str, cwd: str) -> Optional[Path]:
    """Locate the JSONL transcript for this session.

    Path format: ~/.claude/projects/{slug}/{session_id}.jsonl
    """
    return get_transcript_path(session_id, cwd)


def _extract_all_assistant_texts(transcript_path: Path, max_chars: int = 20000) -> List[str]:
    """Extract all assistant text responses from a JSONL transcript (for SessionEnd)."""
    texts = []
    total = 0
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                content = obj.get("message", {}).get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text", "")
                        if t and len(t) > 30:  # skip trivial responses
                            texts.append(t)
                            total += len(t)
                if total >= max_chars:
                    break
    except (OSError, UnicodeDecodeError):
        pass
    return texts


def _call_ollama_generate(prompt: str, model: str = None,
                          timeout: int = 120) -> str:
    """Call Ollama generate API via dual-backend client.

    Default timeout=120s: qwen3 thinking mode needs ~30s on GTX 1050 Ti.
    Background threads (extraction) can afford to wait.
    """
    try:
        client = get_client()
        # think="auto" → rdchat(gemma4:e4b): think=True + 4096, local(qwen3:1.7b): think=False + 2048
        # 不用 format="json" — gemma4 think=false + format 有 bug (ollama#15260)
        return client.generate(
            prompt, model=model, timeout=timeout,
            temperature=0.0, think="auto",
        )
    except Exception as e:
        _atom_debug_error("萃取:_call_ollama_generate", e)
        return ""


_EXTRACT_PROMPT_TEMPLATE = (
    "你是「原子記憶系統」的知識萃取器。從 AI 回應中萃取可跨 session 重用的知識。\n"
    "輸出 JSON array: [{{\"content\": \"精簡事實，最多150字\", "
    "\"type\": \"factual|procedural|architectural|pitfall|decision\"}}]\n\n"
    "只萃取：根因分析、API 行為、架構限制、除錯模式、設定值、環境特有行為。\n"
    "不萃取：程式碼變更、通用程式知識、session 進度、問候語。\n"
    "沒有值得萃取的內容就輸出 []。直接輸出 JSON。\n\n"
    "回應文字:\n{text}\n\nJSON:"
)


def _llm_extract_knowledge(text: str, existing_queue: List[dict],
                           source: str = "session-end") -> List[dict]:
    """Use local LLM to extract knowledge from assistant text (SessionEnd only).

    Args:
        text: Assistant response text
        existing_queue: Already queued knowledge items (for dedup)
        source: extraction source label

    Returns:
        List of knowledge items: [{content, classification, knowledge_type, source, at}]
    """
    if not text or len(text) < 50:
        return []

    max_chars = 4000
    max_items = 5

    truncated = text[:max_chars]
    prompt = _EXTRACT_PROMPT_TEMPLATE.format(text=truncated)

    raw = _call_ollama_generate(prompt)
    if not raw:
        return []

    # Parse JSON (with fallback)
    items = []
    try:
        # Try to find JSON array in response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            items = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        # Regex fallback: try to extract content/type pairs
        for m in re.finditer(r'"content"\s*:\s*"([^"]{10,150})"', raw):
            items.append({"content": m.group(1), "type": "factual"})

    if not items:
        return []

    # Dedup against existing queue
    existing_fingerprints = {
        q.get("content", "")[:40].lower() for q in existing_queue
    }

    results = []
    now = _now_iso()
    for item in items[:max_items]:
        content = item.get("content", "").strip()
        if not content or len(content) < 10:
            continue
        # Skip if too similar to existing
        if content[:40].lower() in existing_fingerprints:
            continue
        knowledge_type = item.get("type", "factual")
        if knowledge_type not in ("factual", "procedural", "architectural", "pitfall", "decision"):
            knowledge_type = "factual"
        results.append({
            "content": content[:150],
            "classification": "[臨]",
            "knowledge_type": knowledge_type,
            "source": source,
            "at": now,
        })
        existing_fingerprints.add(content[:40].lower())

    return results


# ─── V2.4 Phase 3: Cross-Session Pattern Consolidation ──────────────────────


def _check_cross_session_patterns(
    knowledge_items: List[dict], session_id: str, config: Dict[str, Any]
) -> List[dict]:
    """Check if knowledge items appeared in past sessions via vector search.

    For each item, query vector service top-3 (min_score: 0.75).
    Count distinct sessions that mention similar knowledge.
    - 2+ sessions → auto-promote [臨] → [觀]
    - 4+ sessions → mark suggestion to promote [觀] → [固] (not auto)

    Returns list of cross-session observation dicts for episodic atom.
    Also mutates knowledge_items in-place (classification upgrade).
    """
    vs_config = config.get("vector_search", {})
    if not vs_config.get("enabled", True):
        return []

    port = vs_config.get("service_port", 3849)
    cross_session_config = config.get("cross_session", {})
    min_score = cross_session_config.get("min_score", 0.75)
    promote_threshold = cross_session_config.get("promote_threshold", 2)
    suggest_threshold = cross_session_config.get("suggest_threshold", 4)
    timeout_s = cross_session_config.get("timeout_seconds", 5)

    observations: List[dict] = []
    current_session_prefix = session_id[:8] if session_id else ""

    for item in knowledge_items:
        content = item.get("content", "")
        if not content or len(content) < 20:
            continue

        # Query vector search for similar knowledge
        try:
            import urllib.parse
            params = urllib.parse.urlencode({
                "q": content[:200],
                "top_k": 5,
                "min_score": min_score,
            })
            url = f"http://127.0.0.1:{port}/search/ranked?{params}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    results = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    # Fallback to basic /search
                    params = urllib.parse.urlencode({
                        "q": content[:200], "top_k": 5, "min_score": min_score,
                    })
                    url = f"http://127.0.0.1:{port}/search?{params}"
                    req = urllib.request.Request(url, headers={"Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                        results = json.loads(resp.read())
                else:
                    continue

            # Count distinct sessions from results (episodic atoms encode session info)
            session_hits = set()
            for r in results:
                atom_name = r.get("atom_name", "")
                # Episodic atoms: "episodic-YYYYMMDD-slug" → each is a different session
                if "episodic" in atom_name.lower():
                    # Exclude current session's atom (prefix match)
                    if current_session_prefix and current_session_prefix in atom_name:
                        continue
                    session_hits.add(atom_name)
                else:
                    # Non-episodic atoms: check if they contain session references
                    atom_text = r.get("text", r.get("content", ""))
                    if atom_text:
                        session_hits.add(f"atom:{atom_name}")

            hit_count = len(session_hits)
            if hit_count < promote_threshold:
                continue

            # V2.11: No auto-promote — Confirmations +1 only, hint at 4+
            current_class = item.get("classification", "[臨]")
            action = ""

            if hit_count >= suggest_threshold:
                action = f"建議晉升（{hit_count} sessions 命中，需使用者確認）"
            else:
                action = f"跨 session 命中 {hit_count} 次（Confirmations +1）"

            # Increment Confirmations in matched atom files (Path B: cross-session behavior hit)
            for r in results:
                atom_file = r.get("file_path", "")
                if atom_file and os.path.isfile(atom_file):
                    try:
                        atom_text = Path(atom_file).read_text(encoding="utf-8-sig")
                        cm = re.search(r"^(- Confirmations:\s*)(\d+)", atom_text, re.MULTILINE)
                        if cm:
                            new_c = int(cm.group(2)) + 1
                            # S3.0: 走 atom_io.update_atom_field funnel（單欄位 in-place 更新）
                            update_atom_field(
                                Path(atom_file), "Confirmations", str(new_c),
                                source="hook:episodic-confirm",
                            )
                        # Phase B: write correlation_id to access.json
                        try:
                            import uuid as _uuid
                            access_file = Path(atom_file).with_suffix(".access.json")
                            if access_file.exists():
                                adata = json.loads(access_file.read_text(encoding="utf-8"))
                            else:
                                adata = {"timestamps": [], "confirmations": []}
                            if "confirmations" not in adata:
                                adata["confirmations"] = []
                            adata["confirmations"].append({
                                "ts": time.time(),
                                "correlation_id": str(_uuid.uuid4()),
                                "hit_count": hit_count,
                            })
                            adata["confirmations"] = adata["confirmations"][-100:]
                            access_file.write_text(json.dumps(adata), encoding="utf-8")
                        except (OSError, json.JSONDecodeError):
                            pass
                    except (OSError, UnicodeDecodeError):
                        pass

            observations.append({
                "content": content[:80],
                "classification": current_class,
                "sessions_hit": hit_count,
                "action": action,
                "matched_atoms": list(session_hits)[:5],
            })

            print(
                f"[v2.11] Cross-session: \"{content[:40]}...\" → {action}",
                file=sys.stderr,
            )

        except Exception as e:
            print(f"[v2.4] Cross-session check error: {e}", file=sys.stderr)
            continue

    return observations


# ─── V2.11: Conflict Detection ───────────────────────────────────────────────


def _detect_atom_conflicts(
    state: Dict[str, Any], config: Dict[str, Any]
) -> List[dict]:
    """Detect potential conflicts between session-modified atoms and existing atoms.

    For each modified atom file, query vector search (score 0.60-0.95).
    Results in that range suggest semantically similar but different content — potential conflicts.
    """
    vs_config = config.get("vector_search", {})
    if not vs_config.get("enabled", True):
        return []

    port = vs_config.get("service_port", 3849)
    timeout_s = 5
    conflicts: List[dict] = []

    modified = state.get("modified_files", [])
    atom_files = [
        m for m in modified
        if "/memory/" in m.get("path", "").replace("\\", "/")
        and m.get("path", "").endswith(".md")
    ]

    for m in atom_files:
        fpath = m["path"]
        try:
            content = Path(fpath).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue

        # Use first 200 chars as query
        query = content[:200].strip()
        if len(query) < 30:
            continue

        try:
            import urllib.parse
            params = urllib.parse.urlencode({
                "q": query, "top_k": 5, "min_score": 0.60,
            })
            url = f"http://127.0.0.1:{port}/search/ranked?{params}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    results = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    params = urllib.parse.urlencode({
                        "q": query, "top_k": 5, "min_score": 0.60,
                    })
                    url = f"http://127.0.0.1:{port}/search?{params}"
                    req = urllib.request.Request(url, headers={"Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                        results = json.loads(resp.read())
                else:
                    continue

            fname = Path(fpath).stem
            for r in results:
                score = r.get("score", 0)
                other_name = r.get("atom_name", "")
                other_path = r.get("file_path", "")
                # Skip self-match (same file or score > 0.95)
                if score > 0.95 or other_name == fname:
                    continue
                if other_path and os.path.normpath(other_path) == os.path.normpath(fpath):
                    continue
                conflicts.append({
                    "source": fname,
                    "target": other_name,
                    "score": round(score, 3),
                    "snippet": r.get("text", r.get("content", ""))[:80],
                })

        except Exception as e:
            print(f"[v2.11] Conflict detection error: {e}", file=sys.stderr)
            continue

    return conflicts


# ─── Episodic Summary Building ───────────────────────────────────────────────


def _build_episodic_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    """Build structured session summary from state."""
    modified = state.get("modified_files", [])
    area_counts: Counter = Counter()
    for m in modified:
        area = _extract_area(m.get("path", ""))
        area_counts[area] += 1

    work_areas = [{"area": a, "count": c} for a, c in area_counts.most_common()]
    primary_area = work_areas[0]["area"] if work_areas else "session-work"

    knowledge_items = []
    for kq in state.get("knowledge_queue", []):
        knowledge_items.append({
            "content": kq.get("content", "")[:80],
            "classification": kq.get("classification", "[臨]"),
        })

    atoms_referenced = list(state.get("injected_atoms", []))

    # V2.10: Read tracking
    accessed = state.get("accessed_files", [])
    accessed_areas: Counter = Counter()
    for a in accessed:
        area = _extract_area(a.get("path", ""))
        accessed_areas[area] += 1

    # Topic tracker enrichment (v2.2)
    tracker = state.get("topic_tracker", {})
    intent_dist = tracker.get("intent_distribution", {})
    dominant_intent = max(intent_dist, key=intent_dist.get) if intent_dist else "general"

    # V2.10: Use accessed areas as fallback for primary_area when no modifications
    if not work_areas and accessed_areas:
        acc_areas = [{"area": a, "count": c} for a, c in accessed_areas.most_common()]
        primary_area = acc_areas[0]["area"] if acc_areas else "session-work"

    return {
        "work_areas": work_areas,
        "knowledge_items": knowledge_items,
        "atoms_referenced": atoms_referenced,
        "files_modified": len(modified),
        "primary_area": primary_area,
        "dominant_intent": dominant_intent,
        "intent_distribution": intent_dist,
        "prompt_count": tracker.get("prompt_count", 0),
        "session_description": tracker.get("first_prompt_summary", ""),
        "keyword_topics": tracker.get("keyword_signals", []),
        "related_episodic": tracker.get("related_episodic", []),
        "accessed_files": accessed,
        "files_accessed": len(accessed),
        "accessed_areas": [{"area": a, "count": c} for a, c in accessed_areas.most_common()],
        "vcs_queries": state.get("vcs_queries", []),
    }


def _generate_triggers(state: Dict[str, Any], work_areas: list) -> list:
    """Auto-generate trigger keywords from session data."""
    triggers = {"session", "episodic"}

    for wa in work_areas:
        for word in wa["area"].split("-"):
            if len(word) >= 3:
                triggers.add(word.lower())

    for kq in state.get("knowledge_queue", []):
        words = re.findall(r"\b[a-zA-Z]{4,}\b", kq.get("content", ""))
        for w in words[:3]:
            triggers.add(w.lower())

    for atom_name in state.get("injected_atoms", []):
        triggers.add(atom_name.lower())

    # Keyword topics from topic tracker (v2.2)
    for kw in state.get("topic_tracker", {}).get("keyword_signals", [])[:5]:
        triggers.add(kw.lower())

    return sorted(triggers)[:12]


def _update_memory_index(memory_dir: Path, atom_name: str, triggers: list) -> None:
    """Append a row to _ATOM_INDEX.md (V3.2) or MEMORY.md atom index table."""
    # V3.2: prefer _ATOM_INDEX.md
    atom_idx = memory_dir / ATOM_INDEX
    index_path = atom_idx if atom_idx.exists() else memory_dir / MEMORY_INDEX
    if not index_path.exists():
        return

    text = index_path.read_text(encoding="utf-8-sig")
    trigger_str = ", ".join(triggers)
    new_row = f"| {atom_name} | memory/{atom_name}.md | {trigger_str} |"

    lines = text.splitlines()
    insert_idx = None
    in_table = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("| Atom") or stripped.startswith("|Atom"):
            in_table = True
            continue
        if in_table:
            if stripped.startswith("|---"):
                continue
            if stripped.startswith("|"):
                insert_idx = i
            else:
                break

    if insert_idx is not None:
        lines.insert(insert_idx + 1, new_row)
    else:
        lines.append(new_row)

    index_path.write_text("\n".join(lines), encoding="utf-8")


# ─── Episodic Section Builders ───────────────────────────────────────────────


def _build_read_tracking_section(summary: Dict[str, Any]) -> str:
    """Build '## 閱讀軌跡' section — compressed summary (V2.14 token diet).

    Instead of listing every file path (which vector search can't match anyway),
    produce a compact summary: count + area breakdown.
    """
    accessed = summary.get("accessed_files", [])
    vcs = summary.get("vcs_queries", [])
    if not accessed and not vcs:
        return ""
    lines = ["## 閱讀軌跡\n"]
    if accessed:
        # Group by area (parent directory or project)
        areas: Dict[str, int] = {}
        for af in accessed:
            path = af.get("path", "")
            # Extract meaningful area from path
            parts = path.replace("\\", "/").split("/")
            # Use the last 2 significant directory parts as area key
            area = "/".join(p for p in parts[-3:-1] if p) or "root"
            areas[area] = areas.get(area, 0) + 1
        area_parts = [f"{a} ({c})" for a, c in sorted(areas.items(), key=lambda x: -x[1])[:5]]
        lines.append(f"- 讀 {len(accessed)} 檔: {', '.join(area_parts)}")
    if vcs:
        lines.append(f"- 版控查詢 {len(vcs)} 次")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def _build_cross_session_section(state: Dict[str, Any]) -> str:
    """Build '## 跨 Session 觀察' section from cross-session observations."""
    obs = state.get("cross_session_observations", [])
    if not obs:
        return ""
    lines = ["## 跨 Session 觀察\n"]
    for o in obs:
        cls = o.get("classification", "[觀]")
        content = o.get("content", "")
        action = o.get("action", "")
        hits = o.get("sessions_hit", 0)
        lines.append(f"- [{cls.strip('[]')}] \"{content}\" — {hits} sessions 出現，{action}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def _build_conflict_section(state: Dict[str, Any]) -> str:
    """V2.11: Build '## ⚠ 衝突警告' section from conflict detection results."""
    warnings = state.get("conflict_warnings", [])
    if not warnings:
        return ""
    lines = ["## ⚠ 衝突警告\n"]
    for w in warnings:
        lines.append(
            f"- {w['source']} ↔ {w['target']} (score={w['score']}) "
            f"— \"{w.get('snippet', '')[:60]}\""
        )
    lines.append("")
    lines.append("")
    return "\n".join(lines)


# ─── Main Episodic Generation ────────────────────────────────────────────────


def _generate_episodic_atom(
    session_id: str, state: Dict[str, Any], config: Dict[str, Any]
) -> Optional[str]:
    """Auto-generate an episodic atom summarizing this session.

    Returns the filename of the generated atom, or None if skipped.
    Project-scoped: if CWD maps to a known project, episodic goes to project layer.
    """
    if not _should_generate_episodic(state, config):
        return None

    summary = _build_episodic_summary(state)
    slug = _derive_short_summary(summary["primary_area"])
    today = datetime.now().strftime("%Y-%m-%d")
    date_compact = datetime.now().strftime("%Y%m%d")
    expires = (datetime.now() + timedelta(days=24)).strftime("%Y-%m-%d")
    triggers = _generate_triggers(state, summary["work_areas"])

    episodic_dir, scope_label = _resolve_episodic_dir(state)
    episodic_dir.mkdir(parents=True, exist_ok=True)
    atom_path = _resolve_episodic_filename(episodic_dir, date_compact, slug)
    atom_name = atom_path.stem

    # Build knowledge lines
    knowledge_lines = []
    if summary["work_areas"]:
        areas_str = ", ".join(
            f"{wa['area']} ({wa['count']} files)" for wa in summary["work_areas"]
        )
        knowledge_lines.append(f"- [臨] 工作區域: {areas_str}")
    knowledge_lines.append(f"- [臨] 修改 {summary['files_modified']} 個檔案")
    if summary["atoms_referenced"]:
        knowledge_lines.append(
            f"- [臨] 引用 atoms: {', '.join(summary['atoms_referenced'])}"
        )
    for ki in summary["knowledge_items"]:
        # V2.22: Filter out plan-type knowledge items from episodic atoms
        if is_plan_content(ki.get("content", "")):
            continue
        knowledge_lines.append(f"- [{ki['classification'].strip('[]')}] {ki['content']}")

    # V2.10: Read tracking summary
    if summary.get("files_accessed", 0) > 0:
        knowledge_lines.append(f"- [臨] 閱讀 {summary['files_accessed']} 個檔案")
        if summary.get("accessed_areas"):
            read_areas_str = ", ".join(
                f"{ra['area']} ({ra['count']})" for ra in summary["accessed_areas"][:5]
            )
            knowledge_lines.append(f"- [臨] 閱讀區域: {read_areas_str}")
    vcs = summary.get("vcs_queries", [])
    if vcs:
        knowledge_lines.append(f"- [臨] 版控查詢 {len(vcs)} 次")

    # V2.17: 覆轍信號 — record cross-session retry patterns
    rut_signals = []
    edit_counts = state.get("edit_counts", {})
    for fpath, cnt in edit_counts.items():
        if cnt >= 3:
            short = Path(fpath).name
            rut_signals.append(f"same_file_3x:{short}")
    if state.get("wisdom_retry_count", 0) >= 2:
        rut_signals.append("retry_escalation")
    if rut_signals:
        knowledge_lines.append(f"- [臨] 覆轍信號: {', '.join(rut_signals)}")

    # Build 摘要 section (v2.2)
    desc = summary.get("session_description", "")
    dom_intent = summary.get("dominant_intent", "general")
    prompt_count = summary.get("prompt_count", 0)
    summary_line = f"{dom_intent.capitalize()}-focused session ({prompt_count} prompts)."
    if desc:
        summary_line += f" {desc}"

    # Build 關聯 section (v2.2)
    relation_lines = []
    intent_dist = summary.get("intent_distribution", {})
    if intent_dist:
        dist_str = ", ".join(f"{k} ({v})" for k, v in
                             sorted(intent_dist.items(), key=lambda x: -x[1]))
        relation_lines.append(f"- 意圖分布: {dist_str}")
    related_ep = summary.get("related_episodic", [])
    if related_ep:
        relation_lines.append(f"- Related sessions: {', '.join(related_ep)}")
    if summary["atoms_referenced"]:
        relation_lines.append(
            f"- Referenced atoms: {', '.join(summary['atoms_referenced'])}"
        )

    content = (
        f"# Session: {today} {summary['primary_area']}\n"
        f"\n"
        f"- Scope: {scope_label}\n"
        f"- Confidence: [臨]\n"
        f"- Type: episodic\n"
        f"- Trigger: {', '.join(triggers)}\n"
        f"- Last-used: {today}\n"
        f"- Created: {today}\n"
        f"- Confirmations: 0\n"
        f"- ReadHits: 0\n"
        f"- TTL: 24d\n"
        f"- Expires-at: {expires}\n"
        f"\n"
        f"## 摘要\n"
        f"\n"
        f"{summary_line}\n"
        f"\n"
        f"## 知識\n"
        f"\n"
        + "\n".join(knowledge_lines)
        + f"\n"
        f"\n"
        + (f"## 關聯\n\n" + "\n".join(relation_lines) + "\n\n" if relation_lines else "")
        + _build_read_tracking_section(summary)
        + _build_cross_session_section(state)
        + _build_conflict_section(state)
        + f"## 行動\n"
        f"\n"
        f"- session 自動摘要，TTL 24d 後自動淘汰\n"
        f"- 若需長期保留特定知識，應遷移至專屬 atom\n"
        f"\n"
        f"## 演化日誌\n"
        f"\n"
        f"| 日期 | 變更 | 來源 |\n"
        f"|------|------|------|\n"
        f"| {today} | 自動建立 episodic atom (v2.2) | session:{session_id[:8]} |\n"
    )

    # S3.3: episodic atom 走 funnel write_raw（在 SKIP_DIRS 不算 V4 atom，
    # 但仍經 audit log 確保 PreToolUse 強制門禁可放行）
    write_raw(atom_path, content, source="hook:episodic", op="episodic_create")
    # v2.2: Episodic atoms NOT listed in MEMORY.md index (TTL 24d, vector search discovers them)

    # Debug log: one-line summary instead of full content (full is in atom file)
    kn_count = len(knowledge_lines)
    _atom_debug_log(
        "萃取:episodic",
        f"{atom_path.name} | {scope_label} | {summary_line[:80]} | {kn_count} 筆知識 | TTL 24d → {expires}",
        config,
    )
    print(f"[episodic] Generated: {atom_path.name} (scope: {scope_label})", file=sys.stderr)
    return atom_name


# ─── V2.7: Output Quality Feedback ──────────────────────────────────────────


def _check_output_quality(
    file_path: str, session_id: str, config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Check if file_path was modified in a recent (different) session.

    Scans recent state files for ended sessions. If the same file was
    modified in a previous session, returns a quality feedback record.
    Returns None if no match or if the file is a memory/plan file.
    """
    normalized = file_path.replace("\\", "/").lower()

    # Skip memory atoms and plan files — they're expected to be updated often
    if "/memory/" in normalized or "/plans/" in normalized:
        return None

    scan_count = config.get("quality_feedback", {}).get("scan_recent_sessions", 5)

    try:
        state_files = sorted(
            WORKFLOW_DIR.glob("state-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception as e:
        _atom_debug_error("萃取:_check_output_quality:glob", e)
        return None

    for sf in state_files[:scan_count + 5]:  # scan extra to skip active sessions
        sid = sf.stem.replace("state-", "")
        if sid == session_id:
            continue

        try:
            with sf.open(encoding="utf-8") as f:
                prev = json.load(f)
        except Exception as e:
            _atom_debug_error(f"萃取:_check_output_quality:parse:{sf.name}", e)
            continue

        # Only check ended sessions
        if not prev.get("ended_at"):
            continue

        prev_files = {
            m.get("path", "").replace("\\", "/").lower()
            for m in prev.get("modified_files", [])
        }

        if normalized in prev_files:
            return {
                "path": file_path,
                "original_session": sid[:8],
                "original_ended": prev.get("ended_at", ""),
                "at": _now_iso(),
            }

    return None
