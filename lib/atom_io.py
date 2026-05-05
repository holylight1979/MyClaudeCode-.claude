"""atom_io.py — 全系統 atom 寫入唯一 funnel (S1.3)

設計目標：
  - 所有 atom 寫入入口（MCP server.js / hooks / tools）統一走 write_atom()
  - 行為對拍 server.js:1065 toolAtomWrite （byte-identical 內容契約）
  - 反向證明：每筆寫入記入 _meta/atom_io_audit.jsonl，可對拍 mtime 找出繞過

S1 邊界（硬限制）：
  - 本檔已可獨立呼叫 + 通過 byte-equivalence 等價測試
  - 但**不接任何現役 caller**，避免測試結果被現役寫入污染
  - S2.2 / S3.1 / S3.2 才把 hooks/tools/server.js 切到本檔

Skip flags：
  - skip_gate=True: 不呼叫 memory-write-gate.py（migration / 測試用）
  - skip_conflict_check=True: 不呼叫 memory-conflict-detector.py（同上）
  - dry_run=True: 算路徑、構造內容、validate，但不落檔（測試用）
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .atom_spec import (
    SKIP_DIRS, MEMORY_INDEX, ATOM_INDEX, VALID_CONFIDENCE, VALID_SCOPES,
    build_atom_content, slugify, validate_atom_content,
)


# ─── Constants ────────────────────────────────────────────────────────────────

CLAUDE_DIR = Path.home() / ".claude"
GLOBAL_MEMORY_DIR = CLAUDE_DIR / "memory"
AUDIT_LOG = GLOBAL_MEMORY_DIR / "_meta" / "atom_io_audit.jsonl"

# 接受的 source（供 audit 反查；未列舉值會 raise ValueError）
VALID_SOURCES = frozenset({
    "mcp",
    "hook:atom-inject",  # Wave 2: workflow-guardian.py 注入 atom 時走 atom_access
    "hook:episodic",
    "hook:episodic-confirm",  # wg_episodic L367 cross-session 加計
    "hook:user-extract",
    "hook:extract-worker",
    "tool:atom-move",
    "tool:atom-health-audit",  # Wave 3: atom 體質審視工具
    "tool:changelog-roll",
    "tool:memory-audit",  # memory-audit demote/compact/log_evolution 修補
    "tool:memory-cleanup",  # 一次性根目錄整理（merge-orphan-access）
    "tool:migrate",
    "tool:sync-atom-index",
    "tool:sync-memory-index",
    "tool:undo",
    "test",  # 測試用，等價測試 fixture 使用
})

# SPEC §7.4 sensitive audience triggers auto-pending
SENSITIVE_AUDIENCE = frozenset({"architecture", "decision"})


# ─── Result type ──────────────────────────────────────────────────────────────


@dataclass
class WriteResult:
    ok: bool
    path: Optional[Path] = None
    error: Optional[str] = None
    audit_id: str = ""
    routed_to_pending: bool = False
    skip_gate: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path) if self.path else None
        return d


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _gen_audit_id() -> str:
    """ULID-ish: 13-char timestamp(ms) + 10-char random hex (足夠 audit 唯一性)。"""
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return f"{ts_ms:013d}-{secrets.token_hex(5)}"


def _audit_log(entry: Dict[str, Any]) -> None:
    """Append JSONL entry to atom_io_audit.jsonl（best-effort）。"""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _atomic_write(path: Path, content: str) -> None:
    """tmp + rename 落檔，與 server.js 行為等價。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def _find_project_root(cwd: Optional[str]) -> Optional[Path]:
    """對拍 wg_paths.find_project_root / server.js findProjectRoot。"""
    if not cwd:
        return None
    p = Path(cwd).resolve()
    for _ in range(4):
        if (p / ".claude" / "memory" / MEMORY_INDEX).exists():
            return p
        if (p / "_AIDocs").is_dir():
            return p
        if (p / ".git").exists() or (p / ".svn").exists():
            return p
        parent = p.parent
        if parent == p:
            break
        p = parent
    return None


