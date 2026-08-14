"""Event messaging v1 — RenderedEvent contract + translation disposition table + render().

Plan ``2026-05-24-004-feat-event-messaging-v1`` F001 (contract) + F003
(translation table + render function).

Artifacts in this module:

1. :class:`RenderedEvent` — a frozen dataclass whose fields are a near-perfect
   subset of :class:`dontpanic_orchestrate.operator_console.ActionItem`.

2. :data:`DISPOSITION_TABLE` — a mapping keyed by the INBOX ``event=`` string
   per D017; every one of the 27 INBOX event names receives exactly one
   :class:`Disposition` verdict. Totality is enforced by test.

3. :data:`TRANSLATION_TABLE` (F003) — per-kind copy entries (headline / why /
   action templates) sourced from
   ``docs/design/dashboard-value-language-ia-v0/copy-map.md`` vocabulary.

4. :func:`render` (F003) — pure function:
   ``render(event, plan_meta, feature_meta) -> RenderedEvent | None``. Returns
   ``None`` when the disposition is ``inbox_only`` / ``audit_only`` (the
   caller skips rendering for those branches).

Honest-commands rule (D008): any non-None ``exact_command`` is run through
:func:`command_validation.validate_command_tokens` before being placed on the
``RenderedEvent``. Validation failures collapse the command to ``None`` and
log a debug line.

Brand-drift normalization (D010): the renderer rewrites legacy
``jarvis approve`` / ``jarvis-orchestrate approve`` / ``Jarvis [...]`` strings
to the ``dontpanic`` equivalents at render time. Source bodies are NOT edited.

Backward-compat normalization (D009): the legacy colon-separated
``breaker:patch_incomplete`` INBOX event name renders as if it were
``breaker_tripped`` with ``breaker_kind='patch_incomplete'``. The INBOX event
name remains unchanged at the emit site.

Impact-first copy (plan ``2026-08-09-002`` F005): when an event carries a
:class:`decision_brief.DecisionBrief`, the renderable ``needs_action``
templates lead with the declared product impact and demote the plan label,
gate and stage to a supporting reference line (USER.md:15). See
:data:`IMPACT_FIRST_TABLE`.
"""

from __future__ import annotations

import dataclasses
import enum
import re
import shlex
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final


class Disposition(str, enum.Enum):
    """Per-kind verdict that routes an INBOX event to its rendered sinks.

    Definitions come from ``plan.md`` § *Translation Disposition*:

    - ``LIVE`` — renders to Discord + terminal-notifier + dashboard sidecar.
    - ``DASHBOARD_ACTION`` — renders to dashboard sidecar only.
    - ``INBOX_ONLY`` — INBOX entry only; operator may read but no live ping.
    - ``AUDIT_ONLY`` — durable INBOX record for auditor reconstruction.
    """

    LIVE = "live"
    DASHBOARD_ACTION = "dashboard_action"
    INBOX_ONLY = "inbox_only"
    AUDIT_ONLY = "audit_only"


_VALID_DISPOSITIONS: Final[frozenset[str]] = frozenset(d.value for d in Disposition)

# Mirrors operator_console.Band — we do not import Band to keep this module
# pure-stdlib (validator-purity test asserts no project imports). F003 maps
# RenderedEvent.band into Band when materializing an ActionItem.
_VALID_BAND_VALUES: Final[frozenset[str]] = frozenset(
    {"needs_action", "advisory", "info", "ready"}
)


@dataclasses.dataclass(frozen=True)
class RenderedEvent:
    """A rendered event ready for sink-specific projection.

    Field semantics mirror :class:`operator_console.ActionItem` for the five
    fields they share (``band``, ``title``, ``detail``, ``exact_command``,
    ``evidence_uri``). F003 maps a RenderedEvent into an ActionItem at sidecar
    write time by adding ``id``, ``source``, ``updated_at`` and the
    ``automatable`` / ``human_required_reason`` pair.

    ``disposition`` is the F001 verdict (one of :class:`Disposition`).
    ``technical_metadata`` is the long-tail dict per D017 — held as a
    :class:`types.MappingProxyType` view so the frozen dataclass cannot be
    silently mutated through this attribute.

    The :attr:`headline` accessor returns the title — terminal-notifier
    consumes a single short line per ``plan.md`` § *Product Model* (Layer 1).

    Plan ``2026-08-09-002`` F004 widened the contract with the decision-brief
    slots. ``what_changes`` / ``user_impact`` / ``affected_audience`` are the
    product-context fields (what the change is, who feels it, which audience);
    ``plain_consequence`` and ``reversible`` mirror the same-named
    :class:`operator_console.ActionItem` fields so the brief's
    decision-consequence element survives the projection into an ActionItem
    instead of that slot being aliased to the orchestration prose in
    ``detail``. All five default to their empty value, so an event carrying no
    brief renders exactly as before.
    """

    band: str
    title: str
    detail: str | None
    exact_command: str | None
    evidence_uri: str | None
    disposition: Disposition
    technical_metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    # F004 — decision-brief product context (element one + element two).
    what_changes: str | None = None
    user_impact: str | None = None
    affected_audience: str | None = None
    # F004 — decision-brief decision context (element three). Named to match
    # ActionItem so the projection is a copy, not a reinterpretation.
    plain_consequence: str | None = None
    reversible: bool = False

    def __post_init__(self) -> None:
        if self.band not in _VALID_BAND_VALUES:
            raise ValueError(
                f"RenderedEvent.band={self.band!r} not in {sorted(_VALID_BAND_VALUES)}"
            )
        if not isinstance(self.title, str) or not self.title:
            raise ValueError("RenderedEvent.title must be a non-empty string")
        if not isinstance(self.disposition, Disposition):
            raise TypeError(
                "RenderedEvent.disposition must be a Disposition enum member; "
                f"got {type(self.disposition).__name__}"
            )
        if not isinstance(self.technical_metadata, Mapping):
            raise TypeError(
                "RenderedEvent.technical_metadata must be a Mapping; "
                f"got {type(self.technical_metadata).__name__}"
            )
        # Wrap in a read-only view so callers can't mutate technical_metadata
        # through the frozen dataclass attribute.
        if not isinstance(self.technical_metadata, MappingProxyType):
            object.__setattr__(
                self,
                "technical_metadata",
                MappingProxyType(dict(self.technical_metadata)),
            )

    @property
    def headline(self) -> str:
        """One-sentence headline rendered by terminal-notifier.

        Per ``plan.md`` § *Product Model* the headline is the value-first
        label (Layer 1). RenderedEvent stores it in ``title``; the accessor
        exists so terminal-notifier callers don't bind to a structural detail
        that may evolve.
        """
        return self.title


# ── Translation disposition table ───────────────────────────────────────────
#
# Keyed by the INBOX ``event=`` string at the paired ``append_event`` call
# (D017). F002 will add ``NotifyEvent.inbox_event`` carrying the same string
# so F003's renderer can look up disposition without needing NotifyEvent.kind.
#
# Per-kind rationale lives in ``evidence/f001-inventory-draft.md`` Section 2.
# Short rationale for the verdict choice:
#
#   live              — has a NotifyEvent dispatch (existing or F002-added)
#                       and surfaces high-value operator signal. Discord +
#                       terminal + sidecar + INBOX annotation.
#   dashboard_action  — no live ping but materializes a dashboard ActionItem
#                       via the sidecar pattern (D003). Requires a
#                       NotifyEvent dispatch to route through dispatch_event.
#   inbox_only        — operator-visible but no NotifyEvent dispatch in v1;
#                       operator scans INBOX directly.
#   audit_only        — pure audit-trail entry; not surfaced to operator.
#
# Totality (every 27 INBOX kinds present, no duplicates) is enforced by test.

_DISPOSITIONS: Final[dict[str, Disposition]] = {
    # Existing NotifyEvent emit sites → live (already on Discord/terminal):
    "breaker_tripped": Disposition.LIVE,
    "calibration_required": Disposition.LIVE,
    "gate_hit": Disposition.LIVE,
    "volley_start": Disposition.LIVE,
    "volley_terminal": Disposition.LIVE,
    # F002 adds NotifyEvent dispatch at six currently-silent emit sites → live:
    "architecture_regen_failed": Disposition.LIVE,
    "environmental_blocker_short_circuit": Disposition.LIVE,
    "gate_state_reconciliation_failed": Disposition.LIVE,
    "no_progress_classification": Disposition.LIVE,
    "verdict_blocked_reconciled": Disposition.LIVE,
    "verdict_mismatch": Disposition.LIVE,
    # D009: legacy colon-separated name normalizes internally to
    # breaker_tripped + breaker_kind=patch_incomplete at render time. The
    # INBOX event name stays as-is; the routed disposition matches the
    # normalized form (live).
    "breaker:patch_incomplete": Disposition.LIVE,
    # Dashboard-action kinds (D007 + plan.md § Translation Disposition):
    # operator-actionable but the soft / drift-style signal would be noise on
    # Discord. Materialize an ActionItem via the sidecar pattern (D003); the
    # rendered annotation also appends to INBOX so the operator can read why.
    "config_required": Disposition.DASHBOARD_ACTION,
    "quota_warn": Disposition.DASHBOARD_ACTION,
    "unit_mismatch": Disposition.DASHBOARD_ACTION,
    # No live notify in v1, but operator-actionable — surface as INBOX entry:
    "blocked_no_findings": Disposition.INBOX_ONLY,
    "defer_tripped": Disposition.INBOX_ONLY,
    # ``error`` stays INBOX_ONLY in v1: every emit site in supervisor.py
    # (search for `event="error"`) writes to INBOX directly without a
    # paired ``dispatch_event`` call, so the renderer is never invoked for
    # this kind. The matching ``error`` template lives in TRANSLATION_TABLE
    # as defensive coverage — if a future emit site grows a dispatch_event
    # call and flips this disposition to LIVE / DASHBOARD_ACTION, render()
    # will produce honest-commands output (``exact_command=None`` per D008)
    # without further changes here.
    "error": Disposition.INBOX_ONLY,
    "feature_operator_resolved": Disposition.INBOX_ONLY,
    "nested_child_pending": Disposition.INBOX_ONLY,
    "volley_crash_caught": Disposition.INBOX_ONLY,
    # Pure auditor-reconstruction records — no operator surface:
    "architecture_regenerated": Disposition.AUDIT_ONLY,
    "auto_cleared_pre_impl": Disposition.AUDIT_ONLY,
    "defer_cleared": Disposition.AUDIT_ONLY,
    "gate_cleared": Disposition.AUDIT_ONLY,
    "pre_impl_status_synced": Disposition.AUDIT_ONLY,
    "resumed": Disposition.AUDIT_ONLY,
}

DISPOSITION_TABLE: Final[Mapping[str, Disposition]] = MappingProxyType(_DISPOSITIONS)


