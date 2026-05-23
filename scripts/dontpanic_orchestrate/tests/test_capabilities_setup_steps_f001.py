"""Plan 2026-05-22-002 F001 — setup_steps[] schema-additive field tests."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dontpanic_orchestrate.capabilities import (
    CapabilityManifestError,
    SetupStep,
    load_capabilities,
    validate_capability_file,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

# Patterns that look like real secrets and must NEVER appear in checked-in
# command_template strings. Placeholders such as `<YOUR_TOKEN>` are allowed —
# real tokens are not.
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bsk_live_[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}"),
    re.compile(r"https://discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+"),
)


def _base_manifest(capability_id: str = "example") -> dict:
    return {
        "schema_version": "1.0.0",
        "id": capability_id,
        "title": "Example capability",
        "kind": "service_adapter",
        "category": "pm-tool",
        "summary": "Example manifest for tests.",
        "setup_required": True,
        "setup_doc": "docs/USE_CASES.md",
        "default_in_profiles": [],
        "use_cases": ["U8"],
        "requires": {
            "commands": ["example-cli"],
            "env": [],
            "files": [],
            "services": ["Example"],
            "auth": ["Example token"],
            "config": ["mapping"],
        },
        "verify": {
            "doctor_profiles": [],
            "probes": ["adapter:example_registered"],
            "readiness": "Ready when registered.",
        },
        "owner_boundary": {
            "dontpanic_core": ["contract"],
            "adapter": ["wrapper"],
            "operator": ["token"],
        },
        "mutation_boundary": {
            "writes_dontpanic_state": False,
            "external_mutation": "push_status",
            "allowed_path": "Adapter writes external status and evidence.",
            "forbidden": ["direct plan writes"],
        },
        "notes": ["test fixture"],
    }


def _write_manifest(root: Path, name: str, payload: dict) -> Path:
    path = root / "capabilities" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _copy_schema_and_docs(root: Path) -> None:
    schema_src = REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0" / "capability.schema.json"
    schema_dst = root / "claude" / "shared" / "schemas" / "v1.0" / "capability.schema.json"
    schema_dst.parent.mkdir(parents=True, exist_ok=True)
    schema_dst.write_text(schema_src.read_text(encoding="utf-8"), encoding="utf-8")
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "USE_CASES.md").write_text("# Use cases\n", encoding="utf-8")


def test_setup_step_model_accepts_minimum_required_fields():
    step = SetupStep(id="install_cli", what="Install the CLI.", automatable=True)

    assert step.id == "install_cli"
    assert step.command_template is None
    assert step.verify_probe is None
    assert step.human_required_reason is None


def test_manifest_without_setup_steps_loads_with_empty_tuple(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    manifest_path = _write_manifest(tmp_path, "example", _base_manifest())

    manifest = validate_capability_file(manifest_path, repo_root=tmp_path)

    assert manifest.setup_steps == ()


def test_manifest_with_setup_steps_round_trips(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    payload = _base_manifest()
    payload["setup_steps"] = [
        {
            "id": "install_cli",
            "what": "Install the example CLI.",
            "automatable": True,
            "command_template": "brew install example-cli",
            "verify_probe": "cli:example",
            "human_required_reason": None,
        },
        {
            "id": "paste_token",
            "what": "Paste the API token into ~/.dontpanic/adapters/example.json.",
            "automatable": False,
            "command_template": None,
            "verify_probe": None,
            "human_required_reason": "Operator must mint their own token.",
        },
    ]
    manifest_path = _write_manifest(tmp_path, "example", payload)

    manifest = validate_capability_file(manifest_path, repo_root=tmp_path)

    assert len(manifest.setup_steps) == 2
    assert manifest.setup_steps[0].id == "install_cli"
    assert manifest.setup_steps[0].automatable is True
    assert manifest.setup_steps[1].automatable is False
    assert manifest.setup_steps[1].human_required_reason == "Operator must mint their own token."


def test_setup_step_missing_required_field_fails_schema_validation(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    payload = _base_manifest()
    payload["setup_steps"] = [
        {
            "what": "Step without id.",
            "automatable": True,
        }
    ]
    manifest_path = _write_manifest(tmp_path, "example", payload)

    with pytest.raises(CapabilityManifestError, match="schema validation failed"):
        validate_capability_file(manifest_path, repo_root=tmp_path)


def test_setup_step_wrong_automatable_type_fails_schema_validation(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    payload = _base_manifest()
    payload["setup_steps"] = [
        {
            "id": "install_cli",
            "what": "Install the example CLI.",
            "automatable": "yes",
        }
    ]
    manifest_path = _write_manifest(tmp_path, "example", payload)

    with pytest.raises(CapabilityManifestError, match="schema validation failed"):
        validate_capability_file(manifest_path, repo_root=tmp_path)


def test_setup_step_bad_id_pattern_fails_schema_validation(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    payload = _base_manifest()
    payload["setup_steps"] = [
        {
            "id": "Install CLI!",
            "what": "Install the example CLI.",
            "automatable": True,
        }
    ]
    manifest_path = _write_manifest(tmp_path, "example", payload)

    with pytest.raises(CapabilityManifestError, match="schema validation failed"):
        validate_capability_file(manifest_path, repo_root=tmp_path)


def test_setup_step_duplicate_id_fails_schema_validation(tmp_path: Path):
    # The JSON Schema declares `uniqueBy: "id"` on setup_steps; the loader
    # registers a matching custom keyword so two entries sharing `id` are
    # rejected at the schema-validation step (before Pydantic ever runs),
    # even when their other fields differ.
    _copy_schema_and_docs(tmp_path)
    payload = _base_manifest()
    payload["setup_steps"] = [
        {"id": "install_cli", "what": "Install once.", "automatable": True},
        {"id": "install_cli", "what": "Install again.", "automatable": False},
    ]
    manifest_path = _write_manifest(tmp_path, "example", payload)

    with pytest.raises(CapabilityManifestError, match="schema validation failed"):
        validate_capability_file(manifest_path, repo_root=tmp_path)


def test_setup_step_extra_field_rejected(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    payload = _base_manifest()
    payload["setup_steps"] = [
        {
            "id": "install_cli",
            "what": "Install the CLI.",
            "automatable": True,
            "owner": "operator",
        }
    ]
    manifest_path = _write_manifest(tmp_path, "example", payload)

    with pytest.raises(CapabilityManifestError, match="schema validation failed"):
        validate_capability_file(manifest_path, repo_root=tmp_path)


def test_firebase_dashboard_manifest_has_minimum_setup_steps():
    manifest = load_capabilities(REPO_ROOT).require("firebase-dashboard")

    assert len(manifest.setup_steps) >= 6


def test_linear_manifest_has_minimum_setup_steps():
    manifest = load_capabilities(REPO_ROOT).require("linear")

    assert len(manifest.setup_steps) >= 4


def test_discord_notify_manifest_has_minimum_setup_steps():
    manifest = load_capabilities(REPO_ROOT).require("discord-notify")

    assert len(manifest.setup_steps) >= 2


def test_agent_claude_cli_manifest_has_minimum_setup_steps():
    manifest = load_capabilities(REPO_ROOT).require("agent-claude-cli")

    assert len(manifest.setup_steps) >= 2


def test_command_templates_contain_no_obvious_secrets():
    index = load_capabilities(REPO_ROOT)

    offenders: list[str] = []
    for manifest in index.all:
        for step in manifest.setup_steps:
            template = step.command_template
            if template is None:
                continue
            for pattern in _SECRET_PATTERNS:
                if pattern.search(template):
                    offenders.append(f"{manifest.id}.{step.id}: matches {pattern.pattern}")
    assert not offenders, "real-looking secrets in command_template entries: " + ", ".join(
        offenders
    )


def test_non_automatable_steps_explain_human_required_reason():
    index = load_capabilities(REPO_ROOT)

    for manifest in index.all:
        for step in manifest.setup_steps:
            if step.automatable:
                continue
            assert step.human_required_reason, (
                f"{manifest.id}.{step.id}: automatable=False must provide human_required_reason"
            )
