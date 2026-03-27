#!/usr/bin/env python3
"""install.py — 原子記憶系統一鍵安裝腳本

Usage:
  python ~/.claude/install.py

執行後，下次開啟 Claude Code 即可直接使用原子記憶系統。

Steps:
  1. 前置檢查 (Python 版本、Node.js、目錄)
  2. npm 全域套件安裝
  3. ~/.claude.json 合併 (mcpServers)
  4. BOOTSTRAP 設定 (IDENTITY/USER 初始化)
  5. 驗證報告
"""

import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────
CLAUDE_DIR = Path.home() / ".claude"
CLAUDE_JSON = Path.home() / ".claude.json"
TEMPLATE_FILE = CLAUDE_DIR / "mcp-servers.template.json"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"

IS_WINDOWS = sys.platform == "win32"

# ── ANSI Colors ───────────────────────────────────────────────────────────
def _enable_ansi():
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7
            )
            return True
        except Exception:
            return False
    return True

_USE_COLOR = _enable_ansi()

def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text

def ok(msg):      print(f"  {_c('✓', '92')} {msg}")
def warn(msg):    print(f"  {_c('!', '93')} {msg}")
def fail(msg):    print(f"  {_c('✗', '91')} {msg}")
def info(msg):    print(f"  {_c('→', '96')} {msg}")
def section(t):   print(f"\n{_c(t, '1;96')}\n{'─' * 52}")


