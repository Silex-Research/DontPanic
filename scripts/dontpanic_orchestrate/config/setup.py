"""Plan G F006 — ``dontpanic setup`` interactive bootstrap.

Preview-by-default; mutation requires ``--yes``. Refuses secret-shaped
values for credential pointer fields (D014). Shapes a minimal config
spanning the global ``roles`` block and per-project ``runtime_evidence``
defaults.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Patterns that mark a value as a credential VALUE rather than a pointer.
# Greppable list (D014); kept under a flag-only constant so the source
# scanner in ``test_f006_config_setup_surface.py`` can ignore this line
# while still catching real leaks elsewhere.
_FORBIDDEN_LITERAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^AKIA[0-9A-Z]{12,}$"),  # AWS-shaped
    re.compile(r"^ghp_[A-Za-z0-9]{20,}$"),  # GitHub PAT
    re.compile(r"^gh[osu]_[A-Za-z0-9]{20,}$"),  # GitHub fine-grained
    re.compile(r"^xox[baprs]-[A-Za-z0-9-]{10,}$"),  # Slack
    re.compile(r"^sk-[A-Za-z0-9-_]{20,}$"),  # OpenAI-shaped
    re.compile(r"^Bearer\s+", re.IGNORECASE),  # bearer literal
    re.compile(r"=\s*['\"]?[A-Za-z0-9]+", re.IGNORECASE),  # key=value shape
)

_POINTER_PATH_PREFIXES: tuple[str, ...] = ("/", "./", "../", "~/")
_ENV_POINTER_RE = re.compile(r"^env:[A-Z_][A-Z0-9_]*$")


def is_credential_pointer(value: str) -> bool:
    """Whether ``value`` is one of the allowed pointer shapes (D014).

    Allowed:
      - ``adc`` (Application Default Credentials sentinel).
      - path-only refs starting with ``/``, ``./``, ``../``, or ``~/``.
      - ``env:NAME`` where NAME matches ``[A-Z_][A-Z0-9_]*``.

    Anything else — including bare strings that don't look like paths,
    base64-shaped strings, JWT-shaped strings, or anything matching the
    forbidden-literal patterns — is rejected.
    """
    if not value or not isinstance(value, str):
        return False
    if value == "adc":
        return True
    if _ENV_POINTER_RE.match(value):
        return True
    if value.startswith(_POINTER_PATH_PREFIXES):
        # Belt + suspenders: even path-shaped strings cannot match a
        # forbidden literal pattern (e.g. someone pasting `Bearer xyz`
        # with a leading `/` won't sneak through).
        for rx in _FORBIDDEN_LITERAL_PATTERNS:
            if rx.search(value):
                return False
        return True
    return False


@dataclass(frozen=True)
class SetupPlan:
    """The set of writes :func:`run_setup` would perform.

    ``preview_lines`` is human-readable output for the operator;
    ``apply()`` is what mutates state when ``--yes`` is supplied.
    """

    preview_lines: tuple[str, ...]
    global_writes: tuple[tuple[str, str], ...]  # (dotted_key, value)
    project_writes: tuple[tuple[Path, str, Any], ...]  # (project_dir, dotted_key, value)


@dataclass(frozen=True)
class SetupArgs:
    """Operator-supplied flags. ``None`` fields don't trigger a write.

    ``project_dir`` is the per-project target for any
    ``runtime_evidence.*`` writes — required for those (D015).
    """

    implementer: str | None = None
    auditor: str | None = None
    goal_auditor: str | None = None

    project_dir: Path | None = None
    web_base_url: str | None = None
    ios_scheme: str | None = None
    ios_simulator: str | None = None
    android_package: str | None = None
    android_adb_device_serial: str | None = None
    backend_provider: str | None = None
    backend_project: str | None = None
    backend_auth: str | None = None  # POINTER, not value (D014)


class SetupError(Exception):
    """Raised when setup arguments fail validation (e.g. secret-shaped
    credential value, no flags supplied in non-interactive mode)."""


def plan_setup(args: SetupArgs) -> SetupPlan:
    """Build a :class:`SetupPlan` from the operator's flags.

    Validates pointer-shape constraints (D014) at plan-time so the
    refusal happens BEFORE any preview output that might leak the value
    in logs. Raises :class:`SetupError` on validation failure.
    """
    # Pre-validate pointer fields. Backend auth is the only pointer
    # field in F006; G2-G5 may register more via their own setup flags
    # (out of scope for F006).
    if args.backend_auth is not None and not is_credential_pointer(args.backend_auth):
        raise SetupError(
            "refusing to store a credential value (D014); "
            "use a pointer shape: 'adc', 'env:NAME', or a path "
            "(./secrets/sa.json, ~/abs/path, /abs/path)"
        )

    global_writes: list[tuple[str, str]] = []
    project_writes: list[tuple[Path, str, Any]] = []
    preview_lines: list[str] = []

    if args.implementer:
        global_writes.append(("roles.implementer", args.implementer))
    if args.auditor:
        global_writes.append(("roles.auditor", args.auditor))
    if args.goal_auditor:
        global_writes.append(("roles.goal_auditor", args.goal_auditor))

    project_runtime_writes: list[tuple[str, Any]] = []
    if args.web_base_url:
        project_runtime_writes.append(("runtime_evidence.web.base_url", args.web_base_url))
    if args.ios_scheme:
        project_runtime_writes.append(("runtime_evidence.ios.scheme", args.ios_scheme))
    if args.ios_simulator:
        project_runtime_writes.append(("runtime_evidence.ios.simulator", args.ios_simulator))
    if args.android_package:
        project_runtime_writes.append(("runtime_evidence.android.package", args.android_package))
    if args.android_adb_device_serial:
        project_runtime_writes.append(
            ("runtime_evidence.android.adb_device_serial", args.android_adb_device_serial)
        )
    if args.backend_provider:
        project_runtime_writes.append(("runtime_evidence.backend.provider", args.backend_provider))
    if args.backend_project:
        project_runtime_writes.append(("runtime_evidence.backend.project", args.backend_project))
    if args.backend_auth:
        project_runtime_writes.append(("runtime_evidence.backend.auth", args.backend_auth))

    if project_runtime_writes:
        if args.project_dir is None:
            raise SetupError(
                "runtime_evidence.* writes require --project-dir (D015 — "
                "runtime evidence is project-scoped, never global)"
            )
        for key, value in project_runtime_writes:
            project_writes.append((args.project_dir, key, value))

    if not global_writes and not project_writes:
        raise SetupError(
            "no writes to plan; supply at least one of --implementer / "
            "--auditor / --goal-auditor / --web-base-url / --ios-* / "
            "--android-* / --backend-*"
        )

    preview_lines.append("[setup preview]")
    if global_writes:
        from dontpanic_orchestrate import global_config as gc

        preview_lines.append(f"  global config target: {gc.config_path()}")
        for key, value in global_writes:
            preview_lines.append(f"    set {key} = {value}")
    if project_writes:
        from dontpanic_orchestrate import project_config as pc

        for proj_dir, key, value in project_writes:
            preview_lines.append(f"  project config target: {pc.project_config_path(proj_dir)}")
            preview_lines.append(f"    set {key} = {value}")

    return SetupPlan(
        preview_lines=tuple(preview_lines),
        global_writes=tuple(global_writes),
        project_writes=tuple(project_writes),
    )


def apply_setup(plan: SetupPlan) -> None:
    """Execute the writes in ``plan``. Caller is responsible for showing
    the preview first when running interactively without ``--yes``."""
    from dontpanic_orchestrate.config.cli_helpers import (
        write_global_dotted_key,
        write_project_dotted_key,
    )

    for key, value in plan.global_writes:
        write_global_dotted_key(key, value)
    for proj_dir, key, value in plan.project_writes:
        write_project_dotted_key(proj_dir, key, value)


__all__ = [
    "SetupArgs",
    "SetupError",
    "SetupPlan",
    "apply_setup",
    "is_credential_pointer",
    "plan_setup",
]
