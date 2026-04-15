#!/usr/bin/env python3
"""
memory-conflict-detector.py — Atomic Memory Conflict Detection (v2.1 Sprint 2)

掃描所有活躍 atom，透過向量相似度找出疑似衝突對，
再用 LLM (rdchat: gemma4:e4b / local: qwen3:1.7b) 判定 AGREE/CONTRADICT/EXTEND/UNRELATED。

Session-end 離線路徑，不在 hook timeout 內執行。

Usage:
    python memory-conflict-detector.py                  # 全掃描
    python memory-conflict-detector.py --atom X         # 只掃 atom X 的衝突
    python memory-conflict-detector.py --dry-run        # 不呼叫 LLM，只列 candidate pairs
    python memory-conflict-detector.py --json           # JSON 輸出
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ollama_client import get_client

CLAUDE_DIR = Path.home() / ".claude"
AUDIT_LOG = CLAUDE_DIR / "memory" / "_vectordb" / "audit.log"

# V4 Phase 5 conflict detection
WRITE_CHECK_THRESHOLD = 0.85       # SPEC §7.3
WRITE_CHECK_VECTOR_MIN = 0.60      # vector pre-filter (cheaper than LLM)
WRITE_CHECK_DUP_THRESHOLD = 0.95   # duplicate cutoff (handled by write-gate)
DETECTOR_MODEL_LABEL = "gemma4:e4b"  # SPEC §9 (info only — actual model from ollama_client)

# Confidence ranking for arbitration
CONF_RANK = {"[固]": 3, "[觀]": 2, "[臨]": 1}

# ─── Atom Discovery (lightweight, no dependency on memory-audit.py) ──────────

META_RE = re.compile(r"^-\s+([\w-]+):\s*(.+)$")
SKIP_FILES = {"MEMORY.md", "_CHANGELOG.md", "_CHANGELOG_ARCHIVE.md"}
SKIP_PREFIXES = ("SPEC_", "_")
BULLET_RE = re.compile(r"^- \[([固觀臨])\]\s*(.+)")


def discover_layers(project_dir: Optional[Path] = None) -> List[Tuple[str, Path]]:
    """Discover global + project memory layers.

    V2.21: project_dir 若提供，優先列在全域層之前。
    """
    layers = []
    # V2.21: 專案自治層優先（project_dir 若有效才加）
    if project_dir is not None and project_dir.is_dir() and (project_dir / "MEMORY.md").exists():
        layers.append(("project", project_dir))
    global_mem = CLAUDE_DIR / "memory"
    if global_mem.is_dir():
        layers.append(("global", global_mem))
    # Legacy: ~/.claude/projects/{slug}/memory/
    projects_dir = CLAUDE_DIR / "projects"
    if projects_dir.is_dir():
        for proj_dir in sorted(projects_dir.iterdir()):
            if proj_dir.is_dir():
                mem_dir = proj_dir / "memory"
                if mem_dir.is_dir():
                    layers.append((f"project:{proj_dir.name}", mem_dir))
    return layers


def discover_atoms(layers: List[Tuple[str, Path]]) -> List[Tuple[str, Path, str]]:
    """Find atom files. Returns [(layer, path, atom_name), ...]."""
    atoms = []
    for layer_name, mem_dir in layers:
        for md_file in sorted(mem_dir.glob("*.md")):
            if md_file.name in SKIP_FILES:
                continue
            if any(md_file.name.startswith(p) for p in SKIP_PREFIXES):
                continue
            atoms.append((layer_name, md_file, md_file.stem))
    return atoms


def parse_atom_meta(path: Path) -> Dict[str, Any]:
    """Extract metadata from atom file."""
    meta = {"title": "", "scope": "", "confidence": "", "last_used": "", "tags": []}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return meta
    for line in text.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            meta["title"] = line[2:].strip()
        m = META_RE.match(line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key == "Scope":
                meta["scope"] = val
            elif key == "Confidence":
                cm = re.search(r"\[(固|觀|臨)\]", val)
                meta["confidence"] = f"[{cm.group(1)}]" if cm else val
            elif key == "Last-used":
                meta["last_used"] = val
            elif key == "Tags":
                meta["tags"] = [t.strip() for t in val.split(",") if t.strip()]
    return meta


def extract_facts(path: Path) -> List[str]:
    """Extract knowledge bullet points from atom's 知識 section."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []

    facts = []
    in_knowledge = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            section = stripped[3:].strip()
            in_knowledge = "知識" in section
            continue
        if in_knowledge and stripped.startswith("- "):
            # Strip confidence prefix if present
            bm = BULLET_RE.match(stripped)
            if bm:
                facts.append(bm.group(2).strip())
            else:
                facts.append(stripped[2:].strip())
    return [f for f in facts if len(f) > 10]  # Skip trivially short


