"""F005b — executor argv translation per role + forbidden-flag guard.

Covers F002 + F003 acceptance:

  F002 unit-level (this file):
    - Exact argv for all 4 (executor, role) pairs against fake-binary path
    - permission_policy=None preserves legacy argv shape (no permission flags)

  F003 (this file):
    - check_forbidden_flags(['claude', '--dangerously-skip-permissions'])
      raises ValueError; same for the other two forbidden flags
    - No produced argv across {implementer, auditor, None} × {Claude, Codex}
      contains any forbidden flag (6 cases swept)
    - Both executors call the guard before subprocess.run

  F004 fake-CLI shim level (also this file):
    - Implementer sentinel WRITTEN; auditor sentinel NOT written. "No timeout"
      alone is not sufficient; the sentinel checks prove the agent actually
      attempted tool use (implementer) or was correctly denied (auditor).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from jarvis_orchestrate.executors.base import (
    FORBIDDEN_FLAGS,
    DispatchTask,
    check_forbidden_flags,
)
from jarvis_orchestrate.executors.claude_cli import ClaudeCLIExecutor
from jarvis_orchestrate.executors.codex_cli import CodexCLIExecutor

FAKE_CLI_DIR = Path(__file__).parent / "fake_cli"
FAKE_CLAUDE = FAKE_CLI_DIR / "fake-claude"
FAKE_CODEX = FAKE_CLI_DIR / "fake-codex"


def _make_task(tmp_path: Path, *, role: str | None) -> DispatchTask:
    return DispatchTask(
        plan_id="p",
        plan_dir=tmp_path,
        feature_id="F001",
        feature_description="d",
        feature_acceptance="a",
        feature_steps=[],
        agent_role=role or "implementer",
        cwd=tmp_path,
        permission_policy=role,  # type: ignore[arg-type]
    )


# ── F003: forbidden-flag guard ────────────────────────────────────────────


def test_forbidden_flags_set_contents():
    """The frozenset contains exactly the three documented bypass flags.
    If a future change adds more bypass flags upstream, this test fails
    loudly so we update FORBIDDEN_FLAGS deliberately rather than by accident."""
    assert FORBIDDEN_FLAGS == frozenset({
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
        "--dangerously-bypass-approvals-and-sandbox",
    })


@pytest.mark.parametrize(
    "flag",
    [
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
        "--dangerously-bypass-approvals-and-sandbox",
    ],
)
def test_check_forbidden_flags_raises_on_direct_injection(flag):
    """Direct injection of any forbidden flag raises ValueError. This is the
    layer that catches a future change introducing an override surface, even
    if no override surface exists today."""
    with pytest.raises(ValueError, match="forbidden flag in argv"):
        check_forbidden_flags(["claude", flag])


def test_check_forbidden_flags_clean_argv_returns_silently():
    # Sanity — non-forbidden args don't raise.
    check_forbidden_flags(["claude", "-p", "--allowedTools", "Read"])
    check_forbidden_flags(["codex", "exec", "--json", "prompt"])


# ── F002: exact argv per (executor, role) ─────────────────────────────────


@pytest.mark.parametrize(
    "policy,expected_tail",
    [
        (
            "implementer",
            (
                "--permission-mode",
                "acceptEdits",
                "--allowedTools",
                "Read Edit Write Bash",
            ),
        ),
        (
            "auditor",
            (
                "--permission-mode",
                "dontAsk",
                "--allowedTools",
                "Read",
            ),
        ),
        (None, ()),
    ],
)
def test_claude_executor_argv(monkeypatch, tmp_path, policy, expected_tail):
    """ClaudeCLIExecutor produces the exact argv we documented in plan.md.
    Captured via subprocess.run monkey-patch; no real CLI invocation."""
    captured: dict = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        # Return a successful CompletedProcess with valid JSON so dispatch
        # parses cleanly.
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout='{"result":"ok","is_error":false,"usage":{},"modelUsage":{"v1":{}}}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    ex = ClaudeCLIExecutor(binary="/bin/echo")  # binary doesn't matter; subprocess.run is mocked
    ex.dispatch(_make_task(tmp_path, role=policy))
    argv = captured["argv"]
    # First three args are the legacy -p --output-format json shape.
    assert argv[1:4] == ["-p", "--output-format", "json"]
    # Next 0 or 4 args are the role-derived permission flags.
    assert tuple(argv[4 : 4 + len(expected_tail)]) == expected_tail
    # Forbidden-flag guard cleared the produced argv.
    assert not any(f in argv for f in FORBIDDEN_FLAGS)


@pytest.mark.parametrize(
    "policy,expected_global",
    [
        (
            "implementer",
            ("--ask-for-approval", "never", "--sandbox", "workspace-write"),
        ),
        (
            "auditor",
            ("--ask-for-approval", "never", "--sandbox", "read-only"),
        ),
        (None, ()),
    ],
)
def test_codex_executor_argv(monkeypatch, tmp_path, policy, expected_global):
    """CodexCLIExecutor inserts global flags BEFORE the `exec` subcommand —
    verified by checking position of `exec` in the produced argv."""
    captured: dict = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=(
                '{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}\n'
                '{"type":"turn.completed","usage":{}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    ex = CodexCLIExecutor(binary="/bin/echo")
    ex.dispatch(_make_task(tmp_path, role=policy))
    argv = captured["argv"]
    # Global flags (if any) must appear BEFORE the `exec` token.
    exec_idx = argv.index("exec")
    if expected_global:
        # The four global tokens are the four argv slots immediately before
        # `exec`. Assert exactly those slots.
        assert tuple(argv[exec_idx - len(expected_global) : exec_idx]) == expected_global
        # And nothing else between binary and the global flags.
        assert exec_idx - len(expected_global) == 1
    else:
        # No flags: argv[1] is `exec` (legacy shape preserved).
        assert exec_idx == 1
    # Forbidden-flag guard cleared the produced argv.
    assert not any(f in argv for f in FORBIDDEN_FLAGS)


# ── F003: produced-argv sweep — no forbidden flag in any combination ──────


@pytest.mark.parametrize("policy", ["implementer", "auditor", None])
@pytest.mark.parametrize(
    "executor_factory,fake_run_stdout",
    [
        (
            lambda: ClaudeCLIExecutor(binary="/bin/echo"),
            '{"result":"ok","is_error":false,"usage":{},"modelUsage":{"v1":{}}}',
        ),
        (
            lambda: CodexCLIExecutor(binary="/bin/echo"),
            '{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}\n{"type":"turn.completed","usage":{}}\n',
        ),
    ],
)
def test_produced_argv_never_contains_forbidden_flag(
    monkeypatch, tmp_path, executor_factory, fake_run_stdout, policy
):
    """Sweep all 6 (executor, role) combinations and assert no produced argv
    contains any of the forbidden bypass flags."""
    captured: dict = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=fake_run_stdout, stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    ex = executor_factory()
    ex.dispatch(_make_task(tmp_path, role=policy))
    for flag in FORBIDDEN_FLAGS:
        assert flag not in captured["argv"], (
            f"forbidden flag {flag!r} appeared in produced argv {captured['argv']!r} "
            f"for {ex.agent_name}/{policy}"
        )


def test_executors_call_check_forbidden_flags_before_subprocess(monkeypatch, tmp_path):
    """If a future change introduces an argv-override surface, check_forbidden_flags
    must run before subprocess.run so the guard catches the injection. Verified by
    monkey-patching check_forbidden_flags to raise; subprocess.run must NOT have been
    called, proving the guard runs first."""
    from jarvis_orchestrate.executors import claude_cli, codex_cli

    subprocess_called = {"count": 0}

    def _record_subprocess(*a, **kw):
        subprocess_called["count"] += 1
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="{}", stderr="")

    def _raise_guard(_argv):
        raise ValueError("guard fired before subprocess.run")

    monkeypatch.setattr(claude_cli, "check_forbidden_flags", _raise_guard)
    monkeypatch.setattr(codex_cli, "check_forbidden_flags", _raise_guard)
    monkeypatch.setattr(subprocess, "run", _record_subprocess)

    for ex in (ClaudeCLIExecutor(binary="/bin/echo"), CodexCLIExecutor(binary="/bin/echo")):
        with pytest.raises(ValueError, match="guard fired"):
            ex.dispatch(_make_task(tmp_path, role="implementer"))
    assert subprocess_called["count"] == 0, "subprocess.run must not run after guard raises"


# ── F004: fake-CLI shim — sentinel write/no-write ─────────────────────────


def test_fake_cli_shims_exist_and_executable():
    """Sanity: the shims must exist and be executable for the smoke tests to run."""
    assert FAKE_CLAUDE.is_file(), f"missing fake-CLI shim: {FAKE_CLAUDE}"
    assert FAKE_CODEX.is_file(), f"missing fake-CLI shim: {FAKE_CODEX}"
    import os

    assert os.access(FAKE_CLAUDE, os.X_OK), f"not executable: {FAKE_CLAUDE}"
    assert os.access(FAKE_CODEX, os.X_OK), f"not executable: {FAKE_CODEX}"


def test_fake_cli_smoke_claude_implementer_writes_sentinel(tmp_path):
    """End-to-end through the executor with the fake-CLI shim. The shim writes
    sentinel-implementer.txt only when it sees implementer flags. This proves
    the executor is producing the expected role flags and that the shim
    interpreted them — not just 'no timeout', a real artifact of tool use."""
    ex = ClaudeCLIExecutor(binary=str(FAKE_CLAUDE))
    result = ex.dispatch(_make_task(tmp_path, role="implementer"))
    assert result.success, f"dispatch failed: {result.error}"
    assert (tmp_path / "sentinel-implementer.txt").is_file(), (
        "implementer flags should cause shim to write sentinel-implementer.txt; "
        "absence means the executor is not producing implementer flags"
    )


def test_fake_cli_smoke_claude_auditor_no_sentinel(tmp_path):
    """Auditor flags must NOT produce a sentinel — the shim refused to write
    because it saw read-only flags. Proves the executor is producing auditor
    flags, not implementer flags. 'No timeout' alone wouldn't catch a regression
    where the executor accidentally widened the auditor allowlist."""
    ex = ClaudeCLIExecutor(binary=str(FAKE_CLAUDE))
    result = ex.dispatch(_make_task(tmp_path, role="auditor"))
    assert result.success, f"dispatch failed: {result.error}"
    assert not (tmp_path / "sentinel-implementer.txt").is_file(), (
        "auditor flags must NOT cause shim to write a sentinel — its presence "
        "would mean the executor is producing implementer flags for the auditor role"
    )


def test_fake_cli_smoke_codex_implementer_writes_sentinel(tmp_path):
    ex = CodexCLIExecutor(binary=str(FAKE_CODEX))
    result = ex.dispatch(_make_task(tmp_path, role="implementer"))
    assert result.success, f"dispatch failed: {result.error}"
    assert (tmp_path / "sentinel-implementer.txt").is_file()


def test_fake_cli_smoke_codex_auditor_no_sentinel(tmp_path):
    ex = CodexCLIExecutor(binary=str(FAKE_CODEX))
    result = ex.dispatch(_make_task(tmp_path, role="auditor"))
    assert result.success, f"dispatch failed: {result.error}"
    assert not (tmp_path / "sentinel-implementer.txt").is_file()


# ── F004: real-CLI no-hang regression — env-var gated ─────────────────────
#
# These tests invoke the real `claude -p` / `codex exec` CLIs. They are the
# regression detector the operator runs manually after a CLI version update;
# they are NOT part of the default pytest suite because:
#   (a) They consume real Claude/Codex quota.
#   (b) Their behavior depends on the locally-installed CLI versions and auth.
#   (c) Default `pytest` should run in <30s without external dependencies.
#
# Opt in by setting `JARVIS_RUN_REAL_CLI_TESTS=1`. The env-var gate is per the
# locked design (D014); we deliberately do NOT modify pyproject.toml addopts.
#
# Manual command:
#   JARVIS_RUN_REAL_CLI_TESTS=1 pytest \
#     scripts/jarvis_orchestrate/tests/test_f005b_executor_argv.py::test_real_claude_implementer_writes_in_cwd \
#     -v
#
# If any of these tests fails with subprocess.TimeoutExpired, F005b has
# regressed — a permission prompt is blocking. If a deny case writes the
# sentinel anyway, the permission system has been bypassed.

import os
import shutil

_RUN_REAL = os.environ.get("JARVIS_RUN_REAL_CLI_TESTS") == "1"
_HAVE_CLAUDE = shutil.which("claude") is not None
_HAVE_CODEX = shutil.which("codex") is not None

_real_claude = pytest.mark.skipif(
    not (_RUN_REAL and _HAVE_CLAUDE),
    reason="set JARVIS_RUN_REAL_CLI_TESTS=1 and install `claude` to run real-CLI tests",
)
_real_codex = pytest.mark.skipif(
    not (_RUN_REAL and _HAVE_CODEX),
    reason="set JARVIS_RUN_REAL_CLI_TESTS=1 and install `codex` to run real-CLI tests",
)


@_real_claude
def test_real_claude_implementer_writes_in_cwd(tmp_path):
    """Real Claude CLI with implementer flags against a write-to-cwd task
    completes in <15s and produces a sentinel file (proves tool use happened).
    If TimeoutExpired fires, F005b has regressed — a permission prompt is
    blocking subprocess dispatch."""
    ex = ClaudeCLIExecutor()
    task = _make_task(tmp_path, role="implementer")
    # Override the prompt so the agent has a concrete instruction.
    task.extra_context = {
        "prompt_override": (
            "Use the Write tool to create a file named real-impl-sentinel.txt "
            "in the current working directory containing the single line OK. "
            "Do not run any other commands. Reply with one short sentence."
        )
    }
    # Tighten timeout — locked acceptance is 15s.
    import jarvis_orchestrate.executors.claude_cli as cc

    orig_run = subprocess.run

    def _short_timeout_run(argv, **kw):
        kw["timeout"] = 15
        return orig_run(argv, **kw)

    import unittest.mock as mock

    with mock.patch.object(cc.subprocess, "run", side_effect=_short_timeout_run):
        result = ex.dispatch(task)
    assert result.error is None or "TimeoutExpired" not in (result.error or ""), (
        f"real Claude implementer dispatch hit TimeoutExpired: {result.error}"
    )
    sentinel = tmp_path / "real-impl-sentinel.txt"
    assert sentinel.is_file(), (
        "real Claude implementer did not produce sentinel; the agent may have "
        "demurred verbally instead of using the Write tool — check result.summary"
    )


@_real_claude
def test_real_claude_auditor_read_success(tmp_path):
    """Real Claude CLI with auditor flags reads a fixture file successfully and
    reports its content. Critical for the changelog dogfood: Codex (and Claude
    when used as auditor) must be able to actually inspect files — 'no timeout
    on a denied write' isn't sufficient evidence that the auditor role works
    for its real job, which is reading and reporting on content."""
    fixture = tmp_path / "fixture.txt"
    fixture_content = "MAGIC_TOKEN_ALPHA_7841"
    fixture.write_text(f"This is a test file.\nContents: {fixture_content}\n")
    ex = ClaudeCLIExecutor()
    task = _make_task(tmp_path, role="auditor")
    task.extra_context = {
        "prompt_override": (
            f"Use the Read tool to read the file fixture.txt in the current "
            f"working directory. Then reply with one short sentence that "
            f"includes the literal token after 'Contents: ' from the file."
        )
    }
    result = ex.dispatch(task)
    assert result.error is None or "TimeoutExpired" not in (result.error or ""), (
        f"real Claude auditor read dispatch hit TimeoutExpired: {result.error}"
    )
    assert fixture_content in (result.summary or ""), (
        f"real Claude auditor failed to read and report fixture content; "
        f"summary={result.summary!r}"
    )
    # Read-only allowlist must NOT have written anything.
    new_files = [p.name for p in tmp_path.iterdir() if p.name != "fixture.txt"]
    assert not new_files, f"auditor wrote unexpected files: {new_files}"


@_real_claude
def test_real_claude_auditor_edit_attempt_denies_no_timeout(tmp_path):
    """Real Claude CLI with auditor flags (Read-only) asked to perform an Edit
    must complete in <15s (no TimeoutExpired) AND must NOT produce a write —
    `dontAsk` mode should deny rather than prompt."""
    ex = ClaudeCLIExecutor()
    task = _make_task(tmp_path, role="auditor")
    task.extra_context = {
        "prompt_override": (
            "Use the Write tool to create a file named real-aud-denied.txt "
            "in the current working directory. If you cannot, reply with one "
            "short sentence explaining why."
        )
    }
    result = ex.dispatch(task)
    assert result.error is None or "TimeoutExpired" not in (result.error or ""), (
        f"real Claude auditor dispatch hit TimeoutExpired: {result.error} — "
        "dontAsk mode is prompting instead of denying; F005b is BLOCKED until "
        "an alternative auditor strategy lands"
    )
    assert not (tmp_path / "real-aud-denied.txt").is_file(), (
        "real Claude auditor wrote a file despite Read-only allowlist — "
        "the permission system was bypassed somehow"
    )


def _git_init_tmp(tmp_path: Path) -> Path:
    """Codex refuses to run outside a trusted git directory. tmp_path isn't a
    git repo by default, so we init one. In production the supervisor's cwd is
    registry_repo_root which IS a git repo, so this only affects tests.

    --no-gpg-sign defends against operator-level signing config (1Password,
    yubikey, etc.) that would otherwise fail in a test fixture without the
    signing material wired up."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c", "user.email=test@x",
            "-c", "user.name=t",
            "-c", "commit.gpgsign=false",
            "commit", "--allow-empty", "--no-gpg-sign", "-m", "init", "-q",
        ],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


