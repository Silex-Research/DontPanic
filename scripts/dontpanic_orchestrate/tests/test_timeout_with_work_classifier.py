"""Plan 2026-05-04-003 F003 — supervisor classifier excludes timeout-with-work
from no-progress / diminishing-returns counting.

Acceptance coverage map:

(1) Classifier helper exists; pure function           → TestClassifierHelper
(2) No-progress excludes timeout-with-work             → TestNoProgressDetector
(3) Diminishing-returns excludes timeout-with-work     → TestDiminishingReturnsDetector
(4) Loop history fidelity                              → TestLoopHistoryFidelity
(5) Plan B retroactive diagnosability → stopped_cap    → TestPlanBRetroactive
(6) No regression on blocked-without-work              → TestPlanBRetroactive
(7) No breaker enum / threshold / status changes       → TestBoundaryDiscipline
(8) Auditor invocation unchanged                       → TestAuditorStillInvoked
(9) Transcript visibility line                         → TestTranscriptVisibility
(10) Test isolation discipline (no sys.modules churn)  → asserted by external grep
(15) No new audit envelope fields / status enum values → TestBoundaryDiscipline

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_timeout_with_work_classifier.py
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from dontpanic_orchestrate import circuit_breakers as cb
from dontpanic_orchestrate import supervisor, transcript
from dontpanic_orchestrate.executors import AGENT_REGISTRY
from dontpanic_orchestrate.executors.base import (
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ───────────────────────────  envelope builders  ───────────────────────────


def _impl_envelope(
    *,
    audit_status: str,
    iteration: int = 0,
    worktree_marker: str | None = "true",
    extra_markers: list[str] | None = None,
) -> dict[str, Any]:
    """Build a minimal implementer envelope.

    ``worktree_marker`` controls whether ``validation_performed`` includes a
    ``worktree_changed=<value>`` marker:
      - "true"  → blocked-with-worktree-changes (the F003 classifier hits)
      - "false" → blocked-without-worktree-changes (legitimate no-progress)
      - "unknown" → non-git cwd (does NOT count as timeout-with-work)
      - None     → marker absent (pre-F002 envelope shape; counts as legitimate)
    """
    markers: list[str] = ["read ~/.jarvis/quota_state.json (claude pct=0)"]
    if worktree_marker is not None:
        markers.extend(
            [
                "subprocess_timeout_seconds=600",
                f"worktree_changed={worktree_marker}",
                "grace_period_used=false",
            ]
        )
    if extra_markers:
        markers.extend(extra_markers)
    return {
        "task_id": "2026-05-04-003-test-plan",
        "audit_id": f"2026-05-04-003-test-plan#claude#{iteration}",
        "agent": "claude",
        "agent_role": "implementer",
        "iteration": iteration,
        "started_at": _iso_now(),
        "completed_at": _iso_now(),
        "audit_status": audit_status,
        "validation_performed": markers,
        "summary": "[F003] (synthetic test envelope)",
        "findings": [],
        "quota_consumed": {"api_calls": 0},
    }


def _aud_envelope(
    *,
    audit_status: str,
    iteration: int = 0,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "task_id": "2026-05-04-003-test-plan",
        "audit_id": f"2026-05-04-003-test-plan#codex#{iteration}",
        "agent": "codex",
        "agent_role": "auditor",
        "iteration": iteration,
        "started_at": _iso_now(),
        "completed_at": _iso_now(),
        "audit_status": audit_status,
        "validation_performed": [f"reviewing implementer audit i{iteration}"],
        "summary": f"[F003] auditor verdict iteration {iteration}",
        "findings": findings
        or [
            {
                "severity": "high",
                "category": "test_coverage",
                "feature_id": "F001",
                "issue": "Synthetic auditor finding for F003 classifier test",
                "evidence": "pinned for diminishing-returns reproducibility",
            }
        ],
        "quota_consumed": {"api_calls": 1},
    }


def _write_pair(
    audit_dir: Path,
    iteration: int,
    impl_env: dict[str, Any],
    aud_env: dict[str, Any],
) -> tuple[Path, Path]:
    """Write an (implementer, auditor) pair to disk in the order audit_paths
    accumulates during a real volley. Returns the paths in the same order so
    callers can splice them into a list."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    impl_path = audit_dir / f"claude-implementer-F001-i{iteration}.json"
    aud_path = audit_dir / f"codex-auditor-F001-i{iteration}.json"
    impl_path.write_text(json.dumps(impl_env, indent=2))
    aud_path.write_text(json.dumps(aud_env, indent=2))
    return impl_path, aud_path


