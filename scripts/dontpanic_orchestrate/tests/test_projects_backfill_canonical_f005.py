"""Plan 2026-06-17-001 F005 — backfill operator entrypoint.

Covers the C4-pinned ``dontpanic projects backfill-canonical`` surface that wraps
the F002 engine:

  * default ledger/evidence path resolution through the same ``$DONTPANIC_HOME``
    logic the live ledger writer uses, plus explicit ``--ledger`` / ``--evidence``
    overrides;
  * preview (``--dry-run``) makes no write; write mode stamps;
  * the C8 sole-lock-owner contract — F005 acquires the ``<ledger>.lock`` sidecar
    EXACTLY ONCE (no double-acquire of the non-reentrant lock) and passes the held
    lock into F002 (which refuses to write without it and never self-acquires);
  * a concurrent append is serialized, never lost, during a write-mode backfill;
  * the C4 status contract (exit 0 even with skipped rows; exit 2 on usage /
    file-fatal evidence / unreadable ledger / flock-unavailable write failure);
  * the stable report schema with scrubbed ledger/evidence paths (C1/C3);
  * the C7 negative hook guard — the command never installs, modifies, removes,
    chains, reads, or depends on git hooks.
"""

from __future__ import annotations

import inspect
import json
import os
import threading
import time
from pathlib import Path

import pytest

import sys

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import canonical_backfill as cb  # noqa: E402
from dontpanic_orchestrate import canonical_evidence as ce  # noqa: E402
from dontpanic_orchestrate import cli  # noqa: E402
from dontpanic_orchestrate import global_config  # noqa: E402
from dontpanic_orchestrate import invocation_ledger as il  # noqa: E402

_NOW = "2026-06-17T00:00:00Z"


def _rp(p: str | Path) -> str:
    return os.path.realpath(str(p))