# The full canonical set of INBOX event names from
# ``evidence/f001-inventory-draft.md`` Section 2. The disposition-table
# totality test asserts ``DISPOSITION_TABLE.keys() == INBOX_EVENT_KINDS``.
INBOX_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "architecture_regen_failed",
        "architecture_regenerated",
        "auto_cleared_pre_impl",
        "blocked_no_findings",
        "breaker:patch_incomplete",
        "breaker_tripped",
        "calibration_required",
        "config_required",
        "defer_cleared",
        "defer_tripped",
        "environmental_blocker_short_circuit",
        "error",
        "feature_operator_resolved",
        "gate_cleared",
        "gate_hit",
        "gate_state_reconciliation_failed",
        "nested_child_pending",
        "no_progress_classification",
        "pre_impl_status_synced",
        "quota_warn",
        "resumed",
        "unit_mismatch",
        "verdict_blocked_reconciled",
        "verdict_mismatch",
        "volley_crash_caught",
        "volley_start",
        "volley_terminal",
    }
)


def disposition_for(inbox_event: str) -> Disposition:
    """Return the disposition for an INBOX event name.

    Raises ``KeyError`` for unknown event names — the disposition table is
    closed v1 (totality enforced by test); adding a new INBOX event without
    a matching disposition is a caller bug.
    """
    return DISPOSITION_TABLE[inbox_event]


# ── F003 translation table ──────────────────────────────────────────────────
#
# Per D017 + D007, the translation table is keyed by ``NotifyEvent.inbox_event``
# (the INBOX ``event=`` value at the paired ``append_event`` call). Each entry
# carries headline / why / action templates that map to RenderedEvent.title /
# detail / exact_command respectively. Copy references the IA value-language
# copy map at ``docs/design/dashboard-value-language-ia-v0/copy-map.md`` §2.2 +
# §2.7 (no new vocabulary authored here).
#
# Per D008 honest-commands rule, kinds with no canonical CLI remediation
# render ``action=None`` (validator never runs against None; placeholder copy
# explains the next step in ``why`` instead).
#
# Per D009 backward-compat, ``breaker:patch_incomplete`` is normalized at
# render time to behave like ``breaker_tripped`` + ``breaker_kind=patch_incomplete``;
# its template entry is therefore not authored as a distinct kind here — the
# renderer routes through the ``breaker_tripped`` entry.


@dataclasses.dataclass(frozen=True)
class _Template:
    """One translation table row.

    ``headline`` and ``why`` are Python ``.format(**fields)`` templates; each
    must successfully format under the field-set the renderer assembles.
    ``action`` is ``None`` for honest-commands kinds (D008) or a format
    template like ``"dontpanic approve {plan_id} {gate}"``.

    ``band`` resolves to one of the four operator-console bands and is
    inlined here so disposition routing alone determines the band (rather
    than threading band through severity, which is closed at three values).

    Plan ``2026-08-09-002`` F004 added the three decision-brief copy slots
    (``what_changes`` / ``user_impact`` / ``affected_audience``). They default
    to ``None`` so every row authored before this feature keeps constructing
    unchanged, and they are only consulted when the event carries no
    :class:`decision_brief.DecisionBrief` — a declared brief always wins over
    table copy, because the brief is what the operator is actually deciding.
    """

    band: str
    headline: str
    why: str
    action: str | None
    what_changes: str | None = None
    user_impact: str | None = None
    affected_audience: str | None = None


_NEEDS_ACTION: Final[str] = "needs_action"
_ADVISORY: Final[str] = "advisory"
_INFO: Final[str] = "info"
_READY: Final[str] = "ready"


# Templates reference the copy map § 2.2 / §2.7 vocabulary:
#   "Approval needed"   → gate_hit
#   "Blocked work"      → volley_terminal (non-signed-off), error
#   "Setup drift"       → reconcile-derived (gate_state_reconciliation_failed)
#   "Active AI work"    → volley_start
#   "AI work finished"  → signoff (synthesized — INBOX event volley_terminal +
#                         final_status=signed_off; the supervisor's dispatch
#                         site already routes the signed-off variant through
#                         the volley_terminal inbox_event with a different
#                         kind. We surface this in the why/headline copy
#                         conditional on final_status when present.)
#   "System warning"    → architecture_regen_failed
#   "Budget guardrail"  → calibration_required / unit_mismatch / config_required
_TEMPLATES: Final[Mapping[str, _Template]] = {
    # Approval / gate ────────────────────────────────────────────────────
    "gate_hit": _Template(
        band=_NEEDS_ACTION,
        headline="Approval needed on {plan_label}",
        why=(
            "Supervisor paused at gate `{gate}` "
            "(stage `{stage}`). Operator must approve before dispatch "
            "continues."
        ),
        action="dontpanic approve {plan_id} {gate}",
    ),
    # Setup drift — gate-state reconciliation failure (honest-commands: None).
    "gate_state_reconciliation_failed": _Template(
        band=_NEEDS_ACTION,
        headline="Setup drift on {plan_label} — gate state inconsistent",
        why=(
            "Persisted gate state contradicts plan declaration "
            "(`{contradiction_kind}`, gate=`{gate}`, stage=`{stage}`). "
            "There is no canonical reconcile subcommand; inspect the "
            "persisted state file and INBOX entry before re-dispatching."
        ),
        action=None,  # D008 — no canonical CLI to auto-reconcile gate state
    ),
    # Blocked work — verdict mismatch (honest-commands: None).
    "verdict_mismatch": _Template(
        band=_NEEDS_ACTION,
        headline="Blocked work on {plan_label} — verdict mismatch",
        why=(
            "Auditor narrative verdict (`{narrative_verdict}`) disagrees "
            "with structured `audit_status` (`{structured_status}`) on "
            "iteration {iteration_label}. No automated re-audit command; "
            "open the audit envelope and reconcile manually."
        ),
        action=None,  # D008 — no canonical CLI for verdict reconciliation
    ),
    # Blocked work — generic error (honest-commands: None — context-specific).
    "error": _Template(
        band=_NEEDS_ACTION,
        headline="Blocked work on {plan_label} — error reported",
        why="Supervisor recorded an error condition; see INBOX entry for the originating site.",
        action=None,  # D008 — error sites are context-specific
    ),
    # Volley terminal — covers both signed-off (info) and blocked variants.
    # We branch on final_status in the renderer to swap headline/why/band.
    "volley_terminal": _Template(
        band=_NEEDS_ACTION,
        headline="Blocked work on {plan_label} — {final_status_label}",
        why=(
            "Volley terminated after {rounds} round(s) with status "
            "`{final_status}`. Review the audit envelope before "
            "deciding next step."
        ),
        action="dontpanic resume {plan_id} --all",
    ),
    # Active AI work — volley start (info band; no operator action).
    "volley_start": _Template(
        band=_INFO,
        headline="Active AI work on {plan_label}",
        why=(
            "Volley begins with implementer `{implementer}` and "
            "auditor `{auditor}` (cap {iteration_label})."
        ),
        action=None,
    ),
    # Breaker tripped — needs operator clearance. Templates branch on
    # APPROVAL vs hard-stop breakers in the renderer.
    "breaker_tripped": _Template(
        band=_NEEDS_ACTION,
        headline="Blocked work on {plan_label} — breaker `{breaker_kind}` tripped",
        why=(
            "Circuit breaker `{breaker_kind}` tripped. Operator clearance "
            "required before dispatch continues."
        ),
        action="dontpanic approve {plan_id} breaker:{breaker_kind}",
    ),
    # Budget guardrail — calibration required (honest path: calibrate-claude
    # IS canonical and has all required flags).
    "calibration_required": _Template(
        band=_NEEDS_ACTION,
        headline="Budget guardrail on {plan_label} — calibration required",
        why=(
            "Calibration sample required for `{agent}.{window}` so the "
            "breaker can convert local proxy units into percent-of-plan."
        ),
        action=(
            "python -m dontpanic_orchestrate calibrate-claude "
            "--window {window} --dashboard-pct 0"
        ),
    ),
    # System warning — architecture regen failure (info; advisory only).
    "architecture_regen_failed": _Template(
        band=_ADVISORY,
        headline="System warning on {plan_label} — architecture map may be stale",
        why=(
            "Post-commit architecture regen failed (`{error_type}`). The "
            "volley terminal is unaffected; operator may re-run the regen."
        ),
        action="dontpanic architecture regen",
    ),
    # Setup-drift derivatives from auditor classification.
    "no_progress_classification": _Template(
        band=_NEEDS_ACTION,
        headline="Blocked work on {plan_label} — no-progress taxonomy",
        why=(
            "Auditor verdict taxonomy `{aggregate_class}` "
            "(blocking={blocking_label}); recommended: review the audit "
            "envelope before re-dispatch."
        ),
        action="dontpanic resume {plan_id} --all",
    ),
    "verdict_blocked_reconciled": _Template(
        band=_NEEDS_ACTION,
        headline="Blocked work on {plan_label} — verdict reconciled",
        why=(
            "Auditor said `blocked` but every finding classified as "
            "advisory (`{aggregate_class}`); supervisor promoted the "
            "terminal to `stopped_environmental_blocker`."
        ),
        action=(
            "dontpanic approve {plan_id} breaker:environmental_blocker"
        ),
    ),
    "environmental_blocker_short_circuit": _Template(
        band=_NEEDS_ACTION,
        headline="Blocked work on {plan_label} — environmental blocker",
        why=(
            "Every auditor finding classified as "
            "`environmental_reproduction_failure`; volley short-circuited "
            "without another paid implementer round."
        ),
        action=(
            "dontpanic approve {plan_id} breaker:environmental_blocker"
        ),
    ),
    # Dashboard-action: budget-guardrail soft warning. No Discord ping
    # (operator would tune that down to noise quickly); the dashboard
    # ActionItem keeps it visible until acknowledged.
    "quota_warn": _Template(
        band=_ADVISORY,
        headline="Budget guardrail on {plan_label} — quota soft warn",
        why=(
            "Quota soft-warn for `{agent}` at `{percent_weekly}%` of weekly "
            "cap (threshold `{threshold}%`). Volley continues under "
            "`JARVIS_QUOTA_ENFORCE=soft`; set `hard` to halt at threshold."
        ),
        action=None,  # D008 — operator decides whether to tune the cap or stop
    ),
    # Dashboard-action: calibration drift between recorded cap unit and the
    # observed quota_check.py unit. Operator must hand-edit the caps file.
    "unit_mismatch": _Template(
        band=_NEEDS_ACTION,
        headline="Setup drift on {plan_label} — quota cap unit mismatch",
        why=(
            "Quota cap unit drift for `{agent}.{window}`: cap.unit=`{cap_unit}` "
            "≠ observed=`{observed_unit}`. Edit `~/.jarvis/quota_caps.json` "
            "so cap.unit matches what quota_check.py emits."
        ),
        action=None,  # D008 — no canonical CLI; hand-edit required
    ),
    # Dashboard-action: quota config missing / unusable. Operator must seed
    # caps or re-run quota_check.py.
    "config_required": _Template(
        band=_NEEDS_ACTION,
        headline="Setup drift on {plan_label} — quota config required",
        why=(
            "Quota config required (`{cause}`). Run "
            "`python -m dontpanic_orchestrate quota-caps init` to seed "
            "defaults, hand-edit `~/.jarvis/quota_caps.json` for "
            "`no_cap_for_signal`, or re-run `scripts/quota_check.py` for "
            "`missing_vendor_block`."
        ),
        action="python -m dontpanic_orchestrate quota-caps init",
    ),
}

