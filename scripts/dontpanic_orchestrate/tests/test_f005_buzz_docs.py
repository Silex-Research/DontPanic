"""F005: Buzz as strongly recommended caller/notify surface — doc contract.

Asserts ECOSYSTEM.md and GETTING_STARTED.md carry the F005 requirements:
caller row, private-vs-public community split, locked non-goals, identity
mapping, no forced joining of maintainer-owned communities, and that the
unshipped DontPanic-side integration is marked as planned rather than
presented as operational.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ECOSYSTEM = ROOT / "docs" / "ECOSYSTEM.md"
GETTING_STARTED = ROOT / "docs" / "GETTING_STARTED.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(path: Path) -> str:
    """Doc text with all whitespace collapsed, so hard-wrapping can't break asserts."""
    return re.sub(r"\s+", " ", _read(path))


def _caller_table_rows(text: str) -> list[str]:
    section = text.split("## Who calls DontPanic", 1)[1].split("\n## ", 1)[0]
    return [line for line in section.splitlines() if line.startswith("| ")]


def test_ecosystem_caller_table_has_buzz_row_strongly_recommended() -> None:
    rows = [r for r in _caller_table_rows(_read(ECOSYSTEM)) if "Buzz" in r]
    assert rows, "callers table must include a Buzz row"
    assert "**strongly recommended**" in rows[0]
    assert "private" in rows[0].lower()


def test_buzz_section_exists_and_is_strongly_recommended_not_required() -> None:
    text = _read(ECOSYSTEM)
    assert "## Buzz as caller and notify surface (strongly recommended)" in text
    assert "not a hard dependency" in text
    assert "never required" in text


def test_private_community_is_default_work_surface() -> None:
    eco = _read(ECOSYSTEM)
    assert "### Community model: private by default" in eco
    assert "**Private operator community** (default)" in eco
    gs = _read(GETTING_STARTED)
    assert "**private community that you create and own**" in gs


def test_no_forced_join_of_maintainer_owned_communities() -> None:
    eco = _flat(ECOSYSTEM)
    assert (
        "DontPanic never requires you to join or post into a maintainer-owned community"
        in eco
    )
    gs = _flat(GETTING_STARTED)
    assert "never required to join or post into a maintainer-owned community" in gs
    for text in (eco, gs):
        assert not re.search(r"must join|required to join the", text, re.I)


def test_silex_is_private_dogfood_not_public_support() -> None:
    eco = _read(ECOSYSTEM)
    assert "**Maintainer dogfood:**" in eco
    assert "not a support channel" in eco
    gs = _read(GETTING_STARTED)
    assert "not a public support surface" in gs
    # The i0 audit flagged "public Silex" phrasing as contradicting the
    # private-dogfood classification — it must not reappear.
    for text in (eco, gs):
        assert "public Silex" not in text


def test_non_goals_locked() -> None:
    text = _read(ECOSYSTEM)
    section = text.split("### Buzz non-goals (locked)", 1)[1]
    assert "**No relay or Nostr client inside DontPanic.**" in section
    assert "**No forced join of maintainer-owned communities.**" in section
    assert "**No auto-confirm from chat.**" in section
    assert "**No secrets on relays.**" in section


def test_identity_mapping_is_legibility_not_authorization() -> None:
    text = _flat(ECOSYSTEM)
    assert "### Identity mapping: builder key ≠ auditor key" in text
    assert "legibility convention only" in text
    assert "Buzz community membership is not authorization" in text
    assert "`AGENT_REGISTRY`" in text


def test_caller_sketch_present() -> None:
    text = _read(ECOSYSTEM)
    assert "### Concrete integration recipe (Buzz-as-caller, sketch)" in text
    assert "reactions/emoji never auto-confirm" in text


def test_integration_status_doctor_and_notify_sink_shipped() -> None:
    """F009 shipped the setup/doctor Buzz check; F006 (2026-07-27-001)
    shipped the notify sink. The docs must state both honestly — the doctor
    check as live (advisory WARN, never a failure) and the sink as shipped
    AND fail-soft (never a hard dependency)."""
    eco = _read(ECOSYSTEM)
    assert (
        "**Integration status: doctor check and notify sink shipped.**"
        in eco
    )
    assert "fail-soft" in eco
    gs = _read(GETTING_STARTED)
    assert "**fail-soft**" in gs
    # The pre-F006 "planned / not yet shipped" markers must not survive —
    # they would now understate what ships.
    for text in (eco, _flat(GETTING_STARTED)):
        assert "not yet shipped" not in text
    # Every buzz.json mention must sit in an honest-status context: the
    # shipped doctor-check behavior (advisory / doctor) or the shipped
    # fail-soft sink behavior.
    for path, name in ((ECOSYSTEM, "ECOSYSTEM"), (GETTING_STARTED, "GETTING_STARTED")):
        flat = _flat(path)
        for match in re.finditer(r"buzz\.json", flat):
            context = flat[max(0, match.start() - 400) : match.end() + 400].lower()
            assert (
                "fail-soft" in context
                or "advisory" in context
                or "doctor" in context
                or "notify sink" in context
            ), (
                f"{name}: buzz.json mentioned without a nearby status marker "
                f"(fail-soft / advisory / doctor / notify sink) at offset "
                f"{match.start()}"
            )
    # The i0 audit flagged this nonfunctional checklist step.
    assert "until Buzz shows configured" not in gs


def test_missing_buzz_config_documented_as_advisory_never_failure() -> None:
    """F009: both docs describe the shipped doctor behavior — missing Buzz
    config is an advisory WARN, never a failure — and name the CI silence env."""
    for path in (ECOSYSTEM, GETTING_STARTED):
        flat = _flat(path)
        assert "advisory WARN" in flat
        assert "DONTPANIC_SKIP_BUZZ" in flat


def test_self_host_vs_hosted_relay_guidance_present() -> None:
    text = _read(ECOSYSTEM)
    assert "**Self-host vs buzz.xyz:**" in text
    assert "projections" in text
    assert "self-host the relay" in text
