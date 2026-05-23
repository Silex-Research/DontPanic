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


ALL_PROJECTS_SENTINEL = "all"
"""CLI value for ``--project all`` meaning "build every registered
project plus the fleet summary"."""

PROJECT_REGISTRY_FILENAME = projects_registry.REGISTRY_FILENAME
"""Re-exported so the dashboard serve watcher can fingerprint the
registry alongside its other source files."""


# ── selection model + errors ────────────────────────────────────────────


class UnknownProjectError(ValueError):
    """Raised when ``--project <name>`` does not match any registered
    project. Carries the unknown name, the list of known names (in
    registry order), and a shell-ready add-command shape so the CLI can
    print an actionable failure without re-deriving any of it.
    """

    def __init__(
        self,
        name: str,
        *,
        known_names: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.known_names = tuple(known_names)
        super().__init__(self._format())

    def add_command(self) -> str:
        return f"dontpanic projects add {self.name} <path>"

    def _format(self) -> str:
        if self.known_names:
            known = ", ".join(self.known_names)
            known_line = f"known projects: {known}"
        else:
            known_line = "no projects are registered yet"
        return (
            f"unknown project {self.name!r}; {known_line}. "
            f"register it with: {self.add_command()}"
        )


@dataclass(frozen=True)
class ResolvedSelection:
    """Outcome of :func:`resolve_selection`.

    ``kind`` is one of:
      * ``"current_repo"`` — no registry / fall back to single-repo
        ``dashboard.build`` against ``<cwd>/docs/plans``.
      * ``"all"`` — build every registered project and the fleet
        summary.
      * ``"project"`` — build the one project named by ``project_name``
        plus the fleet summary so the selector still has every option.

    ``is_default`` is True when the caller did not pass ``--project``
    explicitly; the CLI uses it to decide whether to print the
    "defaulted to X" advisory.

    ``cwd_match`` is True when the default resolution found a registered
    project containing the operator's cwd — the UI / CLI surfaces this
    so the operator can see *why* a given project was selected.
    """

    kind: str
    project_name: str | None = None
    is_default: bool = False
    cwd_match: bool = False
    reason: str = ""


def find_cwd_project_entry(
    cwd: Path,
    entries: Iterable[projects_registry.ProjectEntry],
) -> projects_registry.ProjectEntry | None:
    """Return the registry entry whose ``path`` contains ``cwd``.

    Compares resolved absolute paths. Ties (cwd inside a nested project)
    pick the deepest path so a subproject wins over its parent. Returns
    None when no entry contains cwd.
    """

    try:
        cwd_resolved = cwd.expanduser().resolve()
    except OSError:
        return None
    best: projects_registry.ProjectEntry | None = None
    best_depth = -1
    for entry in entries:
        try:
            root = Path(entry.path).expanduser().resolve()
        except OSError:
            continue
        if cwd_resolved == root or root in cwd_resolved.parents:
            depth = len(root.parts)
            if depth > best_depth:
                best = entry
                best_depth = depth
    return best


def resolve_selection(
    requested: str | None,
    *,
    cwd: Path | None = None,
    registry: projects_registry.Registry | None = None,
) -> ResolvedSelection:
    """Map a ``--project`` value (or absence) to a :class:`ResolvedSelection`.

    Per plan §Command Shape:
      * no registry → ``current_repo`` regardless of ``requested``
        being absent (an explicit ``--project`` against an empty
        registry is an error and surfaced by the CLI before reaching
        here).
      * explicit ``"all"`` → ``all``.
      * explicit ``"<name>"`` → ``project`` if known, else
        :class:`UnknownProjectError`.
      * ``None`` (operator didn't pass ``--project``):
          - cwd inside a registered project → that project (cwd_match)
          - else exactly one project registered → that project
          - else multi-project → ``all``
          - else no projects → ``current_repo``
    """

    reg = registry if registry is not None else projects_registry.load_registry()
    entries = list(reg.projects)
    cwd = cwd if cwd is not None else Path.cwd()

    if requested is not None:
        if requested == ALL_PROJECTS_SENTINEL:
            return ResolvedSelection(
                kind="all",
                is_default=False,
                reason="explicit --project all",
            )
        match = next((e for e in entries if e.name == requested), None)
        if match is None:
            raise UnknownProjectError(
                requested,
                known_names=tuple(e.name for e in entries),
            )
        return ResolvedSelection(
            kind="project",
            project_name=match.name,
            is_default=False,
            reason=f"explicit --project {match.name}",
        )

    # Default resolution.
    if not entries:
        return ResolvedSelection(
            kind="current_repo",
            is_default=True,
            reason="no registered projects; using current-repo mode",
        )

    cwd_entry = find_cwd_project_entry(cwd, entries)
    if cwd_entry is not None:
        return ResolvedSelection(
            kind="project",
            project_name=cwd_entry.name,
            is_default=True,
            cwd_match=True,
            reason=f"cwd is inside registered project {cwd_entry.name!r}",
        )

    if len(entries) == 1:
        only = entries[0]
        return ResolvedSelection(
            kind="project",
            project_name=only.name,
            is_default=True,
            reason=f"only one project registered ({only.name!r})",
        )

    return ResolvedSelection(
        kind="all",
        is_default=True,
        reason="multiple projects registered; defaulting to all",
    )


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


# ── selection orchestrator (F002) ───────────────────────────────────────


@dataclass(frozen=True)
class SelectedBuildResult:
    """Outcome of :func:`build_selected`.

    Records both the resolved selection and the build outputs the CLI
    needs to print or surface in the served dashboard tree:

      * ``selection`` — the :class:`ResolvedSelection` that was acted on.
      * ``current_repo_report`` — populated only when ``kind ==
        "current_repo"`` (zero registered projects).
      * ``project_reports`` — one :class:`ProjectBuildReport` per built
        project. Always includes the focused project for
        ``kind=="project"`` builds plus lightweight stub reports for the
        rest of the registry so the fleet summary still surfaces every
        registered project to the selector. Empty for
        ``kind=="current_repo"``.
      * ``fleet_summary_path`` — path written by
        :func:`build_fleet_summary` (``None`` for ``current_repo``).
    """

    selection: ResolvedSelection
    current_repo_report: dashboard.BuildReport | None = None
    project_reports: tuple[ProjectBuildReport, ...] = field(default_factory=tuple)
    fleet_summary_path: Path | None = None

    def focused_project(self) -> ProjectBuildReport | None:
        """The fully-built ProjectBuildReport for ``kind=="project"``.

        Returns None when this build was ``all`` or ``current_repo``;
        in those cases callers either iterate ``project_reports`` or use
        ``current_repo_report``.
        """

        if self.selection.kind != "project" or not self.selection.project_name:
            return None
        for r in self.project_reports:
            if r.context.name == self.selection.project_name and not r.skipped:
                return r
        return None


def _stub_project_report(context: ProjectContext) -> ProjectBuildReport:
    """Build a no-op :class:`ProjectBuildReport` for an unbuilt project.

    Used when ``--project <name>`` is in focused mode: every other
    project still needs a fleet-summary entry so the selector can render
    it, but we don't want to re-run :func:`dashboard.build` for the
    whole fleet on every focused refresh.

    The stub writes only ``build-warnings.json`` (so the cache layout
    invariant — every project dir has the warnings sibling — holds) and
    annotates the warning so the UI can render "stale: focused build of
    another project" without inventing the message client-side.
    """

    out_dir = context.dashboard_cache_path
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings = [
        f"project {context.name!r} not rebuilt this pass — focused build of another project",
    ]
    warnings_path = _write_build_warnings(
        out_dir, context=context, warnings=warnings, skipped=True
    )
    return ProjectBuildReport(
        context=context,
        build_report=None,
        build_warnings_path=warnings_path,
        warnings=tuple(warnings),
        skipped=True,
        skipped_reason="not focused this pass",
    )


def build_selected(
    requested: str | None,
    *,
    plans_root: Path | None = None,
    out_dir: Path | None = None,
    redact_level: str = "operator",
    plan_id: str | None = None,
    repo_root: Path | None = None,
    warn: Callable[[str], None] | None = None,
    cwd: Path | None = None,
    dontpanic_version: str | None = None,
) -> SelectedBuildResult:
    """Resolve the ``--project`` selection and execute the matching build.

    Behavior matrix:
      * ``current_repo`` (zero registered projects) — defers to
        :func:`dashboard.build` against ``plans_root`` / ``out_dir`` so
        a fresh operator with no registry still gets a dashboard.
      * ``all`` — builds every registered project and writes the fleet
        summary.
      * ``project`` — builds the focused project fully and emits
        lightweight stub reports for the rest so the fleet summary
        surfaces every registered project. The focused project's full
        state is what the operator interacts with; the other entries
        carry their existing snapshot's data age (or a "not focused"
        warning if no snapshot has been built yet).

    Raises :class:`UnknownProjectError` from
    :func:`resolve_selection` when the operator passes
    ``--project <name>`` for an unregistered name.
    """

    warn = warn if warn is not None else (lambda _msg: None)
    registry = projects_registry.load_registry()
    selection = resolve_selection(requested, cwd=cwd, registry=registry)

    if selection.kind == "current_repo":
        # Single-repo fallback — preserves the pre-F002 dashboard.build
        # behavior exactly.
        report = dashboard.build(
            plans_root=plans_root,
            out_dir=out_dir,
            redact_level=redact_level,
            plan_id=plan_id,
            repo_root=repo_root,
            warn=warn,
        )
        return SelectedBuildResult(
            selection=selection,
            current_repo_report=report,
            project_reports=(),
            fleet_summary_path=None,
        )

    # Registry-driven build.
    contexts = [project_context_from_entry(e) for e in registry.projects]
    project_reports: list[ProjectBuildReport] = []
    if selection.kind == "all":
        for ctx in contexts:
            project_reports.append(
                build_project_state(ctx, redact_level=redact_level, warn=warn)
            )
    else:  # selection.kind == "project"
        focused = selection.project_name
        for ctx in contexts:
            if ctx.name == focused:
                project_reports.append(
                    build_project_state(
                        ctx, redact_level=redact_level, warn=warn
                    )
                )
            else:
                project_reports.append(_stub_project_report(ctx))

    summary_path = build_fleet_summary(
        project_reports,
        dontpanic_version=dontpanic_version,
    )
    return SelectedBuildResult(
        selection=selection,
        current_repo_report=None,
        project_reports=tuple(project_reports),
        fleet_summary_path=summary_path,
    )


def mirror_selection_into_state_dir(
    result: SelectedBuildResult,
    *,
    state_out_dir: Path,
) -> None:
    """Copy the fleet summary and focused project state into the served tree.

    The static dashboard reads ``state/`` from its served root, so the
    serve command needs the fleet summary and the focused project's
    state-snapshot / what-now / build-warnings available there. We
    deliberately mirror — rather than symlink — so the served directory
    works on every filesystem and the operator-local cache remains the
    source of truth (the dashboard UI may also fetch it directly via
    the cache path advertised in the fleet summary).

    No-op for ``current_repo`` builds (the single-repo
    :func:`dashboard.build` writes ``state_out_dir`` directly).
    """

    if result.selection.kind == "current_repo":
        return
    state_out_dir.mkdir(parents=True, exist_ok=True)

    if result.fleet_summary_path is not None and result.fleet_summary_path.is_file():
        (state_out_dir / FLEET_SUMMARY_FILENAME).write_text(
            result.fleet_summary_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    # Mirror per-project state into state_out_dir/projects/<name>/ so the
    # selector can fetch ``projects/<name>/state-snapshot.json`` from
    # the served root without leaking absolute $HOME paths into the
    # browser. Each per-project mirror is a snapshot of the operator
    # cache at this point in time; the next build pass refreshes it.
    projects_root = state_out_dir / "projects"
    for report in result.project_reports:
        cache_dir = report.context.dashboard_cache_path
        if not cache_dir.is_dir():
            continue
        target = projects_root / report.context.name
        target.mkdir(parents=True, exist_ok=True)
        for source in cache_dir.iterdir():
            if not source.is_file():
                continue
            (target / source.name).write_text(
                source.read_text(encoding="utf-8"),
                encoding="utf-8",
            )


# ── small helpers ───────────────────────────────────────────────────────


def _now_iso() -> str:
    return _iso(dt.datetime.now(dt.timezone.utc))


def _iso(when: dt.datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "ALL_PROJECTS_SENTINEL",
    "BUILD_WARNINGS_FILENAME",
    "FLEET_SUMMARY_FILENAME",
    "FLEET_SUMMARY_SCHEMA_VERSION",
    "PROJECTS_DASHBOARD_SUBDIR",
    "PROJECT_REGISTRY_FILENAME",
    "ProjectBuildReport",
    "ProjectContext",
    "ResolvedSelection",
    "SelectedBuildResult",
    "UnknownProjectError",
    "build_fleet_summary",
    "build_project_state",
    "build_selected",
    "find_cwd_project_entry",
    "fleet_summary_path",
    "load_project_contexts",
    "mirror_selection_into_state_dir",
    "project_context_from_entry",
    "project_dashboard_dir",
    "resolve_selection",
]
