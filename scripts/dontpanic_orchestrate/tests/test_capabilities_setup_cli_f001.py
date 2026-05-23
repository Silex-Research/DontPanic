"""Plan 2026-05-22-004 F001 — `dontpanic capabilities setup --print-steps` CLI tests."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from dontpanic_orchestrate import capabilities_setup as cs_setup
from dontpanic_orchestrate import capabilities_status as cs_status
from dontpanic_orchestrate.capabilities import (
    CapabilityManifestError,
    load_capabilities,
    validate_capability_file,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── resolve_capability ────────────────────────────────────────────────────


def test_resolve_capability_returns_manifest_when_id_known():
    index = load_capabilities(REPO_ROOT)

    manifest = cs_setup.resolve_capability("firebase-dashboard", index)

    assert manifest.id == "firebase-dashboard"


def test_resolve_capability_raises_with_closest_match_for_typo():
    index = load_capabilities(REPO_ROOT)

    with pytest.raises(CapabilityManifestError) as excinfo:
        cs_setup.resolve_capability("firebase-dashboarrd", index)

    assert "firebase-dashboard" in str(excinfo.value)
    assert "did you mean" in str(excinfo.value)


def test_resolve_capability_raises_with_known_list_when_no_close_match():
    index = load_capabilities(REPO_ROOT)

    with pytest.raises(CapabilityManifestError) as excinfo:
        cs_setup.resolve_capability("totally-unrelated-thing-xyz", index)

    msg = str(excinfo.value)
    assert "known:" in msg
    assert "firebase-dashboard" in msg


# ── render_print_steps ────────────────────────────────────────────────────


def _build_status_result(capability_id: str) -> cs_status.CapabilityStatusResult:
    """Build a status result the way run_status() would, without probes."""
    manifest = load_capabilities(REPO_ROOT).require(capability_id)
    return cs_status.build_capability_result(
        manifest,
        probe_results=(),
        requires_resolution=cs_status.RequiresResolution(),
        in_active_profile=True,
    )


def test_render_print_steps_firebase_includes_all_steps_in_order():
    """Acceptance #1: render all setup_steps in declaration order."""
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    status_result = _build_status_result("firebase-dashboard")

    rendered = cs_setup.render_print_steps(manifest, status_result)

    assert f"capability: firebase-dashboard" in rendered
    assert f"Setup steps ({len(manifest.setup_steps)})" in rendered
    last_pos = -1
    for step in manifest.setup_steps:
        pos = rendered.find(step.id)
        assert pos > last_pos, f"step {step.id!r} out of declared order"
        last_pos = pos


def test_render_print_steps_marks_human_required_with_reason():
    """Acceptance #2: human-required steps include reason text."""
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    status_result = _build_status_result("firebase-dashboard")

    rendered = cs_setup.render_print_steps(manifest, status_result)

    # firebase_login is automatable=False with a human_required_reason.
    assert "[human-required] firebase_login" in rendered
    assert (
        "Requires interactive browser sign-in with the operator's Google account"
        in rendered
    )
    for step in manifest.setup_steps:
        if step.automatable:
            continue
        assert step.human_required_reason in rendered, (
            f"missing reason text for human-required step {step.id!r}"
        )


def test_render_print_steps_marks_automatable_with_command_and_probe():
    """Acceptance #3: automatable steps include command_template and verify_probe when present."""
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    status_result = _build_status_result("firebase-dashboard")

    rendered = cs_setup.render_print_steps(manifest, status_result)

    assert "[automatable] install_firebase_cli" in rendered
    assert "command_template: npm install -g firebase-tools" in rendered
    assert "verify_probe: cli:firebase" in rendered
    # deploy_firestore_rules has command_template but no verify_probe; ensure
    # we don't fabricate a verify_probe line.
    rules_block_start = rendered.find("[automatable] deploy_firestore_rules")
    rules_block = rendered[rules_block_start:]
    next_step = rules_block.find("[automatable] deploy_cloud_functions")
    rules_block = rules_block[:next_step] if next_step >= 0 else rules_block
    assert "verify_probe" not in rules_block


def test_render_print_steps_linear_renders_four_steps():
    """Acceptance #1 — applies equally to Linear manifest."""
    manifest = load_capabilities(REPO_ROOT).require("linear")
    status_result = _build_status_result("linear")

    rendered = cs_setup.render_print_steps(manifest, status_result)

    assert "capability: linear" in rendered
    assert "Setup steps (4)" in rendered
    for step_id in ("emit_pp_binary", "register_adapter", "paste_api_token", "validate_mapping"):
        assert step_id in rendered
    # The paste-token step is human-required and must show its reason.
    assert (
        "Operator must mint and paste their own Linear API token" in rendered
    )


