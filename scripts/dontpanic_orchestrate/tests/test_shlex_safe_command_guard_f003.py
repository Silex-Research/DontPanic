"""Plan 2026-05-12-001 v4 F003 — shlex-safe command-string handling (D025).

Covers the three acceptance criteria:

  (1) Every shlex.split() in the agent-output pipeline is wrapped with
      try/except.
  (2) Bad-input shlex strings produce structured warnings, not unhandled
      exceptions.
  (3) Fixture tests cover the three classic shlex failure modes
      (unbalanced single quote, unbalanced double quote, escape error).
  (4) Backstop ValueError catch in dispatch_volley's iter loop handles
      parse failures from outside our shlex callers.
  (5) Plan 004 F002 reproducer test asserts the volley reaches a clean
      terminal even with the parse-breaking input.

Run:
  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_shlex_safe_command_guard_f003.py
"""

from __future__ import annotations

import datetime as dt
import json
import shlex
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import command_guard, notify, supervisor  # noqa: E402
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)


# ──────────────────────────────  command_guard.shlex hardening  ──────────────────────────────


@pytest.mark.parametrize(
    "bad_cmd, label",
    [
        ("gcloud services list --project=foo'", "unbalanced_single_quote"),
        ('gcloud services list --project="foo', "unbalanced_double_quote"),
        ("gcloud services list --project=foo\\", "trailing_backslash_escape"),
    ],
)
def test_check_command_does_not_raise_on_shlex_parse_failure(bad_cmd: str, label: str) -> None:
    """All three classic shlex failure modes flow through check_command
    without raising ValueError, surfacing the parser message via
    GuardResult.parse_error."""
    print(f"\n[test] check_command_does_not_raise_on_shlex_parse_failure[{label}] ...")
    # Sanity: the raw shlex.split call would have raised.
    with pytest.raises(ValueError):
        shlex.split(bad_cmd)
    # Through command_guard: parse_error surfaces, no exception.
    r = command_guard.check_command(bad_cmd)
    assert r.parse_error is not None, f"expected parse_error on {bad_cmd!r}"
    assert "shlex parse failed" in r.parse_error
    assert r.allowed is False, "unparseable command should not be allowed"
    print(f"  ✓ {label}: parse_error surfaces, no ValueError raised")


def test_check_command_happy_path_no_parse_error() -> None:
    """Well-formed command produces parse_error=None and routes through the
    existing allow/reject branches."""
    print("\n[test] check_command_happy_path_no_parse_error ...")
    r = command_guard.check_command("firebase deploy --only hosting --project foo")
    assert r.parse_error is None
    assert r.allowed is True
    print("  ✓ valid command: parse_error=None, allowed=True")


def test_check_required_flags_skips_on_parse_error() -> None:
    """check_required_flags returns None on unparseable input (caller handles
    parse failure via check_command's GuardResult.parse_error)."""
    print("\n[test] check_required_flags_skips_on_parse_error ...")
    assert command_guard.check_required_flags("firebase deploy --project='foo") is None
    print("  ✓ check_required_flags returns None on shlex parse failure")


def test_assert_allowed_raises_on_parse_failure() -> None:
    """assert_allowed preserves the loud-fail contract for code that asserts
    on commands WE constructed: parse failure surfaces as CommandRejected."""
    print("\n[test] assert_allowed_raises_on_parse_failure ...")
    with pytest.raises(command_guard.CommandRejected) as excinfo:
        command_guard.assert_allowed("gcloud services list --project=foo'")
    assert "shlex parse failed" in str(excinfo.value)
    print("  ✓ assert_allowed raises CommandRejected on unparseable input")


# ──────────────────────────────  supervisor._apply_target_accountability  ──────────────────────────────


