"""Plan 2026-06-04-004 F007 — Architecture tab truthful status render."""

from __future__ import annotations

from dontpanic_orchestrate.architecture_regen import (
    RegenState,
    RegenStatus,
    render_architecture_status,
)


def test_fresh_render_self_heals_no_operator_action():
    state = RegenState(
        status=RegenStatus.FRESH,
        last_generated_at="2026-06-04T12:00:00Z",
        source_commit="abc1234",
        dirty=False,
    )
    r = render_architecture_status(state)
    assert r["status"] == "fresh"
    assert r["operator_action_required"] is False
    assert r["self_healing"] is True
    assert r["last_generated_at"] == "2026-06-04T12:00:00Z"
    assert r["source_commit"] == "abc1234"
    assert r["dirty_marker"] == ""
    assert r["manual_regen_is_advanced_fallback"] is True
    assert r["manual_regen_command"] == "dontpanic dashboard build"


def test_dirty_worktree_marker_shown():
    state = RegenState(status=RegenStatus.FRESH, source_commit="def5678", dirty=True)
    r = render_architecture_status(state)
    assert r["dirty"] is True
    assert r["dirty_marker"] == " (dirty)"


def test_regenerating_render_is_self_healing():
    r = render_architecture_status(RegenState(status=RegenStatus.REGENERATING))
    assert r["status"] == "regenerating"
    assert r["operator_action_required"] is False
    assert r["self_healing"] is True


def test_stale_queued_offers_manual_fallback_without_demanding_it():
    r = render_architecture_status(RegenState(status=RegenStatus.STALE_QUEUED))
    assert r["status"] == "stale_queued"
    assert r["operator_action_required"] is False  # daemon will heal / optional manual
    assert r["self_healing"] is True
    assert r["manual_regen_is_advanced_fallback"] is True
    assert "manually" in (r["detail"] or "")


def test_failed_render_requires_operator_action_and_surfaces_error():
    state = RegenState(status=RegenStatus.FAILED, last_error="RuntimeError: graphviz missing")
    r = render_architecture_status(state)
    assert r["status"] == "failed"
    assert r["operator_action_required"] is True  # human must fix the error
    assert r["self_healing"] is False
    assert r["last_error"] == "RuntimeError: graphviz missing"
    assert "graphviz missing" in r["detail"]
    # When human input IS required, manual regen is no longer just an advanced hint.
    assert r["manual_regen_is_advanced_fallback"] is False