TRANSLATION_TABLE: Final[Mapping[str, _Template]] = MappingProxyType(dict(_TEMPLATES))


# ── F005 impact-first overlay ───────────────────────────────────────────────
#
# Plan ``2026-08-09-002`` F005. Every headline above opens with the
# orchestrator's own vocabulary — ``Approval needed on 2026-08-08-001`` — so
# the person being asked to decide learns the plan id before, and often
# instead of, what the change does. USER.md:15 asks for the opposite ordering:
# product outcome and who feels it lead; F-ids, gates and verdict names are
# supporting references.
#
# The overlay is a second table rather than extra columns on ``_Template``
# because the two are consulted under different conditions and have different
# lifetimes: a row above is the copy of record for an event carrying no brief,
# and a row here only applies once F003's snapshot is present. Keeping them
# apart also keeps the ``action`` templates provably untouched — F005 changes
# prose only, and no command is authored here.
#
# Scope is exactly the *renderable* ``needs_action`` kinds. ``INBOX_ONLY`` /
# ``AUDIT_ONLY`` kinds never reach render(), and the advisory / info / ready
# bands are not approval prompts, so neither gets an overlay row.


@dataclasses.dataclass(frozen=True)
class _ImpactFirst:
    """The impact-first half of one renderable ``needs_action`` kind.

    ``reason`` is what the old headline said *minus* its ``on {plan_label}``
    clause — the IA vocabulary token plus whatever qualifier that kind carried
    ("breaker `X` tripped", "verdict mismatch"). It trails the impact line so
    the headline reads "who feels it, what changes — why you are being asked".

    ``why`` replaces the row's body only for the two kinds whose body leads
    with the gate and stage; those two facts move to the reference line, so
    repeating them inline would be the demotion failing to happen. ``None``
    means the row's own ``why`` is already product-neutral and is reused.
    """

    reason: str
    why: str | None = None


_IMPACT_FIRST: Final[Mapping[str, _ImpactFirst]] = {
    "gate_hit": _ImpactFirst(
        reason="Approval needed",
        # "Supervisor paused" is a fact about what already happened, not a
        # restatement of the gate: it survives the rewrite. Only the inline
        # "at gate `X` (stage `Y`)" moves to the reference line.
        why="Supervisor paused. Operator must approve before dispatch continues.",
    ),
    "gate_state_reconciliation_failed": _ImpactFirst(
        reason="Setup drift: gate state inconsistent",
        why=(
            "Persisted gate state contradicts plan declaration "
            "(`{contradiction_kind}`). There is no canonical reconcile "
            "subcommand; inspect the persisted state file and INBOX entry "
            "before re-dispatching."
        ),
    ),
    "verdict_mismatch": _ImpactFirst(reason="Blocked work: verdict mismatch"),
    "volley_terminal": _ImpactFirst(reason="Blocked work: {final_status_label}"),
    "breaker_tripped": _ImpactFirst(
        reason="Blocked work: breaker `{breaker_kind}` tripped"
    ),
    "calibration_required": _ImpactFirst(
        reason="Budget guardrail: calibration required"
    ),
    "no_progress_classification": _ImpactFirst(
        reason="Blocked work: no-progress taxonomy"
    ),
    "verdict_blocked_reconciled": _ImpactFirst(
        reason="Blocked work: verdict reconciled"
    ),
    "environmental_blocker_short_circuit": _ImpactFirst(
        reason="Blocked work: environmental blocker"
    ),
    "unit_mismatch": _ImpactFirst(reason="Setup drift: quota cap unit mismatch"),
    "config_required": _ImpactFirst(reason="Setup drift: quota config required"),
}

IMPACT_FIRST_TABLE: Final[Mapping[str, _ImpactFirst]] = MappingProxyType(
    dict(_IMPACT_FIRST)
)


# Who feels it, in the operator's language. Keyed by the ``audience`` enum in
# ``features.schema.json`` § user_impact. ``none`` is absent on purpose: that
# declaration asserts no external consequence and so carries no summary to
# lead with. An audience outside this map renders with no label rather than a
# guessed plural — inventing prose at the render boundary is what D002 forbids.
_AUDIENCE_LABELS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "end_user": "End users",
        "operator": "Operators",
        "agent": "Agents",
    }
)

#: Marker phrase the reference line carries when no feature is in scope. A
#: plan-level pause gets its own honest line rather than a feature-shaped one
#: with an empty slot where the F-id would go.
PLAN_LEVEL_REFERENCE_MARKER: Final[str] = "plan-level — no feature in scope"

#: Status value (``decision_brief.BriefStatus.DECLARED``) the impact lead
#: requires. Compared as a string so this module keeps its pure-stdlib import
#: surface. ``possibly_stale`` deliberately does not qualify: presenting a
#: summary written against different description text as if it were current is
#: what D005 forbids, and marking it stale is F006's job, not a lead here.
_DECLARED_STATUS: Final[str] = "declared"
#: The other two ``decision_brief.BriefStatus`` values, compared as strings for
#: the same reason.
_POSSIBLY_STALE_STATUS: Final[str] = "possibly_stale"
_UNDECLARED_STATUS: Final[str] = "undeclared"


# ── F006: the honesty rules ─────────────────────────────────────────────────
#
# D002: when impact is undeclared the renderer says so verbatim and supplies no
# substitute. Every sentence below is a module-level string constant, written
# by a person, containing no interpolation — an invented consequence at an
# approval prompt is fabrication at the moment the reader has stopped verifying
# and started trusting, and a blank at least sends them to look.
# :func:`scan_non_generative_copy` asserts that property over the source rather
# than trusting this comment.
#
# D005: a declaration whose recorded digest no longer matches the description
# it was written against is still shown — dropping it would lose a fact — but
# it is shown labelled as written against an earlier version, never as current.

#: Rendered when a feature carries no ``user_impact`` block at all.
UNDECLARED_IMPACT_SENTENCE: Final[str] = (
    "User impact not declared for this feature."
)

#: The same statement for a plan-level pause, where no feature is in scope and
#: "this feature" would name something the event never carried.
PLAN_LEVEL_UNDECLARED_IMPACT_SENTENCE: Final[str] = (
    "User impact not declared for this plan."
)

#: Prefixes the declared summary when the brief is ``possibly_stale``. The
#: summary itself follows verbatim; the label is the whole point, so it leads.
STALE_IMPACT_PREFIX: Final[str] = (
    "User impact was declared against an earlier version of this feature and "
    "has not been re-confirmed since: "
)

#: Rendered when the declaration is present and complete but asserts no
#: external consequence (``audience: none``, which by contract carries no
#: summary). Stating the declaration is not synthesizing one: the operator
#: would otherwise see the same blank as the undeclared case and could not tell
#: "nobody wrote this down" from "somebody wrote down that nobody feels it".
NO_USER_IMPACT_SENTENCE: Final[str] = (
    "Declared as having no user-facing impact."
)

#: Terminates the stale line. The declared summary is spliced verbatim (D015)
#: and operator-authored summaries rarely end in punctuation, so without this
#: the stale sentence runs straight into the reference line that follows it
#: ("…invented prose Reference: plan `P`"). One character, and it is the
#: difference between two sentences and one unreadable one.
STALE_IMPACT_TERMINATOR: Final[str] = "."

#: Fallback for a ``possibly_stale`` brief whose summary is empty. Unreachable
#: through the schema (a stale brief carries a claim by construction), but the
#: renderer must not fall through to silence if it ever is reached.
STALE_IMPACT_WITHOUT_SUMMARY_SENTENCE: Final[str] = (
    "User impact was declared against an earlier version of this feature and "
    "the declared summary is unavailable."
)

#: Every honesty sentence, by the name it is bound to. Read by
#: :func:`scan_non_generative_copy` so a sentence added later without being
#: registered here is a scan violation rather than an unchecked string.
_HONESTY_CONSTANT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "UNDECLARED_IMPACT_SENTENCE",
        "PLAN_LEVEL_UNDECLARED_IMPACT_SENTENCE",
        "STALE_IMPACT_PREFIX",
        "NO_USER_IMPACT_SENTENCE",
        "STALE_IMPACT_WITHOUT_SUMMARY_SENTENCE",
    }
)


# Brand-drift translation (D010). Order matters: longer prefixes first so
# `jarvis-orchestrate approve` is normalized before the generic `jarvis approve`
# substring would otherwise eat its prefix.
_BRAND_REWRITES: Final[tuple[tuple[str, str], ...]] = (
    ("jarvis-orchestrate approve", "dontpanic approve"),
    ("jarvis approve", "dontpanic approve"),
    ("jarvis resume", "dontpanic resume"),
    ("jarvis-orchestrate resume", "dontpanic resume"),
    ("Jarvis [", "DontPanic ["),
    ("jarvis: ", "dontpanic: "),
)


def normalize_brand_drift(text: str | None) -> str | None:
    """Translate legacy ``jarvis*`` brand strings to the ``dontpanic`` brand.

    Per D010: source body strings are NOT edited; translation happens at the
    render boundary. ``None`` passes through unchanged so callers don't need
    to guard.
    """
    if text is None:
        return None
    out = text
    for legacy, modern in _BRAND_REWRITES:
        out = out.replace(legacy, modern)
    return out


# ── F003 render() ───────────────────────────────────────────────────────────


def _normalize_inbox_event(inbox_event: str) -> tuple[str, str | None]:
    """Apply D009 backward-compat normalization for ``breaker:patch_incomplete``.

    Returns (normalized_inbox_event, breaker_kind_override). D009 authorizes
    exactly one legacy colon-key (``breaker:patch_incomplete``) for backward
    compat with the supervisor's CLI gate name; the renderer treats it as if
    the INBOX event were ``breaker_tripped`` and the override carries the
    kind. Any other ``breaker:<unknown>`` value is intentionally NOT
    normalized — the table lookup will miss and render() returns None so
    unknown breaker kinds never produce a fake live notification with a
    bogus ``dontpanic approve p breaker:<unknown>`` command.
    """
    if inbox_event == "breaker:patch_incomplete":
        return "breaker_tripped", "patch_incomplete"
    return inbox_event, None


def _plan_label(plan_id: str, feature_meta: Mapping[str, Any] | None) -> str:
    """`<plan_id> F00X` when a feature is in scope; bare plan_id otherwise."""
    feature_id: str | None = None
    if feature_meta is not None:
        feature_id = feature_meta.get("id") or feature_meta.get("feature_id")
    if feature_id:
        return f"{plan_id} {feature_id}"
    return plan_id


def _final_status_label(status: str | None) -> str:
    if not status:
        return "stopped"
    return status.replace("_", " ")


