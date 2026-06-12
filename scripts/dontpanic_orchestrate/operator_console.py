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
from dontpanic_orchestrate.action_resolvability import (
    RESOLUTION_BLOCKED_EXTERNAL,
    RESOLUTION_CHAINED,
    RESOLUTION_COMMAND_RESOLVABLE,
    RESOLUTION_OPERATOR_ATTESTED,
    ClearsWhen,
    validate_resolution_class,
)

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


# Stable, CLOSED source vocabulary (CP-D002): ``source`` MUST be one of these.
# The ``id`` prefix is OPAQUE and is NOT constrained to this set — e.g. an
# operations-guidance item carries ``id`` prefix ``operations:`` while its
# ``source`` is ``supervisor`` by design. Identity/dedup authority is the
# producer-set ``dedupe_key``, never the id-prefix. Do not parse the id-prefix
# to infer source.
SOURCE_GATE = "gate"
SOURCE_CAPABILITY = "capability"
SOURCE_RECONCILE = "reconcile"
SOURCE_SUPERVISOR = "supervisor"
SOURCE_ARCHITECTURE = "architecture"
# Plan 2026-06-04-003 F001 — operator-owned integration steps (deploy /
# credentials / smokes) modelled as ActionItems, never executed in-repo.
SOURCE_INTEGRATION = "integration"

# Plan 2026-06-04-005 F004 — the lower-priority section uncertainty (demotion)
# cards render under: never Needs Action, always "Status could not be refreshed".
SECTION_STATUS_UNCERTAIN = "status_uncertain"

_VALID_SOURCES: frozenset[str] = frozenset(
    {
        SOURCE_GATE,
        SOURCE_CAPABILITY,
        SOURCE_RECONCILE,
        SOURCE_SUPERVISOR,
        SOURCE_ARCHITECTURE,
        SOURCE_INTEGRATION,
    }
)

_SOURCE_PRIORITY: dict[str, int] = {
    SOURCE_GATE: 0,
    SOURCE_RECONCILE: 1,
    SOURCE_CAPABILITY: 2,
    SOURCE_SUPERVISOR: 3,
    SOURCE_ARCHITECTURE: 4,
    SOURCE_INTEGRATION: 5,
}


# Plan 2026-06-02-001 F001 (CP-D001) — control-plane audience vocabulary.
# ``audience`` declares WHO an ActionItem is for. The four roles are
# independent capabilities, not a ranking: an item may target several at
# once (e.g. a gate approval is for the human operator). Closed set —
# adding a role is a deliberate edit, mirroring ``_VALID_SOURCES``.
AUDIENCE_OPERATOR = "operator"
AUDIENCE_WORKER = "worker"
AUDIENCE_ORCHESTRATOR = "orchestrator"
AUDIENCE_HUMAN = "human"

_VALID_AUDIENCES: frozenset[str] = frozenset(
    {
        AUDIENCE_OPERATOR,
        AUDIENCE_WORKER,
        AUDIENCE_ORCHESTRATOR,
        AUDIENCE_HUMAN,
    }
)


def _validate_exact_command_or_raise(exact_command: str, *, item_id: str) -> None:
    """Plan 2026-06-02-001 F001 (CP-D001) — boundary command validation.

    Enforce the honest-commands rule (D008) at the ActionItem construction
    boundary rather than only producer-side: any non-None ``exact_command``
    must pass :func:`command_validation.validate_command_tokens`. Producers
    that cannot determine a safe, validated command must emit
    ``exact_command=None`` (and explanation-only copy) instead of a broken
    copy-paste target.

    The invocation prefixes ``dontpanic`` / ``python -m dontpanic_orchestrate``
    are stripped before tokenizing, matching the renderer's contract
    (event_copy._validate_exact_command). Raises ``ValueError`` on failure.
    """
    import shlex

    from dontpanic_orchestrate import command_validation

    stripped = exact_command.strip()
    body = stripped
    for prefix in ("python -m dontpanic_orchestrate ", "dontpanic "):
        if body.startswith(prefix):
            body = body[len(prefix) :]
            break
    try:
        tokens = shlex.split(body)
    except ValueError as exc:
        raise ValueError(
            f"ActionItem id={item_id!r} exact_command {exact_command!r} is not "
            f"shell-parseable: {exc}"
        ) from exc
    result = command_validation.validate_command_tokens(tokens)
    if not result.ok:
        raise ValueError(
            f"ActionItem id={item_id!r} exact_command {exact_command!r} failed "
            f"command validation: {result.reason}"
        )


