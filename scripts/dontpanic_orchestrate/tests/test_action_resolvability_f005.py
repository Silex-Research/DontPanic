"""Plan 2026-06-04-001 F005 — generic round-trip invariant over ALL emitters.

The build-time guarantee: NO ActionItem emitter may produce a NEEDS_ACTION card
that is "non-resolving guidance" — a card the operator can act on but that never
clears. Every NEEDS_ACTION item MUST resolve via exactly one mechanism:

  * recompute      — carries a ``clears_when`` predicate (F001/F002): running the
                     action flips live state and suppress-at-source drops it
                     (gates, reconcile readiness + drift).
  * evidence       — ``resolution_class`` in {operator_attested, blocked_external}
                     (F004): clears when matching evidence appears, never on a
                     command (capability needs_setup / blocked).
  * reconstruction — the emitter projects the card FRESH from live state each
                     build, so a resolved decision is simply not re-emitted
                     (operations-guidance decision prompts). This is a legitimate
                     third mechanism that predates this plan (D006); it is allowed
                     ONLY for projected sources, never for a static emitter (the
                     old gate bug was a static emitter masquerading as resolvable).

An emitter that yields a NEEDS_ACTION + command_resolvable + clears_when=None card
from a non-projected source FAILS this test — that is exactly the dashboard's
"Needs Action that never clears" defect.
"""

from __future__ import annotations

import dataclasses

import pytest

from dontpanic_orchestrate import action_resolvability as ar
from dontpanic_orchestrate import operations_guidance, operator_console
from dontpanic_orchestrate.operator_console import (
    SOURCE_CAPABILITY,
    SOURCE_GATE,
    SOURCE_RECONCILE,
    SOURCE_SUPERVISOR,
    ActionItem,
    Band,
)

_TS = "2026-06-04T00:00:00Z"

# Sources whose NEEDS_ACTION cards are projected fresh from live state each build
# (reconstruction-resolvable). operations-guidance items carry source=supervisor
# (CP-D002) with an "operations:" id prefix.
_RECONSTRUCTION_PREFIXES = ("operations:",)


def _classify(item: ActionItem) -> str:
    # resolution_class is the semantic authority: operator_attested/blocked_external
    # clear on EVIDENCE even if they also carry a clears_when convenience predicate.
    if item.resolution_class in ar.NON_COMMAND_RESOLUTION_CLASSES:
        return "evidence"
    if item.clears_when is not None:
        return "recompute"
    if item.source == SOURCE_SUPERVISOR and item.id.startswith(_RECONSTRUCTION_PREFIXES):
        return "reconstruction"
    return "NON_RESOLVING"


def assert_needs_action_is_resolvable(item: ActionItem) -> str:
    """The build-time invariant for one NEEDS_ACTION item. Returns its mechanism."""
    mechanism = _classify(item)
    assert mechanism != "NON_RESOLVING", (
        f"non-resolving NEEDS_ACTION guidance: id={item.id!r} "
        f"source={item.source!r} resolution_class={item.resolution_class!r} "
        f"(command={item.exact_command!r}) — every actionable card must carry a "
        f"clears_when predicate, be operator_attested/blocked_external, or be a "
        f"reconstruction-projected source."
    )
    return mechanism


# ── shims to drive the emitters ───────────────────────────────────────────────
@dataclasses.dataclass
class _GateView:
    plan_id: str
    gate_name: str
    kind: object = None
    reason: str | None = None


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


