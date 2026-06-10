"""Plan 2026-06-09-002 F003 — per-finding disposition artifact.

Pins: each kind end-to-end, per-class refusal (plan_contract only waivable),
missing-reason/missing-followup refusals, decisions.jsonl mirroring, strict
invalidation on fingerprint change and on cell-set change, and that an
undisposed blocking finding still refuses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.sufficiency_convergence import (  # noqa: E402
    ConvergenceError,
    append_audit_round,
    effective_dispositions,
    latest_round,
    load_dispositions,
    read_ledger,
    record_disposition,
)


def _finding(journey: str, desc: str, severity: str = "medium", cls: str = "matrix_pin"):
    return {
        "severity": severity,
        "journey_id": journey,
        "gap_class": "coverage_gap",
        "description": desc * 10,
        "feature_refs": ["F004"],
        "recommendation": None,
        "finding_class": cls,
    }


@pytest.fixture()
def plan_dir(tmp_path: Path) -> Path:
    d = tmp_path / "plan"
    d.mkdir()
    (d / "decisions.jsonl").write_text("")
    return d


def _seed_round(plan_dir: Path, findings: list[dict], fp: str = "sha256:1") -> dict:
    return append_audit_round(plan_dir, findings, input_fingerprint=fp)


def _only_id(record: dict) -> str:
    return record["findings"][0]["finding_id"]


# ──────────────────────────────  recording + validation  ──────────────────────────────


@pytest.mark.parametrize(
    "kind,kwargs",
    [
        ("accepted_into_plan", {}),
        ("deferred_to_impl", {}),
        ("waived_with_reason", {"reason": "operator judged impl-level"}),
        ("split_to_followup_plan", {"followup_plan": "2026-06-10-001"}),
    ],
)
def test_each_kind_records_and_mirrors(plan_dir: Path, kind: str, kwargs: dict):
    record = _seed_round(plan_dir, [_finding("a", "x")])
    fid = _only_id(record)
    entry = record_disposition(plan_dir, finding_id=fid, kind=kind, **kwargs)
    assert load_dispositions(plan_dir)[fid]["kind"] == kind
    assert entry["fingerprint"] == record["findings"][0]["fingerprint"]
    mirrored = [json.loads(line) for line in (plan_dir / "decisions.jsonl").read_text().splitlines()]
    assert any(m["id"] == f"DSP-{fid}" and kind in m["decision"] for m in mirrored)


def test_waived_requires_reason(plan_dir: Path):
    fid = _only_id(_seed_round(plan_dir, [_finding("a", "x")]))
    with pytest.raises(ConvergenceError, match="reason"):
        record_disposition(plan_dir, finding_id=fid, kind="waived_with_reason", reason="  ")


def test_split_requires_followup_ref(plan_dir: Path):
    fid = _only_id(_seed_round(plan_dir, [_finding("a", "x")]))
    with pytest.raises(ConvergenceError, match="followup"):
        record_disposition(plan_dir, finding_id=fid, kind="split_to_followup_plan")


def test_plan_contract_refuses_deferred_and_split(plan_dir: Path):
    fid = _only_id(_seed_round(plan_dir, [_finding("a", "x", cls="plan_contract")]))
    for kind in ("deferred_to_impl", "split_to_followup_plan"):
        with pytest.raises(ConvergenceError, match="plan_contract"):
            record_disposition(plan_dir, finding_id=fid, kind=kind, followup_plan="2026-06-10-001")
    # waived_with_reason IS permitted for plan_contract.
    record_disposition(
        plan_dir, finding_id=fid, kind="waived_with_reason", reason="operator-approved waiver"
    )


def test_unknown_finding_id_refused(plan_dir: Path):
    _seed_round(plan_dir, [_finding("a", "x")])
    with pytest.raises(ConvergenceError, match="not present"):
        record_disposition(plan_dir, finding_id="f-doesnotexist", kind="deferred_to_impl")


# ──────────────────────────────  strict invalidation  ──────────────────────────────


def test_invalidated_on_fingerprint_change(plan_dir: Path):
    record = _seed_round(plan_dir, [_finding("a", "x")])
    fid = _only_id(record)
    record_disposition(plan_dir, finding_id=fid, kind="deferred_to_impl")
    assert fid in effective_dispositions(plan_dir)
    # Same cell recurs with ESCALATED severity -> same id, new fingerprint.
    _seed_round(plan_dir, [_finding("a", "x", severity="high")], fp="sha256:2")
    assert fid not in effective_dispositions(plan_dir), (
        "a materially changed finding must never hide behind an old waiver"
    )


def test_invalidated_on_cell_set_change(plan_dir: Path):
    record = _seed_round(plan_dir, [_finding("a", "x")])
    fid = _only_id(record)
    record_disposition(plan_dir, finding_id=fid, kind="deferred_to_impl")
    # The same finding persists VERBATIM but a sibling joins its cell.
    _seed_round(plan_dir, [_finding("a", "x"), _finding("a", "y")], fp="sha256:2")
    current = latest_round(read_ledger(plan_dir))
    assert fid in {f["finding_id"] for f in current["findings"]}, "finding persisted"
    assert fid not in effective_dispositions(plan_dir), (
        "any cell-set change invalidates the cell's dispositions (fail-closed)"
    )


def test_valid_disposition_survives_unrelated_round_changes(plan_dir: Path):
    record = _seed_round(plan_dir, [_finding("a", "x"), _finding("b", "y")])
    fid_a = next(f["finding_id"] for f in record["findings"] if f["journey_id"] == "a")
    record_disposition(plan_dir, finding_id=fid_a, kind="deferred_to_impl")
    # journey-b's finding changes; journey-a's cell is untouched.
    _seed_round(plan_dir, [_finding("a", "x"), _finding("b", "z")], fp="sha256:2")
    assert fid_a in effective_dispositions(plan_dir)
