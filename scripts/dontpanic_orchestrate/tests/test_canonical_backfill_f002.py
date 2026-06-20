"""Plan 2026-06-17-001 F002 — canonical backfill engine.

Covers:
  * the deterministic C4 evidence matrix in :func:`canonical_backfill.confirm_canonical`
    (confirmed, non-reconstructable token, path-key confirmation failure,
    reconstructed temp canonical even with durable=true, durable=false contradiction
    on a durable canonical, origin_key copied only after hash validation, plus the
    F006-delegated shape skips);
  * idempotent stamping over the ledger (re-run is a no-op), recomputed
    durable_checkout, and <home>-scrubbed display from literal-home evidence (C1);
  * file-fatal vs row-level defect tiers (C4);
  * the C8 held-lock write contract — refuses direct write without a held lock,
    and a concurrent append under the F005-owned lock is serialized, never lost;
  * the 51-record (p2a/p2-lock/main) fixture collapsing to one canonical key with
    order + unrelated fields preserved, and the command field never parsed (C6);
  * the repo-local .gitignore / commit guard for the evidence file (C4).
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

from dontpanic_orchestrate import canonical_backfill as cb  # noqa: E402
from dontpanic_orchestrate import canonical_evidence as ce  # noqa: E402
from dontpanic_orchestrate import invocation_ledger as il  # noqa: E402

_NOW = "2026-06-17T00:00:00Z"


def _rp(p: str | Path) -> str:
    return os.path.realpath(str(p))


# ──────────────────────────────  fixtures + helpers  ──────────────────────────────


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A durable/temp split that does not depend on the real /tmp, plus a fake
    ``$HOME`` so ``<home>`` reconstruction is deterministic. Everything under
    ``ephemeral/`` is temp; everything else under tmp_path is durable."""
    synth_temp = tmp_path / "ephemeral"
    synth_temp.mkdir()
    monkeypatch.setattr(il, "_TEMP_PREFIXES", (_rp(synth_temp),))
    home = tmp_path / "home" / "operator"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    # Pin the scrubber's identity inputs so sanitize_capture is deterministic
    # regardless of the real login name. Without this, a default pytest tmp path
    # like ``/.../pytest-of-<realuser>/...`` embeds the real username, which the
    # scrubber would rewrite mid-path and corrupt round-tripped path keys.
    # "operator" matches the fake $HOME leaf and never appears in temp paths.
    monkeypatch.setenv("LOGNAME", "operator")
    monkeypatch.setenv("USER", "operator")
    return {"tmp": tmp_path, "temp": synth_temp, "home": home}


def _canonical_for(real_path: Path, **overrides) -> dict:
    """Build a shape-valid canonical evidence object whose path_key/path_display
    are exactly what make_path_pair derives for ``real_path`` (so the F002
    path-key confirmation passes unless an override breaks it)."""
    pair = il.make_path_pair(real_path)
    obj = {
        "path_key": pair["path_key"],
        "path_display": pair["path_display"],
        "durable_checkout": True,
    }
    obj.update(overrides)
    return obj


def _evidence(obs_map: dict, canonicals: dict) -> dict:
    return {
        "schema_version": "1.0",
        "canonical_repos": canonicals,
        "observation_path_key_to_canonical": obs_map,
    }


def _contract(obs_map: dict, canonicals: dict) -> ce.EvidenceContract:
    return ce.parse_evidence(_evidence(obs_map, canonicals))


def _write_evidence(path: Path, obs_map: dict, canonicals: dict) -> Path:
    path.write_text(json.dumps(_evidence(obs_map, canonicals)), encoding="utf-8")
    return path


def _record(obs_key: str, **extra) -> dict:
    r = {
        "repo": {"path_key": obs_key, "path_display": "<home>/worktree"},
        "branch": "main",
        "plan": None,
        "locality": "local",
        "last_seen": _NOW,
        "result": "ok",
        "command": "dontpanic agent status",
    }
    r.update(extra)
    return r


