"""Plan 2026-05-23-002 F002 — ``dontpanic reconcile check`` tests.

Coverage (one test per acceptance bullet plus structural guards):

  1. Clean state — snapshot matches current capabilities, cache fresh →
     status ``clean`` with exit 0.
  2. Missing snapshot — no anchor on disk → status ``missing_snapshot``
     with exit 1 and the exact ``reconcile baseline --yes`` command.
  3. New capability — capability in current repo absent from snapshot →
     reported in ``new_capabilities`` with its fingerprints.
  4. Removed capability — capability in snapshot absent from current
     repo → reported in ``removed_capabilities`` with its fingerprints.
  5. Setup-step change — manifest_fingerprint stable but
     setup_steps_fingerprint drifts → ``setup_steps_changed=True`` and
     ``manifest_changed=False``; renamed setup_step_ids surface as a
     separate diff entry.
  6. Manifest-only change — manifest_fingerprint drifts but
     setup_steps_fingerprint stable → ``manifest_changed=True`` and
     ``setup_steps_changed=False``.
  7. Missing cache — snapshot exists, cache file absent → status_cache
     state ``missing`` with the exact ``dontpanic capabilities status``
     command.
  8. Stale cache — cache file's ``generated_at`` predates the snapshot's
     ``generated_at`` → status_cache state ``stale`` with the exact
     ``dontpanic capabilities status`` command.
  9. JSON shape — ``--format=json`` emits a stable envelope with the
     expected top-level keys.
  10. No mutation — running ``check`` (with any drift state) leaves the
      filesystem byte-identical.
"""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from dontpanic_orchestrate import install_snapshot as snap
from dontpanic_orchestrate import reconcile
from dontpanic_orchestrate.capabilities import load_capabilities

# ── helpers ──────────────────────────────────────────────────────────────


def _write_snapshot_to(path: Path, snapshot: snap.InstallSnapshot) -> Path:
    """Write a snapshot at ``path`` with the same on-disk shape the
    F001 ``write_snapshot`` helper produces. Tests use this when they
    need to plant a synthetic snapshot whose fingerprints differ from
    the current repo's."""

    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        snapshot.model_dump(mode="json", exclude_none=True),
        indent=2,
        ensure_ascii=False,
    ) + "\n"
    path.write_text(body, encoding="utf-8")
    return path


def _write_fresh_cache(tmp_path: Path, *, snapshot_generated_at: str) -> Path:
    """Plant a capabilities-status cache whose ``generated_at`` post-dates
    the snapshot — so cache drift is *not* in play and tests can isolate
    one capability-drift kind at a time."""
    cache_path = tmp_path / "capabilities-status.json"
    # Bump one hour past the snapshot. Granularity is well above the
    # one-second floor our parser tolerates.
    snapshot_dt = snapshot_generated_at[:-1] if snapshot_generated_at.endswith("Z") else snapshot_generated_at
    fresh_iso = snapshot_generated_at.replace("T00:", "T01:")
    if fresh_iso == snapshot_generated_at:
        # Fallback: tack on a one-hour offset by suffix munging only if
        # the input didn't have the expected ``T00:`` marker.
        fresh_iso = snapshot_dt + "+01:00"
    cache_path.write_text(
        json.dumps({"generated_at": fresh_iso, "capabilities": []}) + "\n",
        encoding="utf-8",
    )
    return cache_path


def _fs_signature(root: Path) -> dict[str, tuple[int, int, str]]:
    """Capture a recursive (size, mode, sha256) snapshot of every file
    under ``root``. Used by the no-mutation test to assert that
    ``reconcile check`` does not touch disk."""

    sig: dict[str, tuple[int, int, str]] = {}
    if not root.exists():
        return sig
    for entry in root.rglob("*"):
        if entry.is_file():
            data = entry.read_bytes()
            sig[str(entry.relative_to(root))] = (
                len(data),
                stat.S_IMODE(entry.stat().st_mode),
                hashlib.sha256(data).hexdigest(),
            )
    return sig


# ── 1. clean state ───────────────────────────────────────────────────────


