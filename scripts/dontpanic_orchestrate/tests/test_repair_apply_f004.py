"""Plan 2026-06-04-006 F004 — tiered opt-in local apply.

`apply_repairs` executes the auto_safe batch for the operator's chosen tier:
--safe-derived-state runs ONLY apply_tier=derived_state actions; --safe --confirm
additionally runs the confirmed_local allowlist. NO tier ever runs a forbidden
kind (deploy/creds/paid/role/plan-state/registry/destructive/baseline) — an
auto_safe assertion over a forbidden kind is REFUSED at execution. Every executed
action is round-trip verified (F005); an effect that raises is skipped + logged,
never aborting the run. The side effect + recompute are injected so the runner is
pure and the test deterministic.
"""

from __future__ import annotations

import copy

from dontpanic_orchestrate import action_resolvability as ar
from dontpanic_orchestrate import repair_apply as rap
from dontpanic_orchestrate import repair_planner as rp
from dontpanic_orchestrate import repair_safety as rs
from dontpanic_orchestrate import repair_verify as rv


def _action(aid, *, kind="recompute_what_now", safety_class=rs.AUTO_SAFE,
            apply_tier=rs.TIER_DERIVED_STATE, resolution_class=ar.RESOLUTION_COMMAND_RESOLVABLE,
            depends_on=()):
    return rp.RepairAction(
        id=aid, kind=kind, safety_class=safety_class, apply_tier=apply_tier,
        resolution_class=resolution_class,
        clears_when=ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": aid, "gate": "g"}),
        depends_on=tuple(depends_on),
    )


def _state(plan_ids):
    return {"plan_status": {p: "active" for p in plan_ids}, "cleared_gates": {}}


class _World:
    """Mutable side-effect sink: an effect 'completes' the plan (resolving the
    card's predicate); recompute returns the current state."""

    def __init__(self, plan_ids, *, resolves=True, raises_for=()):
        self.state = _state(plan_ids)
        self.effects: list[str] = []
        self._resolves = resolves
        self._raises_for = set(raises_for)

    def effect(self, action):
        if action.id in self._raises_for:
            raise RuntimeError(f"effect blew up for {action.id}")
        self.effects.append(action.id)
        if self._resolves:
            self.state = copy.deepcopy(self.state)
            self.state["plan_status"][action.clears_when.params["plan_id"]] = "completed"

    def recompute(self):
        return self.state


def _run(actions, world, run_tier):
    return rap.apply_repairs(
        actions, world.state, run_tier=run_tier,
        effect_fn=world.effect, recompute_fn=world.recompute,
    )


# ── per-tier execution ──────────────────────────────────────────────────────────
def test_derived_state_tier_runs_only_derived_state_actions():
    derived = _action("D")
    confirmed = _action("C", kind=next(iter(rs.CONFIRMED_LOCAL_KINDS)), apply_tier=rs.TIER_CONFIRMED_LOCAL)
    world = _World(["D", "C"])
    report = _run([derived, confirmed], world, rs.RUN_TIER_DERIVED)
    assert world.effects == ["D"]  # confirmed_local not executed under derived tier
    assert {s.action_id for s in report.applied} == {"D"}
    assert {(d.action_id, d.reason) for d in report.deferred} == {("C", rp.DEFER_SAFETY)}


def test_confirm_tier_runs_derived_and_confirmed_local():
    derived = _action("D")
    confirmed = _action("C", kind=next(iter(rs.CONFIRMED_LOCAL_KINDS)), apply_tier=rs.TIER_CONFIRMED_LOCAL)
    world = _World(["D", "C"])
    report = _run([derived, confirmed], world, rs.RUN_TIER_CONFIRM)
    assert set(world.effects) == {"D", "C"}
    assert {s.action_id for s in report.applied} == {"D", "C"}
    assert report.deferred == ()


# ── forbidden-kind refusal at execution (regardless of flag) ────────────────────
def test_forbidden_kind_asserted_auto_safe_is_refused_and_never_executed():
    for kind in ["deploy", "credential_setup", "paid_dispatch", "role_change",
                 "plan_state_mutation", "registry_change", "destructive_cleanup", "baseline_write"]:
        bad = _action("B", kind=kind, safety_class=rs.AUTO_SAFE, apply_tier=rs.TIER_DERIVED_STATE)
        world = _World(["B"])
        report = _run([bad], world, rs.RUN_TIER_CONFIRM)  # strongest tier still refuses
        assert world.effects == [], kind
        assert {(r.action_id, r.reason) for r in report.refused} == {("B", rap.REFUSED_FORBIDDEN_KIND)}, kind
        assert report.applied == ()