def test_apply_target_accountability_emits_advisory_on_unparseable_command() -> None:
    """Plan 004 F002 reproducer (D025 root cause #1):
    target_context.commands_run contains a string with an unbalanced quote.
    Pre-fix: _apply_target_accountability raised ValueError, killing the
    volley with no terminal record. Post-fix: an advisory parsing finding is
    emitted + the audit_status remains signed_off (advisory severity)."""
    print("\n[test] apply_target_accountability_emits_advisory_on_unparseable_command ...")
    audit = {
        "audit_status": "signed_off",
        "agent_role": "implementer",
        "findings": [],
        "summary": "Repo: Jarvis\nEnv: dev\nProject: jarvis-a6ee1\nDone.",
        "target_context": {
            "env": "dev",
            "project": "jarvis-a6ee1",
            # Note the dangling quote — this is exactly the kind of
            # implementer-prose pattern that crashed plan 004 F002.
            "commands_run": ["gcloud services list --project=foo'"],
        },
    }
    # Must not raise.
    supervisor._apply_target_accountability(
        audit, role="implementer", plan_target_env="dev", plan_target_project="jarvis-a6ee1"
    )
    # Status preserved (advisory severity is non-blocking).
    assert audit["audit_status"] == "signed_off", audit["audit_status"]
    # Advisory parsing finding present.
    parsing_findings = [
        f for f in audit["findings"] if "shlex parse failed" in f.get("issue", "")
    ]
    assert parsing_findings, f"expected a parsing advisory finding; got {audit['findings']}"
    pf = parsing_findings[0]
    assert pf["severity"] == "advisory", pf
    assert pf["category"] == "parsing", pf
    # Evidence references the offending command (truncated).
    assert "gcloud services list" in pf["evidence"], pf
    print("  ✓ unparseable command → advisory parsing finding, no crash, status preserved")


@pytest.mark.parametrize(
    "bad_cmd, label",
    [
        ("gcloud services list --project=foo'", "unbalanced_single_quote"),
        ('gcloud services list --project="foo', "unbalanced_double_quote"),
        ("gcloud services list --project=foo\\", "trailing_backslash_escape"),
    ],
)
def test_apply_target_accountability_handles_all_three_shlex_failure_modes(
    bad_cmd: str, label: str
) -> None:
    """Acceptance #3: all three classic shlex failure modes surface as
    advisory findings, never as raised exceptions."""
    print(
        "\n[test] apply_target_accountability_handles_all_three_shlex_failure_modes"
        f"[{label}] ..."
    )
    audit = {
        "audit_status": "signed_off",
        "agent_role": "implementer",
        "findings": [],
        "summary": "Repo: Jarvis\nEnv: dev\nProject: jarvis-a6ee1\nDone.",
        "target_context": {
            "env": "dev",
            "project": "jarvis-a6ee1",
            "commands_run": [bad_cmd],
        },
    }
    supervisor._apply_target_accountability(
        audit, role="implementer", plan_target_env="dev", plan_target_project="jarvis-a6ee1"
    )
    assert audit["audit_status"] == "signed_off", audit["audit_status"]
    assert any(
        "shlex parse failed" in f.get("issue", "") for f in audit["findings"]
    ), audit["findings"]
    print(f"  ✓ {label}: advisory parsing finding emitted, no crash")


def test_apply_target_accountability_mixed_good_and_bad_commands() -> None:
    """Bad commands produce advisory findings; good forbidden commands still
    produce high/security findings. The two paths are independent."""
    print("\n[test] apply_target_accountability_mixed_good_and_bad_commands ...")
    audit = {
        "audit_status": "signed_off",
        "agent_role": "implementer",
        "findings": [],
        "summary": "Repo: Jarvis\nEnv: dev\nProject: jarvis-a6ee1\nDone.",
        "target_context": {
            "env": "dev",
            "project": "jarvis-a6ee1",
            "commands_run": [
                "gcloud services list --project=foo'",  # parse error
                "gcloud config set project wrong-project",  # forbidden
                "firebase deploy --project foo --only hosting",  # allowed
            ],
        },
    }
    supervisor._apply_target_accountability(
        audit, role="implementer", plan_target_env="dev", plan_target_project="jarvis-a6ee1"
    )
    # Forbidden command (high/security) → implementer downgrade to needs_changes.
    assert audit["audit_status"] == "needs_changes", audit["audit_status"]
    parse_findings = [
        f for f in audit["findings"] if "shlex parse failed" in f.get("issue", "")
    ]
    forbidden_findings = [
        f for f in audit["findings"] if "Forbidden command" in f.get("issue", "")
    ]
    assert len(parse_findings) == 1, parse_findings
    assert parse_findings[0]["severity"] == "advisory", parse_findings[0]
    assert len(forbidden_findings) == 1, forbidden_findings
    assert forbidden_findings[0]["severity"] == "high", forbidden_findings[0]
    print("  ✓ mixed input: each command classifies independently; status driven by worst class")


