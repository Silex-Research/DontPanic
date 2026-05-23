"""Plan 2026-05-23-002 F001 — operator-local install snapshot.

The install snapshot is the reconciliation anchor written to
``~/.dontpanic/install-snapshot.json``. It captures the surface that
``dontpanic reconcile check`` (F002) will compare against:

  * DontPanic runtime version + agent-manifest schema version
  * Active install profile (e.g. ``core``)
  * Current MCP tool surface (names only — no schemas, no payloads)
  * Per-capability identity: capability id + deterministic manifest
    fingerprint + deterministic setup_steps fingerprint + ordered
    setup_step_ids
  * Optional metadata about ``~/.dontpanic/capabilities-status.json``
    (path, mtime, sha256) so a reconciler can flag stale status caches
    without re-running the probe sweep

Secret-free invariant (mirrors ``agent_manifest`` D006): the snapshot
schema's own field names must not contain ``_token``, ``_key``, or
``_secret`` substrings. Asserted at module import time so a future
contributor accidentally adding a credential-shaped field is caught
immediately.

Deterministic invariant: re-running :func:`build_snapshot` with the
same inputs produces a snapshot whose body is byte-identical except for
``generated_at``. Fingerprints are SHA-256 hex digests over canonical
JSON encodings (``sort_keys=True``, ``ensure_ascii=False``) of the
relevant subset of each capability manifest.

File-mode invariant: :func:`write_snapshot` always chmods the snapshot
to ``0o600`` (operator-only). The parent ``~/.dontpanic`` directory is
created with mode ``0o700`` on first write.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import stat
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from dontpanic_orchestrate import __version__ as _DONTPANIC_VERSION
from dontpanic_orchestrate import agent_manifest as _agent_manifest
from dontpanic_orchestrate import global_config as _gc
from dontpanic_orchestrate.capabilities import (
    CapabilityIndex,
    CapabilityManifest,
    CapabilityManifestError,
    load_capabilities,
)

_STATUS_CACHE_FILENAME = "capabilities-status.json"

_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
"""Pinned at the v1 install-snapshot contract. Bump when fields are
added or removed; readers that don't recognize a newer schema_version
should refuse to interpret the file rather than guess."""

SNAPSHOT_FILENAME = "install-snapshot.json"
SNAPSHOT_FILE_MODE = 0o600
SNAPSHOT_DIR_MODE = 0o700

# Mirror agent_manifest D006: no credential-shaped field names on the
# schema. Snapshot is install-state metadata, not a credential surface.
_FORBIDDEN_FIELD_SUBSTRINGS = ("_token", "_key", "_secret")


# ── models ────────────────────────────────────────────────────────────────


class CapabilityFingerprint(BaseModel):
    """Per-capability identity entry within the snapshot.

    ``manifest_fingerprint`` is a deterministic SHA-256 over the
    capability manifest's canonical JSON (less the in-memory
    ``source_path`` field, which is a runtime detail and not part of
    capability identity). ``setup_steps_fingerprint`` is a separate
    SHA-256 over just the ordered ``setup_steps`` so a manifest change
    that does not touch setup_steps can be distinguished from one that
    does.

    ``setup_step_ids`` is the ordered list of ids so a reconciler can
    cheaply diff which steps were added/removed without re-reading
    every manifest.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str
    manifest_fingerprint: str
    setup_steps_fingerprint: str
    setup_step_ids: tuple[str, ...]


class StatusCacheMeta(BaseModel):
    """Metadata about ``~/.dontpanic/capabilities-status.json`` if present.

    The snapshot intentionally records only path + mtime + content
    fingerprint. It does NOT copy the cache contents into the snapshot —
    that would duplicate per-probe state already owned by the cache.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    mtime_iso: str
    sha256: str


class InstallSnapshot(BaseModel):
    """Top-level install-snapshot envelope.

    All fields are stamped at :func:`build_snapshot` time. Re-running
    the builder with the same inputs produces a snapshot whose body is
    byte-identical except for ``generated_at``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    generated_at: str
    dontpanic_version: str
    profile: str
    agent_manifest_schema_version: str
    mcp_tool_names: tuple[str, ...]
    capability_ids: tuple[str, ...]
    capabilities: tuple[CapabilityFingerprint, ...]
    status_cache: StatusCacheMeta | None = None