def _gather_fields(
    *,
    inbox_event: str,
    event: Any,
    plan_meta: Mapping[str, Any] | None,
    feature_meta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Assemble the ``.format(**fields)`` keyword set for a render call.

    Pulls from NotifyEvent first-class fields (D004 + D017), then
    technical_metadata (long-tail per D017), then plan_meta / feature_meta.
    Missing values render as ``"-"`` so a templated reference to a never-set
    field doesn't KeyError the renderer.
    """
    plan_id = getattr(event, "plan_id", "(unknown plan)")
    feature_id = getattr(event, "feature_id", None) or (
        (feature_meta or {}).get("id") or (feature_meta or {}).get("feature_id")
    )

    fields: dict[str, Any] = {
        "plan_id": plan_id or "(unknown plan)",
        "feature_id": feature_id or "-",
        "plan_label": _plan_label(plan_id or "(unknown plan)", feature_meta),
        "feature_display_name": (
            getattr(event, "feature_display_name", None)
            or (feature_meta or {}).get("display_name")
            or (feature_meta or {}).get("description")
            or feature_id
            or "-"
        ),
        "breaker_kind": getattr(event, "breaker_kind", None) or "-",
        "subtype": getattr(event, "subtype", None) or "-",
        "iteration_count": getattr(event, "iteration_count", None),
        "iteration_label": (
            str(getattr(event, "iteration_count", None))
            if getattr(event, "iteration_count", None) is not None
            else "-"
        ),
        "aggregate_class": getattr(event, "aggregate_class", None) or "-",
        "blocking": getattr(event, "blocking", None),
        "blocking_label": (
            "true" if getattr(event, "blocking", None) else "false"
        ),
        "target_env": getattr(event, "target_env", None) or "-",
        "target_project": getattr(event, "target_project", None) or "(none)",
    }
    # technical_metadata fields by name (long-tail per D017)
    technical = getattr(event, "technical_metadata", None) or {}
    if isinstance(technical, Mapping):
        for key, val in technical.items():
            # Don't clobber first-class fields with technical_metadata.
            fields.setdefault(key, val if val is not None else "-")

    # Derived labels used by some templates.
    fields.setdefault("gate", fields.get("gate") or fields.get("subtype") or "-")
    fields.setdefault("stage", fields.get("stage") or fields.get("subtype") or "-")
    fields.setdefault("final_status", fields.get("final_status") or "-")
    fields.setdefault(
        "final_status_label", _final_status_label(fields.get("final_status"))
    )
    fields.setdefault("rounds", fields.get("rounds") or "-")
    fields.setdefault("narrative_verdict", fields.get("narrative_verdict") or "-")
    fields.setdefault("structured_status", fields.get("structured_status") or "-")
    fields.setdefault("contradiction_kind", fields.get("contradiction_kind") or fields.get("kind") or "-")
    fields.setdefault("error_type", fields.get("error_type") or "-")
    fields.setdefault("agent", fields.get("agent") or "-")
    fields.setdefault("window", fields.get("window") or "-")
    fields.setdefault("implementer", fields.get("implementer") or "-")
    fields.setdefault("auditor", fields.get("auditor") or "-")
    return fields


def _validate_exact_command(command: str) -> str | None:
    """Strip prefix, validate the token shape, return command or None.

    Per D008 + F001 acceptance: any non-None exact_command must pass
    :func:`command_validation.validate_command_tokens`. Failures collapse to
    ``None`` so the renderer never emits a broken copy-paste target.
    """
    from dontpanic_orchestrate import command_validation

    stripped = command.strip()
    # Strip allowed invocation prefixes per command_validation docstring.
    prefixes = ("python -m dontpanic_orchestrate ", "dontpanic ")
    body = stripped
    for prefix in prefixes:
        if body.startswith(prefix):
            body = body[len(prefix):]
            break
    try:
        tokens = shlex.split(body)
    except ValueError:
        return None
    result = command_validation.validate_command_tokens(tokens)
    return stripped if result.ok else None


def _band_for(template: _Template, final_status: str | None) -> str:
    """Resolve the band, branching on volley_terminal's signed_off vs other."""
    if final_status == "signed_off":
        return _READY
    return template.band


def _resolve_evidence_uri(event: Any) -> str | None:
    """Read evidence_uri first, fall back to action_link alias (D005)."""
    return getattr(event, "evidence_uri", None) or getattr(event, "action_link", None)


def _brief_fields(
    event: Any, template: _Template, fields: Mapping[str, Any]
) -> dict[str, Any]:
    """Plan 2026-08-09-002 F004 — resolve the five decision-brief slots.

    The snapshot on ``NotifyEvent.decision_brief`` (F003) is authoritative:
    it was taken where the plan and feature records were genuinely in scope,
    so nothing here re-derives or substitutes for it. Table copy is a
    fallback for events that carry no brief, and ``plain_consequence`` /
    ``reversible`` come only from the brief — there is no table copy for
    "what approving does", and inventing one would be the same mistake as
    aliasing the slot to the orchestration prose.
    """
    brief = getattr(event, "decision_brief", None)
    if brief is not None:
        # Verbatim. D010's brand-drift rewrite is deliberately NOT applied to
        # brief-sourced copy: the brief is a snapshot taken upstream, and F004
        # AC2 requires the decision-consequence element to reach ActionItem
        # byte-for-byte. Rewriting it here silently mutated operator-visible
        # text (`Run jarvis approve F004.` arrived as `Run dontpanic approve
        # F004.`) and broke that contract. Rewriting only some of the slots
        # would additionally let one brief render in two brand spellings, so
        # all four pass through untouched; the fallback copy below — authored
        # in this repo's table, which is what D010 was written for — is still
        # normalized.
        return {
            "what_changes": getattr(brief, "what_changes", None),
            "user_impact": getattr(brief, "user_impact", None),
            "affected_audience": getattr(brief, "affected_audience", None),
            "plain_consequence": getattr(brief, "decision_consequence", None),
            "reversible": bool(getattr(brief, "reversible", False)),
        }

    def _row(value: str | None) -> str | None:
        return normalize_brand_drift(value.format(**fields)) if value else None

    return {
        "what_changes": _row(template.what_changes),
        "user_impact": _row(template.user_impact),
        "affected_audience": _row(template.affected_audience),
        "plain_consequence": None,
        "reversible": False,
    }


def _status_value(brief: Any) -> str | None:
    """The brief's status as a plain string (enum member or str both accepted)."""
    raw = getattr(brief, "status", None)
    return getattr(raw, "value", raw)


def _impact_lead(brief: Any) -> str | None:
    """F005 — "who feels it, and what they feel" as one leading clause.

    Returns ``None`` whenever there is nothing declared to lead with: no
    brief, ``audience: none`` (which carries no summary by contract), or a
    declaration that no longer matches the description it was written
    against. In every one of those cases the caller keeps the current headline
    shape — nothing is synthesized to fill the gap (D002).
    """
    if brief is None:
        return None
    if _status_value(brief) != _DECLARED_STATUS:
        return None
    summary = (getattr(brief, "user_impact", None) or "").strip()
    if not summary:
        return None
    # Trailing sentence punctuation would collide with the " — " join.
    lead = summary.rstrip(". ")
    label = _AUDIENCE_LABELS.get(getattr(brief, "affected_audience", None) or "")
    return f"{label}: {lead}" if label else lead


def _feature_in_scope(fields: Mapping[str, Any]) -> bool:
    """Whether this event names a feature, by the same test the reference line
    uses — ``_gather_fields`` renders a missing feature id as ``"-"``."""
    feature_id = str(fields.get("feature_id") or "")
    return bool(feature_id) and feature_id != "-"


def _impact_status_line(brief: Any, fields: Mapping[str, Any]) -> str | None:
    """F006 — what the renderer knows about impact, stated in its own words.

    Returns ``None`` only when the headline already carries the claim: a
    declared brief with a summary leads with it (F005's ``_impact_lead``), and
    repeating it in the body would state one fact twice. Every other case gets
    a sentence, because every other case is the renderer admitting a limit:

    ``undeclared``      → the literal sentence, and nothing else. D002 forbids
                          a substitute, so there is none — not a hedge, not a
                          restatement of the feature description dressed up as
                          an impact claim.
    ``possibly_stale``  → the declared summary, verbatim, behind a label saying
                          which version it was written against. D005: the copy
                          is a fact worth carrying and a claim not worth
                          trusting, and the label is what separates the two.
    declared, no claim  → ``audience: none`` is a complete declaration that
                          nobody outside feels this, and saying so distinguishes
                          it from the blank above.

    Nothing here is interpolated from event data or from anything a model
    produced; the only variable text is the operator-authored summary carried
    on the snapshot, spliced verbatim per D015.
    """
    if brief is None:
        return None
    status = _status_value(brief)
    if status == _UNDECLARED_STATUS:
        return (
            UNDECLARED_IMPACT_SENTENCE
            if _feature_in_scope(fields)
            else PLAN_LEVEL_UNDECLARED_IMPACT_SENTENCE
        )
    summary = (getattr(brief, "user_impact", None) or "").strip()
    if status == _POSSIBLY_STALE_STATUS:
        if not summary:
            return STALE_IMPACT_WITHOUT_SUMMARY_SENTENCE
        # Same trailing-punctuation trim as the impact lead, for the same
        # reason: the declared summary is a fragment, and the terminator is
        # this module's, not the author's.
        return STALE_IMPACT_PREFIX + summary.rstrip(". ") + STALE_IMPACT_TERMINATOR
    if status == _DECLARED_STATUS and not summary:
        return NO_USER_IMPACT_SENTENCE
    return None


#: Kinds whose emit site threads the pause *stage* through ``NotifyEvent
#: .subtype`` — ``supervisor._emit_gate_paused_discord`` sets ``subtype=stage``.
#: Nothing else does: ``verdict_mismatch`` puts the structured audit status
#: there, ``gate_state_reconciliation_failed`` the contradiction kind,
#: ``plan_drift_detected`` the drift class. Reading subtype as a gate or stage
#: outside this set invents an orchestration fact the event never carried.
_SUBTYPE_IS_STAGE: Final[frozenset[str]] = frozenset({"gate_hit"})


def _reference_gate_stage(
    inbox_event: str, event: Any
) -> tuple[str | None, str | None]:
    """The gate and stage the reference line may name, or ``None`` each.

    Deliberately narrower than ``_gather_fields``, which aliases ``subtype``
    into both slots so a template referencing ``{gate}`` never KeyErrors. That
    alias is fine for a template that only fires on a gate-shaped event; it is
    not fine here, because the reference line runs for *every* renderable
    ``needs_action`` kind and would report the real ``verdict_mismatch``
    subtype ``signed_off`` as ``gate `signed_off```.

    So the gate comes only from explicit gate metadata, and the stage only from
    explicit metadata or from the one event kind whose emit site is documented
    to put the stage in ``subtype``.
    """
    technical = getattr(event, "technical_metadata", None)
    technical = technical if isinstance(technical, Mapping) else {}

    def _explicit(name: str) -> str | None:
        value = technical.get(name)
        text = str(value).strip() if value is not None else ""
        return text or None

    # ``pending_gates`` wins over ``gate`` where both exist: the intended
    # split is ``gate`` for the single gate a rendered command clears (the CLI
    # takes one per invocation) and ``pending_gates`` for everything still
    # unmet. The reference line reports the state, not the command, so the
    # fuller fact is the right one to state.
    #
    # Today only ``gate_state_reconciliation_failed`` publishes ``gate``, and
    # nothing publishes ``pending_gates``: the pause emitter carries no gate
    # metadata at all, and giving it some would change its exact command,
    # which F005 may not do. Plan 2026-08-10-001 F001 owns that wiring.
    gate = _explicit("pending_gates") or _explicit("gate")
    stage = _explicit("stage")
    if stage is None and inbox_event in _SUBTYPE_IS_STAGE:
        subtype = getattr(event, "subtype", None)
        stage = str(subtype).strip() or None if subtype else None
    return gate, stage


def _reference_pair(name: str, value: str) -> str:
    """``gate `pre_merge``` — or ``gates `pre_impl`, `pre_merge``` for several.

    A pause can be blocked on more than one unmet gate, and the emitter passes
    them as one comma-separated value. Printing that inside a single pair of
    backticks would name a gate called ``pre_impl, pre_merge``, which does not
    exist; each is backticked separately and the label agrees in number.
    """
    values = [item.strip() for item in value.split(",") if item.strip()]
    if len(values) > 1:
        return f"{name}s " + ", ".join(f"`{item}`" for item in values)
    return f"{name} `{value}`"


def _reference_line(
    fields: Mapping[str, Any], gate: str | None, stage: str | None
) -> str:
    """The supporting reference line the headline's orchestration facts move to.

    Carries the plan label verbatim (so nothing the old headline said is lost),
    the feature when one is in scope, and the gate / stage when they are known.
    Unknown values are omitted rather than printed as ``-``: a reference line
    that names a gate it does not have is worse than one that stays quiet.
    """
    plan_label = str(fields.get("plan_label") or fields.get("plan_id") or "")
    feature_id = str(fields.get("feature_id") or "")
    if feature_id and feature_id != "-":
        if feature_id in plan_label:
            parts = [f"plan `{plan_label}`"]
        else:
            parts = [f"plan `{plan_label}`", f"feature `{feature_id}`"]
    else:
        parts = [f"plan `{plan_label}` ({PLAN_LEVEL_REFERENCE_MARKER})"]
    seen: set[str] = set()
    for name, value in (("gate", gate), ("stage", stage)):
        # A gate and a stage can legitimately carry the same value (the pause
        # emitter names the stage and the gate identically at `pre_merge`), and
        # one value under two names reads as two facts when it is only one.
        if value and value != "-" and value not in seen:
            seen.add(value)
            parts.append(_reference_pair(name, value))
    return "Reference: " + ", ".join(parts) + "."


#: First-class NotifyEvent fields copied onto the rendered event's technical
#: tail. Module-level (rather than inline at the loop) so the non-generative
#: scan can enumerate every attribute the one dynamic ``getattr(event, key)``
#: in this module can name, and check each against
#: :data:`_EVENT_ATTRIBUTES_READ`.
_RENDERED_TAIL_FIELDS: Final[tuple[str, ...]] = (
    "feature_id",
    "subtype",
    "iteration_count",
    "aggregate_class",
    "blocking",
    "target_env",
    "target_project",
)


def render(
    event: Any,
    plan_meta: Mapping[str, Any] | None = None,
    feature_meta: Mapping[str, Any] | None = None,
) -> "RenderedEvent | None":
    """Produce a RenderedEvent from a NotifyEvent, or None for non-rendered kinds.

    Lookup keying is ``event.inbox_event`` (the INBOX ``event=`` value, per
    D017). Returns ``None`` for ``inbox_only`` / ``audit_only`` dispositions,
    and for unknown / un-keyed events — callers fall back to the raw INBOX
    entry per plan.md § Implementation Strategy.
    """
    inbox_event = getattr(event, "inbox_event", None) or getattr(event, "kind", None)
    if not inbox_event:
        return None

    # D009 normalization: breaker:<kind> → breaker_tripped + breaker_kind override.
    normalized_key, kind_override = _normalize_inbox_event(inbox_event)
    if kind_override is not None and not getattr(event, "breaker_kind", None):
        # Pretend NotifyEvent.breaker_kind was set (without mutating the
        # frozen event itself). Use object.__setattr__ would violate the
        # event's frozen invariant; instead, inject via fields below.
        synthetic_breaker_kind = kind_override
    else:
        synthetic_breaker_kind = None

    if normalized_key not in DISPOSITION_TABLE:
        return None
    disposition = DISPOSITION_TABLE[normalized_key]
    if disposition in (Disposition.INBOX_ONLY, Disposition.AUDIT_ONLY):
        return None

    template = TRANSLATION_TABLE.get(normalized_key)
    if template is None:
        return None

    fields = _gather_fields(
        inbox_event=normalized_key,
        event=event,
        plan_meta=plan_meta,
        feature_meta=feature_meta,
    )
    if synthetic_breaker_kind is not None:
        fields["breaker_kind"] = synthetic_breaker_kind

    final_status = fields.get("final_status")
    if normalized_key == "volley_terminal" and final_status == "signed_off":
        headline = f"AI work finished on {fields['plan_label']}"
        why = (
            f"Volley completed after {fields['rounds']} round(s) with "
            "`signed_off`. No action needed."
        )
        command_raw: str | None = None
    else:
        headline = template.headline.format(**fields)
        why = template.why.format(**fields)
        command_raw = None
        if template.action is not None:
            command_raw = template.action.format(**fields)

    # D010 brand-drift normalization at render boundary.
    headline = normalize_brand_drift(headline) or headline
    why = normalize_brand_drift(why) or ""
    command_raw = normalize_brand_drift(command_raw)

    # D008 honest-commands rule: validate any non-None command, collapse on fail.
    validated_command: str | None = None
    if command_raw is not None:
        validated_command = _validate_exact_command(command_raw)

    band = _band_for(template, final_status)

    # ── F005: the impact-first rewrite of the renderable needs_action band ──
    #
    # Applied here, after the table copy is built, so the overlay is provably a
    # prose swap: ``validated_command`` is already resolved above and nothing
    # below can reach it. Three conditions gate the swap, and all three are
    # about honesty rather than taste:
    #
    #   * an overlay row exists — i.e. this is a renderable ``needs_action``
    #     kind. Advisory / info / ready copy is not an approval prompt.
    #   * the *resolved* band is still ``needs_action`` — volley_terminal's
    #     signed-off variant resolves to ``ready`` and keeps its own copy.
    #   * the event carries a brief. Without one there is no product claim to
    #     lead with and no reference line to demote anything to, so legacy
    #     emit sites keep their prior copy byte-for-byte.
    #
    # The reference line goes on whenever a brief is present, including the
    # undeclared / stale / plan-level cases where the headline falls back:
    # the plan label, gate and stage still belong in a supporting line, and
    # the fallback headline keeps them too, so nothing is stated only once and
    # then lost. Only the *lead* requires a declaration (D002/D005).
    brief = getattr(event, "decision_brief", None)
    impact = IMPACT_FIRST_TABLE.get(normalized_key)
    if impact is not None and band == _NEEDS_ACTION and brief is not None:
        if impact.why is not None:
            why = normalize_brand_drift(impact.why.format(**fields)) or ""
        gate, stage = _reference_gate_stage(normalized_key, event)
        reference = normalize_brand_drift(_reference_line(fields, gate, stage)) or ""
        # F006 — the honesty line sits between the body and the reference:
        # after the orchestration prose it qualifies, and before the reference
        # so "Reference: ..." stays the tail of the detail string. It is not
        # brand-normalized because the only variable part of it is the
        # brief-sourced summary, which passes through verbatim (D015).
        honesty = _impact_status_line(brief, fields)
        why = " ".join(part for part in (why, honesty, reference) if part).strip()
        lead = _impact_lead(brief)
        if lead is not None:
            reason = normalize_brand_drift(impact.reason.format(**fields)) or ""
            # The lead is spliced verbatim, not normalized: it is brief-sourced
            # copy, and F004 established that a snapshot taken upstream reaches
            # the operator byte-for-byte rather than being rewritten here.
            headline = f"{lead} — {reason}"

    # technical_metadata for the RenderedEvent: include everything callers
    # might need to reconstruct context (iteration, audit_path, breaker kind,
    # final_status). Skip None values for cleanliness.
    tech: dict[str, Any] = {}
    src_tech = getattr(event, "technical_metadata", None)
    if isinstance(src_tech, Mapping):
        for k, v in src_tech.items():
            if v is not None:
                tech[k] = v
    # First-class fields worth surfacing in the rendered tail. Read through the
    # module-level tuple rather than an inline one so :func:`scan_non_generative
    # _copy` can resolve what this dynamic ``getattr`` may name (F006).
    for key in _RENDERED_TAIL_FIELDS:
        val = getattr(event, key, None)
        if val is not None:
            tech.setdefault(key, val)
    if synthetic_breaker_kind is not None:
        tech.setdefault("breaker_kind", synthetic_breaker_kind)
    elif getattr(event, "breaker_kind", None):
        tech.setdefault("breaker_kind", event.breaker_kind)
    tech.setdefault("inbox_event", inbox_event)
    # The plan_id is useful for sidecar consumers that don't have NotifyEvent.
    tech.setdefault("plan_id", getattr(event, "plan_id", None) or "")

    brief_slots = _brief_fields(event, template, fields)

    return RenderedEvent(
        band=band,
        title=headline,
        detail=why,
        exact_command=validated_command,
        evidence_uri=_resolve_evidence_uri(event),
        disposition=disposition,
        technical_metadata=tech,
        # Already resolved by _brief_fields: brief-sourced slots verbatim,
        # table-fallback copy normalized. Nothing is rewritten here.
        what_changes=brief_slots["what_changes"],
        user_impact=brief_slots["user_impact"],
        affected_audience=brief_slots["affected_audience"],
        plain_consequence=brief_slots["plain_consequence"],
        reversible=brief_slots["reversible"],
    )


# ── F006: the source-level non-generative assertion (D002) ──────────────────
#
# D002 makes the render boundary strictly non-generative: no approval template
# body may be populated from model output at render time. That is a claim about
# this file, so it is checked against this file — the scan below parses the
# module's own source and reports anything that would let generated text reach
# an operator through a template.
#
# A test asserting "render() returns the expected string" cannot catch this: a
# renderer that called a model and happened to return the right text for the
# fixture would pass. What has to be pinned is the *shape* of the source — every
# template body a literal, no import that could reach a model, no dynamic
# execution — and that is what a reader of the diff would check by hand.

#: Module roots whose presence anywhere in this file would mean copy could
#: originate outside it: a network client, a subprocess, a vendor SDK, or one of
#: this package's own model-dispatch modules. ``command_validation`` (the one
#: project import, function-local in :func:`_validate_exact_command`) is
#: deliberately absent — it validates a command's token shape and authors no
#: copy.
_GENERATIVE_MODULE_ROOTS: Final[frozenset[str]] = frozenset(
    {
        "anthropic",
        "codex_stream",
        "executors",
        "http",
        "httpx",
        "openai",
        "prompts",
        "requests",
        "socket",
        "subprocess",
        "supervisor",
        "urllib",
    }
)

#: Builtins that turn data into executable code. A template body assembled by
#: any of these is not a source literal no matter how it reads.
_DYNAMIC_EXECUTION_BUILTINS: Final[frozenset[str]] = frozenset(
    {"compile", "eval", "exec", "__import__"}
)

#: The two copy tables, by the name each is bound to at module level, paired
#: with the constructor whose keyword arguments carry operator-visible text.
_COPY_TABLES: Final[Mapping[str, str]] = MappingProxyType(
    {"_TEMPLATES": "_Template", "_IMPACT_FIRST": "_ImpactFirst"}
)

#: Constructor keywords that reach the operator as prose or as a command.
_COPY_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "headline",
        "why",
        "action",
        "reason",
        "what_changes",
        "user_impact",
        "affected_audience",
    }
)

