"""Plan 2026-05-22-002 F003 — lock-time advisory required-capabilities sidecar.

``dontpanic plan lock`` calls into this module after the status flip to emit
``evidence/required-capabilities.json``, a per-capability readiness summary
sourced from:

* ``external_refs[]`` entries whose URI scheme maps to a registered adapter
  with a declared ``capability_id`` (the F004 substrate), AND
* the new ``requires_capabilities[]`` plan frontmatter field.

The sidecar is ADVISORY ONLY. Lock proceeds even when bound capabilities are
not ready; the only hard error is an unknown ``capability_id`` in
``requires_capabilities[]`` (operator-introduced bad reference, surfaced via
:class:`RequiresCapabilityUnknownError` with a closest-match suggestion).

Sanitization invariant: emitted ``next_actions[]`` carry ``step.what`` only,
never the manifest's ``command_template`` (avoids leaking placeholder
examples that look like secrets).
"""

from __future__ import annotations

import datetime as _dt
import difflib
import json
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.capabilities import (
    CapabilityIndex,
    CapabilityManifest,
    load_capabilities,
)
from dontpanic_orchestrate.capabilities_status import (
    DEFAULT_CACHE_PATH,
    CapabilityStatus,
    run_status,
)
from dontpanic_orchestrate.external_refs_sync import AdapterResolver

SIDECAR_RELPATH: Path = Path("evidence") / "required-capabilities.json"
SCHEMA_VERSION = "1.0.0"


class RequiresCapabilityUnknownError(ValueError):
    """Raised when ``requires_capabilities[]`` references an unknown id.

    The error message embeds a closest-match suggestion (when one exists)
    so the operator sees an actionable fix without re-reading the manifest
    directory. Lock callers translate this into a loud REFUSED message and
    halt the status flip — bad references are config errors, not runtime
    environment-state issues.
    """


def validate_requires_capabilities(
    required_ids: list[str],
    capability_index: CapabilityIndex,
) -> None:
    """Validate every ``requires_capabilities[]`` id against the manifest index.

    Raises :class:`RequiresCapabilityUnknownError` on the first unknown id
    with a closest-match suggestion when one exists. Empty lists return
    silently (advisory absent = no validation).
    """

    known_ids = [m.id for m in capability_index.all]
    for capability_id in required_ids:
        if capability_index.get(capability_id) is not None:
            continue
        suggestion = difflib.get_close_matches(capability_id, known_ids, n=1, cutoff=0.5)
        if suggestion:
            raise RequiresCapabilityUnknownError(
                f"requires_capabilities[]: unknown capability_id "
                f"{capability_id!r}; did you mean {suggestion[0]!r}?"
            )
        raise RequiresCapabilityUnknownError(
            f"requires_capabilities[]: unknown capability_id "
            f"{capability_id!r}; known: {', '.join(known_ids) or '<none>'}"
        )


# ── plan frontmatter readers ──────────────────────────────────────────────


def _read_plan_frontmatter(plan_dir: Path) -> dict[str, Any]:
    """Narrow YAML parse of ``plan.md`` frontmatter. Returns ``{}`` for
    plans missing the file or the delimiter — callers treat that as "no
    advisory binding declared" and short-circuit."""

    import yaml

    plan_md = plan_dir / "plan.md"
    if not plan_md.is_file():
        return {}
    text = plan_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = yaml.safe_load(parts[1]) or {}
    return fm if isinstance(fm, dict) else {}


def read_requires_capabilities(plan_dir: Path) -> list[str]:
    """Plan-frontmatter accessor for ``requires_capabilities[]``."""

    fm = _read_plan_frontmatter(plan_dir)
    raw = fm.get("requires_capabilities") or []
    return [str(item) for item in raw]


def read_external_refs(plan_dir: Path) -> list[dict[str, Any]]:
    """Plan-frontmatter accessor for ``external_refs[]`` as plain dicts.

    Kept thin — the sidecar only reads ``uri`` and ``capability_id``, so
    the full :class:`ExternalRef` Pydantic round-trip is overkill (and
    would couple this module to the schemas package import path).
    """

    fm = _read_plan_frontmatter(plan_dir)
    raw = fm.get("external_refs") or []
    return [r for r in raw if isinstance(r, dict)]


