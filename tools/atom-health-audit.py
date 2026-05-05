"""atom-health-audit.py — Atom 體質審視工具（Wave 3）

讀每個 atom 的 .md（Confidence / Trigger / Created）+ access.json
（read_hits / confirmations / last_used / first_seen），依固定規則分類：

| 分類 | 判斷規則 | 預設處置 |
|------|---------|---------|
| 歸檔候選（episodic 過期）| episodic 且 now - last_used > 24 days | git mv → memory/_distant/episodic/ |
| 晉升候選 [臨]→[觀]      | Confidence=[臨] 且（confirmations≥4 OR read_hits≥20）| 提示跑 atom_promote MCP |
| 晉升候選 [觀]→[固]      | Confidence=[觀] 且（confirmations≥10 OR read_hits≥50）| 提示跑 atom_promote MCP |
| 冷凍候選                 | read_hits=0 且 now - first_seen > 30 days 且非 template | git mv → memory/_distant/cold/ |
| 缺欄補齊                 | 缺 Confidence 欄 | 補 [臨]（依 access 計數） |
| trigger 補強候選         | read_hits=0 但 first_seen ≤ 30 days | 列出 trigger 給使用者目視 |
| 保留                     | 其餘                                | 不動 |

用法：
  python tools/atom-health-audit.py            # 試跑（預設）→ 列分類
  python tools/atom-health-audit.py --apply    # 真動：歸檔 / 補欄；
                                                 # 晉升仍走 atom_promote MCP（本工具不直接動）

歸檔目的地：
  - 過期 episodic → memory/_distant/episodic/<filename>
  - 冷凍 atom    → memory/_distant/cold/<filename>
  - 對應 .access.json 連帶搬遷
  - 用 git mv（變更入版控；可 git mv 還原）

不刪除任何 atom — 所有「處置」都是搬到 _distant/，未來人工確認再清理。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / "memory"
DISTANT_DIR = MEMORY_DIR / "_distant"

# 與 lib/atom_spec.py 對齊的 SKIP_DIRS（不重複 import 避免測試耦合）
SKIP_DIRS_RELATIVE = {
    "_meta", "_reference", "_staging", "_vectordb", "_distant",
    "templates", "_pending_review", "personal", "wisdom",
}
EXCLUDE_FILES = {"MEMORY.md", "_ATOM_INDEX.md", "DESIGN.md"}
EXCLUDE_PREFIXES = ("_CHANGELOG", "SPEC_")

# 規則門檻（與 server.js 升級 gate 對齊）
PROMOTE_TEMP_TO_OBS_CONF = 4
PROMOTE_TEMP_TO_OBS_RH = 20
PROMOTE_OBS_TO_FIX_CONF = 10
PROMOTE_OBS_TO_FIX_RH = 50

EPISODIC_TTL_DAYS = 24
COLD_FIRST_SEEN_THRESHOLD_DAYS = 30
RECENT_FIRST_SEEN_THRESHOLD_DAYS = 30  # 「剛建未命中」門檻

RE_CONFIDENCE = re.compile(r"^- Confidence:\s*(\[(?:臨|觀|固)\])\s*$", re.MULTILINE)
RE_TRIGGER = re.compile(r"^- Trigger:\s*(.+?)\s*$", re.MULTILINE)
RE_TYPE = re.compile(r"^- Type:\s*(.+?)\s*$", re.MULTILINE)


@dataclass
class AtomHealth:
    md_path: Path
    rel_path: str
    confidence: Optional[str] = None
    trigger: str = ""
    atom_type: str = ""
    is_episodic: bool = False
    read_hits: int = 0
    confirmations: int = 0
    last_used: Optional[str] = None
    first_seen: Optional[str] = None
    category: str = "保留"
    note: str = ""
    suggested_action: str = "no-op"
    new_path: Optional[Path] = None  # 歸檔/冷凍目的地


def is_atom_file(p: Path) -> bool:
    if p.name in EXCLUDE_FILES:
        return False
    for pfx in EXCLUDE_PREFIXES:
        if p.name.startswith(pfx):
            return False
    parts = set(p.relative_to(MEMORY_DIR).parts[:-1])
    if parts & SKIP_DIRS_RELATIVE:
        return False
    return p.suffix == ".md"


def load_access(md_path: Path) -> Dict[str, Any]:
    acc_p = md_path.with_suffix(".access.json")
    if not acc_p.exists():
        return {}
    try:
        return json.loads(acc_p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def days_since(iso_date: str) -> int:
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except ValueError:
        return 9999
    today = datetime.now(timezone.utc).date()
    return (today - d).days


def classify(atom: AtomHealth) -> None:
    """套用規則分類，寫入 atom.category / suggested_action / new_path。"""

    # 1. 過期 episodic
    if atom.is_episodic and atom.last_used:
        if days_since(atom.last_used) > EPISODIC_TTL_DAYS:
            atom.category = "歸檔候選（episodic 過期）"
            atom.suggested_action = "git_mv_to_distant_episodic"
            atom.new_path = DISTANT_DIR / "episodic" / atom.md_path.name
            atom.note = f"last_used={atom.last_used} ({days_since(atom.last_used)}d ago)"
            return

    # 2. 缺 Confidence 欄
    if atom.confidence is None:
        atom.category = "缺欄補齊"
        atom.suggested_action = "add_confidence_temp"
        atom.note = "預設標 [臨]"
        return

    # 3. 晉升候選
    if atom.confidence == "[臨]":
        if (atom.confirmations >= PROMOTE_TEMP_TO_OBS_CONF
                or atom.read_hits >= PROMOTE_TEMP_TO_OBS_RH):
            atom.category = "晉升候選 [臨]→[觀]"
            atom.suggested_action = "atom_promote_mcp"
            atom.note = (f"confirmations={atom.confirmations}/{PROMOTE_TEMP_TO_OBS_CONF}, "
                         f"read_hits={atom.read_hits}/{PROMOTE_TEMP_TO_OBS_RH}")
            return
    elif atom.confidence == "[觀]":
        if (atom.confirmations >= PROMOTE_OBS_TO_FIX_CONF
                or atom.read_hits >= PROMOTE_OBS_TO_FIX_RH):
            atom.category = "晉升候選 [觀]→[固]"
            atom.suggested_action = "atom_promote_mcp"
            atom.note = (f"confirmations={atom.confirmations}/{PROMOTE_OBS_TO_FIX_CONF}, "
                         f"read_hits={atom.read_hits}/{PROMOTE_OBS_TO_FIX_RH}")
            return

    # 4. 冷凍候選 / trigger 補強
    if atom.read_hits == 0 and atom.first_seen:
        d = days_since(atom.first_seen)
        if d > COLD_FIRST_SEEN_THRESHOLD_DAYS:
            atom.category = "冷凍候選"
            atom.suggested_action = "git_mv_to_distant_cold"
            atom.new_path = DISTANT_DIR / "cold" / atom.md_path.name
            atom.note = f"read_hits=0, first_seen={atom.first_seen} ({d}d ago)"
            return
        else:
            atom.category = "trigger 補強候選"
            atom.suggested_action = "review_trigger"
            atom.note = f"剛建未命中（first_seen={atom.first_seen}, {d}d ago）trigger={atom.trigger[:60]}"
            return

    # 5. 保留
    atom.category = "保留"
    atom.suggested_action = "no-op"


def collect() -> List[AtomHealth]:
    candidates = sorted(p for p in MEMORY_DIR.rglob("*.md") if is_atom_file(p))
    out: List[AtomHealth] = []
    for md in candidates:
        try:
            text = md.read_text(encoding="utf-8-sig")
        except OSError:
            continue

        cm = RE_CONFIDENCE.search(text)
        confidence = cm.group(1) if cm else None
        tm = RE_TRIGGER.search(text)
        trigger = tm.group(1) if tm else ""
        ty = RE_TYPE.search(text)
        atom_type = ty.group(1).strip().lower() if ty else ""

        # episodic 兩個判定來源：路徑或 Type
        rel_parts = md.relative_to(MEMORY_DIR).parts
        is_episodic = (rel_parts and rel_parts[0] == "episodic") or atom_type == "episodic"

        access = load_access(md)
        atom = AtomHealth(
            md_path=md,
            rel_path=str(md.relative_to(MEMORY_DIR)),
            confidence=confidence,
            trigger=trigger,
            atom_type=atom_type,
            is_episodic=is_episodic,
            read_hits=int(access.get("read_hits") or 0),
            confirmations=int(access.get("confirmations") or 0),
            last_used=access.get("last_used"),
            first_seen=access.get("first_seen"),
        )
        classify(atom)
        out.append(atom)
    return out


def report(atoms: List[AtomHealth]) -> None:
    by_cat: Dict[str, List[AtomHealth]] = {}
    for a in atoms:
        by_cat.setdefault(a.category, []).append(a)

    print("=== Atom 健康審視 ===")
    print(f"總計 {len(atoms)} atoms\n")
    cats_order = [
        "歸檔候選（episodic 過期）",
        "冷凍候選",
        "晉升候選 [臨]→[觀]",
        "晉升候選 [觀]→[固]",
        "缺欄補齊",
        "trigger 補強候選",
        "保留",
    ]
    for cat in cats_order:
        lst = by_cat.get(cat, [])
        if not lst:
            continue
        print(f"--- {cat}（{len(lst)}） ---")
        for a in lst:
            line = f"  {a.rel_path}"
            if a.note:
                line += f"  | {a.note}"
            if a.new_path:
                rel_new = a.new_path.relative_to(MEMORY_DIR)
                line += f"  → {rel_new}"
            print(line)
        print()


def add_missing_confidence(md_path: Path) -> bool:
    """為缺 Confidence 的 atom 補上 [臨]。回傳是否實際寫入。"""
    try:
        text = md_path.read_text(encoding="utf-8-sig")
    except OSError:
        return False
    if RE_CONFIDENCE.search(text):
        return False
    pat = re.compile(r"(^- Trigger:.*$)", re.MULTILINE)
    if not pat.search(text):
        return False
    new_text = pat.sub(r"\1\n- Confidence: [臨]", text, count=1)
    tmp = md_path.with_suffix(md_path.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(md_path)
    return True


def git_mv(src: Path, dst: Path) -> bool:
    """用 git mv 搬檔；同時搬 .access.json 對應檔。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmds = []
    if src.exists():
        cmds.append(["git", "mv", "-f", str(src), str(dst)])
    src_access = src.with_suffix(".access.json")
    dst_access = dst.with_suffix(".access.json")
    if src_access.exists():
        cmds.append(["git", "mv", "-f", str(src_access), str(dst_access)])
    for cmd in cmds:
        try:
            r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
            if r.returncode != 0:
                print(f"[WARN] {' '.join(cmd)} failed: {r.stderr.strip()}",
                      file=sys.stderr)
                # fallback: 一般 mv（git 仍會偵測為 rename）
                try:
                    shutil.move(str(cmd[3]), str(cmd[4]))
                except (OSError, IndexError) as e:
                    print(f"[WARN] fallback mv failed: {e}", file=sys.stderr)
                    return False
        except OSError as e:
            print(f"[WARN] subprocess {cmd}: {e}", file=sys.stderr)
            return False
    return True