# ── Render-path provenance (F006 audit i0, finding 3) ───────────────────────
#
# Literal tables and a clean import list are necessary and not sufficient: a
# renderer whose tables are all literals can still overwrite the copy it just
# built with something read off the event at the last moment. The audit proved
# exactly that — an inserted ``why = getattr(event, "model_output", why)``
# inside :func:`render` left the old scan reporting zero violations.
#
# So the scan also follows the copy itself. Every local that ends up as
# operator-visible prose is named below, and every assignment to one of them,
# anywhere in this module, must be built from the small vocabulary that
# follows: source literals, the two copy tables, the honesty sentences, the
# formatting field set, and the handful of helpers that combine them. A name or
# a call from outside that vocabulary is a violation whether or not it happens
# to be a model today, because provenance that cannot be read off the source is
# provenance nobody is checking.

#: The functions that assemble operator-visible prose. The copy rules below are
#: applied inside exactly these, and the scan reports a violation if one of them
#: is missing — a rename that quietly moved the assembly out from under the
#: check would otherwise read as a clean pass.
#:
#: Everything else in this module is deliberately outside the copy rules and
#: covered by the event-attribute allowlist instead: :func:`_gather_fields`
#: exists precisely to read orchestration metadata off the event, and holding it
#: to "no event reads" would say nothing true.
_COPY_ASSEMBLY_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {
        "_impact_lead",
        "_impact_status_line",
        "_reference_line",
        "_reference_pair",
        "normalize_brand_drift",
        "render",
    }
)