def _resolve_target(
    scope: str,
    project_cwd: Optional[str],
    role: Optional[str],
    user: Optional[str],
    audience: Optional[List[str]],
    force_global: bool,
) -> Dict[str, Any]:
    """回傳 {dir, base, scope_label, error, routed_to_pending}。

    對拍 server.js:777 resolveMemDir + 1095-1101 sensitive audience routing。
    """
    if force_global:
        scope = "global"

    if scope == "global":
        GLOBAL_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        return {"dir": GLOBAL_MEMORY_DIR, "base": GLOBAL_MEMORY_DIR,
                "scope_label": "global", "routed_to_pending": False, "error": None}

    if scope not in ("shared", "role", "personal"):
        return {"error": f"Unknown scope: {scope}"}

    if scope == "role" and not role:
        return {"error": "scope=role requires 'role' parameter"}
    if scope == "personal" and not user:
        return {"error": "scope=personal requires 'user' parameter"}

    root = _find_project_root(project_cwd)
    if not root:
        return {"error": f"No project root found for scope={scope} cwd={project_cwd!r}"}
    # ~/.claude itself is global; reject V4 sub-scopes (P1 雙層防護)
    try:
        if root.resolve() == CLAUDE_DIR.resolve():
            return {"error": "cwd is ~/.claude itself; use scope=global for cross-project knowledge"}
    except OSError:
        pass

    base = root / ".claude" / "memory"
    if scope == "shared":
        target_dir = base / "shared"
        scope_label = "shared"
    elif scope == "role":
        target_dir = base / "roles" / role
        scope_label = f"role:{role}"
    else:  # personal
        target_dir = base / "personal" / user
        scope_label = f"personal:{user}"

    routed_to_pending = False
    if scope == "shared" and audience and any(
        a.strip().lower() in SENSITIVE_AUDIENCE for a in audience
    ):
        target_dir = base / "shared" / "_pending_review"
        routed_to_pending = True

    target_dir.mkdir(parents=True, exist_ok=True)
    return {"dir": target_dir, "base": base, "scope_label": scope_label,
            "routed_to_pending": routed_to_pending, "error": None}


# ─── Index update（對拍 server.js:953 appendToIndex） ─────────────────────────


def _resolve_index_path(mem_dir: Path) -> Path:
    """V3.2: 優先 _ATOM_INDEX.md，否則 MEMORY.md（對拍 server.js:827）。"""
    atom_idx = mem_dir / ATOM_INDEX
    if atom_idx.exists():
        return atom_idx
    return mem_dir / MEMORY_INDEX


def write_index(
    base_dir: Path,
    slug: str,
    rel_path: str,
    triggers: Iterable[str],
    source: str,
) -> WriteResult:
    """更新或追加 atom 條目到 MEMORY.md / _ATOM_INDEX.md 表格。

    對拍 server.js:953 appendToIndex byte-identical。
    """
    if source not in VALID_SOURCES:
        return WriteResult(ok=False, error=f"invalid source: {source}",
                           audit_id=_gen_audit_id())

    audit_id = _gen_audit_id()
    index_path = _resolve_index_path(base_dir)
    trigger_str = ", ".join(triggers)
    new_row = f"| {slug} | {rel_path} | {trigger_str} |"

    try:
        content = index_path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        content = "\n".join([
            "# Atom Index", "",
            "> Session 啟動時先讀此索引。比對 Trigger → Read 對應 atom。",
            "| Atom | Path | Trigger |",
            "|------|------|---------|",
            "",
        ])

    escaped = re.escape(slug)
    existing_re = re.compile(rf"^\|\s*{escaped}\s*\|.*$", re.MULTILINE)
    if existing_re.search(content):
        content = existing_re.sub(new_row, content, count=1)
    else:
        lines = content.split("\n")
        insert_idx = -1
        found_sep = False
        for i, line in enumerate(lines):
            if line.startswith("|------"):
                found_sep = True
                continue
            if found_sep and not line.startswith("|"):
                insert_idx = i
                break
        if insert_idx >= 0:
            lines.insert(insert_idx, new_row)
            content = "\n".join(lines)
        else:
            content = content.rstrip() + "\n" + new_row + "\n"

    _atomic_write(index_path, content)
    _audit_log({
        "audit_id": audit_id, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "op": "index", "source": source, "path": str(index_path), "slug": slug,
    })
    return WriteResult(ok=True, path=index_path, audit_id=audit_id)


def write_index_full(
    index_path: Path,
    content: str,
    *,
    source: str,
) -> WriteResult:
    """整檔覆寫 MEMORY.md / _ATOM_INDEX.md（給 sync-memory-index / sync-atom-index 整表重組用）。

    與 write_index 的差異：
      - write_index: row-by-row append/update（單 atom 寫入後同步索引）
      - write_index_full: 整檔覆寫（batch tool 重組整個 atom 索引表，例如 feedback-* 群組合併）

    所有寫入仍走 _atomic_write + _audit_log，行為對拍 funnel 其他入口。
    """
    if source not in VALID_SOURCES:
        return WriteResult(ok=False, error=f"invalid source: {source}",
                           audit_id=_gen_audit_id())
    audit_id = _gen_audit_id()
    try:
        _atomic_write(index_path, content)
    except OSError as e:
        return WriteResult(ok=False, error=f"write failed: {e}", audit_id=audit_id)
    _audit_log({
        "audit_id": audit_id, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "op": "index_full", "source": source, "path": str(index_path),
    })
    return WriteResult(ok=True, path=index_path, audit_id=audit_id)


