#!/usr/bin/env python3
"""
memory-audit.py — Atomic Memory System Health Checker

掃描 Claude Code 記憶層（全域 + 專案），驗證 atom 格式、
檢查過期、建議晉升/降級、驗證索引一致性、偵測重複。

Usage:
    python memory-audit.py
    python memory-audit.py --global-only
    python memory-audit.py --project c--Projects
    python memory-audit.py --search-distant handler
    python memory-audit.py --restore path/to/atom.md
    python memory-audit.py --move-distant path/to/atom.md
    python memory-audit.py --json

Requirements: Python 3.8+, no external dependencies.
"""

import sys, io
# Force UTF-8 stdout on Windows (cp950 codepage causes mojibake in JSON output)
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import argparse
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ─── Constants ───────────────────────────────────────────────────────────────

STALENESS_THRESHOLDS: Dict[str, int] = {"[固]": 90, "[觀]": 60, "[臨]": 30}
# v2.1 Sprint 3: Type-based decay multiplier (procedural ages slower, episodic faster)
TYPE_DECAY_MULTIPLIER: Dict[str, float] = {"semantic": 1.0, "episodic": 0.8, "procedural": 1.5}
# SYNC: memory/decisions.md — dual-track promotion thresholds (suggest only, not gate)
PROMOTION_THRESHOLDS = {
    "[臨]": {"confirmations": 4, "readhits": 20},
    "[觀]": {"confirmations": 10, "readhits": 50},
}
INDEX_MAX_LINES = 40
ATOM_MAX_LINES = 200
TRIGGER_MIN = 3
TRIGGER_MAX = 12
MEMORY_INDEX = "MEMORY.md"
DISTANT_DIR = "_distant"
SKIP_PREFIXES = ("SPEC_", "_")  # Files to skip during atom scanning
REQUIRED_METADATA = {"Scope", "Confidence", "Trigger", "Last-used"}
OPTIONAL_METADATA = {"Confirmations", "ReadHits", "Privacy", "Source", "Type", "Created", "TTL",
                     "Expires-at", "Tags", "Related", "Supersedes", "Quality"}
# 行動 always required; 知識 or 印象（指標型 atom 變體）二選一即可
REQUIRED_SECTIONS = {"行動"}
KNOWLEDGE_SECTIONS = {"知識", "印象"}
VALID_CONFIDENCE = {"[固]", "[觀]", "[臨]"}
VALID_TYPES = {"semantic", "episodic", "procedural"}
VALID_PRIVACY = {"public", "internal", "sensitive"}

# ─── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class AtomMetadata:
    file_path: Path
    layer_name: str
    title: str = ""
    scope: str = ""
    confidence: str = ""
    trigger: List[str] = field(default_factory=list)
    last_used: Optional[date] = None
    confirmations: int = 0
    privacy: str = ""
    source: str = ""
    line_count: int = 0
    sections_found: Set[str] = field(default_factory=set)
    has_evolution_log: bool = False
    evolution_entries: int = 0
    raw_metadata: Dict[str, str] = field(default_factory=dict)
    is_claude_native: bool = False    # True if --- YAML frontmatter (Claude auto-memory)
    # v2.1 fields (all optional, graceful fallback)
    atom_type: str = "semantic"       # semantic/episodic/procedural
    created: Optional[date] = None
    ttl: Optional[str] = None         # e.g. "30d"
    expires_at: Optional[date] = None
    tags: List[str] = field(default_factory=list)
    related: List[str] = field(default_factory=list)
    supersedes: List[str] = field(default_factory=list)
    quality: Optional[float] = None


@dataclass
class IndexEntry:
    atom_name: str
    path: str
    trigger: str
    confidence: str = ""


@dataclass
class Issue:
    file: str
    level: str  # "error", "warning", "info"
    category: str
    message: str


@dataclass
class Suggestion:
    file: str
    current: str
    suggested: str
    reason: str


@dataclass
class DuplicatePair:
    file_a: str
    file_b: str
    shared_triggers: List[str]
    title_match: bool


@dataclass
class HealthReport:
    scan_date: date = field(default_factory=date.today)
    layers_scanned: List[str] = field(default_factory=list)
    total_atoms: int = 0
    confidence_counts: Dict[str, int] = field(default_factory=dict)
    issues: List[Issue] = field(default_factory=list)
    promotions: List[Suggestion] = field(default_factory=list)
    demotions: List[Suggestion] = field(default_factory=list)
    duplicates: List[DuplicatePair] = field(default_factory=list)
    distant_count: int = 0
    audit_stats: Dict[str, Any] = field(default_factory=dict)


# ─── Parsing ─────────────────────────────────────────────────────────────────