# ─── Vector Service Query ────────────────────────────────────────────────────

def vector_search(query: str, top_k: int = 10, min_score: float = 0.40) -> List[Dict]:
    """Search via Memory Vector Service."""
    try:
        import urllib.parse
        params = urllib.parse.urlencode({"q": query, "top_k": top_k, "min_score": min_score})
        url = f"http://127.0.0.1:3849/search?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return []


# ─── LLM Conflict Classification ─────────────────────────────────────────────

def ollama_classify(fact_a: str, atom_a: str, conf_a: str,
                    fact_b: str, atom_b: str, conf_b: str) -> str:
    """Ask LLM to classify relationship. Returns AGREE/CONTRADICT/EXTEND/UNRELATED."""
    prompt = (
        f"Classify the relationship between two knowledge facts from a memory system.\n\n"
        f"Fact A (from {atom_a}, confidence {conf_a}):\n{fact_a}\n\n"
        f"Fact B (from {atom_b}, confidence {conf_b}):\n{fact_b}\n\n"
        f"Reply with exactly one word: AGREE, CONTRADICT, EXTEND, or UNRELATED.\n"
        f"/no_think"
    )
    try:
        client = get_client()
        text = client.chat(
            [{"role": "user", "content": prompt}],
            system="You classify memory relationships. Reply with exactly one word.",
            timeout=30,
        ).strip().upper()
        for label in ("CONTRADICT", "EXTEND", "AGREE", "UNRELATED"):
            if label in text:
                return label
        return "UNRELATED"
    except Exception as e:
        print(f"  [LLM error] {e}", file=sys.stderr)
        return "ERROR"


# ─── Arbitration ──────────────────────────────────────────────────────────────

def arbitrate(meta_a: Dict, meta_b: Dict) -> Dict[str, Any]:
    """Determine winner for CONTRADICT pair. Returns suggestion dict."""
    scope_a = meta_a.get("scope", "")
    scope_b = meta_b.get("scope", "")
    conf_a = meta_a.get("confidence", "")
    conf_b = meta_b.get("confidence", "")
    date_a = meta_a.get("last_used", "")
    date_b = meta_b.get("last_used", "")

    reason = ""
    winner = "a"

    # Rule 1: project > global
    if "project" in scope_a and "global" in scope_b:
        winner, reason = "a", "project scope overrides global"
    elif "project" in scope_b and "global" in scope_a:
        winner, reason = "b", "project scope overrides global"
    # Rule 2: higher confidence wins
    elif CONF_RANK.get(conf_a, 0) > CONF_RANK.get(conf_b, 0):
        winner, reason = "a", f"higher confidence ({conf_a} > {conf_b})"
    elif CONF_RANK.get(conf_b, 0) > CONF_RANK.get(conf_a, 0):
        winner, reason = "b", f"higher confidence ({conf_b} > {conf_a})"
    # Rule 3: newer Last-used wins
    elif date_a > date_b:
        winner, reason = "a", f"more recent ({date_a} > {date_b})"
    elif date_b > date_a:
        winner, reason = "b", f"more recent ({date_b} > {date_a})"
    else:
        winner, reason = "a", "tie — manual review recommended"

    return {"winner": winner, "reason": reason}


# ─── Audit Log ────────────────────────────────────────────────────────────────

