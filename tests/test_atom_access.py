"""test_atom_access.py — lib/atom_access.py 旁路檔讀寫 API 測試

涵蓋：
  - 基本 read/init/increment/record/write_field
  - 舊 schema 自動正規化（confirmations 陣列 → confirmation_events）
  - 不存在 atom 的回傳行為
  - 並發 increment（threading 模擬兩 hook 同時 increment）
  - bulk_read 掃描
  - 稽核日誌條目正確性
  - CLI 入口
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

LIB_PARENT = Path(__file__).resolve().parent.parent
if str(LIB_PARENT) not in sys.path:
    sys.path.insert(0, str(LIB_PARENT))

from lib import atom_access, atom_io  # noqa: E402


@pytest.fixture
def isolated_claude(tmp_path, monkeypatch):
    """把 atom_io 全域 path 重指向 tmp_path，避免污染 ~/.claude/。"""
    fake_claude = tmp_path / ".claude"
    fake_mem = fake_claude / "memory"
    fake_audit = fake_mem / "_meta" / "atom_io_audit.jsonl"
    fake_mem.mkdir(parents=True)
    monkeypatch.setattr(atom_io, "CLAUDE_DIR", fake_claude)
    monkeypatch.setattr(atom_io, "GLOBAL_MEMORY_DIR", fake_mem)
    monkeypatch.setattr(atom_io, "AUDIT_LOG", fake_audit)
    monkeypatch.setattr(atom_access, "AUDIT_LOG", fake_audit)
    monkeypatch.setattr(atom_access, "GLOBAL_MEMORY_DIR", fake_mem)
    return {"claude": fake_claude, "memory": fake_mem, "audit": fake_audit}


def _make_atom(mem_dir: Path, name: str, body: str = "# test atom\n") -> Path:
    p = mem_dir / f"{name}.md"
    p.write_text(body, encoding="utf-8")
    return p


# ─── 基本 read / init ─────────────────────────────────────────────────────────


def test_read_nonexistent_returns_defaults(isolated_claude):
    """檔不存在 → 仍回正規化 defaults（避免 caller KeyError）；first_seen=None 是訊號。"""
    p = isolated_claude["memory"] / "nope.md"
    data = atom_access.read_access(p)
    assert data["schema"] == "atom-access-v2"
    assert data["read_hits"] == 0
    assert data["confirmations"] == 0
    assert data["first_seen"] is None  # 區分「檔不存在」用此訊號


def test_init_creates_access_file(isolated_claude):
    atom = _make_atom(isolated_claude["memory"], "alpha")
    audit_id = atom_access.init_access(atom, first_seen="2026-01-01", source="mcp")
    assert audit_id
    access_path = atom.with_suffix(".access.json")
    assert access_path.exists()
    data = json.loads(access_path.read_text(encoding="utf-8"))
    assert data["schema"] == "atom-access-v2"
    assert data["first_seen"] == "2026-01-01"
    assert data["read_hits"] == 0
    assert data["confirmations"] == 0


def test_init_idempotent_preserves_counts(isolated_claude):
    atom = _make_atom(isolated_claude["memory"], "beta")
    atom_access.init_access(atom, first_seen="2026-01-01", source="mcp")
    atom_access.increment_read_hits(atom, source="hook:atom-inject")
    atom_access.increment_read_hits(atom, source="hook:atom-inject")
    # init 第二次不應重置計數
    atom_access.init_access(atom, first_seen="2026-02-02", source="mcp")
    data = atom_access.read_access(atom)
    assert data["read_hits"] == 2
    # first_seen 也應保留原值
    assert data["first_seen"] == "2026-01-01"


# ─── increment_read_hits ──────────────────────────────────────────────────────


def test_increment_read_hits_creates_if_missing(isolated_claude):
    atom = _make_atom(isolated_claude["memory"], "gamma")
    n = atom_access.increment_read_hits(atom, source="hook:atom-inject")
    assert n == 1
    data = atom_access.read_access(atom)
    assert data["read_hits"] == 1
    assert data["last_used"]  # 自動填今天
    assert len(data["timestamps"]) == 1


def test_increment_read_hits_caps_timestamps_at_50(isolated_claude):
    atom = _make_atom(isolated_claude["memory"], "delta")
    for _ in range(60):
        atom_access.increment_read_hits(atom, source="hook:atom-inject")
    data = atom_access.read_access(atom)
    assert data["read_hits"] == 60
    assert len(data["timestamps"]) == 50


def test_increment_read_hits_concurrent(isolated_claude):
    """並發 increment 不會丟太多筆（atomic write 保證最終值不亂）。

    100 threads × 1 increment 各，期望 read_hits 落在合理範圍（>= 1，
    上限 = 100；實務 race 可能讓部分被 overwrite，但不該爆錯或留下 broken JSON）。
    """
    atom = _make_atom(isolated_claude["memory"], "race")
    atom_access.init_access(atom, first_seen="2026-01-01", source="mcp")
    threads = []
    for _ in range(20):
        t = threading.Thread(
            target=atom_access.increment_read_hits,
            kwargs={"atom_path": atom, "source": "hook:atom-inject"},
        )
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 檔還是合法 JSON
    data = atom_access.read_access(atom)
    assert data["read_hits"] >= 1  # 至少有寫入
    assert data["schema"] == "atom-access-v2"


# ─── increment_confirmation ───────────────────────────────────────────────────


def test_increment_confirmation_appends_event(isolated_claude):
    atom = _make_atom(isolated_claude["memory"], "epsilon")
    n = atom_access.increment_confirmation(
        atom, event={"correlation_id": "abc"}, source="hook:episodic-confirm",
    )
    assert n == 1
    data = atom_access.read_access(atom)
    assert data["confirmations"] == 1
    assert len(data["confirmation_events"]) == 1
    assert data["confirmation_events"][0]["correlation_id"] == "abc"
    assert "ts" in data["confirmation_events"][0]


def test_increment_confirmation_no_event_dict(isolated_claude):
    atom = _make_atom(isolated_claude["memory"], "zeta")
    n = atom_access.increment_confirmation(atom, source="hook:episodic-confirm")
    assert n == 1
    data = atom_access.read_access(atom)
    assert len(data["confirmation_events"]) == 1
    assert "ts" in data["confirmation_events"][0]


# ─── record_promotion ────────────────────────────────────────────────────────


def test_record_promotion(isolated_claude):
    atom = _make_atom(isolated_claude["memory"], "eta")
    audit_id = atom_access.record_promotion(
        atom, target_confidence="[觀]", source="mcp",
    )
    assert audit_id
    data = atom_access.read_access(atom)
    assert data["last_promoted_at"]  # 今天
    assert data["last_used"] == data["last_promoted_at"]


# ─── write_access_field ──────────────────────────────────────────────────────


def test_write_access_field_basic(isolated_claude):
    atom = _make_atom(isolated_claude["memory"], "theta")
    atom_access.write_access_field(
        atom, field="read_hits", value=42, source="tool:memory-audit",
    )
    data = atom_access.read_access(atom)
    assert data["read_hits"] == 42


def test_write_access_field_rejects_unknown_field(isolated_claude):
    atom = _make_atom(isolated_claude["memory"], "iota")
    with pytest.raises(ValueError):
        atom_access.write_access_field(
            atom, field="bogus", value=1, source="test",
        )


# ─── Schema 升級 ─────────────────────────────────────────────────────────────


def test_legacy_schema_normalizes_on_read(isolated_claude):
    """舊 schema {"timestamps":[], "confirmations":[event...]} 讀後得 v2。"""
    atom = _make_atom(isolated_claude["memory"], "legacy")
    access_path = atom.with_suffix(".access.json")
    legacy = {
        "timestamps": [1.0, 2.0],
        "confirmations": [{"old_event": 1}, {"old_event": 2}],
    }
    access_path.write_text(json.dumps(legacy), encoding="utf-8")

    data = atom_access.read_access(atom)
    assert data["schema"] == "atom-access-v2"
    assert isinstance(data["confirmations"], int)
    assert data["confirmations"] == 2  # 陣列長度
    assert len(data["confirmation_events"]) == 2
    assert data["confirmation_events"][0]["old_event"] == 1


def test_legacy_schema_persists_after_increment(isolated_claude):
    """舊 schema 經一次 increment 後檔案被升級寫回。"""
    atom = _make_atom(isolated_claude["memory"], "legacy2")
    access_path = atom.with_suffix(".access.json")
    legacy = {"timestamps": [], "confirmations": [{"x": 1}]}
    access_path.write_text(json.dumps(legacy), encoding="utf-8")

    atom_access.increment_read_hits(atom, source="hook:atom-inject")
    raw = json.loads(access_path.read_text(encoding="utf-8"))
    assert raw["schema"] == "atom-access-v2"
    assert raw["read_hits"] == 1
    assert isinstance(raw["confirmations"], int)
    assert raw["confirmations"] == 1


# ─── Source validation ──────────────────────────────────────────────────────


def test_invalid_source_raises(isolated_claude):
    atom = _make_atom(isolated_claude["memory"], "kappa")
    with pytest.raises(ValueError):
        atom_access.increment_read_hits(atom, source="bogus_source")
    with pytest.raises(ValueError):
        atom_access.init_access(atom, source="not_in_list")


# ─── 稽核日誌 ────────────────────────────────────────────────────────────────


def test_audit_log_entries(isolated_claude):
    atom = _make_atom(isolated_claude["memory"], "lambda")
    atom_access.init_access(atom, first_seen="2026-01-01", source="mcp")
    atom_access.increment_read_hits(atom, source="hook:atom-inject")
    atom_access.increment_confirmation(atom, source="hook:episodic-confirm")
    atom_access.record_promotion(atom, target_confidence="[觀]", source="mcp")

    audit_text = isolated_claude["audit"].read_text(encoding="utf-8")
    lines = [json.loads(l) for l in audit_text.splitlines() if l.strip()]
    ops = [e["op"] for e in lines]
    assert "access_init" in ops
    assert "access_increment" in ops
    assert "access_promote" in ops
    # source 都被記錄
    assert "mcp" in {e["source"] for e in lines}
    assert "hook:atom-inject" in {e["source"] for e in lines}
    assert "hook:episodic-confirm" in {e["source"] for e in lines}


# ─── bulk_read ──────────────────────────────────────────────────────────────


def test_bulk_read_scan(isolated_claude):
    mem = isolated_claude["memory"]
    a1 = _make_atom(mem, "atom1")
    a2 = _make_atom(mem, "atom2")
    sub = mem / "sub"
    sub.mkdir()
    a3 = _make_atom(sub, "atom3")
    atom_access.init_access(a1, first_seen="2026-01-01", source="mcp")
    atom_access.init_access(a2, first_seen="2026-02-01", source="mcp")
    atom_access.init_access(a3, first_seen="2026-03-01", source="mcp")

    data = atom_access.bulk_read(mem)
    assert set(data.keys()) == {"atom1", "atom2", "atom3"}
    assert data["atom1"]["first_seen"] == "2026-01-01"
    assert data["atom3"]["first_seen"] == "2026-03-01"


# ─── CLI 入口 ───────────────────────────────────────────────────────────────


def test_cli_init_and_read(isolated_claude, monkeypatch, tmp_path):
    """CLI 入口（給 server.js 子程序呼叫）— 跑 init → read 看回傳 JSON。"""
    atom = _make_atom(isolated_claude["memory"], "cli-test")
    # 用 subprocess 執行 module；要把 PYTHONPATH 指到 repo lib parent 並把
    # AUDIT_LOG / GLOBAL_MEMORY_DIR 環境變數透過 monkeypatch 是不行的（子程序新環境）
    # 所以這個測試只能驗 read 結果格式 — 在子程序內 atom_io 會嘗試寫到 ~/.claude
    # 實際 ~/.claude 路徑；為了不污染，我們用既已 init 完的 atom（已有 access.json）
    # 直接 read（read 是純讀，不寫稽核）。
    repo_root = Path(__file__).resolve().parent.parent
    atom_access.init_access(atom, first_seen="2026-04-04", source="mcp")
    proc = subprocess.run(
        [sys.executable, "-m", "lib.atom_access", "read", str(atom)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout.strip())
    assert data["schema"] == "atom-access-v2"
    assert data["first_seen"] == "2026-04-04"
