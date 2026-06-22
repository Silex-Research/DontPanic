"""F001 — upgrade release manifest loader + Pydantic model tests.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_release_manifest.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
PKG_DIR = HERE.parents[2] / "dontpanic_orchestrate"
sys.path.insert(0, str(HERE.parents[2]))

# D045: the validation model is imported from INSIDE the shipped package, not
# from the repo-root claude/shared mirror — so the import works from an
# installed wheel exactly as it does in-repo.
from dontpanic_orchestrate.release_manifest import (  # noqa: E402
    MANIFEST_RESOURCE,
    ReleaseManifestNotFoundError,
    ReleaseManifestValidationError,
    default_manifest_path,
    load_release_manifest,
)
from dontpanic_orchestrate.upgrade_releases_model import (  # noqa: E402
    CommandLabel,
    Kind,
    Severity,
    UpgradeManifest,
)

# ──────────────────────────────  fixtures  ──────────────────────────────


def _ordered_commands() -> list[dict]:
    return [
        {"label": "preview", "command": "dontpanic projects discover", "description": "dry run"},
        {"label": "apply", "command": "dontpanic projects discover --backfill"},
        {"label": "verify", "command": "dontpanic doctor --upgrade --json"},
    ]


def _required_action() -> dict:
    return {
        "id": "canonical-backfill",
        "kind": "required",
        "severity": "critical",
        "title": "Backfill canonical discovery",
        "detail": "Tracked projects must be reconciled into the canonical registry.",
        "commands": _ordered_commands(),
        "introduced_commands": ["dontpanic projects discover"],
        "applies_when": "has_tracked_projects",
        "status_probe": "canonical_discovery_registered_active",
        "success_message": "Canonical registry is active.",
        "failure_message": "Backfill still pending.",
        "human_next_step": "Run the apply command, then re-run doctor.",
        "docs_url": "docs/upgrade/canonical-discovery.md",
        "evidence_uri": "evidence/canonical-backfill.json",
    }


def _advisory_action() -> dict:
    return {
        "id": "review-changelog",
        "kind": "advisory",
        "title": "Review the CHANGELOG",
        "detail": "Several quality-of-life improvements landed.",
        "commands": [],
        "applies_when": None,
        "status_probe": None,
    }


def _valid_manifest() -> dict:
    return {
        "baseline_release": "2026-06-14-baseline",
        "baseline_date": "2026-06-14",
        "releases": [
            {
                "id": "2026-06-15-experience-readiness",
                "date": "2026-06-15",
                "plan_refs": ["2026-06-15-001"],
                "summary": "Experience Readiness rollout.",
                "show_on_first_run": True,
                "actions": [_advisory_action()],
            },
            {
                "id": "2026-06-17-canonical-discovery",
                "date": "2026-06-17",
                "plan_refs": ["2026-06-17-001"],
                "summary": "Canonical repo discovery.",
                "actions": [_required_action()],
            },
        ],
    }


def _write(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "releases.json"
    p.write_text(json.dumps(payload))
    return p


# ──────────────────────────────  happy path  ──────────────────────────────


def test_valid_manifest_parses_full_field_set(tmp_path: Path) -> None:
    manifest = load_release_manifest(_write(tmp_path, _valid_manifest()))
    assert isinstance(manifest, UpgradeManifest)
    assert manifest.baseline_release == "2026-06-14-baseline"
    assert manifest.baseline_date == "2026-06-14"
    # Releases preserve authoring order.
    assert [r.id for r in manifest.releases] == [
        "2026-06-15-experience-readiness",
        "2026-06-17-canonical-discovery",
    ]

    advisory = manifest.releases[0].actions[0]
    assert advisory.kind is Kind.advisory
    assert advisory.status_probe is None
    assert advisory.applies_when is None
    assert advisory.commands == []
    assert manifest.releases[0].show_on_first_run is True

    required = manifest.releases[1].actions[0]
    assert required.kind is Kind.required
    assert required.severity is Severity.critical
    assert required.status_probe == "canonical_discovery_registered_active"
    assert required.applies_when == "has_tracked_projects"
    assert [c.label for c in required.commands] == [
        CommandLabel.preview,
        CommandLabel.apply,
        CommandLabel.verify,
    ]
    assert required.introduced_commands == ["dontpanic projects discover"]
    assert required.success_message == "Canonical registry is active."
    assert required.failure_message == "Backfill still pending."
    assert required.human_next_step == "Run the apply command, then re-run doctor."
    assert required.docs_url == "docs/upgrade/canonical-discovery.md"
    # show_on_first_run defaults to False when omitted.
    assert manifest.releases[1].show_on_first_run is False


def test_advisory_accepts_empty_commands_and_null_probe(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"] = [payload["releases"][0]]  # advisory-only release
    manifest = load_release_manifest(_write(tmp_path, payload))
    assert manifest.releases[0].actions[0].kind is Kind.advisory


# ──────────────────────────────  malformed structure  ──────────────────────────────


def test_missing_baseline_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    del payload["baseline_release"]
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_unknown_kind_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][0]["actions"][0]["kind"] = "mandatory"
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_unknown_severity_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][0]["actions"][0]["severity"] = "blocker"
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_unknown_command_label_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][1]["actions"][0]["commands"][0]["label"] = "rollback"
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    del payload["releases"][0]["actions"][0]["title"]
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_non_date_date_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][0]["date"] = "2026-13-45"
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_non_date_baseline_date_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["baseline_date"] = "not-a-date"
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_unknown_key_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][0]["actions"][0]["surprise"] = "value"
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_malformed_json_rejected(tmp_path: Path) -> None:
    p = tmp_path / "releases.json"
    p.write_text("{ not json")
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(p)


def test_missing_file_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(ReleaseManifestNotFoundError):
        load_release_manifest(tmp_path / "does-not-exist.json")


# ──────────────────  required-action invariant (D021)  ──────────────────


def test_required_action_null_status_probe_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][1]["actions"][0]["status_probe"] = None
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_required_action_empty_status_probe_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][1]["actions"][0]["status_probe"] = "   "
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_advisory_action_null_status_probe_accepted(tmp_path: Path) -> None:
    # Mirror of the D021 rejection: advisory may omit the probe.
    payload = _valid_manifest()
    payload["releases"] = [payload["releases"][0]]
    manifest = load_release_manifest(_write(tmp_path, payload))
    assert manifest.releases[0].actions[0].status_probe is None


# ──────────────────  required-command invariant (D029)  ──────────────────


def test_required_action_empty_commands_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][1]["actions"][0]["commands"] = []
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_required_action_no_apply_command_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][1]["actions"][0]["commands"] = [
        {"label": "preview", "command": "dontpanic projects discover"},
        {"label": "verify", "command": "dontpanic doctor --upgrade"},
    ]
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


# ──────────────────  ordered-checklist invariant (D036)  ──────────────────


def test_required_action_missing_verify_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][1]["actions"][0]["commands"] = [
        {"label": "preview", "command": "dontpanic projects discover"},
        {"label": "apply", "command": "dontpanic projects discover --backfill"},
    ]
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_required_action_out_of_order_labels_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][1]["actions"][0]["commands"] = [
        {"label": "verify", "command": "dontpanic doctor --upgrade"},
        {"label": "apply", "command": "dontpanic projects discover --backfill"},
    ]
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_required_action_preview_after_apply_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][1]["actions"][0]["commands"] = [
        {"label": "apply", "command": "dontpanic projects discover --backfill"},
        {"label": "preview", "command": "dontpanic projects discover"},
        {"label": "verify", "command": "dontpanic doctor --upgrade"},
    ]
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


# ──────────────────  id-uniqueness invariant (D030)  ──────────────────


def test_duplicate_release_ids_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][1]["id"] = payload["releases"][0]["id"]
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


def test_duplicate_action_ids_within_release_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    dup = _advisory_action()
    payload["releases"][0]["actions"] = [dup, dict(dup)]
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


# ──────────────────  blank command invariant (D047)  ──────────────────


def test_blank_command_string_rejected(tmp_path: Path) -> None:
    payload = _valid_manifest()
    payload["releases"][1]["actions"][0]["commands"][1]["command"] = "   "
    with pytest.raises(ReleaseManifestValidationError):
        load_release_manifest(_write(tmp_path, payload))


# ──────────────────  package-relative resolution (D045)  ──────────────────


def test_default_manifest_path_resolves_off_cwd_and_git(tmp_path: Path, monkeypatch) -> None:
    # D045: resolution is package-relative — independent of cwd. chdir into a
    # temp dir well outside the repo root (and with no .git), then assert the
    # default path still resolves to the shipped manifest and loads.
    outside = tmp_path / "somewhere" / "else"
    outside.mkdir(parents=True)
    monkeypatch.chdir(outside)

    resolved = default_manifest_path()
    assert resolved.is_file()
    assert resolved.name == "releases.json"
    assert resolved.is_absolute()
    # Path must not depend on the (temp) cwd.
    assert str(outside) not in str(resolved)

    manifest = load_release_manifest()  # no explicit path -> package-relative
    assert isinstance(manifest, UpgradeManifest)
    assert manifest.baseline_release


def test_default_manifest_path_does_not_consult_cwd_releases(tmp_path: Path, monkeypatch) -> None:
    # A stray releases.json in cwd must NOT be picked up (resolution ignores cwd).
    decoy = tmp_path / "docs" / "upgrade"
    decoy.mkdir(parents=True)
    (decoy / "releases.json").write_text(json.dumps({"baseline_release": "DECOY"}))
    monkeypatch.chdir(tmp_path)

    resolved = default_manifest_path()
    assert os.path.realpath(str(resolved)) != os.path.realpath(str(decoy / "releases.json"))


def test_default_manifest_resolves_inside_package(tmp_path: Path, monkeypatch) -> None:
    # D045: the resolved manifest is the PACKAGED resource (under the package
    # dir), never a repo-root docs/ path — that is what ships in the wheel.
    monkeypatch.chdir(tmp_path)
    resolved = default_manifest_path()
    assert resolved.is_file()
    assert resolved.parent == PKG_DIR / MANIFEST_RESOURCE[0]
    # It is package-relative, not under the repo-root docs/ tree.
    assert "docs" not in resolved.parts


# ──────────────  D045: installed / off-git package resolution  ──────────────


def test_loads_from_isolated_installed_package(tmp_path: Path) -> None:
    """Simulate a pip-installed wheel: copy ONLY the package into an isolated
    site dir with no repo-root layout (no claude/, no docs/, no .git), put it on
    a clean PYTHONPATH, run from an unrelated cwd, and assert the manifest still
    loads. This is the case the prior cwd-only test did not cover (D045)."""
    site = tmp_path / "site-packages"
    pkg = site / "dontpanic_orchestrate"
    (pkg / "data").mkdir(parents=True)

    # Minimal installed package: __init__, the loader, the vendored model, and
    # the packaged manifest data. Deliberately NOTHING else from the repo.
    (pkg / "__init__.py").write_text('__version__ = "0.0.0-test"\n')
    shutil.copy(PKG_DIR / "release_manifest.py", pkg / "release_manifest.py")
    shutil.copy(PKG_DIR / "upgrade_releases_model.py", pkg / "upgrade_releases_model.py")
    shutil.copy(PKG_DIR / "data" / "releases.json", pkg / "data" / "releases.json")

    # Unrelated cwd with no .git and no repo files.
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()

    # Clean env: PYTHONPATH points ONLY at the isolated site dir, so the real
    # repo package cannot be found. (pydantic resolves from site-packages.)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(site)
    env.pop("PYTHONDONTWRITEBYTECODE", None)

    code = (
        "from dontpanic_orchestrate.release_manifest import load_release_manifest;"
        "m = load_release_manifest();"
        "print(m.baseline_release, len(m.releases))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    # Confirms the package resolved its own manifest, off-git and off-cwd.
    assert "DECOY" not in result.stdout
    baseline, _, count = result.stdout.strip().partition(" ")
    assert baseline
    assert int(count) >= 1


# ──────────────  D045: shipped resources stay in sync with their mirrors  ──────────────


def test_packaged_manifest_matches_authored_docs_copy() -> None:
    """Drift guard: the shipped package manifest must match the human-authored
    docs/upgrade/releases.json so the two never silently diverge."""
    docs_copy = REPO_ROOT / "docs" / "upgrade" / "releases.json"
    packaged = PKG_DIR / "data" / "releases.json"
    if not docs_copy.is_file():
        pytest.skip("authored docs copy not present (installed package)")
    # Compare parsed JSON (whitespace-insensitive, the contract is the data).
    assert json.loads(packaged.read_text()) == json.loads(docs_copy.read_text())


def test_packaged_model_matches_shared_mirror() -> None:
    """Drift guard: the vendored runtime model must stay byte-identical to the
    agent-conventions mirror under claude/shared so validation logic is one
    contract authored in one place (D045 rationale)."""
    mirror = (
        REPO_ROOT
        / "claude"
        / "shared"
        / "schemas"
        / "v1.0"
        / "models"
        / "upgrade_releases_model.py"
    )
    vendored = PKG_DIR / "upgrade_releases_model.py"
    if not mirror.is_file():
        pytest.skip("agent-conventions mirror not present (installed package)")
    assert vendored.read_text() == mirror.read_text()
