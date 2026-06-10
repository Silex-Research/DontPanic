"""Plan 2026-06-09-002 F004 — dogfood against the real round history.

Replays the six committed C0 sufficiency rounds (plan 2026-06-09-001) and
the meta-plan's own three rounds as OFFLINE fixtures: ledger reconstruction,
full-clearance detection at every boundary, per-round policy verdicts, the
round-6 eligibility split, and the un-annotated conservative-fallback
companion. Zero live auditor invocations — enforced by an autouse guard.

The fixture corpus carries explicit RETROSPECTIVE class annotations
(operator-reviewed metadata, clearly marked, never auditor-emitted): the
historical evidence predates the finding_class field.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import sufficiency_auditor as _sa  # noqa: E402
from dontpanic_orchestrate.sufficiency_convergence import (  # noqa: E402
    VERDICT_BLOCK,
    VERDICT_DISPOSITION_REQUIRED,
    VERDICT_PLAIN_GATE,
    build_round_record,
    convergence_verdict,
    full_clearance,
    verdict_for,
)

FIXTURE = HERE.parent / "fixtures" / "convergence_rounds" / "real_rounds.json"


@pytest.fixture(autouse=True)
def _no_paid_calls(monkeypatch):
    """The whole suite is offline — any auditor invocation fails loudly."""

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("live auditor invoked from the fixture suite")

    monkeypatch.setattr(_sa, "run_sufficiency_audit", _boom)
    monkeypatch.setattr(_sa, "_production_sufficiency_dispatch", _boom, raising=False)


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def _ledger_from(rounds: list[dict], *, annotated: bool) -> list[dict]:
    """Reconstruct a rounds ledger from the raw fixture rounds. With
    ``annotated`` the retrospective classes apply; without, every finding
    goes through the conservative fallback (no class field at all)."""
    ledger: list[dict] = []
    prior = None
    for i, rnd in enumerate(rounds, start=1):
        findings = []
        for f in rnd["findings"]:
            item = {k: v for k, v in f.items() if k != "retrospective_class"}
            if annotated and f.get("retrospective_class"):
                item["finding_class"] = f["retrospective_class"]
            else:
                item.pop("finding_class", None)
            findings.append(item)
        record = build_round_record(
            findings,
            prior=prior,
            input_fingerprint=rnd["input_fingerprint"],
            round_number=i,
            generated_at=rnd["generated_at"],
        )
        ledger.append(record)
        prior = record
    return ledger


# ──────────────────────────────  C0: six real rounds  ──────────────────────────────


def test_c0_round_counts_match_history():
    rounds = _load()["c0_rounds"]
    assert [len(r["findings"]) for r in rounds] == [4, 2, 4, 4, 4, 5]


def test_c0_full_clearance_at_every_boundary():
    ledger = _ledger_from(_load()["c0_rounds"], annotated=True)
    for record in ledger[1:]:
        assert full_clearance(record), (
            f"round {record['round']} did not fully clear its predecessor — "
            "but the C0 history cleared 100% every round"
        )


def test_c0_per_round_policy_verdicts():
    rounds = _load()["c0_rounds"]
    ledger = _ledger_from(rounds, annotated=True)
    # Round 1: no prior history -> plain gate.
    assert convergence_verdict(ledger[:1], {}).verdict == VERDICT_PLAIN_GATE
    for upto in range(2, len(ledger) + 1):
        v = convergence_verdict(ledger[:upto], {})
        current = ledger[upto - 1]
        has_high = any(f["severity"] in ("high", "critical") for f in current["findings"])
        has_contract = any(f["finding_class"] == "plan_contract" for f in current["findings"])
        if has_high or has_contract:
            assert v.verdict == VERDICT_BLOCK, f"round {upto} must block"
        else:
            assert v.verdict == VERDICT_DISPOSITION_REQUIRED, (
                f"round {upto}: all-eligible pins after full clearance must demand "
                "disposition, not another paid spiral"
            )


def test_c0_round_2_would_have_been_disposition_eligible():
    """Historical insight the policy formalizes: C0 round 2 (two medium
    matrix pins after a 100% clearance) would have required disposition —
    not the paid re-lock that was actually spent."""
    ledger = _ledger_from(_load()["c0_rounds"], annotated=True)
    v = convergence_verdict(ledger[:2], {})
    assert v.verdict == VERDICT_DISPOSITION_REQUIRED
    assert v.branch == "a_full_clearance_pins"


def test_c0_round_6_eligibility_split():
    rounds = _load()["c0_rounds"]
    r6 = rounds[5]
    cells = {
        (f["severity"], f["retrospective_class"]): verdict_for(
            f["severity"], f["retrospective_class"]
        )
        for f in r6["findings"]
    }
    assert cells[("high", "plan_contract")] == "block", "tier-1 language set keeps the block"
    assert cells[("medium", "plan_contract")] == "block_unless_waived"
    # The three medium eligible-class findings: purity parity (matrix_pin),
    # empty-repo wording (editorial), missing C+ scope guard (scope_guard).
    assert cells[("medium", "matrix_pin")] == "disposition_eligible"
    assert cells[("medium", "editorial")] == "disposition_eligible"
    assert cells[("medium", "scope_guard")] == "disposition_eligible"


def test_c0_note_finding_escalation_is_material():
    """The low-confidence-note finding first appeared at LOW severity in
    round 1 and recurred at MEDIUM in round 5 — under the new identity
    model that escalation is always a material change."""
    rounds = _load()["c0_rounds"]
    low = next(f for f in rounds[0]["findings"] if f["severity"] == "low")
    from dontpanic_orchestrate.sufficiency_convergence import finding_fingerprint

    escalated = dict(low, severity="medium")
    assert finding_fingerprint(low) != finding_fingerprint(escalated)


# ──────────────────────────────  companion: conservative fallback  ──────────────────────────────


def test_unannotated_corpus_falls_back_to_plan_contract_and_blocks():
    rounds = _load()["c0_rounds"]
    ledger = _ledger_from(rounds, annotated=False)
    for record in ledger:
        assert all(f["finding_class"] == "plan_contract" for f in record["findings"])
    for upto in range(2, len(ledger) + 1):
        v = convergence_verdict(ledger[:upto], {})
        assert v.verdict == VERDICT_BLOCK, (
            "without classifier data every round must block — the fallback is "
            "never disposition-eligible"
        )


# ──────────────────────────────  meta-plan: three real rounds  ──────────────────────────────


def test_meta_rounds_reconstruct_and_block_on_highs():
    rounds = _load()["meta_rounds"]
    assert [len(r["findings"]) for r in rounds] == [6, 6, 6]
    ledger = _ledger_from(rounds, annotated=False)
    # Round 1: plain gate (no history). Rounds 2-3: full clearance each time,
    # but highs present -> hard block regardless of class.
    assert convergence_verdict(ledger[:1], {}).verdict == VERDICT_PLAIN_GATE
    for upto in (2, 3):
        assert full_clearance(ledger[upto - 1])
        v = convergence_verdict(ledger[:upto], {})
        assert v.verdict == VERDICT_BLOCK
        assert v.branch == "b_high_severity"