# ─────────────────────────────  classifier helper  ─────────────────────────────


class TestClassifierHelper:
    """AC #1 — `_envelope_is_timeout_with_work` is a pure function returning
    True only for `audit_status: blocked AND worktree_changed=true`."""

    def test_blocked_with_worktree_changed_true(self) -> None:
        env = _impl_envelope(audit_status="blocked", worktree_marker="true")
        assert cb._envelope_is_timeout_with_work(env) is True

    def test_blocked_with_worktree_changed_false(self) -> None:
        env = _impl_envelope(audit_status="blocked", worktree_marker="false")
        assert cb._envelope_is_timeout_with_work(env) is False

    def test_blocked_with_worktree_changed_unknown(self) -> None:
        env = _impl_envelope(audit_status="blocked", worktree_marker="unknown")
        assert cb._envelope_is_timeout_with_work(env) is False

    def test_blocked_without_marker(self) -> None:
        env = _impl_envelope(audit_status="blocked", worktree_marker=None)
        assert cb._envelope_is_timeout_with_work(env) is False

    def test_signed_off_with_marker_does_not_classify(self) -> None:
        env = _impl_envelope(audit_status="signed_off", worktree_marker="true")
        assert cb._envelope_is_timeout_with_work(env) is False

    def test_needs_changes_does_not_classify(self) -> None:
        env = _impl_envelope(audit_status="needs_changes", worktree_marker="true")
        assert cb._envelope_is_timeout_with_work(env) is False

    @pytest.mark.parametrize("invalid", [None, [], "not-a-dict", 42])
    def test_non_dict_inputs(self, invalid: Any) -> None:
        assert cb._envelope_is_timeout_with_work(invalid) is False

    def test_validation_performed_not_a_list(self) -> None:
        env = {
            "audit_status": "blocked",
            "validation_performed": "worktree_changed=true",  # str, not list
        }
        assert cb._envelope_is_timeout_with_work(env) is False

    def test_pure_function_no_mutation(self) -> None:
        env = _impl_envelope(audit_status="blocked", worktree_marker="true")
        before = json.dumps(env, sort_keys=True)
        cb._envelope_is_timeout_with_work(env)
        cb._envelope_is_timeout_with_work(env)
        after = json.dumps(env, sort_keys=True)
        assert before == after


# ───────────────────────────  no-progress detector  ───────────────────────────


class TestNoProgressDetector:
    """AC #2 — parametric over the required envelope shapes; only
    blocked-with-work is skipped by no-progress."""

    @pytest.mark.parametrize(
        "audit_status,worktree_marker,expected_trip",
        [
            ("blocked", "true", False),  # timeout-with-work → skipped
            ("blocked", "false", True),  # legitimate no-progress
            ("blocked", "unknown", True),  # non-git cwd still counts
            ("signed_off", "true", True),  # non-blocked status still counts
            ("blocked", None, True),  # pre-F002 envelope still counts
        ],
    )
    def test_no_progress_parametric(
        self, audit_status: str, worktree_marker: str | None, expected_trip: bool
    ) -> None:
        env = _impl_envelope(audit_status=audit_status, worktree_marker=worktree_marker)
        # prior_status == current_status == "needs_changes" — would normally trip.
        tripped, reason = cb.check_no_progress(
            "needs_changes",
            "needs_changes",
            current_impl_envelope=env,
        )
        assert tripped is expected_trip, (
            f"shape={audit_status},{worktree_marker} expected trip={expected_trip}, "
            f"got tripped={tripped}, reason={reason!r}"
        )

    def test_no_progress_signed_off_envelope_does_not_skip(self) -> None:
        """An auditor-style signed_off envelope passed in (degenerate) should
        not gate the detector — only timeout-with-work does."""
        env = _impl_envelope(audit_status="signed_off", worktree_marker="true")
        tripped, _ = cb.check_no_progress(
            "needs_changes", "needs_changes", current_impl_envelope=env
        )
        assert tripped is True

    def test_no_progress_default_param_preserves_legacy_behavior(self) -> None:
        """Without ``current_impl_envelope``, behavior matches pre-F003."""
        tripped, reason = cb.check_no_progress("needs_changes", "needs_changes")
        assert tripped is True
        assert "needs_changes" in reason

    def test_no_progress_first_round_does_not_trip(self) -> None:
        # prior_status=None → returns (False, "") regardless of envelope shape
        env = _impl_envelope(audit_status="blocked", worktree_marker="false")
        tripped, _ = cb.check_no_progress(None, "needs_changes", current_impl_envelope=env)
        assert tripped is False


