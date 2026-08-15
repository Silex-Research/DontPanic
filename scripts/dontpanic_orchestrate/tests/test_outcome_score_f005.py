"""F005 — the lock record is durable, and its loss is reportable.

Plan 2026-08-13-001. Covers the three acceptance criteria:

  1. A plan locked BEFORE the sidecar artifact existed still closes exactly as
     it does today — the live contract is the whole obligation set and no new
     refusal category can reach it. — ``test_ac1_*``
  2. A deleted, corrupt, or altered ``outcome-score.json`` on a plan that WAS
     locked with one is distinguishable from case 1 and behaves differently at
     close: it refuses, naming the receipt, until the loss is acknowledged with
     ``{"kind": "lock_evidence_lost"}`` in decisions.jsonl. The semantics are
     recorded as D013. — ``test_ac2_*``
  3. Lock never exits zero while reporting that gaps were not recorded: the
     score AND its receipt are persisted before the status flip, and a failure
     of either leaves the plan draft with a nonzero exit. — ``test_ac3_*``

The mechanism under all three is :func:`outcome_score.read_lock_evidence`,
which reads two artifacts that cannot be destroyed by the same act: the
sidecar (whose presence proves a lock wrote one) and the decisions.jsonl
receipt (append-only, outside ``evidence/``, so deleting the sidecar cannot
erase the fact that it existed).

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_outcome_score_f005.py -q
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import cli, completion_gate, outcome_score
from dontpanic_orchestrate.tests.test_outcome_score_f002 import (
    _WALK_PROOF,
    _screenshot_feature,
    _slice,
    _status_of,
    _write_plan,
)


def _sidecar_path(plan_dir: Path) -> Path:
    return (
        plan_dir
        / "evidence"
        / "goal-governance"
        / "pre_impl"
        / outcome_score.OUTCOME_SCORE_ARTIFACT
    )


def _receipts(plan_dir: Path) -> list[dict]:
    return [
        entry
        for entry in outcome_score.read_decision_entries(plan_dir)
        if entry.get("kind") == outcome_score.LOCK_RECEIPT_KIND
    ]


def _provable_plan(tmp_path: Path, plan_id: str, *, status: str = "draft") -> Path:
    """A plan with one operator slice proved by a walk, whose F001 already
    carries the screenshot that pays it.

    Chosen so the plan closes clean: any refusal it later meets is about the
    lock record and nothing else, which is what makes the AC2 comparisons
    readable.
    """
    return _write_plan(
        tmp_path,
        plan_id,
        status=status,
        delivers=[_slice(audience="operator", proof=dict(_WALK_PROOF))],
        features=[_screenshot_feature()],
    )


def _locked_plan(tmp_path: Path, plan_id: str) -> Path:
    plan_dir = _provable_plan(tmp_path, plan_id)
    assert cli._plan_lock_main([str(plan_dir)]) == 0, "the fixture did not lock"
    assert _sidecar_path(plan_dir).is_file()
    return plan_dir


# ───────────────────────────  acceptance 1  ───────────────────────────


def test_ac1_a_plan_locked_before_the_sidecar_is_a_legacy_absence(
    tmp_path: Path,
) -> None:
    """AC1 — no sidecar and no receipt is the ONE state that means
    grandfathered, and it reads as such."""
    print("\n[test] ac1_plan_locked_before_the_sidecar_is_a_legacy_absence ...")
    plan_dir = _provable_plan(tmp_path, "2026-08-13-950-feat-f005-legacy", status="active")
    evidence = outcome_score.read_lock_evidence(plan_dir)
    assert evidence.state == outcome_score.LOCK_EVIDENCE_LEGACY
    assert evidence.payload is None and evidence.receipt is None
    assert evidence.detail is None and not evidence.is_destroyed
    assert outcome_score.lock_evidence_defect(plan_dir) is None
    print("  ✓ legacy absence carries no defect")


def test_ac1_a_legacy_plan_closes_against_the_live_contract(tmp_path: Path) -> None:
    """AC1 — the obligation set is the live one, and a clean plan closes."""
    print("\n[test] ac1_legacy_plan_closes_against_the_live_contract ...")
    plan_dir = _provable_plan(tmp_path, "2026-08-13-951-feat-f005-legacy-close", status="active")
    score = outcome_score.score_plan(plan_dir)
    obligations = outcome_score.close_obligations(plan_dir, score)
    assert [(o.index, o.locked, o.drift) for o in obligations] == [(1, False, None)]
    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    print("  ✓ live contract only, no refusal")


def test_ac1_a_legacy_plan_with_an_unrun_proof_refuses_for_the_old_reason(
    tmp_path: Path,
) -> None:
    """AC1 — no NEW refusal category reaches a grandfathered plan. The one it
    can still meet is the pre-existing 'proof never ran', not a word about
    lock evidence."""
    print("\n[test] ac1_legacy_plan_with_unrun_proof_refuses_for_the_old_reason ...")
    plan_dir = _write_plan(
        tmp_path,
        "2026-08-13-952-feat-f005-legacy-unrun",
        status="active",
        delivers=[_slice(audience="operator", proof=dict(_WALK_PROOF))],
    )
    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert len(reasons) == 1
    assert "never ran" in reasons[0]
    assert "lock evidence" not in reasons[0]
    print("  ✓ the only refusal is the one that predates this feature")


# ───────────────────────────  acceptance 2  ───────────────────────────


def test_ac2_a_deleted_sidecar_is_distinguishable_from_a_legacy_plan(
    tmp_path: Path,
) -> None:
    """AC2 — the receipt outlives the artifact, so a deletion reads as a
    deletion."""
    print("\n[test] ac2_deleted_sidecar_is_distinguishable_from_a_legacy_plan ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-953-feat-f005-deleted")
    receipt = _receipts(plan_dir)[-1]
    _sidecar_path(plan_dir).unlink()

    evidence = outcome_score.read_lock_evidence(plan_dir)
    assert evidence.state == outcome_score.LOCK_EVIDENCE_MISSING
    assert evidence.is_destroyed
    assert evidence.receipt is not None and evidence.receipt["id"] == receipt["id"]
    assert evidence.detail and receipt["id"] in evidence.detail
    print(f"  ✓ {evidence.state}, receipted by {receipt['id']}")


def test_ac2_legacy_and_deleted_behave_differently_at_close(tmp_path: Path) -> None:
    """AC2 — the heart of the criterion: two plans with the SAME live contract
    and the same (paid) live proof, differing only in whether a lock record
    once existed, get different answers from close."""
    print("\n[test] ac2_legacy_and_deleted_behave_differently_at_close ...")
    legacy = _provable_plan(tmp_path, "2026-08-13-954-feat-f005-cmp-legacy", status="active")
    deleted = _locked_plan(tmp_path, "2026-08-13-955-feat-f005-cmp-deleted")
    _sidecar_path(deleted).unlink()

    assert outcome_score.evaluate_close_proofs(legacy) == []
    reasons = outcome_score.evaluate_close_proofs(deleted)
    assert len(reasons) == 1, reasons
    assert "lock evidence (missing)" in reasons[0]
    assert outcome_score.OUTCOME_SCORE_ARTIFACT in reasons[0]
    print("  ✓ same contract, same live proof, opposite close verdicts")


def test_ac2_close_refuses_naming_the_lost_lock_record(tmp_path: Path) -> None:
    """AC2 — the refusal reaches the real close command, not just the scorer."""
    print("\n[test] ac2_close_refuses_naming_the_lost_lock_record ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-956-feat-f005-close-refuses")
    _sidecar_path(plan_dir).unlink()
    with pytest.raises(completion_gate.CompletionGateError) as excinfo:
        completion_gate.close_plan(plan_dir, dry_run=True)
    assert "lock evidence" in str(excinfo.value)
    assert _status_of(plan_dir) == "active", "close must not flip a refused plan"
    print("  ✓ plan close refuses and the status is untouched")


@pytest.mark.parametrize(
    ("payload", "expected_state"),
    [
        ("{ this is not json", outcome_score.LOCK_EVIDENCE_CORRUPT),
        ("[]", outcome_score.LOCK_EVIDENCE_CORRUPT),
        ('{"schema_version": 1, "slice_scores": []}', outcome_score.LOCK_EVIDENCE_ALTERED),
    ],
    ids=["unparseable", "not-an-object", "rewritten"],
)
def test_ac2_a_damaged_sidecar_is_reported_not_silently_ignored(
    tmp_path: Path, payload: str, expected_state: str
) -> None:
    """AC2 — the three ways a present file stops being the locked record.

    ``rewritten`` is the quiet one: valid JSON with the obligations edited out.
    It reads as ``altered`` because the receipt names the sha256 of what lock
    actually wrote.
    """
    print(f"\n[test] ac2_damaged_sidecar_reported ({expected_state}) ...")
    plan_dir = _locked_plan(tmp_path, f"2026-08-13-957-feat-f005-{expected_state}")
    _sidecar_path(plan_dir).write_text(payload, encoding="utf-8")

    evidence = outcome_score.read_lock_evidence(plan_dir)
    assert evidence.state == expected_state
    assert evidence.payload is None, "a damaged record must never be read as obligations"
    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert any(f"lock evidence ({expected_state})" in r for r in reasons), reasons
    print(f"  ✓ {expected_state} refuses close")


def test_ac2_a_corrupt_sidecar_needs_no_receipt_to_be_reported(tmp_path: Path) -> None:
    """AC2 — a plan locked before the receipt existed still reports a corrupt
    record: the file's own presence proves a lock wrote one."""
    print("\n[test] ac2_corrupt_sidecar_needs_no_receipt ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-958-feat-f005-corrupt-noreceipt")
    (plan_dir / "decisions.jsonl").write_text("", encoding="utf-8")  # pre-receipt plan
    _sidecar_path(plan_dir).write_text("not json at all", encoding="utf-8")

    evidence = outcome_score.read_lock_evidence(plan_dir)
    assert evidence.state == outcome_score.LOCK_EVIDENCE_CORRUPT
    assert evidence.receipt is None
    assert outcome_score.lock_evidence_defect(plan_dir) is not None
    print("  ✓ corruption is legible without a receipt")


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        '{"hello": "world"}',
        '{"schema_version": 1, "plan_id": "p"}',
        '{"schema_version": "1", "plan_id": "p", "slice_scores": []}',
        '{"schema_version": 1, "plan_id": "", "slice_scores": []}',
        '{"schema_version": 1, "plan_id": "p", "slice_scores": {"1": {}}}',
        '{"schema_version": 1, "plan_id": "p", "slice_scores": ["F001"]}',
    ],
    ids=["empty", "unrelated", "no-slices-key", "version-not-int", "no-plan-id",
         "slices-not-a-list", "slices-not-objects"],
)
def test_ac2_a_receiptless_sidecar_that_is_not_a_score_is_corrupt(
    tmp_path: Path, payload: str
) -> None:
    """AC2 (audit i0, finding 2) — valid-JSON corruption of a PRE-RECEIPT
    sidecar is distinguishable from a legacy absence.

    Before this, any receiptless JSON object read as ``intact`` and close held
    the plan to whatever obligations it could find there — none — while
    reporting the record healthy. The file's own presence proves a lock wrote
    one, so a file that no longer says what lock recorded is destroyed
    evidence, receipt or no receipt.
    """
    print("\n[test] ac2_receiptless_sidecar_that_is_not_a_score_is_corrupt ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-966-feat-f005-shape")
    (plan_dir / "decisions.jsonl").write_text("", encoding="utf-8")  # pre-receipt plan
    _sidecar_path(plan_dir).write_text(payload, encoding="utf-8")

    evidence = outcome_score.read_lock_evidence(plan_dir)
    assert evidence.state == outcome_score.LOCK_EVIDENCE_CORRUPT, payload
    assert evidence.payload is None and evidence.receipt is None
    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert any("lock evidence (corrupt)" in r for r in reasons), reasons
    print(f"  ✓ {payload[:40]!r} → corrupt, not intact")


