"""Plan 2026-05-23-005 F004 — typed relevance table for global blockers.

This module encodes the relevance table from
``docs/plans/2026-05-23-005-feat-dashboard-project-selector-v0/plan.md``
§F004 Design Table into executable rules. Every dashboard blocker class
has exactly one entry below — adding a new blocker class is a
deliberate edit of :data:`RELEVANCE_RULES`, not a fall-through default.

The rules answer one question, given an :class:`operator_console.
ActionItem` and a :class:`ProjectDeclarations` projection:

    is this global blocker relevant to the selected project?

The F004 design table:

| Blocker class                          | Scope   | Project relevance rule |
|----------------------------------------|---------|-------------------------|
| Capability not installed/configured    | Global  | Relevant only when the selected project's plans declare ``requires_capabilities[]`` or matching ``external_refs[]`` |
| Doctor/install blocker                 | Global  | Relevant to every project |
| DontPanic install drift                | Global  | Relevant to every project |
| Architecture stale/missing             | Project | Relevant only to the selected project |
| Adapter not configured                 | Global  | Relevant only when the selected project references that adapter category or capability |
| Dashboard build warning                | Project/Fleet | Relevant to the affected project; Fleet groups warnings by project |

Per-project items (architecture, build warnings, gates) carry their
``project_name`` directly — :func:`is_item_relevant_to_project`
short-circuits to a string-equality check before consulting the
relevance table. The table only handles unscoped *global* items.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from dontpanic_orchestrate import operator_console

_LOG = logging.getLogger(__name__)


# ── Project capability declarations ───────────────────────────────────────


@dataclass(frozen=True)
class ProjectDeclarations:
    """Capability/adapter declarations a project's plans surface.

    Built once per project at dashboard-build time from the plan
    frontmatter under ``<plans_root>/*/plan.md``. The dashboard reads
    this via :func:`load_project_declarations` to decide which global
    blockers are relevant to the project.

    ``required_capability_ids`` is the union of every plan's
    ``requires_capabilities[]`` plus any ``external_refs[].capability_id``
    string. ``referenced_adapter_categories`` is the set of capability
    *categories* referenced — useful when the operator hasn't named a
    specific capability but the project clearly touches a category
    (e.g. ``dashboard-realtime``).
    """

    project_name: str
    required_capability_ids: frozenset[str] = field(default_factory=frozenset)
    referenced_adapter_categories: frozenset[str] = field(default_factory=frozenset)

    def declares(self, capability_id: str) -> bool:
        return capability_id in self.required_capability_ids

    def references_category(self, category: str) -> bool:
        return category in self.referenced_adapter_categories


def load_project_declarations(
    project_name: str,
    plans_root: Path,
) -> ProjectDeclarations:
    """Walk ``plans_root`` and collect every plan's capability declarations.

    Tolerates malformed plan.md files (logs + skips). The dashboard
    treats absence as "no declarations" — a project with no
    ``requires_capabilities[]`` simply doesn't see capability-class
    blockers in its filtered what-now view.
    """

    if not plans_root.exists() or not plans_root.is_dir():
        return ProjectDeclarations(project_name=project_name)

    cap_ids: set[str] = set()
    categories: set[str] = set()
    for plan_dir in sorted(plans_root.iterdir()):
        plan_md = plan_dir / "plan.md"
        if not plan_md.is_file():
            continue
        try:
            text = plan_md.read_text(encoding="utf-8")
        except OSError as exc:
            _LOG.warning("could not read %s: %s", plan_md, exc)
            continue
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError as exc:
            _LOG.warning("malformed frontmatter in %s: %s", plan_md, exc)
            continue
        if not isinstance(fm, dict):
            continue
        # requires_capabilities[]: list of strings.
        rc = fm.get("requires_capabilities") or []
        if isinstance(rc, list):
            for item in rc:
                if isinstance(item, str) and item:
                    cap_ids.add(item)
        # external_refs[]: list of dicts; capability_id is the explicit
        # binding the sidecar respects.
        er = fm.get("external_refs") or []
        if isinstance(er, list):
            for ref in er:
                if isinstance(ref, dict):
                    cap = ref.get("capability_id")
                    if isinstance(cap, str) and cap:
                        cap_ids.add(cap)
        # Optional: adapter categories an operator can declare on a plan
        # to claim it touches a class of capability without naming one
        # specific id. Kept additive — absence is fine.
        cats = fm.get("adapter_categories") or []
        if isinstance(cats, list):
            for c in cats:
                if isinstance(c, str) and c:
                    categories.add(c)

    return ProjectDeclarations(
        project_name=project_name,
        required_capability_ids=frozenset(cap_ids),
        referenced_adapter_categories=frozenset(categories),
    )


# ── Relevance rules ───────────────────────────────────────────────────────


# Capability ids whose blockers always apply to every project. These are
# the doctor/install blockers + DontPanic install drift in the plan.md
# design table: their failure modes affect every operator action,
# regardless of which project the operator selected.
GLOBAL_DOCTOR_CAPABILITIES: frozenset[str] = frozenset(
    {
        "python",
        "schema-support",
        "dontpanic-install",
        "git",
    }
)

# Capability categories that always apply to every project (Python
# runtime, schema tooling, source control). A category here overrides
# the per-project ``requires_capabilities[]`` declarations.
GLOBAL_DOCTOR_CATEGORIES: frozenset[str] = frozenset(
    {
        "runtime",
        "schema",
        "git",
    }
)


def _capability_id_from_item(item: operator_console.ActionItem) -> str | None:
    """Extract the trailing capability id from a ``capability:`` ActionItem.

    Returns None when the id is not a capability ActionItem.
    """

    if item.source != operator_console.SOURCE_CAPABILITY:
        return None
    prefix = f"{operator_console.SOURCE_CAPABILITY}:"
    if not item.id.startswith(prefix):
        return None
    return item.id[len(prefix) :] or None


def _reconcile_kind_from_item(item: operator_console.ActionItem) -> str | None:
    """Extract the drift kind from a ``reconcile:`` ActionItem."""

    if item.source != operator_console.SOURCE_RECONCILE:
        return None
    prefix = f"{operator_console.SOURCE_RECONCILE}:"
    if not item.id.startswith(prefix):
        return None
    return item.id[len(prefix) :] or None


def is_global_doctor_blocker(item: operator_console.ActionItem) -> bool:
    """True iff ``item`` is a doctor / install / install-drift class blocker.

    These are the rows of the relevance table marked "Relevant to every
    project" — Python runtime, schema support, DontPanic install drift,
    and git. The function trusts the F001 provider id shapes:

      * ``capability:<id>`` where ``<id>`` ∈ :data:`GLOBAL_DOCTOR_CAPABILITIES`
      * ``reconcile:<kind>`` — install drift always applies to every
        project (every project shares the operator's one install).

    The function never branches on ``band`` because severity is the
    operator console's concern, not relevance's.
    """

    cap_id = _capability_id_from_item(item)
    if cap_id is not None and cap_id in GLOBAL_DOCTOR_CAPABILITIES:
        return True
    if _reconcile_kind_from_item(item) is not None:
        # All reconcile drift kinds are install-state drift — universally
        # relevant. The F001 provider already filters out ``clean``.
        return True
    return False


def is_item_relevant_to_project(
    item: operator_console.ActionItem,
    declarations: ProjectDeclarations,
    *,
    capability_categories: dict[str, str] | None = None,
) -> bool:
    """Apply the F004 relevance table for one ActionItem.

    Precedence (highest to lowest):

      1. ``item.project_name`` set and equals ``declarations.project_name``
         → True (per-project item belongs to this project).
      2. ``item.project_name`` set but differs → False (per-project item
         belongs to a different project).
      3. Item is a doctor / install / drift class blocker
         (:func:`is_global_doctor_blocker`) → True (universally relevant).
      4. Item is a capability ActionItem:
           - declared in ``requires_capabilities[]`` / ``external_refs[]``
             → True.
           - the capability's category appears in
             ``referenced_adapter_categories`` → True.
           - otherwise → False.
      5. Architecture items without a ``project_name`` are unscoped —
         legacy single-repo behavior — and treated as relevant to the
         current project.
      6. Supervisor / gate items: relevant only when ``project_name``
         set; legacy items with no project_name are treated as relevant.

    ``capability_categories`` is an optional ``capability_id → category``
    map (typically derived from
    :func:`capabilities.load_capabilities`). When missing, the category
    branch is simply skipped.
    """

    # Per-project items: stable string equality wins over every other
    # rule. The dashboard tags every project-scoped ActionItem with
    # ``project_name`` at build time.
    if item.project_name is not None:
        return item.project_name == declarations.project_name

    # Global doctor / install / drift blockers — universally relevant.
    if is_global_doctor_blocker(item):
        return True

    # Capability + adapter rules: explicit declaration wins, then
    # category fallback.
    cap_id = _capability_id_from_item(item)
    if cap_id is not None:
        if declarations.declares(cap_id):
            return True
        if capability_categories is not None:
            category = capability_categories.get(cap_id)
            if category is not None and declarations.references_category(category):
                return True
        return False

    # Architecture without project_name: legacy single-repo emit. Treat
    # as relevant — operators running the V0 console without a registry
    # still want architecture warnings in their (one) project view.
    if item.source == operator_console.SOURCE_ARCHITECTURE:
        return True

    # Supervisor / gate / other sources: default to relevant when the
    # item is unscoped, matching the V0 single-repo behavior.
    return True


def filter_items_for_project(
    items: Iterable[operator_console.ActionItem],
    declarations: ProjectDeclarations,
    *,
    capability_categories: dict[str, str] | None = None,
) -> tuple[operator_console.ActionItem, ...]:
    """Return only the ActionItems relevant to ``declarations.project_name``.

    Deterministic: same input order is preserved.
    """

    return tuple(
        it
        for it in items
        if is_item_relevant_to_project(
            it, declarations, capability_categories=capability_categories
        )
    )


# ── Build-warning ActionItems ────────────────────────────────────────────


def build_warning_action_items(
    *,
    project_name: str,
    display_name: str,
    warnings: Iterable[str],
    skipped: bool,
    skipped_reason: str | None,
    warnings_path: Path | None = None,
    now_iso: str,
) -> tuple[operator_console.ActionItem, ...]:
    """Project a project's build warnings into ActionItem shape.

    F004 acceptance (4) requires skipped/malformed warnings to be
    surfaced in the dashboard, not just stderr. The persisted
    ``build-warnings.json`` already lives in the per-project cache; this
    helper translates it into the four-band taxonomy:

      * ``skipped=True`` (repo missing or inactive) → ``advisory`` —
        operator can re-enable / fix the path without blocking.
      * ``skipped=False`` with warnings → ``advisory`` — partial-build
        state, dashboard surface remains usable.

    Each warning becomes one ActionItem so the UI can render it
    individually. The id is prefixed with the project name to avoid
    collisions across the fleet.
    """

    items: list[operator_console.ActionItem] = []
    warnings_list = list(warnings)
    if skipped:
        reason = skipped_reason or "project build skipped"
        # Fold the build warnings into the skipped item's detail so the
        # operator sees the concrete cause ("repo_root does not exist:
        # /…") next to the short reason ("repo_root missing"). Keeping
        # it a single item preserves the build-warnings contract: one
        # skipped project → one advisory ActionItem.
        if warnings_list:
            detail = f"{reason}: {'; '.join(warnings_list)}"
        else:
            detail = reason
        items.append(
            operator_console.ActionItem(
                id=f"{operator_console.SOURCE_ARCHITECTURE}:build-warning:{project_name}:skipped",
                source=operator_console.SOURCE_ARCHITECTURE,
                band=operator_console.Band.ADVISORY,
                title=f"Project {display_name!r} build skipped",
                detail=detail,
                exact_command=None,
                automatable=False,
                human_required_reason="resolve project state",
                evidence_uri=str(warnings_path) if warnings_path is not None else None,
                updated_at=now_iso,
                project_name=project_name,
                display_name=display_name,
            )
        )
        return tuple(items)

    for idx, warning in enumerate(warnings_list):
        items.append(
            operator_console.ActionItem(
                id=f"{operator_console.SOURCE_ARCHITECTURE}:build-warning:{project_name}:{idx}",
                source=operator_console.SOURCE_ARCHITECTURE,
                band=operator_console.Band.ADVISORY,
                title=f"Build warning ({display_name})",
                detail=warning,
                exact_command=None,
                automatable=False,
                human_required_reason="review build warning",
                evidence_uri=str(warnings_path) if warnings_path is not None else None,
                updated_at=now_iso,
                project_name=project_name,
                display_name=display_name,
            )
        )
    return tuple(items)


__all__ = [
    "GLOBAL_DOCTOR_CAPABILITIES",
    "GLOBAL_DOCTOR_CATEGORIES",
    "ProjectDeclarations",
    "build_warning_action_items",
    "filter_items_for_project",
    "is_global_doctor_blocker",
    "is_item_relevant_to_project",
    "load_project_declarations",
]
