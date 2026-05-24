"""Plan 2026-05-23-004 F001 — Operator console v0 ActionItem provider model.

The dashboard / future MCP / agents all need the same answer to one
question: *what needs action now?* This module is the single source of
truth for that answer.

Two contracts live here:

1. The :class:`Band` taxonomy. Subsystems use private vocabularies
   (capability status has its own enum, reconcile has its own status
   strings, gates have their own kinds). The dashboard cannot keep
   reasoning about all of those at once, so this module collapses them
   into four bands:

   * ``needs_action`` — operator must do something before progress
     continues (an unmet gate, a blocked capability, a missing or
     drifted reconcile baseline, a verdict mismatch).
   * ``advisory``    — should be looked at soon, but does not block
     work (architecture map is stale, a status cache predates the
     latest snapshot, a not-installed optional adapter the operator
     hasn't opted into).
   * ``info``        — situational awareness only (an active
     supervisor for the same plan, a baseline that is currently
     clean but worth surfacing).
   * ``ready``       — reserved for surfaces that want to render a
     positive confirmation. V0 providers emit ``ready`` items
     rarely; the dashboard's quiet state is "no needs_action items"
     rather than "lots of ready items".

   The four-band vocabulary is the **only** status language the V0
   provider output uses. Consumers branch on band; subsystem-specific
   strings live inside ``detail`` for human reading.

2. The :class:`ActionItem` envelope. Every provider emits the same
   shape so dashboard, cache writer, and agents can iterate uniformly.

   Fields:
     * ``id``                  — stable, source-prefixed identifier
                                 (e.g. ``gate:<plan_id>:<gate_name>``).
                                 Agents key off this for dedup; the same
                                 underlying state must always produce the
                                 same id.
     * ``source``              — provenance: ``gate`` / ``capability`` /
                                 ``reconcile`` / ``supervisor`` /
                                 ``architecture``. Lets consumers filter
                                 without parsing ``id``.
     * ``band``                — the four-band taxonomy entry.
     * ``title``               — one-line operator-readable headline.
     * ``detail``              — longer description, may be ``None``.
     * ``exact_command``       — copy-pasteable shell command the
                                 operator/agent should run next, or
                                 ``None`` when no exact command applies.
     * ``automatable``         — ``True`` iff a script/agent can run the
                                 command without human judgement.
     * ``human_required_reason`` — why human action is required (e.g.
                                 ``"gate approval"``), ``None`` when
                                 ``automatable=True``.
     * ``evidence_uri``        — pointer to a file/dir/URL with the
                                 underlying state (e.g. plan dir,
                                 ``capabilities-status.json``,
                                 install snapshot). Never inline content.
     * ``updated_at``          — ISO-8601 UTC timestamp the provider
                                 observed this state.

Providers are pure functions:
  * They take already-loaded subsystem state as input.
  * They mutate nothing.
  * They emit a deterministically-ordered tuple of ActionItems.
  * They never embed secrets; the :func:`_assert_no_secret_shapes`
    invariant runs against every rendered envelope.

The cache writer at :func:`write_cache` lands the JSON envelope at
``~/.dontpanic/dashboard/what-now.json`` so headless consumers
(dashboard build, agents, MCP) can read it without re-running every
provider themselves.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import os
import re
import stat
from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import global_config as _gc

# Bind to the existing sanitization regexes so the no-secret invariant
# matches the OSS sanitization gate. Imported lazily so test isolation
# does not need to load the whole scripts dir when only ActionItem
# helpers are exercised.
_SECRET_REGEXES: tuple[re.Pattern[str], ...] | None = None


def _load_secret_regexes() -> tuple[re.Pattern[str], ...]:
    global _SECRET_REGEXES
    if _SECRET_REGEXES is not None:
        return _SECRET_REGEXES
    import sys as _sys

    scripts_dir = Path(__file__).resolve().parent.parent
    if str(scripts_dir) not in _sys.path:
        _sys.path.insert(0, str(scripts_dir))
    from sanitization_check import SECRET_REGEXES as _RX  # noqa: E402

    _SECRET_REGEXES = tuple(_RX)
    return _SECRET_REGEXES


SCHEMA_VERSION = "1.0.0"
CACHE_FILENAME = "what-now.json"
CACHE_SUBDIR = "dashboard"
CACHE_FILE_MODE = 0o600

# Plan 2026-05-24-004 F003 (D003) — sidecar file for event-derived ActionItems.
# Per-line JSON for append-safety; one ActionItem-shaped dict per line.
EVENT_SIDECAR_FILENAME = "event-actions.jsonl"


class Band(str, Enum):
    """The four-band taxonomy. Stable; consumers branch on these values.

    Ordering reflects display priority: ``needs_action`` always renders
    first, ``info`` and ``ready`` last. The numeric :data:`_BAND_PRIORITY`
    map keeps sort order in lockstep with declaration order.
    """

    NEEDS_ACTION = "needs_action"
    ADVISORY = "advisory"
    INFO = "info"
    READY = "ready"


_BAND_PRIORITY: dict[Band, int] = {
    Band.NEEDS_ACTION: 0,
    Band.ADVISORY: 1,
    Band.INFO: 2,
    Band.READY: 3,
}


# Stable source vocabulary. ``id`` strings are prefixed with one of these.
SOURCE_GATE = "gate"
SOURCE_CAPABILITY = "capability"
SOURCE_RECONCILE = "reconcile"
SOURCE_SUPERVISOR = "supervisor"
SOURCE_ARCHITECTURE = "architecture"

_VALID_SOURCES: frozenset[str] = frozenset(
    {
        SOURCE_GATE,
        SOURCE_CAPABILITY,
        SOURCE_RECONCILE,
        SOURCE_SUPERVISOR,
        SOURCE_ARCHITECTURE,
    }
)

_SOURCE_PRIORITY: dict[str, int] = {
    SOURCE_GATE: 0,
    SOURCE_RECONCILE: 1,
    SOURCE_CAPABILITY: 2,
    SOURCE_SUPERVISOR: 3,
    SOURCE_ARCHITECTURE: 4,
}


@dataclasses.dataclass(frozen=True)
class ActionItem:
    """One operator-facing item the dashboard / agents render.

    Construct via the provider functions in this module rather than
    instantiating directly outside tests — providers enforce the
    id-prefix convention and supply ``updated_at`` from a single
    captured-at clock so a snapshot is internally consistent.

    Plan 2026-05-23-005 F004 added the optional ``project_name`` /
    ``display_name`` fields. They are populated only when the item
    comes from a project-scoped source (per-project gates, architecture,
    build warnings) so the fleet view can group items by project and
    the project filter can short-circuit relevance via string equality.
    Legacy single-repo callers leave them as None — the dashboard's
    relevance function treats unscoped items as belonging to the
    selected project (V0 single-repo compat).
    """

    id: str
    source: str
    band: Band
    title: str
    detail: str | None
    exact_command: str | None
    automatable: bool
    human_required_reason: str | None
    evidence_uri: str | None
    updated_at: str
    project_name: str | None = None
    display_name: str | None = None

    def __post_init__(self) -> None:
        if self.source not in _VALID_SOURCES:
            raise ValueError(
                f"ActionItem.source={self.source!r} not in {sorted(_VALID_SOURCES)}"
            )
        if not isinstance(self.band, Band):
            raise TypeError(
                f"ActionItem.band must be Band, got {type(self.band).__name__}"
            )
        if self.automatable and self.human_required_reason is not None:
            raise ValueError(
                "ActionItem.human_required_reason must be None when automatable=True"
            )
        if not self.automatable and not self.human_required_reason:
            raise ValueError(
                "ActionItem.human_required_reason is required when automatable=False"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "band": self.band.value,
            "title": self.title,
            "detail": self.detail,
            "exact_command": self.exact_command,
            "automatable": self.automatable,
            "human_required_reason": self.human_required_reason,
            "evidence_uri": self.evidence_uri,
            "updated_at": self.updated_at,
            "project_name": self.project_name,
            "display_name": self.display_name,
        }


def _now_iso(now: _dt.datetime | None = None) -> str:
    ts = now or _dt.datetime.now(_dt.timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── providers ────────────────────────────────────────────────────────────


def provide_gate_actions(
    gates: Sequence[Any],
    *,
    now: _dt.datetime | None = None,
    plan_dirs: dict[str, Path] | None = None,
) -> tuple[ActionItem, ...]:
    """Map :class:`state_snapshot_model.GateEntry`-shaped entries into
    ActionItems.

    Every unmet gate is ``needs_action`` — gate-paused dispatch cannot
    proceed without operator intervention by definition. The exact
    command is ``dontpanic approve <plan_id> <gate>`` regardless of gate
    kind so the operator does not have to remember the breaker/defer
    nuance the supervisor cares about internally.
    """

    updated_at = _now_iso(now)
    items: list[ActionItem] = []
    for entry in gates:
        plan_id = _attr(entry, "plan_id")
        gate_name = _attr(entry, "gate_name")
        if plan_id is None or gate_name is None:
            continue
        reason = _attr(entry, "reason")
        evidence_uri = None
        if plan_dirs and plan_id in plan_dirs:
            evidence_uri = str(plan_dirs[plan_id] / "audit" / "gate-state.json")
        title = f"Gate {gate_name} on {plan_id} needs approval"
        detail_parts: list[str] = []
        if reason:
            detail_parts.append(str(reason))
        kind = _attr(entry, "kind")
        if kind is not None:
            kind_val = kind.value if hasattr(kind, "value") else str(kind)
            detail_parts.append(f"kind={kind_val}")
        detail = "; ".join(detail_parts) or None
        command = f"dontpanic approve {plan_id} {gate_name}"
        items.append(
            ActionItem(
                id=f"{SOURCE_GATE}:{plan_id}:{gate_name}",
                source=SOURCE_GATE,
                band=Band.NEEDS_ACTION,
                title=title,
                detail=detail,
                exact_command=command,
                automatable=False,
                human_required_reason="gate approval",
                evidence_uri=evidence_uri,
                updated_at=updated_at,
            )
        )
    return _sort(items)


def provide_capability_actions(
    envelope: Any | None,
    *,
    now: _dt.datetime | None = None,
    cache_path: Path | None = None,
) -> tuple[ActionItem, ...]:
    """Map a ``capabilities_status.StatusEnvelope`` (or its dict form)
    into ActionItems.

    Band mapping:
      * ``blocked``       → ``needs_action``  (probe failed; pipeline broken)
      * ``needs_setup``   → ``needs_action``  (requires resolution; operator
                                                must complete setup)
      * ``not_installed`` → ``advisory``      (operator hasn't opted into the
                                                adapter; not urgent)
      * ``optional``      → skip              (out-of-profile; noise the
                                                operator did not ask for)
      * ``ready``         → skip              (quiet state)

    An ``envelope`` of ``None`` is the legitimate "no cache yet" case and
    yields an empty tuple; the reconcile provider surfaces stale/missing
    cache separately so we do not double-emit here.
    """

    if envelope is None:
        return ()

    updated_at = _now_iso(now)
    caps = _attr(envelope, "capabilities") or []
    if isinstance(envelope, dict):
        caps = envelope.get("capabilities", [])

    items: list[ActionItem] = []
    for cap in caps:
        cap_id = _attr(cap, "capability_id") or (
            cap.get("capability_id") if isinstance(cap, dict) else None
        )
        status = _attr(cap, "status") or (
            cap.get("status") if isinstance(cap, dict) else None
        )
        if cap_id is None or status is None:
            continue
        status_val = status.value if hasattr(status, "value") else str(status)

        if status_val in ("ready", "optional"):
            continue

        if status_val == "blocked":
            band = Band.NEEDS_ACTION
            title = f"Capability {cap_id} is blocked"
            reason = "capability probe failed"
        elif status_val == "needs_setup":
            band = Band.NEEDS_ACTION
            title = f"Capability {cap_id} needs setup"
            reason = "capability setup incomplete"
        elif status_val == "not_installed":
            band = Band.ADVISORY
            title = f"Capability {cap_id} is not installed"
            reason = "adapter not registered"
        else:
            continue

        missing = _attr(cap, "missing") or (
            cap.get("missing") if isinstance(cap, dict) else ()
        )
        detail = None
        if missing:
            detail = "missing: " + ", ".join(str(m) for m in missing)

        evidence_uri = str(cache_path) if cache_path is not None else None

        items.append(
            ActionItem(
                id=f"{SOURCE_CAPABILITY}:{cap_id}",
                source=SOURCE_CAPABILITY,
                band=band,
                title=title,
                detail=detail,
                exact_command=f"dontpanic capabilities status {cap_id}",
                automatable=False,
                human_required_reason=reason,
                evidence_uri=evidence_uri,
                updated_at=updated_at,
            )
        )
    return _sort(items)


def provide_reconcile_actions(
    check_result: Any | None,
    *,
    now: _dt.datetime | None = None,
) -> tuple[ActionItem, ...]:
    """Map a ``reconcile.CapabilityCheckResult`` (or its dict form) into
    ActionItems.

    Band mapping:
      * ``missing_snapshot``       → ``advisory``    (no baseline yet — operator
                                                       has to run baseline before
                                                       drift detection is meaningful)
      * ``new_capabilities``       → ``needs_action``
      * ``removed_capabilities``   → ``needs_action``
      * ``changed_capabilities``   → ``needs_action``
      * ``stale_status_cache``     → ``advisory``
      * ``clean`` / ``None``       → no emit

    One ActionItem per drift kind, not per affected capability — the V0
    dashboard wants a compact "what to fix" list, not a long enumeration.
    """

    if check_result is None:
        return ()

    status = _attr(check_result, "status") or (
        check_result.get("status") if isinstance(check_result, dict) else None
    )
    if status in (None, "clean"):
        return ()

    drift_kinds_raw = _attr(check_result, "drift_kinds")
    if not drift_kinds_raw and isinstance(check_result, dict):
        drift_kinds_raw = check_result.get("drift_kinds")
    # Fall back to (status,) so callers that only set status still emit
    # exactly one item rather than silently swallowing the drift.
    drift_kinds = tuple(drift_kinds_raw) if drift_kinds_raw else (status,)

    snapshot_path = _attr(check_result, "snapshot_path") or (
        check_result.get("snapshot_path") if isinstance(check_result, dict) else None
    )
    next_commands = _attr(check_result, "next_commands") or (
        check_result.get("next_commands") if isinstance(check_result, dict) else ()
    )

    updated_at = _now_iso(now)
    items: list[ActionItem] = []
    for kind in drift_kinds:
        kind_str = str(kind)
        if kind_str == "missing_snapshot":
            band = Band.ADVISORY
            title = "Install snapshot is missing"
            command = "dontpanic reconcile baseline --yes"
            reason = "no baseline to compare against"
        elif kind_str == "new_capabilities":
            band = Band.NEEDS_ACTION
            title = "Reconcile drift: new capabilities since baseline"
            command = "dontpanic reconcile baseline --yes"
            reason = "capability set diverged from baseline"
        elif kind_str == "removed_capabilities":
            band = Band.NEEDS_ACTION
            title = "Reconcile drift: capabilities removed since baseline"
            command = "dontpanic reconcile baseline --yes"
            reason = "capability set diverged from baseline"
        elif kind_str == "changed_capabilities":
            band = Band.NEEDS_ACTION
            title = "Reconcile drift: capability manifests changed since baseline"
            command = "dontpanic reconcile baseline --yes"
            reason = "capability set diverged from baseline"
        elif kind_str == "stale_status_cache":
            band = Band.ADVISORY
            title = "Capability status cache is stale relative to install snapshot"
            command = "dontpanic capabilities status"
            reason = "status cache predates baseline"
        else:
            # Unknown drift kind from a future schema. Surface it as
            # advisory rather than silently dropping; consumers can branch
            # on ``id`` prefix.
            band = Band.ADVISORY
            title = f"Reconcile drift: {kind_str}"
            command = next_commands[0] if next_commands else None
            reason = "unrecognized drift kind"

        items.append(
            ActionItem(
                id=f"{SOURCE_RECONCILE}:{kind_str}",
                source=SOURCE_RECONCILE,
                band=band,
                title=title,
                detail=None,
                exact_command=command,
                automatable=False,
                human_required_reason=reason,
                evidence_uri=str(snapshot_path) if snapshot_path else None,
                updated_at=updated_at,
            )
        )
    return _sort(items)


def provide_supervisor_actions(
    supervisors: Sequence[Any],
    *,
    now: _dt.datetime | None = None,
) -> tuple[ActionItem, ...]:
    """Surface active supervisors. V0 emits each as ``info`` — an active
    supervisor is not an error, but the operator should know one is
    running before they kick off a parallel volley.

    Stuck/zombie detection is a V1 concern. V0 trusts the registry: any
    entry returned by ``active_supervisors.list_active`` (which already
    prunes dead PIDs) is reported as a live supervisor.
    """

    updated_at = _now_iso(now)
    items: list[ActionItem] = []
    for entry in supervisors:
        plan_id = _attr(entry, "plan_id")
        pid = _attr(entry, "pid")
        if plan_id is None or pid is None:
            continue
        started_at = _attr(entry, "started_at")
        target_env = _attr(entry, "target_env")
        detail_parts = []
        if started_at:
            detail_parts.append(f"started_at={started_at}")
        if target_env:
            detail_parts.append(f"env={target_env}")
        detail = ", ".join(detail_parts) or None
        items.append(
            ActionItem(
                id=f"{SOURCE_SUPERVISOR}:{pid}:{plan_id}",
                source=SOURCE_SUPERVISOR,
                band=Band.INFO,
                title=f"Supervisor active on {plan_id}",
                detail=detail,
                exact_command="dontpanic ps",
                automatable=True,
                human_required_reason=None,
                evidence_uri=None,
                updated_at=updated_at,
            )
        )
    return _sort(items)


def provide_architecture_actions(
    arch_status: dict[str, Any] | None,
    *,
    now: _dt.datetime | None = None,
) -> tuple[ActionItem, ...]:
    """Map the dict returned by ``architecture.status()`` into an
    ActionItem. V0 surfaces stale/absent state as advisory (operator
    should regen) but never blocks dispatch on it.
    """

    if arch_status is None:
        return ()
    state = arch_status.get("state")
    if state not in ("stale", "absent"):
        return ()
    updated_at = _now_iso(now)
    output_path = arch_status.get("output_path")
    if state == "absent":
        title = "Architecture snapshot is missing"
    else:
        title = "Architecture snapshot is stale"
    return (
        ActionItem(
            id=f"{SOURCE_ARCHITECTURE}:{state}",
            source=SOURCE_ARCHITECTURE,
            band=Band.ADVISORY,
            title=title,
            detail=None,
            exact_command="dontpanic architecture regen",
            automatable=True,
            human_required_reason=None,
            evidence_uri=str(output_path) if output_path else None,
            updated_at=updated_at,
        ),
    )


# ── aggregation + ordering ───────────────────────────────────────────────


def aggregate(*provider_outputs: Iterable[ActionItem]) -> tuple[ActionItem, ...]:
    """Merge ActionItems from multiple providers and apply deterministic
    ordering. Duplicate ids are coalesced — last writer wins so a
    caller that wants to override a provider entry can do so by passing
    its tuple after the original.
    """

    merged: dict[str, ActionItem] = {}
    for outputs in provider_outputs:
        for item in outputs:
            merged[item.id] = item
    return _sort(merged.values())


def _sort(items: Iterable[ActionItem]) -> tuple[ActionItem, ...]:
    """Deterministic sort: band priority, then source priority, then id.

    Same input always yields byte-identical output — necessary for the
    cache JSON to be stable across reruns when no source state changed.
    """

    def key(item: ActionItem) -> tuple[int, int, str]:
        return (
            _BAND_PRIORITY.get(item.band, 99),
            _SOURCE_PRIORITY.get(item.source, 99),
            item.id,
        )

    return tuple(sorted(items, key=key))


# ── render + cache ──────────────────────────────────────────────────────


def _attr(obj: Any, name: str) -> Any:
    """Best-effort field access — works on dataclasses, Pydantic models,
    and plain dicts. Returns None when the attribute / key is absent."""

    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def render_envelope(
    items: Sequence[ActionItem],
    *,
    captured_at: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Return the cache JSON envelope as a plain dict.

    Schema is intentionally compact:

      {
        "schema_version": "1.0.0",
        "captured_at":    "<iso>",
        "items":          [<ActionItem.to_dict()>, ...]
      }

    No subsystem-specific fields leak in here — agents bind to this
    shape and the four-band taxonomy, not to gate-kind enums or
    capability status strings.
    """

    captured = _now_iso(captured_at)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured,
        "items": [it.to_dict() for it in items],
    }
    _assert_no_secret_shapes(payload)
    return payload


