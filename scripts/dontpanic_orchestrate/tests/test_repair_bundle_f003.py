"""Plan 2026-06-04-006 F003 — emit-only agent-handoff bundle.

`build_bundle` turns the F002-ordered, safety-classified repair actions into a
machine-readable JSON bundle an external agentic operator (Codex/Claude/Grok)
runs. Each action carries command, safety_class, apply_tier, clears_when,
plain_consequence, and scope. It is PURE — emitting the bundle mutates nothing.
`action_to_repair_action` adapts a live ActionItem into a RepairAction, reading
PRODUCER-ASSERTED safety (never inferring it); an item whose producer declared no
safety fails closed to human_required at emit time.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from dontpanic_orchestrate import action_resolvability as ar
from dontpanic_orchestrate import repair_bundle as rb
from dontpanic_orchestrate import repair_planner as rp
from dontpanic_orchestrate import repair_safety as rs


def _ra(aid, *, kind="recompute_what_now", safety_class=rs.AUTO_SAFE,
        apply_tier=rs.TIER_DERIVED_STATE, depends_on=(), command="dontpanic state build",
        plain_consequence="Rebuilds the dashboard projection.", scope="project:glam"):
    return rp.RepairAction(
        id=aid, kind=kind, safety_class=safety_class, apply_tier=apply_tier,
        resolution_class=ar.RESOLUTION_COMMAND_RESOLVABLE,
        clears_when=ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": aid, "gate": "g"}),
        depends_on=tuple(depends_on), command=command,
        plain_consequence=plain_consequence, scope=scope,
    )


# ── bundle shape (snapshot) ─────────────────────────────────────────────────────
def test_bundle_emits_the_six_required_fields_per_action():
    bundle = rb.build_bundle([_ra("A")], scope="project:glam")
    assert bundle["scope"] == "project:glam"
    [action] = bundle["actions"]
    assert action == {
        "id": "A",
        "command": "dontpanic state build",
        "safety_class": "auto_safe",
        "apply_tier": "derived_state",
        "resolution_class": "command_resolvable",
        "clears_when": {"predicate": "gate_no_longer_actionable", "params": {"plan_id": "A", "gate": "g"}},
        "plain_consequence": "Rebuilds the dashboard projection.",
        "scope": "project:glam",
        "depends_on": [],
    }


# ── ordering preserved ──────────────────────────────────────────────────────────
def test_bundle_actions_are_dependency_ordered():
    a = _ra("A")
    b = _ra("B", depends_on=["A"])
    bundle = rb.build_bundle([b, a], scope="fleet")
    assert [x["id"] for x in bundle["actions"]] == ["A", "B"]


def test_cyclic_actions_listed_as_deferred_not_in_actions():
    a = _ra("A", depends_on=["B"])
    b = _ra("B", depends_on=["A"])
    bundle = rb.build_bundle([a, b], scope="fleet")
    assert bundle["actions"] == []
    assert {(d["id"], d["reason"]) for d in bundle["deferred"]} == {("A", "cycle"), ("B", "cycle")}


# ── fail-closed: producer-asserted, never inferred ──────────────────────────────
def test_unclassified_action_emits_human_required():
    # producer declared no safety -> resolve_safety fails closed -> human_required
    a = _ra("A", safety_class=None, apply_tier=None)
    [action] = rb.build_bundle([a], scope="fleet")["actions"]
    assert action["safety_class"] == "human_required"
    assert action["apply_tier"] is None


def test_forbidden_kind_emits_human_required_even_if_asserted_auto_safe():
    a = _ra("A", kind="deploy", safety_class=rs.AUTO_SAFE, apply_tier=rs.TIER_DERIVED_STATE)
    [action] = rb.build_bundle([a], scope="fleet")["actions"]
    assert action["safety_class"] == "human_required"
    assert action["apply_tier"] is None


# ── adapter from a live ActionItem (producer-asserted via attrs) ─────────────────
def test_action_to_repair_action_reads_producer_asserted_safety():
    card = SimpleNamespace(
        id="gate:glam:F001",
        repair_kind="recompute_what_now",
        safety_class=rs.AUTO_SAFE,
        apply_tier=rs.TIER_DERIVED_STATE,
        resolution_class=ar.RESOLUTION_COMMAND_RESOLVABLE,
        clears_when=ar.ClearsWhen("gate_no_longer_actionable", {"plan_id": "glam", "gate": "g"}),
        depends_on=("gate:glam:F000",),
        exact_command="dontpanic state build",
        plain_consequence="Rebuilds projection.",
        scope="project:glam",
    )
    ra = rb.action_to_repair_action(card)
    assert (ra.id, ra.kind, ra.safety_class, ra.apply_tier) == (
        "gate:glam:F001", "recompute_what_now", rs.AUTO_SAFE, rs.TIER_DERIVED_STATE
    )
    assert ra.command == "dontpanic state build"
    assert ra.depends_on == ("gate:glam:F000",)


def test_action_to_repair_action_fails_closed_when_producer_silent():
    # a legacy ActionItem with no safety fields -> None -> human_required downstream
    card = SimpleNamespace(
        id="gate:glam:F001",
        resolution_class=ar.RESOLUTION_COMMAND_RESOLVABLE,
        clears_when=None,
        exact_command=None,
        plain_consequence=None,
        scope="project:glam",
    )
    ra = rb.action_to_repair_action(card)
    assert ra.safety_class is None and ra.apply_tier is None and ra.depends_on == ()
    [action] = rb.build_bundle([ra], scope="project:glam")["actions"]
    assert action["safety_class"] == "human_required"


# ── emit-only: zero mutation ─────────────────────────────────────────────────────
def test_build_bundle_is_pure_no_input_mutation():
    actions = [_ra("A"), _ra("B", depends_on=["A"])]
    snapshot = [(x.id, x.depends_on, x.safety_class) for x in actions]
    rb.build_bundle(actions, scope="fleet")
    rb.build_bundle(actions, scope="fleet")  # idempotent
    assert [(x.id, x.depends_on, x.safety_class) for x in actions] == snapshot


def test_render_json_is_valid_json_and_round_trips():
    bundle = rb.build_bundle([_ra("A")], scope="fleet")
    text = rb.render_json(bundle)
    assert json.loads(text) == bundle


def test_render_human_summarizes_counts():
    bundle = rb.build_bundle([_ra("A"), _ra("B", safety_class=None, apply_tier=None)], scope="fleet")
    out = rb.render_human(bundle)
    assert "fleet" in out
    assert "auto_safe" in out and "human_required" in out


# ── CLI `dontpanic repair plan` is read-only and emits the bundle ──────────────
def _snapshot_tree(root):
    return {
        str(p.relative_to(root)): p.stat().st_mtime_ns
        for p in root.rglob("*")
        if p.is_file()
    }


def test_repair_plan_cli_emits_json_and_mutates_nothing(tmp_path, capsys):
    from dontpanic_orchestrate import cli

    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    before = _snapshot_tree(tmp_path)

    rc = cli.main(
        [
            "repair", "plan",
            "--scope", "fleet",
            "--plans-root", str(plans_root),
            "--repo-root", str(repo_root),
            "--format", "json",
        ]
    )
    out = capsys.readouterr().out
    bundle = json.loads(out)

    assert rc == 0
    assert bundle["scope"] == "fleet"
    assert isinstance(bundle["actions"], list)
    assert isinstance(bundle["deferred"], list)
    # emit-only: no file under the temp tree was created or modified.
    assert _snapshot_tree(tmp_path) == before


def test_repair_cli_without_subcommand_is_usage_error(tmp_path, capsys):
    from dontpanic_orchestrate import cli

    rc = cli.main(["repair"])
    assert rc == 2


def test_repair_plan_cli_text_format(tmp_path, capsys):
    from dontpanic_orchestrate import cli

    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    rc = cli.main(
        ["repair", "plan", "--plans-root", str(plans_root), "--repo-root", str(tmp_path), "--format", "text"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Repair plan for scope: fleet" in out