def test_check_clean_when_snapshot_matches_and_cache_fresh(
    tmp_path, monkeypatch, capsys
):
    """Snapshot generated from the current repo + a cache whose
    ``generated_at`` post-dates the snapshot → exit 0 + status clean."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    # Write a snapshot at a pinned time.
    s = snap.build_snapshot(
        profile="core",
        mcp_tool_names=(),
        now_iso="2026-05-23T00:00:00Z",
    )
    snap.write_snapshot(s, path=tmp_path / snap.SNAPSHOT_FILENAME)

    # Write a fresh cache (generated_at AFTER the snapshot).
    cache_path = tmp_path / "capabilities-status.json"
    cache_path.write_text(
        json.dumps({"generated_at": "2026-05-23T01:00:00Z", "capabilities": []})
        + "\n",
        encoding="utf-8",
    )

    rc = reconcile.reconcile_main(["check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "reconcile check (capabilities): clean" in out
    # Acceptance #5 mirror: a fresh cache should be reported as fresh.
    assert "status_cache: fresh" in out


# ── 2. missing snapshot ──────────────────────────────────────────────────


def test_check_missing_snapshot_exits_non_zero_with_baseline_command(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))
    # No snapshot file written.
    rc = reconcile.reconcile_main(["check"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "missing_snapshot" in out
    # Acceptance #2: exact baseline command.
    assert "$ dontpanic reconcile baseline --yes" in out


# ── 3. new capability ────────────────────────────────────────────────────


def test_check_reports_new_capability_with_fingerprints(tmp_path, monkeypatch):
    """A capability present in the current repo but missing from the
    snapshot must surface in ``new_capabilities`` carrying its
    fingerprints."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    # Build a snapshot that drops the first capability.
    index = load_capabilities()
    all_caps = tuple(index.all)
    assert len(all_caps) >= 2, "need at least 2 capabilities to drop one"
    dropped = all_caps[0]
    kept_caps = all_caps[1:]
    fingerprints = tuple(snap.capability_fingerprint(m) for m in kept_caps)
    truncated = snap.InstallSnapshot(
        schema_version=snap.SCHEMA_VERSION,
        generated_at="2026-05-23T00:00:00Z",
        dontpanic_version="0.0.0-test",
        profile="core",
        agent_manifest_schema_version="1.0",
        mcp_tool_names=(),
        capability_ids=tuple(m.id for m in kept_caps),
        capabilities=fingerprints,
        status_cache=None,
    )
    _write_snapshot_to(tmp_path / snap.SNAPSHOT_FILENAME, truncated)
    _write_fresh_cache(tmp_path, snapshot_generated_at=truncated.generated_at)

    result = reconcile.check_capabilities()
    # Vocabulary contract: a sole new capability surfaces the specific
    # status, not a generic "drift" catch-all.
    assert result.status == "new_capabilities"
    assert result.drift_kinds == ("new_capabilities",)
    new_ids = [c.capability_id for c in result.new_capabilities]
    assert dropped.id in new_ids
    # Per acceptance #3: report with current fingerprints.
    new_entry = next(c for c in result.new_capabilities if c.capability_id == dropped.id)
    assert len(new_entry.manifest_fingerprint) == 64
    assert len(new_entry.setup_steps_fingerprint) == 64
    # Per acceptance: include baseline command.
    assert "dontpanic reconcile baseline --yes" in result.next_commands


# ── 4. removed capability ────────────────────────────────────────────────


