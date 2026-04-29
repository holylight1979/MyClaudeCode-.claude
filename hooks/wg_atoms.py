"""
wg_atoms.py — 原子記憶索引解析、Trigger 匹配、ACT-R Activation、載入與預算

Memory Index 解析、atom 檔案載入、token budget 控制、
metadata stripping、activation-based truncation。
"""

import json
import math
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from wg_paths import MEMORY_DIR, EPISODIC_DIR, MEMORY_INDEX, ATOM_INDEX, resolve_access_json
from wg_core import CONTEXT_BUDGET_DEFAULT

# ─── Memory Index Parsing ────────────────────────────────────────────────────

TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
ALIAS_RE = re.compile(r"^>\s*Project-Aliases:\s*(.+)", re.MULTILINE)  # v2.9

# Atom entry: (name, relative_path, trigger_keywords[])
AtomEntry = Tuple[str, str, List[str]]


def parse_memory_index(memory_dir: Path) -> List[AtomEntry]:
    """Parse atom index, return list of (name, path, triggers).

    V3.2: 優先讀 _ATOM_INDEX.md（不被 @import 的機器專用索引），
    Fallback 到 MEMORY.md（向後相容）。
    V2.21: 如果 MEMORY.md 是指標型（Status: migrated-v2.21），
    自動重導向到 Root 指向的新路徑讀取。
    """
    # V3.2: 優先讀 _ATOM_INDEX.md
    atom_index_path = memory_dir / ATOM_INDEX
    if atom_index_path.exists():
        try:
            text = atom_index_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            text = None
        if text:
            return _parse_trigger_table(text)

    # Fallback: MEMORY.md
    index_path = memory_dir / MEMORY_INDEX
    if not index_path.exists():
        return []
    try:
        text = index_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []

    # V2.21: 指標型 MEMORY.md 重導向
    if "Status: migrated-v2.21" in text:
        root_m = re.search(r"^-\s+Root:\s*(.+)$", text, re.MULTILINE)
        if root_m:
            redirect_dir = Path(root_m.group(1).strip()) / ".claude" / "memory"
            if redirect_dir.is_dir() and redirect_dir != memory_dir:
                return parse_memory_index(redirect_dir)
        return []

    return _parse_trigger_table(text)


def _parse_trigger_table(text: str) -> List[AtomEntry]:
    """Parse markdown trigger table into atom entries."""
    atoms: List[AtomEntry] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_table:
            if stripped.startswith("| Atom") or stripped.startswith("|Atom"):
                in_table = True
                continue
        else:
            if stripped.startswith("|---") or stripped.startswith("| ---"):
                continue
            if not stripped.startswith("|"):
                in_table = False
                continue
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if len(cells) >= 3:
                name = cells[0]
                rel_path = cells[1]
                triggers = [t.strip().lower() for t in cells[2].split(",") if t.strip()]
                atoms.append((name, rel_path, triggers))
            elif cells:
                atoms.append((cells[0], "", []))
    return atoms


def _parse_atom_index_file(file_path: Path) -> List[AtomEntry]:
    """Parse a standalone atom index file (like _AIAtoms/_ATOM_INDEX.md)."""
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []
    atoms: List[AtomEntry] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_table:
            if stripped.startswith("| Atom") or stripped.startswith("|Atom"):
                in_table = True
                continue
        else:
            if stripped.startswith("|---") or stripped.startswith("| ---"):
                continue
            if not stripped.startswith("|"):
                in_table = False
                continue
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if len(cells) >= 3:
                name = cells[0]
                rel_path = cells[1]
                triggers = [t.strip().lower() for t in cells[2].split(",") if t.strip()]
                atoms.append((name, rel_path, triggers))
            elif cells:
                atoms.append((cells[0], "", []))
    return atoms


def parse_project_aliases(memory_dir: Path) -> List[str]:
    """Parse > Project-Aliases: line from MEMORY.md. Returns lowercase alias keywords."""
    index_path = memory_dir / MEMORY_INDEX
    if not index_path.exists():
        return []
    try:
        text = index_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []
    m = ALIAS_RE.search(text)
    if not m:
        return []
    return [a.strip().lower() for a in m.group(1).split(",") if a.strip()]


