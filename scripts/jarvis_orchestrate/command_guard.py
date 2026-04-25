"""Guardrails for commands that mutate process-global tool state."""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


class CommandRejected(ValueError):
    """Raised when a command is forbidden by Jarvis execution policy."""


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str


def check_command(
    command: str | Sequence[str],
    env: Mapping[str, str] | None = None,
) -> GuardResult:
    argv = _argv(command)
    if not argv:
        return GuardResult(True, "empty command")

    tool = Path(argv[0]).name
    env = env or {}

    if _matches(argv, "gcloud", "config", "set", "project"):
        return _reject(
            "gcloud config set project mutates shared gcloud state; "
            "pass --project or CLOUDSDK_CORE_PROJECT"
        )

    if _matches(
        argv, "gcloud", "config", "configurations", "activate"
    ) and not env.get("CLOUDSDK_CONFIG"):
        return _reject(
            "gcloud config configurations activate requires isolated CLOUDSDK_CONFIG"
        )

    if _matches(argv, "firebase", "use"):
        return _reject(
            "firebase use mutates configstore state; pass --project explicitly"
        )

    if _matches(argv, "kubectl", "config", "use-context"):
        return _reject(
            "kubectl config use-context mutates kubeconfig state; pass --context explicitly"
        )

    if _matches(argv, "gh", "auth", "switch"):
        return _reject(
            "gh auth switch mutates GitHub CLI auth state; "
            "set GH_CONFIG_DIR or GH_TOKEN explicitly"
        )

    if (
        tool in {"npm", "yarn", "pnpm"}
        and len(argv) >= 3
        and argv[1:3] == ["config", "set"]
    ):
        return _reject(
            f"{tool} config set mutates package-manager state; "
            "use a project-local config or env override"
        )

    if _matches(argv, "git", "config") and "--global" in argv[2:]:
        return _reject(
            "git config --global mutates user state; use --local in the target worktree"
        )

    if _matches(argv, "docker", "context", "use"):
        return _reject(
            "docker context use mutates Docker CLI state; pass --context explicitly"
        )

    return GuardResult(True, "allowed")


def assert_allowed(
    command: str | Sequence[str],
    env: Mapping[str, str] | None = None,
) -> None:
    result = check_command(command, env=env)
    if not result.allowed:
        raise CommandRejected(result.reason)


def _argv(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command)
    return [str(part) for part in command]


def _matches(argv: Sequence[str], *prefix: str) -> bool:
    if len(argv) < len(prefix):
        return False
    normalized = [Path(argv[0]).name, *argv[1:]]
    return list(prefix) == normalized[: len(prefix)]


def _reject(reason: str) -> GuardResult:
    return GuardResult(False, reason)


__all__ = ["CommandRejected", "GuardResult", "assert_allowed", "check_command"]
