"""Plan 2026-05-22-002 F002 — `dontpanic capabilities status` CLI tests."""

from __future__ import annotations

import io
import json
import stat
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from dontpanic_orchestrate import capabilities_status as cs
from dontpanic_orchestrate.capabilities import load_capabilities
from dontpanic_orchestrate.prereq_registry import (
    ActivationCondition,
    PrereqProbe,
    ProbeResult,
    ProbeStatus,
    SeverityWhenInactive,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _probe_result(
    *,
    name: str,
    status: ProbeStatus,
    reason: str = "fixture",
    capability_id: str | None = None,
) -> ProbeResult:
    return ProbeResult(
        name=name,
        status=status,
        severity_reason=reason,
        version_found=None,
        fix_url="https://example.invalid/fix",
        fix_command=["echo", "fix"],
        required_for_profiles=["core"],
        activation_condition="always",
        activation_resolved=True,
        elapsed_s=0.0,
        capability_id=capability_id,
        setup_doc=None,
    )


# ── unit tests against compute_capability_status ──────────────────────────


def test_compute_status_ready_when_everything_resolves():
    manifest = load_capabilities(REPO_ROOT).require("agent-claude-cli")
    resolution = cs.RequiresResolution(
        resolved_commands=("claude",),
        resolved_env=(),
        resolved_files=("~/.dontpanic/config.json",),
    )
    probes = [_probe_result(name="cli:claude", status=ProbeStatus.PASS)]

    status = cs.compute_capability_status(manifest, probes, resolution)

    assert status is cs.CapabilityStatus.READY


def test_compute_status_blocked_when_any_non_pending_probe_fails():
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    resolution = cs.RequiresResolution(
        resolved_commands=("firebase", "gcloud"),
        resolved_env=("DONTPANIC_FIREBASE_PROJECT",),
        resolved_files=("environments.json", ".firebaserc"),
    )
    probes = [
        _probe_result(name="cli:firebase", status=ProbeStatus.PASS),
        _probe_result(name="firebase-auth", status=ProbeStatus.FAIL, reason="not logged in"),
    ]

    status = cs.compute_capability_status(manifest, probes, resolution)

    assert status is cs.CapabilityStatus.BLOCKED


def test_compute_status_needs_setup_when_requires_unresolved():
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    resolution = cs.RequiresResolution(
        unresolved_commands=("firebase",),
        unresolved_env=("DONTPANIC_FIREBASE_PROJECT",),
    )
    probes = [_probe_result(name="cli:firebase", status=ProbeStatus.PASS)]

    status = cs.compute_capability_status(manifest, probes, resolution)

    assert status is cs.CapabilityStatus.NEEDS_SETUP


def test_compute_status_needs_setup_when_auth_or_config_unconfirmed():
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    resolution = cs.RequiresResolution(
        resolved_commands=("firebase", "gcloud"),
        resolved_env=("DONTPANIC_FIREBASE_PROJECT",),
        resolved_files=("environments.json", ".firebaserc"),
        informational_auth=("firebase login",),
        informational_config=("Firestore rules",),
    )
    probes = [_probe_result(name="cli:firebase", status=ProbeStatus.PASS)]

    status = cs.compute_capability_status(manifest, probes, resolution)

    assert status is cs.CapabilityStatus.NEEDS_SETUP


def test_pending_probes_alone_do_not_block_status():
    """Acceptance #4: PENDING probes alone never produce `blocked`."""
    manifest = load_capabilities(REPO_ROOT).require("agent-claude-cli")
    resolution = cs.RequiresResolution(
        resolved_commands=("claude",),
        resolved_files=("~/.dontpanic/config.json",),
    )
    probes = [
        _probe_result(name="cli:claude", status=ProbeStatus.PENDING, reason="not wired"),
        _probe_result(name="agent_role_config", status=ProbeStatus.PENDING),
    ]

    status = cs.compute_capability_status(manifest, probes, resolution)

    assert status is cs.CapabilityStatus.READY


def test_not_installed_overrides_other_status():
    manifest = load_capabilities(REPO_ROOT).require("linear")
    resolution = cs.RequiresResolution()
    probes: list[ProbeResult] = []

    status = cs.compute_capability_status(manifest, probes, resolution, adapter_is_installed=False)

    assert status is cs.CapabilityStatus.NOT_INSTALLED


def test_optional_when_filtered_out_of_profile():
    manifest = load_capabilities(REPO_ROOT).require("discord-notify")
    resolution = cs.RequiresResolution(resolved_commands=())
    probes: list[ProbeResult] = []

    status = cs.compute_capability_status(manifest, probes, resolution, in_active_profile=False)

    assert status is cs.CapabilityStatus.OPTIONAL


# ── envelope assembly + rendering ─────────────────────────────────────────


def test_run_status_renders_all_four_checked_in_manifests():
    """Acceptance #1: runs against the four checked-in manifests."""
    envelope = cs.run_status(
        capability_index=load_capabilities(REPO_ROOT),
        probes=[],  # forces graceful-degradation path
        repo_root=REPO_ROOT,
    )

    ids = [c.capability_id for c in envelope.capabilities]
    assert set(ids) == {
        "agent-claude-cli",
        "discord-notify",
        "firebase-dashboard",
        "linear",
    }
    text = cs.render_text(envelope)
    assert "Capability status (schema 1.0.0)" in text
    for cap in envelope.capabilities:
        assert cap.capability_id in text


def test_json_render_is_stable_snapshot_shape():
    """Acceptance #2 + #5: stable JSON snapshot with PENDING + automatable/human_required arrays."""
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    resolution = cs.RequiresResolution(
        resolved_commands=("firebase", "gcloud"),
        unresolved_env=("DONTPANIC_FIREBASE_PROJECT",),
        informational_services=("Firebase project",),
    )
    probes = [
        _probe_result(
            name="firebase-auth",
            status=ProbeStatus.PENDING,
            reason="needs_probe_implementation",
        ),
    ]
    result = cs.build_capability_result(
        manifest, probes, requires_resolution=resolution, in_active_profile=True
    )
    envelope = cs.StatusEnvelope(
        schema_version=cs.SCHEMA_VERSION,
        generated_at="2026-05-22T00:00:00Z",
        capabilities=(result,),
    )

    payload = json.loads(cs.render_json(envelope))

    expected = {
        "advisory_notes": [],
        "capabilities": [
            {
                "advisory_notes": [],
                "automatable": [
                    {
                        "command_template": "npm install -g firebase-tools",
                        "id": "install_firebase_cli",
                        "what": "Install the Firebase CLI so the operator can deploy rules and Cloud Functions.",
                    },
                    {
                        "command_template": "curl -sSL https://sdk.cloud.google.com | bash",
                        "id": "install_gcloud_cli",
                        "what": "Install the gcloud CLI so the operator can manage service accounts and deploy credentials.",
                    },
                    {
                        "command_template": "firebase use --add --project <YOUR_FIREBASE_PROJECT_ID>",
                        "id": "select_target_project",
                        "what": "Point the local Firebase config at the operator's target Firebase project.",
                    },
                    {
                        "command_template": "firebase deploy --project <YOUR_FIREBASE_PROJECT_ID> --only firestore:rules",
                        "id": "deploy_firestore_rules",
                        "what": "Deploy the dashboard Firestore rules so the mirror collection enforces read-only browser access.",
                    },
                    {
                        "command_template": "firebase deploy --project <YOUR_FIREBASE_PROJECT_ID> --only functions",
                        "id": "deploy_cloud_functions",
                        "what": "Deploy the Cloud Functions that proxy dashboard mutations through the DontPanic MCP server.",
                    },
                    {
                        "command_template": "dontpanic mcp serve --bind 127.0.0.1:<YOUR_MCP_PORT>",
                        "id": "run_mcp_bridge",
                        "what": "Start the local MCP bridge process the Cloud Functions call back into for mutations.",
                    },
                    {
                        "command_template": "dontpanic capabilities smoke firebase-dashboard --project <YOUR_FIREBASE_PROJECT_ID>",
                        "id": "smoke_test",
                        "what": "Trigger a dashboard action end-to-end to confirm the browser->Cloud Function->MCP mutation path is wired.",
                    },
                ],
                "capability_id": "firebase-dashboard",
                "configured": ["firebase", "gcloud"],
                "human_required": [
                    {
                        "command_template": "firebase login",
                        "human_required_reason": "Requires interactive browser sign-in with the operator's Google account; DontPanic cannot proxy this consent.",
                        "id": "firebase_login",
                        "what": "Authenticate the Firebase CLI against the operator's Google account.",
                    },
                    {
                        "command_template": "gcloud auth login && gcloud auth application-default login",
                        "human_required_reason": "Requires interactive browser sign-in; the operator must approve cloud platform scopes.",
                        "id": "gcloud_auth_login",
                        "what": "Authenticate gcloud and set application-default credentials for deploys.",
                    },
                ],
                "missing": [
                    "DONTPANIC_FIREBASE_PROJECT",
                    "Firebase project",
                ],
                "next_actions": [
                    {
                        "automatable": True,
                        "command_template": "npm install -g firebase-tools",
                        "human_required_reason": None,
                        "id": "install_firebase_cli",
                        "verify_probe": "cli:firebase",
                        "what": "Install the Firebase CLI so the operator can deploy rules and Cloud Functions.",
                    },
                    {
                        "automatable": True,
                        "command_template": "curl -sSL https://sdk.cloud.google.com | bash",
                        "human_required_reason": None,
                        "id": "install_gcloud_cli",
                        "verify_probe": "cli:gcloud",
                        "what": "Install the gcloud CLI so the operator can manage service accounts and deploy credentials.",
                    },
                    {
                        "automatable": False,
                        "command_template": "firebase login",
                        "human_required_reason": "Requires interactive browser sign-in with the operator's Google account; DontPanic cannot proxy this consent.",
                        "id": "firebase_login",
                        "verify_probe": "firebase-auth",
                        "what": "Authenticate the Firebase CLI against the operator's Google account.",
                    },
                    {
                        "automatable": False,
                        "command_template": "gcloud auth login && gcloud auth application-default login",
                        "human_required_reason": "Requires interactive browser sign-in; the operator must approve cloud platform scopes.",
                        "id": "gcloud_auth_login",
                        "verify_probe": "gcloud-auth",
                        "what": "Authenticate gcloud and set application-default credentials for deploys.",
                    },
                    {
                        "automatable": True,
                        "command_template": "firebase use --add --project <YOUR_FIREBASE_PROJECT_ID>",
                        "human_required_reason": None,
                        "id": "select_target_project",
                        "verify_probe": "target-project",
                        "what": "Point the local Firebase config at the operator's target Firebase project.",
                    },
                    {
                        "automatable": True,
                        "command_template": "firebase deploy --project <YOUR_FIREBASE_PROJECT_ID> --only firestore:rules",
                        "human_required_reason": None,
                        "id": "deploy_firestore_rules",
                        "verify_probe": None,
                        "what": "Deploy the dashboard Firestore rules so the mirror collection enforces read-only browser access.",
                    },
                    {
                        "automatable": True,
                        "command_template": "firebase deploy --project <YOUR_FIREBASE_PROJECT_ID> --only functions",
                        "human_required_reason": None,
                        "id": "deploy_cloud_functions",
                        "verify_probe": None,
                        "what": "Deploy the Cloud Functions that proxy dashboard mutations through the DontPanic MCP server.",
                    },
                    {
                        "automatable": True,
                        "command_template": "dontpanic mcp serve --bind 127.0.0.1:<YOUR_MCP_PORT>",
                        "human_required_reason": None,
                        "id": "run_mcp_bridge",
                        "verify_probe": "firebase_dashboard_config",
                        "what": "Start the local MCP bridge process the Cloud Functions call back into for mutations.",
                    },
                    {
                        "automatable": True,
                        "command_template": "dontpanic capabilities smoke firebase-dashboard --project <YOUR_FIREBASE_PROJECT_ID>",
                        "human_required_reason": None,
                        "id": "smoke_test",
                        "verify_probe": "firebase_dashboard_config",
                        "what": "Trigger a dashboard action end-to-end to confirm the browser->Cloud Function->MCP mutation path is wired.",
                    },
                ],
                "owner_boundary": {
                    "adapter": [
                        "Firestore mirror schema",
                        "sync daemon",
                        "Firebase dashboard configuration",
                        "Cloud Functions that call DontPanic MCP",
                        "Firestore rules",
                    ],
                    "dontpanic_core": [
                        "state projection",
                        "bundled static dashboard export",
                        "MCP mutation tools",
                        "doctor profile hooks",
                        "adapter governance contract",
                    ],
                    "operator": [
                        "Firebase project ownership",
                        "Firebase Auth configuration",
                        "gcloud/firebase authentication",
                        "service account and deploy credentials",
                        "cost and quota management",
                        "hosting/deploy choice",
                    ],
                },
                "pending_probes": [
                    {"name": "firebase-auth", "reason": "needs_probe_implementation"}
                ],
                "status": "needs_setup",
            }
        ],
        "generated_at": "2026-05-22T00:00:00Z",
        "schema_version": "1.0.0",
    }
    assert payload == expected
    cap = payload["capabilities"][0]
    assert cap["status"] in cs.CAPABILITY_STATUS_VALUES
    assert "pending" not in cs.CAPABILITY_STATUS_VALUES  # PENDING is probe-state only.


def test_pending_probe_renders_as_informational_chip_in_text():
    """Acceptance #5: text output carries a `probe pending` chip."""
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    probes = [
        _probe_result(
            name="firebase-auth",
            status=ProbeStatus.PENDING,
            reason="needs_probe_implementation",
        ),
    ]
    result = cs.build_capability_result(
        manifest,
        probes,
        requires_resolution=cs.RequiresResolution(),
        in_active_profile=True,
    )
    envelope = cs.StatusEnvelope(
        schema_version=cs.SCHEMA_VERSION,
        generated_at="2026-05-22T00:00:00Z",
        capabilities=(result,),
    )

    text = cs.render_text(envelope)

    assert "probe pending: firebase-auth — needs_probe_implementation" in text


def test_firebase_dashboard_detail_view_emits_six_next_actions():
    """Acceptance #3: detail view exposes ≥6 next_actions sourced from setup_steps."""
    envelope = cs.run_status(
        capability_index=load_capabilities(REPO_ROOT),
        probes=[],
        repo_root=REPO_ROOT,
    )

    detail = cs.filter_for_capability(envelope, "firebase-dashboard", load_capabilities(REPO_ROOT))

    assert len(detail.capabilities) == 1
    assert len(detail.capabilities[0].next_actions) >= 6


def test_profile_filter_excludes_unrelated_capabilities():
    """Acceptance #7: --profile=firebase-dashboard filters that profile."""
    envelope = cs.run_status(
        capability_index=load_capabilities(REPO_ROOT),
        probes=[],
        profile="firebase-dashboard",
        repo_root=REPO_ROOT,
    )

    assert [c.capability_id for c in envelope.capabilities] == ["firebase-dashboard"]
    assert envelope.capabilities[0].status is not cs.CapabilityStatus.OPTIONAL


# ── CLI behaviour: cache + flags + unknown id ─────────────────────────────


def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Re-root ``~`` so cache writes land under ``tmp_path``."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Stale module-level constant resolved from a real $HOME at import time —
    # patch it to the new sandbox path.
    monkeypatch.setattr(
        cs, "DEFAULT_CACHE_PATH", tmp_path / ".dontpanic" / "capabilities-status.json"
    )
    return tmp_path


def test_cli_writes_cache_with_mode_0600(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Acceptance #6: cache written; mode 0600."""
    home = _isolated_home(tmp_path, monkeypatch)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = cs.main(["status", "--format=json"])

    assert exit_code == 0
    cache_path = home / ".dontpanic" / "capabilities-status.json"
    assert cache_path.is_file(), stderr.getvalue()
    mode_bits = stat.S_IMODE(cache_path.stat().st_mode)
    assert mode_bits == 0o600
    # Cache must equal stdout JSON for downstream consumers.
    assert cache_path.read_text(encoding="utf-8") == stdout.getvalue()


def test_no_cache_write_flag_skips_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Acceptance #6 inverse: --no-cache-write skips cache."""
    home = _isolated_home(tmp_path, monkeypatch)
    stdout = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
        exit_code = cs.main(["status", "--format=json", "--no-cache-write"])

    assert exit_code == 0
    cache_path = home / ".dontpanic" / "capabilities-status.json"
    assert not cache_path.exists()


def test_unknown_capability_id_exits_nonzero_with_suggestion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Acceptance #8: unknown id exits non-zero with closest-match suggestion."""
    _isolated_home(tmp_path, monkeypatch)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = cs.main(["status", "firebase-dashboarrd", "--format=json", "--no-cache-write"])

    assert exit_code == 2
    assert "firebase-dashboard" in stderr.getvalue()


def test_graceful_degradation_when_no_probes_have_capability_id(tmp_path: Path):
    """Acceptance #9: works when V0a F002 binding has not landed."""
    unbound_probe = PrereqProbe(
        name="some-unbound-probe",
        probe_command=lambda: (True, "ok"),
        version_constraint=None,
        fix_url="https://example.invalid",
        fix_command=["echo", "noop"],
        auto_install_safe=False,
        why_needed="fixture",
        required_for_profiles=frozenset({"core"}),
        activation_condition=ActivationCondition.ALWAYS,
        severity_when_inactive=SeverityWhenInactive.OMIT,
    )

    envelope = cs.run_status(
        capability_index=load_capabilities(REPO_ROOT),
        probes=[unbound_probe],
        repo_root=REPO_ROOT,
    )

    assert any(
        "No probes declare capability_id bindings" in note for note in envelope.advisory_notes
    )
    # Status is still computed for every manifest.
    assert {c.capability_id for c in envelope.capabilities} == {
        "agent-claude-cli",
        "discord-notify",
        "firebase-dashboard",
        "linear",
    }


def test_automatable_partition_matches_setup_steps_kind():
    """Acceptance: automatable[]/human_required[] partition derives from setup_steps."""
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    result = cs.build_capability_result(
        manifest,
        probe_results=(),
        requires_resolution=cs.RequiresResolution(),
        in_active_profile=True,
    )

    auto_ids = {entry["id"] for entry in result.automatable}
    human_ids = {entry["id"] for entry in result.human_required}
    for step in manifest.setup_steps:
        if step.automatable:
            assert step.id in auto_ids
            assert step.id not in human_ids
        else:
            assert step.id in human_ids
            assert step.id not in auto_ids


def test_requires_resolution_uses_injected_env_and_which(tmp_path: Path):
    """Pure function — resolves against an injected env/which without touching $PATH."""
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")
    # Pretend gcloud is present but firebase isn't; pretend the env var is set.
    fake_which = lambda cmd: "/usr/bin/" + cmd if cmd == "gcloud" else None  # noqa: E731 - test stub
    fake_env = {"DONTPANIC_FIREBASE_PROJECT": "fake-project"}

    res = cs.resolve_requires(manifest, env=fake_env, home=tmp_path, which=fake_which)

    assert "gcloud" in res.resolved_commands
    assert "firebase" in res.unresolved_commands
    assert "DONTPANIC_FIREBASE_PROJECT" in res.resolved_env


def test_cli_text_default_renders_owner_boundary_chips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Acceptance #1: text output includes owner_boundary chips."""
    _isolated_home(tmp_path, monkeypatch)
    stdout = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
        exit_code = cs.main(["status", "--no-cache-write"])

    assert exit_code == 0
    out = stdout.getvalue()
    assert "owner_boundary:" in out
    assert "firebase-dashboard" in out