# ────────────────────────  diminishing-returns detector  ────────────────────────


class TestDiminishingReturnsDetector:
    """AC #3 — parametric over the same required envelope shapes; only rounds
    with timeout-with-work implementer envelopes are skipped."""

    @pytest.mark.parametrize(
        "audit_status,worktree_marker,expected_trip",
        [
            ("blocked", "true", False),  # both rounds skipped → window empty
            ("blocked", "false", True),  # both rounds count → window full
            ("blocked", "unknown", True),
            ("signed_off", "true", True),
            ("blocked", None, True),
        ],
    )
    def test_diminishing_returns_parametric(
        self,
        tmp_path: Path,
        audit_status: str,
        worktree_marker: str | None,
        expected_trip: bool,
    ) -> None:
        audit_dir = tmp_path / "audit"

        # Build a finding that yields a stable signature so the signature-based
        # path can match across rounds when the rounds DO count.
        pinned_finding = {
            "severity": "high",
            "category": "test_coverage",
            "feature_id": "F001",
            "issue": "persistent finding across rounds — pin signature for DR",
            "evidence": "stable text",
        }

        paths: list[Path] = []
        for i in range(2):
            ip, ap = _write_pair(
                audit_dir,
                i,
                _impl_envelope(
                    audit_status=audit_status,
                    iteration=i,
                    worktree_marker=worktree_marker,
                ),
                _aud_envelope(
                    audit_status="needs_changes",
                    iteration=i,
                    findings=[pinned_finding],
                ),
            )
            paths.append(ip)
            paths.append(ap)

        tripped, reason = cb.check_diminishing_returns(paths)
        assert tripped is expected_trip, (
            f"shape={audit_status},{worktree_marker}: tripped={tripped} "
            f"expected={expected_trip}, reason={reason!r}"
        )

    def test_diminishing_returns_mixed_window_does_not_trip(self, tmp_path: Path) -> None:
        """When iteration 0 is timeout-with-work and iteration 1 is
        blocked-without-work, only one round survives the filter — below the
        2-round threshold, no trip."""
        audit_dir = tmp_path / "audit"
        paths: list[Path] = []
        # iter 0: timeout-with-work (skipped)
        ip0, ap0 = _write_pair(
            audit_dir,
            0,
            _impl_envelope(audit_status="blocked", iteration=0, worktree_marker="true"),
            _aud_envelope(audit_status="needs_changes", iteration=0),
        )
        paths.extend([ip0, ap0])
        # iter 1: legitimate (counts)
        ip1, ap1 = _write_pair(
            audit_dir,
            1,
            _impl_envelope(audit_status="blocked", iteration=1, worktree_marker="false"),
            _aud_envelope(audit_status="needs_changes", iteration=1),
        )
        paths.extend([ip1, ap1])
        tripped, _ = cb.check_diminishing_returns(paths)
        assert tripped is False


# ──────────────────────────  loop history fidelity  ──────────────────────────