@pytest.mark.parametrize(
    ("mutate", "expected_fragment"),
    [
        (lambda p: p.__setitem__("plan_id", "2026-08-13-999-some-other-plan"), "not this plan"),
        (lambda p: p.__setitem__("slice_scores", [{}]), "no integer 'index'"),
        (
            lambda p: p.__setitem__("slice_scores", [{"index": "1", "capability": "x"}]),
            "no integer 'index'",
        ),
        (
            lambda p: p.__setitem__(
                "slice_scores", [dict(p["slice_scores"][0]), dict(p["slice_scores"][0])]
            ),
            "twice",
        ),
        (
            lambda p: p["slice_scores"][0].__setitem__("proof_refs", "F001"),
            "not a list of feature ids",
        ),
        (
            lambda p: p["slice_scores"][0].__setitem__("proof_refs", [{"id": "F001"}]),
            "not a list of feature ids",
        ),
        (
            lambda p: p["slice_scores"][0].__setitem__("capability", {"text": "x"}),
            "non-string 'capability'",
        ),
        (
            lambda p: p["slice_scores"][0].__setitem__("method_checked_at_close", ["walk"]),
            "non-string 'method_checked_at_close'",
        ),
    ],
    ids=[
        "another-plans-score",
        "slice-without-index",
        "slice-index-not-int",
        "duplicate-slice-index",
        "proof-refs-not-a-list",
        "proof-refs-not-strings",
        "capability-not-a-string",
        "method-not-a-string",
    ],
)
def test_ac2_receiptless_structurally_plausible_corruption_is_corrupt(
    tmp_path: Path, mutate, expected_fragment: str
) -> None:
    """AC2 (audit i1, finding 1) — corruption that keeps the sidecar's SHAPE is
    still corruption.

    Every case here parsed as JSON, carried all three required top-level keys,
    and read as ``intact`` before this: another plan's score copied over the
    path, and slice records the close-time readers silently discard. Discarding
    a record discards the obligation it carried, so the plan closed against the
    mutable live contract while the lock record reported healthy — the exact
    failure F005 exists to remove.
    """
    print(f"\n[test] ac2_receiptless_structurally_plausible_corruption ({expected_fragment}) ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-973-feat-f005-plausible")
    payload = json.loads(_sidecar_path(plan_dir).read_text(encoding="utf-8"))
    assert payload["slice_scores"], "the fixture must lock at least one slice"
    (plan_dir / "decisions.jsonl").write_text("", encoding="utf-8")  # pre-receipt plan
    mutate(payload)
    _sidecar_path(plan_dir).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    defect = outcome_score.score_payload_defect(payload, plan_ids={plan_dir.name})
    assert defect is not None and expected_fragment in defect, defect

    evidence = outcome_score.read_lock_evidence(plan_dir)
    assert evidence.state == outcome_score.LOCK_EVIDENCE_CORRUPT
    assert evidence.payload is None, "damaged obligations must never be read as obligations"
    assert outcome_score.backfill_lock_receipt(plan_dir) is None, "damage must not be receipted"
    reasons = outcome_score.evaluate_close_proofs(plan_dir)
    assert any("lock evidence (corrupt)" in r for r in reasons), reasons
    print(f"  ✓ {expected_fragment} → corrupt, not intact")