def ask(prompt, default="y"):
    """互動式 yes/no 提示，回傳 bool。"""
    yn = "[Y/n]" if default == "y" else "[y/N]"
    try:
        resp = input(f"  {prompt} {yn} ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return default == "y"
    return (resp in ("y", "yes")) if resp else (default == "y")


# ── JSON Helpers ──────────────────────────────────────────────────────────
def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Node / npm Helpers ────────────────────────────────────────────────────
def _find_node():
    """Return absolute path to node executable, or None."""
    if IS_WINDOWS:
        for base in [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ]:
            if base:
                p = Path(base) / "nodejs" / "node.exe"
                if p.exists():
                    return str(p)
    cmd = ["where", "node"] if IS_WINDOWS else ["which", "node"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            first = r.stdout.strip().splitlines()[0]
            if first:
                return first
    except Exception:
        pass
    return None


def _npm_global_prefix():
    """Return npm global node_modules parent directory."""
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        if appdata:
            p = Path(appdata) / "npm"
            if p.exists():
                return str(p)
    try:
        r = subprocess.run(
            ["npm", "prefix", "-g"], capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _resolve_entry(sdef, npm_prefix):
    """Resolve JS entry path. Returns (abs_path_str, exists_bool)."""
    if "entry_absolute" in sdef:
        p = Path(sdef["entry_absolute"].replace("{claude_dir}", str(CLAUDE_DIR)))
        return str(p), p.exists()
    if npm_prefix and "entry_relative" in sdef:
        p = Path(npm_prefix) / "node_modules" / sdef["entry_relative"]
        return str(p), p.exists()
    return None, False


def _build_server_entry(sdef, node_cmd, entry_path):
    """Build a mcpServers JSON entry dict."""
    entry = {}
    if sdef.get("type"):
        entry["type"] = sdef["type"]
    entry["command"] = node_cmd
    entry["args"] = [entry_path]
    if "env" in sdef:
        entry["env"] = sdef["env"]
    return entry


# ── Step 1: 前置檢查 ───────────────────────────────────────────────────────
def step_prerequisites():
    section("Step 1 — 前置檢查")
    issues = []

    # Python 版本
    pv = sys.version_info
    if pv >= (3, 10):
        ok(f"Python {pv.major}.{pv.minor}.{pv.micro}")
    else:
        fail(f"Python {pv.major}.{pv.minor} — 需要 ≥ 3.10")
        issues.append("python_version")

    # 作業系統
    if IS_WINDOWS:
        ok("作業系統: Windows")
    elif sys.platform == "darwin":
        ok("作業系統: macOS")
    else:
        ok(f"作業系統: Linux ({sys.platform})")

    # ~/.claude 目錄
    if CLAUDE_DIR.exists():
        ok(f"~/.claude 目錄: {CLAUDE_DIR}")
    else:
        fail(f"~/.claude 不存在 — 請先 git clone <repo> ~/.claude")
        issues.append("claude_dir")

    # Node.js
    node = _find_node()
    if node:
        ok(f"Node.js: {node}")
    else:
        warn("Node.js 未找到")
        if IS_WINDOWS:
            warn("安裝指令: winget install OpenJS.NodeJS.LTS")
        else:
            warn("安裝: https://nodejs.org/")
        warn("安裝後重新執行 install.py")
        issues.append("nodejs")

    return issues


# ── Step 2: npm 全域套件安裝 ────────────────────────────────────────────────
def step_npm_install(skip):
    section("Step 2 — npm 全域套件安裝")

    if skip:
        warn("Node.js 未安裝，跳過此步驟")
        return []

    if not TEMPLATE_FILE.exists():
        warn(f"找不到 {TEMPLATE_FILE}，跳過")
        return []

    template = _load_json(TEMPLATE_FILE)
    npm_prefix = _npm_global_prefix()
    to_install = []

    for name, sdef in template.get("servers", {}).items():
        pkg = sdef.get("npm_package")
        if not pkg:
            info(f"{name} — 內建 (無需 npm)")
            continue
        _, exists = _resolve_entry(sdef, npm_prefix)
        if exists:
            ok(f"{name} ({pkg}) — 已安裝")
        else:
            to_install.append((name, pkg))

    if not to_install:
        ok("所有 npm 套件已就緒")
        return []

    print()
    info("待安裝套件：")
    for name, pkg in to_install:
        print(f"      {pkg}  ({name})")

    if not ask(f"\n  安裝以上 {len(to_install)} 個套件？"):
        warn("跳過 npm 安裝（可稍後手動執行）")
        return [pkg for _, pkg in to_install]

    failed = []
    for name, pkg in to_install:
        info(f"安裝 {pkg} ...")
        try:
            r = subprocess.run(
                ["npm", "i", "-g", pkg],
                capture_output=True, text=True, timeout=180,
            )
            if r.returncode == 0:
                ok(f"{name} ({pkg}) — 安裝成功")
            else:
                fail(f"{name} ({pkg}) — 安裝失敗")
                stderr = (r.stderr or "").strip()
                if stderr:
                    print(f"      {stderr[:300]}")
                failed.append(pkg)
        except subprocess.TimeoutExpired:
            fail(f"{name} ({pkg}) — 逾時 (>3 分鐘)")
            failed.append(pkg)
        except Exception as e:
            fail(f"{name} ({pkg}) — 例外: {e}")
            failed.append(pkg)

    return failed


# ── Step 3: ~/.claude.json 合併 ─────────────────────────────────────────────
def step_merge_claude_json():
    section("Step 3 — ~/.claude.json 合併")

    if not TEMPLATE_FILE.exists():
        warn(f"找不到 {TEMPLATE_FILE}，跳過 MCP 設定")
        return

    template = _load_json(TEMPLATE_FILE)
    node = _find_node()
    node_cmd = node or "node"   # fallback: rely on PATH
    npm_prefix = _npm_global_prefix()

    # 建立 ~/.claude.json（若不存在）
    if not CLAUDE_JSON.exists():
        _save_json(CLAUDE_JSON, {"mcpServers": {}, "_mcpTemplateVersion": 0})
        ok(f"~/.claude.json 已建立: {CLAUDE_JSON}")

    claude = _load_json(CLAUDE_JSON)
    if not isinstance(claude, dict):
        claude = {}

    current_servers = claude.get("mcpServers", {})
    stored_ver = claude.get("_mcpTemplateVersion", 0)
    tmpl_ver = template.get("_version", 0)
    changed = False

    for name, sdef in template.get("servers", {}).items():
        entry_path, exists = _resolve_entry(sdef, npm_prefix)

        if not exists:
            # 套件未安裝 / 絕對路徑不存在
            pkg = sdef.get("npm_package")
            if pkg:
                warn(f"{name} — 套件未安裝，待下次 SessionStart 自動補上")
            else:
                warn(f"{name} — entry 不存在: {entry_path}")
            continue

        server_entry = _build_server_entry(sdef, node_cmd, entry_path)

        if name not in current_servers:
            current_servers[name] = server_entry
            changed = True
            ok(f"新增 MCP server: {name}")
        elif tmpl_ver > stored_ver:
            current_servers[name] = server_entry
            changed = True
            ok(f"更新 MCP server: {name} (template v{stored_ver} → v{tmpl_ver})")
        else:
            ok(f"保留 MCP server: {name}")

    if changed:
        claude["mcpServers"] = current_servers
        claude["_mcpTemplateVersion"] = tmpl_ver
        _save_json(CLAUDE_JSON, claude)
        ok("~/.claude.json 已儲存")
    else:
        ok("~/.claude.json 無需變更")


# ── Step 4: BOOTSTRAP 設定 ──────────────────────────────────────────────────
def step_bootstrap():
    section("Step 4 — 身份設定 (BOOTSTRAP)")

    try:
        username = getpass.getuser()
    except Exception:
        username = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    info(f"目前使用者: {username}")

    _setup_identity_file(username, "IDENTITY")
    _setup_identity_file(username, "USER")

    print()
    info("提示：開啟 Claude Code 後若 IDENTITY.md / USER.md 為空，")
    info("      系統會引導你完成身份設定（BOOTSTRAP 流程）。")


def _setup_identity_file(username, prefix):
    """建立 {prefix}-{username}.md（從 template）並同步到 {prefix}.md。"""
    per_user = CLAUDE_DIR / f"{prefix}-{username}.md"
    template  = CLAUDE_DIR / f"{prefix}.template.md"
    target    = CLAUDE_DIR / f"{prefix}.md"

    # 從 template 建立 per-user 檔（不覆蓋已存在）
    if not per_user.exists():
        if template.exists():
            shutil.copy2(template, per_user)
            info(f"已從 template 建立 {per_user.name}")
        else:
            warn(f"找不到 {template.name}，{per_user.name} 未建立")

    # 同步到 target（不覆蓋已有實質內容的 target）
    if per_user.exists():
        target_size = target.stat().st_size if target.exists() else 0
        per_user_size = per_user.stat().st_size
        if not target.exists() or target_size < 20:
            shutil.copy2(per_user, target)

    # 報告狀態
    if target.exists() and target.stat().st_size > 50:
        ok(f"{prefix}.md 已設定 ({target.stat().st_size} bytes)")
    else:
        warn(f"{prefix}.md 尚未填寫 — 請編輯 {per_user.name}")


# ── Step 5: 驗證 ────────────────────────────────────────────────────────────
def step_verify():
    section("Step 5 — 驗證報告")
    results = {}

    # ~/.claude.json mcpServers
    if CLAUDE_JSON.exists():
        data = _load_json(CLAUDE_JSON)
        if data.get("mcpServers"):
            ok("~/.claude.json — mcpServers 有值")
            results["claude_json"] = True
        else:
            warn("~/.claude.json — mcpServers 為空")
            results["claude_json"] = False
    else:
        fail("~/.claude.json 不存在")
        results["claude_json"] = False

    # npm 套件
    npm_prefix = _npm_global_prefix()
    template = _load_json(TEMPLATE_FILE) if TEMPLATE_FILE.exists() else {}
    npm_all_ok = True
    for name, sdef in template.get("servers", {}).items():
        if not sdef.get("npm_package"):
            continue
        _, exists = _resolve_entry(sdef, npm_prefix)
        if exists:
            ok(f"npm: {name}")
        else:
            warn(f"npm: {name} — 未安裝")
            npm_all_ok = False
    results["npm_packages"] = npm_all_ok

    # hooks/ 腳本
    hooks_ok = True
    for hook in ["workflow-guardian.py", "ensure-mcp.py", "user-init.sh"]:
        p = CLAUDE_DIR / "hooks" / hook
        if p.exists():
            ok(f"hooks/{hook}")
        else:
            fail(f"hooks/{hook} — 不存在")
            hooks_ok = False
    results["hooks"] = hooks_ok

    # settings.json SessionStart 包含 ensure-mcp.py
    if SETTINGS_FILE.exists():
        text = SETTINGS_FILE.read_text(encoding="utf-8")
        if "ensure-mcp.py" in text:
            ok("settings.json — SessionStart 包含 ensure-mcp.py")
            results["settings"] = True
        else:
            warn("settings.json — 未找到 ensure-mcp.py hook")
            results["settings"] = False
    else:
        fail("settings.json 不存在")
        results["settings"] = False

    passed = sum(v for v in results.values())
    total = len(results)
    print()
    if passed == total:
        print(f"  {_c(f'✓ 全部通過 ({passed}/{total})', '1;92')}")
    else:
        print(f"  {_c(f'部分通過 {passed}/{total}', '1;93')}")

    return passed == total


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    print(f"\n{_c('原子記憶系統 — 安裝程式', '1;96')}")
    print("=" * 52)
    print(f"  安裝目錄 : {CLAUDE_DIR}")
    print(f"  設定檔   : {CLAUDE_JSON}")

    # ── Step 1: 前置檢查
    issues = step_prerequisites()

    if "claude_dir" in issues:
        print(f"\n{_c('安裝中止', '1;91')}: 請先 git clone <repo> ~/.claude")
        sys.exit(1)
    if "python_version" in issues:
        print(f"\n{_c('安裝中止', '1;91')}: Python 版本不符")
        sys.exit(1)

    skip_nodejs = "nodejs" in issues

    # ── Step 2: npm 安裝
    failed_pkgs = step_npm_install(skip_nodejs)

    # ── Step 3: ~/.claude.json 合併
    step_merge_claude_json()

    # ── Step 4: Bootstrap
    step_bootstrap()

    # ── Step 5: 驗證
    all_ok = step_verify()

    # ── 最終摘要
    print(f"\n{'=' * 52}")
    if all_ok:
        print(f"  {_c('安裝完成！', '1;92')} 下次開啟 Claude Code 即可使用原子記憶系統。")
    else:
        print(f"  {_c('安裝完成（部分項目待處理）', '1;93')}")
        if skip_nodejs:
            print(f"\n  待辦：安裝 Node.js 後重新執行 install.py")
            if IS_WINDOWS:
                print(f"         winget install OpenJS.NodeJS.LTS")
        if failed_pkgs:
            print(f"\n  npm 安裝失敗，可手動執行：")
            print(f"    npm i -g {' '.join(failed_pkgs)}")
    print()


if __name__ == "__main__":
    main()
