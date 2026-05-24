"""Event messaging v1 — RenderedEvent contract + translation disposition table.

Plan ``2026-05-24-004-feat-event-messaging-v1`` F001. This module ships the
contracts that F003 will populate; no copy text or render logic is committed
here.

Two artifacts live in this module:

1. :class:`RenderedEvent` — a frozen dataclass whose fields are a near-perfect
   subset of :class:`dontpanic_orchestrate.operator_console.ActionItem`
   (``band``, ``title``, ``detail``, ``exact_command``, ``evidence_uri``) plus
   two messaging-specific additions: ``disposition`` (the F001 verdict that
   routes a kind to its sinks) and ``technical_metadata`` (the long-tail
   structured bag per D017). A ``headline`` accessor returns the value used as
   the terminal-notifier message body — defined as ``title`` per the four-layer
   message anatomy in ``plan.md`` § *Product Model*.

2. :data:`DISPOSITION_TABLE` — a mapping keyed by the INBOX ``event=`` string
   (the same string the paired ``inbox.append_event`` call uses; F002 will add
   the matching ``inbox_event`` field on ``NotifyEvent`` per D017). Every one
   of the 27 INBOX event names enumerated in
   ``evidence/f001-inventory-draft.md`` Section 2 receives exactly one
   :class:`Disposition` verdict. Totality is enforced by test.

This module deliberately defines no copy templates — F003 owns
``event_copy.render(event, plan_meta, feature_meta) -> RenderedEvent`` and the
translation table that materializes RenderedEvents from NotifyEvents.
"""

from __future__ import annotations

import dataclasses
import enum
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
    # No live notify in v1, but operator-actionable — surface as INBOX entry:
    "blocked_no_findings": Disposition.INBOX_ONLY,
    "config_required": Disposition.INBOX_ONLY,
    "defer_tripped": Disposition.INBOX_ONLY,
    "error": Disposition.INBOX_ONLY,
    "feature_operator_resolved": Disposition.INBOX_ONLY,
    "nested_child_pending": Disposition.INBOX_ONLY,
    "quota_warn": Disposition.INBOX_ONLY,
    "unit_mismatch": Disposition.INBOX_ONLY,
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