# ── source binding ────────────────────────────────────────────────────────


def _collect_external_ref_capability_ids(
    refs: list[dict[str, Any]],
    resolver: AdapterResolver | None,
) -> dict[str, list[str]]:
    """Walk ``external_refs[]`` and pull capability bindings.

    Precedence: explicit ``capability_id`` on the ref wins. When the ref
    omits it, fall back to ``resolver.capability_id_for_uri(uri)`` so a
    registered adapter with a capability_id surfaces its binding to the
    sidecar even for legacy refs.

    Returns a mapping ``capability_id → [uri, …]`` so the JSON shape can
    list every URI that contributed to a given capability binding.
    """

    bindings: dict[str, list[str]] = {}
    for ref in refs:
        explicit = ref.get("capability_id")
        if isinstance(explicit, str) and explicit:
            bindings.setdefault(explicit, []).append(str(ref.get("uri", "")))
            continue
        if resolver is None:
            continue
        uri = ref.get("uri")
        if not isinstance(uri, str):
            continue
        capability_id = resolver.capability_id_for_uri(uri)
        if capability_id is not None:
            bindings.setdefault(capability_id, []).append(uri)
    return bindings


# ── status data sources ───────────────────────────────────────────────────


def _read_status_from_cache(cache_path: Path) -> dict[str, dict[str, Any]] | None:
    """Read the F002 ``capabilities-status.json`` cache when present.

    Returns ``capability_id → entry`` mapping or ``None`` when the cache
    is missing or malformed. A best-effort read — corruption falls back
    to recomputation rather than blocking lock.
    """

    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list):
        return None
    out: dict[str, dict[str, Any]] = {}
    for entry in capabilities:
        if not isinstance(entry, dict):
            continue
        capability_id = entry.get("capability_id")
        if isinstance(capability_id, str):
            out[capability_id] = entry
    return out


def _compute_status_fresh(
    capability_index: CapabilityIndex,
) -> dict[str, dict[str, Any]]:
    """Recompute status via the F002 run_status pipeline.

    Used when the cache is absent / malformed, and indirectly by tests
    that want the sidecar to ignore a stale cache.
    """

    envelope = run_status(capability_index=capability_index)
    return {c.capability_id: _envelope_entry_to_dict(c) for c in envelope.capabilities}


def _envelope_entry_to_dict(entry: Any) -> dict[str, Any]:
    """Adapter from CapabilityStatusResult → cache-shaped dict.

    Keeps the cache-read and recompute-read paths producing the same
    shape, so the sidecar emitter doesn't branch on source.
    """

    status_value = (
        entry.status.value if isinstance(entry.status, CapabilityStatus) else str(entry.status)
    )
    return {
        "capability_id": entry.capability_id,
        "status": status_value,
        "owner_boundary": {k: list(v) for k, v in entry.owner_boundary.items()},
        "missing": list(entry.missing),
        "next_actions": [dict(a) for a in entry.next_actions],
    }


# ── sanitization ──────────────────────────────────────────────────────────