def _command_is_valid(exact_command: str) -> bool:
    """Non-raising form of :func:`_validate_exact_command_or_raise`.

    Producers use this to decide whether to emit a candidate command or fall
    back to ``None`` (honest-commands rule) BEFORE construction, so a future /
    unknown command shape never trips the boundary validator.
    """
    try:
        _validate_exact_command_or_raise(exact_command, item_id="<candidate>")
    except ValueError:
        return False
    return True


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
    # Plan 2026-06-02-001 F001 (CP-D001) — control-plane spine fields. Additive
    # over the durable F001 envelope so every surface (dashboard, CLI/JSON,
    # agent-brief) renders one contract.
    #   * ``audience``        — closed-set roles this item is FOR (see
    #                           :data:`_VALID_AUDIENCES`). Defaults to
    #                           ``(operator,)``; producers narrow/widen it.
    #   * ``dedupe_key``      — the producer-set identity authority used for
    #                           dedup (CP-D002). REQUIRED: construction rejects
    #                           an empty value rather than silently aliasing it
    #                           to ``id``, so "producer-set dedupe_key is the
    #                           identity authority" is enforced, not assumed. The
    #                           id-prefix is treated as opaque. Boundaries that
    #                           rehydrate persisted entries (sidecar / fleet
    #                           cache) supply ``entry["id"]`` as the explicit
    #                           fallback for pre-field data before constructing.
    #   * ``reversible``      — True iff taking the action is safe to undo /
    #                           re-run (read-only or idempotent). Conservative
    #                           default False.
    #   * ``plain_consequence`` — one plain-language line a non-technical human
    #                           can read for "what happens if I do this".
    #   * ``dashboard_url``   — pointer to the live dashboard view for this item,
    #                           populated at the render boundary (F003); None here.
    audience: tuple[str, ...] = (AUDIENCE_OPERATOR,)
    dedupe_key: str = ""
    reversible: bool = False
    plain_consequence: str | None = None
    dashboard_url: str | None = None
    # Plan 2026-06-04-001 F001 — resolvability contract. Additive over CP-D001 so
    # existing constructions keep working; emitters opt in, and F005's invariant
    # test is what enforces every emitter sets a registry predicate (or marks the
    # item operator_attested / blocked_external).
    #   * ``clears_when``      — reference into the closed predicate registry
    #                            (predicate name + bound params). None = "does not
    #                            declare a resolution predicate", so recompute
    #                            cannot suppress it (D002.1).
    #   * ``resolution_class`` — how the item resolves; one of the four
    #                            RESOLUTION_CLASSES (D002.3). Default
    #                            command_resolvable.
    clears_when: ClearsWhen | None = None
    resolution_class: str = RESOLUTION_COMMAND_RESOLVABLE
    # Plan 2026-06-04-005 F002 — explicit producer-asserted scope. Default None
    # means "unscoped legacy": scope_lattice.resolve_card_scope_state routes such
    # items through a LOGGED adapter and refuses to silently treat them as the
    # selected project's work. There is intentionally NO default that infers scope
    # from ``project_name``. New emitters set ``scope`` (one of Scope.*) explicitly;
    # ``plan_id`` / ``feature_id`` let plan/feature-scoped cards resolve to a project.
    scope: str | None = None
    plan_id: str | None = None
    feature_id: str | None = None
    # Plan 2026-06-04-005 F004 — render section. None = the default Needs Action /
    # advisory placement; SECTION_STATUS_UNCERTAIN marks an uncertainty card built
    # by build_uncertainty_card (a stale/failed source the gate demoted).
    section: str | None = None
    # Plan 2026-06-04-003 F001 — integration display fields. operator_command
    # is the honest-commands escape hatch: an EXTERNAL command rendered as
    # run-this-yourself copy that never passes the validated exact_command
    # boundary. credential_env_vars carries env-var NAMES only (presence is
    # display data; values are never read into item fields).
    operator_command: str | None = None
    credential_env_vars: tuple[str, ...] = ()
    evidence_expected: str | None = None
    trigger_condition: str | None = None

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
        # CP-D001 audience: must be a non-empty tuple of known roles.
        if not isinstance(self.audience, tuple):
            object.__setattr__(self, "audience", tuple(self.audience))
        if not self.audience:
            raise ValueError("ActionItem.audience must name at least one role")
        invalid = [a for a in self.audience if a not in _VALID_AUDIENCES]
        if invalid:
            raise ValueError(
                f"ActionItem.audience members {invalid!r} not in "
                f"{sorted(_VALID_AUDIENCES)}"
            )
        # CP-D002 dedupe_key: producer-set identity authority. REQUIRED — an
        # empty value is rejected rather than silently aliased to ``id``, so the
        # "producer-set dedupe_key is the identity authority" invariant is
        # enforced at the boundary. Dedup keys on this, never on parsing the
        # id-prefix. Rehydration boundaries (sidecar / fleet cache) pass
        # ``entry["id"]`` as the explicit fallback for pre-field persisted data.
        if not self.dedupe_key:
            raise ValueError(
                "ActionItem.dedupe_key is required and must be non-empty "
                "(producer-set identity authority); pass dedupe_key explicitly"
            )
        # CP-D001 boundary command validation (D008 honest-commands): a non-None
        # exact_command must pass token-shape validation. Producers that cannot
        # determine a safe command must emit None instead of a broken target.
        if self.exact_command is not None:
            _validate_exact_command_or_raise(self.exact_command, item_id=self.id)
        # F001 resolvability: resolution_class must be one of the four classes.
        validate_resolution_class(self.resolution_class)

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
            "audience": list(self.audience),
            "dedupe_key": self.dedupe_key,
            "reversible": self.reversible,
            "plain_consequence": self.plain_consequence,
            "dashboard_url": self.dashboard_url,
            "clears_when": self.clears_when.to_dict() if self.clears_when else None,
            "resolution_class": self.resolution_class,
            "operator_command": self.operator_command,
            "credential_env_vars": list(self.credential_env_vars),
            "evidence_expected": self.evidence_expected,
            "trigger_condition": self.trigger_condition,
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
        item_id = f"{SOURCE_GATE}:{plan_id}:{gate_name}"
        items.append(
            ActionItem(
                id=item_id,
                source=SOURCE_GATE,
                band=Band.NEEDS_ACTION,
                title=title,
                detail=detail,
                exact_command=command,
                automatable=False,
                human_required_reason="gate approval",
                evidence_uri=evidence_uri,
                updated_at=updated_at,
                audience=(AUDIENCE_OPERATOR, AUDIENCE_HUMAN),
                dedupe_key=item_id,
                reversible=False,
                plain_consequence=(
                    f"Approving lets dispatch continue past the {gate_name} gate."
                ),
                # F003 phantom suppression: a gate card is only honest while the
                # plan is live-but-unfinished AND the gate is still uncleared.
                # suppress_resolved (F002) drops it the moment the plan goes
                # completed/abandoned or the gate clears — so cards no longer
                # point at closed plans.
                clears_when=ClearsWhen(
                    "gate_no_longer_actionable",
                    {"plan_id": plan_id, "gate": gate_name},
                ),
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

        # F004: needs_setup / blocked require the operator to supply the missing
        # credential / setup — a read-only `capabilities status` does NOT resolve
        # them, so they are operator_attested and clear ONLY when a re-probe
        # reports the capability ready (clear on evidence, never on the command).
        # not_installed is an opt-in advisory and keeps the command_resolvable
        # default.
        cap_clears: ClearsWhen | None = None
        cap_class = RESOLUTION_COMMAND_RESOLVABLE
        if status_val == "blocked":
            band = Band.NEEDS_ACTION
            title = f"Capability {cap_id} is blocked"
            reason = "capability probe failed"
            cap_clears = ClearsWhen("capability_ready", {"capability_id": cap_id})
            cap_class = RESOLUTION_OPERATOR_ATTESTED
        elif status_val == "needs_setup":
            band = Band.NEEDS_ACTION
            title = f"Capability {cap_id} needs setup"
            reason = "capability setup incomplete"
            cap_clears = ClearsWhen("capability_ready", {"capability_id": cap_id})
            cap_class = RESOLUTION_OPERATOR_ATTESTED
        elif status_val == "not_installed":
            band = Band.ADVISORY
            title = f"Capability {cap_id} is not installed"
            reason = "adapter not registered"
        else:
            continue

        missing = _attr(cap, "missing") or (
            cap.get("missing") if isinstance(cap, dict) else ()
        )
        # Plan 2026-06-05-001 F002 — plain-language detail from the manifest's
        # setup steps (each carries a human-readable ``what`` + an optional
        # human_required_reason) instead of a raw ``missing: <token, …>`` blob.
        # Fall back to the missing summary only when no steps are available.
        steps = _attr(cap, "next_actions")
        if steps is None and isinstance(cap, dict):
            steps = cap.get("next_actions")
        step_parts: list[str] = []
        for s in steps or ():
            if isinstance(s, dict):
                what, human = s.get("what"), s.get("human_required_reason")
            else:
                what, human = _attr(s, "what"), _attr(s, "human_required_reason")
            if what:
                step_parts.append(f"{what} (needs you)" if human else str(what))
        detail: str | None = None
        if step_parts:
            detail = "Setup: " + "; ".join(step_parts)
        elif missing:
            detail = "missing: " + ", ".join(str(m) for m in missing)

        evidence_uri = str(cache_path) if cache_path is not None else None

        cap_item_id = f"{SOURCE_CAPABILITY}:{cap_id}"
        items.append(
            ActionItem(
                id=cap_item_id,
                source=SOURCE_CAPABILITY,
                band=band,
                title=title,
                detail=detail,
                # Plan 2026-06-05-001 F001 — surface the RESOLVING guidance
                # command, not the read-only `capabilities status` diagnostic
                # (which never resolves setup). `--print-steps` only PRINTS the
                # plan, so the consequence is guidance, not an auto-fix; the card
                # still clears on evidence (a later ready re-probe), never on this
                # command.
                exact_command=f"dontpanic capabilities setup {cap_id} --print-steps",
                automatable=False,
                human_required_reason=reason,
                evidence_uri=evidence_uri,
                updated_at=updated_at,
                audience=(AUDIENCE_OPERATOR, AUDIENCE_HUMAN),
                dedupe_key=cap_item_id,
                reversible=True,  # `capabilities setup --print-steps` is read-only
                plain_consequence=(
                    f"Prints the setup steps for {cap_id} so you can complete it."
                ),
                clears_when=cap_clears,
                resolution_class=cap_class,
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
    # F004: the global-readiness kinds (missing snapshot / stale cache) resolve
    # via the SAME composite predicate — snapshot present AND status cache fresh.
    # missing_snapshot is `chained` (running baseline is step 1; refreshing the
    # status cache is the surfaced next step), stale_status_cache is directly
    # command_resolvable (running `capabilities status` clears it). Drift kinds
    # (new/removed/changed) are command_resolvable and clear via reconcile_clean
    # on the rebuild after the operator re-baselines.
    _readiness_clears = ClearsWhen("install_snapshot_fresh")
    for kind in drift_kinds:
        kind_str = str(kind)
        recon_clears: ClearsWhen | None = None
        recon_class = RESOLUTION_COMMAND_RESOLVABLE
        if kind_str == "missing_snapshot":
            band = Band.ADVISORY
            title = "Install snapshot is missing"
            command = "dontpanic reconcile baseline --yes"
            reason = "no baseline to compare against"
            recon_clears = _readiness_clears
            recon_class = RESOLUTION_CHAINED
        elif kind_str == "new_capabilities":
            band = Band.NEEDS_ACTION
            title = "Reconcile drift: new capabilities since baseline"
            command = "dontpanic reconcile baseline --yes"
            reason = "capability set diverged from baseline"
            recon_clears = ClearsWhen("reconcile_clean")
        elif kind_str == "removed_capabilities":
            band = Band.NEEDS_ACTION
            title = "Reconcile drift: capabilities removed since baseline"
            command = "dontpanic reconcile baseline --yes"
            reason = "capability set diverged from baseline"
            recon_clears = ClearsWhen("reconcile_clean")
        elif kind_str == "changed_capabilities":
            band = Band.NEEDS_ACTION
            title = "Reconcile drift: capability manifests changed since baseline"
            command = "dontpanic reconcile baseline --yes"
            reason = "capability set diverged from baseline"
            recon_clears = ClearsWhen("reconcile_clean")
        elif kind_str == "stale_status_cache":
            band = Band.ADVISORY
            title = "Capability status cache is stale relative to install snapshot"
            command = "dontpanic capabilities status"
            reason = "status cache predates baseline"
            recon_clears = _readiness_clears
            recon_class = RESOLUTION_COMMAND_RESOLVABLE
        else:
            # Unknown drift kind from a future schema. Surface it as
            # advisory rather than silently dropping; consumers can branch
            # on ``id`` prefix.
            band = Band.ADVISORY
            title = f"Reconcile drift: {kind_str}"
            # CP-D001 honest-commands: a next_command from a future schema may
            # not validate against the closed CLI vocabulary. Drop it to None
            # rather than minting a broken copy-paste target that would also
            # trip the ActionItem boundary validator.
            command = None
            if next_commands and _command_is_valid(str(next_commands[0])):
                command = str(next_commands[0])
            reason = "unrecognized drift kind"

        recon_item_id = f"{SOURCE_RECONCILE}:{kind_str}"
        items.append(
            ActionItem(
                id=recon_item_id,
                source=SOURCE_RECONCILE,
                band=band,
                title=title,
                detail=None,
                exact_command=command,
                automatable=False,
                human_required_reason=reason,
                evidence_uri=str(snapshot_path) if snapshot_path else None,
                updated_at=updated_at,
                audience=(AUDIENCE_OPERATOR, AUDIENCE_HUMAN),
                dedupe_key=recon_item_id,
                reversible=False,
                plain_consequence=(
                    "Re-baselines the install snapshot so drift detection is "
                    "meaningful again."
                ),
                clears_when=recon_clears,
                resolution_class=recon_class,
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
        sup_item_id = f"{SOURCE_SUPERVISOR}:{pid}:{plan_id}"
        items.append(
            ActionItem(
                id=sup_item_id,
                source=SOURCE_SUPERVISOR,
                band=Band.INFO,
                title=f"Supervisor active on {plan_id}",
                detail=detail,
                exact_command="dontpanic ps",
                automatable=True,
                human_required_reason=None,
                evidence_uri=None,
                updated_at=updated_at,
                audience=(AUDIENCE_OPERATOR,),
                dedupe_key=sup_item_id,
                reversible=True,  # `ps` is read-only
                plain_consequence="Lists the running supervisor processes.",
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
    arch_item_id = f"{SOURCE_ARCHITECTURE}:{state}"
    return (
        ActionItem(
            id=arch_item_id,
            source=SOURCE_ARCHITECTURE,
            band=Band.ADVISORY,
            title=title,
            detail=None,
            exact_command="dontpanic architecture regen",
            automatable=True,
            human_required_reason=None,
            evidence_uri=str(output_path) if output_path else None,
            updated_at=updated_at,
            audience=(AUDIENCE_OPERATOR,),
            dedupe_key=arch_item_id,
            reversible=True,  # regen rebuilds a derived artifact; re-runnable
            plain_consequence="Regenerates the architecture snapshot from the repo.",
        ),
    )


# ── aggregation + ordering ───────────────────────────────────────────────


def aggregate(*provider_outputs: Iterable[ActionItem]) -> tuple[ActionItem, ...]:
    """Merge ActionItems from multiple providers and apply deterministic
    ordering. Duplicate ``dedupe_key`` values are coalesced — last writer
    wins so a caller that wants to override a provider entry can do so by
    passing its tuple after the original.

    Plan 2026-06-02-001 F001 (CP-D002): dedup keys on the producer-set
    ``dedupe_key`` (the identity authority), NOT on parsing the id-prefix.
    For current producers ``dedupe_key == id`` so ordering is unchanged.
    """

    merged: dict[str, ActionItem] = {}
    for outputs in provider_outputs:
        for item in outputs:
            merged[item.dedupe_key] = item
    return _sort(merged.values())


def build_uncertainty_card(
    *,
    source: str,
    last_checked: str | None,
    reason: str,
    captured_at: str | None = None,
) -> ActionItem:
    """Plan 2026-06-04-005 F004 — one uncertainty card for a source the render
    gate demoted (stale, or recompute failed/skipped). Never Needs Action:
    band=INFO, resolution_class=blocked_external, section=status_uncertain. States
    the source, last-checked time, and reason so the operator/agent sees honest
    uncertainty instead of fake actionable work."""
    detail = (
        f"Last checked: {last_checked or 'unknown'}. "
        f"Reason: {reason or 'source could not be refreshed'}."
    )
    return ActionItem(
        id=f"uncertain:{source}",
        source=source,
        band=Band.INFO,
        title=f"Status could not be refreshed: {source}",
        detail=detail,
        exact_command=None,
        automatable=False,
        human_required_reason=reason or "source could not be refreshed",
        evidence_uri=None,
        updated_at=captured_at or last_checked or "",
        dedupe_key=f"uncertain:{source}",
        reversible=True,
        resolution_class=RESOLUTION_BLOCKED_EXTERNAL,
        section=SECTION_STATUS_UNCERTAIN,
    )


def collapse_demoted_to_uncertainty(
    demoted_cards: "Iterable[Any]",
    *,
    freshness_by_source: "Mapping[str, Mapping[str, Any]]",
    captured_at: str | None = None,
) -> list[ActionItem]:
    """Plan 2026-06-04-005 F004 — collapse the gate's demoted cards into exactly
    ONE uncertainty card per distinct source (N stale-source cards → 1). Reconcile,
    capabilities, gates, and architecture all demote through this single path."""
    order: list[str] = []
    seen: set[str] = set()
    for c in demoted_cards:
        src = getattr(c, "source", None)
        if src is None or src in seen:
            continue
        seen.add(src)
        order.append(src)
    cards: list[ActionItem] = []
    for src in order:
        info = dict(freshness_by_source.get(src) or {})
        cards.append(
            build_uncertainty_card(
                source=src,
                last_checked=info.get("evaluated_at"),
                reason=info.get("reason") or "source stale or could not be evaluated",
                captured_at=captured_at,
            )
        )
    return cards


def provide_integration_actions(
    evidence_dir: Path,
    *,
    now: _dt.datetime | None = None,
) -> tuple[ActionItem, ...]:
    """Plan 2026-06-04-003 F001 — map the literal integration catalog into
    ActionItems, deriving state from the append-only evidence history ONLY
    (env-var presence is a display hint, never a status driver).

    Band semantics (F003): untriggered gated rows render as ``info``
    (not-yet-needed, never hidden); trigger-met-but-credentials-absent rows
    render as ``advisory`` naming the missing env-var NAMES; ready rows are
    ``needs_action``. Rows whose own evidence already satisfies their
    clears_when predicate are not emitted as ACTION items (F004 surfaces
    their status separately).

    Honest-commands (CP-D008): external commands ride the display-only
    ``operator_command`` field; ``exact_command`` is set ONLY for validated
    dontpanic commands (the static smoke).
    """
    from dontpanic_orchestrate import integration_actions as _itg
    from dontpanic_orchestrate.action_resolvability import ClearsWhen

    updated_at = _now_iso(now)
    histories = {
        action.integration_id: _itg.read_evidence(evidence_dir, action.integration_id)
        for action in _itg.INTEGRATION_CATALOG
    }

    items: list[ActionItem] = []
    for action in _itg.INTEGRATION_CATALOG:
        records = histories[action.integration_id]
        if _itg.has_passed_evidence(records, action.action_id):
            continue  # resolved — F004 renders the status item instead

        creds_present = all(name in os.environ for name in action.credential_env_vars)
        trigger_met = action.trigger_condition is None or _itg.has_passed_evidence(
            records, _itg.TRIGGER_ACTION_FIREBASE
        )

        if not trigger_met:
            band = Band.INFO
            state_note = f"Not yet needed — gated on: {action.trigger_condition}."
        elif action.credential_env_vars and not creds_present:
            band = Band.ADVISORY
            state_note = (
                "Waiting on credential provisioning: "
                + ", ".join(action.credential_env_vars)
                + "."
            )
        else:
            band = Band.NEEDS_ACTION
            state_note = None

        detail_parts = [action.why]
        if state_note:
            detail_parts.append(state_note)
        if action.operator_command:
            detail_parts.append(f"Run yourself: {action.operator_command}")
        if action.credential_env_vars:
            detail_parts.append(
                "Credentials required: " + ", ".join(action.credential_env_vars)
            )
        detail_parts.append(f"Evidence expected: {action.evidence_expected}")

        automatable = action.exact_command is not None and not action.credential_env_vars
        if automatable:
            resolution = RESOLUTION_COMMAND_RESOLVABLE
            reason = None
        else:
            resolution = RESOLUTION_OPERATOR_ATTESTED
            reason = (
                "operator-owned step: external command and/or credentials "
                "DontPanic never executes or reads"
            )

        item_id = f"{SOURCE_INTEGRATION}:{action.integration_id}:{action.action_id}"
        items.append(
            ActionItem(
                id=item_id,
                source=SOURCE_INTEGRATION,
                band=band,
                title=action.what,
                detail=" ".join(detail_parts),
                exact_command=action.exact_command,
                automatable=automatable,
                human_required_reason=reason,
                evidence_uri=str(_itg.evidence_file(evidence_dir, action.integration_id)),
                updated_at=updated_at,
                audience=(AUDIENCE_OPERATOR, AUDIENCE_HUMAN),
                dedupe_key=item_id,
                reversible=action.reversible,
                plain_consequence=(
                    f"Records evidence for the {action.integration_id} integration; "
                    "nothing runs against external services from DontPanic itself."
                ),
                clears_when=ClearsWhen(
                    predicate="integration_evidence_present",
                    params={
                        "integration_id": action.integration_id,
                        "action_id": action.action_id,
                        "outcome": "passed",
                    },
                ),
                resolution_class=resolution,
                trigger_condition=action.trigger_condition,
                operator_command=action.operator_command,
                credential_env_vars=action.credential_env_vars,
                evidence_expected=action.evidence_expected,
            )
        )
    return _sort(items)


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

    # CP-D001 audience: an event surfaced by dispatch is for the operator;
    # needs_action items additionally call for a human decision.
    if automatable:
        audience = [AUDIENCE_OPERATOR]
    else:
        audience = [AUDIENCE_OPERATOR, AUDIENCE_HUMAN]
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
        # CP-D001/CP-D002 control-plane spine fields. dedupe_key is the
        # producer-set identity authority (== id for this producer).
        "audience": audience,
        "dedupe_key": item_id,
        "reversible": False,
        "plain_consequence": getattr(rendered, "detail", None),
        "dashboard_url": None,
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

    Plan 2026-05-24-004 F004 (D011 + D020): raise-mode sanitization. Any
    secret-shaped substring in the projected entry triggers a ``ValueError``
    via :func:`_assert_no_secret_shapes` and the write is rejected before
    the sidecar file is touched. This is the operator-fixable boundary —
    a leaked secret in a rendered ActionItem is a bug worth surfacing
    immediately, since the sidecar is persisted (durable) state. The live
    notification paths use substitute mode instead (see
    :func:`state_projection.scrub_secrets`) so the supervisor never
    fail-hards on a transient notification.
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
    # secret-shape leaks. Failure here surfaces a ValueError to the caller
    # so an operator can fix the rendered ActionItem rather than persisting
    # the leak. Live notification paths use substitute mode (scrub_secrets)
    # because the supervisor must not fail-hard on a transient dispatch.
    _assert_no_secret_shapes(entry)
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
        raw_audience = entry.get("audience")
        audience = (
            tuple(str(a) for a in raw_audience)
            if isinstance(raw_audience, (list, tuple)) and raw_audience
            else (AUDIENCE_OPERATOR,)
        )
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
            audience=audience,
            dedupe_key=entry.get("dedupe_key") or entry["id"],
            reversible=bool(entry.get("reversible", False)),
            plain_consequence=entry.get("plain_consequence"),
            dashboard_url=entry.get("dashboard_url"),
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
    # CP-D002: dedup on the producer-set dedupe_key (identity authority), not
    # the id-prefix. Provider items win on conflict — the sidecar is advisory.
    provider_keys = {item.dedupe_key for item in provider_list}
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
        if item.dedupe_key in provider_keys:
            # Provider items win on conflict — sidecar is advisory.
            continue
        # Dedupe within the sidecar itself (re-fires of the same event
        # append additional lines; keep the most recent).
        sidecar_items = [si for si in sidecar_items if si.dedupe_key != item.dedupe_key]
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
    # Plan 2026-06-02-001 F003: the dashboard cache is rendered through the
    # shared render boundary (dedupe by dedupe_key + scrub secrets + brand
    # normalize) so the served what-now agrees byte-for-byte with the CLI and
    # agent-brief surfaces. Lazy import avoids an action_renderers↔operator_console
    # import cycle. The boundary scrub is a no-op on already-clean data, so this
    # preserves the F001 cache shape and the no-secret invariant.
    from dontpanic_orchestrate import action_renderers as _action_renderers

    payload = _action_renderers.render_dashboard_json(
        final_items, captured_at=captured_at
    )
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
    "AUDIENCE_HUMAN",
    "AUDIENCE_OPERATOR",
    "AUDIENCE_ORCHESTRATOR",
    "AUDIENCE_WORKER",
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