def _find_atom_path(name: str, all_atoms: List[Tuple[AtomEntry, Path]]) -> Optional[Path]:
    """Find the file path for a named atom from the all_atoms list."""
    for (aname, rel_path, _triggers), base_dir in all_atoms:
        if aname == name:
            return (base_dir / rel_path) if rel_path else (base_dir / "memory" / f"{name}.md")
    return None


# ─── Atom Matching & Activation ──────────────────────────────────────────────


def spread_related(
    matched_names: set,
    all_atoms: List[Tuple[AtomEntry, Path]],
    already_injected: List[str],
    max_depth: int = 1,
) -> List[Tuple[AtomEntry, Path]]:
    """沿 Related 邊擴散，回傳尚未匹配的相關 atoms (depth-limited BFS)."""
    _RELATED_RE = re.compile(r"^- Related:\s*(.+)", re.MULTILINE)
    visited = set(matched_names) | set(already_injected)
    wave = list(matched_names)
    result: List[Tuple[AtomEntry, Path]] = []

    for _depth in range(max_depth):
        next_wave: List[str] = []
        for name in wave:
            atom_path = _find_atom_path(name, all_atoms)
            if not atom_path or not atom_path.exists():
                continue
            try:
                text = atom_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            rm = _RELATED_RE.search(text)
            if not rm:
                continue
            for rn in (r.strip() for r in rm.group(1).split(",") if r.strip()):
                if rn not in visited:
                    visited.add(rn)
                    for entry_tuple in all_atoms:
                        if entry_tuple[0][0] == rn:
                            result.append(entry_tuple)
                            next_wave.append(rn)
                            break
        wave = next_wave
    return result


