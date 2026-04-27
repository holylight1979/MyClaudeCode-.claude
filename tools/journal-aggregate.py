#!/usr/bin/env python3
"""journal-aggregate.py — 從 episodic atoms + workflow state 彙整工作日誌

Usage:
    python journal-aggregate.py              # 今天的日誌
    python journal-aggregate.py 2026-04-07   # 指定日期
    python journal-aggregate.py week         # 本週週報
    python journal-aggregate.py week 2026-04-07  # 含該日期的那週
    python journal-aggregate.py month        # 本月月報
    python journal-aggregate.py month 2026-04    # 指定月份月報
    python journal-aggregate.py range 2026-04-01 2026-04-10  # 任意日期範圍（逐日產）
    python journal-aggregate.py --cleanup    # 僅清理過期日誌
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows cp950 → UTF-8
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

CLAUDE_DIR = Path.home() / ".claude"
DEFAULT_JOURNALS_DIR = CLAUDE_DIR / "journals"
WORKFLOW_DIR = CLAUDE_DIR / "workflow"
RETENTION_DAYS = 60

def _load_env_from_settings(name: str) -> str | None:
    """Fallback：os.environ 沒有時，從 ~/.claude/settings*.json 的 env 區段讀。"""
    for fn in ("settings.local.json", "settings.json"):
        p = Path.home() / ".claude" / fn
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            v = data.get("env", {}).get(name)
            if v:
                return v
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _env(name: str, default: str | None = None) -> str | None:
    """環境變數讀取：os.environ → settings*.json env → default。"""
    v = os.environ.get(name)
    if v:
        return v
    v = _load_env_from_settings(name)
    return v if v is not None else default


def _resolve_journal_dirs() -> list[Path]:
    """日誌儲存路徑解析。優先序：
    1. CLAUDE_JOURNAL_DIRS（新，多路徑 pathsep 分隔，第一個為主、其餘複製）
    2. CLAUDE_JOURNAL_OBSIDIAN_DIR（向後相容，視為單一主路徑）
    3. ~/.claude/journals/（預設 fallback）
    """
    multi = _env("CLAUDE_JOURNAL_DIRS")
    if multi:
        dirs: list[Path] = []
        seen: set[str] = set()
        for p in multi.split(os.pathsep):
            p = p.strip()
            if p and p not in seen:
                seen.add(p)
                dirs.append(Path(p))
        if dirs:
            return dirs
    legacy = _env("CLAUDE_JOURNAL_OBSIDIAN_DIR")
    if legacy:
        return [Path(legacy)]
    return [DEFAULT_JOURNALS_DIR]


JOURNAL_DIRS = _resolve_journal_dirs()
JOURNAL_SUBDIR = {"daily": "日報", "weekly": "週報", "monthly": "月報"}
JOURNALS_DIR = JOURNAL_DIRS[0]  # 主要儲存（向後相容變數名）

VCS_TIMEOUT = 10

_WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]

# Episodic 知識行中屬於統計類的 pattern（日誌中跳過）
_STAT_PATTERNS = ("閱讀 ", "閱讀區域", "版控查詢", "覆轍信號", "引用 atoms")

# HTML/XML 標籤 + 註解（避免 catclaw_cli_bridge 訊息標頭未閉合 tag 汙染 markdown 渲染）
_HTML_RE = re.compile(r"<!--.*?-->|<[^>]+>", re.DOTALL)

# 「我的增補」heading：重產時整段內容（heading 之後到下一個 heading 之前）保留
KEEPOUT_HEADING = "### 我的增補"
_KEEPOUT_RE = re.compile(
    r"(^" + re.escape(KEEPOUT_HEADING) + r"\s*\n)(.*?)(?=^##\s|^###\s|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _strip_html(s: str) -> str:
    """移除 HTML/XML tag 與註解，壓縮空白。
    殘留的孤立 `<`（未閉合 tag/註解）視為汙染，從該位置截掉到結尾。"""
    if not s:
        return s
    s = _HTML_RE.sub("", s)
    idx = s.find("<")
    if idx >= 0:
        s = s[:idx]
    return re.sub(r"\s+", " ", s).strip()


def _extract_keepout(path: Path) -> str | None:
    """從既有檔抽出『### 我的增補』 heading 之後到下個 heading 之前的全部內容。
    清掉舊版的 `<!-- ai-keepout:start/end -->` 標記殘留（一次性遷移）。"""
    if not path.exists():
        return None
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _KEEPOUT_RE.search(existing)
    if not m:
        return None
    body = re.sub(r"<!--\s*ai-keepout:(?:start|end)\s*-->\s*\n?", "", m.group(2))
    return body


def _apply_keepout(content: str, preserved: str | None) -> str:
    """把保留內容塞回新 content 的『### 我的增補』段（取代預設空段）。"""
    if preserved is None:
        return content
    return _KEEPOUT_RE.sub(
        lambda m: m.group(1) + preserved,
        content,
        count=1,
    )


# ── Episodic Atoms ──────────────────────────────────────────────

def _find_episodic_dirs():
    """回傳所有 episodic 目錄 [(label, Path), ...]"""
    dirs = []
    g = CLAUDE_DIR / "memory" / "episodic"
    if g.exists():
        dirs.append(("global", g))
    proj = CLAUDE_DIR / "projects"
    if proj.exists():
        for p in proj.iterdir():
            ep = p / "memory" / "episodic"
            if ep.exists():
                dirs.append((p.name, ep))
    return dirs


