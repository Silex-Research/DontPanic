"""Plan 2026-05-12-001 v4 F004 — supervisor iter-checkpoint artifacts (D025
root cause #2).

Covers the four acceptance criteria:

  (1) Every iter wrapped with try/except + checkpoint write.
  (2) Synthetic-crash fixture produces a ``terminal-state-iter{N}.json``
      artifact with the expected shape.
  (3) Dispatch always returns a clean exit code (no unhandled exceptions).
  (4) Operator-recovery instructions embedded in the checkpoint payload.

Pairs with the plan 004 F002 retrospective: replay the orphaned-implementer-
envelope crash mode and verify the checkpoint includes pointers to the
orphaned envelope plus the shlex parse-error context.

Run:
  PYTHONPATH=scripts pytest \\
    scripts/dontpanic_orchestrate/tests/test_iter_checkpoint_f004.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import auditor_taxonomy, supervisor  # noqa: E402


# ──────────────────────────────  _write_iter_checkpoint helper  ──────────────────────────────


def test_write_iter_checkpoint_records_stage_and_recovery_command(tmp_path: Path) -> None:
    """Acceptance #4: the checkpoint payload embeds the operator-resolved
    close-out command with the actual plan_id + feature_id substituted, so
    the operator can copy-paste it verbatim instead of hand-editing a
    template."""
    print("\n[test] write_iter_checkpoint_records_stage_and_recovery_command ...")
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    target = supervisor._write_iter_checkpoint(
        plan_dir=plan_dir,
        feature_id="F004",
        iteration=0,
        stage="auditor",
        exception=RuntimeError("synthetic auditor crash"),
        last_good_paths=[plan_dir / "audit" / "claude-implementer-F004-i0.json"],
        plan_id="2026-05-12-001-fix-harness-frictions-v4",
    )
    assert target is not None
    assert target.name == "terminal-state-iter0.json"
    payload = json.loads(target.read_text())
    # Acceptance #2 — expected shape.
    assert payload["schema"] == "terminal-state.v0"
    assert payload["feature_id"] == "F004"
    assert payload["iteration"] == 0
    assert payload["stage"] == "auditor"
    assert payload["exception_class"] == "RuntimeError"
    assert "synthetic auditor crash" in payload["exception_message"]
    # Acceptance #2 — last-good evidence pointers preserved.
    assert payload["audit_paths"] == [
        str(plan_dir / "audit" / "claude-implementer-F004-i0.json")
    ]
    assert payload["last_good_audit_path"] == str(
        plan_dir / "audit" / "claude-implementer-F004-i0.json"
    )
    # Acceptance #4 — operator-resolved command embedded verbatim.
    expected_cmd = (
        "dontpanic close --operator-resolved "
        "2026-05-12-001-fix-harness-frictions-v4 F004 "
        "--reason environmental_reproduction_failure"
    )
    assert payload["recommended_command"] == expected_cmd
    assert payload["recommended_recovery"] == expected_cmd
    assert payload["plan_id"] == "2026-05-12-001-fix-harness-frictions-v4"
    # Audit-trail discipline: ``written_at`` is RFC3339 UTC.
    assert payload["written_at"].endswith("Z")
    dt.datetime.strptime(payload["written_at"], "%Y-%m-%dT%H:%M:%SZ")
    print("  ✓ checkpoint payload: stage + last-good path + plan-id-bound recovery command")


def test_write_iter_checkpoint_records_recovery_notes(tmp_path: Path) -> None:
    """Acceptance #4: ``recovery_notes`` is a free-text addendum the caller
    uses to point at the orphaned implementer envelope or capture the parse-
    error context. The supervisor's F004 backstop populates it; tests below
    rely on the field being round-tripped."""
    print("\n[test] write_iter_checkpoint_records_recovery_notes ...")
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    target = supervisor._write_iter_checkpoint(
        plan_dir=plan_dir,
        feature_id="F004",
        iteration=1,
        stage="auditor",
        exception=OSError("schema not found"),
        last_good_paths=[plan_dir / "audit" / "claude-implementer-F004-i1.json"],
        plan_id="plan-xyz",
        recovery_notes="implementer envelope at <path>; shlex context: ...",
    )
    assert target is not None
    payload = json.loads(target.read_text())
    assert (
        payload["recovery_notes"]
        == "implementer envelope at <path>; shlex context: ..."
    )
    print("  ✓ recovery_notes round-trips through the helper")


def test_write_iter_checkpoint_handles_empty_last_good_paths(tmp_path: Path) -> None:
    """When the implementer never landed an envelope (e.g. iter_setup or
    implementer-quota stage crashed before _run_round wrote anything),
    ``last_good_audit_path`` is None instead of crashing the helper."""
    print("\n[test] write_iter_checkpoint_handles_empty_last_good_paths ...")
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    target = supervisor._write_iter_checkpoint(
        plan_dir=plan_dir,
        feature_id="F004",
        iteration=0,
        stage="implementer",
        exception=RuntimeError("crash before envelope"),
        last_good_paths=[],
        plan_id="plan-xyz",
    )
    assert target is not None
    payload = json.loads(target.read_text())
    assert payload["audit_paths"] == []
    assert payload["last_good_audit_path"] is None
    assert payload["stage"] == "implementer"
    print("  ✓ empty last_good_paths → last_good_audit_path=None, no crash")


def test_write_iter_checkpoint_swallows_oserror(tmp_path: Path, monkeypatch) -> None:
    """Best-effort: an OSError during the disk write must not propagate, so
    the caller's transcript + INBOX + signoff steps still execute."""
    print("\n[test] write_iter_checkpoint_swallows_oserror ...")
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    monkeypatch.setattr(
        "pathlib.Path.write_text",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("readonly")),
    )
    result = supervisor._write_iter_checkpoint(
        plan_dir=plan_dir,
        feature_id="F004",
        iteration=0,
        stage="post_iter",
        exception=KeyError("verdict"),
        last_good_paths=[],
        plan_id="plan-xyz",
    )
    assert result is None
    print("  ✓ OSError during write returns None instead of propagating")