def compute_activation(atom_name: str, atom_dir: Path) -> float:
    """ACT-R base-level activation: B_i = ln(Σ t_k^{-0.5})."""
    access_file = atom_dir / f"{atom_name}.access.json"
    if not access_file.exists():
        return -10.0
    try:
        data = json.loads(access_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return -10.0
    timestamps = data.get("timestamps", [])
    if not timestamps:
        return -10.0
    now = time.time()
    total = 0.0
    for ts in timestamps:
        t_k = max(now - ts, 1.0)
        total += t_k ** -0.5
    return math.log(total) if total > 0 else -10.0


def _kw_match(kw: str, prompt_lower: str) -> bool:
    """Match a trigger keyword against prompt.
    ASCII keywords use word-boundary but exclude hyphenated compounds.
    CJK keywords use plain substring match."""
    if kw.isascii():
        return bool(re.search(r'(?<![\w-])' + re.escape(kw) + r'(?![\w-])', prompt_lower))
    return kw in prompt_lower


def match_triggers(prompt: str, atoms: List[AtomEntry]) -> List[AtomEntry]:
    """Match user prompt against atom Trigger keywords. Case-insensitive."""
    prompt_lower = prompt.lower()
    matched = []
    for name, rel_path, triggers in atoms:
        if any(_kw_match(kw, prompt_lower) for kw in triggers):
            matched.append((name, rel_path, triggers))
    return matched


# ─── Token Budget & Atom Loading ─────────────────────────────────────────────


def compute_token_budget(prompt: str) -> int:
    """Auto-adjust injection budget (estimated tokens) based on prompt complexity."""
    plen = len(prompt)
    if plen < 50:
        return 1500       # Mode 1: light
    elif plen < 200:
        return 3000       # transitional
    else:
        return 5000       # Mode 2: deep


# V2.14: Token Diet — strip non-essential metadata before injection
_STRIP_META_RE = re.compile(
    r"^- (?:Scope|Type|Trigger|Last-used|Created|Confirmations|ReadHits|Tags|TTL|Expires-at):\s.*$\n?",
    re.MULTILINE,
)

_STRIP_SECTION_RE = re.compile(
    r"^## (?:行動|演化日誌)\s*\n[\s\S]*?(?=^## |\Z)",
    re.MULTILINE,
)


# REG-005 A-layer (2026-04-28): summary-first injection helpers.
# Design: memory/_staging/reg-005-atom-injection-refactor.md

_FRONTMATTER_KEEP_RE = re.compile(
    r"^- (?:Confidence|Trigger|Last-used):\s*.+$",
    re.MULTILINE,
)

_KNOWLEDGE_CAP_TOKENS_DEFAULT = 200


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _extract_named_section(
    content: str, section_title: str, max_tokens: Optional[int] = None,
) -> Optional[str]:
    """Extract a single ## section by exact title (until next ## or EOF).

    Returns the section as `## title\\n<body>` (rstripped), or None if absent.
    When `max_tokens` is provided and the section is larger, the body is truncated
    at the nearest paragraph/line boundary and a `…（已截斷，原 N tokens）` marker
    is appended.
    """
    pattern = re.compile(
        r"^##[ \t]+" + re.escape(section_title) + r"[ \t]*\n([\s\S]*?)(?=^## |\Z)",
        re.MULTILINE,
    )
    m = pattern.search(content)
    if not m:
        return None
    body = m.group(1).rstrip()
    full = f"## {section_title}\n{body}"

    if max_tokens is None:
        return full

    full_tokens = _estimate_tokens(full)
    if full_tokens <= max_tokens:
        return full

    header = f"## {section_title}\n"
    marker = f"\n\n…（已截斷，原 {full_tokens} tokens）"
    target_chars = max_tokens * 4 - len(header) - len(marker)
    if target_chars < 50:
        target_chars = 50
    truncated = body[:target_chars]
    snap = truncated.rfind("\n\n")
    if snap < target_chars * 0.5:
        snap = truncated.rfind("\n")
    if snap > 0:
        truncated = truncated[:snap]
    return f"{header}{truncated.rstrip()}{marker}"


def _detect_atom_type(content: str) -> str:
    """Classify atom layout for injection routing.

    - "knowledge_mixed": has ## 知識 (with or without ## 印象) — needs cap on 知識
    - "impression_action": has ## 印象 but no ## 知識 — inject in full
    - "fallback": neither — delegate to legacy strip
    """
    has_knowledge = _extract_named_section(content, "知識") is not None
    if has_knowledge:
        return "knowledge_mixed"
    has_impression = _extract_named_section(content, "印象") is not None
    if has_impression:
        return "impression_action"
    return "fallback"


def _extract_title_and_frontmatter(content: str) -> str:
    """Build header block: `# Title` + whitelisted frontmatter (Confidence/Trigger/Last-used)."""
    title_line = ""
    for line in content.split("\n"):
        if line.startswith("# ") and not line.startswith("## "):
            title_line = line.rstrip()
            break

    keep_lines = [m.group(0) for m in _FRONTMATTER_KEEP_RE.finditer(content)]
    parts: List[str] = []
    if title_line:
        parts.append(title_line)
    if keep_lines:
        if title_line:
            parts.append("")
        parts.extend(keep_lines)
    return "\n".join(parts)


def _legacy_strip_atom_for_injection(content: str) -> str:
    """V2.14 legacy strip: metadata + 行動/演化日誌 lines removed.

    Used as fallback for atoms lacking standard ## 印象/## 知識 sections.
    """
    content = _STRIP_META_RE.sub("", content)
    content = _STRIP_SECTION_RE.sub("", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def _strip_atom_for_injection(
    content: str, knowledge_cap_tokens: int = _KNOWLEDGE_CAP_TOKENS_DEFAULT,
) -> str:
    """REG-005 A-layer: summary-first injection (replaces V2.14 token diet).

    Routes by atom layout:
    - impression_action → title + frontmatter + ## 印象 (full) + ## 行動 (full)
    - knowledge_mixed   → title + frontmatter + ## 印象 (if any) + ## 知識 (capped) + ## 行動 (full)
    - fallback          → legacy strip (all sections except 行動/演化日誌)

    `knowledge_cap_tokens` truncates the ## 知識 section in mixed atoms
    (default 200; tunable per call).
    """
    atom_type = _detect_atom_type(content)

    if atom_type == "fallback":
        return _legacy_strip_atom_for_injection(content)

    parts: List[str] = []
    header = _extract_title_and_frontmatter(content)
    if header:
        parts.append(header)

    impression = _extract_named_section(content, "印象")
    if impression:
        parts.append(impression)

    if atom_type == "knowledge_mixed":
        knowledge = _extract_named_section(content, "知識", max_tokens=knowledge_cap_tokens)
        if knowledge:
            parts.append(knowledge)

    action = _extract_named_section(content, "行動")
    if action:
        parts.append(action)

    return "\n\n".join(parts).strip()


def _strip_atom_for_injection_impression_only(content: str) -> str:
    """REG-005 B-layer fallback: title + frontmatter + ## 印象 only.

    Used when per-turn token budget is tight. If ## 印象 is absent, returns
    header alone.
    """
    parts: List[str] = []
    header = _extract_title_and_frontmatter(content)
    if header:
        parts.append(header)
    impression = _extract_named_section(content, "印象")
    if impression:
        parts.append(impression)
    return "\n\n".join(parts).strip()


# REG-005 B-layer (2026-04-29): per-turn budget tracker.
# Hard cap on cumulative atom injection per UserPromptSubmit turn. Independent
# of `compute_token_budget` (which sizes the broader Context Budget for all
# injection types: hot cache + project memory + episodic + atoms).

_TURN_BUDGET_LIMIT = 800  # tokens


def decide_atom_injection(
    raw_content: str,
    full_content: str,
    used_tokens: int,
    budget_limit: int = _TURN_BUDGET_LIMIT,
) -> Tuple[str, str, int]:
    """Decide ok / fallback / skip for an atom against per-turn budget.

    Returns (decision, content_to_inject, tokens_consumed):
    - "ok"       : full_content fits within budget — inject as-is
    - "fallback" : full overflows but impression-only fits — inject minimal
    - "skip"     : even impression-only overflows or is not smaller — caller
                   should append a summary line and continue
    """
    full_tokens = _estimate_tokens(full_content)
    if used_tokens + full_tokens <= budget_limit:
        return ("ok", full_content, full_tokens)

    fb_content = _strip_atom_for_injection_impression_only(raw_content)
    fb_tokens = _estimate_tokens(fb_content)
    # Avoid pathological "fallback" to a version larger than full
    if fb_tokens >= full_tokens:
        return ("skip", "", 0)
    if used_tokens + fb_tokens <= budget_limit:
        return ("fallback", fb_content, fb_tokens)
    return ("skip", "", 0)


def load_atoms_within_budget(
    matched: List[AtomEntry],
    memory_dir: Path,
    budget_tokens: int,
    already_injected: List[str],
) -> Tuple[List[str], List[str], int]:
    """Load atom file contents up to budget. Returns (content_lines, injected_names, used_tokens)."""
    lines: List[str] = []
    injected: List[str] = []
    used = 0

    for name, rel_path, triggers in matched:
        if name in already_injected:
            continue
        atom_path = (memory_dir / rel_path) if rel_path else (memory_dir / f"{name}.md")
        if not atom_path.exists():
            continue
        try:
            content = atom_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue

        content = _strip_atom_for_injection(content)
        content_tokens = len(content) // 4
        if used + content_tokens <= budget_tokens:
            lines.append(f"[Atom:{name}]\n{content}")
            injected.append(name)
            used += content_tokens
        else:
            first_line = content.split("\n", 1)[0].strip("# ").strip()
            lines.append(f"[Atom:{name}] {first_line} (full: Read {rel_path or name + '.md'})")
            injected.append(name)
            break

    return lines, injected, used


def _truncate_context_by_activation(
    lines: List[str], limit: int = CONTEXT_BUDGET_DEFAULT,
    source_dirs: Optional[Dict[str, Path]] = None,
) -> List[str]:
    """V2.11: Truncate additionalContext lines to fit within token budget.

    Identifies [Atom:xxx] blocks, scores them by ACT-R activation,
    and replaces lowest-scoring atoms with summary lines until under limit.
    """
    full_text = "\n".join(lines)
    used = len(full_text) // 4
    if used <= limit:
        lines.append(f"[Context budget: {used}/{limit} tokens]")
        return lines

    ATOM_LINE_RE = re.compile(r"^\[Atom:(\S+)\]")
    atom_blocks: List[dict] = []
    i = 0
    while i < len(lines):
        m = ATOM_LINE_RE.match(lines[i])
        if m:
            name = m.group(1)
            end = i + 1
            while end < len(lines) and not ATOM_LINE_RE.match(lines[end]):
                end += 1
            block_text = "\n".join(lines[i:end])
            atom_blocks.append({
                "name": name,
                "start": i,
                "end": end,
                "tokens": len(block_text) // 4,
                "first_line": lines[i].split("\n", 1)[0] if "\n" in lines[i] else lines[i],
            })
            i = end
        else:
            i += 1

    if not atom_blocks:
        lines.append(f"[Context budget: {used}/{limit} tokens (over)]")
        return lines

    for ab in atom_blocks:
        atom_name = ab["name"]
        src_dir = source_dirs.get(atom_name) if source_dirs else None
        if src_dir:
            ab["activation"] = compute_activation(atom_name, src_dir)
        else:
            ab["activation"] = compute_activation(atom_name, MEMORY_DIR)
            if ab["activation"] <= -10.0:
                ab["activation"] = compute_activation(atom_name, EPISODIC_DIR)

    atom_blocks.sort(key=lambda x: x["activation"])

    truncated_indices: set = set()
    for ab in atom_blocks:
        if used <= limit:
            break
        summary = f"[Atom:{ab['name']}] (truncated, activation={ab['activation']:.2f}) Read memory/{ab['name']}.md"
        saved = ab["tokens"] - (len(summary) // 4)
        if saved > 0:
            truncated_indices.add(ab["start"])
            ab["summary"] = summary
            used -= saved

    new_lines: List[str] = []
    skip_until = -1
    for idx, line in enumerate(lines):
        if idx < skip_until:
            continue
        found = False
        for ab in atom_blocks:
            if ab["start"] == idx and idx in truncated_indices:
                new_lines.append(ab["summary"])
                skip_until = ab["end"]
                found = True
                break
        if not found and idx >= skip_until:
            new_lines.append(line)

    new_lines.append(f"[Context budget: {used}/{limit} tokens]")
    return new_lines


# ─── Section-Level Extraction (v2.18) ───────────────────────────────────────

SECTION_INJECT_THRESHOLD = 200  # tokens; atoms smaller than this → full inject (REG-005 B-layer 2026-04-29: 300 → 200)

_SECTION_HEADER_RE = re.compile(r"^(#{2,3})\s+(.+)", re.MULTILINE)
_RELATED_LINE_RE = re.compile(r"^- Related:\s*.+", re.MULTILINE)


def _extract_sections(
    content: str,
    section_hints: List[Dict[str, Any]],
) -> Optional[str]:
    """Extract matching sections from atom content based on vector search hints.

    Args:
        content: Full atom text (already stripped of metadata).
        section_hints: List of dicts with 'section', 'text', 'line_number' from ranked_search_sections.

    Returns:
        Extracted content string, or None if should fallback to full injection
        (0 matches, or extracted ≥ 70% of original).
    """
    if not section_hints:
        return None

    lines = content.split("\n")
    total_lines = len(lines)

    # Build section map: [{header, level, start_line, end_line}]
    section_map: List[Dict[str, Any]] = []
    for m in _SECTION_HEADER_RE.finditer(content):
        level = len(m.group(1))  # 2 or 3
        header_text = m.group(2).strip()
        # Find line number (0-based)
        line_no = content[:m.start()].count("\n")
        section_map.append({
            "header": header_text,
            "level": level,
            "start": line_no,
            "end": total_lines,  # will be refined
        })

    # Set end boundaries
    for i in range(len(section_map) - 1):
        section_map[i]["end"] = section_map[i + 1]["start"]

    # Collect hint section names (lowered)
    hint_names = set()
    for h in section_hints:
        s = h.get("section", "").strip()
        if s:
            hint_names.add(s.lower())

    # Match sections: exact first, then substring fuzzy
    matched_sections: List[Dict[str, Any]] = []
    matched_indices: set = set()

    for idx, sec in enumerate(section_map):
        header_lower = sec["header"].lower()
        if header_lower in hint_names:
            matched_sections.append(sec)
            matched_indices.add(idx)

    # Substring fuzzy for remaining hints
    unmatched_hints = hint_names - {sec["header"].lower() for sec in matched_sections}
    if unmatched_hints:
        for idx, sec in enumerate(section_map):
            if idx in matched_indices:
                continue
            header_lower = sec["header"].lower()
            for hint in unmatched_hints:
                if hint in header_lower or header_lower in hint:
                    matched_sections.append(sec)
                    matched_indices.add(idx)
                    break

    if not matched_sections:
        return None

    # 2E: Chunk expansion — include parent ## if we only matched ### children
    parent_indices: set = set()
    for sec in matched_sections:
        if sec["level"] == 3:
            # Find parent ## (last ## before this ### section)
            sec_start = sec["start"]
            candidate_idx = None
            for idx, s in enumerate(section_map):
                if s["level"] == 2 and s["start"] < sec_start:
                    candidate_idx = idx
            # Add parent header line only (not content)
            if candidate_idx is not None and candidate_idx not in matched_indices:
                parent_indices.add(candidate_idx)

    # Collect lines to include
    include_lines: set = set()

    # Always include atom title (first # line) and Related line
    for i, line in enumerate(lines):
        if line.startswith("# ") and not line.startswith("## "):
            include_lines.add(i)
            break
    rm = _RELATED_LINE_RE.search(content)
    if rm:
        rel_line_no = content[:rm.start()].count("\n")
        include_lines.add(rel_line_no)

    # Include matched section lines (with expansion for bullet context)
    for sec in matched_sections:
        for i in range(sec["start"], sec["end"]):
            include_lines.add(i)

    # Include parent ## header lines (just the header, not content)
    for pidx in parent_indices:
        include_lines.add(section_map[pidx]["start"])

    # Check 70% threshold
    if len(include_lines) >= total_lines * 0.70:
        return None

    # Build output
    omitted = len(section_map) - len(matched_sections) - len(parent_indices)
    output_lines: List[str] = []
    sorted_lines = sorted(include_lines)

    prev = -1
    for i in sorted_lines:
        if prev >= 0 and i > prev + 1:
            # Gap marker (only if significant gap)
            pass
        output_lines.append(lines[i])
        prev = i

    if omitted > 0:
        output_lines.append(f"\n[+{omitted} sections omitted]")

    result = "\n".join(output_lines)
    return result


# ─── _AIDocs Index Parsing (v2.10) ──────────────────────────────────────────

AiDocsEntry = Tuple[str, str, List[str]]  # (filename, description, keywords)


def parse_aidocs_index(project_root: Path) -> List[AiDocsEntry]:
    """Parse _AIDocs/_INDEX.md table, return [(filename, description, keywords)]."""
    index_path = project_root / "_AIDocs" / "_INDEX.md"
    if not index_path.exists():
        return []
    try:
        text = index_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []

    entries: List[AiDocsEntry] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_table:
            if stripped.startswith("| #") or stripped.startswith("|#"):
                in_table = True
                continue
        else:
            if stripped.startswith("|---") or stripped.startswith("| ---"):
                continue
            if not stripped.startswith("|"):
                in_table = False
                continue
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if len(cells) >= 3:
                fname = cells[1].strip("[]() ")
                link_match = re.match(r"\[([^\]]+)\]", cells[1])
                if link_match:
                    fname = link_match.group(1)
                desc = cells[2]
                if fname.startswith("~~") or "淘汰" in desc:
                    continue
                keywords: List[str] = []
                if len(cells) >= 4 and cells[3].strip():
                    keywords = [k.strip().lower() for k in cells[3].split(",") if k.strip()]
                entries.append((fname, desc, keywords))
    return entries


def extract_aidocs_keywords(entries: List[AiDocsEntry]) -> Dict[str, List[str]]:
    """Extract search keywords from _AIDocs entries."""
    STOP = {"的", "與", "和", "等", "個", "含", "—", "md", "分析", "說明", "文件", "專案"}
    result: Dict[str, List[str]] = {}
    for fname, desc, explicit_kw in entries:
        if explicit_kw:
            result[fname] = explicit_kw[:15]
        else:
            words = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z_]{3,}", desc.lower())
            keywords = [w for w in words if w not in STOP]
            stem = Path(fname).stem.lower().replace("_", " ").replace("-", " ")
            keywords.extend(stem.split())
            result[fname] = list(set(keywords))[:10]
    return result
