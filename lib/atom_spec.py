"""atom_spec.py — 全系統「什麼是合法 atom」的唯一規則來源 (S1.2)

純資料 + 純函式，零 IO（除 resolve_scope_dir 需訪問 fs 標記）。
被 memory-audit / atom-health-check / atom_io 共用 import，避免規則漂移。

行為等價對拍 server.js: slugify / buildAtomContent / validateAtomContent / resolveMemDir
（V4 SPEC §4 metadata 順序、§8 scope dir 結構）。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


# ─── Constants（單一規則來源） ───────────────────────────────────────────────

# 子目錄跳過清單（rglob 掃描時用）
# - feedback/: 行為 atom，必掃
# - personal/: V4 user role 宣告檔（role.md），非 atom
# - wisdom/: Wisdom Engine 設計文件（DESIGN.md），非 atom（用設計文件章節）
# - episodic/: auto-generated session 摘要，使用 ## 摘要 章節，與 atom 格式不同
# - _pending_review/: shared 敏感原子待裁決區，非活躍 atom
SKIP_DIRS = frozenset({
    "_meta", "_reference", "_staging", "_vectordb", "_distant",
    "episodic", "templates", "personal", "wisdom", "_pending_review",
})

# 系統檔前綴（檔名等級跳過）
SKIP_PREFIXES = ("SPEC_", "_")

# 索引檔名稱
MEMORY_INDEX = "MEMORY.md"
ATOM_INDEX = "_ATOM_INDEX.md"

# Wave 2: Last-used / Confirmations / ReadHits 移到 <atom>.access.json，
# 故 atom .md 不再 require 這些欄位（OPTIONAL_METADATA 仍接受 legacy 欄位過渡）。
REQUIRED_METADATA = frozenset({"Scope", "Confidence", "Trigger"})
OPTIONAL_METADATA = frozenset({
    "Last-used", "Confirmations", "ReadHits",  # legacy 過渡欄；migration 後清空
    "Privacy", "Source", "Type", "Created", "TTL",
    "Expires-at", "Tags", "Related", "Supersedes", "Quality",
    "Audience", "Author", "Pending-review-by", "Merge-strategy", "Created-at",
})

# 行動 always required; 知識 or 印象（指標型 atom 變體）二選一
REQUIRED_SECTIONS = frozenset({"行動"})
KNOWLEDGE_SECTIONS = frozenset({"知識", "印象"})

VALID_CONFIDENCE = frozenset({"[固]", "[觀]", "[臨]"})
VALID_SCOPES = frozenset({"global", "shared", "role", "personal"})

TRIGGER_MIN = 3
TRIGGER_MAX = 12
ATOM_MAX_LINES = 200
INDEX_MAX_LINES = 40


# ─── Pure functions ───────────────────────────────────────────────────────────


_SLUG_SPACE_RE = re.compile(r"[\s_]+")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9一-鿿㐀-䶿-]")
_SLUG_DASH_RE = re.compile(r"-+")


def slugify(title: str) -> str:
    """Atom 檔名 slug。對拍 server.js:655-663 行為等價。

    規則：lowercase → 空白/底線→`-` → 非 ascii/cjk/dash 剝除 → 連續 dash 合併 → trim dash
    """
    s = (title or "").lower()
    s = _SLUG_SPACE_RE.sub("-", s)
    s = _SLUG_STRIP_RE.sub("", s)
    s = _SLUG_DASH_RE.sub("-", s)
    s = s.strip("-")
    return s or "untitled"


def is_atom_file(path: Path, memory_root: Path) -> bool:
    """判斷一個 .md 是否為合法 atom 檔（會被 audit/health/index 計入）。

    排除：MEMORY.md / _ATOM_INDEX.md / SPEC_* / _* 前綴 / SKIP_DIRS 中間目錄。
    """
    if not path.is_file() or path.suffix != ".md":
        return False
    if path.name == MEMORY_INDEX or path.name == ATOM_INDEX:
        return False
    if any(path.name.startswith(p) for p in SKIP_PREFIXES):
        return False
    try:
        rel_parts = path.relative_to(memory_root).parts
    except ValueError:
        return False
    # rel_parts: directory parts + filename. Check intermediate dirs only.
    if any(part in SKIP_DIRS for part in rel_parts[:-1]):
        return False
    return True


_META_LINE_RE = re.compile(r"^-\s+([\w-]+):\s*(.+)$")


def parse_frontmatter(content: str) -> Dict[str, str]:
    """解析 atom-style metadata block（`- Key: Value` 列表）。

    從 # 標題後的連續 `- Key: Value` 區塊抽 metadata；遇空行/`##` 結束。
    支援 BOM。回傳 dict（無 `_format` key — atom_spec 不關心 Claude-native YAML）。
    """
    if content.startswith("﻿"):
        content = content[1:]
    fm: Dict[str, str] = {}
    in_meta = False
    for line in content.splitlines():
        if line.startswith("- "):
            m = _META_LINE_RE.match(line)
            if m:
                fm[m.group(1)] = m.group(2).strip()
                in_meta = True
        elif in_meta and (line.strip() == "" or line.startswith("##")):
            break
    return fm


def validate_atom_content(content: str) -> Optional[str]:
    """驗證 atom 內容結構。回傳 None 表通過；錯誤字串表第一個違規。

    對拍 server.js:724-742 validateAtomContent 行為等價。
    （注意：不檢 REQUIRED_METADATA 完整性，那是 audit 報告層級的檢查；
      此函式只驗 build_atom_content 產出契約。）
    """
    if "---\n" in content and content.index("---\n") < 5:
        return "YAML frontmatter (---) is forbidden in atom files"
    if not re.search(r"^# .+", content, re.MULTILINE):
        return "Missing # title heading"
    if "## 知識" not in content:
        return "Missing ## 知識 section"
    if "## 行動" not in content:
        return "Missing ## 行動 section"
    m = re.search(r"^- Confidence:\s*(.+)$", content, re.MULTILINE)
    if not m or m.group(1).strip() not in VALID_CONFIDENCE:
        return "Missing or invalid Confidence metadata"
    return None


def build_atom_content(
    *,
    title: str,
    scope: str,
    confidence: str,
    triggers: Iterable[str],
    knowledge: Iterable[str],
    actions: Optional[Iterable[str]] = None,
    related: Optional[Iterable[str]] = None,
    audience: Optional[Iterable[str]] = None,
    author: Optional[str] = None,
    pending_review_by: Optional[str] = None,
    merge_strategy: Optional[str] = None,
    created_at: Optional[str] = None,
    today: Optional[str] = None,
) -> str:
    """從結構化參數構造 atom 檔內容。

    對拍 server.js:669-721 buildAtomContent —— byte-identical 等價契約。
    SPEC §4 metadata 順序：Scope → Audience → Author → Confidence → Trigger →
    Last-used → Confirmations → ReadHits → Pending-review-by → Merge-strategy →
    Created-at → Related。空值欄位省略。
    """
    today = today or date.today().isoformat()
    triggers_list = list(triggers)
    knowledge_list = list(knowledge)
    actions_list = list(actions) if actions else []
    related_list = list(related) if related else []
    audience_list = list(audience) if audience else []

    lines: List[str] = [f"# {title}", ""]
    lines.append(f"- Scope: {scope}")
    if audience_list:
        lines.append(f"- Audience: {', '.join(audience_list)}")
    if author:
        lines.append(f"- Author: {author}")
    lines.append(f"- Confidence: {confidence}")
    lines.append(f"- Trigger: {', '.join(triggers_list)}")
    # Wave 2: Last-used / Confirmations / ReadHits 移到 <atom>.access.json，不再寫入 .md 檔頭
    if pending_review_by:
        lines.append(f"- Pending-review-by: {pending_review_by}")
    if merge_strategy and merge_strategy != "ai-assist":
        lines.append(f"- Merge-strategy: {merge_strategy}")
    lines.append(f"- Created-at: {created_at or today}")
    if related_list:
        lines.append(f"- Related: {', '.join(related_list)}")
    lines.extend(["", "## 知識", ""])
    for k in knowledge_list:
        lines.append(k if k.startswith("- ") else f"- {k}")
    lines.extend(["", "## 行動", ""])
    if actions_list:
        for a in actions_list:
            lines.append(a if a.startswith("- ") else f"- {a}")
    else:
        lines.append("- （依知識內容判斷）")
    lines.append("")
    return "\n".join(lines)


def resolve_scope_dir(
    scope: str,
    base_dir: Path,
    role: Optional[str] = None,
    user: Optional[str] = None,
) -> Optional[Path]:
    """V4 scope → 子目錄解析。對拍 server.js:777-824 resolveMemDir 結構部分。

    base_dir 含義：
      - global: ~/.claude/memory/  → 直接回傳 base_dir
      - shared/role/personal: {project_root}/.claude/memory/ → 回傳對應子層

    這支函式只負責結構映射，不做 fs marker 檢查（那是 atom_io 呼叫端職責）。
    無效輸入（unknown scope / 必填欄位缺）回傳 None；caller 自行 raise。
    """
    if scope == "global":
        return base_dir
    if scope == "shared":
        return base_dir / "shared"
    if scope == "role":
        if not role:
            return None
        return base_dir / "roles" / role
    if scope == "personal":
        if not user:
            return None
        return base_dir / "personal" / user
    return None


# ─── Helpers used by audit/health-check ───────────────────────────────────────


def iter_atom_files(memory_root: Path):
    """yield memory_root 下所有合法 atom .md（遞迴）。

    audit/health-check 共用，以 is_atom_file 為唯一判定。
    """
    if not memory_root.is_dir():
        return
    for md in sorted(memory_root.rglob("*.md")):
        if is_atom_file(md, memory_root):
            yield md


def required_metadata_missing(fm: Dict[str, Any]) -> List[str]:
    """回傳 fm 中缺的 REQUIRED_METADATA key 清單（保持插入順序穩定）。"""
    return [k for k in ("Scope", "Confidence", "Trigger", "Last-used") if k not in fm]
