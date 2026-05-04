"""
wg_core.py — Workflow Guardian 共用基礎模組

常數、設定載入、State I/O、Output helpers、Debug logging。
所有 wg_*.py 模組共用此檔。

V2.20: 路徑相關常數/函式已移至 wg_paths.py。
本模組 re-export 以維持向後相容（下一版移除）。
"""

import json
import os
import sys
import re
import time
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── Path constants & functions (V2.20: delegated to wg_paths) ───────────────
# Re-export for backward compatibility. Direct import from wg_paths preferred.
from wg_paths import (  # noqa: F401
    CLAUDE_DIR, MEMORY_DIR, EPISODIC_DIR, WORKFLOW_DIR, CONFIG_PATH,
    MEMORY_INDEX,
    cwd_to_project_slug, get_project_memory_dir, find_project_root,
    get_project_claude_dir, get_transcript_path,
    resolve_episodic_dir, resolve_failures_dir, resolve_staging_dir,
    resolve_access_json, get_slug_pointer_path,
    discover_all_project_memory_dirs, discover_memory_layers,
    state_file_path,
)

# ─── Constants (non-path) ────────────────────────────────────────────────────

CONTEXT_BUDGET_DEFAULT = 3000  # V2.11: default token cap

# Defaults (overridable via config.json)
DEFAULTS = {
    "enabled": True,
    "stop_gate_max_blocks": 2,
    "min_files_to_block": 2,
    "remind_after_turns": 3,
    "max_reminders": 3,
    "stale_threshold_hours": 24,
    "sync_keywords": ["同步", "sync", "commit", "提交", "結束", "收工"],
    "completion_indicators": ["已同步", "同步完成", "已更新", "已提交", "committed"],
    # v2.2 Sprint 2: Session context injection
    "session_context": {
        "enabled": True,
        "max_episodic": 3,
        "reserved_tokens": 200,
        "min_score": 0.35,
        "search_timeout_ms": 1500,
    },
    # v2.10: _AIDocs Bridge
    "aidocs": {
        "enabled": True,
        "max_session_start_entries": 15,
        "max_prompt_matches": 3,
    },
    # 2026-05-04: Sync reminder soft block — Stop 階段任何 modified_files>0
    # 但仍未 commit 時提一次軟阻，避免單檔修改溜過 min_files_to_block 硬閘。
    # 與 stop_gate_max_blocks 互不影響；本 gate 用 sync_reminder_count 自行限速。
    "sync_reminder": {
        "enabled": True,
        "max_reminders": 1,
    },
    # v3.3: DocDrift detection
    "docdrift": {
        "enabled": True,
        "path_mappings": {},
        "exclude_patterns": [
            "_aidocs/", "memory/", "_staging/", ".git/",
            "node_modules/", "__pycache__/", ".claude/workflow/",
        ],
        "keyword_match_threshold": 2,
        "max_pending_display": 5,
    },
    # v2.2 Sprint 2: Proactive classification
    "proactive": {
        "pattern_threshold": 2,
        "migration_hint_threshold": 3,
    },
}


# ─── Config ──────────────────────────────────────────────────────────────────


def load_config() -> Dict[str, Any]:
    """Load config with defaults fallback."""
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            config.update(user_config)
        except (json.JSONDecodeError, OSError):
            pass
    return config


# ─── Utility ─────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _estimate_tokens(text: str) -> int:
    """CJK-aware token estimation. Chinese ~1.5 tok/char, ASCII ~0.25 tok/word."""
    if not text:
        return 0
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f')
    ascii_part = len(text) - cjk
    return int(cjk * 1.5 + ascii_part * 0.25)


# ─── State File I/O ──────────────────────────────────────────────────────────


def state_path(session_id: str) -> Path:
    """Alias for wg_paths.state_file_path (backward compat)."""
    return state_file_path(session_id)


