"""F023 EC13 — active-supervisor registry + jarvis ps CLI.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_ec13_active_supervisors.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import active_supervisors as aS  # noqa: E402
from jarvis_orchestrate import cli  # noqa: E402


def _redirect_registry(td: Path) -> Path:
    """Point the active-supervisors registry at a tmp file for hermetic tests.

    The conftest autouse fixture already sets JARVIS_ACTIVE_SUPERVISORS_PATH to
    a per-test tmp_path; some EC13 tests still want their OWN tmp file (so
    assertions on aS.REGISTRY_PATH.read_text() match what the test wrote).
    Set both: env var (which _effective_registry_path() consults first) AND
    the module attribute (so test code can read aS.REGISTRY_PATH directly).
    """
    tmp_file = td / "active.jsonl"
    os.environ["JARVIS_ACTIVE_SUPERVISORS_PATH"] = str(tmp_file)
    aS.REGISTRY_PATH = tmp_file
    return tmp_file


# ──────────────────────────────  register / unregister roundtrip  ──────────────────────────────


def test_register_unregister_roundtrip() -> None:
    print("\n[test] register_unregister_roundtrip ...")
    with tempfile.TemporaryDirectory() as td:
        _redirect_registry(Path(td))
        e = aS.register("2026-04-26-400-infra-rt", "dev", "jarvis-a6ee1", "/tmp/cfg")
        assert e.pid == os.getpid() and e.target_env == "dev"
        active = aS.list_active()
        assert len(active) == 1 and active[0].plan_id == e.plan_id
        removed = aS.unregister(e.plan_id)
        assert removed == 1
        assert aS.list_active() == []
    print("  ✓ register adds entry; unregister removes it")


def test_unregister_filters_by_pid() -> None:
    print("\n[test] unregister_filters_by_pid ...")
    with tempfile.TemporaryDirectory() as td:
        _redirect_registry(Path(td))
        aS.register("2026-04-26-401-infra-pid-x", "dev", "p1", "/tmp/a", pid=os.getpid())
        # Manually inject a different-pid entry for the same plan_id
        with aS.REGISTRY_PATH.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "pid": os.getpid() + 1,
                        "plan_id": "2026-04-26-401-infra-pid-x",
                        "target_env": "dev",
                        "target_project": "p2",
                        "started_at": "2020-01-01T00:00:00Z",
                        "supervisor_config_dir": None,
                    }
                )
                + "\n"
            )
        # Unregister should remove only the matching PID
        removed = aS.unregister("2026-04-26-401-infra-pid-x", pid=os.getpid())
        assert removed == 1
    print("  ✓ unregister scoped by (plan_id, pid) — leaves other pids untouched")


# ──────────────────────────────  list_active filters dead PIDs  ──────────────────────────────


def test_list_active_filters_dead_pid() -> None:
    print("\n[test] list_active_filters_dead_pid ...")
    with tempfile.TemporaryDirectory() as td:
        _redirect_registry(Path(td))
        # Inject a stale PID entry directly
        with aS.REGISTRY_PATH.open("w") as f:
            f.write(
                json.dumps(
                    {
                        "pid": 9_999_999,  # almost certainly dead
                        "plan_id": "2026-04-26-402-infra-stale",
                        "target_env": "dev",
                        "target_project": "p",
                        "started_at": "2020-01-01T00:00:00Z",
                        "supervisor_config_dir": None,
                    }
                )
                + "\n"
            )
        alive = aS.list_active()
        assert alive == []
        # Pruning side-effect: file rewritten without dead row
        assert aS.REGISTRY_PATH.read_text() == ""
    print("  ✓ dead PID dropped + registry pruned as side effect")


# ──────────────────────────────  re-entrancy detection  ──────────────────────────────


def test_check_reentrancy_detects_running_plan() -> None:
    print("\n[test] check_reentrancy_detects_running_plan ...")
    with tempfile.TemporaryDirectory() as td:
        _redirect_registry(Path(td))
        aS.register("2026-04-26-403-infra-reentry", "dev", "x", "/tmp/c1")
        hit = aS.check_reentrancy("2026-04-26-403-infra-reentry")
        assert hit is not None and hit.target_project == "x"
        miss = aS.check_reentrancy("some-other-plan-id")
        assert miss is None
    print("  ✓ check_reentrancy returns live entry for matching plan_id, None otherwise")


# ──────────────────────────────  jarvis ps CLI subcommand  ──────────────────────────────


def test_ps_cli_empty_registry_message() -> None:
    print("\n[test] ps_cli_empty_registry_message ...")
    with tempfile.TemporaryDirectory() as td:
        _redirect_registry(Path(td))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["ps"])
        assert rc == 0
        assert "No active supervisors." in buf.getvalue()
    print("  ✓ `jarvis ps` on empty registry prints empty message")


def test_ps_cli_renders_table() -> None:
    print("\n[test] ps_cli_renders_table ...")
    with tempfile.TemporaryDirectory() as td:
        _redirect_registry(Path(td))
        aS.register("2026-04-26-404-infra-ps-table", "dev", "jarvis-a6ee1", "/tmp/cfg-x")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["ps"])
        assert rc == 0
        out = buf.getvalue()
        for col in ("PID", "PLAN_ID", "ENV", "PROJECT", "STARTED", "CONFIG_DIR"):
            assert col in out, out
        assert "2026-04-26-404-infra-ps-table" in out
        assert "jarvis-a6ee1" in out
    print("  ✓ `jarvis ps` table contains headers + registered entry")


# ──────────────────────────────  format_entries  ──────────────────────────────


def test_format_entries_pretty_print() -> None:
    print("\n[test] format_entries_pretty_print ...")
    with tempfile.TemporaryDirectory() as td:
        _redirect_registry(Path(td))
        aS.register("2026-04-26-405-infra-fmt", "prod", None, None)  # host-local
        text = aS.format_entries(aS.list_active())
        assert "(none)" in text and "(inherit)" in text
    print("  ✓ format_entries handles host-local sentinels gracefully")