def test_render_print_steps_empty_setup_steps_emits_helpful_notice(tmp_path: Path):
    """Edge case: a manifest with zero setup_steps still renders cleanly."""
    # Build an isolated repo root with the schema + a minimal manifest.
    schema_src = REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0" / "capability.schema.json"
    schema_dst = tmp_path / "claude" / "shared" / "schemas" / "v1.0" / "capability.schema.json"
    schema_dst.parent.mkdir(parents=True, exist_ok=True)
    schema_dst.write_text(schema_src.read_text(encoding="utf-8"), encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "USE_CASES.md").write_text("# Use cases\n", encoding="utf-8")
    cap_dir = tmp_path / "capabilities"
    cap_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0.0",
        "id": "empty-cap",
        "title": "Empty capability",
        "kind": "external_adapter",
        "category": "pm-tool",
        "summary": "Manifest with no setup_steps.",
        "setup_required": False,
        "setup_doc": "docs/USE_CASES.md",
        "default_in_profiles": [],
        "use_cases": [],
        "requires": {
            "commands": [],
            "env": [],
            "files": [],
            "services": [],
            "auth": [],
            "config": [],
        },
        "verify": {
            "doctor_profiles": [],
            "probes": [],
            "readiness": "Ready by construction.",
        },
        "owner_boundary": {
            "dontpanic_core": ["nothing"],
            "adapter": ["nothing"],
            "operator": ["nothing"],
        },
        "mutation_boundary": {
            "writes_dontpanic_state": False,
            "external_mutation": "none",
            "allowed_path": "Adapter is inert.",
            "forbidden": ["mutate plan state"],
        },
        "notes": [],
    }
    (cap_dir / "empty-cap.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest = validate_capability_file(
        cap_dir / "empty-cap.json", repo_root=tmp_path
    )
    status_result = cs_status.build_capability_result(
        manifest,
        probe_results=(),
        requires_resolution=cs_status.RequiresResolution(),
        in_active_profile=True,
    )

    rendered = cs_setup.render_print_steps(manifest, status_result)

    assert "no setup steps declared in manifest" in rendered
    assert "F001 is a planning surface only — no commands are executed." in rendered


def test_render_print_steps_emits_no_commands_executed_notice():
    """Acceptance #4: render contains a 'no commands executed' notice."""
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    status_result = _build_status_result("firebase-dashboard")

    rendered = cs_setup.render_print_steps(manifest, status_result)

    assert "no commands are executed" in rendered


def test_render_print_steps_includes_status_badge():
    """Status from V0b status projection is surfaced in the header."""
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    status_result = _build_status_result("firebase-dashboard")

    rendered = cs_setup.render_print_steps(manifest, status_result)

    # The status line is always present; exact badge depends on local env
    # (we feed an empty requires_resolution → no informational unresolved →
    # status defaults to READY).
    assert "status:" in rendered


def test_pending_probe_surfaces_as_readiness_chip_on_matching_step():
    """Status's pending_probes are surfaced next to the matching setup step."""
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    # Hand-build a status result with a PENDING probe whose name matches one
    # of firebase's setup_steps[].verify_probe entries.
    pending_result = cs_status.CapabilityStatusResult(
        capability_id=manifest.id,
        status=cs_status.CapabilityStatus.NEEDS_SETUP,
        owner_boundary={
            "dontpanic_core": manifest.owner_boundary.dontpanic_core,
            "adapter": manifest.owner_boundary.adapter,
            "operator": manifest.owner_boundary.operator,
        },
        configured=(),
        missing=(),
        automatable=(),
        human_required=(),
        pending_probes=({"name": "cli:firebase", "reason": "needs_probe_implementation"},),
        next_actions=(),
    )

    rendered = cs_setup.render_print_steps(manifest, pending_result)

    assert "readiness: verify_probe cli:firebase: pending — needs_probe_implementation" in rendered


# ── CLI behaviour ─────────────────────────────────────────────────────────


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = cs_setup.main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_cli_print_steps_firebase_dashboard_happy_path():
    """Acceptance #1 end-to-end: full firebase-dashboard render via CLI."""
    exit_code, stdout, stderr = _run_cli(
        ["firebase-dashboard", "--print-steps"]
    )

    assert exit_code == 0, stderr
    assert "capability: firebase-dashboard" in stdout
    assert "Setup steps" in stdout
    assert "install_firebase_cli" in stdout
    assert "smoke_test" in stdout  # last step in manifest
    assert "no commands are executed" in stdout


def test_cli_requires_print_steps_flag_for_f001():
    """Acceptance #4: without --print-steps, the CLI refuses to run."""
    exit_code, stdout, stderr = _run_cli(["firebase-dashboard"])

    assert exit_code == 2
    assert "--print-steps" in stderr
    assert stdout == ""


