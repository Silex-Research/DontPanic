"""Plan 2026-05-23-005 F001 — multi-repo dashboard substrate.

This module is the per-project / fleet-level extension of the existing
single-repo dashboard (``dontpanic_orchestrate.dashboard``). It exposes:

  * :class:`ProjectContext` — a projection of one registered project
    plus its derived dashboard cache + artifact paths. Computed at
    build time from a :class:`projects_registry.ProjectEntry`; never
    persisted. ``ProjectEntry.name`` remains the stable identity.
  * :func:`build_project_state` — writes per-project dashboard state
    (state-snapshot + per-stream files + what-now + capabilities +
    reconcile + architecture-status + build-warnings) directly into the
    operator-local cache (``~/.dontpanic/dashboard/projects/<name>/``,
    flat layout per plan §Data Shape). No file lands in the target repo
    by construction — every write target is rooted at
    :func:`global_config.dontpanic_home`. Per-project builds also
    redirect the operator-global capabilities-status.json and
    what-now.json caches into the project's own cache dir so a fleet
    build cannot last-project-wins the single-repo global caches.
  * :func:`build_fleet_summary` — generates
    ``~/.dontpanic/dashboard/fleet-summary.json`` with one entry per
    registered project (health rollup band, data age, warning count,
    cache paths). Inactive projects are still included but flagged so
    the UI can render them muted; the rollup itself skips them.

Single-repo behavior is preserved: callers that do not pass a registry
(or whose registry is empty) keep using the existing
``dashboard.build()`` surface unchanged. This module never imports the
single-repo build's CLI; it composes its public helpers.

Acceptance items handled here (F001):
  (1) registry stable name — :func:`load_project_contexts` keys by
      :attr:`projects_registry.ProjectEntry.name`.
  (2) generated state never lands in the target repo — every write
      target is derived from :func:`global_config.dontpanic_home`.
  (3) fleet summary exists — :func:`build_fleet_summary` writes
      ``fleet-summary.json``.
  (4) zero-state fallback — when the registry is empty, callers
      retain the single-repo dashboard.build() behavior; this module
      is opt-in.
  (5) legacy registry compatibility — old entries without optional
      dashboard fields (``display_name`` / ``profile`` / ``active`` /
      ``dontpanic_version``) load via the additive Pydantic model.
  (6) same-version assumption — fleet summary stamps the operator's
      installed DontPanic version once at the envelope level.
  (7) no-secret output — every JSON write goes through
      :func:`operator_console._assert_no_secret_shapes` so cache
      leakage is impossible.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import (
    architecture,
    dashboard,
    global_config,
    operator_console,
    project_config,
    projects_registry,
)

_LOG = logging.getLogger(__name__)

PROJECTS_DASHBOARD_SUBDIR = "dashboard/projects"
"""Per-project cache root under ``~/.dontpanic/``."""

FLEET_SUMMARY_FILENAME = "fleet-summary.json"
"""Cache filename for the All-Projects rollup."""

FLEET_SUMMARY_SCHEMA_VERSION = "1.0.0"
"""Schema version for the fleet summary envelope. Bump only on
breaking shape changes — the dashboard reads this to refuse a stale
cache loudly instead of mis-rendering it."""

BUILD_WARNINGS_FILENAME = "build-warnings.json"
"""Per-project dashboard build warnings cache. Lets the UI surface
malformed or skipped artifacts without making the operator scrape
stderr."""


# ── ProjectContext projection ────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectContext:
    """Projection of one registered project at dashboard-build time.

    Built from a :class:`projects_registry.ProjectEntry` plus the
    project's per-project config (``plans_dir`` only, no other fields
    leak into the dashboard). Never persisted — the registry is the
    source of truth.

    ``name`` is the stable identity (same string as
    :attr:`projects_registry.ProjectEntry.name`). All path fields are
    absolute. ``repo_root`` may not exist on disk if the operator
    deleted the directory after registering it; callers must handle
    that explicitly (see :func:`build_project_state` warnings).
    """

    name: str
    display_name: str
    repo_root: Path
    plans_root: Path
    architecture_path: Path
    dashboard_cache_path: Path
    profile: str | None = None
    active: bool = True
    dontpanic_version: str | None = None
    last_used_at: str | None = None


def project_dashboard_dir(name: str) -> Path:
    """Operator-local cache directory for one project.

    ``~/.dontpanic/dashboard/projects/<name>/`` — never touches the
    registered repo. Honors ``$DONTPANIC_HOME`` / ``$JARVIS_HOME`` via
    :func:`global_config.dontpanic_home`.
    """

    return global_config.dontpanic_home() / PROJECTS_DASHBOARD_SUBDIR / name


def fleet_summary_path() -> Path:
    """Operator-local fleet summary cache path."""

    return global_config.dontpanic_home() / "dashboard" / FLEET_SUMMARY_FILENAME


def project_context_from_entry(entry: projects_registry.ProjectEntry) -> ProjectContext:
    """Project the registry entry into a build-time :class:`ProjectContext`.

    Reads the per-project config (when present) only to discover
    ``plans_dir``. No other per-project config fields leak into the
    projection; they remain owned by the supervisor/dispatcher.

    ``display_name`` defaults to ``entry.name`` when unset so the UI
    always has something to render. ``active`` defaults to True when the
    field is absent so legacy registry files (pre-F001) keep behaving as
    fully-active projects.
    """

    repo_root = Path(entry.path).expanduser().resolve()
    cfg = None
    if repo_root.is_dir():
        # Only consult the per-project config when the repo still
        # exists. A missing dir is the operator's problem; we record
        # the projection regardless and let the build step surface
        # the warning.
        cfg = project_config.load_project_config(repo_root)
    plans_rel = (cfg.plans_dir if cfg is not None else None) or project_config.DEFAULT_PLANS_DIR
    plans_root = (repo_root / plans_rel).resolve()
    arch_path = (repo_root / architecture.DEFAULT_OUTPUT_REL).resolve()
    cache_path = project_dashboard_dir(entry.name)

    return ProjectContext(
        name=entry.name,
        display_name=entry.display_name or entry.name,
        repo_root=repo_root,
        plans_root=plans_root,
        architecture_path=arch_path,
        dashboard_cache_path=cache_path,
        profile=entry.profile,
        # Legacy entries (active absent) are treated as active.
        active=True if entry.active is None else bool(entry.active),
        dontpanic_version=entry.dontpanic_version,
        last_used_at=entry.last_used_at,
    )


def load_project_contexts() -> list[ProjectContext]:
    """Return one ProjectContext per registered project (registry order).

    Empty when no registry exists — the caller falls back to single-repo
    behavior. Never raises; a malformed registry yields an empty list
    via the load_registry warn-and-empty contract.
    """

    reg = projects_registry.load_registry()
    return [project_context_from_entry(e) for e in reg.projects]


# ── per-project build ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectBuildReport:
    """Summary of one :func:`build_project_state` call.

    Mirrors the shape of :class:`dashboard.BuildReport` plus the
    project context the build was scoped to, and the build-warnings
    cache path. The fleet summary aggregator consumes this.
    """

    context: ProjectContext
    build_report: dashboard.BuildReport | None
    build_warnings_path: Path
    warnings: tuple[str, ...] = field(default_factory=tuple)
    skipped: bool = False
    skipped_reason: str | None = None


def build_project_state(
    context: ProjectContext,
    *,
    redact_level: str = "operator",
    warn: Callable[[str], None] | None = None,
) -> ProjectBuildReport:
    """Build one project's dashboard state into the operator-local cache.

    The output directory is always rooted at
    :func:`global_config.dontpanic_home` — by construction no generated
    file lands inside the target repo. We compose
    :func:`dashboard.build` with the project's plans_root and repo_root,
    then write a small ``build-warnings.json`` sibling so the dashboard
    UI can surface skipped/malformed artifacts.

    Returns even when the underlying repo no longer exists or the build
    itself fails — the report's ``skipped`` flag / ``warnings`` tuple
    tells the fleet aggregator what to render.
    """

    warn = warn if warn is not None else (lambda _msg: None)
    warnings: list[str] = []

    out_dir = context.dashboard_cache_path
    out_dir.mkdir(parents=True, exist_ok=True)
    # Plan §Data Shape: per-project files (state-snapshot.json,
    # what-now.json, capabilities-required.json, …) sit directly under
    # the project's cache dir. No nested ``state/`` subdir.
    state_out_dir = out_dir

    if not context.repo_root.is_dir():
        msg = f"repo_root does not exist: {context.repo_root}"
        warnings.append(msg)
        warn(msg)
        warnings_path = _write_build_warnings(
            out_dir, context=context, warnings=warnings, skipped=True
        )
        return ProjectBuildReport(
            context=context,
            build_report=None,
            build_warnings_path=warnings_path,
            warnings=tuple(warnings),
            skipped=True,
            skipped_reason="repo_root missing",
        )

    if not context.active:
        msg = f"project {context.name!r} is inactive — skipped"
        warnings.append(msg)
        warn(msg)
        warnings_path = _write_build_warnings(
            out_dir, context=context, warnings=warnings, skipped=True
        )
        return ProjectBuildReport(
            context=context,
            build_report=None,
            build_warnings_path=warnings_path,
            warnings=tuple(warnings),
            skipped=True,
            skipped_reason="inactive",
        )

    build_report: dashboard.BuildReport | None = None
    try:
        # Redirect operator-global cache writes into the project's own
        # cache directory so per-project builds (and fleet builds) do
        # not last-project-wins the single-repo global caches at
        # ``~/.dontpanic/capabilities-status.json`` and
        # ``~/.dontpanic/dashboard/what-now.json``. The static dashboard
        # copies under ``state_out_dir`` are already project-scoped.
        build_report = dashboard.build(
            plans_root=context.plans_root,
            out_dir=state_out_dir,
            redact_level=redact_level,
            repo_root=context.repo_root,
            # dashboard.build already returns every warning in
            # BuildReport.warnings. Forward to the caller for terminal
            # visibility, but do not append here or build-warnings.json
            # and fleet warning_count double-count each message.
            warn=warn,
            capabilities_cache_path=out_dir / "capabilities-required.json",
            what_now_cache_path_override=out_dir / "what-now-cache.json",
        )
    except Exception as exc:  # noqa: BLE001 — surface to warnings, do not crash fleet
        msg = f"dashboard build failed for {context.name!r}: {exc}"
        warnings.append(msg)
        warn(msg)

    if build_report is not None:
        warnings.extend(build_report.warnings)

    warnings_path = _write_build_warnings(
        out_dir, context=context, warnings=warnings, skipped=False
    )

    return ProjectBuildReport(
        context=context,
        build_report=build_report,
        build_warnings_path=warnings_path,
        warnings=tuple(warnings),
        skipped=False,
    )


def _write_build_warnings(
    out_dir: Path,
    *,
    context: ProjectContext,
    warnings: list[str],
    skipped: bool,
) -> Path:
    """Persist build warnings to ``<out_dir>/build-warnings.json``.

    Passes through the operator_console secret-shape guard so a stray
    secret in a warning string (e.g. a path with an API key in it)
    refuses to write rather than silently leaking.
    """

    payload = {
        "schema_version": "1.0.0",
        "project_name": context.name,
        "display_name": context.display_name,
        "captured_at": _now_iso(),
        "skipped": skipped,
        "warnings": list(warnings),
    }
    # Reuse the existing operator_console secret-shape walker so the
    # invariant is enforced identically with the what-now cache.
    operator_console._assert_no_secret_shapes(payload)  # noqa: SLF001
    path = out_dir / BUILD_WARNINGS_FILENAME
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


# ── fleet summary ───────────────────────────────────────────────────────


def build_fleet_summary(
    project_reports: Iterable[ProjectBuildReport],
    *,
    dontpanic_version: str | None = None,
    captured_at: dt.datetime | None = None,
    output_path: Path | None = None,
) -> Path:
    """Write the All-Projects rollup to ``~/.dontpanic/dashboard/fleet-summary.json``.

    The summary is a flat envelope of per-project entries plus a
    fleet-wide health band derived from the worst per-project band.
    Inactive projects are included with ``"active": false`` so the UI
    can render them muted; they are skipped for the rollup's
    ``worst_band`` calculation.

    ``dontpanic_version`` is stamped once at envelope scope — V0
    explicitly assumes one DontPanic install operates every registered
    project (plan §Schema Assumptions). A future cross-version selector
    would move this to per-entry.
    """

    captured = captured_at or dt.datetime.now(dt.timezone.utc)
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=dt.timezone.utc)

    entries: list[dict[str, Any]] = []
    worst_band = "ready"
    has_active = False
    for report in project_reports:
        entry = _fleet_entry(report, captured_at=captured)
        entries.append(entry)
        if not report.skipped and report.context.active:
            has_active = True
            band = entry.get("health_band") or "ready"
            worst_band = _worst_band(worst_band, band)

    payload = {
        "schema_version": FLEET_SUMMARY_SCHEMA_VERSION,
        "captured_at": _iso(captured),
        "dontpanic_version": dontpanic_version,
        "project_count": len(entries),
        "active_count": sum(1 for e in entries if e.get("active")),
        "worst_band": worst_band if has_active else "ready",
        "projects": entries,
    }
    operator_console._assert_no_secret_shapes(payload)  # noqa: SLF001

    target = output_path if output_path is not None else fleet_summary_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def _fleet_entry(
    report: ProjectBuildReport, *, captured_at: dt.datetime
) -> dict[str, Any]:
    """Build one fleet-summary entry from a per-project build report."""

    ctx = report.context
    cache_dir = ctx.dashboard_cache_path
    snapshot_path = cache_dir / "state-snapshot.json"
    what_now_path = cache_dir / "what-now.json"
    warnings_path = report.build_warnings_path

    data_age_seconds: float | None = None
    if snapshot_path.is_file():
        mtime = dt.datetime.fromtimestamp(
            snapshot_path.stat().st_mtime, tz=dt.timezone.utc
        )
        data_age_seconds = max(0.0, (captured_at - mtime).total_seconds())

    health_band = _derive_health_band(
        report=report,
        what_now_path=what_now_path,
    )

    entry: dict[str, Any] = {
        "name": ctx.name,
        "display_name": ctx.display_name,
        "profile": ctx.profile,
        "active": ctx.active,
        "dontpanic_version": ctx.dontpanic_version,
        "last_used_at": ctx.last_used_at,
        "repo_root": str(ctx.repo_root),
        "plans_root": str(ctx.plans_root),
        "architecture_path": str(ctx.architecture_path),
        "dashboard_cache_path": str(cache_dir),
        "state_snapshot_path": str(snapshot_path),
        "what_now_path": str(what_now_path),
        "build_warnings_path": str(warnings_path),
        "data_age_seconds": data_age_seconds,
        "warning_count": len(report.warnings),
        "skipped": report.skipped,
        "skipped_reason": report.skipped_reason,
        "health_band": health_band,
    }
    return entry


def _derive_health_band(
    *,
    report: ProjectBuildReport,
    what_now_path: Path,
) -> str:
    """Derive a four-band health value for one project.

    Bands match the operator_console.Band taxonomy (``needs_action`` /
    ``advisory`` / ``ready`` / ``quiet``). Logic:

      * inactive / skipped / no build report → ``quiet``
      * any what-now item with band ``needs_action`` → ``needs_action``
      * any what-now item with band ``advisory`` → ``advisory``
      * otherwise → ``ready``

    We read the cached what-now JSON rather than re-deriving from the
    build report so the dashboard and the fleet summary agree byte-
    for-byte on what was rolled up. Missing cache → ``ready`` (the
    operator_console treats absence as no work to do).
    """

    if report.skipped or report.build_report is None:
        return "quiet"
    if not what_now_path.is_file():
        return "ready"
    try:
        envelope = json.loads(what_now_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "ready"
    items = envelope.get("items") or []
    if not isinstance(items, list):
        return "ready"
    bands = {str(it.get("band")) for it in items if isinstance(it, dict)}
    if "needs_action" in bands:
        return "needs_action"
    if "advisory" in bands:
        return "advisory"
    return "ready"


# Worst-band ordering: needs_action > advisory > ready > quiet.
_BAND_PRIORITY = {
    "needs_action": 3,
    "advisory": 2,
    "ready": 1,
    "quiet": 0,
}


def _worst_band(current: str, candidate: str) -> str:
    if _BAND_PRIORITY.get(candidate, 0) > _BAND_PRIORITY.get(current, 0):
        return candidate
    return current


# ── small helpers ───────────────────────────────────────────────────────


def _now_iso() -> str:
    return _iso(dt.datetime.now(dt.timezone.utc))


def _iso(when: dt.datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "BUILD_WARNINGS_FILENAME",
    "FLEET_SUMMARY_FILENAME",
    "FLEET_SUMMARY_SCHEMA_VERSION",
    "PROJECTS_DASHBOARD_SUBDIR",
    "ProjectBuildReport",
    "ProjectContext",
    "build_fleet_summary",
    "build_project_state",
    "fleet_summary_path",
    "load_project_contexts",
    "project_context_from_entry",
    "project_dashboard_dir",
]