def _all_emitter_items() -> dict[str, list[ActionItem]]:
    """Drive every NEEDS_ACTION-capable emitter and return {source_label: items}."""
    by_source: dict[str, list[ActionItem]] = {}

    by_source["gate"] = list(
        operator_console.provide_gate_actions([_GateView("p", "pre_impl")])
    )
    by_source["capability"] = list(
        operator_console.provide_capability_actions(
            _Envelope(
                capabilities=[
                    _Cap("firebase", "needs_setup"),
                    _Cap("docker", "blocked"),
                    _Cap("optional-thing", "not_installed"),
                ]
            )
        )
    )
    by_source["reconcile"] = list(
        operator_console.provide_reconcile_actions(
            _Check(
                status="new_capabilities",
                drift_kinds=(
                    "missing_snapshot",
                    "stale_status_cache",
                    "new_capabilities",
                    "removed_capabilities",
                    "changed_capabilities",
                ),
            )
        )
    )
    by_source["supervisor"] = list(operator_console.provide_supervisor_actions([]))
    by_source["architecture"] = list(
        operator_console.provide_architecture_actions(None)
    )

    # operations-guidance: a human-required decision prompt (no command) -> NEEDS_ACTION.
    choice = operations_guidance.ActionChoice(
        id="raise_ceiling",
        kind="raise_ceiling",
        title="Raise the budget ceiling",
        rationale="A human must decide the new ceiling.",
        risk=operations_guidance.Risk.HIGH,
        requires_human=True,
    )
    guidance = operations_guidance.Guidance(
        plan_id="p", feature_id=None, headline="blocked", choices=(choice,)
    )
    by_source["operations"] = list(guidance.to_action_items(updated_at=_TS))

    return by_source


# ── the invariant ─────────────────────────────────────────────────────────────
def test_every_emitter_needs_action_item_is_resolvable():
    by_source = _all_emitter_items()
    seen_mechanisms: dict[str, set[str]] = {}
    needs_action_total = 0
    for source, items in by_source.items():
        for item in items:
            if item.band != Band.NEEDS_ACTION:
                continue
            needs_action_total += 1
            mech = assert_needs_action_is_resolvable(item)
            seen_mechanisms.setdefault(source, set()).add(mech)

    # We actually exercised the emitters that can produce NEEDS_ACTION cards.
    assert needs_action_total >= 4
    assert seen_mechanisms["gate"] == {"recompute"}
    assert seen_mechanisms["capability"] == {"evidence"}
    assert seen_mechanisms["reconcile"] == {"recompute"}
    assert seen_mechanisms["operations"] == {"reconstruction"}


# ── the invariant actually CATCHES non-resolving guidance ─────────────────────
def test_invariant_rejects_a_non_resolving_card():
    bad = ActionItem(
        id="reconcile:phantom",
        source=SOURCE_RECONCILE,  # not a reconstruction-projected source
        band=Band.NEEDS_ACTION,
        title="do a thing",
        detail=None,
        exact_command=None,
        automatable=False,
        human_required_reason="x",
        evidence_uri=None,
        updated_at=_TS,
        dedupe_key="reconcile:phantom",
        clears_when=None,  # command_resolvable default + no predicate => non-resolving
    )
    assert _classify(bad) == "NON_RESOLVING"
    with pytest.raises(AssertionError):
        assert_needs_action_is_resolvable(bad)


# ── behavioral: each mechanism actually clears ────────────────────────────────
def test_recompute_mechanism_clears(  # gates + reconcile via suppress_resolved
):
    gate = operator_console.provide_gate_actions([_GateView("p", "pre_impl")])
    kept, _ = ar.suppress_resolved(gate, {"plan_status": {"p": "completed"}})
    assert kept == ()  # plan terminal -> gate recompute-suppressed


def test_evidence_mechanism_clears():  # capability operator_attested
    caps = operator_console.provide_capability_actions(
        _Envelope(capabilities=[_Cap("firebase", "needs_setup")])
    )
    kept, _ = ar.suppress_resolved(caps, {"capabilities": {"firebase": "ready"}})
    assert kept == ()  # re-probe ready -> evidence cleared


def test_reconstruction_mechanism_clears():  # operations-guidance re-projection
    # The decision is resolved -> the live guidance no longer offers that choice,
    # so re-projecting omits the item (no clears_when needed).
    resolved = operations_guidance.Guidance(
        plan_id="p", feature_id=None, headline="unblocked", choices=()
    )
    assert resolved.to_action_items(updated_at=_TS) == []