def write_audit(entries: List[Dict]) -> None:
    """Append conflict detection results to audit.log (JSONL)."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ─── Main Scan Logic ─────────────────────────────────────────────────────────

def scan_conflicts(
    target_atom: Optional[str] = None,
    dry_run: bool = False,
    project_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Scan for conflicts across all active atoms.

    Strategy:
    1. Extract facts from each atom's 知識 section
    2. For each fact, vector-search for similar facts in OTHER atoms
    3. Pairs with score 0.70-0.95 = candidate conflicts
    4. LLM classifies each candidate (unless dry_run)
    """
    layers = discover_layers(project_dir=project_dir)
    atoms = discover_atoms(layers)

    if target_atom:
        atoms = [(l, p, n) for l, p, n in atoms if n == target_atom]
        if not atoms:
            print(f"Atom '{target_atom}' not found.", file=sys.stderr)
            return []

    # Collect all facts with their metadata
    all_facts: List[Dict[str, Any]] = []
    atom_metas: Dict[str, Dict] = {}

    for layer, path, name in atoms:
        meta = parse_atom_meta(path)
        meta["layer"] = layer
        meta["atom_name"] = name
        atom_metas[f"{layer}:{name}"] = meta

        facts = extract_facts(path)
        for fact in facts:
            all_facts.append({
                "text": fact,
                "atom_name": name,
                "layer": layer,
                "confidence": meta["confidence"],
            })

    print(f"Scanning {len(atoms)} atoms, {len(all_facts)} facts...", file=sys.stderr)

    # Find candidate pairs via vector similarity
    candidates: List[Dict] = []
    checked_pairs = set()

    for fact_info in all_facts:
        results = vector_search(fact_info["text"], top_k=5, min_score=0.60)
        for r in results:
            r_atom = r.get("atom_name", "")
            r_layer = r.get("layer", "")
            # Skip same atom
            if r_atom == fact_info["atom_name"] and r_layer == fact_info["layer"]:
                continue
            # Skip if score too high (likely same fact) or too low
            score = r.get("score", 0)
            if score > 0.95 or score < 0.60:
                continue
            # Deduplicate pair
            pair_key = tuple(sorted([
                f"{fact_info['layer']}:{fact_info['atom_name']}:{fact_info['text'][:50]}",
                f"{r_layer}:{r_atom}:{r.get('text', '')[:50]}"
            ]))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)

            candidates.append({
                "fact_a": fact_info["text"],
                "atom_a": fact_info["atom_name"],
                "layer_a": fact_info["layer"],
                "conf_a": fact_info["confidence"],
                "fact_b": r.get("text", ""),
                "atom_b": r_atom,
                "layer_b": r_layer,
                "conf_b": r.get("confidence", ""),
                "similarity": score,
            })

    print(f"Found {len(candidates)} candidate pairs.", file=sys.stderr)

    if dry_run:
        return candidates

    # LLM classification
    results = []
    audit_entries = []

    for i, cand in enumerate(candidates):
        print(f"  [{i+1}/{len(candidates)}] {cand['atom_a']} vs {cand['atom_b']} "
              f"(sim={cand['similarity']:.3f})...", file=sys.stderr)

        label = ollama_classify(
            cand["fact_a"], cand["atom_a"], cand["conf_a"],
            cand["fact_b"], cand["atom_b"], cand["conf_b"],
        )
        cand["classification"] = label

        if label == "CONTRADICT":
            meta_a = atom_metas.get(f"{cand['layer_a']}:{cand['atom_a']}", {})
            meta_b = atom_metas.get(f"{cand['layer_b']}:{cand['atom_b']}", {})
            arb = arbitrate(meta_a, meta_b)
            cand["arbitration"] = arb

        results.append(cand)

        audit_entries.append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "action": "conflict_scan",
            "atom_a": cand["atom_a"],
            "atom_b": cand["atom_b"],
            "similarity": round(cand["similarity"], 4),
            "classification": label,
        })

    if audit_entries:
        write_audit(audit_entries)

    return results


# ─── Output Formatting ───────────────────────────────────────────────────────

