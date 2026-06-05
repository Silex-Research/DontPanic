"""Plan 2026-05-23-004 F003 — `dontpanic dashboard` CLI.

Three subcommands compose existing surfaces into the V0 operator console:

  dontpanic dashboard build [--plans-root <p>] [--out <dir>]
      Export state-snapshot + per-stream files (state_cli.export_dashboard),
      capability status cache, reconcile check status, architecture status,
      and the F001 what-now ActionItem cache. Each subsystem failure is
      surfaced as a stderr warning, not a hard failure — operators may
      legitimately run `build` before reconcile baseline or capability
      status have ever been written.

  dontpanic dashboard open [...build flags...] [--no-launch]
      Run `build`, then print the canonical local path/URL to stdout and
      best-effort hand off to the OS opener (open / xdg-open / start).
      `--no-launch` (default in non-TTY / CI / sandbox) skips the opener.

  dontpanic dashboard serve [--host 127.0.0.1] [--port 0] [--no-watch]
                            [--watch-interval 2.0] [--once]
      Bind a localhost-only HTTP server in ``dashboard/`` and re-run the
      build loop on a periodic interval whenever a watched source has
      changed. ``--host`` defaults to ``127.0.0.1`` and refuses ``0.0.0.0``
      / ``::`` / hostnames that resolve to public addresses unless the
      operator passes the explicit ``--allow-remote`` flag — V0 console is
      operator-local by definition.

Compositional, not monolithic: the build orchestrator imports each
subsystem's existing public function (``state_cli`` export, ``capabilities_
status.run_status`` + ``write_cache``, ``reconcile.check_capabilities`` +
``render_check_json``, ``architecture.status``, and
``operator_console.write_cache``). Nothing in this module re-implements
those surfaces; we just sequence them and tolerate optional inputs.
"""

from __future__ import annotations

import argparse
import http.server
import ipaddress
import json
import os
import platform
import secrets
import signal
import socket
import socketserver
import subprocess  # noqa: S404 — invoked with fixed args + shell=False; see _default_opener
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import (
    active_supervisors,
    architecture,
    architecture_view_state,
    capabilities,
    capabilities_status,
    global_config,
    operator_console,
    plan_loader,
    reconcile,
    state_projection,
)
from dontpanic_orchestrate import gate_pause as _gp
from dontpanic_orchestrate import action_resolvability as _ar
from dontpanic_orchestrate import render_gate as _rg
from dontpanic_orchestrate import scope_lattice as _sl
import dataclasses as _dataclasses
import datetime as _dt

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 0  # 0 = pick a free ephemeral port; tests rely on this
DEFAULT_WATCH_INTERVAL_SECONDS = 2.0
DEFAULT_DASHBOARD_DIR_NAME = "dashboard"
DEFAULT_STATE_SUBDIR_NAME = "state"
LOCAL_LOOPBACK_ADDRESSES: frozenset[str] = frozenset(
    {"127.0.0.1", "::1", "localhost"}
)

# V0 console is local-only; realtime-dashboard adapters (the optional
# remote-mirror category) are explicitly out of scope and must not surface
# as dashboard action items per V0 acceptance (4).
V0_DASHBOARD_EXCLUDED_CATEGORIES: frozenset[str] = frozenset({"dashboard-realtime"})

# Plan-directory source files whose edits should retrigger a serve rebuild.
# Enumerated explicitly so the watcher (a) does not depend on parent-dir
# mtime bumps for inline edits, and (b) never picks up generated output.
_PLAN_SOURCE_RELATIVE_GLOBS: tuple[str, ...] = (
    "plan.md",
    "features.json",
    "INBOX.md",
    "decisions.jsonl",
    "signoff.json",
    "audit/*",
    "evidence/*",
)


# ── BuildReport ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BuildReport:
    """Summary of one ``build`` invocation.

    The fields are intentionally narrow: the serve loop reads them to
    decide whether anything actually changed, and tests assert on
    ``state_files`` and ``what_now_cache_path`` to confirm acceptance.
    """

    out_dir: Path
    state_files: tuple[Path, ...]
    what_now_cache_path: Path | None
    capability_cache_path: Path | None
    reconcile_status_path: Path | None
    architecture_status_path: Path | None
    architecture_view_state_path: Path | None = None
    config_inventory_path: Path | None = None
    skill_recommendations_path: Path | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


# ── public helpers (testable seams) ─────────────────────────────────────


def default_plans_root(cwd: Path | None = None) -> Path:
    """``<cwd>/docs/plans`` — the same default ``state_cli`` uses."""

    base = cwd if cwd is not None else Path.cwd()
    return base / "docs" / "plans"


def default_dashboard_dir(cwd: Path | None = None) -> Path:
    """``<cwd>/dashboard`` — the checked-in static dashboard root."""

    base = cwd if cwd is not None else Path.cwd()
    return base / DEFAULT_DASHBOARD_DIR_NAME


def default_state_out_dir(cwd: Path | None = None) -> Path:
    """``<cwd>/dashboard/state`` — the canonical export location."""

    return default_dashboard_dir(cwd) / DEFAULT_STATE_SUBDIR_NAME


def local_what_now_cache_path() -> Path:
    """Re-export so the serve loop can compare mtimes without re-deriving."""

    return operator_console.default_cache_path()


# ── dashboard serve singleton detection (F013 AC2) ──────────────────────
#
# A running `dashboard serve` records a small JSON singleton under the canonical
# DontPanic HOME (``global_config.dontpanic_home()``) — NOT the served
# ``dashboard_dir`` / cwd — so config inventory / operations guidance can
# AUTO-DETECT the live URL for the response-level dashboard hint without the
# caller threading a URL through. Keying by the home (rather than the dashboard
# dir) is what makes the "one dashboard server per DontPanic home" guarantee
# (F010 AC1) impossible to bypass by serving the same home from a different
# working directory or ``--dashboard-dir``. F010 builds the full
# refuse-second-serve / --replace behavior on top of this detection primitive;
# F013 only needs "is a dashboard live, and at what URL?".
#
# Every singleton helper takes an optional ``home`` directory (defaulting to the
# canonical home) so tests can drive a hermetic per-test home. The autouse
# conftest fixture already redirects ``DONTPANIC_HOME`` to a tmp dir, so a
# no-argument call is isolated per test without any explicit threading.

DEFAULT_SINGLETON_FILENAME = ".serve-singleton.json"


def _singleton_record_path(home: Path | None = None) -> Path:
    base = home if home is not None else global_config.dontpanic_home()
    return base / DEFAULT_SINGLETON_FILENAME


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we cannot signal it — still alive.
        return True
    except OSError:
        return False
    return True


def detect_active_dashboard(home: Path | None = None) -> dict[str, Any] | None:
    """Return the live serve-singleton record for this DontPanic home, or None.

    Reads the record written by :func:`serve_start` under the canonical DontPanic
    home, verifies the recorded pid is still alive, and prunes a stale record
    (dead pid) so a crashed serve never advertises a phantom URL. This is the
    detection primitive the config inventory uses to auto-populate the
    response-level dashboard hint's ``active_url`` (F013 AC2).
    """
    path = _singleton_record_path(home)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pid = record.get("pid") if isinstance(record, dict) else None
    if not isinstance(pid, int) or not _pid_alive(pid):
        # Stale / malformed record — prune it.
        try:
            path.unlink()
        except OSError:  # noqa: S110 — best-effort prune; nothing to recover
            pass
        return None
    return record


def detect_active_url(home: Path | None = None) -> str | None:
    """Active dashboard URL when a serve singleton is live for this home, else None."""
    record = detect_active_dashboard(home)
    if not record:
        return None
    url = record.get("url")
    return url if isinstance(url, str) and url else None


# ── dashboard status helper + singleton guard (F010) ────────────────────
#
# F013 added the detection primitive (detect_active_dashboard / detect_active_url).
# F010 layers the operator-facing surface on top: a single status helper that
# CLI/agent guidance routes through (so dashboard discovery is implemented once),
# a refuse-second-serve / --replace guard so local servers do not accumulate, and
# a shared render helper that emits the dashboard hint once per response.

DASHBOARD_START_COMMAND = "dontpanic dashboard serve"


def render_hint_line(
    *,
    is_running: bool,
    url: str | None,
    start_command: str = DASHBOARD_START_COMMAND,
) -> str:
    """Canonical single source for the dashboard-pointer wording (F010).

    Every response surface — operations guidance, skill recommendation, and
    config inventory — renders its dashboard hint through this one function (via
    their ``text()`` methods, which delegate here), so the wording lives in
    exactly one place rather than being re-spelled at each call site (codex F010
    i1 architecture finding). :meth:`DashboardStatus.hint_text` and
    :func:`render_dashboard_hint_once` route through it too.
    """
    if is_running and url:
        return f"Dashboard is running — open {url}"
    return f"Dashboard is not running — start it with `{start_command}`"


class DashboardAlreadyRunningError(RuntimeError):
    """Raised when ``dashboard serve`` is requested for a DontPanic home that
    already has a live singleton and the caller did not pass ``replace=True``
    (F010 AC1).

    Carries the existing ``url`` (when recorded) and the ``home`` the live
    singleton belongs to so the CLI can print an actionable refusal — open the
    running dashboard or pass ``--replace``. Keyed by the canonical DontPanic
    home, not the served dashboard dir, so launching from a different cwd /
    ``--dashboard-dir`` against the same home is still refused."""

    def __init__(
        self,
        url: str | None,
        home: Path,
        project: str | None = None,
    ) -> None:
        self.url = url
        self.home = home
        self.project = project
        super().__init__(
            f"a dashboard is already serving this home at {url or home}"
        )


class SameProcessReplaceError(RuntimeError):
    """Raised when ``replace=True`` is requested but the live singleton is owned
    by THIS process (``record["pid"] == os.getpid()``) (F010 fix#2).

    Silently clearing the record and binding a second server would leave the old
    in-process server still bound and serving — two live servers, one record. We
    cannot SIGTERM ourselves to stop it, so we refuse honestly: the in-process
    dashboard must be shut down (``handle.shutdown()``) before re-serving in the
    same process. Carries the existing ``url`` so the caller can report it."""

    def __init__(self, url: str | None, home: Path) -> None:
        self.url = url
        self.home = home
        super().__init__(
            "a dashboard is already running in THIS process at "
            f"{url or home}; stop it (handle.shutdown()) before re-serving — "
            "--replace cannot supersede an in-process server"
        )