#: The locals that become ``RenderedEvent.title`` / ``.detail`` /
#: ``.exact_command``, plus the clause-level pieces they are assembled from.
_COPY_VARIABLES: Final[frozenset[str]] = frozenset(
    {
        "command_raw",
        "feature_id",
        "headline",
        "honesty",
        "label",
        "lead",
        "out",
        "parts",
        "plan_label",
        "reason",
        "reference",
        "summary",
        "validated_command",
        "values",
        "why",
    }
)

#: Names a copy assignment may read. Everything here is either a copy local, a
#: copy table row, the operator-authored ``summary`` spliced verbatim per D015,
#: the ``fields`` mapping assembled by :func:`_gather_fields`, a module-level
#: copy constant, or a loop variable used to join clauses. ``event`` is
#: deliberately absent: that is the whole point of the check.
_COPY_SOURCE_NAMES: Final[frozenset[str]] = (
    _COPY_VARIABLES
    | _HONESTY_CONSTANT_NAMES
    | frozenset(
        {
            "PLAN_LEVEL_REFERENCE_MARKER",
            "STALE_IMPACT_TERMINATOR",
            "_AUDIENCE_LABELS",
            "_BRAND_REWRITES",
            "brief",
            "fields",
            "gate",
            "impact",
            "item",
            "legacy",
            "modern",
            "name",
            "part",
            "stage",
            "template",
            "text",
            "value",
        }
    )
)

#: Functions a copy assignment may call. Each is defined in this file and is
#: itself covered by the same rules — including ``_row``, the closure inside
#: :func:`_brief_fields` that formats a table-fallback slot: the walk descends
#: into nested definitions, so its ``return`` is checked in place.
_COPY_SOURCE_CALLS: Final[frozenset[str]] = frozenset(
    {
        "_feature_in_scope",
        "_impact_lead",
        "_impact_status_line",
        "_reference_line",
        "_reference_pair",
        "_row",
        "_validate_exact_command",
        "normalize_brand_drift",
    }
)

#: Builtins a copy assignment may call. All three only narrow or measure what
#: they are handed; none of them can introduce text that was not already there.
_COPY_SOURCE_BUILTINS: Final[frozenset[str]] = frozenset({"bool", "len", "str"})

#: String / mapping methods a copy assignment may call. ``format`` is how table
#: literals take their field values; the rest only trim, split and join what is
#: already there. Notably absent is anything that could fetch new text.
_COPY_SOURCE_METHODS: Final[frozenset[str]] = frozenset(
    {"format", "get", "join", "replace", "rstrip", "split", "strip"}
)

#: Methods a statement may call *on* a copy local for its side effect. Appending
#: to ``parts`` is how the reference line is built, and an unchecked mutation
#: would be exactly as good a smuggling route as an unchecked assignment.
_COPY_MUTATION_METHODS: Final[frozenset[str]] = frozenset({"append", "extend"})

#: Attributes a copy assignment may read, by the table local they hang off.
_COPY_SOURCE_ATTRIBUTES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        # The last three are the brief-slot fallback rows :func:`_brief_fields`
        # uses for events that carry no snapshot. Like the first three they are
        # ``_Template`` keywords, so check (1) has already verified each one is
        # a source literal.
        "template": frozenset(
            {
                "action",
                "affected_audience",
                "headline",
                "user_impact",
                "what_changes",
                "why",
            }
        ),
        "impact": frozenset({"reason", "why"}),
    }
)

#: Mappings a copy assignment may subscript. ``fields`` is the sanctioned
#: interpolation set; ``brief_slots`` is :func:`_brief_fields`' output, which is
#: the brief snapshot carried verbatim per D015.
_COPY_SOURCE_SUBSCRIPTS: Final[frozenset[str]] = frozenset(
    {"brief_slots", "fields"}
)

#: Module-level copy that is neither a template row nor an honesty sentence but
#: still reaches the operator: the audience prefix on an impact lead, the
#: plan-level reference marker, and the brand-drift rewrite pairs. Each must be
#: a nested literal, checked to its leaves.
_LITERAL_COPY_STRUCTURES: Final[frozenset[str]] = frozenset(
    {"_AUDIENCE_LABELS", "_BRAND_REWRITES"}
)

#: Single-string module-level copy outside the honesty set, held to the same
#: "must be a source literal" rule.
_LITERAL_COPY_MARKERS: Final[frozenset[str]] = frozenset(
    {"PLAN_LEVEL_REFERENCE_MARKER", "STALE_IMPACT_TERMINATOR"}
)

#: Call wrappers a literal structure may be built through. Both are read-only
#: views over the literal they are handed and add no text of their own.
_LITERAL_WRAPPERS: Final[frozenset[str]] = frozenset(
    {"MappingProxyType", "frozenset"}
)

#: Functions whose ``return`` values are operator-visible prose in their own
#: right — the F006 honesty sentences, the F005 impact lead, and the F004 brief
#: slots. Checked under the same rules as an assignment, so a fabricated claim
#: cannot enter by being returned rather than assigned.
#:
#: :func:`_brief_fields` is here because the audit found it was the one prose
#: path the scan did not follow: its four text slots become
#: ``RenderedEvent.user_impact`` and friends, and the construction-site rule
#: only pins that they are read out of ``brief_slots`` — not what
#: :func:`_brief_fields` put there. Rewriting ``brief.user_impact`` to
#: ``brief.model_output`` inside it produced a clean scan.
_COPY_RETURNING_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {"_brief_fields", "_impact_lead", "_impact_status_line"}
)

#: The name the ``DecisionBrief`` snapshot is bound to in this module — the
#: parameter of every helper that reads it, and the local :func:`_brief_fields`
#: binds it to. Same role as :data:`_EVENT_PARAM_NAME` for the event.
_BRIEF_LOCAL_NAME: Final[str] = "brief"

#: Every ``DecisionBrief`` attribute this module may read. The brief is a
#: declared copy source — it is the upstream snapshot, carried verbatim — but
#: "carried verbatim" is only worth anything if *which* fields are carried is
#: pinned. Without this, ``getattr(brief, "model_output", None)`` reads as a
#: legitimate brief splice, because ``brief`` itself is allowlisted; the fields
#: below are the ones :class:`decision_brief.DecisionBrief` actually declares,
#: and adding a name here is a visible, reviewable act.
_BRIEF_ATTRIBUTES_READ: Final[frozenset[str]] = frozenset(
    {
        "affected_audience",
        "decision_consequence",
        "reversible",
        "status",
        "user_impact",
        "what_changes",
    }
)

#: The ``RenderedEvent`` keywords that carry prose or a command. Each must be a
#: bare copy local at the construction site, so the value handed to the operator
#: is the one the rules above followed all the way down.
_RENDERED_COPY_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"title", "detail", "exact_command"}
)

#: The ``RenderedEvent`` brief slots (F004). These are not assembled from copy
#: locals at all — they are the upstream snapshot, carried verbatim — so the
#: rule is different in shape and identical in intent: each must be read out of
#: :func:`_brief_fields`' return value under a literal key, and nothing may be
#: substituted for it at the construction site.
_RENDERED_BRIEF_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"affected_audience", "plain_consequence", "user_impact", "what_changes"}
)

#: The local the brief slots must be read from.
_BRIEF_SLOT_SOURCE: Final[str] = "brief_slots"

#: The name every ``NotifyEvent`` is bound to in this module — the parameter of
#: :func:`render` and of every helper it hands the event to. The attribute check
#: keys off it, so a helper that took the event under another name would escape
#: the check; there is none, and the scan's own vocabulary makes adding one a
#: visible act.
_EVENT_PARAM_NAME: Final[str] = "event"

#: Every ``NotifyEvent`` attribute this module may read. The renderer legitimately
#: reads orchestration metadata off the event; what it may not do is grow a new
#: read without anyone noticing, which is how model-authored text would arrive.
#: Adding a name here is a visible, reviewable act — and the check is what makes
#: the audit's ``getattr(event, "model_output", ...)`` mutation fail the scan.
_EVENT_ATTRIBUTES_READ: Final[frozenset[str]] = frozenset(
    {
        "action_link",
        "aggregate_class",
        "blocking",
        "breaker_kind",
        "decision_brief",
        "evidence_uri",
        "feature_display_name",
        "feature_id",
        "inbox_event",
        "iteration_count",
        "kind",
        "plan_id",
        "subtype",
        "target_env",
        "target_project",
        "technical_metadata",
    }
)

#: Module-level tuples a dynamic ``getattr(event, key)`` may iterate. Their
#: members are checked against :data:`_EVENT_ATTRIBUTES_READ` too, so the
#: indirection buys no exemption.
_EVENT_ATTRIBUTE_SOURCES: Final[frozenset[str]] = frozenset({"_RENDERED_TAIL_FIELDS"})


