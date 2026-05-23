"""Plan 2026-05-21-001 F002 — capability_id binding on prereq probes.

Acceptance covered:
  (1) PrereqProbe and ProbeResult include optional capability_id.
  (2) Bound probe IDs validate through the F001 manifest loader.
  (3) Doctor JSON includes capability_id + setup_doc for bound probes.
  (4) Existing profile severity behavior is unchanged.
  (5) Tests cover Claude, Firebase, Discord, and an invalid
      capability_id registry-authoring failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dontpanic_orchestrate import capabilities as cap
from dontpanic_orchestrate import prereq_registry as pr

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── (1) dataclass fields wire through ──────────────────────────────────


def test_prereq_probe_accepts_optional_capability_id() -> None:
    probe = pr.PrereqProbe(
        name="x",
        probe_command=lambda: (True, "ok"),
        version_constraint=None,
        fix_url="https://example.com",
        fix_command=["echo", "ok"],
        auto_install_safe=False,
        why_needed="x",
        required_for_profiles=frozenset({"core"}),
        activation_condition=pr.ActivationCondition.ALWAYS,
        severity_when_inactive=pr.SeverityWhenInactive.OMIT,
        capability_id="agent-claude-cli",
    )
    assert probe.capability_id == "agent-claude-cli"


def test_prereq_probe_default_capability_id_is_none() -> None:
    probe = pr.PrereqProbe(
        name="x",
        probe_command=lambda: (True, "ok"),
        version_constraint=None,
        fix_url="https://example.com",
        fix_command=["echo", "ok"],
        auto_install_safe=False,
        why_needed="x",
        required_for_profiles=frozenset({"core"}),
        activation_condition=pr.ActivationCondition.ALWAYS,
        severity_when_inactive=pr.SeverityWhenInactive.OMIT,
    )
    assert probe.capability_id is None


def test_probe_result_carries_capability_id_and_setup_doc() -> None:
    result = pr.ProbeResult(
        name="x",
        status=pr.ProbeStatus.PASS,
        severity_reason="ok",
        version_found=None,
        fix_url="https://example.com",
        fix_command=["echo", "ok"],
        required_for_profiles=["core"],
        activation_condition="always",
        activation_resolved=True,
        elapsed_s=0.0,
        capability_id="agent-claude-cli",
        setup_doc="docs/GETTING_STARTED.md#setup-tracks--pick-yours",
    )
    assert result.capability_id == "agent-claude-cli"
    assert result.setup_doc == "docs/GETTING_STARTED.md#setup-tracks--pick-yours"


# ── (2) registry construction validates IDs ────────────────────────────


def test_default_probes_bind_expected_capability_ids() -> None:
    """Claude, Firebase (cli/gcloud/sa-key), and Discord must be bound."""
    by_name = {p.name: p.capability_id for p in pr.default_probes()}
    assert by_name["claude-cli"] == "agent-claude-cli"
    assert by_name["firebase-cli"] == "firebase-dashboard"
    assert by_name["gcloud"] == "firebase-dashboard"
    assert by_name["sa-key"] == "firebase-dashboard"
    assert by_name["discord-webhook"] == "discord-notify"
    # Unbound probes stay unbound.
    assert by_name["python-version"] is None
    assert by_name["jq"] is None
    assert by_name["git-user-email"] is None


def test_default_profile_registry_accepts_real_manifest_bindings() -> None:
    """Loading the real registry must succeed — every bound capability_id
    must resolve through the F001 loader against the checked-in manifests."""
    registry = pr.default_profile_registry()
    # Membership is unchanged — capability_id is metadata only.
    assert "claude-cli" in registry.profiles["core"]
    assert "firebase-cli" in registry.profiles["firebase-dashboard"]
    assert "discord-webhook" in registry.profiles["discord"]


def test_default_profile_registry_rejects_unknown_capability_id() -> None:
    """Authoring a probe against a non-existent capability ID must
    fail loud at registry construction time (acceptance #5)."""
    bad_probe = pr.PrereqProbe(
        name="bogus-cli",
        probe_command=lambda: (True, "ok"),
        version_constraint=None,
        fix_url="https://example.com",
        fix_command=["echo", "ok"],
        auto_install_safe=False,
        why_needed="x",
        required_for_profiles=frozenset({"core"}),
        activation_condition=pr.ActivationCondition.ALWAYS,
        severity_when_inactive=pr.SeverityWhenInactive.OMIT,
        capability_id="not-a-real-capability",
    )
    with pytest.raises(ValueError, match="unknown capability_id"):
        pr.default_profile_registry(probes=[bad_probe])


def test_validate_capability_bindings_accepts_injected_index() -> None:
    """The validator can be called with an explicit CapabilityIndex —
    useful for tests that want to avoid filesystem coupling."""
    empty_index = cap.CapabilityIndex([])
    bound = pr.PrereqProbe(
        name="x",
        probe_command=lambda: (True, "ok"),
        version_constraint=None,
        fix_url="https://example.com",
        fix_command=["echo", "ok"],
        auto_install_safe=False,
        why_needed="x",
        required_for_profiles=frozenset({"core"}),
        activation_condition=pr.ActivationCondition.ALWAYS,
        severity_when_inactive=pr.SeverityWhenInactive.OMIT,
        capability_id="agent-claude-cli",
    )
    # An empty index cannot resolve the binding.
    with pytest.raises(ValueError, match="unknown capability_id"):
        pr.validate_capability_bindings([bound], capability_index=empty_index)
    # Unbound probes pass even with an empty index.
    pr.validate_capability_bindings(
        [
            pr.PrereqProbe(
                name="x",
                probe_command=lambda: (True, "ok"),
                version_constraint=None,
                fix_url="https://example.com",
                fix_command=["echo", "ok"],
                auto_install_safe=False,
                why_needed="x",
                required_for_profiles=frozenset({"core"}),
                activation_condition=pr.ActivationCondition.ALWAYS,
                severity_when_inactive=pr.SeverityWhenInactive.OMIT,
            )
        ],
        capability_index=empty_index,
    )


# ── (3) JSON envelope carries capability_id + setup_doc when bound ─────


def _ctx() -> pr.ActivationContext:
    return pr.ActivationContext(
        repo_root=Path("/nonexistent"),
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=True,  # let firebase-* probes run in firebase profile
    )


def _named(probes: list[pr.PrereqProbe], name: str) -> list[pr.PrereqProbe]:
    return [p for p in probes if p.name == name]


def test_envelope_carries_claude_capability_id_and_setup_doc(monkeypatch) -> None:
    monkeypatch.setattr(pr.shutil, "which", lambda name: f"/usr/bin/{name}")
    index = cap.load_capabilities(REPO_ROOT)
    sweep = pr.run_sweep(
        profile="core",
        probes=_named(pr.default_probes(), "claude-cli"),
        activation_context=_ctx(),
        capability_index=index,
    )
    envelope = pr.envelope_for_sweep(sweep, generated_at="2026-05-22T00:00:00Z")
    items = {item["name"]: item for item in envelope["prereq_probes"]}
    claude = items["claude-cli"]
    assert claude["capability_id"] == "agent-claude-cli"
    assert claude["setup_doc"] == index.require("agent-claude-cli").setup_doc


def test_envelope_carries_firebase_capability_id_and_setup_doc(monkeypatch) -> None:
    monkeypatch.setattr(pr.shutil, "which", lambda name: f"/usr/bin/{name}")
    index = cap.load_capabilities(REPO_ROOT)
    firebase_probes = [
        p for p in pr.default_probes() if p.name in {"firebase-cli", "gcloud", "sa-key"}
    ]
    sweep = pr.run_sweep(
        profile="firebase-dashboard",
        probes=firebase_probes,
        activation_context=_ctx(),
        capability_index=index,
    )
    envelope = pr.envelope_for_sweep(sweep, generated_at="2026-05-22T00:00:00Z")
    items = {item["name"]: item for item in envelope["prereq_probes"]}
    expected_setup_doc = index.require("firebase-dashboard").setup_doc
    for probe_name in ("firebase-cli", "gcloud", "sa-key"):
        item = items[probe_name]
        assert item["capability_id"] == "firebase-dashboard"
        assert item["setup_doc"] == expected_setup_doc


def test_envelope_carries_discord_capability_id_and_setup_doc(monkeypatch) -> None:
    monkeypatch.setenv(
        "DONTPANIC_DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/abc/xyz",
    )
    index = cap.load_capabilities(REPO_ROOT)
    sweep = pr.run_sweep(
        profile="discord",
        probes=_named(pr.default_probes(), "discord-webhook"),
        activation_context=_ctx(),
        capability_index=index,
    )
    envelope = pr.envelope_for_sweep(sweep, generated_at="2026-05-22T00:00:00Z")
    items = {item["name"]: item for item in envelope["prereq_probes"]}
    discord = items["discord-webhook"]
    assert discord["capability_id"] == "discord-notify"
    assert discord["setup_doc"] == index.require("discord-notify").setup_doc


def test_envelope_omits_capability_fields_when_probe_unbound() -> None:
    """Backwards-compat: legacy probes without capability_id keep the
    original 10-key envelope shape (no spurious capability_id/setup_doc)."""
    # python-version is NOT bound to a capability — pin the shape.
    result = pr.ProbeResult(
        name="python-version",
        status=pr.ProbeStatus.PASS,
        severity_reason="in-profile + ok",
        version_found="python 3.11",
        fix_url="https://www.python.org/downloads/",
        fix_command=["echo", "Install Python 3.10+"],
        required_for_profiles=["core"],
        activation_condition="always",
        activation_resolved=True,
        elapsed_s=0.001,
    )
    sweep = pr.SweepResult(profile="core", probes=[result], elapsed_s=0.001)
    envelope = pr.envelope_for_sweep(sweep, generated_at="2026-05-22T00:00:00Z")
    item = envelope["prereq_probes"][0]
    assert "capability_id" not in item
    assert "setup_doc" not in item


# ── (4) severity behavior is unchanged for bound probes ────────────────


def test_bound_probes_keep_existing_pass_status(monkeypatch) -> None:
    """Severity must depend only on raw_ok + profile membership +
    severity_when_inactive — capability binding must NOT change it."""
    monkeypatch.setattr(pr.shutil, "which", lambda name: f"/usr/bin/{name}")
    sweep = pr.run_sweep(
        profile="core",
        probes=_named(pr.default_probes(), "claude-cli"),
        activation_context=_ctx(),
    )
    claude = next(p for p in sweep.probes if p.name == "claude-cli")
    assert claude.status is pr.ProbeStatus.PASS


def test_bound_probes_keep_existing_fail_status(monkeypatch) -> None:
    monkeypatch.setattr(pr.shutil, "which", lambda name: None)
    sweep = pr.run_sweep(
        profile="core",
        probes=_named(pr.default_probes(), "claude-cli"),
        activation_context=_ctx(),
    )
    claude = next(p for p in sweep.probes if p.name == "claude-cli")
    assert claude.status is pr.ProbeStatus.FAIL
    assert claude.capability_id == "agent-claude-cli"


def test_firebase_probe_omits_under_core_unchanged(monkeypatch) -> None:
    """The cross-profile leak guard from F001 must still apply —
    firebase-cli must NOT surface under --profile=core regardless of
    capability binding."""
    monkeypatch.setattr(pr.shutil, "which", lambda name: None)
    sweep = pr.run_sweep(
        profile="core",
        probes=_named(pr.default_probes(), "firebase-cli"),
        activation_context=_ctx(),
    )
    assert all(p.name != "firebase-cli" for p in sweep.probes)


def test_discord_probe_keeps_existing_fail_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("JARVIS_DISCORD_WEBHOOK_URL", raising=False)
    sweep = pr.run_sweep(
        profile="discord",
        probes=_named(pr.default_probes(), "discord-webhook"),
        activation_context=_ctx(),
    )
    discord = next(p for p in sweep.probes if p.name == "discord-webhook")
    assert discord.status is pr.ProbeStatus.FAIL
    assert discord.capability_id == "discord-notify"