# ──────────────────────────────  fixtures + helpers  ──────────────────────────────


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Deterministic durable/temp split + fake $HOME + isolated $DONTPANIC_HOME so
    default-path resolution and ``<home>`` scrubbing are reproducible."""
    synth_temp = tmp_path / "ephemeral"
    synth_temp.mkdir()
    monkeypatch.setattr(il, "_TEMP_PREFIXES", (_rp(synth_temp),))
    home = tmp_path / "home" / "operator"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LOGNAME", "operator")
    monkeypatch.setenv("USER", "operator")
    dphome = tmp_path / "dphome"
    dphome.mkdir()
    monkeypatch.setenv(global_config.DONTPANIC_HOME_ENV, str(dphome))
    return {"tmp": tmp_path, "temp": synth_temp, "home": home, "dphome": dphome}


def _canonical_for(real_path: Path, **overrides) -> dict:
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


def _write_evidence(path: Path, obs_map: dict, canonicals: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_evidence(obs_map, canonicals)), encoding="utf-8")
    return path


def _record(obs_key: str, **extra) -> dict:
    r = {
        "repo": {"path_key": obs_key, "path_display": "<home>/worktree"},
        "branch": "main",
        "last_seen": _NOW,
        "result": "ok",
        "command": "dontpanic agent status",
    }
    r.update(extra)
    return r


def _seed_ledger(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
    )


def _read_ledger(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _run(argv: list[str]) -> int:
    """Invoke the entrypoint via the `projects` dispatcher (proves wiring)."""
    return cli._projects_main(["backfill-canonical", *argv])


# ──────────────────────────────  default path resolution (configured home)  ──────────────────────────────


def test_default_paths_honor_configured_home(env, capsys):
    # Seed the ledger + evidence at the SAME defaults the live ledger writer uses,
    # then run with NO overrides and prove the entrypoint resolved both via
    # $DONTPANIC_HOME (the report echoes the scrubbed default paths).
    ledger = il.ledger_path()
    ev = cb.default_evidence_path()
    assert ledger.parent == env["dphome"]  # sanity: home resolution wired
    assert ev.parent == env["dphome"]

    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])

    rc = _run(["--dry-run", "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ledger_path"] == cb._scrub_path(str(ledger))
    assert report["evidence_path"] == cb._scrub_path(str(ev))
    assert report["would_stamp"] == 1


def test_explicit_overrides_are_used(env, capsys):
    # Put the override files somewhere OTHER than $DONTPANIC_HOME and prove the
    # entrypoint used them, not the defaults.
    ledger = env["tmp"] / "custom" / "invocations.jsonl"
    ev = env["tmp"] / "custom" / "evidence.json"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])
    # The default-home files MUST stay absent so the report can only reflect overrides.
    assert not il.ledger_path().exists()

    rc = _run(["--dry-run", "--json", "--ledger", str(ledger), "--evidence", str(ev)])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ledger_path"] == cb._scrub_path(str(ledger))
    assert report["evidence_path"] == cb._scrub_path(str(ev))
    assert report["would_stamp"] == 1


# ──────────────────────────────  preview vs write  ──────────────────────────────


def test_preview_mode_does_not_write(env, capsys):
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA"), _record("obsA")])
    before = ledger.read_bytes()

    rc = _run(["--dry-run", "--json", "--ledger", str(ledger), "--evidence", str(ev)])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["would_stamp"] == 2
    assert report["stamped"] == 0
    assert report["dry_run"] is True
    assert ledger.read_bytes() == before  # no write in preview


def test_write_mode_stamps(env, capsys):
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])

    rc = _run(["--json", "--ledger", str(ledger), "--evidence", str(ev)])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["stamped"] == 1
    assert report["dry_run"] is False
    row = _read_ledger(ledger)[0]
    assert row["canonical_repo"]["path_key"] == obj["path_key"]
    assert str(env["home"]) not in json.dumps(row)  # no raw home (C1)


# ──────────────────────────────  C8 sole-lock-owner / no double-acquire  ──────────────────────────────


def test_write_acquires_lock_exactly_once_and_f002_never_self_acquires(env, monkeypatch):
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])

    calls: list[Path | None] = []
    real_hold = il.hold_ledger_lock

    def _counting_hold(target=None):
        calls.append(target)
        return real_hold(target)

    # The CLI resolves the module attribute at call time, so patching the module
    # object is sufficient to observe every acquire from BOTH F005 and (would-be)
    # F002 self-acquires.
    monkeypatch.setattr(il, "hold_ledger_lock", _counting_hold)

    rc = _run(["--json", "--ledger", str(ledger), "--evidence", str(ev)])
    assert rc == 0
    # Exactly ONE acquire total — F005 owns it; F002 never re-acquires the
    # non-reentrant lock.
    assert len(calls) == 1
    assert _rp(calls[0]) == _rp(ledger)


def test_f002_refuses_direct_write_without_held_lock(env):
    # The contract F005 relies on: the engine refuses a write with no held lock,
    # leaving the ledger untouched (proves F005 is genuinely the sole owner).
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])
    before = ledger.read_bytes()

    with pytest.raises(cb.BackfillWriteError):
        cb.run_backfill(ledger_path=ledger, evidence_path=ev, dry_run=False, lock=None)
    assert ledger.read_bytes() == before


def test_concurrent_append_is_serialized_not_lost_during_write(env, capsys):
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])

    started = threading.Event()
    release = threading.Event()

    # Patch hold_ledger_lock so the F005 write holds the lock long enough for the
    # appender to provably block on the sidecar before the rename happens.
    real_hold = il.hold_ledger_lock

    import contextlib

    @contextlib.contextmanager
    def _slow_hold(target=None):
        with real_hold(target) as tok:
            started.set()
            release.wait(2)
            yield tok

    monkeypatch_target = il
    orig = monkeypatch_target.hold_ledger_lock
    monkeypatch_target.hold_ledger_lock = _slow_hold
    try:
        def _appender() -> None:
            started.wait(2)
            time.sleep(0.1)  # ensure the appender races AFTER F005 holds the lock
            release.set()
            il._atomic_append_line(
                ledger, json.dumps({"appended": True, "repo": {"path_key": "x"}})
            )

        t = threading.Thread(target=_appender)
        t.start()
        rc = _run(["--json", "--ledger", str(ledger), "--evidence", str(ev)])
        t.join(5)
        assert not t.is_alive()
    finally:
        monkeypatch_target.hold_ledger_lock = orig

    assert rc == 0
    rows = _read_ledger(ledger)
    assert len(rows) == 2  # stamped row + serialized append, none lost
    assert any(r.get("appended") for r in rows)
    assert any(r.get("canonical_repo") for r in rows)


def test_flock_unavailable_fails_closed_exit_2(env, capsys, monkeypatch):
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])
    before = ledger.read_bytes()

    def _no_flock(target=None):
        raise SystemExit(2)

    monkeypatch.setattr(il, "hold_ledger_lock", _no_flock)
    rc = _run(["--json", "--ledger", str(ledger), "--evidence", str(ev)])
    assert rc == 2  # fail closed, never an uncoordinated rename
    assert ledger.read_bytes() == before


# ──────────────────────────────  C4 status contract + report schema  ──────────────────────────────


def test_skipped_rows_still_exit_zero(env, capsys):
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    # obsZ is absent from the evidence -> a row-level SKIP, NOT a fatal error.
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA"), _record("obsZ")])

    rc = _run(["--dry-run", "--json", "--ledger", str(ledger), "--evidence", str(ev)])
    assert rc == 0  # completed run is exit 0 even with skipped rows (C4)
    report = json.loads(capsys.readouterr().out)
    assert report["would_stamp"] == 1
    assert report["would_skip"] == 1
    assert report["skipped"][0]["path_key"] == "obsZ"
    assert report["skipped"][0]["reason"] == ce.SKIP_ABSENT_OBSERVATION_KEY


def test_report_schema_has_stable_keys(env, capsys):
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])

    rc = _run(["--dry-run", "--json", "--ledger", str(ledger), "--evidence", str(ev)])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report) == {
        "would_stamp",
        "stamped",
        "already_stamped",
        "would_skip",
        "skipped",
        "ledger_path",
        "evidence_path",
        "dry_run",
    }
    assert isinstance(report["would_stamp"], int)
    assert isinstance(report["stamped"], int)
    assert isinstance(report["already_stamped"], int)
    assert isinstance(report["would_skip"], int)
    assert isinstance(report["skipped"], list)


def test_file_fatal_evidence_exits_2(env, capsys):
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    ev.write_text("{ not valid json", encoding="utf-8")
    _seed_ledger(ledger, [_record("obsA")])
    before = ledger.read_bytes()

    rc = _run(["--dry-run", "--json", "--ledger", str(ledger), "--evidence", str(ev)])
    assert rc == 2  # file-fatal -> exit 2, stamps nothing
    assert ledger.read_bytes() == before


def test_missing_evidence_file_exits_2(env):
    ledger = env["tmp"] / "invocations.jsonl"
    _seed_ledger(ledger, [_record("obsA")])
    rc = _run(["--dry-run", "--ledger", str(ledger), "--evidence", str(env["tmp"] / "nope.json")])
    assert rc == 2


def test_unreadable_ledger_exits_2(env):
    # Evidence is valid, but the ledger is not valid JSONL -> LedgerReadError -> 2.
    ledger = env["tmp"] / "invocations.jsonl"
    ev = env["tmp"] / "evidence.json"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    ledger.write_text("{ broken jsonl line\n", encoding="utf-8")
    rc = _run(["--dry-run", "--ledger", str(ledger), "--evidence", str(ev)])
    assert rc == 2


def test_usage_error_exits_2(env):
    rc = _run(["--not-a-flag"])
    assert rc == 2


def test_unknown_projects_subcommand_still_refuses(env):
    # Guard the dispatcher wiring did not break the unknown-subcommand path.
    assert cli._projects_main(["totally-unknown"]) == 2


# ──────────────────────────────  C7 negative hook guard  ──────────────────────────────


def test_command_does_not_touch_git_hooks(env, tmp_path, capsys):
    # Run the command inside a real git repo and prove the .git/hooks directory is
    # untouched — the backfill never installs, modifies, removes, chains, or reads
    # a git hook (C7).
    repo = tmp_path / "repo"
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True)
    sentinel = hooks / "pre-commit"
    sentinel.write_text("#!/bin/sh\necho original\n", encoding="utf-8")
    sentinel.chmod(0o755)

    def _snapshot() -> dict[str, str]:
        return {p.name: p.read_text() for p in hooks.iterdir() if p.is_file()}

    before = _snapshot()

    ledger = repo / "invocations.jsonl"
    ev = repo / "evidence.json"
    canon = env["home"] / "code" / "dontpanic"
    obj = _canonical_for(canon)
    _write_evidence(ev, {"obsA": [obj["path_key"]]}, {obj["path_key"]: obj})
    _seed_ledger(ledger, [_record("obsA")])

    # Both preview and write paths.
    assert _run(["--dry-run", "--ledger", str(ledger), "--evidence", str(ev)]) == 0
    assert _run(["--ledger", str(ledger), "--evidence", str(ev)]) == 0

    assert _snapshot() == before  # hooks dir byte-identical
    assert set(hooks.iterdir()) == {sentinel}  # no hook added/removed


def test_entrypoint_source_references_no_hook_machinery():
    # Static guard: the entrypoint must not import or call any git-hook installer
    # (repo_onboarding hook install, subprocess git hook, etc.). The C7 docstring
    # that documents this guarantee is stripped first so it cannot mask a real
    # reference in executable code.
    import ast
    import textwrap

    src = textwrap.dedent(inspect.getsource(cli._projects_backfill_canonical))
    func = ast.parse(src).body[0]
    if ast.get_docstring(func) is not None:
        func.body = func.body[1:]  # drop the docstring Expr node
    executable = "\n".join(ast.unparse(node) for node in func.body)
    lowered = executable.lower()
    assert "hook" not in lowered
    assert "subprocess" not in lowered
    assert "repo_onboarding" not in lowered