def _parse_episodic(stem: str, content: str) -> dict:
    """解析 episodic atom → {workspace, summary, work_areas, files_mod, files_mod_n, knowledge, intent}"""
    info = {"stem": stem, "workspace": "", "summary": "",
            "work_areas": "", "files_mod": "", "files_mod_n": 0,
            "knowledge": [], "intent": ""}

    m = re.match(r"episodic-\d{8}-(.+?)(?:-\d+)?$", stem)
    if m:
        info["workspace"] = m.group(1)

    # 摘要（清掉 HTML/XML tag，避免渲染汙染）
    m = re.search(r"## 摘要\s*\n(.+?)(?=\n## |\Z)", content, re.DOTALL)
    if m:
        info["summary"] = _strip_html(m.group(1))

    # 知識
    m = re.search(r"## 知識\s*\n(.+?)(?=\n## |\Z)", content, re.DOTALL)
    if m:
        for line in m.group(1).strip().splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            if "工作區域" in line:
                info["work_areas"] = line
            elif "修改" in line and "個檔案" in line:
                info["files_mod"] = line
                nm = re.search(r"修改 (\d+) 個", line)
                if nm:
                    info["files_mod_n"] = int(nm.group(1))
            elif not any(p in line for p in _STAT_PATTERNS):
                info["knowledge"].append(line)

    # 關聯（意圖分布）
    m = re.search(r"## 關聯\s*\n(.+?)(?=\n## |\Z)", content, re.DOTALL)
    if m:
        for line in m.group(1).strip().splitlines():
            if "意圖分布" in line:
                info["intent"] = line.strip().removeprefix("- ")
                break

    return info


def _dedup_episodic(atoms: list[dict]) -> list[dict]:
    """同 workspace 的增量快照只保留最完整的那筆（files_mod_n 最大）"""
    best = {}
    for a in atoms:
        ws = a["workspace"]
        if ws not in best or a["files_mod_n"] >= best[ws]["files_mod_n"]:
            best[ws] = a
    return list(best.values())


def scan_episodic(target_date: str) -> list[dict]:
    """掃描指定日期的所有 episodic atoms（已去重）"""
    dc = target_date.replace("-", "")
    prefix = f"episodic-{dc}-"
    atoms = []
    for _label, d in _find_episodic_dirs():
        for f in sorted(d.glob(f"{prefix}*.md")):
            try:
                atoms.append(_parse_episodic(f.stem, f.read_text(encoding="utf-8")))
            except Exception:
                pass
    return _dedup_episodic(atoms)


def scan_episodic_range(start: str, end: str) -> dict[str, list[dict]]:
    """掃描日期範圍的 episodic atoms，回傳 {date: [atoms]}"""
    by_date = defaultdict(list)
    for _label, d in _find_episodic_dirs():
        if not d.exists():
            continue
        for f in sorted(d.glob("episodic-*.md")):
            m = re.match(r"episodic-(\d{8})-", f.name)
            if not m:
                continue
            dc = m.group(1)
            fdate = f"{dc[:4]}-{dc[4:6]}-{dc[6:8]}"
            if start <= fdate <= end:
                try:
                    by_date[fdate].append(
                        _parse_episodic(f.stem, f.read_text(encoding="utf-8"))
                    )
                except Exception:
                    pass
    # dedup per day
    return {d: _dedup_episodic(atoms) for d, atoms in by_date.items()}


# ── Workflow State Files ────────────────────────────────────────

def _project_name(cwd: str) -> str:
    parts = cwd.replace("\\", "/").rstrip("/").split("/")
    if len(parts) >= 2 and parts[-1] in ("Develop", "Server", "Client"):
        return f"{parts[-2]}.{parts[-1]}"
    return parts[-1] if parts else "unknown"


def _mod_paths(mod: list) -> list[str]:
    """從 modified_files 取出 path 字串清單。"""
    paths = []
    for m in mod:
        if isinstance(m, dict):
            p = m.get("path", "")
        else:
            p = str(m)
        if p:
            paths.append(p)
    return paths


def _state_record(data: dict) -> dict:
    sess = data["session"]
    started = sess.get("started_at", "")
    topic = data.get("topic_tracker", {})
    kq = data.get("knowledge_queue", [])
    mod_paths = list(dict.fromkeys(_mod_paths(data.get("modified_files", []))))
    cwd = sess.get("cwd", "")
    return {
        "id": sess.get("id", "")[:8],
        "project": _project_name(cwd),
        "cwd": cwd,
        "start": started[11:16],
        "end": data.get("ended_at", "")[11:16] if data.get("ended_at") else "…",
        "prompts": topic.get("prompt_count", 0),
        "intent": topic.get("intent_distribution", {}),
        "modified_files": mod_paths,
        "files_modified": len(mod_paths),
        "knowledge": [k.get("content", "")[:200] for k in kq],
    }