@dataclasses.dataclass(frozen=True)
class NonGenerativeScan:
    """The result of :func:`scan_non_generative_copy`.

    ``violations`` empty is the assertion holding. The other two fields exist so
    a caller can prove the scan was not vacuous: a scan that silently matched no
    templates would otherwise report zero violations and look like a pass.
    """

    #: One human-readable line per violation, in source order.
    violations: tuple[str, ...]
    #: Table name → the keys whose copy keywords were verified as literals.
    template_keys: Mapping[str, tuple[str, ...]]
    #: How many individual copy keywords were inspected across all tables.
    copy_keywords_checked: int
    #: Honesty sentence constants (F006) verified as literals.
    honesty_constants: tuple[str, ...]
    #: How many render-path expressions had their provenance checked — copy
    #: assignments, honesty returns, and the ``RenderedEvent`` copy keywords.
    #: Zero would mean the provenance rules matched nothing and the scan was
    #: reporting a pass it never earned.
    copy_expressions_checked: int = 0
    #: Every ``NotifyEvent`` attribute name the source was found to read.
    event_attributes_seen: tuple[str, ...] = ()
    #: Every ``DecisionBrief`` attribute name the source was found to read.
    #: Empty would mean the brief-provenance rule matched nothing, which on a
    #: module that renders the brief is a vacuous pass, not a clean one.
    brief_attributes_seen: tuple[str, ...] = ()