class TestLoopHistoryFidelity:
    """AC #4 — every iteration's envelope still appears in audit_paths and on
    disk; only the counters change what they count."""

    def test_all_four_shapes_remain_in_audit_paths(self, tmp_path: Path) -> None:
        audit_dir = tmp_path / "audit"
        shapes = [
            ("blocked", "true"),
            ("blocked", "false"),
            ("blocked", "unknown"),
            ("signed_off", None),
        ]
        paths: list[Path] = []
        for i, (status, marker) in enumerate(shapes):
            ip, ap = _write_pair(
                audit_dir,
                i,
                _impl_envelope(audit_status=status, iteration=i, worktree_marker=marker),
                _aud_envelope(audit_status="needs_changes", iteration=i),
            )
            paths.extend([ip, ap])

        # All four implementer envelopes still readable on disk.
        for i in range(4):
            ip = audit_dir / f"claude-implementer-F001-i{i}.json"
            assert ip.exists(), f"impl envelope for iter {i} missing"
            data = json.loads(ip.read_text())
            assert data["iteration"] == i

        # And the diminishing-returns detector observed all four files (it
        # inspects audit_paths for filtering, not for deletion).
        cb.check_diminishing_returns(paths)
        for p in paths:
            assert p.exists(), f"detector should not mutate audit_paths: {p}"

    def test_all_four_shapes_appear_in_transcript(self, tmp_path: Path) -> None:
        """AC #4 reinforced (audit-focus item 3) — all four envelope shapes,
        including timeout-with-work, must show up as transcript rows so
        operators reading transcript.md after the fact see the full loop
        history. Only the counters change what they count; transcript fidelity
        is total."""
        plan_dir = tmp_path
        shapes = [
            ("blocked", "true", "claude", "implementer"),
            ("blocked", "false", "claude", "implementer"),
            ("blocked", "unknown", "claude", "implementer"),
            ("signed_off", None, "codex", "auditor"),
        ]
        # Write a parallel audit dir so transcript.append_round can compute
        # relative paths back to the audit JSON cleanly.
        audit_dir = plan_dir / "audit"
        for i, (status, marker, agent, role) in enumerate(shapes):
            env = _impl_envelope(audit_status=status, iteration=i, worktree_marker=marker)
            ap = audit_dir / f"{agent}-{role}-F001-i{i}.json"
            ap.parent.mkdir(parents=True, exist_ok=True)
            ap.write_text(json.dumps(env, indent=2))
            transcript.append_round(
                plan_dir=plan_dir,
                feature_id="F001",
                iteration=i,
                agent=agent,
                role=role,
                audit_status=status,
                tokens_in=100,
                tokens_out=50,
                audit_path=ap,
            )
            # Mirror supervisor behavior: append a classifier note when the
            # envelope qualifies as timeout-with-work, so operators reading
            # transcript.md alongside the row see why the round was excluded.
            if cb._envelope_is_timeout_with_work(env):
                transcript.append_note(
                    plan_dir,
                    "F001",
                    iteration=i,
                    note=(
                        "envelope is blocked-with-worktree-changes; not counted "
                        "toward no-progress / diminishing-returns; auditor still "
                        "inspecting landed work"
                    ),
                )

        text = (audit_dir / "transcript.md").read_text()
        # Every iteration must appear as `i<N>` somewhere in the transcript —
        # timeout-with-work rounds are NOT silently dropped.
        for i in range(4):
            assert f"i{i}" in text, (
                f"iteration {i} missing from transcript.md; loop history fidelity violated:\n{text}"
            )
        # The status strings for each shape must also appear.
        for status in ("blocked", "signed_off"):
            assert status in text, f"status {status!r} missing from transcript.md"
        # Timeout-with-work iteration (i=0) gets the classifier note line.
        assert "blocked-with-worktree-changes" in text, (
            "timeout-with-work classification note missing from transcript.md; "
            "operators relying on transcript visibility lose the signal"
        )


# ─────────────────────────  synthetic volley scaffolding  ─────────────────────────


class _ScriptedExecutor(BaseExecutor):
    """Minimal scripted executor — no real CLI, configurable per-call."""

    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.received_tasks: list[DispatchTask] = []

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.received_tasks.append(task)
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=f"[scripted {self.agent_name}/{task.agent_role}] iter={task.iteration}",
            model_version="scripted-vN",
            raw_response=f"role={task.agent_role}",
            quota_consumed={"tokens_in": 100, "tokens_out": 50},
        )


def _make_test_plan(tmp_dir: Path) -> Path:
    plan_id = "2026-05-04-003-infra-test-classifier"
    plan_dir = tmp_dir / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)

    plan_md = """---
id: 2026-05-04-003-infra-test-classifier
title: F003 classifier synthetic test plan
type: infra
tier: trivial
status: active
date: "2026-05-04"
description: Synthetic plan exercising the F003 timeout-with-work classifier path.
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

# F003 classifier synthetic plan

## Target

```yaml
target_env: dev
target_project: none
```
"""
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001",
                "category": "test",
                "phase": 0,
                "description": "Synthetic feature exercising the F003 classifier path.",
                "steps": ["scripted impl", "scripted aud"],
                "acceptance": "Volley terminates with the expected status under classifier rules.",
                "passes": False,
                "depends_on": [],
            }
        ],
    }

    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(json.dumps(features, indent=2) + "\n")
    return plan_dir


