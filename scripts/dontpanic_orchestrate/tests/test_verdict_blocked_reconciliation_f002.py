"""Plan 2026-05-12-001 v4 F002 — verdict-vs-finding reconciliation tests.

D022 fix: when the auditor returns ``audit_status=blocked`` we must NOT
trust the verdict string alone. The supervisor now classifies the findings
via the v3 taxonomy and reconciles:

  (a) Plan 010 F002 codex envelope — single advisory test_coverage finding
      citing the sandbox's missing temp dir. Aggregate classifies as
      ``environmental_reproduction_failure`` (advisory). Supervisor must
      promote the terminal to ``stopped_environmental_blocker`` (F003
      ENVIRONMENTAL_BLOCKER semantics) + emit a
      ``verdict_blocked_reconciled`` INBOX event.

  (b) Plan 004 F004 codex envelope — high-severity correctness finding.
      Aggregate classifies as ``implementation_defect`` (substantive).
      Supervisor must preserve the ``blocked`` terminal — substantive
      findings + verdict=blocked = real blocker.

  (c) Crafted verdict=blocked + empty findings → ``blocked_no_findings``
      terminal + INBOX event. Empty-findings is NOT vacuously advisory
      because we have no evidence the blocker IS environmental (could be
      network failure, format error, auditor refusal).

  (d) Crafted verdict=blocked + advisory + substantive mix → ``blocked``
      preserved. Substantive wins.

Plus a unit class pinning ``auditor_taxonomy.is_advisory_only_findings_set``
directly so the contract is independently verifiable.
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


# ───────────────────────── canonical finding shapes ─────────────────────────

# Plan 010 F002 codex envelope's actual finding shape (sandbox can't run pytest).
PLAN_010_F002_ADVISORY_FINDING: dict[str, Any] = {
    "severity": "advisory",
    "category": "test_coverage",
    "feature_id": "F002",
    "issue": (
        "Could not independently rerun pytest-based acceptance checks "
        "because Python reports no usable temporary directory in this "
        "read-only sandbox. Evidence: all pytest invocations failed "
        "before or during setup with `FileNotFoundError: No usable "
        "temporary directory found`."
    ),
    "evidence": "harness blocker — sandbox refused pytest temp dir.",
}

# Plan 004 F004 representative shape — high-severity correctness finding.
PLAN_004_F004_HIGH_FINDING: dict[str, Any] = {
    "severity": "high",
    "category": "correctness",
    "feature_id": "F004",
    "issue": (
        "Implementer's diff drops the null guard around the response "
        "parser, regressing the NPE that the prior round fixed. Calling "
        "the parser with response=None raises AttributeError instead of "
        "returning the documented sentinel."
    ),
    "evidence": "diff line 42 removes `if response is None:` block.",
}

# A second advisory finding — env-reproduction shape.
ENV_REPRO_FINDING: dict[str, Any] = {
    "severity": "high",
    "category": "test_coverage",
    "issue": (
        "Cannot run jest from the auditor sandbox; permission denied "
        "invoking npm test from the harness."
    ),
    "evidence": "sandbox refused to spawn the test runner.",
}

# Substantive correctness finding with feature_id matching the dispatched
# F002 — used by the "mixed advisory + substantive" case so scope_overreach
# does NOT mask the implementation_defect classification. (When a finding's
# feature_id differs from the dispatched feature_id, classify_finding routes
# it as scope_overreach — advisory — before checking severity/category, so
# the mix case must pin feature_id to the dispatched value.)
SUBSTANTIVE_F002_FINDING: dict[str, Any] = {
    "severity": "high",
    "category": "correctness",
    "feature_id": "F002",
    "issue": (
        "Implementer's diff drops the null guard around the response "
        "parser, regressing the NPE the prior round fixed."
    ),
    "evidence": "diff line 42 removes `if response is None:` block.",
}


# ───────────────────────── 1. helper unit tests ─────────────────────────


class TestIsAdvisoryOnlyFindingsSet:
    """Pure tests against ``auditor_taxonomy.is_advisory_only_findings_set``.
    Pins the contract from features.json: non-empty + all-advisory only."""

    def test_empty_findings_is_not_advisory(self) -> None:
        # Empty findings is NOT vacuously advisory (D005 of plan v4).
        assert auditor_taxonomy.is_advisory_only_findings_set([]) is False

    def test_none_findings_is_not_advisory(self) -> None:
        assert auditor_taxonomy.is_advisory_only_findings_set(None) is False

    def test_single_advisory_returns_true(self) -> None:
        assert (
            auditor_taxonomy.is_advisory_only_findings_set(
                [PLAN_010_F002_ADVISORY_FINDING],
                feature_id="F002",
            )
            is True
        )

    def test_single_high_correctness_returns_false(self) -> None:
        assert (
            auditor_taxonomy.is_advisory_only_findings_set(
                [PLAN_004_F004_HIGH_FINDING],
                feature_id="F004",
            )
            is False
        )

    def test_mix_advisory_and_substantive_returns_false(self) -> None:
        # Substantive wins — never auto-promote when ANY finding is
        # implementation_defect / unknown. The substantive finding's
        # feature_id matches the dispatched F002 so scope_overreach
        # doesn't mask the implementation_defect classification.
        assert (
            auditor_taxonomy.is_advisory_only_findings_set(
                [PLAN_010_F002_ADVISORY_FINDING, SUBSTANTIVE_F002_FINDING],
                feature_id="F002",
            )
            is False
        )

    def test_multiple_advisory_returns_true(self) -> None:
        assert (
            auditor_taxonomy.is_advisory_only_findings_set(
                [PLAN_010_F002_ADVISORY_FINDING, ENV_REPRO_FINDING],
                feature_id="F002",
            )
            is True
        )

    def test_non_dict_finding_returns_false(self) -> None:
        # Defensive: malformed entries (string, int) collapse to False so
        # the supervisor falls through to the original `blocked` terminal
        # rather than auto-promoting on garbage input.
        assert (
            auditor_taxonomy.is_advisory_only_findings_set(
                ["not-a-dict"],  # type: ignore[list-item]
                feature_id="F002",
            )
            is False
        )

    def test_taxonomy_classifier_injection_seam(self) -> None:
        """F002 spec — ``taxonomy_classifier`` is an injection seam, not a
        hard-coded dependency on ``classify_finding``. Confirm a stub
        classifier overrides the production heuristics.

        Stub returns SPEC_AMBIGUITY (advisory) for the first finding and
        IMPLEMENTATION_DEFECT (substantive) for the second. The helper
        must reach False once it sees the substantive class, regardless
        of what the real classifier would say about either finding."""
        calls: list[int] = []

        def stub(
            finding: dict[str, Any],
            *,
            finding_index: int,
            feature_id: str | None,
            saved_evidence_paths: tuple[str, ...],
        ) -> auditor_taxonomy.FindingClassification:
            calls.append(finding_index)
            cls = (
                auditor_taxonomy.FindingClass.SPEC_AMBIGUITY
                if finding_index == 0
                else auditor_taxonomy.FindingClass.IMPLEMENTATION_DEFECT
            )
            return auditor_taxonomy.FindingClassification(
                finding_index=finding_index,
                classification=cls,
                severity=str(finding.get("severity") or "unknown"),
                category=str(finding.get("category") or "unknown"),
                issue_excerpt="stub",
                rationale="stub classifier",
            )

        # Both finding dicts would classify as ADVISORY via the real
        # taxonomy (they're env-repro shapes). The stub flips finding[1]
        # to IMPLEMENTATION_DEFECT, which must collapse the helper to
        # False — proving the injection seam controls classification.
        assert (
            auditor_taxonomy.is_advisory_only_findings_set(
                [PLAN_010_F002_ADVISORY_FINDING, PLAN_010_F002_ADVISORY_FINDING],
                feature_id="F002",
                taxonomy_classifier=stub,
            )
            is False
        )
        # Stub was called for both indices (short-circuits after the
        # substantive verdict on finding_index=1, so we expect 2 calls).
        assert calls == [0, 1]

    def test_taxonomy_classifier_defaults_to_real_classify_finding(self) -> None:
        """When ``taxonomy_classifier`` is omitted (None), the helper must
        fall back to :func:`auditor_taxonomy.classify_finding`. Pin via
        a stub-as-default contradiction: passing ``None`` returns True
        for the advisory finding because the real classifier sees env-
        reproduction-failure semantics."""
        assert (
            auditor_taxonomy.is_advisory_only_findings_set(
                [PLAN_010_F002_ADVISORY_FINDING],
                feature_id="F002",
                taxonomy_classifier=None,
            )
            is True
        )


# ───────────────────────── 2. supervisor wiring fixtures ─────────────────────────


class _BlockedAuditorExecutor(BaseExecutor):
    """Implementer + auditor pair where the auditor's prose summary
    declares ``**Verdict: blocked**``. The structured ``audit_status``
    is rewritten by ``_inject_blocked_audit`` to match, so plan
    2026-05-09-002 F001's verdict-mismatch detector does NOT fire."""

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
                "**Verdict: blocked**\n\n"
                "Auditor enumerated findings — see structured envelope."
            )
        else:
            summary = (
                "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "## Target context\nRepo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "[F002] Implementer landed the change."
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


def _make_plan(tmp_path: Path, plan_id: str, feature_id: str = "F002") -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F002 verdict-blocked reconciliation synthetic
type: infra
tier: trivial
status: draft
date: "2026-05-12"
description: Synthetic plan for v4 F002 verdict-vs-finding reconciliation tests.
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

# F002 verdict-blocked reconciliation synthetic

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
                        "id": feature_id,
                        "category": "test",
                        "phase": 0,
                        "description": "Synthetic feature for F002 v4 reconciliation.",
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


def _install_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_BlockedAuditorExecutor, _BlockedAuditorExecutor]:
    impl = _BlockedAuditorExecutor("claude", "implementer")
    aud = _BlockedAuditorExecutor("codex", "auditor")
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


