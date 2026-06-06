"""Plan 2026-06-05-004 F002 — surface derivation over the canonical vocabulary."""

from __future__ import annotations

from dontpanic_orchestrate.surface_derivation import derive_surfaces


def test_declared_only() -> None:
    d = derive_surfaces(declared=["read-only UI"], paths=[])
    assert d.canonical == {"frontend-ui"}
    assert d.unrouteable == set()


def test_path_only_dashboard() -> None:
    d = derive_surfaces(declared=[], paths=["dashboard/pages/repair/repair.js"])
    assert "frontend-ui" in d.canonical


def test_path_only_cli() -> None:
    d = derive_surfaces(declared=[], paths=["scripts/dontpanic_orchestrate/cli.py"])
    assert "command" in d.canonical


def test_combined_declared_and_paths_union() -> None:
    d = derive_surfaces(
        declared=["security"],
        paths=["dashboard/core.css", "ios/App/View.swift"],
    )
    assert {"security-review", "frontend-ui", "mobile-app"} <= d.canonical


def test_empty_inputs_derive_nothing() -> None:
    d = derive_surfaces(declared=[], paths=[])
    assert d.canonical == set()
    assert d.unrouteable == set()


def test_unknown_declared_surface_is_reported_unrouteable() -> None:
    d = derive_surfaces(declared=["quantum-teleporter"], paths=[])
    assert d.canonical == set()
    assert "quantum-teleporter" in d.unrouteable
