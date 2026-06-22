"""F001 — upgrade release manifest loader.

The upgrade release manifest is the single MACHINE source of truth for upgrade
intent (D002): not the prose CHANGELOG, not the plan ledger. This module parses
that file, validates it against the ``UpgradeManifest`` Pydantic model, and
returns the typed manifest (baseline + ordered releases).

MANIFEST RESOLUTION (D045): the shipped manifest is PACKAGED DATA inside the
``dontpanic_orchestrate`` distribution (``dontpanic_orchestrate/data/releases.json``)
and is resolved with ``importlib.resources`` — NOT by walking ``__file__`` up to
a repo-root layout. It therefore loads when the CLI is invoked outside the repo
root, from a pip-installed wheel, and off-git, and never consults the current
working directory or git metadata. The validation model is likewise imported
from inside the package (``dontpanic_orchestrate.upgrade_releases_model``), a
runtime copy kept byte-identical to the agent-conventions mirror under
``claude/shared/schemas/v1.0/models`` (guarded by a drift test), so validation
needs no repo-relative ``sys.path`` injection either.

Cross-field invariants (required-action D021/D029/D036/D047, id-uniqueness
D030) are enforced by the Pydantic model; the loader surfaces any failure as a
typed ``ReleaseManifestValidationError``.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from dontpanic_orchestrate.upgrade_releases_model import UpgradeManifest

if TYPE_CHECKING:
    from importlib.abc import Traversable

# The manifest ships as package data under this package-relative path. Kept as a
# constant so the F009 coverage lint (and tests) can reference one stable name.
PACKAGE_NAME = "dontpanic_orchestrate"
MANIFEST_RESOURCE = ("data", "releases.json")
# Repo-relative location of the human-authored manifest, for documentation only.
# Resolution does NOT use this path; the packaged resource above is authoritative.
RELEASES_RELPATH = Path(PACKAGE_NAME) / "data" / "releases.json"


class ReleaseManifestError(Exception):
    """Base class for release manifest loader errors."""


class ReleaseManifestNotFoundError(ReleaseManifestError):
    """No releases.json was found at the resolved path."""


class ReleaseManifestValidationError(ReleaseManifestError):
    """releases.json failed JSON parsing or schema/invariant validation."""


def _default_manifest_resource() -> Traversable:
    """Return the packaged manifest resource (D045).

    Uses ``importlib.resources`` so the path is package-relative and works from
    a pip-installed wheel, off-git, and from any cwd. For a regular (non-zip)
    install this is a concrete ``pathlib.Path``; for a zipimport it is a
    ``Traversable`` that still supports ``is_file``/``read_text``.
    """
    return resources.files(PACKAGE_NAME).joinpath(*MANIFEST_RESOURCE)


def default_manifest_path() -> Path:
    """Resolve the package-relative manifest path (D045).

    Returns the packaged ``releases.json`` as a concrete filesystem ``Path``.
    Never consults cwd or git. (When the package is imported from a zip, the
    resource is materialized to a temporary file on access by the loader; this
    accessor is for filesystem installs and tests.)
    """
    return Path(str(_default_manifest_resource()))


def _read_manifest_text(path: Path | str | None) -> tuple[str, str]:
    """Return ``(label, text)`` for the manifest, raising if it is absent.

    ``label`` is a human-readable identifier of the source for error messages.
    When ``path`` is ``None`` the packaged resource is read via
    ``importlib.resources`` (D045); otherwise the explicit filesystem path is
    read (used by tests and callers with a custom manifest).
    """
    if path is not None:
        manifest_path = Path(path)
        if not manifest_path.is_file():
            raise ReleaseManifestNotFoundError(f"{manifest_path} does not exist")
        return str(manifest_path), manifest_path.read_text()

    resource = _default_manifest_resource()
    if not resource.is_file():
        raise ReleaseManifestNotFoundError(
            f"packaged manifest {PACKAGE_NAME}/{'/'.join(MANIFEST_RESOURCE)} is missing"
        )
    return str(resource), resource.read_text()


def load_release_manifest(path: Path | str | None = None) -> UpgradeManifest:
    """Load, parse, and validate the upgrade release manifest.

    Args:
        path: Explicit manifest path. When ``None`` (default), resolves the
            packaged ``releases.json`` resource (D045) — package-relative,
            cwd- and git-independent.

    Returns:
        The validated ``UpgradeManifest`` (baseline + ordered releases).

    Raises:
        ReleaseManifestNotFoundError: the file/resource does not exist.
        ReleaseManifestValidationError: malformed JSON, schema violation, or a
            cross-field invariant failure (D021/D029/D030/D036/D047).
    """
    label, text = _read_manifest_text(path)

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReleaseManifestValidationError(f"{label}: malformed JSON — {exc}") from exc

    try:
        return UpgradeManifest.model_validate(raw)
    except ValidationError as exc:
        raise ReleaseManifestValidationError(f"{label}: {exc}") from exc


__all__ = [
    "MANIFEST_RESOURCE",
    "PACKAGE_NAME",
    "RELEASES_RELPATH",
    "ReleaseManifestError",
    "ReleaseManifestNotFoundError",
    "ReleaseManifestValidationError",
    "default_manifest_path",
    "load_release_manifest",
]
