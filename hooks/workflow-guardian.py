#!/usr/bin/env python3
"""
workflow-guardian.py — Workflow Guardian Hook Script

Claude Code hooks 的統一入口，從 stdin 讀取 JSON，
根據 hook_event_name 分派到對應 handler。

Handles: SessionStart, UserPromptSubmit, PostToolUse,
         PreCompact, Stop, SessionEnd

Requirements: Python 3.8+, zero external dependencies.
"""

import json
import os
import subprocess
import sys
import re
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── 確保模組搜尋路徑包含 hooks/ 目錄（runpy.run_path 不會自動加）─────────
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ─── wg_paths: path constants & functions (V2.20 single source of truth) ─────
from wg_paths import (
    CLAUDE_DIR, WORKFLOW_DIR, MEMORY_DIR, EPISODIC_DIR, CONFIG_PATH,
    MEMORY_INDEX,
    cwd_to_project_slug, get_project_memory_dir, find_project_root,
    resolve_episodic_dir, resolve_failures_dir, resolve_staging_dir,
    resolve_access_json, discover_all_project_memory_dirs, register_project,
)
# ─── wg_core: config, state I/O, output, debug ──────────────────────────────
from wg_core import (
    CONTEXT_BUDGET_DEFAULT, DEFAULTS,
    load_config,
    _now_iso, _estimate_tokens,
    state_path, read_state, write_state, new_state, _ensure_state,
    _find_active_sibling_state,  # V3/1.5A: SessionStart dedup
    output_json, output_nothing, output_block,
    _atom_debug_log, _atom_debug_error,
)
from wg_iteration import (
    _collect_iteration_metrics, _detect_oscillation,
    _calculate_maturity_phase, _self_iterate_atoms,
    _save_oscillation_state, _load_oscillation_warnings,
    _detect_rut_patterns, _check_periodic_review_due, _save_review_marker,
)
from wg_atoms import (
    TABLE_ROW_RE, ALIAS_RE, AtomEntry, AiDocsEntry,
    parse_memory_index, _parse_atom_index_file, parse_project_aliases,
    _find_atom_path, spread_related, compute_activation,
    _kw_match, match_triggers, compute_token_budget,
    _STRIP_META_RE, _STRIP_SECTION_RE, _strip_atom_for_injection,
    SECTION_INJECT_THRESHOLD, _extract_sections,
    load_atoms_within_budget, _truncate_context_by_activation,
    parse_aidocs_index, extract_aidocs_keywords,
)
from wg_intent import (
    INTENT_PATTERNS, classify_intent,
    _update_topic_tracker,
    _search_episodic_context, _build_session_context,
    _detect_cross_session_patterns, _proactive_classify,
    _check_mcp_servers, _ensure_vector_service,
    _semantic_search, _trigger_incremental_index,
)
from wg_extraction import (
    _is_pid_alive, _find_transcript, _count_new_assistant_chars,
    _spawn_extract_worker, _maybe_spawn_per_turn_extraction,
    _detect_failure_keywords, _maybe_spawn_failure_extraction,
)
from wg_episodic import (
    _should_generate_episodic, _extract_area,
    _find_session_transcript, _extract_all_assistant_texts,
    _call_ollama_generate, _EXTRACT_PROMPT_TEMPLATE, _llm_extract_knowledge,
    _check_cross_session_patterns, _detect_atom_conflicts,
    _build_episodic_summary, _derive_short_summary, _resolve_episodic_filename,
    _generate_triggers, _update_memory_index,
    _build_read_tracking_section, _build_cross_session_section, _build_conflict_section,
    _resolve_episodic_dir, _generate_episodic_atom,
    _check_output_quality,
)

sys.path.insert(0, str(Path.home() / ".claude" / "tools"))
from ollama_client import get_client, check_long_die_status, disable_backend, OllamaClient

# ─── V2.8: Wisdom Engine (lazy import, graceful fallback) ────────────────────
try:
    from wisdom_engine import (
        classify_situation,
        get_reflection_summary,
        reflect as wisdom_reflect,
        track_retry as wisdom_track_retry,
    )
    WISDOM_AVAILABLE = True
except ImportError:
    WISDOM_AVAILABLE = False

# ─── V3: Hot Cache (lazy import, graceful fallback) ─────────────────────────
try:
    from wg_hot_cache import read_hot_cache, mark_injected, HOT_CACHE_PATH
except ImportError:
    read_hot_cache = None


# (State I/O moved to wg_core.py)


# (Intent, Topic Tracker, Session Context, MCP, Vector Service moved to wg_intent.py)

# V2.22: Use shared content classifier (was inline _AIDOCS_TEMP_PATTERNS)
from wg_content_classify import is_plan_filename, is_plan_content
_SUPERSEDES_RE = re.compile(r"^- Supersedes:\s*(.+)", re.MULTILINE)

# ─── Project Delegate Hook (V2.21) ───────────────────────────────────────────