def test_cli_unknown_capability_id_exits_nonzero_with_suggestion():
    """Acceptance #5: unknown id exits non-zero with closest-match suggestion."""
    exit_code, stdout, stderr = _run_cli(
        ["firebase-dashboarrd", "--print-steps"]
    )

    assert exit_code == 2
    assert "firebase-dashboard" in stderr
    assert "did you mean" in stderr
    assert stdout == ""


def test_cli_unknown_capability_id_no_close_match_lists_known():
    exit_code, stdout, stderr = _run_cli(
        ["totally-unrelated-xyz", "--print-steps"]
    )

    assert exit_code == 2
    assert "known:" in stderr
    assert "firebase-dashboard" in stderr


def test_cli_linear_print_steps_happy_path():
    exit_code, stdout, stderr = _run_cli(["linear", "--print-steps"])

    assert exit_code == 0, stderr
    assert "capability: linear" in stdout
    for step_id in ("emit_pp_binary", "register_adapter", "paste_api_token", "validate_mapping"):
        assert step_id in stdout


def test_cli_executes_zero_subprocesses_for_print_steps():
    """Acceptance #4 (strict): ``--print-steps`` invokes ZERO subprocesses.

    F001 is a planning surface — no setup_steps[].command_template payloads,
    no status-gathering probes, no network calls. We trap every subprocess
    entrypoint (``subprocess.run``/``Popen``/``call``/``check_*``,
    ``os.system``, ``os.popen``) and the CLI must complete without invoking
    any of them. This is a stronger contract than "the printed command
    templates don't run" because in F001 we deliberately route around
    ``run_status()``'s probe sweep so status-context lookups are pure
    PATH/env/filesystem checks.
    """

    invocations: list[str] = []

    def _explode_subprocess_run(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        invocations.append(f"subprocess.run({argv!r})")
        raise AssertionError(
            f"capabilities setup --print-steps must not invoke subprocess.run; got {argv!r}"
        )

    def _explode_subprocess_popen(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        invocations.append(f"subprocess.Popen({argv!r})")
        raise AssertionError(
            f"capabilities setup --print-steps must not invoke subprocess.Popen; got {argv!r}"
        )

    def _explode_subprocess_call(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        invocations.append(f"subprocess.call({argv!r})")
        raise AssertionError(
            f"capabilities setup --print-steps must not invoke subprocess.call; got {argv!r}"
        )

    def _explode_os_system(cmd):
        invocations.append(f"os.system({cmd!r})")
        raise AssertionError(
            f"capabilities setup --print-steps must not invoke os.system; got {cmd!r}"
        )

    def _explode_os_popen(cmd, *args, **kwargs):
        invocations.append(f"os.popen({cmd!r})")
        raise AssertionError(
            f"capabilities setup --print-steps must not invoke os.popen; got {cmd!r}"
        )

    with (
        patch("subprocess.run", side_effect=_explode_subprocess_run),
        patch("subprocess.Popen", side_effect=_explode_subprocess_popen),
        patch("subprocess.call", side_effect=_explode_subprocess_call),
        patch("subprocess.check_call", side_effect=_explode_subprocess_call),
        patch("subprocess.check_output", side_effect=_explode_subprocess_run),
        patch("os.system", side_effect=_explode_os_system),
        patch("os.popen", side_effect=_explode_os_popen),
    ):
        exit_code, stdout, stderr = _run_cli(
            ["firebase-dashboard", "--print-steps"]
        )

    assert exit_code == 0, stderr
    assert "capability: firebase-dashboard" in stdout
    assert invocations == [], (
        f"capabilities setup --print-steps spawned forbidden side-effect calls: "
        f"{invocations!r}"
    )


def test_build_planning_status_uses_only_pure_lookups():
    """Acceptance #4: status-context build path is subprocess-free.

    The setup planner must not call ``run_status()`` (which runs the probe
    sweep). We unit-test the helper directly: it should resolve requires
    via ``shutil.which`` / env / filesystem only — never spawn a process.
    """

    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")

    def _explode(*args, **kwargs):
        raise AssertionError(
            "build_planning_status must not invoke subprocess/os.system"
        )

    with (
        patch("subprocess.run", side_effect=_explode),
        patch("subprocess.Popen", side_effect=_explode),
        patch("subprocess.call", side_effect=_explode),
        patch("subprocess.check_call", side_effect=_explode),
        patch("subprocess.check_output", side_effect=_explode),
        patch("os.system", side_effect=_explode),
        patch("os.popen", side_effect=_explode),
    ):
        result = cs_setup.build_planning_status(manifest)

    assert result.capability_id == "firebase-dashboard"
    # status must be from the closed set (pure requires-based)
    assert result.status in {
        cs_status.CapabilityStatus.READY,
        cs_status.CapabilityStatus.NEEDS_SETUP,
        cs_status.CapabilityStatus.BLOCKED,
        cs_status.CapabilityStatus.NOT_INSTALLED,
        cs_status.CapabilityStatus.OPTIONAL,
    }
