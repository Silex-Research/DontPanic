"""Plan 2026-06-04-004 F006 — bounded architecture-regen daemon."""

from __future__ import annotations

import datetime as dt

import pytest

from dontpanic_orchestrate.architecture_regen import (
    ArchitectureRegenDaemon,
    RegenStatus,
)

_T0 = dt.datetime(2026, 6, 4, 12, 0, 0, tzinfo=dt.timezone.utc)


def _at(seconds: float) -> dt.datetime:
    return _T0 + dt.timedelta(seconds=seconds)


def test_invalid_bounds_raise():
    with pytest.raises(ValueError):
        ArchitectureRegenDaemon(large_repo_change_threshold=0)


# ── debounce: a burst collapses into exactly ONE regen ────────────────────────
def test_burst_collapses_into_one_regen():
    d = ArchitectureRegenDaemon(debounce_seconds=2.0)
    runs = []

    def regen():
        runs.append(1)

    # rapid burst of 5 edits within the debounce window
    for i in range(5):
        d.notify_change(now=_at(i * 0.1))
    assert d.state.status == RegenStatus.QUEUED
    # still settling at +1s -> no run
    assert d.run_if_ready(now=_at(1.0), regen_fn=regen) is False
    assert runs == []
    # quiet for >= debounce -> exactly one regen for the whole burst
    assert d.run_if_ready(now=_at(3.0), regen_fn=regen) is True
    assert runs == [1]
    assert d.state.status == RegenStatus.FRESH
    assert d.state.pending_changes == 0
    # nothing pending -> no further runs
    assert d.run_if_ready(now=_at(10.0), regen_fn=regen) is False
    assert runs == [1]


# ── deferral: never regen while a write/dispatch is in flight ─────────────────
def test_deferred_while_busy_then_runs_when_idle():
    d = ArchitectureRegenDaemon(debounce_seconds=1.0)
    runs = []
    d.notify_change(now=_at(0))
    # debounce elapsed but a write is in flight -> deferred, stays queued
    assert d.run_if_ready(now=_at(2.0), busy=True, regen_fn=lambda: runs.append(1)) is False
    assert d.state.status == RegenStatus.QUEUED
    assert runs == []
    # writer done -> runs
    assert d.run_if_ready(now=_at(2.5), busy=False, regen_fn=lambda: runs.append(1)) is True
    assert runs == [1]


# ── failure isolation: a raising regen never blocks serve ─────────────────────
def test_regen_failure_is_isolated_and_recorded():
    d = ArchitectureRegenDaemon(debounce_seconds=0.0)

    def boom():
        raise RuntimeError("graphviz missing")

    d.notify_change(now=_at(0))
    # must NOT raise
    attempted = d.run_if_ready(now=_at(1.0), regen_fn=boom)
    assert attempted is True
    assert d.state.status == RegenStatus.FAILED
    assert "graphviz missing" in (d.state.last_error or "")
    assert d.state.last_generated_at is None


# ── large-repo guard: a huge burst is marked stale/queued, not auto-run ───────
def test_large_burst_marks_stale_queued_and_does_not_run():
    d = ArchitectureRegenDaemon(debounce_seconds=0.0, large_repo_change_threshold=3)
    runs = []
    for i in range(5):  # exceeds threshold of 3
        d.notify_change(now=_at(i))
    assert d.state.status == RegenStatus.STALE_QUEUED
    assert d.run_if_ready(now=_at(10.0), regen_fn=lambda: runs.append(1)) is False
    assert runs == []  # never thrashed
    assert d.state.status == RegenStatus.STALE_QUEUED


# ── success records provenance for the F007 render ────────────────────────────
def test_success_records_source_commit_and_dirty():
    d = ArchitectureRegenDaemon(debounce_seconds=0.0)
    d.notify_change(now=_at(0))
    d.run_if_ready(
        now=_at(1.0),
        regen_fn=lambda: {"source_commit": "abc1234", "dirty": True},
        run_seconds=4.2,
    )
    assert d.state.status == RegenStatus.FRESH
    assert d.state.source_commit == "abc1234"
    assert d.state.dirty is True
    assert d.state.last_run_seconds == 4.2
    assert d.state.to_dict()["status"] == "fresh"
