"""
wg_paths.py — 原子記憶系統路徑集中管理 (V2.20)

所有路徑構造/判斷邏輯統一在此。其他模組一律 import，禁止自行拼路徑。
新增路徑相關函式時，必須在此檔案中定義。

V2.20: 行為等價重構（路徑仍走 ~/.claude/projects/{slug}/memory/）
V2.21: 切換到 {project_root}/.claude/memory/（僅改此檔）
"""

import json
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── 全域常數 ─────────────────────────────────────────────────────────────────

CLAUDE_DIR = Path.home() / ".claude"
MEMORY_DIR = CLAUDE_DIR / "memory"
EPISODIC_DIR = MEMORY_DIR / "episodic"
WORKFLOW_DIR = CLAUDE_DIR / "workflow"
CONFIG_PATH = WORKFLOW_DIR / "config.json"
MEMORY_INDEX = "MEMORY.md"
ATOM_INDEX = "_ATOM_INDEX.md"  # V3.2: machine-only trigger table (not @imported)

# ─── Project Registry (V2.21 預留) ───────────────────────────────────────────

REGISTRY_PATH = MEMORY_DIR / "project-registry.json"

# ─── Slug ─────────────────────────────────────────────────────────────────────


def cwd_to_project_slug(cwd: str) -> str:
    """Convert CWD to Claude Code project slug.

    V2.20 修復 C7: 全部小寫，避免 Windows C:\\ vs c:\\ 產生不同 slug。
    舊行為: 僅首字母小寫 → 新行為: 整條小寫。
    """
    slug = cwd.replace(":", "-").replace("\\", "-").replace("/", "-").replace(".", "-")
    return slug.lower()


# ─── 專案根目錄 ───────────────────────────────────────────────────────────────


def find_project_root(cwd: str) -> Optional[Path]:
    """Walk up from CWD to find project root.

    辨識標記（優先順序）:
    1. .claude/memory/MEMORY.md 存在（V2.21 新增，專案自治目錄）
    2. _AIDocs/ 目錄存在
    3. .git 或 .svn 存在
    最多向上走 3 層。找不到則回傳 CWD 本身。
    """
    if not cwd:
        return None
    p = Path(cwd)
    for _ in range(4):  # cwd itself + max 3 levels up
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
    return Path(cwd)  # fallback


# ─── 專案記憶目錄 ─────────────────────────────────────────────────────────────


def get_project_memory_dir(cwd: str) -> Optional[Path]:
    """Get project-level memory dir from CWD.

    V2.21: 新路徑（{project_root}/.claude/memory/）優先，舊路徑 fallback。
    """
    if not cwd:
        return None
    # V2.21: 新路徑優先
    root = find_project_root(cwd)
    if root:
        new_mem = root / ".claude" / "memory"
        if new_mem.is_dir() and (new_mem / MEMORY_INDEX).exists():
            return new_mem
    # fallback: 舊路徑（相容未遷移的專案）
    slug = cwd_to_project_slug(cwd)
    old_mem = CLAUDE_DIR / "projects" / slug / "memory"
    if old_mem.exists():
        return old_mem
    return None


def get_project_claude_dir(cwd: str) -> Optional[Path]:
    """回傳 {project_root}/.claude/，不存在回 None。

    V2.21 預留：必須有 memory/MEMORY.md 才算專案自治目錄（修復 W1）。
    """
    root = find_project_root(cwd)
    if root:
        d = root / ".claude"
        if d.is_dir() and (d / "memory" / MEMORY_INDEX).exists():
            return d
    return None


# ─── Transcript（Claude Code 管理，路徑不可變）────────────────────────────────


def get_transcript_path(session_id: str, cwd: str) -> Optional[Path]:
    """Locate session transcript JSONL.

    Path format: ~/.claude/projects/{slug}/{session_id}.jsonl
    Claude Code 自動管理，我們只讀取。
    """
    if not session_id or not cwd:
        return None
    slug = cwd_to_project_slug(cwd)
    candidate = CLAUDE_DIR / "projects" / slug / f"{session_id}.jsonl"
    return candidate if candidate.exists() else None


# ─── Episodic 目錄 ────────────────────────────────────────────────────────────


def resolve_episodic_dir(cwd: str) -> Tuple[Path, str]:
    """Resolve episodic directory: project-scoped if CWD maps to a project, else global.

    Returns (episodic_dir, scope_label).
    """
    mem = get_project_memory_dir(cwd)
    if mem:
        return mem / "episodic", f"project:{cwd_to_project_slug(cwd)}"
    return EPISODIC_DIR, "global"


# ─── Failure 目錄 ─────────────────────────────────────────────────────────────


def resolve_failures_dir(cwd: str) -> Path:
    """Resolve failure atoms directory. Auto-creates if needed."""
    mem = get_project_memory_dir(cwd)
    if mem:
        d = mem / "failures"
        d.mkdir(exist_ok=True)
        return d
    return MEMORY_DIR / "failures"


