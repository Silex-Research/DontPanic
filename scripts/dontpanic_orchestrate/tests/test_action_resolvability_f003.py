"""Plan 2026-06-04-001 F003 — phantom suppression proof.

Gate/approve ActionItems now carry ``clears_when = gate_no_longer_actionable``,
so F002's suppress-at-source drops them for plans whose status is terminal
(completed/abandoned) or whose gate is already cleared. This is the fix for the
live failure where 54/57 gate-approve cards pointed at closed plans.

Two layers of proof:
  1. CONTRACT — provide_gate_actions emits clears_when; suppress_resolved drops
     the cards for terminal plans (reproduces the 54/57 → 0 phantom shape).
  2. INTEGRATION — dashboard._gather_action_items over a real plans_root with a
     completed plan + an active plan: no gate card survives for the completed
     plan; the active plan's gate card remains.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from dontpanic_orchestrate import action_resolvability as ar
from dontpanic_orchestrate import dashboard, operator_console
from dontpanic_orchestrate.operator_console import SOURCE_GATE


# ── shared GateView shim (mirrors state_snapshot_model.GateEntry shape) ───────
@dataclasses.dataclass(frozen=True)
class _GateView:
    plan_id: str
    gate_name: str
    kind: object = None
    reason: str | None = None


# ── 1. CONTRACT: gate cards carry clears_when + suppress for terminal plans ───
def test_gate_card_carries_gate_no_longer_actionable_clears_when():
    items = operator_console.provide_gate_actions(
        [_GateView(plan_id="p", gate_name="pre_impl")]
    )
    assert len(items) == 1
    cw = items[0].clears_when
    assert cw is not None
    assert cw.predicate == "gate_no_longer_actionable"
    assert dict(cw.params) == {"plan_id": "p", "gate": "pre_impl"}


def test_phantom_54_of_57_collapse_to_zero():
    """Reproduce the live ledger shape: 57 gate cards, 54 on closed plans."""
    closed = [
        _GateView(plan_id=f"closed-{i}", gate_name="pre_merge") for i in range(54)
    ]
    live = [_GateView(plan_id=f"live-{i}", gate_name="pre_impl") for i in range(3)]
    items = operator_console.provide_gate_actions(closed + live)
    assert len(items) == 57  # before: every gate card emitted

    plan_status = {f"closed-{i}": "completed" for i in range(54)}
    plan_status.update({f"live-{i}": "active" for i in range(3)})
    live_state = {
        "plan_status": plan_status,
        "cleared_gates": {f"live-{i}": [] for i in range(3)},
    }
    kept, audit = ar.suppress_resolved(items, live_state)

    # After: only the 3 live-plan gate cards survive; 54 phantoms suppressed.
    assert len(kept) == 3
    assert {it.id for it in kept} == {f"{SOURCE_GATE}:live-{i}:pre_impl" for i in range(3)}
    assert len(audit) == 54
    assert all(a["predicate"] == "gate_no_longer_actionable" for a in audit)


def test_abandoned_plan_gate_also_suppressed():
    items = operator_console.provide_gate_actions(
        [_GateView(plan_id="dead", gate_name="pre_merge")]
    )
    kept, audit = ar.suppress_resolved(
        items, {"plan_status": {"dead": "abandoned"}}
    )
    assert kept == ()
    assert audit[0]["dedupe_key"] == f"{SOURCE_GATE}:dead:pre_merge"


def test_cleared_gate_on_live_plan_suppressed_but_uncleared_kept():
    items = operator_console.provide_gate_actions(
        [
            _GateView(plan_id="p", gate_name="pre_impl"),
            _GateView(plan_id="p", gate_name="pre_merge"),
        ]
    )
    live_state = {
        "plan_status": {"p": "active"},
        "cleared_gates": {"p": ["pre_impl"]},  # pre_impl already cleared
    }
    kept, _ = ar.suppress_resolved(items, live_state)
    kept_gates = {it.id for it in kept}
    assert kept_gates == {f"{SOURCE_GATE}:p:pre_merge"}  # only the uncleared one


# ── 2. INTEGRATION: dashboard._gather_action_items over a real plans_root ─────
def _write_plan(plans_root: Path, plan_id: str, *, status: str, gate: str) -> Path:
    plan_dir = plans_root / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F003 phantom synthetic
type: infra
tier: trivial
status: {status}
date: "2026-06-04"
description: Synthetic plan for F003 phantom-suppression integration test.
agents_required:
  - claude
human_gates:
  - {gate}
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# F003 phantom synthetic

## Target

```yaml
target_env: dev
target_project: none
```
""",
        encoding="utf-8",
    )
    (plan_dir / "features.json").write_text(
        '{"task_id": "%s", "schema_version": "1.0", "features": ['
        '{"id": "F001", "category": "test", "phase": 0,'
        ' "description": "synthetic feature for the F003 phantom test",'
        ' "steps": ["scripted"], "acceptance": "ok and verified",'
        ' "passes": false, "depends_on": []}]}\n'
        % plan_id,
        encoding="utf-8",
    )
    return plan_dir


def _gate_items(items) -> set[str]:
    return {it.id for it in items if it.source == SOURCE_GATE}


def test_gather_drops_completed_plan_gate_keeps_active(tmp_path: Path) -> None:
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    # A completed plan with an uncleared declared gate (the phantom shape) +
    # an active plan whose gate is genuinely pending.
    done_id = "2026-06-04-900-infra-done"
    live_id = "2026-06-04-901-infra-live"
    _write_plan(plans_root, done_id, status="completed", gate="pre_merge")
    _write_plan(plans_root, live_id, status="active", gate="pre_impl")

    items = dashboard._gather_action_items(
        plans_root=plans_root,
        capability_envelope=None,
        reconcile_result=None,
        arch_status=None,
        plan_id=None,
    )
    gates = _gate_items(items)
    # The completed plan's gate card must NOT survive recompute…
    assert f"{SOURCE_GATE}:{done_id}:pre_merge" not in gates
    # …while the active plan's gate card remains actionable.
    assert f"{SOURCE_GATE}:{live_id}:pre_impl" in gates