def test_ac2_an_intact_sidecar_survives_the_tightened_checks(tmp_path: Path) -> None:
    """AC2 (audit i1, finding 1) — the other half of the claim: what lock
    actually writes passes every new check, so the tightening refuses no real
    record. A pre-``proof_refs`` sidecar passes too — an ABSENT key is an older
    writer, not damage, and only a present-and-malformed one is corruption."""
    print("\n[test] ac2_intact_sidecar_survives_the_tightened_checks ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-974-feat-f005-still-intact")
    payload = json.loads(_sidecar_path(plan_dir).read_text(encoding="utf-8"))
    assert outcome_score.score_payload_defect(payload, plan_ids={plan_dir.name}) is None
    assert outcome_score.read_lock_evidence(plan_dir).state == outcome_score.LOCK_EVIDENCE_INTACT

    for record in payload["slice_scores"]:
        record.pop("proof_refs", None)
    assert outcome_score.score_payload_defect(payload, plan_ids={plan_dir.name}) is None
    print("  ✓ real records — with and without proof_refs — still read intact")


def test_ac2_a_receipted_sidecar_survives_a_plan_rename(tmp_path: Path) -> None:
    """AC2 (audit i1, finding 1) — the identity check is scoped to records whose
    bytes are NOT vouched for.

    A receipt naming the sha256 on disk proves the file IS what lock wrote, so a
    ``plan_id`` that no longer matches the directory is a rename and not a
    corruption. Refusing it would manufacture the loss report AC1 forbids.
    """
    print("\n[test] ac2_receipted_sidecar_survives_a_plan_rename ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-975-feat-f005-renamed")
    plan_md = plan_dir / "plan.md"
    plan_md.write_text(
        plan_md.read_text(encoding="utf-8").replace(
            f"id: {plan_dir.name}", "id: 2026-08-13-975-feat-f005-renamed-v2"
        ),
        encoding="utf-8",
    )
    assert outcome_score.read_lock_evidence(plan_dir).state == outcome_score.LOCK_EVIDENCE_INTACT
    print("  ✓ receipted bytes are not re-litigated on identity")