def apply_actions(atoms: List[AtomHealth]) -> Dict[str, int]:
    counts = {"archived_episodic": 0, "archived_cold": 0, "confidence_added": 0}
    for a in atoms:
        if a.suggested_action == "git_mv_to_distant_episodic" and a.new_path:
            if git_mv(a.md_path, a.new_path):
                counts["archived_episodic"] += 1
        elif a.suggested_action == "git_mv_to_distant_cold" and a.new_path:
            if git_mv(a.md_path, a.new_path):
                counts["archived_cold"] += 1
        elif a.suggested_action == "add_confidence_temp":
            if add_missing_confidence(a.md_path):
                counts["confidence_added"] += 1
    return counts


def run_sync_indexes() -> None:
    """歸檔／補欄後同步 _ATOM_INDEX.md 與 MEMORY.md。"""
    for tool in ("sync-atom-index.py", "sync-memory-index.py"):
        path = ROOT / "tools" / tool
        if not path.exists():
            continue
        try:
            subprocess.run([sys.executable, str(path), "--write"],
                           cwd=str(ROOT), capture_output=True, text=True)
            print(f"[+] {tool} --write")
        except OSError as e:
            print(f"[WARN] {tool} failed: {e}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="真動：歸檔過期 episodic / 冷凍未命中 atom / 補 Confidence 欄；不指定則 dry-run")
    parser.add_argument("--json", action="store_true",
                        help="JSON 輸出（給程式消費）")
    args = parser.parse_args()

    atoms = collect()

    if args.json:
        out = [
            {
                "rel_path": a.rel_path,
                "confidence": a.confidence,
                "trigger": a.trigger,
                "is_episodic": a.is_episodic,
                "read_hits": a.read_hits,
                "confirmations": a.confirmations,
                "last_used": a.last_used,
                "first_seen": a.first_seen,
                "category": a.category,
                "suggested_action": a.suggested_action,
                "new_path": str(a.new_path.relative_to(MEMORY_DIR)) if a.new_path else None,
                "note": a.note,
            }
            for a in atoms
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    report(atoms)

    if args.apply:
        print("=== 套用處置 ===")
        counts = apply_actions(atoms)
        print(f"歸檔 episodic：{counts['archived_episodic']}")
        print(f"冷凍 atom：{counts['archived_cold']}")
        print(f"補 Confidence 欄：{counts['confidence_added']}")
        if any(counts.values()):
            print("\n=== 同步索引 ===")
            run_sync_indexes()
        else:
            print("\n（無實質異動，不跑 index 同步）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
