"""Plan 2026-05-19-002 F001 — prereq_registry unit tests."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from dontpanic_orchestrate import prereq_registry as pr


# ── (1) PrereqProbe dataclass field validation ─────────────────────────


def test_prereq_probe_rejects_shell_string_fix_command() -> None:
    with pytest.raises(ValueError, match="fix_command must be list"):
        pr.PrereqProbe(
            name="bad",
            probe_command=lambda: (True, "ok"),
            version_constraint=None,
            fix_url="https://example.com",
            fix_command="brew install jq && gh auth login",  # type: ignore[arg-type]
            auto_install_safe=False,
            why_needed="x",
            required_for_profiles=frozenset({"core"}),
            activation_condition=pr.ActivationCondition.ALWAYS,
            severity_when_inactive=pr.SeverityWhenInactive.OMIT,
        )


def test_prereq_probe_rejects_non_string_in_fix_command_list() -> None:
    with pytest.raises(ValueError, match="fix_command must be list"):
        pr.PrereqProbe(
            name="bad",
            probe_command=lambda: (True, "ok"),
            version_constraint=None,
            fix_url="https://example.com",
            fix_command=["brew", 42],  # type: ignore[list-item]
            auto_install_safe=False,
            why_needed="x",
            required_for_profiles=frozenset({"core"}),
            activation_condition=pr.ActivationCondition.ALWAYS,
            severity_when_inactive=pr.SeverityWhenInactive.OMIT,
        )


# ── (2) ProfileRegistry profiles are pure sets ─────────────────────────


def test_profile_registry_has_five_pure_set_profiles() -> None:
    registry = pr.default_profile_registry()
    assert set(registry.profiles.keys()) == {
        "core",
        "discord",
        "firebase-dashboard",
        "openclaw",
        "ci",
    }
    # No conditional pseudo-profiles.
    for name in registry.profiles:
        assert "when" not in name and "if" not in name


def test_profile_registry_has_no_maintainer_profile() -> None:
    registry = pr.default_profile_registry()
    assert "maintainer" not in registry.profiles


def test_profile_registry_probe_membership_is_frozenset() -> None:
    registry = pr.default_profile_registry()
    for profile, members in registry.profiles.items():
        assert isinstance(members, frozenset), profile


# ── (3) + (4) ActivationContext resolves predicates ────────────────────


def test_activation_context_detects_github_remote(tmp_path, monkeypatch) -> None:
    import subprocess

    calls = {}

    def _fake_run(argv, *args: Any, **kwargs: Any):
        calls["argv"] = argv
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout="origin\thttps://github.com/foo/bar.git (fetch)\n",
            stderr="",
        )

    monkeypatch.setattr(pr.subprocess, "run", _fake_run)
    assert pr._detect_github_remote(tmp_path) is True


def test_activation_context_handles_missing_github_remote(tmp_path, monkeypatch) -> None:
    import subprocess

    def _fake_run(argv, *args: Any, **kwargs: Any):
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout="origin\thttps://gitlab.com/foo/bar.git (fetch)\n",
            stderr="",
        )

    monkeypatch.setattr(pr.subprocess, "run", _fake_run)
    assert pr._detect_github_remote(tmp_path) is False


def test_activation_context_resolves_auditor_codex_from_env_file(tmp_path) -> None:
    env_file = tmp_path / "environments.json"
    env_file.write_text(json.dumps({"repo": "test", "auditor": "codex", "dev": {"firebase_project": "x"}}))
    assert pr._detect_auditor_codex_selected(tmp_path, invocation_flags=None) is True


def test_activation_context_resolves_auditor_codex_from_invocation() -> None:
    # No environments.json — invocation flag still wins.
    repo = Path("/nonexistent-test-dir")
    assert pr._detect_auditor_codex_selected(repo, {"auditor": "codex"}) is True
    assert pr._detect_auditor_codex_selected(repo, {"auditor": "claude"}) is False


def test_activation_context_firebase_target_set_reads_env_block(tmp_path) -> None:
    env_file = tmp_path / "environments.json"
    env_file.write_text(json.dumps({"repo": "x", "dev": {"firebase_project": "p1"}}))
    assert pr._detect_firebase_target_set(tmp_path) is True

    env_file.write_text(json.dumps({"repo": "x", "dev": {"gcp_project": "g1"}}))
    assert pr._detect_firebase_target_set(tmp_path) is False


# ── (5) ProbeRunner per-probe timeout enforcement ──────────────────────


def test_probe_runner_enforces_per_probe_timeout(monkeypatch) -> None:
    # Synthetic slow probe: sleeps 5s, timeout is 0.3s.
    def _slow_probe() -> tuple[bool, str]:
        time.sleep(5.0)
        return True, "should not see this"

    slow = pr.PrereqProbe(
        name="slow-probe",
        probe_command=_slow_probe,
        version_constraint=None,
        fix_url="https://example.com",
        fix_command=["echo", "fix"],
        auto_install_safe=False,
        why_needed="test",
        required_for_profiles=frozenset({"core"}),
        activation_condition=pr.ActivationCondition.ALWAYS,
        severity_when_inactive=pr.SeverityWhenInactive.OMIT,
        timeout_s=0.3,
    )
    ctx = pr.ActivationContext(
        repo_root=Path("."),
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    started = time.monotonic()
    sweep = pr.run_sweep(
        profile="core",
        probes=[slow],
        activation_context=ctx,
        wall_clock_budget_s=1.0,
    )
    elapsed = time.monotonic() - started
    # Must NOT have actually waited 5s — wall-clock budget caps it.
    assert elapsed < 2.0
    assert sweep.probes[0].status is pr.ProbeStatus.FAIL


# ── (6) Parallel network probe stays under budget ──────────────────────


def test_full_sweep_stays_under_wall_clock_budget() -> None:
    """A single full-profile sweep must complete within the documented
    10s wall-clock budget. This is the F001 acceptance #7 cap. We
    exercise the default probes (which include a real network probe)
    but keep each probe bounded by its per-probe timeout."""
    ctx = pr.ActivationContext(
        repo_root=Path(__file__).resolve().parents[3],
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    for profile in ("core", "discord", "firebase-dashboard", "openclaw", "ci"):
        started = time.monotonic()
        sweep = pr.run_sweep(
            profile=profile,
            activation_context=ctx,
            wall_clock_budget_s=10.0,
        )
        elapsed = time.monotonic() - started
        assert isinstance(sweep, pr.SweepResult)
        assert elapsed <= 10.0, (
            f"profile={profile} exceeded the 10s wall-clock budget: {elapsed:.2f}s"
        )


def test_aggregate_five_profile_sweep_under_10s_budget() -> None:
    """F001-i1 medium/test_coverage hand-patch.

    The locked acceptance signal "Full sweep wall clock <=10s under
    --profile=core" extends to the whole probe registry: an operator
    walking through ``dontpanic init`` is going to sweep multiple
    profiles in sequence (core, then per-target capability profiles),
    so the *aggregate* wall clock for all five profiles back-to-back
    must also stay under 10s. The earlier per-profile test only caps
    each one at 10s individually — five profiles could each take 2s
    and still pass, but a real operator would wait 10s total.

    This adds an aggregate timer around the whole sweep set."""
    ctx = pr.ActivationContext(
        repo_root=Path(__file__).resolve().parents[3],
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    aggregate_started = time.monotonic()
    for profile in ("core", "discord", "firebase-dashboard", "openclaw", "ci"):
        pr.run_sweep(
            profile=profile,
            activation_context=ctx,
            wall_clock_budget_s=10.0,
        )
    aggregate_elapsed = time.monotonic() - aggregate_started
    assert aggregate_elapsed <= 10.0, (
        f"all-five-profile aggregate sweep exceeded 10s budget: "
        f"{aggregate_elapsed:.2f}s"
    )


# ── (7) JSON envelope schema is stable ─────────────────────────────────


def test_envelope_schema_has_pinned_top_level_keys() -> None:
    sweep = pr.SweepResult(profile="core", probes=[], elapsed_s=0.0)
    env = pr.envelope_for_sweep(sweep, generated_at="2026-05-20T00:00:00Z")
    assert env["schema_version"] == "1.0.0"
    assert env["profile"] == "core"
    assert env["generated_at"] == "2026-05-20T00:00:00Z"
    assert env["exit_code"] == 0
    assert env["prereq_probes"] == []
    assert env["legacy_checks"] == []
    assert set(env.keys()) == {
        "schema_version",
        "profile",
        "generated_at",
        "exit_code",
        "prereq_probes",
        "legacy_checks",
    }


def test_envelope_probe_item_field_order_is_pinned() -> None:
    probe_result = pr.ProbeResult(
        name="x",
        status=pr.ProbeStatus.PASS,
        severity_reason="ok",
        version_found="1.0",
        fix_url="https://example.com",
        fix_command=["echo", "fix"],
        required_for_profiles=["core"],
        activation_condition="always",
        activation_resolved=True,
        elapsed_s=0.01,
    )
    sweep = pr.SweepResult(profile="core", probes=[probe_result], elapsed_s=0.01)
    env = pr.envelope_for_sweep(sweep, generated_at="2026-05-20T00:00:00Z")
    item = env["prereq_probes"][0]
    assert list(item.keys()) == [
        "name",
        "status",
        "severity_reason",
        "version_found",
        "fix_url",
        "fix_command",
        "required_for_profiles",
        "activation_condition",
        "activation_resolved",
        "elapsed_s",
    ]


# ── (8) --profile=core does NOT emit Firebase/agent-conventions ─────────


def test_profile_core_does_not_emit_firebase_dashboard_probes() -> None:
    """The single most important UX guarantee: ``--profile=core`` must
    not red-flag Firebase, gcloud, SA-key, openclaw, discord, etc."""
    ctx = pr.ActivationContext(
        repo_root=Path("/nonexistent-test-dir"),
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    sweep = pr.run_sweep(profile="core", activation_context=ctx)
    names = {p.name for p in sweep.probes}
    forbidden = {
        "firebase-cli",
        "gcloud",
        "sa-key",
        "openclaw-cli",
        "openrouter-key",
        "discord-webhook",
        "sanitization-regex",
    }
    leaked = forbidden & names
    assert not leaked, f"profile=core leaked maintainer-only probes: {leaked}"


# ── (9) codex probe conditional severity ───────────────────────────────


def _codex_probe_only() -> list[pr.PrereqProbe]:
    """Return just the codex-cli probe so tests don't accidentally hit
    other host CLIs."""
    return [p for p in pr.default_probes() if p.name == "codex-cli"]


def _gh_auth_probe_only() -> list[pr.PrereqProbe]:
    return [p for p in pr.default_probes() if p.name == "gh-auth-status"]


def test_codex_probe_is_advisory_under_core_when_codex_not_selected(monkeypatch) -> None:
    """When --profile=core and activation_condition.auditor_codex_selected
    is false, codex-cli surfaces as ADVISORY (not FAIL/WARN)."""
    monkeypatch.setattr(pr.shutil, "which", lambda name: None)
    ctx = pr.ActivationContext(
        repo_root=Path("/nonexistent"),
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    sweep = pr.run_sweep(profile="core", probes=_codex_probe_only(), activation_context=ctx)
    codex = next((p for p in sweep.probes if p.name == "codex-cli"), None)
    assert codex is not None, "codex-cli must surface under core (advisory)"
    assert codex.status is pr.ProbeStatus.ADVISORY


def test_codex_probe_is_fail_under_ci_when_missing(monkeypatch) -> None:
    """In-profile membership → FAIL on missing, regardless of activation."""
    monkeypatch.setattr(pr.shutil, "which", lambda name: None)
    ctx = pr.ActivationContext(
        repo_root=Path("/nonexistent"),
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    sweep = pr.run_sweep(profile="ci", probes=_codex_probe_only(), activation_context=ctx)
    codex = next((p for p in sweep.probes if p.name == "codex-cli"), None)
    assert codex is not None
    assert codex.status is pr.ProbeStatus.FAIL


def test_codex_probe_escalates_to_fail_under_core_when_codex_selected(monkeypatch) -> None:
    """ADVISORY-when-inactive escalates to FAIL once the operator opts
    in to codex via activation_condition.auditor_codex_selected=True."""
    monkeypatch.setattr(pr.shutil, "which", lambda name: None)
    ctx = pr.ActivationContext(
        repo_root=Path("/nonexistent"),
        github_remote_present=False,
        auditor_codex_selected=True,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    sweep = pr.run_sweep(profile="core", probes=_codex_probe_only(), activation_context=ctx)
    codex = next((p for p in sweep.probes if p.name == "codex-cli"), None)
    assert codex is not None
    assert codex.status is pr.ProbeStatus.FAIL


# ── (10) gh-auth probe conditional severity ────────────────────────────


def test_gh_auth_is_warn_under_core_when_github_remote_present(monkeypatch) -> None:
    def _fake_run(argv, *args: Any, **kwargs: Any):
        import subprocess

        return subprocess.CompletedProcess(
            args=argv, returncode=1, stdout="", stderr="not authenticated"
        )

    monkeypatch.setattr(pr.subprocess, "run", _fake_run)
    ctx = pr.ActivationContext(
        repo_root=Path("/nonexistent"),
        github_remote_present=True,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    sweep = pr.run_sweep(
        profile="core", probes=_gh_auth_probe_only(), activation_context=ctx
    )
    gh = next((p for p in sweep.probes if p.name == "gh-auth-status"), None)
    assert gh is not None
    assert gh.status is pr.ProbeStatus.WARN


def test_gh_auth_is_omitted_under_core_when_no_github_remote(monkeypatch) -> None:
    """When github_remote_present resolves false, gh-auth-status must
    NOT appear in output under --profile=core — i.e. no remote, no probe."""

    def _fake_run(argv, *args: Any, **kwargs: Any):
        import subprocess

        # Force gh-auth to fail so we exercise the missing-auth branch.
        return subprocess.CompletedProcess(
            args=argv, returncode=1, stdout="", stderr="not authenticated"
        )

    monkeypatch.setattr(pr.subprocess, "run", _fake_run)
    ctx = pr.ActivationContext(
        repo_root=Path("/nonexistent"),
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    sweep = pr.run_sweep(
        profile="core", probes=_gh_auth_probe_only(), activation_context=ctx
    )
    gh = next((p for p in sweep.probes if p.name == "gh-auth-status"), None)
    assert gh is None, "gh-auth-status must be omitted when no github remote"


def test_gh_auth_is_fail_under_ci_when_missing(monkeypatch) -> None:
    """gh-auth is required_for=ci → FAIL on missing regardless of remote."""

    def _fake_run(argv, *args: Any, **kwargs: Any):
        import subprocess

        return subprocess.CompletedProcess(
            args=argv, returncode=1, stdout="", stderr="not authenticated"
        )

    monkeypatch.setattr(pr.subprocess, "run", _fake_run)
    ctx = pr.ActivationContext(
        repo_root=Path("/nonexistent"),
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    sweep = pr.run_sweep(
        profile="ci", probes=_gh_auth_probe_only(), activation_context=ctx
    )
    gh = next((p for p in sweep.probes if p.name == "gh-auth-status"), None)
    assert gh is not None
    assert gh.status is pr.ProbeStatus.FAIL


# ── (11) python<3.10 + missing claude CLI are unconditional fails ──────


def test_python_below_3_10_is_unconditional_fail(monkeypatch) -> None:
    fake_probes = [
        pr.PrereqProbe(
            name="python-version",
            probe_command=lambda: (False, "python 3.9 (need >=3.10)"),
            version_constraint=">=3.10",
            fix_url="https://www.python.org/downloads/",
            fix_command=["echo", "Install Python 3.10+"],
            auto_install_safe=False,
            why_needed="x",
            required_for_profiles=frozenset({"core"}),
            activation_condition=pr.ActivationCondition.ALWAYS,
            severity_when_inactive=pr.SeverityWhenInactive.OMIT,
        )
    ]
    ctx = pr.ActivationContext(
        repo_root=Path("/nonexistent"),
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    sweep = pr.run_sweep(profile="core", probes=fake_probes, activation_context=ctx)
    assert sweep.probes[0].status is pr.ProbeStatus.FAIL
    assert sweep.exit_code() == 2


def test_missing_claude_cli_is_unconditional_fail_under_core(monkeypatch) -> None:
    monkeypatch.setattr(pr.shutil, "which", lambda name: None)
    ctx = pr.ActivationContext(
        repo_root=Path("/nonexistent"),
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    claude_only = [p for p in pr.default_probes() if p.name == "claude-cli"]
    sweep = pr.run_sweep(profile="core", probes=claude_only, activation_context=ctx)
    claude = next((p for p in sweep.probes if p.name == "claude-cli"), None)
    assert claude is not None
    assert claude.status is pr.ProbeStatus.FAIL


# ── (12) --profile=unknown argparse error ──────────────────────────────


def test_unknown_profile_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown profile"):
        pr.run_sweep(profile="maintainer")  # explicitly forbidden


# ── (13) --profile-strict promotes WARN -> FAIL ────────────────────────


def test_profile_strict_promotes_warn_to_fail(monkeypatch) -> None:
    def _fake_run(argv, *args: Any, **kwargs: Any):
        import subprocess

        return subprocess.CompletedProcess(
            args=argv, returncode=1, stdout="", stderr="not authenticated"
        )

    monkeypatch.setattr(pr.subprocess, "run", _fake_run)
    ctx = pr.ActivationContext(
        repo_root=Path("/nonexistent"),
        github_remote_present=True,  # warn-under-core path
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )
    relaxed = pr.run_sweep(
        profile="core",
        probes=_gh_auth_probe_only(),
        activation_context=ctx,
        profile_strict=False,
    )
    strict = pr.run_sweep(
        profile="core",
        probes=_gh_auth_probe_only(),
        activation_context=ctx,
        profile_strict=True,
    )

    def _status(sweep, name):
        return next((p.status for p in sweep.probes if p.name == name), None)

    assert _status(relaxed, "gh-auth-status") is pr.ProbeStatus.WARN
    assert _status(strict, "gh-auth-status") is pr.ProbeStatus.FAIL


# ── per-probe registry hygiene ─────────────────────────────────────────


def test_every_probe_has_fix_url_and_list_fix_command() -> None:
    for probe in pr.default_probes():
        assert probe.fix_url.startswith(("http://", "https://")) or probe.fix_url == ""
        assert isinstance(probe.fix_command, list)
        assert all(isinstance(s, str) for s in probe.fix_command)
        # No shell-string smuggling.
        joined = " ".join(probe.fix_command)
        assert "&&" not in joined and "||" not in joined and "|" not in joined.split(" echo")[0]