# ──────────────────────────────  dispatch_volley iter-loop backstop  ──────────────────────────────


def test_write_backstop_checkpoint_writes_expected_shape(tmp_path: Path) -> None:
    """The minimal F003 checkpoint stub writes terminal-state-iter{N}.json
    with the exception class + last-good envelope paths so the operator can
    recover via the F2 F004 close CLI. F004 will extend this stub with
    richer recovery context."""
    print("\n[test] write_backstop_checkpoint_writes_expected_shape ...")
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    target = supervisor._write_backstop_checkpoint(
        plan_dir=plan_dir,
        feature_id="F003",
        iteration=0,
        exception=ValueError("No closing quotation"),
        audit_paths=[plan_dir / "audit" / "claude-implementer-F003-i0.json"],
    )
    assert target is not None
    assert target.name == "terminal-state-iter0.json"
    payload = json.loads(target.read_text())
    assert payload["schema"] == "terminal-state.v0"
    assert payload["feature_id"] == "F003"
    assert payload["iteration"] == 0
    assert payload["exception_class"] == "ValueError"
    assert "No closing quotation" in payload["exception_message"]
    assert payload["audit_paths"] == [
        str(plan_dir / "audit" / "claude-implementer-F003-i0.json")
    ]
    assert "operator-resolved" in payload["recommended_recovery"]
    print("  ✓ checkpoint artifact written with v0 schema + exception + recovery hint")


def test_write_backstop_checkpoint_swallows_oserror(tmp_path: Path) -> None:
    """Checkpoint write is best-effort: an OSError on disk-full / readonly /
    permission must not propagate, because the caller's next step
    (transcript + INBOX + signoff) MUST still execute."""
    print("\n[test] write_backstop_checkpoint_swallows_oserror ...")
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    # Force write_text to raise OSError.
    with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
        result = supervisor._write_backstop_checkpoint(
            plan_dir=plan_dir,
            feature_id="F003",
            iteration=0,
            exception=ValueError("anything"),
            audit_paths=[],
        )
    assert result is None
    print("  ✓ OSError during write returns None instead of propagating")


def _make_backstop_plan(tmp: Path) -> Path:
    """Synthetic plan dir used by the backstop dispatch_volley test. Modeled
    on test_volley_synthetic.py's plan fixture so it threads cleanly through
    plan_loader + gate/admission machinery."""
    plan_id = "2026-05-12-002-infra-test-backstop"
    plan_dir = tmp / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F003 backstop synthetic
type: infra
tier: trivial
status: active
date: "2026-05-12"
description: F003 backstop synthetic.
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
# F003 backstop synthetic

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
                        "description": "Synthetic feature for F003 backstop test.",
                        "steps": ["scripted"],
                        "acceptance": "Backstop fires.",
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


