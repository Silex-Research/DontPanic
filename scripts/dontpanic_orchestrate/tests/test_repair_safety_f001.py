"""Plan 2026-06-04-006 F001 — producer-asserted safety taxonomy.

safety_class ∈ {auto_safe, human_required, blocked_external, info} is asserted by
the emitter and VALIDATED against a policy keyed by the action's kind; the runner
never infers it. Fail closed: unclassified, or auto_safe with a forbidden/mismatched
kind, resolves to human_required. apply_tier (derived_state | confirmed_local) gates
which `repair apply` flag may run it; NO kind in FORBIDDEN_KINDS ever auto-runs.
"""

from __future__ import annotations

from types import SimpleNamespace

from dontpanic_orchestrate import repair_safety as rs


def _a(kind=None, safety_class=None, apply_tier=None):
    return SimpleNamespace(kind=kind, safety_class=safety_class, apply_tier=apply_tier)


# ── fail closed ───────────────────────────────────────────────────────────────
def test_unclassified_action_is_human_required():
    assert rs.resolve_safety(_a(kind="rebuild_dashboard_state")) == (rs.HUMAN_REQUIRED, None)


def test_forbidden_kind_never_auto_safe_even_if_asserted():
    for kind in ["deploy", "credential_setup", "paid_dispatch", "role_change",
                 "plan_state_mutation", "registry_change", "destructive_cleanup", "baseline_write"]:
        a = _a(kind=kind, safety_class=rs.AUTO_SAFE, apply_tier=rs.TIER_DERIVED_STATE)
        assert rs.resolve_safety(a) == (rs.HUMAN_REQUIRED, None), kind


# ── derived_state tier ────────────────────────────────────────────────────────
def test_auto_safe_derived_state_kind_resolves():
    a = _a(kind="recompute_what_now", safety_class=rs.AUTO_SAFE, apply_tier=rs.TIER_DERIVED_STATE)
    assert rs.resolve_safety(a) == (rs.AUTO_SAFE, rs.TIER_DERIVED_STATE)


def test_auto_safe_derived_tier_with_non_derived_kind_fails_closed():
    # asserts derived_state but the kind isn't a derived-state regeneration → human_required
    a = _a(kind="reconcile_baseline_write", safety_class=rs.AUTO_SAFE, apply_tier=rs.TIER_DERIVED_STATE)
    assert rs.resolve_safety(a) == (rs.HUMAN_REQUIRED, None)


def test_auto_safe_without_valid_tier_fails_closed():
    a = _a(kind="recompute_what_now", safety_class=rs.AUTO_SAFE, apply_tier=None)
    assert rs.resolve_safety(a) == (rs.HUMAN_REQUIRED, None)


# ── confirmed_local tier (allowlist) ──────────────────────────────────────────
def test_confirmed_local_allowlisted_kind_resolves():
    kind = next(iter(rs.CONFIRMED_LOCAL_KINDS))
    a = _a(kind=kind, safety_class=rs.AUTO_SAFE, apply_tier=rs.TIER_CONFIRMED_LOCAL)
    assert rs.resolve_safety(a) == (rs.AUTO_SAFE, rs.TIER_CONFIRMED_LOCAL)


def test_confirmed_local_non_allowlisted_kind_fails_closed():
    a = _a(kind="not_on_allowlist", safety_class=rs.AUTO_SAFE, apply_tier=rs.TIER_CONFIRMED_LOCAL)
    assert rs.resolve_safety(a) == (rs.HUMAN_REQUIRED, None)


# ── non-auto classes pass through ─────────────────────────────────────────────
def test_human_required_and_blocked_external_and_info_pass_through():
    assert rs.resolve_safety(_a(safety_class=rs.HUMAN_REQUIRED)) == (rs.HUMAN_REQUIRED, None)
    assert rs.resolve_safety(_a(safety_class=rs.BLOCKED_EXTERNAL)) == (rs.BLOCKED_EXTERNAL, None)
    assert rs.resolve_safety(_a(safety_class=rs.INFO)) == (rs.INFO, None)


# ── tier gating: which `repair apply` flag may run an action ──────────────────
def test_derived_state_runs_at_both_tiers_confirmed_only_at_confirm():
    derived = _a(kind="regen_architecture", safety_class=rs.AUTO_SAFE, apply_tier=rs.TIER_DERIVED_STATE)
    confirmed = _a(kind=next(iter(rs.CONFIRMED_LOCAL_KINDS)), safety_class=rs.AUTO_SAFE, apply_tier=rs.TIER_CONFIRMED_LOCAL)
    human = _a(kind="deploy", safety_class=rs.AUTO_SAFE, apply_tier=rs.TIER_DERIVED_STATE)  # forbidden

    assert rs.is_runnable_at(derived, rs.RUN_TIER_DERIVED) is True
    assert rs.is_runnable_at(derived, rs.RUN_TIER_CONFIRM) is True
    # confirmed_local is NOT runnable under --safe-derived-state, only under --safe --confirm
    assert rs.is_runnable_at(confirmed, rs.RUN_TIER_DERIVED) is False
    assert rs.is_runnable_at(confirmed, rs.RUN_TIER_CONFIRM) is True
    # forbidden/human never runs
    assert rs.is_runnable_at(human, rs.RUN_TIER_DERIVED) is False
    assert rs.is_runnable_at(human, rs.RUN_TIER_CONFIRM) is False


def test_baseline_write_is_forbidden_not_derived():
    # reconcile-baseline writes are source-of-truth -> forbidden, never derived_state
    assert "baseline_write" in rs.FORBIDDEN_KINDS
    assert "baseline_write" not in rs.DERIVED_STATE_KINDS
