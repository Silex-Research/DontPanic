"""Goal Governance V1 F004 — plan-lock sufficiency gate tests.

Covers the 6 cases enumerated in F004 step 6:

  (a) ``_should_gate_sufficiency`` returns True only for the 4 gated
      goal_type values (parity / new_feature / migration / incident).
  (b) ``enforce_sufficiency_gate`` is no-op for non-gated plans.
  (c) ``enforce_sufficiency_gate`` raises on blocking findings without
      override.
  (d) ``lock_plan`` writes override evidence + flips status when an
      override reason is supplied.
  (e) CLI lock subcommand exercises pass + fail paths through the
      actual ``dontpanic plan lock`` entry.
  (f) Backward compat — locking a plan without ``goal_type`` flips
      status without running the gate.

Plus extras covering the locked design points:

  - input-bound override invalidation (B): edit features.json after
    override → next gate call refuses with stale-override error;
  - blocking threshold (A): medium severity blocks lock;
  - dispatch backstop: hand-edited active plan with blocking findings
    is refused at first dispatch_volley call.

Run:

    PYTHONPATH=scripts python3 -m pytest \
        scripts/dontpanic_orchestrate/tests/test_sufficiency_gate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import cli, supervisor  # noqa: E402
from dontpanic_orchestrate import sufficiency_auditor as _sa  # noqa: E402
from dontpanic_orchestrate.sufficiency_gate import (  # noqa: E402
    BLOCKING_SEVERITIES,
    SufficiencyGateError,
    _should_gate_sufficiency,
    enforce_sufficiency_gate,
    lock_plan,
)

# ──────────────────────────────  fixture helpers  ──────────────────────────────


def _valid_contract(goal_type: str = "parity") -> dict:
    return {
        "goal_type": goal_type,
        "source_of_truth": "Some prior plan / curated reference",
        "user_journeys": [
            {
                "name": "onboarding",
                "description": (
                    "User opens the app, completes the welcome flow, and lands "
                    "on the home screen with their workspace loaded."
                ),
            }
        ],
        "completion_test": (
            "Onboarding runs end-to-end on iOS and Android without operator intervention."
        ),
    }


def _valid_features() -> dict:
    return {
        "features": [
            {
                "id": "F001",
                "category": "tooling",
                "phase": 1,
                "description": "fixture feature one for sufficiency gate testing",
                "steps": ["step a", "step b"],
                "acceptance": "Feature passes when both steps complete.",
                "passes": False,
                "depends_on": [],
                "evidence_refs": [],
            }
        ]
    }


def _write_plan(
    plan_dir: Path,
    *,
    goal_type: str | None = "parity",
    status: str = "draft",
    contract: dict | None = None,
    features: dict | None = None,
    findings: list[dict] | None = None,
    plan_id: str = "2026-05-05-999-feat-fixture",
) -> Path:
    plan_dir.mkdir(parents=True)

    fm: dict = {
        "id": plan_id,
        "title": "fixture plan",
        "type": "feat",
        "tier": "local",
        "status": status,
        "date": "2026-05-05",
        "description": "synthetic fixture plan for sufficiency gate tests",
    }
    if goal_type is not None:
        fm["goal_type"] = goal_type
        fm["links"] = {"objective_contract": "./objective_contract.json"}

    plan_md = "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n# fixture\n"
    (plan_dir / "plan.md").write_text(plan_md)

    (plan_dir / "features.json").write_text(
        json.dumps(features if features is not None else _valid_features())
    )

    if goal_type is not None:
        (plan_dir / "objective_contract.json").write_text(
            json.dumps(contract if contract is not None else _valid_contract(goal_type))
        )

    if findings is not None:
        evidence_dir = plan_dir / "evidence" / "goal-governance" / "pre_impl"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        # Stamp the current input fingerprint so the seeded findings represent a
        # fresh audit for THIS plan — the CLI lock path reuses them (the offline
        # reuse branch) instead of regenerating via a paid auditor (2026-06-09).
        (evidence_dir / "sufficiency-findings.json").write_text(
            json.dumps(
                {
                    "schema_version": _sa.FINDINGS_SCHEMA_VERSION,
                    "auditor": "codex",
                    "implementer": "claude",
                    "input_fingerprint": _sa.compute_input_fingerprint(plan_dir),
                    "generated_at": "2026-05-05T00:00:00Z",
                    "findings": findings,
                }
            )
        )

    return plan_dir


# ──────────────────────────────  (a) gating predicate  ──────────────────────────────


@pytest.mark.parametrize(
    "goal_type,expected",
    [
        ("parity", True),
        ("new_feature", True),
        ("migration", True),
        ("incident", True),
        ("mechanical", False),
        ("infra", False),
        ("refactor", False),
        (None, False),
        ("", False),
        ("garbage", False),
    ],
)
def test_should_gate_sufficiency_only_gates_four_required_types(
    goal_type: str | None, expected: bool
) -> None:
    plan_data = {"id": "x", "status": "draft"}
    if goal_type is not None:
        plan_data["goal_type"] = goal_type
    assert _should_gate_sufficiency(plan_data) is expected


def test_blocking_severities_locked_at_medium_plus() -> None:
    """Threshold A: medium / high / critical block; low / advisory pass."""
    assert "medium" in BLOCKING_SEVERITIES
    assert "high" in BLOCKING_SEVERITIES
    assert "critical" in BLOCKING_SEVERITIES
    assert "low" not in BLOCKING_SEVERITIES
    assert "advisory" not in BLOCKING_SEVERITIES


# ──────────────────────────────  (b) gate is no-op for non-gated plans  ────────


def test_enforce_sufficiency_gate_no_op_when_no_goal_type(tmp_path: Path) -> None:
    plan_dir = _write_plan(tmp_path / "no-goal", goal_type=None)
    enforce_sufficiency_gate(plan_dir)  # must not raise


def test_enforce_sufficiency_gate_no_op_for_mechanical(tmp_path: Path) -> None:
    plan_dir = _write_plan(tmp_path / "mechanical", goal_type="mechanical")
    enforce_sufficiency_gate(plan_dir)  # must not raise


# ──────────────────────────────  (c) blocking findings refuse  ────────────────


def test_enforce_sufficiency_gate_refuses_on_high_finding(tmp_path: Path) -> None:
    plan_dir = _write_plan(
        tmp_path / "blocking-high",
        findings=[
            {
                "severity": "high",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Onboarding journey is not covered by any current feature acceptance.",
                "feature_refs": [],
            }
        ],
    )
    with pytest.raises(SufficiencyGateError, match="blocking sufficiency finding"):
        enforce_sufficiency_gate(plan_dir)


def test_enforce_sufficiency_gate_refuses_on_medium_finding(tmp_path: Path) -> None:
    """Threshold A: medium severity must block lock (locked F004 design)."""
    plan_dir = _write_plan(
        tmp_path / "blocking-medium",
        findings=[
            {
                "severity": "medium",
                "journey_id": "onboarding",
                "gap_class": "wiring_gap",
                "description": "Welcome screen acceptance does not bind to home-load timing surfaces.",
                "feature_refs": ["F001"],
            }
        ],
    )
    with pytest.raises(SufficiencyGateError, match="≥ medium"):
        enforce_sufficiency_gate(plan_dir)


def test_enforce_sufficiency_gate_passes_on_low_severity_only(tmp_path: Path) -> None:
    """Low/advisory below threshold — gate passes silently."""
    plan_dir = _write_plan(
        tmp_path / "advisory-only",
        findings=[
            {
                "severity": "low",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Optional polish: onboarding could mention the closet feature explicitly.",
                "feature_refs": [],
            },
            {
                "severity": "advisory",
                "journey_id": "onboarding",
                "gap_class": "wiring_gap",
                "description": "Consider rewording the welcome copy for friendliness; not gating.",
                "feature_refs": [],
            },
        ],
    )
    enforce_sufficiency_gate(plan_dir)  # must not raise


def test_enforce_sufficiency_gate_refuses_when_findings_missing(tmp_path: Path) -> None:
    """Gated plan with no findings file → refuse pointing at F003."""
    plan_dir = _write_plan(tmp_path / "no-findings", findings=None)
    with pytest.raises(SufficiencyGateError, match="findings missing"):
        enforce_sufficiency_gate(plan_dir)


# ──────────────────────────────  (d) lock_plan mutates + override flow  ───────


def test_lock_plan_no_goal_type_flips_status_no_gate(tmp_path: Path) -> None:
    """Backward compat (acceptance #6): plans without goal_type lock without
    running the gate, regardless of any other state."""
    plan_dir = _write_plan(tmp_path / "no-goal", goal_type=None)
    lock_plan(plan_dir)
    fm = yaml.safe_load((plan_dir / "plan.md").read_text().split("---")[1])
    assert fm["status"] == "active"


def test_lock_plan_passes_gate_then_flips_status(tmp_path: Path) -> None:
    plan_dir = _write_plan(
        tmp_path / "green-pass",
        findings=[
            {
                "severity": "low",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Optional polish only — not load-bearing.",
                "feature_refs": [],
            }
        ],
    )
    lock_plan(plan_dir)
    fm = yaml.safe_load((plan_dir / "plan.md").read_text().split("---")[1])
    assert fm["status"] == "active"


def test_lock_plan_blocked_without_override_refuses(tmp_path: Path) -> None:
    plan_dir = _write_plan(
        tmp_path / "blocked-no-override",
        findings=[
            {
                "severity": "high",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Onboarding journey is not covered by any current feature acceptance.",
                "feature_refs": [],
            }
        ],
    )
    with pytest.raises(SufficiencyGateError):
        lock_plan(plan_dir)
    # status NOT flipped
    fm = yaml.safe_load((plan_dir / "plan.md").read_text().split("---")[1])
    assert fm["status"] == "draft"


def test_lock_plan_with_override_records_evidence_and_flips(tmp_path: Path) -> None:
    plan_dir = _write_plan(
        tmp_path / "override-flow",
        findings=[
            {
                "severity": "high",
                "journey_id": "publish-flow",
                "gap_class": "missing_feature",
                "description": "No feature in features.json points at the publish-flow journey.",
                "feature_refs": [],
            }
        ],
    )
    lock_plan(plan_dir, override_reason="P0 — ship before merge freeze", approved_by="bayesian")

    # status flipped
    fm = yaml.safe_load((plan_dir / "plan.md").read_text().split("---")[1])
    assert fm["status"] == "active"

    # override evidence recorded
    override_path = plan_dir / "evidence" / "goal-governance" / "pre_impl" / "override.json"
    assert override_path.is_file()
    override = json.loads(override_path.read_text())
    assert override["reason"] == "P0 — ship before merge freeze"
    assert override["approved_by"] == "bayesian"
    assert override["plan_id"] == "2026-05-05-999-feat-fixture"
    assert override["goal_type"] == "parity"
    assert override["objective_contract_path"] == "./objective_contract.json"
    # all three required hashes present
    for key in ("features_hash", "objective_contract_hash", "sufficiency_findings_hash"):
        assert key in override
        assert override[key].startswith("sha256:")


def test_lock_plan_refuses_when_status_not_draft(tmp_path: Path) -> None:
    plan_dir = _write_plan(tmp_path / "already-active", status="active", findings=[])
    with pytest.raises(SufficiencyGateError, match="status='active'"):
        lock_plan(plan_dir)


def test_lock_plan_rejects_override_for_non_gated_plan(tmp_path: Path) -> None:
    """A meaningless --ignore-sufficiency-findings on a non-gated plan must
    refuse loudly — silent acceptance would teach operators to use the flag
    blindly."""
    plan_dir = _write_plan(tmp_path / "non-gated-with-override", goal_type=None)
    with pytest.raises(SufficiencyGateError, match="meaningless"):
        lock_plan(plan_dir, override_reason="not applicable")


# ──────────────────────────────  override durability + invalidation  ──────────


def test_override_honored_on_subsequent_gate_calls(tmp_path: Path) -> None:
    """Once override.json is recorded with matching hashes, the gate
    returns silently on every subsequent call (durable)."""
    plan_dir = _write_plan(
        tmp_path / "durable-override",
        findings=[
            {
                "severity": "critical",
                "journey_id": "onboarding",
                "gap_class": "missing_feature",
                "description": "Critical-severity gap that the operator decided to bypass.",
                "feature_refs": [],
            }
        ],
    )
    lock_plan(plan_dir, override_reason="approved bypass", approved_by="op")
    # Subsequent gate calls (e.g. dispatch backstop) honor the override.
    enforce_sufficiency_gate(plan_dir)
    enforce_sufficiency_gate(plan_dir)  # idempotent


def test_override_invalidated_when_features_change(tmp_path: Path) -> None:
    """Threshold B: override is input-bound. Edit features.json after
    override → next gate call refuses with stale-override error."""
    plan_dir = _write_plan(
        tmp_path / "stale-override-features",
        findings=[
            {
                "severity": "high",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Onboarding gap that operator initially bypassed.",
                "feature_refs": [],
            }
        ],
    )
    lock_plan(plan_dir, override_reason="initial bypass", approved_by="op")

    # Mutate features.json — override should now be stale
    features = json.loads((plan_dir / "features.json").read_text())
    features["features"][0]["description"] = "MATERIALLY DIFFERENT description after lock"
    (plan_dir / "features.json").write_text(json.dumps(features))

    with pytest.raises(SufficiencyGateError, match="override is stale"):
        enforce_sufficiency_gate(plan_dir)


def test_override_invalidated_when_findings_change(tmp_path: Path) -> None:
    plan_dir = _write_plan(
        tmp_path / "stale-override-findings",
        findings=[
            {
                "severity": "high",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Initial finding the operator chose to bypass.",
                "feature_refs": [],
            }
        ],
    )
    lock_plan(plan_dir, override_reason="initial bypass", approved_by="op")

    # Re-run F003 (simulated) — findings file changes
    findings_path = (
        plan_dir / "evidence" / "goal-governance" / "pre_impl" / "sufficiency-findings.json"
    )
    payload = json.loads(findings_path.read_text())
    payload["findings"].append(
        {
            "severity": "critical",
            "journey_id": "publish-flow",
            "gap_class": "missing_feature",
            "description": "New gap surfaced after re-running the auditor — not previously bypassed.",
            "feature_refs": [],
        }
    )
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(SufficiencyGateError, match="override is stale"):
        enforce_sufficiency_gate(plan_dir)


def test_override_lists_which_inputs_drifted(tmp_path: Path) -> None:
    plan_dir = _write_plan(
        tmp_path / "stale-which",
        findings=[
            {
                "severity": "high",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Initial finding — long enough for the description min_length.",
                "feature_refs": [],
            }
        ],
    )
    lock_plan(plan_dir, override_reason="bypass", approved_by="op")

    # Drift only objective_contract.json
    contract = json.loads((plan_dir / "objective_contract.json").read_text())
    contract["completion_test"] = "MATERIALLY different completion test wording for parity goal."
    (plan_dir / "objective_contract.json").write_text(json.dumps(contract))

    with pytest.raises(SufficiencyGateError) as exc_info:
        enforce_sufficiency_gate(plan_dir)
    assert "objective_contract_hash" in str(exc_info.value)


# ──────────────────────────────  (e) CLI integration  ─────────────────────────


def _run_cli_plan_lock(plan_dir: Path, *extra: str) -> int:
    return cli.main(["plan", "lock", str(plan_dir), *extra])


def test_cli_plan_lock_pass_path_flips_status(tmp_path: Path) -> None:
    plan_dir = _write_plan(tmp_path / "cli-pass", findings=[])
    rc = _run_cli_plan_lock(plan_dir)
    assert rc == 0
    fm = yaml.safe_load((plan_dir / "plan.md").read_text().split("---")[1])
    assert fm["status"] == "active"


def test_cli_plan_lock_fail_path_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_dir = _write_plan(
        tmp_path / "cli-fail",
        findings=[
            {
                "severity": "high",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Onboarding gap that should block CLI lock without override.",
                "feature_refs": [],
            }
        ],
    )
    rc = _run_cli_plan_lock(plan_dir)
    assert rc == 3  # CLI uses exit 3 for gate refusal
    captured = capsys.readouterr()
    assert "REFUSED" in captured.err
    fm = yaml.safe_load((plan_dir / "plan.md").read_text().split("---")[1])
    assert fm["status"] == "draft"


def test_cli_plan_lock_with_override_flag_records_evidence(tmp_path: Path) -> None:
    plan_dir = _write_plan(
        tmp_path / "cli-override",
        findings=[
            {
                "severity": "high",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Onboarding gap that operator overrides via CLI flag.",
                "feature_refs": [],
            }
        ],
    )
    rc = _run_cli_plan_lock(plan_dir, "--ignore-sufficiency-findings", "P0 — ship before freeze")
    assert rc == 0
    override_path = plan_dir / "evidence" / "goal-governance" / "pre_impl" / "override.json"
    assert override_path.is_file()
    fm = yaml.safe_load((plan_dir / "plan.md").read_text().split("---")[1])
    assert fm["status"] == "active"


def test_cli_plan_lock_empty_override_reason_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_dir = _write_plan(tmp_path / "cli-empty-reason")
    rc = _run_cli_plan_lock(plan_dir, "--ignore-sufficiency-findings", "   ")
    assert rc == 2
    assert "non-empty reason" in capsys.readouterr().err


# ──────────────────────────────  dispatch backstop (D011)  ─────────────────────


def test_dispatch_volley_backstop_refuses_blocked_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a plan was hand-edited to ``status: active`` while sufficiency
    findings still include a blocking finding (and no valid override),
    the supervisor's first dispatch_volley call refuses via the gate
    backstop. Fakes the plan_loader/executor surface so the test stays
    a unit test on the gate placement, not a full volley."""
    plan_dir = _write_plan(
        tmp_path / "hand-edited-active",
        status="active",  # operator hand-edited around the lock command
        findings=[
            {
                "severity": "high",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Onboarding gap; operator skipped lock command.",
                "feature_refs": [],
            }
        ],
    )

    # The gate raises before dispatch_volley reaches plan_loader.load /
    # executor resolution, so the test does not need to mock those out.
    with pytest.raises(SufficiencyGateError, match="blocking sufficiency"):
        supervisor.dispatch_volley(plan_dir, feature_id="F001")


def test_dispatch_volley_backstop_no_op_for_non_gated_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backward compat: existing tests without goal_type are unaffected by
    the supervisor wiring. The gate returns silently and dispatch_volley
    proceeds to its existing failure mode (KeyError on missing feature
    here, since we don't mock the rest of the supervisor)."""
    plan_dir = _write_plan(tmp_path / "no-goal-backstop", goal_type=None, status="active")
    # The gate should not raise. dispatch_volley will fail later for unrelated
    # reasons (no real plan_loader fixture); the assertion is only that the
    # gate didn't intercept.
    with pytest.raises(Exception) as exc_info:
        supervisor.dispatch_volley(plan_dir, feature_id="F001")
    # SufficiencyGateError is a ValueError; if the gate intercepted, we'd see
    # the gate's error message. Confirm we got a different failure.
    assert "blocking sufficiency" not in str(exc_info.value)
    assert "override is stale" not in str(exc_info.value)
