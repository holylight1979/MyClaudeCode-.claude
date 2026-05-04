"""test_atom_io_equivalence.py — atom_io.write_atom byte-equivalence vs server.js (S1.3)

10 情境覆蓋 server.js:1065 toolAtomWrite 行為契約。每情境 fixture 寫死 today
日期，比對 build_atom_content 與 write_atom 落檔結果 byte-identical。

S1 不接 caller，故無實際 write-gate / conflict-detector 涉入；測試以 skip_gate=True
跑純 funnel 路徑。S2/S3 切 caller 後再加 e2e gate 測試。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

LIB_PARENT = Path(__file__).resolve().parent.parent
if str(LIB_PARENT) not in sys.path:
    sys.path.insert(0, str(LIB_PARENT))

from lib import atom_io  # noqa: E402
from lib.atom_io import write_atom  # noqa: E402
from lib.atom_spec import build_atom_content  # noqa: E402


FIXED_TODAY = "2026-05-04"


@pytest.fixture
def isolated_claude(tmp_path, monkeypatch):
    """把 atom_io 的全域 root path 重指向 tmp_path，避免測試污染現役 ~/.claude/。"""
    fake_claude = tmp_path / ".claude"
    fake_global_mem = fake_claude / "memory"
    fake_audit = fake_global_mem / "_meta" / "atom_io_audit.jsonl"
    fake_global_mem.mkdir(parents=True)
    monkeypatch.setattr(atom_io, "CLAUDE_DIR", fake_claude)
    monkeypatch.setattr(atom_io, "GLOBAL_MEMORY_DIR", fake_global_mem)
    monkeypatch.setattr(atom_io, "AUDIT_LOG", fake_audit)
    return {
        "root": tmp_path,
        "claude": fake_claude,
        "memory": fake_global_mem,
        "audit": fake_audit,
    }


@pytest.fixture
def fake_project(tmp_path):
    """建一個 fake project root（有 .git marker），供 shared/role/personal 測試用。"""
    proj = tmp_path / "myproj"
    proj.mkdir()
    (proj / ".git").mkdir()  # marker for find_project_root
    return proj


# ─── 1. global atom create ─────────────────────────────────────────────────────


def test_01_global_create_byte_identical(isolated_claude):
    expected = build_atom_content(
        title="Hello", scope="global", confidence="[臨]",
        triggers=["a", "b", "c"], knowledge=["fact1", "fact2"],
        today=FIXED_TODAY,
    )
    result = write_atom(
        title="Hello", scope="global", confidence="[臨]",
        triggers=["a", "b", "c"], knowledge=["fact1", "fact2"],
        mode="create", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    assert result.ok, result.error
    actual = result.path.read_text(encoding="utf-8")
    assert actual == expected, f"DIFF\nEXPECTED:\n{expected}\nACTUAL:\n{actual}"
    assert result.path == isolated_claude["memory"] / "hello.md"


# ─── 2. shared atom create (project scope) ────────────────────────────────────


def test_02_shared_create(isolated_claude, fake_project):
    result = write_atom(
        title="Shared Knowledge", scope="shared", confidence="[臨]",
        triggers=["x", "y", "z"], knowledge=["k1"],
        project_cwd=str(fake_project),
        mode="create", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    assert result.ok, result.error
    expected_path = fake_project / ".claude" / "memory" / "shared" / "shared-knowledge.md"
    assert result.path == expected_path
    content = result.path.read_text(encoding="utf-8")
    assert "- Scope: shared" in content
    assert "# Shared Knowledge" in content


# ─── 3. role atom create ──────────────────────────────────────────────────────


def test_03_role_create(isolated_claude, fake_project):
    result = write_atom(
        title="Role Atom", scope="role", confidence="[臨]",
        triggers=["t1", "t2", "t3"], knowledge=["k"], role="programmer",
        project_cwd=str(fake_project),
        mode="create", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    assert result.ok, result.error
    expected_path = fake_project / ".claude" / "memory" / "roles" / "programmer" / "role-atom.md"
    assert result.path == expected_path
    content = result.path.read_text(encoding="utf-8")
    assert "- Scope: role:programmer" in content


# ─── 4. personal atom create ──────────────────────────────────────────────────


def test_04_personal_create(isolated_claude, fake_project):
    result = write_atom(
        title="Personal Atom", scope="personal", confidence="[臨]",
        triggers=["p1", "p2", "p3"], knowledge=["k"], user="alice",
        project_cwd=str(fake_project),
        mode="create", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    assert result.ok, result.error
    expected_path = fake_project / ".claude" / "memory" / "personal" / "alice" / "personal-atom.md"
    assert result.path == expected_path
    content = result.path.read_text(encoding="utf-8")
    assert "- Scope: personal:alice" in content


# ─── 5. all optional fields render correctly ──────────────────────────────────


def test_05_optional_fields(isolated_claude):
    result = write_atom(
        title="Full Atom", scope="global", confidence="[臨]",
        triggers=["a", "b", "c"], knowledge=["k1", "k2"],
        actions=["do this", "- already prefixed"],
        related=["other-atom-1", "other-atom-2"],
        audience=["programmer"],  # not in SENSITIVE_AUDIENCE
        author="testuser", merge_strategy="manual",
        mode="create", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    assert result.ok, result.error
    content = result.path.read_text(encoding="utf-8")
    assert "- Audience: programmer" in content
    assert "- Author: testuser" in content
    assert "- Merge-strategy: manual" in content
    assert "- Related: other-atom-1, other-atom-2" in content
    assert "- do this" in content
    assert "- already prefixed" in content
    # ai-assist (default) should NOT emit Merge-strategy line
    result2 = write_atom(
        title="Full Atom 2", scope="global", confidence="[臨]",
        triggers=["x", "y", "z"], knowledge=["k"],
        merge_strategy="ai-assist",
        mode="create", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    assert "Merge-strategy:" not in result2.path.read_text(encoding="utf-8")


# ─── 6. sensitive audience → _pending_review/ ─────────────────────────────────


def test_06_sensitive_audience_routes_pending(isolated_claude, fake_project):
    result = write_atom(
        title="Decision Atom", scope="shared", confidence="[臨]",
        triggers=["d1", "d2", "d3"], knowledge=["k"],
        audience=["decision"],  # sensitive
        project_cwd=str(fake_project),
        mode="create", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    assert result.ok, result.error
    assert result.routed_to_pending is True
    assert "_pending_review" in str(result.path)
    content = result.path.read_text(encoding="utf-8")
    assert "- Pending-review-by: management" in content


# ─── 7. mode=append ───────────────────────────────────────────────────────────


def test_07_append_mode(isolated_claude):
    write_atom(
        title="Appendable", scope="global", confidence="[臨]",
        triggers=["a", "b", "c"], knowledge=["original-fact"],
        mode="create", source="test", skip_gate=True, today="2026-05-01",
    )
    file_path = isolated_claude["memory"] / "appendable.md"
    before = file_path.read_text(encoding="utf-8")
    assert "- original-fact" in before
    assert "- Last-used: 2026-05-01" in before

    result = write_atom(
        title="Appendable", scope="global", confidence="[臨]",
        triggers=["a", "b", "c"], knowledge=["new-fact-1", "new-fact-2"],
        mode="append", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    assert result.ok, result.error
    after = file_path.read_text(encoding="utf-8")
    assert "- original-fact" in after  # preserved
    assert "- new-fact-1" in after
    assert "- new-fact-2" in after
    assert f"- Last-used: {FIXED_TODAY}" in after  # updated
    # appended knowledge must be before ## 行動
    assert after.index("- new-fact-2") < after.index("## 行動")


# ─── 8. mode=replace preserves Confirmations / ReadHits / Author / Created-at ─


def test_08_replace_preserves_counters(isolated_claude):
    initial = write_atom(
        title="Counter Atom", scope="global", confidence="[臨]",
        triggers=["c1", "c2", "c3"], knowledge=["v1"],
        author="orig-author",
        mode="create", source="test", skip_gate=True, today="2026-05-01",
    )
    # Manually bump counters in file (simulate post-write evolution)
    fp = initial.path
    text = fp.read_text(encoding="utf-8")
    text = text.replace("- Confirmations: 0", "- Confirmations: 7")
    text = text.replace("- ReadHits: 0", "- ReadHits: 42")
    fp.write_text(text, encoding="utf-8")

    result = write_atom(
        title="Counter Atom", scope="global", confidence="[臨]",
        triggers=["c1", "c2", "c3"], knowledge=["v2-replaced"],
        author="new-author-should-be-ignored",
        mode="replace", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    assert result.ok, result.error
    after = fp.read_text(encoding="utf-8")
    assert "- Confirmations: 7" in after  # preserved
    assert "- ReadHits: 42" in after  # preserved
    assert "- Author: orig-author" in after  # preserved (initial author wins)
    assert "- Created-at: 2026-05-01" in after  # preserved
    assert "- v2-replaced" in after  # new content
    assert "- v1" not in after  # old content gone


# ─── 9. dry_run: no file written ──────────────────────────────────────────────


def test_09_dry_run_no_write(isolated_claude):
    result = write_atom(
        title="Ghost Atom", scope="global", confidence="[臨]",
        triggers=["g1", "g2", "g3"], knowledge=["k"],
        mode="create", source="test", skip_gate=True,
        dry_run=True, today=FIXED_TODAY,
    )
    assert result.ok
    assert result.extra.get("dry_run") is True
    assert not result.path.exists()
    # content still returned for inspection
    assert "# Ghost Atom" in result.extra["content"]
    # audit log not appended in dry_run
    assert not isolated_claude["audit"].exists()


# ─── 10. error paths ──────────────────────────────────────────────────────────


def test_10_error_paths(isolated_claude, fake_project):
    # 10a: invalid source
    r1 = write_atom(
        title="X", scope="global", confidence="[臨]",
        triggers=["a", "b", "c"], knowledge=["k"],
        mode="create", source="hacker:bypass", skip_gate=True,
    )
    assert not r1.ok and "invalid source" in r1.error

    # 10b: invalid scope
    r2 = write_atom(
        title="X", scope="bogus", confidence="[臨]",
        triggers=["a", "b", "c"], knowledge=["k"],
        mode="create", source="test", skip_gate=True,
    )
    assert not r2.ok and ("scope" in r2.error.lower() or "Unknown" in r2.error)

    # 10c: confidence != [臨] on create
    r3 = write_atom(
        title="X", scope="global", confidence="[固]",
        triggers=["a", "b", "c"], knowledge=["k"],
        mode="create", source="test", skip_gate=True,
    )
    assert not r3.ok and "[臨]" in r3.error

    # 10d: file exists (create twice)
    write_atom(
        title="Once", scope="global", confidence="[臨]",
        triggers=["a", "b", "c"], knowledge=["k"],
        mode="create", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    r4 = write_atom(
        title="Once", scope="global", confidence="[臨]",
        triggers=["a", "b", "c"], knowledge=["k"],
        mode="create", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    assert not r4.ok and "already exists" in r4.error

    # 10e: append nonexistent
    r5 = write_atom(
        title="Nonexistent", scope="global", confidence="[臨]",
        triggers=["a", "b", "c"], knowledge=["k"],
        mode="append", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    assert not r5.ok and "not found" in r5.error


# ─── Bonus: audit log byte-shape sanity ───────────────────────────────────────


def test_audit_log_appends_jsonl(isolated_claude):
    write_atom(
        title="LoggedAtom", scope="global", confidence="[臨]",
        triggers=["a", "b", "c"], knowledge=["k"],
        mode="create", source="test", skip_gate=True, today=FIXED_TODAY,
    )
    audit_path = isolated_claude["audit"]
    assert audit_path.exists()
    lines = [ln for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln]
    # Expect at least 1 write entry + 1 index entry
    assert len(lines) >= 2
    entries = [json.loads(ln) for ln in lines]
    ops = [e["op"] for e in entries]
    assert "write" in ops
    assert "index" in ops
    sources = {e["source"] for e in entries}
    assert sources == {"test"}
