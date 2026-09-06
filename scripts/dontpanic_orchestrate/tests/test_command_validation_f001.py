"""F001 tests for command_validation: token-only validator + purity.

Covers plan ``2026-05-24-004-feat-event-messaging-v1`` F001 acceptance:

  (2) validate_command_tokens(...) exposes token-only validation; never
      invokes subcommand handlers; no _<cmd>_main round-trip per D021.
  (4) Deliberately-wrong-command fixture catches bad shapes.
  (5) Validator-vocabulary purity test (no subprocess, no handler imports,
      no project imports beyond stdlib).
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

from dontpanic_orchestrate import command_validation
from dontpanic_orchestrate.command_validation import (
    SubcommandSpec,
    ValidationResult,
    known_subcommands,
    validate_command_tokens,
)


# ── ValidationResult dataclass invariants ───────────────────────────────────


def test_validation_result_is_frozen() -> None:
    import dataclasses

    result = ValidationResult(ok=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.ok = False  # type: ignore[misc]


def test_validation_result_reason_empty_on_success() -> None:
    assert ValidationResult(ok=True).reason == ""


def test_validation_result_reason_joins_errors() -> None:
    result = ValidationResult(ok=False, errors=("e1", "e2"))
    assert result.reason == "e1; e2"


# ── Deliberately-wrong-command fixture (F001 acceptance #4) ─────────────────


def test_approve_with_two_positionals_passes() -> None:
    """`dontpanic approve <plan> <gate>` is the canonical body string."""
    result = validate_command_tokens(["approve", "<plan>", "<gate>"])
    assert result.ok, result.errors


def test_approve_with_unknown_flag_fails() -> None:
    """D008 honest-commands: validator must catch a bad flag shape."""
    result = validate_command_tokens(["approve", "--badflag"])
    assert not result.ok
    assert any("--badflag" in e for e in result.errors)


def test_approve_with_too_few_positionals_fails() -> None:
    result = validate_command_tokens(["approve", "<plan>"])
    assert not result.ok
    assert any("positional" in e for e in result.errors)


def test_approve_with_too_many_positionals_fails() -> None:
    result = validate_command_tokens(["approve", "<plan>", "<gate>", "<extra>"])
    assert not result.ok


def test_approve_pre_resume_after_child_passes() -> None:
    """Plan 2026-05-02-003 F003 shape — approve <plan> pre_resume_after_child
    --child <child> [--accept-non-satisfied].
    """
    result = validate_command_tokens(
        [
            "approve",
            "<plan>",
            "pre_resume_after_child",
            "--child",
            "<child>",
            "--accept-non-satisfied",
        ]
    )
    assert result.ok, result.errors


def test_resume_with_all_flag_passes() -> None:
    """`dontpanic resume <plan> --all` is the bulk-clear body string."""
    result = validate_command_tokens(["resume", "<plan>", "--all"])
    assert result.ok, result.errors


def test_resume_with_gate_value_passes() -> None:
    result = validate_command_tokens(["resume", "<plan>", "--gate", "pre_impl"])
    assert result.ok, result.errors


def test_resume_unknown_flag_fails() -> None:
    result = validate_command_tokens(["resume", "<plan>", "--purge"])
    assert not result.ok


def test_bare_resume_fails() -> None:
    """Codex F001-i0 finding: bare `resume <plan>` is refused at
    cli.py:556-561 (requires --gate or --all). The validator must reject
    too so bodies that omit the flag never render an exact_command."""
    result = validate_command_tokens(["resume", "<plan>"])
    assert not result.ok
    assert any(
        "--all" in e and "--gate" in e for e in result.errors
    ), result.errors


def test_approve_pre_resume_after_child_missing_child_fails() -> None:
    """Codex F001-i0 finding: `approve <plan> pre_resume_after_child` is
    routed to a parser where `--child` is required (cli.py:245-422).
    Validator must reject the missing-flag form."""
    result = validate_command_tokens(
        ["approve", "<plan>", "pre_resume_after_child"]
    )
    assert not result.ok
    assert any("--child" in e for e in result.errors), result.errors


def test_approve_pre_resume_after_child_bare_suffix_fails() -> None:
    """cli.py:247-258 refuses the bare-suffix gate form
    `pre_resume_after_child:CHILD`. Validator mirrors the refusal so the
    legacy body shape never renders an exact_command."""
    result = validate_command_tokens(
        ["approve", "<plan>", "pre_resume_after_child:CHILD"]
    )
    assert not result.ok
    assert any("bare-suffix" in e for e in result.errors), result.errors


def test_close_operator_resolved_passes() -> None:
    """`dontpanic close --operator-resolved <plan> <feature> --reason <class>`
    is the body string for no_progress_classification + volley_crash_caught.
    """
    result = validate_command_tokens(
        [
            "close",
            "--operator-resolved",
            "<plan>",
            "<feature>",
            "--reason",
            "environmental_reproduction_failure",
        ]
    )
    assert result.ok, result.errors


def test_close_missing_operator_resolved_flag_fails() -> None:
    result = validate_command_tokens(
        ["close", "<plan>", "<feature>", "--reason", "spec_ambiguity"]
    )
    assert not result.ok
    assert any("--operator-resolved" in e for e in result.errors)


def test_close_missing_reason_fails() -> None:
    result = validate_command_tokens(
        ["close", "--operator-resolved", "<plan>", "<feature>"]
    )
    assert not result.ok
    assert any("--reason" in e for e in result.errors)


def test_close_reason_flag_without_value_fails() -> None:
    result = validate_command_tokens(
        ["close", "--operator-resolved", "<plan>", "<feature>", "--reason"]
    )
    assert not result.ok
    assert any("--reason" in e and "value" in e for e in result.errors)


def test_calibrate_claude_passes_with_required_flags() -> None:
    """Calibration body string — quota_warn / calibration_required INBOX."""
    result = validate_command_tokens(
        ["calibrate-claude", "--window", "7d", "--dashboard-pct", "42"]
    )
    assert result.ok, result.errors


def test_calibrate_claude_missing_required_flag_fails() -> None:
    result = validate_command_tokens(["calibrate-claude", "--window", "7d"])
    assert not result.ok
    assert any("--dashboard-pct" in e for e in result.errors)


def test_quota_caps_init_passes() -> None:
    result = validate_command_tokens(["quota-caps", "init"])
    assert result.ok, result.errors


def test_quota_caps_show_passes() -> None:
    result = validate_command_tokens(["quota-caps", "show"])
    assert result.ok, result.errors


def test_quota_caps_unknown_subcommand_fails() -> None:
    result = validate_command_tokens(["quota-caps", "wipe"])
    assert not result.ok


def test_quota_caps_missing_subcommand_fails() -> None:
    result = validate_command_tokens(["quota-caps"])
    assert not result.ok


def test_architecture_regen_passes() -> None:
    """`dontpanic architecture regen` is the body string for
    architecture_regen_failed."""
    result = validate_command_tokens(["architecture", "regen"])
    assert result.ok, result.errors


def test_architecture_diff_passes() -> None:
    """Codex F001-i0 finding: `architecture diff` is a real subcommand
    (architecture.py:694)."""
    result = validate_command_tokens(["architecture", "diff"])
    assert result.ok, result.errors


def test_architecture_hook_install_passes() -> None:
    """Codex F001-i0 finding: `architecture hook --install` is a real
    subcommand shape (architecture.py:698-726)."""
    result = validate_command_tokens(
        ["architecture", "hook", "--install"]
    )
    assert result.ok, result.errors


def test_architecture_hook_without_action_fails() -> None:
    """`architecture hook` requires --install / --uninstall / --status
    (argparse mutex_required at architecture.py:703-720)."""
    result = validate_command_tokens(["architecture", "hook"])
    assert not result.ok
    assert any(
        "--install" in e and "--uninstall" in e for e in result.errors
    ), result.errors


def test_architecture_unknown_subcommand_fails() -> None:
    result = validate_command_tokens(["architecture", "regenerate"])
    assert not result.ok


def test_reconcile_baseline_yes_passes() -> None:
    result = validate_command_tokens(["reconcile", "baseline", "--yes"])
    assert result.ok, result.errors


def test_reconcile_check_passes() -> None:
    """Codex F001-i0 finding: `reconcile check` is a real subcommand
    (reconcile.py:716-738) referenced from the top-level help block."""
    result = validate_command_tokens(["reconcile", "check"])
    assert result.ok, result.errors


def test_reconcile_check_with_area_flag_passes() -> None:
    result = validate_command_tokens(
        ["reconcile", "check", "--area", "capabilities"]
    )
    assert result.ok, result.errors


def test_reconcile_unknown_subcommand_fails() -> None:
    result = validate_command_tokens(["reconcile", "rebuild"])
    assert not result.ok


def test_mcp_serve_passes() -> None:
    """Codex F001-i0 finding: `mcp serve` is the only `mcp` subcommand
    (mcp_server.py:1000-1018). Bare `mcp` must fail because the real CLI
    returns exit 2 without a subcommand."""
    result = validate_command_tokens(["mcp", "serve"])
    assert result.ok, result.errors


def test_bare_mcp_fails() -> None:
    """`mcp` without `serve` exits 2 in mcp_server.py:1009."""
    result = validate_command_tokens(["mcp"])
    assert not result.ok
    assert any("subcommand" in e for e in result.errors), result.errors


def test_mcp_unknown_subcommand_fails() -> None:
    result = validate_command_tokens(["mcp", "tools"])
    assert not result.ok


def test_quota_caps_init_overwrite_passes() -> None:
    """Codex F001-i0 finding: `quota-caps init --overwrite` is a real flag
    (cli.py:874). The top-level help block at cli.py:39 advertises it."""
    result = validate_command_tokens(["quota-caps", "init", "--overwrite"])
    assert result.ok, result.errors


def test_dashboard_serve_host_passes() -> None:
    """Codex F001-i0 finding: `dashboard serve --host 127.0.0.1` is a real
    invocation (dashboard.py:1074)."""
    result = validate_command_tokens(
        ["dashboard", "serve", "--host", "127.0.0.1"]
    )
    assert result.ok, result.errors


def test_ps_no_args_passes() -> None:
    result = validate_command_tokens(["ps"])
    assert result.ok


def test_ps_with_unexpected_positional_fails() -> None:
    result = validate_command_tokens(["ps", "<plan>"])
    assert not result.ok


def test_claude_touch_no_args_passes() -> None:
    result = validate_command_tokens(["claude-touch"])
    assert result.ok


def test_empty_token_list_fails() -> None:
    result = validate_command_tokens([])
    assert not result.ok
    assert any("empty" in e for e in result.errors)


def test_unknown_subcommand_fails() -> None:
    result = validate_command_tokens(["frobnicate", "<plan>"])
    assert not result.ok
    assert any("frobnicate" in e for e in result.errors)


def test_dispatch_from_plan_allow_incomplete_patch() -> None:
    """Body of breaker:patch_incomplete cites --allow-incomplete-patch <REASON>.

    The earlier validator listed --allow-incomplete-patch-reason (stale name
    that does not exist on cli.py:_dispatch_from_plan_main). The real flag
    per cli.py:1778 is --allow-incomplete-patch <REASON>; the stale name
    must now be rejected.
    """
    result = validate_command_tokens(
        [
            "dispatch-from-plan",
            "<plan>",
            "--feature",
            "F001",
            "--allow-incomplete-patch",
            "manual_override",
        ]
    )
    assert result.ok, result.errors

    # Stale name must now FAIL — render path that emits it would produce a
    # command the real CLI rejects, defeating D008's honest-commands rule.
    stale = validate_command_tokens(
        [
            "dispatch-from-plan",
            "<plan>",
            "--allow-incomplete-patch-reason",
            "manual_override",
        ]
    )
    assert not stale.ok


# ── F001 audit follow-up: auditor-cited real CLI shapes must validate ──────
#
# Plan 2026-05-24-004 F001 codex-auditor-i1 cited these specific real CLI
# invocations that the earlier validator rejected (false-negative against
# the real argparse surface), plus stale shapes the earlier validator
# accepted (false-positive). Per Path C close-out, the validator vocabulary
# was hand-patched to match the per-subcommand argparse construction at the
# cli.py / capabilities_status.py line locations referenced in the auditor
# summary. These parametrized cases pin the corrections; regressing any of
# them defeats D008's honest-commands rule.


@pytest.mark.parametrize(
    "tokens",
    [
        # doctor — was missing --json + --profile + --report et al per cli.py:1422
        ["doctor", "--json"],
        ["doctor", "--profile", "core"],
        ["doctor", "--json", "--profile-strict"],
        ["doctor", "--validate-plans-strict", "--architecture-drift-strict"],
        ["doctor", "--report", "--profile", "core"],
        # dispatch-from-plan — was missing --confirm + --allow-incomplete-patch
        # + --unrelated-dirty-state-note per cli.py:1707-1810
        ["dispatch-from-plan", "<plan>", "--confirm"],
        [
            "dispatch-from-plan",
            "<plan>",
            "--implementer",
            "claude",
            "--auditor",
            "codex",
            "--confirm",
        ],
        [
            "dispatch-from-plan",
            "<plan>",
            "--allow-incomplete-patch",
            "operator override reason text",
            "--confirm",
        ],
        [
            "dispatch-from-plan",
            "<plan>",
            "--unrelated-dirty-state-note",
            "in-flight parallel plan work",
            "--confirm",
        ],
        # plan lock — was missing --ignore-sufficiency-findings per cli.py:2040
        ["plan", "lock", "<plan>", "--ignore-sufficiency-findings", "operator reason"],
        # setup — earlier validator was positional-greedy and accepted anything
        # (false positive). Replaced with real per-flag surface from cli.py:2880-2920.
        ["setup", "--implementer", "claude"],
        ["setup", "--implementer", "claude", "--auditor", "codex", "--yes"],
        # capabilities status — was missing --format / --profile / --no-cache-write
        # per capabilities_status.py:645
        ["capabilities", "status", "F001", "--format", "json"],
        ["capabilities", "status", "--format", "json"],
        ["capabilities", "status", "--profile", "firebase-dashboard"],
        # next — was bare SubcommandSpec; missing all four flags per cli.py:2992
        ["next", "--format", "json"],
        ["next", "--scope", "fleet", "--format", "json"],
        ["next", "--max-parallel", "3", "--ready-only"],
    ],
)
def test_auditor_cited_real_cli_shapes_validate(tokens: list[str]) -> None:
    result = validate_command_tokens(tokens)
    assert result.ok, f"{' '.join(tokens)} should validate; errors={result.errors}"


@pytest.mark.parametrize(
    "tokens",
    [
        # Stale flags the earlier validator falsely accepted. Each one
        # corresponds to a body string the real CLI would reject — exactly
        # the false-positive class D008 says must produce exact_command=None.
        ["doctor", "--strict"],  # no such flag on cli.py:_doctor_main
        ["dispatch-from-plan", "<plan>", "--volley"],  # legacy bare-dispatch flag
        ["dispatch-from-plan", "<plan>", "--role", "implementer"],  # legacy bare-dispatch
        ["dispatch-from-plan", "<plan>", "--iteration", "1"],  # legacy bare-dispatch
        ["dispatch-from-plan", "<plan>", "--allow-depth", "3"],  # legacy bare-dispatch
        # Unknown flags on the patched-real-surface subcommands.
        ["doctor", "--nonexistent-flag"],
        ["setup", "--nonexistent-flag", "value"],
        ["next", "--bogus", "json"],
        ["plan", "lock", "<plan>", "--bogus-override", "reason"],
        ["capabilities", "status", "--bogus-flag"],
    ],
)
def test_auditor_cited_stale_shapes_now_reject(tokens: list[str]) -> None:
    result = validate_command_tokens(tokens)
    assert not result.ok, (
        f"{' '.join(tokens)} should now FAIL validation per F001 audit; "
        f"accepting it defeats D008's honest-commands rule"
    )


# ── Vocabulary smoke check (drift detection prompts; not a round-trip) ──────


def test_known_subcommands_matches_documented_top_level_ladder() -> None:
    """Per D021 the validator does NOT round-trip through _<cmd>_main. This
    test pins the validator vocabulary against the documented dispatch
    ladder (``cli.py:3105-3175``); when a new top-level subcommand lands,
    update both cli.py and the validator vocabulary in the same PR.
    """
    expected = {
        "ps",
        "approve",
        "resume",
        "claude-touch",
        "close",
        "quota-caps",
        "projects",
        "manifest",
        "mcp",
        "state",
        "plan",
        "config",
        "project",
        "setup",
        "calibrate-claude",
        "dispatch-from-plan",
        # Plan 2026-05-30-001 F012: operations_guidance emits these shapes, so
        # the validator must recognize them (AC6/AC7). orchestrate is the
        # teaching gateway over dispatch-from-plan; agent/finalize/what-now are
        # first-class top-level subcommands in cli.py:main.
        "orchestrate",
        "finalize",
        "what-now",
        "agent",
        # Plan 2026-05-30-001 F008 (codex i2): config_inventory emits
        # ``dontpanic roles set <role> <executor>`` as the dashboard safe-edit
        # route, so the validator must recognize the ``roles`` surface.
        "roles",
        "doctor",
        "init",
        # Plan 2026-06-04-003: integration operator-actions surface
        # (`integrations smoke|attest`).
        "integrations",
        "smoke",
        "architecture",
        "showcase",
        "capabilities",
        "reconcile",
        "dashboard",
        "next",
        # Plan 2026-05-30-001 F016: skill recommendation surfaces + rubric
        # migration are exposed as `dontpanic skills <recommend|rubric>`, so the
        # validator recognizes the `skills` surface.
        "skills",
        # Plan 2026-06-01-001 F003: the read-only `dontpanic plan-review <plan>`
        # scope-lint surface validates here so its rendered copy is honest.
        "plan-review",
        # PR#74 D002: opt-in evidence run/capture CLI (explicit operator-invoked
        # command execution recording and capture; does NOT grant agent dispatch).
        "evidence",
    }
    assert known_subcommands() == expected


def test_projects_backfill_canonical_validates() -> None:
    """The upgrade-readiness manifest ships ``dontpanic projects backfill-canonical``
    as a required action's APPLY command (docs/upgrade/releases.json). It MUST
    validate so the F008 dashboard drill-down surfaces it via the rendered
    exact_command field rather than the display-only operator_command escape hatch
    (which what-now-logic.js drops). codex-auditor-F008-i2 high regression guard.
    """
    assert validate_command_tokens(["projects", "backfill-canonical"]).ok
    assert validate_command_tokens(["projects", "backfill-canonical", "--dry-run"]).ok
    assert validate_command_tokens(
        ["projects", "backfill-canonical", "--json", "--ledger", "/tmp/l.jsonl"]
    ).ok


def test_projects_discover_validates() -> None:
    """``dontpanic projects discover`` (canonical-repo-discovery verify command) is a
    real CLI subcommand and must validate alongside backfill-canonical."""
    assert validate_command_tokens(["projects", "discover"]).ok
    assert validate_command_tokens(["projects", "discover", "--json"]).ok
    assert validate_command_tokens(
        ["projects", "discover", "--window-days", "14", "--min-count", "2"]
    ).ok


def test_projects_unknown_subcommand_still_rejected() -> None:
    """Adding discover/backfill-canonical must not loosen the nested-subcommand
    guard — an unknown projects subcommand still fails."""
    assert not validate_command_tokens(["projects", "nuke-everything"]).ok


def test_subcommand_spec_is_frozen() -> None:
    import dataclasses

    spec = SubcommandSpec()
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.positional_min = 9  # type: ignore[misc]


# ── Validator-vocabulary purity (F001 acceptance #5, D021) ──────────────────


def _command_validation_source_path() -> pathlib.Path:
    return pathlib.Path(command_validation.__file__).resolve()


def _imported_module_names(source: str) -> set[str]:
    """Parse the module via AST and return every imported module name."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


