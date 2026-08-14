"""F004 — slice identity at close is the features a slice proves, not its
position in ``delivers[]``.

Plan 2026-08-13-001. Covers the four acceptance criteria:

  1. Replacing a locked slice with a different feature at the SAME numeric
     index keeps the locked obligation AND surfaces the live slice as its own
     obligation. — ``test_replacing_a_locked_slice_at_the_same_index_*``
  2. Prepending a slice, and separately reordering slices, each leave every
     locked obligation intact. — ``test_prepending_*``, ``test_reordering_*``
  3. ``close_obligations()`` does not key on index: mutating only the index of
     a live slice does not change the obligation set — for a record naming its
     features AND for a legacy record naming none. — ``test_close_*``,
     ``test_a_legacy_record_*``
  4. A cross-plan proof ref ``"<parent>:F001"`` is satisfied only by evidence
     on F001 of THAT plan; a local F001 carrying matching evidence does not
     pay it. — ``test_cross_plan_*``
  5. Two slices naming the SAME proving features but differing in capability
     text, swapped in order, produce byte-identical obligations and no drift —
     each locked record pairs with the live slice carrying its own capability.
     — ``test_swapping_two_slices_of_the_same_identity_*``
  6. Two slices identical in identity AND capability are interchangeable — a
     reorder of those is a no-op whether or not their methods differ, and
     nothing in the pairing invents a distinction the contract never made. —
     ``test_two_slices_identical_in_*``, ``test_identical_capability_slices_*``

The lock-time obligation machinery itself (a deleted slice still owes its
proof, a method swap is named as drift) is covered in
``test_outcome_score_f002.py`` and is regression cover for this module.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_outcome_score_f004.py -q
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from dontpanic_orchestrate import cli, outcome_score
from dontpanic_orchestrate.tests.test_outcome_score_f002 import (
    _CLEAN_FEATURE,
    _WALK_PROOF,
    _rewrite_contract,
    _slice,
    _write_plan,
)


def _feature(fid: str, *, evidence: list[dict] | None = None) -> dict:
    feature = dict(_CLEAN_FEATURE)
    feature["id"] = fid
    if evidence is not None:
        feature["evidence_refs"] = evidence
    return feature


def _proven_slice(feature_id: str, *, audience: str = "operator") -> dict:
    """One well-formed slice proved by ``feature_id``, with a declared proof so
    the lock records a method rather than inferring one."""
    return _slice(
        audience=audience,
        capability=f"The {audience} can see what {feature_id} delivers.",
        feature_id=feature_id,
        proof=dict(_WALK_PROOF),
    )


def _multi_slice(*feature_ids: str, audience: str = "operator") -> dict:
    """One well-formed slice proved by SEVERAL features — the shape that
    distinguishes exact identity from a shared-feature overlap."""
    item = _proven_slice(feature_ids[0], audience=audience)
    item["proof_refs"] = [{"type": "feature", "id": fid} for fid in feature_ids]
    item["capability"] = f"The {audience} can see what {'+'.join(feature_ids)} deliver."
    return item


def _locked_plan(tmp_path: Path, plan_id: str, *slice_features: str) -> Path:
    """A plan whose contract declares one proven slice per feature, locked."""
    audiences = ("operator", "agent", "builder")
    plan_dir = _write_plan(
        tmp_path,
        plan_id,
        delivers=[
            _proven_slice(fid, audience=audiences[i % len(audiences)])
            for i, fid in enumerate(slice_features)
        ],
        features=[_feature(fid) for fid in slice_features],
    )
    assert cli._plan_lock_main([str(plan_dir)]) == 0, "the fixture did not lock"
    return plan_dir


def _shape(obligations: list[outcome_score.ProofObligation]) -> list[tuple]:
    return [(o.index, o.locked, o.feature_ids, o.drift) for o in obligations]


def _identity_shape(obligations: list[outcome_score.ProofObligation]) -> list[tuple]:
    """Everything about an obligation EXCEPT the number it is addressed by —
    i.e. what is owed, by whom, and whether the contract moved under it."""
    return [(o.locked, o.feature_ids, o.method, o.drift) for o in obligations]


def _renumbered(
    score: outcome_score.OutcomeScore, *, by: int = 40, reverse: bool = False
) -> outcome_score.OutcomeScore:
    """The same live score with every slice's index shifted, and optionally the
    order reversed: a mutation of position and of nothing else."""
    slices = tuple(reversed(score.slice_scores)) if reverse else score.slice_scores
    return dataclasses.replace(
        score,
        slice_scores=tuple(dataclasses.replace(s, index=s.index + by) for s in slices),
    )


def _sidecar_path(plan_dir: Path) -> Path:
    return (
        plan_dir
        / "evidence"
        / "goal-governance"
        / "pre_impl"
        / outcome_score.OUTCOME_SCORE_ARTIFACT
    )


def _strip_proof_refs_from_sidecar(plan_dir: Path) -> None:
    """Rewrite the lock-time sidecar into the pre-``proof_refs`` shape — a
    record that names no feature at all, which is all a legacy sidecar has."""
    path = _sidecar_path(plan_dir)
    payload = json.loads(path.read_text())
    for record in payload["slice_scores"]:
        record.pop("proof_refs", None)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _obligations(plan_dir: Path) -> list[outcome_score.ProofObligation]:
    return outcome_score.close_obligations(
        plan_dir, outcome_score.score_plan(plan_dir)
    )


# ───────────  AC1 — replacing a slice keeps the locked one and adds the new  ───────────


def test_replacing_a_locked_slice_at_the_same_index_keeps_both_obligations(
    tmp_path: Path,
) -> None:
    """Index 1 now proves F002. The F001 proof the lock recorded is still owed
    — and F002's proof is owed too, so the swap adds an obligation rather than
    quietly inheriting the one it displaced."""
    print("\n[test] replacing_a_locked_slice_at_the_same_index ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-901-feat-replace-slice", "F001")
    _rewrite_contract(plan_dir, delivers=[_proven_slice("F002", audience="agent")])

    obligations = _obligations(plan_dir)
    assert len(obligations) == 2, _shape(obligations)
    locked, live = obligations[0], obligations[1]
    assert (locked.locked, locked.feature_ids) == (True, ("F001",))
    assert locked.drift and "no longer in the contract" in locked.drift
    assert (live.locked, live.feature_ids, live.drift) == (False, ("F002",), None)
    assert len(outcome_score.evaluate_close_proofs(plan_dir)) == 2
    print("  ✓ the displaced F001 proof and the new F002 proof are both owed")


def test_changing_one_feature_of_a_multi_feature_slice_keeps_both_obligations(
    tmp_path: Path,
) -> None:
    """A locked ``{F001, F002}`` slice is re-authored to prove ``{F001, F003}``.
    Sharing F001 does not make it the same slice: the locked pair is still owed
    in full, and the live pair is owed on its own. Pairing on a shared feature
    would consume the live slice and leave F003's proof owed by nobody."""
    print("\n[test] changing_one_feature_of_a_multi_feature_slice ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-907-feat-partial-refs",
        delivers=[_multi_slice("F001", "F002")],
        features=[_feature(fid) for fid in ("F001", "F002", "F003")],
    )
    assert cli._plan_lock_main([str(plan_dir)]) == 0, "the fixture did not lock"
    _rewrite_contract(plan_dir, delivers=[_multi_slice("F001", "F003")])

    obligations = _obligations(plan_dir)
    assert len(obligations) == 2, _shape(obligations)
    locked, live = obligations[0], obligations[1]
    assert (locked.locked, locked.feature_ids) == (True, ("F001", "F002"))
    assert locked.drift and "no longer in the contract" in locked.drift
    assert (live.locked, live.feature_ids, live.drift) == (False, ("F001", "F003"), None)
    assert len(outcome_score.evaluate_close_proofs(plan_dir)) == 2
    print("  ✓ a shared feature does not let the new slice inherit the old proof")


