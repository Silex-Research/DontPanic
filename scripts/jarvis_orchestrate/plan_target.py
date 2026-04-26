"""F023 EC2 + EC7 — plan-level Target contract + prod gate.

Per D066, target_env / target_project live in a visible `## Target` section
of plan.md (NOT frontmatter — the schema v1.1 bump is deferred). This module
parses that section, normalizes the host-local sentinel, and enforces the
EC7 prod gate.
"""
from __future__ import annotations

import re

import yaml


VALID_TARGET_ENVS = {"dev", "staging", "prod"}
TARGET_PROJECT_NONE_SENTINEL = "none"
PROD_REQUIRED_GATES = ("pre_impl", "on_escalation")


_TARGET_SECTION_RE = re.compile(
    r"^##[ \t]+Target[ \t]*\n(?P<body>.*?)(?=^##[ \t]|\Z)",
    re.MULTILINE | re.DOTALL,
)
_YAML_BLOCK_RE = re.compile(
    r"^```(?:yaml|yml)?[ \t]*\n(?P<yaml>.*?)\n```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


class PlanTargetError(ValueError):
    """Raised when a plan's Target section is missing or malformed,
    or a prod plan lacks the required human_gates."""


def parse_target_section(plan_md_text: str) -> dict[str, str]:
    """Extract and validate target_env / target_project from plan.md.

    Returns a dict with keys 'target_env' and 'target_project'. The sentinel
    string 'none' for target_project is preserved here; loader-level code
    normalizes it to Python None via `normalize_target_project()`.
    """
    section_match = _TARGET_SECTION_RE.search(plan_md_text)
    if not section_match:
        raise PlanTargetError(
            "plan.md missing required `## Target` section. "
            "Add a section like:\n\n## Target\n\n```yaml\n"
            "target_env: dev\ntarget_project: <firebase-project-id>\n```"
        )

    body = section_match.group("body")
    yaml_match = _YAML_BLOCK_RE.search(body)
    if not yaml_match:
        raise PlanTargetError(
            "`## Target` section must contain a fenced ```yaml ...``` block "
            "with target_env and target_project."
        )

    try:
        parsed = yaml.safe_load(yaml_match.group("yaml")) or {}
    except yaml.YAMLError as exc:
        raise PlanTargetError(f"Target yaml block failed to parse: {exc}") from exc

    if not isinstance(parsed, dict):
        raise PlanTargetError(
            f"Target yaml block must be a mapping; got {type(parsed).__name__}"
        )

    target_env = parsed.get("target_env")
    target_project = parsed.get("target_project")

    if not target_env:
        raise PlanTargetError("Target section missing required key `target_env`")
    if target_env not in VALID_TARGET_ENVS:
        raise PlanTargetError(
            f"target_env must be one of {sorted(VALID_TARGET_ENVS)}; got {target_env!r}"
        )
    if not target_project:
        raise PlanTargetError(
            "Target section missing required key `target_project` "
            f"(use {TARGET_PROJECT_NONE_SENTINEL!r} for host-local plans with no cloud project)"
        )
    if not isinstance(target_project, str):
        raise PlanTargetError(
            f"target_project must be a string; got {type(target_project).__name__}"
        )

    return {"target_env": target_env, "target_project": target_project}


def validate_prod_gates(
    target_env: str,
    human_gates: list[str] | None,
    required_override: list[str] | None = None,
) -> None:
    """EC7 prod gate + Expansion B (requires_gates[] bridge from environments.json).

    When required_override is provided (non-None), it supersedes the hardcoded
    PROD_REQUIRED_GATES set and applies regardless of target_env (so a non-prod
    tier can declare its own required gates via environments.json). When
    required_override is None, the original behavior holds: only target_env=prod
    is gated, and the required set is the hardcoded PROD_REQUIRED_GATES.
    """
    if required_override is not None:
        required = list(required_override)
    elif target_env == "prod":
        required = list(PROD_REQUIRED_GATES)
    else:
        return
    gates = set(human_gates or [])
    missing = [g for g in required if g not in gates]
    if missing:
        source = "environments.json requires_gates" if required_override is not None else "hardcoded PROD gate"
        raise PlanTargetError(
            f"target_env={target_env} requires human_gates {required} ({source}); "
            f"missing: {missing}"
        )


def normalize_target_project(target_project: str) -> str | None:
    """Convert the 'none' sentinel string to Python None; pass other values through."""
    if target_project == TARGET_PROJECT_NONE_SENTINEL:
        return None
    return target_project


__all__ = [
    "PROD_REQUIRED_GATES",
    "PlanTargetError",
    "TARGET_PROJECT_NONE_SENTINEL",
    "VALID_TARGET_ENVS",
    "normalize_target_project",
    "parse_target_section",
    "validate_prod_gates",
]
