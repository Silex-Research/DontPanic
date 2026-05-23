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
    capabilities,
    capabilities_status,
    global_config,
    operator_console,
    plan_loader,
    reconcile,
    state_projection,
)
from dontpanic_orchestrate import gate_pause as _gp

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
            )
            (out_dir / "what-now.json").write_text(
                operator_console.render_json(items),
                encoding="utf-8",
            )
            what_now_cache_path = operator_console.write_cache(
                items,
                path=what_now_cache_path_override,
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"what-now cache skipped: {exc}"
            warnings.append(msg)
            warn(msg)

    return BuildReport(
        out_dir=out_dir,
        state_files=tuple(state_files),
        what_now_cache_path=what_now_cache_path,
        capability_cache_path=capability_cache_path,
        reconcile_status_path=reconcile_status_path,
        architecture_status_path=architecture_status_path,
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
) -> tuple[operator_console.ActionItem, ...]:
    """Drive each provider against already-loaded inputs."""

    # Gates: walk plans_root, reuse gate_pause.unmet_gates so we surface
    # the same set state_projection does.
    gate_inputs: list[Any] = []
    plan_dirs_by_id: dict[str, Path] = {}
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
            declared = list(loaded.plan.human_gates or [])
            if not declared:
                continue
            unmet = _gp.unmet_gates(loaded.plan_dir, declared)
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

    return operator_console.aggregate(
        gate_items, capability_items, reconcile_items, supervisor_items, arch_items
    )


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


def _make_server(
    *, host: str, port: int, directory: Path
) -> socketserver.TCPServer:
    """Construct a TCPServer rooted at ``directory``.

    Uses functools.partial-style binding via a thin subclass so the
    handler reaches the right cwd without changing the process cwd.
    """

    dir_str = str(directory)

    def handler_factory(*args: Any, **kwargs: Any) -> _SilentRequestHandler:
        return _SilentRequestHandler(*args, directory=dir_str, **kwargs)

    return socketserver.TCPServer((host, port), handler_factory)


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

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def shutdown(self) -> None:
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

    server = _make_server(host=host, port=port, directory=dashboard_dir)
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
    )

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
    parser = argparse.ArgumentParser(
        prog="dontpanic dashboard",
        description=(
            "Local-first operator console. "
            "`build` exports state + caches to dashboard/state. "
            "`open` builds and prints the local URL/path. "
            "`serve` binds localhost-only with file-watch refresh."
        ),
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
        )
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
    "LOCAL_LOOPBACK_ADDRESSES",
    "ServeHandle",
    "V0_DASHBOARD_EXCLUDED_CATEGORIES",
    "build",
    "build_parser",
    "default_dashboard_dir",
    "default_plans_root",
    "default_state_out_dir",
    "local_what_now_cache_path",
    "main",
    "open_dashboard",
    "serve_start",
]