def print_report(results: List[Dict], dry_run: bool = False) -> None:
    """Print human-readable conflict report."""
    if not results:
        print("No conflicts or candidates found.")
        return

    if dry_run:
        print(f"\n=== Candidate Pairs ({len(results)}) ===\n")
        for i, r in enumerate(results, 1):
            print(f"[{i}] {r['atom_a']} ({r['layer_a']}) <-> {r['atom_b']} ({r['layer_b']})")
            print(f"    Similarity: {r['similarity']:.3f}")
            print(f"    A: {r['fact_a'][:80]}...")
            print(f"    B: {r['fact_b'][:80]}...")
            print()
        return

    contradictions = [r for r in results if r.get("classification") == "CONTRADICT"]
    extends = [r for r in results if r.get("classification") == "EXTEND"]
    agrees = [r for r in results if r.get("classification") == "AGREE"]

    print(f"\n=== Conflict Detection Report ===")
    print(f"Total pairs scanned: {len(results)}")
    print(f"  CONTRADICT: {len(contradictions)}")
    print(f"  EXTEND: {len(extends)}")
    print(f"  AGREE: {len(agrees)}")
    print(f"  UNRELATED/ERROR: {len(results) - len(contradictions) - len(extends) - len(agrees)}")

    if contradictions:
        print(f"\n--- CONTRADICTIONS ({len(contradictions)}) ---\n")
        for r in contradictions:
            arb = r.get("arbitration", {})
            winner_label = r[f"atom_{arb.get('winner', 'a')}"]
            print(f"  {r['atom_a']} vs {r['atom_b']} (sim={r['similarity']:.3f})")
            print(f"    A [{r['conf_a']}]: {r['fact_a'][:100]}")
            print(f"    B [{r['conf_b']}]: {r['fact_b'][:100]}")
            print(f"    Suggestion: keep {winner_label} ({arb.get('reason', '')})")
            print()

    if extends:
        print(f"\n--- EXTENSIONS ({len(extends)}) ---\n")
        for r in extends:
            print(f"  {r['atom_a']} extends {r['atom_b']} (sim={r['similarity']:.3f})")
            print(f"    Consider merging or adding Related link.")
            print()


# ─── V4 Phase 5: write-check / pull-audit shared helpers ─────────────────────

MERGE_HISTORY_NAME = "_merge_history.log"
LAST_AUDIT_TS_NAME = ".last_pull_audit_ts"
GIT_ONLY_RE = re.compile(r"^-\s+Merge-strategy:\s*git-only", re.IGNORECASE | re.MULTILINE)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_merge_history(proj_root: Path, action: str, atom: str,
                          scope: str, by: str, detail: str) -> None:
    """TSV append-only audit log under {proj}/.claude/memory/."""
    log_path = proj_root / ".claude" / "memory" / MERGE_HISTORY_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    safe = lambda s: str(s).replace("\t", " ").replace("\n", " ").strip() or "-"
    line = "\t".join([_utcnow_iso(), safe(action), safe(atom),
                      safe(scope), safe(by), safe(detail)]) + "\n"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        print(f"[merge_history] write failed: {e}", file=sys.stderr)


def _is_git_only_atom(text: str) -> bool:
    return bool(GIT_ONLY_RE.search(text))


def _classify_match(content: str, match: Dict[str, Any]) -> str:
    """Wrap ollama_classify for write-time/pull-time pairs.

    On any LLM error returns "ERROR" — caller treats as conservative pending.
    """
    return ollama_classify(
        fact_a=content[:1500],
        atom_a="<incoming>",
        conf_a="[臨]",
        fact_b=match.get("text", "")[:1500],
        atom_b=match.get("atom_name", ""),
        conf_b=match.get("confidence", ""),
    )