def test_legacy_write_backstop_checkpoint_defaults_stage(tmp_path: Path) -> None:
    """Backward compat with F003: callers that pass no ``stage`` still get a
    valid payload (stage defaults to ``iter_loop_backstop``)."""
    print("\n[test] legacy_write_backstop_checkpoint_defaults_stage ...")
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    target = supervisor._write_backstop_checkpoint(
        plan_dir=plan_dir,
        feature_id="F003",
        iteration=0,
        exception=ValueError("No closing quotation"),
        audit_paths=[],
    )
    assert target is not None
    payload = json.loads(target.read_text())
    assert payload["stage"] == "iter_loop_backstop"
    # Legacy recommendation token preserved.
    assert "operator-resolved" in payload["recommended_recovery"]
    print("  ✓ legacy F003 caller: stage defaults to iter_loop_backstop")


# ──────────────────────────────  dispatch_volley per-stage F004 backstop  ──────────────────────────────


def _make_f004_plan(tmp: Path) -> Path:
    """Synthetic plan dir modeled on test_shlex_safe_command_guard_f003.py so
    it threads cleanly through plan_loader + gate/admission machinery."""
    plan_id = "2026-05-12-003-infra-test-f004"
    plan_dir = tmp / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F004 synthetic
type: infra
tier: trivial
status: active
date: "2026-05-12"
description: F004 synthetic.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---
# F004 synthetic

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
                        "description": "Synthetic feature for F004 backstop test.",
                        "steps": ["scripted"],
                        "acceptance": "F004 backstop fires per stage.",
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


class _FakeExecutor:
    """Stub executor so dispatch_volley doesn't try to resolve real CLIs."""

    binary = "fake"

    def is_available(self) -> bool:
        return True

    def availability_hint(self) -> str:
        return "stubbed for test"


