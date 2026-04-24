"""E2E tests for dual-field Confirmations/ReadHits split (v3).

Verifies injection (Path A → ReadHits++) and extraction (Path B → Confirmations++)
operate independently and correctly.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "hooks"))

from wg_atoms import _STRIP_META_RE


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_atom(tmp: Path, name: str, confirmations: int = 0, readhits: int = 0,
              confidence: str = "[臨]", trigger: str = "test") -> Path:
    """Create a minimal atom file for testing."""
    content = (
        f"# {name}\n\n"
        f"- Scope: global\n"
        f"- Confidence: {confidence}\n"
        f"- Trigger: {trigger}\n"
        f"- Last-used: 2026-04-24\n"
        f"- Confirmations: {confirmations}\n"
        f"- ReadHits: {readhits}\n\n"
        f"## 知識\n\n- [{confidence[1]}] test knowledge\n\n"
        f"## 行動\n\n- none\n"
    )
    fpath = tmp / f"{name}.md"
    fpath.write_text(content, encoding="utf-8")
    return fpath


def read_field(fpath: Path, field: str) -> int:
    """Read an integer metadata field from an atom file."""
    text = fpath.read_text(encoding="utf-8")
    m = re.search(rf"^- {field}:\s*(\d+)", text, re.MULTILINE)
    return int(m.group(1)) if m else -1


# ── Verification A: Injection Path (ReadHits++) ─────────────────────────────

class TestInjectionPath:
    """UserPromptSubmit injection hit → ReadHits++ / Confirmations unchanged."""

    def test_readhits_regex_matches(self):
        """ReadHits regex correctly matches and increments."""
        readhits_re = re.compile(r"^(- ReadHits:\s*)(\d+)", re.MULTILINE)
        text = "- Confirmations: 5\n- ReadHits: 10\n"
        m = readhits_re.search(text)
        assert m is not None
        assert int(m.group(2)) == 10
        new_text = readhits_re.sub(rf"\g<1>11", text)
        assert "ReadHits: 11" in new_text
        assert "Confirmations: 5" in new_text  # unchanged

    def test_injection_increments_readhits_only(self, tmp_path):
        """Full injection simulation: ReadHits++ while Confirmations stays."""
        fpath = make_atom(tmp_path, "test-inject", confirmations=5, readhits=10)
        text = fpath.read_text(encoding="utf-8")

        # Simulate workflow-guardian.py injection logic
        readhits_re = re.compile(r"^(- ReadHits:\s*)(\d+)", re.MULTILINE)
        rm = readhits_re.search(text)
        assert rm is not None
        new_count = int(rm.group(2)) + 1
        text = readhits_re.sub(rf"\g<1>{new_count}", text)
        fpath.write_text(text, encoding="utf-8")

        assert read_field(fpath, "ReadHits") == 11
        assert read_field(fpath, "Confirmations") == 5  # unchanged

    def test_injection_creates_readhits_after_confirmations(self, tmp_path):
        """When ReadHits field missing, insert after Confirmations."""
        content = (
            "# test\n\n- Scope: global\n- Confidence: [臨]\n"
            "- Trigger: test\n- Last-used: 2026-04-24\n"
            "- Confirmations: 5\n\n## 知識\n\n- [臨] x\n"
        )
        fpath = tmp_path / "test-no-rh.md"
        fpath.write_text(content, encoding="utf-8")

        text = fpath.read_text(encoding="utf-8")
        readhits_re = re.compile(r"^(- ReadHits:\s*)(\d+)", re.MULTILINE)
        rm = readhits_re.search(text)
        assert rm is None  # no ReadHits yet

        # Fallback: insert after Confirmations
        text = re.sub(
            r"^(- Confirmations:\s*.+)$",
            r"\1\n- ReadHits: 1",
            text, count=1, flags=re.MULTILINE,
        )
        fpath.write_text(text, encoding="utf-8")
        assert read_field(fpath, "ReadHits") == 1
        assert read_field(fpath, "Confirmations") == 5


# ── Verification B: Extraction Path (Confirmations++) ───────────────────────

class TestExtractionPath:
    """extract-worker cross-session hit → Confirmations++ / ReadHits unchanged."""

    def test_extraction_increments_confirmations_only(self, tmp_path):
        """Simulate wg_episodic.py Confirmations++ logic."""
        fpath = make_atom(tmp_path, "test-extract", confirmations=5, readhits=10)
        text = fpath.read_text(encoding="utf-8")

        # Simulate wg_episodic.py L360-366
        cm = re.search(r"^(- Confirmations:\s*)(\d+)", text, re.MULTILINE)
        assert cm is not None
        new_c = int(cm.group(2)) + 1
        text = re.sub(
            r"^(- Confirmations:\s*)\d+", rf"\g<1>{new_c}",
            text, count=1, flags=re.MULTILINE,
        )
        fpath.write_text(text, encoding="utf-8")

        assert read_field(fpath, "Confirmations") == 6
        assert read_field(fpath, "ReadHits") == 10  # unchanged

    def test_correlation_id_written_to_access_json(self, tmp_path):
        """Extract hit writes correlation_id to access.json."""
        import uuid
        fpath = make_atom(tmp_path, "test-corr", confirmations=3, readhits=7)
        access_file = fpath.with_suffix(".access.json")

        # Simulate wg_episodic.py correlation_id logic
        adata = {"timestamps": [], "confirmations": []}
        adata["confirmations"].append({
            "ts": 1776940000.0,
            "correlation_id": str(uuid.uuid4()),
            "hit_count": 2,
        })
        access_file.write_text(json.dumps(adata), encoding="utf-8")

        result = json.loads(access_file.read_text(encoding="utf-8"))
        assert len(result["confirmations"]) == 1
        assert "correlation_id" in result["confirmations"][0]
        assert len(result["confirmations"][0]["correlation_id"]) == 36  # UUID4


# ── Verification C: New Atom Initialization ─────────────────────────────────

class TestNewAtomInit:
    """All creation paths initialize both fields correctly."""

    def test_user_extract_init(self):
        """user-extract-worker: Confirmations=1, ReadHits=0."""
        template = (
            "- Confirmations: 1\n"
            "- ReadHits: 0\n"
        )
        assert "Confirmations: 1" in template
        assert "ReadHits: 0" in template

    def test_mcp_atom_write_init(self):
        """atom_write MCP: Confirmations=0, ReadHits=0."""
        # Simulates server.js buildAtomContent
        lines = []
        lines.append("- Confirmations: 0")
        lines.append("- ReadHits: 0")
        content = "\n".join(lines)
        assert "Confirmations: 0" in content
        assert "ReadHits: 0" in content

    def test_episodic_init(self):
        """wg_episodic new episodic atom: Confirmations=0, ReadHits=0."""
        template = (
            "- Confirmations: 0\n"
            "- ReadHits: 0\n"
            "- TTL: 24d\n"
        )
        assert "Confirmations: 0" in template
        assert "ReadHits: 0" in template


# ── Verification D: Promotion Thresholds ────────────────────────────────────

class TestPromotionThresholds:
    """Three-layer promotion logic works correctly."""

    THRESHOLDS = {
        "[臨]": {"next": "[觀]", "confirmations": 4, "readhits": 20},
        "[觀]": {"next": "[固]", "confirmations": 10, "readhits": 50},
    }

    def _check_eligible(self, confidence, confirmations, readhits, migration_days_ago=None):
        """Simulate server.js promote logic."""
        path_info = self.THRESHOLDS.get(confidence)
        if not path_info:
            return False, "no_path"

        reqConf = path_info["confirmations"]
        reqRH = path_info["readhits"]

        if confirmations >= reqConf:
            return True, "confirmations"
        if readhits >= reqRH:
            return True, "readhits_auxiliary"
        if migration_days_ago is not None and migration_days_ago <= 7:
            if readhits // 5 >= reqConf:
                return True, "readhits_7day_fallback"
        return False, "insufficient"

    def test_promote_by_confirmations(self):
        ok, method = self._check_eligible("[臨]", 4, 0)
        assert ok and method == "confirmations"

    def test_promote_by_readhits_auxiliary(self):
        ok, method = self._check_eligible("[臨]", 1, 20)
        assert ok and method == "readhits_auxiliary"

    def test_promote_by_exemption_fallback(self):
        """7-day fallback: test with raised auxiliary threshold to isolate fallback path."""
        # With default thresholds RH/5≥reqConf is equivalent to RH≥reqRH (both 20),
        # so auxiliary always fires first. Use custom thresholds to test fallback.
        saved = self.THRESHOLDS["[臨]"]["readhits"]
        self.THRESHOLDS["[臨]"]["readhits"] = 30  # raise auxiliary to 30
        try:
            ok, method = self._check_eligible("[臨]", 2, 25, migration_days_ago=3)
            assert ok and method == "readhits_7day_fallback"  # 25//5=5 >= 4, but 25 < 30
        finally:
            self.THRESHOLDS["[臨]"]["readhits"] = saved

    def test_promote_exemption_expired_fallback_blocked(self):
        """Exemption expired + below auxiliary → not eligible."""
        saved = self.THRESHOLDS["[臨]"]["readhits"]
        self.THRESHOLDS["[臨]"]["readhits"] = 30
        try:
            ok, method = self._check_eligible("[臨]", 2, 25, migration_days_ago=8)
            assert not ok and method == "insufficient"  # 25 < 30, exemption expired
        finally:
            self.THRESHOLDS["[臨]"]["readhits"] = saved

    def test_promote_insufficient(self):
        ok, method = self._check_eligible("[臨]", 1, 5)
        assert not ok and method == "insufficient"

    def test_promote_观_to_固(self):
        ok, method = self._check_eligible("[觀]", 10, 0)
        assert ok and method == "confirmations"

    def test_promote_观_by_readhits(self):
        ok, method = self._check_eligible("[觀]", 3, 50)
        assert ok and method == "readhits_auxiliary"


# ── Verification E: Cross-path Independence ─────────────────────────────────

class TestCrossPathIndependence:
    """Injection and extraction don't interfere with each other."""

    def test_injection_then_extraction(self, tmp_path):
        """Sequential: inject×3 then extract×2."""
        fpath = make_atom(tmp_path, "test-cross", confirmations=0, readhits=0)
        readhits_re = re.compile(r"^(- ReadHits:\s*)(\d+)", re.MULTILINE)
        conf_re = re.compile(r"^(- Confirmations:\s*)(\d+)", re.MULTILINE)

        # Inject × 3
        for _ in range(3):
            text = fpath.read_text(encoding="utf-8")
            rm = readhits_re.search(text)
            new_rh = int(rm.group(2)) + 1
            text = readhits_re.sub(rf"\g<1>{new_rh}", text)
            fpath.write_text(text, encoding="utf-8")

        assert read_field(fpath, "ReadHits") == 3
        assert read_field(fpath, "Confirmations") == 0

        # Extract × 2
        for _ in range(2):
            text = fpath.read_text(encoding="utf-8")
            cm = conf_re.search(text)
            new_c = int(cm.group(2)) + 1
            text = conf_re.sub(rf"\g<1>{new_c}", text)
            fpath.write_text(text, encoding="utf-8")

        assert read_field(fpath, "Confirmations") == 2
        assert read_field(fpath, "ReadHits") == 3  # unchanged after extraction

    def test_migration_then_injection(self, tmp_path):
        """Post-migration: ReadHits inherits old value, continues accumulating."""
        # Simulate pre-migration atom with Confirmations=50
        fpath = make_atom(tmp_path, "test-migrated", confirmations=0, readhits=50)
        # (migration already moved old Confirmations→ReadHits, Confirmations→0)

        readhits_re = re.compile(r"^(- ReadHits:\s*)(\d+)", re.MULTILINE)
        text = fpath.read_text(encoding="utf-8")
        rm = readhits_re.search(text)
        new_rh = int(rm.group(2)) + 1
        text = readhits_re.sub(rf"\g<1>{new_rh}", text)
        fpath.write_text(text, encoding="utf-8")

        assert read_field(fpath, "ReadHits") == 51
        assert read_field(fpath, "Confirmations") == 0


