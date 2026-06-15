"""Plan 2026-06-14-001 F008 — operator-surface capability-manifest shape (TDD).

Tests assert:
1. The schema/loader ACCEPTS a valid operator_surface manifest.
2. A manifest omitting any of the six minimum probes FAILS validation.
3. Each of the four seeded manifests loads, validates, and declares the full
   minimum probe set.
4. EXACTLY those four surfaces are seeded (cursor, claude_desktop, codex_app,
   antigravity) — no Gemini/Grok surface manifest.
5. No agent-channels.json file exists anywhere under the repo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate.capabilities import (
    CapabilityManifestError,
    load_capabilities,
    validate_capability_file,
    validate_operator_surface_manifest,
)
from dontpanic_orchestrate.invocation_context import OperatorSurface

REPO_ROOT = Path(__file__).resolve().parents[3]

# ── canonical minimum probe ids (D013) ─────────────────────────────────────────

MINIMUM_PROBES = {
    "path",
    "home",
    "repo_visibility",
    "worktree_binding",
    "config",
    "mcp_availability",
}

# ── four seeded operator surfaces ───────────────────────────────────────────────

SEEDED_SURFACE_IDS: frozenset[str] = frozenset(
    {"cursor", "claude_desktop", "codex_app", "antigravity"}
)


# ── helpers ──────────────────────────────────────────────────────────────────────


def _copy_schema_and_docs(root: Path) -> None:
    schema_src = REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0" / "capability.schema.json"
    schema_dst = root / "claude" / "shared" / "schemas" / "v1.0" / "capability.schema.json"
    schema_dst.parent.mkdir(parents=True, exist_ok=True)
    schema_dst.write_text(schema_src.read_text(encoding="utf-8"), encoding="utf-8")
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "GETTING_STARTED.md").write_text("# Getting Started\n## Setup tracks\n", encoding="utf-8")


def _write_manifest(root: Path, name: str, payload: dict) -> Path:
    path = root / "capabilities" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _base_operator_surface_manifest(surface_id: str = "cursor", extra_probes: list[str] | None = None) -> dict:
    """Return a minimal valid operator_surface manifest for testing."""
    probes = sorted(MINIMUM_PROBES | set(extra_probes or []))
    return {
        "schema_version": "1.0.0",
        "id": surface_id,
        "title": f"{surface_id.replace('_', ' ').title()} operator surface",
        "kind": "operator_surface",
        "category": "operator-surface",
        "summary": f"Operator surface manifest for {surface_id}.",
        "setup_required": False,
        "setup_doc": "docs/GETTING_STARTED.md#setup-tracks",
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
            "probes": probes,
            "readiness": f"Surface {surface_id} is usable when all minimum probes pass.",
        },
        "owner_boundary": {
            "dontpanic_core": ["invocation context resolution", "probe dispatch"],
            "adapter": [],
            "operator": ["installs and authenticates the surface application"],
        },
        "mutation_boundary": {
            "writes_dontpanic_state": False,
            "external_mutation": "none",
            "allowed_path": "Operator surface manifests are read-only; DontPanic never mutates the surface runtime.",
            "forbidden": [],
        },
        "notes": [],
    }


# ── test 1: schema accepts a valid operator_surface manifest ─────────────────────


def test_valid_operator_surface_manifest_validates(tmp_path: Path) -> None:
    """Schema/loader accepts a valid operator_surface manifest with minimum probes."""
    _copy_schema_and_docs(tmp_path)
    manifest_path = _write_manifest(tmp_path, "cursor", _base_operator_surface_manifest("cursor"))

    manifest = validate_capability_file(manifest_path, repo_root=tmp_path)

    assert manifest.id == "cursor"
    assert manifest.kind == "operator_surface"
    assert set(manifest.verify.probes) >= MINIMUM_PROBES


# ── test 2: missing any minimum probe fails validation ───────────────────────────


@pytest.mark.parametrize("missing_probe", sorted(MINIMUM_PROBES))
def test_operator_surface_manifest_missing_probe_fails(tmp_path: Path, missing_probe: str) -> None:
    """A manifest omitting any one of the six minimum probes must fail validation."""
    _copy_schema_and_docs(tmp_path)
    payload = _base_operator_surface_manifest("cursor")
    probes_without_missing = [p for p in payload["verify"]["probes"] if p != missing_probe]
    payload["verify"]["probes"] = probes_without_missing
    manifest_path = _write_manifest(tmp_path, "cursor", payload)

    with pytest.raises(CapabilityManifestError, match="minimum probe"):
        validate_operator_surface_manifest(manifest_path, repo_root=tmp_path)


# ── test 3: four seeded manifests load, validate, and declare full minimum probe set ─


@pytest.mark.parametrize("surface_id", sorted(SEEDED_SURFACE_IDS))
def test_seeded_surface_manifest_loads_and_has_minimum_probes(surface_id: str) -> None:
    """Each seeded operator_surface manifest validates and declares the full minimum probe set."""
    manifest_path = REPO_ROOT / "capabilities" / f"{surface_id}.json"
    assert manifest_path.is_file(), f"Seeded manifest not found: {manifest_path}"

    manifest = validate_operator_surface_manifest(manifest_path, repo_root=REPO_ROOT)

    assert manifest.kind == "operator_surface"
    assert manifest.id == surface_id
    declared_probes = set(manifest.verify.probes)
    missing = MINIMUM_PROBES - declared_probes
    assert not missing, (
        f"Seeded manifest {surface_id!r} is missing minimum probes: {missing}"
    )


# ── test 4: exactly four surfaces are seeded (no Gemini/Grok) ───────────────────


def test_exactly_four_surfaces_seeded_no_gemini_grok() -> None:
    """Exactly cursor, claude_desktop, codex_app, antigravity are seeded; Gemini/Grok absent."""
    capabilities_dir = REPO_ROOT / "capabilities"
    assert capabilities_dir.is_dir(), "capabilities directory not found"

    # Load all manifests and find operator_surface kind
    all_manifests = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(capabilities_dir.glob("*.json"))
    ]
    surface_ids = {m["id"] for m in all_manifests if m.get("kind") == "operator_surface"}

    assert surface_ids == SEEDED_SURFACE_IDS, (
        f"Expected seeded surfaces {SEEDED_SURFACE_IDS!r}, got {surface_ids!r}"
    )

    # Explicitly confirm Gemini and Grok are NOT seeded as operator surfaces
    assert "gemini" not in surface_ids
    assert "grok" not in surface_ids

    # Confirm the seeded ids are canonical OperatorSurface values from F001
    valid_surface_values = {s.value for s in OperatorSurface}
    for sid in surface_ids:
        assert sid in valid_surface_values, (
            f"Seeded surface id {sid!r} is not a canonical OperatorSurface value"
        )


# ── test 5: no agent-channels.json file exists anywhere under the repo ──────────


def test_no_agent_channels_json_in_repo() -> None:
    """No file named agent-channels.json is introduced anywhere in the repo by F008."""
    # Search known directories that might contain such a file
    search_roots = [
        REPO_ROOT / "capabilities",
        REPO_ROOT / "scripts",
        REPO_ROOT / "dashboard",
        REPO_ROOT / "docs",
        REPO_ROOT / "claude",
        REPO_ROOT / "config",
    ]
    found: list[Path] = []
    for search_root in search_roots:
        if search_root.is_dir():
            found.extend(search_root.rglob("agent-channels.json"))
    # Also check repo root itself
    root_level = REPO_ROOT / "agent-channels.json"
    if root_level.is_file():
        found.append(root_level)

    assert not found, (
        f"agent-channels.json must not exist anywhere in the repo; found: {found}"
    )
