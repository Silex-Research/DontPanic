"""Plan 2026-08-09-004 F008 — a data-only add is picked up by the walker."""

from __future__ import annotations

from pathlib import Path

from dontpanic_orchestrate.smoke.corpus import discover_scenarios


def test_guidance_add_is_discovered_without_package_edit() -> None:
    ids = {s.id for s in discover_scenarios()}
    assert "corpus-dirty-dispatch" in ids
    added = Path(
        "scripts/dontpanic_orchestrate/smoke/scenarios/corpus-dirty-dispatch/scenario.json"
    )
    assert added.is_file()
    guide = Path("docs/authoring-corpus-scenario.md")
    assert guide.is_file()
    text = guide.read_text()
    assert "Trigger" in text
    assert "same sitting" in text.lower() or "same sitting" in text