def test_dispatch_volley_backstop_catches_value_error_from_iter_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan 004 F002 reproducer (D025): when ValueError is raised mid-iter
    from somewhere outside our wrapped shlex callers (dependencies,
    subprocess parsers, Pydantic), the supervisor must catch it, write a
    backstop checkpoint, emit a clean 'blocked' terminal, and return without
    propagating the exception.

    We synthesize the crash by monkey-patching ``supervisor._run_round`` to
    raise ValueError on first call. This sits inside the wrapped try block
    and proves the backstop fires on raises from anywhere in the iter body,
    not just from our own shlex.split callers."""
    print("\n[test] dispatch_volley_backstop_catches_value_error_from_iter_loop ...")
    plan_dir = _make_backstop_plan(tmp_path)

    def _raise_value_error(*_a, **_kw):
        raise ValueError("No closing quotation")  # mimics shlex's wording

    # Replace _run_round itself with the synthetic crash. This is the inner-
    # most call inside the wrapped try block, so any raise here exercises the
    # F003 backstop directly without needing real executors.
    monkeypatch.setattr(supervisor, "_run_round", _raise_value_error)
    # Bypass the per-agent quota gate (otherwise it tries to read
    # ~/.jarvis/quota_state.json).
    monkeypatch.setattr(
        supervisor, "_quota_gate", lambda agent: (None, f"[quota] {agent}: bypassed for test")
    )
    # Stub the executor resolution so dispatch_volley doesn't error trying to
    # locate real claude/codex binaries.

    class _FakeExecutor:
        binary = "fake"

        def is_available(self) -> bool:
            return True

        def availability_hint(self) -> str:
            return "stubbed for test"

    monkeypatch.setattr(supervisor, "_resolve_executor", lambda name: _FakeExecutor())
    # Silence notify side-effects.
    monkeypatch.setattr(supervisor.notify, "notify", lambda **kw: None)
    monkeypatch.setattr(supervisor.notify_event, "dispatch_event", lambda *_a, **_kw: None)

    result = supervisor.dispatch_volley(plan_dir=plan_dir, feature_id="F001")

    # Volley reached a clean terminal — no exception propagated.
    assert result.final_status == "blocked", result.final_status
    assert "F003 backstop" in result.reason, result.reason
    assert "No closing quotation" in result.reason, result.reason
    # Backstop checkpoint artifact written.
    checkpoint = plan_dir / "audit" / "terminal-state-iter0.json"
    assert checkpoint.is_file(), f"expected backstop checkpoint at {checkpoint}"
    payload = json.loads(checkpoint.read_text())
    assert payload["exception_class"] == "ValueError"
    assert "No closing quotation" in payload["exception_message"]
    print("  ✓ ValueError in iter loop → clean blocked terminal + checkpoint artifact")


def test_dispatch_volley_backstop_reraises_target_context_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The F003 backstop catches ``ValueError`` to neutralize D025 root cause
    #1, but ``target_context_prelude.TargetContextError`` is also a
    ``ValueError`` subclass and signals an intentional F023 EC6 validation
    failure (audit rejected; no file should land). The backstop MUST NOT
    swallow it — it must re-raise so the audit_writer/F002 contract holds."""
    print("\n[test] dispatch_volley_backstop_reraises_target_context_error ...")
    from dontpanic_orchestrate.target_context_prelude import TargetContextError

    plan_dir = _make_backstop_plan(tmp_path)

    def _raise_target_context_error(*_a, **_kw):
        raise TargetContextError("target_context invalid: synthetic test")

    monkeypatch.setattr(supervisor, "_run_round", _raise_target_context_error)
    monkeypatch.setattr(
        supervisor, "_quota_gate", lambda agent: (None, f"[quota] {agent}: bypassed for test")
    )

    class _FakeExecutor:
        binary = "fake"

        def is_available(self) -> bool:
            return True

        def availability_hint(self) -> str:
            return "stubbed for test"

    monkeypatch.setattr(supervisor, "_resolve_executor", lambda name: _FakeExecutor())
    monkeypatch.setattr(supervisor.notify, "notify", lambda **kw: None)
    monkeypatch.setattr(supervisor.notify_event, "dispatch_event", lambda *_a, **_kw: None)

    with pytest.raises(TargetContextError) as excinfo:
        supervisor.dispatch_volley(plan_dir=plan_dir, feature_id="F001")
    assert "synthetic test" in str(excinfo.value)
    # No backstop checkpoint should land — TargetContextError isn't a D025
    # crash, it's a contract violation that propagates.
    checkpoint = plan_dir / "audit" / "terminal-state-iter0.json"
    assert not checkpoint.exists(), (
        f"backstop checkpoint should not land for TargetContextError; "
        f"found {checkpoint}"
    )
    print("  ✓ TargetContextError propagates past F003 backstop; no checkpoint written")


# Path to the on-disk plan 004 F002 implementer envelope — the actual JSON the
# supervisor read when D025 crashed. Loaded by the replay tests below so they
# replay the real reproducer, not a fabricated stand-in.
_PLAN_004_F002_IMPL_ENVELOPE = (
    HERE.parents[3]
    / "docs"
    / "plans"
    / "2026-05-09-004-feat-firebase-dashboard-adapter-v0"
    / "audit"
    / "claude-implementer-F002-i0.json"
)


