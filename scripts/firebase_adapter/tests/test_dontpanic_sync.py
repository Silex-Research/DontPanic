"""Plan 2026-05-09-004 F002 — sync daemon tests against the InMemoryFirestore stub.

Covers:
  - first-poll initial upserts to projects/<pid>/<stream> shape
  - idempotent re-poll: zero writes when the snapshot is unchanged
  - diff: only the changed doc is rewritten
  - delete: doc vanishes from snapshot → doc deleted from Firestore
  - --include honored: streams outside the include set are left alone
  - per-doc failure: one bad stream surfaces in result.failures and the
    rest still sync
  - run_daemon loop with --max-iterations
  - CLI --dry-run path uses the stub and prints zero real writes
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from firebase_adapter.dontpanic_sync import (
    ALL_STREAMS,
    SyncEngine,
    fetch_snapshot_via_cli,
    main,
    run_daemon,
)
from firebase_adapter.firestore_stub import InMemoryFirestore

# ─────────────────── fixtures ───────────────────


def _envelope(**streams):
    base = {s: [] for s in ALL_STREAMS}
    base.update(streams)
    return {
        "schema_version": "1.0",
        "captured_at": "2026-05-12T00:00:00Z",
        "redact_level": "operator",
        "streams": base,
    }


def _plan_doc(plan_id="p1", status="active", title="T"):
    return {
        "plan_id": plan_id,
        "status": status,
        "title": title,
        "type": "feat",
        "tier": "local",
        "goal_type": "infra",
        "surfaces": ["infra"],
        "features_summary": {"total": 1, "passing": 0},
        "target_env": "dev",
        "target_project": None,
        "agents_required": ["claude"],
        "date": "2026-05-09",
    }


def _gate_doc(plan_id="p1", gate_name="pre_merge"):
    return {
        "plan_id": plan_id,
        "gate_name": gate_name,
        "kind": "pre_merge",
        "stage": "pre_merge",
        "reason": "awaiting",
        "paused_at": "2026-05-12T00:00:00Z",
        "approval_required": True,
        "feature_id": None,
    }


def _inbox_doc(plan_id="p1", event_id="p1:start:2026-05-12T00:00:00Z:F001"):
    return {
        "plan_id": plan_id,
        "event": "volley_start",
        "event_id": event_id,
        "captured_at": "2026-05-12T00:00:00Z",
        "feature_id": "F001",
        "body": "hi",
        "headers": {},
    }


def _quota_doc(vendor="claude", window="daily", pct=42.0):
    return {
        "vendor": vendor,
        "window": window,
        "percent_of_cap": pct,
        "percent_threshold": 90.0,
        "status": "ok",
        "captured_at": "2026-05-12T00:00:00Z",
    }


@pytest.fixture
def stub():
    return InMemoryFirestore()


@pytest.fixture
def engine():
    return SyncEngine(project_id="proj-test")


# ─────────────────── upsert + diff (acceptance #4) ───────────────────


def test_first_sync_writes_every_doc_at_correct_path(engine, stub):
    snap = _envelope(
        plans=[_plan_doc("p1"), _plan_doc("p2", title="Two")],
        gates=[_gate_doc("p1")],
        quota=[_quota_doc()],
    )
    result = engine.sync_once(snap, stub)

    assert result.sets == 4
    assert result.deletes == 0
    assert result.failures == 0
    # paths use single-tenant projects/<pid>/<stream> shape per D002
    assert set(stub.docs_at("projects/proj-test/plans").keys()) == {"p1", "p2"}
    assert "p1__pre_merge" in stub.docs_at("projects/proj-test/gates")
    assert "claude__daily" in stub.docs_at("projects/proj-test/quota")


def test_diff_only_writes_changed_doc(engine, stub):
    snap1 = _envelope(plans=[_plan_doc("p1", status="active"), _plan_doc("p2")])
    engine.sync_once(snap1, stub)
    stub.reset_log()

    snap2 = _envelope(
        plans=[
            _plan_doc("p1", status="completed"),  # changed
            _plan_doc("p2"),  # unchanged
        ]
    )
    result = engine.sync_once(snap2, stub)

    assert result.sets == 1
    assert result.skipped_unchanged == 1
    sets = [w for w in stub.writes if w.op == "set"]
    assert len(sets) == 1 and sets[0].doc_id == "p1"


def test_missing_doc_in_new_snapshot_is_deleted(engine, stub):
    engine.sync_once(_envelope(plans=[_plan_doc("p1"), _plan_doc("p2")]), stub)
    stub.reset_log()

    result = engine.sync_once(_envelope(plans=[_plan_doc("p1")]), stub)

    assert result.deletes == 1
    deletes = [w for w in stub.writes if w.op == "delete"]
    assert len(deletes) == 1 and deletes[0].doc_id == "p2"
    assert "p2" not in stub.docs_at("projects/proj-test/plans")


# ─────────────────── idempotency (acceptance #2) ───────────────────


def test_idempotent_re_sync_produces_zero_writes(engine, stub):
    snap = _envelope(
        plans=[_plan_doc("p1")],
        gates=[_gate_doc("p1")],
        inbox=[_inbox_doc("p1")],
        quota=[_quota_doc()],
    )
    engine.sync_once(snap, stub)
    stub.reset_log()

    result = engine.sync_once(snap, stub)

    assert stub.write_count() == 0
    assert result.sets == 0
    assert result.deletes == 0
    assert result.failures == 0
    assert result.skipped_unchanged == 4


def test_idempotent_across_three_polls_when_state_static(engine, stub):
    snap = _envelope(plans=[_plan_doc("p1")])
    engine.sync_once(snap, stub)
    engine.sync_once(snap, stub)
    stub.reset_log()
    engine.sync_once(snap, stub)
    assert stub.write_count() == 0


# ─────────────────── --include filtering (acceptance #3) ───────────────────


def test_include_filter_only_syncs_listed_streams(engine, stub):
    snap = _envelope(
        plans=[_plan_doc("p1")],
        gates=[_gate_doc("p1")],
        inbox=[_inbox_doc("p1")],
    )
    result = engine.sync_once(snap, stub, owned_streams=("plans", "gates"))

    assert result.sets == 2
    assert stub.docs_at("projects/proj-test/plans")
    assert stub.docs_at("projects/proj-test/gates")
    assert stub.docs_at("projects/proj-test/inbox") == {}


def test_include_filter_does_not_delete_unlisted_stream_docs(engine, stub):
    """Toggling --include off for a stream MUST NOT wipe Firestore — the
    operator may have other adapters writing the same collection.
    """
    # First sync everything.
    engine.sync_once(
        _envelope(plans=[_plan_doc("p1")], inbox=[_inbox_doc("p1")]), stub
    )
    assert stub.docs_at("projects/proj-test/inbox")
    stub.reset_log()

    # Now sync only `plans`; inbox should be untouched.
    snap2 = _envelope(plans=[_plan_doc("p1", status="completed")])
    result = engine.sync_once(snap2, stub, owned_streams=("plans",))

    assert all(w.path == "projects/proj-test/plans" for w in stub.writes)
    assert result.deletes == 0
    assert stub.docs_at("projects/proj-test/inbox")  # still there


# ─────────────────── failure paths (acceptance #4) ───────────────────


def test_failed_set_is_counted_and_does_not_block_other_writes(engine, stub):
    stub.fail_paths.add("projects/proj-test/plans")
    snap = _envelope(
        plans=[_plan_doc("p1")],
        gates=[_gate_doc("p1")],
    )
    result = engine.sync_once(snap, stub)

    assert result.failures == 1
    # The gate still wrote.
    assert "p1__pre_merge" in stub.docs_at("projects/proj-test/gates")


def test_failed_set_is_retried_on_next_sync_when_path_clears(engine, stub):
    stub.fail_paths.add("projects/proj-test/plans")
    snap = _envelope(plans=[_plan_doc("p1")])
    engine.sync_once(snap, stub)
    assert engine.last_written.get("plans", {}) == {}  # cache NOT populated

    stub.fail_paths.clear()
    stub.reset_log()
    result = engine.sync_once(snap, stub)
    assert result.sets == 1
    assert "p1" in stub.docs_at("projects/proj-test/plans")


def test_malformed_item_is_skipped_not_fatal(engine, stub):
    """Plans stream missing its `plan_id` should record a failure but
    leave the rest of the sync intact.
    """
    snap = _envelope(
        plans=[{"status": "active"}],  # missing plan_id
        gates=[_gate_doc("p1")],
    )
    result = engine.sync_once(snap, stub)

    assert result.failures == 1
    assert "p1__pre_merge" in stub.docs_at("projects/proj-test/gates")


# ─────────────────── doc-id determinism ───────────────────


def test_doc_ids_for_each_stream_are_stable():
    """Re-syncing the same item across SyncEngine instances must produce
    the same doc id (otherwise idempotency across restarts breaks).
    """
    e1, e2 = SyncEngine(project_id="x"), SyncEngine(project_id="x")
    fs1, fs2 = InMemoryFirestore(), InMemoryFirestore()
    snap = _envelope(
        plans=[_plan_doc("p1")],
        inbox=[_inbox_doc("p1")],
        gates=[_gate_doc("p1")],
        quota=[_quota_doc()],
    )
    e1.sync_once(snap, fs1)
    e2.sync_once(snap, fs2)
    assert fs1.docs == fs2.docs


def test_evidence_ref_without_natural_key_gets_deterministic_hash():
    e = SyncEngine(project_id="x")
    fs = InMemoryFirestore()
    snap = _envelope(
        evidence_refs=[
            {
                "plan_id": "p1",
                "feature_id": "F001",
                "type": "log",
                "uri": "evidence/x.log",
            }
        ]
    )
    e.sync_once(snap, fs)
    # Same input → same id; running it again rewrites zero docs.
    fs.reset_log()
    e.sync_once(snap, fs)
    assert fs.write_count() == 0


# ─────────────────── daemon loop ───────────────────


def test_run_daemon_max_iterations_stops_after_n_cycles(engine, stub):
    snap = _envelope(plans=[_plan_doc("p1")])
    sleeps: list[float] = []
    cycles = run_daemon(
        engine=engine,
        snapshot_source=lambda: snap,
        firestore_client=stub,
        interval_s=999,
        max_iterations=3,
        sleep_fn=sleeps.append,
    )
    assert len(cycles) == 3
    # First cycle wrote, next two were idempotent.
    assert cycles[0].sets == 1
    assert cycles[1].sets == 0 and cycles[2].sets == 0


def test_run_daemon_should_stop_short_circuits_loop(engine, stub):
    snap = _envelope(plans=[_plan_doc("p1")])
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 1  # let cycle 1 run, stop before cycle 2

    cycles = run_daemon(
        engine=engine,
        snapshot_source=lambda: snap,
        firestore_client=stub,
        interval_s=0,
        should_stop=stop,
        sleep_fn=lambda _: None,
    )
    assert len(cycles) == 1


def test_run_daemon_recovers_from_snapshot_source_error(engine, stub):
    bad = {"n": 0}

    def source():
        bad["n"] += 1
        if bad["n"] == 1:
            raise RuntimeError("transient")
        return _envelope(plans=[_plan_doc("p1")])

    cycles = run_daemon(
        engine=engine,
        snapshot_source=source,
        firestore_client=stub,
        interval_s=0,
        max_iterations=2,
        sleep_fn=lambda _: None,
    )
    # First cycle errored (no result); second succeeded.
    assert len(cycles) == 1
    assert cycles[0].sets == 1


# ─────────────────── fetch_snapshot_via_cli ───────────────────


def test_fetch_snapshot_via_cli_parses_compact_json(monkeypatch):
    envelope = _envelope(plans=[_plan_doc("p1")])

    class _FakeProc:
        returncode = 0
        stdout = json.dumps(envelope)
        stderr = ""

    def _fake_run(argv, **kwargs):
        assert "--json" in argv and "--compact" in argv
        assert "--plans-root" in argv
        assert "--include" in argv
        return _FakeProc()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    out = fetch_snapshot_via_cli(
        plans_root=Path("/tmp/plans"),  # noqa: S108 — test arg
        include=("plans",),
    )
    assert out["streams"]["plans"][0]["plan_id"] == "p1"


def test_fetch_snapshot_via_cli_raises_on_nonzero_exit(monkeypatch):
    class _FakeProc:
        returncode = 2
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())
    with pytest.raises(RuntimeError, match="exit 2"):
        fetch_snapshot_via_cli()


# ─────────────────── CLI entry point (acceptance #1) ───────────────────


def test_cli_start_dry_run_runs_one_cycle_against_stub(monkeypatch, capsys):
    envelope = _envelope(plans=[_plan_doc("p1")])

    class _FakeProc:
        returncode = 0
        stdout = json.dumps(envelope)
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())

    rc = main(
        [
            "start",
            "--project-id",
            "proj-cli",
            "--once",
            "--dry-run",
            "--interval",
            "0",
        ]
    )
    assert rc == 0


def test_cli_rejects_unknown_include_stream():
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "start",
                "--project-id",
                "x",
                "--include",
                "plans,not_a_stream",
                "--once",
                "--dry-run",
            ]
        )
    assert "unknown stream" in str(exc.value)


def test_cli_requires_project_id():
    with pytest.raises(SystemExit):
        main(["start", "--once", "--dry-run"])
