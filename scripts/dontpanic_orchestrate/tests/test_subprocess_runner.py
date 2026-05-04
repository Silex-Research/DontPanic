"""Plan 2026-05-04-003 F001 — shared subprocess runner tests."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dontpanic_orchestrate import subprocess_runner as runner


def _fast_timeout_env(monkeypatch: pytest.MonkeyPatch, timeout: int = 1, grace: int = 1) -> dict:
    monkeypatch.setattr(runner, "MIN_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(runner, "MIN_GRACE_SECONDS", 1)
    return {
        runner.TIMEOUT_ENV: str(timeout),
        runner.GRACE_ENV: str(grace),
    }


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_happy_path_captures_exit_and_bytes(tmp_path: Path) -> None:
    result = runner.run_subprocess(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('hello'); sys.stderr.write('warn')",
        ],
        cwd=tmp_path,
    )

    assert result.exit_code == 0
    assert result.stdout == b"hello"
    assert result.stderr == b"warn"
    assert result.timed_out is False
    assert result.captured_stdout_bytes == 5
    assert result.captured_stderr_bytes == 4
    assert result.grace_period_used is False
    assert result.pgid > 0


def test_timeout_sigterm_drains_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _fast_timeout_env(monkeypatch)
    result = runner.run_subprocess(
        [
            sys.executable,
            "-c",
            "import sys,time; sys.stdout.write('partial'); sys.stdout.flush(); time.sleep(20)",
        ],
        cwd=tmp_path,
        env={**os.environ, **env},
    )

    assert result.timed_out is True
    assert result.timeout_seconds == 1
    assert result.grace_period_used is True
    assert result.stdout == b"partial"
    assert result.captured_stdout_bytes == len(b"partial")


def test_timeout_escalates_to_sigkill_when_sigterm_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _fast_timeout_env(monkeypatch)
    result = runner.run_subprocess(
        [
            sys.executable,
            "-c",
            (
                "import signal,sys,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "sys.stdout.write('ignoring'); sys.stdout.flush(); "
                "time.sleep(20)"
            ),
        ],
        cwd=tmp_path,
        env={**os.environ, **env},
    )

    assert result.timed_out is True
    assert result.grace_period_used is True
    assert result.stdout == b"ignoring"
    assert result.exit_code is not None and result.exit_code < 0


def test_timeout_kills_grandchild_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _fast_timeout_env(monkeypatch)
    pidfile = tmp_path / "grandchild.pid"
    script = tmp_path / "spawn_grandchild.py"
    script.write_text(
        """
import os
import sys
import time

pidfile = sys.argv[1]
pid = os.fork()
if pid == 0:
    with open(pidfile, "w") as fh:
        fh.write(str(os.getpid()))
        fh.flush()
    time.sleep(60)
else:
    time.sleep(60)
""".lstrip()
    )

    result = runner.run_subprocess(
        [sys.executable, str(script), str(pidfile)],
        cwd=tmp_path,
        env={**os.environ, **env},
    )

    assert result.timed_out is True
    assert pidfile.is_file()
    grandchild_pid = int(pidfile.read_text())
    deadline = time.time() + 3
    while time.time() < deadline and _is_alive(grandchild_pid):
        time.sleep(0.05)
    assert not _is_alive(grandchild_pid), "grandchild survived process-group kill"


@pytest.mark.parametrize(
    ("raw", "expected", "marker_part"),
    [
        ("900", 900, None),
        ("20", runner.DEFAULT_TIMEOUT_SECONDS, "out of range"),
        ("9000", runner.DEFAULT_TIMEOUT_SECONDS, "out of range"),
        ("foo", runner.DEFAULT_TIMEOUT_SECONDS, "unparseable"),
        (None, runner.DEFAULT_TIMEOUT_SECONDS, None),
    ],
)
def test_parse_timeout_env_matrix(raw: str | None, expected: int, marker_part: str | None) -> None:
    env = {} if raw is None else {runner.TIMEOUT_ENV: raw}
    value, marker = runner._parse_timeout_env(
        runner.TIMEOUT_ENV,
        runner.DEFAULT_TIMEOUT_SECONDS,
        runner.MIN_TIMEOUT_SECONDS,
        runner.MAX_TIMEOUT_SECONDS,
        env=env,
    )

    assert value == expected
    if marker_part is None:
        assert marker is None
    else:
        assert marker is not None and marker_part in marker


def test_worktree_detection_git_repo_no_changes(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    result = runner.run_subprocess([sys.executable, "-c", "print('ok')"], cwd=tmp_path)

    assert result.exit_code == 0
    assert result.worktree_changed is False


def test_worktree_detection_git_repo_changes(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    result = runner.run_subprocess(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; Path('landed.txt').write_text('work')",
        ],
        cwd=tmp_path,
    )

    assert result.exit_code == 0
    assert result.worktree_changed is True


def test_worktree_detection_non_git_is_unknown(tmp_path: Path) -> None:
    result = runner.run_subprocess([sys.executable, "-c", "print('ok')"], cwd=tmp_path)

    assert result.exit_code == 0
    assert result.worktree_changed is None


def test_worktree_detection_git_failure_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*args, **kwargs):
        raise FileNotFoundError("git missing")

    monkeypatch.setattr(runner.subprocess, "run", _raise)

    result = runner.run_subprocess([sys.executable, "-c", "print('ok')"], cwd=tmp_path)

    assert result.exit_code == 0
    assert result.worktree_changed is None
