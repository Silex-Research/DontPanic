"""Per-project config at ``<project>/.dontpanic/dontpanic.json``.

The per-project config lives *inside the registered project*, not under
``~/.dontpanic/``. It is committable so a team can share defaults via
git; absence is the valid zero state. The legacy
``<project>/.jarvis/jarvis.json`` path remains read-compatible during
the staged rename. The lookup chain at dispatch time is:

    per-project ``.dontpanic/dontpanic.json`` (or legacy ``.jarvis/jarvis.json``)
      > global ``~/.dontpanic/config.json`` (or legacy ``~/.jarvis/config.json``)
      > hardcoded fallbacks (``implementer='claude'``, ``auditor='codex'``)

All three layers can independently leave a field unset (``None`` /
absent) and the resolver falls through to the next. The resolver
explicitly does NOT distinguish "explicit None" from "field absent" in
the per-project file: a JSON ``null`` and a missing key both mean "no
override at this layer, fall through to the next" (see
:func:`resolve_dispatch_defaults`). This is the simplest, single-meaning
interpretation; tests pin it.

Schema is Pydantic v2 with ``extra='forbid'`` so a stale config from an
older DontPanic cannot silently break a newer one — invalid files degrade
to ``None`` and emit a WARN.

Cross-validation at load time:
    - ``human_gates`` (when set) must intersect the canonical gate names
      from :mod:`models.plan_model`.HumanGate — unknown gate names fail
      validation (degraded to None + WARN by :func:`load_project_config`).
    - ``protected_paths`` must be a list of strings (Pydantic enforces
      the shape; values aren't path-checked here — that's the doctor's job).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from dontpanic_orchestrate import global_config as gc
from dontpanic_orchestrate import projects_registry as pr
from dontpanic_orchestrate.config.roles import RoleModelsConfig, RolesConfig
from dontpanic_orchestrate.config.runtime_evidence import RuntimeEvidenceConfig
from dontpanic_orchestrate.config.worker_profiles import WorkerProfile
from dontpanic_orchestrate.executors import AGENT_REGISTRY

_LOG = logging.getLogger(__name__)

PROJECT_CONFIG_DIRNAME = ".dontpanic"
"""Preferred directory under a project root that holds the per-project config."""

PROJECT_CONFIG_FILENAME = "dontpanic.json"
"""Preferred filename of the per-project config."""

LEGACY_PROJECT_CONFIG_DIRNAME = ".jarvis"
"""Legacy project config directory, read-compatible during migration."""

LEGACY_PROJECT_CONFIG_FILENAME = "jarvis.json"
"""Legacy project config filename, read-compatible during migration."""

DEFAULT_PLANS_DIR = "docs/plans"
"""Hardcoded default for ``plans_dir`` when neither per-project nor global
config sets it. Matches the existing on-disk layout used by every plan
shipped to date."""

DEFAULT_TARGET_ENV = "dev"
"""Hardcoded default for ``default_target_env`` when unset."""

FALLBACK_IMPLEMENTER = "claude"
FALLBACK_AUDITOR = "codex"


def _known_gate_names() -> set[str]:
    """Return the canonical set of gate name strings declared by the
    plan model's ``HumanGate`` enum. Imported lazily to avoid forcing the
    plan-loader's schema-discovery to run at import time."""
    # plan_loader's import side-effect adds the schemas dir to sys.path;
    # we depend on that being run before we import the enum. The supervisor
    # always imports plan_loader, so by the time per-project config is
    # consulted the path is populated. Order matters: keep plan_loader first
    # so its `_find_schemas_dir()` runs before models.plan_model resolves.
    from dontpanic_orchestrate import plan_loader  # noqa: F401, I001

    from models.plan_model import HumanGate  # noqa: I001

    return {g.value for g in HumanGate}


