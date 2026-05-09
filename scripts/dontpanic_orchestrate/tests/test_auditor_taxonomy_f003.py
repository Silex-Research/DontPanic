"""Plan 2026-05-08-003 F003 — auditor verdict taxonomy tests.

Pins the closed v0 taxonomy and the dispatch-time ``stopped_no_progress``
classifier wiring. Fixtures here mirror the patterns the preserved
audit-trail evidence catalogues:

  * environmental_reproduction_failure — sandbox / Xcode / Jest / CLI
    auth blockers reported in the auditor's ``issue`` text.
  * evidence_shape_disagreement — the auditor wanted a screenshot/JSON/
    log shape that the implementer satisfied with an equivalent saved
    artifact already referenced in the audit trail.
  * scope_overreach — finding cites a different feature_id than the
    one being volleyed, OR the issue text declares itself out of scope.
  * implementation_defect — substantive correctness/security/etc.
    severity=high finding with no harness/scope marker.
  * mixed — at least one ``implementation_defect`` plus at least one
    advisory class — must remain blocking.
  * unknown — opaque finding the classifier cannot place; remains
    blocking by default.

Acceptance items pinned here:
  (1) classifier is pure / deterministic;
  (2) closed taxonomy values used consistently;
  (3) environmental cases are classified separately from defects;
  (4) evidence-shape disagreement requires saved/operator evidence in
      the trail before flipping;
  (5) mixed/unknown remain blocking; no auto-signoff;
  (6) stopped_no_progress reporting names the class + recommended
      action (asserted via INBOX body + sidecar JSON);
  (7) all six fixture classes covered.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    auditor_taxonomy,
    inbox,
    notify,
    supervisor,
)
from dontpanic_orchestrate.auditor_taxonomy import FindingClass  # noqa: E402
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ───────────────────────── fixture finding builders ─────────────────────────


def _finding(
    *,
    severity: str = "high",
    category: str = "correctness",
    issue: str,
    evidence: str = "",
    feature_id: str | None = None,
    file: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "severity": severity,
        "category": category,
        "issue": issue,
    }
    if evidence:
        out["evidence"] = evidence
    if feature_id is not None:
        out["feature_id"] = feature_id
    if file is not None:
        out["file"] = file
    return out


# ───────────────────────── 1. Pure classifier unit tests ─────────────────────────


class TestPureClassifier:
    def test_environmental_xcode_unavailable(self) -> None:
        finding = _finding(
            issue=(
                "Auditor cannot run iOS UI tests; Xcode unavailable in this "
                "sandbox host."
            ),
            severity="high",
            category="test_coverage",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.ENVIRONMENTAL_REPRODUCTION_FAILURE
        assert "Xcode" in result.issue_excerpt or "xcode" in result.issue_excerpt.lower()

    def test_environmental_jest_could_not_run(self) -> None:
        finding = _finding(
            issue="Could not run Jest test suite in the auditor sandbox.",
            severity="medium",
            category="test_coverage",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.ENVIRONMENTAL_REPRODUCTION_FAILURE

    def test_environmental_permission_denied(self) -> None:
        finding = _finding(
            issue="Permission denied invoking gcloud auth login from the sandbox.",
            severity="high",
            category="security",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.ENVIRONMENTAL_REPRODUCTION_FAILURE

    def test_evidence_shape_with_saved_evidence_flips(self) -> None:
        finding = _finding(
            issue="Expected a screenshot of the rendered UI; received only logs.",
            severity="medium",
            category="documentation",
        )
        # Saved evidence path passed in — equivalent artifact landed earlier.
        saved = ("evidence/ui-render-trace.log", "evidence/ui-render.png")
        result = auditor_taxonomy.classify_finding(
            finding, feature_id="F001", saved_evidence_paths=saved
        )
        assert result.classification == FindingClass.EVIDENCE_SHAPE_DISAGREEMENT
        assert "saved evidence" in result.rationale.lower()

    def test_evidence_shape_without_saved_evidence_stays_blocking(self) -> None:
        """Acceptance #4: evidence-shape disagreement only flips when the
        audit trail already references equivalent evidence. Without saved
        paths, the finding falls back to the substantive-severity
        heuristic — high severity → implementation_defect (blocking)."""
        finding = _finding(
            issue="Expected a screenshot of the rendered UI; received only logs.",
            severity="high",
            category="correctness",
        )
        result = auditor_taxonomy.classify_finding(
            finding, feature_id="F001", saved_evidence_paths=()
        )
        assert result.classification == FindingClass.IMPLEMENTATION_DEFECT

    def test_scope_overreach_via_feature_id_mismatch(self) -> None:
        finding = _finding(
            issue="Authentication flow is missing rate limiting.",
            severity="high",
            category="security",
            feature_id="F042",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.SCOPE_OVERREACH

    def test_scope_overreach_via_text(self) -> None:
        finding = _finding(
            issue="Concern about retry budgets — unrelated to this feature.",
            severity="medium",
            category="performance",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.SCOPE_OVERREACH

    def test_implementation_defect_substantive(self) -> None:
        finding = _finding(
            issue=(
                "Race condition in the auth listener: token refresh can fire "
                "after sign-out, leading to a Firestore listener crash."
            ),
            severity="high",
            category="correctness",
            file="services/AuthService.swift",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.IMPLEMENTATION_DEFECT

    def test_unknown_for_low_severity_no_pattern(self) -> None:
        finding = _finding(
            issue="Minor quibble about variable naming in the helper.",
            severity="low",
            category="style",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.UNKNOWN

    def test_classifier_is_pure_and_deterministic(self) -> None:
        """Acceptance #1: pure / deterministic — repeated calls return
        identical results. No subprocess / network / filesystem probing."""
        finding = _finding(
            issue="Could not run npm test from sandbox",
            severity="medium",
            category="test_coverage",
        )
        first = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        second = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert first == second


# ───────────────────────── 2. Aggregate (terminal) classification ─────────────────────────


class TestTerminalClassification:
    def test_all_environmental_advisory(self) -> None:
        envelope = {
            "audit_status": "needs_changes",
            "findings": [
                _finding(issue="Could not run Xcode tests", severity="high", category="test_coverage"),
                _finding(issue="CLI auth required for gcloud, not available", severity="medium", category="security"),
            ],
        }
        result = auditor_taxonomy.classify_terminal(
            feature_id="F001", final_audit_envelope=envelope
        )
        assert result.aggregate == FindingClass.ENVIRONMENTAL_REPRODUCTION_FAILURE
        assert result.blocking is False
        assert "verification locally" in result.recommended_action.lower()

    def test_mixed_defect_plus_environmental_stays_blocking(self) -> None:
        """Acceptance #5: mixed sets remain blocking. The aggregate
        elevates to implementation_defect."""
        envelope = {
            "audit_status": "needs_changes",
            "findings": [
                _finding(
                    issue="Race condition in token refresh listener",
                    severity="critical",
                    category="correctness",
                ),
                _finding(
                    issue="Could not run npm test in sandbox",
                    severity="medium",
                    category="test_coverage",
                ),
            ],
        }
        result = auditor_taxonomy.classify_terminal(
            feature_id="F001", final_audit_envelope=envelope
        )
        assert result.aggregate == FindingClass.IMPLEMENTATION_DEFECT
        assert result.blocking is True

    def test_unknown_finding_present_remains_blocking(self) -> None:
        envelope = {
            "audit_status": "needs_changes",
            "findings": [
                _finding(issue="Style nitpick on naming", severity="low", category="style"),
                _finding(issue="Could not run pytest in sandbox", severity="medium", category="test_coverage"),
            ],
        }
        result = auditor_taxonomy.classify_terminal(
            feature_id="F001", final_audit_envelope=envelope
        )
        assert result.aggregate == FindingClass.UNKNOWN
        assert result.blocking is True

    def test_empty_findings_collapse_to_unknown_blocking(self) -> None:
        envelope = {"audit_status": "needs_changes", "findings": []}
        result = auditor_taxonomy.classify_terminal(
            feature_id="F001", final_audit_envelope=envelope
        )
        assert result.aggregate == FindingClass.UNKNOWN
        assert result.blocking is True

    def test_evidence_shape_uses_prior_envelopes(self) -> None:
        """Acceptance #4: ``collect_saved_evidence_paths`` reads prior
        implementer envelopes' validation_performed + summary so the
        shape-disagreement gate has the full audit trail in view."""
        prior = [
            {
                "agent_role": "implementer",
                "summary": (
                    "Landed retries logic + saved trace at "
                    "evidence/retry-trace.log for verification."
                ),
                "validation_performed": ["wrote evidence/retry-trace.log"],
            }
        ]
        final = {
            "audit_status": "needs_changes",
            "findings": [
                _finding(
                    issue="Expected JSON output for the retry trace, received plain log.",
                    severity="medium",
                    category="documentation",
                )
            ],
        }
        result = auditor_taxonomy.classify_terminal(
            feature_id="F001",
            final_audit_envelope=final,
            prior_envelopes=prior,
        )
        assert result.aggregate == FindingClass.EVIDENCE_SHAPE_DISAGREEMENT
        assert result.blocking is False
        # Prior envelope's path was collected into saved_evidence_paths.
        assert any("evidence/retry-trace.log" in p for p in result.saved_evidence_paths)

    def test_inbox_body_names_class_and_action(self) -> None:
        """Acceptance #6: stopped_no_progress reporting names the class
        and recommended action."""
        envelope = {
            "audit_status": "needs_changes",
            "findings": [
                _finding(issue="Could not run Xcode tests", severity="high", category="test_coverage"),
            ],
        }
        result = auditor_taxonomy.classify_terminal(
            feature_id="F001", final_audit_envelope=envelope
        )
        body = auditor_taxonomy.format_inbox_body(result)
        assert "[environmental_reproduction_failure]" in body
        assert "ADVISORY" in body
        assert "Recommended next action" in body

    def test_sidecar_json_persists(self, tmp_path: Path) -> None:
        envelope = {
            "audit_status": "needs_changes",
            "findings": [_finding(issue="Race in auth listener", severity="critical")],
        }
        classification = auditor_taxonomy.classify_terminal(
            feature_id="F001", final_audit_envelope=envelope
        )
        path = auditor_taxonomy.write_classification_sidecar(
            plan_dir=tmp_path,
            feature_id="F001",
            iteration=2,
            classification=classification,
        )
        assert path.is_file()
        payload = json.loads(path.read_text())
        assert payload["aggregate"] == "implementation_defect"
        assert payload["blocking"] is True
        assert payload["feature_id"] == "F001"
        assert len(payload["findings"]) == 1


# ───────────────────────── 3. Supervisor wiring (end-to-end no-progress) ─────────────────────────


def _summary(agent: str, role: str, status: str) -> str:
    return (
        "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
        "## Target context\nRepo: synthetic\nEnv: dev\nProject: (none)\n\n"
        f"Overall verdict: {status}.\n{agent}/{role}.\n"
    )


class _ScriptedExecutor(BaseExecutor):
    """Scripted executor that returns a fixed status. The scripted no-
    progress test forces the auditor to produce ``needs_changes`` with a
    chosen findings list across two consecutive rounds."""

    def __init__(self, agent: str, *, status: str = "needs_changes") -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.status = status

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=_summary(self.agent_name, task.agent_role, self.status),
            raw_response=_summary(self.agent_name, task.agent_role, self.status),
            error=None,
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _make_plan(tmp_path: Path, plan_id: str) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F003 no-progress synthetic
type: infra
tier: trivial
status: draft
date: "2026-05-09"
description: Synthetic plan for F003 no-progress taxonomy wiring tests.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 2
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# F003 no-progress synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "test",
                        "phase": 0,
                        "description": "Synthetic feature for taxonomy wiring.",
                        "steps": ["scripted"],
                        "acceptance": "ok",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return plan_dir


def _install_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[BaseExecutor, BaseExecutor]:
    impl = _ScriptedExecutor("claude")
    aud = _ScriptedExecutor("codex")
    monkeypatch.setenv(notify.DISABLE_ENV, "1")
    monkeypatch.setitem(AGENT_REGISTRY, "claude", lambda: impl)
    monkeypatch.setitem(AGENT_REGISTRY, "codex", lambda: aud)
    monkeypatch.setattr(
        supervisor,
        "_quota_gate",
        lambda agent: (None, f"[quota] {agent}: bypassed"),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "evaluate_global",
        lambda: supervisor.circuit_breakers.GlobalBreakerState(False, 0),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_wall_clock",
        lambda *args, **kwargs: (False, ""),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_budget_ceiling",
        lambda *args, **kwargs: supervisor.circuit_breakers.BudgetCeilingResult(
            supervisor.circuit_breakers.BudgetCeilingKind.OK, False, ""
        ),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_diminishing_returns",
        lambda audit_paths: (False, ""),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_convergence_collapse",
        lambda audit_paths: (False, ""),
    )
    monkeypatch.setattr(
        supervisor.quota_admission,
        "evaluate",
        lambda *args, **kwargs: supervisor.quota_admission.AdmissionCheck(
            supervisor.quota_admission.DispatchClass.AUTONOMOUS,
            supervisor.quota_admission.QuotaCheck(False, None, None, 90.0),
            supervisor.quota_admission.InteractiveCheck(False, None),
            frozenset(),
        ),
    )
    return impl, aud


def _force_auditor_findings(
    monkeypatch: pytest.MonkeyPatch, findings: list[dict[str, Any]]
) -> None:
    """Patch _run_round to inject the chosen findings + needs_changes
    verdict on every auditor envelope. Drives the no-progress detector
    (identical status across two rounds) and feeds the taxonomy
    classifier deterministic input."""
    original = supervisor._run_round

    def wrapped(*args: Any, **kwargs: Any) -> Path:
        path = original(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            data = json.loads(path.read_text())
            data["audit_status"] = "needs_changes"
            data["findings"] = findings
            path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    monkeypatch.setattr(supervisor, "_run_round", wrapped)


class TestNoProgressWiring:
    def test_advisory_no_progress_emits_classification(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Plan 2026-05-09-002 F003 — env-only findings now short-circuit
        # via BreakerKind.ENVIRONMENTAL_BLOCKER BEFORE no_progress can
        # fire, so the env path is no longer reachable through this
        # wiring. This test now exercises a sibling advisory aggregate
        # (scope_overreach: finding.feature_id != dispatched feature_id)
        # that classify_terminal also marks blocking=False but that
        # F003's short-circuit deliberately does NOT match (it's keyed
        # exactly on environmental_reproduction_failure). The advisory-
        # but-not-env path still reaches the no_progress classifier and
        # the wiring this test pins must keep producing the sidecar +
        # INBOX event with the correct non-env aggregate.
        _install_runtime(monkeypatch)
        _force_auditor_findings(
            monkeypatch,
            [
                _finding(
                    issue="Reorganizing CI workflow naming — separate plan",
                    severity="high",
                    category="correctness",
                    feature_id="F999",
                )
            ],
        )
        plan_dir = _make_plan(tmp_path, "2026-05-09-940-fix-no-progress-advisory")

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=2)

        assert result.final_status == "stopped_no_progress"
        assert "scope_overreach" in result.reason
        assert "blocking=False" in result.reason
        # Sidecar JSON landed.
        sidecars = list((plan_dir / "audit").glob(
            f"{auditor_taxonomy.CLASSIFICATION_SIDECAR_PREFIX}_F001_iter*.json"
        ))
        assert len(sidecars) == 1
        payload = json.loads(sidecars[0].read_text())
        assert payload["aggregate"] == "scope_overreach"
        assert payload["blocking"] is False
        # INBOX classification event.
        events = inbox.read_events(plan_dir)
        cls_events = [e for e in events if e.event == "no_progress_classification"]
        assert len(cls_events) == 1
        assert cls_events[0].headers["aggregate"] == "scope_overreach"
        assert cls_events[0].headers["blocking"] == "false"

    def test_defect_no_progress_remains_blocking(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance #5: implementation_defect class always stays
        blocking and the no-progress terminal does not auto-advance."""
        _install_runtime(monkeypatch)
        _force_auditor_findings(
            monkeypatch,
            [
                _finding(
                    issue="Race condition in auth listener; sign-out callback fires after token refresh",
                    severity="critical",
                    category="correctness",
                )
            ],
        )
        plan_dir = _make_plan(tmp_path, "2026-05-09-941-fix-no-progress-defect")

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=2)

        assert result.final_status == "stopped_no_progress"
        assert "implementation_defect" in result.reason
        assert "blocking=True" in result.reason
        events = inbox.read_events(plan_dir)
        cls_events = [e for e in events if e.event == "no_progress_classification"]
        assert len(cls_events) == 1
        assert cls_events[0].headers["aggregate"] == "implementation_defect"
        assert cls_events[0].headers["blocking"] == "true"
