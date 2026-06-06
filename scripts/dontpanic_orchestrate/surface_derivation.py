"""Plan 2026-06-05-004 F002 — derive a plan's canonical surfaces.

Pure: unions a plan's DECLARED surface class with surfaces INFERRED from its changed/
declared paths, resolving every input through the F001 canonical alias map so the four
source vocabularies converge on one canonical set. Unknown inputs are reported (not
dropped) via :attr:`SurfaceDerivation.unrouteable`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from dontpanic_orchestrate.plan_review.lint import surfaces_in
from dontpanic_orchestrate.surface_taxonomy import UNROUTEABLE, resolve_surface


@dataclass(frozen=True)
class SurfaceDerivation:
    """Canonical surfaces a plan touches + any inputs that could not be routed."""

    canonical: set[str] = field(default_factory=set)
    unrouteable: set[str] = field(default_factory=set)


# Path-pattern → source-vocabulary token. Resolved through the canonical alias map, so a
# new alias automatically re-targets these. Kept small + explicit (v0).
_PATH_SIGNALS: tuple[tuple[str, str], ...] = (
    ("dashboard/", "dashboard"),
    (".css", "dashboard"),
    (".html", "dashboard"),
    (".swift", "ios"),
    ("/ios/", "ios"),
    ("/android/", "android"),
    (".kt", "android"),
    ("cli.py", "cli"),
    ("/cli", "cli"),
    (".schema.json", "schema"),
    ("/migrations/", "persistence"),
    (".tf", "infra"),
    ("wrangler", "infra"),
    ("firebase.json", "infra"),
)


def _tokens_from_paths(paths: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for raw in paths:
        p = raw.lower()
        for needle, token in _PATH_SIGNALS:
            if needle in p:
                out.add(token)
    return out


def derive_surfaces(
    *,
    declared: Iterable[str] = (),
    paths: Iterable[str] = (),
    text: str = "",
) -> SurfaceDerivation:
    """Return the canonical surfaces a plan touches (+ unrouteable inputs).

    ``declared``: the plan's declared surface-class tokens.
    ``paths``: changed / declared file paths.
    ``text``: optional free text (plan/feature prose) — tagged via the existing
    plan-review surface tagger and resolved through the canonical map.
    """
    paths = list(paths)
    tokens: set[str] = set(declared)
    tokens |= _tokens_from_paths(paths)
    if text or paths:
        # Reuse the existing plan-review surface tagging (returns () on no match).
        tokens |= set(surfaces_in(f"{text}\n" + "\n".join(paths)))

    canonical: set[str] = set()
    unrouteable: set[str] = set()
    for tok in tokens:
        resolved = resolve_surface(tok)
        if resolved == UNROUTEABLE:
            unrouteable.add(tok)
        else:
            canonical.add(resolved)
    return SurfaceDerivation(canonical=canonical, unrouteable=unrouteable)
