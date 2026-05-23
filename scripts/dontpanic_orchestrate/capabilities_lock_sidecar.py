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
    applicability_report: Any | None = None,
) -> Path | None:
    """Write ``evidence/required-capabilities.json`` for one plan.

    Returns the sidecar path when the plan declares external_refs OR
    requires_capabilities OR yields any F005 advisory match (surface or
    skill inference) — even if no bindings ultimately resolve. Returns
    ``None`` only when ALL inputs are empty.

    The public contract is ``emit_required_capabilities(plan_dir, *,
    status_cache=None, applicability_report=None)`` —
    :class:`CapabilityIndex` and :class:`AdapterResolver` defaults are
    lazy-loaded from the manifest registry and the operator's adapter
    config respectively. Tests still pass instances for hermetic fakes.

    F005 (plan 2026-05-21-001) adds the ``matches[]`` + ``skips[]``
    arrays alongside the existing ``required_capabilities[]`` view. The
    new arrays infer capabilities from plan ``surfaces``,
    ``external_refs[]``, and the optional applicability report — see
    :func:`infer_advisory_capabilities` for the precedence rules.

    The caller is responsible for pre-validating ``requires_capabilities``
    via :func:`validate_requires_capabilities` BEFORE calling this — the
    sidecar emitter assumes every requested id is known. Lock CLI wires
    that ordering; tests do too.
    """

    plan_dir = Path(plan_dir).resolve()
    requires_caps = read_requires_capabilities(plan_dir)
    external_refs = read_external_refs(plan_dir)

    plan_frontmatter = _read_plan_frontmatter(plan_dir)
    raw_surfaces = plan_frontmatter.get("surfaces") or []
    surfaces = [str(s) for s in raw_surfaces if isinstance(s, str)]

    if capability_index is None:
        capability_index = load_capabilities()

    # Lazy-load the adapter resolver only when the plan actually declares
    # external_refs[] and the caller didn't inject one. Plans with only
    # requires_capabilities[] pay no adapter-registry import cost.
    if resolver is None and external_refs:
        from dontpanic_orchestrate.integrations.adapter_registry import default_resolver

        resolver = default_resolver(capability_index=capability_index)

    # Status data: prefer the F002 cache, fall back to fresh recompute.
    # Computed up-front because F005 inference also consumes it for the
    # ``verified|missing_config|...`` status mapping.
    cache_path = status_cache if status_cache is not None else DEFAULT_CACHE_PATH
    status_data: dict[str, dict[str, Any]] | None = None
    if not requires_caps and not external_refs and not surfaces and applicability_report is None:
        # Cheap exit: no inputs at all → no sidecar.
        return None

    status_data = _read_status_from_cache(cache_path)
    if status_data is None:
        status_data = _compute_status_fresh(capability_index)

    # F005 (plan 2026-05-21-001) advisory inference. Runs even when only
    # surfaces or a skill applicability report are present, so plans without
    # external_refs/requires_capabilities can still emit a matches[] view.
    f005_matches, f005_skips = infer_advisory_capabilities(
        surfaces=surfaces,
        external_refs=external_refs,
        applicability_report=applicability_report,
        capability_index=capability_index,
        status_data=status_data,
        resolver=resolver,
    )

    if not requires_caps and not external_refs and not f005_matches and not f005_skips:
        return None

    # Pull external_refs capability bindings (explicit + resolver-derived).
    ref_bindings = _collect_external_ref_capability_ids(external_refs, resolver)

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
        # F005 plan 2026-05-21-001 — advisory matches/skips inferred from
        # plan surfaces, external_refs, and (optional) skill applicability.
        "matches": f005_matches,
        "skips": f005_skips,
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


# ── F005 advisory inference (plan 2026-05-21-001) ─────────────────────────
#
# Separate from the requires_capabilities/external_refs ``required_capabilities[]``
# path above: F005 emits a complementary ``matches[]`` + ``skips[]`` view that
# captures advisory bindings inferred from plan surfaces, external_refs, and
# matched skill applicability results. Status values use the F005 vocabulary
# (``unknown|verified|missing_config|not_registered``) rather than the F003
# CapabilityStatus enum so consumers can read either array without conflating
# the schemas.


# Surface → capability advisory hints. Intentionally a small, reviewable
# table — F005 is advisory only, so over-matching is worse than missing
# matches (each row should be defensible without an ADR amendment). The
# mapping reflects ADR-001's category split: surfaces that commonly involve
# a hosted dashboard surface (web/backend/infra) hint at firebase-dashboard.
_SURFACE_CAPABILITY_HINTS: dict[str, tuple[str, ...]] = {
    "web": ("firebase-dashboard",),
    "backend": ("firebase-dashboard",),
    "infra": ("firebase-dashboard",),
}