@dataclass(frozen=True)
class DashboardStatus:
    """Lightweight running-state of the dashboard for CLI/agent guidance (F010 AC4).

    When a singleton is live this carries the active ``url`` plus the recorded
    ``project`` and the ``scope`` (the dashboard home the record belongs to).
    When nothing is running ``is_running`` is False and ``start_command`` is the
    exact command to launch it. config inventory and operations guidance both
    route their dashboard discovery through :func:`dashboard_status` rather than
    re-deriving it, so the "is it running, and where?" question has one answer.
    """

    is_running: bool
    url: str | None = None
    project: str | None = None
    # ``scope`` is the DontPanic home the singleton record belongs to (str(home)).
    scope: str | None = None
    start_command: str = DASHBOARD_START_COMMAND

    def hint_text(self) -> str:
        return render_hint_line(
            is_running=self.is_running,
            url=self.url,
            start_command=self.start_command,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_running": self.is_running,
            "url": self.url if self.is_running else None,
            "project": self.project,
            "scope": self.scope,
            "start_command": None if self.is_running else self.start_command,
            "text": self.hint_text(),
        }


def dashboard_status(home: Path | None = None) -> DashboardStatus:
    """Single source of truth for "is a dashboard running, and at what URL?" (AC4).

    Keyed by the canonical DontPanic home (``global_config.dontpanic_home()`` when
    ``home`` is None) — the same location :func:`serve_start` records its
    singleton — so config inventory and operations guidance, which both call this
    with no argument, discover a live serve regardless of which cwd / dashboard
    dir it was launched from. Routes through :func:`detect_active_url` (so
    callers/tests that monkeypatch detection keep working) and
    :func:`detect_active_dashboard` for the recorded project. Both prune a
    stale/dead-pid record as a side effect (AC2). Returns a not-running status
    carrying the exact serve command when no singleton is live.
    """
    base = home if home is not None else global_config.dontpanic_home()
    url = detect_active_url(base)
    if not url:
        return DashboardStatus(is_running=False, scope=str(base))
    project: str | None = None
    record = detect_active_dashboard(base)
    if record:
        proj = record.get("project")
        project = proj if isinstance(proj, str) and proj else None
    return DashboardStatus(
        is_running=True,
        url=url,
        project=project,
        scope=str(base),
    )


def render_dashboard_hint_once(
    status: DashboardStatus, *, human_required_count: int
) -> str | None:
    """Emit the dashboard hint text exactly once per response (AC5).

    Returns the single hint line when at least one item in the response requires
    human input — regardless of HOW MANY do, so the dedup lives in this shared
    helper rather than at each call site. Returns ``None`` when nothing needs a
    human (no dashboard pointer is shown for an all-clear response).
    """
    if human_required_count <= 0:
        return None
    return status.hint_text()


# --replace supersede: how long to wait for the old server to exit and release
# its port before the fresh serve binds, and how often to poll. SIGTERM is
# asynchronous, so binding immediately races the old listener's socket release
# (codex F010 i1). We poll for the pid to exit, escalate to SIGKILL if it ignores
# SIGTERM within the window, and only then let the bind proceed (with a few
# reuse-address retries to absorb the final kernel release).
_SUPERSEDE_TIMEOUT_SECONDS = 5.0
_SUPERSEDE_POLL_INTERVAL_SECONDS = 0.1


# --replace identity guard: before SIGTERM/SIGKILLing the recorded pid, POSITIVELY
# confirm that the live pid is actually a dontpanic dashboard server. A reused PID
# (the old dashboard died and the OS reassigned its number to an unrelated process)
# must never be killed by --replace (codex F010 i2 high). We inspect the live
# process's command line via `ps` (shell=False, fixed args) and only treat it as
# ours when the command line carries a dashboard-serve signature.
_PS_PROCESS_PROBE_TIMEOUT_SECONDS = 3.0

# A live process counts as "our dashboard" when its command line contains BOTH
# tokens of any one of these pairs (case-insensitive). This is intentionally a
# small module-level constant so tests can read/extend it and so the signature
# rule lives in exactly one place.
_DASHBOARD_PROCESS_SIGNATURES: tuple[tuple[str, ...], ...] = (
    ("dashboard", "serve"),
    ("dontpanic", "serve"),
)


def _command_matches_dashboard_signature(command: str) -> bool:
    """True when ``command`` (a process command line) looks like a dontpanic
    dashboard serve — every token of at least one signature pair is present
    (case-insensitive). Pure/string-only so tests can drive it directly."""
    lowered = command.lower()
    return any(
        all(token in lowered for token in signature)
        for signature in _DASHBOARD_PROCESS_SIGNATURES
    )


def _pid_is_dashboard_process(pid: int) -> bool:
    """POSITIVELY confirm ``pid`` is a live dontpanic dashboard server (macOS/no /proc).

    Runs ``ps -p <pid> -o command=`` (shell=False, fixed args) and returns True
    ONLY when the resulting command line matches a dashboard-serve signature
    (:data:`_DASHBOARD_PROCESS_SIGNATURES`). On ANY failure — ps missing,
    non-zero exit (pid gone), timeout, or empty output — returns False: we cannot
    confirm the process is ours, so we treat it as NOT our dashboard and never
    signal it. Module-level so tests can monkeypatch it to simulate an
    "alive but foreign" pid without spawning a real process.
    """
    if pid <= 0:
        return False
    try:
        # noqa S603/S607: fixed args, shell=False; `ps` is PATH-resolved by design.
        ps_argv = ["ps", "-p", str(pid), "-o", "command="]  # noqa: S607
        result = subprocess.run(  # noqa: S603
            ps_argv,
            capture_output=True,
            text=True,
            timeout=_PS_PROCESS_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    command = (result.stdout or "").strip()
    if not command:
        return False
    return _command_matches_dashboard_signature(command)


def _wait_for_pid_exit(pid: int, *, timeout: float) -> bool:
    """Poll until ``pid`` is gone or ``timeout`` elapses. True if it exited."""
    deadline = time.monotonic() + timeout
    while _pid_alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(_SUPERSEDE_POLL_INTERVAL_SECONDS)
    return True


def _supersede_existing_singleton(
    home: Path, record: dict[str, Any]
) -> None:
    """Stop a live singleton so ``--replace`` can take over its port (AC3).

    SIGTERMs the recorded pid ONLY when it is alive, is NOT the current process
    (we never signal ourselves), AND :func:`_pid_is_dashboard_process` POSITIVELY
    confirms the live pid really is a dontpanic dashboard server (codex F010 i2
    high). A reused PID — the old dashboard died and the OS reassigned its number
    to an unrelated process — is alive but NOT confirmed as ours, so we never
    signal it: we just clear the stale record and let the fresh serve proceed.
    For the confirmed-dashboard case we WAIT for it to exit so the old server
    releases its listening socket before the fresh serve binds, escalating to
    SIGKILL within :data:`_SUPERSEDE_TIMEOUT_SECONDS` so the operator's explicit
    ``--replace`` is honored rather than silently leaving two servers. The record
    is cleared regardless so the new server records its own.
    """
    pid = record.get("pid")
    if (
        isinstance(pid, int)
        and pid > 0
        and pid != os.getpid()
        and _pid_alive(pid)
        and _pid_is_dashboard_process(pid)
    ):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:  # noqa: S110 — best-effort supersede; record is still cleared
            pass
        else:
            if not _wait_for_pid_exit(pid, timeout=_SUPERSEDE_TIMEOUT_SECONDS):
                # Graceful stop ignored — escalate so the replace actually frees
                # the port instead of racing a still-live old server.
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:  # noqa: S110 — already gone is fine
                    pass
                _wait_for_pid_exit(pid, timeout=_SUPERSEDE_TIMEOUT_SECONDS)
    # Alive-but-not-confirmed (PID reuse / foreign process) falls through here:
    # no signal is sent; we only drop the stale record so the fresh serve proceeds.
    _clear_singleton_record(home)


def _write_singleton_record(
    *, home: Path, host: str, port: int, url: str, project: str | None
) -> Path:
    path = _singleton_record_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "url": url,
        "project": project,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # Dashboard-specific identity for the --replace guard: a unique token so a
        # record can be matched to the process/handle that wrote it, independent of
        # the OS-recyclable pid (codex F010 i2 high). Combined with the positive
        # ps-based process confirmation, this keeps --replace from ever signaling a
        # reused PID belonging to an unrelated process.
        "guard_token": secrets.token_hex(16),
    }
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _clear_singleton_record(home: Path | None = None) -> None:
    path = _singleton_record_path(home)
    try:
        if path.is_file():
            path.unlink()
    except OSError:  # noqa: S110 — best-effort cleanup on shutdown
        pass


