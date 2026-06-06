"""Plan 2026-06-05-004 F003 — sufficiency-pack registry + unrouteable-skills inventory."""

from __future__ import annotations

from dontpanic_orchestrate.sufficiency_packs import (
    get_pack,
    is_stub_surface,
    unrouteable_skills,
)


def test_frontend_pack_is_seeded_with_items_and_references() -> None:
    items = get_pack("frontend-ui")
    assert items, "frontend pack must be seeded"
    ids = {it.id for it in items}
    assert {"design-system-consistency", "real-shell-journey-proof"} <= ids
    # every item names what to prove + a reference doc
    for it in items:
        assert it.prove
        assert it.reference
    refs = " ".join(it.reference for it in items)
    assert "dashboard-design-system.md" in refs
    assert "qa-sufficiency-contract.md" in refs


def test_other_surfaces_are_named_demand_gated_stubs() -> None:
    for surface in ("backend-api", "command", "mobile-app", "infra-deploy"):
        assert get_pack(surface) == []
        assert is_stub_surface(surface) is True
    assert is_stub_surface("frontend-ui") is False


def test_unknown_surface_returns_empty_pack_not_error() -> None:
    assert get_pack("quantum-teleporter") == []


def test_unrouteable_inventory_lists_skills_missing_or_malformed_applies_to() -> None:
    metas = [
        {"name": "good-skill", "applies_to": {"surfaces": ["web", "ux"]}},
        {"name": "no-meta-skill"},  # missing applies_to entirely
        {"name": "empty-skill", "applies_to": {"surfaces": []}},  # empty surfaces
        {"name": "malformed-skill", "applies_to": "web,ux"},  # not a dict
    ]
    out = unrouteable_skills(metas)
    assert out == ["empty-skill", "malformed-skill", "no-meta-skill"]
    assert "good-skill" not in out
