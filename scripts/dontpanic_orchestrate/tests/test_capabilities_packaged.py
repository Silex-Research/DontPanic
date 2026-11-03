"""Capability manifest loading from package resources outside a checkout."""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from dontpanic_orchestrate import capabilities, prereq_registry  # noqa: E402


def _repo_capability_ids() -> set[str]:
    return {
        json.loads(path.read_text(encoding="utf-8"))["id"]
        for path in (REPO_ROOT / "capabilities").glob("*.json")
    }


def test_load_capabilities_falls_back_to_packaged_manifests(tmp_path: Path):
    assert not (tmp_path / "capabilities").exists()

    loaded = capabilities.load_capabilities(repo_root=tmp_path)

    assert {manifest.id for manifest in loaded.all} == _repo_capability_ids()


def test_packaged_manifest_mirror_matches_and_sync_check_detects_drift(
    tmp_path: Path,
):
    source_dir = REPO_ROOT / "capabilities"
    package_dir = REPO_ROOT / "scripts" / "dontpanic_orchestrate" / "capability_manifests"
    source_files = {path.name: path.read_bytes() for path in source_dir.glob("*.json")}

    assert package_dir.is_dir()
    package_files = {path.name: path.read_bytes() for path in package_dir.glob("*.json")}
    assert package_files == source_files

    sync_script = REPO_ROOT / "scripts" / "sync_capability_manifests.py"
    assert sync_script.is_file()
    clean = subprocess.run(
        [sys.executable, str(sync_script), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert clean.returncode == 0, clean.stderr

    copied_root = tmp_path / "repo-copy"
    shutil.copytree(source_dir, copied_root / "capabilities")
    shutil.copytree(package_dir, copied_root / "scripts/dontpanic_orchestrate/capability_manifests")
    copied_script = copied_root / "scripts/sync_capability_manifests.py"
    copied_script.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sync_script, copied_script)
    mirrored_file = copied_root / "scripts/dontpanic_orchestrate/capability_manifests" / next(iter(source_files))
    mirrored_file.write_bytes(mirrored_file.read_bytes() + b"\n")

    drift = subprocess.run(
        [sys.executable, str(copied_script), "--check"],
        cwd=copied_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert drift.returncode == 1


def test_capability_schema_validation_uses_packaged_schema_without_checkout_schema(
    tmp_path: Path,
):
    source_manifest = REPO_ROOT / "capabilities" / "agent-claude-cli.json"
    payload = json.loads(source_manifest.read_text(encoding="utf-8"))
    copied_manifest = tmp_path / "capabilities" / source_manifest.name
    copied_manifest.parent.mkdir(parents=True)
    copied_manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    setup_doc = payload["setup_doc"].split("#", 1)[0]
    source_doc = REPO_ROOT / setup_doc
    copied_doc = tmp_path / setup_doc
    copied_doc.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_doc, copied_doc)

    assert not (tmp_path / "claude/shared/schemas/v1.0/capability.schema.json").exists()
    manifest = capabilities.validate_capability_file(copied_manifest, repo_root=tmp_path)

    assert manifest.id == payload["id"]


def test_sanitization_probe_uses_importable_secret_patterns_without_checkout_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret_patterns = importlib.import_module("dontpanic_orchestrate.secret_patterns")
    assert secret_patterns is not None

    fake_module = tmp_path / "scripts/dontpanic_orchestrate/prereq_registry.py"
    fake_module.parent.mkdir(parents=True)
    assert not (tmp_path / "scripts/sanitization_check.py").exists()
    monkeypatch.setattr(prereq_registry, "__file__", str(fake_module))

    ok, message = prereq_registry._sanitization_regex_probe()

    assert ok is True
    assert str(tmp_path) not in message