def _disable_quota_gate() -> None:
    supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed for F003 test")


def _patch_run_round_to_force_envelope(
    *,
    impl_audit_status: str,
    impl_worktree_marker: str | None,
    aud_audit_status: str,
    aud_findings_per_iter: list[list[dict[str, Any]]] | None = None,
) -> None:
    """Wrap supervisor._run_round so that after each round the freshly-written
    envelope is rewritten to the scripted shape. This mirrors
    test_volley_synthetic.py's `_patch_supervisor_to_force_status` pattern but
    handles BOTH roles: implementer envelope gets timeout markers; auditor
    envelope gets the scripted verdict.

    ``aud_findings_per_iter`` (optional): when supplied, the auditor envelope
    for iteration i is rewritten with ``aud_findings_per_iter[i]``. Used to
    decouple no-progress (status-identity) from diminishing-returns
    (finding-signature identity): different findings per round let no-progress
    trip while DR's window stays unmatched. Default keeps the in-built single
    finding stable across rounds.
    """
    orig = supervisor._run_round

    def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
        path = orig(*args, **kwargs)
        role = kwargs.get("role")
        iteration_idx = kwargs.get("iteration", 0)
        data = json.loads(path.read_text())
        if role == "implementer":
            data["audit_status"] = impl_audit_status
            markers = list(data.get("validation_performed") or [])
            # Drop any pre-existing worktree marker (defensive — shouldn't
            # exist on a real success-path scripted run, but the test scripts
            # we feed in shouldn't trigger that anyway).
            markers = [m for m in markers if not m.startswith("worktree_changed=")]
            if impl_worktree_marker is not None:
                markers.append(f"worktree_changed={impl_worktree_marker}")
                markers.append("subprocess_timeout_seconds=600")
            data["validation_performed"] = markers
        elif role == "auditor":
            data["audit_status"] = aud_audit_status
            if aud_findings_per_iter is not None and iteration_idx < len(aud_findings_per_iter):
                data["findings"] = aud_findings_per_iter[iteration_idx]
        path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    supervisor._run_round = wrapped


def _restore_supervisor() -> None:
    """Re-bind ``_run_round`` from the live module without touching
    ``sys.modules`` (Plan A/B test-isolation discipline — AC #10)."""
    import importlib

    importlib.reload(supervisor)


def _register_scripted() -> tuple[_ScriptedExecutor, _ScriptedExecutor]:
    impl = _ScriptedExecutor("claude")
    aud = _ScriptedExecutor("codex")
    AGENT_REGISTRY["claude"] = lambda i=impl: i  # type: ignore[assignment]
    AGENT_REGISTRY["codex"] = lambda a=aud: a  # type: ignore[assignment]
    return impl, aud


# ─────────────────────────────  Plan B retroactive  ─────────────────────────────


