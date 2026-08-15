"""F002 — outcome / slices / proofs score at lock and close.

Plan 2026-08-13-001. Covers the seven acceptance criteria F002 carries after
the D010 split (F004 owns slice identity, F005 owns sidecar durability):

  1. A fixture with no delivers[], no inherits, and no proof-carrying feature
     REFUSES lock with a message that names 'outcome' (status stays draft).
     — ``test_ac1_*``
  2. A fixture that inherits a parent and declares one delta slice LOCKS.
     — ``test_ac2_*``
  3. A fixture whose features each carry a proof and which declares no
     delivers[] LOCKS, scoring one slice per proof-carrying feature (D009).
     — ``test_ac3_*``
  4. A feature-as-slice with no user_impact LOCKS and records an accepted gap
     naming the absent audience — never a refusal (D009). — ``test_ac4_*``
  5. A fixture with an outcome and an accepted missing proof LOCKS and the
     gap is recorded in the pre_impl sidecar. — ``test_ac5_*``
  6. Existing plans without proof still lock — inferred or accepted-gap,
     never a surprise refuse (including plans below the schema_version 1.1
     threshold, which carry no contract at all). — ``test_ac6_*``
  7. This suite passes, evidenced with real command output (evidence/
     F002-outcome-score-suite.md).

Plus the pure-scorer contracts: outcome/slices/proofs classification,
overlap detection, method inference, inherits resolution, the evidence↔method
rule the close check runs on, and the close-time obligation behaviour F004 and
F005 inherit (kept here as regression cover, not as an F002 criterion).

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_outcome_score_f002.py -q
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import cli, completion_gate, outcome_score  # noqa: E402

_PLAN_MD = """---
id: {plan_id}
title: Synthetic outcome-score fixture
type: {plan_type}
tier: {tier}
status: {status}
date: "2026-08-13"
{schema_version_line}description: Synthetic plan exercising the F002 outcome/slices/proofs score.
links:
  features: ./features.json
  objective_contract: ./objective_contract.json
---

# Outcome-score synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""

_CLEAN_FEATURE = {
    "id": "F001",
    "category": "tooling",
    "phase": 0,
    "description": "A pure deterministic scoring core module.",
    "steps": ["Compute the score.", "Return the typed report."],
    "acceptance": "(1) The scorer returns a typed report for the input.",
    "passes": False,
    "depends_on": [],
}


def _slice(
    *,
    audience: str = "operator",
    kind: str = "reliability",
    capability: str = "NAV history survives a restart instead of evaporating.",
    feature_id: str = "F001",
    plan: str | None = None,
    proof: dict | None = None,
) -> dict:
    ref: dict = {"type": "feature", "id": feature_id}
    if plan is not None:
        ref["plan"] = plan
    item: dict = {
        "audience": audience,
        "kind": kind,
        "capability": capability,
        "proof_refs": [ref],
    }
    if proof is not None:
        item["proof"] = proof
    return item


_WALK_PROOF = {
    "metric": "restart the process and the prior NAV row is still listed",
    "method": "walk",
    "surface": "backend",
}


def _write_plan(
    repo: Path,
    plan_id: str,
    *,
    delivers: list[dict] | None = None,
    inherits: str | None = None,
    contract: bool = True,
    decisions: list[dict] | None = None,
    features: list[dict] | None = None,
    schema_version: str | None = "1.1",
    tier: str = "local",
    status: str = "draft",
    plan_type: str = "feat",
) -> Path:
    """Write a minimal plan dir under ``repo/docs/plans/<plan_id>``."""
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        _PLAN_MD.format(
            plan_id=plan_id,
            plan_type=plan_type,
            tier=tier,
            status=status,
            schema_version_line=(
                f'schema_version: "{schema_version}"\n' if schema_version else ""
            ),
        )
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "schema_version": "1.0",
                "features": features if features is not None else [_CLEAN_FEATURE],
            },
            indent=2,
        )
        + "\n"
    )
    if contract:
        payload: dict = {
            "goal_type": "infra",
            "source_of_truth": "Curated fixture reference for the F002 score tests",
            "completion_test": "The lock prints a three-line score for this fixture.",
        }
        if inherits is not None:
            payload["inherits"] = inherits
        if delivers is not None:
            payload["delivers"] = delivers
        (plan_dir / "objective_contract.json").write_text(
            json.dumps(payload, indent=2) + "\n"
        )
    if decisions is not None:
        (plan_dir / "decisions.jsonl").write_text(
            "".join(json.dumps(d) + "\n" for d in decisions)
        )
    return plan_dir


def _status_of(plan_dir: Path) -> str:
    text = (plan_dir / "plan.md").read_text(encoding="utf-8")
    m = re.search(r"^status:\s*(\S+)\s*$", text, re.MULTILINE)
    assert m, "no status line in plan.md"
    return m.group(1)


# ─────────────────────────────  pure scorer  ─────────────────────────────


