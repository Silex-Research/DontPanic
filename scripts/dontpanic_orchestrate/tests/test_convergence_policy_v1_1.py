"""Plan 2026-06-10-001 — convergence policy v1.1.

F001 — streak-gated eligibility for HIGH matrix_pin findings: clearance_streak
helper, the suppression rule in convergence_verdict, the streak-conditional
verdict_for cell, and the unchanged-v1 invariants (critical never; plan_contract
under the v1 waiver-only rule at any severity; conservative fallback never;
medium/low and legacy override untouched).

F002 — the waived_matrix_pin_high disposition kind: fail-closed validation
(severity, class, streak, confirmation length, literal-placeholder rejection),
no-audit membership, CLI passthrough, and refusal-message naming.

F003 — dual real-corpus dogfood: the C0 live rounds (1-4) and the
worktree-isolation-v0 rounds (1-3), both with auditor-emitted classes, copied
verbatim; eligibility, discrimination, fallback-blocked, the ordered
completion path (the new kind is the FINAL gate), and auditor-prompt scope
guards. Zero live auditor invocations — enforced by the autouse guard.
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
    CONFIRMATION_PLACEHOLDER,
    DISPOSITION_KINDS,
    FINDING_CLASSES,
    MATRIX_PIN_STREAK_THRESHOLD,
    NO_AUDIT_DISPOSITION_KINDS,
    SEVERITIES,
    VERDICT_BLOCK,
    VERDICT_PROCEED,
    WAIVED_MATRIX_PIN_HIGH,
    ConvergenceError,
    clearance_streak,
    convergence_verdict,
    effective_dispositions,
    gate_decision,
    read_ledger,
    record_disposition,
    verdict_for,
)

FIXTURES = HERE.parent / "fixtures" / "convergence_rounds"
C0_LEDGER = FIXTURES / "c0_live_rounds.jsonl"
WORKTREE_LEDGER = FIXTURES / "worktree_v0_rounds.jsonl"


# ── guard: zero auditor invocations anywhere in this module ──────────────


@pytest.fixture(autouse=True)
def _no_live_auditor(monkeypatch):
    def _boom(*args, **kwargs):  # pragma: no cover - tripwire
        raise AssertionError("live auditor invocation attempted in offline fixture test")

    monkeypatch.setattr(_sa, "run_sufficiency_audit", _boom, raising=True)
    yield


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _rounds_prefix(ledger: list[dict], upto: int) -> list[dict]:
    return [r for r in ledger if r.get("type") == "audit_round" and r.get("round") <= upto]


def _plan_dir_with(tmp_path: Path, ledger_records: list[dict]) -> Path:
    plan_dir = tmp_path / "plan"
    evid = plan_dir / "evidence" / "goal-governance" / "pre_impl"
    evid.mkdir(parents=True)
    with (evid / "sufficiency-rounds.jsonl").open("w") as fh:
        for record in ledger_records:
            fh.write(json.dumps(record) + "\n")
    (plan_dir / "decisions.jsonl").write_text("")
    return plan_dir


def _find(round_record: dict, *, severity: str, finding_class: str) -> dict:
    for f in round_record["findings"]:
        if f["severity"] == severity and f["finding_class"] == finding_class:
            return f
    raise AssertionError(f"no {severity}/{finding_class} finding in round {round_record['round']}")


REAL_CONFIRMATION = (
    "Operator-confirmed: this detector-table cell is pinned in code with an "
    "equality test; further enumeration is implementation-level."
)


# ──────────────────────────────  F001: streak helper  ──────────────────────────────


class TestClearanceStreak:
    def test_first_round_never_counts(self):
        ledger = _rounds_prefix(_load(C0_LEDGER), 1)
        assert clearance_streak(ledger) == 0

    def test_c0_worked_example_round2_is_1_round3_is_2(self):
        ledger = _load(C0_LEDGER)
        assert clearance_streak(_rounds_prefix(ledger, 2)) == 1
        assert clearance_streak(_rounds_prefix(ledger, 3)) == 2
        assert clearance_streak(_rounds_prefix(ledger, 4)) == 3

    def test_worktree_round3_is_2(self):
        ledger = _load(WORKTREE_LEDGER)
        assert clearance_streak(_rounds_prefix(ledger, 3)) == 2

    def test_override_events_excluded(self):
        # the verbatim C0 ledger ends with an override_used event — it must
        # neither count as a round nor break the streak computation.
        full = _load(C0_LEDGER)
        assert any(r.get("type") == "override_used" for r in full)
        assert clearance_streak(full) == 3

    def test_empty_ledger(self):
        assert clearance_streak([]) == 0

    def test_persisted_findings_break_streak(self):
        ledger = _load(C0_LEDGER)
        rounds = _rounds_prefix(ledger, 3)
        rounds[-1] = dict(rounds[-1], persisted_ids=["f-x"])
        assert clearance_streak(rounds) == 0


# ──────────────────────────────  F001: policy rule  ──────────────────────────────


class TestStreakGatedSuppression:
    def _disposition_for(self, finding: dict, kind: str = WAIVED_MATRIX_PIN_HIGH) -> dict:
        return {
            finding["finding_id"]: {
                "kind": kind,
                "fingerprint": finding["fingerprint"],
                "cell_key": finding["cell_key"],
                "reason": REAL_CONFIRMATION,
            }
        }

    def test_high_matrix_pin_suppressed_with_streak_and_dedicated_kind(self, tmp_path):
        # C0 round 3: ONLY blocking high is the matrix_pin; mediums dispositioned lawfully.
        ledger = _rounds_prefix(_load(C0_LEDGER), 3)
        plan_dir = _plan_dir_with(tmp_path, ledger)
        r3 = ledger[-1]
        for f in r3["findings"]:
            if f["severity"] == "high":
                record_disposition(
                    plan_dir, finding_id=f["finding_id"],
                    kind=WAIVED_MATRIX_PIN_HIGH, reason=REAL_CONFIRMATION,
                )
            elif f["severity"] == "medium":
                record_disposition(
                    plan_dir, finding_id=f["finding_id"],
                    kind="waived_with_reason",
                    reason="explicit operator waiver for fixture completion path",
                )
        decision = gate_decision(plan_dir)
        assert decision.verdict == VERDICT_PROCEED

    def test_high_matrix_pin_not_suppressed_below_streak(self, tmp_path):
        # C0 round 2 (streak = 1): the high matrix_pin must NOT be suppressible.
        ledger = _rounds_prefix(_load(C0_LEDGER), 2)
        r2 = ledger[-1]
        high_pin = _find(r2, severity="high", finding_class="matrix_pin")
        dispositions = self._disposition_for(high_pin)
        # inject a synthetic valid-shaped disposition straight into the pure verdict:
        verdict = convergence_verdict(ledger, dispositions)
        assert verdict.verdict == VERDICT_BLOCK
        assert high_pin["finding_id"] in verdict.undisposed_ids

    def test_high_plan_contract_never_suppressed_by_new_kind(self):
        # worktree round 3 (streak=2): its high is plan_contract — v1.1 must not unlock it.
        ledger = _load(WORKTREE_LEDGER)
        r3 = ledger[-1]
        high_pc = _find(r3, severity="high", finding_class="plan_contract")
        verdict = convergence_verdict(ledger, self._disposition_for(high_pc))
        assert verdict.verdict == VERDICT_BLOCK
        assert high_pc["finding_id"] in verdict.undisposed_ids

    def test_critical_never_suppressed(self):
        ledger = _rounds_prefix(_load(C0_LEDGER), 3)
        r3 = dict(ledger[-1])
        boosted = [dict(f) for f in r3["findings"]]
        for f in boosted:
            if f["severity"] == "high" and f["finding_class"] == "matrix_pin":
                f["severity"] = "critical"
                crit = f
        r3["findings"] = boosted
        verdict = convergence_verdict(ledger[:-1] + [r3], self._disposition_for(crit))
        assert verdict.verdict == VERDICT_BLOCK

    def test_dedicated_kind_does_not_suppress_mediums(self):
        # waived_matrix_pin_high on a medium finding must not suppress it.
        ledger = _rounds_prefix(_load(C0_LEDGER), 3)
        r3 = ledger[-1]
        med = next(f for f in r3["findings"] if f["severity"] == "medium")
        verdict = convergence_verdict(ledger, self._disposition_for(med))
        assert verdict.verdict == VERDICT_BLOCK

    def test_other_kinds_do_not_suppress_highs(self):
        ledger = _rounds_prefix(_load(C0_LEDGER), 3)
        high_pin = _find(ledger[-1], severity="high", finding_class="matrix_pin")
        for kind in ("deferred_to_impl", "waived_with_reason", "split_to_followup_plan"):
            verdict = convergence_verdict(ledger, self._disposition_for(high_pin, kind=kind))
            assert verdict.verdict == VERDICT_BLOCK, kind

    def test_block_detail_names_streak_unlocked_eligibility(self):
        ledger = _rounds_prefix(_load(C0_LEDGER), 3)
        high_pin = _find(ledger[-1], severity="high", finding_class="matrix_pin")
        verdict = convergence_verdict(ledger, {})
        assert verdict.verdict == VERDICT_BLOCK
        assert high_pin["finding_id"] in verdict.streak_unlocked_ids
        assert WAIVED_MATRIX_PIN_HIGH in verdict.detail

    def test_no_eligibility_named_below_streak(self):
        ledger = _rounds_prefix(_load(C0_LEDGER), 2)
        verdict = convergence_verdict(ledger, {})
        assert verdict.streak_unlocked_ids == ()


# ──────────────────────────────  F001: verdict_for matrix  ──────────────────────────────


class TestVerdictForMatrix:
    def test_high_matrix_pin_streak_conditional_cell(self):
        assert verdict_for("high", "matrix_pin") == "block"
        assert verdict_for("high", "matrix_pin", streak_ok=False) == "block"
        assert (
            verdict_for("high", "matrix_pin", streak_ok=True)
            == "disposition_eligible_with_streak"
        )

    def test_matrix_total_both_streak_contexts(self):
        for severity in SEVERITIES:
            for cls in (*FINDING_CLASSES, None, "garbage"):
                for streak_ok in (False, True):
                    v = verdict_for(severity, cls, streak_ok=streak_ok)
                    assert v in (
                        "pass", "block", "block_unless_waived",
                        "disposition_eligible", "disposition_eligible_with_streak",
                    )

    def test_streak_never_changes_non_high_matrix_pin_cells(self):
        for severity in SEVERITIES:
            for cls in (*FINDING_CLASSES, None, "garbage"):
                if severity == "high" and cls == "matrix_pin":
                    continue
                assert verdict_for(severity, cls, streak_ok=True) == verdict_for(
                    severity, cls, streak_ok=False
                ), (severity, cls)

    def test_critical_and_plan_contract_and_fallback_block_even_with_streak(self):
        assert verdict_for("critical", "matrix_pin", streak_ok=True) == "block"
        assert verdict_for("high", "plan_contract", streak_ok=True) == "block"
        assert verdict_for("high", None, streak_ok=True) == "block"  # fallback


# ──────────────────────────────  F001: single threshold source  ──────────────────────────────


class TestSingleThresholdSource:
    def test_consumers_share_the_module_constant(self, tmp_path):
        import inspect

        from dontpanic_orchestrate import sufficiency_convergence as sc

        assert sc.MATRIX_PIN_STREAK_THRESHOLD == 2
        # convergence_verdict + record_disposition default their threshold
        # parameter to the ONE module constant (no second literal default).
        for fn in (sc.convergence_verdict, sc.record_disposition, sc.clearance_streak):
            sig = inspect.signature(fn)
            if "streak_threshold" in sig.parameters:
                assert (
                    sig.parameters["streak_threshold"].default
                    is sc.MATRIX_PIN_STREAK_THRESHOLD
                )

    def test_disagreement_impossible_refusal_matches_validation(self, tmp_path):
        # at streak=1 the verdict names no eligibility AND record_disposition refuses
        # — the two consumers cannot disagree because both read the same source.
        ledger = _rounds_prefix(_load(C0_LEDGER), 2)
        plan_dir = _plan_dir_with(tmp_path, ledger)
        verdict = gate_decision(plan_dir)
        assert verdict.streak_unlocked_ids == ()
        high_pin = _find(ledger[-1], severity="high", finding_class="matrix_pin")
        with pytest.raises(ConvergenceError, match="streak"):
            record_disposition(
                plan_dir, finding_id=high_pin["finding_id"],
                kind=WAIVED_MATRIX_PIN_HIGH, reason=REAL_CONFIRMATION,
            )


# ──────────────────────────────  F002: disposition kind  ──────────────────────────────


class TestWaivedMatrixPinHighKind:
    def test_kind_registered_and_no_audit(self):
        assert WAIVED_MATRIX_PIN_HIGH in DISPOSITION_KINDS
        assert WAIVED_MATRIX_PIN_HIGH in NO_AUDIT_DISPOSITION_KINDS

    def _c0_r3_plan(self, tmp_path):
        ledger = _rounds_prefix(_load(C0_LEDGER), 3)
        return _plan_dir_with(tmp_path, ledger), ledger[-1]

    def test_accepts_eligible_high_matrix_pin(self, tmp_path):
        plan_dir, r3 = self._c0_r3_plan(tmp_path)
        pin = _find(r3, severity="high", finding_class="matrix_pin")
        entry = record_disposition(
            plan_dir, finding_id=pin["finding_id"],
            kind=WAIVED_MATRIX_PIN_HIGH, reason=REAL_CONFIRMATION,
        )
        assert entry["kind"] == WAIVED_MATRIX_PIN_HIGH
        # mirrored into decisions.jsonl like existing kinds
        assert pin["finding_id"] in (plan_dir / "decisions.jsonl").read_text()
        # effective (valid) against the latest round
        assert pin["finding_id"] in effective_dispositions(plan_dir)

    def test_refuses_wrong_severity(self, tmp_path):
        plan_dir, r3 = self._c0_r3_plan(tmp_path)
        med = next(f for f in r3["findings"] if f["severity"] == "medium")
        with pytest.raises(ConvergenceError, match="high"):
            record_disposition(
                plan_dir, finding_id=med["finding_id"],
                kind=WAIVED_MATRIX_PIN_HIGH, reason=REAL_CONFIRMATION,
            )

    def test_refuses_wrong_class(self, tmp_path):
        ledger = _load(WORKTREE_LEDGER)
        plan_dir = _plan_dir_with(tmp_path, ledger)
        high_pc = _find(ledger[-1], severity="high", finding_class="plan_contract")
        with pytest.raises(ConvergenceError, match="matrix_pin"):
            record_disposition(
                plan_dir, finding_id=high_pc["finding_id"],
                kind=WAIVED_MATRIX_PIN_HIGH, reason=REAL_CONFIRMATION,
            )

    def test_refuses_streak_too_short(self, tmp_path):
        ledger = _rounds_prefix(_load(C0_LEDGER), 2)
        plan_dir = _plan_dir_with(tmp_path, ledger)
        pin = _find(ledger[-1], severity="high", finding_class="matrix_pin")
        with pytest.raises(ConvergenceError, match="streak"):
            record_disposition(
                plan_dir, finding_id=pin["finding_id"],
                kind=WAIVED_MATRIX_PIN_HIGH, reason=REAL_CONFIRMATION,
            )

    def test_refuses_short_confirmation(self, tmp_path):
        plan_dir, r3 = self._c0_r3_plan(tmp_path)
        pin = _find(r3, severity="high", finding_class="matrix_pin")
        with pytest.raises(ConvergenceError, match="confirmation"):
            record_disposition(
                plan_dir, finding_id=pin["finding_id"],
                kind=WAIVED_MATRIX_PIN_HIGH, reason="too short",
            )

    def test_refuses_literal_placeholder(self, tmp_path):
        plan_dir, r3 = self._c0_r3_plan(tmp_path)
        pin = _find(r3, severity="high", finding_class="matrix_pin")
        with pytest.raises(ConvergenceError, match="placeholder"):
            record_disposition(
                plan_dir, finding_id=pin["finding_id"],
                kind=WAIVED_MATRIX_PIN_HIGH, reason=CONFIRMATION_PLACEHOLDER,
            )
        # padding around the placeholder is still a refusal
        with pytest.raises(ConvergenceError, match="placeholder"):
            record_disposition(
                plan_dir, finding_id=pin["finding_id"],
                kind=WAIVED_MATRIX_PIN_HIGH,
                reason=f"confirmed {CONFIRMATION_PLACEHOLDER} thanks",
            )

    def test_cli_passthrough(self, tmp_path, capsys, monkeypatch):
        from dontpanic_orchestrate.cli import _plan_disposition_main

        plan_dir, r3 = self._c0_r3_plan(tmp_path)
        pin = _find(r3, severity="high", finding_class="matrix_pin")
        rc = _plan_disposition_main(
            [str(plan_dir), "--finding", pin["finding_id"],
             "--kind", WAIVED_MATRIX_PIN_HIGH, "--reason", REAL_CONFIRMATION]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert WAIVED_MATRIX_PIN_HIGH in out


# ──────────────────────────────  F002: refusal naming  ──────────────────────────────


class TestRefusalNaming:
    def test_gate_refusal_names_finding_and_command_template(self, tmp_path):
        from dontpanic_orchestrate import sufficiency_gate as sg

        ledger = _rounds_prefix(_load(C0_LEDGER), 3)
        plan_dir = _plan_dir_with(tmp_path, ledger)
        r3 = ledger[-1]
        pin = _find(r3, severity="high", finding_class="matrix_pin")
        # build the findings file the gate loads (shape: auditor findings list)
        evid = plan_dir / "evidence" / "goal-governance" / "pre_impl"
        raw = [
            {
                "severity": f["severity"],
                "journey_id": f.get("journey_id") or "journey",
                "gap_class": f.get("gap_class") or "coverage_gap",
                "description": f.get("description") or ("x" * 50),
                "feature_refs": f.get("feature_refs") or [],
                "recommendation": None,
                "finding_class": f["finding_class"],
            }
            for f in r3["findings"]
        ]
        (evid / "sufficiency-findings.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "auditor": "codex",
                    "implementer": "claude",
                    "input_fingerprint": r3.get("input_fingerprint") or "fp",
                    "generated_at": "2026-06-10T00:00:00Z",
                    "findings": raw,
                }
            )
        )
        (plan_dir / "plan.md").write_text(
            "---\n"
            "id: 2026-06-10-001-feat-convergence-policy-v1-1\n"
            "title: fixture\n"
            "type: feat\n"
            "status: draft\n"
            'date: "2026-06-10"\n'
            "goal_type: new_feature\n"
            "links:\n"
            "  objective_contract: ./objective_contract.json\n"
            "---\n"
        )
        (plan_dir / "features.json").write_text("{}")
        (plan_dir / "objective_contract.json").write_text("{}")
        with pytest.raises(sg.SufficiencyGateError) as exc:
            sg.enforce_sufficiency_gate(plan_dir)
        message = str(exc.value)
        assert pin["finding_id"] in message
        assert WAIVED_MATRIX_PIN_HIGH in message
        assert CONFIRMATION_PLACEHOLDER in message  # must-replace placeholder shown


# ──────────────────────────────  F003: dual-corpus dogfood  ──────────────────────────────


class TestDualCorpusDogfood:
    def test_c0_round4_discrimination(self, tmp_path):
        # explicit setup step: temp evidence dir from the verbatim ledger,
        # record the matrix-pin disposition, plan_contract high still blocks.
        ledger = _rounds_prefix(_load(C0_LEDGER), 4)
        plan_dir = _plan_dir_with(tmp_path, ledger)
        r4 = ledger[-1]
        pin = _find(r4, severity="high", finding_class="matrix_pin")
        pc = _find(r4, severity="high", finding_class="plan_contract")
        record_disposition(
            plan_dir, finding_id=pin["finding_id"],
            kind=WAIVED_MATRIX_PIN_HIGH, reason=REAL_CONFIRMATION,
        )
        decision = gate_decision(plan_dir)
        assert decision.verdict == VERDICT_BLOCK
        assert pc["finding_id"] in decision.undisposed_ids
        assert pin["finding_id"] not in decision.undisposed_ids

    def test_worktree_round3_negative_case(self, tmp_path):
        ledger = _load(WORKTREE_LEDGER)
        plan_dir = _plan_dir_with(tmp_path, ledger)
        decision = gate_decision(plan_dir)
        assert decision.verdict == VERDICT_BLOCK
        high_pc = _find(ledger[-1], severity="high", finding_class="plan_contract")
        assert high_pc["finding_id"] in decision.undisposed_ids
        # and the streak-unlocked list must NOT contain the plan_contract high
        assert high_pc["finding_id"] not in decision.streak_unlocked_ids

    def test_fallback_high_blocked_and_refused(self, tmp_path):
        # synthetic: a HIGH with NO finding_class atop a streak — conservative
        # fallback (plan_contract) must keep it blocked and un-dispositionable.
        from dontpanic_orchestrate.sufficiency_convergence import (
            assign_identities,
            build_round_record,
        )

        ledger = _rounds_prefix(_load(C0_LEDGER), 2)
        prior = ledger[-1]
        raw = [{
            "severity": "high",
            "journey_id": "mature-matrix-tail",
            "gap_class": "coverage_gap",
            "description": "unclassified high finding atop a long streak " + "x" * 20,
            "feature_refs": ["F001"],
            "recommendation": None,
            # finding_class deliberately ABSENT
        }]
        record = build_round_record(
            raw,
            prior=prior,
            input_fingerprint="fp-fallback",
            round_number=3,
        )
        full = ledger + [record]
        verdict = convergence_verdict(full, {})
        assert verdict.verdict == VERDICT_BLOCK
        fid = record["findings"][0]["finding_id"]
        assert fid not in verdict.streak_unlocked_ids
        plan_dir = _plan_dir_with(tmp_path, full)
        with pytest.raises(ConvergenceError, match="matrix_pin"):
            record_disposition(
                plan_dir, finding_id=fid,
                kind=WAIVED_MATRIX_PIN_HIGH, reason=REAL_CONFIRMATION,
            )

    def test_completion_path_new_kind_is_final_gate(self, tmp_path):
        # ORDERED: mediums first -> still refuses naming ONLY the eligible high;
        # the new kind recorded LAST flips refusal to success.
        ledger = _rounds_prefix(_load(C0_LEDGER), 3)
        plan_dir = _plan_dir_with(tmp_path, ledger)
        r3 = ledger[-1]
        pin = _find(r3, severity="high", finding_class="matrix_pin")
        for f in r3["findings"]:
            if f["severity"] != "medium":
                continue
            if f["finding_class"] == "plan_contract":
                record_disposition(
                    plan_dir, finding_id=f["finding_id"], kind="waived_with_reason",
                    reason="explicit operator waiver — fixture completion path",
                )
            else:
                record_disposition(
                    plan_dir, finding_id=f["finding_id"], kind="deferred_to_impl",
                )
        mid = gate_decision(plan_dir)
        assert mid.verdict == VERDICT_BLOCK
        assert mid.undisposed_ids == (pin["finding_id"],)
        assert pin["finding_id"] in mid.streak_unlocked_ids
        # FINAL step: the new kind alone flips the decision.
        record_disposition(
            plan_dir, finding_id=pin["finding_id"],
            kind=WAIVED_MATRIX_PIN_HIGH, reason=REAL_CONFIRMATION,
        )
        assert gate_decision(plan_dir).verdict == VERDICT_PROCEED

    def test_completion_path_reverse_order_refuses(self, tmp_path):
        ledger = _rounds_prefix(_load(C0_LEDGER), 3)
        plan_dir = _plan_dir_with(tmp_path, ledger)
        pin = _find(ledger[-1], severity="high", finding_class="matrix_pin")
        record_disposition(
            plan_dir, finding_id=pin["finding_id"],
            kind=WAIVED_MATRIX_PIN_HIGH, reason=REAL_CONFIRMATION,
        )
        assert gate_decision(plan_dir).verdict == VERDICT_BLOCK


# ──────────────────────────────  F003: scope guards  ──────────────────────────────


class TestAuditorContractUnchanged:
    def test_prompt_class_instruction_block_pinned(self):
        import inspect

        source = inspect.getsource(_sa)
        # equality-pin the instruction fragment exactly as shipped by 2026-06-09-002
        assert (
            "- `finding_class` (optional string, one of: plan_contract, " in source
        )
        assert (
            "implementation_detail, editorial, scope_guard, matrix_pin — " in source
        )
        assert "matrix_pin for unpinned deterministic-rule cells" in source

    def test_schema_field_description_pinned(self):
        field = _sa.SufficiencyFinding.model_fields["finding_class"]
        assert field.description == (
            "Convergence class (plan 2026-06-09-002): plan_contract / "
            "implementation_detail / editorial / scope_guard / matrix_pin. "
            "Optional — a missing or invalid value falls back CONSERVATIVELY to "
            "plan_contract at ledger time, never to a disposition-eligible class."
        )
