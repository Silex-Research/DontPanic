"""Plan 2026-06-04-001 F004 — reconcile/global readiness round-trip.

Proves the SECOND resolvability proof case:

* The install-snapshot/capabilities readiness items carry the composite
  ``install_snapshot_fresh`` predicate (snapshot present AND status cache
  fresh) and round-trip: missing_snapshot (chained) -> run baseline -> the
  stale-cache step surfaces -> run capabilities status -> rebuild clears it.
* Credential/setup steps are ``operator_attested``: a read-only command does
  NOT clear them; they clear only when a re-probe reports the capability ready
  (clear on evidence), never silently.
"""

from __future__ import annotations

import dataclasses

from dontpanic_orchestrate import action_resolvability as ar
from dontpanic_orchestrate import dashboard, operator_console
from dontpanic_orchestrate.operator_console import SOURCE_CAPABILITY, SOURCE_RECONCILE


# ── shims mirroring the shapes the providers read ─────────────────────────────
@dataclasses.dataclass
class _Check:
    status: str
    drift_kinds: tuple[str, ...] = ()


@dataclasses.dataclass
class _Cap:
    capability_id: str
    status: str
    missing: tuple[str, ...] = ()


@dataclasses.dataclass
class _Envelope:
    capabilities: list


def _recon(kind: str) -> tuple:
    return operator_console.provide_reconcile_actions(
        _Check(status=kind, drift_kinds=(kind,))
    )


# ── reconcile readiness items carry the composite predicate + classes ─────────
def test_missing_snapshot_is_chained_with_readiness_predicate():
    (item,) = _recon("missing_snapshot")
    assert item.resolution_class == ar.RESOLUTION_CHAINED
    assert item.clears_when is not None
    assert item.clears_when.predicate == "install_snapshot_fresh"
    assert item.exact_command == "dontpanic reconcile baseline --yes"


def test_stale_status_cache_is_command_resolvable_with_readiness_predicate():
    (item,) = _recon("stale_status_cache")
    assert item.resolution_class == ar.RESOLUTION_COMMAND_RESOLVABLE
    assert item.clears_when.predicate == "install_snapshot_fresh"
    assert item.exact_command == "dontpanic capabilities status"


def test_drift_items_are_command_resolvable_via_reconcile_clean():
    for kind in ("new_capabilities", "removed_capabilities", "changed_capabilities"):
        (item,) = _recon(kind)
        assert item.resolution_class == ar.RESOLUTION_COMMAND_RESOLVABLE
        assert item.clears_when.predicate == "reconcile_clean"
        assert item.exact_command == "dontpanic reconcile baseline --yes"


def test_drift_card_clears_only_when_next_check_is_clean():
    item = _recon("new_capabilities")
    # Same pass: live_state still carries the drift -> kept.
    kept_a, _ = ar.suppress_resolved(item, {"reconcile": {"drift_kinds": ["new_capabilities"]}})
    assert [it.id for it in kept_a] == [f"{SOURCE_RECONCILE}:new_capabilities"]
    # Rebuild after baseline: fresh check clean -> suppressed.
    kept_b, audit_b = ar.suppress_resolved(item, {"reconcile": {"drift_kinds": []}})
    assert kept_b == ()
    assert audit_b[0]["predicate"] == "reconcile_clean"


