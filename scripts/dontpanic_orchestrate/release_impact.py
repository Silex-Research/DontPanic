"""Plan 2026-05-23-007 F003 — release-impact advisory checker.

Maps a plan's declared intent (draft-time) and/or a git diff (lock-time) to
the operator-visible surfaces that probably need updates: root CHANGELOG.md,
agent-conventions changelog, README, onboarding, architecture map, dashboard,
capability manifests, CLI help, schemas, public metadata.

The checker is intentionally advisory:

  - It never blocks plan lock, dispatch, or audit.
  - It writes nothing. The caller picks the rendering surface — `dontpanic
    next` is the v0 primary, plan-lock messaging is the v0 secondary.
  - False positives are tolerated; the path patterns favor recall over
    precision so a docs/dashboard/CLI change doesn't silently slip past the
    operator.

Public surface:
  - :data:`SURFACES`              tuple of all advisory surface ids
  - :class:`ReleaseImpactAdvisory` value type returned to callers
  - :func:`analyze_paths`         path-only advisory (lock-time git diff)
  - :func:`analyze_plan_intent`   intent-only advisory (draft-time plan)
  - :func:`analyze`               combines both inputs
  - :func:`render_text`           short human-readable summary

The path/surface pattern table lives in ``docs/RELEASE_IMPACT.md`` and is
mirrored as :data:`_PATH_PATTERNS` below. Updating one without the other is
a docs/code drift and is caught by the F003 tests.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Iterable

# ─────────────────────────  surface vocabulary  ─────────────────────────

# Stable surface ids. The order here is also the rendering order.
SURFACES: tuple[str, ...] = (
    "root_changelog",
    "shared_changelog",
    "readme",
    "onboarding",
    "architecture",
    "dashboard",
    "capability_manifest",
    "cli_help",
    "schemas",
    "public_metadata",
)

_SURFACE_DESCRIPTIONS: dict[str, str] = {
    "root_changelog": "root CHANGELOG.md (product-facing entry)",
    "shared_changelog": "claude/shared/CHANGELOG.md (agent-conventions subtree)",
    "readme": "README.md",
    "onboarding": "onboarding / getting-started / init / doctor flow",
    "architecture": "architecture map (docs/architecture/**)",
    "dashboard": "dashboard UX or state shape",
    "capability_manifest": "capability manifest(s) under capabilities/",
    "cli_help": "CLI command, flag, or --help text",
    "schemas": "claude/shared/schemas/** (and Pydantic mirrors)",
    "public_metadata": "repo description / social preview / discoverability",
}


# ─────────────────────────  path → surface map  ─────────────────────────
#
# Order matters: the first matching pattern in a rule contributes its
# surfaces. A path may match multiple rules; the union is reported. Globs
# use fnmatch semantics with the explicit "**" extension expanded by
# :func:`_match_glob`.

# Rules are (label, glob, surfaces_to_suggest). The label is what the
# advisory prints back so the operator can see *why* a surface was
# suggested.
_PATH_RULE = tuple[str, str, tuple[str, ...]]

# Internal/no-changelog patterns are matched first. A hit here suppresses
# all later rules for that path so internal scaffolding doesn't drag
# public surfaces into the advisory.
_INTERNAL_PATTERNS: tuple[str, ...] = (
    "docs/plans/**",
    "**/audit/**",
    "**/evidence/**",
    "**/decisions.jsonl",
    "**/events.jsonl",
    "**/INBOX.md",
    "**/__pycache__/**",
    "**/*.pyc",
    "scripts/dontpanic_orchestrate/tests/**",
    "scripts/dontpanic_orchestrate/runtime_evidence/**",
    "scripts/dontpanic_orchestrate/showcase/**",
)

# Rule table — keep in lockstep with docs/RELEASE_IMPACT.md.
_PATH_PATTERNS: tuple[_PATH_RULE, ...] = (
    # Schemas under the agent-conventions subtree → shared changelog +
    # schemas surface. The CLI starts enforcing a schema is a separate
    # signal callers must layer on top.
    (
        "agent-conventions schema",
        "claude/shared/schemas/**",
        ("shared_changelog", "schemas"),
    ),
    (
        "agent-conventions models",
        "claude/shared/**/models/**",
        ("shared_changelog", "schemas"),
    ),
    (
        "agent-conventions resolver/conventions",
        "claude/shared/**",
        ("shared_changelog",),
    ),
    # README / public docs / onboarding.
    (
        "README",
        "README.md",
        ("root_changelog", "readme"),
    ),
    (
        "getting-started doc",
        "docs/GETTING_STARTED.md",
        ("root_changelog", "onboarding"),
    ),
    (
        "agent quickstart",
        "docs/AGENT_QUICKSTART.md",
        ("root_changelog", "onboarding"),
    ),
    (
        "public docs",
        "docs/PRODUCT.md",
        ("root_changelog", "readme"),
    ),
    (
        "public docs",
        "docs/USE_CASES.md",
        ("root_changelog", "readme"),
    ),
    (
        "public docs",
        "docs/ECOSYSTEM.md",
        ("root_changelog", "readme"),
    ),
    (
        "public docs",
        "docs/DISCOVERABILITY.md",
        ("root_changelog", "public_metadata"),
    ),
    # Architecture surface.
    (
        "architecture docs",
        "docs/architecture/**",
        ("architecture",),
    ),
    (
        "architecture map",
        "docs/architecture.json",
        ("architecture",),
    ),
    # Dashboard surface.
    (
        "dashboard assets",
        "dashboard/**",
        ("root_changelog", "dashboard"),
    ),
    (
        "dashboard backend",
        "scripts/dontpanic_orchestrate/dashboard*.py",
        ("root_changelog", "dashboard"),
    ),
    (
        "operator console",
        "scripts/dontpanic_orchestrate/operator_console.py",
        ("root_changelog", "dashboard"),
    ),
    (
        "state projection",
        "scripts/dontpanic_orchestrate/state_projection.py",
        ("dashboard",),
    ),
    # Capability manifests.
    (
        "capability manifest",
        "capabilities/*.json",
        ("root_changelog", "capability_manifest"),
    ),
    # CLI surface — the canonical operator interface.
    (
        "CLI entry point",
        "scripts/dontpanic_orchestrate/cli.py",
        ("root_changelog", "cli_help"),
    ),
    (
        "CLI module",
        "scripts/dontpanic_orchestrate/__main__.py",
        ("root_changelog", "cli_help"),
    ),
    # Public metadata / discoverability.
    (
        "repo metadata",
        ".github/repository.yml",
        ("root_changelog", "public_metadata"),
    ),
    (
        "social preview",
        ".github/social-preview*",
        ("root_changelog", "public_metadata"),
    ),
    (
        "package metadata",
        "pyproject.toml",
        ("root_changelog", "public_metadata"),
    ),
    # Firebase / Firestore deployable surfaces.
    (
        "Firebase config",
        "firebase.json",
        ("root_changelog",),
    ),
    (
        "Firestore rules",
        "firestore.rules",
        ("root_changelog",),
    ),
    (
        "Firestore indexes",
        "firestore.indexes.json",
        ("root_changelog",),
    ),
    (
        "Storage rules",
        "storage.rules",
        ("root_changelog",),
    ),
    # General docs catch-all — informational only, no changelog mandate.
    (
        "general docs",
        "docs/*.md",
        (),
    ),
)


# ─────────────────────────  intent-specific broad-glob normalization  ─────────────────────────
#
# Charter ``allowed_paths`` often declare broad subtree globs like ``docs/**``
# that the concrete-path rule table above (whose globs match specific files
# such as ``docs/PRODUCT.md``) does not fire on. Without normalization,
# ``analyze_plan_intent(allowed_paths=["docs/**"])`` would return zero
# surfaces and mislabel the plan as internal-only.
#
# This table is consulted ONLY by :func:`analyze_plan_intent`. Each entry is
# (allowed_paths value, rule label, suggested surfaces). Matching is literal
# (after normalization) so a narrow glob like ``docs/synthetic/**`` does NOT
# fire the broad ``docs/**`` rule — the operator declared a narrow scope and
# we respect that. Lock-time path scans use the concrete rule table above
# instead.

_INTENT_BROAD_PATTERNS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # docs subtree — broad covers README/onboarding/product docs.
    (
        "docs subtree (broad)",
        ("docs/**", "docs/*", "docs", "docs/"),
        ("root_changelog", "readme", "onboarding"),
    ),
    # agent-conventions subtree — schemas + shared changelog.
    (
        "agent-conventions subtree (broad)",
        ("claude/shared/**", "claude/shared", "claude/shared/"),
        ("shared_changelog",),
    ),
    (
        "agent-conventions schemas (broad)",
        ("claude/shared/schemas/**", "claude/shared/schemas"),
        ("shared_changelog", "schemas"),
    ),
    # Architecture subtree.
    (
        "architecture subtree (broad)",
        ("docs/architecture/**", "docs/architecture"),
        ("architecture",),
    ),
    # Dashboard subtree (already matched by concrete rules, but listed here
    # for symmetry so an operator reading the intent rules sees the full set).
    (
        "dashboard subtree (broad)",
        ("dashboard/**", "dashboard", "dashboard/"),
        ("root_changelog", "dashboard"),
    ),
    # Capability manifests.
    (
        "capability manifest subtree (broad)",
        ("capabilities/**", "capabilities/*", "capabilities"),
        ("root_changelog", "capability_manifest"),
    ),
    # CLI subtree — covers cli.py and __main__.py.
    (
        "CLI subtree (broad)",
        (
            "scripts/dontpanic_orchestrate/cli.py",
            "scripts/dontpanic_orchestrate/cli*",
            "scripts/dontpanic_orchestrate/__main__.py",
        ),
        ("root_changelog", "cli_help"),
    ),
    # Public metadata / .github.
    (
        ".github subtree (broad)",
        (".github/**", ".github"),
        ("root_changelog", "public_metadata"),
    ),
)


def _normalize_intent_path(raw: str) -> str:
    s = str(raw).strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


# ─────────────────────────  plan-intent → surface map  ─────────────────────────
#
# Plans declare an optional `surfaces` field (see plan.schema.json). The
# values map onto the release-impact surfaces below; missing entries fall
# back to path-based inference. The mapping is broad on purpose.

_PLAN_SURFACE_TO_RELEASE: dict[str, tuple[str, ...]] = {
    "docs": ("root_changelog", "readme", "onboarding"),
    "ux": ("root_changelog", "dashboard"),
    "web": ("root_changelog", "dashboard"),
    "ios": ("root_changelog",),
    "android": ("root_changelog",),
    "backend": ("root_changelog",),
    # `infra` covers schemas + capabilities + CLI in DontPanic. Suggest
    # both root and shared changelog plus CLI; operator narrows.
    "infra": ("root_changelog", "cli_help", "capability_manifest", "schemas", "shared_changelog"),
    "security": ("root_changelog",),
    "data": ("root_changelog", "schemas"),
    "ml": ("root_changelog",),
    "external-api-wrap": ("root_changelog", "cli_help"),
}


# ─────────────────────────  data shape  ─────────────────────────


@dataclass(frozen=True)
class SurfaceSuggestion:
    """One advisory surface plus the evidence that triggered it.

    ``evidence`` is a sorted tuple of human-readable strings — either
    "path X matched rule Y" or "plan declared surface=Z".
    """

    surface: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"surface": self.surface, "evidence": list(self.evidence)}


@dataclass(frozen=True)
class ReleaseImpactAdvisory:
    """The full advisory bundle.

    ``surfaces`` is the deduplicated set of suggested surfaces, in the
    rendering order defined by :data:`SURFACES`. ``internal_only`` is True
    when every change matched only internal-no-changelog patterns and no
    plan-intent signal contributed a surface — the advisory then reduces
    to "no release-impact updates needed" and renders compactly.
    """

    surfaces: tuple[SurfaceSuggestion, ...]
    internal_only: bool = False
    inputs: dict[str, Any] = field(default_factory=dict)

    def surface_ids(self) -> tuple[str, ...]:
        return tuple(s.surface for s in self.surfaces)

    def to_dict(self) -> dict[str, Any]:
        return {
            "surfaces": [s.to_dict() for s in self.surfaces],
            "internal_only": self.internal_only,
            "inputs": dict(self.inputs),
        }


# ─────────────────────────  glob matching  ─────────────────────────


def _match_glob(path: str, pattern: str) -> bool:
    """fnmatch-with-``**``. ``**`` matches across path separators; ``*``
    does not. Patterns are matched against the path as-is.
    """
    if "**" not in pattern:
        # Plain fnmatch — but tighten ``*`` so it doesn't cross slashes.
        # We approximate by splitting both into segments and matching
        # segment-by-segment when the pattern has no ``**``.
        path_segs = path.split("/")
        pat_segs = pattern.split("/")
        if len(path_segs) != len(pat_segs):
            return False
        return all(fnmatch.fnmatchcase(p, q) for p, q in zip(path_segs, pat_segs))
    # ``**`` is present — convert to a fnmatch-friendly pattern with a
    # single placeholder. fnmatch treats ``*`` as "any chars except
    # nothing-special" so we replace ``**`` with a sentinel, escape the
    # rest, then put a real ``*`` back. fnmatch's translate() handles
    # the ``*`` → ``.*`` job once we collapse "**" to "*".
    # Simpler approach: replace ``**`` with ``\x00`` (literal placeholder)
    # then re-substitute after escaping.
    # We just rely on fnmatch's ``*`` and let ``**`` collapse — for our
    # rule set ``**`` and ``*`` produce the same match because rule
    # globs are anchored.
    collapsed = pattern.replace("**", "*")
    return fnmatch.fnmatchcase(path, collapsed)


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(_match_glob(path, p) for p in patterns)


# ─────────────────────────  path analyzer  ─────────────────────────


def analyze_paths(paths: Iterable[str]) -> ReleaseImpactAdvisory:
    """Produce an advisory from a flat list of changed paths.

    Each path is normalized to POSIX separators and matched against the
    internal-suppression patterns first; surviving paths run through the
    public-surface rule table. The output is a deduplicated set of
    :class:`SurfaceSuggestion` values with the matching rule labels as
    evidence.
    """
    cleaned: list[str] = []
    for raw in paths:
        if raw is None:
            continue
        s = str(raw).strip().replace("\\", "/")
        # Strip a leading "./" prefix (a literal ``./``), not arbitrary
        # leading dots — paths like ``.github/social-preview.png`` must
        # keep their leading dot intact.
        while s.startswith("./"):
            s = s[2:]
        if s:
            cleaned.append(s)

    # surface → set of evidence strings
    accum: dict[str, set[str]] = {}
    any_public_match = False
    for path in cleaned:
        if _matches_any(path, _INTERNAL_PATTERNS):
            # Internal-only — no surface contributions.
            continue
        any_public_match_for_path = False
        for label, glob, surfaces in _PATH_PATTERNS:
            if not _match_glob(path, glob):
                continue
            any_public_match_for_path = True
            if not surfaces:
                continue
            for s in surfaces:
                accum.setdefault(s, set()).add(f"{path} matched {label!r}")
        if any_public_match_for_path:
            any_public_match = True

    internal_only = not accum
    if internal_only and cleaned and not any_public_match:
        # All matched paths were either internal-suppression or matched
        # no rule at all — render as internal-only.
        internal_only = True

    surfaces_out = tuple(
        SurfaceSuggestion(surface=s, evidence=tuple(sorted(accum[s])))
        for s in SURFACES
        if s in accum
    )
    return ReleaseImpactAdvisory(
        surfaces=surfaces_out,
        internal_only=internal_only,
        inputs={"paths": list(cleaned)},
    )


# ─────────────────────────  plan-intent analyzer  ─────────────────────────


def analyze_plan_intent(
    *,
    plan_surfaces: Iterable[str] | None = None,
    allowed_paths: Iterable[str] | None = None,
    step_path_tokens: Iterable[str] | None = None,
) -> ReleaseImpactAdvisory:
    """Produce an advisory from declared plan intent.

    ``plan_surfaces``  — the plan's frontmatter ``surfaces`` array.
    ``allowed_paths``  — the child charter's ``allowed_paths`` (globs).
    ``step_path_tokens`` — path-like tokens already extracted from feature
                          ``steps`` (e.g. by the readiness recommender).

    The path-shaped inputs are routed through :func:`analyze_paths` so the
    same rule table covers them; the symbolic ``plan_surfaces`` values
    consult :data:`_PLAN_SURFACE_TO_RELEASE`.
    """
    accum: dict[str, set[str]] = {}

    # Plan-declared `surfaces`.
    decl = list(plan_surfaces or [])
    for s in decl:
        s_key = str(s).strip()
        if not s_key:
            continue
        mapped = _PLAN_SURFACE_TO_RELEASE.get(s_key)
        if not mapped:
            continue
        for ms in mapped:
            accum.setdefault(ms, set()).add(f"plan declared surface={s_key!r}")

    # Path-shaped intent — allowed_paths globs and step tokens.
    # We feed them through the path analyzer so a single rule table
    # governs both inputs.
    pseudo_paths: list[str] = []
    for ap in allowed_paths or []:
        # Glob patterns like "docs/**/*.md" still match our rule globs
        # because fnmatch is symmetric for the simple cases here.
        pseudo_paths.append(str(ap))
    for tok in step_path_tokens or []:
        pseudo_paths.append(str(tok))

    if pseudo_paths:
        sub = analyze_paths(pseudo_paths)
        for entry in sub.surfaces:
            for ev in entry.evidence:
                accum.setdefault(entry.surface, set()).add(
                    f"plan-intent {ev}"
                )

    # Broad-glob intent normalization: charter ``allowed_paths`` like
    # ``docs/**`` do not match the concrete-path rule table above. Walk the
    # intent-broad pattern table to fill in the gap. Match is literal (after
    # normalization) so a narrow glob like ``docs/synthetic/**`` does NOT
    # fire the broad ``docs/**`` rule — the operator declared narrow scope
    # and we respect that.
    for ap in allowed_paths or []:
        ap_norm = _normalize_intent_path(ap)
        if not ap_norm:
            continue
        for label, triggers, surfaces in _INTENT_BROAD_PATTERNS:
            if ap_norm not in triggers:
                continue
            for s in surfaces:
                accum.setdefault(s, set()).add(
                    f"plan-intent allowed_paths={ap_norm!r} matched {label!r}"
                )

    surfaces_out = tuple(
        SurfaceSuggestion(surface=s, evidence=tuple(sorted(accum[s])))
        for s in SURFACES
        if s in accum
    )
    return ReleaseImpactAdvisory(
        surfaces=surfaces_out,
        internal_only=not surfaces_out and bool(decl or pseudo_paths),
        inputs={
            "plan_surfaces": decl,
            "allowed_paths": list(allowed_paths or []),
            "step_path_tokens": list(step_path_tokens or []),
        },
    )


# ─────────────────────────  combined analyzer  ─────────────────────────


def analyze(
    *,
    changed_paths: Iterable[str] | None = None,
    plan_surfaces: Iterable[str] | None = None,
    allowed_paths: Iterable[str] | None = None,
    step_path_tokens: Iterable[str] | None = None,
) -> ReleaseImpactAdvisory:
    """Combine a lock-time path scan and a draft-time intent scan.

    Both inputs are optional. The union of suggested surfaces is returned
    with evidence merged. When both inputs are empty the advisory is
    internal-only (i.e. nothing to suggest).
    """
    path_adv = analyze_paths(changed_paths or [])
    intent_adv = analyze_plan_intent(
        plan_surfaces=plan_surfaces,
        allowed_paths=allowed_paths,
        step_path_tokens=step_path_tokens,
    )

    accum: dict[str, set[str]] = {}
    for entry in path_adv.surfaces:
        accum.setdefault(entry.surface, set()).update(entry.evidence)
    for entry in intent_adv.surfaces:
        accum.setdefault(entry.surface, set()).update(entry.evidence)

    surfaces_out = tuple(
        SurfaceSuggestion(surface=s, evidence=tuple(sorted(accum[s])))
        for s in SURFACES
        if s in accum
    )
    any_input = bool(path_adv.inputs.get("paths")) or bool(
        intent_adv.inputs.get("plan_surfaces")
        or intent_adv.inputs.get("allowed_paths")
        or intent_adv.inputs.get("step_path_tokens")
    )
    return ReleaseImpactAdvisory(
        surfaces=surfaces_out,
        internal_only=not surfaces_out and any_input,
        inputs={
            "changed_paths": path_adv.inputs.get("paths", []),
            "plan_surfaces": intent_adv.inputs.get("plan_surfaces", []),
            "allowed_paths": intent_adv.inputs.get("allowed_paths", []),
            "step_path_tokens": intent_adv.inputs.get("step_path_tokens", []),
        },
    )


# ─────────────────────────  rendering  ─────────────────────────


def render_text(advisory: ReleaseImpactAdvisory) -> str:
    """One-paragraph human-readable summary suitable for `dontpanic next`
    text output or plan-lock messaging.
    """
    if not advisory.surfaces:
        if advisory.internal_only:
            return (
                "Release impact: no public-surface updates inferred — the "
                "scanned changes look internal-only. Confirm before lock; "
                "see docs/RELEASE_IMPACT.md for the full checklist."
            )
        return (
            "Release impact: no advisory inputs supplied. "
            "See docs/RELEASE_IMPACT.md for the full checklist."
        )
    lines = ["Release impact (advisory — confirm before lock):"]
    for entry in advisory.surfaces:
        descr = _SURFACE_DESCRIPTIONS.get(entry.surface, entry.surface)
        lines.append(f"  • {entry.surface} — {descr}")
        # Show up to 3 evidence entries; collapse the rest.
        for ev in entry.evidence[:3]:
            lines.append(f"      ↳ {ev}")
        if len(entry.evidence) > 3:
            lines.append(f"      ↳ (+{len(entry.evidence) - 3} more)")
    return "\n".join(lines)


__all__ = [
    "ReleaseImpactAdvisory",
    "SURFACES",
    "SurfaceSuggestion",
    "analyze",
    "analyze_paths",
    "analyze_plan_intent",
    "render_text",
]
