#!/usr/bin/env python3
"""
init-roles.py — /init-roles backend

SPEC_ATOM_V4.md §6、§9：專案首次啟用 V4 多職務模式時的引導工作。

動作（依參數執行，單次 call 可組合）：
  --bootstrap-personal      呼叫 wg_roles.bootstrap_personal_dir（建 personal/{user}/role.md + .gitignore）
  --scaffold-roles          在 memory/_roles.md 建 roster 樣板（SPEC §3：成員 + 管理職白名單；與 wg_roles 實際讀取位置一致）
  --add-member USER:ROLES   增/改一筆成員（ROLES 逗號分隔）
  --promote-mgmt USER       將 USER 加入 Management 白名單
  --install-hook            將 ~/.claude/hooks/post-git-pull.sh 複製到 .git/hooks/post-merge 並 chmod +x
  --status                  只回報現況（JSON），不做變動

所有動作均冪等。對每項動作回 JSON：
  {"action": "...", "ok": bool, "changed": bool, "path": "...", ...}

典型呼叫：
  python init-roles.py --project-cwd PATH --bootstrap-personal --scaffold-roles
  python init-roles.py --project-cwd PATH --add-member alice:art
  python init-roles.py --project-cwd PATH --promote-mgmt holylight1979
  python init-roles.py --project-cwd PATH --install-hook
"""

import argparse
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HOOKS_DIR = Path.home() / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))
from wg_paths import find_project_root  # noqa: E402
from wg_roles import (  # noqa: E402
    bootstrap_personal_dir,
    get_current_user,
    is_management,
    load_management_roster,
    load_user_role,
)

HOOK_SOURCE = HOOKS_DIR / "post-git-pull.sh"

ROLES_TEMPLATE = """# Project Role Registry

> V4 多職務共享記憶 — 專案成員與角色登記。入版控，管理職雙向認證的白名單端。

## 成員

| User | Roles |
|---|---|

## Management 白名單

<!-- 加入此白名單的 user，若同時在自己 personal/role.md 也宣告 management，
     才會通過 is_management() 雙向認證，可裁決衝突。 -->

## 角色說明

- programmer: 服務於程式人員工作場景的一切知識
- art: 服務於美術工作場景 — asset、shader、素材處理、圖像工作流
- planner: 服務於企劃工作場景 — 設計規格、流程、需求、平衡
- pm: 專案管理（預設未啟用，依 team 需要開通）
- qa: 測試（預設未啟用）
- management: 管理職（裁決事實衝突，需白名單 + personal 宣告雙認）
"""

def _resolve_root(proj_cwd: str) -> Optional[Path]:
    r = find_project_root(proj_cwd)
    if not r:
        return None
    return r


def _proj_memory_base(root: Path) -> Path:
    return root / ".claude" / "memory"


def _roster_path(root: Path) -> Path:
    """SPEC §3: roster 檔在 memory/_roles.md（與 wg_roles.load_management_roster 一致）。"""
    return _proj_memory_base(root) / "_roles.md"


# ─── Actions ────────────────────────────────────────────────────────────────


def action_status(root: Path, user: str) -> Dict[str, Any]:
    mem = _proj_memory_base(root)
    personal = mem / "personal" / user
    role_md = personal / "role.md"
    roster_md = _roster_path(root)
    gi = root / ".gitignore"
    hook_dst = root / ".git" / "hooks" / "post-merge"

    roster = load_management_roster(str(root))
    role_info = load_user_role(str(root), user)

    return {
        "project_root": str(root),
        "user": user,
        "mem_dir": str(mem),
        "personal_dir_exists": personal.is_dir(),
        "role_md_exists": role_md.is_file(),
        "roster_md_exists": roster_md.is_file(),
        "roster_md_path": str(roster_md),
        "gitignore_has_personal": (
            gi.is_file() and
            any(ln.strip() == ".claude/memory/personal/"
                for ln in gi.read_text(encoding="utf-8").splitlines())
        ),
        "post_merge_hook_installed": hook_dst.is_file(),
        "management_roster": roster,
        "current_user_roles": role_info.get("roles", []),
        "current_user_management_self_declared": role_info.get("management", False),
        "current_user_is_management_effective": is_management(str(root), user),
    }