def _seed_ledger(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")


def _read_ledger(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ──────────────────────────────  C4 evidence matrix (confirm_canonical)  ──────────────────────────────


def test_confirm_home_token_canonical_is_confirmed(env):
    canon = env["home"] / "code" / "dontpanic"
    pair = il.make_path_pair(canon)
    contract = _contract({"obs": [pair["path_key"]]}, {pair["path_key"]: _canonical_for(canon)})
    result, reason = cb.confirm_canonical("obs", contract)
    assert reason is None
    assert result.path_key == pair["path_key"]
    assert result.path_display == pair["path_display"]
    assert "<home>" in result.path_display
    assert str(env["home"]) not in result.path_display  # never raw home (C1)
    assert result.durable_checkout is True  # recomputed: non-temp


def test_confirm_copies_origin_key_only_after_hash_validation(env):
    canon = env["home"] / "code" / "proj"
    origin = "00112233445566778899aabbccddeeff"  # 32-hex hash shape
    obj = _canonical_for(canon, origin_key=origin)
    contract = _contract({"obs": [obj["path_key"]]}, {obj["path_key"]: obj})
    result, reason = cb.confirm_canonical("obs", contract)
    assert reason is None
    assert result.origin_key == origin


def test_confirm_raw_origin_url_skips_before_copy(env):
    canon = env["home"] / "code" / "proj"
    obj = _canonical_for(canon, origin_key="https://github.com/o/r.git")  # raw URL
    contract = _contract({"obs": [obj["path_key"]]}, {obj["path_key"]: obj})
    result, reason = cb.confirm_canonical("obs", contract)
    assert result is None
    assert reason == ce.SKIP_ORIGIN_NOT_HASH_SHAPED


def test_confirm_non_reconstructable_scrub_token_skips(env):
    # A residual non-<home> scrub token (e.g. <operator>) cannot be re-expanded.
    obj = {"path_key": "K", "path_display": "<operator>/code/proj", "durable_checkout": True}
    contract = _contract({"obs": ["K"]}, {"K": obj})
    result, reason = cb.confirm_canonical("obs", contract)
    assert result is None
    assert reason == cb.SKIP_NON_RECONSTRUCTABLE_SCRUB_TOKEN


def test_confirm_path_key_confirmation_failed_skips(env):
    canon = env["home"] / "code" / "proj"
    # path_display reconstructs fine, but the declared path_key does not match the
    # recomputed make_path_pair key.
    pair = il.make_path_pair(canon)
    obj = {"path_key": "0000000000000000", "path_display": pair["path_display"], "durable_checkout": True}
    contract = _contract({"obs": ["0000000000000000"]}, {"0000000000000000": obj})
    result, reason = cb.confirm_canonical("obs", contract)
    assert result is None
    assert reason == cb.SKIP_PATH_KEY_CONFIRMATION_FAILED


def test_confirm_reconstructed_temp_canonical_skips_even_when_durable_true(env):
    temp_canon = env["temp"] / "tmp-worktree-canon"
    obj = _canonical_for(temp_canon, durable_checkout=True)  # literal temp display
    contract = _contract({"obs": [obj["path_key"]]}, {obj["path_key"]: obj})
    result, reason = cb.confirm_canonical("obs", contract)
    assert result is None
    assert reason == cb.SKIP_RECONSTRUCTED_TEMP_CANONICAL


def test_confirm_durable_false_on_durable_canonical_is_contradiction(env):
    canon = env["home"] / "code" / "proj"
    obj = _canonical_for(canon, durable_checkout=False)  # contradicts recomputed True
    contract = _contract({"obs": [obj["path_key"]]}, {obj["path_key"]: obj})
    result, reason = cb.confirm_canonical("obs", contract)
    assert result is None
    assert reason == cb.SKIP_DURABLE_CONTRADICTION


def test_confirm_absent_observation_key_skips(env):
    canon = env["home"] / "code" / "proj"
    obj = _canonical_for(canon)
    contract = _contract({"present": [obj["path_key"]]}, {obj["path_key"]: obj})
    result, reason = cb.confirm_canonical("missing", contract)
    assert result is None
    assert reason == ce.SKIP_ABSENT_OBSERVATION_KEY


def test_confirm_multiple_mappings_skips(env):
    canon = env["home"] / "code" / "proj"
    obj = _canonical_for(canon)
    contract = _contract({"obs": [obj["path_key"], "other"]}, {obj["path_key"]: obj})
    result, reason = cb.confirm_canonical("obs", contract)
    assert result is None
    assert reason == ce.SKIP_MULTIPLE_MAPPINGS


def test_confirm_missing_required_field_skips(env):
    obj = {"path_key": "K", "path_display": "<home>/x"}  # no durable_checkout
    contract = _contract({"obs": ["K"]}, {"K": obj})
    result, reason = cb.confirm_canonical("obs", contract)
    assert result is None
    assert reason == ce.SKIP_MISSING_REQUIRED_FIELD


def test_confirm_wrong_value_type_skips(env):
    obj = {"path_key": "K", "path_display": "<home>/x", "durable_checkout": "yes"}
    contract = _contract({"obs": ["K"]}, {"K": obj})
    result, reason = cb.confirm_canonical("obs", contract)
    assert result is None
    assert reason == ce.SKIP_WRONG_VALUE_TYPE


def test_confirm_raw_secret_shape_skips_before_copy(env):
    # A real GitHub PAT is exactly ``ghp_`` + 36 chars; the shared secret matrix
    # only fires on that precise shape, so the fixture must use 36 chars.
    secret_display = "ghp_0123456789abcdefghij0123456789abcdef"  # PAT-shaped (36)
    obj = {"path_key": "K", "path_display": secret_display, "durable_checkout": True}
    contract = _contract({"obs": ["K"]}, {"K": obj})
    result, reason = cb.confirm_canonical("obs", contract)
    assert result is None
    assert reason == ce.SKIP_RAW_SECRET_SHAPE


def test_confirm_path_key_mismatch_with_map_key_skips(env):
    canon = env["home"] / "code" / "proj"
    pair = il.make_path_pair(canon)
    obj = {"path_key": "different", "path_display": pair["path_display"], "durable_checkout": True}
    contract = _contract({"obs": [pair["path_key"]]}, {pair["path_key"]: obj})
    result, reason = cb.confirm_canonical("obs", contract)
    assert result is None
    assert reason == ce.SKIP_PATH_KEY_MISMATCH


# ──────────────────────────────  run_backfill: stamping + idempotence (C1)  ──────────────────────────────


def test_dry_run_reports_would_stamp_without_writing(env):
    # Place the ledger UNDER the operator home so the report path has a <home>
    # token to scrub — proving run_backfill routes the report path through the
    # shared scrubber (raw home is never surfaced).
    ledger = env["home"] / "ledger" / "invocations.jsonl"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    ev = _write_evidence(env["tmp"] / "evidence.json", {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA"), _record("obsA")])
    before = ledger.read_bytes()

    report = cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=True)
    assert report["would_stamp"] == 2
    assert report["stamped"] == 0
    assert report["already_stamped"] == 0
    assert report["would_skip"] == 0
    assert report["dry_run"] is True
    # report path is the shared-scrubber display, never the raw home path
    assert report["ledger_path"] == cb._scrub_path(str(ledger))
    assert "<home>" in report["ledger_path"]
    assert str(env["home"]) not in report["ledger_path"]
    assert ledger.read_bytes() == before  # no write


def test_write_mode_stamps_recomputed_durable_and_scrubbed_display(env):
    ledger = env["tmp"] / "invocations.jsonl"
    # Literal raw-home evidence display (no <home> token) must be normalized to a
    # <home>-scrubbed display on write, never copied through raw (C1).
    canon = env["home"] / "code" / "dontpanic"
    pair = il.make_path_pair(canon)
    raw_home_display = str(canon)  # literal absolute path under $HOME
    obj = {"path_key": pair["path_key"], "path_display": raw_home_display, "durable_checkout": True}
    ev = _write_evidence(env["tmp"] / "evidence.json", {"obsA": [pair["path_key"]]}, {pair["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])

    with il.hold_ledger_lock(ledger) as lock:
        report = cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=lock)

    assert report["stamped"] == 1
    row = _read_ledger(ledger)[0]
    cr = row["canonical_repo"]
    assert cr["path_key"] == pair["path_key"]
    assert cr["durable_checkout"] is True  # recomputed from reconstructed path
    assert cr["path_display"] == pair["path_display"]
    assert "<home>" in cr["path_display"]
    assert str(env["home"]) not in json.dumps(row)  # no raw home anywhere


def test_idempotent_rerun_is_a_no_op(env):
    ledger = env["tmp"] / "invocations.jsonl"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    ev = _write_evidence(env["tmp"] / "evidence.json", {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA"), _record("obsA")])

    with il.hold_ledger_lock(ledger) as lock:
        first = cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=lock)
    after_first = ledger.read_bytes()
    assert first["stamped"] == 2

    with il.hold_ledger_lock(ledger) as lock:
        second = cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=lock)
    assert second["stamped"] == 0
    assert second["already_stamped"] == 2
    assert ledger.read_bytes() == after_first  # byte-identical: re-run is a no-op


def test_ambiguous_and_absent_keys_are_skipped_and_reported(env):
    ledger = env["tmp"] / "invocations.jsonl"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    # obsA confirms; obsB maps to two canonicals (ambiguous); obsZ is absent.
    ev = _write_evidence(
        env["tmp"] / "evidence.json",
        {"obsA": [obj["path_key"]], "obsB": [obj["path_key"], "other"]},
        {obj["path_key"]: obj},
    )
    _seed_ledger(ledger, [_record("obsA"), _record("obsB"), _record("obsZ")])

    report = cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=True)
    assert report["would_stamp"] == 1
    assert report["would_skip"] == 2
    reasons = {row["path_key"]: row["reason"] for row in report["skipped"]}
    assert reasons["obsB"] == ce.SKIP_MULTIPLE_MAPPINGS
    assert reasons["obsZ"] == ce.SKIP_ABSENT_OBSERVATION_KEY


# ──────────────────────────────  defect tiers (C4)  ──────────────────────────────


def test_malformed_evidence_is_file_fatal_stamps_nothing(env):
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    ev.write_text("{ not valid json", encoding="utf-8")
    _seed_ledger(ledger, [_record("obsA")])
    before = ledger.read_bytes()

    with pytest.raises(ce.EvidenceFatalError) as exc:
        cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=True)
    assert exc.value.reason == ce.FATAL_INVALID_JSON
    assert ledger.read_bytes() == before  # nothing stamped


def test_missing_evidence_file_is_file_fatal(env):
    ledger = env["tmp"] / "invocations.jsonl"
    _seed_ledger(ledger, [_record("obsA")])
    with pytest.raises(ce.EvidenceFatalError) as exc:
        cb.run_backfill(ledger_path=ledger, evidence_path=env["tmp"] / "nope.json", dry_run=True)
    assert exc.value.reason == ce.FATAL_MISSING_FILE


def test_wrong_schema_version_is_file_fatal(env):
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    ev.write_text(json.dumps({"schema_version": "9.9", "canonical_repos": {},
                              "observation_path_key_to_canonical": {}}), encoding="utf-8")
    _seed_ledger(ledger, [_record("obsA")])
    with pytest.raises(ce.EvidenceFatalError) as exc:
        cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=True)
    assert exc.value.reason == ce.FATAL_WRONG_SCHEMA_VERSION


# ──────────────────────────────  C8 held-lock write contract  ──────────────────────────────


def test_held_lock_proof_is_unforgeable(env):
    # A direct construction (the forgery the auditor demonstrated) must raise, and
    # must NOT yield a token that authorizes a write.
    ledger = env["tmp"] / "invocations.jsonl"
    with pytest.raises(RuntimeError):
        il.HeldLedgerLock(target=ledger, active=True)

    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    ev = _write_evidence(env["tmp"] / "evidence.json", {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])
    before = ledger.read_bytes()

    # Forging via an arbitrary guard object is rejected at construction.
    with pytest.raises(RuntimeError):
        il.HeldLedgerLock(target=ledger, active=True, _guard=object())
    assert ledger.read_bytes() == before


def test_forged_token_with_real_guard_does_not_authorize(env):
    # The auditor's exact forgery: the _LOCK_GUARD sentinel is process-readable, so
    # construction with il._LOCK_GUARD SUCCEEDS — but authorization is bound to the
    # token's OWN live hold_ledger_lock() acquisition (its registered lease), not to
    # "any holder of the sidecar lock". A forged token carries no registered lease,
    # so it must NOT authorize and run_backfill must refuse, leaving the ledger
    # untouched.
    ledger = env["tmp"] / "invocations.jsonl"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    ev = _write_evidence(env["tmp"] / "evidence.json", {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])
    before = ledger.read_bytes()

    forged = il.HeldLedgerLock(target=ledger, active=True, _guard=il._LOCK_GUARD)
    assert forged.authorizes(ledger) is False  # no lease, no live acquisition

    with pytest.raises(cb.BackfillWriteError):
        cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=forged)
    assert ledger.read_bytes() == before  # nothing stamped


def test_forged_token_stays_unauthorized_while_unrelated_lock_is_held(env):
    # REGRESSION (auditor i2 high finding): previously a forged token rode on ANY
    # holder's sidecar lock, so opening an unrelated hold_ledger_lock() context made
    # the forgery authorize. Now authorization is bound to the token's own
    # acquisition: a forged token (no registered lease) must remain unauthorized even
    # while a genuine, unrelated lock context concurrently holds the same sidecar
    # lock — and only the token minted by that genuine context authorizes.
    ledger = env["tmp"] / "invocations.jsonl"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    ev = _write_evidence(env["tmp"] / "evidence.json", {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])
    before = ledger.read_bytes()

    forged = il.HeldLedgerLock(target=ledger, active=True, _guard=il._LOCK_GUARD)
    with il.hold_ledger_lock(ledger) as genuine:
        # The genuine token authorizes; the forged one does NOT, even though the
        # sidecar lock IS held right now (by the genuine context).
        assert genuine.authorizes(ledger) is True
        assert forged.authorizes(ledger) is False
        # And the forged token cannot smuggle a write in under the genuine lock.
        with pytest.raises(cb.BackfillWriteError):
            cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=forged)
    assert ledger.read_bytes() == before

    # Once the genuine context exits, even its own (now-released) token is dead.
    assert genuine.authorizes(ledger) is False


