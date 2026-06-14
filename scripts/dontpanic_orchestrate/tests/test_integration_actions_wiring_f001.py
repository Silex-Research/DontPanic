"""Plan 2026-06-04-003 F001 — real-build wiring (finding #2/#5).

These tests prove the provider is wired through the SHIPPED dashboard
aggregation path (`_gather_action_items` / `build`), not just callable in
isolation: integration items must appear in the gathered card set with the
new display fields surviving the normalizers, and they must survive the
fleet/project projection rehydration round-trip where unknown sources are at
risk of being filtered.

The autouse conftest fixture redirects DONTPANIC_HOME to a tmp dir, so the
install-level integration evidence dir these tests write to is the same one
the provider reads from at build time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import dashboard  # noqa: E402
from dontpanic_orchestrate import global_config  # noqa: E402
from dontpanic_orchestrate import integration_actions as itg  # noqa: E402
from dontpanic_orchestrate import operator_console as oc  # noqa: E402


@pytest.fixture()
def plans_root(tmp_path):
    p = tmp_path / "plans"
    p.mkdir()
    return p


def _integration_items(cards):
    return [c for c in cards if getattr(c, "source", None) == oc.SOURCE_INTEGRATION]


def test_integration_items_reach_the_real_gathered_set(plans_root):
    cards = dashboard._gather_action_items(
        plans_root=plans_root,
        capability_envelope=None,
        reconcile_result=None,
        arch_status=None,
        plan_id=None,
    )
    integ = _integration_items(cards)
    # the static-dashboard smoke (no creds, no trigger) is always actionable
    ids = {c.id for c in integ}
    assert "integration:static-dashboard:static-dashboard-smoke" in ids
    # every integration card carries the new display fields through the gather
    smoke = next(c for c in integ if c.id.endswith("static-dashboard-smoke"))
    assert smoke.exact_command == "dontpanic integrations smoke static-dashboard"
    assert smoke.evidence_expected is not None
    assert smoke.credential_env_vars == ()


def test_passed_evidence_suppresses_the_action_card_through_the_gate(plans_root):
    # Write a passed smoke record into the install-level evidence dir the
    # provider + suppression gate both read.
    evidence_dir = global_config.dontpanic_home() / itg.EVIDENCE_SUBDIR
    evidence_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "schema_version": "1.0",
        "integration_id": "static-dashboard",
        "action_id": "static-dashboard-smoke",
        "outcome": "passed",
    }
    itg.evidence_file(evidence_dir, "static-dashboard").write_text(
        json.dumps(rec) + "\n"
    )

    cards = dashboard._gather_action_items(
        plans_root=plans_root,
        capability_envelope=None,
        reconcile_result=None,
        arch_status=None,
        plan_id=None,
    )
    ids = {c.id for c in _integration_items(cards)}
    # resolved via integration_evidence_present → suppressed at source
    assert "integration:static-dashboard:static-dashboard-smoke" not in ids


def test_display_fields_survive_fleet_projection_rehydration(plans_root):
    """Finding #5: the new source + display fields must survive the
    fleet/project projection serialize→rehydrate round-trip."""
    cards = dashboard._gather_action_items(
        plans_root=plans_root,
        capability_envelope=None,
        reconcile_result=None,
        arch_status=None,
        plan_id=None,
    )
    smoke = next(
        c for c in _integration_items(cards) if c.id.endswith("static-dashboard-smoke")
    )
    # serialize as the fleet cache does, then rehydrate via the shipped
    # constructor path and assert the integration fields round-trip.
    payload = smoke.to_dict()
    assert payload["source"] == "integration"
    assert payload["operator_command"] is None
    assert payload["evidence_expected"] is not None
    # the fleet/project cache rehydrates persisted entries via this shipped path
    rehydrated = oc._action_item_from_sidecar_dict(payload)
    assert rehydrated is not None
    assert rehydrated.source == oc.SOURCE_INTEGRATION
    assert rehydrated.exact_command == smoke.exact_command
    assert rehydrated.credential_env_vars == smoke.credential_env_vars
    assert rehydrated.evidence_expected == smoke.evidence_expected
    assert rehydrated.trigger_condition == smoke.trigger_condition