# ───────────────────  AC2 — prepending and reordering are inert  ───────────────────


def test_prepending_a_slice_leaves_the_locked_obligation_intact(
    tmp_path: Path,
) -> None:
    """F001 slid from index 1 to index 2. It is the same slice, so it carries
    no drift — only the prepended F002 is new."""
    print("\n[test] prepending_a_slice_leaves_the_locked_obligation_intact ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-902-feat-prepend-slice", "F001")
    _rewrite_contract(
        plan_dir,
        delivers=[_proven_slice("F002", audience="agent"), _proven_slice("F001")],
    )

    obligations = _obligations(plan_dir)
    assert len(obligations) == 2, _shape(obligations)
    by_feature = {o.feature_ids: o for o in obligations}
    assert by_feature[("F001",)].locked is True
    assert by_feature[("F001",)].drift is None, "the prepend was read as drift"
    assert by_feature[("F002",)].locked is False
    print("  ✓ the prepended slice does not disturb the locked obligation")


def test_reordering_slices_leaves_every_locked_obligation_intact(
    tmp_path: Path,
) -> None:
    """Swapping two locked slices changes nothing: same two obligations, same
    lock-time indices, no drift on either."""
    print("\n[test] reordering_slices_leaves_every_locked_obligation_intact ...")
    plan_dir = _locked_plan(
        tmp_path, "2026-08-13-903-feat-reorder-slices", "F001", "F002"
    )
    before = _shape(_obligations(plan_dir))
    _rewrite_contract(
        plan_dir,
        delivers=[_proven_slice("F002", audience="agent"), _proven_slice("F001")],
    )

    assert _shape(_obligations(plan_dir)) == before
    assert before == [
        (1, True, ("F001",), None),
        (2, True, ("F002",), None),
    ], before
    print("  ✓ the reorder leaves both locked obligations byte-identical")