# ── D006 import-time secret-free check ────────────────────────────────────


def _assert_no_credential_shaped_fields() -> None:
    """Walk every model in the snapshot schema and verify no field name
    contains a forbidden substring. Asserted at module import time so a
    contributor accidentally adding a credential-shaped field is caught
    immediately, not later by a sanitization pass."""

    for model in (InstallSnapshot, CapabilityFingerprint, StatusCacheMeta):
        for field_name in model.model_fields:
            for forbidden in _FORBIDDEN_FIELD_SUBSTRINGS:
                if forbidden in field_name:  # pragma: no cover - defensive
                    raise RuntimeError(
                        f"{model.__name__}.{field_name} contains forbidden substring "
                        f"{forbidden!r}; secret-shaped field names are banned by the "
                        "install-snapshot no-secrets invariant"
                    )


_assert_no_credential_shaped_fields()


# ── paths ────────────────────────────────────────────────────────────────


def _canonical_dontpanic_home() -> Path:
    """Canonical DontPanic home for install-snapshot anchoring.

    Unlike :func:`global_config.dontpanic_home`, this does NOT honor
    ``$JARVIS_HOME`` and does NOT fall back to an existing ``~/.jarvis``
    directory. The install snapshot is the v1 reconciliation anchor and
    must anchor on the canonical DontPanic location only — the plan's
    acceptance is explicit that ``reconcile baseline --yes`` on a legacy
    install creates the anchor at ``~/.dontpanic/install-snapshot.json``
    rather than migrating into ``.jarvis``.

    ``$DONTPANIC_HOME`` remains honored as the explicit operator/test
    override so existing tests (and operators with non-standard layouts)
    keep working.
    """
    override = os.environ.get(_gc.DONTPANIC_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / _gc.DEFAULT_DIRNAME


def snapshot_path() -> Path:
    """Resolve ``~/.dontpanic/install-snapshot.json``.

    Anchors at the canonical DontPanic home (see
    :func:`_canonical_dontpanic_home`). Legacy ``$JARVIS_HOME`` and
    ``~/.jarvis`` are intentionally NOT honored for install snapshots.
    """
    return _canonical_dontpanic_home() / SNAPSHOT_FILENAME


# ── fingerprints ──────────────────────────────────────────────────────────


def _canonical_json_bytes(value: Any) -> bytes:
    """Canonical JSON serialization for fingerprinting.

    ``sort_keys=True`` so dict ordering does not affect the digest;
    ``ensure_ascii=False`` so non-ASCII characters serialize as
    themselves rather than ``\\uXXXX`` escapes (otherwise two byte
    sequences could hash to different values that are semantically
    identical).
    """
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash_canonical(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _manifest_payload(manifest: CapabilityManifest) -> dict[str, Any]:
    """Subset of the capability manifest used for the manifest
    fingerprint. Excludes ``source_path`` (a runtime-only detail) and
    ``setup_steps`` (covered by ``setup_steps_fingerprint``)."""
    return manifest.model_dump(
        mode="json",
        exclude={"source_path", "setup_steps"},
    )


def _setup_steps_payload(manifest: CapabilityManifest) -> list[dict[str, Any]]:
    return [step.model_dump(mode="json") for step in manifest.setup_steps]


def capability_fingerprint(manifest: CapabilityManifest) -> CapabilityFingerprint:
    """Build the per-capability fingerprint entry. Pure function — no
    filesystem access beyond what's already loaded into ``manifest``."""

    return CapabilityFingerprint(
        capability_id=manifest.id,
        manifest_fingerprint=_hash_canonical(_manifest_payload(manifest)),
        setup_steps_fingerprint=_hash_canonical(_setup_steps_payload(manifest)),
        setup_step_ids=tuple(step.id for step in manifest.setup_steps),
    )


# ── MCP tool name discovery ───────────────────────────────────────────────


def discover_mcp_tool_names() -> tuple[str, ...]:
    """Return the current MCP tool surface without starting the server.

    Imports :mod:`dontpanic_orchestrate.mcp_server` and reads the
    in-process tool registry. No stdio loop, no JSON-RPC handshake.
    Returns ``()`` if the MCP module is unavailable (defensive — F002
    of the parent ecosystem plan already wired it in).
    """

    try:
        from dontpanic_orchestrate import mcp_server
    except ImportError:  # pragma: no cover - mcp_server is checked in
        return ()
    return tuple(mcp_server.list_tool_names())


# ── status-cache meta ─────────────────────────────────────────────────────


def _read_status_cache_meta(cache_path: Path | None = None) -> StatusCacheMeta | None:
    """Build :class:`StatusCacheMeta` if the cache file exists.

    Records path + ISO mtime (UTC) + content sha256. The cache contents
    themselves are NOT embedded in the snapshot — only fingerprint
    metadata, so a reconciler can flag staleness without duplicating
    per-probe state.
    """

    path = (
        cache_path
        if cache_path is not None
        else _canonical_dontpanic_home() / _STATUS_CACHE_FILENAME
    )
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _LOG.warning(
            "install-snapshot: status cache at %s unreadable (%s); omitting status_cache",
            path,
            exc,
        )
        return None
    try:
        mtime = _dt.datetime.fromtimestamp(path.stat().st_mtime, tz=_dt.timezone.utc)
    except OSError as exc:  # pragma: no cover - stat after read should succeed
        _LOG.warning(
            "install-snapshot: status cache stat at %s failed (%s); omitting status_cache",
            path,
            exc,
        )
        return None
    return StatusCacheMeta(
        path=str(path),
        mtime_iso=mtime.isoformat().replace("+00:00", "Z"),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


# ── builder ───────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return (
        _dt.datetime.now(tz=_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def build_snapshot(
    *,
    profile: str,
    capability_index: CapabilityIndex | None = None,
    repo_root: Path | None = None,
    mcp_tool_names: tuple[str, ...] | None = None,
    status_cache_path: Path | None = None,
    now_iso: str | None = None,
) -> InstallSnapshot:
    """Build a fresh :class:`InstallSnapshot` from current host inputs.

    ``capability_index`` defaults to :func:`load_capabilities` of the
    DontPanic repo at ``repo_root``. ``mcp_tool_names`` defaults to the
    in-process MCP registry. ``status_cache_path`` defaults to
    ``~/.dontpanic/capabilities-status.json``. ``now_iso`` is exposed so
    tests can pin ``generated_at`` for deterministic-fingerprint
    assertions.

    Re-invoking with the same inputs produces a snapshot whose body is
    byte-identical except for ``generated_at`` (deterministic-fingerprint
    invariant).
    """

    if capability_index is None:
        capability_index = load_capabilities(repo_root=repo_root)
    fingerprints = tuple(
        capability_fingerprint(manifest) for manifest in capability_index.all
    )
    return InstallSnapshot(
        schema_version=SCHEMA_VERSION,
        generated_at=now_iso if now_iso is not None else _now_iso(),
        dontpanic_version=_DONTPANIC_VERSION,
        profile=profile,
        agent_manifest_schema_version=_agent_manifest.SCHEMA_VERSION,
        mcp_tool_names=mcp_tool_names if mcp_tool_names is not None else discover_mcp_tool_names(),
        capability_ids=tuple(manifest.id for manifest in capability_index.all),
        capabilities=fingerprints,
        status_cache=_read_status_cache_meta(status_cache_path),
    )


# ── io ────────────────────────────────────────────────────────────────────


def _serialize(snapshot: InstallSnapshot) -> str:
    """JSON body written to disk. Uses ``exclude_none`` so optional
    fields (status_cache when absent) don't appear as ``null`` in the
    file — they're simply omitted, matching the regenerable-bytes
    convention used by ``agent_manifest`` and ``global_config``."""
    return (
        json.dumps(
            snapshot.model_dump(mode="json", exclude_none=True),
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


def write_snapshot(
    snapshot: InstallSnapshot,
    *,
    path: Path | None = None,
) -> Path:
    """Persist the snapshot with mode 0o600 (operator-only).

    Creates the parent DontPanic home directory if missing, tightens
    its mode to 0o700 (best-effort — silently skipped on filesystems
    that mask mode bits). Re-attempts the file chmod once if the first
    read-back shows looser bits, defending against shared-FS timing.
    """

    target = path if path is not None else snapshot_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, SNAPSHOT_DIR_MODE)
    except OSError:  # pragma: no cover - best-effort tightening
        pass
    target.write_text(_serialize(snapshot), encoding="utf-8")
    os.chmod(target, SNAPSHOT_FILE_MODE)
    mode_bits = stat.S_IMODE(target.stat().st_mode)
    if mode_bits != SNAPSHOT_FILE_MODE:  # pragma: no cover - FS quirk fallback
        os.chmod(target, SNAPSHOT_FILE_MODE)
    return target


def load_snapshot(path: Path | None = None) -> InstallSnapshot | None:
    """Read the snapshot. Returns ``None`` for missing or unreadable
    files (logs WARN on unreadable / invalid JSON / schema violation).
    Never raises — first-run zero state is ``None`` with no warning."""

    target = path if path is not None else snapshot_path()
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning(
            "install snapshot at %s is unreadable or invalid JSON (%s); returning None",
            target,
            exc,
        )
        return None
    try:
        return InstallSnapshot.model_validate(raw)
    except Exception as exc:
        _LOG.warning(
            "install snapshot at %s failed schema validation (%s); returning None",
            target,
            exc,
        )
        return None


# ── renderers (used by `dontpanic reconcile baseline`) ────────────────────


def render_snapshot_json(snapshot: InstallSnapshot) -> str:
    """JSON output for ``--format=json``. Same shape as the on-disk
    file (``exclude_none=True``)."""
    return _serialize(snapshot)


def render_snapshot_text(snapshot: InstallSnapshot, *, target_path: Path) -> str:
    """Compact human-friendly summary."""

    lines: list[str] = []
    lines.append(f"install-snapshot target: {target_path}")
    lines.append(f"  schema_version:                {snapshot.schema_version}")
    lines.append(f"  dontpanic_version:             {snapshot.dontpanic_version}")
    lines.append(f"  profile:                       {snapshot.profile}")
    lines.append(
        f"  agent_manifest_schema_version: {snapshot.agent_manifest_schema_version}"
    )
    lines.append(f"  generated_at:                  {snapshot.generated_at}")
    lines.append(f"  mcp_tool_names ({len(snapshot.mcp_tool_names)}):")
    for name in snapshot.mcp_tool_names:
        lines.append(f"    - {name}")
    lines.append(f"  capabilities ({len(snapshot.capabilities)}):")
    for cap in snapshot.capabilities:
        lines.append(
            f"    - {cap.capability_id} "
            f"manifest={cap.manifest_fingerprint[:12]}… "
            f"setup_steps={cap.setup_steps_fingerprint[:12]}… "
            f"steps={list(cap.setup_step_ids)}"
        )
    if snapshot.status_cache is not None:
        lines.append("  status_cache:")
        lines.append(f"    path:      {snapshot.status_cache.path}")
        lines.append(f"    mtime_iso: {snapshot.status_cache.mtime_iso}")
        lines.append(f"    sha256:    {snapshot.status_cache.sha256[:16]}…")
    else:
        lines.append("  status_cache: (not present)")
    return "\n".join(lines)


__all__ = [
    "CapabilityFingerprint",
    "InstallSnapshot",
    "SCHEMA_VERSION",
    "SNAPSHOT_DIR_MODE",
    "SNAPSHOT_FILE_MODE",
    "SNAPSHOT_FILENAME",
    "StatusCacheMeta",
    "build_snapshot",
    "capability_fingerprint",
    "discover_mcp_tool_names",
    "load_snapshot",
    "render_snapshot_json",
    "render_snapshot_text",
    "snapshot_path",
    "write_snapshot",
]


# Re-exported so capability-error consumers don't need a second import.
CapabilityLoadError = CapabilityManifestError
__all__.append("CapabilityLoadError")