def test_ac2_backfill_makes_a_pre_receipt_deletion_reportable(tmp_path: Path) -> None:
    """AC2 (audit i0, finding 2) — the migration. A plan locked before receipts
    existed gets one at first write-capable contact, and from then on its
    record's deletion reads as a deletion rather than as a legacy absence."""
    print("\n[test] ac2_backfill_makes_a_pre_receipt_deletion_reportable ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-967-feat-f005-backfill")
    (plan_dir / "decisions.jsonl").write_text("", encoding="utf-8")  # pre-receipt plan
    on_disk = hashlib.sha256(_sidecar_path(plan_dir).read_bytes()).hexdigest()

    receipt = outcome_score.backfill_lock_receipt(plan_dir)
    assert receipt is not None
    assert receipt["backfilled"] is True
    assert receipt["sha256"] == on_disk
    assert outcome_score.read_lock_evidence(plan_dir).state == (
        outcome_score.LOCK_EVIDENCE_INTACT
    )

    _sidecar_path(plan_dir).unlink()
    evidence = outcome_score.read_lock_evidence(plan_dir)
    assert evidence.state == outcome_score.LOCK_EVIDENCE_MISSING
    assert evidence.detail and receipt["id"] in evidence.detail
    print(f"  ✓ backfilled {receipt['id']}, deletion now reports missing")


