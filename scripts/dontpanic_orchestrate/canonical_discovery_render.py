"""Plan 2026-06-17-001 F004 — render layer for ``dontpanic projects discover``.

F003 (:mod:`canonical_discovery`) owns the logic core: the ledger / registry
adapters and the pure five-state ``reconcile`` projection. This module is the
**presentation layer** that F004's CLI wraps around that projection, and it
encodes the C1 privacy boundary as code, not folklore:

* :func:`build_discover_json` serializes the reconcile projection into the pinned
  ``--json`` field contract — scrubbed ``path_display`` + hashed keys + counts /
  recency + ``suggestion_status`` + ``suggested_name`` only. It **never** emits a
  reconstructed raw add-command path; ``registered_path_missing`` /
  ``registered_unresolved`` rows keep ``canonical_repo_key=null`` plus
  ``registry_name`` + ``registry_path_key`` and carry NO ``observed_count`` /
  ``last_seen`` (there is no canonical key to join usage to).

* :func:`render_discover_text` is the concise human summary. It is the ONLY place
  a real absolute path may appear, and only because it reconstructs that path
  **operator-locally at read time** via the three C1 rules
  (:func:`suggestion_status_for` / :func:`reconstruct_add_path`): home-token ->
  ``Path.home()`` substitution, literal -> verbatim, non-reconstructable scrub
  token -> a literal ``<path>`` placeholder flagged needs-manual-path. The
  reconstructed path is computed in the read-time process and never persisted or
  serialized.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.completion_dispatch import sanitize_capture

# C1 suggestion-status enum — exactly these two values (pinned field contract).
SUGGESTION_CAN_RENDER = "can_render_command"
SUGGESTION_NEEDS_MANUAL = "needs_manual_path"

# The only scrub token that is safely re-expandable operator-locally (C1 rule a).
# noqa rationale: S105 misfires on the ``TOKEN`` name — this is a scrub placeholder,
# not a credential.
_HOME_TOKEN = "<home>"  # noqa: S105
# Literal placeholder argument for a non-reconstructable display (C1 rule c),
# mirroring the existing ``UnknownProjectError.add_command`` shape.
_PATH_PLACEHOLDER = "<path>"
# Any ``<...>`` scrub token (``<home>``, ``<operator>``, ``<host>``, …).
_SCRUB_TOKEN_RE = re.compile(r"<[^>]+>")


# ──────────────────────────────  C1 path reconstruction  ──────────────────────────────


def suggestion_status_for(path_display: str | None) -> str:
    """Classify a scrubbed ``path_display`` per the C1 reconstruction rules.

    Returns :data:`SUGGESTION_CAN_RENDER` when a real local path can be
    reconstructed operator-locally — i.e. the display is either a plain literal
    (no scrub token) or carries only the ``<home>`` token — and
    :data:`SUGGESTION_NEEDS_MANUAL` when it carries any non-``<home>`` scrub token
    (``<operator>`` / ``<host>`` / …) that cannot be safely re-expanded, or is
    empty/None (nothing to reconstruct -> fail closed)."""
    if not path_display:
        return SUGGESTION_NEEDS_MANUAL
    tokens = _SCRUB_TOKEN_RE.findall(path_display)
    if any(tok != _HOME_TOKEN for tok in tokens):
        return SUGGESTION_NEEDS_MANUAL
    return SUGGESTION_CAN_RENDER


def reconstruct_add_path(path_display: str | None) -> str | None:
    """Reconstruct the real local path from a scrubbed ``path_display`` (C1).

    * ``<home>``-scrubbed display -> substitute ``str(Path.home())`` for the
      token (rule a);
    * literal display (no scrub token) -> the display verbatim (rule b);
    * non-reconstructable display (any non-``<home>`` token) or empty -> ``None``
      (rule c — the caller emits a ``<path>`` placeholder, never a guess).

    This is computed in the read-time process only and is NEVER persisted or
    serialized."""
    if suggestion_status_for(path_display) != SUGGESTION_CAN_RENDER:
        return None
    if path_display is None:  # unreachable — the status check above fails closed on None
        return None
    if _HOME_TOKEN in path_display:
        return path_display.replace(_HOME_TOKEN, str(Path.home()))
    return path_display


def render_add_command(suggested_name: str, path_display: str | None) -> str:
    """The operator-local ``dontpanic projects add`` command for a candidate (C1).

    Uses the reconstructed real path when the display is reconstructable, else a
    literal ``<path>`` placeholder so the operator fills it in by hand. A concrete
    reconstructed path is run through :func:`shlex.quote` so paths with spaces or
    shell metacharacters produce a copy-pasteable command; the ``<path>``
    placeholder is emitted verbatim (it is intentionally not a real path). Human
    output only — this string is never serialized to ``--json``."""
    real = reconstruct_add_path(path_display)
    path_arg = shlex.quote(real) if real is not None else _PATH_PLACEHOLDER
    name_arg = shlex.quote(suggested_name) if suggested_name else suggested_name
    return f"dontpanic projects add {name_arg} {path_arg}"


# ──────────────────────────────  --json contract (C1)  ──────────────────────────────


def _emit_display(path_display: Any) -> str | None:
    """Scrub a ``path_display`` at the JSON emit boundary (C1 fail-closed).

    The F003 projection already tokenizes displays (``<home>`` / ``<operator>`` /
    ``<host>``), but ``--json`` is the privacy boundary, so we re-run the canonical
    :func:`sanitize_capture` here so a raw home path can NEVER be serialized even if
    an upstream row slipped through unscrubbed. ``sanitize_capture`` is idempotent —
    an already-tokenized display is returned unchanged. ``None`` stays ``None``."""
    if path_display is None:
        return None
    return sanitize_capture(str(path_display))


def _used_unregistered_json(row: Mapping[str, Any]) -> dict[str, Any]:
    """A ``used_unregistered`` JSON row — scrubbed display + key + counts/recency
    + suggestion_status + suggested_name only. No reconstructed raw path."""
    path_display = row.get("path_display")
    return {
        "canonical_repo_key": row.get("canonical_repo_key"),
        "path_display": _emit_display(path_display),
        "observed_count": int(row.get("observed_count", 0)),
        "last_seen": row.get("last_seen"),
        "suggestion_status": suggestion_status_for(path_display),
        "suggested_name": row.get("suggested_name"),
    }


def _registered_json(row: Mapping[str, Any]) -> dict[str, Any]:
    """A ``registered_active`` / ``registered_stale`` JSON row — keyed on
    ``canonical_repo_key``, with conflict surface and pinned observed fields
    (``observed_count=0`` / ``last_seen=null`` when no observed row exists)."""
    return {
        "canonical_repo_key": row.get("canonical_repo_key"),
        "registry_name": row.get("registry_name"),
        "path_display": _emit_display(row.get("path_display")),
        "observed_count": int(row.get("observed_count", 0)),
        "last_seen": row.get("last_seen"),
        "registry_conflict": bool(row.get("registry_conflict", False)),
        "conflicting_registry_names": list(row.get("conflicting_registry_names", [])),
    }


def _null_keyed_json(row: Mapping[str, Any]) -> dict[str, Any]:
    """A ``registered_path_missing`` / ``registered_unresolved`` JSON row —
    ``canonical_repo_key=null`` plus ``registry_name`` + ``registry_path_key`` and
    NO ``observed_count`` / ``last_seen`` (no canonical key to join usage to)."""
    return {
        "canonical_repo_key": None,
        "registry_name": row.get("registry_name"),
        "registry_path_key": row.get("registry_path_key"),
        "path_display": _emit_display(row.get("path_display")),
        "canonicalization_status": row.get("canonicalization_status"),
    }


def build_discover_json(projection: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """Serialize the F003 reconcile projection into the pinned ``--json`` contract.

    Top-level object ``{used_unregistered, registered_active, registered_stale,
    registered_path_missing, registered_unresolved}``; each row is reshaped to
    EXACTLY its pinned field set (no extra keys leak through, no raw path is
    emitted). Empty-state inputs serialize to empty arrays."""
    return {
        "used_unregistered": [
            _used_unregistered_json(r) for r in projection.get("used_unregistered", [])
        ],
        "registered_active": [
            _registered_json(r) for r in projection.get("registered_active", [])
        ],
        "registered_stale": [
            _registered_json(r) for r in projection.get("registered_stale", [])
        ],
        "registered_path_missing": [
            _null_keyed_json(r) for r in projection.get("registered_path_missing", [])
        ],
        "registered_unresolved": [
            _null_keyed_json(r) for r in projection.get("registered_unresolved", [])
        ],
    }


# ──────────────────────────────  human summary  ──────────────────────────────


def _fmt_recency(observed_count: Any, last_seen: Any) -> str:
    return f"count={int(observed_count or 0)}, last_seen={last_seen if last_seen else 'never'}"


def render_discover_text(projection: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    """Concise human summary of the reconcile projection.

    Lists the used-but-unregistered candidates (with an operator-local
    reconstructed ``dontpanic projects add`` command per the C1 rules), the stale
    registered projects, and the registered entries whose path is missing or
    unresolved. This is the ONLY surface that reconstructs a real path; ``--json``
    never does."""
    used = list(projection.get("used_unregistered", []))
    stale = list(projection.get("registered_stale", []))
    missing = list(projection.get("registered_path_missing", []))
    unresolved = list(projection.get("registered_unresolved", []))
    active = list(projection.get("registered_active", []))

    lines: list[str] = []
    lines.append(
        "discover: "
        f"{len(used)} used-unregistered, {len(active)} active, {len(stale)} stale, "
        f"{len(missing) + len(unresolved)} path missing/unresolved"
    )

    if used:
        lines.append("")
        lines.append("used but unregistered (durable repos in recent active use):")
        for row in used:
            path_display = row.get("path_display")
            suggested = str(row.get("suggested_name") or "project")
            lines.append(
                f"  {path_display}  ({_fmt_recency(row.get('observed_count'), row.get('last_seen'))})"
            )
            lines.append(f"    $ {render_add_command(suggested, path_display)}")
            if suggestion_status_for(path_display) == SUGGESTION_NEEDS_MANUAL:
                lines.append(
                    "    # needs manual path: replace <path> with the repo's real "
                    "absolute path before running"
                )

    if stale:
        lines.append("")
        lines.append("registered but stale (no recent qualifying usage):")
        for row in stale:
            lines.append(
                f"  {row.get('registry_name')}  {row.get('path_display')}  "
                f"({_fmt_recency(row.get('observed_count'), row.get('last_seen'))})"
            )

    if missing or unresolved:
        lines.append("")
        lines.append("registered path missing/unresolved (registry hygiene):")
        for row in missing + unresolved:
            lines.append(
                f"  {row.get('registry_name')}  {row.get('path_display')}  "
                f"[{row.get('canonicalization_status')}]"
            )

    if not (used or stale or missing or unresolved):
        lines.append("  nothing to surface — registry and observed usage agree.")

    return "\n".join(lines) + "\n"


__all__ = [
    "SUGGESTION_CAN_RENDER",
    "SUGGESTION_NEEDS_MANUAL",
    "build_discover_json",
    "reconstruct_add_path",
    "render_add_command",
    "render_discover_text",
    "suggestion_status_for",
]
