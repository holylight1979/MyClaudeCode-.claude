"""migrate-access-stats.py — 一次性遷移：atom .md 計數欄 → <atom>.access.json (v2)

Wave 2 Phase A3。idempotent、預設試跑、--apply 才動。

行為：
1. 掃 memory/**/*.md（排除 _meta/ MEMORY.md _ATOM_INDEX.md DESIGN.md _CHANGELOG*）
2. 對每個 atom：
   - 從前 30 行抽 `- ReadHits: N` / `- Last-used: YYYY-MM-DD` /
     `- Confirmations: N`（同時兼容 frontmatter `Field: value` 兩種寫法）
   - 讀對應 <atom>.access.json（無則建空）
   - 把舊陣列 confirmations 改名 confirmation_events、計數設為陣列長度
   - 寫 read_hits / last_used / confirmations / first_seen=Created 欄
     （若 access 已有對應欄位且值更大 → 取 max 避免回退）
   - 寫 schema = "atom-access-v2"
3. 從 atom .md 剝除四個計數行（嚴格行首錨定、保留知識欄）
4. 順手：偵測缺 Confidence 欄的 atom → 預設 [臨]（Phase B 會再審）
5. 寫遷移紀錄到 memory/_meta/migration.json 加 access-stats-v2 區塊

執行模式：
  python scripts/migrate-access-stats.py            # 試跑（預設）
  python scripts/migrate-access-stats.py --apply    # 真動

Precondition：跑前確認沒有 active session（避免 hook 同時 increment_read_hits
與 migration 中斷寫產生競態）。本腳本透過 mcp workflow-guardian state file 偵測；
失敗則拒跑提示使用者。

冪等：access 已有 schema=atom-access-v2 且 atom .md 已無計數行 → skip。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent  # ~/.claude
MEMORY_DIR = ROOT / "memory"
META_DIR = MEMORY_DIR / "_meta"
MIGRATION_JSON = META_DIR / "migration.json"

EXCLUDE_FILES = {"MEMORY.md", "_ATOM_INDEX.md", "DESIGN.md"}
EXCLUDE_PREFIXES = ("_CHANGELOG", "SPEC_")
SKIP_DIRS_RELATIVE = {
    "_meta", "_reference", "_staging", "_vectordb", "_distant",
    "templates", "_pending_review",
    "personal",  # V4 user role 宣告，非 atom
    "wisdom",    # Wisdom Engine DESIGN.md，非 atom
}

# 計數欄位 regex（行首嚴格錨定）
RE_READHITS = re.compile(r"^- ReadHits:\s*(\d+)\s*$", re.MULTILINE)
RE_LAST_USED = re.compile(r"^- Last-used:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
RE_CONFIRMATIONS = re.compile(r"^- Confirmations:\s*(\d+)\s*$", re.MULTILINE)
RE_LAST_PROMOTED = re.compile(
    r"^- last_promoted_at:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE,
)
RE_CREATED = re.compile(r"^- Created(?:-at)?:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
RE_CONFIDENCE = re.compile(r"^- Confidence:\s*(.+?)\s*$", re.MULTILINE)

# 剝除的行（順序保留）
STRIP_LINES_RE = re.compile(
    r"^- (?:ReadHits|Last-used|Confirmations|last_promoted_at):.*$\n?",
    re.MULTILINE,
)


def is_atom_file(path: Path) -> bool:
    if path.name in EXCLUDE_FILES:
        return False
    for pfx in EXCLUDE_PREFIXES:
        if path.name.startswith(pfx):
            return False
    parts = set(path.relative_to(MEMORY_DIR).parts[:-1])
    if parts & SKIP_DIRS_RELATIVE:
        return False
    return path.suffix == ".md"


def access_path_for(md_path: Path) -> Path:
    return md_path.with_suffix(".access.json")


def parse_md_counters(text: str) -> Dict[str, Any]:
    """從 atom .md 抽計數欄；回傳 {read_hits, last_used, confirmations, ...}。"""
    out: Dict[str, Any] = {}
    m = RE_READHITS.search(text)
    if m:
        out["read_hits"] = int(m.group(1))
    m = RE_LAST_USED.search(text)
    if m:
        out["last_used"] = m.group(1)
    m = RE_CONFIRMATIONS.search(text)
    if m:
        out["confirmations"] = int(m.group(1))
    m = RE_LAST_PROMOTED.search(text)
    if m:
        out["last_promoted_at"] = m.group(1)
    m = RE_CREATED.search(text)
    if m:
        out["first_seen"] = m.group(1)
    m = RE_CONFIDENCE.search(text)
    if m:
        out["confidence"] = m.group(1).strip()
    return out


def load_access(access_p: Path) -> Dict[str, Any]:
    if not access_p.exists():
        return {}
    try:
        return json.loads(access_p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def normalize_legacy(data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """legacy: confirmations 是陣列 → 搬到 confirmation_events 並轉計數整數。"""
    upgraded = False
    if isinstance(data.get("confirmations"), list):
        events = data["confirmations"]
        data["confirmation_events"] = events
        data["confirmations"] = len(events)
        upgraded = True
    return data, upgraded


def merge_with_max(access: Dict[str, Any], from_md: Dict[str, Any]) -> Dict[str, Any]:
    """合併：md 來源的計數值若大於 access 既存則取 md，避免回退。"""
    out = dict(access)

    # read_hits / confirmations: int max
    for key in ("read_hits", "confirmations"):
        md_val = from_md.get(key)
        if md_val is None:
            continue
        cur = out.get(key)
        if not isinstance(cur, int):
            out[key] = md_val
        else:
            out[key] = max(cur, md_val)

    # last_used: 取較新日期
    md_lu = from_md.get("last_used")
    cur_lu = out.get("last_used")
    if md_lu and (not cur_lu or md_lu > cur_lu):
        out["last_used"] = md_lu

    # last_promoted_at: 同上
    md_lp = from_md.get("last_promoted_at")
    cur_lp = out.get("last_promoted_at")
    if md_lp and (not cur_lp or md_lp > cur_lp):
        out["last_promoted_at"] = md_lp

    # first_seen: 取較舊日期
    md_fs = from_md.get("first_seen")
    cur_fs = out.get("first_seen")
    if md_fs and (not cur_fs or md_fs < cur_fs):
        out["first_seen"] = md_fs

    return out


def ensure_v2_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
    defaults = {
        "schema": "atom-access-v2",
        "read_hits": 0,
        "last_used": None,
        "confirmations": 0,
        "last_promoted_at": None,
        "first_seen": None,
        "timestamps": [],
        "confirmation_events": [],
    }
    out = dict(data)
    for k, v in defaults.items():
        if k not in out:
            out[k] = v
    out["schema"] = "atom-access-v2"
    return out


def strip_md_counters(text: str) -> str:
    return STRIP_LINES_RE.sub("", text)


def add_missing_confidence(text: str, default: str = "[臨]") -> Tuple[str, bool]:
    """偵測 atom 缺 Confidence 欄 → 在 Trigger 行下方插入。"""
    if RE_CONFIDENCE.search(text):
        return text, False
    # 在 Trigger 行後補上
    pat = re.compile(r"(^- Trigger:.*$)", re.MULTILINE)
    if pat.search(text):
        new_text = pat.sub(rf"\1\n- Confidence: {default}", text, count=1)
        return new_text, True
    return text, False


def already_migrated(access: Dict[str, Any], md_text: str) -> bool:
    if access.get("schema") != "atom-access-v2":
        return False
    # 已 migrate 的標誌：access 是 v2 且 .md 已無任一計數行
    if RE_READHITS.search(md_text):
        return False
    if RE_LAST_USED.search(md_text):
        return False
    if RE_CONFIRMATIONS.search(md_text):
        return False
    return True


def check_active_session() -> Tuple[bool, str]:
    """偵測是否有 active session 在跑（避免遷移時與 hook 競態）。

    依靠 workflow-guardian state 檔；找不到 → 視為無 active。
    """
    state_file = ROOT / "memory" / "_workflow_state.json"
    if not state_file.exists():
        return False, ""
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        phase = data.get("phase")
        if phase and phase != "idle":
            sid = data.get("session_id", "")
            return True, f"phase={phase} session={sid}"
    except (OSError, json.JSONDecodeError):
        pass
    return False, ""


def run(apply: bool) -> int:
    print(f"=== migrate-access-stats {'(--apply)' if apply else '(dry-run)'} ===")
    print(f"memory root: {MEMORY_DIR}")

    if apply:
        active, info = check_active_session()
        if active:
            print(f"[ABORT] active session detected ({info});"
                  f" 等該 session 結束再 --apply", file=sys.stderr)
            return 2

    md_files = sorted(MEMORY_DIR.rglob("*.md"))
    candidates = [p for p in md_files if is_atom_file(p)]
    print(f"found {len(candidates)} candidate atom .md files")

    counts = {
        "scanned": 0, "migrated": 0, "skipped_already_v2": 0,
        "confidence_added": 0, "errors": [],
    }

    for md_path in candidates:
        counts["scanned"] += 1
        try:
            text = md_path.read_text(encoding="utf-8-sig")
        except OSError as e:
            counts["errors"].append(f"{md_path}: read failed {e}")
            continue

        access_p = access_path_for(md_path)
        access_raw = load_access(access_p)
        access_data, _ = normalize_legacy(access_raw)

        if already_migrated(access_data, text):
            counts["skipped_already_v2"] += 1
            continue

        # 從 md 抽計數
        md_counters = parse_md_counters(text)
        merged = merge_with_max(access_data, md_counters)
        merged = ensure_v2_defaults(merged)

        # 剝除 md 的計數行
        new_md_text = strip_md_counters(text)

        # 補 Confidence（若缺）
        new_md_text, confidence_added = add_missing_confidence(new_md_text)
        if confidence_added:
            counts["confidence_added"] += 1

        rel = md_path.relative_to(MEMORY_DIR)
        print(f"[{'+' if apply else '?'}] {rel}")
        if apply:
            try:
                # 寫 access.json
                tmp = access_p.with_suffix(access_p.suffix + ".tmp")
                tmp.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
                tmp.replace(access_p)
                # 寫 atom .md（剝除計數行 + 可能補 Confidence）
                if new_md_text != text:
                    tmp2 = md_path.with_suffix(md_path.suffix + ".tmp")
                    tmp2.write_text(new_md_text, encoding="utf-8")
                    tmp2.replace(md_path)
                counts["migrated"] += 1
            except OSError as e:
                counts["errors"].append(f"{md_path}: write failed {e}")

    print()
    print(f"--- summary ---")
    print(f"scanned: {counts['scanned']}")
    print(f"migrated: {counts['migrated']}")
    print(f"skipped (already v2): {counts['skipped_already_v2']}")
    print(f"confidence added: {counts['confidence_added']}")
    print(f"errors: {len(counts['errors'])}")
    for e in counts["errors"]:
        print(f"  {e}")

    if apply:
        # 寫 migration.json
        try:
            mig_data: Dict[str, Any] = {}
            if MIGRATION_JSON.exists():
                mig_data = json.loads(MIGRATION_JSON.read_text(encoding="utf-8"))
            mig_data["access-stats-v2"] = {
                "version": "access-stats-v2",
                "timestamp": time.time(),
                "iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "atoms_scanned": counts["scanned"],
                "atoms_migrated": counts["migrated"],
                "atoms_skipped_already_v2": counts["skipped_already_v2"],
                "confidence_added": counts["confidence_added"],
                "errors": counts["errors"][:20],
            }
            META_DIR.mkdir(parents=True, exist_ok=True)
            MIGRATION_JSON.write_text(
                json.dumps(mig_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"migration record → {MIGRATION_JSON}")
        except OSError as e:
            print(f"[WARN] failed to write migration.json: {e}", file=sys.stderr)
            return 1

    return 0 if not counts["errors"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="真動（不指定預設 dry-run）")
    args = parser.parse_args()
    return run(apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
