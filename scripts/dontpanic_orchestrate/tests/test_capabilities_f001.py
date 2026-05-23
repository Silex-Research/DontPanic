"""Plan 2026-05-21-001 F001 — capability manifest loader tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate.capabilities import (
    CapabilityIndex,
    CapabilityManifestError,
    load_capabilities,
    validate_capability_file,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


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


def test_checked_in_manifests_load_and_lookup_by_id():
    index = load_capabilities(REPO_ROOT)

    assert index.require("linear").category == "pm-tool"
    assert index.require("firebase-dashboard").kind == "external_adapter"
    assert index.get("missing") is None


def test_lookup_by_category_is_sorted_and_read_only():
    pm_tools = load_capabilities(REPO_ROOT).by_category("pm-tool")

    assert [manifest.id for manifest in pm_tools] == ["linear"]
    assert load_capabilities(REPO_ROOT).by_category("does-not-exist") == ()


def test_valid_temp_manifest_validates(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    manifest_path = _write_manifest(tmp_path, "example", _base_manifest())

    manifest = validate_capability_file(manifest_path, repo_root=tmp_path)

    assert manifest.id == "example"
    assert manifest.owner_boundary.operator == ("token",)


def test_missing_required_field_fails_schema_validation(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    payload = _base_manifest()
    payload.pop("owner_boundary")
    manifest_path = _write_manifest(tmp_path, "example", payload)

    with pytest.raises(CapabilityManifestError, match="schema validation failed"):
        validate_capability_file(manifest_path, repo_root=tmp_path)


def test_invalid_kind_fails_schema_validation(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    payload = _base_manifest()
    payload["kind"] = "bespoke_plugin"
    manifest_path = _write_manifest(tmp_path, "example", payload)

    with pytest.raises(CapabilityManifestError, match="kind"):
        validate_capability_file(manifest_path, repo_root=tmp_path)


def test_id_must_match_filename_stem(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    manifest_path = _write_manifest(tmp_path, "filename", _base_manifest("declared"))

    with pytest.raises(CapabilityManifestError, match="must match filename stem"):
        validate_capability_file(manifest_path, repo_root=tmp_path)


def test_duplicate_id_fails_loud(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    manifest_path = _write_manifest(tmp_path, "one", _base_manifest("one"))
    manifest = validate_capability_file(manifest_path, repo_root=tmp_path)
    duplicate = manifest.model_copy(update={"source_path": tmp_path / "copy.json"})

    with pytest.raises(CapabilityManifestError, match="duplicate capability id"):
        CapabilityIndex([manifest, duplicate])


def test_missing_setup_doc_file_fails_loud(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)
    payload = _base_manifest()
    payload["setup_doc"] = "docs/MISSING.md#anchor"
    manifest_path = _write_manifest(tmp_path, "example", payload)

    with pytest.raises(CapabilityManifestError, match="setup_doc target not found"):
        validate_capability_file(manifest_path, repo_root=tmp_path)


def test_missing_capabilities_dir_fails_loud(tmp_path: Path):
    _copy_schema_and_docs(tmp_path)

    with pytest.raises(CapabilityManifestError, match="capabilities directory not found"):
        load_capabilities(tmp_path)
