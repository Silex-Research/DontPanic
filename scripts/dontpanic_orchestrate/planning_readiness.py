"""Plan 2026-05-23-007 F002 — read-only parallel-readiness recommender.

Pure analysis of plan inventories: scans active/draft plan directories,
inspects feature ``depends_on`` and plan frontmatter ``dependencies``,
folds in known gate / breaker / defer / budget state when available, and
warns when recommended work overlaps known active supervisors or
intersecting ``allowed_paths``.

The recommender is intentionally advisory: it never writes files,
dispatches work, or mutates state. Fleet mode is aggregation, not a
scheduler — per-project recommendations are labeled with project identity
and surfaced as a single rolled-up envelope. Cross-project dependency
edges are out of scope (and would be misleading without a registry that
declares them explicitly).

Public surface used by the ``dontpanic next`` CLI:
  - :func:`analyze_repo`         scan one plans root
  - :func:`analyze_fleet`        aggregate per-project ``analyze_repo`` runs
  - :func:`render_text`          human-readable text
  - :func:`render_json`          machine-readable JSON envelope
  - :data:`SCHEMA_VERSION`       JSON envelope schema version

Collision warnings are precision-biased per plan §Product Rules: we warn
only when same plan/feature is already running OR when a recommended
feature's project + allowed_paths intersect an active supervisor's
declared paths AND a path-shaped step token shares at least one segment
with the overlap. False negatives are accepted in v0.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import (
    active_supervisors,
    circuit_breakers,
    gate_pause,
    plan_loader,
    project_config,
    projects_registry,
    quota_admission,
    release_impact,
)

_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"

# Plan-statuses considered "in flight" — i.e. their features can be
# recommended for dispatch. completed / abandoned / blocked are excluded.
# ``draft`` is included because draft plans with status-locked subtrees
# can still surface child-plan readiness, and the operator may want a
# preview before locking.
_ACTIVE_PLAN_STATUSES: frozenset[str] = frozenset(
    {"draft", "active", "ready_for_audit", "in_audit"}
)

# Status values that mean "this plan is done; don't block other work on it".
_COMPLETED_PLAN_STATUSES: frozenset[str] = frozenset({"completed"})

# Status values that mean "this plan is finished but not in a way that
# unblocks descendants" — abandoned/blocked plans hold dependents back.
_TERMINAL_NEGATIVE_STATUSES: frozenset[str] = frozenset({"abandoned", "blocked"})


# ─────────────────────────  data shapes (JSON-serializable)  ─────────────────────────


@dataclass(frozen=True)
class ReadyItem:
    kind: str  # "feature" | "plan"
    plan_id: str
    plan_dir: str
    feature_id: str | None
    title: str
    reason: str
    project_name: str | None = None
    command: str | None = None


@dataclass(frozen=True)
class NotReadyItem:
    kind: str  # "feature" | "plan"
    plan_id: str
    plan_dir: str
    feature_id: str | None
    title: str
    reasons: tuple[str, ...]
    project_name: str | None = None


@dataclass(frozen=True)
class Warning:
    # "collision" | "gate" | "breaker" | "defer" | "budget" | "load_error"
    # | "scope" | "release_impact"
    kind: str
    subject: str  # "<plan_id>" or "<plan_id>:<feature_id>"
    message: str
    project_name: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecommendationReport:
    schema_version: str
    generated_at: str
    scope: str  # "repo" | "fleet"
    ready: tuple[ReadyItem, ...]
    not_ready: tuple[NotReadyItem, ...]
    warnings: tuple[Warning, ...]
    candidate_commands: tuple[str, ...]
    # Fleet-mode: per-project sub-reports keyed by project_name. Empty
    # for repo-scope reports.
    by_project: dict[str, "RecommendationReport"] = field(default_factory=dict)
    # max-parallel applied when computing ``candidate_commands``. None
    # means "include everything in ready[]"; the CLI default of 0 is
    # rendered as None here.
    max_parallel: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "scope": self.scope,
            "ready": [asdict(r) for r in self.ready],
            "not_ready": [
                {**asdict(n), "reasons": list(n.reasons)} for n in self.not_ready
            ],
            "warnings": [
                {**asdict(w)} for w in self.warnings
            ],
            "candidate_commands": list(self.candidate_commands),
            "max_parallel": self.max_parallel,
        }
        if self.by_project:
            d["by_project"] = {
                name: rep.to_dict() for name, rep in self.by_project.items()
            }
        return d


# ─────────────────────────────  internal helpers  ─────────────────────────────


def _now_iso(now: _dt.datetime | None = None) -> str:
    ts = now or _dt.datetime.now(_dt.timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _status_value(plan: Any) -> str:
    status = getattr(plan, "status", None)
    if status is None:
        return ""
    return status.value if hasattr(status, "value") else str(status)


def _safe_load_plan(plan_dir: Path) -> tuple[Any | None, str | None]:
    """Best-effort load. Returns (LoadedPlan, None) on success,
    (None, error_message) on any failure (missing files, schema violations,
    YAML errors, etc.). Used so a single malformed plan does not poison
    the entire scan."""
    try:
        return plan_loader.load(plan_dir), None
    except Exception as exc:  # noqa: BLE001 — defensive: any load failure becomes a warning
        return None, f"{type(exc).__name__}: {exc}"


@dataclass(frozen=True)
class _ParentRoadmap:
    """Tolerant metadata-only view of a plan that has plan.md but no
    valid features.json. Lets roadmap parents participate in the
    inventory (status + dependencies + parent/child relationships)
    without forcing every roadmap to ship a features.json."""

    plan_id: str
    plan_dir: Path
    title: str
    status: str
    dependencies: list[str]
    raw_frontmatter: dict[str, Any]


def _safe_load_roadmap_parent(
    plan_dir: Path,
) -> tuple[_ParentRoadmap | None, str | None]:
    """Frontmatter-only fallback when plan_loader.load() rejects the plan
    (typically because features.json is missing). Returns a metadata
    record that can satisfy dependent-plan checks and surface a plan-
    level not-ready entry without crashing the scan."""
    plan_md = plan_dir / "plan.md"
    if not plan_md.is_file():
        return None, "plan.md missing"
    try:
        fm = plan_loader._frontmatter(plan_md)
    except Exception as exc:  # noqa: BLE001 — defensive
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(fm, dict):
        return None, "plan.md frontmatter is not a mapping"
    plan_id = str(fm.get("id") or plan_dir.name)
    title = str(fm.get("title") or plan_id)
    status = str(fm.get("status") or "")
    raw_deps = fm.get("dependencies") or []
    if isinstance(raw_deps, list):
        deps = [str(d) for d in raw_deps if d is not None]
    else:
        deps = []
    return (
        _ParentRoadmap(
            plan_id=plan_id,
            plan_dir=plan_dir,
            title=title,
            status=status,
            dependencies=deps,
            raw_frontmatter=fm,
        ),
        None,
    )


def _load_inventory(
    plans_root: Path,
) -> tuple[list[Any], list[_ParentRoadmap], list[Warning]]:
    """Walk plans_root for one-level plan dirs, load each, and return
    (loaded_plans, roadmap_parents, warnings).

    Plans that load cleanly via :func:`plan_loader.load` go to the first
    bucket. Plans that fail to load but still have a parseable plan.md
    frontmatter (typically roadmap parents that don't ship a features.json)
    fall back to a metadata-only entry in ``roadmap_parents`` — they can
    satisfy dependent-plan checks and surface as plan-level not-ready
    items without poisoning the scan. Everything that fails both paths
    becomes a ``load_error`` warning."""
    plans: list[Any] = []
    roadmaps: list[_ParentRoadmap] = []
    warnings: list[Warning] = []
    if not plans_root.is_dir():
        return plans, roadmaps, warnings
    for child in sorted(plans_root.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "plan.md").is_file():
            continue
        loaded, err = _safe_load_plan(child)
        if loaded is not None:
            plans.append(loaded)
            continue
        # Fallback: try to extract roadmap-parent metadata so the plan
        # still participates in the inventory.
        roadmap, fm_err = _safe_load_roadmap_parent(child)
        if roadmap is not None:
            roadmaps.append(roadmap)
            continue
        warnings.append(
            Warning(
                kind="load_error",
                subject=child.name,
                message=f"plan failed to load: {err}; frontmatter fallback also failed: {fm_err}",
                detail={"plan_dir": str(child)},
            )
        )
    return plans, roadmaps, warnings


def _plan_dependencies(plan: Any) -> list[str]:
    """Plan frontmatter ``dependencies`` is a list of plan IDs in
    agent-conventions v1.0+. Tolerate missing field."""
    deps = getattr(plan.plan, "dependencies", None)
    if not deps:
        return []
    return [str(d) for d in deps]


def _feature_passes(feature: Any) -> bool:
    return bool(getattr(feature, "passes", False))


def _feature_depends_on(feature: Any) -> list[str]:
    deps = getattr(feature, "depends_on", None) or []
    return [str(d) for d in deps]


def _features_map(loaded: Any) -> dict[str, Any]:
    return {f.id: f for f in loaded.features.features}


def _plan_index(
    plans: list[Any], roadmaps: list[_ParentRoadmap]
) -> dict[str, Any]:
    """Build a lookup keyed by plan_id covering both fully-loaded plans
    and tolerant roadmap-parent records. Loaded plans win on collision
    (a parseable features.json is a strictly more informative record)."""
    index: dict[str, Any] = {r.plan_id: r for r in roadmaps}
    for p in plans:
        index[p.plan_id] = p
    return index


def _entry_status(entry: Any) -> str:
    """Status accessor that works for both LoadedPlan and _ParentRoadmap."""
    if isinstance(entry, _ParentRoadmap):
        return entry.status
    return _status_value(getattr(entry, "plan", None))


def _entry_completed(entry: Any) -> bool:
    """An inventory entry is "completed" (and so can satisfy dependents)
    iff status is in :data:`_COMPLETED_PLAN_STATUSES` OR every feature
    has ``passes=True``. Roadmap parents with no features.json can only
    satisfy via explicit ``status: completed``."""
    status = _entry_status(entry)
    if status in _COMPLETED_PLAN_STATUSES:
        return True
    if isinstance(entry, _ParentRoadmap):
        # No features.json → no per-feature evidence; only status counts.
        return False
    feats = list(entry.features.features)
    if not feats:
        return False
    return all(_feature_passes(f) for f in feats)


def _plan_dependency_state(
    deps: list[str],
    plan_index: dict[str, Any],
    *,
    parent_plan_id: str | None = None,
) -> list[str]:
    """Return human-readable not-ready reasons for unmet plan-frontmatter
    dependencies. Empty list = dependencies satisfied."""
    reasons: list[str] = []
    for dep_id in deps:
        dep = plan_index.get(dep_id)
        if dep is None:
            reasons.append(
                f"depends on plan {dep_id} which is not present in the inventory"
            )
            continue
        if dep_id == parent_plan_id:
            dep_status = _entry_status(dep) or "unknown"
            if dep_status not in _TERMINAL_NEGATIVE_STATUSES:
                # A child plan often declares its active roadmap parent in
                # frontmatter dependencies for provenance. That edge is an
                # ancestry/precondition edge, not "wait until the roadmap is
                # completed"; otherwise every child would be blocked by the
                # roadmap it is meant to advance.
                continue
        if not _entry_completed(dep):
            dep_status = _entry_status(dep) or "unknown"
            reasons.append(
                f"depends on plan {dep_id} (status={dep_status}; not all features pass)"
            )
    return reasons


def _feature_dependency_state(
    feature: Any, features_map: dict[str, Any]
) -> list[str]:
    """Return unmet-feature-dependency reasons. Unknown feature IDs are
    reported but treated as a hard block (we can't prove a missing
    feature passes)."""
    reasons: list[str] = []
    for dep_id in _feature_depends_on(feature):
        dep = features_map.get(dep_id)
        if dep is None:
            reasons.append(f"depends on feature {dep_id} which is not declared in features.json")
            continue
        if not _feature_passes(dep):
            reasons.append(f"depends on feature {dep_id} (passes=false)")
    return reasons


def _read_gate_state_strictly(plan_dir: Path) -> dict[str, Any]:
    """Strictly read-only gate-state.json read.

    Plan §Product Rules invariant #9: ``dontpanic next`` never writes
    files. The shared :func:`gate_pause._read_state` helper writes a
    ``.corrupt.json`` backup when the JSON is malformed; that side
    effect is unsafe for a read-only recommender, so this command
    intentionally uses its own loader.

    Returns the parsed JSON dict on success, an empty dict on missing /
    malformed / unreadable files. Corruption is reflected by an empty
    dict (i.e. "no state available") — the caller can still emit a
    warning, but the on-disk artifact is never touched."""
    state_path = plan_dir / "audit" / gate_pause.GATE_STATE_FILENAME
    if not state_path.is_file():
        return {}
    try:
        raw = state_path.read_text()
    except OSError as exc:  # pragma: no cover — defensive
        _LOG.debug("gate-state read failed for %s: %s", plan_dir, exc)
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Corrupt JSON. Do NOT write a .corrupt.json backup — that's
        # the production gate_pause helper's job, not ours.
        return {}
    return data if isinstance(data, dict) else {}


def _gate_state_summary(plan_dir: Path, loaded: Any) -> dict[str, list[str]]:
    """Read persisted gate state without writing anything. Returns
    ``{'unmet': [...], 'active_breakers': [...], 'active_defers': [...]}``
    derived from a strictly read-only load."""
    declared = [
        g.value if hasattr(g, "value") else str(g)
        for g in (getattr(loaded.plan, "human_gates", None) or [])
    ]
    state = _read_gate_state_strictly(plan_dir)
    cleared_raw = state.get("cleared_gates")
    if isinstance(cleared_raw, list):
        cleared = {str(g) for g in cleared_raw}
    elif isinstance(cleared_raw, dict):
        cleared = {str(g) for g, v in cleared_raw.items() if v}
    else:
        cleared = set()
    breakers_raw = state.get("active_breakers") or []
    defers_raw = state.get("active_defers") or []
    breakers = [str(b) for b in breakers_raw] if isinstance(breakers_raw, list) else []
    defers = [str(d) for d in defers_raw] if isinstance(defers_raw, list) else []
    plan_unmet = [g for g in declared if g not in cleared]
    return {
        "unmet": plan_unmet,
        "active_breakers": breakers,
        "active_defers": defers,
    }


def _budget_state_warnings(
    plan_id: str,
    project_name: str | None,
    *,
    agents: list[str] | None = None,
) -> list[Warning]:
    """Surface global breaker AND per-agent quota/budget state as
    advisory warnings.

    Two read-only signals:
      - global circuit breaker history (``circuit_breakers.evaluate_global``)
        — a trip means autonomous dispatch is refused everywhere.
      - quota threshold across this plan's participating agents
        (``quota_admission.evaluate_quota_threshold``) — when an agent's
        weekly usage already crosses the defer threshold, dispatching
        will immediately pause on ``defer:quota_threshold``.

    Both helpers are pure reads. Per plan §Product Rules, when the
    substrate cannot be read we say so explicitly rather than implying
    the work is clear.
    """
    warnings: list[Warning] = []
    try:
        # `evaluate_global` returns iteration_cap rollup; a tripped
        # global breaker means autonomous dispatch is refused everywhere.
        gstate = circuit_breakers.evaluate_global()
    except Exception as exc:  # noqa: BLE001 — defensive
        warnings.append(
            Warning(
                kind="budget",
                subject=plan_id,
                message=(
                    "could not read global breaker history; treat the "
                    f"recommendation as advisory only ({type(exc).__name__})"
                ),
                project_name=project_name,
            )
        )
    else:
        if gstate.tripped:
            warnings.append(
                Warning(
                    kind="breaker",
                    subject=plan_id,
                    message=(
                        f"global circuit breaker is tripped "
                        f"({gstate.hits_in_window}/{gstate.threshold} hits in "
                        f"{gstate.window_seconds}s) — autonomous dispatch is refused. "
                        "Wait for the window to expire."
                    ),
                    project_name=project_name,
                    detail={
                        "hits_in_window": gstate.hits_in_window,
                        "threshold": gstate.threshold,
                        "window_seconds": gstate.window_seconds,
                    },
                )
            )

    # Quota threshold across the plan's declared agents. evaluate_quota_threshold
    # is a pure read of ~/.jarvis/quota_state.json + caps file; no writes.
    if agents:
        try:
            qcheck = quota_admission.evaluate_quota_threshold(agents)
        except Exception as exc:  # noqa: BLE001 — defensive
            warnings.append(
                Warning(
                    kind="budget",
                    subject=plan_id,
                    message=(
                        "could not read quota state; treat the recommendation "
                        f"as advisory only ({type(exc).__name__})"
                    ),
                    project_name=project_name,
                )
            )
        else:
            if qcheck.over_threshold:
                if qcheck.cause is not None:
                    msg = (
                        f"quota check is in terminal state "
                        f"{qcheck.cause!r} for agent {qcheck.offending_agent or '?'}"
                        " — autonomous dispatch will pause on defer:quota_threshold."
                    )
                else:
                    msg = (
                        f"quota for agent {qcheck.offending_agent or '?'} is at "
                        f"{qcheck.observed_pct:.1f}% (>{qcheck.threshold:.1f}%) — "
                        "autonomous dispatch will pause on defer:quota_threshold."
                    )
                warnings.append(
                    Warning(
                        kind="budget",
                        subject=plan_id,
                        message=msg,
                        project_name=project_name,
                        detail={
                            "offending_agent": qcheck.offending_agent,
                            "observed_pct": qcheck.observed_pct,
                            "threshold": qcheck.threshold,
                            "cause": qcheck.cause,
                        },
                    )
                )
    return warnings


# ─────────────────────────  collision detection  ─────────────────────────


def _allowed_paths(loaded: Any) -> list[str]:
    charter = getattr(loaded, "child_charter", None)
    if charter is None:
        return []
    paths = getattr(charter, "allowed_paths", None) or []
    return [str(p) for p in paths]


def _path_segments(path_like: str) -> set[str]:
    """Tokenize a glob-ish path into the set of literal segments. ``**``
    and ``*`` are dropped so they don't dominate the intersection."""
    out: set[str] = set()
    for seg in path_like.replace("\\", "/").split("/"):
        seg = seg.strip()
        if not seg or seg in {"*", "**"}:
            continue
        # Strip leading "./" and trailing wildcards on the segment itself.
        seg = seg.lstrip(".")
        if not seg:
            continue
        out.add(seg)
    return out


def _step_path_tokens(feature: Any) -> set[str]:
    """Extract path-shaped tokens from a feature's ``steps`` text. We
    treat any token containing ``/`` (and not starting with ``http``)
    as path-like and emit its segments."""
    out: set[str] = set()
    for step in getattr(feature, "steps", None) or []:
        for raw in str(step).split():
            cleaned = raw.strip(".,;:()[]`\"'")
            if "/" not in cleaned:
                continue
            if cleaned.startswith(("http://", "https://")):
                continue
            out |= _path_segments(cleaned)
    return out


def _step_path_raw_tokens(feature: Any) -> list[str]:
    """Raw path-shaped tokens (slashes preserved) from feature ``steps``.

    The collision detector wants tokenized segments. The release-impact
    advisory wants full path-like tokens so its glob rules can match.
    Both consumers feed off the same step text, but their tokenization
    needs differ — keep them separate to avoid coupling the two
    consumers' false-positive characteristics.
    """
    out: list[str] = []
    for step in getattr(feature, "steps", None) or []:
        for raw in str(step).split():
            cleaned = raw.strip(".,;:()[]`\"'")
            if "/" not in cleaned:
                continue
            if cleaned.startswith(("http://", "https://")):
                continue
            normalized = cleaned.replace("\\", "/")
            while normalized.startswith("./"):
                normalized = normalized[2:]
            out.append(normalized)
    return out


def _paths_overlap(
    a_allowed: list[str], a_tokens: set[str], b_allowed: list[str]
) -> tuple[bool, set[str]]:
    """Return (overlap_present, intersection_segments).

    The overlap rule per plan §Product Rules is precision-biased:
    intersecting allowed_paths PLUS at least one shared step-token
    segment. Returning early-empty on either branch suppresses the
    noisier false positives.
    """
    a_segs: set[str] = set()
    for p in a_allowed:
        a_segs |= _path_segments(p)
    b_segs: set[str] = set()
    for p in b_allowed:
        b_segs |= _path_segments(p)
    path_intersection = a_segs & b_segs
    if not path_intersection:
        return False, set()
    if not a_tokens:
        # Without a path-shaped step token we can't justify the warning
        # — drop into "tolerate the false negative" mode.
        return False, set()
    token_intersection = a_tokens & b_segs
    if not token_intersection:
        return False, set()
    return True, (path_intersection | token_intersection)


def _active_supervisor_collisions(
    loaded: Any,
    feature: Any,
    *,
    active: list[active_supervisors.SupervisorEntry],
    plan_index: dict[str, Any],
    project_name: str | None,
) -> list[Warning]:
    """Emit collision warnings against the live active-supervisor registry.

    Two distinct cases:
      (a) same plan_id is already running → strong "same plan/feature"
          collision (always warned).
      (b) different plan but the active plan's allowed_paths intersect
          THIS plan's allowed_paths AND a step path-token shares a
          segment → advisory substrate overlap.
    """
    warnings: list[Warning] = []
    a_allowed = _allowed_paths(loaded)
    a_tokens = _step_path_tokens(feature)
    subject = f"{loaded.plan_id}:{feature.id}"
    for entry in active:
        if entry.plan_id == loaded.plan_id:
            warnings.append(
                Warning(
                    kind="collision",
                    subject=subject,
                    message=(
                        f"active supervisor pid={entry.pid} is already running plan "
                        f"{entry.plan_id}; dispatching a second volley on the same "
                        "plan corrupts audit iteration numbering"
                    ),
                    project_name=project_name,
                    detail={
                        "active_plan_id": entry.plan_id,
                        "active_pid": entry.pid,
                        "since": entry.started_at,
                    },
                )
            )
            continue
        other = plan_index.get(entry.plan_id)
        if other is None:
            continue
        b_allowed = _allowed_paths(other)
        if not b_allowed:
            continue
        overlap, segs = _paths_overlap(a_allowed, a_tokens, b_allowed)
        if not overlap:
            continue
        warnings.append(
            Warning(
                kind="collision",
                subject=subject,
                message=(
                    f"allowed_paths overlap active supervisor pid={entry.pid} on "
                    f"plan {entry.plan_id} (shared segments: "
                    f"{sorted(segs)[:5]}); advisory only — confirm "
                    "before dispatch"
                ),
                project_name=project_name,
                detail={
                    "active_plan_id": entry.plan_id,
                    "active_pid": entry.pid,
                    "shared_segments": sorted(segs),
                },
            )
        )
    return warnings


# ─────────────────────────  release-impact advisory  ─────────────────────────


def _plan_surfaces(loaded: Any) -> list[str]:
    """Plan frontmatter ``surfaces`` array (agent-conventions v1.7+).
    Tolerate missing field / non-list shape."""
    raw = getattr(loaded.plan, "surfaces", None)
    if not raw:
        return []
    out: list[str] = []
    for s in raw:
        s_val = s.value if hasattr(s, "value") else str(s)
        if s_val:
            out.append(s_val)
    return out


def _release_impact_warnings_for_plan(
    loaded: Any,
    *,
    project_name: str | None,
    changed_paths: list[str] | None = None,
) -> list[Warning]:
    """Emit per-plan release-impact advisories via :mod:`release_impact`.

    Inputs:
      - plan-declared ``surfaces`` (draft-time intent)
      - child charter ``allowed_paths`` (draft-time intent)
      - union of feature step path tokens (draft-time intent)
      - optional ``changed_paths`` from a lock-time git diff (precision)

    Each plan produces at most one ``release_impact`` Warning. The
    advisory's rendered text is the warning message; the structured
    advisory dict rides on ``detail`` for JSON consumers.
    """
    plan_surfaces = _plan_surfaces(loaded)
    allowed_paths = _allowed_paths(loaded)
    # Union of all features' step path tokens — a single plan-level
    # advisory covers every not-yet-passing feature.
    token_set: list[str] = []
    seen: set[str] = set()
    for feature in getattr(loaded.features, "features", []) or []:
        if _feature_passes(feature):
            continue
        for tok in _step_path_raw_tokens(feature):
            if tok not in seen:
                seen.add(tok)
                token_set.append(tok)

    advisory = release_impact.analyze(
        changed_paths=changed_paths or [],
        plan_surfaces=plan_surfaces,
        allowed_paths=allowed_paths,
        step_path_tokens=token_set,
    )
    # If the advisory has no inputs at all (no plan surfaces, no
    # allowed_paths, no step tokens, no diff) the helper returns an
    # empty advisory we should not emit.
    if not advisory.surfaces and not advisory.internal_only:
        return []
    return [
        Warning(
            kind="release_impact",
            subject=loaded.plan_id,
            message=release_impact.render_text(advisory),
            project_name=project_name,
            detail=advisory.to_dict(),
        )
    ]


# ─────────────────────────  command synthesis  ─────────────────────────


def _candidate_command_for_feature(loaded: Any, feature_id: str) -> str:
    """Exact ``dispatch-from-plan`` command — operator runs with ``--confirm``
    to actually dispatch. This is intentionally the dry-run shape (no
    ``--confirm``) so a copy-paste does not auto-dispatch."""
    return (
        f"python -m dontpanic_orchestrate dispatch-from-plan "
        f"{loaded.plan_id} --feature {feature_id}"
    )


def _candidate_command_for_plan(loaded: Any) -> str | None:
    """Plan-level recommendations point at the first not-yet-passing
    feature when one exists; otherwise we can't form an exact command
    and the caller emits the reason text instead."""
    for f in loaded.features.features:
        if not _feature_passes(f):
            return _candidate_command_for_feature(loaded, f.id)
    return None


# ─────────────────────────────  core analyzer  ─────────────────────────────


def analyze_repo(
    plans_root: Path,
    *,
    project_name: str | None = None,
    max_parallel: int | None = None,
    include_not_ready: bool = True,
    active_entries: list[active_supervisors.SupervisorEntry] | None = None,
    now: _dt.datetime | None = None,
) -> RecommendationReport:
    """Scan one plans root and produce a recommendation report.

    Parameters
    ----------
    plans_root
        Filesystem path to the directory containing per-plan dirs
        (e.g. ``<repo>/docs/plans``). Missing directories return an
        empty report (with a single ``scope`` warning).
    project_name
        Optional project name to label every emitted item. Fleet mode
        passes the registered project name; repo mode leaves it None.
    max_parallel
        Cap on ``candidate_commands[]``. ``None`` or ``0`` means "include
        every ready item". Ready items are returned in deterministic
        order (plan_id, feature_id).
    include_not_ready
        When False, the returned ``not_ready`` tuple is empty (the CLI
        ``--include-not-ready`` flag controls this).
    active_entries
        Pre-resolved list of live supervisors. When None, the live
        registry is read; pass an empty list to disable collision checks.
    """
    ts = _now_iso(now)
    warnings: list[Warning] = []

    if not plans_root.is_dir():
        warnings.append(
            Warning(
                kind="scope",
                subject=str(plans_root),
                message=f"plans root does not exist or is not a directory: {plans_root}",
                project_name=project_name,
            )
        )
        return RecommendationReport(
            schema_version=SCHEMA_VERSION,
            generated_at=ts,
            scope="repo",
            ready=(),
            not_ready=(),
            warnings=tuple(warnings),
            candidate_commands=(),
            max_parallel=max_parallel if max_parallel else None,
        )

    plans, roadmaps, load_warnings = _load_inventory(plans_root)
    warnings.extend(load_warnings)
    plan_index = _plan_index(plans, roadmaps)

    if active_entries is None:
        try:
            # prune=False so we never rewrite the active-supervisors
            # registry file from a read-only recommender. Dead PIDs in
            # the registry would survive this call; the production
            # supervisor's own register/unregister/`jarvis ps` paths are
            # responsible for pruning.
            active_entries = active_supervisors.list_active(prune=False)
        except Exception as exc:  # noqa: BLE001 — defensive
            _LOG.debug("active_supervisors.list_active failed: %s", exc)
            active_entries = []

    # Pre-compute parent → child relationships so a roadmap parent can
    # report which children are still in flight. Looks at every
    # fully-loaded plan's `orchestration.parent_plan_id`.
    children_by_parent: dict[str, list[Any]] = {}
    for loaded in plans:
        orch = getattr(loaded, "orchestration", None)
        parent_id = getattr(orch, "parent_plan_id", None) if orch else None
        if parent_id:
            children_by_parent.setdefault(str(parent_id), []).append(loaded)

    ready: list[ReadyItem] = []
    not_ready: list[NotReadyItem] = []

    # Roadmap-parent (frontmatter-only) entries: emit them as plan-level
    # not-ready items reflecting their children's state, then skip them
    # in the main per-plan loop.
    for roadmap in roadmaps:
        status = roadmap.status
        if status in _COMPLETED_PLAN_STATUSES or status in _TERMINAL_NEGATIVE_STATUSES:
            continue
        if status and status not in _ACTIVE_PLAN_STATUSES:
            warnings.append(
                Warning(
                    kind="scope",
                    subject=roadmap.plan_id,
                    message=(
                        f"roadmap parent status {status!r} is not in the "
                        f"known active set {sorted(_ACTIVE_PLAN_STATUSES)}; skipping"
                    ),
                    project_name=project_name,
                )
            )
            continue
        dep_reasons = _plan_dependency_state(roadmap.dependencies, plan_index)
        kids = children_by_parent.get(roadmap.plan_id, [])
        kid_reasons: list[str] = []
        if not kids:
            kid_reasons.append(
                "roadmap parent has no features.json and no child plans declare "
                "it as parent_plan_id; nothing dispatchable from this entry"
            )
        else:
            for kid in kids:
                if not _entry_completed(kid):
                    kid_status = _entry_status(kid) or "unknown"
                    kid_reasons.append(
                        f"waiting on child plan {kid.plan_id} (status={kid_status})"
                    )
        all_reasons = [f"plan blocked: {r}" for r in dep_reasons] + kid_reasons
        if not all_reasons:
            # All children complete and no dep gaps — roadmap is dispatch-clear
            # but still has no features of its own to emit. Surface a hint
            # rather than a hard not-ready entry.
            warnings.append(
                Warning(
                    kind="scope",
                    subject=roadmap.plan_id,
                    message=(
                        "roadmap parent has no features.json and every child "
                        "plan is completed — consider flipping plan status to "
                        "completed"
                    ),
                    project_name=project_name,
                )
            )
            continue
        if include_not_ready:
            not_ready.append(
                NotReadyItem(
                    kind="plan",
                    plan_id=roadmap.plan_id,
                    plan_dir=str(roadmap.plan_dir),
                    feature_id=None,
                    title=roadmap.title,
                    reasons=tuple(all_reasons),
                    project_name=project_name,
                )
            )

    for loaded in plans:
        plan_id = loaded.plan_id
        plan_dir_str = str(loaded.plan_dir)
        status = _status_value(loaded.plan)

        # Terminal statuses: skip entirely (completed/abandoned/blocked).
        if status in _COMPLETED_PLAN_STATUSES:
            continue
        if _entry_completed(loaded):
            continue
        if status in _TERMINAL_NEGATIVE_STATUSES:
            continue
        if status and status not in _ACTIVE_PLAN_STATUSES:
            # Unknown / future status — skip with an advisory.
            warnings.append(
                Warning(
                    kind="scope",
                    subject=plan_id,
                    message=(
                        f"plan status {status!r} is not in the known active "
                        f"set {sorted(_ACTIVE_PLAN_STATUSES)}; skipping"
                    ),
                    project_name=project_name,
                )
            )
            continue

        orch = getattr(loaded, "orchestration", None)
        parent_plan_id = str(getattr(orch, "parent_plan_id", "") or "") or None
        plan_dep_reasons = _plan_dependency_state(
            _plan_dependencies(loaded),
            plan_index,
            parent_plan_id=parent_plan_id,
        )
        gate_summary = _gate_state_summary(loaded.plan_dir, loaded)

        # Plan-level gate/breaker/defer warnings carry the plan id as the
        # subject so the CLI can scope them correctly.
        for breaker in gate_summary["active_breakers"]:
            warnings.append(
                Warning(
                    kind="breaker",
                    subject=plan_id,
                    message=f"active breaker on plan: {breaker}",
                    project_name=project_name,
                )
            )
        for defer in gate_summary["active_defers"]:
            warnings.append(
                Warning(
                    kind="defer",
                    subject=plan_id,
                    message=f"active defer on plan: {defer}",
                    project_name=project_name,
                )
            )

        # Global budget/breaker state is surfaced once per plan so the
        # operator sees it close to the recommendation that would hit it.
        plan_agents = [str(a) for a in (getattr(loaded.plan, "agents_required", None) or [])]
        warnings.extend(
            _budget_state_warnings(plan_id, project_name, agents=plan_agents)
        )

        # Plan 2026-05-23-007 F003 — release-impact advisory. One per plan,
        # surfaced as a release_impact warning so the JSON envelope shape
        # stays stable. Draft-time only (no git diff) at this seam; lock-
        # time messaging can call release_impact.analyze directly with the
        # diff for precision.
        warnings.extend(
            _release_impact_warnings_for_plan(
                loaded, project_name=project_name
            )
        )

        features_map = _features_map(loaded)
        any_feature_ready = False

        for feature in loaded.features.features:
            feature_id = feature.id
            subject = f"{plan_id}:{feature_id}"
            title = getattr(feature, "description", "") or ""
            # Trim long descriptions for display.
            title_short = title.split(".")[0].strip()[:160] or feature_id

            if _feature_passes(feature):
                continue

            reasons: list[str] = []

            # Plan-level blockers apply to every feature.
            for r in plan_dep_reasons:
                reasons.append(f"plan blocked: {r}")
            for g in gate_summary["unmet"]:
                reasons.append(f"plan gate {g!r} not cleared")
            for b in gate_summary["active_breakers"]:
                reasons.append(f"plan paused on {b}")
            for d in gate_summary["active_defers"]:
                reasons.append(f"plan deferred on {d}")

            # Feature-level dependencies.
            reasons.extend(_feature_dependency_state(feature, features_map))

            # Active-supervisor / collision warnings are advisory; they
            # do NOT add a not-ready reason (precision-biased), they
            # surface as warnings.
            collision_warnings = _active_supervisor_collisions(
                loaded,
                feature,
                active=active_entries,
                plan_index=plan_index,
                project_name=project_name,
            )
            warnings.extend(collision_warnings)

            if reasons:
                if include_not_ready:
                    not_ready.append(
                        NotReadyItem(
                            kind="feature",
                            plan_id=plan_id,
                            plan_dir=plan_dir_str,
                            feature_id=feature_id,
                            title=title_short,
                            reasons=tuple(reasons),
                            project_name=project_name,
                        )
                    )
                continue

            ready.append(
                ReadyItem(
                    kind="feature",
                    plan_id=plan_id,
                    plan_dir=plan_dir_str,
                    feature_id=feature_id,
                    title=title_short,
                    reason="all declared dependencies satisfied",
                    project_name=project_name,
                    command=_candidate_command_for_feature(loaded, feature_id),
                )
            )
            any_feature_ready = True

        # Plan-level entry for orchestration roadmaps with no individual
        # feature work (e.g. a tracking parent waiting on children).
        if not any_feature_ready and not loaded.features.features and include_not_ready:
            not_ready.append(
                NotReadyItem(
                    kind="plan",
                    plan_id=plan_id,
                    plan_dir=plan_dir_str,
                    feature_id=None,
                    title=getattr(loaded.plan, "title", plan_id),
                    reasons=("plan declares no features",),
                    project_name=project_name,
                )
            )

    # Deterministic sort: by plan_id then feature_id.
    ready.sort(key=lambda r: (r.plan_id, r.feature_id or ""))
    not_ready.sort(key=lambda n: (n.plan_id, n.feature_id or ""))

    cap = max_parallel if max_parallel and max_parallel > 0 else None
    if cap is None:
        candidate_commands = tuple(r.command for r in ready if r.command)
    else:
        candidate_commands = tuple(
            r.command for r in ready[:cap] if r.command
        )

    return RecommendationReport(
        schema_version=SCHEMA_VERSION,
        generated_at=ts,
        scope="repo",
        ready=tuple(ready),
        not_ready=tuple(not_ready),
        warnings=tuple(warnings),
        candidate_commands=candidate_commands,
        max_parallel=cap,
    )


def analyze_fleet(
    *,
    max_parallel: int | None = None,
    include_not_ready: bool = True,
    now: _dt.datetime | None = None,
    active_entries: list[active_supervisors.SupervisorEntry] | None = None,
) -> RecommendationReport:
    """Aggregate ``analyze_repo`` across every registered project.

    Fleet mode is *aggregation, not coordination*: each registered
    project is scanned with its own per-project plans_dir, and the
    resulting reports are concatenated under ``by_project``. The
    top-level ``ready[]`` / ``not_ready[]`` / ``warnings[]`` are the
    union, labeled with ``project_name``. ``candidate_commands[]``
    interleaves projects in round-robin order so the operator can pick
    parallel work across projects without over-weighting one.
    """
    ts = _now_iso(now)
    if active_entries is None:
        try:
            # prune=False: see analyze_repo for the read-only rationale.
            active_entries = active_supervisors.list_active(prune=False)
        except Exception as exc:  # noqa: BLE001 — defensive
            _LOG.debug("active_supervisors.list_active failed: %s", exc)
            active_entries = []

    reg = projects_registry.load_registry()
    by_project: dict[str, RecommendationReport] = {}
    aggregated_ready: list[ReadyItem] = []
    aggregated_not_ready: list[NotReadyItem] = []
    aggregated_warnings: list[Warning] = []

    for entry in reg.projects:
        if entry.active is False:
            continue
        proj_path = Path(entry.path).expanduser().resolve()
        if not proj_path.is_dir():
            aggregated_warnings.append(
                Warning(
                    kind="scope",
                    subject=entry.name,
                    message=f"registered project path does not exist: {proj_path}",
                    project_name=entry.name,
                )
            )
            continue
        cfg = project_config.load_project_config(proj_path)
        plans_dir_rel = cfg.plans_dir if cfg is not None else project_config.DEFAULT_PLANS_DIR
        plans_root = proj_path / plans_dir_rel
        report = analyze_repo(
            plans_root,
            project_name=entry.name,
            # Per-project max_parallel is unbounded — the top-level cap
            # is applied across the aggregated commands so the operator
            # can constrain total parallelism even when one project has
            # many ready features.
            max_parallel=None,
            include_not_ready=include_not_ready,
            active_entries=active_entries,
            now=now,
        )
        by_project[entry.name] = report
        aggregated_ready.extend(report.ready)
        aggregated_not_ready.extend(report.not_ready)
        aggregated_warnings.extend(report.warnings)

    # Stable order (project_name, plan_id, feature_id).
    aggregated_ready.sort(
        key=lambda r: (r.project_name or "", r.plan_id, r.feature_id or "")
    )
    aggregated_not_ready.sort(
        key=lambda n: (n.project_name or "", n.plan_id, n.feature_id or "")
    )

    # Round-robin per-project candidate commands so one busy project
    # doesn't dominate the operator's first-N picks.
    per_project_queues: dict[str, list[str]] = {}
    for name, rep in by_project.items():
        per_project_queues[name] = [r.command for r in rep.ready if r.command]
    interleaved: list[str] = []
    while any(per_project_queues.values()):
        for name in sorted(per_project_queues.keys()):
            q = per_project_queues[name]
            if q:
                interleaved.append(q.pop(0))
    cap = max_parallel if max_parallel and max_parallel > 0 else None
    candidate_commands = (
        tuple(interleaved) if cap is None else tuple(interleaved[:cap])
    )

    return RecommendationReport(
        schema_version=SCHEMA_VERSION,
        generated_at=ts,
        scope="fleet",
        ready=tuple(aggregated_ready),
        not_ready=tuple(aggregated_not_ready),
        warnings=tuple(aggregated_warnings),
        candidate_commands=candidate_commands,
        by_project=by_project,
        max_parallel=cap,
    )


# ─────────────────────────────  rendering  ─────────────────────────────


def render_json(report: RecommendationReport) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)