def test_check_reports_removed_capability_with_fingerprints(tmp_path, monkeypatch):
    """A capability that was in the snapshot but is no longer present
    in the current repo must surface in ``removed_capabilities``."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    # Build a snapshot with a synthetic extra capability that does NOT
    # exist in the current repo.
    index = load_capabilities()
    current_fingerprints = tuple(
        snap.capability_fingerprint(m) for m in index.all
    )
    ghost = snap.CapabilityFingerprint(
        capability_id="ghost-removed",
        manifest_fingerprint="a" * 64,
        setup_steps_fingerprint="b" * 64,
        setup_step_ids=("step_one", "step_two"),
    )
    inflated = snap.InstallSnapshot(
        schema_version=snap.SCHEMA_VERSION,
        generated_at="2026-05-23T00:00:00Z",
        dontpanic_version="0.0.0-test",
        profile="core",
        agent_manifest_schema_version="1.0",
        mcp_tool_names=(),
        capability_ids=tuple(c.capability_id for c in current_fingerprints) + ("ghost-removed",),
        capabilities=current_fingerprints + (ghost,),
        status_cache=None,
    )
    _write_snapshot_to(tmp_path / snap.SNAPSHOT_FILENAME, inflated)
    _write_fresh_cache(tmp_path, snapshot_generated_at=inflated.generated_at)

    result = reconcile.check_capabilities()
    # Vocabulary contract: removed-only drift reports the specific kind.
    assert result.status == "removed_capabilities"
    assert result.drift_kinds == ("removed_capabilities",)
    assert any(c.capability_id == "ghost-removed" for c in result.removed_capabilities)
    removed_entry = next(
        c for c in result.removed_capabilities if c.capability_id == "ghost-removed"
    )
    assert removed_entry.manifest_fingerprint == "a" * 64
    assert removed_entry.setup_step_ids == ("step_one", "step_two")


# ── 5. setup-step change (with renamed step_ids surfaced) ────────────────


def test_check_reports_setup_steps_change_and_renamed_step_ids(tmp_path, monkeypatch):
    """A capability whose setup_steps fingerprint OR setup_step_ids
    list changes must surface with ``setup_steps_changed=True`` and the
    old/new step_id lists must be visible in the result."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    index = load_capabilities()
    all_caps = tuple(index.all)
    target = all_caps[0]
    other_fingerprints = tuple(
        snap.capability_fingerprint(m) for m in all_caps[1:]
    )
    # Use the current manifest fingerprint, but mutate setup_step_ids
    # so the diff surfaces setup_steps_changed without manifest drift.
    current_fp = snap.capability_fingerprint(target)
    drifted = snap.CapabilityFingerprint(
        capability_id=target.id,
        manifest_fingerprint=current_fp.manifest_fingerprint,
        setup_steps_fingerprint="c" * 64,
        setup_step_ids=("legacy_step_id",),
    )
    snapshot = snap.InstallSnapshot(
        schema_version=snap.SCHEMA_VERSION,
        generated_at="2026-05-23T00:00:00Z",
        dontpanic_version="0.0.0-test",
        profile="core",
        agent_manifest_schema_version="1.0",
        mcp_tool_names=(),
        capability_ids=(target.id,) + tuple(c.capability_id for c in other_fingerprints),
        capabilities=(drifted,) + other_fingerprints,
        status_cache=None,
    )
    _write_snapshot_to(tmp_path / snap.SNAPSHOT_FILENAME, snapshot)
    _write_fresh_cache(tmp_path, snapshot_generated_at=snapshot.generated_at)

    result = reconcile.check_capabilities()
    # Vocabulary contract: setup-steps drift maps to changed_capabilities.
    assert result.status == "changed_capabilities"
    assert result.drift_kinds == ("changed_capabilities",)
    changed_entry = next(
        c for c in result.changed_capabilities if c.capability_id == target.id
    )
    assert changed_entry.manifest_changed is False
    assert changed_entry.setup_steps_changed is True
    assert changed_entry.old_setup_step_ids == ("legacy_step_id",)
    # Acceptance #4: changed setup_step_ids are named.
    assert changed_entry.new_setup_step_ids == current_fp.setup_step_ids


# ── 6. manifest-only change ──────────────────────────────────────────────


