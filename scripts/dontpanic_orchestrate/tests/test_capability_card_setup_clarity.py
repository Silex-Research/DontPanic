"""Plan 2026-06-05-001 — capability card setup clarity (F001/F002/F003).

F001: a capability card that needs setup surfaces the RESOLVING guidance command
`dontpanic capabilities setup <id> --print-steps` (not the read-only
`capabilities status` diagnostic), with an honest "prints the setup steps"
consequence; it stays non-automatable and clears only on a later ready re-probe.
F002: the card detail is plain-language step descriptions + human reasons (with a
fallback to the missing summary). F003: capability-sourced items carry a
`global_tool_setup` group label at the render boundary.
"""

from __future__ import annotations

from dontpanic_orchestrate import action_renderers as ar
from dontpanic_orchestrate import operator_console as oc


def _env(*caps):
    return {"capabilities": list(caps)}


def _cap(cap_id, status, *, missing=(), next_actions=()):
    return {
        "capability_id": cap_id,
        "status": status,
        "missing": list(missing),
        "next_actions": list(next_actions),
    }


# ── F001: resolving guidance command, honest consequence ────────────────────────
def test_setup_cards_emit_the_setup_print_steps_command():
    env = _env(
        _cap("agent-claude-cli", "needs_setup", missing=["env.TOKEN"]),
        _cap("gcloud", "blocked", missing=["gcloud"]),
        _cap("linear", "not_installed"),
    )
    by_id = {it.id: it for it in oc.provide_capability_actions(env)}
    for cap_id in ("agent-claude-cli", "gcloud", "linear"):
        it = by_id[f"capability:{cap_id}"]
        assert it.exact_command == f"dontpanic capabilities setup {cap_id} --print-steps"
        # honest, guidance-only consequence — never implies an auto-fix
        assert it.plain_consequence and "setup steps" in it.plain_consequence.lower()
        assert "fix" not in it.plain_consequence.lower()
        assert it.automatable is False


def test_setup_cards_stay_operator_attested_and_clear_on_ready():
    env = _env(_cap("agent-claude-cli", "needs_setup"))
    [it] = oc.provide_capability_actions(env)
    assert it.resolution_class == oc.RESOLUTION_OPERATOR_ATTESTED
    assert it.clears_when is not None and it.clears_when.predicate == "capability_ready"


# ── F002: plain-language detail from setup steps ────────────────────────────────
def test_detail_uses_plain_step_descriptions_and_human_reasons():
    env = _env(
        _cap(
            "agent-claude-cli",
            "needs_setup",
            missing=["env.TOKEN"],
            next_actions=[
                {"what": "Install the Claude CLI", "human_required_reason": None},
                {"what": "Authenticate the Claude CLI", "human_required_reason": "Operator pastes a secret token"},
            ],
        )
    )
    [it] = oc.provide_capability_actions(env)
    detail = it.detail or ""
    assert "Install the Claude CLI" in detail
    assert "Authenticate the Claude CLI" in detail
    assert "needs you" in detail.lower()  # human-required marker
    assert not detail.startswith("missing:")  # no raw token blob when steps exist


def test_detail_falls_back_to_missing_summary_when_no_steps():
    env = _env(_cap("gcloud", "blocked", missing=["gcloud", "env.PROJECT"]))
    [it] = oc.provide_capability_actions(env)
    detail = it.detail or ""
    assert "gcloud" in detail and "env.PROJECT" in detail


# ── F003: capability items carry the global_tool_setup group label ──────────────
def test_capability_items_carry_global_tool_group_label():
    env = _env(_cap("linear", "not_installed"))
    [cap_item] = oc.provide_capability_actions(env)
    assert ar.action_view(cap_item).get("group") == "global_tool_setup"


def test_non_capability_items_do_not_carry_the_global_tool_group():
    gate = oc.ActionItem(
        id="gate:plan-a:F001:pre_impl",
        source=oc.SOURCE_GATE,
        band=oc.Band.NEEDS_ACTION,
        title="Gate not cleared",
        detail=None,
        exact_command="dontpanic approve plan-a pre_impl",
        automatable=False,
        human_required_reason="operator approval",
        evidence_uri=None,
        updated_at="2026-06-05T00:00:00Z",
        dedupe_key="gate:plan-a:F001:pre_impl",
    )
    assert ar.action_view(gate).get("group") is None
