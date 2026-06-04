"""Plan 2026-05-03-003 F001 — global agent manifest at
``~/.dontpanic/agent-manifest.json``.

Discovery file answering "How does an agent find and invoke DontPanic on
this machine?" Read by ecosystem agents (OpenClaw skills, Claude Code,
Codex CLI, Cursor, Claude-managed agents, MCP clients) to bootstrap a
calling relationship without operator hand-holding. Mirrors the global
config / projects registry / project config patterns established by
Phase A (F001/F002/F003 of plan 2026-05-03-001).

Schema invariants (D006):
- ``extra='forbid'`` on all models — rejects every unknown field.
- Schema's own field names are checked against `_token` / `_key` /
  `_secret` substrings via :data:`_FORBIDDEN_FIELD_SUBSTRINGS` so a
  future contributor accidentally adding a credential-shaped field is
  caught at import time. The manifest is machine-level discovery, not
  a credential surface.
- Regenerable: :func:`write_manifest` is idempotent at the byte level.
  Same inputs → same bytes. No timestamps in the body.

Safety-rule invariant (D007): :func:`bootstrap_manifest` always seeds
``safety_rules`` with the canonical "do not dispatch without user
approval" string so any agent reading the manifest sees it.

Filesystem path: resolved through :mod:`dontpanic_orchestrate.global_config`
(`dontpanic_home()`). New installs use ``~/.dontpanic/agent-manifest.json``;
``$JARVIS_HOME`` and ``~/.jarvis/agent-manifest.json`` remain compatibility
fallbacks during the staged rename.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from dontpanic_orchestrate import __version__ as _DONTPANIC_VERSION
from dontpanic_orchestrate import global_config as gc

_LOG = logging.getLogger(__name__)

MANIFEST_FILENAME = "agent-manifest.json"

SCHEMA_VERSION = "1.0"
"""Pinned at the v1 contract. Bump when fields are added or removed; readers
that don't recognize a newer schema_version should refuse to interpret the
file rather than guess."""

InstallSource = Literal["pipx", "pip-editable", "source"]
"""Where this DontPanic install came from. ``pipx`` is the canonical
end-user install path; ``pip-editable`` is for contributor / dev-mode
installs; ``source`` is for runs out of an unpacked git checkout."""

# D007: the canonical "do not dispatch without user approval" rule.
# Stamped into every bootstrapped manifest's safety_rules. Tested for
# verbatim presence by F003's discoverability docs as well so the same
# string lands in README + ECOSYSTEM.md.
SAFETY_RULE_NO_AUTO_DISPATCH = (
    "Always surface the plan to the user before calling "
    "dispatch(confirm=true). Do NOT auto-confirm."
)

_FORBIDDEN_FIELD_SUBSTRINGS = ("_token", "_key", "_secret")
"""D006 secret-free invariant. Manifest schema's own field names must not
contain any of these substrings. Asserted at module import time below so a
future contributor accidentally adding a credential-shaped field is caught
immediately, not by a sanitization pass run after the fact."""


class McpServerSpec(BaseModel):
    """How to invoke the DontPanic MCP server. Optional in F001; populated
    by F002 once ``dontpanic mcp serve`` ships. Re-running
    :func:`bootstrap_manifest` after F002 lands fills this in."""

    model_config = ConfigDict(extra="forbid")

    command: str
    args: list[str] = []


class AgentManifest(BaseModel):
    """Global discovery file at ``~/.dontpanic/agent-manifest.json``.

    Machine-level state. Not committed to project repos. Regenerable:
    operators (or a future ``dontpanic bootstrap`` helper) can rewrite
    this file from scratch and recover from corruption. The schema
    rejects unknown fields under ``extra='forbid'`` so an outdated
    manifest from an older DontPanic cannot silently break a newer
    one — readers that fail validation degrade to ``None`` + WARN
    (see :func:`load_manifest`).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    """Pinned to ``'1.0'`` for the v1 contract. Bumped only when
    ``AgentManifest`` field set changes."""

    dontpanic_version: str
    """The DontPanic runtime version that produced this manifest. Stamped
    from :data:`dontpanic_orchestrate.__version__` at write time."""

    install_source: InstallSource
    """Where this install came from. Constrained enum so future tooling
    (e.g. ``dontpanic upgrade``) can branch on the install path."""

    cli_path: str
    """Absolute path to the ``dontpanic`` (or legacy ``jarvis``) console
    script on this machine. Agents use this to invoke the CLI without
    relying on PATH."""

    project_registry_path: str
    """Absolute path to ``projects.json`` under the resolved DontPanic
    home. Lets agents discover registered projects without recomputing
    the home-directory precedence themselves."""

    supported_commands: list[str]
    """Stable subcommand names this DontPanic version exposes. Agents
    that branch on capability inspect this list before invoking a
    command. New commands appear here as features ship."""

    safety_rules: list[str]
    """Operator-facing rules that agents reading the manifest should
    honor. Always seeded by :func:`bootstrap_manifest` with at least
    the canonical "do not dispatch without user approval" rule (D007)."""

    mcp_server: McpServerSpec | None = None
    """How to invoke the MCP server, if available on this install.
    Optional in F001 — F002 lands the server and re-runs
    :func:`bootstrap_manifest` to populate this field."""