def write_config_inventory(
    *,
    out_dir: Path,
    project_name: str | None,
    dashboard_url: str | None = None,
    warn: Callable[[str], None] | None = None,
) -> Path | None:
    """Render the F008 config inventory into ``out_dir/config-inventory.json``.

    Shared by :func:`build` and :func:`serve_start` so the served dashboard's
    inventory is rebuilt AFTER the serve-singleton record exists — otherwise the
    first served inventory falls back to the start command even though the
    dashboard is live immediately afterward (F013 AC2).

    ``build`` passes ``dashboard_url=None`` so the response-level hint
    auto-detects a running singleton via the default dashboard home — the AC2
    "no manual URL pass-through" path. ``serve_start`` passes its freshly-bound
    ``handle.url`` directly: it just bound that socket, so threading the known
    URL is both correct and independent of which ``dashboard_dir`` it serves
    (auto-detection keys off the *default* home, which a ``--dashboard-dir``
    serve would miss).

    Best-effort: a rendering failure is surfaced to ``warn`` and returns ``None``
    rather than crashing the caller (build must tolerate optional inputs).
    """

    warn = warn if warn is not None else (lambda _msg: None)
    try:
        from dontpanic_orchestrate import config_inventory

        try:
            inventory = config_inventory.collect_inventory(
                project=project_name, dashboard_url=dashboard_url
            )
        except config_inventory.UnresolvedProjectError:
            # A fleet (`all`) / unresolved selector has no single project scope;
            # fall back to machine-only so the served inventory still renders.
            inventory = config_inventory.collect_inventory(
                project=None, dashboard_url=dashboard_url
            )
        path = out_dir / "config-inventory.json"
        path.write_text(
            json.dumps(
                config_inventory.to_dashboard_state(inventory),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return path
    except Exception as exc:  # noqa: BLE001 — surface to warn, never crash the build
        warn(f"config inventory skipped: {exc}")
        return None


def write_skill_recommendations(
    *,
    out_dir: Path,
    plans_root: Path,
    plan_id: str | None,
    project_name: str | None = None,
    dashboard_url: str | None = None,
    warn: Callable[[str], None] | None = None,
) -> Path | None:
    """Render the F016 skill recommendations into ``out_dir/skill-recommendations.json``.

    Renders the SAME :class:`skill_recommendation.RecommendationReport` the CLI
    ``dontpanic skills recommend`` prints (F016 AC9), so the dashboard and CLI
    never drift. Skill recommendations are plan-scoped (they need the plan's
    applicable-skills + rubrics), so this is a no-op when no ``plan_id`` is in
    scope or no ``claude/skills`` dir exists above the plan.

    Best-effort: a rendering failure is surfaced to ``warn`` and returns ``None``
    rather than crashing the build (must tolerate optional inputs)."""
    warn = warn if warn is not None else (lambda _msg: None)
    if not plan_id:
        return None
    try:
        from dontpanic_orchestrate import cli as _cli
        from dontpanic_orchestrate import skill_recommendation

        plan_dir = plans_root / plan_id
        if not plan_dir.is_dir():
            return None
        skills_dir = _cli._resolve_skills_dir(plan_dir)
        if skills_dir is None:
            return None
        report = skill_recommendation.collect(
            plan_dir,
            skills_dir,
            project=project_name,
            dashboard_url=dashboard_url,
        )
        path = out_dir / "skill-recommendations.json"
        path.write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path
    except Exception as exc:  # noqa: BLE001 — surface to warn, never crash the build
        warn(f"skill recommendations skipped: {exc}")
        return None


# ── build orchestrator ──────────────────────────────────────────────────


def build(
    *,
    plans_root: Path | None = None,
    out_dir: Path | None = None,
    redact_level: str = "operator",
    plan_id: str | None = None,
    write_what_now_cache: bool = True,
    write_capabilities_cache: bool = True,
    check_reconcile: bool = True,
    check_architecture: bool = True,
    repo_root: Path | None = None,
    warn: Callable[[str], None] | None = None,
    capabilities_cache_path: Path | None = None,
    what_now_cache_path_override: Path | None = None,
    project_name: str | None = None,
    project_display_name: str | None = None,
) -> BuildReport:
    """Compose every V0 dashboard surface into a single build pass.

    The function deliberately swallows per-surface failures into the
    ``warnings`` tuple of the returned :class:`BuildReport`. Acceptance
    item (5) — *missing optional inputs* — means a fresh operator with
    no install snapshot or no capability cache must still be able to run
    ``build`` and get a usable dashboard with what-now degraded
    gracefully.

    ``capabilities_cache_path`` and ``what_now_cache_path_override``
    redirect the operator-global write targets when set. Per-project
    builds (``projects_dashboard.build_project_state``) pass per-project
    paths so a fleet build cannot last-project-wins the global
    single-repo caches at ``~/.dontpanic/capabilities-status.json`` and
    ``~/.dontpanic/dashboard/what-now.json``. ``None`` preserves the
    existing single-repo defaults.
    """

    plans_root = plans_root if plans_root is not None else default_plans_root()
    out_dir = out_dir if out_dir is not None else default_state_out_dir()
    warn = warn if warn is not None else (lambda _msg: None)
    warnings: list[str] = []

    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. State projection export — required, but tolerate empty plans_root.
    state_files = _export_state(
        plans_root=plans_root,
        out_dir=out_dir,
        redact_level=redact_level,
        plan_id=plan_id,
        warn=lambda msg: (warnings.append(msg), warn(msg)),
    )

    # 2. Capability status cache.
    #    The full envelope still lands in the operator-local cache
    #    (~/.dontpanic/capabilities-status.json) because operators who
    #    opt into out-of-scope adapters (e.g. realtime mirror) still
    #    need that view from `dontpanic capabilities`. The *dashboard*
    #    copy and the action-item generator both consume a V0-scoped
    #    envelope so out-of-scope capabilities never surface as console
    #    work — see V0_DASHBOARD_EXCLUDED_CATEGORIES.
    capability_cache_path: Path | None = None
    capability_envelope = None
    dashboard_capability_envelope = None
    if write_capabilities_cache:
        try:
            capability_index = capabilities.load_capabilities(repo_root)
            capability_envelope = capabilities_status.run_status(
                capability_index=capability_index,
                repo_root=repo_root,
            )
            capability_cache_target = (
                capabilities_cache_path
                if capabilities_cache_path is not None
                else global_config.dontpanic_home() / "capabilities-status.json"
            )
            capability_cache_path = capabilities_status.write_cache(
                capability_envelope,
                path=capability_cache_target,
            )
            dashboard_capability_envelope = _scope_envelope_to_v0_local(
                capability_envelope, capability_index
            )
            (out_dir / "capabilities-status.json").write_text(
                capabilities_status.render_json(dashboard_capability_envelope),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 — surface to warnings, do not crash build
            msg = f"capabilities status skipped: {exc}"
            warnings.append(msg)
            warn(msg)

    # 3. Reconcile check (capabilities-area drift).
    reconcile_status_path: Path | None = None
    reconcile_result = None
    if check_reconcile:
        try:
            reconcile_result = reconcile.check_capabilities(repo_root=repo_root)
            reconcile_status_path = out_dir / "reconcile-status.json"
            reconcile_status_path.write_text(
                reconcile.render_check_json(reconcile_result),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"reconcile check skipped: {exc}"
            warnings.append(msg)
            warn(msg)

    # 4. Architecture status (advisory only — V0 never blocks on it).
    architecture_status_path: Path | None = None
    arch_status: dict[str, Any] | None = None
    architecture_view_state_path: Path | None = None
    if check_architecture:
        try:
            root = repo_root if repo_root is not None else Path.cwd()
            arch_status = architecture.status(root)
            architecture_status_path = out_dir / "architecture-status.json"
            architecture_status_path.write_text(
                json.dumps(arch_status, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"architecture status skipped: {exc}"
            warnings.append(msg)
            warn(msg)

        # Plan 2026-05-24-002 F001 — derive the architecture view-state
        # cache from the existing snapshot. Best-effort; missing/stale
        # architecture is represented inside the view-state itself, not
        # surfaced as a build error.
        try:
            root = repo_root if repo_root is not None else Path.cwd()
            view_inputs = architecture_view_state.load_inputs(
                root,
                project_name=project_name,
                project_display_name=project_display_name,
            )
            view_state = architecture_view_state.build_view_state(
                view_inputs, repo_root=root
            )
            architecture_view_state_path = architecture_view_state.write_cache(
                view_state, out_dir=out_dir
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"architecture view-state skipped: {exc}"
            warnings.append(msg)
            warn(msg)

    # 5. What-now ActionItem cache — F001 envelope. Always emit a dashboard
    #    copy alongside the operator-local cache so the static loader does
    #    not need to traverse $HOME. Action items consume the V0-scoped
    #    envelope so out-of-scope capabilities never become console work.
    what_now_cache_path: Path | None = None
    if write_what_now_cache:
        try:
            items = _gather_action_items(
                plans_root=plans_root,
                capability_envelope=dashboard_capability_envelope,
                reconcile_result=reconcile_result,
                arch_status=arch_status,
                plan_id=plan_id,
                project_name=project_name,
            )
            # Plan 2026-05-24-004 F003 (D003 + D019) — merge event-actions
            # sidecar into provider-derived items BEFORE writing what-now.json
            # to out_dir. Both write paths (dashboard.build's out_dir copy +
            # operator_console.write_cache's home cache) must merge or the
            # served dashboard state goes stale on whichever path skips.
            merged_items = operator_console.merge_with_event_sidecar(items)
            # Plan 2026-06-02-001 F003 — the dashboard build JSON MUST route
            # through the shared render boundary (action_renderers), not
            # operator_console.render_json, so the served what-now.json is
            # deduped-by-dedupe_key + secret-scrubbed + brand-normalized
            # IDENTICALLY to the CLI/JSON and agent-brief surfaces. Lazy import
            # avoids an action_renderers↔dashboard cycle at module load.
            from dontpanic_orchestrate import action_renderers as _action_renderers

            (out_dir / "what-now.json").write_text(
                _action_renderers.render_dashboard_json(merged_items),
                encoding="utf-8",
            )
            # write_cache merges by default (merge_event_sidecar=True); pass
            # the already-merged list and disable the inner merge to avoid
            # double-application that would be a no-op anyway.
            what_now_cache_path = operator_console.write_cache(
                merged_items,
                path=what_now_cache_path_override,
                merge_event_sidecar=False,
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"what-now cache skipped: {exc}"
            warnings.append(msg)
            warn(msg)

    # 6. Config inventory (F013) — render the SAME F008 inventory the CLI
    #    `config inventory` shows as dashboard Settings/Setup cards, not merely a
    #    generated state blob. collect_inventory auto-detects a running dashboard
    #    singleton for the response-level hint (no manual dashboard_url needed).
    config_inventory_path = write_config_inventory(
        out_dir=out_dir,
        project_name=project_name,
        warn=lambda msg: (warnings.append(msg), warn(msg)),
    )

    # 7. Skill recommendations (F016) — render the SAME SkillAction data the CLI
    #    `dontpanic skills recommend` shows so CLI and dashboard reach parity
    #    (AC9). Plan-scoped: a no-op when no plan_id or no claude/skills dir. The
    #    missing-input ActionChoice is ALSO merged into the what-now action queue
    #    above (see `_gather_action_items`) so the recommendation surfaces as a
    #    real console action, not merely a state blob (AC8/AC9).
    skill_recommendations_path = write_skill_recommendations(
        out_dir=out_dir,
        plans_root=plans_root,
        plan_id=plan_id,
        project_name=project_name,
        warn=lambda msg: (warnings.append(msg), warn(msg)),
    )

    return BuildReport(
        out_dir=out_dir,
        state_files=tuple(state_files),
        what_now_cache_path=what_now_cache_path,
        capability_cache_path=capability_cache_path,
        reconcile_status_path=reconcile_status_path,
        architecture_status_path=architecture_status_path,
        architecture_view_state_path=architecture_view_state_path,
        config_inventory_path=config_inventory_path,
        skill_recommendations_path=skill_recommendations_path,
        warnings=tuple(warnings),
    )


def _export_state(
    *,
    plans_root: Path,
    out_dir: Path,
    redact_level: str,
    plan_id: str | None,
    warn: Callable[[str], None],
) -> list[Path]:
    """Mirror of ``state_cli._export_dashboard_main`` but library-callable.

    We do not shell out to the CLI because that drags argparse + stderr
    coupling into the build loop. ``state_projection.gather`` is the same
    surface ``state_cli`` calls, so the JSON shape stays identical.
    """

    written: list[Path] = []

    def _on_malformed(plan_dir: Path, exc: Exception) -> None:
        warn(f"state export skipping malformed plan {plan_dir.name}: {exc}")

    try:
        snap = state_projection.gather(
            plans_root,
            redact_level=redact_level,
            plan_id=plan_id,
            tolerate_malformed_plans=True,
            on_malformed_plan=_on_malformed,
        )
    except Exception as exc:  # noqa: BLE001
        warn(f"state export skipped: {exc}")
        return written

    envelope = snap.model_dump(mode="json")

    snapshot_path = out_dir / "state-snapshot.json"
    snapshot_path.write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    written.append(snapshot_path)

    streams = envelope.get("streams", {})
    for stream_name in state_projection.ALL_STREAMS:
        path = out_dir / f"{stream_name}.json"
        path.write_text(
            json.dumps(streams.get(stream_name, []), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        written.append(path)

    manifest = {
        "schema_version": envelope.get("schema_version"),
        "captured_at": envelope.get("captured_at"),
        "redact_level": envelope.get("redact_level"),
        "dontpanic_version": envelope.get("dontpanic_version"),
        "streams": [
            {
                "name": s,
                "file": f"{s}.json",
                "count": len(streams.get(s, [])),
            }
            for s in state_projection.ALL_STREAMS
        ],
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    written.append(manifest_path)
    return written


def _gather_action_items(
    *,
    plans_root: Path,
    capability_envelope: Any | None,
    reconcile_result: Any | None,
    arch_status: dict[str, Any] | None,
    plan_id: str | None,
    project_name: str | None = None,
) -> tuple[operator_console.ActionItem, ...]:
    """Drive each provider against already-loaded inputs."""

    # Gates: walk plans_root, reuse gate_pause.unmet_gates so we surface
    # the same set state_projection does.
    gate_inputs: list[Any] = []
    plan_dirs_by_id: dict[str, Path] = {}
    # F002 LiveState inputs: plan lifecycle status + cleared gates, captured for
    # EVERY loaded plan (incl. completed/abandoned), so clears_when predicates can
    # suppress resolved/phantom items at source.
    plan_status_by_id: dict[str, str | None] = {}
    cleared_gates_by_id: dict[str, list[str]] = {}
    if plans_root.exists() and plans_root.is_dir():
        for child in sorted(plans_root.iterdir()):
            if not (child.is_dir() and (child / "plan.md").is_file()):
                continue
            if plan_id is not None and child.name != plan_id:
                continue
            try:
                loaded = plan_loader.load(child)
            except Exception:  # noqa: BLE001, S112 — malformed plan dirs skipped silently for dashboard
                continue
            plan_dirs_by_id[loaded.plan_id] = loaded.plan_dir
            # Coerce enum-valued status/gates to plain strings so clears_when
            # predicates (which compare against string status/gate sets) match.
            # plan_loader returns Status/HumanGate enums; leaking them into
            # live_state would make `Status.active not in {"active", ...}` True
            # and wrongly suppress live plans' gate cards.
            _status = getattr(loaded.plan, "status", None)
            plan_status_by_id[loaded.plan_id] = (
                _status.value if hasattr(_status, "value") else _status
            )
            declared = list(loaded.plan.human_gates or [])
            if not declared:
                continue
            unmet = _gp.unmet_gates(loaded.plan_dir, declared)
            unmet_set = set(unmet)
            cleared_gates_by_id[loaded.plan_id] = [
                (g.value if hasattr(g, "value") else str(g))
                for g in declared
                if (g.value if hasattr(g, "value") else str(g)) not in unmet_set
            ]
            for gate_name in unmet:
                gate_inputs.append(
                    _GateView(
                        plan_id=loaded.plan_id,
                        gate_name=gate_name,
                        kind=_classify_gate_kind(gate_name),
                        reason="declared gate not cleared",
                    )
                )

    gate_items = operator_console.provide_gate_actions(
        gate_inputs, plan_dirs=plan_dirs_by_id
    )
    capability_items = operator_console.provide_capability_actions(capability_envelope)
    reconcile_items = operator_console.provide_reconcile_actions(reconcile_result)
    arch_items = operator_console.provide_architecture_actions(arch_status)

    try:
        supervisors = active_supervisors.list_active(prune=False)
    except Exception:
        supervisors = []
    supervisor_items = operator_console.provide_supervisor_actions(supervisors)

    # Plan 2026-05-30-001 F007: surface the operations-guidance decision set
    # (wait/redispatch, raise-ceiling, finalize a cleared signoff, resume/close)
    # as ActionItems built from the SAME typed ActionChoice data the CLI prints,
    # so budget/iteration/finalize decisions never drift between the two surfaces.
    operations_items = _gather_operations_items(plan_dirs_by_id)

    # Plan 2026-05-30-001 F016: surface the skill-recommendation missing-input
    # ActionChoice (and its shared dashboard affordance) as ActionItems built from
    # the SAME typed data the CLI `dontpanic skills recommend` prints, so the
    # recommendation is a real console action and not merely a state blob (AC8/AC9).
    skill_items = _gather_skill_recommendation_items(
        plan_dirs_by_id, project_name=project_name
    )

    aggregated = operator_console.aggregate(
        gate_items,
        capability_items,
        reconcile_items,
        supervisor_items,
        arch_items,
        operations_items,
        skill_items,
    )
    # F002 suppress-at-source: drop any item whose clears_when is already
    # satisfied against live state. Items with clears_when=None are kept
    # unchanged. F003 wires gate cards; F004 wires reconcile readiness +
    # operator-attested capabilities below.
    live_state = {
        "plan_status": plan_status_by_id,
        "cleared_gates": cleared_gates_by_id,
        # F004 reconcile readiness (global scope): snapshot present iff a
        # reconcile result exists without a missing_snapshot drift; cache fresh
        # iff there is no stale_status_cache drift. install_snapshot_fresh keys
        # off both. None reconcile -> unknown -> readiness items kept (correct:
        # we cannot prove readiness, so do not auto-hide).
        "reconcile": _reconcile_live_state(reconcile_result),
        # F004 operator-attested capabilities: capability_id -> status string;
        # capability_ready suppresses a needs_setup/blocked card only once a
        # re-probe reports the capability ready (clear on evidence).
        "capabilities": _capabilities_live_state(capability_envelope),
    }
    # Plan 2026-06-04-005 wiring: route EVERY card through the unified render gate
    # (F001) — suppress-unless-proven-live — instead of 001's render-unless-resolved
    # suppress_resolved. Each card's scope (F002) and per-source freshness (F003)
    # are computed here and injected; DEMOTE'd cards collapse into F004 uncertainty
    # cards (never silently dropped). The gate is now the ONLY path by which a
    # Needs Action card reaches the rendered set.
    now = _dt.datetime.now(_dt.timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    selected_scope = _sl.Scope.PROJECT.value if project_name else _sl.Scope.FLEET.value

    # Producer-asserted scope by source semantics (NOT project_name inference):
    # install/reconcile/capabilities/supervisors are global install/fleet state;
    # gates + architecture are per-repo (project), carrying their project_name.
    _source_scope = {
        operator_console.SOURCE_RECONCILE: _sl.Scope.GLOBAL.value,
        operator_console.SOURCE_CAPABILITY: _sl.Scope.GLOBAL.value,
        operator_console.SOURCE_SUPERVISOR: _sl.Scope.GLOBAL.value,
        operator_console.SOURCE_GATE: _sl.Scope.PROJECT.value,
        operator_console.SOURCE_ARCHITECTURE: _sl.Scope.PROJECT.value,
    }
    # All sources here were just evaluated at build time → fresh + ok. A source
    # whose producer input was absent (couldn't evaluate) is marked eval_ok=False
    # so the gate demotes only that source's cards (F003 fail-closed).
    present_sources = {getattr(c, "source", None) for c in aggregated}
    source_eval_map = {
        s: {"evaluated_at": now_iso, "eval_ok": True} for s in present_sources if s
    }
    if reconcile_result is None and operator_console.SOURCE_RECONCILE in source_eval_map:
        source_eval_map[operator_console.SOURCE_RECONCILE]["eval_ok"] = False
    if capability_envelope is None and operator_console.SOURCE_CAPABILITY in source_eval_map:
        source_eval_map[operator_console.SOURCE_CAPABILITY]["eval_ok"] = False

    rendered: list[operator_console.ActionItem] = []
    demoted: list[operator_console.ActionItem] = []
    for card in aggregated:
        if getattr(card, "scope", None) is None:
            _sc = _source_scope.get(getattr(card, "source", None))
            if _sc is not None:
                card = _dataclasses.replace(card, scope=_sc)
        st = _sl.resolve_card_scope_state(
            card, selected_scope=selected_scope, selected_project=project_name
        )
        fr = state_projection.card_source_freshness(card, source_eval_map, now=now)
        decision = _rg.render_decision(
            card,
            scope_state=st,
            source_fresh=not fr["is_stale"],
            source_evaluable=fr["eval_ok"],
            live_state=live_state,
        )
        if decision == _rg.RENDER:
            rendered.append(card)
        elif decision == _rg.DEMOTE:
            demoted.append(card)
        # SUPPRESS → dropped (not relevant to this scope, or resolved at source)

    # F004: a demoted source's cards collapse into one uncertainty card each.
    freshness_by_source = {
        getattr(c, "source", None): {
            "evaluated_at": now_iso,
            "reason": "source stale or could not be evaluated",
        }
        for c in demoted
    }
    uncertainty = operator_console.collapse_demoted_to_uncertainty(
        demoted, freshness_by_source=freshness_by_source, captured_at=now_iso
    )
    return tuple(rendered) + tuple(uncertainty)


def _reconcile_live_state(reconcile_result: Any | None) -> dict[str, bool]:
    """Derive {snapshot_present, cache_fresh} from a reconcile check result for
    the install_snapshot_fresh predicate (F004). Returns an empty mapping when
    no reconcile result is available, so the predicate evaluates False and the
    readiness item is kept rather than auto-suppressed."""
    if reconcile_result is None:
        return {}
    status = getattr(reconcile_result, "status", None)
    if status is None and isinstance(reconcile_result, dict):
        status = reconcile_result.get("status")
    status_val = status.value if hasattr(status, "value") else status
    if status_val in (None, "clean"):
        return {"snapshot_present": True, "cache_fresh": True, "drift_kinds": []}
    drift_raw = getattr(reconcile_result, "drift_kinds", None)
    if not drift_raw and isinstance(reconcile_result, dict):
        drift_raw = reconcile_result.get("drift_kinds")
    drift_list = [str(d) for d in (drift_raw or (status_val,))]
    drift = set(drift_list)
    # Only true capability DRIFT (not the snapshot/cache readiness kinds) keys
    # reconcile_clean; otherwise a missing-snapshot state would wrongly mark
    # drift cards clean.
    drift_only = [
        d
        for d in drift_list
        if d in ("new_capabilities", "removed_capabilities", "changed_capabilities")
    ]
    return {
        "snapshot_present": "missing_snapshot" not in drift,
        "cache_fresh": "stale_status_cache" not in drift,
        "drift_kinds": drift_only,
    }


def _capabilities_live_state(capability_envelope: Any | None) -> dict[str, str]:
    """Derive {capability_id -> status_string} from a capabilities StatusEnvelope
    for the capability_ready predicate (F004). Empty when no envelope."""
    if capability_envelope is None:
        return {}
    caps = getattr(capability_envelope, "capabilities", None)
    if caps is None and isinstance(capability_envelope, dict):
        caps = capability_envelope.get("capabilities", [])
    out: dict[str, str] = {}
    for cap in caps or ():
        cap_id = getattr(cap, "capability_id", None) or (
            cap.get("capability_id") if isinstance(cap, dict) else None
        )
        status = getattr(cap, "status", None) or (
            cap.get("status") if isinstance(cap, dict) else None
        )
        if cap_id is None or status is None:
            continue
        out[cap_id] = status.value if hasattr(status, "value") else str(status)
    return out


def _gather_skill_recommendation_items(
    plan_dirs_by_id: dict[str, Path],
    *,
    project_name: str | None = None,
) -> tuple[operator_console.ActionItem, ...]:
    """Build skill-recommendation ActionItems (F016 AC8/AC9) for each in-scope plan.

    Drives :func:`skill_recommendation.collect` per plan and converts the resulting
    report's ONE missing-input ActionChoice (+ shared dashboard affordance) via the
    F007 ``Guidance.to_action_items`` converter the report reuses, so the dashboard
    renders the SAME typed data the CLI prints. A plan whose skills are all ready
    yields no missing-input action and contributes nothing. Each plan is isolated in
    a try/except — a missing ``claude/skills`` dir or a malformed plan never sinks
    the cache (advisory; never blocks core use). Items are de-duplicated on the
    producer-set ``dedupe_key`` (CP-D002 identity authority), not the id-prefix.
    """
    from dontpanic_orchestrate import cli as _cli
    from dontpanic_orchestrate import skill_recommendation

    items: list[operator_console.ActionItem] = []
    seen_keys: set[str] = set()
    for _plan_id, plan_dir in plan_dirs_by_id.items():
        try:
            skills_dir = _cli._resolve_skills_dir(plan_dir)
            if skills_dir is None:
                continue
            report = skill_recommendation.collect(
                plan_dir, skills_dir, project=project_name
            )
            report_items = report.to_action_items()
        except Exception:  # noqa: BLE001 — advisory surface, never sinks the cache
            continue
        for item in report_items:
            if item.dedupe_key in seen_keys:
                continue
            seen_keys.add(item.dedupe_key)
            items.append(item)
    return tuple(items)


def _gather_operations_items(
    plan_dirs_by_id: dict[str, Path],
) -> tuple[operator_console.ActionItem, ...]:
    """Build operations-guidance ActionItems for each plan with a blocked state.

    Drives :func:`operations_guidance.collect_state` per plan AND per blocked
    feature, converting the resulting choices via ``Guidance.to_action_items``
    (F007 AC3). Finding 1: guidance must surface for the ACTUAL blocked feature(s)
    — ``blocked_feature_ids`` reads ``features.json`` so F007 (and any other
    in-flight feature) appears, not a hard-coded ``F001``. A plan/feature with no
    operational blockers yields no choices and contributes nothing. Each plan and
    feature is isolated in a try/except — a single malformed plan never sinks the
    cache. Items are de-duplicated on the producer-set ``dedupe_key`` (CP-D002
    identity authority), not the id-prefix (a plan-level blocker that surfaces
    under several features collapses to one ActionItem).
    """
    from dontpanic_orchestrate import operations_guidance

    items: list[operator_console.ActionItem] = []
    seen_keys: set[str] = set()
    # AC7d: when any guidance references the response-level dashboard affordance,
    # the affordance itself must be PRESENT in the cache (not just named in detail
    # text). Capture one affordance across all plans and append exactly one item.
    affordance: operations_guidance.DashboardAffordance | None = None
    for plan_id, plan_dir in plan_dirs_by_id.items():
        try:
            feature_ids = operations_guidance.blocked_feature_ids(plan_dir)
        except Exception:  # noqa: BLE001 — malformed features.json skipped
            feature_ids = ["F001"]
        for feature_id in feature_ids:
            try:
                guidance = operations_guidance.collect_state(
                    plan_dir, plan_id=plan_id, feature_id=feature_id
                )
            except Exception:  # noqa: BLE001 — malformed/blocked-read plans skipped
                continue
            if not guidance.choices:
                continue
            if guidance.affordance is not None and affordance is None:
                affordance = guidance.affordance
            try:
                feature_items = guidance.to_action_items()
            except Exception:  # noqa: BLE001
                continue
            for item in feature_items:
                if item.dedupe_key in seen_keys:
                    continue
                seen_keys.add(item.dedupe_key)
                items.append(item)
    # Append the single dashboard affordance item iff at least one operations
    # item referenced it (i.e. some choice required human input).
    if affordance is not None:
        try:
            hint = affordance.to_action_item()
        except Exception:  # noqa: BLE001
            hint = None
        if hint is not None and hint.dedupe_key not in seen_keys:
            seen_keys.add(hint.dedupe_key)
            items.append(hint)
    return tuple(items)


@dataclass(frozen=True)
class _GateView:
    plan_id: str
    gate_name: str
    kind: str
    reason: str | None


def _scope_envelope_to_v0_local(
    envelope: capabilities_status.StatusEnvelope | None,
    capability_index: capabilities.CapabilityIndex | None,
) -> capabilities_status.StatusEnvelope | None:
    """Drop capabilities whose category is out of scope for the V0 local console.

    The V0 dashboard is operator-local — realtime / remote-mirror
    adapters are an explicit non-goal. Surfacing their ``needs_setup``
    status as dashboard action work would violate V0 acceptance (4) by
    promoting remote-mirror adapter configuration into the operator's
    what-now queue. The operator-local capabilities cache still receives
    the full envelope (operators who opt into out-of-scope adapters
    still want that view from ``dontpanic capabilities status``); only
    the dashboard copy and the what-now action-item generator consume
    the scoped envelope.
    """

    if envelope is None or capability_index is None:
        return envelope
    excluded_ids = {
        m.id
        for m in capability_index.all
        if m.category in V0_DASHBOARD_EXCLUDED_CATEGORIES
    }
    if not excluded_ids:
        return envelope
    scoped = tuple(
        c for c in envelope.capabilities if c.capability_id not in excluded_ids
    )
    if len(scoped) == len(envelope.capabilities):
        return envelope
    return capabilities_status.StatusEnvelope(
        schema_version=envelope.schema_version,
        generated_at=envelope.generated_at,
        capabilities=scoped,
        advisory_notes=envelope.advisory_notes,
    )


def _classify_gate_kind(gate_name: str) -> str:
    if gate_name == "pre_impl":
        return "pre_impl"
    if gate_name == "pre_merge":
        return "pre_merge"
    if gate_name.startswith("breaker:"):
        return "breaker"
    if gate_name.startswith("defer:"):
        return "defer"
    return "custom"


# ── open: print URL/path, best-effort OS opener ─────────────────────────


def open_dashboard(
    *,
    build_report: BuildReport,
    dashboard_dir: Path | None = None,
    launch: bool = True,
    printer: Callable[[str], None] | None = None,
    opener: Callable[[Path], bool] | None = None,
) -> Path:
    """Print the local dashboard file path and best-effort launch the GUI.

    Returns the absolute path/URL that was printed. The path is printed
    even when ``launch=False`` or the OS opener is unavailable —
    acceptance item (2) is "prints a usable local URL/path"; the launch
    is bonus.
    """

    dashboard_dir = dashboard_dir if dashboard_dir is not None else default_dashboard_dir()
    printer = printer if printer is not None else (lambda msg: print(msg))
    index = dashboard_dir / "index.html"
    target = index if index.is_file() else dashboard_dir
    printer(f"dashboard: {target}")
    printer(f"  state:   {build_report.out_dir}")
    if build_report.what_now_cache_path:
        printer(f"  what-now: {build_report.what_now_cache_path}")
    if launch:
        opened = (opener or _default_opener)(target)
        if not opened:
            printer("  (GUI opener unavailable — path above is usable directly)")
    return target


def _default_opener(target: Path) -> bool:
    """Best-effort GUI hand-off. Returns True iff a launcher was spawned.

    Honors ``$BROWSER`` for explicit overrides, falls back to platform
    defaults (``open`` on macOS, ``xdg-open`` on Linux, ``start`` on
    Windows). Never raises — sandboxed / headless callers get False back.
    """

    try:
        target_str = str(target)
        env_browser = os.environ.get("BROWSER")
        if env_browser:
            subprocess.Popen(  # noqa: S603 — shell=False, args are operator $BROWSER + dashboard path
                [env_browser, target_str],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        system = platform.system()
        if system == "Darwin":
            cmd = ["open", target_str]
        elif system == "Windows":
            cmd = ["cmd", "/c", "start", "", target_str]
        else:
            cmd = ["xdg-open", target_str]
        subprocess.Popen(  # noqa: S603 — shell=False, OS opener with fixed cmd + dashboard path
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:  # noqa: BLE001 — best-effort opener; printer above already showed the path
        return False


# ── serve: localhost-only HTTP + watch loop ─────────────────────────────


def _is_loopback_host(host: str) -> bool:
    """True iff host string resolves to a loopback-only address.

    Rejects 0.0.0.0 / ::/0 outright; accepts 127.0.0.1, ::1, localhost,
    and any IP in the loopback range. Hostnames that resolve to anything
    other than a loopback IP are rejected — V0 console binds local by
    default and the only escape hatch is the explicit --allow-remote flag.
    """

    if host in LOCAL_LOOPBACK_ADDRESSES:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Hostname — resolve and verify every record is loopback.
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        if not infos:
            return False
        for info in infos:
            sockaddr = info[4]
            addr = sockaddr[0]
            try:
                if not ipaddress.ip_address(addr).is_loopback:
                    return False
            except ValueError:
                return False
        return True
    return ip.is_loopback


def _iter_plan_source_files(plans_root: Path) -> Iterator[Path]:
    """Yield plan-directory files whose edits should retrigger a rebuild.

    Enumerated via :data:`_PLAN_SOURCE_RELATIVE_GLOBS` rather than a
    blanket ``rglob('*')`` so we (a) skip irrelevant artifacts the
    operator/agents drop into a plan dir, and (b) reliably detect
    inline edits to existing files — relying on the plan-dir mtime
    alone misses those because most filesystems only bump parent-dir
    mtime on add/remove, not on inline file writes.
    """

    if not plans_root.exists() or not plans_root.is_dir():
        return
    for plan_dir in plans_root.iterdir():
        if not plan_dir.is_dir():
            continue
        for pattern in _PLAN_SOURCE_RELATIVE_GLOBS:
            yield from plan_dir.glob(pattern)


def _iter_static_dashboard_files(
    dashboard_dir: Path, *, excluded_dir: Path
) -> Iterator[Path]:
    """Walk the static dashboard tree, excluding the generated state dir.

    The generated state dir is written by every rebuild; including it in
    the watcher would create a self-trigger feedback loop.
    """

    if not dashboard_dir.exists() or not dashboard_dir.is_dir():
        return
    try:
        excluded_resolved = excluded_dir.resolve()
    except OSError:
        excluded_resolved = excluded_dir
    for path in dashboard_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved == excluded_resolved or excluded_resolved in resolved.parents:
            continue
        yield path


def _source_fingerprint(
    *, plans_root: Path, dashboard_dir: Path, state_out_dir: Path
) -> tuple[tuple[str, int, int], ...]:
    """Fingerprint watched sources so creates, edits, and deletes rebuild.

    A max-mtime-only watcher misses deletions: removing the newest source
    file can lower the max timestamp, so ``current > previous`` never
    fires. The serve loop needs file-set semantics, so it tracks
    relative path, mtime_ns, and size for every watched source while
    still excluding generated dashboard state.

    Also tracks the project registry at ``~/.dontpanic/projects.json``
    (F002 acceptance 5: a newly-added project surfaces in the served
    selector without manual restart). The registry path is enumerated
    via :func:`projects_registry.registry_path` so a missing file is
    still represented in the fingerprint when it later appears.
    """

    from dontpanic_orchestrate import projects_registry as pr

    entries: list[tuple[str, int, int]] = []
    entries.extend(
        _fingerprint_entries("plans", plans_root, _iter_plan_source_files(plans_root))
    )
    entries.extend(
        _fingerprint_entries(
            "dashboard",
            dashboard_dir,
            _iter_static_dashboard_files(dashboard_dir, excluded_dir=state_out_dir),
        )
    )
    # Registry file. Missing → ("absent", 0, 0) so the next presence
    # change registers as a fingerprint diff.
    reg_path = pr.registry_path()
    if reg_path.is_file():
        try:
            stat = reg_path.stat()
            entries.append(("registry/projects.json", stat.st_mtime_ns, stat.st_size))
        except OSError:
            entries.append(("registry/projects.json", 0, -1))
    else:
        entries.append(("registry/projects.json", 0, 0))
    return tuple(sorted(entries))


def _fingerprint_entries(
    root_name: str, root: Path, paths: Iterable[Path]
) -> Iterator[tuple[str, int, int]]:
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        yield (f"{root_name}/{rel.as_posix()}", stat.st_mtime_ns, stat.st_size)


class _SilentRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Quiet handler — keeps stderr clean during tests; logs only errors."""

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return


class _ReusableTCPServer(socketserver.TCPServer):
    """TCPServer that sets ``SO_REUSEADDR`` (like :class:`http.server.HTTPServer`).

    Without this, a fresh ``--replace`` serve on the SAME port a just-superseded
    server held can fail with ``EADDRINUSE`` while that port lingers in
    ``TIME_WAIT`` even though the old process has already exited (codex F010 i1).
    Reuse-address still REFUSES to bind a port with a live competing LISTEN
    socket, so the ordinary same-port conflict (AC6) still raises ``OSError``.
    """

    allow_reuse_address = True


def _make_server(
    *, host: str, port: int, directory: Path, bind_attempts: int = 1
) -> socketserver.TCPServer:
    """Construct a TCPServer rooted at ``directory``.

    Uses functools.partial-style binding via a thin subclass so the
    handler reaches the right cwd without changing the process cwd.

    ``bind_attempts`` > 1 retries the bind on ``OSError`` with a short backoff —
    used only when we have just superseded a live singleton (``--replace``) so
    the kernel has a brief window to release the old listener's socket before we
    claim the same port. With the default of 1 attempt an ordinary same-port
    conflict surfaces immediately (AC6).
    """

    dir_str = str(directory)

    def handler_factory(*args: Any, **kwargs: Any) -> _SilentRequestHandler:
        return _SilentRequestHandler(*args, directory=dir_str, **kwargs)

    attempts = max(1, bind_attempts)
    last_err: OSError | None = None
    for attempt in range(attempts):
        try:
            return _ReusableTCPServer((host, port), handler_factory)
        except OSError as err:
            last_err = err
            if attempt + 1 < attempts:
                time.sleep(_SUPERSEDE_POLL_INTERVAL_SECONDS)
    if last_err is None:
        # Unreachable: attempts >= 1, so a returned-or-raised path was taken above.
        raise RuntimeError(
            "dashboard server bind exhausted all attempts without an error"
        )
    raise last_err


@dataclass
class ServeHandle:
    """Returned by :func:`serve_start`. Tests use this to bind/teardown
    without parsing CLI output. ``shutdown()`` is safe to call twice."""

    server: socketserver.TCPServer
    host: str
    port: int
    directory: Path
    thread: threading.Thread | None = None
    watcher_stop: threading.Event | None = None
    watcher_thread: threading.Thread | None = None
    # Canonical DontPanic home whose serve-singleton record this handle owns, set
    # by serve_start so shutdown() can prune it (F013 AC2 detection primitive).
    singleton_dir: Path | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def shutdown(self) -> None:
        if self.singleton_dir is not None:
            _clear_singleton_record(self.singleton_dir)
        if self.watcher_stop is not None:
            self.watcher_stop.set()
        if self.watcher_thread is not None and self.watcher_thread.is_alive():
            self.watcher_thread.join(timeout=5)
        try:
            self.server.shutdown()
        except Exception:  # noqa: BLE001, S110 — server may already be torn down; nothing to recover
            pass
        try:
            self.server.server_close()
        except Exception:  # noqa: BLE001, S110 — socket close failure on already-closed handle
            pass
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=5)


def serve_start(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    dashboard_dir: Path | None = None,
    plans_root: Path | None = None,
    state_out_dir: Path | None = None,
    watch: bool = True,
    watch_interval: float = DEFAULT_WATCH_INTERVAL_SECONDS,
    allow_remote: bool = False,
    repo_root: Path | None = None,
    warn: Callable[[str], None] | None = None,
    project: str | None = None,
    replace: bool = False,
) -> ServeHandle:
    """Bind a localhost-only HTTP server and (optionally) start the watch
    loop. Returns immediately — tests/operator code can poll
    ``handle.url`` and ``handle.shutdown()`` when done.

    Raises ``ValueError`` if the supplied host is not loopback and
    ``allow_remote`` was not set.

    ``project`` controls which scope is served:
      * ``None`` (default) — resolves via :func:`projects_dashboard.resolve_selection`
        (cwd-match, then single-project default, else ``all`` or current
        repo). This matches ``dashboard build``'s default behavior.
      * ``"all"`` — serve the fleet view.
      * registry project name — serve that one project. The fleet
        summary still surfaces every registered project so the selector
        UI in F003 can render them all.

    Raises :class:`projects_dashboard.UnknownProjectError` for an
    unknown name so the CLI can fail loud before binding the socket.
    """

    if not allow_remote and not _is_loopback_host(host):
        raise ValueError(
            f"host={host!r} is not loopback; refusing to bind. "
            "Pass --allow-remote (CLI) or allow_remote=True (lib) to override; "
            "V0 console binds local-only by default."
        )

    dashboard_dir = dashboard_dir if dashboard_dir is not None else default_dashboard_dir()
    plans_root = plans_root if plans_root is not None else default_plans_root()
    state_out_dir = state_out_dir if state_out_dir is not None else (dashboard_dir / DEFAULT_STATE_SUBDIR_NAME)
    warn = warn if warn is not None else (lambda _msg: None)

    # F010 AC1/AC2/AC3 — singleton guard, keyed by the canonical DontPanic HOME
    # (NOT the served dashboard_dir / cwd). Keying by the home is what enforces
    # "one dashboard server per DontPanic home": a second serve launched from a
    # different working directory or --dashboard-dir against the SAME home still
    # resolves the same singleton and is refused. detect_active_dashboard prunes a
    # stale (dead-pid) record as a side effect, so a crashed serve never blocks a
    # fresh one (AC2). A LIVE record refuses the second serve (AC1) unless the
    # caller asked to supersede it, in which case we SIGTERM the old process and
    # clear the record before binding our own (AC3). This runs BEFORE the initial
    # build and socket bind so a refused serve does no work.
    singleton_home = global_config.dontpanic_home()
    existing = detect_active_dashboard(singleton_home)
    just_superseded = False
    if existing is not None:
        existing_url = existing.get("url") if isinstance(existing, dict) else None
        if not replace:
            raise DashboardAlreadyRunningError(
                url=existing_url,
                home=singleton_home,
                project=existing.get("project") if isinstance(existing, dict) else None,
            )
        existing_pid = existing.get("pid") if isinstance(existing, dict) else None
        if isinstance(existing_pid, int) and existing_pid == os.getpid():
            # Same-process replace cannot stop the old in-process server (we never
            # SIGTERM ourselves), so silently clearing the record would leave two
            # live servers. Refuse honestly instead (F010 fix#2).
            raise SameProcessReplaceError(url=existing_url, home=singleton_home)
        _supersede_existing_singleton(singleton_home, existing)
        just_superseded = True

    # Always run an initial build so the first request sees fresh data.
    # Resolves --project up-front so an unknown name raises before we
    # bind the socket (operators don't want a server they then have to
    # tear down because of a typo).
    from dontpanic_orchestrate import projects_dashboard

    initial_result = projects_dashboard.build_selected(
        project,
        plans_root=plans_root,
        out_dir=state_out_dir,
        repo_root=repo_root,
        warn=warn,
    )
    if initial_result.selection.kind != "current_repo":
        projects_dashboard.mirror_selection_into_state_dir(
            initial_result, state_out_dir=state_out_dir
        )

    # When we just superseded a live singleton, the old process has exited but
    # the kernel may still be releasing its listener socket; retry the bind for a
    # short window (reuse-address absorbs TIME_WAIT). A normal serve uses a single
    # attempt so an ordinary same-port conflict surfaces immediately (AC6).
    bind_attempts = (
        int(_SUPERSEDE_TIMEOUT_SECONDS / _SUPERSEDE_POLL_INTERVAL_SECONDS)
        if just_superseded
        else 1
    )
    server = _make_server(
        host=host, port=port, directory=dashboard_dir, bind_attempts=bind_attempts
    )
    bound_host, bound_port = server.server_address[:2]

    serve_thread = threading.Thread(
        target=server.serve_forever,
        name="dontpanic-dashboard-serve",
        daemon=True,
    )
    serve_thread.start()

    handle = ServeHandle(
        server=server,
        host=str(bound_host),
        port=int(bound_port),
        directory=dashboard_dir,
        thread=serve_thread,
        singleton_dir=singleton_home,
    )

    # Record the live serve singleton under the canonical DontPanic home so config
    # inventory / operations guidance auto-detect this URL for the dashboard hint
    # (F013 AC2) regardless of cwd. Best-effort: a recording failure must never
    # sink a successfully-bound server.
    try:
        _write_singleton_record(
            home=singleton_home,
            host=handle.host,
            port=handle.port,
            url=handle.url,
            project=project,
        )
        # The initial build above ran BEFORE the singleton existed, so its
        # config-inventory.json fell back to the start command. Re-render it now
        # that the server is live, passing the freshly-bound URL so the FIRST
        # served inventory the dashboard loads shows its own active_url (F013
        # AC2) regardless of which dashboard_dir is served.
        #
        # Keep the focused project's SCOPE (not None) so a served project
        # dashboard's top-level inventory isn't silently rebuilt at machine
        # scope (codex F013 i1). A fleet ("all") / current-repo selection has no
        # single focused project, so it stays machine-scoped (write_config_inventory
        # falls back to None on an unresolved selector anyway).
        focused_project = (
            initial_result.selection.project_name
            if initial_result.selection.kind == "project"
            else None
        )
        write_config_inventory(
            out_dir=state_out_dir,
            project_name=focused_project,
            dashboard_url=handle.url,
            warn=warn,
        )
        # The per-project mirror (state/projects/<name>/config-inventory.json)
        # was written during the initial build, also before the singleton — so
        # its hint fell back to the start command. The dashboard UI loads that
        # mirror when the focused project is selected, so re-render it with the
        # live URL too, keeping active-url detection on the per-project path.
        if focused_project is not None:
            project_state_dir = state_out_dir / "projects" / focused_project
            if project_state_dir.is_dir():
                write_config_inventory(
                    out_dir=project_state_dir,
                    project_name=focused_project,
                    dashboard_url=handle.url,
                    warn=warn,
                )
    except Exception as exc:  # noqa: BLE001 — recording is advisory
        warn(f"dashboard singleton record skipped: {exc}")

    if watch:
        stop_event = threading.Event()
        handle.watcher_stop = stop_event
        watcher = threading.Thread(
            target=_watch_loop,
            kwargs={
                "stop_event": stop_event,
                "interval": watch_interval,
                "plans_root": plans_root,
                "dashboard_dir": dashboard_dir,
                "state_out_dir": state_out_dir,
                "repo_root": repo_root,
                "warn": warn,
                "project": project,
            },
            name="dontpanic-dashboard-watch",
            daemon=True,
        )
        watcher.start()
        handle.watcher_thread = watcher

    return handle


def _watch_loop(
    *,
    stop_event: threading.Event,
    interval: float,
    plans_root: Path,
    dashboard_dir: Path,
    state_out_dir: Path,
    repo_root: Path | None,
    warn: Callable[[str], None],
    project: str | None = None,
) -> None:
    """Polling rebuild loop. Polling beats inotify here because the V0
    sources span $HOME (capability cache, install snapshot) and the repo,
    and the operator-facing latency is ``watch_interval`` seconds — well
    inside human reaction time.

    Re-enters :func:`projects_dashboard.build_selected` each tick so
    registry edits (a new ``dontpanic projects add``) surface in the
    served fleet summary without a manual server restart. An unknown
    project name supplied at server start has already been rejected by
    :func:`serve_start`; a project that *vanishes* from the registry
    while the server is running degrades gracefully by falling back to
    default resolution and logging a warning.
    """

    from dontpanic_orchestrate import projects_dashboard

    last_fingerprint = _source_fingerprint(
        plans_root=plans_root,
        dashboard_dir=dashboard_dir,
        state_out_dir=state_out_dir,
    )
    while not stop_event.is_set():
        if stop_event.wait(timeout=interval):
            return
        # Re-enumerate each tick so newly-added plan source files (and
        # newly-created plan dirs / project registry edits) are picked
        # up without restart.
        current = _source_fingerprint(
            plans_root=plans_root,
            dashboard_dir=dashboard_dir,
            state_out_dir=state_out_dir,
        )
        if current != last_fingerprint:
            try:
                effective_project = project
                try:
                    result = projects_dashboard.build_selected(
                        effective_project,
                        plans_root=plans_root,
                        out_dir=state_out_dir,
                        repo_root=repo_root,
                        warn=warn,
                    )
                except projects_dashboard.UnknownProjectError as exc:
                    # The previously-known project was removed from the
                    # registry mid-run. Degrade to default selection.
                    warn(
                        f"project {project!r} no longer registered; "
                        f"falling back to default selection ({exc})"
                    )
                    result = projects_dashboard.build_selected(
                        None,
                        plans_root=plans_root,
                        out_dir=state_out_dir,
                        repo_root=repo_root,
                        warn=warn,
                    )
                if result.selection.kind != "current_repo":
                    projects_dashboard.mirror_selection_into_state_dir(
                        result, state_out_dir=state_out_dir
                    )
            except Exception as exc:  # noqa: BLE001
                warn(f"watch rebuild failed: {exc}")
            # Re-baseline AFTER the build using a fresh enumeration so
            # the rebuild's own writes to state_out_dir cannot register
            # as "new" work on the next tick. _source_fingerprint
            # excludes state_out_dir, so the baseline here only reflects
            # sources.
            last_fingerprint = _source_fingerprint(
                plans_root=plans_root,
                dashboard_dir=dashboard_dir,
                state_out_dir=state_out_dir,
            )


# ── argparse + main ─────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    # F005: human-handoff agent-guidance footer, projected from the F002
    # inventory so the help points agents at this local decision surface when
    # DontPanic requires a human decision or visual inspection.
    from dontpanic_orchestrate import command_guidance

    parser = argparse.ArgumentParser(
        prog="dontpanic dashboard",
        description=(
            "Local-first operator console. "
            "`build` exports state + caches to dashboard/state. "
            "`open` builds and prints the local URL/path. "
            "`serve` binds localhost-only with file-watch refresh."
        ),
        epilog=command_guidance.command_help_agent_snippet("dashboard"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="subcommand")

    common_build = argparse.ArgumentParser(add_help=False)
    common_build.add_argument(
        "--plans-root",
        default=None,
        help="Plans directory (default: <cwd>/docs/plans).",
    )
    common_build.add_argument(
        "--out",
        dest="out_dir",
        default=None,
        help="Output directory (default: <cwd>/dashboard/state).",
    )
    common_build.add_argument(
        "--redact-level",
        choices=("public", "operator", "full"),
        default="operator",
    )
    common_build.add_argument(
        "--plan",
        dest="plan_id",
        default=None,
        help="Restrict state export + action items to one plan id.",
    )
    common_build.add_argument(
        "--project",
        dest="project",
        default=None,
        help=(
            "Project to build (`all` for the fleet, or a registered project "
            "name from `dontpanic projects list`). When omitted, the default "
            "is the cwd-matched project if cwd is inside one, otherwise "
            "`all` when more than one project is registered, otherwise the "
            "current-repo single-project mode."
        ),
    )

    sub.add_parser(
        "build",
        parents=[common_build],
        help=(
            "Compose state-snapshot + capabilities cache + reconcile + "
            "architecture + what-now cache into the dashboard state dir. "
            "Pass --project to switch between fleet and per-project builds."
        ),
    )

    open_parser = sub.add_parser(
        "open",
        parents=[common_build],
        help=(
            "Run `build` then print the local dashboard URL/path. "
            "Best-effort GUI launch; sandbox/headless prints the path only."
        ),
    )
    open_parser.add_argument(
        "--dashboard-dir",
        default=None,
        help="Static dashboard root (default: <cwd>/dashboard).",
    )
    open_parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Do not attempt to launch a GUI opener; just print the path.",
    )

    serve_parser = sub.add_parser(
        "serve",
        help=(
            "Bind a localhost-only HTTP server in dashboard/ with file-watch "
            "refresh. Operator-local by default; --allow-remote required to "
            "bind a non-loopback host."
        ),
    )
    serve_parser.add_argument("--host", default=DEFAULT_HOST)
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve_parser.add_argument(
        "--dashboard-dir",
        default=None,
        help="Static dashboard root (default: <cwd>/dashboard).",
    )
    serve_parser.add_argument(
        "--plans-root",
        default=None,
        help="Plans directory (default: <cwd>/docs/plans).",
    )
    serve_parser.add_argument(
        "--state-out",
        dest="state_out_dir",
        default=None,
        help="Where build writes state files (default: <dashboard>/state).",
    )
    serve_parser.add_argument(
        "--watch-interval",
        type=float,
        default=DEFAULT_WATCH_INTERVAL_SECONDS,
        help=f"Polling interval seconds (default: {DEFAULT_WATCH_INTERVAL_SECONDS}).",
    )
    serve_parser.add_argument(
        "--no-watch",
        action="store_true",
        help="Build once and serve without polling for changes.",
    )
    serve_parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "Build + bind + print URL + immediately shut down. Used by "
            "tests and operator dry-runs to confirm the server is wired."
        ),
    )
    serve_parser.add_argument(
        "--allow-remote",
        action="store_true",
        help=(
            "Permit a non-loopback host. V0 console binds local-only by "
            "default; this flag exists strictly for explicit operator opt-in."
        ),
    )
    serve_parser.add_argument(
        "--project",
        dest="project",
        default=None,
        help=(
            "Project to serve (`all` for the fleet, or a registered project "
            "name from `dontpanic projects list`). Defaults match "
            "`dashboard build`: cwd-match if applicable, else `all` for "
            "multi-project registries, else current-repo single-project."
        ),
    )
    serve_parser.add_argument(
        "--replace",
        "--force-single",
        dest="replace",
        action="store_true",
        help=(
            "Supersede an existing live dashboard serving the same home — stop "
            "it and take over — instead of refusing. Use this to recover when a "
            "previous serve is still holding the singleton for this home."
        ),
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.subcommand is None:
        parser.print_help(sys.stderr)
        return 2

    if args.subcommand == "build":
        return _build_main(args)
    if args.subcommand == "open":
        return _open_main(args)
    if args.subcommand == "serve":
        return _serve_main(args)
    parser.print_help(sys.stderr)
    return 2


def _build_main(args: argparse.Namespace) -> int:
    # Late import — projects_dashboard imports dashboard at module load,
    # so a top-level import would deadlock during module init.
    from dontpanic_orchestrate import projects_dashboard

    plans_root = Path(args.plans_root) if args.plans_root else default_plans_root()
    out_dir = Path(args.out_dir) if args.out_dir else default_state_out_dir()
    requested = getattr(args, "project", None)

    def _warn(msg: str) -> None:
        print(f"dashboard build: {msg}", file=sys.stderr)

    try:
        result = projects_dashboard.build_selected(
            requested,
            plans_root=plans_root,
            out_dir=out_dir,
            redact_level=args.redact_level,
            plan_id=args.plan_id,
            warn=_warn,
        )
    except projects_dashboard.UnknownProjectError as exc:
        print(f"dashboard build: {exc}", file=sys.stderr)
        return 2

    if result.selection.kind == "current_repo":
        report = result.current_repo_report
        assert report is not None
        print(f"wrote {len(report.state_files)} state files to {report.out_dir}")
        if report.what_now_cache_path:
            print(f"wrote what-now cache to {report.what_now_cache_path}")
        if report.capability_cache_path:
            print(f"wrote capabilities cache to {report.capability_cache_path}")
        if report.reconcile_status_path:
            print(f"wrote reconcile status to {report.reconcile_status_path}")
        if report.architecture_status_path:
            print(f"wrote architecture status to {report.architecture_status_path}")
        return 0

    # Project-scoped build (kind == "project" or "all"). Mirror into the
    # served state dir so the static dashboard finds fleet-summary +
    # per-project state without leaking absolute $HOME paths.
    projects_dashboard.mirror_selection_into_state_dir(
        result, state_out_dir=out_dir
    )
    selection = result.selection
    # F013 (codex F013 i2): the fleet/project BUILD path must also write the
    # top-level config-inventory.json — the dashboard defaults its selection to
    # `all`, whose resolveConfigInventory() reads only the top-level file, so
    # without this the default All-Projects view renders an EMPTY Settings
    # inventory. Mirror the serve path: top-level scoped to the focused project
    # (None for `all` → machine-only), plus the per-project mirror when focused.
    focused_project = (
        selection.project_name if selection.kind == "project" else None
    )
    write_config_inventory(out_dir=out_dir, project_name=focused_project, warn=_warn)
    if focused_project is not None:
        project_state_dir = out_dir / "projects" / focused_project
        if project_state_dir.is_dir():
            write_config_inventory(
                out_dir=project_state_dir,
                project_name=focused_project,
                warn=_warn,
            )
    if selection.is_default:
        print(f"dashboard build: defaulted to {_format_selection(selection)} ({selection.reason})")
    else:
        print(f"dashboard build: scope {_format_selection(selection)}")
    print(f"wrote fleet summary to {result.fleet_summary_path}")
    for r in result.project_reports:
        if r.skipped:
            continue
        print(
            f"wrote project {r.context.name!r} state to {r.context.dashboard_cache_path}"
        )
    return 0


def _format_selection(selection: Any) -> str:
    """Human-readable label for a :class:`projects_dashboard.ResolvedSelection`."""

    if selection.kind == "all":
        return "All Projects"
    if selection.kind == "project":
        return f"project {selection.project_name!r}"
    return "current repo"


def _open_main(args: argparse.Namespace) -> int:
    from dontpanic_orchestrate import projects_dashboard

    plans_root = Path(args.plans_root) if args.plans_root else default_plans_root()
    out_dir = Path(args.out_dir) if args.out_dir else default_state_out_dir()
    dashboard_dir = (
        Path(args.dashboard_dir) if args.dashboard_dir else default_dashboard_dir()
    )
    requested = getattr(args, "project", None)

    def _warn(msg: str) -> None:
        print(f"dashboard open: {msg}", file=sys.stderr)

    try:
        result = projects_dashboard.build_selected(
            requested,
            plans_root=plans_root,
            out_dir=out_dir,
            redact_level=args.redact_level,
            plan_id=args.plan_id,
            warn=_warn,
        )
    except projects_dashboard.UnknownProjectError as exc:
        print(f"dashboard open: {exc}", file=sys.stderr)
        return 2

    # ``open_dashboard`` only needs the dashboard dir + a BuildReport for
    # the path/what-now-cache lines it prints. For project-scoped builds
    # we synthesize a minimal BuildReport pointing at the mirrored state
    # so the displayed paths are accurate.
    if result.selection.kind == "current_repo":
        report = result.current_repo_report
        assert report is not None
    else:
        projects_dashboard.mirror_selection_into_state_dir(
            result, state_out_dir=out_dir
        )
        report = BuildReport(
            out_dir=out_dir,
            state_files=(),
            what_now_cache_path=None,
            capability_cache_path=None,
            reconcile_status_path=None,
            architecture_status_path=None,
            warnings=(),
        )

    launch = not args.no_launch and _gui_launch_is_safe()
    open_dashboard(
        build_report=report,
        dashboard_dir=dashboard_dir,
        launch=launch,
    )
    return 0


def _gui_launch_is_safe() -> bool:
    """Cheap heuristic for "are we headless/sandboxed".

    Skips GUI launch when stdout is not a tty (CI / piped output) and on
    common CI/sandbox env vars. The path is still printed; this only
    decides whether to spawn an opener subprocess.
    """

    if not sys.stdout.isatty():
        return False
    for env_var in ("CI", "GITHUB_ACTIONS", "DONTPANIC_HEADLESS"):
        if os.environ.get(env_var):
            return False
    return True


def _serve_main(args: argparse.Namespace) -> int:
    from dontpanic_orchestrate import projects_dashboard

    plans_root = Path(args.plans_root) if args.plans_root else default_plans_root()
    dashboard_dir = (
        Path(args.dashboard_dir) if args.dashboard_dir else default_dashboard_dir()
    )
    state_out_dir = (
        Path(args.state_out_dir)
        if args.state_out_dir
        else dashboard_dir / DEFAULT_STATE_SUBDIR_NAME
    )
    requested = getattr(args, "project", None)

    def _warn(msg: str) -> None:
        print(f"dashboard serve: {msg}", file=sys.stderr)

    try:
        handle = serve_start(
            host=args.host,
            port=args.port,
            dashboard_dir=dashboard_dir,
            plans_root=plans_root,
            state_out_dir=state_out_dir,
            watch=not args.no_watch,
            watch_interval=args.watch_interval,
            allow_remote=args.allow_remote,
            warn=_warn,
            project=requested,
            replace=getattr(args, "replace", False),
        )
    except DashboardAlreadyRunningError as exc:
        # F010 AC1 — refuse the second serve with an actionable message: the
        # existing URL to open, or how to take over.
        loc = exc.url or exc.home
        print(
            f"dashboard serve: REFUSED: a dashboard is already running for this "
            f"home at {loc}. Open it in your browser, or pass --replace "
            f"(alias --force-single) to stop it and serve here instead.",
            file=sys.stderr,
        )
        return 2
    except projects_dashboard.UnknownProjectError as exc:
        print(f"dashboard serve: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"dashboard serve: REFUSED: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"dashboard serve: bind failed: {exc}", file=sys.stderr)
        return 1

    print(f"dashboard serving at {handle.url}")
    print(f"  directory: {handle.directory}")
    print(f"  state:     {state_out_dir}")
    if not args.no_watch:
        print(f"  watch interval: {args.watch_interval}s")
    print("ctrl-c to stop")

    if args.once:
        handle.shutdown()
        return 0

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\ndashboard serve: stopping")
    finally:
        handle.shutdown()
    return 0


__all__ = [
    "BuildReport",
    "DEFAULT_DASHBOARD_DIR_NAME",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_STATE_SUBDIR_NAME",
    "DEFAULT_WATCH_INTERVAL_SECONDS",
    "DASHBOARD_START_COMMAND",
    "DashboardAlreadyRunningError",
    "DashboardStatus",
    "LOCAL_LOOPBACK_ADDRESSES",
    "ServeHandle",
    "V0_DASHBOARD_EXCLUDED_CATEGORIES",
    "build",
    "build_parser",
    "dashboard_status",
    "default_dashboard_dir",
    "default_plans_root",
    "default_state_out_dir",
    "detect_active_dashboard",
    "detect_active_url",
    "local_what_now_cache_path",
    "main",
    "open_dashboard",
    "render_dashboard_hint_once",
    "render_hint_line",
    "serve_start",
    "write_config_inventory",
    "write_skill_recommendations",
]