META_PATTERN = re.compile(r"^-\s+([\w-]+):\s*(.+)$")
SECTION_PATTERN = re.compile(r"^##\s+(.+)$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TABLE_ROW_PATTERN = re.compile(r"^\|(.+)\|$")
CONFIDENCE_EXTRACT = re.compile(r"\[(固|觀|臨)\]")


def parse_atom_file(path: Path, layer_name: str) -> AtomMetadata:
    """Parse a .md atom file into AtomMetadata.

    Supports two formats:
    1. Atom-style: `- Key: Value` metadata block (project standard)
    2. Claude-native: `---\\nname:...\\n---` YAML frontmatter (auto-memory system)
    """
    atom = AtomMetadata(file_path=path, layer_name=layer_name)
    try:
        text = path.read_text(encoding="utf-8-sig")  # handles BOM
    except (OSError, UnicodeDecodeError):
        return atom

    lines = text.splitlines()
    atom.line_count = len(lines)

    # Detect Claude-native YAML frontmatter — skip atom-style validation
    if lines and lines[0].strip() == "---":
        atom.is_claude_native = True
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                break
            m = re.match(r"^([\w-]+):\s*(.*)$", lines[i])
            if m:
                atom.raw_metadata[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        # Use 'name' as title, fall back to file stem
        atom.title = atom.raw_metadata.get("name", path.stem)
        return atom

    # Title (first # heading)
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            atom.title = line[2:].strip()
            break

    # Metadata block (lines starting with "- Key: Value")
    in_meta = False
    for line in lines:
        if line.startswith("- "):
            m = META_PATTERN.match(line)
            if m:
                key, val = m.group(1), m.group(2).strip()
                atom.raw_metadata[key] = val
                in_meta = True
        elif in_meta and line.strip() == "":
            break  # end of metadata block

    # Extract structured fields
    atom.scope = atom.raw_metadata.get("Scope", "")
    raw_conf = atom.raw_metadata.get("Confidence", "")
    cm = CONFIDENCE_EXTRACT.search(raw_conf)
    atom.confidence = f"[{cm.group(1)}]" if cm else raw_conf

    raw_trigger = atom.raw_metadata.get("Trigger", "")
    atom.trigger = [t.strip() for t in re.split(r"[,，]", raw_trigger) if t.strip()]

    raw_date = atom.raw_metadata.get("Last-used", "").strip()
    if DATE_PATTERN.match(raw_date):
        try:
            atom.last_used = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    raw_conf_count = atom.raw_metadata.get("Confirmations", "0")
    try:
        atom.confirmations = int(raw_conf_count)
    except ValueError:
        atom.confirmations = 0
    raw_rh_count = atom.raw_metadata.get("ReadHits", "0")
    try:
        atom.readhits = int(raw_rh_count)
    except ValueError:
        atom.readhits = 0

    atom.privacy = atom.raw_metadata.get("Privacy", "public")
    atom.source = atom.raw_metadata.get("Source", "")

    # v2.1 fields — graceful fallback to defaults
    atom.atom_type = atom.raw_metadata.get("Type", "semantic").strip().lower()
    if atom.atom_type not in VALID_TYPES:
        atom.atom_type = "semantic"

    raw_created = atom.raw_metadata.get("Created", "").strip()
    if DATE_PATTERN.match(raw_created):
        try:
            atom.created = datetime.strptime(raw_created, "%Y-%m-%d").date()
        except ValueError:
            pass

    atom.ttl = atom.raw_metadata.get("TTL", None)
    if atom.ttl:
        atom.ttl = atom.ttl.strip()

    raw_expires = atom.raw_metadata.get("Expires-at", "").strip()
    if DATE_PATTERN.match(raw_expires):
        try:
            atom.expires_at = datetime.strptime(raw_expires, "%Y-%m-%d").date()
        except ValueError:
            pass

    raw_tags = atom.raw_metadata.get("Tags", "")
    atom.tags = [t.strip() for t in re.split(r"[,，]", raw_tags) if t.strip()]

    raw_related = atom.raw_metadata.get("Related", "")
    atom.related = [r.strip() for r in re.split(r"[,，]", raw_related) if r.strip()]

    raw_supersedes = atom.raw_metadata.get("Supersedes", "")
    atom.supersedes = [s.strip() for s in re.split(r"[,，]", raw_supersedes) if s.strip()]

    raw_quality = atom.raw_metadata.get("Quality", "")
    if raw_quality:
        try:
            atom.quality = float(raw_quality)
        except ValueError:
            pass

    # Sections
    for line in lines:
        sm = SECTION_PATTERN.match(line)
        if sm:
            section_name = sm.group(1).strip()
            atom.sections_found.add(section_name)
            if "演化日誌" in section_name:
                atom.has_evolution_log = True

    # Count evolution log entries
    if atom.has_evolution_log:
        in_log = False
        for line in lines:
            if "演化日誌" in line:
                in_log = True
                continue
            if in_log and TABLE_ROW_PATTERN.match(line):
                cells = [c.strip() for c in line.split("|") if c.strip()]
                if len(cells) >= 2 and DATE_PATTERN.match(cells[0]):
                    atom.evolution_entries += 1

    return atom


def parse_memory_index(path: Path) -> Tuple[List[IndexEntry], int]:
    """Parse MEMORY.md index file. Returns (entries, line_count)."""
    entries: List[IndexEntry] = []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return entries, 0

    lines = text.splitlines()
    line_count = len(lines)

    # Find the table
    in_table = False
    header_seen = False
    for line in lines:
        stripped = line.strip()
        if not in_table:
            if stripped.startswith("| Atom") or stripped.startswith("|Atom"):
                in_table = True
                header_seen = True
                continue
        else:
            if stripped.startswith("|---") or stripped.startswith("| ---"):
                continue  # separator
            if not stripped.startswith("|"):
                break  # end of table
            cells = [c.strip() for c in stripped.split("|")]
            cells = [c for c in cells if c]  # remove empties from leading/trailing |
            if len(cells) >= 3:
                # Legacy 3-col format: | Atom | Path | Trigger | [Confidence]
                entry = IndexEntry(
                    atom_name=cells[0],
                    path=cells[1],
                    trigger=cells[2],
                    confidence=cells[3] if len(cells) >= 4 else "",
                )
                entries.append(entry)
            elif len(cells) == 2:
                # Compact 2-col format: | Atom | 說明 |
                # Path is inferred from atom name (supports wildcards like "feedback-*")
                name = cells[0]
                entry = IndexEntry(
                    atom_name=name,
                    path=f"{name}.md",
                    trigger="",
                    confidence="",
                )
                entries.append(entry)

    return entries, line_count


# ─── Validation ──────────────────────────────────────────────────────────────


def validate_format(atom: AtomMetadata) -> List[Issue]:
    """Validate atom file format compliance."""
    issues: List[Issue] = []
    rel = _rel_path(atom.file_path)

    # Claude-native YAML frontmatter has its own schema — skip atom-style validation
    if atom.is_claude_native:
        return issues

    # Title
    if not atom.title:
        issues.append(Issue(rel, "error", "format", "缺少 # 標題"))

    # Required metadata
    for key in REQUIRED_METADATA:
        if key not in atom.raw_metadata:
            issues.append(Issue(rel, "error", "format", f"缺少必要欄位: {key}"))

    # Confidence value
    if atom.confidence and atom.confidence not in VALID_CONFIDENCE:
        issues.append(
            Issue(rel, "error", "format", f"Confidence 值無效: {atom.confidence}（應為 [固]/[觀]/[臨]）")
        )

    # Last-used date
    if "Last-used" in atom.raw_metadata and atom.last_used is None:
        issues.append(
            Issue(rel, "warning", "format", f"Last-used 日期格式無效: {atom.raw_metadata['Last-used']}")
        )

    # Required sections
    for section in REQUIRED_SECTIONS:
        if section not in atom.sections_found:
            issues.append(Issue(rel, "warning", "format", f"缺少建議區段: ## {section}"))
    # 知識 / 印象 二選一（指標型 atom 用 ## 印象 取代 ## 知識）
    if not (atom.sections_found & KNOWLEDGE_SECTIONS):
        issues.append(Issue(rel, "warning", "format", "缺少建議區段: ## 知識 或 ## 印象"))

    # Line count
    if atom.line_count > ATOM_MAX_LINES:
        issues.append(
            Issue(rel, "warning", "size", f"Atom 超過 {ATOM_MAX_LINES} 行（目前 {atom.line_count} 行）")
        )

    # Trigger count
    trigger_count = len(atom.trigger)
    if trigger_count > 0 and (trigger_count < TRIGGER_MIN or trigger_count > TRIGGER_MAX):
        issues.append(
            Issue(rel, "info", "trigger", f"Trigger 數量 {trigger_count}（建議 {TRIGGER_MIN}~{TRIGGER_MAX}）")
        )

    return issues


def check_staleness(atom: AtomMetadata, today: date) -> Optional[Suggestion]:
    """Check if atom is stale based on Last-used date and atom type."""
    if not atom.last_used or not atom.confidence:
        return None

    base_threshold = STALENESS_THRESHOLDS.get(atom.confidence)
    if base_threshold is None:
        return None
    type_mult = TYPE_DECAY_MULTIPLIER.get(atom.atom_type, 1.0)
    threshold = int(base_threshold * type_mult)

    days = (today - atom.last_used).days
    if days <= threshold:
        return None

    rel = _rel_path(atom.file_path)
    type_note = f", type={atom.atom_type}" if atom.atom_type != "semantic" else ""
    if atom.confidence == "[臨]":
        return Suggestion(rel, atom.confidence, "遙遠記憶", f"Last-used {days} 天前（閾值 {threshold}天{type_note}）")
    elif atom.confidence == "[觀]":
        return Suggestion(rel, atom.confidence, "確認或遙遠記憶", f"Last-used {days} 天前（閾值 {threshold}天{type_note}）")
    else:  # [固]
        return Suggestion(rel, atom.confidence, "建議人工檢視", f"Last-used {days} 天前（閾值 {threshold}天）")


def suggest_promotions(atom: AtomMetadata) -> Optional[Suggestion]:
    """Suggest promotion based on dual-track thresholds (v3)."""
    thresholds = PROMOTION_THRESHOLDS.get(atom.confidence)
    if thresholds is None:
        return None

    conf_ok = atom.confirmations >= thresholds["confirmations"]
    rh_ok = getattr(atom, "readhits", 0) >= thresholds["readhits"]
    if not conf_ok and not rh_ok:
        return None

    method = "Conf" if conf_ok else "ReadHits"
    val = atom.confirmations if conf_ok else getattr(atom, "readhits", 0)
    req = thresholds["confirmations"] if conf_ok else thresholds["readhits"]
    rel = _rel_path(atom.file_path)
    if atom.confidence == "[臨]":
        return Suggestion(
            rel, "[臨]", "[觀]", f"{method}={val}（閾值 {req}）"
        )
    elif atom.confidence == "[觀]":
        return Suggestion(
            rel, "[觀]", "[固]", f"{method}={val}（閾值 {req}）"
        )
    return None


def validate_index(index_path: Path, memory_dir: Path, index_entries: List[IndexEntry]) -> List[Issue]:
    """Cross-reference index entries with actual files."""
    issues: List[Issue] = []
    rel_index = _rel_path(index_path)

    # Get actual atom files (exclude MEMORY.md, SPEC_*, _distant/)
    actual_files: Set[str] = set()
    for f in memory_dir.iterdir():
        if f.is_file() and f.suffix == ".md" and f.name != MEMORY_INDEX:
            if not any(f.name.startswith(p) for p in SKIP_PREFIXES):
                actual_files.add(f.name)

    # Check index → file
    indexed_files: Set[str] = set()
    for entry in index_entries:
        entry_path = Path(entry.path)
        file_name = entry_path.name

        # Wildcard entries (e.g. "feedback-*.md") — expand against actual files
        if "*" in file_name:
            prefix = file_name.split("*")[0].rstrip("-_.")
            matched_any = False
            for fname in actual_files:
                stem = fname[:-3] if fname.endswith(".md") else fname  # strip .md
                if stem == prefix or stem.startswith(f"{prefix}_") or stem.startswith(f"{prefix}-"):
                    indexed_files.add(fname)
                    matched_any = True
            if not matched_any:
                issues.append(
                    Issue(rel_index, "warning", "index", f"索引 wildcard '{entry.atom_name}' 無匹配檔案")
                )
            continue

        indexed_files.add(file_name)

        full_path = memory_dir / file_name
        if not full_path.exists():
            # Try relative to parent of memory_dir
            alt_path = memory_dir.parent / entry.path
            if not alt_path.exists():
                issues.append(
                    Issue(rel_index, "error", "index", f"索引指向不存在的檔案: {entry.path}")
                )

    # Check file → index
    for fname in actual_files:
        if fname not in indexed_files:
            issues.append(
                Issue(rel_index, "warning", "index", f"檔案 {fname} 未在索引中列出")
            )

    return issues


def detect_duplicates(all_atoms: List[AtomMetadata]) -> List[DuplicatePair]:
    """Detect potential duplicate atoms across layers."""
    pairs: List[DuplicatePair] = []

    for i in range(len(all_atoms)):
        for j in range(i + 1, len(all_atoms)):
            a, b = all_atoms[i], all_atoms[j]
            # Same layer skip
            if a.file_path.parent == b.file_path.parent:
                continue

            # Title match
            title_match = (
                a.title and b.title and _normalize(a.title) == _normalize(b.title)
            )

            # Trigger overlap
            set_a = {t.lower() for t in a.trigger}
            set_b = {t.lower() for t in b.trigger}
            shared = set_a & set_b

            if title_match or len(shared) >= 3:
                pairs.append(
                    DuplicatePair(
                        _rel_path(a.file_path),
                        _rel_path(b.file_path),
                        sorted(shared),
                        title_match,
                    )
                )

    return pairs


# ─── Distant Memory Operations ───────────────────────────────────────────────


def search_distant(memory_dir: Path, keyword: str) -> List[Tuple[Path, str]]:
    """Search _distant/ subdirectories for atoms matching keyword."""
    results: List[Tuple[Path, str]] = []
    distant_dir = memory_dir / DISTANT_DIR

    if not distant_dir.exists():
        return results

    kw_lower = keyword.lower()
    for year_month_dir in sorted(distant_dir.iterdir()):
        if not year_month_dir.is_dir():
            continue
        for md_file in sorted(year_month_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            if kw_lower in text.lower() or kw_lower in md_file.stem.lower():
                # Extract title
                title = ""
                for line in text.splitlines():
                    if line.startswith("# ") and not line.startswith("## "):
                        title = line[2:].strip()
                        break
                results.append((md_file, title or md_file.stem))

    return results


def restore_from_distant(atom_path: Path) -> Tuple[bool, str]:
    """Move atom from _distant/ back to active area, reset Confidence to [臨]."""
    if not atom_path.exists():
        return False, f"檔案不存在: {atom_path}"

    # Find the memory/ dir (go up until we leave _distant)
    parts = atom_path.parts
    distant_idx = None
    for i, p in enumerate(parts):
        if p == DISTANT_DIR:
            distant_idx = i
            break

    if distant_idx is None:
        return False, f"路徑不在 _distant/ 下: {atom_path}"

    memory_dir = Path(*parts[:distant_idx])
    dest = memory_dir / atom_path.name

    if dest.exists():
        return False, f"活躍區已有同名檔案: {dest}"

    # Read, reset Confidence, write to dest
    try:
        text = atom_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        return False, f"讀取失敗: {e}"

    # Reset confidence to [臨]
    text = re.sub(
        r"^(-\s+Confidence:\s*).*$",
        r"\g<1>[臨]",
        text,
        count=1,
        flags=re.MULTILINE,
    )

    # Update Last-used to today
    today_str = date.today().isoformat()
    text = re.sub(
        r"^(-\s+Last-used:\s*).*$",
        rf"\g<1>{today_str}",
        text,
        count=1,
        flags=re.MULTILINE,
    )

    # Reset confirmations + readhits
    text = re.sub(
        r"^(-\s+Confirmations:\s*).*$",
        r"\g<1>0",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^(-\s+ReadHits:\s*).*$",
        r"\g<1>0",
        text,
        count=1,
        flags=re.MULTILINE,
    )

    try:
        dest.write_text(text, encoding="utf-8")
        atom_path.unlink()
        # Clean up empty year_month dir
        parent = atom_path.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
        return True, f"已拉回: {dest}（Confidence 重置為 [臨]）"
    except OSError as e:
        return False, f"寫入失敗: {e}"


def _append_evolution_entry(atom_path: Path, change: str, source: str = "memory-audit --enforce") -> None:
    """Append an entry to the atom's evolution log."""
    try:
        text = atom_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return
    today_str = date.today().isoformat()
    entry_line = f"| {today_str} | {change} | {source} |"

    if "## 演化日誌" in text:
        # Find the last table row and append after it
        lines = text.splitlines()
        insert_idx = None
        in_log = False
        for i, line in enumerate(lines):
            if "演化日誌" in line:
                in_log = True
                continue
            if in_log:
                if TABLE_ROW_PATTERN.match(line.strip()):
                    insert_idx = i
                elif line.strip().startswith("##"):
                    break
        if insert_idx is not None:
            lines.insert(insert_idx + 1, entry_line)
        else:
            # Table header exists but no data rows; append after separator
            for i, line in enumerate(lines):
                if "演化日誌" in line:
                    # Find separator
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if lines[j].strip().startswith("|---"):
                            lines.insert(j + 1, entry_line)
                            break
                    break
        atom_path.write_text("\n".join(lines), encoding="utf-8")
    else:
        # No evolution log section; append one
        text += f"\n\n## 演化日誌\n\n| 日期 | 變更 | 來源 |\n|------|------|------|\n{entry_line}\n"
        atom_path.write_text(text, encoding="utf-8")


def compact_evolution_logs(
    atom_path: Path, max_entries: int = 10, dry_run: bool = False
) -> Optional[str]:
    """Compact evolution log: merge oldest entries into a summary if > max_entries (v2.1 Sprint 3)."""
    try:
        text = atom_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None

    if "## 演化日誌" not in text:
        return None

    lines = text.splitlines()
    # Find data rows in evolution log table
    in_log = False
    log_end = len(lines)
    entries: List[Tuple[int, str]] = []  # (line_index, date_str)

    for i, line in enumerate(lines):
        if "演化日誌" in line:
            in_log = True
            continue
        if in_log:
            if line.strip().startswith("##"):
                log_end = i
                break
            stripped = line.strip()
            if TABLE_ROW_PATTERN.match(stripped):
                cells = [c.strip() for c in stripped.split("|") if c.strip()]
                if len(cells) >= 2 and DATE_PATTERN.match(cells[0]):
                    entries.append((i, cells[0]))
                elif len(cells) >= 2 and cells[0].startswith("[合併]"):
                    entries.append((i, cells[0]))  # already-merged line

    if len(entries) <= max_entries:
        return None

    # Merge oldest entries, keep newest (max_entries - 1)
    merge_count = len(entries) - (max_entries - 1)
    to_merge = entries[:merge_count]

    # Extract date range from merge targets
    dates = [d for _, d in to_merge if DATE_PATTERN.match(d)]
    earliest = dates[0] if dates else to_merge[0][1]
    latest = dates[-1] if dates else to_merge[-1][1]
    summary_line = f"| [合併] | {merge_count} 筆歷史記錄 ({earliest}~{latest}) | auto-compact |"

    rel = _rel_path(atom_path)
    if dry_run:
        return f"[DRY-RUN] Would compact {rel}: merge {merge_count} entries ({earliest}~{latest})"

    merged_indices = {idx for idx, _ in to_merge}
    new_lines = []
    summary_inserted = False
    for i, line in enumerate(lines):
        if i in merged_indices:
            if not summary_inserted:
                new_lines.append(summary_line)
                summary_inserted = True
        else:
            new_lines.append(line)

    atom_path.write_text("\n".join(new_lines), encoding="utf-8")
    return f"COMPACTED: {rel} — merged {merge_count} entries ({earliest}~{latest})"


def delete_atom(
    atom_name: str, layer: str = "global", purge: bool = False, dry_run: bool = False
) -> Tuple[bool, str]:
    """Delete an atom with full chain propagation (v2.1 Sprint 2).

    Steps:
    1. Locate atom file
    2. LanceDB: delete all chunks for this atom
    3. Scan Related references in other atoms → remove
    4. Update MEMORY.md index → remove row
    5. Move to _distant/ (or permanent delete if purge)
    6. Trigger incremental re-index
    7. Write audit.log
    """
    import urllib.request
    import urllib.error

    # 1. Locate atom file
    layers = discover_layers()
    atom_path = None
    mem_dir = None
    for layer_name, mdir in layers:
        if layer_name == layer:
            candidate = mdir / f"{atom_name}.md"
            if candidate.exists():
                atom_path = candidate
                mem_dir = mdir
                break

    if atom_path is None:
        return False, f"Atom '{atom_name}' not found in layer '{layer}'"

    actions = []
    mode = "PURGE" if purge else "DELETE"

    if dry_run:
        actions.append(f"[DRY-RUN] Would {mode.lower()} atom: {atom_name} (layer: {layer})")
    else:
        actions.append(f"[{mode}] Processing atom: {atom_name} (layer: {layer})")

    # 2. LanceDB cleanup
    try:
        VECTORDB_DIR = CLAUDE_DIR / "memory" / "_vectordb"
        if VECTORDB_DIR.exists():
            import lancedb
            db = lancedb.connect(str(VECTORDB_DIR))
            try:
                table = db.open_table("atom_chunks")
                if dry_run:
                    # Count rows that would be deleted
                    rows = table.search().select(["atom_name", "layer"]).limit(10000).to_list()
                    count = sum(1 for r in rows if r.get("atom_name") == atom_name and r.get("layer") == layer)
                    actions.append(f"  [DRY-RUN] Would delete {count} LanceDB chunks")
                else:
                    table.delete(f"atom_name = '{atom_name}' AND layer = '{layer}'")
                    actions.append("  LanceDB chunks deleted")
            except Exception as e:
                actions.append(f"  LanceDB: {e}")
    except ImportError:
        actions.append("  LanceDB: not installed (skipped)")

    # 3. Scan Related references in other atoms → remove
    related_cleaned = 0
    for layer_name, mdir in layers:
        for md_file in sorted(mdir.glob("*.md")):
            if md_file.name == MEMORY_INDEX or md_file == atom_path:
                continue
            if any(md_file.name.startswith(p) for p in SKIP_PREFIXES):
                continue
            try:
                text = md_file.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            changed = False
            new_lines = []
            for line in text.splitlines():
                if line.strip().startswith("- Related:"):
                    m = re.match(r"^(- Related:\s*)(.+)$", line)
                    if m:
                        related_list = [r.strip() for r in m.group(2).split(",")]
                        filtered = [r for r in related_list if r and r != atom_name]
                        if len(filtered) != len(related_list):
                            changed = True
                            related_cleaned += 1
                            if filtered:
                                new_lines.append(f"- Related: {', '.join(filtered)}")
                            # else: remove the line entirely
                            continue
                if line.strip().startswith("- Supersedes:"):
                    m = re.match(r"^(- Supersedes:\s*)(.+)$", line)
                    if m:
                        sup_list = [s.strip() for s in m.group(2).split(",")]
                        if atom_name in sup_list:
                            actions.append(f"  WARNING: {md_file.stem} supersedes deleted atom {atom_name}")
                new_lines.append(line)
            if changed and not dry_run:
                md_file.write_text("\n".join(new_lines), encoding="utf-8")
    if related_cleaned:
        actions.append(f"  Related references cleaned: {related_cleaned} atom(s)")

    # 4. Update MEMORY.md index
    if mem_dir:
        index_path = mem_dir / "MEMORY.md"
        if index_path.exists():
            try:
                idx_text = index_path.read_text(encoding="utf-8-sig")
                new_idx_lines = []
                removed = False
                for line in idx_text.splitlines():
                    # Match table row containing atom name
                    if line.strip().startswith("|") and f"| {atom_name} " in line:
                        removed = True
                        continue
                    new_idx_lines.append(line)
                if removed:
                    if dry_run:
                        actions.append("  [DRY-RUN] Would remove MEMORY.md index row")
                    else:
                        index_path.write_text("\n".join(new_idx_lines), encoding="utf-8")
                        actions.append("  MEMORY.md index row removed")
            except (OSError, UnicodeDecodeError) as e:
                actions.append(f"  MEMORY.md update failed: {e}")

    # 5. Move/remove file
    if not dry_run:
        _append_evolution_entry(atom_path, f"{'永久刪除' if purge else '刪除移入 _distant/'}", "memory-audit --delete")
        if purge:
            try:
                os.remove(str(atom_path))
                actions.append(f"  File permanently deleted: {atom_path.name}")
            except OSError as e:
                actions.append(f"  File delete failed: {e}")
                return False, "\n".join(actions)
        else:
            ok, msg = move_to_distant(atom_path)
            actions.append(f"  {msg}")
            if not ok:
                return False, "\n".join(actions)

    # 6. Trigger incremental re-index
    if not dry_run:
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:3849/index/incremental",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
            actions.append("  Incremental re-index triggered")
        except Exception:
            actions.append("  Incremental re-index: service not available (skipped)")

    # 7. Audit log
    if not dry_run:
        _write_audit_entry({
            "action": "purge" if purge else "delete",
            "atom": atom_name,
            "layer": layer,
        })
        actions.append("  Audit log entry written")

    return True, "\n".join(actions)


def _project_dir_from_args(args: argparse.Namespace) -> Optional[Path]:
    """Helper: extract project_dir from parsed args."""
    val = getattr(args, "project_dir", None)
    return Path(val) if val else None


def enforce_decay(args: argparse.Namespace) -> None:
    """Execute automated decay: move stale [臨] to _distant/, mark stale [觀] as pending-review."""
    today = date.today()
    dry_run = args.dry_run
    layers = discover_layers(global_only=args.global_only, project_filter=args.project,
                             project_dir=_project_dir_from_args(args))
    actions: List[str] = []

    for layer_name, mem_dir in layers:
        for md_file in sorted(mem_dir.glob("*.md")):
            if md_file.name == MEMORY_INDEX:
                continue
            if any(md_file.name.startswith(p) for p in SKIP_PREFIXES):
                continue

            atom = parse_atom_file(md_file, layer_name)
            if not atom.last_used or not atom.confidence:
                continue

            days = (today - atom.last_used).days
            base_threshold = STALENESS_THRESHOLDS.get(atom.confidence)
            if base_threshold is None:
                continue
            type_mult = TYPE_DECAY_MULTIPLIER.get(atom.atom_type, 1.0)
            threshold = int(base_threshold * type_mult)
            if days <= threshold:
                continue

            rel = _rel_path(atom.file_path)

            if atom.confidence == "[臨]":
                if dry_run:
                    actions.append(f"[DRY-RUN] Would move {rel} to _distant/ ({days}d > {threshold}d)")
                else:
                    _append_evolution_entry(md_file, f"--enforce 自動淘汰 ({days}d > {threshold}d)")
                    compact_evolution_logs(md_file)
                    ok, msg = move_to_distant(md_file)
                    actions.append(f"{'OK' if ok else 'FAIL'}: {msg}")
                    _write_audit_entry({"action": "decay", "atom": md_file.stem,
                                        "layer": layer_name, "confidence": atom.confidence,
                                        "days_stale": days, "type": atom.atom_type})

            elif atom.confidence == "[觀]":
                if dry_run:
                    actions.append(f"[DRY-RUN] Would mark {rel} as pending-review ({days}d > {threshold}d)")
                else:
                    # Add pending-review tag
                    try:
                        text = md_file.read_text(encoding="utf-8-sig")
                        if "pending-review" not in text:
                            # Add Tags line or update existing
                            if "- Tags:" in text:
                                text = re.sub(
                                    r"^(- Tags:\s*)(.+)$",
                                    r"\1\2, pending-review",
                                    text, count=1, flags=re.MULTILINE,
                                )
                            else:
                                # Insert after Last-used line
                                text = re.sub(
                                    r"^(- Last-used:\s*.+)$",
                                    r"\1\n- Tags: pending-review",
                                    text, count=1, flags=re.MULTILINE,
                                )
                            md_file.write_text(text, encoding="utf-8")
                            _append_evolution_entry(md_file, f"標記 pending-review ({days}d > {threshold}d)")
                            compact_evolution_logs(md_file)
                            actions.append(f"MARKED: {rel} → pending-review")
                            _write_audit_entry({"action": "decay", "atom": md_file.stem,
                                                "layer": layer_name, "confidence": atom.confidence,
                                                "days_stale": days, "type": atom.atom_type,
                                                "sub_action": "pending-review"})
                    except (OSError, UnicodeDecodeError) as e:
                        actions.append(f"FAIL: {rel} — {e}")

    if actions:
        print("\n".join(actions))
    else:
        print("No stale atoms found requiring action.")


def move_to_distant(atom_path: Path) -> Tuple[bool, str]:
    """Move an active atom to _distant/{year}_{month}/."""
    if not atom_path.exists():
        return False, f"檔案不存在: {atom_path}"

    memory_dir = atom_path.parent
    today = date.today()
    year_month = f"{today.year}_{today.month:02d}"
    distant_target = memory_dir / DISTANT_DIR / year_month

    distant_target.mkdir(parents=True, exist_ok=True)
    dest = distant_target / atom_path.name

    if dest.exists():
        return False, f"遙遠記憶已有同名檔案: {dest}"

    try:
        shutil.move(str(atom_path), str(dest))
        return True, f"已移入遙遠記憶: {dest}"
    except OSError as e:
        return False, f"移動失敗: {e}"


# ─── Layer Discovery ─────────────────────────────────────────────────────────

CLAUDE_DIR = Path.home() / ".claude"
AUDIT_LOG_PATH = CLAUDE_DIR / "memory" / "_vectordb" / "audit.log"


def _write_audit_entry(entry: Dict[str, Any]) -> None:
    """Append a JSONL entry to audit.log (v2.1 Sprint 3)."""
    entry["ts"] = datetime.now().isoformat(timespec="seconds")
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def parse_audit_log() -> Dict[str, Any]:
    """Parse audit.log JSONL and aggregate statistics (v2.1 Sprint 3)."""
    stats: Dict[str, Any] = {
        "total_entries": 0,
        "by_action": {},
        "conflicts": 0,
        "deletes": 0,
        "purges": 0,
        "adds": 0,
        "skips": 0,
        "decays": 0,
    }
    if not AUDIT_LOG_PATH.exists():
        return stats

    try:
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                action = entry.get("action", "unknown")
                stats["total_entries"] += 1
                stats["by_action"][action] = stats["by_action"].get(action, 0) + 1
                if "conflict" in action:
                    stats["conflicts"] += 1
                elif action == "delete":
                    stats["deletes"] += 1
                elif action == "purge":
                    stats["purges"] += 1
                elif action == "add":
                    stats["adds"] += 1
                elif action == "skip":
                    stats["skips"] += 1
                elif action in ("decay", "enforce"):
                    stats["decays"] += 1
    except OSError:
        pass

    return stats


def discover_layers(
    global_only: bool = False,
    project_filter: Optional[str] = None,
    project_dir: Optional[Path] = None,
) -> List[Tuple[str, Path]]:
    """Discover all memory layers.

    V2.21: project_dir 若提供，優先列在 global 之前（專案層優先）。
    """
    layers: List[Tuple[str, Path]] = []

    # V2.21: 專案自治層（{project_root}/.claude/memory/）
    # global_only=True 時跳過專案層
    if not global_only and project_dir and project_dir.is_dir() and (project_dir / MEMORY_INDEX).exists():
        layers.append(("project", project_dir))

    # Global layer
    global_mem = CLAUDE_DIR / "memory"
    if global_mem.is_dir():
        layers.append(("global", global_mem))

    if global_only:
        return layers

    # Legacy project layers（~/.claude/projects/{slug}/memory/）
    projects_dir = CLAUDE_DIR / "projects"
    if projects_dir.is_dir():
        for proj_dir in sorted(projects_dir.iterdir()):
            if not proj_dir.is_dir():
                continue

            if project_filter and project_filter not in proj_dir.name:
                continue

            mem_dir = proj_dir / "memory"
            if mem_dir.is_dir():
                layers.append((proj_dir.name, mem_dir))

    return layers


# ─── Report Generation ───────────────────────────────────────────────────────


def generate_markdown_report(report: HealthReport) -> str:
    """Generate a Markdown health report."""
    lines: List[str] = []
    lines.append("# Atomic Memory Health Report")
    lines.append(f"> Generated: {report.scan_date.isoformat()}")
    lines.append("")

    # Summary
    errors = sum(1 for i in report.issues if i.level == "error")
    warnings = sum(1 for i in report.issues if i.level == "warning")
    conf_str = " | ".join(f"{k}: {v}" for k, v in sorted(report.confidence_counts.items()))

    lines.append("## Summary")
    lines.append(f"- Layers: {len(report.layers_scanned)} ({', '.join(report.layers_scanned)})")
    lines.append(f"- Active atoms: {report.total_atoms} | Distant: {report.distant_count}")
    lines.append(f"- {conf_str}" if conf_str else "- (no atoms)")
    lines.append(f"- Errors: {errors} | Warnings: {warnings}")
    lines.append(f"- Promotion candidates: {len(report.promotions)} | Demotion candidates: {len(report.demotions)}")
    if report.duplicates:
        lines.append(f"- Duplicate suspects: {len(report.duplicates)}")
    lines.append("")

    # Issues
    if report.issues:
        lines.append("## Issues")
        lines.append("")
        lines.append("| Level | File | Category | Message |")
        lines.append("|-------|------|----------|---------|")
        for i in report.issues:
            lines.append(f"| {i.level} | {i.file} | {i.category} | {i.message} |")
        lines.append("")

    # Staleness / Demotions
    if report.demotions:
        lines.append("## Staleness / Demotion Suggestions")
        lines.append("")
        lines.append("| File | Current | Suggested | Reason |")
        lines.append("|------|---------|-----------|--------|")
        for s in report.demotions:
            lines.append(f"| {s.file} | {s.current} | {s.suggested} | {s.reason} |")
        lines.append("")

    # Promotions
    if report.promotions:
        lines.append("## Promotion Suggestions")
        lines.append("")
        lines.append("| File | Current → Suggested | Reason |")
        lines.append("|------|---------------------|--------|")
        for s in report.promotions:
            lines.append(f"| {s.file} | {s.current}→{s.suggested} | {s.reason} |")
        lines.append("")

    # Duplicates
    if report.duplicates:
        lines.append("## Duplicate Suspects")
        lines.append("")
        lines.append("| File A | File B | Shared Triggers | Title Match |")
        lines.append("|--------|--------|-----------------|-------------|")
        for d in report.duplicates:
            triggers = ", ".join(d.shared_triggers[:5])
            lines.append(f"| {d.file_a} | {d.file_b} | {triggers} | {'Yes' if d.title_match else 'No'} |")
        lines.append("")

    # Audit Trail Summary (v2.1 Sprint 3)
    if report.audit_stats and report.audit_stats.get("total_entries", 0) > 0:
        stats = report.audit_stats
        lines.append("## Audit Trail Summary")
        lines.append("")
        lines.append(f"- Total log entries: {stats['total_entries']}")
        lines.append(f"- Write Gate adds: {stats.get('adds', 0)} | skips: {stats.get('skips', 0)}")
        lines.append(f"- Deletes: {stats.get('deletes', 0)} | Purges: {stats.get('purges', 0)}")
        lines.append(f"- Conflicts detected: {stats.get('conflicts', 0)}")
        lines.append(f"- Decay actions: {stats.get('decays', 0)}")
        lines.append("")

    return "\n".join(lines)


def generate_json_report(report: HealthReport) -> str:
    """Generate a JSON health report."""
    data = {
        "scan_date": report.scan_date.isoformat(),
        "layers": report.layers_scanned,
        "total_atoms": report.total_atoms,
        "distant_count": report.distant_count,
        "confidence_counts": report.confidence_counts,
        "issues": [
            {"file": i.file, "level": i.level, "category": i.category, "message": i.message}
            for i in report.issues
        ],
        "promotions": [
            {"file": s.file, "current": s.current, "suggested": s.suggested, "reason": s.reason}
            for s in report.promotions
        ],
        "demotions": [
            {"file": s.file, "current": s.current, "suggested": s.suggested, "reason": s.reason}
            for s in report.demotions
        ],
        "duplicates": [
            {
                "file_a": d.file_a,
                "file_b": d.file_b,
                "shared_triggers": d.shared_triggers,
                "title_match": d.title_match,
            }
            for d in report.duplicates
        ],
        "audit_stats": report.audit_stats,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _rel_path(p: Path) -> str:
    """Return a short relative path for display."""
    try:
        return str(p.relative_to(CLAUDE_DIR))
    except ValueError:
        return str(p)


def _normalize(s: str) -> str:
    """Normalize string for comparison."""
    return re.sub(r"\s+", " ", s.strip().lower())


def _count_distant(memory_dir: Path) -> int:
    """Count atoms in _distant/."""
    distant_dir = memory_dir / DISTANT_DIR
    if not distant_dir.exists():
        return 0
    count = 0
    for ym_dir in distant_dir.iterdir():
        if ym_dir.is_dir():
            count += sum(1 for f in ym_dir.glob("*.md"))
    return count


# ─── Main ────────────────────────────────────────────────────────────────────


def run_audit(args: argparse.Namespace) -> HealthReport:
    """Run the full audit and return a HealthReport."""
    today = date.today()
    report = HealthReport(scan_date=today)

    layers = discover_layers(
        global_only=args.global_only,
        project_filter=args.project,
        project_dir=Path(args.project_dir) if getattr(args, "project_dir", None) else None,
    )

    all_atoms: List[AtomMetadata] = []

    for layer_name, mem_dir in layers:
        report.layers_scanned.append(layer_name)
        report.distant_count += _count_distant(mem_dir)

        # Parse index
        index_path = mem_dir / MEMORY_INDEX
        if index_path.exists():
            index_entries, idx_lines = parse_memory_index(index_path)

            # Check index line count
            if idx_lines > INDEX_MAX_LINES:
                report.issues.append(
                    Issue(
                        _rel_path(index_path),
                        "warning",
                        "size",
                        f"MEMORY.md {idx_lines} 行（上限 {INDEX_MAX_LINES}）",
                    )
                )

            # Validate index ↔ files
            report.issues.extend(validate_index(index_path, mem_dir, index_entries))
        else:
            # Skip "missing MEMORY.md" error if directory has no atom files at root
            # (orphan/empty memory dir from deleted project — harmless)
            has_atoms = any(
                f.is_file() and f.suffix == ".md"
                and f.name != MEMORY_INDEX
                and not any(f.name.startswith(p) for p in SKIP_PREFIXES)
                for f in mem_dir.iterdir()
            )
            if has_atoms:
                report.issues.append(
                    Issue(str(mem_dir), "error", "index", "缺少 MEMORY.md 索引檔")
                )

        # Parse all atom files
        for md_file in sorted(mem_dir.glob("*.md")):
            if md_file.name == MEMORY_INDEX:
                continue
            if any(md_file.name.startswith(p) for p in SKIP_PREFIXES):
                continue

            atom = parse_atom_file(md_file, layer_name)
            all_atoms.append(atom)
            report.total_atoms += 1

            # Count confidence
            if atom.confidence in VALID_CONFIDENCE:
                report.confidence_counts[atom.confidence] = (
                    report.confidence_counts.get(atom.confidence, 0) + 1
                )

            # Validate format
            report.issues.extend(validate_format(atom))

            # Check staleness
            stale = check_staleness(atom, today)
            if stale:
                report.demotions.append(stale)

            # Check promotions
            promo = suggest_promotions(atom)
            if promo:
                report.promotions.append(promo)

    # Detect cross-layer duplicates
    report.duplicates.extend(detect_duplicates(all_atoms))

    # Audit trail statistics (v2.1 Sprint 3)
    report.audit_stats = parse_audit_log()

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Atomic Memory System Health Checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Scan options
    parser.add_argument("--global-only", action="store_true", help="只掃描全域層")
    parser.add_argument("--project", type=str, default=None, help="指定專案名稱過濾（舊路徑過濾）")
    parser.add_argument("--project-dir", type=str, default=None,
                        help="V2.21 專案記憶目錄（{project_root}/.claude/memory/），列在全域層之前")
    parser.add_argument("--json", action="store_true", help="JSON 格式輸出")
    parser.add_argument("--verbose", action="store_true", help="含逐 atom 詳細資訊")

    # Decay enforce (v2.1)
    parser.add_argument("--enforce", action="store_true",
                        help="自動淘汰：[臨]>30d 移入 _distant/，[觀]>60d 標記 pending-review")
    parser.add_argument("--dry-run", action="store_true",
                        help="搭配 --enforce/--compact-logs，只報告不執行")

    # Evolution log compaction (v2.1 Sprint 3)
    parser.add_argument("--compact-logs", action="store_true",
                        help="壓縮演化日誌：超過 10 筆合併為摘要")

    # Delete propagation (v2.1 Sprint 2)
    parser.add_argument("--delete", type=str, metavar="ATOM_NAME",
                        help="刪除 atom（移入 _distant/），全鏈清除 LanceDB + Related 引用 + MEMORY.md 索引")
    parser.add_argument("--purge", type=str, metavar="ATOM_NAME",
                        help="永久刪除 atom（不移入 _distant/），全鏈清除")
    parser.add_argument("--layer", type=str, default="global",
                        help="搭配 --delete/--purge 指定層（default: global）")

    # Distant memory operations
    parser.add_argument("--search-distant", type=str, metavar="KEYWORD", help="搜尋遙遠記憶區")
    parser.add_argument("--restore", type=str, metavar="PATH", help="從遙遠記憶拉回活躍區")
    parser.add_argument("--move-distant", type=str, metavar="PATH", help="手動移入遙遠記憶")

    args = parser.parse_args()

    # Handle delete/purge (v2.1 Sprint 2)
    if args.delete or args.purge:
        atom_name = args.delete or args.purge
        purge = bool(args.purge)
        ok, msg = delete_atom(atom_name, args.layer, purge=purge, dry_run=args.dry_run)
        print(msg)
        sys.exit(0 if ok else 1)

    # Handle distant memory operations
    if args.search_distant:
        keyword = args.search_distant
        layers = discover_layers(global_only=args.global_only, project_filter=args.project,
                                 project_dir=_project_dir_from_args(args))
        found_any = False
        for layer_name, mem_dir in layers:
            results = search_distant(mem_dir, keyword)
            if results:
                found_any = True
                print(f"\n[{layer_name}] _distant/ 搜尋結果:")
                for path, title in results:
                    print(f"  {title}")
                    print(f"    路徑: {path}")
        if not found_any:
            print(f"遙遠記憶中找不到包含 '{keyword}' 的 atom。")
        return

    if args.restore:
        path = Path(args.restore)
        ok, msg = restore_from_distant(path)
        print(msg)
        sys.exit(0 if ok else 1)

    if args.move_distant:
        path = Path(args.move_distant)
        ok, msg = move_to_distant(path)
        print(msg)
        sys.exit(0 if ok else 1)

    # Enforce decay (v2.1)
    if args.enforce:
        enforce_decay(args)
        return

    # Compact evolution logs (v2.1 Sprint 3)
    if args.compact_logs:
        layers = discover_layers(global_only=args.global_only, project_filter=args.project,
                                 project_dir=_project_dir_from_args(args))
        actions: List[str] = []
        for layer_name, mem_dir in layers:
            for md_file in sorted(mem_dir.glob("*.md")):
                if md_file.name == MEMORY_INDEX or any(md_file.name.startswith(p) for p in SKIP_PREFIXES):
                    continue
                result = compact_evolution_logs(md_file, dry_run=args.dry_run)
                if result:
                    actions.append(result)
        if actions:
            print("\n".join(actions))
        else:
            print("No evolution logs require compaction.")
        return

    # Run audit
    report = run_audit(args)

    if args.json:
        print(generate_json_report(report))
    else:
        print(generate_markdown_report(report))

    # Exit code: 1 if any errors
    has_errors = any(i.level == "error" for i in report.issues)
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
