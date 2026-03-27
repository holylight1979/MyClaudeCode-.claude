"""
migrate-v221.py — V2.21 專案記憶自治遷移工具

將舊路徑的 atoms 遷移到 {project_root}/.claude/memory/ 結構。

用法:
  python migrate-v221.py --project C:\\Projects [--dry-run]
  python migrate-v221.py --slug c--projects [--dry-run]
"""

import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── 路徑常數 ─────────────────────────────────────────────────────────────────

CLAUDE_DIR = Path.home() / ".claude"
MEMORY_DIR = CLAUDE_DIR / "memory"
REGISTRY_PATH = MEMORY_DIR / "project-registry.json"
MEMORY_INDEX = "MEMORY.md"

# 遷移後舊 MEMORY.md 的指標型內容模板
POINTER_TEMPLATE = """\
# Project Pointer

- Root: {root}
- Memory: {root}\\.claude\\memory\\MEMORY.md
- Status: migrated-v2.21
"""

GITIGNORE_CONTENT = """\
# 原子記憶系統 — 暫存檔（不版控）
*.access.json
episodic/
_staging/
vector-db/

# 版控
!memory/MEMORY.md
!memory/*.md
!memory/failures/
!memory/failures/*.md
!hooks/
"""

# ─── 資料型別 ─────────────────────────────────────────────────────────────────

# (atom_name, rel_path, triggers_str, confidence)
AtomEntry = Tuple[str, str, str, str]

# ─── Slug ─────────────────────────────────────────────────────────────────────


def cwd_to_slug(cwd: str) -> str:
    slug = cwd.replace(":", "-").replace("\\", "-").replace("/", "-").replace(".", "-")
    return slug.lower()


# ─── 解析 _ATOM_INDEX.md (shared) ─────────────────────────────────────────────


def parse_atom_index(file_path: Path) -> Tuple[List[AtomEntry], List[str], List[str], str, str]:
    """
    解析 _AIAtoms/_ATOM_INDEX.md。

    回傳:
      (entries, aliases, high_freq_facts, project_title, git_url)
      entries: [(name, path, triggers_str, confidence), ...]
      aliases: 字串列表
      high_freq_facts: 每行一個 fact
      project_title: 如 "SGI Project (Shared)"
      git_url: git URL 字串（可能為空）
    """
    if not file_path.exists():
        return [], [], [], "", ""

    text = file_path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()

    entries: List[AtomEntry] = []
    aliases: List[str] = []
    high_freq_facts: List[str] = []
    git_url = ""
    project_title = ""
    in_table = False
    in_hff = False

    # 解析標題
    for line in lines:
        if line.startswith("# "):
            project_title = line.lstrip("# ").strip()
            break

    for line in lines:
        stripped = line.strip()

        # Project-Aliases
        if stripped.startswith("> Project-Aliases:"):
            alias_str = stripped.split(":", 1)[1].strip()
            aliases = [a.strip() for a in alias_str.split(",") if a.strip()]
            continue

        # Git URL
        if stripped.startswith("> Git:"):
            git_url = stripped.split(":", 1)[1].strip()
            continue

        # 高頻事實 section
        if re.match(r"^## 高頻事實", stripped):
            in_hff = True
            in_table = False
            continue

        if in_hff:
            if stripped.startswith("##") or stripped.startswith("---"):
                in_hff = False
            elif stripped.startswith("- ["):
                high_freq_facts.append(stripped)
            continue

        # Atom table
        if not in_table:
            if stripped.startswith("| Atom") or stripped.startswith("|Atom"):
                in_table = True
            continue

        if in_table:
            if stripped.startswith("|---") or stripped.startswith("| ---"):
                continue
            if not stripped.startswith("|"):
                in_table = False
                continue
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if len(cells) >= 3:
                name = cells[0]
                path = cells[1]
                triggers = cells[2]
                confidence = cells[3] if len(cells) >= 4 else "[固]"
                entries.append((name, path, triggers, confidence))

    return entries, aliases, high_freq_facts, project_title, git_url


# ─── 解析個人 MEMORY.md ───────────────────────────────────────────────────────