def _call_project_hook(project_root: Path, action: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call project-level delegate hook via subprocess isolation.

    Looks for {project_root}/.claude/hooks/project_hooks.py.
    Communicates via stdin/stdout JSON. Timeout 5s.
    Never raises — hook failure must not block core flow.
    """
    hook_script = project_root / ".claude" / "hooks" / "project_hooks.py"
    if not hook_script.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(hook_script), action],
            input=json.dumps(context, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError, Exception) as e:
        _atom_debug_error(f"project_hook:{action}", e)
    return None


# ─── Event Handlers ──────────────────────────────────────────────────────────


def handle_session_start(input_data: Dict[str, Any], config: Dict[str, Any]) -> None:
    session_id = input_data.get("session_id", "unknown")
    cwd = input_data.get("cwd", "")
    source = input_data.get("source", "startup")

    # ── V3/1.5A: SessionStart 去重 — 同 cwd 60s 內有活躍 state 則複用 ──
    sibling = None
    if source != "compact":
        sibling = _find_active_sibling_state(cwd, session_id)
        if sibling and source == "resume":
            # Resume 合併到既有 startup session
            redirect_state = new_state(session_id, cwd, source)
            redirect_state["merged_into"] = sibling["session"]["id"]
            redirect_state["phase"] = "merged"
            write_state(session_id, redirect_state)
            lines = [f"[Workflow Guardian] Session merged ({source})."]
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "\n".join(lines),
                }
            }, ensure_ascii=False))
            sys.exit(0)
        # startup + sibling: 繼續正常流程但後面跳過 vector init

    # On compact/resume, reuse existing state
    existing = read_state(session_id)
    if existing and source in ("compact", "resume"):
        state = existing
        # V3/Phase 2: Atom Recovery — 告知壓縮前已載入的 atoms
        prev_atoms = state.get("injected_atoms", [])
        # Clear injected_atoms so atoms get re-injected after compact (context was truncated)
        state["injected_atoms"] = []
        # Re-inject full context after compaction
        mod_count = len(state.get("modified_files", []))
        kq_count = len(state.get("knowledge_queue", []))
        phase = state.get("phase", "working")
        lines = [
            f"[Workflow Guardian] Session resumed ({source}). Phase: {phase}.",
            f"Modified files: {mod_count}. Knowledge queue: {kq_count}.",
        ]
        if mod_count > 0:
            files = [m["path"].rsplit("/", 1)[-1] for m in state["modified_files"][-5:]]
            lines.append(f"Recent: {', '.join(files)}")
        if kq_count > 0:
            items = [q["content"][:40] for q in state["knowledge_queue"][:3]]
            lines.append(f"Pending knowledge: {'; '.join(items)}")
        # V3/Phase 2: Atom Recovery hint
        if prev_atoms:
            atom_names = ", ".join(prev_atoms)
            lines.append(f"[Atom Recovery] 壓縮前已載入: {atom_names}")
    else:
        state = new_state(session_id, cwd, source)
        # V3/1.5A: startup + sibling → skip vector init
        if sibling and source == "startup":
            state["_skip_vector_init"] = True

        # Parse memory indices (store as serializable lists)
        global_atoms = parse_memory_index(MEMORY_DIR)
        project_mem_dir = get_project_memory_dir(cwd)
        project_atoms = parse_memory_index(project_mem_dir) if project_mem_dir else []
        project_root = find_project_root(cwd)

        # V2.21: Register project in registry (update last_seen)
        register_project(cwd)

        state["atom_index"] = {
            "global": [(n, p, t) for n, p, t in global_atoms],
            "project": [(n, p, t) for n, p, t in project_atoms],
            "project_memory_dir": str(project_mem_dir) if project_mem_dir else "",
            "project_root": str(project_root) if project_root else "",
        }
        state["injected_atoms"] = []
        state["phase"] = "working"

        # ── v2.10: _AIDocs Bridge — scan project _AIDocs index ──────────
        aidocs_entries = parse_aidocs_index(project_root) if project_root else []
        aidocs_keywords = extract_aidocs_keywords(aidocs_entries) if aidocs_entries else {}
        state["aidocs"] = {
            "project_root": str(project_root) if project_root else "",
            "entries": [(f, d) for f, d, _kw in aidocs_entries],
            "keywords": aidocs_keywords,
        }

        g_names = [n for n, _, _ in global_atoms]
        p_names = [n for n, _, _ in project_atoms]
        lines = [
            "[Workflow Guardian] Active.",
            f"Global: {len(g_names)} atoms. Project: {len(p_names)}.",
        ]

        # Inject compact _AIDocs index (v2.10, v2.18 trimmed)
        max_entries = config.get("aidocs", {}).get("max_session_start_entries", 15)
        if aidocs_entries:
            fnames = [f for f, _d, _kw in aidocs_entries[:max_entries]]
            lines.append(f"[AIDocs] {len(aidocs_entries)} docs: {', '.join(fnames)}")

        # ── V2.21: Project delegate hook — on_session_start ──────────────
        if project_root:
            try:
                ph_result = _call_project_hook(
                    project_root, "session_start",
                    {"cwd": cwd, "session_id": session_id},
                )
                if ph_result:
                    for extra_line in ph_result.get("lines", []):
                        if extra_line:
                            lines.append(extra_line)
            except Exception as e:
                _atom_debug_error("project_hook:session_start", e)

    # ── V2.6: Periodic review check ─────────────────────────────────────
    try:
        review_reminder = _check_periodic_review_due(config)
        if review_reminder:
            lines.append(review_reminder)
            state["review_due"] = True
    except Exception as e:
        print(f"[v2.6] Review check error: {e}", file=sys.stderr)

    # ── V2.16: Oscillation warnings from previous session ──────────
    try:
        osc_warning = _load_oscillation_warnings()
        if osc_warning:
            lines.append(osc_warning)
    except Exception as e:
        print(f"[v2.16] Oscillation load error: {e}", file=sys.stderr)

    # ── V2.17: 覆轍偵測 — cross-session repeated failure patterns ──
    try:
        rut_warning = _detect_rut_patterns(state, config)
        if rut_warning:
            lines.append(rut_warning)
    except Exception as e:
        print(f"[v2.17] Rut detection error: {e}", file=sys.stderr)

    # ── V2.8: Wisdom Engine — reflection blind spots ───────────────
    if WISDOM_AVAILABLE:
        try:
            wisdom_lines = get_reflection_summary()
            lines.extend(wisdom_lines)
        except Exception as e:
            print(f"[v2.8] Wisdom reflection error: {e}", file=sys.stderr)

    # ── Dual-Backend: long_die user confirmation ────────────────────────
    try:
        long_die = check_long_die_status()
        if long_die:
            backend_name = long_die.get("backend", "remote")
            until = long_die.get("until", "?")
            lines.append(
                f"[⚠ Long DIE] 遠端 Ollama backend '{backend_name}' 多次連線失敗，"
                f"已暫停至 {until}。請確認是否要永久停用此 backend？"
                f"（回覆「停用 {backend_name}」或「保持」）"
            )
    except Exception as e:
        print(f"[dual-backend] Long DIE check error: {e}", file=sys.stderr)

    # ── MCP Server health check ──────────────────────────────────────
    try:
        mcp_issues = _check_mcp_servers()
        if mcp_issues:
            lines.append("[MCP] " + "; ".join(mcp_issues))
    except Exception as e:
        print(f"[mcp-health] Check error: {e}", file=sys.stderr)

    # CRITICAL: write state before any output so subsequent hooks can read it.
    write_state(session_id, state)

    # V3/2.2A: Clean up stale state files on every SessionStart
    try:
        _cleanup_old_states()
    except Exception as e:
        print(f"[v3] SessionStart cleanup error: {e}", file=sys.stderr)

    # V3/1.5C: Clear vector_ready.flag (will be re-created by background process)
    try:
        (WORKFLOW_DIR / "vector_ready.flag").unlink(missing_ok=True)
    except OSError:
        pass

    # C5/W11 fix: print directly (not via output_json which exits),
    # then spawn vector init as fire-and-forget subprocess, then exit.
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }, ensure_ascii=False))

    # ── V3/1.5C: Vector service — fire-and-forget subprocess ────────────
    # Replaces synchronous _ensure_vector_service + separate warmup.
    # Background subprocess: health check → port guard + spawn → poll ready → flag → warmup.
    if (config.get("vector_search", {}).get("auto_start_service", True)
            and not state.get("_skip_vector_init")):
        try:
            vs_port = config.get("vector_search", {}).get("service_port", 3849)
            vs_script = str(CLAUDE_DIR / "tools" / "vector-service.py")
            flag_path = str(WORKFLOW_DIR / "vector_ready.flag")
            # Inline script: health check → spawn if needed → poll → flag → warmup
            _bg_code = f"""
import urllib.request, urllib.error, subprocess, sys, time, os
from pathlib import Path

port = {vs_port}
base = f"http://127.0.0.1:{{port}}"

# 1. Health check (2s timeout)
try:
    urllib.request.urlopen(f"{{base}}/health", timeout=2)
except Exception:
    # 2. Port guard + spawn service
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.close()
        # Port free → spawn
        kw = {{"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}}
        if sys.platform == "win32":
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        else:
            kw["start_new_session"] = True
        subprocess.Popen([sys.executable, {repr(vs_script)}], **kw)
    except OSError:
        sock.close()  # Port in use — service likely starting

# 3. Poll ready (30 × 0.5s = 15s max)
for _ in range(30):
    try:
        urllib.request.urlopen(f"{{base}}/health", timeout=2)
        break
    except Exception:
        time.sleep(0.5)

# 4. Write ready flag
Path({repr(flag_path)}).write_text("ready", encoding="utf-8")

# 5. Warmup query
try:
    urllib.request.urlopen(f"{{base}}/search?q=warmup&top_k=1&min_score=0.99", timeout=15)
except Exception:
    pass
"""
            _bg_kwargs: dict = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                _bg_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            else:
                _bg_kwargs["start_new_session"] = True
            subprocess.Popen(
                [sys.executable, "-c", _bg_code],
                **_bg_kwargs,
            )
        except Exception as e:
            _atom_debug_error("注入:vector_service_bg", e)

    sys.exit(0)


def _is_memory_system_dev(prompt_lower: str, cwd: str) -> bool:
    """嚴格判斷是否為記憶系統開發場景。需 2+ 命中或 CWD 匹配。"""
    # Rule 1: CWD 在 hooks/tools 目錄下 → 直接觸發
    cwd_norm = cwd.replace("\\", "/")
    if "/.claude/hooks" in cwd_norm or "/.claude/tools" in cwd_norm:
        return True
    # Rule 2: 複合關鍵詞（需 2+ 命中）
    MEM_KEYWORDS = [
        "workflow-guardian", "wg_", "atom memory", "原子記憶",
        "wisdom_engine", "記憶系統", "memory system",
        "hot_cache", "extract-worker", "vector service",
        "hook pipeline", "萃取管線", "注入管線",
    ]
    hits = sum(1 for kw in MEM_KEYWORDS if kw in prompt_lower)
    return hits >= 2


def handle_user_prompt_submit(
    input_data: Dict[str, Any], config: Dict[str, Any]
) -> None:
    session_id = input_data.get("session_id", "")
    state = _ensure_state(session_id, input_data, config)
    if not state:
        output_nothing()
        return

    prompt = input_data.get("prompt", "")
    # Strip IDE context tags to avoid false keyword matches on tag content
    clean_prompt = re.sub(r'<ide_\w+>.*?</ide_\w+>', '', prompt, flags=re.DOTALL).strip()
    prompt_lower = clean_prompt.lower()
    lines: List[str] = []

    # ─── Dual-Backend: long_die user response ─────────────────────────
    try:
        long_die = check_long_die_status()
        if long_die:
            backend_name = long_die.get("backend", "")
            if any(kw in prompt_lower for kw in ("停用", "disable")):
                if disable_backend(backend_name):
                    OllamaClient._clear_long_die_marker()
                    lines.append(
                        f"[Dual-Backend] 已永久停用 '{backend_name}'。"
                        f"如需重新啟用，修改 config.json 中 enabled: true。"
                    )
                else:
                    lines.append(f"[Dual-Backend] 停用 '{backend_name}' 失敗，請手動修改 config.json。")
            elif any(kw in prompt_lower for kw in ("保持", "keep", "忽略")):
                OllamaClient._clear_long_die_marker()
                lines.append(f"[Dual-Backend] 保持 '{backend_name}'，long_die 將在時間段到期後自動恢復。")
    except Exception as e:
        print(f"[dual-backend] Long DIE response error: {e}", file=sys.stderr)

    # ─── V3/Phase -1: Hot Cache Fast Path ───────────────────────────────
    hot_cache_tokens = 0
    if read_hot_cache:
        try:
            hot_data = read_hot_cache(session_id)
            if hot_data:
                lines.append(f"[HotCache:{hot_data.get('source', '?')}] {hot_data.get('summary', '')}")
                hot_cache_tokens = hot_data.get("token_estimate", 50)
                mark_injected(session_id)
        except Exception:
            pass

    # ─── Phase 0: Session Context Injection (first prompt only) ────────
    budget = compute_token_budget(prompt)
    budget = max(budget - hot_cache_tokens, 500)  # V3: deduct hot cache tokens
    if not state.get("session_context_injected", False):
        state["session_context_injected"] = True
        episodic_results = _search_episodic_context(prompt, config)
        if episodic_results:
            # Build compact context block
            ctx_lines = _build_session_context(episodic_results)
            if ctx_lines:
                lines.extend(ctx_lines)
                # Reserve tokens for episodic context
                sc_config = config.get("session_context", {})
                reserved = sc_config.get("reserved_tokens", 200)
                budget = max(budget - reserved, 500)
            # Proactive classification (cross-session patterns, migration hints)
            proactive_lines = _proactive_classify(state, episodic_results, prompt, config)
            lines.extend(proactive_lines)

    # ─── V2.8: Wisdom Engine — situation classification ──────────
    if WISDOM_AVAILABLE:
        try:
            mod_paths = [m["path"] for m in state.get("modified_files", [])]
            tracker = state.get("topic_tracker", {})
            prompt_analysis = {
                "intent": tracker.get("intent_distribution", {}).get("top", ""),
                "keywords": tracker.get("keyword_signals", []),
                "estimated_files": max(len(mod_paths), 1),
            }
            result = classify_situation(prompt_analysis)
            if result.get("inject"):
                lines.append(result["inject"])
            # 記錄最高 approach 供 SessionEnd reflect() 使用
            cur = result.get("approach", "direct")
            prev = state.get("wisdom_approach", "direct")
            rank = {"direct": 0, "confirm": 1, "plan": 2}
            if rank.get(cur, 0) > rank.get(prev, 0):
                state["wisdom_approach"] = cur
        except Exception as e:
            print(f"[v2.8] Wisdom prompt error: {e}", file=sys.stderr)

    # ─── Phase 0.5: _AIDocs keyword matching (v2.10) ──────────────────
    aidocs_state = state.get("aidocs", {})
    aidocs_kw_map = aidocs_state.get("keywords", {})
    max_matches = config.get("aidocs", {}).get("max_prompt_matches", 3)
    if aidocs_kw_map and prompt.strip():
        matched_docs: List[str] = []
        for fname, keywords in aidocs_kw_map.items():
            if any(_kw_match(kw, prompt_lower) for kw in keywords):
                matched_docs.append(fname)
        if matched_docs and len(matched_docs) <= 5:
            aidocs_root = aidocs_state.get("project_root", "")
            pointer_lines = ["[Guardian:AIDocs] Relevant project docs:"]
            for doc in matched_docs[:max_matches]:
                desc = ""
                for f, d in aidocs_state.get("entries", []):
                    if f == doc:
                        desc = d
                        break
                doc_path = f"_AIDocs/{doc}" if aidocs_root else doc
                pointer_lines.append(f"  \u2192 Read `{doc_path}` \u2014 {desc[:80]}")
            lines.extend(pointer_lines)

    # ── V3.1: JIT load internal pipeline reference for memory system dev ──
    if _is_memory_system_dev(prompt_lower, state.get("session", {}).get("cwd", "")):
        ref_path = MEMORY_DIR / "_reference" / "internal-pipeline.md"
        if ref_path.exists():
            try:
                ref_text = ref_path.read_text(encoding="utf-8")
                ref_tokens = len(ref_text) // 4
                jit_budget = min(ref_tokens, 250)
                if jit_budget <= budget:
                    lines.append(f"[JIT:InternalPipeline]\n{ref_text[:jit_budget * 4]}")
                    budget -= jit_budget
            except (OSError, UnicodeDecodeError):
                pass

    # ─── Phase 1: Atom auto-injection (Trigger matching) ─────────────
    atom_index = state.get("atom_index", {})
    already_injected = state.get("injected_atoms", [])
    # budget already computed above (possibly reduced by Phase 0)

    # Collect all atoms from both layers
    # rel_path is relative to the PARENT of memory dir (e.g. ~/.claude/ or ~/.claude/projects/slug/)
    all_atoms: List[Tuple[AtomEntry, Path]] = []
    for entry in atom_index.get("global", []):
        name, rel_path, triggers = entry
        all_atoms.append(((name, rel_path, triggers), MEMORY_DIR.parent))
    proj_dir_str = atom_index.get("project_memory_dir", "")
    proj_root_str = atom_index.get("project_root", "")
    if proj_dir_str:
        proj_parent = Path(proj_dir_str).parent  # projects/slug/memory → projects/slug/
        proj_root = Path(proj_root_str) if proj_root_str else None
        for entry in atom_index.get("project", []):
            name, rel_path, triggers = entry
            # _AIAtoms/ paths are relative to project root, others to projects/slug/
            if rel_path.startswith("_AIAtoms/") and proj_root:
                base = proj_root
            else:
                base = proj_parent
            all_atoms.append(((name, rel_path, triggers), base))

    # Match prompt against triggers (keyword)
    matched_with_dir: List[Tuple[AtomEntry, Path]] = []
    prompt_lower = prompt.lower()
    alias_injected_projects: set = set()  # v2.9: track alias-injected projects

    # ── Cross-project atom discovery (v2.5) + alias matching (v2.9) ──
    # Scan ALL project memory dirs for trigger matches, not just CWD project.
    _MAX_CROSS_PROJECT_SCAN = 20

    loaded_proj_names = set()
    if proj_dir_str:
        loaded_proj_names.add(Path(proj_dir_str).parent.name)
    # V2.20 W13: limit cross-project scan; sort by recency to keep most active first
    _all_cross = [
        (s, m) for s, m in discover_all_project_memory_dirs()
        if s not in loaded_proj_names
    ]
    if len(_all_cross) > _MAX_CROSS_PROJECT_SCAN:
        def _mem_mtime(item: Tuple[str, Path]) -> float:
            try:
                return item[1].stat().st_mtime
            except OSError:
                return 0.0
        _all_cross = sorted(_all_cross, key=_mem_mtime, reverse=True)[:_MAX_CROSS_PROJECT_SCAN]
    for _cross_slug, cross_mem in _all_cross:
        if _cross_slug in loaded_proj_names:
            continue
        # v2.9: Check project aliases before trigger matching
        aliases = parse_project_aliases(cross_mem)
        if aliases and any(alias in prompt_lower for alias in aliases):
            try:
                mem_text = (cross_mem / MEMORY_INDEX).read_text(encoding="utf-8-sig")
                # v2.18: Strip index table from ProjectMemory injection
                mem_lines = mem_text.split("\n")
                mem_lines = [l for l in mem_lines if not (l.startswith("|") and "|" in l[1:])]
                mem_text = "\n".join(l for l in mem_lines if l.strip()).strip()
                lines.append(f"[Guardian:AliasMatch] {_cross_slug} matched via alias")
                if mem_text:
                    lines.append(f"[ProjectMemory:{_cross_slug}]\n{mem_text}")
                alias_injected_projects.add(_cross_slug)
            except (OSError, UnicodeDecodeError):
                pass
        # Existing trigger-based cross-atom discovery
        cross_atoms = parse_memory_index(cross_mem)
        if not cross_atoms:
            continue
        cross_parent = cross_mem.parent
        for name, rel_path, triggers in cross_atoms:
            if name not in already_injected and sum(_kw_match(kw, prompt_lower) for kw in triggers) >= 2:
                all_atoms.append(((name, rel_path, triggers), cross_parent))
                _atom_debug_log("CrossProject", f"{_cross_slug}/{name} matched", config)
    for (name, rel_path, triggers), base_dir in all_atoms:
        if name not in already_injected and any(_kw_match(kw, prompt_lower) for kw in triggers):
            matched_with_dir.append(((name, rel_path, triggers), base_dir))

    # ── Intent classification (v2.1) ────────────────────────────────
    intent = classify_intent(prompt)

    # ── Semantic search (supplement, ranked by intent v2.1) ──────
    kw_matched_names = {e[0][0] for e in matched_with_dir}
    sem_atoms = _semantic_search(prompt, config, intent=intent)
    # v2.18: Build section hints map from semantic search results
    section_hints: Dict[str, List[Dict]] = {}
    for sem_entry in sem_atoms:
        sem_name, sem_path = sem_entry[0], sem_entry[1]
        sem_sections = sem_entry[3] if len(sem_entry) > 3 else []
        if sem_sections:
            section_hints[sem_name] = sem_sections
        if sem_name in kw_matched_names or sem_name in already_injected:
            continue
        # Find the base_dir for this atom from all_atoms
        for (name, rel_path, triggers), base_dir in all_atoms:
            if name == sem_name:
                matched_with_dir.append(((name, rel_path, triggers), base_dir))
                kw_matched_names.add(name)
                break

    # ── Supersedes filtering (v2.1 Sprint 3) ────────────────────
    # If atom A supersedes atom B, and both matched, drop B
    superseded_names: set = set()
    for (name, rel_path, triggers), base_dir in matched_with_dir:
        atom_path = (base_dir / rel_path) if rel_path else (base_dir / "memory" / f"{name}.md")
        if not atom_path.exists():
            continue
        try:
            text = atom_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        sm = _SUPERSEDES_RE.search(text)
        if sm:
            for old in sm.group(1).split(","):
                old = old.strip()
                if old:
                    superseded_names.add(old)
    if superseded_names:
        matched_with_dir = [
            entry for entry in matched_with_dir
            if entry[0][0] not in superseded_names
        ]

    # ── ACT-R Activation Sorting (v2.9) ─────────────────────────
    # Sort matched atoms by time-weighted activation score (high → low)
    def _activation_key(entry):
        (name, rel_path, _triggers), base_dir = entry
        atom_dir = (base_dir / rel_path).parent if rel_path else (base_dir / "memory")
        return compute_activation(name, atom_dir)

    matched_with_dir.sort(key=_activation_key, reverse=True)

    # Load atoms within budget
    newly_injected: List[str] = []
    atom_source_dirs: Dict[str, Path] = {}
    if matched_with_dir:
        atom_lines: List[str] = []
        used_tokens = 0

        for (name, rel_path, triggers), base_dir in matched_with_dir:
            atom_path = (base_dir / rel_path) if rel_path else (base_dir / "memory" / f"{name}.md")
            if not atom_path.exists():
                continue
            atom_source_dirs[name] = atom_path.parent
            try:
                content = atom_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue

            content = _strip_atom_for_injection(content)
            content_tokens = len(content) // 4  # char-to-token estimate

            # v2.18: Section-level injection when hints available and atom is large enough
            if name in section_hints and content_tokens > SECTION_INJECT_THRESHOLD:
                extracted = _extract_sections(content, section_hints[name])
                if extracted is not None:
                    content = extracted
                    content_tokens = len(content) // 4

            if used_tokens + content_tokens <= budget:
                atom_lines.append(f"[Atom:{name}]\n{content}")
                newly_injected.append(name)
                used_tokens += content_tokens
            else:
                # Over budget: summary only
                first_line = content.split("\n", 1)[0].strip("# ").strip()
                display_path = rel_path or f"{name}.md"
                atom_lines.append(f"[Atom:{name}] {first_line} (full: Read {display_path})")
                newly_injected.append(name)
                break

        # ── Related-Edge Spreading (v2.9) ─────────────────────────
        related_entries = spread_related(
            set(newly_injected), all_atoms, already_injected, max_depth=1,
        )
        for (rname, rel_path, _triggers), base_dir in related_entries:
            if rname in newly_injected:
                continue
            rpath = (base_dir / rel_path) if rel_path else (base_dir / "memory" / f"{rname}.md")
            if not rpath.exists():
                continue
            atom_source_dirs[rname] = rpath.parent
            try:
                content = rpath.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            content = _strip_atom_for_injection(content)
            content_tokens = len(content) // 4
            if used_tokens + content_tokens <= budget:
                atom_lines.append(f"[Atom:{rname}] (related)\n{content}")
                newly_injected.append(rname)
                used_tokens += content_tokens
            else:
                first_line = content.split("\n", 1)[0].strip("# ").strip()
                atom_lines.append(f"[Atom:{rname}] (related) {first_line} (full: Read {rel_path or rname + '.md'})")
                newly_injected.append(rname)
                break

        if atom_lines:
            lines.extend(atom_lines)
            state["injected_atoms"] = already_injected + newly_injected

            # Auto-update Last-used timestamp + Confirmations++ in injected atom files (v2.1)
            today_str = datetime.now().strftime("%Y-%m-%d")
            last_used_re = re.compile(r"^(- Last-used:\s*)\d{4}-\d{2}-\d{2}", re.MULTILINE)
            confirmations_re = re.compile(r"^(- Confirmations:\s*)(\d+)", re.MULTILINE)
            confidence_re = re.compile(r"^- Confidence:\s*(\[(?:臨|觀|固)\])", re.MULTILINE)
            PROMOTION_THRESHOLDS = {"[臨]": 2, "[觀]": 4}
            PROMOTION_TARGETS = {"[臨]": "[觀]", "[觀]": "[固]"}
            for inj_name in newly_injected:
                for (name, rel_path, triggers), base_dir in matched_with_dir:
                    if name != inj_name:
                        continue
                    apath = (base_dir / rel_path) if rel_path else (base_dir / "memory" / f"{name}.md")
                    if not apath.exists():
                        break
                    try:
                        text = apath.read_text(encoding="utf-8-sig")
                        changed = False
                        new_count = None
                        # Update Last-used
                        if last_used_re.search(text):
                            new_text = last_used_re.sub(rf"\g<1>{today_str}", text)
                            if new_text != text:
                                text = new_text
                                changed = True
                        # Confirmations++ (v2.1)
                        cm = confirmations_re.search(text)
                        if cm:
                            new_count = int(cm.group(2)) + 1
                            text = confirmations_re.sub(rf"\g<1>{new_count}", text)
                            changed = True
                        elif "- Last-used:" in text:
                            # No Confirmations field yet — add it after Last-used
                            text = re.sub(
                                r"^(- Last-used:\s*.+)$",
                                r"\1\n- Confirmations: 1",
                                text, count=1, flags=re.MULTILINE,
                            )
                            new_count = 1
                            changed = True
                        if changed:
                            apath.write_text(text, encoding="utf-8")
                        # ACT-R access log (v2.9)
                        try:
                            access_file = apath.parent / f"{name}.access.json"
                            if access_file.exists():
                                adata = json.loads(access_file.read_text(encoding="utf-8"))
                            else:
                                adata = {"timestamps": []}
                            adata["timestamps"].append(time.time())
                            adata["timestamps"] = adata["timestamps"][-50:]
                            access_file.write_text(json.dumps(adata), encoding="utf-8")
                        except (OSError, json.JSONDecodeError):
                            pass
                        # Promotion hint (v2.11) — no auto-promote, hint only
                        if new_count is not None:
                            conf_m = confidence_re.search(text)
                            if conf_m:
                                cur = conf_m.group(1)
                                threshold = PROMOTION_THRESHOLDS.get(cur)
                                if threshold and new_count >= threshold:
                                    target = PROMOTION_TARGETS[cur]
                                    lines.append(
                                        f"⚡ [{inj_name}] Confirmations={new_count}, "
                                        f"目前{cur}, 已達{target}門檻，"
                                        f"觸及相關行為時請主動確認是否晉升"
                                    )
                    except (OSError, UnicodeDecodeError):
                        pass
                    break

    # ── Blind-Spot Reporter (v2.9) — debug log only, not injected ──
    if (not matched_with_dir and not newly_injected and not alias_injected_projects
            and len(clean_prompt) >= 10):
        sem_count = len(sem_atoms) if sem_atoms else 0
        _atom_debug_log(
            "BlindSpot",
            f"未匹配: {clean_prompt[:80]} | intent={intent}, sem_results={sem_count}, already_injected={len(already_injected)}",
            config,
        )

    # ── Fix Escalation Protocol (v2.12) ─────────────────────────────
    retry_count = state.get("wisdom_retry_count", 0)
    fix_esc_warned = state.get("fix_escalation_warned", False)
    if retry_count >= 2 and not fix_esc_warned:
        state["fix_escalation_warned"] = True
        lines.append(
            f"[Guardian:FixEscalation] 偵測到重複修正 "
            f"(retry={retry_count})。"
            "依據「精確修正升級」規則，必須暫停直接修復，"
            "執行 /fix-escalation 精確修正會議。"
        )

    # ─── Phase 1.5: Failure-triggered extraction (v2.13) ───────────
    _maybe_spawn_failure_extraction(
        session_id, state, config, clean_prompt, lines
    )

    # ─── Topic tracking (v2.2) ─────────────────────────────────────
    _update_topic_tracker(state, prompt, intent, newly_injected)

    # ─── Phase 2: Sync reminders (existing logic) ────────────────────
    mod_count = len(state.get("modified_files", []))
    kq_count = len(state.get("knowledge_queue", []))
    sync_kw = config.get("sync_keywords", [])
    prompt_has_sync = any(kw in prompt for kw in sync_kw)

    if prompt_has_sync and (mod_count > 0 or kq_count > 0):
        lines.append(f"[Guardian] Sync context: {mod_count} files modified, {kq_count} knowledge items pending.")
        if mod_count > 0:
            files = list({m["path"] for m in state["modified_files"]})
            lines.append(f"Files: {', '.join(f.rsplit('/', 1)[-1] for f in files[:10])}")
        if kq_count > 0:
            for q in state["knowledge_queue"]:
                lines.append(f"  - {q.get('classification', '[臨]')} {q['content'][:60]}")
    elif mod_count > 0 or kq_count > 0:
        remind_after = config.get("remind_after_turns", 3)
        remind_count = state.get("remind_count", 0)
        if remind_count < remind_after:
            state["remind_count"] = remind_count + 1
        else:
            max_reminders = config.get("max_reminders", 3)
            total_reminds = state.get("total_reminds", 0)
            if total_reminds < max_reminders:
                lines.append(
                    f"[Guardian] Reminder: {mod_count} files modified, {kq_count} knowledge items pending. "
                    "Consider syncing when current task completes."
                )
                state["remind_count"] = 0
                state["total_reminds"] = total_reminds + 1

    write_state(session_id, state)

    # atom-debug: log injection summary with token counts
    if (config or {}).get("atom_debug", False):
        prompt_preview = re.sub(r"<[^>]+>", "", prompt[:300]).strip()[:120] if prompt else ""
        total_tok = 0
        summary_parts = []
        _ATOM_BLOCK_RE = re.compile(r"^\[Atom:(\S+)\](?:\s*\(related\))?\n")
        for line_item in lines:
            tok = _estimate_tokens(line_item)
            total_tok += tok
            am = _ATOM_BLOCK_RE.match(line_item)
            if am:
                aname = am.group(1)
                is_related = "(related) " if "(related)" in line_item[:60] else ""
                # Find source path from matched_with_dir
                src = f"memory/{aname}.md"
                for (n, rp, _), bd in matched_with_dir:
                    if n == aname and rp:
                        src = rp
                        break
                summary_parts.append(f"  [注入了 {src}] {is_related}(~{tok} tok)")
            else:
                # Short context lines: keep first line, add token count
                first = line_item.split("\n", 1)[0][:120]
                if line_item.count("\n") > 1:
                    n_lines = line_item.count("\n") + 1
                    summary_parts.append(f"  {first} ...({n_lines}行, ~{tok} tok)")
                else:
                    summary_parts.append(f"  {first} (~{tok} tok)")
        injection_body = (
            f"[PROMPT] {prompt_preview}\n"
            f"[注入摘要] {len(lines)}項, 合計 ~{total_tok} tok\n"
            + ("\n".join(summary_parts) if summary_parts else "NONE")
        )
        _atom_debug_log("注入", injection_body, config)

    if lines:
        # V2.11: Context budget hard cap
        lines = _truncate_context_by_activation(lines, budget, atom_source_dirs)
        output_json({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "\n".join(lines),
            }
        })
    else:
        output_nothing()


def handle_post_tool_use(input_data: Dict[str, Any], config: Dict[str, Any]) -> None:
    session_id = input_data.get("session_id", "")
    state = _ensure_state(session_id, input_data, config)
    if not state:
        output_nothing()
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if tool_name in ("Edit", "Write") and file_path:
        state.setdefault("modified_files", []).append({
            "path": file_path,
            "tool": tool_name,
            "at": _now_iso(),
        })
        state["sync_pending"] = True

        # V2.11: Track per-file edit counts for over-engineering detection
        edit_counts = state.setdefault("edit_counts", {})
        edit_counts[file_path] = edit_counts.get(file_path, 0) + 1

        # V2.8: Wisdom Engine retry tracking
        if WISDOM_AVAILABLE:
            try:
                wisdom_track_retry(state, file_path)
            except Exception as e:
                print(f"[v2.8] Wisdom retry track error: {e}", file=sys.stderr)

        # V2.7: Check if this file was modified in a previous session
        try:
            qf = _check_output_quality(file_path, session_id, config)
            if qf:
                state.setdefault("quality_feedback", {}).setdefault(
                    "rewritten_files", []
                ).append(qf)
                print(
                    f"[v2.7] Quality feedback: {file_path} was also modified "
                    f"in session {qf['original_session']}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[v2.7] Quality check error: {e}", file=sys.stderr)

        write_state(session_id, state)

        # Trigger incremental vector index if an atom file was modified
        normalized = file_path.replace("\\", "/")
        if "/memory/" in normalized and normalized.endswith(".md"):
            _trigger_incremental_index(config)

        # V2.16: Staging filename validation — warn on non-standard names
        if "/_staging/" in normalized and normalized.endswith(".md"):
            staging_fname = normalized.rsplit("/", 1)[-1]
            if staging_fname != "next-phase.md":
                state["_staging_advisory"] = (
                    f"⚠ `_staging/{staging_fname}` 非標準檔名。"
                    f"/continue 優先讀 `next-phase.md`。"
                    f"建議重新命名：mv → next-phase.md"
                )
                print(
                    f"[v2.16] Staging name gate: {staging_fname}", file=sys.stderr
                )

        # V2.22: Memory path enforcement — block writes to legacy personal project path
        # when the current project has been migrated to V2.21 (project_root exists).
        # Exempt: MEMORY.md pointer file itself (used by project registry/init),
        #         episodic/, access.json, transcript files (Claude Code managed).
        _claude_projects_pat = "/.claude/projects/"
        if _claude_projects_pat in normalized and "/memory/" in normalized:
            _proj_root = state.get("atom_index", {}).get("project_root", "")
            # Only enforce when project has been migrated (project_root is set)
            if _proj_root:
                _rel_part = normalized.split("/memory/", 1)[-1]
                # Exempt: MEMORY.md pointer, episodic/, access.json — these stay in personal path
                _exempt = (
                    _rel_part == "MEMORY.md"
                    or _rel_part.startswith("episodic/")
                    or _rel_part == "access.json"
                )
                if not _exempt:
                    _proj_root_norm = _proj_root.replace("\\", "/")
                    _correct_base = f"{_proj_root_norm}/.claude/memory/"
                    state["_path_enforcement_advisory"] = (
                        f"🚫 **路徑錯誤** — 寫入了舊個人層路徑 `~/.claude/projects/*/memory/`。\n"
                        f"V2.21 規則：專案記憶必須寫到 `{_correct_base}`。\n"
                        f"正確路徑：`{_correct_base}{_rel_part}`\n"
                        f"請立即搬移檔案並刪除錯誤路徑的副本。"
                    )
                    print(
                        f"[v2.22] Path enforcement BLOCKED: {normalized} → should be {_correct_base}{_rel_part}",
                        file=sys.stderr,
                    )

        # V2.15: _AIDocs content classification gate — warn on temporary files
        if "/_AIDocs/" in normalized or "/_aidocs/" in normalized.lower():
            fname = normalized.rsplit("/", 1)[-1]
            if is_plan_filename(fname):
                state["_aidocs_advisory"] = (
                    f"⚠ {fname} 看起來是暫時性文件，"
                    f"建議放 memory/_staging/ 而非 _AIDocs/。"
                    f"判斷基準：實作完成後是否仍有長期參考價值？"
                )
                print(f"[v2.15] AIDocs gate triggered: {fname}", file=sys.stderr)

        # V2.25: _AIDocs Drift Detection — src changed but docs not updated
        if normalized.endswith(".ts") and "/src/" in normalized:
            _drift_warned = state.setdefault("_aidocs_drift_warned", set())
            # Convert set from JSON (lists) back if needed
            if isinstance(_drift_warned, list):
                _drift_warned = set(_drift_warned)
                state["_aidocs_drift_warned"] = _drift_warned

            if normalized not in _drift_warned:
                _proj_root_drift = state.get("session", {}).get("cwd", "")
                if _proj_root_drift:
                    _aidocs_dir = os.path.join(_proj_root_drift, "_AIDocs", "modules")
                    if os.path.isdir(_aidocs_dir):
                        # Derive candidate .md name from src path
                        _src_rel = normalized.split("/src/", 1)[-1]  # e.g. core/agent-loop.ts
                        _ts_name = _src_rel.rsplit("/", 1)[-1].replace(".ts", "")  # agent-loop

                        # Directory-level mappings (src/memory/*.ts → memory-engine.md, etc.)
                        _dir_map = {
                            "memory": "memory-engine",
                            "providers": "providers",
                            "tools": "tool-registry",
                            "skills": "skills",
                            "hooks": "hooks",
                            "accounts": "accounts",
                            "safety": "safety",
                            "workflow": "workflow",
                            "mcp": "mcp-client",
                            "vector": "vector-service",
                        }
                        _src_dir = _src_rel.split("/")[0] if "/" in _src_rel else ""
                        _candidate_md = _dir_map.get(_src_dir, _ts_name) + ".md"
                        _md_path = os.path.join(_aidocs_dir, _candidate_md)

                        if os.path.isfile(_md_path):
                            # Check if this .md was already modified in this session
                            _mod_paths = {m["path"] for m in state.get("modified_files", [])}
                            if _md_path not in _mod_paths and _candidate_md not in {
                                p.rsplit("/", 1)[-1] for p in _mod_paths
                            }:
                                state["_aidocs_drift_advisory"] = (
                                    f"`{_src_rel}` 已修改，"
                                    f"`_AIDocs/modules/{_candidate_md}` 可能需要同步更新。"
                                )
                                print(
                                    f"[v2.25] DocDrift: {_src_rel} → modules/{_candidate_md}",
                                    file=sys.stderr,
                                )
                        _drift_warned.add(normalized)
                        state["_aidocs_drift_warned"] = list(_drift_warned)  # JSON serializable

    elif tool_name == "Read" and file_path:
        # V2.10: Read Tracking — deduplicate, keep first occurrence only
        accessed = state.setdefault("accessed_files", [])
        if not any(a["path"] == file_path for a in accessed):
            accessed.append({"path": file_path, "at": _now_iso()})
            write_state(session_id, state)

    elif tool_name == "Bash":
        # V2.10: VCS query capture (git log/blame/show/diff, svn log/blame/diff)
        command = tool_input.get("command", "")
        if re.search(r"\b(git\s+(log|blame|show|diff)|svn\s+(log|blame|diff))\b", command):
            vcs = state.setdefault("vcs_queries", [])
            vcs.append({"command": command[:200], "at": _now_iso()})
            write_state(session_id, state)

    # V2.15+V2.16: Output advisory if gate triggered
    advisories = []
    if state:
        for key, prefix in [
            ("_path_enforcement_advisory", "[Guardian:PathEnforce]"),
            ("_aidocs_advisory", "[Guardian:AIDocs]"),
            ("_aidocs_drift_advisory", "[Guardian:DocDrift]"),
            ("_staging_advisory", "[Guardian:StagingName]"),
        ]:
            val = state.get(key)
            if val:
                advisories.append(f"{prefix} {val}")
                del state[key]

    # V3/1C: Hot Cache mid-turn injection
    if read_hot_cache:
        try:
            hot_data = read_hot_cache(session_id)
            if hot_data:
                advisories.append(f"[HotCache] {hot_data.get('summary', '')}")
                mark_injected(session_id)
        except Exception:
            pass

    if advisories:
        write_state(session_id, state)
        output_json({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n".join(advisories),
            }
        })
    else:
        output_nothing()


def handle_pre_compact(input_data: Dict[str, Any], config: Dict[str, Any]) -> None:
    session_id = input_data.get("session_id", "")
    state = _ensure_state(session_id, input_data, config)
    if not state:
        output_nothing()
        return

    # Mark snapshot for recovery after compaction
    state["pre_compact_snapshot"] = _now_iso()

    # V2.22: Episodic checkpoint — generate episodic here because SessionEnd
    # often doesn't fire (user closes window / context limit / VSCode reload).
    # Only once per session to avoid duplicates.
    if not state.get("episodic_checkpoint_done"):
        ep_cfg = config.get("episodic", {})
        if ep_cfg.get("auto_generate", True) and _should_generate_episodic(state, config):
            try:
                result = _generate_episodic_atom(session_id, state, config)
                if result:
                    state["episodic_checkpoint_done"] = True
                    print(f"[v2.22] episodic checkpoint: {result}", file=sys.stderr)
            except Exception as e:
                print(f"[v2.22] episodic checkpoint failed: {e}", file=sys.stderr)

    write_state(session_id, state)
    output_nothing()


# (Per-turn extraction, failure detection moved to wg_extraction.py)


# ─── Stop Hook ────────────────────────────────────────────────────────────


def handle_stop(input_data: Dict[str, Any], config: Dict[str, Any]) -> None:
    session_id = input_data.get("session_id", "")
    state = _ensure_state(session_id, input_data, config)
    if not state:
        output_nothing()
        return

    max_blocks = config.get("stop_gate_max_blocks", 2)
    stop_count = state.get("stop_blocked_count", 0)
    phase = state.get("phase", "working")

    # Anti-loop guard
    if stop_count >= max_blocks:
        state["phase"] = "done"
        write_state(session_id, state)
        _maybe_spawn_per_turn_extraction(session_id, state, config)
        output_nothing()
        return

    # Already synced or marked done
    if phase in ("done", "syncing"):
        _maybe_spawn_per_turn_extraction(session_id, state, config)
        output_nothing()
        return

    # Check if sync is needed
    mod_count = len(state.get("modified_files", []))
    kq_count = len(state.get("knowledge_queue", []))
    unique_files = list({m["path"] for m in state.get("modified_files", [])})
    min_files = config.get("min_files_to_block", 2)

    # Muted session — always allow
    if state.get("muted"):
        _maybe_spawn_per_turn_extraction(session_id, state, config)
        output_nothing()
        return

    # Nothing to sync
    if mod_count == 0 and kq_count == 0:
        state["phase"] = "done"
        write_state(session_id, state)
        _maybe_spawn_per_turn_extraction(session_id, state, config)
        output_nothing()
        return

    # Below threshold: soft reminder only (no block)
    if len(unique_files) < min_files and kq_count == 0:
        state["phase"] = "done"
        write_state(session_id, state)
        _maybe_spawn_per_turn_extraction(session_id, state, config)
        output_nothing()
        return

    # Block: meaningful sync needed
    state["stop_blocked_count"] = stop_count + 1
    write_state(session_id, state)
    _maybe_spawn_per_turn_extraction(session_id, state, config)

    file_names = ", ".join(f.rsplit("/", 1)[-1] for f in unique_files[:8])

    reason = (
        f"[Workflow Guardian] This session modified {len(unique_files)} file(s)"
        + (f" and has {kq_count} pending knowledge item(s)" if kq_count > 0 else "")
        + f". Files: {file_names}.\n"
        "Please check CLAUDE.md sync rules and ask the user which sync steps apply."
    )

    output_block(reason)


def _cleanup_old_states() -> None:
    """V3/2.2A: Tiered TTL cleanup for state files.

    - age < 600s (10m): always keep (protect fresh states)
    - merged_into + > 600s: delete
    - prompt_count=0 + working + > 600s: delete (empty startup)
    - prompt_count>0 + working + > 1800s (30m): delete (orphaned)
    - done + sync_pending=false + > 3600s (1h): delete (synced, no value)
    - done + sync_pending=true + > 14400s (4h): delete (stale pending)
    - fallback > 7d: delete
    """
    now = time.time()
    for f in WORKFLOW_DIR.glob("state-*.json"):
        try:
            age = now - f.stat().st_mtime
            if age < 600:
                continue

            # Parse state for tiered decisions
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                # Corrupt file — delete if old enough
                if age > 7 * 86400:
                    f.unlink(missing_ok=True)
                continue

            phase = data.get("phase", "")
            prompt_count = data.get("topic_tracker", {}).get("prompt_count", 0)
            merged = data.get("merged_into")
            sync_pending = data.get("sync_pending", False)

            if merged and age > 600:
                f.unlink(missing_ok=True)
            elif prompt_count == 0 and phase == "working" and age > 600:
                f.unlink(missing_ok=True)
            elif prompt_count > 0 and phase == "working" and age > 1800:
                f.unlink(missing_ok=True)
            elif phase == "done" and not sync_pending and age > 3600:
                f.unlink(missing_ok=True)
            elif phase == "done" and sync_pending and age > 14400:
                f.unlink(missing_ok=True)
            elif age > 7 * 86400:
                f.unlink(missing_ok=True)
        except OSError:
            pass


def handle_session_end(input_data: Dict[str, Any], config: Dict[str, Any]) -> None:
    session_id = input_data.get("session_id", "")
    state = _ensure_state(session_id, input_data, config)
    if not state:
        sys.exit(0)
        return

    state["ended_at"] = _now_iso()
    state["phase"] = "done"

    # W10/V3-2.2A: Clean up stale state files (tiered TTL)
    try:
        _cleanup_old_states()
    except Exception as e:
        print(f"[v3] SessionEnd cleanup error: {e}", file=sys.stderr)

    # ─── Spawn extract-worker.py as detached subprocess (V2.12) ─────────
    rc = config.get("response_capture", {})
    if rc.get("enabled", True):
        cwd = state.get("session", {}).get("cwd", "")
        tracker = state.get("topic_tracker", {})
        dist = tracker.get("intent_distribution", {})
        intent = max(dist, key=dist.get, default="build") if dist else "build"
        worker_ctx = {
            "session_id": session_id,
            "cwd": cwd,
            "config": config,
            "knowledge_queue": state.get("knowledge_queue", []),
            "session_intent": intent,
            # V2.14: pass byte_offset so SessionEnd skips already-extracted bytes
            "byte_offset": state.get("extraction_offset", 0),
        }
        pid = _spawn_extract_worker(worker_ctx)
        if pid:
            print(f"[v2.12] extract-worker spawned (pid={pid}, intent={intent})", file=sys.stderr)
        state["extract_worker_pid"] = 0  # SessionEnd: don't track PID (session ending)

    mod_count = len(state.get("modified_files", []))
    kq_count = len(state.get("knowledge_queue", []))
    if state.get("sync_pending") and (mod_count > 0 or kq_count > 0):
        print(
            f"Warning: Session ending with unsaved work. "
            f"{mod_count} modified files, {kq_count} knowledge items.",
            file=sys.stderr,
        )

    # ─── V2.6: Self-iteration metrics + oscillation detection ──────
    try:
        metrics = _collect_iteration_metrics(state)
        state["iteration_metrics"] = metrics

        oscillations = _detect_oscillation(state, config)
        if oscillations:
            state["iteration_metrics"]["oscillations"] = oscillations
            for osc in oscillations:
                print(
                    f"[v2.6] Oscillation detected: {osc['atom']} "
                    f"({osc['count']} sessions)",
                    file=sys.stderr,
                )
        # V2.16: Persist oscillation state for next SessionStart
        _save_oscillation_state(oscillations if oscillations else [])
    except Exception as e:
        print(f"[v2.6] Self-iteration metrics error: {e}", file=sys.stderr)

    # ─── V2.16: Self-iteration automation (decay + promotion) ────────
    try:
        si_results = _self_iterate_atoms(state, config)
        if si_results.get("promoted"):
            for p in si_results["promoted"]:
                print(
                    f"[v2.16] Auto-promoted [臨]→[觀] in {p['atom']}: "
                    f"{len(p['items'])} items",
                    file=sys.stderr,
                )
        if si_results.get("archive_candidates"):
            print(
                f"[v2.16] Archive candidates: "
                f"{len(si_results['archive_candidates'])} atoms (low decay score)",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"[v2.16] Self-iteration error: {e}", file=sys.stderr)

    # ─── V2.8: Wisdom Engine — session reflection ────────────────────
    if WISDOM_AVAILABLE:
        try:
            wisdom_reflect(state)
        except Exception as e:
            print(f"[v2.8] Wisdom reflect error: {e}", file=sys.stderr)

    # ─── V2.11: over_engineering 統計已由 wisdom_reflect(state) 統一處理 ────
    # （track_retry 累計 wisdom_retry_count → reflect() 寫入 reflection_metrics）
    try:
        edit_counts = state.get("edit_counts", {})
        if edit_counts:
            reverted = sum(1 for c in edit_counts.values() if c >= 2)
            if reverted > 0:
                print(
                    f"[v2.11] Over-engineering: {reverted}/{len(edit_counts)} files "
                    f"edited 2+ times",
                    file=sys.stderr,
                )
    except Exception as e:
        print(f"[v2.11] Over-engineering metrics error: {e}", file=sys.stderr)

    # V2.10: Staging area reminder (V2.21: project-aware)
    cwd = state.get("session", {}).get("cwd", "")
    staging_dir = resolve_staging_dir(cwd)
    if staging_dir.exists():
        staging_files = list(staging_dir.glob("*.md"))
        if staging_files:
            print(
                f"[v2.10] _staging/ 有 {len(staging_files)} 個暫存檔案待清理",
                file=sys.stderr,
            )

    # ─── V2.11: Conflict detection ──────────────────────────────────
    try:
        conflict_warnings = _detect_atom_conflicts(state, config)
        if conflict_warnings:
            state["conflict_warnings"] = conflict_warnings
            for cw in conflict_warnings:
                print(
                    f"[v2.11] Conflict: {cw['source']} ↔ {cw['target']} "
                    f"(score={cw['score']})",
                    file=sys.stderr,
                )
    except Exception as e:
        print(f"[v2.11] Conflict detection error: {e}", file=sys.stderr)

    # ─── V2.18: Auto-fix missing reverse references ─────────────────
    try:
        import subprocess as _sp
        _hc_script = str(CLAUDE_DIR / "tools" / "atom-health-check.py")
        # Fix global atoms
        _sp.run(
            [sys.executable, _hc_script, "--fix-refs"],
            capture_output=True, timeout=10,
        )
        # Fix project atoms if present
        _proj_mem = get_project_memory_dir(state.get("session", {}).get("cwd", ""))
        if _proj_mem:
            _sp.run(
                [sys.executable, _hc_script, "--fix-refs", "--memory-root", str(_proj_mem)],
                capture_output=True, timeout=10,
            )
    except Exception as e:
        print(f"[v2.18] fix-refs error: {e}", file=sys.stderr)

    # v2.1 Task #2: Auto-generate episodic atom (skip if PreCompact already did it)
    episodic_generated = state.get("episodic_checkpoint_done", False)
    if not episodic_generated and config.get("episodic", {}).get("auto_generate", True):
        try:
            _generate_episodic_atom(session_id, state, config)
            episodic_generated = True
        except Exception as e:
            print(f"[episodic] generation failed: {e}", file=sys.stderr)
            _atom_debug_error("萃取:_generate_episodic_atom", e)

    # V2.11-fix: Save review marker if review was due this session
    if state.get("review_due"):
        try:
            # V2.21: count global + all project episodic atoms
            total = sum(1 for _ in EPISODIC_DIR.glob("episodic-*.md")) if EPISODIC_DIR.exists() else 0
            for _slug, _mem_dir in discover_all_project_memory_dirs():
                _ep = _mem_dir / "episodic"
                if _ep.exists():
                    total += sum(1 for _ in _ep.glob("episodic-*.md"))
            _save_review_marker(total)
            print(f"[v2.6] Review marker saved (total={total})", file=sys.stderr)
        except Exception as e:
            print(f"[v2.6] Review marker save error: {e}", file=sys.stderr)

    write_state(session_id, state)

    # v2.1 Sprint 3: Trigger incremental vector index if atoms were modified
    modified = state.get("modified_files", [])
    has_atom_changes = any(
        "/memory/" in m.get("path", "").replace("\\", "/")
        and m.get("path", "").endswith(".md")
        for m in modified
    )
    if has_atom_changes or episodic_generated:
        _trigger_incremental_index(config)

    sys.exit(0)


# ─── Dispatcher ──────────────────────────────────────────────────────────────

HANDLERS = {
    "SessionStart": handle_session_start,
    "UserPromptSubmit": handle_user_prompt_submit,
    "PostToolUse": handle_post_tool_use,
    "PreCompact": handle_pre_compact,
    "Stop": handle_stop,
    "SessionEnd": handle_session_end,
}


def main():
    # Force UTF-8 output on Windows
    if sys.platform == "win32":
        sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)
        sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', closefd=False)

    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)

    # Read JSON from stdin
    try:
        raw = sys.stdin.buffer.read()
        input_data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Can't parse input; exit silently (non-blocking)
        sys.exit(0)

    config = load_config()
    if not config.get("enabled", True):
        sys.exit(0)

    event = input_data.get("hook_event_name", "")
    handler = HANDLERS.get(event)
    if handler:
        try:
            handler(input_data, config)
        except Exception as e:
            # Never crash; log to stderr (verbose mode only) and continue
            print(f"[workflow-guardian] Error in {event}: {e}", file=sys.stderr)
            _atom_debug_error(f"workflow-guardian:{event}", e)
            sys.exit(0)
    else:
        sys.exit(0)



# (V2.6: Self-Iteration Engine → wg_iteration.py)
# (V2.1+: Episodic/Extraction/Quality → wg_episodic.py)


if __name__ == "__main__":
    main()