def test_ac2_backfill_is_idempotent_and_never_invents_a_record(
    tmp_path: Path,
) -> None:
    """AC2 (audit i0, finding 2) — the three no-ops. The migration must never
    claim more than the disk shows: it re-receipts nothing, receipts no absent
    file (which would manufacture the loss report AC1 forbids), and freezes no
    corruption in as if it were what lock wrote."""
    print("\n[test] ac2_backfill_is_idempotent_and_never_invents_a_record ...")
    already = _locked_plan(tmp_path, "2026-08-13-968-feat-f005-bf-receipted")
    assert outcome_score.backfill_lock_receipt(already) is None
    assert len(_receipts(already)) == 1

    legacy = _provable_plan(tmp_path, "2026-08-13-969-feat-f005-bf-legacy", status="active")
    assert outcome_score.backfill_lock_receipt(legacy) is None
    assert _receipts(legacy) == []
    assert outcome_score.read_lock_evidence(legacy).state == (
        outcome_score.LOCK_EVIDENCE_LEGACY
    )

    damaged = _locked_plan(tmp_path, "2026-08-13-970-feat-f005-bf-corrupt")
    (damaged / "decisions.jsonl").write_text("", encoding="utf-8")
    _sidecar_path(damaged).write_text('{"schema_version": 1}', encoding="utf-8")
    assert outcome_score.backfill_lock_receipt(damaged) is None
    assert _receipts(damaged) == []
    assert outcome_score.read_lock_evidence(damaged).state == (
        outcome_score.LOCK_EVIDENCE_CORRUPT
    )
    print("  ✓ receipted / absent / corrupt all left alone")


def test_ac2_close_backfills_the_receipt_it_reads(tmp_path: Path) -> None:
    """AC2 (audit i0, finding 2) — the migration is WIRED, not just available:
    a real close of a pre-receipt plan leaves the receipt behind. ``--dry-run``
    does not, because close_plan promises to be read-only there."""
    print("\n[test] ac2_close_backfills_the_receipt_it_reads ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-971-feat-f005-close-backfill")
    (plan_dir / "decisions.jsonl").write_text("", encoding="utf-8")

    completion_gate.close_plan(plan_dir, dry_run=True)
    assert _receipts(plan_dir) == [], "a dry run must not write to the ledger"

    completion_gate.close_plan(plan_dir)
    receipts = _receipts(plan_dir)
    assert len(receipts) == 1 and receipts[0]["backfilled"] is True
    print(f"  ✓ close backfilled {receipts[0]['id']}")


def test_ac2_a_receiptless_readable_sidecar_is_intact(tmp_path: Path) -> None:
    """AC2 — and the same plan with an untouched sidecar is INTACT, so plans
    locked between the sidecar landing and the receipt landing are not
    retroactively broken."""
    print("\n[test] ac2_receiptless_readable_sidecar_is_intact ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-959-feat-f005-intact-noreceipt")
    (plan_dir / "decisions.jsonl").write_text("", encoding="utf-8")

    evidence = outcome_score.read_lock_evidence(plan_dir)
    assert evidence.state == outcome_score.LOCK_EVIDENCE_INTACT
    assert evidence.payload is not None
    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    print("  ✓ no receipt is not the same as no record")