def parse_personal_memory(memory_dir: Path) -> Tuple[List[AtomEntry], List[str], List[str], str]:
    """
    解析 ~/.claude/projects/{slug}/memory/MEMORY.md。

    回傳:
      (entries, aliases, high_freq_facts, project_title)
    """
    index_path = memory_dir / MEMORY_INDEX
    if not index_path.exists():
        return [], [], [], ""

    text = index_path.read_text(encoding="utf-8-sig")

    # 偵測指標型（已遷移）
    if "Status: migrated-v2.21" in text:
        return [], [], [], ""

    lines = text.splitlines()
    entries: List[AtomEntry] = []
    aliases: List[str] = []
    high_freq_facts: List[str] = []
    project_title = ""
    in_table = False
    in_hff = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("# "):
            project_title = stripped.lstrip("# ").strip()
            continue

        if stripped.startswith("> Project-Aliases:"):
            alias_str = stripped.split(":", 1)[1].strip()
            aliases = [a.strip() for a in alias_str.split(",") if a.strip()]
            continue

        if re.match(r"^## 高頻事實", stripped):
            in_hff = True
            in_table = False
            continue

        if in_hff:
            if stripped.startswith("##") or stripped.startswith("---"):
                in_hff = False
            elif stripped.startswith("- ["):
                high_freq_facts.append(stripped)
            continue

        if not in_table:
            if stripped.startswith("| Atom") or stripped.startswith("|Atom"):
                in_table = True
            continue

        if in_table:
            if stripped.startswith("|---") or stripped.startswith("| ---"):
                continue
            if not stripped.startswith("|"):
                in_table = False
                continue
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if len(cells) >= 3:
                name = cells[0]
                path = cells[1]
                triggers = cells[2]
                confidence = cells[3] if len(cells) >= 4 else ""
                entries.append((name, path, triggers, confidence))

    return entries, aliases, high_freq_facts, project_title


# ─── 合併 atoms ────────────────────────────────────────────────────────────────


def merge_atoms(
    shared: List[AtomEntry],
    personal: List[AtomEntry],
) -> List[AtomEntry]:
    """
    合併共享和個人 atoms。個人優先（相同 name 時個人覆蓋共享）。
    共享 _AIAtoms/ 路徑自動轉換為 memory/ 路徑。
    """
    result: Dict[str, AtomEntry] = {}

    # 先放共享（path 轉換：_AIAtoms/xxx.md → memory/xxx.md）
    for name, path, triggers, confidence in shared:
        if path.startswith("_AIAtoms/"):
            new_path = "memory/" + path[len("_AIAtoms/"):]
        else:
            new_path = path
        result[name] = (name, new_path, triggers, confidence)

    # 個人覆蓋（path 保持不變，已是 memory/xxx.md 格式）
    for name, path, triggers, confidence in personal:
        result[name] = (name, path, triggers, confidence)

    return list(result.values())


# ─── 合併高頻事實 ─────────────────────────────────────────────────────────────


def merge_high_freq_facts(shared_facts: List[str], personal_facts: List[str]) -> List[str]:
    """合併，保持個人版本的獨特條目（個人有 Redmine key 等私人資訊）。"""
    # 用 set 去重（完全相同行），但保留個人獨有條目
    seen = set()
    merged = []

    # 個人優先
    for fact in personal_facts:
        key = re.sub(r"\s+", " ", fact.lower())
        if key not in seen:
            merged.append(fact)
            seen.add(key)

    # 共享中有但個人沒有的
    for fact in shared_facts:
        key = re.sub(r"\s+", " ", fact.lower())
        if key not in seen:
            merged.append(fact)
            seen.add(key)

    return merged


# ─── 建立新 MEMORY.md ────────────────────────────────────────────────────────


def build_new_memory_md(
    project_name: str,
    aliases: List[str],
    git_url: str,
    atoms: List[AtomEntry],
    high_freq_facts: List[str],
) -> str:
    """生成新的統一 MEMORY.md 內容。"""
    lines = []

    # 標題（去掉 "Atom Index — " 前綴 + "(Shared)" / "(Personal)" 後綴）
    clean_name = re.sub(r"^Atom Index\s*[—-]\s*", "", project_name).strip()
    clean_name = re.sub(r"\s*\((?:Shared|Personal)\)\s*$", "", clean_name).strip()
    if not clean_name:
        clean_name = "Project"
    lines.append(f"# Atom Index — {clean_name}")
    lines.append("")

    if aliases:
        lines.append(f"> Project-Aliases: {', '.join(aliases)}")
    if git_url:
        lines.append(f"> Git: {git_url}")
    lines.append("")

    # Atom 表格
    lines.append("| Atom | Path | Trigger | Confidence |")
    lines.append("|------|------|---------|------------|")
    for name, path, triggers, confidence in atoms:
        lines.append(f"| {name} | {path} | {triggers} | {confidence} |")
    lines.append("")

    # 高頻事實
    if high_freq_facts:
        lines.append("---")
        lines.append("")
        lines.append("## 高頻事實")
        lines.append("")
        for fact in high_freq_facts:
            lines.append(fact)
        lines.append("")

    return "\n".join(lines)


# ─── 實際遷移邏輯 ─────────────────────────────────────────────────────────────