def _inject_blocked_audit(
    monkeypatch: pytest.MonkeyPatch,
    findings_per_round: list[list[dict[str, Any]] | None],
) -> None:
    """Wrap ``_run_round`` to set the auditor envelope's ``audit_status``
    to ``blocked`` and overwrite findings per round. When ``findings_per_round[idx]``
    is ``None``, the findings field is removed entirely (simulates an
    auditor that refused to produce findings)."""
    original = supervisor._run_round
    counter = {"n": 0}

    def wrapped(*args: Any, **kwargs: Any) -> Path:
        path = original(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            data = json.loads(path.read_text())
            idx = counter["n"]
            counter["n"] += 1
            if idx < len(findings_per_round):
                findings = findings_per_round[idx]
                if findings is None:
                    data.pop("findings", None)
                else:
                    data["findings"] = findings
            data["audit_status"] = "blocked"
            path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    monkeypatch.setattr(supervisor, "_run_round", wrapped)


def _inject_replay_audit(
    monkeypatch: pytest.MonkeyPatch,
    envelopes_per_round: list[dict[str, Any]],
) -> None:
    """Wrap ``_run_round`` to replay a real auditor envelope verbatim on
    each round (preserving its ``audit_status`` + ``summary`` + ``findings``
    so neither the verdict-mismatch detector nor the verdict-blocked
    reconciliation gate sees synthesized fields).

    Identity-preserving rewrites: ``task_id``, ``audit_id``, ``agent``,
    ``agent_role``, ``iteration`` come from the supervisor's pass — only
    operational fields (status / findings / summary / target_context) are
    replayed from the recorded envelope. This keeps the v3 audit_id +
    iteration sequence consistent with the synthetic plan_id used by the
    test harness."""
    original = supervisor._run_round
    counter = {"n": 0}

    def wrapped(*args: Any, **kwargs: Any) -> Path:
        path = original(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            base = json.loads(path.read_text())
            idx = counter["n"]
            counter["n"] += 1
            replay = envelopes_per_round[min(idx, len(envelopes_per_round) - 1)]
            for key in (
                "audit_status",
                "summary",
                "findings",
                "validation_performed",
                "target_context",
                "quota_consumed",
            ):
                if key in replay:
                    base[key] = replay[key]
            path.write_text(json.dumps(base, indent=2) + "\n")
        return path

    monkeypatch.setattr(supervisor, "_run_round", wrapped)


def _load_real_envelope(relative_path: str) -> dict[str, Any]:
    """Locate the repo-root and load a recorded audit envelope verbatim.

    ``relative_path`` is taken from the repo root (e.g.
    ``docs/plans/.../audit/codex-auditor-F004-i0.json``)."""
    repo_root = HERE.parents[3]
    return json.loads((repo_root / relative_path).read_text())


# Real Plan 004 F004 codex envelope (audit_status=needs_changes, high
# correctness finding). Plan v4 F002 acceptance (3) requires that
# replaying this envelope leaves the verdict-blocked branch untouched —
# reconciliation must NOT run on a `needs_changes` verdict.
PLAN_004_F004_REAL_ENVELOPE_PATH = (
    "docs/plans/2026-05-11-002-fix-harness-frictions-v3/audit/"
    "codex-auditor-F004-i0.json"
)


class TestVerdictBlockedReconciliation:
    def test_plan010_f002_advisory_promotes_to_environmental(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance (2): plan 010 F002 codex envelope (single advisory
        test_coverage finding) terminates as stopped_environmental_blocker,
        not blocked. Reconciliation INBOX event documents the override."""
        impl, aud = _install_runtime(monkeypatch)
        _inject_blocked_audit(monkeypatch, [[PLAN_010_F002_ADVISORY_FINDING]])
        plan_id = "2026-05-12-880-fix-f002-advisory-promote"
        plan_dir = _make_plan(tmp_path, plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F002", max_iterations=4)

        assert result.final_status == "stopped_environmental_blocker", result
        assert impl.calls == 1
        assert aud.calls == 1

        # Sidecar JSON written.
        sidecars = list(
            (plan_dir / "audit").glob("no_progress_classification_F002_iter*.json")
        )
        assert len(sidecars) == 1, sidecars
        sidecar = json.loads(sidecars[0].read_text())
        assert sidecar["aggregate"] == "environmental_reproduction_failure"
        assert sidecar["blocking"] is False

        # INBOX reconciliation event landed.
        events = inbox.read_events(plan_dir)
        reconciled = [e for e in events if e.event == "verdict_blocked_reconciled"]
        assert len(reconciled) == 1, [e.event for e in events]
        ev = reconciled[0]
        assert ev.headers["aggregate"] == "environmental_reproduction_failure"
        assert ev.headers["blocking"] == "false"
        assert ev.headers["feature_id"] == "F002"
        assert ev.headers["iteration"] == "1"
        assert ev.headers["original_verdict"] == "blocked"

        # No `blocked_no_findings` event should fire on the advisory path.
        assert not any(e.event == "blocked_no_findings" for e in events)

    def test_plan004_f004_real_envelope_preserves_needs_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance (3): replay the REAL Plan 004 F004 codex envelope
        (audit_status=needs_changes, high-severity correctness finding)
        verbatim. The verdict-blocked branch must NOT be entered — the
        real envelope's verdict is ``needs_changes``, not ``blocked``,
        so reconciliation never applies and the auditor's substantive
        finding routes through the normal needs_changes flow.

        The exact terminal depends on no-progress / diminishing-returns
        thresholds (the replayed envelope is identical across rounds,
        so no-progress fires once the threshold is met), but the
        assertion that pins acceptance (3) is: (a) NO
        ``verdict_blocked_reconciled`` event was ever emitted, (b) NO
        ``blocked_no_findings`` event was ever emitted, (c) the final
        terminal status is NOT ``blocked`` / ``stopped_environmental_blocker``
        / ``blocked_no_findings`` — substantive needs_changes findings
        never auto-promote, never reach the blocked-reconciliation gate.
        """
        real_envelope = _load_real_envelope(PLAN_004_F004_REAL_ENVELOPE_PATH)
        # Sanity: the recorded envelope must encode the acceptance-named
        # shape (audit_status=needs_changes, high-severity correctness).
        assert real_envelope["audit_status"] == "needs_changes"
        assert any(
            f.get("severity") == "high" and f.get("category") == "correctness"
            for f in real_envelope.get("findings") or []
        ), "real envelope must carry the high-correctness finding F002 spec cites"

        impl, aud = _install_runtime(monkeypatch)
        _inject_replay_audit(monkeypatch, [real_envelope, real_envelope])
        plan_id = "2026-05-12-881-fix-f004-real-envelope-preserves"
        plan_dir = _make_plan(tmp_path, plan_id, feature_id="F004")

        result = supervisor.dispatch_volley(plan_dir, "F004", max_iterations=4)

        # The verdict-blocked branch must NEVER fire on needs_changes —
        # reconciliation and the empty-findings terminal are both
        # reachable only via the verdict=blocked branch.
        events = inbox.read_events(plan_dir)
        assert not any(
            e.event == "verdict_blocked_reconciled" for e in events
        ), [e.event for e in events]
        assert not any(e.event == "blocked_no_findings" for e in events)
        # And no environmental_blocker sidecar should land for this case
        # via the verdict-blocked path (the needs_changes short-circuit
        # path is a different code path; the substantive finding here
        # blocks that too).
        assert result.final_status not in {
            "blocked",
            "blocked_no_findings",
            "stopped_environmental_blocker",
        }, result
        # The audit envelope's audit_status on disk remains needs_changes
        # across every round — pin acceptance (3)'s "unchanged behavior"
        # at the data-shape level.
        for audit_path in (plan_dir / "audit").glob("codex-auditor-F004-i*.json"):
            data = json.loads(audit_path.read_text())
            assert data["audit_status"] == "needs_changes", audit_path

    def test_synthetic_substantive_blocked_preserves_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance (3) extended (paired with the mixed case below):
        when ``audit_status`` IS rewritten to ``blocked`` but the only
        finding is substantive (implementation_defect / high correctness),
        the supervisor must NOT auto-promote. Substantive finding +
        verdict=blocked = real blocker, original ``blocked`` terminal
        preserved.

        Differs from ``test_plan004_f004_real_envelope_preserves_needs_changes``
        above (which replays the real envelope verbatim and exercises
        the needs_changes branch). This synthetic case exercises the
        verdict-blocked branch directly, confirming the
        is_advisory_only_findings_set guard rejects substantive findings.
        """
        impl, aud = _install_runtime(monkeypatch)
        _inject_blocked_audit(monkeypatch, [[PLAN_004_F004_HIGH_FINDING]])
        plan_id = "2026-05-12-881-fix-substantive-blocked-preserves"
        plan_dir = _make_plan(tmp_path, plan_id, feature_id="F004")

        result = supervisor.dispatch_volley(plan_dir, "F004", max_iterations=4)

        assert result.final_status == "blocked", result
        events = inbox.read_events(plan_dir)
        # No reconciliation occurred — substantive finding wins.
        assert not any(
            e.event == "verdict_blocked_reconciled" for e in events
        ), [e.event for e in events]
        assert not any(e.event == "blocked_no_findings" for e in events)
        # Volley_terminal event records the original `blocked` status.
        terminals = [e for e in events if e.event == "volley_terminal"]
        assert len(terminals) == 1
        assert terminals[0].headers["final_status"] == "blocked"

    def test_empty_findings_terminates_as_blocked_no_findings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance (4): verdict=blocked + empty findings list →
        ``blocked_no_findings`` terminal + INBOX event. Do NOT auto-promote
        because we have no evidence the blocker IS environmental."""
        impl, aud = _install_runtime(monkeypatch)
        _inject_blocked_audit(monkeypatch, [[]])
        plan_id = "2026-05-12-882-fix-empty-findings-blocked"
        plan_dir = _make_plan(tmp_path, plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F002", max_iterations=4)

        assert result.final_status == "blocked_no_findings", result
        assert impl.calls == 1
        assert aud.calls == 1

        events = inbox.read_events(plan_dir)
        no_findings_events = [e for e in events if e.event == "blocked_no_findings"]
        assert len(no_findings_events) == 1, [e.event for e in events]
        ev = no_findings_events[0]
        assert ev.headers["feature_id"] == "F002"
        assert ev.headers["iteration"] == "1"
        assert "audit_path" in ev.headers

        # No reconciliation event — we did NOT auto-promote.
        assert not any(e.event == "verdict_blocked_reconciled" for e in events)
        # No environmental_blocker sidecar written.
        sidecars = list(
            (plan_dir / "audit").glob("no_progress_classification_F002_iter*.json")
        )
        assert sidecars == []

    def test_missing_findings_field_terminates_as_blocked_no_findings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defensive: if the auditor's envelope has the ``findings`` field
        missing entirely (not just empty), reconciliation still routes
        through ``blocked_no_findings`` rather than auto-promoting."""
        impl, aud = _install_runtime(monkeypatch)
        _inject_blocked_audit(monkeypatch, [None])
        plan_id = "2026-05-12-883-fix-missing-findings-field"
        plan_dir = _make_plan(tmp_path, plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F002", max_iterations=4)

        assert result.final_status == "blocked_no_findings", result
        events = inbox.read_events(plan_dir)
        assert any(e.event == "blocked_no_findings" for e in events)
        assert not any(e.event == "verdict_blocked_reconciled" for e in events)

    def test_mixed_advisory_plus_substantive_preserves_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance (3) extended (D): mix of advisory + substantive →
        substantive wins. Preserve original ``blocked`` terminal."""
        impl, aud = _install_runtime(monkeypatch)
        _inject_blocked_audit(
            monkeypatch,
            [[PLAN_010_F002_ADVISORY_FINDING, SUBSTANTIVE_F002_FINDING]],
        )
        plan_id = "2026-05-12-884-fix-mixed-preserves-blocked"
        plan_dir = _make_plan(tmp_path, plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F002", max_iterations=4)

        assert result.final_status == "blocked", result
        events = inbox.read_events(plan_dir)
        assert not any(e.event == "verdict_blocked_reconciled" for e in events)
        assert not any(e.event == "blocked_no_findings" for e in events)
