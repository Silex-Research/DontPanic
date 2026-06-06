"""F004 — dontpanic operator brief: the agent-facing render of the F001 model.

Journeys A1/A2 (boot -> run-plan + escalation list), A3 (report back), A4 (narrate
uncertain, never fabricate). Verified on the real 313-item fleet fixture + a synthetic
uncertain item. Command-line surface only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import operator_brief as ob
from dontpanic_orchestrate import operator_triage as ot

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "docs/plans/2026-06-06-001-feat-operator-triage-surface-v0"
    / "evidence/fleet-fixture-real.json"
)


@pytest.fixture(scope="module")
def real_items() -> list[dict]:
    return json.loads(_FIXTURE.read_text())["items"]


@pytest.fixture(scope="module")
def model(real_items):
    return ot.build_triage(real_items, safety_class_for=lambda it: None, live_supervisors=[], dedupe=True)


# --- A1/A2: run-plan (allow) vs escalation (human) ------------------------

def test_allow_and_escalate_are_disjoint(model):
    brief = ob.build_brief(model)
    allow_ids = {i["id"] for i in brief["allow_list"]}
    esc_ids = {i["id"] for i in brief["escalate_list"]}
    assert allow_ids.isdisjoint(esc_ids)


def test_escalate_is_exactly_needs_auth_plus_needs_decision(model):
    brief = ob.build_brief(model)
    assert all(i["operator_bucket"] in ("needs_auth", "needs_decision") for i in brief["escalate_list"])
    counts = model["data_quality"]["counts"]
    assert len(brief["escalate_list"]) == counts.get("needs_auth", 0) + counts.get("needs_decision", 0)


def test_allow_is_only_agent_runnable_and_auto_safe(model):
    brief = ob.build_brief(model)
    assert all(i["operator_bucket"] in ("agent_runnable", "auto_safe") for i in brief["allow_list"])
    # the agent never sees a human-gated item in its run-plan (A2)
    assert not any(i["operator_bucket"] in ("needs_auth", "needs_decision") for i in brief["allow_list"])


# --- A3: report back -- items carry what's needed -------------------------

def test_items_carry_command_scope_and_run_state(model):
    brief = ob.build_brief(model)
    for i in brief["allow_list"] + brief["escalate_list"]:
        assert "operator_bucket" in i and "scope" in i and "run_state" in i
        assert "exact_command" in i and "dedupe_key" in i


# --- A4: uncertain surfaced, never fabricated -----------------------------

def test_uncertain_and_data_quality_are_first_class():
    items = [
        {"id": "ok", "band": "needs_action", "resolution_class": "command_resolvable"},
        {"id": "weird", "band": "needs_action", "resolution_class": None},  # -> uncertain
    ]
    model = ot.build_triage(items, safety_class_for=lambda it: None, live_supervisors=[])
    brief = ob.build_brief(model)
    assert [i["id"] for i in brief["uncertain"]] == ["weird"]
    assert brief["data_quality"]["uncertain"] == 1
    # the uncertain item is NOT smuggled into the agent run-plan
    assert "weird" not in {i["id"] for i in brief["allow_list"]}


def test_brief_carries_honesty_contract(model):
    brief = ob.build_brief(model)
    text = " ".join(brief["honesty_contract"]).lower()
    assert brief["honesty_contract"]
    assert "uncertain" in text and ("never run" in text or "human" in text)


# --- render + CLI ---------------------------------------------------------

def test_render_text_summarizes_needs_you(model):
    brief = ob.build_brief(model)
    out = ob.render_text(brief)
    assert isinstance(out, str) and "need" in out.lower()
    assert str(brief["summary"]["needs_you"]) in out


def test_cli_main_emits_valid_json_on_real_fixture(capsys):
    rc = ob.cli_main(["brief", "--json", "--fixture", str(_FIXTURE)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "operator-brief/v0"
    # default dedupe on: the raw fleet is 313, collapsing to fewer unique items
    assert payload["summary"]["input_count"] == 313
    assert payload["summary"]["total"] < 313
    assert set(payload) >= {"escalate_list", "allow_list", "uncertain", "data_quality", "honesty_contract"}


def test_cli_text_mode_runs(capsys):
    rc = ob.cli_main(["brief", "--text", "--fixture", str(_FIXTURE)])
    assert rc == 0
    assert "need" in capsys.readouterr().out.lower()