def read_state(session_id: str) -> Optional[Dict[str, Any]]:
    """Read state file. Returns None if not found or corrupt."""
    path = state_path(session_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_state(session_id: str, state: Dict[str, Any]) -> None:
    """Atomic write with advisory lock to prevent concurrent R-M-W races (C6).

    Uses msvcrt.locking on Windows for advisory file locking (best-effort):
    if lock acquisition fails, proceeds without lock — tmp+replace still
    provides crash safety.
    """
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)

    # V2.22: Use canonical session ID from state object — when _ensure_state
    # returns a sibling's state, writes go to the sibling's file, not the ghost's.
    canonical_id = state.get("session", {}).get("id")
    if canonical_id and canonical_id != session_id:
        session_id = canonical_id

    state["last_updated"] = _now_iso()
    path = state_path(session_id)
    tmp_path = path.with_suffix(".tmp")
    lock_path = path.with_suffix(".lock")

    # Advisory lock (Windows only, best-effort)
    lock_fh = None
    if sys.platform == "win32":
        try:
            import msvcrt
            lock_fh = open(lock_path, "ab")
            msvcrt.locking(lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            if lock_fh:
                lock_fh.close()
            lock_fh = None  # Failed to acquire — proceed without lock

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        tmp_path.replace(path)
    except OSError:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    finally:
        if lock_fh is not None:
            try:
                import msvcrt
                msvcrt.locking(lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            lock_fh.close()
            try:
                lock_path.unlink()
            except OSError:
                pass


def new_state(session_id: str, cwd: str, source: str) -> Dict[str, Any]:
    """Create a fresh state object."""
    return {
        "schema_version": "1.1",
        "session": {
            "id": session_id,
            "started_at": _now_iso(),
            "cwd": cwd,
            "source": source,
        },
        "phase": "init",
        "modified_files": [],
        "accessed_files": [],
        "vcs_queries": [],
        "knowledge_queue": [],
        "sync_pending": False,
        "stop_blocked_count": 0,
        "remind_count": 0,
        "topic_tracker": {
            "intent_distribution": {},
            "prompt_count": 0,
            "first_prompt_summary": "",
            "keyword_signals": [],
            "related_episodic": [],
        },
        "session_context_injected": False,
        "last_updated": _now_iso(),
    }


def _find_active_sibling_state(
    cwd: str, current_session_id: str, window_seconds: int = 60
) -> Optional[Dict[str, Any]]:
    """掃描 WORKFLOW_DIR/state-*.json，找同 cwd + 近期活躍的兄弟 state。

    用於 SessionStart 去重：若同 workspace 已有活躍 state，回傳之。
    多個匹配時回傳 mtime 最新的。任何異常安全降級回 None。
    """
    try:
        norm_cwd = cwd.lower().replace("\\", "/")
        best: Optional[Dict[str, Any]] = None
        best_mtime: float = 0.0
        now = datetime.now(timezone.utc).astimezone()

        for fp in WORKFLOW_DIR.glob("state-*.json"):
            # 跳過自己
            if current_session_id in fp.name:
                continue
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    candidate = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            # 比對 cwd
            candidate_cwd = candidate.get("session", {}).get("cwd", "")
            if candidate_cwd.lower().replace("\\", "/") != norm_cwd:
                continue

            # 必須是 working 且未合併
            if candidate.get("phase") != "working":
                continue
            if candidate.get("merged_into"):
                continue

            # 檢查 started_at 是否在 window 內
            started_at_str = candidate.get("session", {}).get("started_at", "")
            if not started_at_str:
                continue
            try:
                started_at = datetime.fromisoformat(started_at_str)
                delta = (now - started_at).total_seconds()
                if delta < 0 or delta > window_seconds:
                    continue
            except (ValueError, TypeError):
                continue

            # 多匹配取 mtime 最新
            mtime = fp.stat().st_mtime
            if mtime > best_mtime:
                best = candidate
                best_mtime = mtime

        return best
    except Exception:
        return None


def _ensure_state(
    session_id: str, input_data: Dict[str, Any], config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Read state; if missing (SessionStart was skipped), auto-create one."""
    state = read_state(session_id)
    if state:
        merged_into = state.get("merged_into")
        if merged_into:
            target = read_state(merged_into)
            if target:
                return target
            # Self-heal: merge target 已被 cleanup 或從未建立 → 當前 session 升為活躍，
            # 避免寫入落到 phase=merged 的死水 state（會導致 V4.1 pending_user_extract
            # 等後續 hook 寫入被 worker 忽略）
            state.pop("merged_into", None)
            state["phase"] = "working"
            write_state(session_id, state)
            _atom_debug_log(
                "MergeSelfHeal",
                f"{session_id[:12]}… merged_into={merged_into[:12]}… target missing "
                f"→ self-heal to active",
                config,
            )
        return state

    cwd = input_data.get("cwd", "")

    # V2.22: Before creating fallback, check if same cwd already has a working
    # session. If found, return it directly — write_state's canonical ID redirect
    # ensures all writes go to the real session's file (no ghost file created).
    sibling = _find_active_sibling_state(cwd, session_id, window_seconds=86400)
    if sibling:
        real_id = sibling.get("session", {}).get("id", "")
        _atom_debug_log(
            "Fallback→Sibling",
            f"{session_id[:12]}… → existing {real_id[:12] if real_id else '?'}…",
            config,
        )
        return sibling

    state = new_state(session_id, cwd, "fallback")
    state["phase"] = "working"
    write_state(session_id, state)
    _atom_debug_log(
        "Fallback",
        f"SessionStart missed for {session_id[:12]}… — auto-created state",
        config,
    )
    return state


# ─── Output Helpers ──────────────────────────────────────────────────────────


def output_json(data: Dict[str, Any]) -> None:
    """Print JSON to stdout and exit 0."""
    print(json.dumps(data, ensure_ascii=False))
    sys.exit(0)


def output_nothing() -> None:
    """Exit 0 with no output (fast path)."""
    sys.exit(0)


def output_block(reason: str) -> None:
    """Output a block decision (for Stop hook)."""
    output_json({"decision": "block", "reason": reason})


# ─── Promotion Audit Log ─────────────────────────────────────────────────────

def log_promotion_audit(action: str, atom: str, **fields: Any) -> None:
    """Append one JSONL entry to memory/_promotion_audit.jsonl.

    action ∈ {"hint", "auto_observe", "manual_promote"}
      - hint: UserPromptSubmit 晉升提示注入
      - auto_observe: wg_iteration [臨]→[觀] 自動晉升（內部條目或 header）
      - manual_promote: atom_promote MCP 執行
    fields 依 action 帶不同欄位（from/to/confirmations/session_id 等）。
    失敗不 raise — audit 不該影響主流程。
    """
    try:
        entry = {"ts": datetime.now().isoformat(timespec="seconds"),
                 "action": action, "atom": atom}
        entry.update(fields)
        audit_path = MEMORY_DIR / "_promotion_audit.jsonl"
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ─── Atom Debug Log ──────────────────────────────────────────────────────────


def _atom_debug_log(tag: str, content: str, config: Dict[str, Any] = None) -> None:
    """Write to atom-debug.log when atom_debug flag is on.
    For ERROR tag, always write regardless of flag.
    Skips empty/NONE entries to reduce noise."""
    if tag != "ERROR" and not (config or {}).get("atom_debug", False):
        return
    if not content or not content.strip():
        return
    try:
        log_dir = Path.home() / ".claude" / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"atom-debug-{datetime.now().strftime('%Y-%m-%d_%H')}.log"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}][{tag}] {content.strip()}\n\n")
    except Exception:
        pass


def _atom_debug_error(source: str, exc: Exception) -> None:
    """Log error with source context. Network errors get one-line summary."""
    if isinstance(exc, (TimeoutError, OSError, ConnectionError)):
        msg = f"{type(exc).__name__}: {exc}"
    else:
        import traceback
        msg = traceback.format_exc()
        if "NoneType" in msg:
            msg = f"{type(exc).__name__}: {exc}"
    _atom_debug_log("ERROR", f"[{source}] {msg}", {"atom_debug": True})
