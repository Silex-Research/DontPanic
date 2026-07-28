"""Plan 2026-05-01-002 F002 — compact NotifyEvent envelope + dispatcher.

Two responsibilities:

1. ``NotifyEvent`` — frozen dataclass that both sinks consume. Closed
   severity vocabulary; closed plan-boundary kind set; ``action_link`` is
   REQUIRED when severity is ``escalation`` (constructor invariant).

2. ``dispatch_event`` — fans the event to all sinks honoring the
   ``DONTPANIC_NOTIFY_LEVEL`` (legacy ``JARVIS_NOTIFY_LEVEL``) filter.
   Returns ``{terminal: bool, discord: bool, buzz: bool, ...}``. Never
   raises — sink
   exceptions are swallowed and recorded as ``False`` in the result map.

Level matrix:
  - ``quiet`` → severity == 'escalation' only.
  - ``normal`` (default) → severity in {action_required, escalation}
    OR kind in PLAN_BOUNDARY_KINDS (volley_start / volley_terminal /
    signoff).
  - ``verbose`` → every event.

Adding a new sink requires no changes to emit sites: they call
``dispatch_event`` with a ``NotifyEvent``. Adding a new sink is a single
call inside :func:`dispatch_event`.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from dataclasses import dataclass, field
from typing import Final

from dontpanic_orchestrate import notify, notify_buzz, notify_discord

SEVERITY_INFO: Final[str] = "info"
SEVERITY_ACTION_REQUIRED: Final[str] = "action_required"
SEVERITY_ESCALATION: Final[str] = "escalation"
_VALID_SEVERITIES: Final[frozenset[str]] = frozenset(
    {SEVERITY_INFO, SEVERITY_ACTION_REQUIRED, SEVERITY_ESCALATION}
)

# Closed set — kinds that pass the ``normal`` level filter even at info
# severity. Future kinds added explicitly here, not implicitly.
PLAN_BOUNDARY_KINDS: Final[frozenset[str]] = frozenset(
    {"volley_start", "volley_terminal", "signoff"}
)

LEVEL_QUIET: Final[str] = "quiet"
LEVEL_NORMAL: Final[str] = "normal"
LEVEL_VERBOSE: Final[str] = "verbose"
_VALID_LEVELS: Final[frozenset[str]] = frozenset(
    {LEVEL_QUIET, LEVEL_NORMAL, LEVEL_VERBOSE}
)

_LEVEL_ENV_MODERN: Final[str] = "DONTPANIC_NOTIFY_LEVEL"
_LEVEL_ENV_LEGACY: Final[str] = "JARVIS_NOTIFY_LEVEL"

# Warn-once dedup so a misconfigured level env doesn't spam stderr.
_level_warned: set[str] = set()


def _reset_level_warn_cache() -> None:
    _level_warned.clear()


@dataclass(frozen=True)
class NotifyEvent:
    """Compact event envelope shared by all notify sinks.

    Fields:
      kind: extensible vocabulary (volley_start, gate_paused,
        breaker_tripped, signoff, calibration_required, ...).
      severity: closed vocabulary (info / action_required / escalation).
      plan_id: the plan whose volley emitted the event.
      feature_id: optional — None for plan-level events.
      body: markdown content rendered directly by all sinks.
      action_link: DEPRECATED alias for ``evidence_uri`` (plan 2026-05-24-004
        D005). Optional file path / file:// URL pointing to where the
        operator should look (INBOX.md, signoff.json, etc.). REQUIRED when
        severity == 'escalation' — emit sites without a link are caller
        bugs. New code should populate ``evidence_uri`` instead; both names
        read the same underlying storage and remain in lock-step.
      timestamp: tz-aware UTC datetime.
      inbox_event: the INBOX ``event=`` value used at the paired
        :func:`inbox.append_event` call (plan 2026-05-24-004 D017). Acts as
        the translation-table key for ``event_copy``. Populated at every
        new emit site; existing emit sites populate where the INBOX event
        name is known.
      subtype, breaker_kind, iteration_count, feature_display_name,
      aggregate_class, blocking, target_env, target_project: optional
        first-class metadata fields (plan 2026-05-24-004 D004). All
        default to ``None`` so existing emit sites continue to work
        without populating them.
      evidence_uri: preferred name for ``action_link`` (plan 2026-05-24-004
        D005). Aliases ``action_link``; both fields read the same storage.
      technical_metadata: long-tail kind-specific data per plan
        2026-05-24-004 D017 — kept out of the first-class field set when
        the value is only meaningful to one kind (verdict_mismatch's
        ``narrative_verdict``/``structured_status``/``audit_path``;
        defer_tripped's ``defer_gate``/``dispatch_class``;
        volley_terminal's ``final_status``/``rounds``;
        gate_state_reconciliation_failed's ``persisted_state_path``;
        etc.). Empty dict by default.
    """

    kind: str
    severity: str
    plan_id: str
    feature_id: str | None
    body: str
    action_link: str | None = None
    timestamp: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc)
    )
    inbox_event: str | None = None
    subtype: str | None = None
    breaker_kind: str | None = None
    iteration_count: int | None = None
    feature_display_name: str | None = None
    aggregate_class: str | None = None
    blocking: bool | None = None
    target_env: str | None = None
    target_project: str | None = None
    evidence_uri: str | None = None
    technical_metadata: dict[str, str | int | bool | None] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        # D005 alias reconciliation: action_link and evidence_uri are two
        # names for the same value. If both are provided they must agree;
        # otherwise the unset side is back-filled so downstream sinks can
        # read either name and get the same answer.
        if self.action_link is not None and self.evidence_uri is not None:
            if self.action_link != self.evidence_uri:
                raise ValueError(
                    "NotifyEvent: action_link and evidence_uri were both "
                    f"provided with different values ({self.action_link!r} "
                    f"!= {self.evidence_uri!r}). Pass only one — they are "
                    "aliases for the same field."
                )
        elif self.evidence_uri is not None:
            object.__setattr__(self, "action_link", self.evidence_uri)
        elif self.action_link is not None:
            object.__setattr__(self, "evidence_uri", self.action_link)

        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"NotifyEvent.severity must be one of {sorted(_VALID_SEVERITIES)}; "
                f"got {self.severity!r}"
            )
        if self.severity == SEVERITY_ESCALATION and not self.action_link:
            raise ValueError(
                "NotifyEvent: action_link is required when severity=='escalation'. "
                "Escalation events MUST link the operator to the source artifact "
                "(INBOX.md / signoff.json / sidecar) so the actionable signal is "
                "always one click away."
            )


def _read_level() -> str:
    """Resolve the active level env. Modern wins; legacy fallback; unknown
    falls back to ``normal`` with a warn-once."""
    raw = os.environ.get(_LEVEL_ENV_MODERN, "").strip().lower()
    if not raw:
        raw = os.environ.get(_LEVEL_ENV_LEGACY, "").strip().lower()
    if not raw:
        return LEVEL_NORMAL
    if raw not in _VALID_LEVELS:
        if raw not in _level_warned:
            _level_warned.add(raw)
            print(
                f"[notify_event] unknown DONTPANIC_NOTIFY_LEVEL={raw!r}; "
                f"falling back to {LEVEL_NORMAL!r}.",
                file=sys.stderr,
            )
        return LEVEL_NORMAL
    return raw


def _allowed_at_level(event: NotifyEvent) -> bool:
    """Pure filter: decide whether ``event`` is delivered at the active
    level. Single source of truth for the matrix; tests pin it directly."""
    level = _read_level()
    if level == LEVEL_VERBOSE:
        return True
    if event.severity == SEVERITY_ESCALATION:
        return True
    if level == LEVEL_QUIET:
        return False
    # level == LEVEL_NORMAL.
    if event.severity == SEVERITY_ACTION_REQUIRED:
        return True
    return event.kind in PLAN_BOUNDARY_KINDS


SINK_TERMINAL: Final[str] = "terminal"
SINK_DISCORD: Final[str] = "discord"
SINK_BUZZ: Final[str] = "buzz"
ALL_SINKS: Final[tuple[str, ...]] = (SINK_TERMINAL, SINK_DISCORD, SINK_BUZZ)


def dispatch_event(
    event: NotifyEvent,
    *,
    sinks: tuple[str, ...] = ALL_SINKS,
    plan_dir=None,
) -> dict[str, bool]:
    """Fan ``event`` to the named sinks honoring the level filter.

    ``sinks`` defaults to all configured sinks. Pass a narrower tuple to
    skip a sink — e.g. ``sinks=("discord",)`` when the caller has already
    fired the terminal notifier directly with a richer kind-specific
    title (transitional pattern while supervisor emit sites keep their
    existing :func:`notify.notify` calls; once those are removed, every
    emit site goes back to the default).

    Plan 2026-05-24-004 F003: when the event's ``inbox_event`` maps to a
    ``live`` or ``dashboard_action`` disposition, the event_copy renderer
    produces a RenderedEvent that drives a sidecar JSONL append and an
    optional INBOX rendered-annotation block (when ``plan_dir`` is in
    scope). Both writes are best-effort — failures suppress and never
    crash supervisor flow.

    Returns a dict naming each sink's outcome — useful for tests and for
    operator diagnostics. Never raises: a sink that throws is captured
    and recorded as ``False`` so a misbehaving sink can't break supervisor
    flow.

    INVARIANT documented for emit-site authors: the durable INBOX write
    MUST happen BEFORE calling :func:`dispatch_event`. INBOX is the
    truth-of-record; live notifications are advisory and may be silenced
    or fail without affecting plan progress.
    """
    out: dict[str, bool] = {
        "terminal": False,
        "discord": False,
        "buzz": False,
        "sidecar": False,
        "inbox_annotation": False,
    }
    if not _allowed_at_level(event):
        # Even when filtered out for live sinks, render for sidecar so the
        # dashboard still reflects the event. The level filter governs the
        # noisy live channels (Discord + terminal) but the sidecar / INBOX
        # annotation are durable surfaces the operator browses on demand —
        # no reason to silence them on quiet-level.
        pass

    # Resolve disposition once via event_copy.render(); a None return means
    # the event doesn't render (inbox_only / audit_only / unknown).
    rendered = None
    known_disposition: str | None = None
    try:
        from dontpanic_orchestrate import event_copy

        rendered = event_copy.render(event)
        # When render() returns None we still want to know whether the
        # inbox_event is a *known* non-rendered kind (inbox_only / audit_only)
        # versus an unknown / legacy kind. Suppressing live sinks for the
        # former is required by F003 acceptance #10 + audit finding (i0).
        inbox_event_key = (
            getattr(event, "inbox_event", None) or getattr(event, "kind", None)
        )
        if inbox_event_key:
            # D009 normalization: collapse the one authorized legacy
            # colon-key (breaker:patch_incomplete) to breaker_tripped
            # before the table lookup. Any other breaker:<unknown>
            # value falls through unrendered (its DISPOSITION_TABLE
            # lookup misses), so an unknown breaker kind never reaches
            # live sinks via this path.
            if inbox_event_key == "breaker:patch_incomplete":
                inbox_event_key = "breaker_tripped"
            disp = event_copy.DISPOSITION_TABLE.get(inbox_event_key)
            if disp is not None:
                known_disposition = disp.value
    except Exception as exc:  # noqa: BLE001 — render failures must not crash
        print(
            f"[notify_event] event_copy.render raised {type(exc).__name__}; suppressed.",
            file=sys.stderr,
        )
        rendered = None
        known_disposition = None

    level_allows_live = _allowed_at_level(event)
    disposition = getattr(rendered, "disposition", None) if rendered is not None else None
    # event_copy.Disposition values: "live", "dashboard_action", "inbox_only",
    # "audit_only". Compare by .value to avoid an import-time coupling to
    # event_copy here.
    disp_value = disposition.value if disposition is not None else known_disposition
    is_live = disp_value == "live"
    is_dashboard_action = disp_value == "dashboard_action"
    # A *known* non-rendered disposition (inbox_only / audit_only) must NOT
    # fan out to terminal / Discord — the legacy fallback path below only
    # fires when the disposition is genuinely unknown (e.g. ad-hoc test
    # events without an entry in DISPOSITION_TABLE).
    is_known_non_live = disp_value in {"inbox_only", "audit_only"}

    if SINK_TERMINAL in sinks and level_allows_live and is_live:
        try:
            # F003 audit finding (i1): pass the already-produced
            # RenderedEvent so the terminal sink does not re-render.
            out["terminal"] = bool(notify.notify_event(event, rendered=rendered))
        except Exception as exc:  # noqa: BLE001 — sinks must never propagate.
            print(
                f"[notify_event] terminal sink raised {type(exc).__name__}; suppressed.",
                file=sys.stderr,
            )
    if SINK_DISCORD in sinks and level_allows_live and is_live:
        try:
            # F003 audit finding (i1): pass the already-produced
            # RenderedEvent so the Discord sink does not re-render.
            out["discord"] = bool(notify_discord.notify(event, rendered=rendered))
        except Exception as exc:  # noqa: BLE001 — sinks must never propagate.
            print(
                f"[notify_event] discord sink raised {type(exc).__name__}; suppressed.",
                file=sys.stderr,
            )
    if SINK_BUZZ in sinks and level_allows_live and is_live:
        try:
            # Plan 2026-07-27-001 F006: Buzz sink fans out alongside Discord,
            # consuming the same already-produced RenderedEvent. Fail-soft —
            # unconfigured Buzz records False without raising.
            out["buzz"] = bool(notify_buzz.notify(event, rendered=rendered))
        except Exception as exc:  # noqa: BLE001 — sinks must never propagate.
            print(
                f"[notify_event] buzz sink raised {type(exc).__name__}; suppressed.",
                file=sys.stderr,
            )

    # Sidecar + INBOX annotation: fire for both live AND dashboard_action.
    # Per plan.md § Implementation Strategy + D003 + D018:
    #   live              → discord + terminal + sidecar + INBOX annotation
    #   dashboard_action  → sidecar + INBOX annotation only
    if rendered is not None and (is_live or is_dashboard_action):
        try:
            from dontpanic_orchestrate import operator_console

            operator_console.write_event_action_sidecar(rendered)
            out["sidecar"] = True
        except Exception as exc:  # noqa: BLE001 — sidecar write is best-effort
            print(
                f"[notify_event] sidecar write raised {type(exc).__name__}; suppressed.",
                file=sys.stderr,
            )
        if plan_dir is not None:
            try:
                from dontpanic_orchestrate import inbox

                inbox.append_rendered_annotation(
                    plan_dir,
                    plan_id=event.plan_id,
                    rendered=rendered,
                )
                out["inbox_annotation"] = True
            except Exception as exc:  # noqa: BLE001 — annotation is best-effort
                print(
                    f"[notify_event] INBOX annotation raised {type(exc).__name__}; suppressed.",
                    file=sys.stderr,
                )

    # Legacy compatibility: when the renderer returned None *and* the
    # inbox_event is genuinely unknown (no DISPOSITION_TABLE entry), still
    # honor the original sink fan-out so existing tests / direct callers
    # without a translation entry keep working. Known non-rendered
    # dispositions (inbox_only / audit_only) MUST NOT reach live sinks per
    # F003 acceptance + plan.md § Translation Disposition.
    if rendered is None and level_allows_live and not is_known_non_live:
        if SINK_TERMINAL in sinks and not out["terminal"]:
            try:
                out["terminal"] = bool(notify.notify_event(event))
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[notify_event] terminal sink (legacy path) raised "
                    f"{type(exc).__name__}; suppressed.",
                    file=sys.stderr,
                )
        if SINK_DISCORD in sinks and not out["discord"]:
            try:
                out["discord"] = bool(notify_discord.notify(event))
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[notify_event] discord sink (legacy path) raised "
                    f"{type(exc).__name__}; suppressed.",
                    file=sys.stderr,
                )
        if SINK_BUZZ in sinks and not out["buzz"]:
            try:
                out["buzz"] = bool(notify_buzz.notify(event))
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[notify_event] buzz sink (legacy path) raised "
                    f"{type(exc).__name__}; suppressed.",
                    file=sys.stderr,
                )
    return out


__all__ = [
    "ALL_SINKS",
    "LEVEL_NORMAL",
    "LEVEL_QUIET",
    "LEVEL_VERBOSE",
    "NotifyEvent",
    "PLAN_BOUNDARY_KINDS",
    "SEVERITY_ACTION_REQUIRED",
    "SEVERITY_ESCALATION",
    "SEVERITY_INFO",
    "SINK_BUZZ",
    "SINK_DISCORD",
    "SINK_TERMINAL",
    "dispatch_event",
]