def _f005_status_for(
    capability_id: str,
    manifest: CapabilityManifest | None,
    status_entry: dict[str, Any] | None,
    resolver: AdapterResolver | None,
) -> str:
    """Map F003-status + adapter registration into the F005 status vocab.

    ``verified``         → F002 says ready.
    ``missing_config``   → F002 says needs_setup/blocked/not_installed.
    ``not_registered``   → adapter-kind capability with no registered adapter.
    ``unknown``          → no manifest match OR no status data.
    """

    if manifest is None:
        return "unknown"

    # Adapter-kind capabilities need a registered adapter to be useful.
    # Probe the resolver only when one is available; absence of a resolver
    # leaves status to the readiness pipeline.
    if resolver is not None and manifest.kind in {"service_adapter", "external_adapter"}:
        registered = (
            resolver.has_capability_id(capability_id)
            if hasattr(resolver, "has_capability_id")
            else None
        )
        if registered is False:
            return "not_registered"

    if status_entry is None:
        return "unknown"
    raw = status_entry.get("status")
    if raw == CapabilityStatus.READY.value or raw == "ready":
        return "verified"
    if raw in {
        CapabilityStatus.NEEDS_SETUP.value,
        CapabilityStatus.BLOCKED.value,
        CapabilityStatus.NOT_INSTALLED.value,
    }:
        return "missing_config"
    return "unknown"


def _skill_applicability_capability_hints(
    applicability_report: Any | None,
    capability_index: CapabilityIndex,
) -> dict[str, list[str]]:
    """Walk skill matches and bind any external_cli.command back to the
    capability whose ``requires.commands[]`` includes that command.

    Returns ``capability_id → [skill_name, …]`` for attribution. Skipping
    matches without external_cli (internal skills) is fine — those have no
    capability binding by construction.
    """

    if applicability_report is None:
        return {}
    matches = getattr(applicability_report, "matches", None) or []
    bindings: dict[str, list[str]] = {}
    for match in matches:
        ext = getattr(match, "external_cli", None)
        if ext is None:
            continue
        command = getattr(ext, "command", None)
        if not command:
            continue
        for manifest in capability_index.all:
            if command in manifest.requires.commands:
                bindings.setdefault(manifest.id, []).append(getattr(match, "skill_name", ""))
    return bindings


def infer_advisory_capabilities(
    *,
    surfaces: list[str],
    external_refs: list[dict[str, Any]],
    applicability_report: Any | None,
    capability_index: CapabilityIndex,
    status_data: dict[str, dict[str, Any]] | None = None,
    resolver: AdapterResolver | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pure inference: compute F005 ``matches[]`` + ``skips[]`` arrays.

    Sources, in precedence order when a capability is bound by more than
    one (single-valued ``source`` field per F005 spec):

      1. ``external_ref`` — an external_ref carries an explicit capability_id
         or the URI scheme resolves through an adapter whose record declares
         capability_id.
      2. ``skill``        — a matched skill's ``external_cli.command`` is one
         of a capability manifest's ``requires.commands[]``.
      3. ``surface``      — plan surface name is in the small hint table.

    Skips[] records capability ids that were referenced (e.g. via an
    external_ref with explicit capability_id) but for which no manifest is
    registered — useful diagnostic without blocking lock.
    """

    status_data = status_data or {}

    # 1. external_ref bindings (explicit + resolver-derived).
    ref_bindings = _collect_external_ref_capability_ids(external_refs, resolver)

    # 2. skill bindings via external_cli.command → manifest.requires.commands.
    skill_bindings = _skill_applicability_capability_hints(applicability_report, capability_index)

    # 3. surface bindings via the static hint table.
    surface_bindings: dict[str, list[str]] = {}
    for surface in surfaces:
        for cap_id in _SURFACE_CAPABILITY_HINTS.get(surface, ()):
            surface_bindings.setdefault(cap_id, []).append(surface)

    # Precedence resolution. Same capability bound by multiple sources →
    # external_ref wins (explicit cite), then skill, then surface. Sources
    # are intentionally single-valued per F005 spec — a separate per-entry
    # ``contributing_sources[]`` array would over-spec the v0 contract.
    matches: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add_match(cap_id: str, source: str, attribution: list[str] | None) -> None:
        if cap_id in seen:
            return
        seen.add(cap_id)
        manifest = capability_index.get(cap_id)
        if manifest is None:
            skips.append(
                {
                    "capability_id": cap_id,
                    "reason": "no_manifest_match",
                    "source": source,
                }
            )
            return
        status = _f005_status_for(cap_id, manifest, status_data.get(cap_id), resolver)
        entry: dict[str, Any] = {
            "capability_id": cap_id,
            "source": source,
            "setup_required": manifest.setup_required,
            "setup_doc": manifest.setup_doc,
            "owner_boundary": {
                "dontpanic_core": list(manifest.owner_boundary.dontpanic_core),
                "adapter": list(manifest.owner_boundary.adapter),
                "operator": list(manifest.owner_boundary.operator),
            },
            "status": status,
        }
        if source == "external_ref" and attribution:
            entry["external_ref_uris"] = list(attribution)
        elif source == "skill" and attribution:
            entry["skill_names"] = list(attribution)
        elif source == "surface" and attribution:
            entry["surface_names"] = list(attribution)
        matches.append(entry)

    for cap_id, uris in ref_bindings.items():
        _add_match(cap_id, "external_ref", uris)
    for cap_id, skill_names in skill_bindings.items():
        _add_match(cap_id, "skill", skill_names)
    for cap_id, surface_names in surface_bindings.items():
        _add_match(cap_id, "surface", surface_names)

    matches.sort(key=lambda e: e["capability_id"])
    skips.sort(key=lambda e: e["capability_id"])
    return matches, skips


__all__ = [
    "RequiresCapabilityUnknownError",
    "SCHEMA_VERSION",
    "SIDECAR_RELPATH",
    "count_unready_capabilities",
    "emit_required_capabilities",
    "infer_advisory_capabilities",
    "read_external_refs",
    "read_requires_capabilities",
    "validate_requires_capabilities",
]