def render_json(items: Sequence[ActionItem], *, captured_at: _dt.datetime | None = None) -> str:
    payload = render_envelope(items, captured_at=captured_at)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def default_cache_path() -> Path:
    """``<dontpanic_home>/dashboard/what-now.json``.

    Honors ``$DONTPANIC_HOME`` / ``$JARVIS_HOME`` via
    :func:`global_config.dontpanic_home`, so tests + the conftest
    isolation fixture both redirect cleanly.
    """

    return _gc.dontpanic_home() / CACHE_SUBDIR / CACHE_FILENAME


def default_event_sidecar_path() -> Path:
    """``<dontpanic_home>/dashboard/event-actions.jsonl``.

    Plan 2026-05-24-004 F003 (D003) — sidecar file the event_copy renderer
    appends to via :func:`write_event_action_sidecar`. The dashboard build
    (and write_cache) merge the sidecar into the served what-now via
    :func:`merge_with_event_sidecar`.
    """

    return _gc.dontpanic_home() / CACHE_SUBDIR / EVENT_SIDECAR_FILENAME


def _rendered_to_action_item_dict(
    rendered: Any,
    *,
    source: str,
    updated_at: str,
) -> dict[str, Any]:
    """Project a :class:`event_copy.RenderedEvent` into ActionItem-dict shape.

    Used for the sidecar JSONL file so that `merge_with_event_sidecar` can
    rehydrate the entry into an ActionItem alongside provider-derived items.

    Per D003 the sidecar carries ActionItem-shaped entries, NOT raw
    NotifyEvent payloads — agents consuming what-now.json should see one
    uniform contract regardless of provenance.

    Per plan.md § Implementation Strategy this projection is dispatch-driven
    (notification flow), so the resulting items are:
      - automatable=False (operator action), with human_required_reason
        derived from the band (needs_action items need approval/remediation;
        advisory/info/ready never reach the sidecar — those dispositions
        skip rendering).
      - id prefixed with ``supervisor:`` per the existing source vocabulary
        + the inbox_event so the dashboard dedupes against re-fires of the
        same event for the same plan/feature.
    """
    plan_id = ""
    feature_id: str | None = None
    inbox_event = ""
    tech = getattr(rendered, "technical_metadata", None) or {}
    if isinstance(tech, Mapping):
        plan_id = tech.get("plan_id", "") or ""
        feature_id = tech.get("feature_id") or None
        inbox_event = tech.get("inbox_event", "") or ""
    band_value = getattr(rendered, "band", None) or "advisory"
    item_id_parts = [SOURCE_SUPERVISOR, inbox_event or "event"]
    if plan_id:
        item_id_parts.append(plan_id)
    if feature_id:
        item_id_parts.append(feature_id)
    item_id = ":".join(item_id_parts)

    human_reason: str | None
    if band_value == "ready":
        # ready band wouldn't normally reach the sidecar (renderer would
        # return None for inbox_only/audit_only and live ready items don't
        # demand human action) but stay defensive.
        automatable = True
        human_reason = None
    else:
        automatable = False
        human_reason = "operator action surfaced by dispatch_event"

    return {
        "id": item_id,
        "source": source,
        "band": band_value,
        "title": getattr(rendered, "title", "") or "(rendered event)",
        "detail": getattr(rendered, "detail", None),
        "exact_command": getattr(rendered, "exact_command", None),
        "automatable": automatable,
        "human_required_reason": human_reason,
        "evidence_uri": getattr(rendered, "evidence_uri", None),
        "updated_at": updated_at,
        "project_name": tech.get("target_project") if isinstance(tech, Mapping) else None,
        "display_name": None,
    }