def _decide_verdict(matches: List[Dict[str, Any]],
                    threshold: float) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Apply SPEC §7.2 ordering: contradict > duplicate > extend_overlap > ok.

    Returns (verdict, primary_match_or_None).
    """
    contradict = next((m for m in matches if m.get("classification") == "CONTRADICT"), None)
    if contradict:
        return "contradict", contradict
    dup = next((m for m in matches
                if m.get("classification") == "AGREE" and m.get("similarity", 0) >= WRITE_CHECK_DUP_THRESHOLD),
               None)
    if dup:
        return "duplicate", dup
    ext = next((m for m in matches
                if m.get("classification") == "EXTEND" and m.get("similarity", 0) >= threshold),
               None)
    if ext:
        return "extend_overlap", ext
    # Conservative: any ERROR with high similarity → contradict (pending fallback)
    err_high = next((m for m in matches
                     if m.get("classification") == "ERROR" and m.get("similarity", 0) >= threshold),
                    None)
    if err_high:
        return "contradict", err_high
    return "ok", None


def run_write_check(content: str, project_cwd: Optional[str], scope: str,
                    threshold: float = WRITE_CHECK_THRESHOLD) -> Dict[str, Any]:
    """Pre-write semantic conflict check (SPEC §7.1 write-time).

    Returns:
      {verdict, matches: [...], detector_model, skipped, skip_reason}
    Verdict ∈ {ok, extend_overlap, contradict, duplicate}.

    On any vector/LLM unavailability: verdict=ok + skipped=True (fail-open at
    write-time so dead infrastructure does not block all writes).
    """
    out = {
        "verdict": "ok",
        "matches": [],
        "detector_model": DETECTOR_MODEL_LABEL,
        "skipped": False,
        "skip_reason": None,
        "scope": scope,
    }
    if not content or not content.strip():
        out["skipped"] = True
        out["skip_reason"] = "empty content"
        return out

    try:
        hits = vector_search(content, top_k=3, min_score=WRITE_CHECK_VECTOR_MIN)
    except Exception as e:
        out["skipped"] = True
        out["skip_reason"] = f"vector_search failed: {e}"
        return out

    if not hits:
        return out

    matches: List[Dict[str, Any]] = []
    llm_errors = 0
    for h in hits:
        sim = float(h.get("score", 0))
        if sim < WRITE_CHECK_VECTOR_MIN:
            continue
        # Skip git-only atoms (SPEC §7.3)
        try:
            atom_path = Path(h.get("file_path", ""))
            if atom_path.is_file() and _is_git_only_atom(atom_path.read_text(encoding="utf-8-sig")):
                continue
        except OSError:
            pass

        label = _classify_match(content, h)
        if label == "ERROR":
            llm_errors += 1
        matches.append({
            "atom_name": h.get("atom_name", ""),
            "layer": h.get("layer", ""),
            "similarity": round(sim, 4),
            "classification": label,
            "fact_preview": h.get("text", "")[:120],
            "file_path": h.get("file_path", ""),
            "confidence": h.get("confidence", ""),
        })

    out["matches"] = matches
    if llm_errors and llm_errors == len(matches):
        out["skipped"] = True
        out["skip_reason"] = "all LLM classifications failed"
        return out

    verdict, _primary = _decide_verdict(matches, threshold)
    out["verdict"] = verdict
    return out


# ─── pull-audit ──────────────────────────────────────────────────────────────


def _get_last_audit_ts(proj_root: Path) -> str:
    """Return ISO ts of last audit, or unix epoch start if first run."""
    f = proj_root / ".claude" / "memory" / "shared" / LAST_AUDIT_TS_NAME
    if f.is_file():
        try:
            return f.read_text(encoding="utf-8").strip() or "1970-01-01T00:00:00Z"
        except OSError:
            pass
    return "1970-01-01T00:00:00Z"


def _set_last_audit_ts(proj_root: Path, ts: str) -> None:
    f = proj_root / ".claude" / "memory" / "shared" / LAST_AUDIT_TS_NAME
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        f.write_text(ts, encoding="utf-8")
    except OSError as e:
        print(f"[pull-audit] cannot persist ts: {e}", file=sys.stderr)


def _git(args: List[str], cwd: Path) -> Tuple[int, str, str]:
    """Run git command. Returns (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd)] + args,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def _collect_changed_atoms(proj_root: Path, since_ts: str) -> List[Dict[str, Any]]:
    """Use git log to find atoms in shared/ changed since `since_ts`.

    Returns list of {commit, path, atom_name, content (from HEAD)}.
    Only includes files currently present in working tree (deleted ones skipped).
    """
    rel = ".claude/memory/shared"
    rc, out, err = _git(["log", f"--since={since_ts}", "--name-only",
                         "--pretty=format:COMMIT %H", "--", rel], proj_root)
    if rc != 0:
        print(f"[pull-audit] git log failed: {err}", file=sys.stderr)
        return []

    seen: Dict[str, str] = {}  # path -> latest commit hash
    current_commit = ""
    for line in out.splitlines():
        if line.startswith("COMMIT "):
            current_commit = line[7:].strip()
            continue
        line = line.strip()
        if not line or not line.endswith(".md"):
            continue
        if not line.startswith(rel + "/"):
            continue
        # Skip pending review and system files
        rest = line[len(rel) + 1:]
        if rest.startswith("_") or rest.startswith("SPEC_"):
            continue
        if rest in ("MEMORY.md", "_ATOM_INDEX.md"):
            continue
        if line not in seen:
            seen[line] = current_commit

    out_list: List[Dict[str, Any]] = []
    for path_rel, commit in seen.items():
        abs_path = proj_root / path_rel
        if not abs_path.is_file():
            continue
        try:
            text = abs_path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        atom_name = abs_path.stem
        out_list.append({
            "commit": commit,
            "path": str(abs_path),
            "rel_path": path_rel,
            "atom_name": atom_name,
            "content": text,
        })
    return out_list