# ── unclassified never executes ─────────────────────────────────────────────────
def test_unclassified_action_is_never_executed():
    unclassified = _action("U", safety_class=None, apply_tier=None)
    world = _World(["U"])
    report = _run([unclassified], world, rs.RUN_TIER_CONFIRM)
    assert world.effects == []
    assert report.applied == ()
    assert {(d.action_id, d.reason) for d in report.deferred} == {("U", rp.DEFER_SAFETY)}


# ── round-trip verification (F005) on every executed action ─────────────────────
def test_executed_action_is_round_trip_verified_cleared():
    world = _World(["D"], resolves=True)
    report = _run([_action("D")], world, rs.RUN_TIER_DERIVED)
    assert [(s.action_id, s.outcome) for s in report.applied] == [("D", rv.CLEARED)]


def test_executed_action_that_does_not_move_predicate_is_unchanged_defective():
    world = _World(["D"], resolves=False)  # effect runs but predicate never clears
    report = _run([_action("D")], world, rs.RUN_TIER_DERIVED)
    assert [(s.action_id, s.outcome) for s in report.applied] == [("D", rv.UNCHANGED)]
    assert report.iterations <= 2  # applied once, never retried -> terminates


# ── execution failure is skipped + logged, run continues ────────────────────────
def test_effect_failure_is_refused_and_does_not_abort_the_run():
    a = _action("A")
    b = _action("B")
    world = _World(["A", "B"], raises_for={"A"})
    report = _run([a, b], world, rs.RUN_TIER_DERIVED)
    assert {(r.action_id, r.reason) for r in report.refused} == {("A", rap.REFUSED_EXECUTION_FAILED)}
    assert {s.action_id for s in report.applied} == {"B"}  # B still ran


def test_refused_execution_failure_carries_detail():
    world = _World(["A"], raises_for={"A"})
    report = _run([_action("A")], world, rs.RUN_TIER_DERIVED)
    [refusal] = report.refused
    assert refusal.detail and "blew up" in refusal.detail


# ── CLI `dontpanic repair apply` — tier flags + no-mutation on current data ──────
import json  # noqa: E402


def _snapshot_tree(root):
    # The invocation ledger (2026-06-14-001 F003) is by-design observability
    # written on EVERY dontpanic invocation; it is orthogonal to repair-target
    # mutation, so exclude it from the "repair mutates nothing" snapshot.
    return {
        str(p.relative_to(root)): p.stat().st_mtime_ns
        for p in root.rglob("*")
        if p.is_file() and "invocations.jsonl" not in str(p)
    }


def test_apply_cli_derived_tier_runs_and_reports(tmp_path, capsys):
    from dontpanic_orchestrate import cli

    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    before = _snapshot_tree(tmp_path)

    rc = cli.main(
        ["repair", "apply", "--safe-derived-state",
         "--plans-root", str(plans_root), "--repo-root", str(repo_root), "--format", "json"]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["run_tier"] == "safe-derived-state"
    for key in ("applied", "refused", "deferred"):
        assert isinstance(out[key], list)
    # no producer asserts derived_state safety yet -> nothing eligible -> no effect
    # fires -> the temp tree is untouched (the apply effect would call build()).
    assert _snapshot_tree(tmp_path) == before


def test_apply_cli_safe_requires_confirm(tmp_path, capsys):
    from dontpanic_orchestrate import cli

    rc = cli.main(["repair", "apply", "--safe", "--plans-root", str(tmp_path), "--repo-root", str(tmp_path)])
    assert rc == 2
    assert "--confirm" in capsys.readouterr().err


def test_apply_cli_requires_a_tier_flag(tmp_path, capsys):
    from dontpanic_orchestrate import cli

    rc = cli.main(["repair", "apply", "--plans-root", str(tmp_path), "--repo-root", str(tmp_path)])
    assert rc == 2
    assert "--safe-derived-state" in capsys.readouterr().err


def test_apply_cli_text_format(tmp_path, capsys):
    from dontpanic_orchestrate import cli

    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    rc = cli.main(
        ["repair", "apply", "--safe", "--confirm",
         "--plans-root", str(plans_root), "--repo-root", str(tmp_path), "--format", "text"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "repair apply (safe-confirm)" in out
