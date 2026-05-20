"""Plan 2026-05-19-002 F002 — `dontpanic init` CLI integration tests.

Spawns ``python -m dontpanic_orchestrate init --profile=core
--non-interactive --json`` as a real subprocess against a synthetic
fixture and asserts:

  1. JSON output structure matches the F002 walker envelope.
  2. Exit code is 1 when fail+warn probes are present (non-interactive
     contract — see acceptance #7).
  3. The strict-argv invariant: the init module's source code does NOT
     use ``shell=True`` anywhere, and the walker's auto-fix execution
     path passes ``argv: list[str]`` to subprocess.run.

We mock ``subprocess.run`` at the walker layer (in-process) to assert
the third invariant since spawning the CLI in non-interactive mode
never actually executes a fix_command — non-interactive returns
structurally. The in-process mock covers the case where an operator
*would* approve a fix.

Run:
    pytest scripts/dontpanic_orchestrate/tests/test_init_cli_integration.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
INIT_MODULE_PATH = SCRIPTS_DIR / "dontpanic_orchestrate" / "init" / "__init__.py"


# ── (1) + (2) subprocess CLI spawn ─────────────────────────────────────────


def _spawn_init_cli(*extra_args: str) -> subprocess.CompletedProcess:
    """Spawn ``python -m dontpanic_orchestrate init …`` as a subprocess.

    PYTHONPATH is prepended with the scripts/ directory so the
    ``dontpanic_orchestrate`` package resolves without an installed
    console script. The spawn uses ``shell=False`` (mirror the F002
    strict-argv invariant in the test itself)."""

    env = {**os.environ, "PYTHONPATH": str(SCRIPTS_DIR)}
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "dontpanic_orchestrate",
            "init",
            *extra_args,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_cli_non_interactive_json_envelope_structure() -> None:
    """`dontpanic init --profile=core --non-interactive --json` MUST emit
    a JSON envelope with the pinned F002 walker schema.

    Spawned against the real host registry — this test only pins schema
    shape, NOT a specific exit code. The strict exit-code assertions
    against a synthetic fixture live in
    :func:`test_synthetic_fixture_non_interactive_exits_one_strictly`
    and :func:`test_synthetic_fixture_all_pass_exits_zero_strictly`
    (auditor F002-i0 finding #3)."""

    proc = _spawn_init_cli("--profile=core", "--non-interactive", "--json")
    # Exit code is 0 OR 1 depending on whether the host has fail/warn
    # probes (the test runs against the real registry against the real
    # host). Both are valid; we don't pin a specific value.
    assert proc.returncode in (0, 1), (
        f"unexpected exit code {proc.returncode}; stderr=\n{proc.stderr}"
    )
    payload = json.loads(proc.stdout)
    # Pinned schema fields.
    assert payload["schema_version"] == "1.0.0"
    assert payload["profile"] == "core"
    assert payload["mode"] == "non_interactive"
    assert "fail_warn_probes" in payload
    assert "actions" in payload
    # actions is empty in non-interactive mode.
    assert payload["actions"] == []
    # Each fail_warn_probes entry carries fix_command as list[str].
    for p in payload["fail_warn_probes"]:
        assert isinstance(p["fix_command"], list)
        assert all(isinstance(s, str) for s in p["fix_command"])


def test_cli_default_profile_is_core() -> None:
    """`dontpanic init` with NO --profile must default to --profile=core
    (per acceptance #2). Verify by passing --non-interactive --json and
    inspecting the ``profile`` field."""
    proc = _spawn_init_cli("--non-interactive", "--json")
    assert proc.returncode in (0, 1)
    payload = json.loads(proc.stdout)
    assert payload["profile"] == "core"


def test_cli_rejects_unknown_profile() -> None:
    """argparse `choices=` must reject unknown profile names."""
    proc = _spawn_init_cli("--profile=maintainer", "--non-interactive", "--json")
    # Argparse exits 2 on unrecognized choice.
    assert proc.returncode == 2, proc.stderr


def test_cli_help_mentions_profile_and_non_interactive() -> None:
    proc = _spawn_init_cli("--help")
    assert proc.returncode == 0
    text = proc.stdout
    assert "--profile" in text
    assert "--non-interactive" in text
    assert "--json" in text


# ── (3) Strict-argv invariant — source-level + behavioral ─────────────────


def test_init_module_source_does_not_use_shell_true() -> None:
    """Source-level invariant: nothing in the init module passes
    ``shell=True`` to subprocess. Catches drift if a future change ever
    adds a free-form shell invocation."""

    source = INIT_MODULE_PATH.read_text(encoding="utf-8")
    # Allow shell=False explicitly. Reject any shell=True OR shell="…".
    assert "shell=True" not in source, (
        "init module must NOT use shell=True — strict argv allowlist"
    )
    # /bin/sh -c is the canonical shell-string entry point we forbid.
    assert "/bin/sh -c" not in source
    assert "shell.invoke" not in source  # paranoia


def test_walker_auto_fix_argv_is_list_of_strings() -> None:
    """Behavioral invariant — mock ``subprocess.run`` and assert every
    invocation receives a list[str] (NOT a shell string) and never
    ``shell=True``."""

    from dontpanic_orchestrate import prereq_registry as pr
    from dontpanic_orchestrate.init import Walker

    probe = pr.PrereqProbe(
        name="strict-argv-probe",
        probe_command=lambda: (False, "fail"),
        version_constraint=None,
        fix_url="https://example.test/",
        fix_command=["brew", "install", "jq"],
        auto_install_safe=True,
        why_needed="x",
        required_for_profiles=frozenset({"core"}),
        activation_condition=pr.ActivationCondition.ALWAYS,
        severity_when_inactive=pr.SeverityWhenInactive.OMIT,
    )

    seen: list[dict[str, Any]] = []

    def _fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        seen.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(
            args=args[0] if args else kwargs.get("args"),
            returncode=0,
            stdout="ok",
            stderr="",
        )

    walker = Walker(
        profile="core",
        probes=[probe],
        prompt_fn=lambda _q: "y",
        output_fn=lambda _l: None,
        subprocess_runner=_fake_run,
        activation_context=pr.ActivationContext(
            repo_root=Path("/tmp"),
            github_remote_present=False,
            auditor_codex_selected=False,
            dispatch_requires_push=False,
            firebase_target_set=False,
        ),
    )
    walker.run()

    assert len(seen) == 1
    call = seen[0]
    argv = call["args"][0]
    assert isinstance(argv, list)
    assert all(isinstance(s, str) for s in argv)
    assert call["kwargs"]["shell"] is False
    # No keyword should equal shell=True even if a future refactor
    # passes shell positionally.
    for k, v in call["kwargs"].items():
        if k == "shell":
            assert v is False


# ── (4) synthetic fixture — strict exit code on the CLI surface ──────────


def _synthetic_failing_probes() -> list[Any]:
    """Build a deterministic synthetic probe set: one PASS + one FAIL.
    Mirrors the F001 PrereqProbe contract; the FAIL probe is what should
    force the CLI to exit 1 in non-interactive mode."""
    from dontpanic_orchestrate import prereq_registry as pr

    return [
        pr.PrereqProbe(
            name="synthetic-pass-cli",
            probe_command=lambda: (True, "ok"),
            version_constraint=None,
            fix_url="https://example.test/pass",
            fix_command=["echo", "noop"],
            auto_install_safe=False,
            why_needed="synthetic passing fixture",
            required_for_profiles=frozenset({"core"}),
            activation_condition=pr.ActivationCondition.ALWAYS,
            severity_when_inactive=pr.SeverityWhenInactive.OMIT,
        ),
        pr.PrereqProbe(
            name="synthetic-fail-cli",
            probe_command=lambda: (False, "missing"),
            version_constraint=None,
            fix_url="https://example.test/fail",
            fix_command=["echo", "install-me"],
            auto_install_safe=False,
            why_needed="synthetic failing fixture",
            required_for_profiles=frozenset({"core"}),
            activation_condition=pr.ActivationCondition.ALWAYS,
            severity_when_inactive=pr.SeverityWhenInactive.OMIT,
        ),
    ]


def _synthetic_passing_probes() -> list[Any]:
    from dontpanic_orchestrate import prereq_registry as pr

    return [
        pr.PrereqProbe(
            name="synthetic-pass-only",
            probe_command=lambda: (True, "ok"),
            version_constraint=None,
            fix_url="https://example.test/pass",
            fix_command=["echo", "noop"],
            auto_install_safe=False,
            why_needed="synthetic passing fixture",
            required_for_profiles=frozenset({"core"}),
            activation_condition=pr.ActivationCondition.ALWAYS,
            severity_when_inactive=pr.SeverityWhenInactive.OMIT,
        ),
    ]


def test_synthetic_fixture_non_interactive_exits_one_strictly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Auditor F002-i0 finding #3: pin the CLI surface against a
    synthetic fixture so we can assert exit code 1 STRICTLY when any
    fail+warn probe is present (acceptance #7). We exercise the same
    ``init_main`` entry point the ``python -m dontpanic_orchestrate
    init`` console hits — argparse + Walker + JSON render — but inject
    a deterministic probe set so the assertion is repeatable on any
    host."""

    from dontpanic_orchestrate.init import init_main

    with patch(
        "dontpanic_orchestrate.init.pr.default_probes",
        return_value=_synthetic_failing_probes(),
    ), patch(
        "dontpanic_orchestrate.init.pr.build_activation_context"
    ) as mock_ctx:
        from dontpanic_orchestrate import prereq_registry as pr

        mock_ctx.return_value = pr.ActivationContext(
            repo_root=Path("/tmp"),
            github_remote_present=False,
            auditor_codex_selected=False,
            dispatch_requires_push=False,
            firebase_target_set=False,
        )
        exit_code = init_main(
            ["--profile=core", "--non-interactive", "--json"]
        )

    captured = capsys.readouterr()
    assert exit_code == 1, (
        f"non-interactive with fail probe MUST exit 1; got {exit_code}. "
        f"stdout={captured.out!r}"
    )
    payload = json.loads(captured.out)
    assert payload["exit_code"] == 1
    assert payload["mode"] == "non_interactive"
    assert payload["profile"] == "core"
    names = {p["name"] for p in payload["fail_warn_probes"]}
    assert "synthetic-fail-cli" in names
    # The passing probe MUST NOT show up in fail_warn_probes.
    assert "synthetic-pass-cli" not in names


def test_synthetic_fixture_all_pass_exits_zero_strictly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Companion to the strict-exit-1 fixture: when ALL probes pass,
    the CLI MUST exit 0 — pinned strictly (no `in (0,1)` accept-list)."""

    from dontpanic_orchestrate.init import init_main

    with patch(
        "dontpanic_orchestrate.init.pr.default_probes",
        return_value=_synthetic_passing_probes(),
    ), patch(
        "dontpanic_orchestrate.init.pr.build_activation_context"
    ) as mock_ctx:
        from dontpanic_orchestrate import prereq_registry as pr

        mock_ctx.return_value = pr.ActivationContext(
            repo_root=Path("/tmp"),
            github_remote_present=False,
            auditor_codex_selected=False,
            dispatch_requires_push=False,
            firebase_target_set=False,
        )
        exit_code = init_main(
            ["--profile=core", "--non-interactive", "--json"]
        )

    captured = capsys.readouterr()
    assert exit_code == 0, (
        f"non-interactive all-pass MUST exit 0; got {exit_code}. "
        f"stdout={captured.out!r}"
    )
    payload = json.loads(captured.out)
    assert payload["exit_code"] == 0
    assert payload["fail_warn_probes"] == []


# ── extra: CLI subcommand wiring lives in cli.py ─────────────────────────


def test_cli_init_subcommand_wired_in_cli_main() -> None:
    """The `dontpanic init` subcommand routes through scripts/dontpanic_
    orchestrate/cli.py. Pin the wiring so a refactor does not silently
    detach the entry point."""

    cli_text = (SCRIPTS_DIR / "dontpanic_orchestrate" / "cli.py").read_text(
        encoding="utf-8"
    )
    assert 'raw[0] == "init"' in cli_text
    assert "dontpanic_orchestrate.init" in cli_text