def test_check_reports_manifest_only_change(tmp_path, monkeypatch):
    """If the manifest fingerprint changes but setup_steps fingerprint
    AND setup_step_ids stay identical, only ``manifest_changed`` flips."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    index = load_capabilities()
    all_caps = tuple(index.all)
    target = all_caps[0]
    other_fingerprints = tuple(
        snap.capability_fingerprint(m) for m in all_caps[1:]
    )
    current_fp = snap.capability_fingerprint(target)
    drifted = snap.CapabilityFingerprint(
        capability_id=target.id,
        manifest_fingerprint="d" * 64,
        setup_steps_fingerprint=current_fp.setup_steps_fingerprint,
        setup_step_ids=current_fp.setup_step_ids,
    )
    snapshot = snap.InstallSnapshot(
        schema_version=snap.SCHEMA_VERSION,
        generated_at="2026-05-23T00:00:00Z",
        dontpanic_version="0.0.0-test",
        profile="core",
        agent_manifest_schema_version="1.0",
        mcp_tool_names=(),
        capability_ids=(target.id,) + tuple(c.capability_id for c in other_fingerprints),
        capabilities=(drifted,) + other_fingerprints,
        status_cache=None,
    )
    _write_snapshot_to(tmp_path / snap.SNAPSHOT_FILENAME, snapshot)
    _write_fresh_cache(tmp_path, snapshot_generated_at=snapshot.generated_at)

    result = reconcile.check_capabilities()
    # Vocabulary contract: manifest-only drift maps to changed_capabilities.
    assert result.status == "changed_capabilities"
    assert result.drift_kinds == ("changed_capabilities",)
    changed_entry = next(
        c for c in result.changed_capabilities if c.capability_id == target.id
    )
    assert changed_entry.manifest_changed is True
    assert changed_entry.setup_steps_changed is False
    assert changed_entry.old_manifest_fingerprint == "d" * 64
    assert changed_entry.new_manifest_fingerprint == current_fp.manifest_fingerprint


# ── 7. missing cache ─────────────────────────────────────────────────────


def test_check_reports_missing_status_cache_with_status_command(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    s = snap.build_snapshot(
        profile="core",
        mcp_tool_names=(),
        now_iso="2026-05-23T00:00:00Z",
    )
    snap.write_snapshot(s, path=tmp_path / snap.SNAPSHOT_FILENAME)
    # No cache file.

    rc = reconcile.reconcile_main(["check"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "status_cache: missing" in out
    # Acceptance #5: exact `dontpanic capabilities status` command.
    assert "$ dontpanic capabilities status" in out


def test_check_status_is_stale_status_cache_when_cache_missing_no_other_drift(
    tmp_path, monkeypatch
):
    """Cache-only drift surfaces ``status == stale_status_cache`` per the
    F002 vocabulary, not a catch-all ``drift`` string."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    s = snap.build_snapshot(
        profile="core",
        mcp_tool_names=(),
        now_iso="2026-05-23T00:00:00Z",
    )
    snap.write_snapshot(s, path=tmp_path / snap.SNAPSHOT_FILENAME)
    # No cache file → status_cache state=missing, no other drift.

    result = reconcile.check_capabilities()
    assert result.status == "stale_status_cache"
    assert result.drift_kinds == ("stale_status_cache",)
    assert result.next_commands == ("dontpanic capabilities status",)


# ── 8. stale cache ───────────────────────────────────────────────────────


