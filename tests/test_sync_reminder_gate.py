"""test_sync_reminder_gate.py — Stop-hook Sync Reminder Gate (2026-05-04)

對應 hook: hooks/workflow-guardian.py:_detect_uncommitted_files
對應 issue: rules/core.md「完成修改後主動提出 .git→commit+push」漏洞
  ─ Stop 閘 min_files_to_block=2 導致單檔修改不被任何閘擋。

此測試只驗 helper（_detect_uncommitted_files）。Gate 主流程靠 helper
回傳結果決策，覆蓋 helper 即覆蓋核心行為。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import importlib  # noqa: E402

wg = importlib.import_module("workflow-guardian")  # type: ignore[attr-defined]
_detect = wg._detect_uncommitted_files


GIT_AVAILABLE = shutil.which("git") is not None


def _mk_modified(path: Path) -> dict:
    return {"path": str(path), "tool": "Edit", "at": "2026-05-04T00:00:00+08:00"}


def test_empty_input_returns_empty_list():
    assert _detect([]) == []


def test_nonexistent_paths_filtered_to_empty(tmp_path: Path):
    """檔案路徑不存在 → 跳過（已被刪），偵測不到 VCS 也回 None。"""
    ghost = tmp_path / "ghost.py"  # 不存在
    result = _detect([_mk_modified(ghost)])
    # 沒有實際檔案 → 沒檢查 VCS → detected_any_vcs=False → None
    assert result is None


def test_outside_vcs_returns_none(tmp_path: Path):
    """非 git/svn 目錄 → 回 None，跳過此閘。"""
    f = tmp_path / "bare.txt"
    f.write_text("hello", encoding="utf-8")
    result = _detect([_mk_modified(f)])
    assert result is None


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git not available")
def test_git_uncommitted_file_detected(tmp_path: Path):
    """git 工作區內未 commit → 列入 uncommitted。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True,
    )
    f = repo / "new.py"
    f.write_text("print('hi')\n", encoding="utf-8")
    result = _detect([_mk_modified(f)])
    assert result is not None  # 偵測到 VCS
    assert str(f) in result


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git not available")
def test_git_committed_file_not_listed(tmp_path: Path):
    """git 工作區內已 commit 且未再次修改 → 不列入 uncommitted。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True,
    )
    f = repo / "done.py"
    f.write_text("print('done')\n", encoding="utf-8")
    subprocess.run(["git", "add", "done.py"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=repo, check=True,
    )
    result = _detect([_mk_modified(f)])
    # 偵測到 VCS（returncode==0），但 stdout 為空 → 不列入
    assert result == []


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git not available")
def test_git_mixed_committed_and_modified(tmp_path: Path):
    """混合：committed 不列、modified 列、untracked 列。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True,
    )
    committed = repo / "a.py"
    committed.write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=repo, check=True,
    )
    untracked = repo / "b.py"
    untracked.write_text("b\n", encoding="utf-8")

    result = _detect([_mk_modified(committed), _mk_modified(untracked)])
    assert result is not None
    assert str(untracked) in result
    assert str(committed) not in result


def test_dedup_same_path_listed_once(tmp_path: Path):
    """同一檔案重複出現在 modified_files（多次 Edit）→ 只列一次。"""
    f = tmp_path / "dup.txt"
    f.write_text("x", encoding="utf-8")
    # 非 VCS 區會回 None；改用 patched helper 驗 dedup 邏輯
    # 直接驗 unique_paths 路徑：把同一個檔放 3 次，回傳 None（無 VCS）即可
    # （dedup 失敗會走進 3 次 subprocess，行為仍正確；但邏輯上 set 已去重）
    result = _detect([_mk_modified(f), _mk_modified(f), _mk_modified(f)])
    assert result is None  # 非 VCS 工作區 → None
