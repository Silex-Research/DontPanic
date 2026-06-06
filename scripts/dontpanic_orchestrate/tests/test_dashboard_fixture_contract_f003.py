"""Plan 2026-06-05-002 F003 — fixture↔producer contract.

The JS journey test (dashboard/tests/integration/dashboard-journey.test.js) drives a
committed real-state fixture through the real shell. This Python test guards that the
fixture stays FAITHFUL to the live producer: the fixture's capability items must carry
the same `group=global_tool_setup` tag + `capabilities setup <id> --print-steps`
command the producer emits. If the producer stops tagging the group, this fails —
signalling the fixture (and the journey test) has gone stale, instead of letting a
synthetic fixture quietly diverge from real output.
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import operator_console as oc
from dontpanic_orchestrate import projects_dashboard as pd

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE = _REPO_ROOT / "dashboard/tests/fixtures/real-state/fleet-what-now.json"


def _fixture_capability_items() -> list[dict]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return [it for it in (payload.get("items") or []) if it.get("source") == "capability"]


def test_fixture_capability_items_carry_group_and_setup_command() -> None:
    caps = _fixture_capability_items()
    assert caps, "real-state fixture must contain producer-generated capability items"
    for c in caps:
        assert c.get("group") == "global_tool_setup", c
        cmd = c.get("exact_command") or ""
        assert cmd.startswith("dontpanic capabilities setup ")
        assert cmd.endswith(" --print-steps"), cmd


def test_producer_still_emits_the_group_the_fixture_asserts() -> None:
    # The live fleet render boundary must tag a capability-source item with the same
    # group the fixture relies on. If this drifts, regenerate the fixture via
    # `dontpanic dashboard build --project all`.
    cap = oc.ActionItem(
        id="capability:linear",
        source=oc.SOURCE_CAPABILITY,
        band=oc.Band.NEEDS_ACTION,
        title="Capability linear is not installed",
        detail="Setup: …",
        exact_command="dontpanic capabilities setup linear --print-steps",
        automatable=False,
        human_required_reason="operator must register the adapter",
        evidence_uri=None,
        updated_at="2026-06-05T00:00:00Z",
        dedupe_key="capability:linear",
    )
    d = pd._fleet_item_to_dict(cap)  # noqa: SLF001 — the render-boundary projection
    assert d["group"] == "global_tool_setup"
    # A non-capability item must NOT get the global-tool group.
    gate = oc.ActionItem(
        id="gate:x",
        source=oc.SOURCE_GATE,
        band=oc.Band.NEEDS_ACTION,
        title="gate",
        detail=None,
        exact_command="dontpanic approve x pre_impl",
        automatable=False,
        human_required_reason="approval",
        evidence_uri=None,
        updated_at="2026-06-05T00:00:00Z",
        dedupe_key="gate:x",
    )
    assert pd._fleet_item_to_dict(gate)["group"] is None  # noqa: SLF001
