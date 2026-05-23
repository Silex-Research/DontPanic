"""Plan 2026-05-22-004 F002 — governed automatable-step runner tests.

Covers the F002 acceptance matrix:
  #1 ``--automate-safe`` requires ``--confirm``.
  #2 Human-required steps never execute.
  #3 Unsafe command templates are denied with explanation.
  #4 Allowlisted automatable steps execute via injected fixture runner.
  #5 Probes/status re-run after attempted steps.
  #6 Tests cover deny/allow/skip/confirm.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from dontpanic_orchestrate import capabilities_setup as cs_setup
from dontpanic_orchestrate import capabilities_setup_runner as cs_runner
from dontpanic_orchestrate import capabilities_status as cs_status
from dontpanic_orchestrate.capabilities import (
    CapabilityManifest,
    SetupStep,
    load_capabilities,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── fixture helpers ──────────────────────────────────────────────────────


@dataclass
class FakeRunner:
    """Recording :class:`CommandRunner` for tests — never spawns processes."""

    calls: list[tuple[str, ...]] = field(default_factory=list)
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""

    def run(self, argv) -> cs_runner.CommandResult:
        self.calls.append(tuple(argv))
        return cs_runner.CommandResult(
            exit_code=self.exit_code,
            stdout=self.stdout,
            stderr=self.stderr,
        )


@dataclass
class FakeStatusProbe:
    """Recording status probe — returns a configurable :class:`CapabilityStatus`."""

    statuses: list[cs_status.CapabilityStatus]
    calls: int = 0

    def __call__(self, manifest: CapabilityManifest) -> cs_status.CapabilityStatusResult:
        # If the test runs out of staged statuses, repeat the last one.
        idx = min(self.calls, len(self.statuses) - 1)
        status = self.statuses[idx]
        self.calls += 1
        return cs_status.CapabilityStatusResult(
            capability_id=manifest.id,
            status=status,
            owner_boundary={
                "dontpanic_core": manifest.owner_boundary.dontpanic_core,
                "adapter": manifest.owner_boundary.adapter,
                "operator": manifest.owner_boundary.operator,
            },
            configured=(),
            missing=(),
            automatable=(),
            human_required=(),
            pending_probes=(),
            next_actions=(),
        )


def _firebase_manifest() -> CapabilityManifest:
    return load_capabilities(REPO_ROOT).require("firebase-dashboard")


def _linear_manifest() -> CapabilityManifest:
    return load_capabilities(REPO_ROOT).require("linear")


# ── evaluate_command_template ────────────────────────────────────────────


def test_allowlist_allows_plain_argv_no_placeholders():
    decision = cs_runner.evaluate_command_template("npm install -g firebase-tools")

    assert decision.allow is True
    assert "passes" in decision.reason


def test_allowlist_denies_unsubstituted_placeholder():
    decision = cs_runner.evaluate_command_template(
        "firebase deploy --project <YOUR_FIREBASE_PROJECT_ID> --only firestore:rules"
    )

    assert decision.allow is False
    assert "placeholder" in decision.reason.lower()


def test_allowlist_denies_shell_pipe():
    decision = cs_runner.evaluate_command_template(
        "curl -sSL https://sdk.cloud.google.com | bash"
    )

    assert decision.allow is False
    assert "shell metacharacter" in decision.reason.lower()


def test_allowlist_denies_redirection():
    decision = cs_runner.evaluate_command_template(
        "echo hello > /tmp/marker"
    )

    assert decision.allow is False
    assert "shell metacharacter" in decision.reason.lower()


def test_allowlist_denies_and_chain():
    decision = cs_runner.evaluate_command_template(
        "gcloud auth login && gcloud auth application-default login"
    )

    assert decision.allow is False
    assert "shell metacharacter" in decision.reason.lower()


def test_allowlist_denies_env_var_prefix():
    decision = cs_runner.evaluate_command_template(
        "PYTHONPATH=scripts python -m firebase_adapter.mcp_http_bridge serve"
    )

    assert decision.allow is False
    assert "env-prefix" in decision.reason.lower() or "var=value" in decision.reason.lower()


def test_allowlist_denies_sudo():
    decision = cs_runner.evaluate_command_template("sudo apt install -y firebase-tools")

    assert decision.allow is False
    assert "sudo" in decision.reason


def test_allowlist_denies_rm():
    decision = cs_runner.evaluate_command_template("rm -rf /var/data")

    assert decision.allow is False
    assert "rm" in decision.reason


# Auditor evidence (F002-i0): these syntactically clean templates passed the
# previous default-allow policy. The positive allowlist must refuse them.


def test_allowlist_denies_git_push():
    decision = cs_runner.evaluate_command_template("git push origin main")

    assert decision.allow is False
    assert "git" in decision.reason
    assert "allowlist" in decision.reason.lower()


def test_allowlist_denies_gh_repo_delete():
    decision = cs_runner.evaluate_command_template("gh repo delete owner/repo --yes")

    assert decision.allow is False
    assert "gh" in decision.reason
    assert "allowlist" in decision.reason.lower()


def test_allowlist_denies_firebase_deploy_real_project():
    decision = cs_runner.evaluate_command_template(
        "firebase deploy --project real-prod --only functions"
    )

    assert decision.allow is False
    assert "firebase" in decision.reason
    assert "allowlist" in decision.reason.lower()


def test_allowlist_denies_npm_publish_subcommand():
    """npm is allowlisted but only for install/ci/list/view/doctor."""
    decision = cs_runner.evaluate_command_template("npm publish --access public")

    assert decision.allow is False
    assert "publish" in decision.reason
    assert "subcommand" in decision.reason.lower()


def test_allowlist_allows_dontpanic_subcommand():
    """The project's own CLI is allowlisted with any subcommand."""
    decision = cs_runner.evaluate_command_template("dontpanic notify smoke --sink discord")

    assert decision.allow is True


