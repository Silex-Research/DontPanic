"""Plan 2026-06-14-001 F003 — sanitized, concurrency-safe invocation presence ledger.

Covers the F003 acceptance: every dontpanic invocation appends EXACTLY ONE
InvocationRecord to ~/.dontpanic/invocations.jsonl carrying the four-axis context
(F001) + repo/worktree/branch/plan + command + timing + result + locality; under
normal exit, argparse failure, early failure, KeyboardInterrupt, and SIGTERM-style
interruption. Paths are stored as a PAIR (home-scrubbed path_display + stable
non-secret path_key, never equal). Command args are redacted. N concurrent appends
yield N intact lines. A documented compaction bounds the ledger while preserving the
fields the channel-view derivation (F009/F010) needs to reproduce buckets.
"""

from __future__ import annotations

import json
import signal
import sys
import threading
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import cli, global_config  # noqa: E402
from dontpanic_orchestrate import invocation_ledger as il  # noqa: E402


def _read_ledger() -> list[dict]:
    p = il.ledger_path()
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


# ──────────────────────────────  path pair (D013)  ──────────────────────────────


def test_make_path_pair_scrubs_display_and_keys_distinctly() -> None:
    real = Path.home() / ".dontpanic" / "worktrees" / "Proj-abc" / "plan-x"
    pair = il.make_path_pair(real)
    assert pair is not None
    # path_display is home-scrubbed: no absolute home path leaks
    assert str(Path.home()) not in pair["path_display"]
    assert "<home>" in pair["path_display"] or "~" in pair["path_display"]
    # path_key is NEVER the scrubbed display string, and is stable across calls
    assert pair["path_key"] != pair["path_display"]
    assert il.make_path_pair(real)["path_key"] == pair["path_key"]
    # different real paths -> different keys
    assert il.make_path_pair(Path.home() / "other")["path_key"] != pair["path_key"]
    assert il.make_path_pair(None) is None


# ──────────────────────────────  redaction  ──────────────────────────────


def test_redact_command_redacts_token_shaped_argument() -> None:
    token = "ghp_0123456789abcdefghij0123456789abcdefij"
    cmd = il.redact_command(["plan", "lock", "--secret", token])
    assert token not in cmd
    assert "[REDACTED]" in cmd
    assert "plan" in cmd and "lock" in cmd  # ordinary args preserved


# ──────────────────────────────  record shape + one-write  ──────────────────────────────

_NOW = "2026-06-14T12:00:00Z"
_LATER = "2026-06-14T12:00:05Z"


def test_recorder_writes_one_well_formed_record() -> None:
    rec = il.start_recording(["agent", "status"], env={"DONTPANIC_AGENT": "claude"}, now=_NOW, install_signal=False)
    rec.finalize(il.RESULT_OK, now=_LATER)
    rows = _read_ledger()
    assert len(rows) == 1
    r = rows[0]
    for key in (
        "operator_surface", "agent_runtime", "role", "execution_locality",
        "repo", "worktree", "branch", "plan", "command",
        "started_at", "finished_at", "last_seen", "result", "locality",
    ):
        assert key in r, f"missing {key}"
    assert r["agent_runtime"] == "claude"
    assert r["result"] == il.RESULT_OK
    assert r["started_at"] == _NOW and r["finished_at"] == _LATER
    assert r["locality"] == r["execution_locality"]


def test_recorder_finalize_is_idempotent() -> None:
    rec = il.start_recording(["ps"], now=_NOW, install_signal=False)
    rec.finalize(il.RESULT_OK, now=_LATER)
    rec.finalize(il.RESULT_ERROR, now=_LATER)  # second call must NOT append
    rows = _read_ledger()
    assert len(rows) == 1
    assert rows[0]["result"] == il.RESULT_OK


@pytest.mark.parametrize("result", [il.RESULT_OK, il.RESULT_ERROR, il.RESULT_INTERRUPTED])
def test_recorder_records_each_result(result: str) -> None:
    rec = il.start_recording(["doctor"], now=_NOW, install_signal=False)
    rec.finalize(result, now=_LATER)
    assert _read_ledger()[0]["result"] == result


