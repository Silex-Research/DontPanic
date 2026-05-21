"""Capability manifest loader.

Plan 2026-05-21-001 F001 turns the ADR-001 manifest convention into a
machine-checkable contract. This module deliberately does not install,
invoke, or configure capabilities; it only loads and validates the
checked-in manifests so existing consumers can bind to stable IDs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CapabilityManifestError(ValueError):
    """Raised when a capability manifest cannot be loaded or validated."""


class CapabilityRequires(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    commands: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    auth: tuple[str, ...] = ()
    config: tuple[str, ...] = ()


class CapabilityVerify(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    doctor_profiles: tuple[str, ...] = ()
    probes: tuple[str, ...] = ()
    readiness: str = Field(..., min_length=1)


class CapabilityOwnerBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dontpanic_core: tuple[str, ...]
    adapter: tuple[str, ...]
    operator: tuple[str, ...]


class CapabilityMutationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    writes_dontpanic_state: bool
    external_mutation: str = Field(..., min_length=1)
    allowed_path: str = Field(..., min_length=1)
    forbidden: tuple[str, ...] = ()


class CapabilityManifest(BaseModel):
    """Typed read-only view of one ``capabilities/<id>.json`` manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    id: str
    title: str = Field(..., min_length=1)
    kind: str
    category: str
    summary: str = Field(..., min_length=1)
    setup_required: bool
    setup_doc: str = Field(..., min_length=1)
    default_in_profiles: tuple[str, ...] = ()
    use_cases: tuple[str, ...] = ()
    requires: CapabilityRequires
    verify: CapabilityVerify
    owner_boundary: CapabilityOwnerBoundary
    mutation_boundary: CapabilityMutationBoundary
    notes: tuple[str, ...] = ()
    source_path: Path | None = None


class CapabilityIndex:
    """Lookup container returned by :func:`load_capabilities`."""

    def __init__(self, manifests: list[CapabilityManifest]) -> None:
        by_id: dict[str, CapabilityManifest] = {}
        by_category: dict[str, list[CapabilityManifest]] = defaultdict(list)
        for manifest in manifests:
            if manifest.id in by_id:
                first = by_id[manifest.id].source_path or manifest.id
                second = manifest.source_path or manifest.id
                raise CapabilityManifestError(
                    f"duplicate capability id {manifest.id!r}: {first} and {second}"
                )
            by_id[manifest.id] = manifest
            by_category[manifest.category].append(manifest)
        self._by_id = by_id
        self._by_category = {
            category: tuple(sorted(items, key=lambda item: item.id))
            for category, items in by_category.items()
        }

    @property
    def all(self) -> tuple[CapabilityManifest, ...]:
        return tuple(self._by_id[key] for key in sorted(self._by_id))

    def get(self, capability_id: str) -> CapabilityManifest | None:
        return self._by_id.get(capability_id)

    def require(self, capability_id: str) -> CapabilityManifest:
        manifest = self.get(capability_id)
        if manifest is None:
            raise CapabilityManifestError(f"unknown capability id {capability_id!r}")
        return manifest

    def by_category(self, category: str) -> tuple[CapabilityManifest, ...]:
        return self._by_category.get(category, ())


def load_capabilities(repo_root: Path | str | None = None) -> CapabilityIndex:
    """Load every manifest under ``<repo_root>/capabilities``."""

    root = _repo_root(repo_root)
    capabilities_dir = root / "capabilities"
    if not capabilities_dir.is_dir():
        raise CapabilityManifestError(f"capabilities directory not found: {capabilities_dir}")
    manifests = [
        validate_capability_file(path, repo_root=root)
        for path in sorted(capabilities_dir.glob("*.json"))
    ]
    return CapabilityIndex(manifests)


def validate_capability_file(
    path: Path | str,
    *,
    repo_root: Path | str | None = None,
) -> CapabilityManifest:
    """Validate one manifest against the checked-in JSON schema."""

    manifest_path = Path(path)
    root = _repo_root(repo_root) if repo_root is not None else _infer_repo_root(manifest_path)
    payload = _read_json(manifest_path)
    schema = _read_json(root / "claude" / "shared" / "schemas" / "v1.0" / "capability.schema.json")
    _jsonschema_validate(payload, schema, manifest_path)

    manifest = CapabilityManifest.model_validate(payload).model_copy(
        update={"source_path": manifest_path}
    )
    if manifest.id != manifest_path.stem:
        raise CapabilityManifestError(
            f"{manifest_path}: id {manifest.id!r} must match filename stem {manifest_path.stem!r}"
        )
    setup_doc_path = root / manifest.setup_doc.split("#", 1)[0]
    if not setup_doc_path.is_file():
        raise CapabilityManifestError(
            f"{manifest_path}: setup_doc target not found: {manifest.setup_doc}"
        )
    return manifest


def _repo_root(repo_root: Path | str | None) -> Path:
    if repo_root is None:
        return Path(__file__).resolve().parents[2]
    return Path(repo_root)


def _infer_repo_root(manifest_path: Path) -> Path:
    if manifest_path.parent.name == "capabilities":
        return manifest_path.parent.parent
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CapabilityManifestError(f"{path}: could not read file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CapabilityManifestError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CapabilityManifestError(f"{path}: expected JSON object")
    return data


def _jsonschema_validate(payload: dict[str, Any], schema: dict[str, Any], path: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - dependency is installed in CI/dev.
        raise CapabilityManifestError(
            "jsonschema is required to validate capability manifests; install jsonschema"
        ) from exc
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        loc = ".".join(str(part) for part in first.path) or "<root>"
        raise CapabilityManifestError(f"{path}: schema validation failed at {loc}: {first.message}")


__all__ = [
    "CapabilityIndex",
    "CapabilityManifest",
    "CapabilityManifestError",
    "CapabilityMutationBoundary",
    "CapabilityOwnerBoundary",
    "CapabilityRequires",
    "CapabilityVerify",
    "load_capabilities",
    "validate_capability_file",
]
