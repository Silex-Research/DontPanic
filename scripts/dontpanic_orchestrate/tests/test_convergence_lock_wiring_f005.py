"""Plan 2026-06-09-002 F005 — lock-path wiring.

Pins: refusals name the convergence policy branch; the no-auditor
disposition-resolution path locks with ZERO auditor invocations; the legacy
--ignore-sufficiency-findings override takes precedence and its use is
logged in the rounds ledger; an undisposed blocking finding still refuses.

The auditor-never-invoked guarantee is enforced by monkeypatching every
dispatch surface to raise — any paid call would fail the test loudly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import sufficiency_auditor as _sa  # noqa: E402
from dontpanic_orchestrate.sufficiency_convergence import (  # noqa: E402
    append_audit_round,
    read_ledger,
    record_disposition,
)
from dontpanic_orchestrate.sufficiency_gate import (  # noqa: E402
    SufficiencyGateError,
    enforce_sufficiency_gate,
    lock_plan,
)


def _contract() -> dict:
    return {
        "goal_type": "new_feature",
        "source_of_truth": "fixture",
        "user_journeys": [
            {"name": "honest-coverage", "description": "x" * 60},
        ],
        "completion_test": "fixture completion test that is long enough to validate.",
    }


def _finding(severity: str = "medium", cls: str = "matrix_pin") -> dict:
    return {
        "severity": severity,
        "journey_id": "honest-coverage",
        "gap_class": "coverage_gap",
        "description": "a substantive fixture finding description exceeding forty characters.",
        "feature_refs": ["F001"],
        "recommendation": None,
        "finding_class": cls,
    }


def _write_plan(plan_dir: Path, findings: list[dict]) -> Path:
    plan_dir.mkdir(parents=True)
    fm = {
        "id": "2026-06-09-998-feat-fixture",
        "title": "fixture",
        "type": "feat",
        "tier": "local",
        "status": "draft",
        "date": "2026-06-09",
        "description": "wiring fixture",
        "goal_type": "new_feature",
        "links": {"objective_contract": "./objective_contract.json"},
    }
    (plan_dir / "plan.md").write_text("---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n")
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "features": [
                    {
                        "id": "F001",
                        "category": "tooling",
                        "phase": 1,
                        "description": "fixture",
                        "steps": ["a"],
                        "acceptance": "fixture acceptance.",
                        "passes": False,
                        "depends_on": [],
                        "evidence_refs": [],
                    }
                ]
            }
        )
    )
    (plan_dir / "objective_contract.json").write_text(json.dumps(_contract()))
    (plan_dir / "decisions.jsonl").write_text("")
    evidence = plan_dir / "evidence" / "goal-governance" / "pre_impl"
    evidence.mkdir(parents=True)
    (evidence / "sufficiency-findings.json").write_text(
        json.dumps(
            {
                "schema_version": _sa.FINDINGS_SCHEMA_VERSION,
                "auditor": "codex",
                "implementer": None,
                "input_fingerprint": _sa.compute_input_fingerprint(plan_dir),
                "generated_at": "2026-06-09T00:00:00Z",
                "findings": findings,
            }
        )
    )
    return plan_dir


@pytest.fixture(autouse=True)
def _no_paid_calls(monkeypatch):
    """ANY auditor invocation fails the test — the F005 zero-paid guarantee."""

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("auditor was invoked — the no-paid guarantee is broken")

    monkeypatch.setattr(_sa, "run_sufficiency_audit", _boom)
    monkeypatch.setattr(_sa, "generate_sufficiency_findings", _boom, raising=False)
    monkeypatch.setattr(_sa, "_production_sufficiency_dispatch", _boom, raising=False)


def _seed_two_rounds(plan_dir: Path, findings: list[dict]) -> dict:
    """Give the plan ledger history so the convergence policy is live:
    round 1 (anything) -> round 2 = the current findings, fully clearing
    round 1."""
    append_audit_round(
        plan_dir,
        [_finding("medium", "plan_contract") | {"journey_id": "weak-graph-any-repo"}],
        input_fingerprint="sha256:r1",
    )
    return append_audit_round(plan_dir, findings, input_fingerprint="sha256:r2")


def test_refusal_names_policy_branch(tmp_path: Path):
    findings = [_finding("medium", "matrix_pin")]
    plan_dir = _write_plan(tmp_path / "plan", findings)
    _seed_two_rounds(plan_dir, findings)
    with pytest.raises(SufficiencyGateError) as exc:
        enforce_sufficiency_gate(plan_dir)
    msg = str(exc.value)
    assert "convergence policy branch: a_full_clearance_pins" in msg
    assert "plan disposition" in msg, "disposition guidance shown instead of re-lock guidance"


def test_high_branch_named_in_refusal(tmp_path: Path):
    findings = [_finding("high", "matrix_pin")]
    plan_dir = _write_plan(tmp_path / "plan", findings)
    _seed_two_rounds(plan_dir, findings)
    with pytest.raises(SufficiencyGateError, match="b_high_severity"):
        enforce_sufficiency_gate(plan_dir)


def test_no_auditor_disposition_resolution_locks(tmp_path: Path):
    findings = [_finding("medium", "matrix_pin")]
    plan_dir = _write_plan(tmp_path / "plan", findings)
    record = _seed_two_rounds(plan_dir, findings)
    fid = record["findings"][0]["finding_id"]
    record_disposition(plan_dir, finding_id=fid, kind="deferred_to_impl")
    # Lock proceeds: zero auditor invocations (autouse fixture would explode),
    # no new audit round appended, status flips to active.
    rounds_before = len(read_ledger(plan_dir))
    lock_plan(plan_dir)
    assert "status: active" in (plan_dir / "plan.md").read_text()
    assert len(read_ledger(plan_dir)) == rounds_before, "no audit round appended"


def test_undisposed_blocking_finding_still_refuses_lock(tmp_path: Path):
    findings = [_finding("medium", "matrix_pin"), _finding("medium", "editorial")]
    plan_dir = _write_plan(tmp_path / "plan", findings)
    record = _seed_two_rounds(plan_dir, findings)
    fid = record["findings"][0]["finding_id"]
    record_disposition(plan_dir, finding_id=fid, kind="deferred_to_impl")
    with pytest.raises(SufficiencyGateError):
        lock_plan(plan_dir)


def test_legacy_override_precedence_and_ledger_log(tmp_path: Path):
    findings = [_finding("high", "plan_contract")]
    plan_dir = _write_plan(tmp_path / "plan", findings)
    _seed_two_rounds(plan_dir, findings)
    # The blunt whole-plan override bypasses dispositions entirely — even a
    # high plan_contract finding — exactly as before this plan.
    lock_plan(plan_dir, override_reason="operator-recorded override for fixture")
    assert "status: active" in (plan_dir / "plan.md").read_text()
    override_path = plan_dir / "evidence" / "goal-governance" / "pre_impl" / "override.json"
    assert override_path.is_file(), "override.json recorded exactly as before"
    events = [r for r in read_ledger(plan_dir) if r.get("type") == "override_used"]
    assert len(events) == 1, "override use is logged in the rounds ledger"
    assert events[0]["reason"] == "operator-recorded override for fixture"


def test_plain_gate_when_no_ledger_history(tmp_path: Path):
    """Backward compatibility: a plan with findings but no rounds ledger
    behaves exactly like the pre-convergence gate (plain refusal, override
    guidance)."""
    findings = [_finding("medium", "matrix_pin")]
    plan_dir = _write_plan(tmp_path / "plan", findings)
    with pytest.raises(SufficiencyGateError) as exc:
        enforce_sufficiency_gate(plan_dir)
    assert "ignore-sufficiency-findings" in str(exc.value)