def test_outcome_present_single_slice_with_proof(tmp_path: Path) -> None:
    """One slice with a declared proof scores present / single / one-per-slice."""
    print("\n[test] outcome_present_single_slice_with_proof ...")
    plan_dir = _write_plan(
        tmp_path, "2026-08-13-901-feat-score-present", delivers=[_slice(proof=_WALK_PROOF)]
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.outcome == outcome_score.OUTCOME_PRESENT
    assert score.slices == outcome_score.SLICES_SINGLE
    assert score.proofs == outcome_score.PROOFS_ONE_PER_SLICE
    assert not score.refuse
    print(f"  ✓ {score.outcome}/{score.slices}/{score.proofs}")


def test_three_clean_slices_score_mece(tmp_path: Path) -> None:
    """Distinct audiences + distinct proof_refs → mece, no overlap recorded."""
    print("\n[test] three_clean_slices_score_mece ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-902-feat-score-mece",
        delivers=[
            _slice(audience="operator", feature_id="F001", proof=_WALK_PROOF),
            _slice(
                audience="end_user",
                capability="The reader sees why the lock refused.",
                feature_id="F002",
                proof=_WALK_PROOF,
            ),
            _slice(
                audience="agent",
                capability="The agent reads the recorded gap instead of guessing.",
                feature_id="F003",
                proof=_WALK_PROOF,
            ),
        ],
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.slices == outcome_score.SLICES_MECE
    assert score.overlaps == ()
    print("  ✓ mece, no overlaps")


def test_same_audience_sharing_proof_refs_scores_overlap(tmp_path: Path) -> None:
    """Overlap is a recorded gap, never a refusal."""
    print("\n[test] same_audience_sharing_proof_refs_scores_overlap ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-903-feat-score-overlap",
        delivers=[
            _slice(audience="operator", feature_id="F001", proof=_WALK_PROOF),
            _slice(
                audience="operator",
                capability="The operator also reads the gap in the sidecar.",
                feature_id="F001",
                proof=_WALK_PROOF,
            ),
        ],
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.slices == outcome_score.SLICES_OVERLAP
    assert score.overlaps and "F001" in score.overlaps[0]
    assert not score.refuse  # D003: only a missing outcome refuses
    print(f"  ✓ overlap named, lock not refused: {score.overlaps[0]}")


@pytest.mark.parametrize(
    ("audience", "expected"),
    [
        ("end_user", "walk"),
        ("operator", "walk"),
        ("builder", "walk"),
        ("agent", "named_test"),
        ("auditor", "named_test"),
        ("implementer", "named_test"),
    ],
)
def test_missing_proof_infers_method_by_audience(
    tmp_path: Path, audience: str, expected: str
) -> None:
    """Step 3 — user-facing slices infer 'walk'; everything else 'named_test'."""
    print(f"\n[test] missing_proof_infers_method_by_audience[{audience}] ...")
    plan_dir = _write_plan(
        tmp_path,
        f"2026-08-13-910-feat-score-infer-{audience.replace('_', '-')}",
        delivers=[_slice(audience=audience)],
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.proofs == outcome_score.PROOFS_INFERRED
    assert score.slice_scores[0].method == expected
    assert score.slice_scores[0].declared_method is None
    print(f"  ✓ {audience} → inferred '{expected}'")


def test_accepted_gap_beats_inference(tmp_path: Path) -> None:
    """An operator acceptance in decisions.jsonl scores accepted-gap and the
    reason is carried onto the slice."""
    print("\n[test] accepted_gap_beats_inference ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-904-feat-score-accepted",
        delivers=[_slice()],
        decisions=[
            {
                "id": "D001",
                "kind": "proof_gap_accepted",
                "slice": "F001",
                "reason": "the walk needs a device we do not have until Thursday",
            }
        ],
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.proofs == outcome_score.PROOFS_ACCEPTED_GAP
    assert score.slice_scores[0].accepted
    assert "Thursday" in (score.slice_scores[0].accept_reason or "")
    print("  ✓ accepted-gap with the operator's reason attached")


@pytest.mark.parametrize("token", ["1", 1, "F001", "*", "all"])
def test_gap_entry_addresses_slice_by_index_feature_or_wildcard(
    tmp_path: Path, token: object
) -> None:
    """A slice is addressable by 1-based index, proving feature id, or wildcard."""
    print(f"\n[test] gap_entry_addresses_slice[{token!r}] ...")
    plan_dir = _write_plan(
        tmp_path,
        f"2026-08-13-911-feat-score-addr-{str(token).strip('*')or 'star'}",
        delivers=[_slice()],
        decisions=[{"id": "D001", "kind": "proof_gap_accepted", "slice": token}],
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.slice_scores[0].accepted
    print(f"  ✓ {token!r} addresses slice 1")


def test_unresolvable_inherits_scores_missing_and_refuses(tmp_path: Path) -> None:
    """inherits pointing at a plan that does not exist is not an outcome."""
    print("\n[test] unresolvable_inherits_scores_missing_and_refuses ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-905-fix-score-dangling",
        inherits="2026-01-01-001-feat-does-not-exist",
        plan_type="fix",
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.outcome == outcome_score.OUTCOME_MISSING
    assert score.refuse
    assert "outcome" in (score.refusal or "")
    assert any("does not resolve" in n for n in score.notes)
    print("  ✓ dangling inherits → missing outcome, refusal names 'outcome'")


@pytest.mark.parametrize(
    ("ref", "method", "expected"),
    [
        ({"type": "screenshot", "uri": "./evidence/walk.png"}, "walk", True),
        ({"type": "test_output", "uri": "./evidence/t.txt"}, "named_test", True),
        ({"type": "file", "uri": "./evidence/notes.md"}, "walk", False),
        ({"type": "log", "uri": "./e/x.log", "note": "proof:request 200 OK"}, "request", True),
        ({"type": "file", "uri": "./e/probe-proof:probe.txt"}, "probe", True),
        ({"type": "test_output", "uri": "./e/t.txt"}, "probe", False),
    ],
)
def test_evidence_ref_runs_method(ref: dict, method: str, expected: bool) -> None:
    """Only an unambiguous evidence type, or an explicit proof:<method> marker,
    counts as the proof having run."""
    print(f"\n[test] evidence_ref_runs_method[{ref['type']}/{method}] ...")
    assert outcome_score.evidence_ref_runs_method(ref, method) is expected
    print(f"  ✓ → {expected}")


# ───────────────────────────  acceptance 1  ───────────────────────────


def test_ac1_no_delivers_no_inherits_refuses_lock_naming_outcome(
    tmp_path: Path, capsys
) -> None:
    """AC1 — no delivers[], no inherits, and no feature carrying a proof: lock
    refuses (exit 3), names 'outcome', and the status stays draft."""
    print("\n[test] ac1_no_delivers_no_inherits_refuses_lock ...")
    plan_dir = _write_plan(tmp_path, "2026-08-13-921-feat-ac1-no-outcome")
    rc = cli._plan_lock_main([str(plan_dir)])
    captured = capsys.readouterr()
    assert rc == 3
    assert _status_of(plan_dir) == "draft"  # no transition
    assert "outcome" in captured.err
    assert "outcome: missing" in captured.out
    print("  ✓ exit 3, 'outcome' named, status still draft")


def test_ac1_refusal_names_only_the_outcome_not_the_proofs(tmp_path: Path, capsys) -> None:
    """The refusal must stay about the one blocking thing (D003)."""
    print("\n[test] ac1_refusal_names_only_the_outcome ...")
    plan_dir = _write_plan(tmp_path, "2026-08-13-922-feat-ac1-one-thing")
    cli._plan_lock_main([str(plan_dir)])
    err = capsys.readouterr().err
    assert "are recorded as gaps and checked at close" in err.lower()
    for gap in ("missing proofs", "undeclared audience", "overlapping slices"):
        assert gap in err.lower(), gap
    print("  ✓ refusal says gaps do not block")


# ───────────────────────────  acceptance 2  ───────────────────────────


def test_ac2_inherit_fix_with_one_delta_slice_locks(tmp_path: Path, capsys) -> None:
    """AC2 — a fix plan inheriting a parent outcome locks with one delta."""
    print("\n[test] ac2_inherit_fix_with_one_delta_slice_locks ...")
    parent_id = "2026-08-13-930-feat-ac2-parent"
    _write_plan(
        tmp_path, parent_id, delivers=[_slice(proof=_WALK_PROOF)], status="active"
    )
    child = _write_plan(
        tmp_path,
        "2026-08-13-931-fix-ac2-child",
        plan_type="fix",
        inherits=parent_id,
        delivers=[
            _slice(
                capability="NAV history also survives an unclean kill, not just a restart.",
                proof={
                    "metric": "SIGKILL mid-write and the prior NAV row is still listed",
                    "method": "probe",
                },
            )
        ],
    )
    rc = cli._plan_lock_main([str(child)])
    out = capsys.readouterr().out
    assert rc == 0
    assert _status_of(child) == "active"
    assert "outcome: inherited" in out
    assert parent_id in out
    assert "slices:  single" in out
    print("  ✓ exit 0, status active, score reads inherited/single")


def test_ac2_inherit_with_no_local_delta_still_locks(tmp_path: Path) -> None:
    """Inheriting is enough: a delta is not required to clear the refusal."""
    print("\n[test] ac2_inherit_with_no_local_delta_still_locks ...")
    parent_id = "2026-08-13-932-feat-ac2-parent-only"
    _write_plan(tmp_path, parent_id, delivers=[_slice(proof=_WALK_PROOF)], status="active")
    child = _write_plan(
        tmp_path, "2026-08-13-933-fix-ac2-nodelta", plan_type="fix", inherits=parent_id
    )
    score = outcome_score.score_plan(child)
    assert score.outcome == outcome_score.OUTCOME_INHERITED
    assert score.slices == outcome_score.SLICES_NA
    assert not score.refuse
    print("  ✓ inherited / n/a, no refusal")


# ───────────────────────────  acceptance 5  ───────────────────────────


def _accepted_gap_plan(tmp_path: Path, plan_id: str, *, status: str = "draft") -> Path:
    """A plan with an outcome and ONE accepted missing proof."""
    return _write_plan(
        tmp_path,
        plan_id,
        status=status,
        delivers=[_slice(audience="operator")],
        decisions=[
            {
                "id": "D001",
                "kind": "proof_gap_accepted",
                "slice": 1,
                "reason": "the walk waits until the surface exists",
            }
        ],
    )


def test_ac5_accepted_missing_proof_locks_and_records_the_gap(
    tmp_path: Path, capsys
) -> None:
    """AC5 — lock succeeds (exit 0) and the gap lands in the pre_impl sidecar."""
    print("\n[test] ac5_accepted_missing_proof_locks_and_records_gap ...")
    plan_dir = _accepted_gap_plan(tmp_path, "2026-08-13-940-feat-ac5-accepted")
    rc = cli._plan_lock_main([str(plan_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert _status_of(plan_dir) == "active"
    assert "proofs:  accepted-gap" in out

    sidecar = (
        plan_dir
        / "evidence"
        / "goal-governance"
        / "pre_impl"
        / outcome_score.OUTCOME_SCORE_ARTIFACT
    )
    assert sidecar.is_file(), "the accepted gap was not recorded"
    payload = json.loads(sidecar.read_text())
    assert payload["proofs"] == outcome_score.PROOFS_ACCEPTED_GAP
    recorded = payload["slice_scores"][0]
    assert recorded["gap"] is True
    assert recorded["gap_accepted"] is True
    assert "waits until the surface exists" in recorded["gap_accept_reason"]
    assert recorded["method_checked_at_close"] == "walk"
    print(f"  ✓ exit 0; gap recorded at {sidecar.name}")


# ───────  close pays the accepted gap (F004/F005 contract, regression cover)  ───────
#
# Not an F002 acceptance criterion after the D010 split — close obligations are
# F004's and sidecar durability is F005's. Kept here because the behaviour is
# reached through this module's evaluate_close_proofs(), and a scoring change
# that silently retired a gap would otherwise go unnoticed.


def test_close_fails_until_proof_runs_or_gap_is_deferred(tmp_path: Path) -> None:
    """The accepted gap is paid at close: refuse, then pass on evidence, and
    pass on a decisions.jsonl deferral."""
    print("\n[test] close_fails_until_proof_runs_or_deferred ...")
    plan_dir = _accepted_gap_plan(
        tmp_path, "2026-08-13-950-feat-close-gap", status="active"
    )

    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert len(reasons) == 1
    assert "walk" in reasons[0]
    with pytest.raises(completion_gate.CompletionGateError, match="never ran"):
        completion_gate.close_plan(plan_dir)
    assert _status_of(plan_dir) == "active"  # no transition
    print("  ✓ close refused while the proof is unrun")

    # ── the proof runs: a screenshot on the proving feature ──
    features_path = plan_dir / "features.json"
    data = json.loads(features_path.read_text())
    data["features"][0]["evidence_refs"] = [
        {"type": "screenshot", "uri": "./evidence/nav-walk.png", "note": "the walk"}
    ]
    features_path.write_text(json.dumps(data, indent=2) + "\n")
    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    result = completion_gate.close_plan(plan_dir, dry_run=True)
    assert result.status_flipped is False  # dry-run
    print("  ✓ a screenshot on the proving feature satisfies the walk")

    # ── or the gap is deferred instead ──
    data["features"][0].pop("evidence_refs")
    features_path.write_text(json.dumps(data, indent=2) + "\n")
    assert outcome_score.evaluate_close_proofs(plan_dir)  # unrun again
    with (plan_dir / "decisions.jsonl").open("a") as fh:
        fh.write(
            json.dumps(
                {
                    "id": "D002",
                    "kind": "proof_gap_deferred",
                    "slice": 1,
                    "reason": "surface slipped to the next plan; carried forward",
                }
            )
            + "\n"
        )
    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    closed = completion_gate.close_plan(plan_dir)
    assert closed.status_flipped is True
    assert _status_of(plan_dir) == "completed"
    print("  ✓ a deferral in decisions.jsonl closes the plan")


def test_wrong_evidence_type_does_not_satisfy_the_proof(tmp_path: Path) -> None:
    """A named_test proof is not paid by a screenshot."""
    print("\n[test] wrong_evidence_type_does_not_satisfy ...")
    feature = dict(_CLEAN_FEATURE)
    feature["evidence_refs"] = [{"type": "screenshot", "uri": "./evidence/x.png"}]
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-951-feat-close-wrongtype",
        status="active",
        features=[feature],
        delivers=[
            _slice(
                audience="agent",
                proof={"metric": "the named regression test passes", "method": "named_test"},
            )
        ],
    )
    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert len(reasons) == 1 and "named_test" in reasons[0]
    print("  ✓ screenshot does not pay a named_test proof")


def test_close_is_silent_for_plans_with_no_slices(tmp_path: Path) -> None:
    """Every plan authored before this contract closes exactly as before."""
    print("\n[test] close_is_silent_for_plans_with_no_slices ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-952-feat-close-legacy",
        status="active",
        contract=False,
        schema_version=None,
    )
    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    closed = completion_gate.close_plan(plan_dir)
    assert closed.status_flipped is True
    print("  ✓ no slices → no close check")


# ───────────────────────────  acceptance 6  ───────────────────────────


def test_ac6_legacy_plan_without_contract_locks(tmp_path: Path, capsys) -> None:
    """AC6 — a pre-1.1 plan carrying no contract at all still locks; the score
    prints and says out loud that the outcome gap is advisory."""
    print("\n[test] ac6_legacy_plan_without_contract_locks ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-960-feat-ac6-legacy",
        contract=False,
        schema_version=None,
    )
    rc = cli._plan_lock_main([str(plan_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert _status_of(plan_dir) == "active"
    assert "outcome: missing" in out
    assert "advisory only" in out
    print("  ✓ legacy plan locks; the gap prints as advisory")


def test_ac6_trivial_tier_plan_is_not_refused(tmp_path: Path) -> None:
    """The refusal mirrors the validator's applicability: trivial plans are
    exempt even at schema_version 1.1."""
    print("\n[test] ac6_trivial_tier_plan_is_not_refused ...")
    plan_dir = _write_plan(
        tmp_path, "2026-08-13-961-feat-ac6-trivial", tier="trivial", contract=False
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.outcome == outcome_score.OUTCOME_MISSING
    assert not score.delivers_required
    assert not score.refuse
    print("  ✓ trivial tier scores missing but is not refused")


def test_ac6_plan_with_outcome_but_no_proof_locks_as_inferred(
    tmp_path: Path, capsys
) -> None:
    """AC6 — an outcome with no proof at all locks (inferred), never refuses."""
    print("\n[test] ac6_plan_with_outcome_but_no_proof_locks_as_inferred ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-962-feat-ac6-noproof",
        delivers=[_slice(audience="end_user")],
    )
    rc = cli._plan_lock_main([str(plan_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert _status_of(plan_dir) == "active"
    assert "outcome: present" in out
    assert "proofs:  inferred" in out
    assert "walk" in out
    print("  ✓ exit 0; proofs inferred (walk)")


# ─────────────────  cross-plan proof refs (i1 finding 1)  ─────────────────


def _screenshot_feature() -> dict:
    feature = dict(_CLEAN_FEATURE)
    feature["evidence_refs"] = [
        {"type": "screenshot", "uri": "./evidence/walk.png", "note": "the walk"}
    ]
    return feature


def test_cross_plan_proof_ref_is_not_paid_by_local_evidence(tmp_path: Path) -> None:
    """A slice proved by ``<other-plan>:F001`` is NOT satisfied by evidence on
    the LOCAL F001 — different plan, different feature, unrelated screenshot."""
    print("\n[test] cross_plan_proof_ref_is_not_paid_by_local_evidence ...")
    other_id = "2026-08-13-980-feat-crossplan-parent"
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-981-feat-crossplan-child",
        status="active",
        features=[_screenshot_feature()],  # local F001 carries the screenshot
        delivers=[_slice(audience="operator", plan=other_id)],
    )
    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert len(reasons) == 1, reasons
    assert "walk" in reasons[0]
    assert other_id in reasons[0], "the unresolved cross-plan ref is not named"
    print("  ✓ a local screenshot cannot pay another plan's proof")


def test_cross_plan_proof_ref_is_paid_by_the_target_plans_evidence(
    tmp_path: Path,
) -> None:
    """The same ref IS satisfied once the referenced plan's own features.json
    carries the evidence — resolution is by (plan_id, feature_id)."""
    print("\n[test] cross_plan_proof_ref_is_paid_by_target_plan ...")
    other_id = "2026-08-13-982-feat-crossplan-target"
    _write_plan(tmp_path, other_id, features=[_screenshot_feature()], contract=False)
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-983-feat-crossplan-consumer",
        status="active",
        features=[dict(_CLEAN_FEATURE)],  # local F001 has NO evidence
        delivers=[_slice(audience="operator", plan=other_id)],
    )
    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    print("  ✓ evidence on the referenced plan pays the proof")


def test_cross_plan_slice_is_addressable_by_bare_feature_id(tmp_path: Path) -> None:
    """A decisions.jsonl deferral may address the slice as 'F001' even when the
    ref is stored fully qualified."""
    print("\n[test] cross_plan_slice_addressable_by_bare_feature_id ...")
    other_id = "2026-08-13-984-feat-crossplan-defer-target"
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-985-feat-crossplan-defer",
        status="active",
        delivers=[_slice(audience="operator", plan=other_id)],
        decisions=[
            {
                "id": "D001",
                "kind": "proof_gap_deferred",
                "slice": "F001",
                "reason": "the parent plan carries the walk",
            }
        ],
    )
    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    print("  ✓ bare feature id addresses a cross-plan slice")


# ───────────────  gap recording precedes the flip (i1 finding 2)  ───────────────


def test_lock_refuses_when_the_score_cannot_be_recorded(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A sidecar write failure REFUSES the lock: an active plan whose accepted
    gaps were never recorded cannot be honoured at close."""
    print("\n[test] lock_refuses_when_score_cannot_be_recorded ...")
    plan_dir = _accepted_gap_plan(tmp_path, "2026-08-13-990-feat-record-fails")

    def _boom(_plan_dir, _score):
        raise OSError("read-only file system")

    monkeypatch.setattr(outcome_score, "write_score_sidecar", _boom)
    rc = cli._plan_lock_main([str(plan_dir)])
    err = capsys.readouterr().err
    assert rc != 0
    assert _status_of(plan_dir) == "draft", "the plan flipped despite unrecorded gaps"
    assert "outcome-score" in err and "REFUSED" in err
    print("  ✓ write failure refuses the lock and leaves the plan draft")


def test_score_is_recorded_before_the_status_flip(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Ordering: the sidecar exists even when the flip itself is refused."""
    print("\n[test] score_is_recorded_before_the_status_flip ...")
    plan_dir = _accepted_gap_plan(tmp_path, "2026-08-13-991-feat-record-ordering")
    sidecar = (
        plan_dir
        / "evidence"
        / "goal-governance"
        / "pre_impl"
        / outcome_score.OUTCOME_SCORE_ARTIFACT
    )

    def _refuse(*_args, **_kwargs):
        raise cli.sufficiency_gate.SufficiencyGateError("synthetic gate refusal")

    monkeypatch.setattr(cli.sufficiency_gate, "lock_plan", _refuse)
    rc = cli._plan_lock_main([str(plan_dir)])
    capsys.readouterr()
    assert rc == 3
    assert _status_of(plan_dir) == "draft"
    assert sidecar.is_file(), "the score was only recorded after the flip"
    assert json.loads(sidecar.read_text())["slice_scores"][0]["gap_accepted"] is True
    print("  ✓ the gap set is on disk before the flip is attempted")


# ─────────────  a locked obligation survives a contract edit (i2 #1)  ─────────────


def _rewrite_contract(plan_dir: Path, **changes) -> None:
    """Edit objective_contract.json in place after the lock."""
    path = plan_dir / "objective_contract.json"
    payload = json.loads(path.read_text())
    payload.update(changes)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def test_locked_obligation_survives_deleting_the_slice(tmp_path: Path) -> None:
    """Removing a slice from the contract after the lock does NOT remove the
    proof it owes: close still refuses, naming the drift."""
    print("\n[test] locked_obligation_survives_deleting_the_slice ...")
    plan_dir = _accepted_gap_plan(tmp_path, "2026-08-13-992-feat-erase-slice")
    assert cli._plan_lock_main([str(plan_dir)]) == 0

    _rewrite_contract(plan_dir, delivers=[])
    assert outcome_score.score_plan(plan_dir).slice_scores == ()  # live contract is empty

    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert len(reasons) == 1, reasons
    assert "walk" in reasons[0]
    assert "no longer in the contract" in reasons[0]
    with pytest.raises(completion_gate.CompletionGateError, match="never ran"):
        completion_gate.close_plan(plan_dir)
    assert _status_of(plan_dir) == "active"
    print("  ✓ the deleted slice still owes its walk")


def test_locked_obligation_survives_deleting_the_whole_contract(tmp_path: Path) -> None:
    """The strongest erasure — the contract file itself goes away."""
    print("\n[test] locked_obligation_survives_deleting_the_contract ...")
    plan_dir = _accepted_gap_plan(tmp_path, "2026-08-13-993-feat-erase-contract")
    assert cli._plan_lock_main([str(plan_dir)]) == 0

    (plan_dir / "objective_contract.json").unlink()
    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert len(reasons) == 1 and "no longer in the contract" in reasons[0]
    print("  ✓ deleting the contract does not delete the obligation")


def test_locked_method_cannot_be_weakened_after_lock(tmp_path: Path) -> None:
    """Swapping the proof method post-lock does not let other evidence pay it:
    the locked method is what close checks, and the swap is named."""
    print("\n[test] locked_method_cannot_be_weakened_after_lock ...")
    plan_dir = _accepted_gap_plan(tmp_path, "2026-08-13-994-feat-swap-method")
    assert cli._plan_lock_main([str(plan_dir)]) == 0  # locked obligation: walk

    _rewrite_contract(
        plan_dir,
        delivers=[
            _slice(
                audience="operator",
                proof={"metric": "the named regression test passes", "method": "named_test"},
            )
        ],
    )
    features_path = plan_dir / "features.json"
    data = json.loads(features_path.read_text())
    data["features"][0]["evidence_refs"] = [
        {"type": "test_output", "uri": "./evidence/t.txt"}
    ]
    features_path.write_text(json.dumps(data, indent=2) + "\n")

    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert len(reasons) == 1, reasons
    assert "walk" in reasons[0]
    assert "proof method changed after lock" in reasons[0]
    print("  ✓ a test_output does not pay the walk the lock recorded")


def test_locked_obligation_is_paid_by_the_evidence_it_named(tmp_path: Path) -> None:
    """The snapshot is not a ratchet: run the proof the lock recorded and close
    proceeds, contract edit or not."""
    print("\n[test] locked_obligation_is_paid_by_the_evidence_it_named ...")
    plan_dir = _accepted_gap_plan(tmp_path, "2026-08-13-995-feat-locked-paid")
    assert cli._plan_lock_main([str(plan_dir)]) == 0

    _rewrite_contract(plan_dir, delivers=[])
    features_path = plan_dir / "features.json"
    data = json.loads(features_path.read_text())
    data["features"][0]["evidence_refs"] = [
        {"type": "screenshot", "uri": "./evidence/nav-walk.png", "note": "the walk"}
    ]
    features_path.write_text(json.dumps(data, indent=2) + "\n")

    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    assert completion_gate.close_plan(plan_dir).status_flipped is True
    print("  ✓ the recorded walk, once run, closes the plan")


def test_locked_obligation_is_still_deferrable(tmp_path: Path) -> None:
    """The escape hatch stays the documented one — a decisions.jsonl deferral,
    not a contract edit."""
    print("\n[test] locked_obligation_is_still_deferrable ...")
    plan_dir = _accepted_gap_plan(tmp_path, "2026-08-13-996-feat-locked-deferred")
    assert cli._plan_lock_main([str(plan_dir)]) == 0
    _rewrite_contract(plan_dir, delivers=[])
    with (plan_dir / "decisions.jsonl").open("a") as fh:
        fh.write(
            json.dumps(
                {
                    "id": "D002",
                    "kind": "proof_gap_deferred",
                    "slice": 1,
                    "reason": "the slice moved to the follow-up plan",
                }
            )
            + "\n"
        )
    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    print("  ✓ a deferral still clears a locked obligation")


def test_slice_added_after_lock_is_also_an_obligation(tmp_path: Path) -> None:
    """The snapshot adds to the live set, it does not replace it."""
    print("\n[test] slice_added_after_lock_is_also_an_obligation ...")
    plan_dir = _accepted_gap_plan(tmp_path, "2026-08-13-997-feat-added-after-lock")
    assert cli._plan_lock_main([str(plan_dir)]) == 0
    _rewrite_contract(
        plan_dir,
        delivers=[
            _slice(audience="operator"),
            _slice(
                audience="agent",
                capability="The agent reads the second slice added after the lock.",
                feature_id="F002",
            ),
        ],
    )
    obligations = outcome_score.close_obligations(
        plan_dir, outcome_score.score_plan(plan_dir)
    )
    assert [(o.index, o.locked) for o in obligations] == [(1, True), (2, False)]
    assert len(outcome_score.evaluate_close_proofs(plan_dir)) == 2
    print("  ✓ locked slice 1 + live slice 2 are both owed")


def test_plans_locked_before_the_sidecar_use_the_live_contract(tmp_path: Path) -> None:
    """No sidecar → the pre-existing behaviour, unchanged."""
    print("\n[test] plans_locked_before_the_sidecar_use_the_live_contract ...")
    plan_dir = _accepted_gap_plan(tmp_path, "2026-08-13-998-feat-no-sidecar", status="active")
    assert outcome_score.read_score_sidecar(plan_dir) is None
    obligations = outcome_score.close_obligations(
        plan_dir, outcome_score.score_plan(plan_dir)
    )
    assert [(o.index, o.locked, o.drift) for o in obligations] == [(1, False, None)]
    print("  ✓ live contract is the whole obligation set without a sidecar")


# ─────────────  a malformed delivers[] is not an outcome (i2 #2)  ─────────────


@pytest.mark.parametrize(
    ("item", "expected_defect"),
    [
        ({}, "no 'audience'"),
        ({"kind": "reliability", "capability": "x" * 20, "proof_refs": [{"id": "F001"}]}, "no 'audience'"),
        ({"audience": "operator", "capability": "x" * 20, "proof_refs": [{"id": "F001"}]}, "no 'kind'"),
        ({"audience": "operator", "kind": "reliability", "capability": "too short", "proof_refs": [{"id": "F001"}]}, "'capability' is absent or shorter"),
        ({"audience": "operator", "kind": "reliability", "capability": "x" * 20}, "no 'proof_refs'"),
        ({"audience": "operator", "kind": "reliability", "capability": "x" * 20, "proof_refs": []}, "no 'proof_refs'"),
        ({"audience": "operator", "kind": "reliability", "capability": "x" * 20, "proof_refs": [{"type": "feature"}]}, "no 'proof_refs'"),
        ("not a mapping", "not a JSON object"),
    ],
)
def test_slice_defects_names_the_missing_field(item: object, expected_defect: str) -> None:
    """Every required field of objective_contract.schema.json is checked."""
    print(f"\n[test] slice_defects[{expected_defect}] ...")
    defects = outcome_score.slice_defects(item)
    assert any(expected_defect in d for d in defects), defects
    print(f"  ✓ {defects}")


def test_valid_slice_has_no_defects() -> None:
    print("\n[test] valid_slice_has_no_defects ...")
    assert outcome_score.slice_defects(_slice(proof=_WALK_PROOF)) == ()
    print("  ✓ a well-formed slice is clean")


def test_empty_delivers_item_does_not_satisfy_the_outcome(tmp_path: Path, capsys) -> None:
    """`delivers: [{}]` must refuse the lock for the missing outcome, not pass
    it on the strength of a mapping that names nobody."""
    print("\n[test] empty_delivers_item_does_not_satisfy_the_outcome ...")
    plan_dir = _write_plan(
        tmp_path, "2026-08-13-999-feat-malformed-slice", delivers=[{}]
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.outcome == outcome_score.OUTCOME_MISSING
    assert score.slice_scores == ()
    assert score.refuse
    assert "delivers[1] states no outcome" in " ".join(score.notes)

    rc = cli._plan_lock_main([str(plan_dir)])
    captured = capsys.readouterr()
    assert rc == 3
    assert _status_of(plan_dir) == "draft"
    assert "states no outcome" in captured.err
    print("  ✓ a malformed slice is not an outcome")


def test_malformed_slice_alongside_a_valid_one_is_noted_not_fatal(tmp_path: Path) -> None:
    """One real outcome is enough to lock; the junk entry is still named."""
    print("\n[test] malformed_slice_alongside_a_valid_one ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-989-feat-mixed-slices",
        delivers=[{"audience": "operator"}, _slice(proof=_WALK_PROOF)],
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.outcome == outcome_score.OUTCOME_PRESENT
    assert [s.index for s in score.slice_scores] == [2]  # index stays 1-based on the raw array
    assert not score.refuse
    assert any("delivers[1] states no outcome" in n for n in score.notes)
    print("  ✓ the valid slice carries the outcome; the junk one is a note")


def test_inheriting_a_parent_whose_delivers_are_malformed_does_not_resolve(
    tmp_path: Path,
) -> None:
    """A parent carrying only junk carries no outcome to inherit."""
    print("\n[test] inheriting_a_malformed_parent_does_not_resolve ...")
    parent_id = "2026-08-13-988-feat-malformed-parent"
    _write_plan(tmp_path, parent_id, delivers=[{}], status="active")
    child = _write_plan(
        tmp_path,
        "2026-08-13-987-fix-malformed-parent-child",
        plan_type="fix",
        inherits=parent_id,
    )
    score = outcome_score.score_plan(child)
    assert score.outcome == outcome_score.OUTCOME_MISSING
    assert not score.inherits_resolved
    assert score.refuse
    print("  ✓ an empty parent outcome cannot be inherited")


# ───────────────────────────  rendering  ───────────────────────────


def test_render_score_lines_is_exactly_three_axes(tmp_path: Path) -> None:
    """Step 1 — the score is three lines: outcome, slices, proofs."""
    print("\n[test] render_score_lines_is_exactly_three_axes ...")
    plan_dir = _write_plan(
        tmp_path, "2026-08-13-970-feat-score-render", delivers=[_slice(proof=_WALK_PROOF)]
    )
    lines = outcome_score.render_score_lines(outcome_score.score_plan(plan_dir))
    assert len(lines) == 3, lines  # no notes on a clean plan
    assert lines[0].startswith("[outcome-score] outcome: ")
    assert lines[1].startswith("[outcome-score] slices:  ")
    assert lines[2].startswith("[outcome-score] proofs:  ")
    print("  ✓ three axes, one line each")


# ─────────────  a feature carrying its own proof IS a slice (D009)  ─────────────
#
# The third route to an outcome. Covers the rewritten F002 acceptance:
#   AC1 — the refusal now requires all three routes to be absent, and names
#         the feature route as a way out.
#   AC3 — a plan whose features each carry a proof and declares no delivers[]
#         LOCKS, scoring one slice per proof-carrying feature.
#   AC4 — a feature-as-slice with no user_impact locks and records an accepted
#         gap naming the absent audience.
#   AC6 — a feature without a proof is not a slice, so no existing plan is
#         newly scored (or newly refused).


def _proof_feature(
    fid: str,
    *,
    method: str = "named_test",
    metric: str = "the named test passes against the built surface",
    audience: str | None = "operator",
    summary: str = "The operator can see the thing that used to be invisible.",
    category: str = "tooling",
) -> dict:
    """A features.json feature carrying its own proof."""
    description = f"{fid} — an independently testable unit of the plan."
    feature: dict = {
        "id": fid,
        "category": category,
        "description": description,
        "acceptance": f"(1) {fid} does the thing it says it does.",
        "passes": False,
        "proof": {"metric": metric, "method": method},
    }
    if audience is not None:
        impact: dict = {"audience": audience}
        if audience != "none":
            # D005 binds the claim to the description it was written against.
            impact["summary"] = summary
            impact["surfaces"] = ["backend"]
            impact["description_hash"] = hashlib.sha256(
                description.encode("utf-8")
            ).hexdigest()
        feature["user_impact"] = impact
    return feature


def test_feature_proof_method_reads_only_the_four_cheap_methods() -> None:
    """A `proof` block is a proof only when its method is in the closed set."""
    print("\n[test] feature_proof_method_reads_only_the_four_methods ...")
    for method in ("walk", "request", "named_test", "probe"):
        assert outcome_score.feature_proof_method(_proof_feature("F001", method=method)) == method
    assert outcome_score.feature_proof_method(_proof_feature("F001", method="kpi_warehouse")) is None
    assert outcome_score.feature_proof_method({"id": "F001"}) is None
    assert outcome_score.feature_proof_method({"id": "F001", "proof": "walk"}) is None
    assert outcome_score.feature_proof_method({"id": "F001", "proof": {"metric": "x" * 12}}) is None
    print("  ✓ four methods in, everything else out")


@pytest.mark.parametrize(
    ("proof", "expected_defect"),
    [
        pytest.param({"method": "walk"}, "metric", id="metric-absent"),
        pytest.param({"metric": "too short", "method": "walk"}, "metric", id="metric-too-short"),
        pytest.param({"metric": "   " + " " * 20, "method": "walk"}, "metric", id="metric-blank"),
        pytest.param({"metric": 12, "method": "walk"}, "metric", id="metric-not-a-string"),
        pytest.param({"metric": "x" * 12}, "method", id="method-absent"),
        pytest.param({"metric": "x" * 12, "method": "kpi_warehouse"}, "method", id="method-offenum"),
        pytest.param({"metric": "x" * 12, "method": None}, "method", id="method-null"),
        pytest.param("walk", "not a JSON object", id="proof-not-an-object"),
        pytest.param([], "not a JSON object", id="proof-a-list"),
    ],
)
def test_proof_defects_names_the_missing_half(proof: object, expected_defect: str) -> None:
    """Both halves are load-bearing. A proof that names a method and measures
    nothing is not a proof — the metric is what close would check."""
    print(f"\n[test] proof_defects[{expected_defect}] ...")
    defects = outcome_score.proof_defects(proof)
    assert defects, f"{proof!r} should state no measurement"
    assert any(expected_defect in d for d in defects), defects
    print(f"  ✓ {defects[0]}")


def test_proof_defects_accepts_a_complete_proof() -> None:
    """A metric of at least ten characters plus an allowed method is a proof."""
    print("\n[test] proof_defects_accepts_a_complete_proof ...")
    assert outcome_score.proof_defects(_WALK_PROOF) == ()
    for method in ("walk", "request", "named_test", "probe"):
        assert outcome_score.proof_defects({"metric": "x" * 10, "method": method}) == ()
    print("  ✓ metric >= 10 chars + allowed method = a proof")


@pytest.mark.parametrize(
    ("proof", "why"),
    [
        pytest.param({"method": "walk"}, "no metric at all", id="metric-absent"),
        pytest.param({"metric": "restart", "method": "walk"}, "metric under the floor", id="short"),
        pytest.param({"metric": None, "method": "probe"}, "null metric", id="metric-null"),
    ],
)
def test_a_feature_proof_that_measures_nothing_is_not_a_slice(proof: dict, why: str) -> None:
    """Regression (F002 i0): `feature_proof_method()` validated the method but
    not the metric, so `proof: {"method": "walk"}` alone made a feature a slice
    and cleared the missing-outcome refusal while owing nothing at close."""
    print(f"\n[test] feature_proof_that_measures_nothing_is_not_a_slice[{why}] ...")
    feature = _proof_feature("F001")
    feature["proof"] = proof
    assert outcome_score.feature_proof_method(feature) is None
    print(f"  ✓ {why} → not proof-carrying")


def test_a_feature_proof_without_a_metric_does_not_clear_the_refusal(tmp_path: Path) -> None:
    """The whole point of the metric floor: no delivers[], no inherits, and a
    feature whose proof measures nothing → the lock still refuses, and the
    refusal still names 'outcome'."""
    print("\n[test] feature_proof_without_metric_does_not_clear_refusal ...")
    feature = _proof_feature("F001")
    feature["proof"] = {"method": "walk"}
    plan_dir = _write_plan(
        tmp_path, "2026-08-13-993-feat-proof-without-metric", delivers=None, features=[feature]
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.outcome == outcome_score.OUTCOME_MISSING
    assert score.slice_scores == ()
    assert score.refuse
    assert "outcome" in (score.refusal or "")
    # The author who wrote a proof and got no slice is told why, not left to guess.
    assert any("F001" in n and "metric" in n for n in score.notes), score.notes
    print("  ✓ still refuses, and the note names F001's absent metric")


def test_an_inherited_parent_needs_a_real_proof_to_resolve(tmp_path: Path) -> None:
    """The parent is held to exactly the bar the child is: a parent whose only
    proof-carrying feature measures nothing carries no outcome to inherit."""
    print("\n[test] inherited_parent_needs_a_real_proof_to_resolve ...")
    parent_id = "2026-08-13-994-feat-hollow-parent"
    hollow = _proof_feature("F001")
    hollow["proof"] = {"method": "named_test"}
    _write_plan(tmp_path, parent_id, delivers=None, features=[hollow], status="active")
    child = _write_plan(
        tmp_path, "2026-08-13-995-feat-inherits-hollow", delivers=None, inherits=parent_id
    )
    score = outcome_score.score_plan(child)
    assert not score.inherits_resolved
    assert score.outcome == outcome_score.OUTCOME_MISSING
    assert score.refuse
    print("  ✓ a hollow parent proof does not resolve an inherits")


def test_a_delivers_proof_that_measures_nothing_falls_back_to_inference(tmp_path: Path) -> None:
    """A malformed `proof` on an otherwise good delivers[] entry does not drop
    the slice — the entry still states an outcome — but it is not counted as a
    declared proof either, so the slice infers a method and says why."""
    print("\n[test] delivers_proof_that_measures_nothing_falls_back ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-996-feat-hollow-delivers-proof",
        delivers=[_slice(proof={"method": "walk"})],
    )
    score = outcome_score.score_plan(plan_dir)
    (slc,) = score.slice_scores
    assert score.outcome == outcome_score.OUTCOME_PRESENT
    assert not score.refuse
    assert not slc.has_proof
    assert slc.declared_method is None
    assert slc.metric is None
    assert slc.method == "walk"  # inferred — 'operator' is a user-facing audience
    assert score.proofs == outcome_score.PROOFS_INFERRED
    assert any("delivers[1]" in n and "metric" in n for n in score.notes), score.notes
    print("  ✓ slice survives, proof does not, and the note names the absent metric")


def test_ac3_features_carrying_proofs_lock_with_no_delivers(tmp_path: Path, capsys) -> None:
    """AC3 — no delivers[], three proof-carrying features → LOCK, three slices."""
    print("\n[test] ac3_features_carrying_proofs_lock_with_no_delivers ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-980-feat-features-as-slices",
        delivers=None,
        features=[
            _proof_feature(
                "F001",
                method="named_test",
                summary="The operator sees the outcome axis scored at lock.",
            ),
            _proof_feature(
                "F002",
                method="walk",
                audience="end_user",
                summary="The reader sees the score printed at lock instead of nothing.",
            ),
            _proof_feature(
                "F003",
                method="probe",
                audience="agent",
                summary="The agent reads the recorded gaps instead of guessing them.",
            ),
        ],
    )
    rc = cli._plan_lock_main([str(plan_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert _status_of(plan_dir) == "active"
    assert "outcome: present" in out
    assert "from proof-carrying feature(s)" in out

    score = outcome_score.score_plan(plan_dir)
    assert len(score.slice_scores) == 3, score.slice_scores
    assert len(score.feature_slices) == 3
    assert [s.feature_ids for s in score.slice_scores] == [("F001",), ("F002",), ("F003",)]
    assert [s.method for s in score.slice_scores] == ["named_test", "walk", "probe"]
    assert score.proofs == outcome_score.PROOFS_ONE_PER_SLICE
    assert score.slices == outcome_score.SLICES_MECE
    assert not score.refuse
    print("  ✓ exit 0, one slice per proof-carrying feature, one-per-slice proofs")


def test_ac3_one_proof_carrying_feature_clears_the_refusal_with_no_contract(
    tmp_path: Path,
) -> None:
    """A plan with no objective_contract.json at all still states an outcome if
    one feature carries a proof. Any one of the three routes is enough."""
    print("\n[test] ac3_one_proof_feature_clears_refusal_with_no_contract ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-981-feat-no-contract-one-proof",
        contract=False,
        features=[_CLEAN_FEATURE, _proof_feature("F002", method="request")],
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.outcome == outcome_score.OUTCOME_PRESENT
    assert not score.refuse
    assert len(score.slice_scores) == 1
    assert score.slice_scores[0].feature_ids == ("F002",)
    assert score.slice_scores[0].origin == outcome_score.SLICE_FROM_FEATURE
    print("  ✓ one proof-carrying feature is an outcome, contract or no contract")


def test_ac4_feature_as_slice_without_user_impact_locks_and_records_the_gap(
    tmp_path: Path, capsys
) -> None:
    """AC4 — no user_impact is an ACCEPTED GAP naming the absent audience, and
    the lock still succeeds (D009: it is never a refusal)."""
    print("\n[test] ac4_feature_as_slice_without_user_impact_records_gap ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-982-feat-slice-without-audience",
        delivers=None,
        features=[_proof_feature("F001", method="walk", audience=None)],
    )
    rc = cli._plan_lock_main([str(plan_dir)])
    out = capsys.readouterr().out
    assert rc == 0, "an absent audience must never refuse a lock"
    assert _status_of(plan_dir) == "active"
    assert "accepted audience gap(s)" in out

    score = outcome_score.score_plan(plan_dir)
    (gap,) = score.audience_gaps
    assert gap.audience == "unknown"
    assert "audience" in gap.audience_gap
    assert "F001" in gap.audience_gap

    sidecar = json.loads(
        (
            plan_dir
            / "evidence"
            / "goal-governance"
            / "pre_impl"
            / outcome_score.OUTCOME_SCORE_ARTIFACT
        ).read_text()
    )
    recorded = sidecar["slice_scores"][0]
    assert recorded["audience_gap"] is True
    assert "audience" in recorded["audience_gap_reason"]
    assert recorded["origin"] == outcome_score.SLICE_FROM_FEATURE
    assert recorded["method_checked_at_close"] == "walk"
    print("  ✓ exit 0; the absent audience is recorded as an accepted gap")


def test_declared_audience_is_taken_from_user_impact_and_none_is_no_gap(
    tmp_path: Path,
) -> None:
    """A declared audience is used verbatim; `none` is a complete declaration
    on its own (features.schema.json), so it is not a gap."""
    print("\n[test] declared_audience_is_taken_from_user_impact ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-983-feat-audience-declared",
        delivers=None,
        features=[
            _proof_feature(
                "F001",
                audience="end_user",
                summary="The reader sees who a slice is for.",
            ),
            _proof_feature("F002", audience="none"),
        ],
    )
    score = outcome_score.score_plan(plan_dir)
    assert [s.audience for s in score.slice_scores] == ["end_user", "none"]
    assert score.audience_gaps == ()
    # end_user is user-facing → walk; `none` is not → named_test.
    assert [s.inferred_method for s in score.slice_scores] == ["walk", "named_test"]
    print("  ✓ audience read from user_impact; 'none' is a declaration, not a gap")


def test_a_feature_already_proven_by_a_delivers_slice_is_not_counted_twice(
    tmp_path: Path,
) -> None:
    """A delivers[] entry that names F001 already made it a slice. Scoring it
    again would invent an overlap the plan does not have."""
    print("\n[test] feature_proven_by_a_delivers_slice_is_not_counted_twice ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-984-feat-no-double-count",
        delivers=[_slice(feature_id="F001", proof=_WALK_PROOF)],
        features=[_proof_feature("F001", method="named_test"), _proof_feature("F002")],
    )
    score = outcome_score.score_plan(plan_dir)
    assert len(score.slice_scores) == 2, score.slice_scores
    assert score.slice_scores[0].origin == outcome_score.SLICE_FROM_DELIVERS
    assert score.slice_scores[0].feature_ids == ("F001",)
    # The contract's method wins for F001 — the feature did not add a second one.
    assert score.slice_scores[0].method == "walk"
    assert score.slice_scores[1].origin == outcome_score.SLICE_FROM_FEATURE
    assert score.slice_scores[1].feature_ids == ("F002",)
    assert score.overlaps == ()
    print("  ✓ F001 scored once, F002 added as its own slice, no overlap")


def test_ac6_a_feature_without_a_proof_is_not_a_slice(tmp_path: Path) -> None:
    """AC6 — existing plans are unchanged: no proof on a feature, no slice, and
    the refusal still fires for the same (missing-outcome) reason."""
    print("\n[test] ac6_feature_without_a_proof_is_not_a_slice ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-985-feat-no-feature-proofs",
        features=[_CLEAN_FEATURE, {**_CLEAN_FEATURE, "id": "F002"}],
    )
    score = outcome_score.score_plan(plan_dir)
    assert score.slice_scores == ()
    assert score.outcome == outcome_score.OUTCOME_MISSING
    assert score.refuse
    assert "no feature in features.json carries its own proof" in score.refusal
    print("  ✓ no proof, no slice — and the refusal names the third route")


def test_ac1_refusal_names_the_feature_route_as_a_way_out(tmp_path: Path) -> None:
    """AC1 — the refusal has to tell the operator all three ways to clear it."""
    print("\n[test] ac1_refusal_names_the_feature_route ...")
    plan_dir = _write_plan(tmp_path, "2026-08-13-986-feat-refusal-routes")
    refusal = outcome_score.score_plan(plan_dir).refusal or ""
    assert "outcome" in refusal
    assert "no outcome is reachable by any route" in refusal
    assert '"inherits"' in refusal
    assert '"proof": {"metric"' in refusal
    assert "walk|request|named_test|probe" in refusal
    print("  ✓ delivers[], inherits, and feature-proof all named")


def test_inheriting_a_parent_whose_features_carry_proofs_resolves(tmp_path: Path) -> None:
    """The parent is held to the same three-route bar the child is."""
    print("\n[test] inheriting_a_parent_whose_features_carry_proofs ...")
    parent_id = "2026-08-13-987-feat-parent-feature-outcome"
    _write_plan(
        tmp_path,
        parent_id,
        delivers=None,
        features=[_proof_feature("F001", method="walk")],
        status="active",
    )
    child = _write_plan(
        tmp_path,
        "2026-08-13-988-fix-child-of-feature-outcome",
        plan_type="fix",
        inherits=parent_id,
    )
    score = outcome_score.score_plan(child)
    assert score.inherits_resolved
    assert score.outcome == outcome_score.OUTCOME_INHERITED
    assert not score.refuse
    print("  ✓ a parent whose outcome is a proof-carrying feature can be inherited")


def test_feature_as_slice_owes_its_proof_at_close(tmp_path: Path) -> None:
    """The slice is real, so the proof it declared is real: close refuses until
    the walk leaves evidence, and passes once it does."""
    print("\n[test] feature_as_slice_owes_its_proof_at_close ...")
    plan_id = "2026-08-13-989-feat-feature-slice-close"
    plan_dir = _write_plan(
        tmp_path,
        plan_id,
        delivers=None,
        features=[_proof_feature("F001", method="walk")],
    )
    assert cli._plan_lock_main([str(plan_dir)]) == 0

    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert len(reasons) == 1, reasons
    assert "'walk' never ran" in reasons[0]
    assert "F001" in reasons[0]

    features = json.loads((plan_dir / "features.json").read_text())
    features["features"][0]["evidence_refs"] = [
        {"type": "screenshot", "uri": "evidence/F001-walk.png", "note": "walked the path"}
    ]
    (plan_dir / "features.json").write_text(json.dumps(features, indent=2) + "\n")
    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    print("  ✓ close refuses, then passes on the screenshot the walk left")


def test_a_features_json_that_cannot_be_read_carries_no_slices(tmp_path: Path) -> None:
    """A broken features.json must not crash a lock — it simply states no
    outcome, and the refusal stays about the outcome."""
    print("\n[test] unreadable_features_json_carries_no_slices ...")
    plan_dir = _write_plan(tmp_path, "2026-08-13-990-feat-broken-features")
    (plan_dir / "features.json").write_text("{ not json at all")
    assert outcome_score.read_feature_records(plan_dir) == []
    score = outcome_score.score_plan(plan_dir)
    assert score.slice_scores == ()
    assert score.refuse
    assert "outcome" in (score.refusal or "")
    print("  ✓ unreadable features.json → no slices, no crash")


def test_a_feature_slice_capability_falls_back_to_the_description(tmp_path: Path) -> None:
    """With no user_impact.summary there is still something to print: the
    feature's own description."""
    print("\n[test] feature_slice_capability_falls_back_to_description ...")
    feature = _proof_feature("F001", audience=None)
    plan_dir = _write_plan(
        tmp_path, "2026-08-13-991-feat-capability-fallback", delivers=None, features=[feature]
    )
    (slc,) = outcome_score.score_plan(plan_dir).slice_scores
    assert slc.capability == feature["description"]
    assert slc.kind == "tooling"  # the feature's category stands in for kind
    print("  ✓ capability falls back to the description, kind to the category")


def test_a_proof_carrying_feature_is_schema_valid(tmp_path: Path) -> None:
    """The contract has to be authorable: features.json carrying `proof` must
    pass the same Features model plan_loader validates against."""
    print("\n[test] proof_carrying_feature_is_schema_valid ...")
    sys.path.insert(0, str(HERE.parents[3] / "claude" / "shared" / "schemas" / "v1.0"))
    from models.features_model import Features  # noqa: PLC0415
    from pydantic import ValidationError  # noqa: PLC0415

    validated = Features.model_validate(
        {
            "task_id": "2026-08-13-992-feat-schema-valid",
            "schema_version": "1.0",
            "features": [_proof_feature("F001", method="walk")],
        }
    )
    assert validated.features[0].proof is not None
    assert validated.features[0].proof.method.value == "walk"
    with pytest.raises(ValidationError):
        Features.model_validate(
            {
                "task_id": "2026-08-13-992-feat-schema-valid",
                "schema_version": "1.0",
                "features": [_proof_feature("F001", method="kpi_warehouse")],
            }
        )
    # The metric floor the scorer enforces is the model's floor too — the two
    # must agree, or a plan could be authorable and unscoreable (or vice versa).
    with pytest.raises(ValidationError):
        Features.model_validate(
            {
                "task_id": "2026-08-13-992-feat-schema-valid",
                "schema_version": "1.0",
                "features": [_proof_feature("F001", method="walk", metric="too short")],
            }
        )
    print("  ✓ proof accepted; off-enum method and under-floor metric rejected")