def _load_plan_004_f002_audit() -> dict:
    """Load the real plan 004 F002 implementer envelope from disk. Returns a
    mutable dict copy — callers may augment commands_run to model the failure
    surface that D025 root cause #1 exposed."""
    assert _PLAN_004_F002_IMPL_ENVELOPE.is_file(), (
        f"plan 004 F002 implementer envelope missing: {_PLAN_004_F002_IMPL_ENVELOPE}"
    )
    return json.loads(_PLAN_004_F002_IMPL_ENVELOPE.read_text())


# Terminal states the supervisor accepts on a finished volley iteration.
_ACCEPTED_TERMINAL_STATUSES = {
    "signed_off",
    "needs_changes",
    "blocked",
    "blocked_no_findings",
}


def test_plan_004_f002_replay_real_envelope_reaches_clean_terminal() -> None:
    """Acceptance #5 (auditor i0 medium#1): replay the *actual* plan 004 F002
    implementer envelope from disk through ``_apply_target_accountability``.
    The real on-disk commands_run are parseable, so the post-iter pipeline
    should reach a clean accepted-terminal status with no parsing findings
    introduced — proving the loud-fail contract isn't lost on the happy path."""
    print("\n[test] plan_004_f002_replay_real_envelope_reaches_clean_terminal ...")
    audit = _load_plan_004_f002_audit()
    prior_findings = list(audit.get("findings") or [])
    prior_status = audit.get("audit_status")
    # Must not raise.
    supervisor._apply_target_accountability(
        audit, role="implementer", plan_target_env="dev", plan_target_project=None
    )
    # Real on-disk commands_run are parseable — no new parsing findings.
    new_parsing_findings = [
        f
        for f in audit["findings"]
        if "shlex parse failed" in f.get("issue", "") and f not in prior_findings
    ]
    assert not new_parsing_findings, (
        f"real envelope's commands_run should be parseable; got parsing findings: "
        f"{new_parsing_findings}"
    )
    # Status remains in the accepted-terminal set (post-fix it is still
    # ``signed_off`` because all real commands are parseable + allowed).
    assert audit["audit_status"] in _ACCEPTED_TERMINAL_STATUSES, audit["audit_status"]
    # And we did not silently downgrade the original status.
    assert audit["audit_status"] == prior_status, (
        f"real envelope status changed from {prior_status!r} to {audit['audit_status']!r}; "
        f"findings={audit['findings']}"
    )
    print(
        f"  ✓ real envelope replay: status preserved as {audit['audit_status']!r}, "
        f"no spurious parsing findings"
    )


def test_plan_004_f002_replay_real_envelope_with_injected_bad_input_does_not_crash() -> None:
    """Acceptance #5 (auditor i0 medium#1): the real plan 004 F002 envelope's
    commands_run are parseable, so the on-disk file alone cannot demonstrate
    the D025 crash mode. Inject the kind of unbalanced-quote string that
    triggered 'No closing quotation' mid-volley into the real envelope's
    commands_run, then replay. Post-fix, the post-iter path must reach an
    accepted terminal (advisory finding only, no exception)."""
    print(
        "\n[test] plan_004_f002_replay_real_envelope_with_injected_bad_input_does_not_crash ..."
    )
    audit = _load_plan_004_f002_audit()
    # Preserve the real commands_run, append the three classic shlex-failure
    # shapes that model the kind of LLM-prose pattern that crashed D025.
    bad_inputs = [
        "echo 'building feature without closing quote",  # unbalanced single quote
        'git commit -m "plan-004 F002 fix without closing dq',  # unbalanced double quote
        "ruff check --select 'F401\\",  # trailing backslash escape
    ]
    audit["target_context"]["commands_run"] = (
        list(audit["target_context"]["commands_run"]) + bad_inputs
    )
    # Must not raise — D025 root cause #1 must be neutralized.
    supervisor._apply_target_accountability(
        audit, role="implementer", plan_target_env="dev", plan_target_project=None
    )
    # Each injected bad command produced one advisory parsing finding.
    parsing_findings = [
        f for f in audit["findings"] if "shlex parse failed" in f.get("issue", "")
    ]
    assert len(parsing_findings) == len(bad_inputs), (
        f"expected {len(bad_inputs)} parsing findings (one per injected bad command); "
        f"got {len(parsing_findings)}: {parsing_findings}"
    )
    for f in parsing_findings:
        assert f["severity"] == "advisory", f
        assert f["category"] == "parsing", f
        # Auditor i0 low#2: parse advisory must not be double-prefixed.
        assert not f["issue"].startswith("shlex parse failed: shlex parse failed"), (
            f"double-prefixed advisory regressed: {f['issue']!r}"
        )
    # The real (parseable) commands did NOT spuriously parse-fail.
    for real_cmd in audit["target_context"]["commands_run"][: -len(bad_inputs)]:
        assert all(real_cmd not in f.get("evidence", "") for f in parsing_findings), (
            f"real parseable command {real_cmd!r} should not surface a parsing finding"
        )
    # Status stays in the accepted-terminal set (advisory severity does not
    # downgrade an implementer's ``signed_off``).
    assert audit["audit_status"] in _ACCEPTED_TERMINAL_STATUSES, audit["audit_status"]
    print(
        f"  ✓ real envelope + injected bad input: {len(parsing_findings)} advisory parsing "
        f"findings, no crash, terminal in {sorted(_ACCEPTED_TERMINAL_STATUSES)}"
    )


