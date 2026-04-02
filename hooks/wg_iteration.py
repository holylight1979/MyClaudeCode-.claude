"""
wg_iteration.py — 自我迭代引擎

衰減分數計算、震盪偵測、[臨]→[觀] 自動晉升、覆轍偵測、定期檢閱。
僅被 SessionStart + SessionEnd 呼叫。
"""

import json
import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from wg_paths import (
    CLAUDE_DIR, WORKFLOW_DIR, MEMORY_DIR,
    get_project_memory_dir, resolve_staging_dir,
    discover_all_project_memory_dirs,
)
from wg_core import _now_iso


# ─── Metrics Collection ─────────────────────────────────────────────────────


def _collect_iteration_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    """Collect self-iteration metrics from session state.

    Gathers atoms referenced (injected_atoms) and atoms modified
    (modified_files matching memory/*.md) into iteration_metrics.
    """
    metrics = state.get("iteration_metrics", {})

    # Atoms referenced this session
    referenced = list(set(state.get("injected_atoms", [])))
    metrics["atoms_referenced"] = referenced

    # Atoms modified this session (extract atom names from modified file paths)
    modified_atoms = []
    for m in state.get("modified_files", []):
        p = m.get("path", "").replace("\\", "/")
        if "/memory/" in p and p.endswith(".md"):
            name = p.rsplit("/", 1)[-1].replace(".md", "")
            if name not in ("MEMORY", "_CHANGELOG", "_CHANGELOG_ARCHIVE"):
                modified_atoms.append(name)
    metrics["atoms_modified"] = list(set(modified_atoms))

    return metrics


# ─── Oscillation Detection ───────────────────────────────────────────────────


