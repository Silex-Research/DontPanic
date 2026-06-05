"""Plan 2026-06-04-004 F006 — bounded architecture-regen daemon (engine only).

`dashboard serve` watches architecture-relevant repo paths + docs/plans/** and,
on change, asks THIS engine whether/how to regenerate the architecture map. The
engine encodes the bounds so the dashboard never thrashes or blocks:

* DEBOUNCE — a rapid burst of edits collapses into ONE regen (run once the burst
  has been quiet for ``debounce_seconds``).
* DEFERRAL — while an active write/dispatch is in flight (``busy``), regen is
  deferred (stays queued), never racing a writer.
* FAILURE ISOLATION — a regen that raises records ``failed`` + ``last_error`` and
  NEVER propagates, so the serve loop keeps running.
* LARGE-REPO GUARD — a burst larger than ``large_repo_change_threshold`` is marked
  ``stale_queued`` (regen offered as a manual/queued step) rather than auto-run,
  so huge repos don't thrash.

The engine is pure/deterministic: the caller injects ``now`` and the ``regen_fn``;
there is no real filesystem watching here (that is the serve loop's job, feeding
``notify_change``/``run_if_ready``). No rendering — F007 renders this state.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable
from enum import Enum
from typing import Any


class RegenStatus(str, Enum):
    IDLE = "idle"
    QUEUED = "queued"
    REGENERATING = "regenerating"
    FRESH = "fresh"
    STALE_QUEUED = "stale_queued"  # too large to auto-run; offered as manual step
    FAILED = "failed"


# What the engine decided to do on a given tick.
DECISION_WAIT = "wait"  # nothing to do (no pending change, or debounce not elapsed)
DECISION_RUN = "run"
DECISION_DEFER = "defer"  # a write/dispatch is in flight
DECISION_STALE_QUEUED = "stale_queued"  # burst too large; do not auto-run


@dataclasses.dataclass
class RegenState:
    status: RegenStatus = RegenStatus.IDLE
    last_generated_at: str | None = None
    last_error: str | None = None
    last_run_seconds: float | None = None
    pending_changes: int = 0
    source_commit: str | None = None
    dirty: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "last_generated_at": self.last_generated_at,
            "last_error": self.last_error,
            "last_run_seconds": self.last_run_seconds,
            "pending_changes": self.pending_changes,
            "source_commit": self.source_commit,
            "dirty": self.dirty,
        }


def _iso(ts: dt.datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


class ArchitectureRegenDaemon:
    """Bounded regen scheduler. See module docstring for the contract."""

    def __init__(
        self,
        *,
        debounce_seconds: float = 2.0,
        large_repo_change_threshold: int = 200,
        max_runtime_seconds: float = 30.0,
    ) -> None:
        if debounce_seconds < 0 or large_repo_change_threshold < 1:
            raise ValueError("invalid daemon bounds")
        self.debounce_seconds = debounce_seconds
        self.large_repo_change_threshold = large_repo_change_threshold
        self.max_runtime_seconds = max_runtime_seconds
        self.state = RegenState()
        self._last_change_at: dt.datetime | None = None

    # ── input: the serve loop saw a watched file change ───────────────────────
    def notify_change(self, *, now: dt.datetime) -> None:
        self.state.pending_changes += 1
        self._last_change_at = now
        if self.state.pending_changes > self.large_repo_change_threshold:
            # A burst this large would thrash a big repo — queue it as stale and
            # let the operator run the manual regen (F007 surfaces the command).
            self.state.status = RegenStatus.STALE_QUEUED
        elif self.state.status not in (RegenStatus.REGENERATING,):
            self.state.status = RegenStatus.QUEUED

    # ── pure decision: what should happen on this tick ────────────────────────
    def decide(self, *, now: dt.datetime, busy: bool) -> str:
        if self.state.pending_changes == 0:
            return DECISION_WAIT
        if self.state.pending_changes > self.large_repo_change_threshold:
            return DECISION_STALE_QUEUED
        if busy:
            return DECISION_DEFER
        if self._last_change_at is None:
            return DECISION_WAIT
        elapsed = (now - self._last_change_at).total_seconds()
        if elapsed < self.debounce_seconds:
            return DECISION_WAIT  # burst still settling
        return DECISION_RUN

    # ── execution: run at most ONE regen per settled burst ────────────────────
    def run_if_ready(
        self,
        *,
        now: dt.datetime,
        regen_fn: Callable[[], Any],
        busy: bool = False,
        run_seconds: float | None = None,
    ) -> bool:
        """Run the regen iff the burst has settled, nothing is busy, and the burst
        is not oversized. Returns True iff a regen was ATTEMPTED (success OR
        isolated failure). Never raises — a failing regen never blocks serve."""
        decision = self.decide(now=now, busy=busy)
        if decision == DECISION_DEFER:
            self.state.status = RegenStatus.QUEUED  # keep it queued; do not drop
            return False
        if decision == DECISION_STALE_QUEUED:
            self.state.status = RegenStatus.STALE_QUEUED
            return False
        if decision != DECISION_RUN:
            return False

        # Collapse the whole burst into this single run.
        self.state.pending_changes = 0
        self._last_change_at = None
        self.state.status = RegenStatus.REGENERATING
        try:
            result = regen_fn()
        except Exception as exc:  # noqa: BLE001 — failure isolation is the point
            self.state.status = RegenStatus.FAILED
            self.state.last_error = f"{type(exc).__name__}: {exc}"
            return True  # attempted; failure recorded, never propagated
        self.state.status = RegenStatus.FRESH
        self.state.last_generated_at = _iso(now)
        self.state.last_error = None
        if run_seconds is not None:
            self.state.last_run_seconds = run_seconds
        if isinstance(result, dict):
            self.state.source_commit = result.get("source_commit")
            self.state.dirty = result.get("dirty")
        return True


# ── F007: truthful architecture-tab render over the daemon state ──────────────
# The manual fallback command (an "advanced" affordance — the map self-heals via
# the F006 daemon, so this is offered, not demanded, unless human input is
# genuinely required).
ARCHITECTURE_MANUAL_REGEN_COMMAND = "dontpanic dashboard build"


def render_architecture_status(
    state: RegenState,
    *,
    manual_regen_command: str = ARCHITECTURE_MANUAL_REGEN_COMMAND,
) -> dict[str, Any]:
    """Plan 2026-06-04-004 F007 — the Architecture tab's truthful status view.

    Reflects the daemon's real status, last-generated time, source commit + a
    dirty-worktree marker, and last error. It surfaces an OPERATOR ACTION only
    when human input is genuinely required (a ``failed`` regen the operator must
    fix); otherwise the map self-heals silently and the manual ``regen`` command
    is presented as an ADVANCED fallback.
    """
    status = state.status
    # Human input is required only when a regen FAILED — the operator must
    # resolve the recorded error (e.g. install a missing tool) before it can heal.
    operator_action_required = status == RegenStatus.FAILED
    # The daemon self-heals everything except a hard failure.
    self_healing = status != RegenStatus.FAILED

    if status == RegenStatus.FAILED:
        headline = "Architecture map regeneration failed"
        detail = state.last_error or "regeneration failed"
    elif status == RegenStatus.REGENERATING:
        headline = "Regenerating architecture map…"
        detail = None
    elif status == RegenStatus.STALE_QUEUED:
        headline = "Architecture map is stale (queued)"
        detail = "Large change burst — regen queued; run manually to refresh now."
    elif status == RegenStatus.QUEUED:
        headline = "Architecture map refresh queued"
        detail = None
    elif status == RegenStatus.FRESH:
        headline = "Architecture map is fresh"
        detail = None
    else:  # IDLE
        headline = "Architecture map idle"
        detail = None

    return {
        "status": status.value,
        "headline": headline,
        "detail": detail,
        "last_generated_at": state.last_generated_at,
        "source_commit": state.source_commit,
        "dirty": state.dirty,
        "dirty_marker": " (dirty)" if state.dirty else "",
        "last_error": state.last_error,
        "self_healing": self_healing,
        "operator_action_required": operator_action_required,
        # Advanced fallback is ALWAYS available; it is the primary CTA only when
        # human input is required.
        "manual_regen_command": manual_regen_command,
        "manual_regen_is_advanced_fallback": not operator_action_required,
    }