def write_event_action_sidecar(
    rendered: Any,
    *,
    source: str = SOURCE_SUPERVISOR,
    path: Path | None = None,
    captured_at: _dt.datetime | None = None,
) -> Path | None:
    """Plan 2026-05-24-004 F003 (D003) — append a sidecar ActionItem entry.

    The sidecar is per-line JSON (JSONL) so the writer can append safely
    without locking the whole what-now.json. The dashboard build / write_cache
    call :func:`merge_with_event_sidecar` to fold the sidecar entries into
    the served ActionItem list.

    Returns the sidecar path, or None when ``rendered`` is None (no-op).
    Never raises — sidecar write is best-effort; failure to write must not
    crash the dispatch loop.
    """
    if rendered is None:
        return None

    target = path if path is not None else default_event_sidecar_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass

    entry = _rendered_to_action_item_dict(
        rendered,
        source=source,
        updated_at=_now_iso(captured_at),
    )
    # Per D011 + F004: the sidecar write is the raise-mode boundary for
    # secret-shape leaks. F004 wires _assert_no_secret_shapes here as part
    # of its sanitization sweep. F003 just appends the entry.
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
    with target.open("a", encoding="utf-8") as f:
        f.write(line)
    try:
        os.chmod(target, CACHE_FILE_MODE)
    except OSError:
        pass
    return target