# ──────────────────────────────  D006: import-time secret-free check  ──────────────────────────────


def _assert_no_credential_shaped_fields() -> None:
    """D006: manifest schema's own field names must not contain
    ``_token`` / ``_key`` / ``_secret``. Asserted at module import time
    so a future contributor accidentally adding a credential-shaped
    field is caught immediately."""
    for field_name in AgentManifest.model_fields:
        for forbidden in _FORBIDDEN_FIELD_SUBSTRINGS:
            if forbidden in field_name:  # pragma: no cover — defensive
                raise RuntimeError(
                    f"AgentManifest.{field_name} contains forbidden substring "
                    f"{forbidden!r}; secret-shaped field names are banned by D006"
                )


_assert_no_credential_shaped_fields()


# ──────────────────────────────  paths + load/save  ──────────────────────────────


def manifest_path() -> Path:
    """Path to ``agent-manifest.json`` under the resolved DontPanic home.
    Honors ``$DONTPANIC_HOME`` first, then ``$JARVIS_HOME`` legacy
    fallback (delegated to :func:`gc.dontpanic_home`)."""
    return gc.dontpanic_home() / MANIFEST_FILENAME


def load_manifest() -> AgentManifest | None:
    """Load the manifest. Total: missing file → ``None`` (no warn — first-run
    zero state); invalid JSON / OSError → WARN + ``None``; schema-violation
    → WARN + ``None``. Never raises. Mirrors :func:`gc.load_config`."""
    path = manifest_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning(
            "agent manifest at %s is unreadable or invalid JSON (%s); returning None",
            path,
            exc,
        )
        return None
    try:
        return AgentManifest.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError or similar
        _LOG.warning(
            "agent manifest at %s failed schema validation (%s); returning None",
            path,
            exc,
        )
        return None


