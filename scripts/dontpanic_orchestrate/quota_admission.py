"""F007 Slice 2 — admission policy for autonomous dispatches.

This module is *admission*, not allocation: it does NOT track 20/10/50/20
cross-plan tier budgets. It computes which `defer:*` gates should be active
right now given:

  - the current ~/.jarvis/quota_state.json (F020),
  - the current ~/.jarvis/interactive_state.json (this slice),
  - the runtime dispatch class derived from the plan and CLI flags.

Two synthetic `defer:*` gates live in this slice:

  - defer:quota_threshold       — any participating agent's percent_weekly
                                   exceeds JARVIS_QUOTA_DEFER_THRESHOLD
                                   (default 70.0). Bypassed by class p0 and
                                   class interactive.
  - defer:interactive_backoff   — Claude is in agents_required and the
                                   operator touched it within the backoff
                                   window. Bypassed by class p0 and
                                   class interactive.

Lifecycle is *transient* — the supervisor reconciles `active_defers` in
gate-state.json on every dispatch:

  - condition true  + not active → add (this dispatch will pause)
  - condition true  + already active → leave alone
  - condition false + active → drop (auto-clear without operator action)
  - condition false + not active → no-op

Operator approve via `jarvis approve <plan> defer:<kind>` pops the entry
from active_defers. On the very next dispatch the reconcile re-evaluates the
underlying condition; if still true the gate fires again. This matches
F006's known approve-vs-persistent-condition trade-off (D074-amend2) — the
escape hatches for the operator are wait-it-out, `--mode interactive`, or
class p0 (via plan.tier).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from dontpanic_orchestrate import (
    circuit_breakers,
    interactive_state,
    quota_caps_loader,
)

DEFAULT_QUOTA_DEFER_THRESHOLD = 70.0
_DEFAULT_QUOTA_STATE_PATH = Path.home() / ".jarvis" / "quota_state.json"
QUOTA_STATE_PATH = _DEFAULT_QUOTA_STATE_PATH


def _effective_quota_state_path() -> Path:
    """Honor JARVIS_QUOTA_STATE_PATH for hermetic test isolation; matches the
    breaker_history / active_supervisors / interactive_state pattern."""
    env_override = os.environ.get("JARVIS_QUOTA_STATE_PATH")
    if env_override:
        return Path(env_override)
    return QUOTA_STATE_PATH


class DeferKind(str, Enum):
    QUOTA_THRESHOLD = "quota_threshold"
    INTERACTIVE_BACKOFF = "interactive_backoff"


def gate_name(kind: DeferKind) -> str:
    """Synthetic gate name for the F008 gate-pause integration."""
    return f"defer:{kind.value}"


# Runtime dispatch classification — NOT a plan.tier value. The existing
# plan.tier schema (trivial | local | cross-cutting | architectural | p0) is
# untouched; this is a *runtime* layer the supervisor computes from
# (plan.tier, CLI mode flag, env override).
class DispatchClass(str, Enum):
    P0 = "p0"
    INTERACTIVE = "interactive"
    AUTONOMOUS = "autonomous"


# Per the F007 Slice 2 lock: P0 is *plan-derived only* (plan.tier == "p0").
# Operators cannot promote a non-P0 plan to the P0 admission lane via CLI
# flag or env; that would silently expand emergency-lane scope. The
# override surface only switches between the two non-P0 classes.
_OVERRIDE_VALUES: frozenset[str] = frozenset(
    {DispatchClass.INTERACTIVE.value, DispatchClass.AUTONOMOUS.value}
)


def classify_dispatch(plan_tier: str | None, *, mode_override: str | None = None) -> DispatchClass:
    """Resolve the runtime class per the F007 Slice 2 lock.

    Precedence:
      1. mode_override ∈ {interactive, autonomous}  (CLI --mode flag)
      2. JARVIS_RUN_MODE env, same allowed set
      3. plan.tier == "p0"  →  DispatchClass.P0
      4. fallback              DispatchClass.AUTONOMOUS

    NOTE: P0 is intentionally NOT a CLI/env override target. The lock
    framed P0 as the plan's emergency lane, derived from the plan-author's
    declared tier; allowing operators to force-promote a non-P0 plan
    would silently expand the bypass surface for both admission gates.
    Any "p0" value passed via mode_override or JARVIS_RUN_MODE is
    therefore ignored (falls through to the next precedence rule).
    argparse on the CLI restricts --mode to the same set, so the kwarg
    only takes "p0" via direct programmatic call.
    """
    if mode_override:
        m = mode_override.lower()
        if m in _OVERRIDE_VALUES:
            return DispatchClass(m)
    env_mode = (os.environ.get("JARVIS_RUN_MODE") or "").lower()
    if env_mode in _OVERRIDE_VALUES:
        return DispatchClass(env_mode)
    if (plan_tier or "").lower() == "p0":
        return DispatchClass.P0
    return DispatchClass.AUTONOMOUS


def _quota_threshold() -> float:
    raw = os.environ.get("JARVIS_QUOTA_DEFER_THRESHOLD")
    if raw is None:
        return DEFAULT_QUOTA_DEFER_THRESHOLD
    try:
        v = float(raw)
        return v if v > 0 else DEFAULT_QUOTA_DEFER_THRESHOLD
    except ValueError:
        return DEFAULT_QUOTA_DEFER_THRESHOLD


def _read_quota_state(path: Path | None = None) -> dict:
    p = path if path is not None else _effective_quota_state_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


@dataclass(frozen=True)
class QuotaCheck:
    """F006b: gained `cause` field (default None) so non-numeric defer
    reasons (caps_file_missing / calibration_required / unit_mismatch /
    missing_vendor_block / no_cap_for_signal) can flow through without
    forcing a synthetic observed_pct. Existing callers reading
    .over_threshold / .observed_pct still work — observed_pct is None when
    cause is set, so callers must handle both shapes."""

    over_threshold: bool
    offending_agent: str | None
    observed_pct: float | None
    threshold: float
    cause: str | None = None


def evaluate_quota_threshold(
    agents: Iterable[str],
    *,
    quota_state_path: Path | None = None,
) -> QuotaCheck:
    """Returns whether ANY agent in `agents` should defer.

    F006b: V2 path uses circuit_breakers.collect_agent_coverage with
    DEFAULT_WINDOW_PRIORITY (rolling_5h primary). Defers when:
      - caps file unavailable → cause='caps_file_missing'
      - any agent has terminal WindowOutcome → cause=outcome.value
      - any KNOWN_VENDORS agent has config_cause → that cause
      - any agent's primary window pct_of_cap > threshold/100 → numeric

    Legacy fallback (pre-F002 vendors{} block missing): preserves the
    F007-original models{}.percent_weekly path with no cause field.
    """
    threshold = _quota_threshold()
    state = _read_quota_state(quota_state_path)
    if not isinstance(state, dict):
        return QuotaCheck(False, None, None, threshold)

    vendors = state.get("vendors")
    if isinstance(vendors, dict) and vendors:
        return _evaluate_quota_threshold_v2(agents, vendors, threshold)

    # Legacy fallback
    circuit_breakers._warn_once(
        "quota_admission",
        "_global",
        "legacy_fallback",
        "[quota_admission] vendors{} missing in quota_state.json; using legacy "
        "models{}.percent_weekly path.",
    )
    models = state.get("models") or {}
    for agent in agents:
        info = models.get(agent) or {}
        pct = info.get("percent_weekly")
        if isinstance(pct, (int, float)) and float(pct) > threshold:
            return QuotaCheck(
                over_threshold=True,
                offending_agent=agent,
                observed_pct=float(pct),
                threshold=threshold,
            )
    return QuotaCheck(False, None, None, threshold)


def _evaluate_quota_threshold_v2(
    agents: Iterable[str], vendors: dict, threshold: float
) -> QuotaCheck:
    """V2 path — shares collect_agent_coverage with the breaker + supervisor
    so calibration/unit/missing-vendor-block handling is identical across the
    three consumers."""
    try:
        caps = quota_caps_loader.load()
    except quota_caps_loader.QuotaCapsError:
        # Caps file missing → defer for the first agent we'd otherwise
        # check. Don't dispatch unguarded — the breaker would also halt
        # on the same condition, but admission halts pre-dispatch which
        # is cheaper.
        first = next(iter(agents), None)
        return QuotaCheck(
            over_threshold=True,
            offending_agent=first,
            observed_pct=None,
            threshold=threshold,
            cause="caps_file_missing",
        )

    known = quota_caps_loader.KNOWN_VENDORS
    for agent in agents:
        report = circuit_breakers.collect_agent_coverage(
            agent=agent,
            vendors=vendors,
            caps=caps,
        )
        if report.terminal is not None:
            # F006b fix#1: TRIPPED is numeric — surface its .pct_of_cap so the
            # supervisor admission reason builder can format observed_pct
            # without falling into the cause-path. Other terminal outcomes
            # (CALIBRATION_REQUIRED, UNIT_MISMATCH) have no meaningful percent
            # and route through the cause path.
            if report.terminal.outcome == circuit_breakers.WindowOutcome.TRIPPED:
                pct_percent = float(report.terminal.pct_of_cap or 0.0) * 100.0
                return QuotaCheck(
                    over_threshold=True,
                    offending_agent=agent,
                    observed_pct=pct_percent,
                    threshold=threshold,
                )
            return QuotaCheck(
                over_threshold=True,
                offending_agent=agent,
                observed_pct=None,
                threshold=threshold,
                cause=report.terminal.outcome.value,
            )
        if report.config_cause is not None and agent in known:
            return QuotaCheck(
                over_threshold=True,
                offending_agent=agent,
                observed_pct=None,
                threshold=threshold,
                cause=report.config_cause,
            )
        if report.primary is not None:
            pct_percent = float(report.primary.pct_of_cap or 0.0) * 100.0
            if pct_percent > threshold:
                return QuotaCheck(
                    over_threshold=True,
                    offending_agent=agent,
                    observed_pct=pct_percent,
                    threshold=threshold,
                )

    return QuotaCheck(False, None, None, threshold)


@dataclass(frozen=True)
class InteractiveCheck:
    within_backoff: bool
    minutes_remaining: float | None


def evaluate_interactive_backoff(agents: Iterable[str]) -> InteractiveCheck:
    """Returns whether Claude is participating AND its touch is within the
    backoff window. Other agents don't enter this slice's check."""
    if "claude" not in set(agents):
        return InteractiveCheck(False, None)
    within, remaining = interactive_state.is_within_backoff("claude")
    return InteractiveCheck(within, remaining)


@dataclass(frozen=True)
class AdmissionCheck:
    """Computed defer set + supporting context, suitable for INBOX bodies."""

    dispatch_class: DispatchClass
    quota: QuotaCheck
    interactive: InteractiveCheck
    active_gates: frozenset[str]  # gate_name(...) for each defer:* that should fire


def evaluate(
    plan_tier: str | None,
    agents: Iterable[str],
    *,
    mode_override: str | None = None,
    quota_state_path: Path | None = None,
) -> AdmissionCheck:
    """Top-level pre-dispatch admission evaluation.

    Returns the runtime class, the underlying check structs (so callers can
    surface reasons), and the SET of defer gate names that should be active
    *given the class*. The supervisor reconciles gate-state.json against this
    set: any gate in this set that isn't already active gets added; any
    active defer gate NOT in this set gets dropped (auto-clear).
    """
    klass = classify_dispatch(plan_tier, mode_override=mode_override)
    agent_list = list(agents)

    # p0 and interactive both bypass everything in this slice.
    if klass in (DispatchClass.P0, DispatchClass.INTERACTIVE):
        return AdmissionCheck(
            dispatch_class=klass,
            quota=QuotaCheck(False, None, None, _quota_threshold()),
            interactive=InteractiveCheck(False, None),
            active_gates=frozenset(),
        )

    # autonomous: enforce both
    quota = evaluate_quota_threshold(agent_list, quota_state_path=quota_state_path)
    interactive = evaluate_interactive_backoff(agent_list)
    gates: set[str] = set()
    if quota.over_threshold:
        gates.add(gate_name(DeferKind.QUOTA_THRESHOLD))
    if interactive.within_backoff:
        gates.add(gate_name(DeferKind.INTERACTIVE_BACKOFF))
    return AdmissionCheck(
        dispatch_class=klass,
        quota=quota,
        interactive=interactive,
        active_gates=frozenset(gates),
    )


__all__ = [
    "AdmissionCheck",
    "DEFAULT_QUOTA_DEFER_THRESHOLD",
    "DeferKind",
    "DispatchClass",
    "InteractiveCheck",
    "QUOTA_STATE_PATH",
    "QuotaCheck",
    "classify_dispatch",
    "evaluate",
    "evaluate_interactive_backoff",
    "evaluate_quota_threshold",
    "gate_name",
]