def test_allowlist_allows_echo_synthetic_step():
    """`echo` is allowlisted so synthetic test manifests work."""
    decision = cs_runner.evaluate_command_template("echo ok")

    assert decision.allow is True


def test_allowlist_denies_none_command():
    decision = cs_runner.evaluate_command_template(None)

    assert decision.allow is False
    assert "no command_template" in decision.reason.lower()


def test_allowlist_denies_empty_command():
    decision = cs_runner.evaluate_command_template("   ")

    assert decision.allow is False
    assert "empty" in decision.reason.lower()


# ── run_automate_safe core behaviour ─────────────────────────────────────


def test_run_automate_safe_requires_confirm_true():
    manifest = _firebase_manifest()
    runner = FakeRunner()
    probe = FakeStatusProbe([cs_status.CapabilityStatus.NEEDS_SETUP])

    with pytest.raises(ValueError) as excinfo:
        cs_runner.run_automate_safe(
            manifest,
            confirm=False,
            command_runner=runner,
            status_probe=probe,
        )

    assert "confirm=True" in str(excinfo.value)
    assert runner.calls == []
    # status_probe must not be called when confirm gate fails closed
    assert probe.calls == 0


def test_run_automate_safe_skips_human_required_steps():
    """Acceptance #2: human-required steps never execute."""
    manifest = _firebase_manifest()
    runner = FakeRunner()
    probe = FakeStatusProbe([cs_status.CapabilityStatus.NEEDS_SETUP])

    report = cs_runner.run_automate_safe(
        manifest,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    by_id = {o.step_id: o for o in report.outcomes}
    # firebase_login is the canonical human-required step
    fl = by_id["firebase_login"]
    assert fl.decision == "skipped_human_required"
    assert fl.automatable is False
    assert "interactive browser" in fl.reason
    # smoke_test is human-required with no command
    st = by_id["smoke_test"]
    assert st.decision == "skipped_human_required"
    assert st.exit_code is None
    # No human-required step appeared in runner.calls
    invoked_argv0 = [argv[0] for argv in runner.calls]
    assert "firebase" not in [a for a in invoked_argv0 if a.startswith("firebase login")]


def test_run_automate_safe_denies_placeholder_steps():
    """Acceptance #3: unsafe templates denied with explanation."""
    manifest = _firebase_manifest()
    runner = FakeRunner()
    probe = FakeStatusProbe([cs_status.CapabilityStatus.NEEDS_SETUP])

    report = cs_runner.run_automate_safe(
        manifest,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    by_id = {o.step_id: o for o in report.outcomes}
    sel = by_id["select_target_project"]
    assert sel.decision == "denied_unsafe"
    assert "placeholder" in sel.reason.lower()
    deploy = by_id["deploy_firestore_rules"]
    assert deploy.decision == "denied_unsafe"


def test_run_automate_safe_executes_allowlisted_steps():
    """Acceptance #4: allowlisted automatable steps run via fixture runner."""
    manifest = _firebase_manifest()
    runner = FakeRunner(exit_code=0, stdout="firebase-tools@13.0.0 installed", stderr="")
    probe = FakeStatusProbe(
        [
            cs_status.CapabilityStatus.NEEDS_SETUP,  # before
            cs_status.CapabilityStatus.NEEDS_SETUP,  # after install_firebase_cli
            cs_status.CapabilityStatus.NEEDS_SETUP,  # after install_gcloud_cli (denied? no — curl|bash is shell)
            cs_status.CapabilityStatus.READY,  # final
        ]
    )

    report = cs_runner.run_automate_safe(
        manifest,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    by_id = {o.step_id: o for o in report.outcomes}
    # install_firebase_cli must execute
    ifc = by_id["install_firebase_cli"]
    assert ifc.decision == "executed"
    assert ifc.exit_code == 0
    assert "firebase-tools" in (ifc.stdout_tail or "")
    assert ifc.argv == ("npm", "install", "-g", "firebase-tools")
    # And it should appear in the call log
    assert ("npm", "install", "-g", "firebase-tools") in runner.calls


def test_run_automate_safe_reruns_status_after_each_attempted_step():
    """Acceptance #5: probes/status re-run after attempted steps."""
    manifest = _firebase_manifest()
    runner = FakeRunner()
    probe = FakeStatusProbe(
        [
            cs_status.CapabilityStatus.NEEDS_SETUP,
            cs_status.CapabilityStatus.NEEDS_SETUP,
            cs_status.CapabilityStatus.READY,
        ]
    )

    report = cs_runner.run_automate_safe(
        manifest,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    executed = [o for o in report.outcomes if o.decision == "executed"]
    # firebase manifest has exactly one allowlisted automatable step
    # (install_firebase_cli) — others either have placeholders, shell metas,
    # or env-prefix.
    assert len(executed) == 1
    # status_probe was called: 1 before + 1 per executed step + 1 after = 3
    assert probe.calls == 3
    # Report carries before/after status values
    assert report.before_status == "needs_setup"
    assert report.after_status == "ready"
    # The executed step's status_after must be populated
    assert executed[0].status_after == "needs_setup"


def test_run_automate_safe_linear_executes_allowlisted_skips_human():
    """Linear manifest covers register_adapter (allowed) + paste_api_token (human-required)."""
    manifest = _linear_manifest()
    runner = FakeRunner()
    probe = FakeStatusProbe([cs_status.CapabilityStatus.NEEDS_SETUP])

    report = cs_runner.run_automate_safe(
        manifest,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    by_id = {o.step_id: o for o in report.outcomes}
    # emit_pp_binary and register_adapter have placeholders → denied
    assert by_id["emit_pp_binary"].decision == "denied_unsafe"
    assert by_id["register_adapter"].decision == "denied_unsafe"
    assert by_id["validate_mapping"].decision == "denied_unsafe"
    # paste_api_token is human-required
    pat = by_id["paste_api_token"]
    assert pat.decision == "skipped_human_required"
    assert "API token" in pat.reason


def test_run_automate_safe_captures_exit_nonzero_output():
    """Captured stdout/stderr/exit_code surface even when the command fails."""
    manifest = _firebase_manifest()
    runner = FakeRunner(exit_code=1, stdout="", stderr="EACCES: permission denied")
    probe = FakeStatusProbe([cs_status.CapabilityStatus.NEEDS_SETUP])

    report = cs_runner.run_automate_safe(
        manifest,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    ifc = next(o for o in report.outcomes if o.step_id == "install_firebase_cli")
    assert ifc.decision == "executed"
    assert ifc.exit_code == 1
    assert "permission denied" in (ifc.stderr_tail or "")


def test_run_automate_safe_synthetic_allowlisted_step_executes():
    """A clean automatable step (no placeholders, no shell features) runs as expected."""
    # Build a synthetic manifest mirroring the schema constraints so we can
    # control the eligibility matrix tightly.
    base = _firebase_manifest()
    synthetic_steps = (
        SetupStep(
            id="safe_step",
            what="A clean automatable step.",
            automatable=True,
            command_template="echo ok",
            verify_probe=None,
            human_required_reason=None,
        ),
        SetupStep(
            id="placeholder_step",
            what="Has unsubstituted placeholder.",
            automatable=True,
            command_template="echo <YOUR_TOKEN>",
            verify_probe=None,
            human_required_reason=None,
        ),
        SetupStep(
            id="manual_step",
            what="Human-required.",
            automatable=False,
            command_template=None,
            verify_probe=None,
            human_required_reason="Operator must do this.",
        ),
    )
    manifest = base.model_copy(update={"setup_steps": synthetic_steps})
    runner = FakeRunner(exit_code=0, stdout="ok\n")
    probe = FakeStatusProbe([cs_status.CapabilityStatus.NEEDS_SETUP, cs_status.CapabilityStatus.READY])

    report = cs_runner.run_automate_safe(
        manifest,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    by_id = {o.step_id: o for o in report.outcomes}
    assert by_id["safe_step"].decision == "executed"
    assert by_id["safe_step"].exit_code == 0
    assert by_id["placeholder_step"].decision == "denied_unsafe"
    assert by_id["manual_step"].decision == "skipped_human_required"
    assert runner.calls == [("echo", "ok")]


# ── CLI integration ──────────────────────────────────────────────────────


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = cs_setup.main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_cli_automate_safe_requires_confirm():
    """Acceptance #1: ``--automate-safe`` without ``--confirm`` exits non-zero."""
    exit_code, stdout, stderr = _run_cli(["firebase-dashboard", "--automate-safe"])

    assert exit_code == 2
    assert "--confirm" in stderr
    assert stdout == ""


def test_cli_requires_one_of_print_steps_or_automate_safe():
    """Bare invocation refuses with usage hint."""
    exit_code, stdout, stderr = _run_cli(["firebase-dashboard"])

    assert exit_code == 2
    assert "--print-steps" in stderr
    assert "--automate-safe" in stderr


def test_cli_print_steps_and_automate_safe_are_mutually_exclusive():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        with pytest.raises(SystemExit) as excinfo:
            cs_setup.main(
                ["firebase-dashboard", "--print-steps", "--automate-safe", "--confirm"]
            )

    # argparse mutually-exclusive group exits 2 with usage on stderr
    assert excinfo.value.code == 2
    assert (
        "not allowed with" in stderr.getvalue() or "argument" in stderr.getvalue()
    )


def test_cli_automate_safe_confirm_runs_runner_via_subprocess_runner(monkeypatch):
    """Acceptance #4 end-to-end: CLI ``--automate-safe --confirm`` executes
    allowlisted commands via the production :class:`SubprocessRunner`."""
    captured: list[list[str]] = []

    class _FakeCompleted:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "fake-stdout"
            self.stderr = ""

    def _fake_subprocess_run(argv, **kwargs):
        captured.append(list(argv))
        assert kwargs.get("capture_output") is True
        assert kwargs.get("text") is True
        assert kwargs.get("check") is False
        return _FakeCompleted()

    monkeypatch.setattr(
        "dontpanic_orchestrate.capabilities_setup_runner.subprocess.run",
        _fake_subprocess_run,
    )

    exit_code, stdout, stderr = _run_cli(
        ["firebase-dashboard", "--automate-safe", "--confirm"]
    )

    assert exit_code == 0, stderr
    # install_firebase_cli is the canonical allowlisted command
    assert ["npm", "install", "-g", "firebase-tools"] in captured
    # And the rendered report names the capability + outcomes
    assert "capability: firebase-dashboard" in stdout
    assert "executed" in stdout
    assert "denied (unsafe)" in stdout
    assert "skipped (human-required)" in stdout


def test_cli_automate_safe_unknown_capability_id_exits_two():
    exit_code, stdout, stderr = _run_cli(
        ["firebase-dashboarrd", "--automate-safe", "--confirm"]
    )

    assert exit_code == 2
    assert "did you mean" in stderr


# ── render_report ────────────────────────────────────────────────────────


# ── SubprocessRunner spawn-failure handling ──────────────────────────────


def test_subprocess_runner_returns_capture_on_missing_binary(monkeypatch):
    """A FileNotFoundError from subprocess.run must surface as a CommandResult.

    Without this guard, the F002 report drops the step and skips the
    post-step status re-run when the operator's environment lacks the
    binary — defeating acceptance #5.
    """

    def _raise_fnf(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr(
        "dontpanic_orchestrate.capabilities_setup_runner.subprocess.run",
        _raise_fnf,
    )

    runner = cs_runner.SubprocessRunner()
    result = runner.run(["does-not-exist", "--flag"])

    assert isinstance(result, cs_runner.CommandResult)
    assert result.exit_code == 127  # conventional "command not found"
    assert result.stdout == ""
    assert "does-not-exist" in result.stderr


def test_subprocess_runner_returns_capture_on_permission_error(monkeypatch):
    """A PermissionError (OSError subclass) must also surface as a CommandResult."""

    def _raise_perm(argv, **kwargs):
        raise PermissionError(13, "Permission denied", argv[0])

    monkeypatch.setattr(
        "dontpanic_orchestrate.capabilities_setup_runner.subprocess.run",
        _raise_perm,
    )

    runner = cs_runner.SubprocessRunner()
    result = runner.run(["restricted-binary"])

    assert result.exit_code == 127
    assert "restricted-binary" in result.stderr


def test_run_automate_safe_records_step_and_reruns_status_on_spawn_failure(monkeypatch):
    """When spawn fails, the report still records the step and the status
    probe still re-runs (acceptance #5)."""

    def _raise_fnf(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr(
        "dontpanic_orchestrate.capabilities_setup_runner.subprocess.run",
        _raise_fnf,
    )

    base = _firebase_manifest()
    synthetic_steps = (
        SetupStep(
            id="install_missing",
            what="A safe step whose binary is missing on this host.",
            automatable=True,
            command_template="npm install -g missing-tool",
            verify_probe=None,
            human_required_reason=None,
        ),
    )
    manifest = base.model_copy(update={"setup_steps": synthetic_steps})
    probe = FakeStatusProbe(
        [
            cs_status.CapabilityStatus.NEEDS_SETUP,  # before
            cs_status.CapabilityStatus.NEEDS_SETUP,  # after the spawn-failed step
            cs_status.CapabilityStatus.NEEDS_SETUP,  # final
        ]
    )

    report = cs_runner.run_automate_safe(
        manifest,
        confirm=True,
        command_runner=cs_runner.SubprocessRunner(),
        status_probe=probe,
    )

    outcome = report.outcomes[0]
    assert outcome.decision == "executed"
    assert outcome.exit_code == 127
    assert "npm" in (outcome.stderr_tail or "")
    # The post-step status probe must have run, recording status_after.
    assert outcome.status_after is not None
    # before + 1 per executed step (even on spawn failure) + after = 3
    assert probe.calls == 3


# ── build_runtime_status (Finding F002-i0 #3) ────────────────────────────


def test_build_runtime_status_runs_probes_for_target_capability():
    """The runtime status helper must invoke probes (unlike planning status).

    Auditor F002-i0 finding #3: the CLI was wiring run_automate_safe to
    build_planning_status, which intentionally skips probes. F002
    acceptance #5 ("Probes/status re-run after attempted steps") requires
    the probe-capable variant.
    """
    manifest = _firebase_manifest()

    result = cs_setup.build_runtime_status(manifest)

    assert result.capability_id == manifest.id
    assert isinstance(result, cs_status.CapabilityStatusResult)
    assert result.status in cs_status.CapabilityStatus


def test_cli_automate_safe_uses_probe_capable_status(monkeypatch):
    """End-to-end: CLI --automate-safe --confirm must call build_runtime_status,
    not build_planning_status (Auditor F002-i0 finding #3)."""

    calls: list[str] = []

    real_runtime = cs_setup.build_runtime_status
    real_planning = cs_setup.build_planning_status

    def _spy_runtime(manifest):
        calls.append("runtime")
        return real_runtime(manifest)

    def _spy_planning(manifest):
        calls.append("planning")
        return real_planning(manifest)

    monkeypatch.setattr(cs_setup, "build_runtime_status", _spy_runtime)
    monkeypatch.setattr(cs_setup, "build_planning_status", _spy_planning)

    class _FakeCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(
        "dontpanic_orchestrate.capabilities_setup_runner.subprocess.run",
        lambda argv, **kwargs: _FakeCompleted(),
    )

    exit_code, _, _ = _run_cli(["firebase-dashboard", "--automate-safe", "--confirm"])

    assert exit_code == 0
    # At least one before + one after + one per executed step → ≥ 2 calls.
    assert calls.count("runtime") >= 2
    # The planning surface must NOT be reached on the executor path.
    assert "planning" not in calls


def test_render_report_includes_status_transition_and_outcomes():
    manifest = _firebase_manifest()
    runner = FakeRunner(exit_code=0, stdout="installed")
    probe = FakeStatusProbe(
        [cs_status.CapabilityStatus.NEEDS_SETUP, cs_status.CapabilityStatus.READY]
    )

    report = cs_runner.run_automate_safe(
        manifest,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )
    rendered = cs_runner.render_report(report)

    assert "capability: firebase-dashboard" in rendered
    assert "before_status:" in rendered
    assert "after_status:" in rendered
    assert "[executed]" in rendered
    assert "[denied (unsafe)]" in rendered
    assert "[skipped (human-required)]" in rendered
