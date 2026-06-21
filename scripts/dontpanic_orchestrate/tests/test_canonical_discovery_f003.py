"""Plan 2026-06-17-001 F003 — ledger adapter + registry adapter + pure reconcile.

Covers the acceptance matrix: the ledger adapter's skip/aggregate/timestamp rules
(C2/C5/C6), the registry adapter's enrichment + active-eligible dedup (C5), the pure
five-state reconcile projection and its truth table (C5), durability gating (C3),
suggested_name derivation (C5), and the metadata-only / command-blind contract (C6).
"""

from __future__ import annotations

import datetime
import hashlib
import os

import pytest

from dontpanic_orchestrate import canonical_discovery as cd
from dontpanic_orchestrate import invocation_ledger as il
from dontpanic_orchestrate.projects_registry import PROJECT_NAME_PATTERN, ProjectEntry

NOW = "2026-06-20T00:00:00Z"


def _now_dt() -> datetime.datetime:
    return datetime.datetime(2026, 6, 20, tzinfo=datetime.timezone.utc)


def _entry(name: str, path: str, *, active: bool | None = None) -> ProjectEntry:
    return ProjectEntry(name=name, path=path, created_at=NOW, active=active)


def _canon(path_key: str, *, display: str = "<home>/src/DontPanic", durable: bool = True) -> dict:
    return {"path_key": path_key, "path_display": display, "durable_checkout": durable}


def _record(*, canonical=None, last_seen="2026-06-19T00:00:00Z", observed_count=None,
            conflict=False, command="dontpanic build", repo_key="obs1"):
    rec: dict = {
        "repo": {"path_key": repo_key, "path_display": "<home>/wt"},
        "command": command,
        "last_seen": last_seen,
        "result": "ok",
    }
    if canonical is not None:
        rec["canonical_repo"] = canonical
    if observed_count is not None:
        rec["observed_count"] = observed_count
    if conflict:
        rec["canonical_compaction_conflict"] = True
    return rec


# ─────────────────────────  ledger adapter (observed_canonical)  ─────────────────────────


def test_ledger_adapter_skips_records_without_canonical_repo():
    rows = cd.observed_canonical_from_ledger([_record(canonical=None)])
    assert rows == []


def test_ledger_adapter_skips_compaction_conflict_rows():
    rows = cd.observed_canonical_from_ledger(
        [_record(canonical=_canon("k1"), conflict=True)]
    )
    assert rows == []


def test_ledger_adapter_skips_non_durable_canonical():
    rows = cd.observed_canonical_from_ledger(
        [_record(canonical=_canon("k1", durable=False))]
    )
    assert rows == []


def test_ledger_adapter_aggregates_count_and_max_last_seen_by_canonical_key():
    records = [
        _record(canonical=_canon("k1"), last_seen="2026-06-10T00:00:00Z"),  # legacy -> 1
        _record(canonical=_canon("k1"), last_seen="2026-06-18T00:00:00Z", observed_count=3),
        _record(canonical=_canon("k1"), last_seen="2026-06-12T00:00:00Z", observed_count=2),
    ]
    rows = cd.observed_canonical_from_ledger(records)
    assert len(rows) == 1
    row = rows[0]
    assert row["canonical_repo_key"] == "k1"
    assert row["observed_count"] == 1 + 3 + 2
    assert row["last_seen"] == "2026-06-18T00:00:00Z"
    assert row["durable_checkout"] is True


def test_ledger_adapter_legacy_rows_count_as_one():
    rows = cd.observed_canonical_from_ledger(
        [_record(canonical=_canon("k1")), _record(canonical=_canon("k1"))]
    )
    assert rows[0]["observed_count"] == 2


def test_ledger_adapter_preserves_scrubbed_display_and_origin_key():
    canon = {**_canon("k1", display="<home>/src/DontPanic"), "origin_key": "abc123def456"}
    rows = cd.observed_canonical_from_ledger([_record(canonical=canon)])
    assert rows[0]["path_display"] == "<home>/src/DontPanic"
    assert rows[0]["origin_key"] == "abc123def456"


def test_ledger_adapter_mixed_attribution_does_not_inflate_or_drop():
    # A conflict-marked row carrying k1 must NOT contribute to k1's count, and a clean
    # k1 row must still aggregate honestly.
    records = [
        _record(canonical=_canon("k1"), observed_count=2),
        _record(canonical=_canon("k1"), conflict=True, observed_count=99),
    ]
    rows = cd.observed_canonical_from_ledger(records)
    assert len(rows) == 1
    assert rows[0]["observed_count"] == 2  # 99 from the conflict row is ignored