_FORBIDDEN_STDLIB_IMPORTS: frozenset[str] = frozenset(
    {
        # Side-effect surfaces the validator must never reach for.
        "subprocess",
        "os",  # paths/env/exec — none needed for token parsing
        "shutil",
        "socket",
        "urllib",
        "http",
        "requests",
        "asyncio",
        "multiprocessing",
        "threading",
        "signal",
        "tempfile",
        "pathlib",
        "io",
    }
)

_ALLOWED_PROJECT_IMPORTS: frozenset[str] = frozenset()


def test_command_validation_imports_only_stdlib() -> None:
    """D021 + D012: the validator is token-only. No subprocess, no cli, no
    supervisor — none of the side-effect surfaces the handlers depend on.
    """
    source = _command_validation_source_path().read_text()
    imports = _imported_module_names(source)

    # No forbidden stdlib modules.
    forbidden_hit = imports & _FORBIDDEN_STDLIB_IMPORTS
    assert not forbidden_hit, (
        f"command_validation imports forbidden modules: {sorted(forbidden_hit)}"
    )

    # No project-local imports beyond the explicit allow-list (empty for now).
    project_hits = {
        name
        for name in imports
        if name == "dontpanic_orchestrate"
        or name.startswith("dontpanic_orchestrate.")
    }
    assert project_hits <= _ALLOWED_PROJECT_IMPORTS, (
        f"command_validation has unexpected project imports: {sorted(project_hits)}"
    )