def test_genuine_lock_token_is_minted_only_by_holder(env):
    # The positive control: the seam still mints a usable token under the lock.
    ledger = env["tmp"] / "invocations.jsonl"
    with il.hold_ledger_lock(ledger) as lock:
        assert isinstance(lock, il.HeldLedgerLock)
        assert lock.authorizes(ledger) is True


def test_write_refuses_without_held_lock_context(env):
    ledger = env["tmp"] / "invocations.jsonl"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    ev = _write_evidence(env["tmp"] / "evidence.json", {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])
    before = ledger.read_bytes()

    with pytest.raises(cb.BackfillWriteError):
        cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=None)
    assert ledger.read_bytes() == before


def test_write_without_lock_refuses_before_loading_evidence(env):
    # The lock gate is checked FIRST: a write call with no held lock must refuse
    # with BackfillWriteError even when the evidence file is missing/malformed,
    # rather than reaching (and failing inside) the evidence loader.
    ledger = env["tmp"] / "invocations.jsonl"
    _seed_ledger(ledger, [_record("obsA")])
    before = ledger.read_bytes()

    # missing evidence file + no lock -> the lock refusal wins, not EvidenceFatalError
    with pytest.raises(cb.BackfillWriteError):
        cb.run_backfill(
            ledger_path=ledger,
            evidence_path=env["tmp"] / "nope.json",
            dry_run=False,
            lock=None,
        )

    # malformed evidence + no lock -> still the lock refusal, before any parse
    bad = env["tmp"] / "evidence.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(cb.BackfillWriteError):
        cb.run_backfill(ledger_path=ledger, evidence_path=bad, dry_run=False, lock=None)
    assert ledger.read_bytes() == before