def scan_states(target_date: str) -> list[dict]:
    """掃描當天仍存在的 state files"""
    if not WORKFLOW_DIR.exists():
        return []
    results = []
    for f in WORKFLOW_DIR.glob("state-*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            started = data.get("session", {}).get("started_at", "")
            if started[:10] != target_date:
                continue
            results.append(_state_record(data))
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return sorted(results, key=lambda s: s["start"])


def scan_states_range(start: str, end: str) -> dict[str, list[dict]]:
    """掃描日期範圍內仍存在的 state files"""
    if not WORKFLOW_DIR.exists():
        return {}
    by_date = defaultdict(list)
    for f in WORKFLOW_DIR.glob("state-*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            started = data.get("session", {}).get("started_at", "")
            sdate = started[:10]
            if not (start <= sdate <= end):
                continue
            by_date[sdate].append(_state_record(data))
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return dict(by_date)


# ── Daily Journal Builder ──────────────────────────────────────

def _truncate(s: str, n: int = 60) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def _project_summary_line(project: str, sessions: list[dict],
                         commits: list[tuple[str, str]],
                         unique_files: int) -> str:
    if commits:
        msgs = "；".join(_truncate(m) for _, m in commits[:4])
        suffix = f"…等 {len(commits)} 個" if len(commits) > 4 else ""
        return f"- **{project}** ({len(commits)} commits): {msgs}{suffix}"
    if unique_files > 0:
        return f"- **{project}**: 改 {unique_files} 檔（未 commit）"
    prompts = sum(s["prompts"] for s in sessions)
    if prompts > 0:
        return f"- **{project}**: {prompts} prompts（純討論）"
    return f"- **{project}**: 閒置"


def _llm_summary(proj_data: list, active_days: int | None = None) -> str:
    """呼叫本地 Ollama 產生 2-4 句話速覽。失敗回 ""。"""
    try:
        sys.path.insert(0, str(Path.home() / ".claude" / "tools"))
        from ollama_client import OllamaClient, OllamaBackend  # type: ignore
    except ImportError:
        return ""

    # 直接用本地 backend，不試遠端（避免 timeout 拖長 journal 產出）
    model = _env("CLAUDE_JOURNAL_LLM_MODEL", "qwen3:1.7b")
    local_backend = OllamaBackend(
        name="local", base_url="http://127.0.0.1:11434", auth=None,
        llm_model=model, embedding_model=None, priority=1,
        enabled=True, think=False, llm_num_predict=512,
    )
    client = OllamaClient([local_backend])

    # 組裝精簡 context
    blocks: list[str] = []
    for item in proj_data:
        if len(item) != 4:
            continue
        _key, g, commits, _vcs = item
        parts = [f"[{g['project']}]"]
        if commits:
            for cid, msg in commits[:6]:
                parts.append(f"  commit: {msg}")
        else:
            files = {f for s in g["sessions"] for f in s["modified_files"]}
            if files:
                parts.append(f"  改檔(未commit): {len(files)} 檔")
                for fp in list(files)[:5]:
                    parts.append(f"    - {Path(fp).name}")
        # top knowledge
        kq = []
        for s in g["sessions"]:
            kq.extend(s["knowledge"][:3])
        for a in g["atoms"]:
            kq.extend(a.get("knowledge", [])[:2])
        seen: set = set()
        kq_unique = []
        for k in kq:
            ck = _clean_knowledge(k)
            if ck and ck not in seen:
                seen.add(ck)
                kq_unique.append(ck)
        for k in kq_unique[:3]:
            parts.append(f"  知識: {_truncate(k, 100)}")
        blocks.append("\n".join(parts))

    context_text = "\n\n".join(blocks)
    period_hint = f"這是一份 {active_days} 天的區間彙總。" if active_days else "這是今日的工作記錄。"
    prompt = f"""{period_hint}請用繁體中文寫一段 2-4 句的「做了什麼」速覽。

資料：
{context_text}

嚴格規則（違反者視為錯誤輸出）：
1. 直接輸出純文字段落，禁止條列、禁止 markdown、禁止項目符號 -
2. 禁止任何前言（如「以下」「總結」「工程主管」「請注意」）
3. 禁止任何時間詞開頭（如「今天」「本次」「這次」）
4. 全部寫在同一段，句子之間用句號分隔
5. 每個專案一句話，不超過 4 句總長
6. 只寫做了什麼、產出什麼，不寫統計數字
"""
    try:
        result = client.generate(prompt, timeout=20, think=False)
        return _strip_preamble((result or "").strip())
    except Exception:
        return ""


def _strip_preamble(text: str) -> str:
    """移除 LLM 常見前言 + 條列前綴。"""
    text = re.sub(r"^<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    # 開頭前言只刪第一次
    for pattern in [
        r"^工程主管.*?[:：]\s*\n?",
        r"^以下是?.*?[:：]\s*\n?",
        r"^(總結|速覽|摘要).*?[:：]\s*\n?",
    ]:
        text = re.sub(pattern, "", text, count=1)
    # 「做了什麼：」可能出現多次，全刪
    text = re.sub(r"做了什麼[:：]\s*", "", text)
    # 把條列轉成段落（移除每行開頭的 - / *）
    cleaned_lines = []
    for line in text.splitlines():
        stripped = re.sub(r"^\s*[-*•]\s*", "", line).strip()
        if stripped:
            cleaned_lines.append(stripped)
    # 用空格而非換行接，避免 LLM 把句子拆行
    return " ".join(cleaned_lines).strip()


def _build_summary(proj_data: list, grand_sessions: int, grand_prompts: int,
                   grand_files: int, grand_commits: int,
                   active_days: int | None = None) -> list[str]:
    lines: list[str] = ["## 總覽", ""]

    # ── 自動分析（LLM）─────────────────────────────────
    lines.append("### 自動分析")
    lines.append("")
    llm_text = _llm_summary(proj_data, active_days)
    if llm_text:
        lines.append(llm_text)
    else:
        lines.append("_（無自動分析；本地 Ollama 不可達或本期無資料）_")
    lines.append("")

    # ── 我的增補（重產時整段保留：heading 之後到下個 heading 之前）──
    lines.append(KEEPOUT_HEADING)
    lines.append("")
    lines.append("")

    # ── 統計 ──────────────────────────────────────────
    lines.append("### 統計")
    lines.append("")

    stats = [
        f"{len(proj_data)} 專案",
        f"{grand_sessions} sessions",
        f"{grand_prompts} prompts",
        f"{grand_files} 檔",
        f"{grand_commits} commits",
    ]
    if active_days is not None:
        stats.insert(0, f"活躍 {active_days} 天")
    lines.append(" · ".join(stats))
    lines.append("")

    # 結構事實列
    for item in proj_data:
        if len(item) != 4:
            continue
        _key, g, commits, _vcs = item
        unique_files = len({f for s in g["sessions"] for f in s["modified_files"]})
        lines.append(_project_summary_line(g["project"], g["sessions"], commits, unique_files))
    lines.append("")

    # 統計表
    if active_days is not None:
        lines.append("| Sessions | Prompts | 改檔 | Commits | 活躍天數 |")
        lines.append("|:--:|:--:|:--:|:--:|:--:|")
        lines.append(
            f"| {grand_sessions} | {grand_prompts} | {grand_files} | "
            f"{grand_commits} | {active_days} |"
        )
    else:
        lines.append("| Sessions | Prompts | 改檔 | Commits |")
        lines.append("|:--:|:--:|:--:|:--:|")
        lines.append(f"| {grand_sessions} | {grand_prompts} | {grand_files} | {grand_commits} |")
    lines.append("")
    return lines


def _intent_str(intent: dict) -> str:
    return " ".join(f"{k}({v})" for k, v in sorted(intent.items(), key=lambda x: -x[1]) if v > 0)


def _clean_knowledge(k: str) -> str:
    s = k.lstrip("- ").removeprefix("[臨] ").removeprefix("[觀] ").removeprefix("[固] ").strip()
    return s


def _build_project_block(project: str, cwd: str, sessions: list[dict],
                         atoms: list[dict], commits: list[tuple[str, str]],
                         vcs: str | None) -> list[str]:
    lines: list[str] = []
    header_meta = cwd if cwd else ""
    if vcs:
        header_meta = f"`{header_meta}` · {vcs}" if header_meta else vcs
    elif header_meta:
        header_meta = f"`{header_meta}`"

    lines.append(f"## {project}")
    if header_meta:
        lines.append(header_meta)
    lines.append("")

    # Sessions
    if sessions:
        total_prompts = sum(s["prompts"] for s in sessions)
        total_files = sum(s["files_modified"] for s in sessions)
        agg_intent: dict = defaultdict(int)
        for s in sessions:
            for k, v in s["intent"].items():
                agg_intent[k] += v
        intent = _intent_str(agg_intent)
        lines.append(
            f"**Sessions ({len(sessions)})** · {total_prompts} prompts · "
            f"{total_files} 改檔" + (f" · {intent}" if intent else "")
        )
        for s in sessions:
            lines.append(f"- `{s['start']}–{s['end']}`")
        lines.append("")

    # Commits
    if commits:
        lines.append(f"**Commits ({len(commits)})**")
        for cid, msg in commits:
            lines.append(f"- `{cid}` {msg}")
        lines.append("")

    # Episodic 摘要 (若有；strip HTML 避免 Obsidian 渲染汙染)
    if atoms:
        for a in atoms:
            cleaned = _strip_html(a.get("summary", ""))
            if cleaned:
                lines.append("**摘要**")
                lines.append(cleaned)
                lines.append("")
                break

    # 知識
    knowledge: list[str] = []
    kseen = set()
    for s in sessions:
        for k in s["knowledge"]:
            ck = _clean_knowledge(k)
            if ck and ck not in kseen:
                kseen.add(ck)
                knowledge.append(ck)
    for a in atoms:
        for k in a.get("knowledge", []):
            ck = _clean_knowledge(k)
            if ck and ck not in kseen:
                kseen.add(ck)
                knowledge.append(ck)
    if knowledge:
        lines.append(f"**知識 ({len(knowledge)})**")
        for k in knowledge:
            lines.append(f"- {_strip_html(k)}")
        lines.append("")

    return lines


def build_journal(target_date: str) -> str:
    atoms = scan_episodic(target_date)
    states = scan_states(target_date)

    # 以 cwd（或 workspace fallback）分組
    by_proj: dict[str, dict] = defaultdict(lambda: {
        "project": "", "cwd": "", "sessions": [], "atoms": [],
    })
    for s in states:
        key = s["cwd"] or s["project"]
        g = by_proj[key]
        g["project"] = s["project"]
        g["cwd"] = s["cwd"]
        g["sessions"].append(s)
    for a in atoms:
        key = a["workspace"]
        g = by_proj[key]
        if not g["project"]:
            g["project"] = a["workspace"]
        g["atoms"].append(a)

    # VCS-only fallback：在沒 atom/state 的 cwd 中找有 commits 的
    existing_cwds = {g["cwd"] for g in by_proj.values() if g["cwd"]}
    vcs_only = _vcs_only_projects(target_date, existing_cwds)
    for cwd, _commits, _vcs in vcs_only:
        g = by_proj[cwd]
        g["project"] = _project_name(cwd)
        g["cwd"] = cwd

    if not by_proj:
        return f"# {target_date} 工作日誌\n\n> 當天無記錄。\n"

    # Commits + 統計
    proj_data = []
    total_commits = 0
    for key, g in by_proj.items():
        commits, vcs = commits_for(g["cwd"], target_date) if g["cwd"] else ([], None)
        total_commits += len(commits)
        proj_data.append((key, g, commits, vcs))

    total_sessions = sum(len(g["sessions"]) for _, g, _, _ in proj_data)
    total_prompts = sum(s["prompts"] for _, g, _, _ in proj_data for s in g["sessions"])
    total_files = sum(s["files_modified"] for _, g, _, _ in proj_data for s in g["sessions"])

    # 排序：有 commit 的優先，然後依 prompts 數
    proj_data.sort(key=lambda x: (-len(x[2]), -sum(s["prompts"] for s in x[1]["sessions"])))

    lines = [f"# {target_date} 工作日誌", ""]
    lines.extend(_build_summary(proj_data, total_sessions, total_prompts,
                                total_files, total_commits))

    for _key, g, commits, vcs in proj_data:
        lines.append("---")
        lines.append("")
        lines.extend(_build_project_block(g["project"], g["cwd"], g["sessions"],
                                          g["atoms"], commits, vcs))

    return "\n".join(lines).rstrip() + "\n"


# ── Weekly Summary Builder ─────────────────────────────────────

def _week_range(ref_date: str) -> tuple[str, str, int, int]:
    """回傳 (monday_str, sunday_str, iso_year, iso_week)"""
    d = datetime.strptime(ref_date, "%Y-%m-%d")
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    iso_year, iso_week, _ = d.isocalendar()
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d"), iso_year, iso_week


def _build_period_lines(start: str, end: str) -> tuple[list[str], bool]:
    """彙整 [start, end] 區間的內容（不含標題）。回傳 (lines, has_data)。"""
    ep_by_date = scan_episodic_range(start, end)
    st_by_date = scan_states_range(start, end)

    # VCS-only 日期：候選 cwd 中當天有 commits、但沒 atom/state
    vcs_only_cwds: set[str] = set()
    vcs_only_dates: set[str] = set()
    existing_dates = set(ep_by_date.keys()) | set(st_by_date.keys())
    existing_cwds: set[str] = set()
    for s_list in st_by_date.values():
        for s in s_list:
            if s["cwd"]:
                existing_cwds.add(s["cwd"])
    for cwd in _historical_cwds():
        if cwd in existing_cwds:
            continue
        for d in _iter_dates(start, end):
            commits, _vcs = commits_for(cwd, d)
            if commits:
                vcs_only_cwds.add(cwd)
                vcs_only_dates.add(d)

    all_dates = sorted(existing_dates | vcs_only_dates)
    if not all_dates:
        return [], False

    return _render_period(all_dates, ep_by_date, st_by_date, vcs_only_cwds), True


def _render_period(all_dates: list[str], ep_by_date: dict, st_by_date: dict,
                   vcs_only_cwds: set[str] | None = None) -> list[str]:
    vcs_only_cwds = vcs_only_cwds or set()
    # 以 cwd（fallback workspace）分組，跨整個區間
    by_proj: dict[str, dict] = defaultdict(lambda: {
        "project": "", "cwd": "", "sessions": [], "atoms": [],
        "dates": set(),
    })
    for d in all_dates:
        for s in st_by_date.get(d, []):
            key = s["cwd"] or s["project"]
            g = by_proj[key]
            g["project"] = s["project"]
            g["cwd"] = s["cwd"]
            g["sessions"].append(s)
            g["dates"].add(d)
        for a in ep_by_date.get(d, []):
            key = a["workspace"]
            g = by_proj[key]
            if not g["project"]:
                g["project"] = a["workspace"]
            g["atoms"].append(a)
            g["dates"].add(d)

    # 補入 VCS-only cwd（之後 commits_for 會逐日查）
    for cwd in vcs_only_cwds:
        g = by_proj[cwd]
        g["project"] = _project_name(cwd)
        g["cwd"] = cwd
        for d in all_dates:
            commits, _vcs = commits_for(cwd, d)
            if commits:
                g["dates"].add(d)

    # 各專案彙整 commits（區間內每天 commits 的聯集）
    proj_data = []
    grand_commits = 0
    for key, g in by_proj.items():
        commits: list[tuple[str, str]] = []
        vcs = None
        if g["cwd"]:
            seen_ids = set()
            for d in sorted(g["dates"]):
                day_commits, vcs_d = commits_for(g["cwd"], d)
                if vcs_d:
                    vcs = vcs_d
                for cid, msg in day_commits:
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        commits.append((cid, msg))
        grand_commits += len(commits)
        proj_data.append((key, g, commits, vcs))

    grand_sessions = sum(len(g["sessions"]) for _, g, _, _ in proj_data)
    grand_prompts = sum(s["prompts"] for _, g, _, _ in proj_data for s in g["sessions"])

    # 改檔（去重至專案內）
    grand_files = 0
    for _, g, _, _ in proj_data:
        seen = set()
        for s in g["sessions"]:
            seen.update(s["modified_files"])
        grand_files += len(seen)

    # 排序：有 commit 的優先
    proj_data.sort(key=lambda x: (-len(x[2]), -sum(s["prompts"] for s in x[1]["sessions"])))

    # ── 總覽（含 自動分析 / 我的增補 / 統計 + 統計表）──
    lines: list[str] = []
    lines.extend(_build_summary(proj_data, grand_sessions, grand_prompts,
                                grand_files, grand_commits, active_days=len(all_dates)))

    # ── 各專案 ──
    for _key, g, commits, vcs in proj_data:
        lines.append("---")
        lines.append("")
        lines.extend(_build_project_block(g["project"], g["cwd"], g["sessions"],
                                          g["atoms"], commits, vcs))

    # ── 每日簡述 ──
    lines.append("---")
    lines.append("")
    lines.append("## 每日簡述")
    lines.append("")
    for d in all_dates:
        dt = datetime.strptime(d, "%Y-%m-%d")
        wd = _WEEKDAY_NAMES[dt.weekday()]
        day_states = st_by_date.get(d, [])
        if day_states:
            parts = []
            for s in sorted(day_states, key=lambda x: x["start"]):
                parts.append(f"{s['project']} {s['prompts']}p")
            lines.append(f"- **{d} ({wd})** · " + " | ".join(parts))
            continue
        day_atoms = ep_by_date.get(d, [])
        if day_atoms:
            parts = [f"{a['workspace']} {a['files_mod_n']}f" for a in day_atoms]
            lines.append(f"- **{d} ({wd})** · " + " | ".join(parts))
            continue
        # VCS-only fallback
        parts = []
        for _, g, _, _ in proj_data:
            if d in g["dates"] and g["cwd"]:
                day_commits, _ = commits_for(g["cwd"], d)
                if day_commits:
                    parts.append(f"{g['project']} {len(day_commits)}c")
        if parts:
            lines.append(f"- **{d} ({wd})** · " + " | ".join(parts))
    lines.append("")

    return lines


def build_weekly(ref_date: str) -> str:
    mon, sun, iso_y, iso_w = _week_range(ref_date)
    title = f"# {iso_y}-W{iso_w:02d} 週報 ({mon} ~ {sun})\n"
    body, has_data = _build_period_lines(mon, sun)
    if not has_data:
        return f"{title}\n> 該週無記錄。\n"
    return title + "\n" + "\n".join(body).rstrip() + "\n"


def _month_range(month_arg: str | None) -> tuple[str, str, str]:
    """月份引數 'YYYY-MM' 或 None（=本月），回傳 (start, end, label)。"""
    if month_arg:
        y, m = (int(x) for x in month_arg.split("-"))
    else:
        now = datetime.now()
        y, m = now.year, now.month
    start = datetime(y, m, 1)
    end = (datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)) - timedelta(days=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), f"{y:04d}-{m:02d}"


def build_monthly(month_arg: str | None) -> tuple[str, str]:
    start, end, label = _month_range(month_arg)
    title = f"# {label} 月報 ({start} ~ {end})\n"
    body, has_data = _build_period_lines(start, end)
    if not has_data:
        return f"{title}\n> 該月無記錄。\n", label
    return title + "\n" + "\n".join(body).rstrip() + "\n", label


def _iter_dates(start: str, end: str):
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    cur = s
    while cur <= e:
        yield cur.strftime("%Y-%m-%d")
        cur += timedelta(days=1)


def _historical_cwds() -> set[str]:
    """收集候選 repo cwd：環境變數 + 當前 state + 歷史 journals 解析。"""
    cwds: set[str] = set()

    env_roots = _env("CLAUDE_JOURNAL_VCS_ROOTS", "") or ""
    for r in env_roots.split(os.pathsep):
        r = r.strip()
        if r:
            cwds.add(r)

    if WORKFLOW_DIR.exists():
        for f in WORKFLOW_DIR.glob("state-*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                cwd = data.get("session", {}).get("cwd", "")
                if cwd:
                    cwds.add(cwd)
            except (json.JSONDecodeError, KeyError, TypeError, OSError):
                pass

    pattern = re.compile(r"`([A-Za-z]:[\\/][^`]+|/[^`]+)`\s*·\s*(git|svn)")
    primary = JOURNAL_DIRS[0]
    scan_dirs: list[Path] = []
    if primary.exists():
        scan_dirs.append(primary)  # 平鋪舊檔
        for sub in JOURNAL_SUBDIR.values():
            d = primary / sub
            if d.exists():
                scan_dirs.append(d)
    for d in scan_dirs:
        for f in d.glob("*.md"):
            try:
                for m in pattern.finditer(f.read_text(encoding="utf-8")):
                    cwds.add(m.group(1))
            except OSError:
                pass

    return cwds


def _vcs_only_projects(target_date: str, exclude_cwds: set[str]) -> list[tuple[str, list[tuple[str, str]], str]]:
    """在沒 atom/state 的 cwd 中找出當天有 commits 的，回傳 [(cwd, commits, vcs)]。"""
    out = []
    for cwd in _historical_cwds():
        if cwd in exclude_cwds:
            continue
        commits, vcs = commits_for(cwd, target_date)
        if commits:
            out.append((cwd, commits, vcs))
    return out


def has_records(target_date: str) -> bool:
    if scan_episodic(target_date) or scan_states(target_date):
        return True
    for cwd in _historical_cwds():
        commits, _ = commits_for(cwd, target_date)
        if commits:
            return True
    return False


# ── Journal Write (Multi-target) ────────────────────────────────

def _path_for(kind: str, filename: str, base: Path | None = None) -> Path | None:
    """取得 (base|JOURNAL_DIRS[0]) / 子目錄 / filename 的完整路徑。kind 不認得回 None。"""
    sub = JOURNAL_SUBDIR.get(kind)
    if not sub:
        return None
    return (base or JOURNAL_DIRS[0]) / sub / filename


def write_journal(content: str, filename: str, kind: str) -> list[Path]:
    """寫入 JOURNAL_DIRS[0] 為主，其餘 dirs 用 shutil.copy2 複製過去。
    若既有檔含 `<!-- ai-keepout:start -->...<!-- ai-keepout:end -->` 區塊，
    內容會被原樣保留塞回新 content。
    回傳實際寫入成功的所有路徑（[0] 是 primary）。"""
    sub = JOURNAL_SUBDIR.get(kind)
    if not sub:
        return []
    written: list[Path] = []
    primary = JOURNAL_DIRS[0] / sub / filename
    preserved = _extract_keepout(primary)
    content = _apply_keepout(content, preserved)
    try:
        primary.parent.mkdir(parents=True, exist_ok=True)
        primary.write_text(content, encoding="utf-8")
        written.append(primary)
    except OSError as e:
        print(f"[ERROR] 主路徑寫入失敗 ({primary}): {e}", file=sys.stderr)
        return []

    for base in JOURNAL_DIRS[1:]:
        if not base.parent.exists():
            print(f"[WARN] 跳過不存在的鏡射 base: {base}", file=sys.stderr)
            continue
        try:
            target_dir = base / sub
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / filename
            shutil.copy2(primary, target)
            written.append(target)
        except OSError as e:
            print(f"[WARN] 複製失敗 ({base}): {e}", file=sys.stderr)
    return written


# ── VCS Commits ─────────────────────────────────────────────────

def _find_repo_root(cwd_str: str) -> tuple[Path, str] | None:
    """從 cwd 往上找 .git/.svn，回傳 (repo_root, vcs_kind)。"""
    if not cwd_str:
        return None
    p = Path(cwd_str)
    if not p.exists():
        return None
    for cur in [p, *p.parents]:
        if (cur / ".git").exists():
            return cur, "git"
        if (cur / ".svn").exists():
            return cur, "svn"
    return None


def _resolve_author(repo_root: Path, vcs: str) -> str:
    env_override = _env("CLAUDE_JOURNAL_AUTHOR")
    if env_override:
        return env_override
    if vcs == "git":
        try:
            r = subprocess.run(
                ["git", "-C", str(repo_root), "config", "user.name"],
                capture_output=True, timeout=VCS_TIMEOUT,
            )
            if r.returncode == 0:
                name = r.stdout.decode("utf-8", errors="replace").strip()
                if name:
                    return name
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, UnicodeDecodeError):
            pass
    return os.environ.get("USERNAME") or os.environ.get("USER") or ""


def _git_commits(repo_root: Path, date: str, author: str) -> list[tuple[str, str]]:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "log",
             f"--since={date} 00:00:00", f"--until={date} 23:59:59",
             f"--author={author}", "--pretty=format:%h|%s"],
            capture_output=True, timeout=VCS_TIMEOUT,
        )
        if r.returncode != 0:
            return []
        out = r.stdout.decode("utf-8", errors="replace")
        return [tuple(line.split("|", 1)) for line in out.splitlines() if "|" in line]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, UnicodeDecodeError):
        return []