def _silence_supervisor_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass the I/O bits dispatch_volley reaches for outside the iter body
    (quota gate, notify sinks, executor resolution). Each test installs its
    own ``_run_round`` mock on top of this baseline."""
    monkeypatch.setattr(
        supervisor, "_quota_gate", lambda agent: (None, f"[quota] {agent}: bypassed for test")
    )
    monkeypatch.setattr(supervisor, "_resolve_executor", lambda name: _FakeExecutor())
    monkeypatch.setattr(supervisor.notify, "notify", lambda **kw: None)
    monkeypatch.setattr(supervisor.notify_event, "dispatch_event", lambda *_a, **_kw: None)


def test_dispatch_volley_catches_runtime_error_in_implementer_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance #1 + #2 + #3: a non-ValueError exception raised inside the
    implementer round (first ``_run_round`` call) is caught by the F004
    backstop, the volley returns a clean ``blocked`` terminal, and the
    ``terminal-state-iter0.json`` checkpoint records stage=implementer."""
    print("\n[test] dispatch_volley_catches_runtime_error_in_implementer_stage ...")
    plan_dir = _make_f004_plan(tmp_path)

    def _raise_runtime_error(*_a, **_kw):
        raise RuntimeError("synthetic implementer crash")

    _silence_supervisor_side_effects(monkeypatch)
    monkeypatch.setattr(supervisor, "_run_round", _raise_runtime_error)

    result = supervisor.dispatch_volley(plan_dir=plan_dir, feature_id="F001")

    # No exception propagated (acceptance #3).
    assert result.final_status == "blocked", result.final_status
    assert "F004 backstop" in result.reason, result.reason
    assert "stage=implementer" in result.reason, result.reason
    assert "RuntimeError" in result.reason, result.reason

    # Acceptance #2 — checkpoint artifact written with stage=implementer.
    checkpoint = plan_dir / "audit" / "terminal-state-iter0.json"
    assert checkpoint.is_file(), f"expected F004 checkpoint at {checkpoint}"
    payload = json.loads(checkpoint.read_text())
    assert payload["stage"] == "implementer", payload
    assert payload["exception_class"] == "RuntimeError", payload
    assert "synthetic implementer crash" in payload["exception_message"], payload
    # Implementer never landed — last_good_audit_path is None.
    assert payload["audit_paths"] == [], payload
    assert payload["last_good_audit_path"] is None, payload
    # Acceptance #4 — recovery command embeds the real plan_id.
    assert "2026-05-12-003-infra-test-f004" in payload["recommended_command"]
    assert "operator-resolved" in payload["recommended_command"]
    print("  ✓ RuntimeError in implementer stage → clean blocked + stage=implementer checkpoint")


