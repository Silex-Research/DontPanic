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

    # F023 EC12: forbid registry mutation via package managers.
    if (
        tool in {"npm", "yarn", "pnpm"}
        and len(argv) >= 4
        and argv[1:3] == ["config", "set"]
        and argv[3].startswith("registry")
    ):
        return _reject(
            f"{tool} config set registry mutates global package-manager state; "
            "use a project-local .npmrc/.yarnrc/.pnpmrc or env override"
        )

    # F023 EC12: gate dangerous push forms targeting protected branches.
    if tool == "git" and len(argv) >= 2 and argv[1] == "push":
        rest = argv[2:]
        force = ("--force" in rest) or ("-f" in rest) or any(
            r.startswith("--force-with-lease") for r in rest
        )
        if force:
            # Branch ref is the last positional arg following the remote name.
            non_flag = [r for r in rest if not r.startswith("-")]
            target_ref = non_flag[-1] if len(non_flag) >= 2 else ""
            target_branch = target_ref.split(":")[-1].split("/")[-1]
            if target_branch in {"main", "master"}:
                return _reject(
                    f"git push --force* to {target_branch!r} is high-risk; "
                    "rebase + open a PR or pin a different branch"
                )

    # F023 EC12: positive-flag enforcement for high-impact CLIs.
    required = check_required_flags(argv)
    if required is not None:
        return _reject(required)

    return GuardResult(True, "allowed")


# F023 EC12: explicit-flag requirements for state-mutating CLI invocations.
# Keys are tool names (Path(argv[0]).name); each entry maps an action-matching
# function to a list of required flag predicates (any-of-tuple = at least one).
def _action_includes(*actions: str):
    def predicate(argv: Sequence[str]) -> bool:
        rest = argv[1:]
        return any(a in rest for a in actions)
    return predicate


def _has_flag(*flag_aliases: str):
    def predicate(argv: Sequence[str]) -> bool:
        for f in flag_aliases:
            if f in argv:
                return True
            # Long flag with `=` form (e.g. --project=foo).
            if any(arg.startswith(f"{f}=") for arg in argv):
                return True
        return False
    return predicate


def _has_any(*group: str):
    """At-least-one-of group flag check (positional or --flag form)."""
    def predicate(argv: Sequence[str]) -> bool:
        return any(g in argv or any(a.startswith(f"{g}=") for a in argv) for g in group)
    return predicate


_REQUIRED_FLAG_RULES: list[tuple[str, callable, list[tuple[str, callable]]]] = [
    # firebase deploy must declare --project explicitly so cross-tier deploys
    # can never silently inherit ambient configstore state.
    (
        "firebase",
        _action_includes("deploy", "emulators:exec", "functions:shell",
                          "hosting:channel:deploy"),
        [("--project", _has_flag("--project", "-P"))],
    ),
    # xcodebuild's build/archive/test must pin scheme + configuration +
    # destination + derivedDataPath so parallel agents don't share simulator
    # state or DerivedData caches.
    (
        "xcodebuild",
        _action_includes("build", "archive", "test", "test-without-building"),
        [
            ("-scheme", _has_flag("-scheme")),
            ("-configuration", _has_flag("-configuration")),
            ("-destination", _has_flag("-destination")),
            ("-derivedDataPath", _has_flag("-derivedDataPath")),
        ],
    ),
    # gradle invocations must pin --gradle-user-home plus an explicit
    # flavor/buildType (any of common shapes).
    (
        "gradle",
        lambda argv: any(t.startswith(("assemble", "bundle", "publish", "test"))
                         for t in argv[1:]),
        [
            ("--gradle-user-home", _has_flag("--gradle-user-home")),
        ],
    ),
    # terraform apply/plan/destroy must reference an explicit backend config
    # (or a workspace having been selected — supervisor checks the flag form).
    (
        "terraform",
        _action_includes("apply", "plan", "destroy"),
        [
            (
                "-backend-config / TF_DATA_DIR",
                lambda argv: _has_flag("-backend-config")(argv)
                or _has_flag("-state")(argv),
            ),
        ],
    ),
    # kubectl mutating verbs require an explicit --context (the EC10 overlay's
    # KUBECONFIG isolates the kubeconfig file, but in-file context selection
    # still needs to be pinned).
    (
        "kubectl",
        _action_includes("apply", "delete", "edit", "scale", "rollout",
                          "patch", "replace"),
        [("--context", _has_flag("--context"))],
    ),
]


def check_required_flags(command: str | Sequence[str]) -> str | None:
    """Return rejection reason if the command matches a positive-flag rule and
    misses a required flag; None when no rule applies or all flags present."""
    argv = _argv(command)
    if not argv:
        return None
    tool = Path(argv[0]).name
    for tool_name, action_match, requirements in _REQUIRED_FLAG_RULES:
        if tool != tool_name:
            continue
        if not action_match(argv):
            continue
        missing = [label for (label, predicate) in requirements if not predicate(argv)]
        if missing:
            return (
                f"{tool} action requires explicit flags missing: {missing}. "
                "Cross-tier mutations must always pin them rather than inherit "
                "from ambient CLI state."
            )
        return None
    return None


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


__all__ = [
    "CommandRejected",
    "GuardResult",
    "assert_allowed",
    "check_command",
    "check_required_flags",
]