# ─── Raw write escape hatch（給 V4 spec 不適用的 atom 子族用） ───────────────


def write_raw(
    file_path: Path,
    content: str,
    *,
    source: str,
    op: str = "raw",
) -> WriteResult:
    """Raw atom 寫入入口 — caller 提供完整 content + 絕對 path。

    用途：failures/ episodic/ cross-session 等子族不符 V4 build_atom_content 規範
    （沒 Trigger / Last-used / 用 Type:procedural 等），無法走 write_atom，但
    仍需走 audit log + PreToolUse 放行清單。

    funnel 只負責 _atomic_write + _audit_log；不做 validate / scope resolve / build。
    """
    audit_id = _gen_audit_id()
    if source not in VALID_SOURCES:
        return WriteResult(ok=False, audit_id=audit_id,
                           error=f"invalid source: {source}")
    try:
        _atomic_write(file_path, content)
    except OSError as e:
        return WriteResult(ok=False, audit_id=audit_id, error=f"write failed: {e}")
    _audit_log({
        "audit_id": audit_id, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "op": op, "source": source, "path": str(file_path),
    })
    return WriteResult(ok=True, audit_id=audit_id, path=file_path)


# Wave 2 移除：update_atom_field
# ----------------------------
# 計數類欄位（ReadHits / Confirmations / Last-used）已移到 <atom>.access.json
# 旁路檔，由 lib/atom_access.py 統一管理。任何過去呼叫 update_atom_field 的位置：
#   - hooks/wg_episodic.py:370 cross-session confirm → atom_access.increment_confirmation
#   - 其餘無實際 caller（grep 確認）
# 詳見 _AIDocs/Architecture.md「Atomic Memory Single Funnel」章節。


# ─── Main entry ───────────────────────────────────────────────────────────────