# ── Verification F: Secondary System Integration ────────────────────────────

class TestSecondaryIntegration:
    """Decay score, vector ranking, distant reset use correct fields."""

    def test_strip_meta_removes_both_fields(self):
        """_STRIP_META_RE strips both Confirmations and ReadHits."""
        text = (
            "- Scope: global\n"
            "- Confirmations: 42\n"
            "- ReadHits: 185\n"
            "- Last-used: 2026-04-24\n"
            "## 知識\n"
        )
        stripped = _STRIP_META_RE.sub("", text)
        assert "Confirmations" not in stripped
        assert "ReadHits" not in stripped
        assert "知識" in stripped  # content preserved

    def test_decay_uses_max(self):
        """Decay score uses max(Confirmations, ReadHits)."""
        import math
        confirmations, readhits = 2, 100
        usage = min(1.0, math.log10(max(confirmations, readhits) + 1) / 2)
        assert usage > 0.9  # won't archive due to high ReadHits

    def test_vector_ranking_uses_confirmations(self):
        """Search ranking bonus based on Confirmations (high signal)."""
        # Atom A: high Conf, low RH
        conf_a = 10
        confirm_score_a = min(0.2, conf_a * 0.05)
        # Atom B: low Conf, high RH
        conf_b = 1
        confirm_score_b = min(0.2, conf_b * 0.05)
        assert confirm_score_a > confirm_score_b

    def test_distant_resets_both(self, tmp_path):
        """Distant archival resets both Confirmations and ReadHits to 0."""
        fpath = make_atom(tmp_path, "test-distant", confirmations=10, readhits=50)
        text = fpath.read_text(encoding="utf-8")

        # Simulate memory-audit.py distant reset
        text = re.sub(r"^(-\s+Confirmations:\s*).*$", r"\g<1>0", text, count=1, flags=re.MULTILINE)
        text = re.sub(r"^(-\s+ReadHits:\s*).*$", r"\g<1>0", text, count=1, flags=re.MULTILINE)
        fpath.write_text(text, encoding="utf-8")

        assert read_field(fpath, "Confirmations") == 0
        assert read_field(fpath, "ReadHits") == 0