def test_dispatch_volley_catches_runtime_error_in_auditor_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance #1 + #2 + #3 + #4: a non-ValueError exception raised inside
    the auditor round (second ``_run_round`` call, AFTER the implementer
    envelope landed) is caught, the volley returns a clean ``blocked``
    terminal, and the checkpoint records stage=auditor + a pointer to the
    orphaned implementer envelope as ``last_good_audit_path``. This is the
    exact retrospective the plan calls out: D025 left the implementer
    envelope orphaned with no auditor record."""
    print("\n[test] dispatch_volley_catches_runtime_error_in_auditor_stage ...")
    plan_dir = _make_f004_plan(tmp_path)

    impl_envelope_path = plan_dir / "audit" / "claude-implementer-F001-i0.json"

    call_count = {"n": 0}

    def _impl_then_auditor_crash(*args, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: implementer round. Land an envelope on disk so
            # the F004 checkpoint can point at it as last_good_audit_path,
            # then return the path the same way _run_round would.
            impl_envelope_path.parent.mkdir(parents=True, exist_ok=True)
            impl_envelope_path.write_text(
                json.dumps(
                    {
                        "schema": "audit.v1",
                        "agent": "claude",
                        "agent_role": "implementer",
                        "iteration": 0,
                        "audit_status": "signed_off",
                        "findings": [],
                        "summary": "Repo: DontPanic\nEnv: dev\nProject: (none)\nDone.",
                        "target_context": {
                            "env": "dev",
                            "project": None,
                            "commands_run": [],
                        },
                    },
                    indent=2,
                )
            )
            return impl_envelope_path
        # Second call: auditor round. Raise a non-ValueError that bypasses
        # the F003 ValueError clause and lands in the F004 broad-Exception
        # clause.
        raise RuntimeError("synthetic auditor crash mid-volley")

    _silence_supervisor_side_effects(monkeypatch)
    monkeypatch.setattr(supervisor, "_run_round", _impl_then_auditor_crash)

    result = supervisor.dispatch_volley(plan_dir=plan_dir, feature_id="F001")

    # Acceptance #3 — no propagation.
    assert result.final_status == "blocked", result.final_status
    assert "F004 backstop" in result.reason, result.reason
    assert "stage=auditor" in result.reason, result.reason

    # Acceptance #2 — checkpoint shape.
    checkpoint = plan_dir / "audit" / "terminal-state-iter0.json"
    assert checkpoint.is_file(), f"expected F004 checkpoint at {checkpoint}"
    payload = json.loads(checkpoint.read_text())
    assert payload["stage"] == "auditor", payload
    assert payload["exception_class"] == "RuntimeError", payload
    assert "synthetic auditor crash mid-volley" in payload["exception_message"], payload

    # Acceptance #2 (retrospective): the orphaned implementer envelope path
    # is recorded in last_good_audit_path / audit_paths so the operator can
    # locate the work the volley landed before the auditor crashed.
    assert payload["last_good_audit_path"] == str(impl_envelope_path), payload
    assert str(impl_envelope_path) in payload["audit_paths"], payload

    # Acceptance #4 — recovery hints.
    assert payload["plan_id"] == "2026-05-12-003-infra-test-f004", payload
    assert "operator-resolved" in payload["recommended_command"], payload
    assert "2026-05-12-003-infra-test-f004" in payload["recommended_command"], payload
    assert "F001" in payload["recommended_command"], payload
    # recovery_notes points at the orphan + names the stage.
    assert "auditor" in payload["recovery_notes"], payload
    print(
        "  ✓ RuntimeError in auditor stage → clean blocked + stage=auditor checkpoint "
        "with last_good pointing at orphaned implementer envelope"
    )


def test_dispatch_volley_catches_oserror_in_post_iter_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance #1 + #2 + #3: an OSError raised during the post-auditor
    processing (after both ``_run_round`` calls land envelopes) is caught
    and recorded with stage=post_iter. We synthesize the crash by patching
    ``auditor_taxonomy.detect_verdict_mismatch`` to raise OSError, which
    fires after the auditor envelope is on disk."""
    print("\n[test] dispatch_volley_catches_oserror_in_post_iter_stage ...")
    plan_dir = _make_f004_plan(tmp_path)

    impl_envelope_path = plan_dir / "audit" / "claude-implementer-F001-i0.json"
    aud_envelope_path = plan_dir / "audit" / "codex-auditor-F001-i0.json"

    call_count = {"n": 0}

    def _both_succeed(*_a, **_kw):
        call_count["n"] += 1
        target = impl_envelope_path if call_count["n"] == 1 else aud_envelope_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "schema": "audit.v1",
                    "agent": "claude" if call_count["n"] == 1 else "codex",
                    "agent_role": "implementer" if call_count["n"] == 1 else "auditor",
                    "iteration": 0,
                    "audit_status": "signed_off",
                    "findings": [],
                    "summary": "Repo: DontPanic\nEnv: dev\nProject: (none)\nDone.",
                    "target_context": {
                        "env": "dev",
                        "project": None,
                        "commands_run": [],
                    },
                },
                indent=2,
            )
        )
        return target

    _silence_supervisor_side_effects(monkeypatch)
    monkeypatch.setattr(supervisor, "_run_round", _both_succeed)
    # Raise from the post-auditor pipeline (verdict-mismatch detector is the
    # first thing the supervisor calls after writing the auditor envelope).
    monkeypatch.setattr(
        supervisor.auditor_taxonomy,
        "detect_verdict_mismatch",
        lambda **kw: (_ for _ in ()).throw(OSError("synthetic post-iter OSError")),
    )

    result = supervisor.dispatch_volley(plan_dir=plan_dir, feature_id="F001")

    assert result.final_status == "blocked", result.final_status
    assert "F004 backstop" in result.reason, result.reason
    assert "stage=post_iter" in result.reason, result.reason

    checkpoint = plan_dir / "audit" / "terminal-state-iter0.json"
    assert checkpoint.is_file(), f"expected F004 checkpoint at {checkpoint}"
    payload = json.loads(checkpoint.read_text())
    assert payload["stage"] == "post_iter", payload
    assert payload["exception_class"] == "OSError", payload
    # Both envelopes landed before the crash — the auditor one is the last
    # successful write.
    assert payload["last_good_audit_path"] == str(aud_envelope_path), payload
    assert str(impl_envelope_path) in payload["audit_paths"], payload
    assert str(aud_envelope_path) in payload["audit_paths"], payload
    print("  ✓ OSError in post-iter stage → clean blocked + stage=post_iter checkpoint")


