"""Showcase target configuration (Plan 2026-05-19-005 F001).

Each :class:`TargetSpec` declares one external repo we generate artifacts
for from inside DontPanic. The generator iterates ``DEFAULT_SHOWCASE_CONFIG``
unless an operator overrides it via ``--config <path>``.

Default checkout layout: sibling directories under
``~/Documents/GitHub/`` (operator's canonical layout). The generator
resolves ``repo_root`` lazily so missing-target degradation can emit a
clear ``skipping`` message and continue.

v0 ships four targets per Plan 5 D002 (operator chose Glam as the 4th
target at lock time):
- dontpanic            (self) → all three artifacts
- agent-conventions    → architecture only (no docs/plans/<plan-id>/)
- axiom                → architecture only (empty docs/plans)
- glam                 → architecture + validate-plans-strict (has plan dirs)

SpinDine is queued for a follow-on showcase expansion. Operators who
want SpinDine in their local sweep can pass ``--config <path>`` with a
JSON config that adds it; it intentionally stays out of the default
``--all`` set so the committed v0 artifact surface matches D002 exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SUPPORTED_ARTIFACT_KINDS = frozenset({"architecture", "validate_plans_strict", "drift"})


@dataclass(frozen=True)
class TargetSpec:
    """One showcase target.

    ``supported_artifacts`` MUST be a subset of
    :data:`SUPPORTED_ARTIFACT_KINDS`; the generator silently skips
    unsupported kinds rather than emitting false-positive failures.

    ``has_dontpanic_plans``: target follows the DontPanic v1.9 plan-dir
    convention (docs/plans/<plan-id>/{plan.md, features.json}).
    ``has_committed_architecture_json``: target ships
    docs/architecture/architecture.json (only DontPanic itself in v0).
    """

    repo_key: str
    label: str
    repo_root: Path
    description: str
    supported_artifacts: frozenset[str]
    has_dontpanic_plans: bool
    has_committed_architecture_json: bool

    def __post_init__(self) -> None:
        unsupported = self.supported_artifacts - SUPPORTED_ARTIFACT_KINDS
        if unsupported:
            raise ValueError(
                f"TargetSpec {self.repo_key}: unsupported artifact kinds "
                f"{sorted(unsupported)}; allowed: {sorted(SUPPORTED_ARTIFACT_KINDS)}"
            )
        if "validate_plans_strict" in self.supported_artifacts and not self.has_dontpanic_plans:
            raise ValueError(
                f"TargetSpec {self.repo_key}: validate_plans_strict requires "
                "has_dontpanic_plans=True"
            )
        if "drift" in self.supported_artifacts and not self.has_committed_architecture_json:
            raise ValueError(
                f"TargetSpec {self.repo_key}: drift requires "
                "has_committed_architecture_json=True"
            )


def _sibling_repo(name: str) -> Path:
    """Resolve ``~/Documents/GitHub/<name>`` against the DontPanic checkout's
    parent. Resolved lazily so the generator's missing-target message can
    print the literal path the operator should fix."""
    here = Path(__file__).resolve()
    # showcase/__file__ → showcase → dontpanic_orchestrate → scripts → repo
    repo_root = here.parents[3]
    return repo_root.parent / name


def _self_repo_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[3]


def default_showcase_config() -> list[TargetSpec]:
    """Build the default config. Function-form so paths are resolved
    against the live filesystem at call time — tests that monkeypatch
    the layout or move the repo get fresh resolution. The module also
    exposes ``DEFAULT_SHOWCASE_CONFIG`` (resolved once at import) for
    callers that want a constant per acceptance criteria."""
    return [
        TargetSpec(
            repo_key="dontpanic",
            label="DontPanic",
            repo_root=_self_repo_root(),
            description=(
                "Orchestration platform — Python supervisor + crawler + "
                "doctor + plan inventory. Showcase shows architecture + "
                "every locked plan's strict-validate status + drift between "
                "the committed architecture.json and the live source tree."
            ),
            supported_artifacts=frozenset({"architecture", "validate_plans_strict", "drift"}),
            has_dontpanic_plans=True,
            has_committed_architecture_json=True,
        ),
        TargetSpec(
            repo_key="agent-conventions",
            label="agent-conventions",
            repo_root=_sibling_repo("agent-conventions"),
            description=(
                "Shared schemas + Pydantic models + plan-artifact resolver. "
                "Schema repo — makes the abstract module-and-validator "
                "surface legible in one map."
            ),
            supported_artifacts=frozenset({"architecture"}),
            has_dontpanic_plans=False,
            has_committed_architecture_json=False,
        ),
        TargetSpec(
            repo_key="axiom",
            label="axiom",
            repo_root=_sibling_repo("axiom"),
            description=(
                "Research workspace (pnpm monorepo). Architecture-only "
                "showcase — axiom has no DontPanic-style plan dirs in v0."
            ),
            supported_artifacts=frozenset({"architecture"}),
            has_dontpanic_plans=False,
            has_committed_architecture_json=False,
        ),
        TargetSpec(
            repo_key="glam",
            label="Glam",
            repo_root=_sibling_repo("Glam"),
            description=(
                "iOS app — creator hub + commerce surface. Largest module "
                "surface of the four targets; architecture map visualizes "
                "iOS feature/service/repo layering."
            ),
            supported_artifacts=frozenset({"architecture", "validate_plans_strict"}),
            has_dontpanic_plans=True,
            has_committed_architecture_json=False,
        ),
    ]


# Module-level constant requested by the F001 acceptance contract.
# Resolved at import — TargetSpec.repo_root values are pure ``Path``
# objects with no filesystem side effects, so a single eager resolution
# is safe (the lazy factory above remains available for tests that
# need a fresh list each call).
DEFAULT_SHOWCASE_CONFIG: list[TargetSpec] = default_showcase_config()