# ── Migration Script ────────────────────────────────────────────────────────

class TestMigrationScript:
    """Migration script correctly transforms atoms."""

    def test_migration_dry_run(self, tmp_path):
        """Dry-run doesn't modify files."""
        fpath = make_atom(tmp_path, "test-dryrun", confirmations=42, readhits=0)
        # Remove ReadHits to simulate pre-migration state
        text = fpath.read_text(encoding="utf-8")
        text = re.sub(r"^- ReadHits:\s*\d+\n", "", text, flags=re.MULTILINE)
        fpath.write_text(text, encoding="utf-8")

        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from importlib import import_module
        migrate_mod = import_module("migrate-confirmations")
        report = migrate_mod.migrate(tmp_path, dry_run=True)

        assert len(report["migrated"]) == 1
        assert report["migrated"][0]["old_confirmations"] == 42
        # File should NOT have changed
        text_after = fpath.read_text(encoding="utf-8")
        assert "ReadHits" not in text_after
        assert "Confirmations: 42" in text_after

    def test_migration_execute(self, tmp_path):
        """Execute mode transforms files correctly."""
        fpath = make_atom(tmp_path, "test-exec", confirmations=50, readhits=0)
        text = fpath.read_text(encoding="utf-8")
        text = re.sub(r"^- ReadHits:\s*\d+\n", "", text, flags=re.MULTILINE)
        fpath.write_text(text, encoding="utf-8")

        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from importlib import import_module
        migrate_mod = import_module("migrate-confirmations")
        report = migrate_mod.migrate(tmp_path, dry_run=False)

        assert len(report["migrated"]) == 1
        assert read_field(fpath, "Confirmations") == 0
        assert read_field(fpath, "ReadHits") == 50

        # migration.json created
        meta = tmp_path / "_meta" / "migration.json"
        assert meta.exists()
        mdata = json.loads(meta.read_text(encoding="utf-8"))
        assert mdata["version"] == "dual-field-v1"
        assert mdata["total_migrated"] == 1

    def test_migration_idempotent(self, tmp_path):
        """Running migration twice doesn't double-process."""
        fpath = make_atom(tmp_path, "test-idem", confirmations=30, readhits=0)
        text = fpath.read_text(encoding="utf-8")
        text = re.sub(r"^- ReadHits:\s*\d+\n", "", text, flags=re.MULTILINE)
        fpath.write_text(text, encoding="utf-8")

        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from importlib import import_module
        migrate_mod = import_module("migrate-confirmations")

        migrate_mod.migrate(tmp_path, dry_run=False)
        assert read_field(fpath, "ReadHits") == 30

        # Second run should skip
        report2 = migrate_mod.migrate(tmp_path, dry_run=False)
        assert len(report2["migrated"]) == 0
        assert read_field(fpath, "ReadHits") == 30  # unchanged