def action_bootstrap_personal(root: Path, user: str) -> Dict[str, Any]:
    personal = bootstrap_personal_dir(str(root), user)
    if not personal:
        return {"action": "bootstrap-personal", "ok": False,
                "error": "root lacks V4 markers"}
    return {
        "action": "bootstrap-personal",
        "ok": True,
        "path": str(personal),
        "role_md": str(personal / "role.md"),
    }


def action_scaffold_roles(root: Path) -> Dict[str, Any]:
    """SPEC §3: roster 檔在 memory/_roles.md（與 wg_roles 讀取位置一致）。"""
    mem = _proj_memory_base(root)
    mem.mkdir(parents=True, exist_ok=True)
    f = _roster_path(root)
    if f.is_file():
        return {"action": "scaffold-roles", "ok": True,
                "changed": False, "path": str(f), "note": "already exists"}
    f.write_text(ROLES_TEMPLATE, encoding="utf-8")
    return {"action": "scaffold-roles", "ok": True,
            "changed": True, "path": str(f)}


def _edit_roles_md(path: Path, update_fn) -> Dict[str, Any]:
    if not path.is_file():
        return {"ok": False, "error": f"_roles.md not found: {path}"}
    text = path.read_text(encoding="utf-8")
    new_text = update_fn(text)
    if new_text == text:
        return {"ok": True, "changed": False, "path": str(path)}
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "changed": True, "path": str(path)}


def _update_member_row(text: str, user: str, roles: List[str]) -> str:
    """在「## 成員」下的 table 插入或更新 user 行。"""
    lines = text.splitlines()
    out: List[str] = []
    in_members = False
    in_table = False
    table_end = -1
    inserted = False

    roles_str = ", ".join(roles)
    new_row = f"| {user} | {roles_str} |"

    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^##\s+成員", stripped):
            in_members = True
            out.append(line)
            continue
        if in_members and stripped.startswith("## "):
            # 結束 table：若未插入過 user 行，在前一個非空行後插入
            if not inserted:
                # 回找 table 末尾（out 的 tail）
                tail_idx = len(out) - 1
                while tail_idx >= 0 and out[tail_idx].strip() == "":
                    tail_idx -= 1
                out.insert(tail_idx + 1, new_row)
                inserted = True
            in_members = False
            in_table = False
            out.append(line)
            continue
        if in_members:
            if stripped.startswith("|---") or stripped.startswith("| ---"):
                in_table = True
                out.append(line)
                continue
            if in_table and stripped.startswith("|"):
                m = re.match(r"^\|\s*([^\s|]+)\s*\|", stripped)
                if m and m.group(1) == user:
                    out.append(new_row)
                    inserted = True
                    continue
            out.append(line)
            continue
        out.append(line)

    if not inserted:
        # 沒成員區 / 沒 table — 附在檔末
        out.append("")
        out.append("## 成員")
        out.append("")
        out.append("| User | Roles |")
        out.append("|---|---|")
        out.append(new_row)
    text_out = "\n".join(out)
    if not text_out.endswith("\n"):
        text_out += "\n"
    return text_out


def action_add_member(root: Path, user: str, roles: List[str]) -> Dict[str, Any]:
    path = _roster_path(root)
    if not path.is_file():
        action_scaffold_roles(root)
    result = _edit_roles_md(path, lambda t: _update_member_row(t, user, roles))
    result["action"] = "add-member"
    result["user"] = user
    result["roles"] = roles
    return result