def _sanitize_next_actions(
    raw_next_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Strip command_template strings — sidecar emits human-readable
    summaries (``step.what``) only. Placeholder examples can pattern-match
    secret-scanner false positives downstream, so we never serialize them
    here even though the manifest tolerates them at rest."""

    sanitized: list[dict[str, Any]] = []
    for action in raw_next_actions:
        entry = {
            "id": action.get("id"),
            "what": action.get("what"),
            "automatable": bool(action.get("automatable", False)),
        }
        # Preserve the human_required_reason — it's plain text guidance,
        # not a command. ``verify_probe`` is also safe (a probe name).
        if action.get("human_required_reason"):
            entry["human_required_reason"] = action["human_required_reason"]
        if action.get("verify_probe"):
            entry["verify_probe"] = action["verify_probe"]
        sanitized.append(entry)
    return sanitized


def _manifest_next_actions(manifest: CapabilityManifest) -> list[dict[str, Any]]:
    """Render setup_steps[] → sidecar next_actions without command_template."""

    return [
        {
            "id": step.id,
            "what": step.what,
            "automatable": step.automatable,
            **(
                {"human_required_reason": step.human_required_reason}
                if step.human_required_reason
                else {}
            ),
            **({"verify_probe": step.verify_probe} if step.verify_probe else {}),
        }
        for step in manifest.setup_steps
    ]


# ── sidecar assembly ──────────────────────────────────────────────────────


def _entry_for_capability(
    capability_id: str,
    sources: list[str],
    status_entry: dict[str, Any] | None,
    manifest: CapabilityManifest | None,
    contributing_uris: list[str] | None = None,
) -> dict[str, Any]:
    """Build one ``required_capabilities[]`` element.

    ``status_entry`` carries shape from either the F002 cache or the
    recompute path (see :func:`_envelope_entry_to_dict`). When neither is
    available — e.g. manifest exists but status pipeline produced no
    result for it — we fall back to a ``status='unknown'`` advisory entry
    sourced from the manifest's own ``setup_steps[]`` so the operator
    still sees actionable next steps.
    """

    next_actions_raw: list[dict[str, Any]]
    if status_entry is not None and status_entry.get("next_actions"):
        next_actions_raw = list(status_entry["next_actions"])
    elif manifest is not None:
        next_actions_raw = _manifest_next_actions(manifest)
    else:
        next_actions_raw = []

    status = (status_entry or {}).get("status", "unknown")
    missing = list((status_entry or {}).get("missing") or [])
    owner_boundary = (status_entry or {}).get("owner_boundary") or (
        {
            "dontpanic_core": list(manifest.owner_boundary.dontpanic_core),
            "adapter": list(manifest.owner_boundary.adapter),
            "operator": list(manifest.owner_boundary.operator),
        }
        if manifest is not None
        else {"dontpanic_core": [], "adapter": [], "operator": []}
    )

    # F003 contract: ``source`` is ALWAYS a string union value
    # (``'external_refs'`` | ``'requires_capabilities'``) — never a list.
    # Precedence when the same capability_id is declared by both origins:
    # ``requires_capabilities`` wins (an operator explicitly listing the
    # id is a stronger declaration than an external_ref scheme match). A
    # separate ``sources[]`` array surfaces every origin so consumers can
    # still attribute readiness drives without re-parsing the field shape.
    primary_source = "requires_capabilities" if "requires_capabilities" in sources else sources[0]
    entry: dict[str, Any] = {
        "capability_id": capability_id,
        "status": status,
        "missing": missing,
        "next_actions": _sanitize_next_actions(next_actions_raw),
        "owner_boundary": owner_boundary,
        "source": primary_source,
    }
    if len(sources) > 1:
        entry["sources"] = list(sources)
    if contributing_uris:
        entry["external_ref_uris"] = list(contributing_uris)
    return entry


def emit_required_capabilities(
    plan_dir: Path,
    *,
    capability_index: CapabilityIndex | None = None,
    resolver: AdapterResolver | None = None,
    status_cache: Path | None = None,
    now: _dt.datetime | None = None,
) -> Path | None:
    """Write ``evidence/required-capabilities.json`` for one plan.

    Returns the sidecar path when the plan declares external_refs OR
    requires_capabilities — even if no capability bindings ultimately
    resolve. Returns ``None`` only when BOTH lists are absent/empty, so
    plans with no advisory binding pay no I/O.

    The public contract is ``emit_required_capabilities(plan_dir, *,
    status_cache=None)`` — :class:`CapabilityIndex` and
    :class:`AdapterResolver` defaults are lazy-loaded from the manifest
    registry and the operator's adapter config respectively, so callers
    that only have a plan path do not need to wire dependency injection
    seams. Tests still pass instances for hermetic fakes.

    The caller is responsible for pre-validating ``requires_capabilities``
    via :func:`validate_requires_capabilities` BEFORE calling this — the
    sidecar emitter assumes every requested id is known. Lock CLI wires
    that ordering; tests do too.
    """

    plan_dir = Path(plan_dir).resolve()
    requires_caps = read_requires_capabilities(plan_dir)
    external_refs = read_external_refs(plan_dir)
    if not requires_caps and not external_refs:
        return None

    if capability_index is None:
        capability_index = load_capabilities()

    # Lazy-load the adapter resolver only when the plan actually declares
    # external_refs[] and the caller didn't inject one. Plans with only
    # requires_capabilities[] pay no adapter-registry import cost.
    if resolver is None and external_refs:
        from dontpanic_orchestrate.integrations.adapter_registry import default_resolver

        resolver = default_resolver(capability_index=capability_index)

    # Pull external_refs capability bindings (explicit + resolver-derived).
    ref_bindings = _collect_external_ref_capability_ids(external_refs, resolver)

    # Status data: prefer the F002 cache, fall back to fresh recompute.
    cache_path = status_cache if status_cache is not None else DEFAULT_CACHE_PATH
    status_data = _read_status_from_cache(cache_path)
    if status_data is None:
        status_data = _compute_status_fresh(capability_index)

    # Source-tag every binding. ``requires_capabilities`` wins precedence
    # when an id appears in both, but the source field encodes both
    # origins so consumers can attribute readiness drives.
    capability_sources: dict[str, list[str]] = {}
    for cap_id in ref_bindings:
        capability_sources.setdefault(cap_id, []).append("external_refs")
    for cap_id in requires_caps:
        capability_sources.setdefault(cap_id, []).append("requires_capabilities")

    advisory_notes: list[str] = []
    if external_refs and not ref_bindings and not requires_caps:
        # All external_refs URIs missed adapter mappings AND no
        # requires_capabilities declared — sidecar still emits (per
        # acceptance #4) but the array is empty plus an advisory note.
        advisory_notes.append(
            "external_refs[] declared but no URI scheme resolved to a "
            "registered adapter with capability_id binding; sidecar emits "
            "an empty required_capabilities[] array."
        )

    required_entries: list[dict[str, Any]] = []
    for capability_id, sources in capability_sources.items():
        manifest = capability_index.get(capability_id)
        status_entry = status_data.get(capability_id)
        contributing_uris = ref_bindings.get(capability_id) if "external_refs" in sources else None
        required_entries.append(
            _entry_for_capability(
                capability_id,
                sources,
                status_entry,
                manifest,
                contributing_uris=contributing_uris,
            )
        )

    # Stable ordering: alphabetical by capability_id keeps snapshots clean.
    required_entries.sort(key=lambda e: e["capability_id"])

    generated_at = (now if now is not None else _dt.datetime.now(_dt.timezone.utc)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    plan_id = _read_plan_frontmatter(plan_dir).get("id", plan_dir.name)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_id,
        "generated_at": generated_at,
        "required_capabilities": required_entries,
    }
    if advisory_notes:
        payload["advisory_notes"] = advisory_notes

    sidecar_path = plan_dir / SIDECAR_RELPATH
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sidecar_path


def count_unready_capabilities(sidecar_path: Path) -> int:
    """Read the sidecar back and count entries with status != 'ready'.

    Used by the lock CLI to decide whether to print the warning chip.
    Returns 0 when the file is missing / unreadable (advisory failure
    must never block the warning code path).
    """

    if not sidecar_path.is_file():
        return 0
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    entries = payload.get("required_capabilities") or []
    return sum(1 for e in entries if isinstance(e, dict) and e.get("status") != "ready")


__all__ = [
    "RequiresCapabilityUnknownError",
    "SCHEMA_VERSION",
    "SIDECAR_RELPATH",
    "count_unready_capabilities",
    "emit_required_capabilities",
    "read_external_refs",
    "read_requires_capabilities",
    "validate_requires_capabilities",
]