def scan_non_generative_copy(source: str | None = None) -> NonGenerativeScan:
    """Assert at source level that no rendered copy can come from a model.

    Five things are checked, each corresponding to a way generated text could
    otherwise reach an approval prompt:

    1. **Every template body is a literal.** Each ``_Template`` / ``_ImpactFirst``
       keyword that carries operator-visible text must be a string (or ``None``)
       constant in this file. A name, a call, an f-string or a concatenation
       would all mean the body is computed, and a computed body is one edit away
       from being computed from model output. The honesty sentences and the
       other module-level copy (audience labels, brand rewrites, the plan-level
       marker) are held to the same rule.
    2. **Nothing here can reach a model.** No import — module-level or
       function-local — resolves to a network client, a subprocess, a vendor SDK
       or this package's own dispatch modules.
    3. **No dynamic execution.** ``eval`` / ``exec`` / ``compile`` /
       ``__import__`` appear nowhere, so no string can become code.
    4. **Render-path provenance.** Inside the copy-assembly functions, every
       assignment to a copy local, every mutation of one, every ``return`` from
       a copy-returning function, and every prose keyword at the
       ``RenderedEvent`` construction site is built only from the declared
       vocabulary — source literals, the copy tables, the honesty sentences,
       ``fields``, the brief snapshot, and the named helpers that combine them.
       This is what (1)-(3) miss: a module whose tables are all literals can
       still overwrite the copy it just built at the last moment, and the i1
       audit proved it by inserting ``why = getattr(event, "model_output", why)``
       into :func:`render` without tripping a single violation.
    5. **Event reads are enumerated.** Every ``NotifyEvent`` attribute this
       module reads — statically, or through the one dynamic ``getattr(event,
       key)`` and its module-level key tuple — appears in
       :data:`_EVENT_ATTRIBUTES_READ`. Model-authored text arriving on the event
       would have to arrive under some attribute name, and growing a new read
       is now a scan violation rather than a silent diff.

    ``source`` overrides the file read, which is how a test proves the scan
    actually fails on a violating source rather than passing vacuously.
    """
    # Imported here rather than at module scope: this module's import surface is
    # asserted pure-stdlib and minimal, and the scan is a check run by tests and
    # tools, not by render().
    import ast
    import pathlib

    if source is None:
        source = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    violations: list[str] = []
    template_keys: dict[str, tuple[str, ...]] = {}
    keywords_checked = 0
    honesty_seen: list[str] = []

    expressions_checked = 0
    attributes_seen: set[str] = set()
    brief_attributes_seen: set[str] = set()
    literal_structures_seen: set[str] = set()
    event_key_tuples: dict[str, Any] = {}

    def _literal(node: Any) -> bool:
        return isinstance(node, ast.Constant) and isinstance(
            node.value, (str, type(None))
        )

    def _literal_tree(node: Any) -> bool:
        """Whether every leaf of a nested literal is a str / ``None`` constant."""
        if _literal(node):
            return True
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return all(_literal_tree(elt) for elt in node.elts)
        if isinstance(node, ast.Dict):
            return all(
                key is not None and _literal_tree(key) for key in node.keys
            ) and all(_literal_tree(val) for val in node.values)
        if isinstance(node, ast.Call):
            wrapper = getattr(node.func, "id", None)
            if wrapper in _LITERAL_WRAPPERS and len(node.args) == 1:
                return _literal_tree(node.args[0])
        return False

    # ── (4) render-path provenance ──────────────────────────────────────────
    #
    # ``_check_copy`` walks one expression and reports every sub-expression that
    # falls outside the declared vocabulary. Unknown node kinds are violations
    # rather than passes: the check is an allowlist, so a construct nobody
    # thought about fails loudly instead of sliding through.

    def _check_copy(node: Any, where: str, bound: frozenset[str]) -> None:
        def _bad(reason: str) -> None:
            line = getattr(node, "lineno", "?")
            violations.append(
                f"line {line}: {where} {reason} — operator-visible copy must be "
                "built from source copy at render time, not from anything a "
                "model produced (D002)"
            )

        def _walk(current: Any, names: frozenset[str]) -> None:
            if current is None or isinstance(current, ast.Constant):
                return
            if isinstance(current, ast.Name):
                if current.id not in _COPY_SOURCE_NAMES and current.id not in names:
                    _bad(f"reads {current.id!r}, which is not a declared copy source")
                return
            if isinstance(current, ast.JoinedStr):
                for value in current.values:
                    _walk(value, names)
                return
            if isinstance(current, ast.FormattedValue):
                _walk(current.value, names)
                _walk(current.format_spec, names)
                return
            if isinstance(current, ast.BoolOp):
                for value in current.values:
                    _walk(value, names)
                return
            if isinstance(current, ast.IfExp):
                _walk(current.test, names)
                _walk(current.body, names)
                _walk(current.orelse, names)
                return
            if isinstance(current, ast.Compare):
                _walk(current.left, names)
                for comparator in current.comparators:
                    _walk(comparator, names)
                return
            if isinstance(current, ast.UnaryOp):
                _walk(current.operand, names)
                return
            if isinstance(current, ast.BinOp):
                # Concatenation and %-formatting join text that is already here;
                # any other operator on prose is a construct nobody reviewed.
                if not isinstance(current.op, (ast.Add, ast.Mod)):
                    _bad("combines copy with an operator other than + or %")
                    return
                _walk(current.left, names)
                _walk(current.right, names)
                return
            if isinstance(current, (ast.Tuple, ast.List, ast.Set)):
                for elt in current.elts:
                    _walk(elt, names)
                return
            if isinstance(current, ast.Dict):
                for key in current.keys:
                    _walk(key, names)
                for value in current.values:
                    _walk(value, names)
                return
            if isinstance(current, ast.Starred):
                _walk(current.value, names)
                return
            if isinstance(current, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
                inner = set(names)
                for generator in current.generators:
                    for target in ast.walk(generator.target):
                        if isinstance(target, ast.Name):
                            inner.add(target.id)
                scoped = frozenset(inner)
                for generator in current.generators:
                    _walk(generator.iter, scoped)
                    for condition in generator.ifs:
                        _walk(condition, scoped)
                _walk(current.elt, scoped)
                return
            if isinstance(current, ast.Attribute):
                owner = getattr(current.value, "id", None)
                allowed = _COPY_SOURCE_ATTRIBUTES.get(str(owner), frozenset())
                if current.attr not in allowed:
                    _bad(
                        f"reads attribute {owner}.{current.attr}, which is not a "
                        "declared copy-table row"
                    )
                return
            if isinstance(current, ast.Subscript):
                owner = getattr(current.value, "id", None)
                if owner not in _COPY_SOURCE_SUBSCRIPTS:
                    _bad(
                        f"subscripts {owner!r}, which is not a declared copy mapping"
                    )
                    return
                _walk(current.slice, names)
                return
            if isinstance(current, ast.Call):
                _walk_call(current, names)
                return
            _bad(f"uses {type(current).__name__}, which the copy rules do not allow")

        def _walk_call(current: Any, names: frozenset[str]) -> None:
            func = current.func
            if isinstance(func, ast.Name):
                if func.id == "getattr":
                    # The one call that could read anything off anything. It is
                    # allowed only against a declared copy source, which is
                    # precisely what makes ``getattr(event, ...)`` a violation.
                    target = current.args[0] if current.args else None
                    target_id = getattr(target, "id", None)
                    if target_id is None or (
                        target_id not in _COPY_SOURCE_NAMES and target_id not in names
                    ):
                        _bad(
                            f"reads copy off {target_id!r} via getattr(), which is "
                            "not a declared copy source"
                        )
                    for arg in current.args[1:]:
                        _walk(arg, names)
                elif func.id in _COPY_SOURCE_CALLS or func.id in _COPY_SOURCE_BUILTINS:
                    for arg in current.args:
                        _walk(arg, names)
                    for keyword in current.keywords:
                        _walk(keyword.value, names)
                else:
                    _bad(f"calls {func.id}(), which is not a declared copy source")
                return
            if isinstance(func, ast.Attribute):
                if func.attr not in _COPY_SOURCE_METHODS:
                    _bad(
                        f"calls .{func.attr}(), which is not a declared copy method"
                    )
                    return
                _walk(func.value, names)
                for arg in current.args:
                    _walk(arg, names)
                for keyword in current.keywords:
                    _walk(keyword.value, names)
                return
            _bad("calls an expression, so the callee cannot be read off the source")

        _walk(node, bound)

    for node in ast.walk(tree):
        # (2) imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _GENERATIVE_MODULE_ROOTS:
                    violations.append(
                        f"line {node.lineno}: imports {alias.name!r}, which could "
                        "carry generated text into this module"
                    )
        elif isinstance(node, ast.ImportFrom):
            parts = (node.module or "").split(".")
            names = [alias.name for alias in node.names]
            for candidate in [*parts, *names]:
                if candidate in _GENERATIVE_MODULE_ROOTS:
                    violations.append(
                        f"line {node.lineno}: imports {candidate!r} from "
                        f"{node.module!r}, which could carry generated text "
                        "into this module"
                    )
        # (3) dynamic execution
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in _DYNAMIC_EXECUTION_BUILTINS:
                violations.append(
                    f"line {node.lineno}: calls {name}(), which would let a "
                    "string become executable code"
                )

    # (1) template bodies — module-level assignments only, so a table shadowed
    # inside a function cannot masquerade as the real one.
    for node in tree.body:
        targets: list[Any]
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        value = node.value
        for target in targets:
            name = getattr(target, "id", None)
            if name in _COPY_TABLES:
                expected_ctor = _COPY_TABLES[str(name)]
                if not isinstance(value, ast.Dict):
                    violations.append(
                        f"line {node.lineno}: {name} is not a dict literal, so "
                        "its template bodies cannot be verified as source copy"
                    )
                    continue
                keys: list[str] = []
                # strict: an ``ast.Dict`` always pairs keys with values one for
                # one (``**spread`` contributes a ``None`` key, not a gap), so a
                # length mismatch would mean the parse is not what this code
                # believes and silently truncating it would under-report.
                for key_node, row in zip(value.keys, value.values, strict=True):
                    key = (
                        key_node.value
                        if isinstance(key_node, ast.Constant)
                        else f"<line {getattr(key_node, 'lineno', node.lineno)}>"
                    )
                    keys.append(str(key))
                    ctor = getattr(getattr(row, "func", None), "id", None)
                    if not isinstance(row, ast.Call) or ctor != expected_ctor:
                        violations.append(
                            f"{name}[{key!r}]: expected a {expected_ctor}(...) "
                            "literal row"
                        )
                        continue
                    for keyword in row.keywords:
                        if keyword.arg not in _COPY_KEYWORDS:
                            continue
                        keywords_checked += 1
                        if not _literal(keyword.value):
                            violations.append(
                                f"{name}[{key!r}].{keyword.arg} is not a source "
                                "literal — operator-visible copy must be written "
                                "in this file, not computed at render time (D002)"
                            )
                template_keys[str(name)] = tuple(keys)
            elif name in _HONESTY_CONSTANT_NAMES:
                honesty_seen.append(str(name))
                if not _literal(value):
                    violations.append(
                        f"{name} is not a source literal — the honesty sentences "
                        "are the one thing that may never be generated (D002)"
                    )
            elif name in _LITERAL_COPY_MARKERS:
                if not _literal(value):
                    violations.append(
                        f"{name} is not a source literal, so operator-visible "
                        "copy would be computed at render time (D002)"
                    )
            elif name in _LITERAL_COPY_STRUCTURES:
                literal_structures_seen.add(str(name))
                if not _literal_tree(value):
                    violations.append(
                        f"{name} is not a literal all the way to its leaves, so "
                        "operator-visible copy would be computed at render time "
                        "(D002)"
                    )
            elif name in _EVENT_ATTRIBUTE_SOURCES:
                event_key_tuples[str(name)] = value

    for missing in sorted(_HONESTY_CONSTANT_NAMES - set(honesty_seen)):
        violations.append(
            f"{missing} is registered as an honesty sentence but was not found "
            "as a module-level literal assignment"
        )
    for table in _COPY_TABLES:
        if table not in template_keys:
            violations.append(f"{table} was not found at module level")
    for missing_structure in sorted(_LITERAL_COPY_STRUCTURES - literal_structures_seen):
        violations.append(
            f"{missing_structure} is registered as module-level copy but was not "
            "found as a module-level literal assignment"
        )

    # ── (4) walk the copy-assembly functions ────────────────────────────────
    assembly_seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in _COPY_ASSEMBLY_FUNCTIONS:
            assembly_seen.add(node.name)
        elif node.name not in _COPY_RETURNING_FUNCTIONS:
            continue
        # Parameters are bound names inside their own function: a helper that
        # takes ``summary`` as an argument is being handed copy by a caller the
        # rules already checked. The event itself is the one exception — it is
        # a parameter of :func:`render` and is still never a copy source, so
        # binding must not quietly readmit it. Without this subtraction, adding
        # one name to :data:`_EVENT_ATTRIBUTES_READ` would be enough to make
        # ``why = getattr(event, "model_output", why)`` pass both checks.
        params = node.args
        bound = frozenset(
            arg.arg
            for arg in [
                *params.posonlyargs,
                *params.args,
                *params.kwonlyargs,
                *([params.vararg] if params.vararg else []),
                *([params.kwarg] if params.kwarg else []),
            ]
        ) - {_EVENT_PARAM_NAME}
        in_assembly = node.name in _COPY_ASSEMBLY_FUNCTIONS
        returns_copy = node.name in _COPY_RETURNING_FUNCTIONS
        for inner in ast.walk(node):
            if returns_copy and isinstance(inner, ast.Return):
                expressions_checked += 1
                _check_copy(inner.value, f"{node.name}() returns a value that", bound)
                continue
            if not in_assembly:
                continue
            targets: list[Any] = []
            value: Any = None
            if isinstance(inner, ast.Assign):
                targets, value = list(inner.targets), inner.value
            elif isinstance(inner, (ast.AnnAssign, ast.AugAssign)):
                targets, value = [inner.target], inner.value
            elif isinstance(inner, ast.Expr) and isinstance(inner.value, ast.Call):
                # A mutation of a copy local — ``parts.append(...)``.
                func = inner.value.func
                owner = getattr(getattr(func, "value", None), "id", None)
                if owner in _COPY_VARIABLES:
                    expressions_checked += 1
                    attr = getattr(func, "attr", "")
                    if attr not in _COPY_MUTATION_METHODS:
                        violations.append(
                            f"line {inner.lineno}: {node.name}() calls "
                            f"{owner}.{attr}(), which is not a declared way to "
                            "change operator-visible copy (D002)"
                        )
                    else:
                        for arg in inner.value.args:
                            _check_copy(
                                arg, f"{node.name}() appends a value that", bound
                            )
                continue
            else:
                continue
            for target in targets:
                if getattr(target, "id", None) in _COPY_VARIABLES:
                    expressions_checked += 1
                    _check_copy(
                        value,
                        f"{node.name}() assigns {target.id} a value that",
                        bound,
                    )

    for missing_fn in sorted(_COPY_ASSEMBLY_FUNCTIONS - assembly_seen):
        violations.append(
            f"{missing_fn}() is registered as a copy-assembly function but was "
            "not found — the render-path provenance check cannot have run over it"
        )

    # ── (4b) the RenderedEvent construction site ────────────────────────────
    construction_seen = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "RenderedEvent":
            continue
        construction_seen = True
        for keyword in node.keywords:
            if keyword.arg in _RENDERED_COPY_KEYWORDS:
                expressions_checked += 1
                name = getattr(keyword.value, "id", None)
                if name not in _COPY_VARIABLES:
                    violations.append(
                        f"line {node.lineno}: RenderedEvent.{keyword.arg} is not "
                        "one of the copy locals the rules followed, so what the "
                        "operator sees is not what was checked (D002)"
                    )
            elif keyword.arg in _RENDERED_BRIEF_KEYWORDS:
                expressions_checked += 1
                slot = keyword.value
                owner = getattr(getattr(slot, "value", None), "id", None)
                if not isinstance(slot, ast.Subscript) or owner != _BRIEF_SLOT_SOURCE:
                    violations.append(
                        f"line {node.lineno}: RenderedEvent.{keyword.arg} is not "
                        f"read from {_BRIEF_SLOT_SOURCE}, so a brief slot could "
                        "carry something other than the upstream snapshot (D002)"
                    )
    if not construction_seen:
        violations.append(
            "no RenderedEvent(...) construction was found, so the keywords the "
            "operator actually sees were never checked"
        )

    # ── (5) enumerated event reads ──────────────────────────────────────────
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if getattr(node.value, "id", None) != _EVENT_PARAM_NAME:
                continue
            attributes_seen.add(node.attr)
            if node.attr not in _EVENT_ATTRIBUTES_READ:
                violations.append(
                    f"line {node.lineno}: reads event.{node.attr}, which is not "
                    "an enumerated NotifyEvent attribute (D002)"
                )
            continue
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "getattr" or not node.args:
            continue
        if getattr(node.args[0], "id", None) != _EVENT_PARAM_NAME:
            continue
        key = node.args[1] if len(node.args) > 1 else None
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            attributes_seen.add(key.value)
            if key.value not in _EVENT_ATTRIBUTES_READ:
                violations.append(
                    f"line {node.lineno}: reads event.{key.value} via getattr(), "
                    "which is not an enumerated NotifyEvent attribute (D002)"
                )
            continue
        # A dynamic key: it must be the loop variable of a declared key tuple,
        # and every member of that tuple is checked in its place.
        source = next(
            (
                name
                for name, tuple_node in event_key_tuples.items()
                if isinstance(tuple_node, (ast.Tuple, ast.List))
            ),
            None,
        )
        if source is None:
            violations.append(
                f"line {node.lineno}: reads an event attribute under a key this "
                "scan cannot resolve to a declared key tuple (D002)"
            )
            continue
        for member in event_key_tuples[source].elts:
            if not _literal(member) or not isinstance(member.value, str):
                violations.append(
                    f"{source} carries a non-literal key, so the attributes it "
                    "names cannot be enumerated (D002)"
                )
                continue
            attributes_seen.add(member.value)
            if member.value not in _EVENT_ATTRIBUTES_READ:
                violations.append(
                    f"{source} names event.{member.value}, which is not an "
                    "enumerated NotifyEvent attribute (D002)"
                )
    for missing_source in sorted(_EVENT_ATTRIBUTE_SOURCES - set(event_key_tuples)):
        violations.append(
            f"{missing_source} is registered as a dynamic event-key tuple but was "
            "not found at module level"
        )

    # ── (6) enumerated brief reads ──────────────────────────────────────────
    #
    # The same rule as (5), one object over. ``brief`` is an allowlisted copy
    # source because the snapshot is carried verbatim, and that allowlisting is
    # what made it a hole: the copy rules happily accept any attribute read off
    # a declared source, so ``getattr(brief, "model_output", None)`` inside
    # :func:`_brief_fields` looked exactly like a legitimate splice and the i2
    # audit demonstrated it scanning clean. Pinning the field names closes it.
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if getattr(node.value, "id", None) != _BRIEF_LOCAL_NAME:
                continue
            brief_attributes_seen.add(node.attr)
            if node.attr not in _BRIEF_ATTRIBUTES_READ:
                violations.append(
                    f"line {node.lineno}: reads brief.{node.attr}, which is not "
                    "an enumerated DecisionBrief attribute (D002)"
                )
            continue
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "getattr" or not node.args:
            continue
        if getattr(node.args[0], "id", None) != _BRIEF_LOCAL_NAME:
            continue
        key = node.args[1] if len(node.args) > 1 else None
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            brief_attributes_seen.add(key.value)
            if key.value not in _BRIEF_ATTRIBUTES_READ:
                violations.append(
                    f"line {node.lineno}: reads brief.{key.value} via getattr(), "
                    "which is not an enumerated DecisionBrief attribute (D002)"
                )
            continue
        # No dynamic-key escape hatch here, unlike the event: nothing reads the
        # brief under a computed name, and a key this scan cannot resolve is a
        # brief slot nobody enumerated.
        violations.append(
            f"line {node.lineno}: reads a brief attribute under a key this scan "
            "cannot resolve to a literal name (D002)"
        )

    return NonGenerativeScan(
        violations=tuple(violations),
        template_keys=MappingProxyType(dict(template_keys)),
        copy_keywords_checked=keywords_checked,
        honesty_constants=tuple(sorted(honesty_seen)),
        copy_expressions_checked=expressions_checked,
        event_attributes_seen=tuple(sorted(attributes_seen)),
        brief_attributes_seen=tuple(sorted(brief_attributes_seen)),
    )


__all__ = [
    "DISPOSITION_TABLE",
    "INBOX_EVENT_KINDS",
    "NO_USER_IMPACT_SENTENCE",
    "PLAN_LEVEL_UNDECLARED_IMPACT_SENTENCE",
    "STALE_IMPACT_PREFIX",
    "STALE_IMPACT_WITHOUT_SUMMARY_SENTENCE",
    "TRANSLATION_TABLE",
    "UNDECLARED_IMPACT_SENTENCE",
    "Disposition",
    "NonGenerativeScan",
    "RenderedEvent",
    "disposition_for",
    "normalize_brand_drift",
    "render",
    "scan_non_generative_copy",
]