class TestPlanBRetroactive:
    """AC #5 + #6 — Plan-B-shaped run terminates at stopped_cap; legitimate
    no-progress run still terminates at stopped_no_progress."""

    def test_plan_b_shape_terminates_at_stopped_cap(self) -> None:
        """Both rounds: timeout-with-work + auditor needs_changes. With Plan C's
        classifier, no-progress and diminishing-returns are skipped both rounds,
        and the volley walks off the end at iteration_cap → stopped_cap."""
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_test_plan(Path(td))
            _disable_quota_gate()
            _patch_run_round_to_force_envelope(
                impl_audit_status="blocked",
                impl_worktree_marker="true",
                aud_audit_status="needs_changes",
            )
            try:
                _register_scripted()
                result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=2)
            finally:
                _restore_supervisor()

            assert result.final_status == "stopped_cap", (
                f"Plan-B-shaped run should terminate at stopped_cap, "
                f"got {result.final_status!r} reason={result.reason!r}"
            )

    def test_legitimate_no_progress_still_terminates_stopped_no_progress(self) -> None:
        """Both rounds: blocked-without-worktree-changes + auditor needs_changes.
        F003 must NOT over-correct: this is the original correct trip path.

        AC #6 requires *exact* `stopped_no_progress` — diminishing_returns is a
        separate trip with its own semantic (signature-identity collapse). To
        isolate no-progress (status-identity), this test gives each round a
        DIFFERENT finding signature so DR's window stays unmatched and the
        supervisor falls through to the no-progress check.
        """
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_test_plan(Path(td))
            _disable_quota_gate()
            _patch_run_round_to_force_envelope(
                impl_audit_status="blocked",
                impl_worktree_marker="false",
                aud_audit_status="needs_changes",
                aud_findings_per_iter=[
                    [
                        {
                            "severity": "high",
                            "category": "correctness",
                            "feature_id": "F001",
                            "issue": "round-0 distinct issue text",
                            "evidence": "evidence-0",
                        }
                    ],
                    [
                        {
                            "severity": "high",
                            "category": "correctness",
                            "feature_id": "F001",
                            "issue": "round-1 distinct issue text",
                            "evidence": "evidence-1",
                        }
                    ],
                    [
                        {
                            "severity": "high",
                            "category": "correctness",
                            "feature_id": "F001",
                            "issue": "round-2 distinct issue text",
                            "evidence": "evidence-2",
                        }
                    ],
                ],
            )
            try:
                _register_scripted()
                result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=2)
            finally:
                _restore_supervisor()

            assert result.final_status == "stopped_no_progress", (
                f"blocked-without-work both rounds with distinct findings must "
                f"terminate at stopped_no_progress (the status-identity trip); "
                f"got {result.final_status!r} reason={result.reason!r}"
            )


# ──────────────  prior_aud_status carry-over (audit-focus item 1)  ──────────────


class TestPriorAudStatusCarryOver:
    """Audit-focus item 1 — a skipped timeout-with-work round must NOT establish
    the no-progress baseline for the next round. Encoded by walking
    iteration-0 = timeout-with-work, iteration-1 = legitimate
    blocked-without-work, iteration-2 = same. Without the carry-over fix, the
    no-progress baseline would be set by iter-0 and trip on iter-1; with the
    fix, iter-1 establishes the baseline and iter-2 trips, both legitimate
    countable rounds."""

    def test_timeout_with_work_round_does_not_advance_baseline(self) -> None:
        """When iteration 0 is timeout-with-work and iterations 1 & 2 are
        legitimate, no-progress trips on the *second* legitimate round, not
        the first — proving the timeout-with-work round did not set the
        baseline. Findings differ across iterations so DR cannot trip first."""
        # Custom patch wrapping `_run_round` per-iteration: iter 0 = TWW, iters
        # 1+ = legitimate.
        orig = supervisor._run_round
        seen_iters: list[int] = []

        def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
            path = orig(*args, **kwargs)
            role = kwargs.get("role")
            i = kwargs.get("iteration", 0)
            data = json.loads(path.read_text())
            if role == "implementer":
                seen_iters.append(i)
                data["audit_status"] = "blocked"
                markers = list(data.get("validation_performed") or [])
                markers = [m for m in markers if not m.startswith("worktree_changed=")]
                # iter 0 = timeout-with-work; subsequent iterations = legitimate.
                marker = "true" if i == 0 else "false"
                markers.append(f"worktree_changed={marker}")
                markers.append("subprocess_timeout_seconds=600")
                data["validation_performed"] = markers
            elif role == "auditor":
                data["audit_status"] = "needs_changes"
                # Distinct findings per iter so DR's signature window cannot
                # match — isolates the no-progress (status-identity) detector.
                data["findings"] = [
                    {
                        "severity": "high",
                        "category": "correctness",
                        "feature_id": "F001",
                        "issue": f"distinct issue text for iter {i}",
                        "evidence": f"evidence-{i}",
                    }
                ]
            path.write_text(json.dumps(data, indent=2) + "\n")
            return path

        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_test_plan(Path(td))
            _disable_quota_gate()
            supervisor._run_round = wrapped
            try:
                _register_scripted()
                # max_iterations=2 → loop runs iters 0, 1, 2 (range(cap+1)).
                # iter 0 TWW → no-progress skipped, baseline NOT advanced.
                # iter 1 legit → no-progress sees prior=None → no trip; baseline = needs_changes.
                # iter 2 legit → no-progress sees prior=needs_changes → trip!
                result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=2)
            finally:
                _restore_supervisor()

            assert result.final_status == "stopped_no_progress", (
                f"Expected stopped_no_progress on iter 2 (after iter-1 baseline), "
                f"got {result.final_status!r} reason={result.reason!r} "
                f"impl iters seen: {seen_iters}"
            )
            # And specifically: the trip must be on iteration 3 (i.e., the
            # third countable round), confirming the TWW round did not
            # contribute to the count. result.rounds is iteration+1 at trip.
            assert result.rounds == 3, (
                f"Expected trip after 3 rounds total (TWW + 2 legit), got rounds={result.rounds}"
            )