# ──────────────────────────────  CLI seam: exactly-one across exit modes  ──────────────────────────────


def test_main_records_exactly_one_for_ordinary_command() -> None:
    rc = cli.main(["agent", "brief"])
    assert rc in (0, None)
    rows = _read_ledger()
    assert len(rows) == 1
    assert "agent" in rows[0]["command"] and "brief" in rows[0]["command"]


def test_main_records_one_on_argparse_failure() -> None:
    with pytest.raises(SystemExit):
        cli.main(["operator-roles", "set"])  # missing required role/value -> argparse exits
    rows = _read_ledger()
    assert len(rows) == 1
    assert rows[0]["result"] == il.RESULT_ERROR


def test_main_records_interrupted_on_keyboardinterrupt(monkeypatch) -> None:
    def _boom(_argv):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_ps_main", _boom)
    with pytest.raises(KeyboardInterrupt):
        cli.main(["ps"])
    rows = _read_ledger()
    assert len(rows) == 1
    assert rows[0]["result"] == il.RESULT_INTERRUPTED


def test_main_records_error_on_unexpected_exception(monkeypatch) -> None:
    def _boom(_argv):
        raise RuntimeError("early import/config failure")

    monkeypatch.setattr(cli, "_ps_main", _boom)
    with pytest.raises(RuntimeError):
        cli.main(["ps"])
    rows = _read_ledger()
    assert len(rows) == 1
    assert rows[0]["result"] == il.RESULT_ERROR


def test_sigterm_handler_records_interrupted_once() -> None:
    rec = il.start_recording(["dispatch-from-plan", "x"], now=_NOW, install_signal=True)
    handler = signal.getsignal(signal.SIGTERM)
    assert callable(handler)
    with pytest.raises(SystemExit):
        handler(signal.SIGTERM, None)  # simulate SIGTERM delivery
    rows = _read_ledger()
    assert len(rows) == 1
    assert rows[0]["result"] == il.RESULT_INTERRUPTED
    # the handler restored the previous SIGTERM disposition
    assert signal.getsignal(signal.SIGTERM) != handler


# ──────────────────────────────  concurrency  ──────────────────────────────


def test_concurrent_appends_yield_intact_lines() -> None:
    path = il.ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 24

    def _worker(i: int) -> None:
        il._atomic_append_line(path, json.dumps({"i": i, "pad": "x" * 200}))

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rows = _read_ledger()
    assert len(rows) == n
    assert {r["i"] for r in rows} == set(range(n))  # every line intact + parseable


# ──────────────────────────────  retention / compaction  ──────────────────────────────


def _seed(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def test_compaction_bounds_ledger_and_preserves_buckets() -> None:
    path = il.ledger_path()
    # 3 distinct buckets, each with several time-ordered duplicate observations
    base = {
        "operator_surface": "terminal", "agent_runtime": "claude", "role": "implementer",
        "execution_locality": "plan_worktree", "locality": "plan_worktree",
        "repo": {"path_display": "<home>/r", "path_key": "k"},
        "worktree": None, "branch": "main", "plan": None,
        "command": "ps", "result": "ok",
    }
    recs = []
    for b in ("alpha", "beta", "gamma"):
        for t in range(4):
            r = dict(base)
            r["plan"] = b
            r["repo"] = {"path_display": "<home>/r", "path_key": f"key-{b}"}
            r["started_at"] = r["finished_at"] = r["last_seen"] = f"2026-06-14T12:0{t}:00Z"
            recs.append(r)
    _seed(path, recs)
    buckets_before = il.derive_buckets(_read_ledger())

    summary = il.compact_ledger(path, max_records=10)
    rows_after = _read_ledger()

    assert summary["records_before"] == 12
    assert len(rows_after) < 12  # bounded: within-bucket duplicates collapsed
    assert len(rows_after) <= 10
    # buckets (and the fields F009/F010 derive them from) are identical post-compaction
    assert il.derive_buckets(rows_after) == buckets_before
    # the preserved record per bucket is the most-recent observation
    for r in rows_after:
        assert r["last_seen"] == "2026-06-14T12:03:00Z"