def test_ac2_an_acknowledged_loss_closes_against_the_live_contract(
    tmp_path: Path,
) -> None:
    """AC2 — the escape. ``lock_evidence_lost`` is the one way the recorded
    proofs stop being owed, and it leaves a written trace of who decided."""
    print("\n[test] ac2_acknowledged_loss_closes_against_the_live_contract ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-960-feat-f005-acknowledged")
    _sidecar_path(plan_dir).unlink()
    assert outcome_score.evaluate_close_proofs(plan_dir)  # refuses first

    with (plan_dir / "decisions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "id": "D999",
                    "kind": "lock_evidence_lost",
                    "reason": "the evidence dir was wiped by a bad rebase; re-lock is worse",
                }
            )
            + "\n"
        )

    assert outcome_score.lock_evidence_defect(plan_dir) is None
    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    obligations = outcome_score.close_obligations(
        plan_dir, outcome_score.score_plan(plan_dir)
    )
    assert [(o.index, o.locked) for o in obligations] == [(1, False)]
    print("  ✓ acknowledged loss falls back to the live contract")


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "D998", "kind": "lock_evidence_lost"},
        {"id": "D998", "kind": "lock_evidence_lost", "reason": ""},
        {"id": "D998", "kind": "lock_evidence_lost", "reason": "   "},
        {"id": "D998", "kind": "lock_evidence_lost", "reason": None},
        {"id": "D998", "kind": "lock_evidence_lost", "reason": 42},
    ],
    ids=["no-reason", "empty-reason", "blank-reason", "null-reason", "non-string-reason"],
)
def test_ac2_a_loss_acknowledgement_without_a_reason_waives_nothing(
    tmp_path: Path, entry: dict
) -> None:
    """AC2 (audit i1, finding 2) — the escape hatch has a required field.

    ``lock_evidence_lost`` is the one entry that retires proofs a lock recorded.
    The generic gap matcher checks only ``kind`` and target, so a bare
    ``{"kind": "lock_evidence_lost"}`` used to waive destroyed evidence while
    telling a later reader nothing about why. The refusal now names the entry,
    so the operator fixes it instead of wondering why theirs had no effect.
    """
    print(f"\n[test] ac2_loss_acknowledgement_without_a_reason ({entry.get('reason')!r}) ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-976-feat-f005-reasonless")
    _sidecar_path(plan_dir).unlink()
    with (plan_dir / "decisions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")

    assert outcome_score.loss_acknowledgement_defect(entry) is not None
    defect = outcome_score.lock_evidence_defect(plan_dir)
    assert defect is not None, "a reasonless acknowledgement must not waive the loss"
    assert "D998" in defect and "states no 'reason'" in defect
    with pytest.raises(completion_gate.CompletionGateError):
        completion_gate.close_plan(plan_dir, dry_run=True)
    assert _status_of(plan_dir) == "active"
    print("  ✓ still refused, and the refusal names the deficient entry")


def test_ac2_a_reasoned_acknowledgement_still_waives_the_loss(tmp_path: Path) -> None:
    """AC2 (audit i1, finding 2) — and one that states a reason still works,
    even alongside a reasonless one: the check is 'at least one real
    acknowledgement', not 'no bad entries anywhere in the ledger'."""
    print("\n[test] ac2_reasoned_acknowledgement_still_waives_the_loss ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-977-feat-f005-reasoned")
    _sidecar_path(plan_dir).unlink()
    with (plan_dir / "decisions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": "D998", "kind": "lock_evidence_lost"}) + "\n")
        handle.write(
            json.dumps(
                {
                    "id": "D999",
                    "kind": "lock_evidence_lost",
                    "reason": "evidence/ was wiped by a bad rebase; re-locking is worse",
                }
            )
            + "\n"
        )

    assert outcome_score.lock_evidence_defect(plan_dir) is None
    assert outcome_score.evaluate_close_proofs(plan_dir) == []
    print("  ✓ one reasoned entry is enough")


