"""
sync-memory-index.py — 從 _ATOM_INDEX.md 自動生成 memory/MEMORY.md

設計依據：_AIDocs/DevHistory/atom-trigger-source-of-truth.md（選項 A §六 Step 2）

行為：
- 讀 _ATOM_INDEX.md 取得所有 atom（按 scope 分組、計數）
- 從每 atom 檔的 H1 第一行抽取「說明」欄
- 重組「Atom Index」區，feedback-* 自動歸納並計數
- 保留現有「知識庫查閱」段落（自動偵測 `> **知識庫查閱**：` 標記後內容）

模式：
  --check  drift 偵測，stderr 列出差異，exit 1 表示有 drift
  --write  覆寫 MEMORY.md
  (default) dry-run，stdout 顯示新內容
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# S2.2: 走 funnel write_index_full（整檔覆寫 + audit log）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.atom_io import write_index_full  # noqa: E402

MEMORY_DIR = Path.home() / ".claude" / "memory"
ATOM_INDEX_NAME = "_ATOM_INDEX.md"
MEMORY_INDEX_NAME = "MEMORY.md"

# atom 顯示說明的覆寫表（針對 feedback-* 群組整體說明用）
GROUP_DESCRIPTIONS = {
    "feedback": "行為校正",
}


def parse_atom_index(index_path: Path) -> List[Tuple[str, str, str]]:
    """Return list of (atom_name, rel_path, scope)."""
    rows: List[Tuple[str, str, str]] = []
    if not index_path.exists():
        return rows
    text = index_path.read_text(encoding="utf-8-sig")
    in_table = False
    for line in text.splitlines():
        s = line.strip()
        if not in_table:
            if s.startswith("| Atom") or s.startswith("|Atom"):
                in_table = True
            continue
        if s.startswith("|---") or s.startswith("| ---"):
            continue
        if not s.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in s.split("|") if c.strip()]
        if len(cells) < 3:
            continue
        name = cells[0]
        path = cells[1]
        scope = cells[3] if len(cells) >= 4 else "global"
        rows.append((name, path, scope))
    return rows


def extract_atom_caption(atom_path: Path) -> str:
    """Read first H1 line as caption."""
    if not atom_path.exists():
        return ""
    try:
        for line in atom_path.read_text(encoding="utf-8-sig").splitlines()[:5]:
            if line.startswith("# "):
                return line[2:].strip()
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def render_atom_section(rows: List[Tuple[str, str, str]],
                        claude_root: Path) -> str:
    """Render the atom index table.
    Group feedback-* into one row '| feedback-* | 行為校正（N 個含 ...）|'.
    Other atoms render individually with their H1 as caption.
    """
    individual: List[Tuple[str, str]] = []  # (name, caption)
    feedback_names: List[str] = []
    for name, rel_path, _scope in rows:
        if name.startswith("feedback") or name == "fix-escalation":
            feedback_names.append(name)
        else:
            cap = extract_atom_caption(claude_root / rel_path) if rel_path else ""
            individual.append((name, cap))

    lines = [
        "# Atom Index — Global",
        "",
        "> Hook 自動匹配 trigger 注入相關 atom（完整觸發表見 `_ATOM_INDEX.md`）。",
        "",
        "| Atom | 說明 |",
        "|------|------|",
    ]
    for name, cap in individual:
        lines.append(f"| {name} | {cap} |")
    if feedback_names:
        sample = ", ".join(n.replace("feedback-", "") for n in feedback_names[:5])
        lines.append(
            f"| feedback-* | 行為校正（{len(feedback_names)} 個含 {sample} 等） |"
        )
    return "\n".join(lines)


KNOWLEDGE_BLOCK_MARKER = "> **知識庫查閱**："


def split_existing(memory_path: Path) -> Tuple[str, str]:
    """Split existing MEMORY.md into (atom_section, knowledge_block).
    knowledge_block 從 marker 那行開始（含），到檔尾。
    """
    if not memory_path.exists():
        return "", ""
    text = memory_path.read_text(encoding="utf-8-sig")
    idx = text.find(KNOWLEDGE_BLOCK_MARKER)
    if idx < 0:
        return text, ""
    # 從 marker 往前找最近一個空白行作為分隔
    head = text[:idx].rstrip() + "\n"
    tail = text[idx:]
    return head, tail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--memory-dir", type=Path, default=MEMORY_DIR)
    args = parser.parse_args()

    memory_dir: Path = args.memory_dir
    claude_root = memory_dir.parent
    index_path = memory_dir / ATOM_INDEX_NAME
    memory_path = memory_dir / MEMORY_INDEX_NAME

    rows = parse_atom_index(index_path)
    if not rows:
        print("[sync-memory-index] _ATOM_INDEX.md empty or missing", file=sys.stderr)
        return 1

    new_atom_section = render_atom_section(rows, claude_root)
    _old_head, knowledge_tail = split_existing(memory_path)
    new_full = new_atom_section + "\n\n" + knowledge_tail if knowledge_tail else new_atom_section + "\n"

    if args.check:
        current = memory_path.read_text(encoding="utf-8-sig") if memory_path.exists() else ""
        if current.strip() != new_full.strip():
            print("[sync-memory-index] MEMORY.md drift detected", file=sys.stderr)
            return 1
        return 0

    if args.write:
        result = write_index_full(memory_path, new_full,
                                  source="tool:sync-memory-index")
        if not result.ok:
            print(f"[sync-memory-index] write failed: {result.error}",
                  file=sys.stderr)
            return 1
        print(f"[sync-memory-index] wrote {memory_path}")
        return 0

    print(new_full)
    return 0


if __name__ == "__main__":
    sys.exit(main())