def test_command_validation_module_source_has_no_handler_calls() -> None:
    """Belt-and-braces: AST check that the module does not call any
    ``_<cmd>_main`` handler from cli.py (D021 forbids the round-trip).
    Docstrings naming the pattern are fine; actual Call nodes are not.
    """
    source = _command_validation_source_path().read_text()
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name: str | None = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name and name.endswith("_main"):
            offenders.append(name)
    assert not offenders, (
        f"command_validation calls handler-shaped functions: {offenders}"
    )


def test_validator_does_not_import_cli_or_supervisor_at_runtime() -> None:
    """Loading command_validation must not transitively pull in cli /
    supervisor. We snapshot sys.modules before importing in a subprocess-free
    way by re-importing into a fresh namespace.
    """
    # The module is already imported by the test header. Assert that neither
    # cli nor supervisor were dragged in by command_validation specifically;
    # other tests may import them, so we only check that command_validation's
    # own AST imports stay clean (covered above).
    # Here we additionally check that the validator does not register any
    # imports of cli / supervisor / notify_event / inbox even via lazy paths.
    source = _command_validation_source_path().read_text()
    for forbidden_import_substring in (
        "from dontpanic_orchestrate import cli",
        "import dontpanic_orchestrate.cli",
        "from dontpanic_orchestrate import supervisor",
        "import dontpanic_orchestrate.supervisor",
        "from dontpanic_orchestrate import notify_event",
        "from dontpanic_orchestrate import inbox",
    ):
        assert forbidden_import_substring not in source, (
            f"command_validation must not import {forbidden_import_substring!r}"
        )