def migrate_project(project_root: Path, dry_run: bool = False) -> bool:
    """
    遷移單一專案到 V2.21 結構。

    回傳 True 表示成功，False 表示失敗。
    """
    print(f"\n{'[DRY RUN] ' if dry_run else ''}遷移: {project_root}")
    print("=" * 60)

    slug = cwd_to_slug(str(project_root))
    print(f"  slug: {slug}")

    # ── 來源路徑 ──
    aiatoms_dir = project_root / "_AIAtoms"
    personal_mem_dir = CLAUDE_DIR / "projects" / slug / "memory"

    has_aiatoms = aiatoms_dir.is_dir() and (aiatoms_dir / "_ATOM_INDEX.md").exists()
    has_personal = personal_mem_dir.is_dir() and (personal_mem_dir / MEMORY_INDEX).exists()

    if not has_aiatoms and not has_personal:
        print(f"  [跳過] 無 _AIAtoms 也無個人記憶，不需遷移。")
        return True

    print(f"  _AIAtoms: {'有' if has_aiatoms else '無'}")
    print(f"  個人記憶 ({slug}): {'有' if has_personal else '無'}")

    # ── 目標路徑 ──
    target_claude_dir = project_root / ".claude"
    target_mem_dir = target_claude_dir / "memory"

    # ── Step 1: 建立目錄結構 ──
    print("\n  [Step 1] 建立目錄結構...")
    dirs_to_create = [
        target_mem_dir,
        target_mem_dir / "episodic",
        target_mem_dir / "failures",
        target_mem_dir / "_staging",
        target_claude_dir / "hooks",
    ]
    for d in dirs_to_create:
        if not d.exists():
            print(f"    mkdir: {d}")
            if not dry_run:
                d.mkdir(parents=True, exist_ok=True)
        else:
            print(f"    exists: {d}")

    # ── Step 2: 解析 atom 索引 ──
    print("\n  [Step 2] 解析 atom 索引...")
    shared_entries: List[AtomEntry] = []
    shared_aliases: List[str] = []
    shared_hff: List[str] = []
    shared_title = ""
    git_url = ""

    if has_aiatoms:
        shared_entries, shared_aliases, shared_hff, shared_title, git_url = parse_atom_index(
            aiatoms_dir / "_ATOM_INDEX.md"
        )
        print(f"    共享 atoms: {len(shared_entries)} 個")

    personal_entries: List[AtomEntry] = []
    personal_aliases: List[str] = []
    personal_hff: List[str] = []
    personal_title = ""

    if has_personal:
        personal_entries, personal_aliases, personal_hff, personal_title = parse_personal_memory(
            personal_mem_dir
        )
        print(f"    個人 atoms: {len(personal_entries)} 個")

    # ── Step 3: 複製共享 atom .md 檔案 ──
    if has_aiatoms:
        print(f"\n  [Step 3] 複製共享 atoms ({aiatoms_dir.name}/) ...")
        skip_files = {"_ATOM_INDEX.md", "README.md"}
        for src_file in sorted(aiatoms_dir.glob("*.md")):
            if src_file.name in skip_files:
                continue
            dst_file = target_mem_dir / src_file.name
            if dst_file.exists():
                print(f"    [已存在跳過] {src_file.name}")
            else:
                print(f"    copy: {src_file.name}")
                if not dry_run:
                    shutil.copy2(src_file, dst_file)
    else:
        print("\n  [Step 3] 無共享 atoms，跳過。")

    # ── Step 4: 複製個人 atom .md 檔案（合併） ──
    if has_personal:
        print(f"\n  [Step 4] 複製個人 atoms ({personal_mem_dir}) ...")
        skip_files = {MEMORY_INDEX}
        for src_file in sorted(personal_mem_dir.glob("*.md")):
            if src_file.name in skip_files:
                continue
            dst_file = target_mem_dir / src_file.name
            if dst_file.exists():
                print(f"    [個人覆蓋] {src_file.name}")
                if not dry_run:
                    shutil.copy2(src_file, dst_file)
            else:
                print(f"    copy: {src_file.name}")
                if not dry_run:
                    shutil.copy2(src_file, dst_file)
    else:
        print("\n  [Step 4] 無個人 atoms，跳過。")

    # ── Step 5: 複製 episodic/, failures/ ──
    print("\n  [Step 5] 複製 episodic/, failures/ ...")
    for subdir_name in ("episodic", "failures"):
        for src_base in (personal_mem_dir,) if has_personal else ():
            src_subdir = src_base / subdir_name
            if src_subdir.is_dir():
                dst_subdir = target_mem_dir / subdir_name
                files = list(src_subdir.glob("*.md"))
                if files:
                    print(f"    {subdir_name}/: {len(files)} 個 .md 檔案")
                    if not dry_run:
                        dst_subdir.mkdir(exist_ok=True)
                        for f in files:
                            shutil.copy2(f, dst_subdir / f.name)
                else:
                    print(f"    {subdir_name}/: 空目錄")

    # ── Step 6: 合併 atoms + 建立新 MEMORY.md ──
    print("\n  [Step 6] 建立新 MEMORY.md ...")
    merged_atoms = merge_atoms(shared_entries, personal_entries)
    merged_aliases = shared_aliases or personal_aliases
    merged_hff = merge_high_freq_facts(shared_hff, personal_hff)
    project_name = shared_title or personal_title or slug

    new_memory_content = build_new_memory_md(
        project_name, merged_aliases, git_url, merged_atoms, merged_hff
    )

    dst_memory = target_mem_dir / MEMORY_INDEX
    print(f"    → {dst_memory}")
    print(f"    atoms 總計: {len(merged_atoms)} 個")
    if dry_run:
        print("    [DRY RUN] 預覽內容:")
        for preview_line in new_memory_content.splitlines()[:30]:
            print(f"      {preview_line}")
        if len(new_memory_content.splitlines()) > 30:
            print(f"      ... (共 {len(new_memory_content.splitlines())} 行)")
    else:
        dst_memory.write_text(new_memory_content, encoding="utf-8")

    # ── Step 7: 生成 .gitignore ──
    print("\n  [Step 7] 生成 .claude/.gitignore ...")
    gitignore_path = target_claude_dir / ".gitignore"
    if gitignore_path.exists():
        print(f"    [已存在] {gitignore_path}")
    else:
        print(f"    write: {gitignore_path}")
        if not dry_run:
            gitignore_path.write_text(GITIGNORE_CONTENT, encoding="utf-8")

    # ── Step 8: 更新 project-registry.json ──
    print("\n  [Step 8] 更新 project-registry.json ...")
    if not dry_run:
        reg = _load_registry()
        entry = reg.setdefault("projects", {}).setdefault(slug, {})
        entry["root"] = str(project_root)
        entry["last_seen"] = date.today().isoformat()
        if merged_aliases:
            entry["aliases"] = merged_aliases
        _save_registry(reg)
        print(f"    已更新 slug={slug}")
    else:
        print(f"    [DRY RUN] 會寫入 slug={slug}, root={project_root}")

    # ── Step 9: 舊 MEMORY.md → 指標型 ──
    print("\n  [Step 9] 將舊 MEMORY.md 改為指標型 ...")
    old_pointer_paths = []

    # 舊個人記憶路徑
    if has_personal:
        old_pointer_paths.append(personal_mem_dir / MEMORY_INDEX)

    for old_path in old_pointer_paths:
        pointer_content = POINTER_TEMPLATE.format(root=str(project_root))
        if dry_run:
            print(f"    [DRY RUN] 改為指標: {old_path}")
        else:
            # 備份原始內容
            backup_path = old_path.with_suffix(".md.bak")
            shutil.copy2(old_path, backup_path)
            old_path.write_text(pointer_content, encoding="utf-8")
            print(f"    指標化: {old_path} (備份: {backup_path})")

    print(f"\n  {'[DRY RUN] ' if dry_run else ''}遷移完成: {project_root}")
    return True