def test_ledger_adapter_skips_invalid_last_seen_without_poisoning_max():
    records = [
        _record(canonical=_canon("k1"), last_seen="2026-06-15T00:00:00Z", observed_count=2),
        _record(canonical=_canon("k1"), last_seen="not-a-timestamp", observed_count=1),
    ]
    rows = cd.observed_canonical_from_ledger(records)
    assert rows[0]["last_seen"] == "2026-06-15T00:00:00Z"
    assert rows[0]["observed_count"] == 3  # invalid-timestamp row still counts


def test_ledger_adapter_all_invalid_last_seen_emits_none():
    records = [_record(canonical=_canon("k1"), last_seen=None, observed_count=2)]
    rows = cd.observed_canonical_from_ledger(records)
    assert rows[0]["last_seen"] is None
    assert rows[0]["observed_count"] == 2


def test_ledger_adapter_never_reads_command():
    secret_command = "dontpanic build --token ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # noqa: S105 — deliberately secret-shaped fixture
    rows = cd.observed_canonical_from_ledger(
        [_record(canonical=_canon("k1"), command=secret_command)]
    )
    # The aggregate carries no trace of command anywhere.
    assert "command" not in rows[0]
    for value in rows[0].values():
        assert "ghp_" not in str(value)


# ─────────────────────────  registry adapter (registered_canonical)  ─────────────────────────


def test_registry_adapter_missing_path_emits_null_key_and_registry_path_key(tmp_path):
    missing = str(tmp_path / "gone")
    rows = cd.registered_canonical_from_registry([_entry("ghost", missing)])
    assert len(rows) == 1
    row = rows[0]
    assert row["canonical_repo_key"] is None
    assert row["path_exists"] is False
    assert row["canonicalization_status"] == cd.CANON_MISSING
    expected = hashlib.sha256(os.path.abspath(missing).encode()).hexdigest()[:16]
    assert row["registry_path_key"] == expected


def test_registry_adapter_unresolved_path_under_temp(monkeypatch, tmp_path):
    real = tmp_path / "repo"
    real.mkdir()
    # Force canonicalize_repo to behave as a temp/3b unresolved path.
    monkeypatch.setattr(il, "canonicalize_repo", lambda root: {"canonical_root": None})
    rows = cd.registered_canonical_from_registry([_entry("temp-proj", str(real))])
    row = rows[0]
    assert row["canonical_repo_key"] is None
    assert row["path_exists"] is True
    assert row["canonicalization_status"] == cd.CANON_UNRESOLVED
    assert row["registry_path_key"]


def test_registry_adapter_existing_canonicalized_path(monkeypatch, tmp_path):
    real = tmp_path / "repo"
    real.mkdir()
    monkeypatch.setattr(
        il, "canonicalize_repo",
        lambda root: {"canonical_root": str(real), "durable_checkout": True, "origin_url": None},
    )
    rows = cd.registered_canonical_from_registry([_entry("dontpanic", str(real))])
    row = rows[0]
    assert row["canonicalization_status"] == cd.CANON_OK
    assert row["canonical_repo_key"] == il.make_path_pair(str(real))["path_key"]
    assert row["registry_conflict"] is False


def test_registry_adapter_dedupes_active_entries_to_lexicographically_first(monkeypatch, tmp_path):
    real = tmp_path / "repo"
    real.mkdir()
    monkeypatch.setattr(
        il, "canonicalize_repo",
        lambda root: {"canonical_root": str(real), "durable_checkout": True, "origin_url": None},
    )
    entries = [
        _entry("zebra", str(real), active=True),
        _entry("alpha", str(real), active=True),
    ]
    rows = cd.registered_canonical_from_registry(entries)
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "alpha"  # lexicographically first wins
    assert row["registry_conflict"] is True
    assert row["conflicting_registry_names"] == ["alpha", "zebra"]


def test_registry_adapter_inactive_first_never_suppresses_active(monkeypatch, tmp_path):
    real = tmp_path / "repo"
    real.mkdir()
    monkeypatch.setattr(
        il, "canonicalize_repo",
        lambda root: {"canonical_root": str(real), "durable_checkout": True, "origin_url": None},
    )
    # The inactive entry "aaa" sorts first but must NOT win the canonical row.
    entries = [
        _entry("aaa", str(real), active=False),
        _entry("zzz", str(real), active=True),
    ]
    rows = cd.registered_canonical_from_registry(entries)
    canonical_key = il.make_path_pair(str(real))["path_key"]
    eligible_rows = [r for r in rows if r["canonical_repo_key"] == canonical_key and r["active"]]
    assert len(eligible_rows) == 1
    assert eligible_rows[0]["name"] == "zzz"
    assert eligible_rows[0]["registry_conflict"] is False  # only one ELIGIBLE entry