def _action_item_from_sidecar_dict(entry: Mapping[str, Any]) -> ActionItem | None:
    """Best-effort rehydrate of a sidecar entry into an ActionItem.

    Returns None when fields are malformed — sidecar entries are advisory
    and a malformed line must not crash the merge path.
    """
    try:
        band_str = entry.get("band") or "advisory"
        band = Band(band_str)
        return ActionItem(
            id=entry["id"],
            source=entry.get("source") or SOURCE_SUPERVISOR,
            band=band,
            title=entry.get("title") or "(event)",
            detail=entry.get("detail"),
            exact_command=entry.get("exact_command"),
            automatable=bool(entry.get("automatable", False)),
            human_required_reason=entry.get("human_required_reason"),
            evidence_uri=entry.get("evidence_uri"),
            updated_at=entry.get("updated_at") or _now_iso(),
            project_name=entry.get("project_name"),
            display_name=entry.get("display_name"),
        )
    except (KeyError, ValueError, TypeError):
        return None


def merge_with_event_sidecar(
    provider_items: Sequence[ActionItem] | Iterable[ActionItem],
    *,
    sidecar_path: Path | None = None,
) -> tuple[ActionItem, ...]:
    """Plan 2026-05-24-004 F003 (D003 + D019) — merge sidecar entries.

    Reads the event-actions sidecar (JSONL) and returns a deduplicated,
    sorted tuple combining ``provider_items`` with sidecar-derived items.
    Provider-derived items WIN on id conflicts — the sidecar is advisory.

    Called from BOTH dashboard.build() (before render_json writes the
    out_dir copy of what-now.json) AND operator_console.write_cache()
    (before writing the home dashboard cache) per D019; either site
    skipping the merge would leave the served dashboard state stale.
    """
    target = sidecar_path if sidecar_path is not None else default_event_sidecar_path()
    provider_list = list(provider_items)
    provider_ids = {item.id for item in provider_list}
    if not target.is_file():
        return _sort(provider_list)
    sidecar_items: list[ActionItem] = []
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return _sort(provider_list)
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        item = _action_item_from_sidecar_dict(entry)
        if item is None:
            continue
        if item.id in provider_ids:
            # Provider items win on conflict — sidecar is advisory.
            continue
        # Dedupe within the sidecar itself (re-fires of the same event
        # append additional lines; keep the most recent).
        sidecar_items = [si for si in sidecar_items if si.id != item.id]
        sidecar_items.append(item)
    return _sort(provider_list + sidecar_items)


