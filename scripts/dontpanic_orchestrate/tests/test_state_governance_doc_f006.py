"""Plan 2026-05-09-003 F006 — STATE_PROJECTION.md governance contract pins.

Asserts the doc exists with the four invariants and that the four
named cross-link docs reference it. This is a pin test, not a
behavioral test — F006 is doc work.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs" / "STATE_PROJECTION.md"


class TestGovernanceDoc:
    def test_doc_exists(self) -> None:
        assert DOC.is_file(), f"{DOC} missing"

    def test_four_invariants_named(self) -> None:
        text = DOC.read_text()
        # The four invariants per the F006 acceptance + schema docstring
        for invariant in (
            "Stable-ID discipline",
            "Schema-version pinning",
            "Redaction respect",
            "No write-back",
        ):
            assert invariant in text, f"invariant {invariant!r} missing from STATE_PROJECTION.md"

    def test_three_consumer_surfaces_named(self) -> None:
        text = DOC.read_text()
        assert "dontpanic state snapshot" in text
        assert "state_snapshot" in text
        assert "state_stream" in text

    def test_three_redact_levels_documented(self) -> None:
        text = DOC.read_text()
        for level in ("public", "operator", "full"):
            assert level in text

    def test_worked_example_present(self) -> None:
        text = DOC.read_text()
        # Worked example uses state_snapshot + state_stream via MCP
        assert "state_snapshot" in text
        assert "state_stream" in text
        assert "schema_version" in text


class TestCrossLinks:
    def test_use_cases_links_governance_doc(self) -> None:
        text = (ROOT / "docs" / "USE_CASES.md").read_text()
        assert "STATE_PROJECTION" in text or "state-projection" in text.lower()

    def test_ecosystem_links_governance_doc(self) -> None:
        text = (ROOT / "docs" / "ECOSYSTEM.md").read_text()
        assert "STATE_PROJECTION" in text or "state-projection" in text.lower()

    def test_agent_quickstart_links_governance_doc(self) -> None:
        text = (ROOT / "docs" / "AGENT_QUICKSTART.md").read_text()
        assert "STATE_PROJECTION" in text or "state-projection" in text.lower()

    def test_configuration_links_governance_doc(self) -> None:
        text = (ROOT / "docs" / "CONFIGURATION.md").read_text()
        assert "STATE_PROJECTION" in text or "state-projection" in text.lower()