def test_write_refuses_released_or_foreign_lock(env):
    ledger = env["tmp"] / "invocations.jsonl"
    other = env["tmp"] / "other.jsonl"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    ev = _write_evidence(env["tmp"] / "evidence.json", {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])

    # a token whose lock has already been released cannot authorize a write
    with il.hold_ledger_lock(ledger) as lock:
        pass
    assert lock.active is False
    with pytest.raises(cb.BackfillWriteError):
        cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=lock)

    # a held token for a DIFFERENT ledger cannot authorize this ledger's write
    with il.hold_ledger_lock(other) as foreign:
        with pytest.raises(cb.BackfillWriteError):
            cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=foreign)


def test_concurrent_append_serialized_under_held_lock(env):
    ledger = env["tmp"] / "invocations.jsonl"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    ev = _write_evidence(env["tmp"] / "evidence.json", {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])

    started = threading.Event()

    def _appender() -> None:
        started.set()
        il._atomic_append_line(ledger, json.dumps({"appended": True, "repo": {"path_key": "x"}}))

    t = threading.Thread(target=_appender)
    with il.hold_ledger_lock(ledger) as lock:
        t.start()
        started.wait(2)
        time.sleep(0.25)  # appender now blocked on the sidecar lock
        report = cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=lock)
    t.join(5)
    assert not t.is_alive()

    assert report["stamped"] == 1
    rows = _read_ledger(ledger)
    assert len(rows) == 2  # backfilled row + serialized append, none lost
    assert any(r.get("appended") for r in rows)
    assert any(r.get("canonical_repo") for r in rows)


