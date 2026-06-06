"""F005 — safe-tier apply engine (command-line). dontpanic triage apply --safe.

Applies ONLY the auto_safe bucket. Dry-run by default; --confirm runs via an
injected runner (tests never shell out); every run writes a reversible evidence
record; needs_auth / needs_decision / agent_runnable / mutations are refused.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import operator_triage as ot
from dontpanic_orchestrate import triage_apply as ta

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "docs/plans/2026-06-06-001-feat-operator-triage-surface-v0"
    / "evidence/fleet-fixture-real.json"
)


def _mixed_model():
    """A model with one auto_safe + one agent_runnable + one needs_decision item."""
    items = [
        {"id": "safe1", "band": "needs_action", "resolution_class": "command_resolvable",
         "automatable": True, "exact_command": "dontpanic architecture regen", "dedupe_key": "k-safe1"},
        {"id": "agentcmd", "band": "needs_action", "resolution_class": "command_resolvable",
         "automatable": False, "exact_command": "dontpanic reconcile baseline --yes", "dedupe_key": "k-agent"},
        {"id": "gate1", "band": "needs_action", "resolution_class": "command_resolvable",
         "title": "Approval needed on p1", "exact_command": "dontpanic approve p1 pre_merge", "dedupe_key": "k-gate"},
    ]
    # only the automatable item gets an asserted auto_safe safety_class
    return ot.build_triage(
        items,
        safety_class_for=lambda it: "auto_safe" if it.get("id") == "safe1" else None,
        live_supervisors=[],
    )


class _FakeRunner:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, command: str) -> dict:
        self.calls.append(command)
        return {"rc": 0, "stdout": f"ran: {command}", "stderr": ""}


def test_dry_run_is_default_and_mutates_nothing():
    runner = _FakeRunner()
    out = ta.apply_safe(_mixed_model(), confirm=False, runner=runner)
    assert out["mode"] == "dry_run"
    assert runner.calls == []  # nothing executed
    assert [i["id"] for i in out["plan"]["items"]] == ["safe1"]  # only auto_safe is planned
    assert out["applied"] == []


def test_confirm_runs_only_auto_safe_and_writes_evidence(tmp_path):
    runner = _FakeRunner()
    ev = tmp_path / "evidence.jsonl"
    out = ta.apply_safe(_mixed_model(), confirm=True, runner=runner, evidence_path=ev)
    assert out["mode"] == "applied"
    assert runner.calls == ["dontpanic architecture regen"]  # ONLY the auto_safe command
    assert len(out["applied"]) == 1
    rec = out["applied"][0]
    assert rec["item_id"] == "safe1" and rec["command"] == "dontpanic architecture regen"
    assert rec["rc"] == 0 and rec["why_safe"] and rec["reversible"] is True
    # evidence persisted
    written = [json.loads(line) for line in ev.read_text().splitlines() if line.strip()]
    assert written and written[-1]["item_id"] == "safe1"


def test_refused_count_is_honest():
    out = ta.apply_safe(_mixed_model(), confirm=False, runner=_FakeRunner())
    # agent_runnable + needs_decision are NOT auto_safe -> reported as not-applied-here
    assert out["refused"] == 2


def test_assert_safe_appliable_rejects_non_auto_safe():
    auth = {"id": "a", "operator_bucket": "needs_auth"}
    gate = {"id": "g", "operator_bucket": "needs_decision"}
    agent = {"id": "r", "operator_bucket": "agent_runnable"}
    for it in (auth, gate, agent):
        with pytest.raises(ta.NotSafeToApply):
            ta.assert_safe_appliable(it)
    ta.assert_safe_appliable({"id": "s", "operator_bucket": "auto_safe"})  # does not raise


def test_real_fleet_has_no_auto_safe_clean_noop():
    items = json.loads(_FIXTURE.read_text())["items"]
    model = ot.build_triage(items, safety_class_for=lambda it: None, live_supervisors=[], dedupe=True)
    out = ta.apply_safe(model, confirm=False, runner=_FakeRunner())
    assert out["plan"]["count"] == 0  # producers don't assert safety_class yet -> nothing auto_safe
    assert out["mode"] == "dry_run"
    assert out["refused"] > 0  # but it honestly reports the human/agent items it won't touch


def test_cli_dry_run_default(capsys):
    rc = ta.cli_main(["apply", "--safe", "--fixture", str(_FIXTURE)])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "dry" in out or "would" in out
    assert "--confirm" in out  # tells the operator how to actually run


def test_cli_rejects_apply_without_safe_flag(capsys):
    rc = ta.cli_main(["apply", "--fixture", str(_FIXTURE)])
    assert rc != 0  # --safe is required; no blanket apply