# ─────────────────────────  reconcile (pure)  ─────────────────────────


def test_reconcile_zero_state_yields_empty_arrays():
    out = cd.reconcile([], [], NOW)
    assert out == {
        "used_unregistered": [],
        "registered_active": [],
        "registered_stale": [],
        "registered_path_missing": [],
        "registered_unresolved": [],
    }


def test_reconcile_performs_no_filesystem_io(monkeypatch):
    # Any os.path / git probe inside reconcile is a contract violation.
    def _boom(*_a, **_k):
        raise AssertionError("reconcile must not touch the filesystem")

    monkeypatch.setattr(os.path, "isdir", _boom)
    monkeypatch.setattr(os.path, "exists", _boom)
    registered = [{
        "name": "dontpanic", "active": True, "path_display": "<home>/src/DontPanic",
        "canonical_repo_key": "k1", "path_exists": True, "canonicalization_status": cd.CANON_OK,
        "registry_path_key": "r1", "registry_conflict": False, "conflicting_registry_names": [],
    }]
    observed = [{
        "canonical_repo_key": "k1", "path_display": "<home>/src/DontPanic",
        "durable_checkout": True, "observed_count": 5, "last_seen": "2026-06-19T00:00:00Z",
    }]
    out = cd.reconcile(registered, observed, NOW)
    assert len(out["registered_active"]) == 1


def test_reconcile_used_unregistered_basic():
    observed = [{
        "canonical_repo_key": "kdp", "path_display": "<home>/src/DontPanic",
        "durable_checkout": True, "observed_count": 5, "last_seen": "2026-06-19T00:00:00Z",
    }]
    out = cd.reconcile([], observed, NOW)
    assert len(out["used_unregistered"]) == 1
    row = out["used_unregistered"][0]
    assert row["canonical_repo_key"] == "kdp"
    assert row["suggested_name"] == "dontpanic"
    assert row["observed_count"] == 5


@pytest.mark.parametrize(
    "observed_count,last_seen,expected",
    [
        (5, "2026-06-19T00:00:00Z", "active"),       # passes both thresholds
        (2, "2026-06-06T00:00:00Z", "active"),       # inclusive boundaries (min=2, 14d)
        (1, "2026-06-19T00:00:00Z", "stale"),        # low count
        (5, "2026-06-05T00:00:00Z", "stale"),        # too old (15 days)
        (5, "not-a-ts", "stale"),                    # invalid timestamp
        (5, None, "stale"),                          # missing timestamp
    ],
)
def test_reconcile_registered_truth_table(observed_count, last_seen, expected):
    registered = [{
        "name": "dontpanic", "active": True, "path_display": "<home>/src/DontPanic",
        "canonical_repo_key": "k1", "path_exists": True, "canonicalization_status": cd.CANON_OK,
        "registry_path_key": "r1", "registry_conflict": False, "conflicting_registry_names": [],
    }]
    observed = [{
        "canonical_repo_key": "k1", "path_display": "<home>/src/DontPanic",
        "durable_checkout": True, "observed_count": observed_count, "last_seen": last_seen,
    }]
    out = cd.reconcile(registered, observed, NOW)
    if expected == "active":
        assert len(out["registered_active"]) == 1 and not out["registered_stale"]
    else:
        assert len(out["registered_stale"]) == 1 and not out["registered_active"]


def test_reconcile_registered_no_observed_row_emits_zero_and_null():
    registered = [{
        "name": "dontpanic", "active": True, "path_display": "<home>/src/DontPanic",
        "canonical_repo_key": "k1", "path_exists": True, "canonicalization_status": cd.CANON_OK,
        "registry_path_key": "r1", "registry_conflict": False, "conflicting_registry_names": [],
    }]
    out = cd.reconcile(registered, [], NOW)
    assert len(out["registered_stale"]) == 1
    row = out["registered_stale"][0]
    assert row["observed_count"] == 0
    assert row["last_seen"] is None


