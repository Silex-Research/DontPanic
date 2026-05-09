"""Plan 2026-05-09-002 F003 — environmental volley short-circuit tests.

Six fixture cases pinning the supervisor's first-round env-only termination:

  (A) Round-0 auditor env-only → volley terminates with
      ``stopped_environmental_blocker``; sidecar JSON + INBOX
      ``environmental_blocker_short_circuit`` event both written; only
      one implementer + one auditor round dispatched.
  (B) Round-0 mixed (env + defect) → does NOT short-circuit;
      ``aggregate=implementation_defect`` keeps blocking=True.
  (C) Round-0 defect-only → does NOT short-circuit (D006 invariant).
  (D) Round-0 unknown aggregate → does NOT short-circuit (UNKNOWN
      collapses to blocking; preserves D006).
  (E) SpinDine F001-i1 representative fixture → 2 paid calls (one
      implementer, one auditor) instead of 4. Replays the env-only
      shape that motivated the plan.
  (F) Malformed envelope (findings missing entirely) → falls through to
      existing logic (UNKNOWN+blocking=True doesn't match short-circuit
      condition); no spurious termination.

Plus a unit class pinning the trigger condition directly against
``auditor_taxonomy.classify_terminal`` so the contract documented in
features.json is independently verifiable.
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
    circuit_breakers,
    inbox,
    notify,
    supervisor,
)
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Canonical finding shapes used across the cases below.
ENV_FINDING = {
    "severity": "high",
    "category": "test_coverage",
    "issue": (
        "Cannot run jest in this sandbox; permission denied invoking "
        "`npm test` from the auditor harness."
    ),
    "evidence": "harness blocker — sandbox refused to spawn the test runner.",
}
ENV_FINDING_2 = {
    "severity": "high",
    "category": "test_coverage",
    "issue": (
        "Could not invoke gcloud — sandbox network unavailable for the "
        "Firebase emulator boot."
    ),
    "evidence": "harness blocker — no internet inside the auditor sandbox.",
}
DEFECT_FINDING = {
    "severity": "high",
    "category": "correctness",
    "issue": (
        "Implementer's diff drops the null guard around the response "
        "parser, regressing the NPE that prior round fixed."
    ),
    "evidence": "diff line 42 removes `if response is None:` block.",
}
UNKNOWN_FINDING = {
    "severity": "low",
    "category": "style",
    "issue": "Variable naming could be more idiomatic.",
    "evidence": "stylistic comment, no concrete defect.",
}


# ───────────────────────── 1. Trigger condition unit tests ─────────────────────────


class TestTriggerCondition:
    """Pure tests against ``auditor_taxonomy.classify_terminal`` to pin the
    short-circuit condition: aggregate==ENVIRONMENTAL_REPRODUCTION_FAILURE
    AND blocking==False."""

    def test_env_only_classifies_as_env_advisory(self) -> None:
        envelope = {"findings": [ENV_FINDING, ENV_FINDING_2]}
        c = auditor_taxonomy.classify_terminal(
            feature_id="F001",
            final_audit_envelope=envelope,
            prior_envelopes=None,
        )
        assert c.aggregate == auditor_taxonomy.FindingClass.ENVIRONMENTAL_REPRODUCTION_FAILURE
        assert c.blocking is False

    def test_mixed_env_plus_defect_blocks(self) -> None:
        envelope = {"findings": [ENV_FINDING, DEFECT_FINDING]}
        c = auditor_taxonomy.classify_terminal(
            feature_id="F001",
            final_audit_envelope=envelope,
            prior_envelopes=None,
        )
        # Mixed: defect wins worst-class-wins; blocking stays True.
        assert c.aggregate == auditor_taxonomy.FindingClass.IMPLEMENTATION_DEFECT
        assert c.blocking is True

    def test_defect_only_blocks(self) -> None:
        envelope = {"findings": [DEFECT_FINDING]}
        c = auditor_taxonomy.classify_terminal(
            feature_id="F001",
            final_audit_envelope=envelope,
            prior_envelopes=None,
        )
        assert c.aggregate == auditor_taxonomy.FindingClass.IMPLEMENTATION_DEFECT
        assert c.blocking is True

    def test_unknown_only_blocks(self) -> None:
        # `style` + `low` doesn't match any taxonomy pattern → UNKNOWN.
        envelope = {"findings": [UNKNOWN_FINDING]}
        c = auditor_taxonomy.classify_terminal(
            feature_id="F001",
            final_audit_envelope=envelope,
            prior_envelopes=None,
        )
        assert c.aggregate == auditor_taxonomy.FindingClass.UNKNOWN
        assert c.blocking is True

    def test_empty_findings_block(self) -> None:
        # Defensive default — opaque terminal collapses to UNKNOWN+blocking.
        envelope = {"findings": []}
        c = auditor_taxonomy.classify_terminal(
            feature_id="F001",
            final_audit_envelope=envelope,
            prior_envelopes=None,
        )
        assert c.aggregate == auditor_taxonomy.FindingClass.UNKNOWN
        assert c.blocking is True

    def test_missing_findings_field_blocks(self) -> None:
        # Malformed envelope with no findings field — same defensive default.
        envelope: dict[str, Any] = {}
        c = auditor_taxonomy.classify_terminal(
            feature_id="F001",
            final_audit_envelope=envelope,
            prior_envelopes=None,
        )
        assert c.aggregate == auditor_taxonomy.FindingClass.UNKNOWN
        assert c.blocking is True


# ───────────────────────── 2. Breaker plumbing ─────────────────────────


class TestBreakerPlumbing:
    """Pin ENVIRONMENTAL_BLOCKER's enum / TERMINAL_STATUS / APPROVAL_BREAKERS
    membership so external consumers (signoff_writer, CLI approve) keep
    working."""

    def test_kind_enum_value(self) -> None:
        assert circuit_breakers.BreakerKind.ENVIRONMENTAL_BLOCKER.value == "environmental_blocker"

    def test_terminal_status_mapping(self) -> None:
        assert (
            circuit_breakers.TERMINAL_STATUS[circuit_breakers.BreakerKind.ENVIRONMENTAL_BLOCKER]
            == "stopped_environmental_blocker"
        )

    def test_membership_in_approval_breakers(self) -> None:
        # Operator clears via `dontpanic approve <plan> breaker:environmental_blocker`
        # — parity with NO_PROGRESS / WALL_CLOCK / etc.
        assert (
            circuit_breakers.BreakerKind.ENVIRONMENTAL_BLOCKER
            in circuit_breakers.APPROVAL_BREAKERS
        )

    def test_global_breaker_unchanged(self) -> None:
        # The global hard-stop breaker remains the only one outside
        # APPROVAL_BREAKERS (no operator clearance).
        assert (
            circuit_breakers.BreakerKind.GLOBAL_CIRCUIT_BREAKER
            not in circuit_breakers.APPROVAL_BREAKERS
        )


# ───────────────────────── 3. Supervisor end-to-end fixtures ─────────────────────────


class _NeedsChangesAuditorExecutor(BaseExecutor):
    """Auditor + implementer pair that produces a summary with the canonical
    ``**Verdict: needs_changes**`` line. Audit envelope's structured
    ``audit_status`` is derived as needs_changes from the summary text +
    findings list. Tests inject the structured findings via a wrapper around
    ``_run_round``.
    """

    def __init__(self, agent: str, role: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.role = role
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.calls += 1
        if self.role == "auditor":
            summary = (
                "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "## Target context\nRepo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "**Verdict: needs_changes**\n\n"
                "Auditor enumerated findings — see structured envelope."
            )
        else:
            summary = (
                "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "## Target context\nRepo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "[F001] Implementer landed the change."
            )
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=summary,
            raw_response=summary,
            error=None,
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _make_plan(tmp_path: Path, plan_id: str) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F003 environmental short-circuit synthetic
type: infra
tier: trivial
status: draft
date: "2026-05-09"
description: Synthetic plan for F003 environmental short-circuit tests.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 4
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# F003 environmental short-circuit synthetic

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
                        "description": "Synthetic feature.",
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


def _install_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[
    _NeedsChangesAuditorExecutor, _NeedsChangesAuditorExecutor
]:
    impl = _NeedsChangesAuditorExecutor("claude", "implementer")
    aud = _NeedsChangesAuditorExecutor("codex", "auditor")
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


def _inject_audit_findings(
    monkeypatch: pytest.MonkeyPatch,
    findings_per_round: list[list[dict[str, Any]]],
    *,
    audit_status: str = "needs_changes",
) -> None:
    """Wrap ``supervisor._run_round`` to overwrite the auditor envelope
    written by audit_writer with the test's structured findings list +
    audit_status. The summary's narrative verdict line is left intact
    (already says ``needs_changes``) so plan 2026-05-09-002 F001's
    verdict-mismatch detector does NOT fire on these fixtures."""
    original = supervisor._run_round
    counter = {"n": 0}

    def wrapped(*args: Any, **kwargs: Any) -> Path:
        path = original(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            data = json.loads(path.read_text())
            idx = counter["n"]
            counter["n"] += 1
            if idx < len(findings_per_round):
                data["findings"] = findings_per_round[idx]
            data["audit_status"] = audit_status
            path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    monkeypatch.setattr(supervisor, "_run_round", wrapped)


def _drop_findings_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrap ``_run_round`` to delete the ``findings`` field from the auditor
    envelope entirely, simulating a malformed envelope. ``audit_status``
    stays ``needs_changes`` so the F003 branch is reached."""
    original = supervisor._run_round

    def wrapped(*args: Any, **kwargs: Any) -> Path:
        path = original(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            data = json.loads(path.read_text())
            data.pop("findings", None)
            data["audit_status"] = "needs_changes"
            path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    monkeypatch.setattr(supervisor, "_run_round", wrapped)


class TestSupervisorWiring:
    def test_round0_env_only_short_circuits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Case (A): round-0 auditor env-only → volley terminates with
        stopped_environmental_blocker; sidecar JSON + INBOX both present;
        only one implementer + one auditor round dispatched (2 paid calls
        total)."""
        impl, aud = _install_runtime(monkeypatch)
        _inject_audit_findings(monkeypatch, [[ENV_FINDING, ENV_FINDING_2]])
        plan_id = "2026-05-09-970-fix-env-short-circuit"
        plan_dir = _make_plan(tmp_path, plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=4)

        assert result.final_status == "stopped_environmental_blocker", result
        # 2 paid calls, not 8 (would have been 4 rounds * 2 agents).
        assert impl.calls == 1, f"implementer called {impl.calls} times; expected 1"
        assert aud.calls == 1, f"auditor called {aud.calls} times; expected 1"
        # Sidecar JSON written.
        sidecar_dir = plan_dir / "audit"
        sidecars = list(sidecar_dir.glob("no_progress_classification_F001_iter*.json"))
        assert len(sidecars) == 1, sidecars
        sidecar = json.loads(sidecars[0].read_text())
        assert sidecar["aggregate"] == "environmental_reproduction_failure"
        assert sidecar["blocking"] is False
        # INBOX environmental_blocker_short_circuit event landed.
        events = inbox.read_events(plan_dir)
        env_events = [e for e in events if e.event == "environmental_blocker_short_circuit"]
        assert len(env_events) == 1, [e.event for e in events]
        ev = env_events[0]
        assert ev.headers["aggregate"] == "environmental_reproduction_failure"
        assert ev.headers["blocking"] == "false"
        assert ev.headers["feature_id"] == "F001"
        assert ev.headers["iteration"] == "1"
        # No no_progress event fired (short-circuit beats no_progress trip).
        assert not any(e.event == "no_progress_classification" for e in events)

    def test_round0_mixed_does_not_short_circuit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Case (B): mixed (env + defect) → aggregate=defect, blocking=True,
        does NOT trigger F003. Volley iterates per existing behavior until
        no_progress / iteration_cap fires."""
        impl, aud = _install_runtime(monkeypatch)
        # Same envelope across all rounds — no_progress will fire after
        # the second auditor round repeats needs_changes.
        _inject_audit_findings(
            monkeypatch,
            [[ENV_FINDING, DEFECT_FINDING]] * 4,
        )
        plan_id = "2026-05-09-971-fix-mixed-no-shortcircuit"
        plan_dir = _make_plan(tmp_path, plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=4)

        # Mixed terminal MUST NOT be stopped_environmental_blocker.
        assert result.final_status != "stopped_environmental_blocker", result
        # More than 1 implementer round dispatched (mixed iterates).
        assert impl.calls >= 2, f"implementer calls={impl.calls}; expected >= 2"
        events = inbox.read_events(plan_dir)
        assert not any(
            e.event == "environmental_blocker_short_circuit" for e in events
        ), [e.event for e in events]

    def test_round0_defect_only_does_not_short_circuit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Case (C): defect-only → aggregate=defect, blocking=True, no
        short-circuit. D006 invariant preserved."""
        impl, aud = _install_runtime(monkeypatch)
        _inject_audit_findings(monkeypatch, [[DEFECT_FINDING]] * 4)
        plan_id = "2026-05-09-972-fix-defect-only-no-shortcircuit"
        plan_dir = _make_plan(tmp_path, plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=4)

        assert result.final_status != "stopped_environmental_blocker", result
        assert impl.calls >= 2
        events = inbox.read_events(plan_dir)
        assert not any(
            e.event == "environmental_blocker_short_circuit" for e in events
        )

    def test_round0_unknown_does_not_short_circuit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Case (D): unknown aggregate → blocking=True, no short-circuit.
        D006 invariant preserved (unknown stays blocking)."""
        impl, aud = _install_runtime(monkeypatch)
        _inject_audit_findings(monkeypatch, [[UNKNOWN_FINDING]] * 4)
        plan_id = "2026-05-09-973-fix-unknown-no-shortcircuit"
        plan_dir = _make_plan(tmp_path, plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=4)

        assert result.final_status != "stopped_environmental_blocker", result
        events = inbox.read_events(plan_dir)
        assert not any(
            e.event == "environmental_blocker_short_circuit" for e in events
        )

    def test_spindine_f001_i1_fixture_two_paid_calls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Case (E): Replay the SpinDine F001-i1 representative shape —
        two env-only findings citing sandbox harness blockers. Volley
        terminates after 2 paid calls (1 impl + 1 aud) instead of 4
        (2 rounds * 2 agents). The documented regression is closed."""
        impl, aud = _install_runtime(monkeypatch)
        spindine_finding_1 = {
            "severity": "high",
            "category": "test_coverage",
            "issue": (
                "Cannot run xcodebuild from this sandbox; binary not found "
                "and simulator unavailable."
            ),
            "evidence": "harness blocker — Xcode CLI tools missing.",
        }
        spindine_finding_2 = {
            "severity": "high",
            "category": "test_coverage",
            "issue": (
                "Cannot invoke gcloud — sandbox network forbidden, "
                "permission denied on auth flow."
            ),
            "evidence": "harness blocker — no internet inside auditor.",
        }
        _inject_audit_findings(
            monkeypatch, [[spindine_finding_1, spindine_finding_2]]
        )
        plan_id = "2026-05-09-974-fix-spindine-fixture"
        plan_dir = _make_plan(tmp_path, plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=4)

        assert result.final_status == "stopped_environmental_blocker", result
        assert impl.calls == 1
        assert aud.calls == 1

    def test_malformed_envelope_falls_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Case (F): missing findings field → classify_terminal collapses
        to UNKNOWN+blocking=True, which doesn't match the short-circuit
        condition. Volley falls through to existing logic. Fail-open."""
        impl, aud = _install_runtime(monkeypatch)
        _drop_findings_field(monkeypatch)
        plan_id = "2026-05-09-975-fix-malformed-env-fall-through"
        plan_dir = _make_plan(tmp_path, plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=4)

        assert result.final_status != "stopped_environmental_blocker", result
        events = inbox.read_events(plan_dir)
        assert not any(
            e.event == "environmental_blocker_short_circuit" for e in events
        )