# ───────────────────────────  auditor still invoked  ───────────────────────────


class TestAuditorStillInvoked:
    """AC #8 — when timeout-with-work envelope is produced, the auditor is
    STILL invoked next; the new classifier doesn't gate auditor execution."""

    def test_auditor_dispatched_after_timeout_with_work(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_test_plan(Path(td))
            _disable_quota_gate()
            _patch_run_round_to_force_envelope(
                impl_audit_status="blocked",
                impl_worktree_marker="true",
                aud_audit_status="needs_changes",
            )
            try:
                impl, aud = _register_scripted()
                result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=2)
            finally:
                _restore_supervisor()

            # Auditor was dispatched once per implementer call — the new
            # classifier does NOT gate auditor invocation. The volley walks
            # all max_iterations+1 rounds before stopped_cap fires (existing
            # supervisor loop semantics: range(cap + 1)).
            impl_calls = sum(1 for t in impl.received_tasks if t.agent_role == "implementer")
            aud_calls = sum(1 for t in aud.received_tasks if t.agent_role == "auditor")
            assert impl_calls == aud_calls, (
                f"auditor invocation must mirror implementer (no gating); "
                f"got impl={impl_calls} aud={aud_calls}; "
                f"final_status={result.final_status}"
            )
            assert impl_calls >= 2, (
                f"expected at least 2 iterations to confirm the auditor was "
                f"called even after the first timeout-with-work envelope; "
                f"got impl={impl_calls}"
            )


# ──────────────────────────  transcript visibility  ──────────────────────────