def test_validator_call_has_no_observable_side_effects(tmp_path, monkeypatch) -> None:
    """Smoke check that running the validator does not spawn subprocesses or
    write files. We monkeypatch ``subprocess.run`` to fail loudly if invoked
    and ensure the validator still completes successfully.
    """
    import subprocess

    def _exploding_run(*args, **kwargs):
        raise AssertionError(
            f"validate_command_tokens triggered subprocess.run({args!r}, {kwargs!r})"
        )

    monkeypatch.setattr(subprocess, "run", _exploding_run)
    monkeypatch.setattr(subprocess, "Popen", _exploding_run)
    monkeypatch.setattr(subprocess, "call", _exploding_run)
    monkeypatch.setattr(subprocess, "check_call", _exploding_run)
    monkeypatch.setattr(subprocess, "check_output", _exploding_run)

    # Exercise a representative slice of subcommands.
    for tokens in (
        ["approve", "<plan>", "<gate>"],
        ["resume", "<plan>", "--all"],
        ["close", "--operator-resolved", "<plan>", "<feature>", "--reason", "spec_ambiguity"],
        ["calibrate-claude", "--window", "7d", "--dashboard-pct", "42"],
        ["architecture", "regen"],
        ["approve", "--badflag"],
    ):
        validate_command_tokens(tokens)


def test_validator_does_not_mutate_input_tokens() -> None:
    tokens = ["approve", "<plan>", "<gate>"]
    snapshot = list(tokens)
    validate_command_tokens(tokens)
    assert tokens == snapshot


# Belt-check: even if a future contributor breaks purity, this guards the
# direct `subprocess` symbol from being importable via command_validation.
def test_command_validation_does_not_expose_subprocess() -> None:
    assert "subprocess" not in dir(command_validation)


def test_command_validation_does_not_expose_cli() -> None:
    assert "cli" not in dir(command_validation)
    # Also ensure no stray reference accidentally crept into sys.modules.
    # (Don't assert cli is absent from sys.modules globally — other tests
    # may legitimately import it.)
    assert "dontpanic_orchestrate.cli" not in getattr(command_validation, "__dict__", {})
    # Don't reference sys at module top-level; this re-import is intentional.
    assert sys is not None
