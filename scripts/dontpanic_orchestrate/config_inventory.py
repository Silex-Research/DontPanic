"""config_inventory — the configuration inventory and setup cockpit.

Plan 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 F008.

A human or interactive agent should be able to run ONE command and see every
DontPanic configuration surface — global config, per-project config, project
registry, agent manifest, roles, runtime evidence, human gates / protected
paths / plans_dir / default target env, quota caps / calibration / state,
circuit breakers, notifications, dashboard, capabilities / adapters, MCP,
environments / Firebase target, secrets / auth, install snapshot / reconcile,
and PM-tool credentials — with each surface's status, whether it is editable,
the exact safe command that routes through an existing validated CLI surface,
and (for secrets / auth / provider setup) the human-required steps with NO
secret values ever echoed.

The module is structured as a model (:class:`InventoryItem`), a set of pure-ish
read-only *providers* (one per surface, each defensive: a failing reader
degrades to ``UNKNOWN`` rather than crashing the whole inventory), an assembler
(:func:`collect_inventory`) that attaches exactly one response-level
:class:`DashboardHint` when any item needs human input, a dashboard projection
(:func:`to_dashboard_state`) that renders the same data as Settings / Setup
cards, and a setup/update planner (:func:`build_setup_plan`) that emits typed
``ActionChoice`` records (reusing F007's vocabulary) or a draft DontPanic plan
for the incomplete setup areas.

Secret safety (AC5): secret-scope providers never put a secret value in
``current_value_summary`` — they report ``configured`` / ``not configured``
only. As defense in depth, every string surfaced to a consumer is passed
through :func:`state_projection.scrub_secrets` before it leaves this module.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

# ─────────────────────────────── vocabulary ────────────────────────────────


class Scope(str, Enum):
    """Where a config surface lives. Consumers branch / group on these."""

    MACHINE = "machine"      # per-user / per-install (~/.dontpanic)
    PROJECT = "project"      # per-repo (<repo>/.dontpanic)
    PLAN = "plan"            # per-plan runtime state
    CAPABILITY = "capability"  # optional adapters / integrations
    SECRET = "secret"        # noqa: S105 — enum label, not a credential value
    RUNTIME = "runtime"      # runtime evidence / live execution targets


class Status(str, Enum):
    """Status band of one inventory item. Drives Settings vs Setup grouping."""

    OK = "ok"                              # configured and valid
    NEEDS_SETUP = "needs_setup"            # required, not yet configured
    MISSING = "missing"                    # required artifact absent
    OPTIONAL_UNCONFIGURED = "optional_unconfigured"  # optional, not set up
    HUMAN_REQUIRED = "human_required"      # only a human can complete it
    UNKNOWN = "unknown"                    # reader failed / indeterminate


class UnresolvedProjectError(ValueError):
    """Raised when an explicit ``--project NAME|PATH`` selector resolves to
    neither a registered project nor an existing directory.

    Mirrors ``project_config.resolve_project_path``'s contract that callers
    MUST hard-refuse unresolved selectors (D003): silently degrading an
    explicitly-requested project to machine-only scope would report an
    optimistic, wrong inventory for a project the caller never asked about.
    The CLI translates this into exit 2 + a clear message.
    """

    def __init__(self, selector: str) -> None:
        self.selector = selector
        super().__init__(
            f"project {selector!r} is not a registered project name and is "
            f"not an existing directory on disk; refusing to fall back to "
            f"machine-only inventory. Register it with `dontpanic projects "
            f"add --onboard` or pass an existing project path."
        )


# Statuses that the setup planner treats as "incomplete work".
_INCOMPLETE_STATUSES: frozenset[Status] = frozenset(
    {Status.NEEDS_SETUP, Status.MISSING, Status.HUMAN_REQUIRED}
)


DASHBOARD_HINT_ID = "config-inventory-dashboard"
DASHBOARD_START_COMMAND = "dontpanic dashboard serve"


# ───────────────────────── response-level dashboard hint ────────────────────


@dataclass(frozen=True)
class DashboardHint:
    """The single response-level dashboard pointer (AC6).

    Exactly one of these is attached to an :class:`Inventory` when any item is
    human-required. ``is_running`` selects which text the renderer shows: the
    active URL (running) or the start command (not running). Individual items
    reference it by :data:`DASHBOARD_HINT_ID` via ``dashboard_hint_ref`` — they
    never embed this text themselves, so it appears exactly once per response.
    """

    is_running: bool
    url: str | None = None
    start_command: str = DASHBOARD_START_COMMAND
    hint_id: str = DASHBOARD_HINT_ID

    def text(self) -> str:
        # Single-sourced wording: delegate to the canonical dashboard helper
        # rather than re-spelling the hint here (codex F010 i1).
        from dontpanic_orchestrate import dashboard

        return dashboard.render_hint_line(
            is_running=self.is_running,
            url=self.url,
            start_command=self.start_command,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hint_id": self.hint_id,
            "is_running": self.is_running,
            "active_url": self.url if self.is_running else None,
            "start_command": None if self.is_running else self.start_command,
            "text": self.text(),
        }


# ──────────────────────────────── InventoryItem ─────────────────────────────


@dataclass(frozen=True)
class InventoryItem:
    """One configuration surface and its status.

    ``safe_command`` is populated only when there is an exact command that
    routes a safe edit through an existing validated surface (``roles set``,
    ``project config set``, ``capabilities setup``, ``quota-caps init``,
    ``calibrate-claude``, ``reconcile homes``, ``projects add --onboard``).
    Secrets / auth never carry a ``safe_command`` — they are ``human_required``
    with verification steps only.

    ``dashboard_mutation_shape`` describes how the dashboard can offer the edit:
    ``None`` for human-required / read-only, else a typed dict the UI renders as
    an editable card control.

    ``dashboard_hint_ref`` carries the shared hint id (never the full text) when
    the item is human-required, so the dashboard pointer renders once.
    """

    id: str
    title: str
    scope: Scope
    status: Status
    editable: bool
    human_required: bool
    optional: bool
    current_value_summary: str
    owner_file_or_env: str
    safe_command: str | None = None
    dashboard_mutation_shape: dict[str, Any] | None = None
    risks: str | None = None
    doctor_probes: tuple[str, ...] = ()
    dashboard_hint_ref: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        # Invariant (AC5 + audit finding): ``safe_command`` is reserved for an
        # EXACT, runnable, validated edit command. Anything with a ``<...>``
        # placeholder is a template and must live in
        # ``dashboard_mutation_shape.command_template`` instead — a placeholder
        # command is not safe to hand a consumer to run verbatim.
        if self.safe_command is not None:
            if "<" in self.safe_command or ">" in self.safe_command:
                raise ValueError(
                    f"safe_command for {self.id!r} contains a placeholder "
                    f"({self.safe_command!r}); put templates in "
                    "dashboard_mutation_shape.command_template, not safe_command"
                )
            if not self.safe_command.startswith("dontpanic "):
                raise ValueError(
                    f"safe_command for {self.id!r} must invoke the dontpanic "
                    f"CLI, got {self.safe_command!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        from dontpanic_orchestrate import state_projection

        scrub = state_projection.scrub_secrets
        return {
            "id": self.id,
            "title": self.title,
            "scope": self.scope.value,
            "status": self.status.value,
            "editable": self.editable,
            "human_required": self.human_required,
            "optional": self.optional,
            "current_value_summary": scrub(self.current_value_summary),
            "owner_file_or_env": self.owner_file_or_env,
            "safe_command": scrub(self.safe_command),
            "dashboard_mutation_shape": self.dashboard_mutation_shape,
            "risks": scrub(self.risks),
            "doctor_probes": list(self.doctor_probes),
            "dashboard_hint_ref": self.dashboard_hint_ref,
            "detail": scrub(self.detail),
        }

    @property
    def is_incomplete(self) -> bool:
        return self.status in _INCOMPLETE_STATUSES


@dataclass(frozen=True)
class Inventory:
    """The full inventory for one (optionally project-scoped) invocation."""

    project_name: str | None
    project_path: str | None
    items: tuple[InventoryItem, ...]
    dashboard_hint: DashboardHint | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "project_path": self.project_path,
            "items": [i.to_dict() for i in self.items],
            # AC6: the dashboard_hint is response-level and appears exactly once.
            "dashboard_hint": self.dashboard_hint.to_dict()
            if self.dashboard_hint
            else None,
        }

    def incomplete_items(self) -> list[InventoryItem]:
        return [i for i in self.items if i.is_incomplete]


# ─────────────────────────────── provider context ──────────────────────────


@dataclass(frozen=True)
class InventoryContext:
    """Resolved scope for the providers.

    ``project_path`` / ``project_name`` are set when ``--project`` resolved or a
    cwd-local ``.dontpanic`` exists; providers that are project-scoped degrade
    gracefully (status ``UNKNOWN`` with an explanatory summary) when no project
    is in scope.
    """

    project_path: Path | None = None
    project_name: str | None = None


# ───────────────────────────────── providers ────────────────────────────────
#
# Every provider takes the context and returns ONE InventoryItem. Each wraps its
# reader in try/except so a single broken surface never sinks the inventory — a
# fresh install with no global config, no registry, and no capability cache must
# still produce a complete, usable inventory (AC4 "do not block core use").


def _probe_loadable(path: Path, model: Any) -> tuple[bool, str | None]:
    """Probe whether a present config ``path`` actually parses + validates.

    The config loaders (``global_config.load_config`` /
    ``project_config.load_project_config``) deliberately NEVER raise — they
    log a warning and degrade invalid JSON / schema failures to an empty
    config so the CLI still starts. That degradation is correct for the CLI
    but wrong for the inventory's *status*: a present-but-broken file must
    report non-ok, not `ok` (AC2c/AC2d). This re-runs the parse + validate the
    loader swallows and returns ``(False, reason)`` when either step fails, so
    the providers can distinguish absent from present-but-unloadable.
    """
    import json

    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return False, type(exc).__name__
    try:
        model.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 — pydantic.ValidationError or similar
        return False, type(exc).__name__
    return True, None


@dataclass(frozen=True)
class StatusFacts:
    """Normalized facts about ONE config surface, fed to :func:`derive_status`.

    AC2e: the non-optimistic-status invariant is implemented as a SINGLE shared
    status-derivation helper applied uniformly by EVERY provider — not per-
    provider ad-hoc ``status=Status.OK if … else …`` branches. Every provider
    reduces its underlying read to these four booleans and routes them through
    :func:`derive_status`, so "present but invalid / incomplete / unloadable ⇒
    non-ok" holds class-wide *by construction*, not because each provider
    happens to repeat the same check.

    Field semantics (each later field is only consulted once the earlier ones
    hold, mirroring the derivation order):

    - ``present``: the underlying artifact exists / is configured at all.
    - ``loadable``: a PRESENT artifact parses + structurally validates. A
      present-but-unloadable file is a hard defect regardless of optionality.
    - ``valid``: a present + loadable artifact is semantically runnable /
      healthy (roles in AGENT_REGISTRY, breaker not tripped, calibration +
      observed state present, registered project paths exist, an adapter is
      ready, …).
    - ``human_required``: an ABSENT required secret only a human can supply.
    """

    optional: bool
    present: bool
    loadable: bool = True
    valid: bool = True
    human_required: bool = False


def derive_status(facts: StatusFacts) -> Status:
    """The ONE shared status-derivation rule every provider routes through (AC2e).

    A present-but-unloadable artifact is a hard defect (``NEEDS_SETUP``) even for
    optional surfaces — the operator must fix or remove it. An absent surface is
    ``HUMAN_REQUIRED`` for a required secret, ``OPTIONAL_UNCONFIGURED`` when
    optional, else ``NEEDS_SETUP``. A present + loadable but semantically
    invalid/incomplete surface degrades softly to ``OPTIONAL_UNCONFIGURED`` when
    optional (never blocks core use, AC4) and to ``NEEDS_SETUP`` when required.
    Only a present + loadable + valid surface is ``OK`` — so an invalid /
    incomplete / unrunnable underlying state can NEVER report ``ok``.
    """
    if facts.present and not facts.loadable:
        return Status.NEEDS_SETUP
    if not facts.present:
        if facts.human_required:
            return Status.HUMAN_REQUIRED
        return Status.OPTIONAL_UNCONFIGURED if facts.optional else Status.NEEDS_SETUP
    if not facts.valid:
        return Status.OPTIONAL_UNCONFIGURED if facts.optional else Status.NEEDS_SETUP
    return Status.OK


def _safe(fn: Callable[[], InventoryItem], *, fallback: InventoryItem) -> InventoryItem:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — degrade, never crash the inventory
        return InventoryItem(
            id=fallback.id,
            title=fallback.title,
            scope=fallback.scope,
            status=Status.UNKNOWN,
            editable=fallback.editable,
            human_required=fallback.human_required,
            optional=fallback.optional,
            current_value_summary=f"could not read: {type(exc).__name__}",
            owner_file_or_env=fallback.owner_file_or_env,
            safe_command=fallback.safe_command,
            doctor_probes=fallback.doctor_probes,
        )


def provider_global_config(ctx: InventoryContext) -> InventoryItem:
    from dontpanic_orchestrate import global_config as gc

    def _build() -> InventoryItem:
        path = gc.config_path()
        # AC2c/AC2d — status must NOT be optimistic. ``load_config`` swallows
        # invalid-JSON / schema-validation failures and degrades to an empty
        # config, so keying status off file existence alone reports `ok` for a
        # present-but-UNLOADABLE config. Probe loadability explicitly: a file
        # that exists but does not parse + validate is non-ok (the operator must
        # fix it), distinct from the absent first-run zero state.
        if not path.is_file():
            return InventoryItem(
                id="global_config",
                title="Global config (per-user defaults)",
                scope=Scope.MACHINE,
                status=derive_status(StatusFacts(optional=False, present=False)),
                editable=True,
                human_required=False,
                optional=False,
                current_value_summary="no ~/.dontpanic/config.json — using hardcoded fallbacks",
                owner_file_or_env=str(path),
                safe_command=None,
                dashboard_mutation_shape={
                    "type": "role_picker",
                    "command_template": "dontpanic roles set <role> <executor> --global",
                    "roles": ["implementer", "auditor", "goal_auditor"],
                },
                risks="Wrong implementer/auditor names dispatch the wrong executor.",
                doctor_probes=("doctor --agent",),
            )
        loadable, load_err = _probe_loadable(path, gc.GlobalConfig)
        if not loadable:
            return InventoryItem(
                id="global_config",
                title="Global config (per-user defaults)",
                scope=Scope.MACHINE,
                status=derive_status(
                    StatusFacts(optional=False, present=True, loadable=False)
                ),
                editable=True,
                human_required=False,
                optional=False,
                current_value_summary=(
                    f"config present at {path.name} but UNLOADABLE "
                    f"({load_err}); fix the file or re-init"
                ),
                owner_file_or_env=str(path),
                safe_command=None,
                dashboard_mutation_shape={
                    "type": "role_picker",
                    "command_template": "dontpanic roles set <role> <executor> --global",
                    "roles": ["implementer", "auditor", "goal_auditor"],
                },
                risks="An unloadable config silently degrades to hardcoded fallbacks.",
                doctor_probes=("doctor --agent",),
            )
        from dontpanic_orchestrate import agent_surface

        cfg = gc.load_config()
        impl = cfg.default_implementer or (cfg.roles.implementer if cfg.roles else None)
        aud = cfg.default_auditor or (cfg.roles.auditor if cfg.roles else None)
        goal_aud = getattr(cfg.roles, "goal_auditor", None) if cfg.roles else None
        # AC2b/AC2c — status must NOT be optimistic (audit finding, codex i1).
        # A worker *default* (implementer / auditor / goal_auditor) whose value
        # is not in AGENT_REGISTRY is operator-only — dispatch would refuse it —
        # so the global config surface is unrunnable and must report non-ok, the
        # same way ``provider_roles`` does for the resolved chain. A default of
        # ``None`` means "use the hardcoded worker fallback" (claude/codex) and
        # is fine; only an explicitly-set non-worker value is a defect.
        configured_defaults = [
            (role, value)
            for role, value in (
                ("implementer", impl),
                ("auditor", aud),
                ("goal_auditor", goal_aud),
            )
            if value
        ]
        unrunnable = [
            (role, value)
            for role, value in configured_defaults
            if not agent_surface.is_worker_capable(value)
        ]
        base_summary = (
            f"implementer={impl or '(fallback claude)'}, auditor={aud or '(fallback codex)'}"
        )
        if unrunnable:
            bad = ", ".join(f"{role}={value}" for role, value in unrunnable)
            summary = (
                f"global default(s) not a worker executor: {bad} "
                f"(not in AGENT_REGISTRY). Reassign with `dontpanic roles set "
                f"<role> <executor> --global`. Resolved: {base_summary}"
            )
        else:
            summary = base_summary
        return InventoryItem(
            id="global_config",
            title="Global config (per-user defaults)",
            scope=Scope.MACHINE,
            # OK only when every explicitly-set worker default is registry-backed
            # (routed through the shared helper: present + loadable + valid → OK).
            status=derive_status(
                StatusFacts(
                    optional=False, present=True, loadable=True, valid=not unrunnable
                )
            ),
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary=summary,
            owner_file_or_env=str(path),
            # Role *defaults* are edited through the validated `roles set`
            # route (which guards the executor against AGENT_REGISTRY), never
            # raw `config set roles.*`. The template lives in the mutation
            # shape; safe_command stays None because there is no single
            # placeholder-free edit command for this surface.
            safe_command=None,
            dashboard_mutation_shape={
                "type": "role_picker",
                "command_template": "dontpanic roles set <role> <executor> --global",
                "roles": ["implementer", "auditor", "goal_auditor"],
            },
            risks="Wrong implementer/auditor names dispatch the wrong executor.",
            doctor_probes=("doctor --agent",),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="global_config",
            title="Global config (per-user defaults)",
            scope=Scope.MACHINE,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary="",
            owner_file_or_env="~/.dontpanic/config.json",
        ),
    )


def provider_project_config(ctx: InventoryContext) -> InventoryItem:
    from dontpanic_orchestrate import project_config as pc

    def _build() -> InventoryItem:
        if ctx.project_path is None:
            return InventoryItem(
                id="project_config",
                title="Project config",
                scope=Scope.PROJECT,
                status=Status.UNKNOWN,
                editable=True,
                human_required=False,
                optional=False,
                current_value_summary="no project in scope — pass --project NAME|PATH",
                owner_file_or_env="<repo>/.dontpanic/dontpanic.json",
                safe_command="dontpanic project config init",
            )
        read_path = pc.project_config_read_path(ctx.project_path)
        # AC2c/AC2d — ``load_project_config`` returns None for BOTH an absent
        # file and a present-but-unloadable one, so we cannot key status off the
        # loader result alone. Use file presence to distinguish: a file that
        # exists but fails to load is non-ok (UNLOADABLE), never `ok`.
        present = read_path.is_file()
        cfg = pc.load_project_config(ctx.project_path)
        if present and cfg is None:
            return InventoryItem(
                id="project_config",
                title="Project config",
                scope=Scope.PROJECT,
                status=derive_status(
                    StatusFacts(optional=False, present=True, loadable=False)
                ),
                editable=True,
                human_required=False,
                optional=False,
                current_value_summary=(
                    f"project config present at {read_path.name} but UNLOADABLE "
                    "(invalid JSON or schema); fix the file or re-init"
                ),
                owner_file_or_env=str(read_path),
                safe_command=None,
                dashboard_mutation_shape={
                    "type": "key_value",
                    "command_template": "dontpanic project config set <key> <value>",
                },
                risks="An unloadable project config silently inherits global defaults.",
                doctor_probes=("doctor --project",),
            )
        summary = (
            f"implementer={cfg.implementer or '(inherit)'}, auditor={cfg.auditor or '(inherit)'}"
            if (present and cfg is not None)
            else "no per-project config — inherits global defaults"
        )
        return InventoryItem(
            id="project_config",
            title="Project config",
            scope=Scope.PROJECT,
            status=derive_status(
                StatusFacts(optional=False, present=present, loadable=True)
            ),
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary=summary,
            owner_file_or_env=str(read_path),
            # Per-key edits need a <key> <value> argument pair, so the routing
            # is a template (mutation shape), not a runnable safe_command.
            safe_command=None,
            dashboard_mutation_shape={
                "type": "key_value",
                "command_template": "dontpanic project config set <key> <value>",
            },
            doctor_probes=("doctor --project",),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="project_config",
            title="Project config",
            scope=Scope.PROJECT,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary="",
            owner_file_or_env="<repo>/.dontpanic/dontpanic.json",
        ),
    )


def provider_projects_registry(ctx: InventoryContext) -> InventoryItem:
    from dontpanic_orchestrate import projects_registry as pr

    def _build() -> InventoryItem:
        reg = pr.load_registry()
        count = len(reg.projects)
        path = pr.registry_path()
        # AC2c / audit finding (codex i0): status must NOT be optimistic. A
        # registry that lists projects whose on-disk path no longer exists (or is
        # not a directory) is STALE — dispatch against those entries would fail —
        # so it must report non-ok, never `ok N project(s) registered`. A project
        # is "runnable" only when its registered path still resolves to a
        # directory on disk; ``valid`` is False when any entry is stale.
        stale = [
            p for p in reg.projects if not Path(p.path).expanduser().is_dir()
        ]
        if not count:
            summary = "0 project(s) registered"
        elif stale:
            bad = ", ".join(f"{p.name}→{p.path}" for p in stale)
            summary = (
                f"{count} project(s) registered but {len(stale)} STALE "
                f"(path missing): {bad}. Re-add with `dontpanic projects add "
                f"<name> <path> --onboard` or remove the stale entry."
            )
        else:
            summary = f"{count} project(s) registered"
        return InventoryItem(
            id="projects_registry",
            title="Project registry",
            scope=Scope.MACHINE,
            status=derive_status(
                StatusFacts(
                    optional=False,
                    present=bool(count),
                    loadable=True,
                    valid=not stale,
                )
            ),
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary=summary,
            owner_file_or_env=str(path),
            # `projects add` needs <name> <path> arguments — a template, not a
            # runnable command; safe_command stays None.
            safe_command=None,
            dashboard_mutation_shape={
                "type": "command_template",
                "command_template": "dontpanic projects add <name> <path> --onboard",
            },
            doctor_probes=("doctor --project",),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="projects_registry",
            title="Project registry",
            scope=Scope.MACHINE,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary="",
            owner_file_or_env="~/.dontpanic/projects.json",
        ),
    )


def provider_agent_manifest(ctx: InventoryContext) -> InventoryItem:
    from dontpanic_orchestrate import agent_manifest as am

    def _build() -> InventoryItem:
        path = am.manifest_path()
        present = path.is_file()
        # AC2c/AC2d (audit finding, codex i0): ``load_manifest`` returns None for
        # BOTH an absent file AND a present-but-unloadable one (it swallows
        # invalid-JSON / schema errors and degrades to None). Keying status off
        # the load result alone reports the same NEEDS_SETUP for a malformed
        # manifest as for a fresh install, but more importantly an OK must never
        # ride a present-but-broken file. Use file presence to distinguish:
        # present + unloadable → non-ok (UNLOADABLE), absent → non-ok (setup).
        manifest = am.load_manifest()
        loadable = (manifest is not None) if present else True
        if present and not loadable:
            summary = (
                f"agent-manifest present at {path.name} but UNLOADABLE "
                "(invalid JSON or schema); fix the file or re-run `dontpanic "
                "manifest init`"
            )
        elif present:
            cmds = getattr(manifest, "supported_commands", None) or []
            summary = f"manifest present ({len(cmds)} supported commands)"
        else:
            summary = "no agent-manifest.json — run `dontpanic manifest init`"
        return InventoryItem(
            id="agent_manifest",
            title="Agent manifest",
            scope=Scope.MACHINE,
            status=derive_status(
                StatusFacts(optional=False, present=present, loadable=loadable)
            ),
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary=summary,
            owner_file_or_env=str(path),
            safe_command="dontpanic manifest init",
            dashboard_mutation_shape={"type": "command", "command": "dontpanic manifest init"},
            doctor_probes=("doctor --agent",),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="agent_manifest",
            title="Agent manifest",
            scope=Scope.MACHINE,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary="",
            owner_file_or_env="~/.dontpanic/agent-manifest.json",
        ),
    )


def provider_roles(ctx: InventoryContext) -> InventoryItem:
    from dontpanic_orchestrate import role_assignment as ra

    def _build() -> InventoryItem:
        scope = ra.ProjectScope(
            path=ctx.project_path or Path.cwd(), name=ctx.project_name
        )
        resolutions = ra.resolve_all(scope)
        # AC2b — status must NOT be optimistic. A role whose resolved executor
        # is operator-only (not in AGENT_REGISTRY) is unrunnable as a worker, so
        # the inventory reports a non-ok status (NEEDS_SETUP) and names the
        # offending roles, rather than claiming `ok`. ``RoleResolution`` already
        # carries ``worker_capable`` from the shared AGENT_REGISTRY guard, so the
        # inventory simply honors it instead of re-deriving membership.
        unrunnable = [r for r in resolutions if not r.worker_capable]
        parts = [
            f"{r.role}={r.value} ({r.source_label})"
            + ("" if r.worker_capable else " — NOT a worker executor")
            for r in resolutions
        ]
        summary = "; ".join(parts)
        if unrunnable:
            bad = ", ".join(f"{r.role}={r.value}" for r in unrunnable)
            summary = (
                f"unrunnable role(s): {bad} (not in AGENT_REGISTRY). "
                f"Reassign with `dontpanic roles set <role> <executor>`. "
                f"Resolved chain: {summary}"
            )
        return InventoryItem(
            id="roles",
            title="Worker role assignments",
            scope=Scope.PROJECT if ctx.project_path else Scope.MACHINE,
            # OK only when every resolved role is a registered worker executor
            # (shared helper: roles always resolve, so present+loadable; the
            # semantic ``valid`` is "no unrunnable role").
            status=derive_status(
                StatusFacts(
                    optional=False, present=True, loadable=True, valid=not unrunnable
                )
            ),
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary=summary,
            owner_file_or_env="roles.* in global/project config",
            # `roles set` requires <role> <executor> args, so the validated
            # route lives in the mutation template; safe_command stays None.
            safe_command=None,
            dashboard_mutation_shape={
                "type": "role_picker",
                "command_template": "dontpanic roles set <role> <executor>",
                "available_executors": ra.available_worker_executors(),
                "roles": [r.role for r in resolutions],
            },
            risks="Assigning an operator-only agent as a worker is refused before write.",
            doctor_probes=("doctor --agent", "doctor --project"),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="roles",
            title="Worker role assignments",
            scope=Scope.MACHINE,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary="",
            owner_file_or_env="roles.* in global/project config",
        ),
    )


def provider_runtime_evidence(ctx: InventoryContext) -> InventoryItem:
    from dontpanic_orchestrate import project_config as pc

    def _build() -> InventoryItem:
        if ctx.project_path is None:
            return InventoryItem(
                id="runtime_evidence",
                title="Runtime evidence defaults",
                scope=Scope.RUNTIME,
                status=derive_status(StatusFacts(optional=True, present=False)),
                editable=True,
                human_required=False,
                optional=True,
                current_value_summary="project-scoped only — pass --project to inspect",
                owner_file_or_env="<repo>/.dontpanic/dontpanic.json runtime_evidence.*",
                safe_command=None,
                dashboard_mutation_shape={
                    "type": "key_value",
                    "command_template": (
                        "dontpanic project config set runtime_evidence.<key> <value>"
                    ),
                },
            )
        cfg = pc.load_project_config(ctx.project_path)
        re_cfg = getattr(cfg, "runtime_evidence", None) if cfg else None
        configured = re_cfg is not None
        summary = (
            "runtime_evidence configured" if configured else "no runtime_evidence defaults set"
        )
        return InventoryItem(
            id="runtime_evidence",
            title="Runtime evidence defaults",
            scope=Scope.RUNTIME,
            status=derive_status(StatusFacts(optional=True, present=configured)),
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary=summary,
            owner_file_or_env="<repo>/.dontpanic/dontpanic.json runtime_evidence.*",
            safe_command=None,
            dashboard_mutation_shape={
                "type": "key_value",
                "command_template": "dontpanic project config set runtime_evidence.<key> <value>",
            },
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="runtime_evidence",
            title="Runtime evidence defaults",
            scope=Scope.RUNTIME,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary="",
            owner_file_or_env="<repo>/.dontpanic/dontpanic.json runtime_evidence.*",
        ),
    )


def provider_gates_paths(ctx: InventoryContext) -> InventoryItem:
    from dontpanic_orchestrate import project_config as pc

    def _build() -> InventoryItem:
        if ctx.project_path is None or (cfg := pc.load_project_config(ctx.project_path)) is None:
            return InventoryItem(
                id="gates_paths",
                title="Human gates / protected paths / plans_dir / default target env",
                scope=Scope.PROJECT,
                status=derive_status(StatusFacts(optional=True, present=False)),
                editable=True,
                human_required=False,
                optional=True,
                current_value_summary="using defaults (plans_dir=docs/plans, no extra gates)",
                owner_file_or_env="<repo>/.dontpanic/dontpanic.json",
                safe_command=None,
                dashboard_mutation_shape={
                    "type": "key_value",
                    "command_template": "dontpanic project config set <key> <value>",
                    "keys": [
                        "plans_dir",
                        "default_target_env",
                        "human_gates",
                        "protected_paths",
                    ],
                },
            )
        gates = cfg.human_gates or []
        protected = cfg.protected_paths or []
        summary = (
            f"plans_dir={cfg.plans_dir}, default_target_env={cfg.default_target_env}, "
            f"human_gates={gates or '(none)'}, protected_paths={len(protected)}"
        )
        return InventoryItem(
            id="gates_paths",
            title="Human gates / protected paths / plans_dir / default target env",
            scope=Scope.PROJECT,
            status=derive_status(StatusFacts(optional=True, present=True)),
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary=summary,
            owner_file_or_env=str(pc.project_config_read_path(ctx.project_path)),
            safe_command=None,
            dashboard_mutation_shape={
                "type": "key_value",
                "command_template": "dontpanic project config set <key> <value>",
                "keys": ["plans_dir", "default_target_env", "human_gates", "protected_paths"],
            },
            risks="Removing a human gate lets dispatch proceed without a pause.",
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="gates_paths",
            title="Human gates / protected paths / plans_dir / default target env",
            scope=Scope.PROJECT,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary="",
            owner_file_or_env="<repo>/.dontpanic/dontpanic.json",
        ),
    )


def provider_quota(ctx: InventoryContext) -> InventoryItem:
    import json
    import os

    from dontpanic_orchestrate import calibration_loader, quota_caps_loader
    from dontpanic_orchestrate import circuit_breakers as cb

    def _build() -> InventoryItem:
        caps_path = quota_caps_loader.effective_caps_path()
        caps_present = caps_path.is_file()
        cal = calibration_loader.load()
        cal_present = bool(cal)
        # Resolve the observed-quota state path the same way the breaker does
        # (honors JARVIS_QUOTA_STATE_PATH for hermetic isolation), then probe it
        # for presence + loadability. The breaker reads this file to compute the
        # percent-of-plan / token proxy it compares against caps; an absent or
        # malformed state file means the breaker has no observed data to act on.
        env_override = os.environ.get("JARVIS_QUOTA_STATE_PATH")
        state_path = Path(env_override) if env_override else cb.QUOTA_STATE_PATH
        state_present = state_path.is_file()
        state_loadable = False
        if state_present:
            try:
                json.loads(state_path.read_text())
                state_loadable = True
            except (OSError, json.JSONDecodeError):
                state_loadable = False
        # AC2b/AC2c — status must NOT be optimistic. The quota surface is only
        # complete when caps, calibration, AND observed state are all present and
        # usable. The breaker cannot convert local token proxies into a
        # comparable percent-of-plan number without operator calibration (see
        # calibration_loader), and it has nothing to evaluate at all without an
        # observed state file. So:
        #   - caps absent                  → NEEDS_SETUP, route to `quota-caps init`
        #   - caps present, NO cal         → NEEDS_SETUP (incomplete), route to
        #                                     `calibrate-claude` (operator-sampled
        #                                     args → a TEMPLATE, never a safe_command)
        #   - caps+cal present, NO state   → NEEDS_SETUP (no observed quota yet)
        #   - caps+cal present, state bad  → NEEDS_SETUP (state unloadable)
        #   - caps + cal + loadable state  → OK
        # Reporting `ok` on caps-present/calibration-absent OR on a
        # missing/unreadable state file (the prior bugs) is exactly the
        # optimistic status the invariant forbids.
        safe_command: str | None = None
        if not caps_present:
            summary = (
                f"caps absent at {caps_path.name}; "
                "run `dontpanic quota-caps init`"
            )
            safe_command = "dontpanic quota-caps init"
        elif not cal_present:
            summary = (
                f"caps present at {caps_path.name} but calibration absent — the "
                "quota breaker is uncalibrated. Calibrate with `dontpanic "
                "calibrate-claude --window <window> --dashboard-pct <pct>`."
            )
            # calibrate-claude requires operator-sampled --window/--dashboard-pct
            # args, so the validated route is a template (mutation shape), not an
            # exact runnable safe_command.
            safe_command = None
        elif not state_present:
            summary = (
                f"caps + calibration present but observed quota state absent at "
                f"{state_path.name} — the breaker has no observed usage to "
                "evaluate yet. Run a quota check to populate it."
            )
            safe_command = None
        elif not state_loadable:
            summary = (
                f"caps + calibration present but quota state at {state_path.name} "
                "is UNLOADABLE (invalid JSON); fix or regenerate the state file."
            )
            safe_command = None
        else:
            summary = (
                f"caps present at {caps_path.name}; calibration present; "
                "observed quota state present"
            )
            # Fully configured → NO safe_command: `quota-caps init` refuses to
            # overwrite an existing caps file, so emitting it here is a
            # non-runnable affordance (codex run9 i1). Re-tuning is the arg-taking
            # calibrate-claude route, surfaced via dashboard_mutation_shape.
            safe_command = None
        # Shared helper (AC2e): caps is the artifact (present iff caps_present);
        # the surface is semantically VALID only when calibration AND a loadable
        # observed-state file are also present — so caps-present/calibration-
        # absent, state-missing, and state-unloadable all collapse to non-ok.
        status = derive_status(
            StatusFacts(
                optional=False,
                present=caps_present,
                loadable=True,
                valid=cal_present and state_present and state_loadable,
            )
        )
        return InventoryItem(
            id="quota",
            title="Quota caps / calibration / admission thresholds",
            scope=Scope.MACHINE,
            status=status,
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary=summary,
            owner_file_or_env=str(caps_path),
            safe_command=safe_command,
            dashboard_mutation_shape={
                "type": "command",
                "command": "dontpanic quota-caps init",
                # calibration route is arg-taking → a template, surfaced so the
                # operator/UI knows HOW to complete the calibration step.
                "command_template": (
                    "dontpanic calibrate-claude --window <window> "
                    "--dashboard-pct <pct>"
                ),
                "secondary": "dontpanic calibrate-claude",
            },
            risks=(
                "Caps that are too low defer dispatch; too high risks overrun. "
                "Missing calibration leaves the breaker unable to compute "
                "percent-of-plan."
            ),
            doctor_probes=("doctor",),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="quota",
            title="Quota caps / calibration / admission thresholds",
            scope=Scope.MACHINE,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary="",
            owner_file_or_env="~/.dontpanic/quota_caps.json",
        ),
    )


def provider_circuit_breakers(ctx: InventoryContext) -> InventoryItem:
    from dontpanic_orchestrate import circuit_breakers as cb

    def _build() -> InventoryItem:
        state = cb.evaluate_global()
        tripped = getattr(state, "is_tripped", False) or getattr(state, "tripped", False)
        hits = getattr(state, "hits_in_window", None)
        threshold = getattr(state, "threshold", None)
        # AC2c/AC2d — status must NOT be optimistic. A TRIPPED global breaker is
        # actively blocking new dispatch (the risk text says so), so reporting
        # `ok` while tripped is exactly the optimistic status the invariant
        # forbids. A tripped breaker is NEEDS_SETUP (operator attention: it ages
        # out of the window, or the operator investigates the iteration-cap hits
        # that tripped it); a clear breaker is OK.
        if tripped:
            summary = (
                "global breaker TRIPPED"
                + (
                    f" ({hits} iteration-cap hit(s) in window"
                    + (f", threshold {threshold}" if threshold is not None else "")
                    + ")"
                    if hits is not None
                    else ""
                )
                + " — new dispatch is blocked until it ages out"
            )
        else:
            summary = (
                "global breaker clear"
                + (f" ({hits} hit(s) in window)" if hits is not None else "")
            )
        return InventoryItem(
            id="circuit_breakers",
            title="Circuit breaker state / history",
            scope=Scope.MACHINE,
            # The breaker state always exists (present); a TRIPPED breaker is the
            # semantically-invalid case → non-ok via the shared helper.
            status=derive_status(
                StatusFacts(
                    optional=False, present=True, loadable=True, valid=not tripped
                )
            ),
            editable=False,
            human_required=False,
            optional=False,
            current_value_summary=summary,
            owner_file_or_env="~/.dontpanic/ breaker history + per-plan gate-state",
            safe_command=None,
            dashboard_mutation_shape=None,
            risks="A tripped global breaker blocks new dispatch until it ages out.",
            doctor_probes=("what-now",),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="circuit_breakers",
            title="Circuit breaker state / history",
            scope=Scope.MACHINE,
            status=Status.UNKNOWN,
            editable=False,
            human_required=False,
            optional=False,
            current_value_summary="",
            owner_file_or_env="~/.dontpanic/ breaker history",
        ),
    )


def provider_notifications(ctx: InventoryContext) -> InventoryItem:
    import os

    from dontpanic_orchestrate import notify

    def _build() -> InventoryItem:
        terminal = notify.is_available()
        discord = bool(
            os.environ.get("DONTPANIC_DISCORD_WEBHOOK_URL")
            or os.environ.get("JARVIS_DISCORD_WEBHOOK_URL")
        )
        summary = (
            f"terminal-notifier {'available' if terminal else 'unavailable'}; "
            f"discord webhook {'set' if discord else 'unset'} (INBOX is always on)"
        )
        return InventoryItem(
            id="notifications",
            title="Notification settings",
            scope=Scope.CAPABILITY,
            status=derive_status(StatusFacts(optional=True, present=discord)),
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary=summary,
            owner_file_or_env="DONTPANIC_DISCORD_WEBHOOK_URL env + terminal-notifier binary",
            safe_command=None,
            dashboard_mutation_shape=None,
            detail=(
                "Optional. INBOX.md is the always-on durable channel; Discord and "
                "terminal-notifier are best-effort sinks and never block core use."
            ),
            doctor_probes=("doctor",),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="notifications",
            title="Notification settings",
            scope=Scope.CAPABILITY,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary="",
            owner_file_or_env="DONTPANIC_DISCORD_WEBHOOK_URL env",
        ),
    )


def provider_dashboard(ctx: InventoryContext) -> InventoryItem:
    from dontpanic_orchestrate import dashboard

    def _build() -> InventoryItem:
        out_dir = dashboard.default_state_out_dir()
        built = out_dir.exists() and any(out_dir.glob("*.json"))
        summary = (
            f"dashboard state {'present' if built else 'not built'} at {out_dir}"
        )
        return InventoryItem(
            id="dashboard",
            title="Dashboard (local / generated state)",
            scope=Scope.MACHINE,
            status=derive_status(StatusFacts(optional=True, present=built)),
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary=summary,
            owner_file_or_env=str(out_dir),
            # `dashboard build` regenerates state — it is a build/start surface,
            # not a config edit, so it is NOT a safe_command. It is surfaced as
            # an informational command the UI/operator can run to refresh state.
            safe_command=None,
            dashboard_mutation_shape={"type": "command", "command": "dontpanic dashboard build"},
            detail="Optional local-first operator console. Core CLI works without it.",
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="dashboard",
            title="Dashboard (local / generated state)",
            scope=Scope.MACHINE,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary="",
            owner_file_or_env="~/.dontpanic/dashboard/",
        ),
    )


def provider_capabilities(ctx: InventoryContext) -> InventoryItem:
    from dontpanic_orchestrate import capabilities, capabilities_status

    def _build() -> InventoryItem:
        index = capabilities.load_capabilities(ctx.project_path)
        envelope = capabilities_status.run_status(
            capability_index=index, repo_root=ctx.project_path
        )
        caps = getattr(envelope, "capabilities", []) or []
        # Audit finding (codex i0): count readiness off the canonical enum VALUE,
        # not str(enum). ``str(CapabilityStatus.READY)`` is
        # "CapabilityStatus.READY" (which does NOT end with "ready"), so the old
        # ``str(...).endswith("ready")`` miscounted a genuinely-ready adapter as
        # 0 ready. Normalize each status to its ``.value`` (falling back to str
        # for a plain string) and compare to "ready" exactly.
        def _ready_value(c: Any) -> str:
            st = getattr(c, "status", "")
            return getattr(st, "value", st) if not isinstance(st, str) else st

        ready = sum(1 for c in caps if _ready_value(c) == "ready")
        # AC2b — status must not be optimistic (audit finding). Routed through the
        # shared helper: capabilities are an OPTIONAL surface, present iff any
        # adapter is known, semantically VALID iff at least one is ready. A
        # population with adapters known but none ready is present+invalid →
        # OPTIONAL_UNCONFIGURED (non-ok, never blocks core use, AC4); one with a
        # ready adapter is OK.
        summary = f"{len(caps)} capabilities/adapters known, {ready} ready"
        return InventoryItem(
            id="capabilities",
            title="Capabilities / adapters",
            scope=Scope.CAPABILITY,
            status=derive_status(
                StatusFacts(
                    optional=True,
                    present=bool(caps),
                    loadable=True,
                    valid=ready > 0,
                )
            ),
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary=summary,
            owner_file_or_env="capability manifests + adapters/",
            # `capabilities setup` needs a <capability> argument — a template,
            # not a runnable command.
            safe_command=None,
            dashboard_mutation_shape={
                "type": "command_template",
                "command_template": "dontpanic capabilities setup <capability> --print-steps",
            },
            detail="Optional integrations. Unready adapters never block core use.",
            doctor_probes=("capabilities status",),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="capabilities",
            title="Capabilities / adapters",
            scope=Scope.CAPABILITY,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary="",
            owner_file_or_env="capability manifests + adapters/",
        ),
    )


def provider_mcp(ctx: InventoryContext) -> InventoryItem:
    def _build() -> InventoryItem:
        import importlib

        ok = importlib.util.find_spec("dontpanic_orchestrate.mcp_server") is not None
        return InventoryItem(
            id="mcp",
            title="MCP server readiness",
            scope=Scope.CAPABILITY,
            # A start surface, never a "configured" edit target → present=False so
            # the shared helper reports OPTIONAL_UNCONFIGURED (never OK).
            status=derive_status(StatusFacts(optional=True, present=False)),
            editable=False,
            human_required=False,
            optional=True,
            current_value_summary=(
                "MCP server module available — start with `dontpanic mcp serve`"
                if ok
                else "MCP server module not importable"
            ),
            owner_file_or_env="dontpanic mcp serve",
            # `mcp serve` starts a long-running server — a start surface, not a
            # config edit. Surfaced as an informational command, not safe_command.
            safe_command=None,
            dashboard_mutation_shape={"type": "command", "command": "dontpanic mcp serve"},
            detail="Optional. Exposes read-only plan state to MCP clients.",
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="mcp",
            title="MCP server readiness",
            scope=Scope.CAPABILITY,
            status=Status.UNKNOWN,
            editable=False,
            human_required=False,
            optional=True,
            current_value_summary="",
            owner_file_or_env="dontpanic mcp serve",
        ),
    )


def provider_environments(ctx: InventoryContext) -> InventoryItem:
    import json

    from dontpanic_orchestrate import environments_loader as el

    def _build() -> InventoryItem:
        if ctx.project_path is None:
            return InventoryItem(
                id="environments",
                title="environments.json / Firebase target",
                scope=Scope.PROJECT,
                status=derive_status(StatusFacts(optional=True, present=False)),
                editable=True,
                human_required=False,
                optional=True,
                current_value_summary="project-scoped — pass --project to inspect",
                owner_file_or_env="<repo>/environments.json + .firebaserc",
                safe_command=None,
            )
        env_path = ctx.project_path / "environments.json"
        fr_path = ctx.project_path / ".firebaserc"
        env_present = env_path.is_file()
        fr_present = fr_path.is_file()
        # The Firebase target lives across TWO surfaces: environments.json (the
        # DontPanic tier registry) and .firebaserc (the Firebase CLI's own
        # alias→project map). The prior provider only inventoried environments.json
        # and never looked at .firebaserc, so it reported `ok environments.json
        # present` while saying nothing about the actual Firebase target aliases
        # (audit finding, codex i1). Inventory BOTH: presence + loadability of each,
        # with the .firebaserc aliases surfaced in the summary. Either file being
        # present-but-UNLOADABLE is a hard defect (non-ok), never `ok`.
        present = env_present or fr_present
        loadable = True
        parts: list[str] = []
        # environments.json — load_environments raises on malformed JSON / schema.
        if env_present:
            try:
                env = el.load_environments(ctx.project_path)
                tiers = getattr(env, "environments", None)
                parts.append(
                    f"environments.json present ({len(tiers)} tier(s))"
                    if isinstance(tiers, dict)
                    else "environments.json present"
                )
            except Exception as exc:  # noqa: BLE001 — EnvironmentsError or similar
                loadable = False
                parts.append(
                    f"environments.json present at {env_path.name} but UNLOADABLE "
                    f"({type(exc).__name__})"
                )
        else:
            parts.append("no environments.json")
        # .firebaserc — the Firebase target alias map. Parse it and surface the
        # declared aliases; a present-but-unparseable .firebaserc is non-ok.
        if fr_present:
            try:
                fr_data = json.loads(fr_path.read_text())
                projects = (
                    (fr_data.get("projects") or {}) if isinstance(fr_data, dict) else {}
                )
                # Surface alias→project so the operator sees the actual Firebase
                # target project IDs, not just the alias names.
                aliases = ", ".join(
                    f"{alias}→{proj}" for alias, proj in sorted(projects.items())
                )
                parts.append(
                    f".firebaserc present (aliases: {aliases})"
                    if aliases
                    else ".firebaserc present (no project aliases)"
                )
            except (OSError, json.JSONDecodeError) as exc:
                loadable = False
                parts.append(
                    f".firebaserc present at {fr_path.name} but UNLOADABLE "
                    f"({type(exc).__name__})"
                )
        else:
            parts.append("no .firebaserc")
        summary = (
            "no environments.json or .firebaserc (optional)"
            if not present
            else "; ".join(parts)
        )
        # Optional surface, but a present-but-unloadable file (either one) is still
        # a hard defect (NEEDS_SETUP) via the shared helper — never OK.
        status = derive_status(
            StatusFacts(optional=True, present=present, loadable=loadable)
        )
        return InventoryItem(
            id="environments",
            title="environments.json / Firebase target",
            scope=Scope.PROJECT,
            status=status,
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary=summary,
            owner_file_or_env=f"{env_path} + {fr_path}",
            safe_command=None,
            detail=(
                "Optional. Only repos that deploy to Firebase/GCP need this; "
                "core orchestration does not."
            ),
            doctor_probes=("doctor --project",),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="environments",
            title="environments.json / Firebase target",
            scope=Scope.PROJECT,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary="",
            owner_file_or_env="<repo>/environments.json",
        ),
    )


def _secret_provider(
    *,
    item_id: str,
    title: str,
    owner_env: str,
    present: bool,
    detail: str,
    verify_command: str,
    optional: bool,
    loadable: bool = True,
    valid: bool = True,
) -> InventoryItem:
    """Shared secret/auth item shape.

    AC5: never echoes a secret value — only a status phrase
    (``configured`` / ``present but …`` / ``not configured``). Secrets are
    always ``human_required`` (when a required one is absent) and carry NO
    ``safe_command``; the operator sets them out-of-band and verifies with
    ``verify_command``.

    AC2c (audit finding, codex i0): a secret artifact that is merely PRESENT is
    not enough to report ``ok``. Mere credential presence is optimistic — a
    present-but-malformed ``~/.claude/.credentials.json`` (unparseable), a
    Discord URL that is not a webhook, or a ``*.json`` under a secrets dir that
    is not a loadable/valid service-account key must report non-ok. The provider
    reduces the secret to ``present`` / ``loadable`` / ``valid`` facts and routes
    them through the SAME shared :func:`derive_status` helper as every other
    provider, so the non-optimistic invariant holds for secrets by construction.
    """
    # human_required for a REQUIRED secret that is not fully good — ABSENT, or
    # PRESENT-but-unloadable/invalid. Operator ruling (D050): a credential cannot
    # be auto-repaired — a human must supply a correct value — so a malformed
    # required secret IS a human-supply gap and must emit the dashboard hint
    # (codex run9 i1), even though its status stays NEEDS_SETUP. An OPTIONAL
    # integration never forces a hint (AC4: optional never blocks core use).
    human_required = (not optional) and not (present and loadable and valid)
    # Routed through the shared helper (AC2e): present + loadable + valid → OK;
    # present-but-unloadable → NEEDS_SETUP (hard defect, even when optional);
    # present-but-invalid → NEEDS_SETUP (required) / OPTIONAL_UNCONFIGURED
    # (optional); absent → HUMAN_REQUIRED (required) / OPTIONAL_UNCONFIGURED.
    status = derive_status(
        StatusFacts(
            optional=optional,
            present=present,
            loadable=loadable,
            valid=valid,
            human_required=human_required,
        )
    )
    if not present:
        summary = "not configured"
    elif not loadable:
        summary = "present but UNLOADABLE"
    elif not valid:
        summary = "present but malformed/invalid"
    else:
        summary = "configured"
    return InventoryItem(
        id=item_id,
        title=title,
        scope=Scope.SECRET,
        status=status,
        editable=False,
        human_required=human_required,
        optional=optional,
        current_value_summary=summary,
        owner_file_or_env=owner_env,
        safe_command=None,  # secrets never route through an auto command
        dashboard_mutation_shape=None,
        risks="Never echo or write the secret value; set it out-of-band.",
        detail=f"{detail} Verify with: {verify_command}",
    )


def _anthropic_auth_facts() -> tuple[bool, bool, bool]:
    """``(present, loadable, valid)`` for the claude worker's auth — secret-safe.

    Claude auth is satisfied by EITHER an ``ANTHROPIC_API_KEY`` env var OR an
    authenticated ``claude`` CLI session. The prior provider only checked the
    env var, so a machine logged in via ``claude`` session — with no
    ANTHROPIC_API_KEY — was falsely reported ``human_required`` despite the item
    claiming "ANTHROPIC_API_KEY or `claude` session" (audit finding, codex i1).
    This probes a real credential artifact — the ANTHROPIC_API_KEY env var, a
    ``~/.claude/.credentials.json`` file, or the macOS keychain
    ``Claude Code-credentials`` entry — and explicitly does NOT treat the
    ``claude`` binary being on PATH as proof of auth (the optimistic status the
    non-optimistic invariant forbids — codex i2).

    AC2c (audit finding, codex i0): mere presence of a non-empty credentials
    file is NOT enough. A present-but-malformed ``~/.claude/.credentials.json``
    (empty, truncated, or non-JSON) must report non-ok, so the file is parsed
    here and the ``loadable`` / ``valid`` facts reflect whether it is a usable
    JSON credential object — never the secret contents themselves. Returns the
    facts only; the value is never returned or logged.
    """
    import json
    import os
    import shutil
    import subprocess

    if os.environ.get("ANTHROPIC_API_KEY"):
        return (True, True, True)
    # File-based credential (Linux / non-keychain installs). Binary-on-PATH
    # alone is NOT auth (codex i2): only a real credential artifact counts.
    cred_file = Path.home() / ".claude" / ".credentials.json"
    try:
        if cred_file.is_file():
            # Present. A present file that cannot be parsed as a JSON object is a
            # hard defect (UNLOADABLE) — never silently treated as configured.
            try:
                raw = json.loads(cred_file.read_text())
            except (OSError, json.JSONDecodeError):
                return (True, False, False)
            return (True, True, isinstance(raw, dict) and bool(raw))
    except OSError:  # best-effort probe
        pass
    # macOS keychain session credential.
    security = shutil.which("security")
    if security:
        try:
            result = subprocess.run(  # noqa: S603 — fixed argv, no user input
                [security, "find-generic-password", "-s", "Claude Code-credentials"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                return (True, True, True)
        except (OSError, subprocess.SubprocessError):  # best-effort probe
            pass
    return (False, True, True)


def _anthropic_auth_configured() -> bool:
    """Back-compat boolean: True only when auth is present, loadable AND valid."""
    present, loadable, valid = _anthropic_auth_facts()
    return present and loadable and valid


def _is_discord_webhook_url(value: str) -> bool:
    """True when ``value`` has the shape of a real Discord webhook URL.

    A bare non-empty string set in ``DONTPANIC_DISCORD_WEBHOOK_URL`` is not a
    usable webhook — the notifier would fail at runtime. Validating the shape
    keeps the secret/auth status non-optimistic (AC2c) without echoing the value.
    """
    import re

    return bool(
        re.match(
            r"^https://(discord(app)?\.com)/api/(v\d+/)?webhooks/\d+/[\w-]+$",
            value,
        )
    )


def _gcp_sa_key_facts() -> tuple[bool, bool, bool]:
    """``(present, loadable, valid)`` for a GCP/Firebase service-account key.

    ``present`` when any ``*.json`` exists under a known secrets dir; ``loadable``
    when at least one parses as JSON; ``valid`` when at least one parses to a
    service-account key shape (``type == "service_account"`` with a
    ``client_email`` and ``private_key``). A dir holding only a malformed or
    non-SA JSON is present-but-not-valid → non-ok (AC2c). Never returns the key.
    """
    import json

    sa_files: list[Path] = []
    for d in (Path.home() / ".dontpanic" / ".secrets", Path(".secrets")):
        try:
            if d.is_dir():
                sa_files.extend(sorted(d.glob("*.json")))
        except OSError:  # best-effort probe
            continue
    if not sa_files:
        return (False, True, True)
    loadable = False
    valid = False
    for f in sa_files:
        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        loadable = True
        if (
            isinstance(data, dict)
            and data.get("type") == "service_account"
            and data.get("client_email")
            and data.get("private_key")
        ):
            valid = True
            break
    return (True, loadable, valid)


def provider_secrets_auth(ctx: InventoryContext) -> list[InventoryItem]:
    """Secrets / auth prerequisites — returns multiple items, all secret-safe."""
    import os

    items: list[InventoryItem] = []

    # Anthropic / Claude auth (required for paid dispatch but core CLI works
    # without it — it is the worker prerequisite, so we mark it required-ish but
    # human-driven). Configured when EITHER ANTHROPIC_API_KEY is set OR a `claude`
    # CLI session is available, so a session-authed machine is not falsely flagged.
    # AC2c: a present-but-malformed credential file reports non-ok, not OK.
    anth_present, anth_loadable, anth_valid = _anthropic_auth_facts()
    items.append(
        _secret_provider(
            item_id="secret_anthropic_auth",
            title="Anthropic / Claude CLI auth",
            owner_env="ANTHROPIC_API_KEY env var or an authenticated `claude` CLI session",
            present=anth_present,
            loadable=anth_loadable,
            valid=anth_valid,
            detail=(
                "Required to dispatch the claude worker executor. Satisfied by "
                "ANTHROPIC_API_KEY or a logged-in `claude` session."
            ),
            verify_command="dontpanic doctor --agent",
            optional=False,
        )
    )
    # Discord webhook (optional notification secret). AC2c: a value that is set
    # but is NOT a real webhook URL is present-but-invalid → non-ok, not OK.
    discord_url = os.environ.get("DONTPANIC_DISCORD_WEBHOOK_URL") or os.environ.get(
        "JARVIS_DISCORD_WEBHOOK_URL"
    )
    items.append(
        _secret_provider(
            item_id="secret_discord_webhook",
            title="Discord webhook URL",
            owner_env="DONTPANIC_DISCORD_WEBHOOK_URL",
            present=bool(discord_url),
            valid=bool(discord_url) and _is_discord_webhook_url(discord_url),
            detail="Optional. Enables Discord notifications; INBOX works without it.",
            verify_command="dontpanic doctor",
            optional=True,
        )
    )
    # GCP / Firebase service-account key (optional, only for deploy repos). AC2c:
    # a present-but-unloadable (non-JSON) or non-service-account key reports
    # non-ok, never OK from mere file presence.
    sa_present, sa_loadable, sa_valid = _gcp_sa_key_facts()
    items.append(
        _secret_provider(
            item_id="secret_gcp_sa_key",
            title="GCP / Firebase service-account key",
            owner_env="~/.dontpanic/.secrets/*.json or <repo>/.secrets/*.json",
            present=sa_present,
            loadable=sa_loadable,
            valid=sa_valid,
            detail="Optional. Only repos deploying to Firebase/GCP need this.",
            verify_command="dontpanic doctor --project <name>",
            optional=True,
        )
    )
    return items


def provider_install_reconcile(ctx: InventoryContext) -> InventoryItem:
    from dontpanic_orchestrate import home_reconcile, install_snapshot

    def _build() -> InventoryItem:
        snap = install_snapshot.load_snapshot()
        snap_present = snap is not None
        # Split-home detection: classify canonical vs legacy.
        split = False
        try:
            states = home_reconcile.classify_homes()
            warnings, _ = home_reconcile.split_brain_summary(states)
            split = bool(warnings)
        except Exception:  # noqa: BLE001 — classification is best-effort
            split = False
        if split:
            summary = "split config homes detected (~/.dontpanic vs ~/.jarvis)"
            cmd = "dontpanic reconcile homes --dry-run"
        else:
            summary = (
                "install snapshot present, homes consistent"
                if snap_present
                else "no install snapshot (optional baseline), homes consistent"
            )
            cmd = "dontpanic reconcile baseline"
        # Shared helper: a split-home is a REQUIRED defect (present + invalid →
        # NEEDS_SETUP); otherwise the baseline snapshot is an OPTIONAL surface
        # (present → OK, absent → OPTIONAL_UNCONFIGURED).
        status = derive_status(
            StatusFacts(
                optional=not split,
                present=split or snap_present,
                loadable=True,
                valid=not split,
            )
        )
        return InventoryItem(
            id="install_reconcile",
            title="Install snapshot / reconcile state",
            scope=Scope.MACHINE,
            status=status,
            editable=True,
            human_required=False,
            optional=not split,
            current_value_summary=summary,
            owner_file_or_env="~/.dontpanic/install-snapshot.json",
            safe_command=cmd,
            dashboard_mutation_shape={"type": "command", "command": cmd},
            risks="Divergent same-name files are never silently merged.",
            doctor_probes=("doctor --agent", "reconcile check"),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="install_reconcile",
            title="Install snapshot / reconcile state",
            scope=Scope.MACHINE,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary="",
            owner_file_or_env="~/.dontpanic/install-snapshot.json",
        ),
    )


def provider_pm_credentials(ctx: InventoryContext) -> InventoryItem:
    import os

    def _build() -> InventoryItem:
        linear = bool(os.environ.get("LINEAR_API_KEY"))
        summary = (
            "Linear API key set" if linear else "no PM-tool credentials (optional)"
        )
        return InventoryItem(
            id="pm_credentials",
            title="PM-tool credentials (Linear, …)",
            scope=Scope.SECRET,
            status=derive_status(StatusFacts(optional=True, present=linear)),
            editable=False,
            # Optional integration: not human-"required". Surfacing it as
            # required would force a dashboard hint for an integration that
            # never blocks core use (AC4).
            human_required=False,
            optional=True,
            current_value_summary=summary,
            owner_file_or_env="LINEAR_API_KEY (and other PM-tool env vars)",
            safe_command=None,
            dashboard_mutation_shape=None,
            risks="Never echo the API key; set it out-of-band.",
            detail="Optional. PM-tool sync is off by default; core use never needs it.",
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="pm_credentials",
            title="PM-tool credentials (Linear, …)",
            scope=Scope.SECRET,
            status=Status.UNKNOWN,
            editable=False,
            human_required=False,
            optional=True,
            current_value_summary="",
            owner_file_or_env="LINEAR_API_KEY",
        ),
    )


def provider_skill_allowlist(ctx: InventoryContext) -> InventoryItem:
    """Plan 2026-05-30-001 F015: surface the skill auto-run allowlist artifact
    and its missing/stale/conflicting state (AC5).

    The allowlist is what authorizes any unattended skill auto-run. A MISSING
    allowlist is the safe zero-state (auto-run disabled, never blocks core use →
    optional). A PRESENT-but-unloadable/stale/conflicting allowlist is an
    untrusted defect the operator must fix + re-approve → non-ok, never `ok`.
    """
    from dontpanic_orchestrate import skill_allowlist as sa

    def _build() -> InventoryItem:
        state = sa.classify_allowlist()
        status_enum = state.status
        missing = status_enum is sa.AllowlistStatus.MISSING
        # UNLOADABLE = present-but-broken JSON/schema → hard defect (loadable
        # False routes to NEEDS_SETUP via the shared helper). STALE/CONFLICTING
        # parse fine but are untrusted → present + loadable + invalid. Both are
        # non-ok; an OK status only rides a present + trusted artifact.
        unloadable = status_enum is sa.AllowlistStatus.UNLOADABLE
        trusted = status_enum is sa.AllowlistStatus.OK
        summary = state.detail
        if state.conflicts:
            summary = f"{summary}: {'; '.join(state.conflicts)}"
        return InventoryItem(
            id="skill_allowlist",
            title="Skill auto-run allowlist",
            scope=Scope.MACHINE,
            status=derive_status(
                StatusFacts(
                    # A MISSING allowlist is optional (auto-run is opt-in); a
                    # PRESENT-but-defective one is a required fix.
                    optional=missing,
                    present=not missing,
                    loadable=not unloadable,
                    valid=trusted,
                )
            ),
            editable=True,
            human_required=False,
            optional=missing,
            current_value_summary=summary,
            owner_file_or_env=str(state.path),
            # Editing the allowlist is an approval-bearing review action, not a
            # single placeholder-free CLI edit; no safe_command. The artifact is
            # hand-curated + content-hashed, so there is no auto-edit affordance.
            safe_command=None,
            dashboard_mutation_shape=None,
            risks=(
                "Only read-only, bounded commands belong here. A stale or "
                "conflicting allowlist authorizes NOTHING until re-approved, so "
                "mutating/credentialed/networked/paid skills are never silently "
                "auto-run."
            ),
            doctor_probes=("doctor --agent", "reconcile homes"),
        )

    return _safe(
        _build,
        fallback=InventoryItem(
            id="skill_allowlist",
            title="Skill auto-run allowlist",
            scope=Scope.MACHINE,
            status=Status.UNKNOWN,
            editable=True,
            human_required=False,
            optional=True,
            current_value_summary="",
            owner_file_or_env="~/.dontpanic/skill-autorun-allowlist.json",
        ),
    )


# Ordered registry of single-item providers. Secrets/auth is a multi-item
# provider handled separately in :func:`collect_inventory`.
_PROVIDERS: tuple[Callable[[InventoryContext], InventoryItem], ...] = (
    provider_global_config,
    provider_project_config,
    provider_projects_registry,
    provider_agent_manifest,
    provider_roles,
    provider_runtime_evidence,
    provider_gates_paths,
    provider_quota,
    provider_circuit_breakers,
    provider_notifications,
    provider_dashboard,
    provider_capabilities,
    provider_mcp,
    provider_environments,
    provider_install_reconcile,
    provider_pm_credentials,
    provider_skill_allowlist,
)


# ──────────────────────────────── assembly ──────────────────────────────────


def resolve_context(project: str | None) -> InventoryContext:
    """Resolve a project arg (name or path) into an :class:`InventoryContext`.

    When ``project`` is None, a cwd-local ``.dontpanic`` directory makes the cwd
    the in-scope project (single-repo compat); otherwise the context is
    machine-only and project-scoped providers degrade gracefully.

    When ``project`` is an explicit selector that resolves to neither a
    registered name nor an existing directory, this raises
    :class:`UnresolvedProjectError` rather than silently falling back to
    machine-only scope (which would report an optimistic inventory for a
    project the caller never asked about — see ``resolve_project_path``'s
    hard-refuse contract).
    """
    from dontpanic_orchestrate import project_config as pc

    if project:
        resolved = pc.resolve_project_path(project)
        if resolved is not None:
            path, name = resolved
            return InventoryContext(project_path=path, project_name=name)
        # Unknown name/path: hard-refuse — never silently degrade an
        # explicitly-requested project to machine-only scope.
        raise UnresolvedProjectError(project)
    cwd = Path.cwd()
    if (cwd / ".dontpanic").is_dir():
        return InventoryContext(project_path=cwd, project_name=None)
    return InventoryContext()


def collect_inventory(
    *, project: str | None = None, dashboard_url: str | None = None
) -> Inventory:
    """Assemble the full inventory.

    Calls every provider (each defensive), then attaches exactly one
    response-level :class:`DashboardHint` when any item is human-required (AC6),
    tagging those items with the shared hint id rather than repeated text.
    """
    ctx = resolve_context(project)
    items: list[InventoryItem] = [p(ctx) for p in _PROVIDERS]
    items.extend(provider_secrets_auth(ctx))

    # AC6: one response-level dashboard hint iff any item needs human input.
    any_human = any(i.human_required for i in items)
    hint: DashboardHint | None = None
    if any_human:
        hint = _detect_dashboard_hint(dashboard_url=dashboard_url)
        # Tag human-required items with the hint id (ref only, never full text).
        items = [
            (
                _with_hint_ref(i, hint.hint_id)
                if i.human_required
                else i
            )
            for i in items
        ]

    return Inventory(
        project_name=ctx.project_name,
        project_path=str(ctx.project_path) if ctx.project_path else None,
        items=tuple(items),
        dashboard_hint=hint,
    )


def _with_hint_ref(item: InventoryItem, hint_id: str) -> InventoryItem:
    from dataclasses import replace

    return replace(item, dashboard_hint_ref=hint_id)


def _detect_dashboard_hint(*, dashboard_url: str | None = None) -> DashboardHint:
    """Build the single response-level dashboard hint (F013 AC2).

    Auto-detects a running dashboard singleton for ``active_url`` and falls back
    to the start command when none is running — the caller no longer has to pass
    ``dashboard_url`` manually (the F008 behavior). An explicit ``dashboard_url``
    still overrides auto-detection so existing callers / tests keep working.
    """
    if dashboard_url:
        return DashboardHint(is_running=True, url=dashboard_url)
    # F010 step 6: route discovery through the single dashboard status helper
    # rather than re-deriving it here, so "is a dashboard running?" has one
    # answer shared with operations guidance.
    try:
        from dontpanic_orchestrate import dashboard

        status = dashboard.dashboard_status()
    except Exception:  # noqa: BLE001 — detection is best-effort; degrade to "not running"
        return DashboardHint(is_running=False)
    if status.is_running and status.url:
        return DashboardHint(is_running=True, url=status.url)
    return DashboardHint(is_running=False)


def _mutation_command_template(item: InventoryItem) -> str | None:
    """Return the edit command template a UI/agent would fill in for ``item``.

    ``safe_command`` carries only exact runnable commands (no placeholders);
    the template — with ``<key>`` / ``<role>`` style placeholders — lives in
    ``dashboard_mutation_shape``. This reads it out under either key so the
    setup planner can still report HOW to configure an arg-taking surface.
    """
    shape = item.dashboard_mutation_shape
    if not shape:
        return None
    return shape.get("command_template") or shape.get("command")


# ─────────────────────────── dashboard projection ───────────────────────────


def to_dashboard_state(inventory: Inventory) -> dict[str, Any]:
    """Render the inventory as dashboard Settings / Setup cards (AC3).

    ``settings_cards`` are the OK / editable surfaces; ``setup_cards`` are the
    incomplete ones (needs_setup / missing / human_required). The single
    response-level ``dashboard_hint`` is carried at the top level so the UI shows
    it once.
    """
    settings_cards: list[dict[str, Any]] = []
    setup_cards: list[dict[str, Any]] = []
    for item in inventory.items:
        card = _item_to_card(item)
        if item.is_incomplete:
            setup_cards.append(card)
        else:
            settings_cards.append(card)
    return {
        "kind": "config_inventory",
        "project_name": inventory.project_name,
        "project_path": inventory.project_path,
        "settings_cards": settings_cards,
        "setup_cards": setup_cards,
        "dashboard_hint": inventory.dashboard_hint.to_dict()
        if inventory.dashboard_hint
        else None,
    }


# Subcommand verbs that mark a command as a build/start/serve RUN-ACTION rather
# than a config edit. A run-action starts or regenerates a surface (e.g.
# `dontpanic dashboard build`, `dontpanic dashboard serve`, `dontpanic mcp
# serve`, `dontpanic dashboard open`); it is NOT an edit affordance and must
# never render as an item's edit ``safe_command`` (F013 AC4).
_RUN_ACTION_VERBS: frozenset[str] = frozenset({"build", "serve", "open", "start"})


def _is_run_action_command(command: str | None) -> bool:
    """True when ``command`` is a build/start/serve run-action, not a config edit."""
    if not command:
        return False
    return any(tok in _RUN_ACTION_VERBS for tok in command.split())


def _item_to_card(item: InventoryItem) -> dict[str, Any]:
    from dontpanic_orchestrate import state_projection

    scrub = state_projection.scrub_secrets

    # F013 AC4 — render edit affordances DISTINCTLY from run-actions.
    #   * ``safe_command`` is the validated, exact edit command. F008 guarantees
    #     it is never a build/start/serve surface, so it is always a safe edit.
    #   * An arg-taking edit route (e.g. `roles set <role> <executor>`) surfaces
    #     as an edit *template* — info, not a runnable command.
    #   * Build/start/serve commands surface SEPARATELY as ``run_action`` and are
    #     never offered as an item's edit command.
    mutation = item.dashboard_mutation_shape
    mutation_command = (
        (mutation.get("command") or mutation.get("command_template"))
        if mutation
        else None
    )
    run_action: dict[str, Any] | None = None
    edit_command: str | None = item.safe_command
    edit_command_template: str | None = None
    if _is_run_action_command(mutation_command):
        run_action = {"type": "run_action", "command": mutation_command}
    elif mutation_command and item.safe_command is None:
        edit_command_template = mutation_command

    return {
        "id": item.id,
        "title": item.title,
        "scope": item.scope.value,
        "status": item.status.value,
        "optional": item.optional,
        "editable": item.editable,
        "human_required": item.human_required,
        "summary": scrub(item.current_value_summary),
        "owner": item.owner_file_or_env,
        # Edit affordance (AC4): exact validated command, or a fill-in template.
        # ``command`` is None for read-only / run-action-only / human-required
        # items, so a build/start/serve command can never ride here.
        "edit": {
            "command": scrub(edit_command),
            "command_template": edit_command_template,
        },
        # Run-action (AC4): build/start/serve surfaces, rendered distinctly from
        # edits. Never carries a config edit; None when the item has no run-action.
        "run_action": run_action,
        # Back-compat flat fields (existing CLI/dashboard-state consumers).
        "safe_command": scrub(edit_command),
        "mutation": mutation,
        "dashboard_hint_ref": item.dashboard_hint_ref,
        "detail": scrub(item.detail),
    }


# ───────────────────────────── setup/update planner ─────────────────────────


def build_setup_plan(inventory: Inventory) -> dict[str, Any]:
    """Emit a setup/update plan for the incomplete inventory areas (AC7).

    Returns BOTH typed ActionChoice records (reusing F007's vocabulary so the
    dashboard renders them like every other decision) and a draft DontPanic plan
    skeleton, so an interactive agent can either act on the choices directly or
    lock the draft plan — rather than inventing next steps.
    """
    from dontpanic_orchestrate import operations_guidance as og

    incomplete = inventory.incomplete_items()
    choices: list[og.ActionChoice] = []
    draft_features: list[dict[str, Any]] = []
    for idx, item in enumerate(incomplete):
        automatable = bool(item.safe_command) and not item.human_required
        template = _mutation_command_template(item)
        choices.append(
            og.ActionChoice(
                id=f"setup_{item.id}",
                kind=og.KIND_DOCTOR if not automatable else og.KIND_ONBOARD,
                title=f"Set up: {item.title}",
                rationale=item.current_value_summary
                or "incomplete configuration surface",
                risk=og.Risk.LOW,
                recommended=(idx == 0),
                exact_command=item.safe_command if automatable else None,
                requires_human=item.human_required or not automatable,
                references_affordance=(
                    inventory.dashboard_hint.hint_id
                    if (item.dashboard_hint_ref and inventory.dashboard_hint)
                    else None
                ),
            )
        )
        draft_features.append(
            {
                "id": f"S{idx + 1:03d}",
                "title": f"Configure {item.title}",
                "scope": item.scope.value,
                # Exact runnable command when there is one; else the template
                # routing (e.g. `dontpanic roles set <role> <executor>`) so the
                # info is not lost just because it needs arguments.
                "safe_command": item.safe_command,
                "command_template": template,
                "human_required": item.human_required,
            }
        )

    draft_plan = {
        "title": "DontPanic setup / update",
        "project": inventory.project_name,
        "summary": (
            f"{len(incomplete)} configuration surface(s) need attention."
            if incomplete
            else "All inventory surfaces are configured."
        ),
        "features": draft_features,
    }
    return {
        "choices": [c.to_dict() for c in choices],
        "draft_plan": draft_plan,
        "dashboard_hint": inventory.dashboard_hint.to_dict()
        if inventory.dashboard_hint
        else None,
    }


# ──────────────────────────────── text render ───────────────────────────────


_STATUS_GLYPH: dict[Status, str] = {
    Status.OK: "✓",
    Status.NEEDS_SETUP: "•",
    Status.MISSING: "✗",
    Status.OPTIONAL_UNCONFIGURED: "○",
    Status.HUMAN_REQUIRED: "!",
    Status.UNKNOWN: "?",
}


def render_text(inventory: Inventory) -> str:
    from dontpanic_orchestrate import state_projection

    scrub = state_projection.scrub_secrets
    lines: list[str] = []
    scope_label = (
        f"project={inventory.project_name or inventory.project_path}"
        if inventory.project_path
        else "scope=machine (no project)"
    )
    lines.append(f"DontPanic configuration inventory ({scope_label})")
    lines.append("")
    for item in inventory.items:
        glyph = _STATUS_GLYPH.get(item.status, "?")
        opt = " [optional]" if item.optional else ""
        lines.append(f"  {glyph} {item.title}{opt} — {item.status.value}")
        lines.append(f"      {scrub(item.current_value_summary)}")
        lines.append(f"      owner: {item.owner_file_or_env}")
        if item.safe_command:
            lines.append(f"      edit:  {scrub(item.safe_command)}")
        if item.human_required:
            lines.append("      human-required (see dashboard hint)")
    if inventory.dashboard_hint is not None:
        lines.append("")
        lines.append(f"  dashboard: {inventory.dashboard_hint.text()}")
    return "\n".join(lines) + "\n"


__all__ = [
    "DASHBOARD_HINT_ID",
    "DashboardHint",
    "Inventory",
    "InventoryContext",
    "InventoryItem",
    "Scope",
    "Status",
    "StatusFacts",
    "UnresolvedProjectError",
    "build_setup_plan",
    "collect_inventory",
    "derive_status",
    "render_text",
    "resolve_context",
    "to_dashboard_state",
]