def _detect_oscillation(
    state: Dict[str, Any], config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Detect atoms modified 2+ times across last 3 sessions (oscillation).

    Scans recent episodic atoms for overlapping atom modification patterns.
    Returns list of {atom, sessions, recommendation}.
    """
    oscillation_window = config.get("self_iteration", {}).get("oscillation_window", 3)
    oscillation_threshold = config.get("self_iteration", {}).get("oscillation_threshold", 2)

    # Find recent episodic atoms
    episodic_dirs = set()
    global_ep = MEMORY_DIR / "episodic"
    if global_ep.exists():
        episodic_dirs.add(global_ep)
    cwd = state.get("session", {}).get("cwd", "")
    proj_mem = get_project_memory_dir(cwd)
    if proj_mem:
        proj_ep = proj_mem / "episodic"
        if proj_ep.exists():
            episodic_dirs.add(proj_ep)

    # Collect recent episodic files (sorted by mtime, newest first)
    recent_files = []
    for ep_dir in episodic_dirs:
        for f in ep_dir.glob("episodic-*.md"):
            recent_files.append((f.stat().st_mtime, f))
    recent_files.sort(key=lambda x: -x[0])
    recent_files = recent_files[:oscillation_window]

    # Parse each episodic for MODIFIED atoms (not just referenced)
    atom_sessions = {}  # atom_name -> [session_dates]
    for _, ep_path in recent_files:
        try:
            text = ep_path.read_text(encoding="utf-8")
            date_match = re.search(r"Created:\s*(\d{4}-\d{2}-\d{2})", text)
            ep_date = date_match.group(1) if date_match else ep_path.stem[:15]
            for line in text.split("\n"):
                if "修改 atoms:" in line:
                    atoms_part = line.split("修改 atoms:")[-1].strip()
                    for a in atoms_part.split(","):
                        a = a.strip()
                        if a:
                            atom_sessions.setdefault(a, []).append(ep_date)
        except (OSError, UnicodeDecodeError):
            continue

    # Also include current session's modified atoms
    current_modified = state.get("iteration_metrics", {}).get("atoms_modified", [])
    today = datetime.now().strftime("%Y-%m-%d")
    for a in current_modified:
        atom_sessions.setdefault(a, []).append(today)

    # Detect oscillation: same atom touched in N+ distinct sessions
    oscillations = []
    for atom_name, sessions in atom_sessions.items():
        unique_sessions = list(set(sessions))
        if len(unique_sessions) >= oscillation_threshold:
            oscillations.append({
                "atom": atom_name,
                "sessions": unique_sessions,
                "count": len(unique_sessions),
                "recommendation": "暫停修改此 atom，等待更多證據再決定方向"
            })

    return oscillations


def _save_oscillation_state(oscillations: List[Dict[str, Any]]) -> None:
    """Persist oscillation detection results for next SessionStart (W8: atomic write)."""
    osc_path = WORKFLOW_DIR / "oscillation_state.json"
    if oscillations:
        data = {
            "detected_at": datetime.now().isoformat(),
            "oscillations": [
                {"atom": o["atom"], "count": o["count"], "sessions": o["sessions"]}
                for o in oscillations
            ],
        }
        tmp = osc_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(osc_path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
    elif osc_path.exists():
        osc_path.unlink()


def _load_oscillation_warnings() -> Optional[str]:
    """Load persisted oscillation warnings for SessionStart injection."""
    osc_path = WORKFLOW_DIR / "oscillation_state.json"
    if not osc_path.exists():
        return None
    try:
        with open(osc_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        oscillations = data.get("oscillations", [])
        if not oscillations:
            return None
        atoms = ", ".join(o["atom"] for o in oscillations)
        return (
            f"[Guardian:Oscillation] 以下 atoms 近期被反覆修改：{atoms}。"
            f"行動：1) 暫停修改 2) Read 該 atom 確認前次意圖 3) 收集更多證據再評估"
        )
    except (json.JSONDecodeError, OSError):
        return None


# ─── Maturity & Self-Iteration ───────────────────────────────────────────────


def _calculate_maturity_phase(config: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate system maturity phase based on episodic atom count.

    Returns {phase, total_sessions, description}.
    Phases: learning (<15), stable (15-50), mature (>50)
    """
    thresholds = config.get("self_iteration", {}).get("maturity_thresholds", {})
    learning_max = thresholds.get("learning", 15)
    stable_max = thresholds.get("stable", 50)

    # Count all episodic atoms across all known directories
    total = 0
    for ep_dir in [MEMORY_DIR / "episodic"]:
        if ep_dir.exists():
            total += sum(1 for _ in ep_dir.glob("episodic-*.md"))

    # Also check project episodic dirs (V2.20: via wg_paths)
    for _slug, _mem_dir in discover_all_project_memory_dirs():
        ep = _mem_dir / "episodic"
        if ep.exists():
            total += sum(1 for _ in ep.glob("episodic-*.md"))

    if total < learning_max:
        phase = "learning"
        desc = f"學習期（{total}/{learning_max} sessions）— 積極學習新模式"
    elif total < stable_max:
        phase = "stable"
        desc = f"穩定期（{total}/{stable_max} sessions）— 收斂規則，減少新增"
    else:
        phase = "mature"
        desc = f"成熟期（{total} sessions）— 極少新增，專注精煉"

    return {"phase": phase, "total_sessions": total, "description": desc}


def _self_iterate_atoms(
    state: Dict[str, Any], config: Dict[str, Any]
) -> Dict[str, Any]:
    """V2.16: Automated self-iteration — decay scoring + [臨]→[觀] auto-promotion.

    Runs at SessionEnd. Scans all atom files, calculates health scores,
    auto-promotes [臨] items in mature atoms, reports archive candidates.
    """
    si_config = config.get("self_iteration", {})
    decay_half_life = si_config.get("decay_half_life_days", 30)
    promote_min_conf = si_config.get("promote_min_confirmations", 20)
    archive_threshold = si_config.get("archive_score_threshold", 0.3)

    results = {"promoted": [], "archive_candidates": [], "scanned": 0}
    today = datetime.now()

    # Collect atom dirs (global + failures/)
    scan_dirs = [MEMORY_DIR]
    failure_dir = MEMORY_DIR / "failures"
    if failure_dir.exists():
        scan_dirs.append(failure_dir)

    for atom_dir in scan_dirs:
        for md_file in atom_dir.glob("*.md"):
            # Skip non-atom files
            if md_file.name in ("MEMORY.md", "SPEC_Atomic_Memory_System.md"):
                continue
            if md_file.name.startswith("_"):
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            results["scanned"] += 1

            # Parse metadata
            lu_match = re.search(r"Last-used:\s*(\d{4}-\d{2}-\d{2})", text)
            conf_match = re.search(r"Confirmations:\s*(\d+)", text)
            if not lu_match or not conf_match:
                continue

            last_used = datetime.strptime(lu_match.group(1), "%Y-%m-%d")
            confirmations = int(conf_match.group(1))

            # Composite decay score
            days_since = (today - last_used).days
            recency = math.exp(-math.log(2) * max(days_since, 0) / decay_half_life)
            usage = min(1.0, math.log10(confirmations + 1) / 2)
            score = 0.5 * recency + 0.5 * usage

            # Archive candidate?
            if score < archive_threshold:
                results["archive_candidates"].append({
                    "atom": md_file.stem,
                    "score": round(score, 3),
                    "last_used": lu_match.group(1),
                    "confirmations": confirmations,
                })

            # Auto-promote [臨]→[觀] if atom confirmations high enough
            if confirmations >= promote_min_conf:
                lines = text.split("\n")
                promoted_in_file = []
                changed = False
                for i, line in enumerate(lines):
                    if re.match(r"^- \[臨\]", line):
                        lines[i] = line.replace("- [臨]", "- [觀]", 1)
                        desc = line.split("[臨]", 1)[-1].strip()[:60]
                        promoted_in_file.append(desc)
                        changed = True

                if changed:
                    # W12: atomic write — prevent partial reads during promotion
                    tmp = md_file.with_suffix(".tmp")
                    try:
                        tmp.write_text("\n".join(lines), encoding="utf-8")
                        tmp.replace(md_file)
                    except OSError:
                        try:
                            tmp.unlink()
                        except OSError:
                            pass
                    results["promoted"].append({
                        "atom": md_file.stem,
                        "items": promoted_in_file,
                        "confirmations": confirmations,
                    })

    # Write archive candidates to staging
    if results["archive_candidates"]:
        cwd = state.get("session", {}).get("cwd", "")
        staging = resolve_staging_dir(cwd)
        staging.mkdir(exist_ok=True)
        out_lines = [
            f"# Archive Candidates ({today.strftime('%Y-%m-%d')})\n",
            f"Score < {archive_threshold} — 考慮封存或刪除：\n",
        ]
        for c in results["archive_candidates"]:
            out_lines.append(
                f"- **{c['atom']}** — score={c['score']}, "
                f"last_used={c['last_used']}, confirmations={c['confirmations']}"
            )
        (staging / "archive-candidates.md").write_text(
            "\n".join(out_lines), encoding="utf-8"
        )

    return results


# ─── Rut Pattern Detection (V2.17) ──────────────────────────────────────────


def _detect_rut_patterns(
    state: Dict[str, Any], config: Dict[str, Any]
) -> Optional[str]:
    """V2.17: Scan recent episodic atoms for repeated 覆轍信號 across sessions.

    Returns warning text if same pattern appears in 2+ sessions, None otherwise.
    Piggybacks on the same episodic scan pattern as _detect_oscillation.
    """
    window = config.get("self_iteration", {}).get("oscillation_window", 3)

    # Collect episodic dirs (same logic as _detect_oscillation)
    episodic_dirs = set()
    global_ep = MEMORY_DIR / "episodic"
    if global_ep.exists():
        episodic_dirs.add(global_ep)
    cwd = state.get("session", {}).get("cwd", "")
    proj_mem = get_project_memory_dir(cwd)
    if proj_mem:
        proj_ep = proj_mem / "episodic"
        if proj_ep.exists():
            episodic_dirs.add(proj_ep)

    # Gather recent episodic files
    recent_files = []
    for ep_dir in episodic_dirs:
        for f in ep_dir.glob("episodic-*.md"):
            recent_files.append((f.stat().st_mtime, f))
    recent_files.sort(key=lambda x: -x[0])
    recent_files = recent_files[:window]

    # Parse 覆轍信號 lines
    signal_sessions: Dict[str, int] = {}  # signal -> session count
    for _, ep_path in recent_files:
        try:
            text = ep_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.split("\n"):
            if "覆轍信號:" not in line:
                continue
            signals_part = line.split("覆轍信號:")[-1].strip()
            for sig in signals_part.split(","):
                sig = sig.strip()
                if sig:
                    signal_sessions[sig] = signal_sessions.get(sig, 0) + 1

    # Alert if any signal appeared in 2+ sessions
    repeated = [s for s, c in signal_sessions.items() if c >= 2]
    if not repeated:
        return None

    return (
        f"[Guardian:覆轍] 跨 session 反覆出現：{', '.join(repeated)}。"
        f"行動：1) 停止表面修復 2) 分析根因 3) 記錄到 atom 防止再犯"
    )


# ─── Periodic Review ────────────────────────────────────────────────────────


def _check_periodic_review_due(config: Dict[str, Any]) -> Optional[str]:
    """Check if periodic self-review is due.

    Counts episodic atoms since last review marker.
    Returns review reminder text if due, None otherwise.
    """
    review_interval = config.get("self_iteration", {}).get("review_interval", 6)
    marker_path = WORKFLOW_DIR / "last_review_marker.json"

    # Read last review marker
    last_review_session_count = 0
    if marker_path.exists():
        try:
            with open(marker_path, "r", encoding="utf-8") as f:
                marker = json.load(f)
            last_review_session_count = marker.get("session_count", 0)
        except (json.JSONDecodeError, OSError):
            pass

    # Count current total sessions
    total = 0
    for ep_dir in [MEMORY_DIR / "episodic"]:
        if ep_dir.exists():
            total += sum(1 for _ in ep_dir.glob("episodic-*.md"))
    # V2.20: via wg_paths
    for _slug, _mem_dir in discover_all_project_memory_dirs():
        ep = _mem_dir / "episodic"
        if ep.exists():
            total += sum(1 for _ in ep.glob("episodic-*.md"))

    sessions_since_review = total - last_review_session_count
    if sessions_since_review >= review_interval:
        maturity = _calculate_maturity_phase(config)
        return (
            f"[自我迭代] 定期檢閱到期（距上次 {sessions_since_review} sessions）。"
            f"系統{maturity['description']}。"
            f"建議在適當時機進行近期 session 回顧：掃描 episodic atoms、"
            f"找出重複模式、收攏或晉升規則。"
        )
    return None


def _save_review_marker(total_sessions: int) -> None:
    """Save review marker after a periodic review is completed."""
    marker_path = WORKFLOW_DIR / "last_review_marker.json"
    marker = {
        "session_count": total_sessions,
        "reviewed_at": _now_iso(),
    }
    try:
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(marker, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