def _write_pull_conflict_report(proj_root: Path, atom_name: str,
                                incoming: Dict[str, Any],
                                match: Dict[str, Any],
                                verdict: str) -> Path:
    """Create _pending_review/{atom}.pull-conflict.md report (non-atom format)."""
    pending_dir = proj_root / ".claude" / "memory" / "shared" / "_pending_review"
    pending_dir.mkdir(parents=True, exist_ok=True)
    report_path = pending_dir / f"{atom_name}.pull-conflict.md"
    body = (
        f"# Pull-time conflict: {atom_name}\n\n"
        f"- Detected-at: {_utcnow_iso()}\n"
        f"- Verdict: {verdict}\n"
        f"- Detector: {DETECTOR_MODEL_LABEL}\n"
        f"- Pending-review-by: management\n\n"
        f"## Incoming (commit `{incoming.get('commit', '?')[:8]}`)\n\n"
        f"Path: `{incoming.get('rel_path', '')}`\n\n"
        "```\n" + incoming.get("content", "")[:4000] + "\n```\n\n"
        f"## Conflicting existing atom\n\n"
        f"- atom: `{match.get('atom_name', '')}` (layer={match.get('layer', '')})\n"
        f"- similarity: {match.get('similarity', 0):.3f}\n"
        f"- classification: {match.get('classification', '')}\n"
        f"- preview: {match.get('fact_preview', '')}\n\n"
        "## Resolution\n\n"
        "管理職 `/conflict-review`：\n"
        "1. 編輯 incoming atom 或 conflicting atom 解決矛盾\n"
        "2. approve（搬到 shared/）或 reject（刪 pending 報告）\n"
    )
    report_path.write_text(body, encoding="utf-8")
    return report_path


