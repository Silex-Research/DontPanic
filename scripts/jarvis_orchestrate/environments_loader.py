"""F023 EC1 — per-repo environments.json loader + supervisor pre-dispatch validator.

Each consumer repo declares its env-tier deployment surface in a top-level
`environments.json` (validated against agent-conventions v1.3 environments.schema.json).
The supervisor walks up from the plan dir to find the registry, loads it, and
checks that the plan's target_env / target_project pair is declared. Mismatches
raise pre-dispatch — before ExecutionEnvironment, before executors.

Two cross-cutting constraints are enforced here in Python (the JSON schema
intentionally stays simple so codegen output is clean):
1. At least one of dev / staging / prod must be declared.
2. Each declared env block must have at least one of firebase_project / gcp_project.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

_SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[2] / ".claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[3] / "agent-conventions" / "schemas" / "v1.0",
]


def _find_schemas_dir() -> Path:
    for c in _SCHEMA_CANDIDATES:
        if (c / "models").is_dir():
            sys.path.insert(0, str(c))
            return c
    raise FileNotFoundError(
        "agent-conventions v1.0 schemas not found. Tried: "
        + ", ".join(str(c) for c in _SCHEMA_CANDIDATES)
    )


SCHEMAS_DIR = _find_schemas_dir()
from models.environments_model import EnvBlock, Environments  # noqa: E402

ENVIRONMENTS_FILENAME = "environments.json"
DECLARABLE_TIERS = ("dev", "staging", "prod")


class EnvironmentsError(Exception):
    """Base class for environments.json loader errors."""


class EnvironmentsNotFoundError(EnvironmentsError):
    """No environments.json was found at the expected path."""


class EnvironmentsValidationError(EnvironmentsError):
    """environments.json failed schema or cross-cutting validation."""


class EnvironmentsTargetMismatchError(EnvironmentsError):
    """Plan target_env / target_project does not match the registry."""


def find_repo_root_for_plan(plan_dir: Path) -> Path | None:
    """Walk up from plan_dir until a directory containing environments.json is found.

    Returns the directory path if found; None if the walk reaches the filesystem
    root without finding one (host-local / no-registry case — supervisor skips
    pre-dispatch validation).
    """
    plan_dir = plan_dir.resolve()
    cur: Path | None = plan_dir
    while cur is not None:
        if (cur / ENVIRONMENTS_FILENAME).is_file():
            return cur
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent
    return None


def _check_declared_tiers(env: Environments) -> list[tuple[str, EnvBlock]]:
    declared: list[tuple[str, EnvBlock]] = [
        (tier, getattr(env, tier))
        for tier in DECLARABLE_TIERS
        if getattr(env, tier) is not None
    ]
    if not declared:
        raise EnvironmentsValidationError(
            f"environments.json {env.repo!r}: at least one of "
            f"{list(DECLARABLE_TIERS)} must be declared"
        )
    for tier, block in declared:
        if not block.firebase_project and not block.gcp_project:
            raise EnvironmentsValidationError(
                f"environments.json {env.repo!r} tier {tier!r}: at least one of "
                "firebase_project or gcp_project must be set"
            )
    return declared


def load_environments(repo_root: Path) -> Environments:
    """Read repo_root/environments.json, validate against schema + cross-cutting rules."""
    repo_root = repo_root.resolve()
    path = repo_root / ENVIRONMENTS_FILENAME
    if not path.is_file():
        raise EnvironmentsNotFoundError(f"{path} does not exist")

    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise EnvironmentsValidationError(f"{path}: malformed JSON — {exc}") from exc

    try:
        env = Environments.model_validate(raw)
    except ValidationError as exc:
        raise EnvironmentsValidationError(f"{path}: {exc}") from exc

    _check_declared_tiers(env)
    return env


def check_firebaserc_consistency(repo_root: Path, target_project: str) -> str | None:
    """F023 EC11: optional consistency check between target_project and the
    consumer repo's .firebaserc.

    Returns a status string on success/skip; raises EnvironmentsTargetMismatchError
    if .firebaserc declares projects but none of them resolve to target_project.
    Skips silently when .firebaserc is absent or has no projects block.
    """
    fr = repo_root / ".firebaserc"
    if not fr.is_file():
        return None
    try:
        data = json.loads(fr.read_text())
    except json.JSONDecodeError as exc:
        raise EnvironmentsValidationError(
            f"{fr}: malformed JSON — {exc}"
        ) from exc
    projects = (data.get("projects") or {}) if isinstance(data, dict) else {}
    if not projects:
        return None
    if target_project not in set(projects.values()):
        raise EnvironmentsTargetMismatchError(
            f"{fr} does not declare target_project={target_project!r}; "
            f"declared aliases→projects: {dict(sorted(projects.items()))}"
        )
    return f".firebaserc reaches {target_project}"


def validate_target(
    env: Environments,
    target_env: str,
    target_project: str | None,
) -> None:
    """Raise if (target_env, target_project) is not declared in the registry.

    Host-local plans (target_project=None) are exempt — they don't touch any
    cloud project, so registry checks are meaningless.
    """
    if target_project is None:
        return

    if target_env not in DECLARABLE_TIERS:
        raise EnvironmentsTargetMismatchError(
            f"target_env {target_env!r} is not in {list(DECLARABLE_TIERS)}"
        )

    block: EnvBlock | None = getattr(env, target_env)
    if block is None:
        declared = [t for t in DECLARABLE_TIERS if getattr(env, t) is not None]
        raise EnvironmentsTargetMismatchError(
            f"environments.json {env.repo!r} does not declare tier {target_env!r}; "
            f"declared tiers: {declared}"
        )

    candidates = [p for p in (block.firebase_project, block.gcp_project) if p]
    if target_project not in candidates:
        raise EnvironmentsTargetMismatchError(
            f"environments.json {env.repo!r} tier {target_env!r}: target_project "
            f"{target_project!r} does not match registered projects {candidates}"
        )


__all__ = [
    "DECLARABLE_TIERS",
    "ENVIRONMENTS_FILENAME",
    "EnvironmentsError",
    "EnvironmentsNotFoundError",
    "EnvironmentsTargetMismatchError",
    "EnvironmentsValidationError",
    "SCHEMAS_DIR",
    "check_firebaserc_consistency",
    "find_repo_root_for_plan",
    "load_environments",
    "validate_target",
]