def test_parse_advisory_is_not_double_prefixed() -> None:
    """Auditor i0 low#2: ``supervisor._apply_target_accountability`` previously
    re-prefixed ``guard.parse_error`` (which already includes ``"shlex parse
    failed: ..."``), producing advisories like ``"shlex parse failed: shlex
    parse failed: No closing quotation"``. Lock in the single-prefix form."""
    print("\n[test] parse_advisory_is_not_double_prefixed ...")
    audit = {
        "audit_status": "signed_off",
        "agent_role": "implementer",
        "findings": [],
        "summary": "Repo: DontPanic\nEnv: dev\nProject: (none)\nDone.",
        "target_context": {
            "env": "dev",
            "project": None,
            "commands_run": ["echo 'No closing quotation"],
        },
    }
    supervisor._apply_target_accountability(
        audit, role="implementer", plan_target_env="dev", plan_target_project=None
    )
    parse_findings = [
        f for f in audit["findings"] if "shlex parse failed" in f.get("issue", "")
    ]
    assert len(parse_findings) == 1, parse_findings
    issue = parse_findings[0]["issue"]
    # Exactly one occurrence of the prefix — no double-prefix regression.
    assert issue.count("shlex parse failed") == 1, (
        f"expected single-prefix advisory; got {issue!r}"
    )
    assert not issue.startswith("shlex parse failed: shlex parse failed"), issue
    print(f"  ✓ single-prefix advisory: {issue!r}")