# ─── Staging 目錄（修復 W4: 專案層 staging）─────────────────────────────────


def resolve_staging_dir(cwd: str) -> Path:
    """Resolve staging directory. Auto-creates if needed."""
    mem = get_project_memory_dir(cwd)
    if mem:
        d = mem / "_staging"
        d.mkdir(exist_ok=True)
        return d
    return MEMORY_DIR / "_staging"


# ─── Access.json 路徑（修復 C2）──────────────────────────────────────────────


def resolve_access_json(atom_name: str, atom_path: Path) -> Path:
    """從 atom 實際路徑推導其 .access.json 位置。

    修復 C2: 不再假設所有 access.json 都在全域 MEMORY_DIR，
    而是跟著 atom 檔案走。
    """
    return atom_path.parent / f"{atom_name}.access.json"


# ─── Project Registry (V2.21) ────────────────────────────────────────────────


def _today() -> str:
    return date.today().isoformat()


def _load_registry() -> Dict[str, Any]:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"projects": {}}


def _save_registry(reg: Dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(REGISTRY_PATH)


def register_project(cwd: str) -> None:
    """SessionStart 時呼叫，更新 project-registry.json。

    只有在找到真正的專案根（有辨識標記）才寫入，避免每個 cwd 都進 registry。
    """
    root = find_project_root(cwd)
    if not root:
        return
    # 確認找到的是有標記的真實專案根，而非 fallback cwd
    root_p = root
    has_marker = (
        (root_p / ".claude" / "memory" / MEMORY_INDEX).exists()
        or (root_p / "_AIDocs").is_dir()
        or (root_p / ".git").exists()
        or (root_p / ".svn").exists()
    )
    if not has_marker:
        return
    slug = cwd_to_project_slug(str(root))
    reg = _load_registry()
    entry = reg.setdefault("projects", {}).setdefault(slug, {})
    entry["root"] = str(root)
    entry["last_seen"] = _today()
    _save_registry(reg)


# ─── Slug 指標檔 ──────────────────────────────────────────────────────────────


def get_slug_pointer_path(cwd: str) -> Path:
    """Claude Code auto-memory 位置。

    ~/.claude/projects/{slug}/memory/MEMORY.md
    V2.21 時改為指標型內容（指向 project_root）。
    """
    slug = cwd_to_project_slug(cwd)
    return CLAUDE_DIR / "projects" / slug / "memory" / MEMORY_INDEX


# ─── 跨專案發現 ──────────────────────────────────────────────────────────────


def discover_all_project_memory_dirs() -> List[Tuple[str, Path]]:
    """Discover all project memory directories.

    V2.21: registry-first，舊路徑掃描作為 fallback（過渡期相容）。

    Returns [(slug, memory_dir_path), ...]
    """
    seen_slugs: set = set()
    results: List[Tuple[str, Path]] = []

    # Registry-based discovery (V2.21)
    reg = _load_registry()
    for slug, info in reg.get("projects", {}).items():
        root = Path(info.get("root", ""))
        if not root.is_dir():
            continue
        # 優先新路徑
        new_mem = root / ".claude" / "memory"
        if new_mem.is_dir() and (new_mem / MEMORY_INDEX).exists():
            results.append((slug, new_mem))
            seen_slugs.add(slug)
            continue
        # 舊路徑 fallback
        old_mem = CLAUDE_DIR / "projects" / slug / "memory"
        if old_mem.is_dir():
            results.append((slug, old_mem))
            seen_slugs.add(slug)

    # 掃描舊路徑補充（過渡期：registry 尚未收錄的專案）
    projects_dir = CLAUDE_DIR / "projects"
    if projects_dir.is_dir():
        for proj_dir in sorted(projects_dir.iterdir()):
            if not proj_dir.is_dir():
                continue
            slug = proj_dir.name
            if slug in seen_slugs:
                continue
            mem = proj_dir / "memory"
            if mem.is_dir():
                results.append((slug, mem))

    return results


# ─── Vector Service Layer 發現 ────────────────────────────────────────────────


def discover_memory_layers(
    layer_filter: Optional[str] = None,
) -> List[Tuple[str, Path]]:
    """Discover all memory layers for vector service indexing.

    Returns [("global", path), ("project:{slug}", path), ...]
    """
    layers: List[Tuple[str, Path]] = [("global", MEMORY_DIR)]
    for slug, mem_dir in discover_all_project_memory_dirs():
        label = f"project:{slug}"
        if (
            layer_filter
            and layer_filter not in ("all", "project")
            and layer_filter != slug
        ):
            continue
        layers.append((label, mem_dir))
    return layers


# ─── State File 路徑 ─────────────────────────────────────────────────────────


def state_file_path(session_id: str) -> Path:
    """State file path for a given session."""
    return WORKFLOW_DIR / f"state-{session_id}.json"
