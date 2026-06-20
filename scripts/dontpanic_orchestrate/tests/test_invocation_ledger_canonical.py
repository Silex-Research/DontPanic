"""Plan 2026-06-17-001 F001 — canonical_repo stamping, compaction invariants, and
the C8 sidecar-lock protocol for the invocation ledger.

Covers:
  * C3 three-case resolution (durable+git / durable+non-git / temp->durable / temp-unresolved)
    including the linked-worktree collapse-to-main-checkout case;
  * start_recording stamps canonical_repo when durable, omits it from a temp 3b path;
  * repo.path_key still drives bucket logic (C2 regression);
  * compact_ledger observed_count summation (legacy rows count as 1), canonical_repo
    survival, before==after canonical observed_count, and fail-closed mixed-attribution
    compaction conflict;
  * no raw home path / raw origin URL ever persisted (C1);
  * C8 sidecar lock on append + compaction, fail-closed on flock-unavailable, and
    compaction-vs-append / compaction-vs-rewriter races (no lost write, no stale inode).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import invocation_ledger as il  # noqa: E402
from dontpanic_orchestrate import operator_console as oc  # noqa: E402

_NOW = "2026-06-17T00:00:00Z"
_LATER = "2026-06-17T00:00:01Z"


# ──────────────────────────────  helpers  ──────────────────────────────


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True)


def _git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q"], path)
    _run(["git", "config", "user.email", "t@example.com"], path)
    _run(["git", "config", "user.name", "tester"], path)
    (path / "README.md").write_text("seed")
    _run(["git", "add", "-A"], path)
    _run(["git", "commit", "-qm", "init"], path)


def _rp(p: str | Path) -> str:
    return os.path.realpath(str(p))


def _read_ledger() -> list[dict]:
    p = il.ledger_path()
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


@pytest.fixture
def temproot(tmp_path, monkeypatch):
    """A synthetic temp prefix INSIDE tmp_path. Anything under it is treated as
    ephemeral; everything else under tmp_path is treated as durable — so we can
    exercise the durable/temp split without depending on the real /tmp."""
    synth = tmp_path / "ephemeral"
    synth.mkdir()
    monkeypatch.setattr(il, "_TEMP_PREFIXES", (_rp(synth),))
    return synth


# ──────────────────────────────  C3 three cases  ──────────────────────────────


def test_c3_case1_durable_git_checkout_canonical_is_self(temproot, tmp_path):
    repo = tmp_path / "durable-main"
    _git_init(repo)
    res = il.canonicalize_repo(repo)
    assert _rp(res["canonical_root"]) == _rp(repo)
    assert res["durable_checkout"] is True


def test_c3_case1_durable_linked_worktree_collapses_to_main(temproot, tmp_path):
    main = tmp_path / "durable-main2"
    _git_init(main)
    wt = tmp_path / "durable-wt"
    _run(["git", "worktree", "add", "-q", "-b", "feature", str(wt)], main)
    res = il.canonicalize_repo(wt)
    # worktrees.py only COMPARES common-dirs; the new helper returns the MAIN root
    assert _rp(res["canonical_root"]) == _rp(main)
    assert res["durable_checkout"] is True


def test_c3_case2_durable_non_git_canonical_is_self(temproot, tmp_path):
    plain = tmp_path / "durable-plain"
    plain.mkdir()
    res = il.canonicalize_repo(plain)
    assert _rp(res["canonical_root"]) == _rp(plain)
    assert res["durable_checkout"] is True


def test_c3_case3a_temp_worktree_resolves_durable_main(temproot, tmp_path):
    main = tmp_path / "durable-main3"
    _git_init(main)
    wt = temproot / "tmp-wt"
    _run(["git", "worktree", "add", "-q", "-b", "tfeature", str(wt)], main)
    res = il.canonicalize_repo(wt)
    assert _rp(res["canonical_root"]) == _rp(main)
    assert res["durable_checkout"] is True  # durability is the canonical repo's property


def test_c3_case3b_temp_non_git_yields_no_canonical(temproot):
    plain = temproot / "tmp-plain"
    plain.mkdir()
    res = il.canonicalize_repo(plain)
    assert res["canonical_root"] is None
    assert res["durable_checkout"] is False


def test_c3_case3b_temp_git_resolving_to_temp_yields_no_canonical(temproot):
    repo = temproot / "tmp-repo"
    _git_init(repo)
    res = il.canonicalize_repo(repo)
    # canonical root resolves but is itself temp -> never self-canonicalize a temp path
    assert res["canonical_root"] is None


# ──────────────────────────────  start_recording stamping  ──────────────────────────────


def test_start_recording_stamps_durable_canonical_repo(temproot, tmp_path, monkeypatch):
    repo = tmp_path / "durable-rec"
    _git_init(repo)
    monkeypatch.chdir(repo)
    rec = il.start_recording(["agent", "status"], now=_NOW, install_signal=False)
    rec.finalize(il.RESULT_OK, now=_LATER)
    rows = _read_ledger()
    assert len(rows) == 1
    cr = rows[0]["canonical_repo"]
    assert cr["durable_checkout"] is True
    assert cr["path_key"] and cr["path_display"]
    # C2: observed repo.path_key is still present and untouched
    assert rows[0]["repo"]["path_key"]


def test_start_recording_omits_canonical_for_temp_3b(temproot, monkeypatch):
    run_dir = temproot / "tmp-run"
    run_dir.mkdir()
    monkeypatch.chdir(run_dir)
    rec = il.start_recording(["agent", "status"], now=_NOW, install_signal=False)
    rec.finalize(il.RESULT_OK, now=_LATER)
    rows = _read_ledger()
    assert len(rows) == 1
    assert "canonical_repo" not in rows[0]  # absent, never a temp canonical


def test_start_recording_marks_temp_worktree_observation(temproot, tmp_path, monkeypatch):
    main = tmp_path / "durable-main4"
    _git_init(main)
    wt = temproot / "tmp-wt2"
    _run(["git", "worktree", "add", "-q", "-b", "wtfeat", str(wt)], main)
    monkeypatch.chdir(wt)
    rec = il.start_recording(["agent", "status"], now=_NOW, install_signal=False)
    rec.finalize(il.RESULT_OK, now=_LATER)
    cr = _read_ledger()[0]["canonical_repo"]
    assert cr["durable_checkout"] is True
    assert _rp(cr["path_display"]) or cr["path_display"]
    assert cr.get("observed_under_temp_prefix") is True


# ──────────────────────────────  legacy load + bucket regression (C2)  ──────────────────────────────


def test_legacy_record_without_canonical_still_loads():
    legacy = {
        "repo": {"path_key": "k", "path_display": "<home>/r"},
        "branch": "main", "plan": None, "locality": "local",
        "last_seen": _NOW, "result": "ok",
    }
    # no canonical_repo, no observed_count — must behave as count 1, no key
    assert il._record_observed_count(legacy) == 1
    assert il._record_canonical_key(legacy) is None
    assert il._bucket_key(legacy)  # does not raise


def test_bucket_key_ignores_canonical_repo():
    base = {"repo": {"path_key": "k"}, "branch": "main", "plan": None, "locality": "loc"}
    r1 = dict(base, canonical_repo={"path_key": "A", "path_display": "x", "durable_checkout": True})
    r2 = dict(base, canonical_repo={"path_key": "B", "path_display": "y", "durable_checkout": True})
    r3 = dict(base)
    assert il._bucket_key(r1) == il._bucket_key(r2) == il._bucket_key(r3)


# ──────────────────────────────  compaction count invariance (C2)  ──────────────────────────────


def _canonical_observed_counts(rows: list[dict]) -> dict[str, int]:
    """F003-style read: sum observed_count per canonical repo, ignoring rows that
    carry a compaction conflict or no canonical_repo."""
    out: dict[str, int] = {}
    for r in rows:
        if r.get("canonical_compaction_conflict"):
            continue
        key = il._record_canonical_key(r)
        if key is None:
            continue
        out[key] = out.get(key, 0) + il._record_observed_count(r)
    return out


def _seed(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def test_compaction_sums_observed_count_and_preserves_canonical(tmp_path):
    path = tmp_path / "invocations.jsonl"
    canonical = {"path_key": "CANON", "path_display": "<home>/proj", "durable_checkout": True}
    base = {
        "operator_surface": "terminal", "agent_runtime": "claude", "role": "implementer",
        "execution_locality": "plan_worktree", "locality": "plan_worktree",
        "repo": {"path_display": "<home>/r", "path_key": "obs"},
        "worktree": None, "branch": "main", "plan": "p", "command": "ps", "result": "ok",
    }
    counts = [3, 2, None]  # third is legacy (no observed_count) -> counts as 1; total 6
    recs = []
    for t, c in enumerate(counts):
        r = dict(base, canonical_repo=dict(canonical))
        if c is not None:
            r["observed_count"] = c
        r["started_at"] = r["finished_at"] = r["last_seen"] = f"2026-06-17T12:0{t}:00Z"
        recs.append(r)
    _seed(path, recs)
    before = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    buckets_before = il.derive_buckets(before)
    canon_before = _canonical_observed_counts(before)

    summary = il.compact_ledger(path, max_records=10)
    after = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    assert summary["records_before"] == 3
    assert len(after) == 1  # collapsed to one preserved row
    row = after[0]
    assert row["observed_count"] == 6  # 3 + 2 + 1(legacy)
    assert row["canonical_repo"]["path_key"] == "CANON"  # canonical survives compaction
    assert row["last_seen"] == "2026-06-17T12:02:00Z"  # most recent preserved
    assert il.derive_buckets(after) == buckets_before  # bucket grouping invariant
    # F003 reads identical canonical observed_count before and after (before==after)
    assert canon_before == {"CANON": 6}
    assert _canonical_observed_counts(after) == canon_before


# ──────────────────────────────  mixed-attribution conflict (C2 fail-closed)  ──────────────────────────────


def test_compaction_mixed_attribution_is_fail_closed(tmp_path):
    path = tmp_path / "invocations.jsonl"
    base = {
        "operator_surface": "terminal", "agent_runtime": "claude", "role": "implementer",
        "execution_locality": "local", "locality": "local",
        "repo": {"path_display": "<home>/r", "path_key": "obs"},
        "worktree": None, "branch": "main", "plan": "p", "command": "ps", "result": "ok",
    }
    canonical = {"path_key": "CANON", "path_display": "<home>/proj", "durable_checkout": True}
    r_canon = dict(base, canonical_repo=dict(canonical), observed_count=4,
                   last_seen="2026-06-17T12:00:00Z")
    r_legacy = dict(base, last_seen="2026-06-17T12:01:00Z")  # no canonical_repo
    _seed(path, [r_canon, r_legacy])

    il.compact_ledger(path, max_records=10)
    after = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(after) == 1
    row = after[0]
    assert row.get("canonical_compaction_conflict") is True
    assert "canonical_repo" not in row  # canonical attribution omitted
    assert "observed_count" not in row  # no canonical observed_count carried
    # F003 ignores it: neither inflated nor silently dropped
    assert _canonical_observed_counts(after) == {}


def test_compaction_multiple_canonical_keys_is_fail_closed(tmp_path):
    path = tmp_path / "invocations.jsonl"
    base = {
        "repo": {"path_display": "<home>/r", "path_key": "obs"},
        "branch": "main", "plan": "p", "locality": "local", "result": "ok",
    }
    a = dict(base, canonical_repo={"path_key": "A", "path_display": "<home>/a", "durable_checkout": True},
             observed_count=2, last_seen="2026-06-17T12:00:00Z")
    b = dict(base, canonical_repo={"path_key": "B", "path_display": "<home>/b", "durable_checkout": True},
             observed_count=5, last_seen="2026-06-17T12:01:00Z")
    _seed(path, [a, b])
    il.compact_ledger(path, max_records=10)
    after = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(after) == 1
    assert after[0].get("canonical_compaction_conflict") is True
    assert "canonical_repo" not in after[0]
    assert _canonical_observed_counts(after) == {}


# ──────────────────────────────  no-secret-shape (C1)  ──────────────────────────────


def test_origin_url_never_persisted_only_hashed(temproot, tmp_path):
    repo = tmp_path / "durable-origin"
    _git_init(repo)
    secret_url = "https://ghp_0123456789abcdefghij0123456789abcdefij@github.com/o/r.git"
    _run(["git", "remote", "add", "origin", secret_url], repo)
    canonical = il._stamp_canonical_repo(repo)
    assert canonical is not None
    blob = json.dumps(canonical)
    assert "ghp_" not in blob and secret_url not in blob
    assert len(canonical["origin_key"]) == 16  # hash-shaped, not the raw URL
    # the rendered record carrying the new fields passes the shared no-secret gate
    oc._assert_no_secret_shapes({"canonical_repo": canonical})


def test_canonical_repo_display_is_home_scrubbed(monkeypatch, temproot, tmp_path):
    # a canonical path under $HOME must persist as a scrubbed display, never raw home
    fake_home = tmp_path / "home" / "me"
    fake_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    project = fake_home / "Projects" / "thing"
    project.mkdir(parents=True)
    canonical = il._stamp_canonical_repo(project)  # durable non-git -> self-canonical
    assert canonical is not None
    assert str(fake_home) not in canonical["path_display"]


# ──────────────────────────────  C8 sidecar lock  ──────────────────────────────


def test_append_acquires_sidecar_lock(tmp_path):
    ledger = tmp_path / "invocations.jsonl"
    il._atomic_append_line(ledger, json.dumps({"a": 1}))
    assert (tmp_path / "invocations.jsonl.lock").exists()
    assert json.loads(ledger.read_text().strip()) == {"a": 1}


def test_append_fails_closed_when_flock_unavailable_no_unlocked_write(tmp_path, monkeypatch):
    """C8: the live append must NOT touch the data file without a held sidecar
    lock. When flock is unavailable the append raises LedgerLockUnavailable
    BEFORE the data file is opened — proven by the data file never existing."""
    ledger = tmp_path / "invocations.jsonl"

    def _boom(*_a, **_k):
        raise OSError("flock unavailable on this platform")

    monkeypatch.setattr(il.fcntl, "flock", _boom)

    with pytest.raises(il.LedgerLockUnavailable):
        il._atomic_append_line(ledger, json.dumps({"a": 1}))

    # the data file was never opened/written without the lock held
    assert not ledger.exists()


def test_append_flock_unavailable_is_non_fatal_via_finalize(tmp_path, monkeypatch):
    """The fail-closed lock stays non-fatal for the command: finalize swallows
    LedgerLockUnavailable (it is an OSError -> Exception) and writes nothing."""
    ledger = tmp_path / "invocations.jsonl"
    monkeypatch.setattr(il, "ledger_path", lambda: ledger)

    def _boom(*_a, **_k):
        raise OSError("flock unavailable on this platform")

    monkeypatch.setattr(il.fcntl, "flock", _boom)

    rec = il.start_recording(["dontpanic", "status"], install_signal=False)
    rec.finalize("ok")  # must not raise

    assert not ledger.exists()  # no unlocked write occurred


def test_compaction_fails_closed_when_flock_unavailable(tmp_path, monkeypatch):
    ledger = tmp_path / "invocations.jsonl"
    ledger.write_text(json.dumps({"repo": {"path_key": "k"}, "branch": "b",
                                  "plan": None, "locality": "l", "last_seen": _NOW}) + "\n")

    def _boom(*_a, **_k):
        raise OSError("flock unavailable on this platform")

    monkeypatch.setattr(il.fcntl, "flock", _boom)
    with pytest.raises(SystemExit) as ei:
        il.compact_ledger(ledger, max_records=10)
    assert ei.value.code == 2
    # the rewrite did NOT happen — original content intact
    assert "repo" in json.loads(ledger.read_text().splitlines()[0])


def test_compaction_vs_append_no_lost_write_no_stale_inode(tmp_path):
    ledger = tmp_path / "invocations.jsonl"
    ledger.write_text(json.dumps({"v": "orig"}) + "\n")
    lock_path = tmp_path / "invocations.jsonl.lock"

    # main thread holds the rewriter sidecar lock (compaction in flight)
    lock_fh = open(lock_path, "a+", encoding="utf-8")
    il.fcntl.flock(lock_fh.fileno(), il.fcntl.LOCK_EX)

    started = threading.Event()

    def _appender() -> None:
        started.set()
        il._atomic_append_line(ledger, json.dumps({"v": "appended"}))

    t = threading.Thread(target=_appender)
    t.start()
    started.wait(2)
    time.sleep(0.25)  # appender is now blocked on the sidecar lock

    # perform the compaction-style atomic rename while holding the lock
    tmp = tmp_path / "invocations.jsonl.compact.tmp"
    tmp.write_text(json.dumps({"v": "compacted"}) + "\n")
    os.replace(tmp, ledger)

    il.fcntl.flock(lock_fh.fileno(), il.fcntl.LOCK_UN)
    lock_fh.close()
    t.join(timeout=5)
    assert not t.is_alive()

    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    vals = {r["v"] for r in rows}
    assert "compacted" in vals  # rewrite survived: append did not clobber a stale inode
    assert "appended" in vals  # append not lost: it landed on the new inode


def test_compaction_vs_backfill_rewriter_race_serializes(tmp_path):
    """C8: two whole-file rewriters — ``compact_ledger`` and a backfill-style
    rewriter — each performing the FULL read + temp-file + rename sequence, race
    concurrently under the shared ``_rewriter_sidecar_lock``. The lock serializes
    them, so neither renames onto a stale inode and neither write is lost: the
    final ledger reflects BOTH the compaction collapse AND the backfill mutation,
    in whichever serial order won.

    Without the lock this is exactly the lost-write / stale-inode bug: both read
    the same 2-record inode, both build a temp, and the last rename wins —
    yielding either an un-collapsed (len 2) or an un-backfilled result. The
    ``len == 1 and backfilled`` assertion below fails in that case, so the test
    genuinely exercises the C8 compaction-vs-backfill protocol."""
    ledger = tmp_path / "invocations.jsonl"
    base = {
        "repo": {"path_key": "obs", "path_display": "<home>/r"},
        "branch": "main", "plan": "p", "locality": "local", "result": "ok",
    }
    # two duplicate records in one bucket so compaction collapses 2 -> 1
    recs = [dict(base, observed_count=1, last_seen=f"2026-06-17T12:0{t}:00Z") for t in range(2)]
    _seed(ledger, recs)

    def _backfill_rewriter() -> None:
        # whole-file rewriter mirroring F005 backfill: read fresh UNDER the lock,
        # stamp every row, atomic temp-file + rename — the same protocol shape as
        # compaction, so the two must mutually exclude.
        with il._rewriter_sidecar_lock(ledger):
            rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
            for row in rows:
                row["backfilled"] = True
            time.sleep(0.2)  # widen the race window while holding the lock
            tmp = ledger.with_suffix(ledger.suffix + ".backfill.tmp")
            tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
            os.replace(tmp, ledger)

    errors: list[BaseException] = []

    def _compactor() -> None:
        try:
            il.compact_ledger(ledger, max_records=10)
        except BaseException as exc:  # noqa: BLE001 — surface any race failure to the assert
            errors.append(exc)

    t1 = threading.Thread(target=_backfill_rewriter)
    t2 = threading.Thread(target=_compactor)
    t1.start()
    t2.start()
    t1.join(5)
    t2.join(5)
    assert not t1.is_alive() and not t2.is_alive()
    assert not errors

    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    # compaction collapsed the duplicate bucket -> exactly one row survives
    # (proves the compaction rename was not lost to a stale-inode clobber)
    assert len(rows) == 1
    # backfill mutation survived in whichever serial order won
    # (proves the backfill rename was not lost to a stale-inode clobber)
    assert rows[0].get("backfilled") is True
    # observed_count summed across the collapsed bucket regardless of order
    assert rows[0].get("observed_count") == 2


def test_two_rewriters_are_mutually_exclusive(tmp_path):
    target = tmp_path / "invocations.jsonl"
    target.write_text("")
    order: list[str] = []
    held = threading.Event()
    release = threading.Event()

    def _first() -> None:
        with il._rewriter_sidecar_lock(target):
            order.append("first-acquire")
            held.set()
            release.wait(2)
            order.append("first-release")

    def _second() -> None:
        held.wait(2)
        with il._rewriter_sidecar_lock(target):
            order.append("second-acquire")

    t1 = threading.Thread(target=_first)
    t2 = threading.Thread(target=_second)
    t1.start()
    held.wait(2)
    t2.start()
    time.sleep(0.25)
    assert "second-acquire" not in order  # blocked while first holds the lock
    release.set()
    t1.join(2)
    t2.join(2)
    assert order == ["first-acquire", "first-release", "second-acquire"]