def _update_mgmt_whitelist(text: str, user: str) -> str:
    """在「## Management 白名單」下冪等 append `- user`。"""
    lines = text.splitlines()
    out: List[str] = []
    in_section = False
    inserted = False
    seen = False
    section_found = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^##\s+Management", stripped, re.IGNORECASE):
            in_section = True
            section_found = True
            out.append(line)
            continue
        if in_section and stripped.startswith("## "):
            if not seen:
                # 回找結束前最後一個列表項位置
                insert_at = len(out)
                while insert_at > 0 and out[insert_at - 1].strip() == "":
                    insert_at -= 1
                out.insert(insert_at, f"- {user}")
                inserted = True
            in_section = False
            out.append(line)
            continue
        if in_section:
            m = re.match(r"^-\s+(\S+)", stripped)
            if m and m.group(1).strip() == user:
                seen = True
        out.append(line)

    if in_section and not seen:
        insert_at = len(out)
        while insert_at > 0 and out[insert_at - 1].strip() == "":
            insert_at -= 1
        out.insert(insert_at, f"- {user}")
        inserted = True

    if not section_found:
        out.append("")
        out.append("## Management 白名單")
        out.append("")
        out.append(f"- {user}")
        inserted = True

    text_out = "\n".join(out)
    if not text_out.endswith("\n"):
        text_out += "\n"
    return text_out if (inserted or seen) else text


def action_promote_mgmt(root: Path, user: str) -> Dict[str, Any]:
    path = _roster_path(root)
    if not path.is_file():
        action_scaffold_roles(root)
    result = _edit_roles_md(path, lambda t: _update_mgmt_whitelist(t, user))
    result["action"] = "promote-mgmt"
    result["user"] = user
    return result


# ─── V4.1: Privacy check [F21] ────────────────────────────────────────────


_CLOUD_SYNC_PATTERNS = [
    # (label, path fragments to check)
    ("Dropbox", ["Dropbox"]),
    ("iCloud", ["iCloud", "iCloudDrive", "com~apple~CloudDocs"]),
    ("OneDrive", ["OneDrive"]),
    ("Google Drive", ["Google Drive", "My Drive", "GoogleDrive"]),
]