class TestTranscriptVisibility:
    """AC #9 — a timeout-with-work iteration produces a clear transcript line
    so operators reading transcripts after the fact see the signal without
    parsing envelope JSON."""

    def test_transcript_note_appended_for_timeout_with_work(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_test_plan(Path(td))
            _disable_quota_gate()
            _patch_run_round_to_force_envelope(
                impl_audit_status="blocked",
                impl_worktree_marker="true",
                aud_audit_status="needs_changes",
            )
            try:
                _register_scripted()
                supervisor.dispatch_volley(plan_dir, "F001", max_iterations=2)
            finally:
                _restore_supervisor()

            transcript_path = plan_dir / "audit" / "transcript.md"
            assert transcript_path.exists(), "transcript.md should be written by the volley"
            text = transcript_path.read_text()
            assert "blocked-with-worktree-changes" in text, (
                "transcript should announce the F003 classification for "
                f"operator visibility; got:\n{text}"
            )
            assert "auditor still inspecting landed work" in text

    def test_append_note_helper_writes_to_transcript(self, tmp_path: Path) -> None:
        """Direct unit test of transcript.append_note — independent of the
        supervisor wiring."""
        transcript.append_note(tmp_path, "F001", iteration=0, note="hello F003")
        text = (tmp_path / "audit" / "transcript.md").read_text()
        assert "hello F003" in text
        assert "iter=0" in text
        assert "F001" in text


# ────────────────────────  boundary discipline (D008)  ────────────────────────


class TestBoundaryDiscipline:
    """AC #7 + #15 — F003's circuit_breakers.py diff carries ONLY the classifier
    logic; no terminal-status string movement, no breaker enum change, no
    threshold default shifts; no new audit_status enum values."""

    def test_terminal_status_strings_unchanged(self) -> None:
        """The terminal-status enum values F003 must not move."""
        assert cb.TERMINAL_STATUS[cb.BreakerKind.NO_PROGRESS] == "stopped_no_progress"
        assert (
            cb.TERMINAL_STATUS[cb.BreakerKind.DIMINISHING_RETURNS] == "stopped_diminishing_returns"
        )
        assert cb.TERMINAL_STATUS[cb.BreakerKind.ITERATION_CAP] == "stopped_cap"
        assert cb.TERMINAL_STATUS[cb.BreakerKind.WALL_CLOCK] == "stopped_wall_clock"
        assert cb.TERMINAL_STATUS[cb.BreakerKind.BUDGET_CEILING] == "stopped_budget"
        assert (
            cb.TERMINAL_STATUS[cb.BreakerKind.CONVERGENCE_COLLAPSE]
            == "stopped_convergence_collapse"
        )
        assert cb.TERMINAL_STATUS[cb.BreakerKind.GLOBAL_CIRCUIT_BREAKER] == "stopped_global_breaker"

    def test_breaker_kind_enum_values_unchanged(self) -> None:
        assert {k.value for k in cb.BreakerKind} == {
            "iteration_cap",
            "budget_ceiling",
            "wall_clock",
            "no_progress",
            "diminishing_returns",
            "convergence_collapse",
            "global_circuit_breaker",
        }

    def test_threshold_defaults_unchanged(self) -> None:
        """F003 does not move thresholds (D008)."""
        assert cb.DIMINISHING_RETURNS_MIN_ROUNDS == 2
        assert cb.CONVERGENCE_COLLAPSE_WINDOW == 3
        assert cb.GLOBAL_THRESHOLD_HITS == 3

    def test_circuit_breakers_diff_scoped_to_classifier(self) -> None:
        """AC #7 — `git diff` on circuit_breakers.py contains only logic
        changes tied to the timeout-with-work classifier; no diff lines that
        touch terminal-status string literals, breaker enum values, threshold
        defaults, or no_progress_threshold arithmetic.

        The check looks at lines added by the F003 working-tree diff (HEAD vs.
        worktree). It is intentionally textual — operators reading the diff
        in code review should see only classifier changes."""
        repo_root = Path(__file__).resolve().parents[3]
        try:
            diff = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "diff",
                    "HEAD",
                    "--",
                    "scripts/dontpanic_orchestrate/circuit_breakers.py",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            pytest.skip("git not available — diff scope check skipped")
            return
        if diff.returncode != 0:
            pytest.skip(f"git diff failed: {diff.stderr.strip()}")
            return

        # Quoted-literal patterns target actual code (TERMINAL_STATUS mapping
        # values, enum string assignments) — NOT prose mentions in docstrings.
        # The classifier's own docstring legitimately references stopped_cap /
        # stopped_no_progress as Plan B context; that's not a status MOVE.
        forbidden_patterns = [
            '"stopped_no_progress"',
            '"stopped_diminishing_returns"',
            '"stopped_cap"',
            '"stopped_wall_clock"',
            '"stopped_budget"',
            '"stopped_convergence_collapse"',
            '"stopped_global_breaker"',
            "DIMINISHING_RETURNS_MIN_ROUNDS =",
            "CONVERGENCE_COLLAPSE_WINDOW =",
            "GLOBAL_THRESHOLD_HITS =",
            "GLOBAL_WINDOW_SECONDS =",
            "DEFAULT_WALL_CLOCK_HOURS =",
            "DEFAULT_BUDGET_PERCENT_CAP =",
            "no_progress_threshold=",
        ]
        # Look only at lines added/removed by F003 (start with + or -, not
        # ++/-- diff headers).
        offending: list[tuple[str, str]] = []
        for line in diff.stdout.splitlines():
            if not line or line.startswith("+++") or line.startswith("---"):
                continue
            if not (line.startswith("+") or line.startswith("-")):
                continue
            for pat in forbidden_patterns:
                if pat in line:
                    offending.append((pat, line))
        assert not offending, (
            "F003 circuit_breakers.py diff touched protected terminal-status / "
            "enum / threshold lines:\n" + "\n".join(f"  [{pat}] {ln}" for pat, ln in offending)
        )

    def test_no_new_audit_status_enum_values(self) -> None:
        """AC #15 — F003 introduces no new audit_status enum values."""
        # Importing audit_writer first ensures the agent-conventions schema
        # candidates path is on sys.path before models.audit_model loads.
        from models.audit_model import AuditStatus  # type: ignore[import]

        from dontpanic_orchestrate import audit_writer  # noqa: F401

        valid = {
            "signed_off",
            "needs_changes",
            "blocked",
            "inconclusive",
            "redaction_required",
        }
        observed = {s.value for s in AuditStatus}
        assert observed == valid, f"audit_status enum drifted: {observed} vs expected {valid}"