def _label(item: ReadyItem | NotReadyItem) -> str:
    if item.feature_id is None:
        base = item.plan_id
    else:
        base = f"{item.plan_id} {item.feature_id}"
    if item.project_name:
        return f"[{item.project_name}] {base}"
    return base


def render_text(report: RecommendationReport) -> str:
    lines: list[str] = []
    header = f"dontpanic next — scope={report.scope} generated_at={report.generated_at}"
    lines.append(header)
    lines.append("=" * len(header))
    lines.append("")

    if report.scope == "fleet" and report.by_project:
        lines.append(
            f"Aggregated across {len(report.by_project)} project(s): "
            + ", ".join(sorted(report.by_project.keys()))
        )
        lines.append(
            "Fleet mode is aggregation, not cross-project scheduling — each "
            "project's recommendations are independent."
        )
        lines.append("")

    lines.append(f"READY ({len(report.ready)}):")
    if not report.ready:
        lines.append("  (none)")
    else:
        for r in report.ready:
            lines.append(f"  • {_label(r)} — {r.title}")
            lines.append(f"      reason: {r.reason}")
            if r.command:
                lines.append(f"      next: $ {r.command}")
    lines.append("")

    if report.not_ready:
        lines.append(f"NOT READY ({len(report.not_ready)}):")
        for n in report.not_ready:
            lines.append(f"  • {_label(n)} — {n.title}")
            for reason in n.reasons:
                lines.append(f"      ✗ {reason}")
        lines.append("")

    if report.warnings:
        lines.append(f"WARNINGS ({len(report.warnings)}):")
        for w in report.warnings:
            scope_label = f"[{w.project_name}] " if w.project_name else ""
            # release_impact messages are multi-line — indent continuation
            # lines so the rendering reads as one logical advisory.
            msg_lines = w.message.split("\n")
            lines.append(
                f"  • {scope_label}{w.kind}: {w.subject} — {msg_lines[0]}"
            )
            for cont in msg_lines[1:]:
                lines.append(f"    {cont}")
        lines.append("")

    lines.append(
        f"CANDIDATE COMMANDS"
        + (f" (max_parallel={report.max_parallel})" if report.max_parallel else "")
        + ":"
    )
    if not report.candidate_commands:
        lines.append("  (none — nothing ready or no exact command could be formed)")
    else:
        for cmd in report.candidate_commands:
            lines.append(f"  $ {cmd}")

    return "\n".join(lines) + "\n"


__all__ = [
    "NotReadyItem",
    "ReadyItem",
    "RecommendationReport",
    "SCHEMA_VERSION",
    "Warning",
    "analyze_fleet",
    "analyze_repo",
    "render_json",
    "render_text",
]