def test_check_reports_stale_status_cache_with_status_command(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    # Snapshot stamped 2026-05-23, but cache stamped 2026-05-22 (older
    # by a day). Cache is stale.
    s = snap.build_snapshot(
        profile="core",
        mcp_tool_names=(),
        now_iso="2026-05-23T00:00:00Z",
    )
    snap.write_snapshot(s, path=tmp_path / snap.SNAPSHOT_FILENAME)
    cache_path = tmp_path / "capabilities-status.json"
    cache_path.write_text(
        json.dumps({"generated_at": "2026-05-22T00:00:00Z", "capabilities": []})
        + "\n",
        encoding="utf-8",
    )

    rc = reconcile.reconcile_main(["check"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "status_cache: stale" in out
    assert "$ dontpanic capabilities status" in out


# ── 9. JSON shape ────────────────────────────────────────────────────────


def test_check_json_envelope_has_stable_top_level_keys(
    tmp_path, monkeypatch, capsys
):
    """Acceptance #6: ``--format=json`` emits a stable envelope agents
    can parse. Keys are part of the contract — adding/removing one
    requires bumping the schema_version."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))
    rc = reconcile.reconcile_main(["check", "--format=json"])
    assert rc == 1  # no snapshot → drift
    body = json.loads(capsys.readouterr().out)
    expected_keys = {
        "schema_version",
        "area",
        "status",
        "drift_kinds",
        "checked_at",
        "snapshot_path",
        "snapshot_generated_at",
        "new_capabilities",
        "removed_capabilities",
        "changed_capabilities",
        "status_cache",
        "next_commands",
    }
    assert set(body.keys()) == expected_keys
    assert body["schema_version"] == reconcile.CHECK_SCHEMA_VERSION
    assert body["area"] == "capabilities"
    assert body["status"] == "missing_snapshot"
    # missing_snapshot is itself a drift kind for agents that key off the
    # list rather than the scalar status.
    assert body["drift_kinds"] == ["missing_snapshot"]
    assert body["next_commands"] == ["dontpanic reconcile baseline --yes"]


def test_check_json_drift_envelope_includes_fingerprint_pairs(
    tmp_path, monkeypatch, capsys
):
    """JSON envelope must include old/new fingerprints and step_ids for
    every ``changed`` entry — agents diff on these fields."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    index = load_capabilities()
    all_caps = tuple(index.all)
    target = all_caps[0]
    other_fingerprints = tuple(
        snap.capability_fingerprint(m) for m in all_caps[1:]
    )
    current_fp = snap.capability_fingerprint(target)
    drifted = snap.CapabilityFingerprint(
        capability_id=target.id,
        manifest_fingerprint="d" * 64,
        setup_steps_fingerprint=current_fp.setup_steps_fingerprint,
        setup_step_ids=current_fp.setup_step_ids,
    )
    snapshot = snap.InstallSnapshot(
        schema_version=snap.SCHEMA_VERSION,
        generated_at="2026-05-23T00:00:00Z",
        dontpanic_version="0.0.0-test",
        profile="core",
        agent_manifest_schema_version="1.0",
        mcp_tool_names=(),
        capability_ids=(target.id,) + tuple(c.capability_id for c in other_fingerprints),
        capabilities=(drifted,) + other_fingerprints,
        status_cache=None,
    )
    _write_snapshot_to(tmp_path / snap.SNAPSHOT_FILENAME, snapshot)
    _write_fresh_cache(tmp_path, snapshot_generated_at=snapshot.generated_at)

    rc = reconcile.reconcile_main(["check", "--format=json"])
    assert rc == 1
    body = json.loads(capsys.readouterr().out)
    # The status must reflect the specific drift kind, not a generic
    # "drift" string, and drift_kinds must enumerate it.
    assert body["status"] == "changed_capabilities"
    assert body["drift_kinds"] == ["changed_capabilities"]
    entry = next(
        c for c in body["changed_capabilities"] if c["capability_id"] == target.id
    )
    assert entry["manifest_changed"] is True
    assert entry["setup_steps_changed"] is False
    assert entry["old_manifest_fingerprint"] == "d" * 64
    assert entry["new_manifest_fingerprint"] == current_fp.manifest_fingerprint
    assert entry["old_setup_step_ids"] == list(current_fp.setup_step_ids)
    assert entry["new_setup_step_ids"] == list(current_fp.setup_step_ids)


# ── 10. no mutation ──────────────────────────────────────────────────────


def test_check_never_mutates_filesystem(tmp_path, monkeypatch):
    """Acceptance #7: ``reconcile check`` must never write to disk —
    not the snapshot, not the cache, not a temp file. A recursive
    pre/post signature of every file under DONTPANIC_HOME must match
    byte-for-byte."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    # Plant a snapshot with synthetic drift + a stale cache so the
    # check has reason to spit out next commands.
    s = snap.build_snapshot(
        profile="core",
        mcp_tool_names=(),
        now_iso="2026-05-23T00:00:00Z",
    )
    snap.write_snapshot(s, path=tmp_path / snap.SNAPSHOT_FILENAME)
    cache_path = tmp_path / "capabilities-status.json"
    cache_path.write_text(
        json.dumps({"generated_at": "2026-05-22T00:00:00Z", "capabilities": []})
        + "\n",
        encoding="utf-8",
    )

    before = _fs_signature(tmp_path)
    rc = reconcile.reconcile_main(["check"])
    assert rc == 1  # stale cache → drift
    after = _fs_signature(tmp_path)
    assert before == after, "reconcile check must not mutate the filesystem"


def test_check_missing_snapshot_does_not_create_snapshot(tmp_path, monkeypatch):
    """Subset of the no-mutation contract: even when the snapshot is
    missing, ``check`` must not attempt to create one (that's
    ``baseline``'s job, gated on ``--yes``)."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))
    rc = reconcile.reconcile_main(["check"])
    assert rc == 1
    assert not (tmp_path / snap.SNAPSHOT_FILENAME).exists()


# ── 11. structural guards on the diff function itself ───────────────────


def test_diff_empty_when_inputs_match():
    """Pure-function guard: diffing a snapshot's caps against itself
    yields no drift entries."""
    index = load_capabilities()
    fingerprints = tuple(snap.capability_fingerprint(m) for m in index.all)
    new, removed, changed = reconcile.diff_capability_fingerprints(
        fingerprints, fingerprints
    )
    assert new == ()
    assert removed == ()
    assert changed == ()


def test_evaluate_status_cache_unknown_when_unparseable(tmp_path):
    """Guard for the ``unknown`` branch — a cache without a parseable
    ``generated_at`` must surface as drift-worthy, not silently treated
    as fresh."""
    cache_path = tmp_path / "capabilities-status.json"
    cache_path.write_text("not-json-at-all", encoding="utf-8")
    fake_snapshot = snap.InstallSnapshot(
        schema_version=snap.SCHEMA_VERSION,
        generated_at="2026-05-23T00:00:00Z",
        dontpanic_version="0.0.0-test",
        profile="core",
        agent_manifest_schema_version="1.0",
        mcp_tool_names=(),
        capability_ids=(),
        capabilities=(),
        status_cache=None,
    )
    state = reconcile.evaluate_status_cache(fake_snapshot, cache_path=cache_path)
    assert state.state == "unknown"


def test_check_combined_drift_status_picks_highest_priority_and_lists_all(
    tmp_path, monkeypatch
):
    """When multiple drift kinds apply simultaneously, ``status`` collapses
    to the highest-priority kind and ``drift_kinds`` enumerates every
    applicable kind in priority order.

    Setup plants:
      * a snapshot whose first capability has a drifted manifest →
        ``changed_capabilities``
      * a stale cache file (older than the snapshot) →
        ``stale_status_cache``

    Priority dictates ``status == "changed_capabilities"`` because
    capability drift outranks cache staleness in :data:`_DRIFT_PRIORITY`.
    Both kinds must still appear in ``drift_kinds``.
    """
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    index = load_capabilities()
    all_caps = tuple(index.all)
    target = all_caps[0]
    other_fingerprints = tuple(
        snap.capability_fingerprint(m) for m in all_caps[1:]
    )
    current_fp = snap.capability_fingerprint(target)
    drifted = snap.CapabilityFingerprint(
        capability_id=target.id,
        manifest_fingerprint="d" * 64,
        setup_steps_fingerprint=current_fp.setup_steps_fingerprint,
        setup_step_ids=current_fp.setup_step_ids,
    )
    snapshot = snap.InstallSnapshot(
        schema_version=snap.SCHEMA_VERSION,
        generated_at="2026-05-23T00:00:00Z",
        dontpanic_version="0.0.0-test",
        profile="core",
        agent_manifest_schema_version="1.0",
        mcp_tool_names=(),
        capability_ids=(target.id,) + tuple(c.capability_id for c in other_fingerprints),
        capabilities=(drifted,) + other_fingerprints,
        status_cache=None,
    )
    _write_snapshot_to(tmp_path / snap.SNAPSHOT_FILENAME, snapshot)
    cache_path = tmp_path / "capabilities-status.json"
    cache_path.write_text(
        json.dumps({"generated_at": "2026-05-22T00:00:00Z", "capabilities": []})
        + "\n",
        encoding="utf-8",
    )

    result = reconcile.check_capabilities()
    assert result.status == "changed_capabilities"
    assert result.drift_kinds == ("changed_capabilities", "stale_status_cache")
    # Both remediation commands must appear, baseline first.
    assert result.next_commands == (
        "dontpanic reconcile baseline --yes",
        "dontpanic capabilities status",
    )


@pytest.mark.parametrize(
    "subcommand",
    ["check", "check --area=capabilities", "check --format=text"],
)
def test_check_argv_variants_accepted(tmp_path, monkeypatch, subcommand):
    """Argparse smoke: every advertised invocation parses without
    falling through to the help screen (which returns exit 2)."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))
    rc = reconcile.reconcile_main(subcommand.split())
    # Missing snapshot → exit 1 (drift). The point of this test is that
    # we DID NOT get exit 2 (usage error) from argparse.
    assert rc in (0, 1)