def test_ac2_the_chosen_semantics_are_recorded_in_decisions_jsonl() -> None:
    """AC2 — the decision itself is on the record, in the plan's own ledger."""
    print("\n[test] ac2_chosen_semantics_recorded_in_decisions_jsonl ...")
    plan_dir = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "plans"
        / "2026-08-13-001-feat-lock-outcome-slices-proof"
    )
    entries = outcome_score.read_decision_entries(plan_dir)
    d013 = [e for e in entries if e.get("id") == "D013"]
    assert d013, "D013 (grandfathered vs destroyed lock evidence) is not recorded"
    answer = str(d013[0].get("answer", ""))
    assert "lock_evidence_lost" in answer
    assert outcome_score.LOCK_RECEIPT_KIND in answer

    # D014 records what D013 left open: the pre-receipt migration, the
    # structural check, the one residual case, and the AC3 refusal.
    d014 = [e for e in entries if e.get("id") == "D014"]
    assert d014, "D014 (backfill + AC3 refusal semantics) is not recorded"
    text = str(d014[0].get("answer", "")) + str(d014[0].get("rationale", ""))
    assert "backfill_lock_receipt" in text
    assert "score_payload_defect" in text
    assert "draft" in text

    # D015 records what the i1 audit found D014's structural check still let
    # through: shape-preserving corruption, and a reasonless loss waiver.
    d015 = [e for e in entries if e.get("id") == "D015"]
    assert d015, "D015 (plausible-corruption + loss-reason semantics) is not recorded"
    text = str(d015[0].get("answer", "")) + str(d015[0].get("rationale", ""))
    assert "plan_id" in text
    assert "index" in text
    assert "reason" in text
    print("  ✓ D013 + D014 + D015 state the semantics")


# ───────────────────────────  acceptance 3  ───────────────────────────


def test_ac3_a_successful_lock_has_persisted_both_score_and_receipt(
    tmp_path: Path, capsys
) -> None:
    """AC3 — exit zero implies the gaps ARE recorded, both artifacts."""
    print("\n[test] ac3_successful_lock_persisted_score_and_receipt ...")
    plan_dir = _provable_plan(tmp_path, "2026-08-13-961-feat-f005-lock-records")
    rc = cli._plan_lock_main([str(plan_dir)])
    captured = capsys.readouterr()
    assert rc == 0
    assert _status_of(plan_dir) == "active"
    assert _sidecar_path(plan_dir).is_file()
    receipts = _receipts(plan_dir)
    assert len(receipts) == 1
    on_disk = hashlib.sha256(_sidecar_path(plan_dir).read_bytes()).hexdigest()
    assert receipts[0]["sha256"] == on_disk
    assert "not recorded" not in (captured.out + captured.err).lower()
    print(f"  ✓ rc=0 with sidecar + receipt {receipts[0]['id']}")