def _svn_commits(repo_root: Path, date: str, author: str) -> list[tuple[str, str]]:
    # 用較寬的 UTC 範圍抓回後依本地時區過濾，避免 SVN client 對 {date} 的時區歧義
    target = datetime.strptime(date, "%Y-%m-%d")
    prev_day = (target - timedelta(days=1)).strftime("%Y-%m-%d")
    next_day = (target + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        r = subprocess.run(
            ["svn", "log", "--xml", "--non-interactive",
             "-r", f"{{{prev_day}}}:{{{next_day}T23:59:59Z}}"],
            capture_output=True, timeout=VCS_TIMEOUT, cwd=str(repo_root),
        )
        if r.returncode != 0:
            return []
        xml_text = r.stdout.decode("utf-8", errors="replace")
        tree = ET.fromstring(xml_text)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ET.ParseError, UnicodeDecodeError):
        return []

    # 本地時區偏移：依當前系統 timezone 計算
    now = datetime.now()
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    tz_offset = now - utc_now
    target_local_start = target
    target_local_end = target + timedelta(days=1)

    out: list[tuple[str, str]] = []
    for entry in tree.findall("logentry"):
        a = entry.find("author")
        if a is None or (a.text or "").strip() != author:
            continue
        date_node = entry.find("date")
        if date_node is None or not date_node.text:
            continue
        try:
            utc_dt = datetime.fromisoformat(date_node.text[:19])
        except ValueError:
            continue
        local_dt = utc_dt + tz_offset
        if not (target_local_start <= local_dt < target_local_end):
            continue
        rev = entry.get("revision", "?")
        msg_node = entry.find("msg")
        msg = ""
        if msg_node is not None and msg_node.text:
            msg = msg_node.text.strip().splitlines()[0] if msg_node.text.strip() else ""
        out.append((f"r{rev}", msg))
    return out