def test_dispatch_volley_reraises_verdict_mismatch_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan 2026-05-09-002 F001 designed the verdict-mismatch detector to
    fail loud (raise after writing INBOX events). The F004 broad-Exception
    catch MUST NOT swallow it — that would silently downgrade a contract
    violation to a generic blocked terminal. Mirror the F003 backstop's
    TargetContextError carve-out for this Exception subclass."""
    print("\n[test] dispatch_volley_reraises_verdict_mismatch_error ...")
    plan_dir = _make_f004_plan(tmp_path)

    call_count = {"n": 0}

    def _both_succeed(*_a, **_kw):
        call_count["n"] += 1
        target = plan_dir / "audit" / (
            "claude-implementer-F001-i0.json"
            if call_count["n"] == 1
            else "codex-auditor-F001-i0.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "schema": "audit.v1",
                    "agent": "claude" if call_count["n"] == 1 else "codex",
                    "agent_role": "implementer" if call_count["n"] == 1 else "auditor",
                    "iteration": 0,
                    "audit_status": "signed_off",
                    "findings": [],
                    "summary": "Repo: DontPanic\nEnv: dev\nProject: (none)\nDone.",
                    "target_context": {
                        "env": "dev",
                        "project": None,
                        "commands_run": [],
                    },
                },
                indent=2,
            )
        )
        return target

    def _detector_returns_mismatch(**_kw):
        # The production detector RETURNS a populated ``VerdictMismatchError``;
        # the supervisor raises it after writing an INBOX event. Mirror that
        # contract — the F004 broad-Exception catch must propagate the raise.
        return auditor_taxonomy.VerdictMismatchError(
            plan_id="2026-05-12-003-infra-test-f004",
            feature_id="F001",
            iteration=0,
            audit_path=plan_dir / "audit" / "codex-auditor-F001-i0.json",
            narrative_verdict="signed_off",
            structured_status="needs_changes",
            remediation="(test) reconcile narrative vs structured verdict",
        )

    _silence_supervisor_side_effects(monkeypatch)
    monkeypatch.setattr(supervisor, "_run_round", _both_succeed)
    monkeypatch.setattr(
        supervisor.auditor_taxonomy,
        "detect_verdict_mismatch",
        _detector_returns_mismatch,
    )

    with pytest.raises(auditor_taxonomy.VerdictMismatchError):
        supervisor.dispatch_volley(plan_dir=plan_dir, feature_id="F001")

    # No F004 checkpoint should land for this contract-violation re-raise.
    checkpoint = plan_dir / "audit" / "terminal-state-iter0.json"
    assert not checkpoint.exists(), (
        f"F004 backstop should not write a checkpoint when VerdictMismatchError "
        f"is propagated; found {checkpoint}"
    )
    print("  ✓ VerdictMismatchError propagates past F004 backstop; no checkpoint written")


def test_dispatch_volley_f003_value_error_path_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: adding the F004 broad-Exception catch must not steal
    ValueError catches from the F003 backstop. A ValueError raised inside
    the iter body should still produce the F003 ``F003 backstop`` reason
    + the legacy ``stage='iter_loop_backstop'`` payload. (The F003 test
    suite already covers this; we re-assert here because F004 placed its
    except clause adjacent to F003's, and python's exception dispatch is
    order-sensitive — ValueError is an Exception subclass, so a misordering
    would silently shadow the F003 clause.)"""
    print("\n[test] dispatch_volley_f003_value_error_path_unchanged ...")
    plan_dir = _make_f004_plan(tmp_path)

    def _raise_value_error(*_a, **_kw):
        raise ValueError("No closing quotation")

    _silence_supervisor_side_effects(monkeypatch)
    monkeypatch.setattr(supervisor, "_run_round", _raise_value_error)

    result = supervisor.dispatch_volley(plan_dir=plan_dir, feature_id="F001")

    assert result.final_status == "blocked", result.final_status
    # F003 wording preserved.
    assert "F003 backstop" in result.reason, result.reason
    assert "F004 backstop" not in result.reason, result.reason

    checkpoint = plan_dir / "audit" / "terminal-state-iter0.json"
    assert checkpoint.is_file()
    payload = json.loads(checkpoint.read_text())
    # F003 caller passes stage='iter_loop_backstop'.
    assert payload["stage"] == "iter_loop_backstop", payload
    assert payload["exception_class"] == "ValueError", payload
    print("  ✓ ValueError still routed to F003 (stage=iter_loop_backstop), not F004")


