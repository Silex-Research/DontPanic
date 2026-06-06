"""Plan 2026-06-05-001 F005 — install-level capabilities reach the fleet surface.

build_fleet_what_now only aggregates the tracked projects' caches; install-level
capability items live in the DontPanic repo (never a tracked project), so the
fleet envelope had 0 capability items and the All-Projects view could not show
"Global tools". F005 includes the install capability items via a reusable
``dashboard.gather_install_capability_items`` seam and preserves the
``group=global_tool_setup`` tag through the fleet render boundary (which uses
``to_dict()``, bypassing ``action_view``).
"""

from __future__ import annotations

import json

import pytest

from dontpanic_orchestrate import dashboard
from dontpanic_orchestrate import operator_console as oc
from dontpanic_orchestrate import projects_dashboard as pd
from dontpanic_orchestrate import projects_registry as pr


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "alpha-repo"
    (d / "docs" / "plans").mkdir(parents=True)
    return d


def _cap_item() -> oc.ActionItem:
    return oc.ActionItem(
        id="capability:linear",
        source=oc.SOURCE_CAPABILITY,
        band=oc.Band.NEEDS_ACTION,
        title="Capability linear is not installed",
        detail="Setup: Install the Linear adapter",
        exact_command="dontpanic capabilities setup linear --print-steps",
        automatable=False,
        human_required_reason="operator must register the adapter",
        evidence_uri=None,
        updated_at="2026-06-05T00:00:00Z",
        dedupe_key="capability:linear",
    )


def test_fleet_envelope_includes_install_capability_items_with_group(
    monkeypatch, project_dir
) -> None:
    monkeypatch.setattr(
        dashboard, "gather_install_capability_items", lambda *a, **k: (_cap_item(),)
    )
    ctx = pd.project_context_from_entry(
        pr.add_project(name="alpha", path=str(project_dir))
    )
    report = pd.build_project_state(ctx)
    out = pd.build_fleet_what_now([report])
    payload = json.loads(out.read_text())

    caps = [it for it in payload["items"] if it.get("source") == "capability"]
    assert len(caps) == 1, "install capability item must reach the fleet envelope"
    assert caps[0]["group"] == "global_tool_setup", "group tag preserved through fleet boundary"
    assert caps[0]["exact_command"] == "dontpanic capabilities setup linear --print-steps"
    # Non-capability items carry no global-tool group.
    others = [it for it in payload["items"] if it.get("source") != "capability"]
    assert all(it.get("group") is None for it in others)


def test_gather_install_capability_items_is_best_effort_empty(tmp_path) -> None:
    # An empty repo (no capability manifests) yields no items, never raises.
    result = dashboard.gather_install_capability_items(repo_root=tmp_path)
    assert isinstance(result, tuple)
    assert all(it.source == oc.SOURCE_CAPABILITY for it in result)