# ── the global readiness ROUND-TRIP ───────────────────────────────────────────
def test_readiness_round_trip_baseline_then_capabilities_status():
    # Stage 0: no snapshot -> missing_snapshot card, NOT suppressed (snapshot
    # absent -> install_snapshot_fresh False).
    missing = _recon("missing_snapshot")
    st0 = {"reconcile": {"snapshot_present": False, "cache_fresh": False}}
    kept0, _ = ar.suppress_resolved(missing, st0)
    assert [it.id for it in kept0] == [f"{SOURCE_RECONCILE}:missing_snapshot"]

    # Stage 1: operator ran baseline -> snapshot present but cache still stale.
    # The chained next step is the stale-cache card, which is still actionable.
    stale = _recon("stale_status_cache")
    st1 = {"reconcile": {"snapshot_present": True, "cache_fresh": False}}
    kept1, _ = ar.suppress_resolved(stale, st1)
    assert [it.id for it in kept1] == [f"{SOURCE_RECONCILE}:stale_status_cache"]

    # Stage 2: operator ran `capabilities status` -> snapshot present + cache
    # fresh -> install_snapshot_fresh True -> the readiness card clears.
    st2 = {"reconcile": {"snapshot_present": True, "cache_fresh": True}}
    kept2, audit2 = ar.suppress_resolved(stale, st2)
    assert kept2 == ()
    assert audit2[0]["predicate"] == "install_snapshot_fresh"


# ── operator-attested capabilities: clear on EVIDENCE, never on the command ───
def _cap_items(status: str) -> tuple:
    env = _Envelope(capabilities=[_Cap(capability_id="firebase", status=status)])
    return operator_console.provide_capability_actions(env)


def test_needs_setup_is_operator_attested_not_command_resolvable():
    (item,) = _cap_items("needs_setup")
    assert item.resolution_class == ar.RESOLUTION_OPERATOR_ATTESTED
    assert item.resolution_class in ar.NON_COMMAND_RESOLUTION_CLASSES
    assert item.clears_when.predicate == "capability_ready"
    # The command is the read-only diagnostic — it does NOT resolve the item.
    assert item.exact_command == "dontpanic capabilities status firebase"


def test_blocked_is_operator_attested():
    (item,) = _cap_items("blocked")
    assert item.resolution_class == ar.RESOLUTION_OPERATOR_ATTESTED
    assert item.clears_when.predicate == "capability_ready"


def test_capability_clears_only_when_reprobe_reports_ready():
    items = _cap_items("needs_setup")
    # Still needs_setup (no evidence) -> kept.
    kept_a, _ = ar.suppress_resolved(items, {"capabilities": {"firebase": "needs_setup"}})
    assert [it.id for it in kept_a] == [f"{SOURCE_CAPABILITY}:firebase"]
    # Re-probe reports ready (operator supplied the credential) -> suppressed.
    kept_b, audit_b = ar.suppress_resolved(items, {"capabilities": {"firebase": "ready"}})
    assert kept_b == ()
    assert audit_b[0]["predicate"] == "capability_ready"


# ── the dashboard live-state derivation feeds those predicates ────────────────
def test_dashboard_reconcile_live_state_derivation():
    assert dashboard._reconcile_live_state(None) == {}
    assert dashboard._reconcile_live_state(_Check(status="clean")) == {
        "snapshot_present": True,
        "cache_fresh": True,
        "drift_kinds": [],
    }
    assert dashboard._reconcile_live_state(
        _Check(status="missing_snapshot", drift_kinds=("missing_snapshot",))
    ) == {"snapshot_present": False, "cache_fresh": True, "drift_kinds": []}
    assert dashboard._reconcile_live_state(
        _Check(status="stale_status_cache", drift_kinds=("stale_status_cache",))
    ) == {"snapshot_present": True, "cache_fresh": False, "drift_kinds": []}
    assert dashboard._reconcile_live_state(
        _Check(status="new_capabilities", drift_kinds=("new_capabilities",))
    ) == {
        "snapshot_present": True,
        "cache_fresh": True,
        "drift_kinds": ["new_capabilities"],
    }


def test_dashboard_capabilities_live_state_derivation():
    assert dashboard._capabilities_live_state(None) == {}
    env = _Envelope(
        capabilities=[
            _Cap(capability_id="firebase", status="needs_setup"),
            _Cap(capability_id="git", status="ready"),
        ]
    )
    assert dashboard._capabilities_live_state(env) == {
        "firebase": "needs_setup",
        "git": "ready",
    }
