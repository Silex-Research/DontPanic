"""Plan 2026-06-14-001 F009 (producer half) — channel-view producer.

A build-time producer derives a channel-view object ONLY from the enumerated
source set (D015) and emits it as dashboard state JSON (``operator-channels.json``)
alongside ``operator-triage.json`` — no new registry, no ``agent-channels.json``:

  * the invocation ledger (F003) — projected to its compaction-retained fields only,
  * capabilities incl operator-surface manifests (F008),
  * worktree bindings (the F004/worktrees health model),
  * operator_roles (F004), and
  * ``AGENT_REGISTRY`` — the SOLE dispatchability source.

Conflict/equality comparisons use ``path_key`` (F003), never the scrubbed
``path_display``. ``supports_dispatch`` for a runtime derives from AGENT_REGISTRY,
never hardcoded. The pure :func:`build_channel_view` takes every source as data;
:func:`write_channel_view_state` does the I/O. The pure JS logic module
(``operator-channels-logic.js``) derives the panel buckets from this object under
a LOCKED rule matrix so producer and renderer cannot diverge.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import operator_role_matrix

_LOG = logging.getLogger(__name__)

SCHEMA = "operator-channels/v0"
CHANNELS_FILENAME = "operator-channels.json"

# The ONLY fields a record may expose — exactly the F003 compaction-retained set
# (derive_buckets inputs) plus the four-axis context for display. Reading any
# other ledger field would mean reading raw, compaction-deleted data.
RETAINED_RECORD_FIELDS: tuple[str, ...] = (
    "operator_surface",
    "agent_runtime",
    "role",
    "execution_locality",
    "locality",
    "repo",
    "worktree",
    "branch",
    "plan",
    "last_seen",
    "result",
)

# Runtimes worth a row even if absent from AGENT_REGISTRY (so the panel can show
# operator_only_runtime_not_dispatchable). Mirrors the F001 canonical runtimes.
_KNOWN_RUNTIMES: tuple[str, ...] = ("claude", "codex", "gemini", "grok", "cursor", "antigravity", "opencode", "aider")


def _project_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {k: record.get(k) for k in RETAINED_RECORD_FIELDS}


def _build_runtimes(
    *,
    agent_registry: Iterable[str],
    capability_ids: Iterable[str],
    operator_role_values: Iterable[str],
) -> list[dict[str, Any]]:
    registry = set(agent_registry)
    caps = set(capability_ids)
    ids = sorted(registry | set(_KNOWN_RUNTIMES) | {v for v in operator_role_values if v})
    return [
        {
            "id": rid,
            "supports_dispatch": rid in registry,  # SOLELY AGENT_REGISTRY
            "has_capability_manifest": rid in caps,
        }
        for rid in ids
    ]


def _fingerprint(model: Mapping[str, Any]) -> str:
    payload = {k: v for k, v in model.items() if k not in ("state_revision", "generated_at")}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def build_channel_view(
    *,
    invocation_records: Sequence[Mapping[str, Any]],
    capability_ids: Iterable[str],
    worktree_bindings: Sequence[Mapping[str, Any]],
    operator_roles_map: Mapping[str, Mapping[str, str]],
    agent_registry: Iterable[str],
    worker_role_assignments: Mapping[str, str] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Pure channel-view builder. Derives ONLY from its arguments (the D015 source
    set); projects each record to the compaction-retained fields; carries path_key
    on every path; derives runtime dispatchability from AGENT_REGISTRY alone."""
    records = [_project_record(r) for r in invocation_records]
    op_values = {str(e.get("value")) for e in operator_roles_map.values() if e.get("value")}
    runtimes = _build_runtimes(
        agent_registry=agent_registry, capability_ids=capability_ids, operator_role_values=op_values
    )
    bindings = [
        {
            "path_key": str(b.get("path_key", "")),
            "path_display": str(b.get("path_display", "")),
            "plan": b.get("plan"),
            "branch": b.get("branch"),
            "healthy": bool(b.get("healthy", False)),
        }
        for b in worktree_bindings
    ]
    model: dict[str, Any] = {
        "schema": SCHEMA,
        "records": records,
        "runtimes": runtimes,
        "dispatchable_agents": sorted(set(agent_registry)),
        "worktree_bindings": bindings,
        "operator_roles": operator_role_matrix.project_role_matrix(
            operator_roles_map, worker_role_assignments=worker_role_assignments
        ),
        "data_quality": {
            "record_count": len(records),
            "runtime_count": len(runtimes),
            "binding_count": len(bindings),
        },
    }
    model["state_revision"] = _fingerprint(model)
    if now is not None:
        model["generated_at"] = now
    return model


# ──────────────────────────────  I/O wrapper  ──────────────────────────────


def _load_ledger_records() -> list[dict[str, Any]]:
    from dontpanic_orchestrate import invocation_ledger

    path = invocation_ledger.ledger_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_capability_ids(repo_root: Path | None) -> set[str]:
    try:
        from dontpanic_orchestrate.capabilities import load_capabilities

        return {m.id for m in load_capabilities(repo_root).all}
    except Exception as exc:  # noqa: BLE001 — best-effort source
        _LOG.warning("channel-view capability load failed: %s", exc)
        return set()


def _load_worktree_bindings() -> list[dict[str, Any]]:
    try:
        from dontpanic_orchestrate import invocation_ledger, worktrees

        model = worktrees.build_status_model()
        out: list[dict[str, Any]] = []
        for b in model.get("bindings", []):
            pair = invocation_ledger.make_path_pair(b.get("worktree_path")) or {}
            out.append(
                {
                    "path_key": pair.get("path_key", ""),
                    "path_display": pair.get("path_display", ""),
                    "plan": b.get("plan_id"),
                    "branch": b.get("branch"),
                    "healthy": bool(b.get("healthy", False)),
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001 — best-effort source
        _LOG.warning("channel-view worktree-binding load failed: %s", exc)
        return []


def _load_operator_roles() -> dict[str, dict[str, str]]:
    try:
        from dontpanic_orchestrate import operator_roles

        return operator_roles.list_operator_roles()
    except Exception as exc:  # noqa: BLE001 — best-effort source
        _LOG.warning("channel-view operator-roles load failed: %s", exc)
        return {}


def _load_agent_registry() -> set[str]:
    try:
        from dontpanic_orchestrate import executors

        return set(executors.AGENT_REGISTRY)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("channel-view AGENT_REGISTRY load failed: %s", exc)
        return set()


def write_channel_view_state(
    out_path: str | Path,
    *,
    now: str | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Load the D015 sources and serialize the channel-view to ``out_path``
    (``operator-channels.json``). Returns the path."""
    model = build_channel_view(
        invocation_records=_load_ledger_records(),
        capability_ids=_load_capability_ids(repo_root),
        worktree_bindings=_load_worktree_bindings(),
        operator_roles_map=_load_operator_roles(),
        agent_registry=_load_agent_registry(),
        now=now,
    )
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    return path


__all__ = [
    "CHANNELS_FILENAME",
    "RETAINED_RECORD_FIELDS",
    "SCHEMA",
    "build_channel_view",
    "write_channel_view_state",
]
