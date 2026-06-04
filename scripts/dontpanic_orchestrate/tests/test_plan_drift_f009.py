"""F009 — active-run plan drift reconciliation tests.

Plan 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 F009 AC(1)-(7).

These tests simulate another process editing plan files mid-run (writing the
baseline, then mutating an artifact, then re-checking) and prove DontPanic
classifies the drift correctly and never continues on stale context silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import plan_drift
from dontpanic_orchestrate.plan_drift import DriftClass

# ─────────────────────────────── fixtures ──────────────────────────────────

_BASE_PLAN_MD = """---
id: 2026-01-01-001-test-drift
title: Drift test plan
status: active
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
loop_caps:
  max_iterations: 3
dependencies: []
protected_paths:
  - secrets/**
child_charter:
  allowed_paths:
    - "src/**"
  forbidden_decisions:
    - "do not touch billing"
---

# Drift test plan

Body text that is not part of the fingerprint projection.
"""

_BASE_FEATURES = {
    "task_id": "2026-01-01-001-test-drift",
    "features": [
        {
            "id": "F001",
            "description": "first feature",
            "acceptance": "(1) it works",
            "depends_on": [],
            "passes": False,
        }
    ],
}

_BASE_OBJECTIVE = {"goal_type": "new_feature", "acceptance_signals": ["works"]}


def _make_plan(tmp_path: Path) -> Path:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "plan.md").write_text(_BASE_PLAN_MD)
    (plan_dir / "features.json").write_text(json.dumps(_BASE_FEATURES, indent=2))
    (plan_dir / "decisions.jsonl").write_text(
        json.dumps({"id": "D001", "title": "first", "body": "x"}) + "\n"
    )
    (plan_dir / "objective_contract.json").write_text(json.dumps(_BASE_OBJECTIVE))
    return plan_dir


def _append_decision(plan_dir: Path, did: str) -> None:
    with (plan_dir / "decisions.jsonl").open("a") as f:
        f.write(json.dumps({"id": did, "title": did, "body": "y"}) + "\n")


# ───────────────────────────── fingerprint / baseline ──────────────────────


def test_record_and_read_baseline_roundtrip(tmp_path):
    """AC1: dispatch records a plan-run fingerprint before work starts."""
    plan_dir = _make_plan(tmp_path)
    path = plan_drift.record_baseline(plan_dir)
    assert path.is_file()
    assert path.name == plan_drift.BASELINE_FILENAME
    fp = plan_drift.read_baseline(plan_dir)
    assert fp is not None
    # Every tracked file that exists at baseline is hashed and present. (The
    # gate-state file is created lazily by the supervisor, so it may be absent
    # at dispatch — its projection is still recorded.)
    for rel in (
        plan_drift.PLAN_MD,
        plan_drift.FEATURES_JSON,
        plan_drift.DECISIONS_JSONL,
        plan_drift.OBJECTIVE_CONTRACT_JSON,
    ):
        assert fp.file_hashes.get(rel) is not None
    # decision_lines fold the id together with a content hash.
    assert len(fp.decision_lines) == 1
    assert plan_drift._decision_id_of(fp.decision_lines[0]) == "D001"
    assert "F001" in fp.features_semantics["by_id"]
    assert fp.gate_semantics == {"cleared_gates": [], "completed_stages": []}


def test_no_change_no_drift(tmp_path):
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.NONE
    assert not report.has_drift
    assert report.changed_files == ()


# ───────────────────────────── classification ──────────────────────────────


def test_additive_decisions_is_additive_ledger(tmp_path):
    """AC3: additive decisions.jsonl drift is reconciled without stopping."""
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    _append_decision(plan_dir, "D002")
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.ADDITIVE_LEDGER
    assert "decisions.jsonl" in report.changed_files
    assert not report.budget_protected  # additive does not pause


def test_decisions_non_additive_edit_is_refresh(tmp_path):
    """A rewritten/removed decision is NOT a safe additive note."""
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    # Rewrite the existing decision (same count, different id) — not append.
    (plan_dir / "decisions.jsonl").write_text(
        json.dumps({"id": "D999", "title": "rewritten", "body": "z"}) + "\n"
    )
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.CONTEXT_REFRESH


def test_decisions_rewrite_plus_append_is_refresh(tmp_path):
    """Finding #4 regression: a SINGLE edit that rewrites an existing decision's
    body AND appends a new one must NOT be misclassified as additive. Tracking
    only ids ("D001") -> ("D001","D002") looks like a clean append; folding the
    content hash into each line fingerprint catches the rewrite."""
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    # Rewrite D001's body AND append D002 in the same write.
    (plan_dir / "decisions.jsonl").write_text(
        json.dumps({"id": "D001", "title": "first", "body": "REWRITTEN"}) + "\n"
        + json.dumps({"id": "D002", "title": "second", "body": "new"}) + "\n"
    )
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.CONTEXT_REFRESH, (
        "rewrite-of-existing + append must be refresh, not additive_ledger"
    )
    assert any(c.dimension == "decisions" for c in report.changes)


def test_pure_append_still_additive(tmp_path):
    """Control for the above: a clean append with every existing line byte-
    identical is still ADDITIVE_LEDGER."""
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    _append_decision(plan_dir, "D002")
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.ADDITIVE_LEDGER
    dec = next(c for c in report.changes if c.dimension == "decisions")
    assert "D002" in dec.summary


# ───────────────────────────── gate-state drift ────────────────────────────


def _write_gate_state(plan_dir: Path, cleared: list[str]) -> None:
    audit = plan_dir / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "gate-state.json").write_text(
        json.dumps(
            {
                "plan_id": "2026-01-01-001-test-drift",
                "cleared_gates": cleared,
                "history": [{"action": "approve", "gate": g} for g in cleared],
            }
        )
    )


def test_gate_state_clear_mid_run_is_refresh(tmp_path):
    """Finding #1: a gate cleared in gate-state.json mid-run (e.g. a human
    hand-editing the file to bypass a pause) IS detected as context-refresh."""
    plan_dir = _make_plan(tmp_path)
    _write_gate_state(plan_dir, ["pre_impl"])
    base = plan_drift.compute_fingerprint(plan_dir)
    # Another process clears pre_merge as well.
    _write_gate_state(plan_dir, ["pre_impl", "pre_merge"])
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.CONTEXT_REFRESH
    assert any(c.dimension == "gate_state" for c in report.changes)
    assert "audit/gate-state.json" in report.changed_files


def test_gate_state_history_only_append_is_not_drift(tmp_path):
    """The projection drops the volatile `history` list, so a record_pause that
    only appends history (same cleared/completed set) must NOT manufacture
    drift — that is what would otherwise phantom-trip on every supervisor pause."""
    plan_dir = _make_plan(tmp_path)
    audit = plan_dir / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "gate-state.json").write_text(
        json.dumps({"plan_id": "p", "cleared_gates": ["pre_impl"], "history": []})
    )
    base = plan_drift.compute_fingerprint(plan_dir)
    # Same cleared set, but history grew (a pause was recorded).
    (audit / "gate-state.json").write_text(
        json.dumps(
            {
                "plan_id": "p",
                "cleared_gates": ["pre_impl"],
                "history": [{"action": "pause", "at": "2026-01-01T00:00:00Z"}],
            }
        )
    )
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert not any(c.dimension == "gate_state" for c in report.changes)


def test_advance_gate_baseline_folds_supervisor_clear(tmp_path):
    """advance_gate_baseline lets the supervisor's OWN gate clear pass without
    a phantom pause, while a CONCURRENT features.json edit in the same window is
    still caught on the next check."""
    plan_dir = _make_plan(tmp_path)
    _write_gate_state(plan_dir, [])
    plan_drift.record_baseline(plan_dir)
    # Supervisor clears pre_impl itself, then advances the gate baseline.
    _write_gate_state(plan_dir, ["pre_impl"])
    plan_drift.advance_gate_baseline(plan_dir)
    decision = plan_drift.check_and_reconcile(
        plan_dir,
        plan_id="2026-01-01-001-test-drift",
        feature_id="F001",
        stage=plan_drift.STAGE_IMPLEMENTER,
    )
    assert decision.proceed is True
    assert decision.report.drift_class is DriftClass.NONE
    # But a real concurrent edit after the advance is still caught.
    feats = json.loads((plan_dir / "features.json").read_text())
    feats["features"][0]["acceptance"] = "changed by another agent"
    (plan_dir / "features.json").write_text(json.dumps(feats))
    decision2 = plan_drift.check_and_reconcile(
        plan_dir,
        plan_id="2026-01-01-001-test-drift",
        feature_id="F001",
        stage=plan_drift.STAGE_AUDITOR,
    )
    assert decision2.proceed is False
    assert decision2.report.drift_class is DriftClass.CONTEXT_REFRESH


def test_feature_acceptance_change_is_refresh(tmp_path):
    """AC4: acceptance drift pauses with refresh guidance."""
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    feats = json.loads((plan_dir / "features.json").read_text())
    feats["features"][0]["acceptance"] = "(1) it works DIFFERENTLY now"
    (plan_dir / "features.json").write_text(json.dumps(feats))
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.CONTEXT_REFRESH
    assert report.budget_protected


def test_feature_list_change_is_refresh(tmp_path):
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    feats = json.loads((plan_dir / "features.json").read_text())
    feats["features"].append(
        {"id": "F002", "description": "second", "acceptance": "(1)", "passes": False}
    )
    (plan_dir / "features.json").write_text(json.dumps(feats))
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.CONTEXT_REFRESH
    assert any(c.dimension == "features.list" for c in report.changes)


@pytest.mark.parametrize(
    "mutation,expected_dim",
    [
        ("max_iterations", "loop_caps"),
        ("human_gates", "human_gates"),
        ("agents_required", "agents_required"),
    ],
)
def test_plan_refresh_fields(tmp_path, mutation, expected_dim):
    """AC4: loop-cap / gate / role drift each pauses with refresh guidance."""
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    text = (plan_dir / "plan.md").read_text()
    if mutation == "max_iterations":
        text = text.replace("max_iterations: 3", "max_iterations: 7")
    elif mutation == "human_gates":
        text = text.replace("  - pre_impl", "  - pre_impl\n  - pre_merge")
    elif mutation == "agents_required":
        text = text.replace("  - codex", "  - gemini")
    (plan_dir / "plan.md").write_text(text)
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.CONTEXT_REFRESH
    assert any(c.dimension == expected_dim for c in report.changes)


def test_objective_contract_change_is_refresh(tmp_path):
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    (plan_dir / "objective_contract.json").write_text(
        json.dumps({"goal_type": "new_feature", "acceptance_signals": ["different"]})
    )
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.CONTEXT_REFRESH


@pytest.mark.parametrize(
    "mutation,expected_dim",
    [
        ("allowed_paths", "allowed_paths"),
        ("forbidden_decisions", "forbidden_decisions"),
        ("protected_paths", "protected_paths"),
    ],
)
def test_scope_policy_change_is_blocking(tmp_path, mutation, expected_dim):
    """AC5: scope/policy drift requires human acknowledgement."""
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    text = (plan_dir / "plan.md").read_text()
    if mutation == "allowed_paths":
        text = text.replace('    - "src/**"', '    - "src/**"\n    - "infra/**"')
    elif mutation == "forbidden_decisions":
        text = text.replace(
            '    - "do not touch billing"', '    - "do not touch billing"\n    - "no schema edits"'
        )
    elif mutation == "protected_paths":
        text = text.replace("  - secrets/**", "  - secrets/**\n  - vault/**")
    (plan_dir / "plan.md").write_text(text)
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.BLOCKING_POLICY
    assert any(c.dimension == expected_dim for c in report.changes)
    assert report.budget_protected


def test_precedence_blocking_dominates_refresh_and_additive(tmp_path):
    """A blocking change wins even when refresh + additive changes co-occur."""
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    # additive decision + acceptance refresh + scope policy change together
    _append_decision(plan_dir, "D002")
    feats = json.loads((plan_dir / "features.json").read_text())
    feats["features"][0]["acceptance"] = "changed"
    (plan_dir / "features.json").write_text(json.dumps(feats))
    text = (plan_dir / "plan.md").read_text().replace(
        '    - "src/**"', '    - "src/**"\n    - "infra/**"'
    )
    (plan_dir / "plan.md").write_text(text)
    after = plan_drift.compute_fingerprint(plan_dir)
    report = plan_drift.classify_drift(base, after)
    assert report.drift_class is DriftClass.BLOCKING_POLICY


# ───────────────────────────── guidance (AC6) ──────────────────────────────


def test_build_guidance_single_choice_refresh(tmp_path):
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    feats = json.loads((plan_dir / "features.json").read_text())
    feats["features"][0]["acceptance"] = "changed"
    (plan_dir / "features.json").write_text(json.dumps(feats))
    report = plan_drift.classify_drift(base, plan_drift.compute_fingerprint(plan_dir))
    guidance = plan_drift.build_guidance("2026-01-01-001-test-drift", "F001", report)
    # AC6: exactly ONE concise reconciliation action, not repeated warnings.
    assert len(guidance.choices) == 1
    choice = guidance.choices[0]
    assert choice.recommended
    assert choice.exact_command and "orchestrate" in choice.exact_command
    assert not choice.requires_human


def test_build_guidance_blocking_requires_human(tmp_path):
    plan_dir = _make_plan(tmp_path)
    base = plan_drift.compute_fingerprint(plan_dir)
    text = (plan_dir / "plan.md").read_text().replace(
        '    - "src/**"', '    - "src/**"\n    - "infra/**"'
    )
    (plan_dir / "plan.md").write_text(text)
    report = plan_drift.classify_drift(base, plan_drift.compute_fingerprint(plan_dir))
    guidance = plan_drift.build_guidance("2026-01-01-001-test-drift", "F001", report)
    assert len(guidance.choices) == 1
    assert guidance.choices[0].requires_human


# ─────────────────────── check_and_reconcile (AC2/3/5/7) ────────────────────


def _read_inbox_events(plan_dir: Path) -> list[str]:
    from dontpanic_orchestrate import inbox

    p = inbox.inbox_path(plan_dir)
    if not p.is_file():
        return []
    events: list[str] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("event:"):
            events.append(line.split(":", 1)[1].strip())
    return events


def test_reconcile_additive_proceeds_and_advances_baseline(tmp_path):
    """AC3 + AC7: additive drift reconciled WITHOUT stopping; event recorded;
    baseline advanced so the same note never re-reports."""
    plan_dir = _make_plan(tmp_path)
    plan_drift.record_baseline(plan_dir)
    _append_decision(plan_dir, "D002")
    decision = plan_drift.check_and_reconcile(
        plan_dir,
        plan_id="2026-01-01-001-test-drift",
        feature_id="F001",
        stage=plan_drift.STAGE_IMPLEMENTER,
    )
    assert decision.proceed is True
    assert decision.report.drift_class is DriftClass.ADDITIVE_LEDGER
    assert "plan_drift_reconciled" in _read_inbox_events(plan_dir)
    # baseline advanced → a second check sees no further drift
    decision2 = plan_drift.check_and_reconcile(
        plan_dir,
        plan_id="2026-01-01-001-test-drift",
        feature_id="F001",
        stage=plan_drift.STAGE_AUDITOR,
    )
    assert decision2.proceed is True
    assert decision2.report.drift_class is DriftClass.NONE


def test_reconcile_refresh_pauses_before_paid_call(tmp_path):
    """AC2 + AC4 + AC7: a concurrent edit to features.json mid-run is detected
    and DontPanic refuses to proceed (does not continue on stale context)."""
    plan_dir = _make_plan(tmp_path)
    plan_drift.record_baseline(plan_dir)
    # Simulate ANOTHER process editing the plan mid-run.
    feats = json.loads((plan_dir / "features.json").read_text())
    feats["features"][0]["acceptance"] = "rewritten by another agent"
    (plan_dir / "features.json").write_text(json.dumps(feats))
    decision = plan_drift.check_and_reconcile(
        plan_dir,
        plan_id="2026-01-01-001-test-drift",
        feature_id="F001",
        stage=plan_drift.STAGE_IMPLEMENTER,
    )
    assert decision.proceed is False
    assert decision.report.drift_class is DriftClass.CONTEXT_REFRESH
    assert decision.report.budget_protected
    assert decision.guidance is not None and len(decision.guidance.choices) == 1
    assert "plan_drift_detected" in _read_inbox_events(plan_dir)


def test_reconcile_blocking_pauses_for_human_ack(tmp_path):
    """AC5: scope/policy drift requires human acknowledgement before continuing."""
    plan_dir = _make_plan(tmp_path)
    plan_drift.record_baseline(plan_dir)
    text = (plan_dir / "plan.md").read_text().replace(
        '    - "src/**"', '    - "src/**"\n    - "infra/**"'
    )
    (plan_dir / "plan.md").write_text(text)
    decision = plan_drift.check_and_reconcile(
        plan_dir,
        plan_id="2026-01-01-001-test-drift",
        feature_id="F001",
        stage=plan_drift.STAGE_SIGNOFF,
    )
    assert decision.proceed is False
    assert decision.report.drift_class is DriftClass.BLOCKING_POLICY
    assert decision.guidance.choices[0].requires_human
    assert "plan_drift_blocked" in _read_inbox_events(plan_dir)


def test_reconcile_missing_baseline_fails_closed(tmp_path):
    """codex #1: a missing/corrupt active-run baseline must FAIL CLOSED — the
    check raises rather than silently re-baselining the (possibly already
    drifted) current state and proceeding. The dispatch-start baseline is the
    true reference; losing it means drift can no longer be proven, so the volley
    must pause, not run blind."""
    plan_dir = _make_plan(tmp_path)
    assert not plan_drift.baseline_path(plan_dir).is_file()
    with pytest.raises(plan_drift.DriftBaselineMissingError):
        plan_drift.check_and_reconcile(
            plan_dir,
            plan_id="2026-01-01-001-test-drift",
            feature_id="F001",
            stage=plan_drift.STAGE_IMPLEMENTER,
        )
    # No baseline was silently written behind the operator's back.
    assert not plan_drift.baseline_path(plan_dir).is_file()


def test_reconcile_corrupt_baseline_fails_closed(tmp_path):
    """codex #1: a baseline file that exists but cannot be parsed is treated the
    same as missing — fail closed rather than proceed on unverifiable state."""
    plan_dir = _make_plan(tmp_path)
    bp = plan_drift.baseline_path(plan_dir)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text("{ this is not valid json")
    with pytest.raises(plan_drift.DriftBaselineMissingError):
        plan_drift.check_and_reconcile(
            plan_dir,
            plan_id="2026-01-01-001-test-drift",
            feature_id="F001",
            stage=plan_drift.STAGE_IMPLEMENTER,
        )


def test_reconcile_no_drift_no_event(tmp_path):
    plan_dir = _make_plan(tmp_path)
    plan_drift.record_baseline(plan_dir)
    decision = plan_drift.check_and_reconcile(
        plan_dir,
        plan_id="2026-01-01-001-test-drift",
        feature_id="F001",
        stage=plan_drift.STAGE_IMPLEMENTER,
    )
    assert decision.proceed is True
    assert decision.report.drift_class is DriftClass.NONE
    assert _read_inbox_events(plan_dir) == []


def test_reconcile_emits_dashboard_sidecar(tmp_path):
    """AC6: the same concise ActionChoice is projected to the dashboard sidecar."""
    from dontpanic_orchestrate import operator_console

    plan_dir = _make_plan(tmp_path)
    plan_drift.record_baseline(plan_dir)
    feats = json.loads((plan_dir / "features.json").read_text())
    feats["features"][0]["acceptance"] = "changed"
    (plan_dir / "features.json").write_text(json.dumps(feats))
    plan_drift.check_and_reconcile(
        plan_dir,
        plan_id="2026-01-01-001-test-drift",
        feature_id="F001",
        stage=plan_drift.STAGE_IMPLEMENTER,
    )
    sidecar = operator_console.default_event_sidecar_path()
    assert sidecar.is_file()
    lines = [ln for ln in sidecar.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    # Rehydrates into a valid ActionItem.
    item = operator_console._action_item_from_sidecar_dict(entry)
    assert item is not None
    assert "refresh" in item.title.lower() or "redispatch" in item.title.lower()