def write_cache(
    items: Sequence[ActionItem],
    *,
    path: Path | None = None,
    captured_at: _dt.datetime | None = None,
    merge_event_sidecar: bool = True,
) -> Path:
    """Write the JSON envelope to the operator-local cache file (mode
    0o600, parent dir 0o700). Returns the path written.

    Plan 2026-05-24-004 F003 (D003 + D019): merges event-actions.jsonl
    sidecar into the provider-derived items by default. Pass
    ``merge_event_sidecar=False`` for tests that need to assert pure
    provider output.
    """

    target = path if path is not None else default_cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    final_items: Sequence[ActionItem]
    if merge_event_sidecar:
        final_items = merge_with_event_sidecar(items)
    else:
        final_items = items
    payload = render_json(final_items, captured_at=captured_at)
    target.write_text(payload, encoding="utf-8")
    os.chmod(target, CACHE_FILE_MODE)
    mode_bits = stat.S_IMODE(target.stat().st_mode)
    if mode_bits != CACHE_FILE_MODE:
        os.chmod(target, CACHE_FILE_MODE)
    return target


# ── no-secret invariant ─────────────────────────────────────────────────


def _assert_no_secret_shapes(payload: dict[str, Any]) -> None:
    """Walk every string in the rendered envelope and assert no
    well-known secret pattern appears. The dashboard cache is operator-
    local but still gets read by agents that may upload it as evidence;
    catching shape regressions here is cheaper than catching them later
    in the OSS sanitization gate.
    """

    regexes = _load_secret_regexes()
    for path, value in _walk_strings(payload, ()):
        for rx in regexes:
            if rx.search(value):
                joined = ".".join(str(p) for p in path) or "<root>"
                raise ValueError(
                    f"operator_console cache field {joined!r} matched secret pattern "
                    f"{rx.pattern!r}; refusing to emit"
                )


def _walk_strings(node: Any, path: tuple[Any, ...]):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, path + (k,))
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            yield from _walk_strings(v, path + (i,))
    elif isinstance(node, str):
        yield path, node
    # ints/bools/None — no string content to scan.


__all__ = [
    "ActionItem",
    "Band",
    "CACHE_FILENAME",
    "CACHE_FILE_MODE",
    "CACHE_SUBDIR",
    "EVENT_SIDECAR_FILENAME",
    "SCHEMA_VERSION",
    "SOURCE_ARCHITECTURE",
    "SOURCE_CAPABILITY",
    "SOURCE_GATE",
    "SOURCE_RECONCILE",
    "SOURCE_SUPERVISOR",
    "aggregate",
    "default_cache_path",
    "default_event_sidecar_path",
    "merge_with_event_sidecar",
    "provide_architecture_actions",
    "provide_capability_actions",
    "provide_gate_actions",
    "provide_reconcile_actions",
    "provide_supervisor_actions",
    "render_envelope",
    "render_json",
    "write_cache",
    "write_event_action_sidecar",
]