def write_atom(
    *,
    title: str,
    scope: str,
    confidence: str,
    triggers: List[str],
    knowledge: List[str],
    actions: Optional[List[str]] = None,
    related: Optional[List[str]] = None,
    audience: Optional[List[str]] = None,
    role: Optional[str] = None,
    user: Optional[str] = None,
    project_cwd: Optional[str] = None,
    mode: str = "create",
    source: str,
    skip_gate: bool = False,
    skip_conflict_check: bool = False,
    dry_run: bool = False,
    force_global: bool = False,
    pending_review_by: Optional[str] = None,
    merge_strategy: Optional[str] = None,
    author: Optional[str] = None,
    today: Optional[str] = None,
) -> WriteResult:
    """寫入 atom 的唯一入口。對拍 server.js:1065 toolAtomWrite byte-identical。

    Required: title, scope, confidence, triggers, knowledge, mode, source
    """
    audit_id = _gen_audit_id()

    # ── Validate ──
    if source not in VALID_SOURCES:
        return WriteResult(ok=False, audit_id=audit_id,
                           error=f"invalid source: {source} (must be in VALID_SOURCES)")
    if not title or not confidence or not triggers or not knowledge or not mode:
        return WriteResult(ok=False, audit_id=audit_id,
                           error="Missing required parameters")
    if confidence not in VALID_CONFIDENCE:
        return WriteResult(ok=False, audit_id=audit_id,
                           error=f"invalid confidence: {confidence}")
    if mode == "create" and confidence != "[臨]":
        return WriteResult(ok=False, audit_id=audit_id,
                           error=f"New atom must start at [臨] (got {confidence})")

    # V4: scope=project legacy mapping → shared
    if scope == "project":
        scope = "shared"
    if scope not in VALID_SCOPES:
        return WriteResult(ok=False, audit_id=audit_id,
                           error=f"Unknown scope: {scope}")

    # ── Resolve target dir ──
    resolved = _resolve_target(scope, project_cwd, role, user, audience, force_global)
    if resolved.get("error"):
        return WriteResult(ok=False, audit_id=audit_id, error=resolved["error"])
    mem_dir = resolved["dir"]
    base_dir = resolved["base"]
    scope_label = resolved["scope_label"]
    routed_to_pending = resolved["routed_to_pending"]

    pending_by = pending_review_by or ("management" if routed_to_pending else None)

    slug = slugify(title)
    file_path = mem_dir / f"{slug}.md"
    rel_from_base = file_path.relative_to(base_dir).as_posix()
    rel_path = f"memory/{rel_from_base}"

    # ── Build content ──
    if mode == "create":
        if file_path.exists():
            return WriteResult(ok=False, audit_id=audit_id,
                               error=f"Atom already exists: {slug}.md (use mode=append/replace)")
        content = build_atom_content(
            title=title, scope=scope_label, confidence=confidence, triggers=triggers,
            knowledge=knowledge, actions=actions, related=related, audience=audience,
            author=author, pending_review_by=pending_by, merge_strategy=merge_strategy,
            today=today,
        )
    elif mode == "append":
        if not file_path.exists():
            return WriteResult(ok=False, audit_id=audit_id,
                               error=f"Atom not found: {slug}.md (use mode=create first)")
        existing = file_path.read_text(encoding="utf-8-sig")
        action_idx = existing.find("## 行動")
        if action_idx < 0:
            return WriteResult(ok=False, audit_id=audit_id,
                               error=f"Atom {slug}.md has no ## 行動 section")
        new_lines = "\n".join(k if k.startswith("- ") else f"- {k}" for k in knowledge)
        before = existing[:action_idx].rstrip()
        after = existing[action_idx:]
        # Wave 2: Last-used 不再寫 .md；append 後由下方 atom_access.write_access_field 刷
        content = before + "\n" + new_lines + "\n\n" + after
    elif mode == "replace":
        # Wave 2: Confirmations/ReadHits 在 access.json，replace 不需保留（檔本就分離）
        # Author/Created-at 仍從舊 atom .md 抽（屬知識性 metadata）
        prev_author = author
        prev_created = today or datetime.now(timezone.utc).date().isoformat()
        if file_path.exists():
            old = file_path.read_text(encoding="utf-8-sig")
            am = re.search(r"^- Author:\s*(.+)$", old, re.MULTILINE)
            if am:
                prev_author = am.group(1).strip()
            cmm = re.search(r"^- Created-at:\s*(.+)$", old, re.MULTILINE)
            if cmm:
                prev_created = cmm.group(1).strip()
        content = build_atom_content(
            title=title, scope=scope_label, confidence=confidence, triggers=triggers,
            knowledge=knowledge, actions=actions, related=related, audience=audience,
            author=prev_author, pending_review_by=pending_by, merge_strategy=merge_strategy,
            created_at=prev_created, today=today,
        )
    else:
        return WriteResult(ok=False, audit_id=audit_id,
                           error=f"Unknown mode: {mode}")

    # ── Validate content ──
    err = validate_atom_content(content)
    if err:
        return WriteResult(ok=False, audit_id=audit_id, error=f"Validation failed: {err}")

    # ── Dry-run short-circuit ──
    if dry_run:
        return WriteResult(ok=True, audit_id=audit_id, path=file_path,
                           routed_to_pending=routed_to_pending, skip_gate=skip_gate,
                           extra={"content": content, "rel_path": rel_path,
                                  "scope_label": scope_label, "dry_run": True})

    # ── Write file ──
    _atomic_write(file_path, content)

    # ── Wave 2: 同步維護 <atom>.access.json 旁路檔 ──
    # 延遲 import 避免 atom_io ↔ atom_access 環依（atom_access import atom_io 的 audit infra）
    today_str = today or datetime.now(timezone.utc).date().isoformat()
    try:
        from . import atom_access
        if mode == "create":
            atom_access.init_access(
                file_path, first_seen=today_str, source=source,
            )
            # 同步把 last_used 設為 today（init 只設 first_seen，未設 last_used）
            atom_access.write_access_field(
                file_path, field="last_used", value=today_str, source=source,
            )
        else:  # append / replace
            atom_access.write_access_field(
                file_path, field="last_used", value=today_str, source=source,
            )
    except (ImportError, ValueError, OSError):
        # access 旁路檔失敗不致命；atom .md 已落檔
        pass

    # ── Update index ──
    if mode in ("create", "replace"):
        write_index(base_dir, slug, rel_path, triggers, source)

    # ── Audit log ──
    _audit_log({
        "audit_id": audit_id, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "op": "write", "source": source, "mode": mode, "scope": scope_label,
        "slug": slug, "path": str(file_path),
        "routed_to_pending": routed_to_pending, "skip_gate": skip_gate,
    })

    return WriteResult(ok=True, audit_id=audit_id, path=file_path,
                       routed_to_pending=routed_to_pending, skip_gate=skip_gate)