# ──────────────────────────────  51-record fixture + preservation (C2/C6)  ──────────────────────────────


def test_51_record_fixture_collapses_to_one_canonical_key(env):
    ledger = env["tmp"] / "invocations.jsonl"
    canon = env["home"] / "src" / "DontPanic"
    obj = _canonical_for(canon)
    ckey = obj["path_key"]
    ev = _write_evidence(
        env["tmp"] / "evidence.json",
        {"obs_p2a": [ckey], "obs_p2lock": [ckey], "obs_main": [ckey]},
        {ckey: obj},
    )
    # Mirror the operator's 51 records: 24 p2a + 17 p2-lock + 10 main.
    records: list[dict] = []
    for i in range(24):
        records.append(_record("obs_p2a", branch=f"feat-{i}", extra_field=i))
    for i in range(17):
        records.append(_record("obs_p2lock", branch=f"lock-{i}"))
    for i in range(10):
        records.append(_record("obs_main", branch="main"))
    _seed_ledger(ledger, records)

    with il.hold_ledger_lock(ledger) as lock:
        report = cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=lock)

    assert report["stamped"] == 51
    out = _read_ledger(ledger)
    assert len(out) == 51  # order + count preserved
    keys = {r["canonical_repo"]["path_key"] for r in out}
    assert keys == {ckey}  # three observed paths collapse to one canonical repo
    # unrelated fields preserved + order preserved (first 24 are the p2a rows)
    assert out[0]["extra_field"] == 0
    assert out[0]["branch"] == "feat-0"
    assert out[23]["branch"] == "feat-23"
    assert out[24]["branch"] == "lock-0"


