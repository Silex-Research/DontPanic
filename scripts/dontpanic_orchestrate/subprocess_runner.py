"""Shared subprocess runner for agent CLI executors.

Plan 2026-05-04-003 F001 replaces per-executor ``subprocess.run`` timeouts
with process-group-aware termination. The runner only records external
observables: stdout/stderr bytes, timeout metadata, environment fallback
markers, and optional git worktree deltas.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

TIMEOUT_ENV = "DONTPANIC_SUBPROCESS_TIMEOUT_SECONDS"
GRACE_ENV = "DONTPANIC_SUBPROCESS_GRACE_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_GRACE_SECONDS = 15
MIN_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 7200
MIN_GRACE_SECONDS = 1
MAX_GRACE_SECONDS = 120
GIT_STATUS_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class SubprocessResult:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    timeout_seconds: int
    grace_period_used: bool
    captured_stdout_bytes: int
    captured_stderr_bytes: int
    worktree_changed: bool | None
    pgid: int
    env_markers: list[str] = field(default_factory=list)


def _parse_timeout_env(
    name: str,
    default: int,
    min_v: int,
    max_v: int,
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str | None]:
    """Parse bounded integer timeout env vars without ever raising.

    Absent env vars return ``default`` with no marker. Invalid values return
    ``default`` plus a marker suitable for later audit ``validation_performed``
    rendering.
    """
    source = env if env is not None else os.environ
    raw = source.get(name)
    if raw is None:
        return default, None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default, f"env_invalid: {name}={raw} (unparseable), fell back to {default}"
    if value < min_v or value > max_v:
        return (
            default,
            f"env_invalid: {name}={raw} (out of range [{min_v},{max_v}]), fell back to {default}",
        )
    return value, None


def _snapshot_worktree(cwd: Path | None) -> str | None:
    """Return ``git status --porcelain=v1`` output or None when unavailable.

    Worktree detection is strictly best-effort. Non-git directories, missing
    git, corrupt repos, permissions, and git timeouts all degrade to unknown
    instead of failing agent dispatch.
    """
    if cwd is None:
        return None
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v1"],  # noqa: S607  # PATH-relative tool invocation per D001
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GIT_STATUS_TIMEOUT_SECONDS,
            check=True,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
    ):
        return None
    return proc.stdout


def _worktree_changed(before: str | None, after: str | None) -> bool | None:
    if before is None or after is None:
        return None
    return before != after


def run_subprocess(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    input_data: str | bytes | None = None,
) -> SubprocessResult:
    """Run a command with process-group timeout handling.

    The subprocess is started as a new session leader so timeout handling can
    signal the entire process group. Stdout/stderr are always captured as
    bytes; callers decode according to their CLI protocol.
    """
    timeout_seconds, timeout_marker = _parse_timeout_env(
        TIMEOUT_ENV,
        DEFAULT_TIMEOUT_SECONDS,
        MIN_TIMEOUT_SECONDS,
        MAX_TIMEOUT_SECONDS,
        env=env,
    )
    grace_seconds, grace_marker = _parse_timeout_env(
        GRACE_ENV,
        DEFAULT_GRACE_SECONDS,
        MIN_GRACE_SECONDS,
        MAX_GRACE_SECONDS,
        env=env,
    )
    env_markers = [m for m in (timeout_marker, grace_marker) if m]
    stdin_bytes = input_data.encode() if isinstance(input_data, str) else input_data

    before = _snapshot_worktree(cwd)
    try:
        proc = subprocess.Popen(  # noqa: S603  # trusted argv + shell=False default per D001
            list(cmd),
            stdin=subprocess.PIPE if stdin_bytes is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env is not None else None,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as exc:
        after = _snapshot_worktree(cwd)
        stderr = f"{type(exc).__name__}: {exc}".encode()
        return SubprocessResult(
            exit_code=None,
            stdout=b"",
            stderr=stderr,
            timed_out=False,
            timeout_seconds=timeout_seconds,
            grace_period_used=False,
            captured_stdout_bytes=0,
            captured_stderr_bytes=len(stderr),
            worktree_changed=_worktree_changed(before, after),
            pgid=0,
            env_markers=env_markers,
        )

    pgid = proc.pid
    timed_out = False
    grace_period_used = False
    try:
        stdout, stderr = proc.communicate(input=stdin_bytes, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        grace_period_used = True
        _kill_process_group(pgid, signal.SIGTERM)
        try:
            stdout, stderr = proc.communicate(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            _kill_process_group(pgid, signal.SIGKILL)
            stdout, stderr = proc.communicate()

    stdout = stdout or b""
    stderr = stderr or b""
    after = _snapshot_worktree(cwd)
    return SubprocessResult(
        exit_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        timeout_seconds=timeout_seconds,
        grace_period_used=grace_period_used,
        captured_stdout_bytes=len(stdout),
        captured_stderr_bytes=len(stderr),
        worktree_changed=_worktree_changed(before, after),
        pgid=pgid,
        env_markers=env_markers,
    )


def _kill_process_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except OSError:
        pass