def action_privacy_check(root: Path, user: str) -> Dict[str, Any]:
    """[F21] Scan if personal/ dir sits under a cloud-sync path. Warn only."""
    mem = _proj_memory_base(root)
    personal_dir = mem / "personal"
    auto_dir = mem / "personal" / "auto" / user

    warnings: List[str] = []
    personal_abs = str(personal_dir.resolve()).replace("\\", "/")

    # Check cloud sync paths
    for label, fragments in _CLOUD_SYNC_PATTERNS:
        for frag in fragments:
            if frag.lower() in personal_abs.lower():
                warnings.append(
                    f"personal/ 位於 {label} 同步路徑下，自動萃取的個人決策可能被雲端同步。"
                    f"建議將 personal/ 加入 {label} 排除清單。"
                )
                break

    # Check .gitignore for personal/
    gitignore = root / ".gitignore"
    gitignore_ok = False
    if gitignore.is_file():
        try:
            gi_text = gitignore.read_text(encoding="utf-8")
            for line in gi_text.splitlines():
                stripped = line.strip()
                if stripped in (
                    ".claude/memory/personal/",
                    ".claude/memory/personal",
                    "personal/",
                ):
                    gitignore_ok = True
                    break
        except (OSError, UnicodeDecodeError):
            pass
    if not gitignore_ok:
        warnings.append(
            ".gitignore 尚未包含 .claude/memory/personal/，"
            "個人 atom 可能被 git 追蹤。建議加入排除。"
        )

    # Check SVN svn:ignore (if SVN repo)
    svn_dir = root / ".svn"
    if svn_dir.is_dir():
        try:
            import subprocess
            result = subprocess.run(
                ["svn", "propget", "svn:ignore", str(mem), "--non-interactive"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                svn_ignores = result.stdout.strip().splitlines()
                if not any("personal" in line for line in svn_ignores):
                    warnings.append(
                        "SVN svn:ignore 尚未排除 personal/，個人 atom 可能被 SVN 追蹤。"
                    )
        except Exception:
            pass  # svn not available or timeout

    return {
        "action": "privacy-check",
        "ok": True,
        "personal_path": str(personal_dir),
        "warnings": warnings,
        "warning_count": len(warnings),
        "gitignore_has_personal": gitignore_ok,
    }


def action_install_hook(root: Path) -> Dict[str, Any]:
    if not HOOK_SOURCE.is_file():
        return {"action": "install-hook", "ok": False,
                "error": f"source hook missing: {HOOK_SOURCE}"}
    git_dir = root / ".git"
    if not git_dir.is_dir():
        return {"action": "install-hook", "ok": False,
                "error": f"not a git repo: {root}"}
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    dst = hooks_dir / "post-merge"
    src_text = HOOK_SOURCE.read_text(encoding="utf-8")
    changed = True
    if dst.is_file():
        try:
            if dst.read_text(encoding="utf-8") == src_text:
                changed = False
        except (OSError, UnicodeDecodeError):
            pass
    if changed:
        dst.write_text(src_text, encoding="utf-8")
    try:
        st = dst.stat().st_mode
        dst.chmod(st | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as e:
        return {"action": "install-hook", "ok": False,
                "error": f"chmod failed: {e}", "path": str(dst)}
    return {"action": "install-hook", "ok": True,
            "changed": changed, "path": str(dst)}


# ─── CLI ────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description="V4 /init-roles backend")
    ap.add_argument("--project-cwd", required=True)
    ap.add_argument("--user", default=None,
                    help="Override current user (defaults to CLAUDE_USER/os login)")
    ap.add_argument("--bootstrap-personal", action="store_true")
    ap.add_argument("--scaffold-roles", action="store_true",
                    help="Create memory/_roles.md with member/whitelist template")
    ap.add_argument("--add-member", metavar="USER:ROLES", default=None,
                    help="逗號分隔 roles，例 alice:art 或 bob:programmer,management")
    ap.add_argument("--promote-mgmt", metavar="USER", default=None)
    ap.add_argument("--install-hook", action="store_true")
    ap.add_argument("--privacy-check", action="store_true",
                    help="[V4.1 F21] Scan cloud-sync paths, .gitignore, SVN ignore for personal/")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    root = _resolve_root(args.project_cwd)
    if not root:
        print(json.dumps({"error": "no project root at cwd",
                          "cwd": args.project_cwd}))
        sys.exit(2)

    user = args.user or get_current_user()
    results: List[Dict[str, Any]] = []

    if args.status:
        print(json.dumps(action_status(root, user), ensure_ascii=False, indent=2))
        return

    if args.bootstrap_personal:
        results.append(action_bootstrap_personal(root, user))
    if args.scaffold_roles:
        results.append(action_scaffold_roles(root))
    if args.add_member:
        if ":" not in args.add_member:
            results.append({"action": "add-member", "ok": False,
                            "error": "format must be USER:ROLES"})
        else:
            u, roles_str = args.add_member.split(":", 1)
            roles = [r.strip() for r in roles_str.split(",") if r.strip()]
            results.append(action_add_member(root, u.strip(), roles))
    if args.promote_mgmt:
        results.append(action_promote_mgmt(root, args.promote_mgmt.strip()))
    if args.install_hook:
        results.append(action_install_hook(root))
    if args.privacy_check:
        results.append(action_privacy_check(root, user))

    # V4.1: auto-run privacy check when bootstrapping (last step of init flow)
    if args.bootstrap_personal and not args.privacy_check:
        results.append(action_privacy_check(root, user))

    if not results:
        results.append({"error": "no action specified; try --status or --help"})

    print(json.dumps({"user": user, "project_root": str(root),
                      "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