def test_command_field_is_never_parsed_or_altered(env):
    ledger = env["tmp"] / "invocations.jsonl"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    ev = _write_evidence(env["tmp"] / "evidence.json", {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    secret_command = "dontpanic run --token ghp_0123456789abcdefghij0123456789abcd narrative"
    _seed_ledger(ledger, [_record("obsA", command=secret_command)])

    with il.hold_ledger_lock(ledger) as lock:
        report = cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=lock)

    row = _read_ledger(ledger)[0]
    assert row["command"] == secret_command  # preserved byte-for-byte, never parsed
    # the report carries no command content (C6: command is never surfaced)
    assert "ghp_" not in json.dumps(report)
    assert "narrative" not in json.dumps(report)


def test_record_order_and_other_fields_preserved(env):
    ledger = env["tmp"] / "invocations.jsonl"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    ev = _write_evidence(env["tmp"] / "evidence.json", {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    # mix a confirmable row with an unmappable row; order + fields preserved
    rows = [
        _record("obsZ", marker="first", branch="b0"),   # skipped (absent)
        _record("obsA", marker="second", branch="b1"),  # stamped
        _record("obsZ", marker="third", branch="b2"),   # skipped (absent)
    ]
    _seed_ledger(ledger, rows)

    with il.hold_ledger_lock(ledger) as lock:
        cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=lock)

    out = _read_ledger(ledger)
    assert [r["marker"] for r in out] == ["first", "second", "third"]
    assert "canonical_repo" not in out[0]
    assert out[1]["canonical_repo"]["path_key"] == obj["path_key"]
    assert "canonical_repo" not in out[2]
    assert [r["branch"] for r in out] == ["b0", "b1", "b2"]


# ──────────────────────────────  evidence-file ignore / commit guard (C4)  ──────────────────────────────


def test_evidence_file_is_gitignored_and_untracked():
    repo_root = HERE.parents[3]
    rel = ".dontpanic/canonical-backfill-evidence.json"
    ignored = subprocess.run(
        ["git", "check-ignore", rel], cwd=str(repo_root), capture_output=True, text=True
    )
    assert ignored.returncode == 0, "evidence file must be git-ignored (C4)"
    tracked = subprocess.run(
        ["git", "ls-files", rel], cwd=str(repo_root), capture_output=True, text=True
    )
    assert tracked.stdout.strip() == "", "evidence file must never be tracked (C4)"