def test_reconcile_inactive_entry_yields_no_active_or_stale_row():
    registered = [{
        "name": "old", "active": False, "path_display": "<home>/src/Old",
        "canonical_repo_key": "k1", "path_exists": True, "canonicalization_status": cd.CANON_OK,
        "registry_path_key": "r1", "registry_conflict": False, "conflicting_registry_names": [],
    }]
    observed = [{
        "canonical_repo_key": "k1", "path_display": "<home>/src/Old",
        "durable_checkout": True, "observed_count": 9, "last_seen": "2026-06-19T00:00:00Z",
    }]
    out = cd.reconcile(registered, observed, NOW)
    assert out["registered_active"] == []
    assert out["registered_stale"] == []
    # An inactive-but-registered repo is NOT recommended as used_unregistered either.
    assert out["used_unregistered"] == []


def test_reconcile_path_missing_and_unresolved_key_shapes():
    registered = [
        {
            "name": "ghost", "active": True, "path_display": "<home>/gone",
            "canonical_repo_key": None, "path_exists": False,
            "canonicalization_status": cd.CANON_MISSING, "registry_path_key": "rm1",
            "registry_conflict": False, "conflicting_registry_names": [],
        },
        {
            "name": "weird", "active": True, "path_display": "<home>/weird",
            "canonical_repo_key": None, "path_exists": True,
            "canonicalization_status": cd.CANON_UNRESOLVED, "registry_path_key": "ru1",
            "registry_conflict": False, "conflicting_registry_names": [],
        },
    ]
    out = cd.reconcile(registered, [], NOW)
    pm = out["registered_path_missing"][0]
    assert pm["canonical_repo_key"] is None
    assert pm["registry_name"] == "ghost"
    assert pm["registry_path_key"] == "rm1"
    assert pm["canonicalization_status"] == cd.CANON_MISSING
    assert "observed_count" not in pm and "last_seen" not in pm
    ur = out["registered_unresolved"][0]
    assert ur["canonical_repo_key"] is None
    assert ur["registry_name"] == "weird"
    assert ur["canonicalization_status"] == cd.CANON_UNRESOLVED


def test_reconcile_registered_conflict_surfaced_on_active_row():
    registered = [{
        "name": "alpha", "active": True, "path_display": "<home>/src/DontPanic",
        "canonical_repo_key": "k1", "path_exists": True, "canonicalization_status": cd.CANON_OK,
        "registry_path_key": "r1", "registry_conflict": True,
        "conflicting_registry_names": ["alpha", "zebra"],
    }]
    observed = [{
        "canonical_repo_key": "k1", "path_display": "<home>/src/DontPanic",
        "durable_checkout": True, "observed_count": 5, "last_seen": "2026-06-19T00:00:00Z",
    }]
    out = cd.reconcile(registered, observed, NOW)
    row = out["registered_active"][0]
    assert row["registry_conflict"] is True
    assert row["conflicting_registry_names"] == ["alpha", "zebra"]


# ─────────────────────────  durability gating (C3)  ─────────────────────────


def test_reconcile_non_durable_observed_never_recommended():
    observed = [{
        "canonical_repo_key": "ktmp", "path_display": "<home>/src/DontPanic",
        "durable_checkout": False, "observed_count": 50, "last_seen": "2026-06-19T00:00:00Z",
    }]
    out = cd.reconcile([], observed, NOW)
    assert out["used_unregistered"] == []


# ─────────────────────────  suggested_name (C5)  ─────────────────────────


def test_suggested_name_slugifies_basename():
    assert cd.derive_suggested_name("<home>/src/DontPanic", "abcdef1234567890", set()) == "dontpanic"


def test_suggested_name_defaults_to_project_for_empty():
    assert cd.derive_suggested_name("<home>/___", "abcdef1234567890", set()) == "project"


def test_suggested_name_collision_appends_hash_suffix():
    name = cd.derive_suggested_name("<home>/src/DontPanic", "abcdef1234567890", {"dontpanic"})
    assert name == "dontpanic-abcdef12"
    assert PROJECT_NAME_PATTERN.fullmatch(name)


def test_suggested_name_collision_when_hash_suffix_also_taken():
    # Both the base and the canonical-key hash-suffixed fallback are already taken;
    # the result must still be unique (deterministically widened/disambiguated).
    taken = {"dontpanic", "dontpanic-abcdef12"}
    name = cd.derive_suggested_name("<home>/src/DontPanic", "abcdef1234567890", taken)
    assert name not in taken
    assert PROJECT_NAME_PATTERN.fullmatch(name)