def test_ac3_a_sidecar_write_failure_leaves_the_plan_draft(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """AC3 — the write-failure proof. Nonzero exit, status draft, and no
    receipt claiming a record that was never written."""
    print("\n[test] ac3_sidecar_write_failure_leaves_the_plan_draft ...")
    plan_dir = _provable_plan(tmp_path, "2026-08-13-962-feat-f005-write-fails")

    def _boom(_plan_dir, _score):
        raise OSError("read-only file system")

    monkeypatch.setattr(outcome_score, "write_score_sidecar", _boom)
    rc = cli._plan_lock_main([str(plan_dir)])
    err = capsys.readouterr().err
    assert rc != 0
    assert _status_of(plan_dir) == "draft"
    assert not _sidecar_path(plan_dir).exists()
    assert _receipts(plan_dir) == []
    assert "REFUSED" in err and "could not record" in err
    print("  ✓ no flip, no receipt, nonzero exit")


def test_ac3_a_receipt_write_failure_also_leaves_the_plan_draft(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """AC3 — the receipt is not best-effort. A lock that cannot leave a trace
    of what it recorded is a lock whose record can later vanish unnoticed, so
    it fails the same way the sidecar write does."""
    print("\n[test] ac3_receipt_write_failure_also_leaves_the_plan_draft ...")
    plan_dir = _provable_plan(tmp_path, "2026-08-13-963-feat-f005-receipt-fails")

    def _boom(_plan_dir, **_kwargs):
        raise OSError("decisions.jsonl is not writable")

    monkeypatch.setattr(outcome_score, "append_lock_receipt", _boom)
    rc = cli._plan_lock_main([str(plan_dir)])
    err = capsys.readouterr().err
    assert rc != 0
    assert _status_of(plan_dir) == "draft"
    assert "REFUSED" in err
    print("  ✓ an unreceiptable lock is a refused lock")


def test_ac3_a_scoring_failure_refuses_the_lock(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """AC3 (audit i0, finding 1) — the invariant is about what exit zero MEANS,
    so a lock that could not score the plan cannot report success either.

    This used to print "lock proceeds unrecorded" and return 0, flipping the
    plan active with no record of the gaps close would later be held to —
    literally the shape AC3 forbids. Draft is the recoverable state (D014).
    """
    print("\n[test] ac3_scoring_failure_refuses_the_lock ...")
    plan_dir = _provable_plan(tmp_path, "2026-08-13-972-feat-f005-score-fails")

    def _boom(_plan_dir):
        raise RuntimeError("the contract reader blew up")

    monkeypatch.setattr(outcome_score, "score_plan", _boom)
    rc = cli._plan_lock_main([str(plan_dir)])
    captured = capsys.readouterr()
    assert rc != 0
    assert _status_of(plan_dir) == "draft"
    assert not _sidecar_path(plan_dir).exists()
    assert _receipts(plan_dir) == []
    assert "REFUSED" in captured.err
    assert "could not score" in captured.err
    print("  ✓ unscorable plan stays draft with a nonzero exit")


def test_ac3_no_lock_reports_success_while_reporting_unrecorded_gaps(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """AC3 (audit i0, finding 1) — stated as the invariant itself, over every
    failure the recording step can meet: score, sidecar, receipt. In no case
    may rc be 0 while the output says the gaps were not recorded."""
    print("\n[test] ac3_no_lock_reports_success_while_reporting_unrecorded_gaps ...")

    def _raise_os(*_args, **_kwargs):
        raise OSError("read-only file system")

    def _raise_runtime(*_args, **_kwargs):
        raise RuntimeError("scorer blew up")

    for n, (attr, boom) in enumerate(
        (
            ("score_plan", _raise_runtime),
            ("write_score_sidecar", _raise_os),
            ("append_lock_receipt", _raise_os),
        )
    ):
        plan_dir = _provable_plan(tmp_path, f"2026-08-13-97{n}-feat-f005-inv-{attr}")
        with monkeypatch.context() as patch:
            patch.setattr(outcome_score, attr, boom)
            rc = cli._plan_lock_main([str(plan_dir)])
        out = capsys.readouterr()
        recorded = _sidecar_path(plan_dir).is_file() and bool(_receipts(plan_dir))
        assert not recorded, f"{attr}: the record must not survive its own failure"
        assert rc != 0, f"{attr}: exit zero with nothing recorded"
        assert _status_of(plan_dir) == "draft", f"{attr}: flipped without a record"
        assert "REFUSED" in out.err, f"{attr}: refusal not reported"
        print(f"  ✓ {attr} failure → rc={rc}, still draft")


def test_ac3_both_artifacts_land_before_the_status_flip(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """AC3 — ordering, proven by refusing the flip itself: the record is
    already on disk when the flip is attempted, never after."""
    print("\n[test] ac3_both_artifacts_land_before_the_status_flip ...")
    plan_dir = _provable_plan(tmp_path, "2026-08-13-964-feat-f005-ordering")
    seen: dict[str, bool] = {}

    def _refuse(target_dir, **_kwargs):
        seen["sidecar"] = _sidecar_path(Path(target_dir)).is_file()
        seen["receipt"] = bool(_receipts(Path(target_dir)))
        raise cli.sufficiency_gate.SufficiencyGateError("synthetic gate refusal")

    monkeypatch.setattr(cli.sufficiency_gate, "lock_plan", _refuse)
    rc = cli._plan_lock_main([str(plan_dir)])
    capsys.readouterr()
    assert rc == 3
    assert _status_of(plan_dir) == "draft"
    assert seen == {"sidecar": True, "receipt": True}
    print("  ✓ score + receipt precede the flip")


def test_ac3_relocking_an_unchanged_plan_does_not_duplicate_the_receipt(
    tmp_path: Path,
) -> None:
    """AC3 housekeeping — the ledger records lock events, not lock attempts,
    so a re-lock of an unchanged score appends nothing."""
    print("\n[test] ac3_relocking_unchanged_plan_does_not_duplicate_receipt ...")
    plan_dir = _locked_plan(tmp_path, "2026-08-13-965-feat-f005-relock")
    assert len(_receipts(plan_dir)) == 1

    plan_md = plan_dir / "plan.md"
    plan_md.write_text(
        plan_md.read_text(encoding="utf-8").replace("status: active", "status: draft"),
        encoding="utf-8",
    )
    assert cli._plan_lock_main([str(plan_dir)]) == 0
    assert len(_receipts(plan_dir)) == 1
    assert outcome_score.read_lock_evidence(plan_dir).state == (
        outcome_score.LOCK_EVIDENCE_INTACT
    )
    print("  ✓ one receipt after two locks of the same score")