# ─────────────────────  AC3 — the index is not the key  ─────────────────────


def test_close_obligations_do_not_key_on_the_slice_index(tmp_path: Path) -> None:
    """Mutate ONLY the index on every live slice: the obligation set must be
    unchanged, which it cannot be if index is what pairs lock to live."""
    print("\n[test] close_obligations_do_not_key_on_the_slice_index ...")
    plan_dir = _locked_plan(
        tmp_path, "2026-08-13-904-feat-index-agnostic", "F001", "F002"
    )
    score = outcome_score.score_plan(plan_dir)

    assert outcome_score.close_obligations(
        plan_dir, _renumbered(score, reverse=True)
    ) == outcome_score.close_obligations(plan_dir, score)
    print("  ✓ renumbering the live slices changes no obligation")


def test_a_legacy_record_naming_no_feature_is_not_paired_by_index(
    tmp_path: Path,
) -> None:
    """AC3 on the remaining path — a pre-``proof_refs`` sidecar.

    A record naming no feature has the EMPTY identity, so it pairs with no live
    slice that names one, at ANY index. Both readings must therefore agree:
    the legacy record is owed as a drifted obligation, and the live slice is
    owed on its own. Falling back to position here would make the obligation
    set depend on a number again — matching at index 1 and splitting at 41,
    which is exactly the defect this feature removes.

    The one thing renumbering may move is the *address* of the live slice's own
    obligation: that number is what a ``decisions.jsonl`` deferral must quote,
    so it tracks the live contract by design. The locked record keeps its
    lock-time number regardless.
    """
    print("\n[test] a_legacy_record_naming_no_feature_is_not_paired_by_index ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-908-feat-legacy-record", "F001")
    _strip_proof_refs_from_sidecar(plan_dir)
    assert outcome_score._record_refs(
        outcome_score.read_score_sidecar(plan_dir)["slice_scores"][0]
    ) == (), "the fixture still names a feature"

    score = outcome_score.score_plan(plan_dir)
    at_1 = outcome_score.close_obligations(plan_dir, score)
    at_41 = outcome_score.close_obligations(plan_dir, _renumbered(score))

    assert _identity_shape(at_1) == _identity_shape(at_41), (
        _shape(at_1),
        _shape(at_41),
    )
    assert [(o.locked, o.feature_ids) for o in at_1] == [
        (True, ()),
        (False, ("F001",)),
    ], _shape(at_1)
    assert at_1[0].drift and "no longer in the contract" in at_1[0].drift
    # The locked record keeps its lock-time number at either live numbering;
    # only the live slice's own obligation is addressed by the live number.
    assert (at_1[0].index, at_41[0].index) == (1, 1)
    assert (at_1[1].index, at_41[1].index) == (1, 41)
    assert len(outcome_score.evaluate_close_proofs(plan_dir)) == 2
    print("  ✓ the legacy record is owed as drift at every live index")


# ───────────  AC4 — a cross-plan ref resolves on (plan_id, feature_id)  ───────────


_SCREENSHOT = [{"type": "screenshot", "uri": "./evidence/walk.png", "note": "the walk"}]