def run_pull_audit(project_cwd: str, since: str = "last") -> Dict[str, Any]:
    """Audit incoming git changes for semantic conflicts (SPEC §7.1 pull-time).

    Strategy:
      1. Resolve since_ts (read .last_pull_audit_ts if "last")
      2. git log → list shared/*.md changed since
      3. For each changed atom: vector_search its content (excluding self) → classify
      4. CONTRADICT/extend_overlap → write _pending_review/{atom}.pull-conflict.md
      5. Append _merge_history.log lines
      6. Update .last_pull_audit_ts
    Fail-open: returns {error: ...} on git failure but never crashes the hook.
    """
    proj_root = Path(project_cwd).resolve()
    if not (proj_root / ".git").exists():
        return {"error": "not a git repo", "project_cwd": str(proj_root)}

    since_ts = _get_last_audit_ts(proj_root) if since == "last" else since
    started_at = _utcnow_iso()
    changed = _collect_changed_atoms(proj_root, since_ts)

    flagged: List[Dict[str, Any]] = []
    for atom in changed:
        if _is_git_only_atom(atom["content"]):
            continue
        # Use the atom's main knowledge body (after `## 知識`) for embedding
        content_for_check = atom["content"]
        m = re.search(r"##\s*知識\s*\n+(.+?)(?=\n##\s|\Z)", content_for_check, re.DOTALL)
        body = (m.group(1).strip() if m else content_for_check)[:1500]
        if not body:
            continue

        try:
            hits = vector_search(body, top_k=3, min_score=WRITE_CHECK_VECTOR_MIN)
        except Exception as e:
            print(f"[pull-audit] vector failed for {atom['atom_name']}: {e}", file=sys.stderr)
            continue

        # Filter out self-matches
        self_path = atom["path"].replace("\\", "/").lower()
        candidates = [h for h in hits
                      if h.get("file_path", "").replace("\\", "/").lower() != self_path]
        if not candidates:
            continue

        for h in candidates:
            label = _classify_match(body, h)
            sim = float(h.get("score", 0))
            if label == "CONTRADICT" or (label == "ERROR" and sim >= WRITE_CHECK_THRESHOLD):
                match = {
                    "atom_name": h.get("atom_name", ""),
                    "layer": h.get("layer", ""),
                    "similarity": round(sim, 4),
                    "classification": label,
                    "fact_preview": h.get("text", "")[:120],
                }
                report = _write_pull_conflict_report(proj_root, atom["atom_name"],
                                                    atom, match, "contradict")
                _append_merge_history(proj_root, "pull-audit-flag", atom["atom_name"],
                                      "shared", "<git>",
                                      f"contradict vs {match['atom_name']} sim={sim:.3f} report={report.name}")
                flagged.append({"atom": atom["atom_name"], "report": str(report),
                                "match": match["atom_name"], "similarity": sim})
                break  # one report per incoming atom

    _set_last_audit_ts(proj_root, started_at)
    return {
        "since": since_ts,
        "until": started_at,
        "atoms_scanned": len(changed),
        "flagged_count": len(flagged),
        "flagged": flagged,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Atomic Memory Conflict Detector (v2.1 / V4 Phase 5)")
    parser.add_argument("--atom", help="Only scan conflicts for this atom (full-scan mode)")
    parser.add_argument("--dry-run", action="store_true", help="List candidates without LLM classification")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--project-dir", type=str, default=None,
                        help="V2.21 專案記憶目錄（{project_root}/.claude/memory/），優先掃描")
    # V4 Phase 5 new modes
    parser.add_argument("--mode", choices=["full-scan", "write-check", "pull-audit"],
                        default="full-scan",
                        help="full-scan (legacy) | write-check | pull-audit")
    parser.add_argument("--content", type=str, default=None,
                        help="(write-check) incoming knowledge text")
    parser.add_argument("--scope", type=str, default="shared",
                        help="(write-check) target scope")
    parser.add_argument("--project-cwd", type=str, default=None,
                        help="(write-check / pull-audit) project root")
    parser.add_argument("--threshold", type=float, default=WRITE_CHECK_THRESHOLD,
                        help="(write-check) cosine threshold for extend_overlap (default 0.85)")
    parser.add_argument("--since", type=str, default="last",
                        help="(pull-audit) ISO ts or 'last' (read .last_pull_audit_ts)")
    args = parser.parse_args()

    # ─ V4 Phase 5: write-check ─
    if args.mode == "write-check":
        if not args.content:
            print(json.dumps({"error": "--content is required for write-check"}))
            sys.exit(2)
        result = run_write_check(args.content, args.project_cwd, args.scope, args.threshold)
        print(json.dumps(result, ensure_ascii=False))
        return

    # ─ V4 Phase 5: pull-audit ─
    if args.mode == "pull-audit":
        if not args.project_cwd:
            print(json.dumps({"error": "--project-cwd is required for pull-audit"}))
            sys.exit(2)
        result = run_pull_audit(args.project_cwd, args.since)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if "error" in result:
                print(f"pull-audit error: {result['error']}", file=sys.stderr)
                sys.exit(1)
            print(f"[pull-audit] scanned {result['atoms_scanned']} atoms, "
                  f"flagged {result['flagged_count']} "
                  f"(since {result['since']} → {result['until']})")
            for f in result.get("flagged", []):
                print(f"  ! {f['atom']} CONTRADICT vs {f['match']} "
                      f"(sim={f['similarity']:.3f}) → {f['report']}")
        return

    # ─ legacy: full-scan ─
    project_dir = Path(args.project_dir) if args.project_dir else None
    results = scan_conflicts(target_atom=args.atom, dry_run=args.dry_run, project_dir=project_dir)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print_report(results, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
