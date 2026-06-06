"""Plan 2026-05-30-001 F010 — dashboard serve singleton guard, status helper,
and deduped response-level hint.

Covers acceptance (1)-(7): a second serve in the same DontPanic home refuses with
an actionable message (1); stale records prune (2); ``--replace`` supersedes a
live singleton (3); the status helper returns the active URL when running and the
serve command when not (4); the shared render helper emits the dashboard hint
once per response even with many human-required items (5); ordinary port-bind
OSError handling still works (6). All tests run without opening a browser (7).

The serve-singleton is keyed by the canonical DontPanic HOME (codex F010 i0
high finding), NOT the served dashboard dir / cwd — so serving the same home
from a different ``--dashboard-dir`` is still refused. The autouse conftest
fixture redirects ``DONTPANIC_HOME`` to a per-test tmp dir, so a no-argument
``detect_active_url()`` / ``dashboard_status()`` reads the hermetic per-test
home and serve_start records there.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys

import pytest

from dontpanic_orchestrate import config_inventory as ci
from dontpanic_orchestrate import dashboard, global_config
from dontpanic_orchestrate import operations_guidance as og

# ───────────────────────────── helpers ──────────────────────────────────


def _serve(tmp_path, *, dash_dir=None, replace=False, port=0):
    """serve_start against hermetic tmp dirs (no real repo, no watcher).

    The singleton lands under the conftest-isolated DontPanic home, independent
    of ``dash_dir`` — that home-keying is exactly what F010 AC1 requires.
    """
    dash_dir = dash_dir if dash_dir is not None else (tmp_path / "dashboard")
    plans_root = tmp_path / "plans"
    plans_root.mkdir(exist_ok=True)
    return dashboard.serve_start(
        host="127.0.0.1",
        port=port,
        dashboard_dir=dash_dir,
        plans_root=plans_root,
        state_out_dir=dash_dir / "state",
        repo_root=tmp_path,
        watch=False,
        replace=replace,
    )


# ─────────────────── AC4: dashboard status helper ────────────────────────


def test_dashboard_status_running_returns_url_project_scope(tmp_path):
    # The status helper accepts an explicit home dir; here we drive the primitive
    # against a hermetic dir to assert the running shape end to end.
    home = tmp_path / "home"
    home.mkdir()
    # _write_singleton_record stamps the live (current) pid, so detection treats
    # it as running.
    dashboard._write_singleton_record(
        home=home,
        host="127.0.0.1",
        port=8123,
        url="http://127.0.0.1:8123/",
        project="alpha",
    )
    status = dashboard.dashboard_status(home)
    assert status.is_running is True
    assert status.url == "http://127.0.0.1:8123/"
    assert status.project == "alpha"
    assert status.scope == str(home)
    # The running form points at the URL, not the start command.
    assert "open http://127.0.0.1:8123/" in status.hint_text()
    d = status.to_dict()
    assert d["url"] == "http://127.0.0.1:8123/"
    assert d["start_command"] is None


def test_dashboard_status_not_running_returns_start_command(tmp_path):
    status = dashboard.dashboard_status(tmp_path / "nope")
    assert status.is_running is False
    assert status.url is None
    assert status.start_command == "dontpanic dashboard serve"
    assert "not running" in status.hint_text()
    assert "dontpanic dashboard serve" in status.hint_text()
    d = status.to_dict()
    assert d["start_command"] == "dontpanic dashboard serve"
    assert d["url"] is None


def test_dashboard_status_defaults_to_canonical_home(tmp_path):
    # No-argument dashboard_status must key off the canonical DontPanic home
    # (conftest-isolated), so config inventory / operations guidance discover a
    # live serve regardless of cwd.
    home = global_config.dontpanic_home()
    dashboard._write_singleton_record(
        home=home,
        host="127.0.0.1",
        port=9090,
        url="http://127.0.0.1:9090/",
        project=None,
    )
    status = dashboard.dashboard_status()
    assert status.is_running is True
    assert status.url == "http://127.0.0.1:9090/"
    assert status.scope == str(home)


def test_dashboard_status_prunes_stale_record(tmp_path):
    # AC2: a dead-pid record must not advertise a phantom URL and must be pruned.
    home = tmp_path / "home"
    record_path = dashboard._singleton_record_path(home)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps({"pid": 2_000_000_000, "url": "http://127.0.0.1:9/"}) + "\n"
    )
    status = dashboard.dashboard_status(home)
    assert status.is_running is False
    assert not record_path.is_file()


# ─────────────────── AC1/AC3: refuse second serve + replace ───────────────


def test_first_serve_records_then_second_refuses(tmp_path):
    dash_dir = tmp_path / "dashboard"
    handle = _serve(tmp_path, dash_dir=dash_dir)
    try:
        # The live singleton is now recorded under the home; a second serve for
        # the SAME home must refuse rather than accumulate another server.
        with pytest.raises(dashboard.DashboardAlreadyRunningError) as ei:
            _serve(tmp_path, dash_dir=dash_dir)
        assert ei.value.url == handle.url
        assert ei.value.home == global_config.dontpanic_home()
    finally:
        handle.shutdown()
    # After shutdown the singleton clears, so a fresh serve is admitted again.
    handle2 = _serve(tmp_path, dash_dir=dash_dir)
    handle2.shutdown()


def test_second_serve_different_dashboard_dir_same_home_refuses(tmp_path):
    # codex F010 i0 (high): the "one server per DontPanic home" guarantee must not
    # be bypassable by serving the SAME home from a different cwd / --dashboard-dir.
    # The singleton is home-keyed, so a second serve at a DIFFERENT dashboard dir
    # is still refused.
    handle = _serve(tmp_path, dash_dir=tmp_path / "dashA")
    try:
        with pytest.raises(dashboard.DashboardAlreadyRunningError) as ei:
            _serve(tmp_path, dash_dir=tmp_path / "dashB")
        assert ei.value.url == handle.url
    finally:
        handle.shutdown()
    # Once the first server stops, the distinct-dir serve is admitted.
    handle2 = _serve(tmp_path, dash_dir=tmp_path / "dashB")
    handle2.shutdown()


def test_second_serve_with_replace_supersedes_same_process(tmp_path):
    # F010 fix#2: replacing a live singleton owned by THIS process cannot stop the
    # old in-process server (we never SIGTERM ourselves), so silently clearing the
    # record and binding a second server would leave two live servers. The corrected
    # behavior REFUSES the same-process replace with an actionable error, and the
    # original server keeps owning the record.
    dash_dir = tmp_path / "dashboard"
    handle = _serve(tmp_path, dash_dir=dash_dir)
    first_url = handle.url
    try:
        with pytest.raises(dashboard.SameProcessReplaceError) as ei:
            _serve(tmp_path, dash_dir=dash_dir, replace=True)
        assert ei.value.url == first_url
        assert ei.value.home == global_config.dontpanic_home()
        # No second server was bound — the original still owns the live record.
        assert dashboard.detect_active_url() == first_url
    finally:
        handle.shutdown()


def test_replace_sigterms_a_foreign_live_pid(tmp_path, monkeypatch):
    # AC3: when the live singleton belongs to ANOTHER (confirmed-dashboard) process,
    # --replace stops it (SIGTERM) before taking over. Spawn a real sleeping process
    # to own it; since the stand-in isn't a real dashboard command line, we confirm
    # its identity via monkeypatch so the security guard (fix#1) treats it as ours.
    # The record lives under the canonical home (not the dashboard dir).
    home = global_config.dontpanic_home()
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    monkeypatch.setattr(
        dashboard, "_pid_is_dashboard_process", lambda pid: pid == proc.pid
    )
    try:
        record_path = dashboard._singleton_record_path(home)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(
                {"pid": proc.pid, "url": "http://127.0.0.1:9998/", "project": None}
            )
            + "\n"
        )
        handle = dashboard.serve_start(
            dashboard_dir=tmp_path / "dashboard",
            plans_root=plans_root,
            state_out_dir=tmp_path / "dashboard" / "state",
            repo_root=tmp_path,
            watch=False,
            replace=True,
        )
        try:
            # The foreign process was signalled and exits; the new server owns
            # the record.
            assert proc.wait(timeout=10) is not None
            assert dashboard.detect_active_url() == handle.url
        finally:
            handle.shutdown()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_replace_rebinds_same_port_after_foreign_server_releases_it(
    tmp_path, monkeypatch
):
    # codex F010 i1 (high): --replace must not race the old server's port release.
    # Spawn a REAL foreign process that binds and LISTENS on a concrete port (not
    # merely sleeps), record it as the singleton on that port, then --replace the
    # serve on the SAME port. The supersede must wait for the old process to exit
    # (releasing the socket) before binding, so the fresh serve claims the port
    # instead of failing with EADDRINUSE. The stand-in isn't a real dashboard
    # command line, so its identity is confirmed via monkeypatch (fix#1 guard).
    home = global_config.dontpanic_home()
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    # The child binds port 0, prints the chosen port, then holds the listener.
    child_src = (
        "import socket, sys, time\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "s.bind(('127.0.0.1', 0))\n"
        "s.listen(1)\n"
        "print(s.getsockname()[1], flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", child_src], stdout=subprocess.PIPE, text=True
    )
    monkeypatch.setattr(
        dashboard, "_pid_is_dashboard_process", lambda pid: pid == proc.pid
    )
    try:
        assert proc.stdout is not None
        port = int(proc.stdout.readline().strip())
        record_path = dashboard._singleton_record_path(home)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(
                {
                    "pid": proc.pid,
                    "port": port,
                    "url": f"http://127.0.0.1:{port}/",
                    "project": None,
                }
            )
            + "\n"
        )
        handle = dashboard.serve_start(
            host="127.0.0.1",
            port=port,
            dashboard_dir=tmp_path / "dashboard",
            plans_root=plans_root,
            state_out_dir=tmp_path / "dashboard" / "state",
            repo_root=tmp_path,
            watch=False,
            replace=True,
        )
        try:
            # The fresh serve claimed the SAME port the foreign server held, which
            # is only possible because supersede waited for that server to exit.
            assert handle.port == port
            assert proc.poll() is not None
            assert dashboard.detect_active_url() == handle.url
        finally:
            handle.shutdown()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_serve_start_admits_after_stale_prune(tmp_path):
    # AC2: a crashed serve left a dead-pid record; a fresh serve must NOT be
    # refused — the stale record is pruned and the new server binds.
    home = global_config.dontpanic_home()
    record_path = dashboard._singleton_record_path(home)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps({"pid": 2_000_000_000, "url": "http://127.0.0.1:9/"}) + "\n"
    )
    handle = _serve(tmp_path, dash_dir=tmp_path / "dashboard")
    try:
        assert dashboard.detect_active_url() == handle.url
        assert json.loads(record_path.read_text())["pid"] == os.getpid()
    finally:
        handle.shutdown()


# ───────────── fix#1: --replace must not signal an arbitrary/reused PID ────────


def test_replace_does_not_signal_alive_but_foreign_pid(tmp_path, monkeypatch):
    # fix#1 (HIGH security): a recorded pid that is ALIVE but NOT confirmed to be a
    # dontpanic dashboard (PID reuse — the OS reassigned the old dashboard's number
    # to an unrelated process) must NEVER be signalled by --replace. The stale
    # record is cleared and the fresh serve proceeds; os.kill is never called with
    # SIGTERM/SIGKILL for that pid.
    home = global_config.dontpanic_home()
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    foreign_pid = 4_242_424
    # Alive (so we'd reach the signal branch) but NOT our dashboard (foreign).
    # The current process must also read as alive so the freshly-recorded
    # singleton (pid == os.getpid()) is detected as running afterward.
    monkeypatch.setattr(
        dashboard, "_pid_alive", lambda pid: pid in (foreign_pid, os.getpid())
    )
    monkeypatch.setattr(dashboard, "_pid_is_dashboard_process", lambda pid: False)

    killed: list[tuple[int, int]] = []
    real_kill = os.kill

    def spy_kill(pid, sig):
        if pid == foreign_pid and sig in (signal.SIGTERM, signal.SIGKILL):
            killed.append((pid, sig))
            return None
        return real_kill(pid, sig)

    monkeypatch.setattr(os, "kill", spy_kill)

    record_path = dashboard._singleton_record_path(home)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps(
            {"pid": foreign_pid, "url": "http://127.0.0.1:9997/", "project": None}
        )
        + "\n"
    )
    handle = _serve(tmp_path, dash_dir=tmp_path / "dashboard", replace=True)
    try:
        # The foreign pid was never signalled; the new server bound and owns the
        # record (the stale foreign record was cleared, not killed).
        assert killed == []
        assert dashboard.detect_active_url() == handle.url
        assert json.loads(record_path.read_text())["pid"] == os.getpid()
    finally:
        handle.shutdown()


def test_replace_signals_confirmed_dashboard_foreign_pid(tmp_path, monkeypatch):
    # fix#1: the mirror case — an alive foreign pid that IS POSITIVELY confirmed as
    # a dontpanic dashboard process IS superseded (SIGTERM sent) before the fresh
    # serve takes over. No real process is spawned; os.kill and _wait_for_pid_exit
    # are monkeypatched so the supersede path runs without side effects.
    home = global_config.dontpanic_home()
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    foreign_pid = 4_343_434
    monkeypatch.setattr(
        dashboard, "_pid_alive", lambda pid: pid in (foreign_pid, os.getpid())
    )
    monkeypatch.setattr(
        dashboard, "_pid_is_dashboard_process", lambda pid: pid == foreign_pid
    )
    # The foreign "server" exits immediately on SIGTERM (no waiting/escalation).
    monkeypatch.setattr(
        dashboard, "_wait_for_pid_exit", lambda pid, *, timeout: True
    )

    signals: list[tuple[int, int]] = []
    real_kill = os.kill

    def spy_kill(pid, sig):
        if pid == foreign_pid:
            signals.append((pid, sig))
            return None
        return real_kill(pid, sig)

    monkeypatch.setattr(os, "kill", spy_kill)

    record_path = dashboard._singleton_record_path(home)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps(
            {"pid": foreign_pid, "url": "http://127.0.0.1:9996/", "project": None}
        )
        + "\n"
    )
    handle = _serve(tmp_path, dash_dir=tmp_path / "dashboard", replace=True)
    try:
        # The confirmed-dashboard foreign pid received SIGTERM (no SIGKILL needed
        # because _wait_for_pid_exit reported a clean exit).
        assert (foreign_pid, signal.SIGTERM) in signals
        assert (foreign_pid, signal.SIGKILL) not in signals
        assert dashboard.detect_active_url() == handle.url
    finally:
        handle.shutdown()


def test_pid_is_dashboard_process_signature_matching(monkeypatch):
    # The signature rule: a command line counts as "our dashboard" only when it
    # carries BOTH tokens of at least one signature pair (case-insensitive).
    assert dashboard._command_matches_dashboard_signature(
        "/usr/bin/python3 -m dontpanic_orchestrate.dashboard serve --port 0"
    )
    assert dashboard._command_matches_dashboard_signature(
        "dontpanic dashboard SERVE"
    )
    # Only one token of a pair present → not a match.
    assert not dashboard._command_matches_dashboard_signature(
        "python3 -m dontpanic_orchestrate.dashboard build"
    )
    assert not dashboard._command_matches_dashboard_signature("sshd: serve")
    # ps failure / non-zero exit / empty output → cannot confirm → False.
    monkeypatch.setattr(
        dashboard.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("ps")),
    )
    assert dashboard._pid_is_dashboard_process(123456) is False


def test_singleton_record_has_guard_token(tmp_path):
    # fix#1: the written record carries a unique guard_token (dashboard identity).
    home = tmp_path / "home"
    home.mkdir()
    path = dashboard._write_singleton_record(
        home=home,
        host="127.0.0.1",
        port=8124,
        url="http://127.0.0.1:8124/",
        project=None,
    )
    record = json.loads(path.read_text())
    token = record.get("guard_token")
    assert isinstance(token, str) and len(token) == 32  # token_hex(16) → 32 hex chars


# ─────────────────── AC1 via CLI + AC6: OSError bind ──────────────────────


def test_cli_serve_refuses_with_actionable_message(tmp_path, capsys):
    dash_dir = tmp_path / "dashboard"
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    # A live singleton owned by this process (recorded under the home) makes the
    # CLI refuse the serve.
    dashboard._write_singleton_record(
        home=global_config.dontpanic_home(),
        host="127.0.0.1",
        port=8765,
        url="http://127.0.0.1:8765/",
        project=None,
    )
    rc = dashboard.main(
        [
            "serve",
            "--dashboard-dir",
            str(dash_dir),
            "--plans-root",
            str(plans_root),
            "--once",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err
    assert "http://127.0.0.1:8765/" in err
    assert "--replace" in err


def test_cli_serve_once_clears_singleton(tmp_path):
    # --once binds, prints the URL, and immediately shuts down — the singleton
    # must not be left behind for the next serve.
    dash_dir = tmp_path / "dashboard"
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    rc = dashboard.main(
        [
            "serve",
            "--dashboard-dir",
            str(dash_dir),
            "--plans-root",
            str(plans_root),
            "--port",
            "0",  # ephemeral — isolate from whatever holds the stable default port
            "--once",
        ]
    )
    assert rc == 0
    assert dashboard.detect_active_url() is None


def test_port_bind_oserror_still_surfaces(tmp_path):
    # AC6: with no live singleton for this home, an ordinary same-port conflict
    # must still raise OSError (not be masked by the singleton guard).
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 0))
    taken_port = blocker.getsockname()[1]
    blocker.listen(1)
    try:
        with pytest.raises(OSError):
            _serve(tmp_path, dash_dir=tmp_path / "fresh", port=taken_port)
    finally:
        blocker.close()


# ─────────────────── AC5: dedup the dashboard hint ────────────────────────


def test_render_dashboard_hint_once_emits_single_line():
    running = dashboard.DashboardStatus(is_running=True, url="http://127.0.0.1:7/")
    # One item or ninety-nine — the helper returns the SAME single hint string.
    one = dashboard.render_dashboard_hint_once(running, human_required_count=1)
    many = dashboard.render_dashboard_hint_once(running, human_required_count=99)
    assert one == many == running.hint_text()
    assert "open http://127.0.0.1:7/" in one
    # No human-required items → no dashboard pointer at all.
    assert dashboard.render_dashboard_hint_once(running, human_required_count=0) is None
    off = dashboard.DashboardStatus(is_running=False)
    assert "not running" in dashboard.render_dashboard_hint_once(off, human_required_count=3)


def test_guidance_render_text_emits_dashboard_line_once_for_many_items():
    # AC5 at the response level: a blocked unit with several human-required
    # choices renders exactly ONE "Dashboard:" line, not one per choice.
    needs = og.SetupNeeds(
        missing_project=True,
        project_name=None,
        project_path=None,
        split_config_homes=True,
        human_required_config="An open configuration question remains.",
    )
    guidance = og.build_guidance(
        "demo-plan",
        feature_id="F001",
        setup=needs,
        dashboard=og.DashboardAffordance(is_running=False),
    )
    human_choices = [c for c in guidance.choices if c.requires_human]
    assert len(human_choices) >= 2, "test needs multiple human-required choices"
    text = og.render_text(guidance)
    assert text.count("Dashboard:") == 1


# ─────────────────── step 6: guidance routes through status helper ─────────


def test_collect_affordance_autodetects_via_status_helper(monkeypatch):
    # With no url threaded, the affordance must auto-detect a running dashboard
    # through dashboard.dashboard_status rather than defaulting to not-running.
    monkeypatch.setattr(
        dashboard,
        "dashboard_status",
        lambda *a, **k: dashboard.DashboardStatus(
            is_running=True, url="http://127.0.0.1:4321/"
        ),
    )
    aff = og.collect_dashboard_affordance()
    assert aff.is_running is True
    assert aff.url == "http://127.0.0.1:4321/"


def test_config_inventory_hint_routes_through_status_helper(monkeypatch):
    monkeypatch.setattr(
        dashboard,
        "dashboard_status",
        lambda *a, **k: dashboard.DashboardStatus(
            is_running=True, url="http://127.0.0.1:5050/"
        ),
    )
    hint = ci._detect_dashboard_hint()
    assert hint.is_running is True
    assert hint.url == "http://127.0.0.1:5050/"
