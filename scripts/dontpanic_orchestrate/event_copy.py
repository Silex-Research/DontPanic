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
    """

    band: str
    title: str
    detail: str | None
    exact_command: str | None
    evidence_uri: str | None
    disposition: Disposition
    technical_metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)

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
    """

    band: str
    headline: str
    why: str
    action: str | None


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
    why = normalize_brand_drift(why)
    command_raw = normalize_brand_drift(command_raw)

    # D008 honest-commands rule: validate any non-None command, collapse on fail.
    validated_command: str | None = None
    if command_raw is not None:
        validated_command = _validate_exact_command(command_raw)

    band = _band_for(template, final_status)

    # technical_metadata for the RenderedEvent: include everything callers
    # might need to reconstruct context (iteration, audit_path, breaker kind,
    # final_status). Skip None values for cleanliness.
    tech: dict[str, Any] = {}
    src_tech = getattr(event, "technical_metadata", None)
    if isinstance(src_tech, Mapping):
        for k, v in src_tech.items():
            if v is not None:
                tech[k] = v
    # First-class fields worth surfacing in the rendered tail:
    for key in (
        "feature_id",
        "subtype",
        "iteration_count",
        "aggregate_class",
        "blocking",
        "target_env",
        "target_project",
    ):
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

    return RenderedEvent(
        band=band,
        title=headline,
        detail=why,
        exact_command=validated_command,
        evidence_uri=_resolve_evidence_uri(event),
        disposition=disposition,
        technical_metadata=tech,
    )


__all__ = [
    "DISPOSITION_TABLE",
    "Disposition",
    "INBOX_EVENT_KINDS",
    "RenderedEvent",
    "TRANSLATION_TABLE",
    "disposition_for",
    "normalize_brand_drift",
    "render",
]