def test_plan_004_f002_retrospective_orphaned_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan 004 F002 retrospective (from the feature steps): replay the D025
    crash mode (shlex parse failure mid-volley after the implementer envelope
    landed) and assert the checkpoint includes pointers to the orphaned
    implementer envelope + the shlex parse-error context. Pre-fix, this
    crash mode left the implementer envelope on disk with no terminal
    record."""
    print("\n[test] plan_004_f002_retrospective_orphaned_envelope ...")
    plan_dir = _make_f004_plan(tmp_path)
    impl_envelope_path = plan_dir / "audit" / "claude-implementer-F001-i0.json"

    call_count = {"n": 0}

    def _impl_lands_then_shlex_crashes(*_a, **_kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            impl_envelope_path.parent.mkdir(parents=True, exist_ok=True)
            impl_envelope_path.write_text(
                json.dumps(
                    {
                        "schema": "audit.v1",
                        "agent": "claude",
                        "agent_role": "implementer",
                        "iteration": 0,
                        "audit_status": "signed_off",
                        "findings": [],
                        "summary": "Repo: DontPanic\nEnv: dev\nProject: (none)\nDone.",
                        "target_context": {
                            "env": "dev",
                            "project": None,
                            "commands_run": [],
                        },
                    },
                    indent=2,
                )
            )
            return impl_envelope_path
        # Mimic the D025 surface: ValueError with shlex's "No closing
        # quotation" wording raised from somewhere outside our wrapped
        # shlex.split sites.
        raise ValueError("No closing quotation")

    _silence_supervisor_side_effects(monkeypatch)
    monkeypatch.setattr(supervisor, "_run_round", _impl_lands_then_shlex_crashes)

    result = supervisor.dispatch_volley(plan_dir=plan_dir, feature_id="F001")

    # Volley reached a clean terminal — D025's orphaned-state pathology fixed.
    assert result.final_status == "blocked", result.final_status

    checkpoint = plan_dir / "audit" / "terminal-state-iter0.json"
    assert checkpoint.is_file(), f"expected checkpoint at {checkpoint}"
    payload = json.loads(checkpoint.read_text())
    # The orphaned implementer envelope is preserved in audit_paths so the
    # operator can locate the work the volley landed before crashing.
    assert str(impl_envelope_path) in payload["audit_paths"], payload
    assert payload["last_good_audit_path"] == str(impl_envelope_path), payload
    # Shlex parse-error context is captured verbatim.
    assert "No closing quotation" in payload["exception_message"], payload
    assert payload["exception_class"] == "ValueError", payload
    # The operator gets a usable close-out command with plan_id bound.
    assert "2026-05-12-003-infra-test-f004" in payload["recommended_command"]
    print(
        "  ✓ D025 retrospective: implementer envelope path + shlex error context "
        "preserved; clean blocked terminal returned"
    )


def test_dispatch_volley_returns_clean_terminal_for_arbitrary_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance #3: dispatch always returns a clean exit code regardless of
    the exception class raised mid-iter. Parametrized over several exception
    types to lock in the broad-Exception contract."""
    print("\n[test] dispatch_volley_returns_clean_terminal_for_arbitrary_exception ...")
    for label, exc in [
        ("KeyError", KeyError("missing-key")),
        ("AttributeError", AttributeError("no-such-attr")),
        ("OSError", OSError("disk full")),
        ("ZeroDivisionError", ZeroDivisionError("denominator was 0")),
    ]:
        plan_dir = _make_f004_plan(tmp_path / label)

        def _raise(*_a, _exc=exc, **_kw):
            raise _exc

        _silence_supervisor_side_effects(monkeypatch)
        monkeypatch.setattr(supervisor, "_run_round", _raise)

        result = supervisor.dispatch_volley(plan_dir=plan_dir, feature_id="F001")
        assert result.final_status == "blocked", (label, result.final_status)
        assert "F004 backstop" in result.reason, (label, result.reason)
        checkpoint = plan_dir / "audit" / "terminal-state-iter0.json"
        assert checkpoint.is_file(), (label, checkpoint)
        payload = json.loads(checkpoint.read_text())
        assert payload["exception_class"] == label, (label, payload)
        print(f"  ✓ {label}: clean blocked terminal + F004 checkpoint")