def write_manifest(manifest: AgentManifest) -> Path:
    """Persist the manifest to ``agent-manifest.json``. Creates the
    DontPanic home if missing. Returns the written path.

    D006 regenerable invariant: re-running with the same input produces
    a byte-identical file. ``exclude_none=True`` keeps optional fields
    (e.g. ``mcp_server`` before F002 ships) out of the body so the
    same logical state serializes the same way before and after F002.
    Pydantic's default field ordering is stable. No timestamps are
    stamped into the body."""
    home = gc.ensure_dontpanic_home()
    path = home / MANIFEST_FILENAME
    path.write_text(
        json.dumps(
            manifest.model_dump(exclude_none=True),
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    return path


# ──────────────────────────────  bootstrap  ──────────────────────────────


def _default_supported_commands() -> list[str]:
    """The Phase A surface that ships in every DontPanic install. Phase B
    F001 adds ``manifest`` to this list; F002 adds ``mcp`` once
    ``dontpanic mcp serve`` is importable. Plan 2026-05-30-001 F002 adds the
    ``agent`` machine surface and the ``orchestrate`` teaching gateway; F004
    adds the ``roles`` worker-role-assignment surface. Future phases append as
    new subcommands ship; the order is stable so the regenerable invariant
    holds."""
    base = [
        "projects",
        "doctor",
        "manifest",
        "agent",
        "orchestrate",
        "roles",
        "approve",
        "resume",
        "ps",
        "dispatch-from-plan",
        # Plan 2026-06-01-001 F003 — read-only scope-lint surface.
        "plan-review",
    ]
    if _detect_mcp_server() is not None:
        base.append("mcp")
    return base


def _default_safety_rules() -> list[str]:
    """Seed safety_rules with at least the canonical "do not dispatch
    without user approval" rule (D007). Future operator-facing rules
    append to this list — the canonical rule stays at index 0 for
    discoverability."""
    return [SAFETY_RULE_NO_AUTO_DISPATCH]


def _detect_mcp_server() -> McpServerSpec | None:
    """Detect whether F002's MCP server is available on this install. Returns
    the canonical operator-CLI invocation (``dontpanic mcp serve``) when the
    :mod:`dontpanic_orchestrate.mcp_server` module is importable, else ``None``.

    The detection is strictly importability-based — it does not call
    ``serve_main`` or open the stdio loop. Re-running
    :func:`bootstrap_manifest` after F002 lands therefore populates the
    manifest's ``mcp_server`` block automatically; before F002 ships the
    import fails and the field stays unset.

    Per D011 of plan 2026-05-03-003, operator-facing strings use the
    canonical ``dontpanic`` form, not ``python -m dontpanic_orchestrate``
    (the latter is reserved for module-invocation / packaging
    verification)."""
    try:
        from dontpanic_orchestrate import mcp_server  # noqa: F401
    except ImportError:
        return None
    return McpServerSpec(
        command=mcp_server.MCP_SERVER_COMMAND,
        args=list(mcp_server.MCP_SERVER_ARGS),
    )


def bootstrap_manifest(
    *,
    install_source: InstallSource = "source",
    cli_path: str = "dontpanic",
) -> AgentManifest:
    """Build a fresh :class:`AgentManifest` from current host inputs.

    The version is pinned from :data:`dontpanic_orchestrate.__version__`
    (single source of truth — same field that pyproject.toml's dynamic
    version resolution reads). The project registry path is derived
    from :func:`gc.dontpanic_home` so the resolved DontPanic home (with
    legacy ``$JARVIS_HOME`` fallback) flows through.

    Plan 2026-05-03-003 F002: when ``dontpanic_orchestrate.mcp_server`` is
    importable, the manifest's ``mcp_server`` block is populated with
    the canonical ``dontpanic mcp serve`` invocation. Before F002 ships
    (or in environments where the module is missing) the field stays
    ``None`` and is excluded from the on-disk JSON via ``exclude_none``.

    Idempotent: same inputs → same output. Combined with
    :func:`write_manifest`'s regenerable invariant, ``bootstrap_manifest()
    → write_manifest()`` produces a byte-identical file on every run
    that shares the same inputs."""
    return AgentManifest(
        schema_version=SCHEMA_VERSION,
        dontpanic_version=_DONTPANIC_VERSION,
        install_source=install_source,
        cli_path=cli_path,
        project_registry_path=str(gc.dontpanic_home() / "projects.json"),
        supported_commands=_default_supported_commands(),
        safety_rules=_default_safety_rules(),
        mcp_server=_detect_mcp_server(),
    )


def to_public_dict(manifest: AgentManifest) -> dict[str, Any]:
    """Serialize the manifest for ``--json`` CLI output. Mirrors the
    on-disk shape (``exclude_none=True``)."""
    return manifest.model_dump(exclude_none=True)


__all__ = [
    "AgentManifest",
    "InstallSource",
    "MANIFEST_FILENAME",
    "McpServerSpec",
    "SAFETY_RULE_NO_AUTO_DISPATCH",
    "SCHEMA_VERSION",
    "bootstrap_manifest",
    "load_manifest",
    "manifest_path",
    "to_public_dict",
    "write_manifest",
]


# Internal helper exported for F002's regression test. Not part of the
# stable public API — tests assert it returns the canonical spec when the
# F002 module is importable.
__all__.append("_detect_mcp_server")