# ──────────────────────────────  full dispatch_volley replay  ──────────────────────────────
#
# Plan 2026-05-12-002 v4.1 F002 D009 close: the prior F003 coverage tested
# `_apply_target_accountability` (the unit where D025 root cause #1 lived) and
# the per-command shlex wrapper, but stopped short of asserting that the FULL
# dispatch_volley terminal path with the Plan 004 F002 reproducer input
# reaches a clean accepted-terminal status. This test threads parse-breaking
# commands_run all the way through a real volley iter (implementer + auditor
# + post-iter pipeline) using mocked executors so no live API calls fire.


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _ParseBreakingExecutor(BaseExecutor):
    """Implementer + auditor pair that emits the Plan 004 F002 reproducer's
    parse-breaking commands_run (`gcloud services list --project=foo'` —
    unbalanced single quote) in the implementer summary. The auditor signs
    off cleanly. ``audit_writer.extract_commands_run`` lifts the `$ <cmd>`
    lines into ``target_context.commands_run`` so the post-iter
    ``_apply_target_accountability`` pipeline sees the parse-breaking
    string verbatim (mirrors what Plan 004 F002 actually wrote to disk)."""

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
        if self.role == "implementer":
            # Implementer prose mirrors the Plan 004 F002 reproducer: the
            # first `$ <cmd>` line has the unbalanced single quote that
            # crashed `shlex.split` pre-F003; the second is well-formed and
            # exercises the happy path so we know the iter genuinely
            # routed through every command, not just short-circuited on
            # the first parse error.
            summary = (
                "Repo: DontPanic\nEnv: dev\nProject: (none)\n\n"
                "## Target context\n"
                "Repo: DontPanic\nEnv: dev\nProject: (none)\n\n"
                "**Verdict: signed off**\n\n"
                "$ gcloud services list --project=foo'\n"
                "$ firebase deploy --project foo --only hosting\n"
            )
        else:  # auditor
            summary = (
                "Repo: DontPanic\nEnv: dev\nProject: (none)\n\n"
                "## Target context\n"
                "Repo: DontPanic\nEnv: dev\nProject: (none)\n\n"
                "**Verdict: signed off**\n\n"
                "Auditor confirms implementer landed clean.\n"
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


def _install_volley_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_ParseBreakingExecutor, _ParseBreakingExecutor]:
    """Wire mocked executors + bypass quota / wall-clock / budget / admission
    so dispatch_volley reaches the iter body without external dependencies."""
    impl = _ParseBreakingExecutor("claude", "implementer")
    aud = _ParseBreakingExecutor("codex", "auditor")
    monkeypatch.setenv(notify.DISABLE_ENV, "1")
    monkeypatch.setitem(AGENT_REGISTRY, "claude", lambda: impl)
    monkeypatch.setitem(AGENT_REGISTRY, "codex", lambda: aud)
    monkeypatch.setattr(
        supervisor, "_quota_gate", lambda agent: (None, f"[quota] {agent}: bypassed")
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


def test_plan_004_f002_replay_full_dispatch_volley_reaches_clean_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v4.1 F002 D009 close — drive the full ``dispatch_volley`` terminal
    path with the Plan 004 F002 reproducer's parse-breaking input. The
    prior coverage exercised only ``_apply_target_accountability`` + the
    per-command shlex wrapper; this test threads the same parse-breaking
    ``commands_run`` end-to-end (implementer → auditor → post-iter →
    terminal) using mocked executors so no live API calls fire. The
    volley must return a ``VolleyResult`` whose ``final_status`` is in
    the accepted-terminal set (no hang, no raise), and the implementer
    envelope must carry an advisory parsing finding citing the unbalanced
    quote (proves the post-iter pipeline ran, not just that the iter
    returned)."""
    print(
        "\n[test] plan_004_f002_replay_full_dispatch_volley_reaches_clean_terminal ..."
    )
    plan_dir = _make_backstop_plan(tmp_path)
    impl, aud = _install_volley_runtime(monkeypatch)

    result = supervisor.dispatch_volley(
        plan_dir=plan_dir, feature_id="F001", max_iterations=1
    )

    # Acceptance #3: volley returns a clean terminal — no hang, no raise.
    assert result.final_status in _ACCEPTED_TERMINAL_STATUSES, result
    # Both executors got called — confirms the iter wasn't short-circuited
    # by quota / breaker mocks before the implementer / auditor ran.
    assert impl.calls >= 1, f"implementer never dispatched: {impl.calls}"
    assert aud.calls >= 1, f"auditor never dispatched: {aud.calls}"

    # The parse-breaking command surfaced as an advisory parsing finding
    # in the implementer envelope — proves _apply_target_accountability
    # ran on the post-iter pipeline (not just that dispatch_volley exited
    # cleanly because it never reached the post-iter stage).
    impl_envelopes = sorted(
        (plan_dir / "audit").glob("claude-implementer-F001-i*.json")
    )
    assert impl_envelopes, list((plan_dir / "audit").glob("*.json"))
    parse_findings: list[dict] = []
    for env_path in impl_envelopes:
        data = json.loads(env_path.read_text())
        for f in data.get("findings") or []:
            if "shlex parse failed" in f.get("issue", ""):
                parse_findings.append(f)
    assert parse_findings, (
        "expected at least one advisory parsing finding in implementer envelope; "
        f"found findings: {[json.loads(p.read_text()).get('findings') for p in impl_envelopes]}"
    )
    for f in parse_findings:
        assert f["severity"] == "advisory", f
        assert f["category"] == "parsing", f
        # The unbalanced-quote command surfaces as the offending evidence
        # (truncated by command_guard's advisory builder).
        assert "gcloud services list" in f.get("evidence", ""), f
    print(
        f"  ✓ full volley replay: final_status={result.final_status!r}, "
        f"{len(parse_findings)} advisory parsing finding(s), no crash"
    )