# ─── Registry helpers（獨立，不依賴 wg_paths） ──────────────────────────────


def _load_registry() -> Dict[str, Any]:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"projects": {}}


def _save_registry(reg: Dict[str, Any]) -> None:
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(REGISTRY_PATH)


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="V2.21 專案記憶遷移工具")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", metavar="PATH", help="專案根目錄路徑")
    group.add_argument("--slug", metavar="SLUG", help="Claude Code 專案 slug")
    group.add_argument("--list", action="store_true", help="列出所有可遷移的專案")
    parser.add_argument("--dry-run", action="store_true", help="僅預覽，不實際修改")
    args = parser.parse_args()

    if args.list:
        print("可遷移的專案（有個人記憶或 _AIAtoms）:")
        projects_dir = CLAUDE_DIR / "projects"
        if projects_dir.is_dir():
            for proj_dir in sorted(projects_dir.iterdir()):
                mem = proj_dir / "memory"
                if mem.is_dir() and (mem / MEMORY_INDEX).exists():
                    mem_md = mem / MEMORY_INDEX
                    is_pointer = "Status: migrated-v2.21" in mem_md.read_text(encoding="utf-8-sig")
                    status = "[已遷移]" if is_pointer else "[待遷移]"
                    print(f"  {status} {proj_dir.name}")
        return

    if args.project:
        project_root = Path(args.project).resolve()
        if not project_root.is_dir():
            print(f"錯誤: 目錄不存在: {project_root}", file=sys.stderr)
            sys.exit(1)
    else:
        # 從 slug 推斷 project root
        slug = args.slug
        reg = _load_registry()
        if slug in reg.get("projects", {}):
            project_root = Path(reg["projects"][slug]["root"])
        else:
            print(f"錯誤: slug '{slug}' 不在 registry 中。請用 --project 指定路徑。", file=sys.stderr)
            sys.exit(1)

    success = migrate_project(project_root, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