def test_cross_plan_proof_ref_is_not_paid_by_a_local_feature_of_the_same_id(
    tmp_path: Path,
) -> None:
    """The parent plan EXISTS and its F001 carries no evidence; the local F001
    carries the screenshot. Close must still refuse — the ref names the
    parent's F001, and same-numbered is not same-feature."""
    print("\n[test] cross_plan_ref_is_not_paid_by_a_local_feature ...")
    parent_id = "2026-08-13-905-feat-crossplan-parent"
    _write_plan(tmp_path, parent_id, features=[_feature("F001")], contract=False)
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-906-feat-crossplan-child",
        status="active",
        features=[_feature("F001", evidence=_SCREENSHOT)],
        delivers=[_slice(audience="operator", plan=parent_id, proof=dict(_WALK_PROOF))],
    )

    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert len(reasons) == 1, reasons
    assert f"{parent_id}:F001" in reasons[0]
    print("  ✓ a local F001 screenshot cannot pay the parent's F001 proof")

    # ── the same evidence, now on the plan the ref actually names ──
    parent_features = tmp_path / "docs" / "plans" / parent_id / "features.json"
    payload = json.loads(parent_features.read_text())
    payload["features"][0]["evidence_refs"] = _SCREENSHOT
    parent_features.write_text(json.dumps(payload, indent=2) + "\n")

    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    print("  ✓ the same evidence on the parent's F001 does pay it")


# ─────────  AC5/AC6 — several slices may share one proving identity  ─────────


def _twin_slice(audience: str, capability: str, *, proof: dict | None = None) -> dict:
    """One of two slices proving the SAME feature. Identity cannot separate
    these; only the capability text can."""
    item = _proven_slice("F001", audience=audience)
    item["capability"] = capability
    if proof is not None:
        item["proof"] = dict(proof)
    return item


_CAP_A = "The operator can see the locked proof survive a reorder."
_CAP_B = "The agent can see the locked proof survive a reorder."

_NAMED_TEST_PROOF = {
    "metric": "the named test lists the prior NAV row after a restart",
    "method": "named_test",
    "surface": "backend",
}


def test_swapping_two_slices_of_the_same_identity_reports_no_drift(
    tmp_path: Path,
) -> None:
    """AC5. Both slices prove F001, so slice identity alone cannot tell them
    apart. Swapped in order, each locked record must still pair with the live
    slice carrying ITS capability — obligations byte-identical, no drift.

    Pairing greedily in live order would hand record 1 the other twin and
    report both as 'capability text changed after lock': drift invented by a
    swap that changed no promise.
    """
    print("\n[test] swapping_two_slices_of_the_same_identity ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-909-feat-duplicate-identity",
        delivers=[_twin_slice("operator", _CAP_A), _twin_slice("agent", _CAP_B)],
        features=[_feature("F001")],
    )
    assert cli._plan_lock_main([str(plan_dir)]) == 0, "the fixture did not lock"
    before = _obligations(plan_dir)
    assert [o.feature_ids for o in before] == [("F001",), ("F001",)], _shape(before)

    _rewrite_contract(
        plan_dir,
        delivers=[_twin_slice("agent", _CAP_B), _twin_slice("operator", _CAP_A)],
    )

    after = _obligations(plan_dir)
    assert after == before, (_shape(before), _shape(after))
    assert [o.drift for o in after] == [None, None], _shape(after)
    print("  ✓ the swap pairs each record with its own capability, no drift")


def test_a_capability_edit_within_an_identity_group_is_still_named_as_drift(
    tmp_path: Path,
) -> None:
    """The other half of AC5: pairing by capability must not become a way to
    LOSE drift. Edit one twin's capability and the reorder-tolerant pairing
    still reports exactly that one record as drifted — the untouched twin
    claims its exact match first, leaving the edited record to the one it
    genuinely moved away from."""
    print("\n[test] a_capability_edit_within_an_identity_group_is_drift ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-910-feat-duplicate-identity-edit",
        delivers=[_twin_slice("operator", _CAP_A), _twin_slice("agent", _CAP_B)],
        features=[_feature("F001")],
    )
    assert cli._plan_lock_main([str(plan_dir)]) == 0, "the fixture did not lock"
    _rewrite_contract(
        plan_dir,
        delivers=[
            _twin_slice("agent", "The agent can see something else entirely now."),
            _twin_slice("operator", _CAP_A),
        ],
    )

    obligations = _obligations(plan_dir)
    drifts = [o.drift for o in obligations]
    assert drifts[0] is None, _shape(obligations)
    assert drifts[1] and "capability text changed after lock" in drifts[1], drifts
    print("  ✓ one edited twin drifts; the untouched twin does not")