class ProjectConfig(BaseModel):
    """Per-project defaults.

    All fields are optional — the empty config is the valid zero state.
    Field names mirror the schema from F003's plan description: ``implementer``,
    ``auditor`` (NOT ``default_implementer`` / ``default_auditor`` — that's
    the global-config naming, retained there for backward compatibility).
    """

    model_config = ConfigDict(extra="forbid")

    implementer: str | None = None
    """Per-project implementer agent. When None or the field is absent,
    falls through to global ``default_implementer`` then to the hardcoded
    fallback (``'claude'``)."""

    auditor: str | None = None
    """Per-project auditor agent. Mirrors ``implementer`` semantics; the
    hardcoded fallback is ``'codex'``."""

    plans_dir: str = DEFAULT_PLANS_DIR
    """Project-relative path to the plans directory (e.g. ``docs/plans``).
    The default matches the convention every shipped plan uses; teams that
    keep plans elsewhere set this to override at load time."""

    default_target_env: str = DEFAULT_TARGET_ENV
    """Project-default ``target_env`` for plans that don't declare one in
    their own frontmatter. Plans that DO declare ``target_env`` always win
    over this."""

    human_gates: list[str] | None = None
    """Per-project default human gates. When set, must intersect the
    canonical gate names from ``HumanGate``."""

    protected_paths: list[str] | None = None
    """Per-project default ``protected_paths`` list (paths that are off-
    limits for the implementer to edit)."""

    roles: RolesConfig | None = None
    """Plan G F006 / D013 — per-project agent role names. Canonical
    write target for ``dontpanic project config set roles.<role>
    <agent>``. Wins over the legacy top-level ``implementer`` /
    ``auditor`` fields when both are set; falls through to global per
    :func:`config.resolvers.resolve_role`."""

    models: RoleModelsConfig | None = None
    """F012 (D1/D011) — per-project per-role vendor model-id overrides.
    Wins over the global ``models`` block; resolved by
    :func:`config.resolvers.resolve_model`. Unset roles keep the harness
    CLI default."""

    worker_profiles: dict[str, WorkerProfile] | None = None
    """F013 (D2) — per-project named worker profiles. Overlaid atop the
    global ``worker_profiles`` block per id (project wins); resolution +
    role/capability gates live in
    :mod:`dontpanic_orchestrate.worker_profiles`."""

    runtime_evidence: RuntimeEvidenceConfig | None = None
    """Plan G F006 / D015 — project-scoped runtime evidence defaults
    (web base URL, iOS scheme, Android package, backend provider).
    **Project-scoped only**; global config never carries these values
    because runtime targets are project-specific by definition."""

    @field_validator("human_gates")
    @classmethod
    def _validate_human_gates(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        known = _known_gate_names()
        unknown = [g for g in v if g not in known]
        if unknown:
            raise ValueError(f"unknown human_gates {unknown!r}; valid gates: {sorted(known)}")
        return v


def project_config_path(project_path: Path) -> Path:
    """Preferred path to ``dontpanic.json`` under ``<project>/.dontpanic/``.

    ``project_path`` must be a project ROOT (the path stored in the
    registry), not the per-project ``.dontpanic`` dir. The function does NOT
    create the dir — :func:`scaffold_empty_config` is the writer."""
    return project_path / PROJECT_CONFIG_DIRNAME / PROJECT_CONFIG_FILENAME


def legacy_project_config_path(project_path: Path) -> Path:
    """Legacy path to ``jarvis.json`` under ``<project>/.jarvis/``."""
    return project_path / LEGACY_PROJECT_CONFIG_DIRNAME / LEGACY_PROJECT_CONFIG_FILENAME


def project_config_read_path(project_path: Path) -> Path:
    """Return the config path to read.

    Preferred ``.dontpanic/dontpanic.json`` wins when present. Legacy
    ``.jarvis/jarvis.json`` is read when the preferred file is absent.
    Missing config returns the preferred path so diagnostics and writers
    point new projects at the new shape.
    """
    preferred = project_config_path(project_path)
    if preferred.is_file():
        return preferred
    legacy = legacy_project_config_path(project_path)
    if legacy.is_file():
        return legacy
    return preferred


def load_project_config(project_path: Path) -> ProjectConfig | None:
    """Load the per-project config.

    Returns:
        - ``None`` if the file is absent (the valid zero state — projects
          are not required to ship a per-project config).
        - ``None`` after a WARN if the file is unreadable / invalid JSON
          / fails schema validation (extra fields, unknown gate names,
          wrong types). Degrade-to-None means dispatch silently falls
          through to global config in that case; the doctor surfaces the
          WARN explicitly so the operator sees it.
        - A populated :class:`ProjectConfig` on the happy path.

    Never raises — config-load errors are operator-fixable in a separate
    pass and must not block dispatch.
    """
    path = project_config_read_path(project_path)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning(
            "per-project config at %s is unreadable or invalid JSON (%s); "
            "falling through to global config",
            path,
            exc,
        )
        return None
    try:
        return ProjectConfig.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError or similar
        _LOG.warning(
            "per-project config at %s failed schema validation (%s); "
            "falling through to global config",
            path,
            exc,
        )
        return None


def scaffold_empty_config(project_path: Path) -> Path:
    """Write an empty ``{}`` per-project config at
    ``<project>/.dontpanic/dontpanic.json``. Used by ``dontpanic projects add
    --init-config`` when the operator opts in. Refuses to overwrite an
    existing file — operators editing their config shouldn't have it
    silently flattened by a re-add."""
    path = project_config_path(project_path)
    legacy = legacy_project_config_path(project_path)
    if path.exists() or legacy.exists():
        existing = path if path.exists() else legacy
        raise FileExistsError(
            f"per-project config already exists at {existing}; refusing to overwrite"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    return path


def resolve_project_path(name_or_path: str) -> tuple[Path, str | None] | None:
    """Resolve a CLI-supplied project identifier to an absolute project
    path + (optional) registered name.

    The CLI accepts both shapes: ``dontpanic dispatch myproject`` (registered
    name) and ``dontpanic dispatch /abs/path/to/proj`` (filesystem path).
    Distinguishing them is structural, not heuristic:

      1. If the input matches the project-name regex (D003) AND the
         registry contains an entry by that name, resolve to the
         registered ``ProjectEntry.path``. This is the *primary* path —
         the registry is the source of truth.
      2. Else if the input is a path that exists as a directory on disk,
         resolve to ``Path(input).expanduser().resolve()``.
      3. Else return ``None``. The CLI must hard-refuse with exit 2 +
         clear message — there is NO silent ``Path.cwd()`` fallback.

    Note: a string can match both the name regex AND look path-shaped
    (e.g. ``foo`` is a valid name AND a valid relative path). The
    registry-first ordering disambiguates: a registered name always wins
    over a coincidental directory in cwd. Callers who want to force the
    path interpretation must pass a path that contains a separator.

    Returns:
        ``(absolute_path, registered_name_or_None)`` on success, ``None``
        when the identifier resolves to neither a registered project nor
        an existing directory.
    """
    # Step 1: registry lookup by exact name. Run this FIRST because the
    # registry is the source of truth — a registered name always wins
    # over a coincidental matching directory.
    if pr.PROJECT_NAME_PATTERN.fullmatch(name_or_path):
        entry = pr.find_project(name_or_path)
        if entry is not None:
            return Path(entry.path).expanduser().resolve(), entry.name

    # Step 2: path-shaped fallback. Only when the input contains a path
    # separator OR resolves to an existing directory. Bare names that
    # don't match the registry never resolve here even if a directory
    # of that name exists in cwd — the operator must register it first.
    if "/" in name_or_path or name_or_path.startswith("~") or name_or_path.startswith("."):
        candidate = Path(name_or_path).expanduser().resolve()
        if candidate.is_dir():
            return candidate, None

    return None


def find_project_for_plan_dir(plan_dir: Path) -> tuple[Path, str] | None:
    """Auto-detect the registered project that contains ``plan_dir``.

    Walks the registry and returns the first entry whose ``path`` is an
    ancestor of (or equal to) ``plan_dir``. When multiple registered
    projects could contain the plan_dir (e.g., a project inside another
    project), the deepest match wins so the most specific project context
    applies.

    Returns:
        ``(absolute_project_path, registered_name)`` on a match, ``None``
        when no registered project contains the plan_dir.

    This is the boundary that turns "where does the plan live on disk"
    into "which per-project config should the supervisor consult". It is
    intentionally registry-driven — we never fall back to walking up
    looking for a stray ``.dontpanic/`` or ``.jarvis/`` directory, because an unregistered
    project should not silently influence dispatch.
    """
    plan_dir_resolved = plan_dir.resolve()
    reg = pr.load_registry()
    best: tuple[Path, str] | None = None
    best_depth = -1
    for entry in reg.projects:
        proj_path = Path(entry.path).expanduser().resolve()
        try:
            plan_dir_resolved.relative_to(proj_path)
        except ValueError:
            continue
        depth = len(proj_path.parts)
        if depth > best_depth:
            best = (proj_path, entry.name)
            best_depth = depth
    return best


def resolve_dispatch_defaults(
    project_path: Path | None,
    *,
    fallback_implementer: str = FALLBACK_IMPLEMENTER,
    fallback_auditor: str = FALLBACK_AUDITOR,
) -> dict[str, Any]:
    """Resolve effective implementer / auditor / plans_dir / target_env at
    dispatch time by walking the precedence chain (D004):

        1. per-project ``<project>/.dontpanic/dontpanic.json``  (when project_path is set)
        2. global ``~/.dontpanic/config.json``
        3. hardcoded fallbacks (``'claude'`` / ``'codex'`` / ``'docs/plans'`` / ``'dev'``)

    A field set to ``None`` (or absent) at one layer falls through to the
    next layer. There is intentionally no way to express "explicitly None,
    don't fall through" — that semantic distinction would create a silent-
    drift bug class with no real-world use case.

    ``project_path`` may be ``None`` (host-local plans / no registered
    project context) — the resolver then walks just (global, fallback).
    Returns a dict with non-None values for ``implementer``, ``auditor``,
    ``plans_dir``, ``target_env``, and (possibly None) ``human_gates`` /
    ``protected_paths``.
    """
    project_cfg: ProjectConfig | None = None
    if project_path is not None:
        project_cfg = load_project_config(project_path)
    global_cfg = gc.load_config()

    # F013 i1 (codex audit i0 high finding): the canonical ``roles.<role>``
    # block must reach dispatch through THIS resolver too, not only through
    # config.resolvers.resolve_role — dispatch_volley and the dispatch-from-
    # plan preflight both key off resolve_dispatch_defaults. Within a layer
    # the canonical roles entry wins over the legacy field, matching
    # config.resolvers._role_from_layer_cfg. Lazy import: resolvers imports
    # this module at module level.
    from dontpanic_orchestrate.config.roles import role_name

    def _layer_role(cfg: Any, canonical: str, legacy_attr: str) -> str | None:
        if cfg is None:
            return None
        roles = getattr(cfg, "roles", None)
        if roles is not None:
            v = role_name(getattr(roles, canonical, None))
            if v:
                return v
        return getattr(cfg, legacy_attr, None) or None

    impl = (
        _layer_role(project_cfg, "implementer", "implementer")
        or _layer_role(global_cfg, "implementer", "default_implementer")
        or fallback_implementer
    )
    aud = (
        _layer_role(project_cfg, "auditor", "auditor")
        or _layer_role(global_cfg, "auditor", "default_auditor")
        or fallback_auditor
    )
    plans_dir = (project_cfg.plans_dir if project_cfg is not None else None) or DEFAULT_PLANS_DIR
    target_env = (
        project_cfg.default_target_env if project_cfg is not None else None
    ) or DEFAULT_TARGET_ENV
    human_gates = project_cfg.human_gates if project_cfg is not None else None
    protected_paths = project_cfg.protected_paths if project_cfg is not None else None

    return {
        "implementer": impl,
        "auditor": aud,
        "plans_dir": plans_dir,
        "target_env": target_env,
        "human_gates": human_gates,
        "protected_paths": protected_paths,
    }


def is_known_agent(name: str) -> bool:
    """Whether ``name`` is a registered executor in :data:`AGENT_REGISTRY`.
    Used by the doctor to FAIL on per-project configs that name an unknown
    implementer / auditor — typos there silently break dispatch otherwise."""
    return name in AGENT_REGISTRY


__all__ = [
    "DEFAULT_PLANS_DIR",
    "DEFAULT_TARGET_ENV",
    "FALLBACK_AUDITOR",
    "FALLBACK_IMPLEMENTER",
    "LEGACY_PROJECT_CONFIG_DIRNAME",
    "LEGACY_PROJECT_CONFIG_FILENAME",
    "PROJECT_CONFIG_DIRNAME",
    "PROJECT_CONFIG_FILENAME",
    "ProjectConfig",
    "is_known_agent",
    "legacy_project_config_path",
    "load_project_config",
    "project_config_read_path",
    "project_config_path",
    "resolve_dispatch_defaults",
    "resolve_project_path",
    "scaffold_empty_config",
]
