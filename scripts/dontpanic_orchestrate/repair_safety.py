"""Plan 2026-06-04-006 F001 — producer-asserted safety taxonomy for repair actions.

A repair action declares a ``safety_class`` (and, for auto_safe, an ``apply_tier``)
plus a ``kind``; :func:`resolve_safety` VALIDATES the assertion against this closed
policy and returns the effective ``(safety_class, apply_tier)``. The runner never
infers safety. Fail closed: an unclassified action, a forbidden kind, or an auto_safe
action whose kind doesn't match its declared tier all resolve to ``human_required``.

``safety_class`` (WHETHER an action may auto-run) is ORTHOGONAL to 001's
``resolution_class`` (HOW the issue it addresses resolves). The two are independent
fields on different objects.

Tiers (only meaningful for auto_safe):
  * ``derived_state``   — regenerates derived/cached projection state only (no
    source-of-truth write); runnable under ``repair apply --safe-derived-state``.
  * ``confirmed_local`` — an explicit allowlist of local safe mutations; runnable
    only under the stronger ``repair apply --safe --confirm``.

No kind in :data:`FORBIDDEN_KINDS` ever auto-runs at any tier (deploys, credential
setup, paid dispatch, role changes, plan-state / registry mutation, destructive
cleanup, reconcile-baseline writes) — those are always ``human_required``.
"""

from __future__ import annotations

from typing import Any

# ── safety classes ────────────────────────────────────────────────────────────
AUTO_SAFE = "auto_safe"
HUMAN_REQUIRED = "human_required"
BLOCKED_EXTERNAL = "blocked_external"
INFO = "info"
SAFETY_CLASSES: frozenset[str] = frozenset({AUTO_SAFE, HUMAN_REQUIRED, BLOCKED_EXTERNAL, INFO})

# ── apply tiers (auto_safe only) ──────────────────────────────────────────────
TIER_DERIVED_STATE = "derived_state"
TIER_CONFIRMED_LOCAL = "confirmed_local"
APPLY_TIERS: frozenset[str] = frozenset({TIER_DERIVED_STATE, TIER_CONFIRMED_LOCAL})

# ── run tiers granted by the `repair apply` flags ─────────────────────────────
RUN_TIER_DERIVED = "safe-derived-state"  # repair apply --safe-derived-state
RUN_TIER_CONFIRM = "safe-confirm"  # repair apply --safe --confirm

# Kinds that may NEVER auto-run at any tier (always human_required).
FORBIDDEN_KINDS: frozenset[str] = frozenset(
    {
        "deploy",
        "credential_setup",
        "paid_dispatch",
        "role_change",
        "plan_state_mutation",
        "registry_change",
        "destructive_cleanup",
        "baseline_write",  # reconcile-baseline write = source-of-truth
    }
)

# Kinds that regenerate derived/cached projection state ONLY (no source-of-truth
# write) — eligible for apply_tier=derived_state.
DERIVED_STATE_KINDS: frozenset[str] = frozenset(
    {
        "rebuild_dashboard_state",
        "recompute_what_now",
        "refresh_capabilities",
        "refresh_reconcile_check",  # the CHECK, not the baseline write
        "regen_architecture",
        "clear_replaceable_cache",
        "re_export_state",
        "suppress_resolved",
    }
)

# Explicit allowlist of local safe MUTATIONS eligible for apply_tier=confirmed_local
# (beyond pure derived-state regen). Intentionally small; grows only by decision.
CONFIRMED_LOCAL_KINDS: frozenset[str] = frozenset(
    {
        "clear_stale_generated_cache",  # delete + let next build re-derive
        "rewrite_local_derived_config",  # rewrite a derived (non-source) config file
    }
)


def resolve_safety(action: Any) -> tuple[str, str | None]:
    """Validate an action's asserted safety against the policy, fail-closed.

    Returns the effective ``(safety_class, apply_tier)``. ``apply_tier`` is None for
    every class except a validated auto_safe action.
    """
    kind = getattr(action, "kind", None)
    asserted = getattr(action, "safety_class", None)
    tier = getattr(action, "apply_tier", None)

    # A forbidden kind can never auto-run, regardless of what was asserted.
    if kind in FORBIDDEN_KINDS:
        return HUMAN_REQUIRED, None
    # No (or unknown) declared class → fail closed.
    if asserted not in SAFETY_CLASSES:
        return HUMAN_REQUIRED, None
    if asserted == AUTO_SAFE:
        if tier == TIER_DERIVED_STATE and kind in DERIVED_STATE_KINDS:
            return AUTO_SAFE, TIER_DERIVED_STATE
        if tier == TIER_CONFIRMED_LOCAL and kind in CONFIRMED_LOCAL_KINDS:
            return AUTO_SAFE, TIER_CONFIRMED_LOCAL
        # auto_safe asserted but kind/tier don't validate → fail closed.
        return HUMAN_REQUIRED, None
    # human_required / blocked_external / info pass through (no tier).
    return asserted, None


def is_forbidden_kind(action: Any) -> bool:
    """True iff the action's ``kind`` is in :data:`FORBIDDEN_KINDS` — a kind that
    may NEVER auto-run at any tier. The apply runner uses this as an explicit
    execution-time guard (defense in depth) on top of :func:`is_runnable_at`."""
    return getattr(action, "kind", None) in FORBIDDEN_KINDS


def is_runnable_at(action: Any, run_tier: str) -> bool:
    """True iff ``action`` may execute under the given run tier (the flag the
    operator passed). derived_state runs under both flags; confirmed_local runs
    ONLY under --safe --confirm; everything else never auto-runs."""
    safety_class, tier = resolve_safety(action)
    if safety_class != AUTO_SAFE:
        return False
    if run_tier == RUN_TIER_DERIVED:
        return tier == TIER_DERIVED_STATE
    if run_tier == RUN_TIER_CONFIRM:
        return tier in (TIER_DERIVED_STATE, TIER_CONFIRMED_LOCAL)
    return False