def commits_for(cwd_str: str, date: str) -> tuple[list[tuple[str, str]], str | None]:
    """回傳 (commits, vcs_kind)。失敗或無 VCS 回傳 ([], None)。"""
    info = _find_repo_root(cwd_str)
    if info is None:
        return [], None
    repo_root, vcs = info
    author = _resolve_author(repo_root, vcs)
    if not author:
        return [], vcs
    if vcs == "git":
        return _git_commits(repo_root, date, author), "git"
    return _svn_commits(repo_root, date, author), "svn"


# ── Migration ───────────────────────────────────────────────────

def _kind_for_filename(name: str) -> str | None:
    """從檔名推斷 kind：week-* / month-* / YYYY-MM-DD."""
    if name.startswith("week-"):
        return "weekly"
    if name.startswith("month-"):
        return "monthly"
    if re.match(r"\d{4}-\d{2}-\d{2}\.md$", name):
        return "daily"
    return None


def _file_hash(p: Path) -> str:
    h = hashlib.md5()
    h.update(p.read_bytes())
    return h.hexdigest()


def _migrate_one(src: Path, dst: Path) -> str:
    """搬一個檔案。回傳: moved/duplicate/conflict/skipped。"""
    if not src.is_file():
        return "skipped"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            if _file_hash(src) == _file_hash(dst):
                src.unlink()
                return "duplicate"
        except OSError:
            return "skipped"
        bak = src.with_suffix(src.suffix + ".conflict")
        try:
            src.rename(bak)
        except OSError:
            return "skipped"
        return "conflict"
    try:
        shutil.move(str(src), str(dst))
    except OSError:
        return "skipped"
    return "moved"


