"""Plan 2026-06-05-004 F003 — sufficiency-pack registry + unrouteable-skills inventory.

A declarative map from canonical surface (F001) to the convention/skill items a plan
touching that surface must dispose of. v0 SEEDS ONLY the frontend pack from the shipped
standards; the other canonical surfaces are named, demand-gated stubs (empty lists) so
the shape is complete but content stays demand-gated.

Separately, because the skill-applicability matcher silently skips skills whose SKILL.md
lacks (or malforms) ``applies_to``, :func:`unrouteable_skills` LISTS them so "all skills
considered" is visible, not assumed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from dontpanic_orchestrate.surface_taxonomy import CANONICAL_SURFACES


@dataclass(frozen=True)
class PackItem:
    """One required convention/skill a plan must dispose of for a surface."""

    id: str
    prove: str
    reference: str


# The ONE seeded pack (the dashboard / read-only-UI worked example), drawn from the
# shipped standards. Every other canonical surface is a demand-gated stub (empty list).
_FRONTEND_PACK: tuple[PackItem, ...] = (
    PackItem(
        "design-system-consistency",
        "Components + tokens follow the dashboard design system (shared primitives, no bespoke reinvention).",
        "docs/dashboard-design-system.md",
    ),
    PackItem(
        "real-shell-journey-proof",
        "A real-state→real-shell journey test enters the surface the operator uses (not render-helper-only).",
        "docs/qa-sufficiency-contract.md",
    ),
    PackItem(
        "action-affordance-honesty",
        "Action labels match behavior (copy vs run vs open) and show success/failure feedback.",
        "docs/dashboard-design-system.md#6-action-affordance-honesty-non-negotiable",
    ),
    PackItem(
        "visible-state-coverage",
        "Loading / empty / zero / error states are visibly distinct (never-ran vs corrupt).",
        "docs/dashboard-design-system.md#7-state-coverage-contract",
    ),
    PackItem(
        "accessibility-contrast-focus",
        "Focus-visible, AA contrast, and non-color status cues are present.",
        "docs/dashboard-design-system.md#9-accessibility-baseline-target-wcag-21-aa",
    ),
    PackItem(
        "component-token-consistency",
        "No unstyled emitted class; page CSS uses tokens (no raw hex/px).",
        "docs/dashboard-design-system.md#11-governance--enforcement",
    ),
)

# canonical surface -> required items. Frontend seeded; the rest are demand-gated stubs.
PACK_REGISTRY: dict[str, tuple[PackItem, ...]] = {
    surface: (_FRONTEND_PACK if surface == "frontend-ui" else ())
    for surface in CANONICAL_SURFACES
}


def get_pack(surface: str) -> list[PackItem]:
    """Return the required items for a canonical surface ([] for stubs / unknown)."""
    return list(PACK_REGISTRY.get(surface, ()))


def is_stub_surface(surface: str) -> bool:
    """True when ``surface`` is a known canonical surface with no seeded items yet."""
    return surface in PACK_REGISTRY and not PACK_REGISTRY[surface]


def _is_routeable_skill(meta: Mapping[str, object]) -> bool:
    applies = meta.get("applies_to")
    if not isinstance(applies, Mapping):
        return False  # missing entirely, or malformed (string/list/etc.)
    surfaces = applies.get("surfaces")
    return isinstance(surfaces, (list, tuple)) and len(surfaces) > 0


def unrouteable_skills(skill_metas: Iterable[Mapping[str, object]]) -> list[str]:
    """Names of skills with missing/malformed/empty ``applies_to`` (sorted).

    These are the skills the applicability matcher silently skips today — listing them
    makes "all skills considered" visible rather than assumed.
    """
    return sorted(
        str(m.get("name", "<unnamed>"))
        for m in skill_metas
        if not _is_routeable_skill(m)
    )
