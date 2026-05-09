"""Plan 2026-05-01-002 F002 — compact NotifyEvent envelope + dispatcher.

Two responsibilities:

1. ``NotifyEvent`` — frozen dataclass that both sinks consume. Closed
   severity vocabulary; closed plan-boundary kind set; ``action_link`` is
   REQUIRED when severity is ``escalation`` (constructor invariant).

2. ``dispatch_event`` — fans the event to all sinks honoring the
   ``DONTPANIC_NOTIFY_LEVEL`` (legacy ``JARVIS_NOTIFY_LEVEL``) filter.
   Returns ``{terminal: bool, discord: bool}``. Never raises — sink
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
from dataclasses import dataclass
from typing import Final

from dontpanic_orchestrate import notify, notify_discord


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
      action_link: optional file path / file:// URL pointing to where
        the operator should look (INBOX.md, signoff.json, etc.).
        REQUIRED when severity == 'escalation' — emit sites without a
        link are caller bugs.
      timestamp: tz-aware UTC datetime.
    """

    kind: str
    severity: str
    plan_id: str
    feature_id: str | None
    body: str
    action_link: str | None
    timestamp: dt.datetime

    def __post_init__(self) -> None:
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
ALL_SINKS: Final[tuple[str, ...]] = (SINK_TERMINAL, SINK_DISCORD)


def dispatch_event(
    event: NotifyEvent,
    *,
    sinks: tuple[str, ...] = ALL_SINKS,
) -> dict[str, bool]:
    """Fan ``event`` to the named sinks honoring the level filter.

    ``sinks`` defaults to all configured sinks. Pass a narrower tuple to
    skip a sink — e.g. ``sinks=("discord",)`` when the caller has already
    fired the terminal notifier directly with a richer kind-specific
    title (transitional pattern while supervisor emit sites keep their
    existing :func:`notify.notify` calls; once those are removed, every
    emit site goes back to the default).

    Returns a dict naming each sink's outcome — useful for tests and for
    operator diagnostics. Never raises: a sink that throws is captured
    and recorded as ``False`` so a misbehaving sink can't break supervisor
    flow.

    INVARIANT documented for emit-site authors: the durable INBOX write
    MUST happen BEFORE calling :func:`dispatch_event`. INBOX is the
    truth-of-record; live notifications are advisory and may be silenced
    or fail without affecting plan progress.
    """
    out = {"terminal": False, "discord": False}
    if not _allowed_at_level(event):
        return out

    if SINK_TERMINAL in sinks:
        try:
            out["terminal"] = bool(notify.notify_event(event))
        except Exception as exc:  # noqa: BLE001 — sinks must never propagate.
            print(
                f"[notify_event] terminal sink raised {type(exc).__name__}; suppressed.",
                file=sys.stderr,
            )
    if SINK_DISCORD in sinks:
        try:
            out["discord"] = bool(notify_discord.notify(event))
        except Exception as exc:  # noqa: BLE001 — sinks must never propagate.
            print(
                f"[notify_event] discord sink raised {type(exc).__name__}; suppressed.",
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
    "SINK_DISCORD",
    "SINK_TERMINAL",
    "dispatch_event",
]