def migrate_legacy_layout() -> dict:
    """把平鋪舊檔搬進子目錄（日報/週報/月報），且把非主路徑的舊位置（DEFAULT_JOURNALS_DIR）
    搬到 JOURNAL_DIRS[0]。冪等。回傳統計。"""
    stats = {"moved": 0, "duplicate": 0, "conflict": 0, "skipped": 0}
    primary = JOURNAL_DIRS[0]
    sources: list[Path] = []
    if primary.exists():
        sources.append(primary)
    if DEFAULT_JOURNALS_DIR.exists() and DEFAULT_JOURNALS_DIR.resolve() != primary.resolve():
        sources.append(DEFAULT_JOURNALS_DIR)

    for src_dir in sources:
        for f in list(src_dir.glob("*.md")):
            kind = _kind_for_filename(f.name)
            if not kind:
                continue
            dst = primary / JOURNAL_SUBDIR[kind] / f.name
            if f.resolve() == dst.resolve():
                continue
            stats[_migrate_one(f, dst)] += 1
    return stats


# ── Cleanup ─────────────────────────────────────────────────────

def cleanup() -> int:
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    removed = 0
    targets: list[Path] = []
    for base in JOURNAL_DIRS:
        if not base.exists():
            continue
        for sub in JOURNAL_SUBDIR.values():
            d = base / sub
            if d.exists():
                targets.append(d)
        targets.append(base)  # 平鋪舊檔
    for d in targets:
        for f in d.glob("*.md"):
            m = re.match(r"(\d{4}-\d{2}-\d{2})", f.name)
            if m:
                try:
                    if datetime.strptime(m.group(1), "%Y-%m-%d") < cutoff:
                        f.unlink()
                        removed += 1
                except ValueError:
                    pass
    return removed