@_real_codex
def test_real_codex_implementer_writes_in_cwd(tmp_path):
    _git_init_tmp(tmp_path)
    ex = CodexCLIExecutor()
    task = _make_task(tmp_path, role="implementer")
    task.extra_context = {
        "prompt_override": (
            "Create a file named real-impl-sentinel.txt in the current working "
            "directory containing the single line OK. Do not run any other commands."
        )
    }
    result = ex.dispatch(task)
    assert result.error is None or "TimeoutExpired" not in (result.error or "")
    assert (tmp_path / "real-impl-sentinel.txt").is_file()


@_real_codex
def test_real_codex_auditor_read_success(tmp_path):
    """Real Codex CLI with auditor flags (--sandbox read-only) reads a fixture
    file. The read-only sandbox blocks writes at the OS level but must allow
    reads — without this guarantee, Codex can't audit anything in the
    changelog dogfood."""
    _git_init_tmp(tmp_path)
    fixture = tmp_path / "fixture.txt"
    fixture_content = "MAGIC_TOKEN_BRAVO_3392"
    fixture.write_text(f"This is a test file.\nContents: {fixture_content}\n")
    ex = CodexCLIExecutor()
    task = _make_task(tmp_path, role="auditor")
    task.extra_context = {
        "prompt_override": (
            f"Read the file fixture.txt in the current working directory and "
            f"reply with one short sentence that includes the literal token "
            f"after 'Contents: ' from the file."
        )
    }
    result = ex.dispatch(task)
    assert result.error is None or "TimeoutExpired" not in (result.error or ""), (
        f"real Codex auditor read dispatch hit TimeoutExpired: {result.error}"
    )
    assert fixture_content in (result.summary or ""), (
        f"real Codex auditor failed to read and report fixture content; "
        f"summary={result.summary!r}"
    )
    # Read-only sandbox must NOT have written anything beyond fixture + git.
    written = sorted(
        p.name for p in tmp_path.iterdir() if p.name not in {"fixture.txt", ".git"}
    )
    assert not written, f"auditor wrote unexpected files: {written}"


@_real_codex
def test_real_codex_auditor_write_attempt_sandbox_deny_no_timeout(tmp_path):
    """Codex auditor sandbox=read-only: any write attempt fails at the OS
    level. Must complete <15s and produce no file."""
    _git_init_tmp(tmp_path)
    ex = CodexCLIExecutor()
    task = _make_task(tmp_path, role="auditor")
    task.extra_context = {
        "prompt_override": (
            "Create a file named real-aud-denied.txt in the current working "
            "directory. If the sandbox refuses, report that in one sentence."
        )
    }
    result = ex.dispatch(task)
    assert result.error is None or "TimeoutExpired" not in (result.error or "")
    assert not (tmp_path / "real-aud-denied.txt").is_file()