def test_suggested_name_unique_against_dense_collision_set():
    # Exhaust the base + all hash widths so the numeric disambiguator is exercised.
    key = "abcdef1234567890"
    taken = {"dontpanic", f"dontpanic-{key[:8]}", f"dontpanic-{key[:12]}", f"dontpanic-{key[:16]}"}
    taken |= {f"dontpanic-{key[:8]}-{n}" for n in range(1, 3)}
    name = cd.derive_suggested_name("<home>/src/DontPanic", key, taken)
    assert name not in taken
    assert PROJECT_NAME_PATTERN.fullmatch(name)


def test_suggested_name_stays_within_64_chars_on_collision():
    long_base = "a" * 80
    name = cd.derive_suggested_name(f"<home>/{long_base}", "abcdef1234567890", {long_base[:64]})
    assert len(name) <= 64
    assert PROJECT_NAME_PATTERN.fullmatch(name)


def test_suggested_name_always_regex_safe():
    name = cd.derive_suggested_name("<home>/My Repo!!!", "DEADBEEFcafe0000", set())
    assert PROJECT_NAME_PATTERN.fullmatch(name)


# ─────────────────────────  end-to-end fixtures (C3/C5)  ─────────────────────────


def test_isolated_registry_yields_used_unregistered(monkeypatch, tmp_path):
    # The DontPanic repo is NOT registered -> its observed usage is a candidate.
    real = tmp_path / "DontPanic"
    real.mkdir()
    monkeypatch.setattr(
        il, "canonicalize_repo",
        lambda root: {"canonical_root": str(real), "durable_checkout": True, "origin_url": None},
    )
    registered = cd.registered_canonical_from_registry([_entry("some-other", str(tmp_path / "other"))])
    canonical_key = il.make_path_pair(str(real))["path_key"]
    observed = [{
        "canonical_repo_key": canonical_key, "path_display": "<home>/src/DontPanic",
        "durable_checkout": True, "observed_count": 24, "last_seen": "2026-06-19T00:00:00Z",
    }]
    out = cd.reconcile(registered, observed, NOW)
    assert len(out["used_unregistered"]) == 1
    assert out["used_unregistered"][0]["canonical_repo_key"] == canonical_key


def test_registered_registry_yields_registered_active(monkeypatch, tmp_path):
    # D010-like: the DontPanic repo IS registered -> registered_active, not unregistered.
    real = tmp_path / "DontPanic"
    real.mkdir()
    monkeypatch.setattr(
        il, "canonicalize_repo",
        lambda root: {"canonical_root": str(real), "durable_checkout": True, "origin_url": None},
    )
    registered = cd.registered_canonical_from_registry([_entry("dontpanic", str(real))])
    canonical_key = il.make_path_pair(str(real))["path_key"]
    observed = [{
        "canonical_repo_key": canonical_key, "path_display": "<home>/src/DontPanic",
        "durable_checkout": True, "observed_count": 24, "last_seen": "2026-06-19T00:00:00Z",
    }]
    out = cd.reconcile(registered, observed, NOW)
    assert out["used_unregistered"] == []
    assert len(out["registered_active"]) == 1
    assert out["registered_active"][0]["registry_name"] == "dontpanic"


def test_p2a_p2lock_main_collapses_to_single_candidate():
    # Three observed paths (p2a, p2-lock, main) all stamped with ONE canonical key.
    canon = _canon("kdontpanic", display="<home>/src/DontPanic")
    records = [
        _record(canonical=canon, repo_key="p2a", last_seen="2026-06-17T00:00:00Z", observed_count=24),
        _record(canonical=canon, repo_key="p2lock", last_seen="2026-06-18T00:00:00Z", observed_count=17),
        _record(canonical=canon, repo_key="main", last_seen="2026-06-19T00:00:00Z", observed_count=10),
    ]
    observed = cd.observed_canonical_from_ledger(records)
    assert len(observed) == 1
    assert observed[0]["observed_count"] == 51
    out = cd.reconcile([], observed, NOW)
    assert len(out["used_unregistered"]) == 1
    assert out["used_unregistered"][0]["suggested_name"] == "dontpanic"


def test_inclusive_boundary_stable_after_compacted_observed_count():
    # A single compacted row carrying observed_count exactly at min_count passes.
    records = [_record(canonical=_canon("k1"), observed_count=2, last_seen="2026-06-19T00:00:00Z")]
    observed = cd.observed_canonical_from_ledger(records)
    out = cd.reconcile([], observed, NOW)
    assert len(out["used_unregistered"]) == 1