# ── Main ────────────────────────────────────────────────────────

def _norm_date(arg: str) -> str | None:
    if re.match(r"\d{4}-\d{2}-\d{2}$", arg):
        return arg
    if re.match(r"\d{8}$", arg):
        return f"{arg[:4]}-{arg[4:6]}-{arg[6:8]}"
    return None


def main():
    target = datetime.now().strftime("%Y-%m-%d")
    mode = "daily"
    only_cleanup = False
    range_dates: list[str] = []
    month_arg: str | None = None

    args = sys.argv[1:]
    for arg in args:
        if arg == "--cleanup":
            only_cleanup = True
        elif arg == "week":
            mode = "weekly"
        elif arg == "month":
            mode = "monthly"
        elif arg == "range":
            mode = "range"
        elif mode == "monthly" and re.match(r"\d{4}-\d{2}$", arg):
            month_arg = arg
        else:
            d = _norm_date(arg)
            if d is None:
                continue
            if mode == "range":
                range_dates.append(d)
            else:
                target = d

    if only_cleanup:
        n = cleanup()
        print(f"清理 {n} 份過期日誌 (>{RETENTION_DAYS} 天)")
        return

    # 路徑可見：讓使用者/AI 知道實際儲存位置
    paths_str = " | ".join(str(p) for p in JOURNAL_DIRS)
    print(f"[INFO] 日誌路徑: {paths_str}", file=sys.stderr)

    # 一次性遷移（冪等）：平鋪舊檔 / DEFAULT_JOURNALS_DIR 搬到 JOURNAL_DIRS[0]/子目錄
    mig = migrate_legacy_layout()
    if any(mig.values()):
        print(f"[OK] 遷移: moved={mig['moved']} dup={mig['duplicate']} "
              f"conflict={mig['conflict']} skipped={mig['skipped']}", file=sys.stderr)

    if mode == "weekly":
        journal = build_weekly(target)
        _, _, iso_y, iso_w = _week_range(target)
        fname = f"week-{iso_y}-W{iso_w:02d}.md"
        written = write_journal(journal, fname, "weekly")
        print(journal)
        for w in written:
            print(f"[OK] 已存檔: {w}")
    elif mode == "monthly":
        journal, label = build_monthly(month_arg)
        fname = f"month-{label}.md"
        written = write_journal(journal, fname, "monthly")
        print(journal)
        for w in written:
            print(f"[OK] 已存檔: {w}")
    elif mode == "range":
        if len(range_dates) != 2:
            print("用法：range YYYY-MM-DD YYYY-MM-DD", file=sys.stderr)
            sys.exit(2)
        start, end = sorted(range_dates)
        produced = 0
        skipped = 0
        for d in _iter_dates(start, end):
            if not has_records(d):
                skipped += 1
                continue
            journal = build_journal(d)
            fname = f"{d}.md"
            written = write_journal(journal, fname, "daily")
            if not written:
                tail = ""
            elif len(written) == 1:
                tail = f" → {written[0]}"
            else:
                tail = f" → {written[0]} (+{len(written)-1} 處)"
            print(f"[OK] {d}:{tail}")
            produced += 1
        print(f"\n[OK] 區間 {start} ~ {end}：產生 {produced} 份日報，跳過 {skipped} 個無記錄日")
    else:
        journal = build_journal(target)
        fname = f"{target}.md"
        written = write_journal(journal, fname, "daily")
        print(journal)
        for w in written:
            print(f"[OK] 已存檔: {w}")

    n = cleanup()
    if n:
        print(f"[OK] 清理 {n} 份過期日誌 (>{RETENTION_DAYS} 天)")


if __name__ == "__main__":
    main()