def test_a_swap_within_an_identity_group_names_the_method_change_not_a_capability_edit(
    tmp_path: Path,
) -> None:
    """AC5 where BOTH order and method moved — the case that shows capability
    must be the tiebreak ahead of method, not after it.

    Locked: (capability A, walk) and (capability B, named_test). Live: the two
    capabilities have swapped position while the methods stayed put, so each
    slice genuinely changed method. Pairing on "nothing drifted at all" finds
    no exact twin for either record, falls through to live order, and pairs A
    with B — reporting a capability edit nobody made and hiding the method
    change that is the real drift. Capability-first pairs A with A and names
    what actually happened.
    """
    print("\n[test] a_swap_within_an_identity_group_names_the_method_change ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-912-feat-duplicate-identity-methods",
        delivers=[
            _twin_slice("operator", _CAP_A, proof=_WALK_PROOF),
            _twin_slice("agent", _CAP_B, proof=_NAMED_TEST_PROOF),
        ],
        features=[_feature("F001")],
    )
    assert cli._plan_lock_main([str(plan_dir)]) == 0, "the fixture did not lock"
    _rewrite_contract(
        plan_dir,
        delivers=[
            _twin_slice("agent", _CAP_B, proof=_WALK_PROOF),
            _twin_slice("operator", _CAP_A, proof=_NAMED_TEST_PROOF),
        ],
    )

    drifts = [o.drift for o in _obligations(plan_dir)]
    assert drifts == [
        "proof method changed after lock (walk → named_test)",
        "proof method changed after lock (named_test → walk)",
    ], drifts
    print("  ✓ the method change is named; no capability edit is invented")


def test_identical_capability_slices_reorder_to_nothing_even_with_different_methods(
    tmp_path: Path,
) -> None:
    """AC6 at its widest: identity AND capability are equal, methods are not.

    The method pass is a refinement WITHIN a capability group, so it can only
    avoid inventing drift, never create it — the reorder is still a no-op.
    """
    print("\n[test] identical_capability_slices_reorder_with_different_methods ...")
    shared = "Either audience can see the same thing become true."
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-913-feat-interchangeable-methods",
        delivers=[
            _twin_slice("operator", shared, proof=_WALK_PROOF),
            _twin_slice("agent", shared, proof=_NAMED_TEST_PROOF),
        ],
        features=[_feature("F001")],
    )
    assert cli._plan_lock_main([str(plan_dir)]) == 0, "the fixture did not lock"
    before = _obligations(plan_dir)
    assert [(o.locked, o.method, o.drift) for o in before] == [
        (True, "walk", None),
        (True, "named_test", None),
    ], _shape(before)

    _rewrite_contract(
        plan_dir,
        delivers=[
            _twin_slice("agent", shared, proof=_NAMED_TEST_PROOF),
            _twin_slice("operator", shared, proof=_WALK_PROOF),
        ],
    )
    assert _obligations(plan_dir) == before, _shape(_obligations(plan_dir))
    print("  ✓ equal capabilities reorder to nothing whatever the methods are")


def test_two_slices_identical_in_identity_and_capability_are_interchangeable(
    tmp_path: Path,
) -> None:
    """AC6. Same proving features, same capability: the contract carries
    nothing that distinguishes these slices, so which record pairs with which
    live slice is not a question with an answer. Every pairing yields the same
    obligations and the same (absent) drift, so a reorder is a no-op by
    construction — and renumbering them is too. (The sibling test above holds
    the same line when the two also differ in method.)"""
    print("\n[test] two_slices_identical_in_identity_and_capability ...")
    shared = "Either audience can see the same thing become true."
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-911-feat-interchangeable-slices",
        delivers=[_twin_slice("operator", shared), _twin_slice("agent", shared)],
        features=[_feature("F001")],
    )
    assert cli._plan_lock_main([str(plan_dir)]) == 0, "the fixture did not lock"
    before = _obligations(plan_dir)
    assert [(o.locked, o.drift) for o in before] == [(True, None), (True, None)]

    _rewrite_contract(
        plan_dir,
        delivers=[_twin_slice("agent", shared), _twin_slice("operator", shared)],
    )
    assert _obligations(plan_dir) == before, _shape(_obligations(plan_dir))

    # ...and the same holds when only the numbers move (AC3 over this group).
    score = outcome_score.score_plan(plan_dir)
    assert outcome_score.close_obligations(
        plan_dir, _renumbered(score, reverse=True)
    ) == outcome_score.close_obligations(plan_dir, score)
    print("  ✓ interchangeable slices reorder and renumber to nothing")
