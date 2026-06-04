"""Suggested-split proposer (F002).

A pure, deterministic function that turns an over-scoped feature — one F001
flagged ``over_surface`` or ``over_ac`` — into an *advisory* partition into
smaller child features. It allocates each of the parent's acceptance criteria
to exactly one child, labels each child with a single surface, and rewires
``depends_on`` so the children form a valid acyclic chain.

The output is data only (:class:`SplitProposal`): :func:`propose_split` never
mutates the plan, the feature, or the :class:`~dontpanic_orchestrate.plan_review.lint.ScopeReport`
it is handed. The operator accepts or edits the proposal; nothing here writes
``features.json``.

Conservation contract (acceptance #3): the multiset union of every child's
``acceptance_subset`` equals the parent's acceptance criteria — zero dropped,
zero duplicated. The partition is exhaustive and disjoint *by construction*
(each criterion, by index, lands in exactly one child's bucket), and the
invariant is additionally asserted in code before the proposal is returned.

Two split strategies:

  * **By surface** (``over_surface``). Each criterion is routed to the parent
    surface it most specifically touches (F001's :func:`tag_surfaces`), so
    every child touches exactly one surface (acceptance #2).
  * **By AC chunk** (``over_ac`` on a single surface). The criteria are sliced
    into sequential chunks no larger than a single dispatch's comfort band,
    each chunk a child on the parent's lone surface.

A single-surface, in-budget feature (no ``over_surface`` / ``over_ac`` flag)
yields ``None`` (acceptance #5).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from dontpanic_orchestrate.plan_review.lint import (
    ScopeReport,
    split_acceptance,
    surfaces_in,
)

# ─────────────────────────────── public types ──────────────────────────────

# The largest AC count a single child should carry when splitting a too-many-AC
# (but single-surface) feature into sequential chunks. Mirrors F001's
# ``_AC_WARN`` comfort band: a child at or below this stays inside one dispatch.
_MAX_CHILD_ACS = 6


class SplitConservationError(ValueError):
    """Raised if a proposed partition fails the conservation invariant.

    By construction the partition is exhaustive and disjoint, so this is a
    defensive guard rather than an expected path — but it is a real raised
    error (not a bare ``assert``) so the invariant is enforced even under
    ``python -O``."""


@dataclass(frozen=True)
class ChildFeature:
    """One proposed child of a split (advisory; not a real feature record).

    ``provisional_id`` is operator-facing only (``F016a``, ``F016b`` …) — it is
    *not* claimed in ``features.json`` until the operator accepts the split.
    ``surfaces`` is normally a single element — a clean child touches one
    surface (acceptance #2). When a *single* acceptance criterion is itself
    multi-surface (e.g. "the cli command and dashboard render agree"), it
    cannot be partitioned further, so the child honestly carries the union of
    the surfaces its criteria touch rather than silently claiming one; the
    offending criterion is also surfaced on
    :attr:`SplitProposal.multi_surface_acs` so the operator can sharpen it.
    ``acceptance_subset`` is the parent criteria routed to this child.
    ``depends_on`` chains the children (and threads the parent's own upstream
    dependencies onto the first child).
    """

    provisional_id: str
    surfaces: tuple[str, ...]
    acceptance_subset: tuple[str, ...]
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class SplitProposal:
    """Advisory partition of an over-scoped feature (acceptance #1, #4).

    ``multi_surface_acs`` lists any acceptance criterion that is *itself*
    multi-surface (text, sorted surfaces). Such an AC cannot be cleanly routed
    to a single-surface child, so it is reported for the operator to sharpen;
    the child holding it carries the union of its surfaces (see
    :class:`ChildFeature`). Empty for a clean split.
    """

    parent_id: str
    children: tuple[ChildFeature, ...]
    conservation_ok: bool
    multi_surface_acs: tuple[tuple[str, tuple[str, ...]], ...] = ()


# ─────────────────────────────── public API ────────────────────────────────


def propose_split(
    feature: dict, scope_report: ScopeReport
) -> SplitProposal | None:
    """Propose a partition of an over-scoped ``feature`` into child features.

    Pure: no network, no filesystem, no mutation of ``feature`` or
    ``scope_report`` (acceptance #1).

    Args:
        feature: the feature dict (``id`` / ``acceptance`` / ``depends_on`` …)
            as authored in a plan ``features.json``.
        scope_report: the :class:`ScopeReport` F001 produced for ``feature``.

    Returns:
        A :class:`SplitProposal` when ``scope_report`` carries an
        ``over_surface`` or ``over_ac`` flag; ``None`` for a single-surface,
        in-budget feature (acceptance #5).
    """
    over_surface = bool(scope_report.flags_of_kind("over_surface"))
    over_ac = bool(scope_report.flags_of_kind("over_ac"))
    if not (over_surface or over_ac):
        return None

    parent_id = str(feature.get("id", ""))
    criteria = split_acceptance(_as_text(feature.get("acceptance")))
    if not criteria:
        return None

    parent_depends_on = _as_tuple(feature.get("depends_on"))

    if over_surface:
        buckets = _partition_by_surface(criteria, scope_report.surfaces)
    else:
        buckets = _partition_by_chunk(criteria, scope_report.surfaces)

    children = _build_children(parent_id, buckets, parent_depends_on)

    # Acceptance criteria that are *themselves* multi-surface cannot be routed
    # to a single-surface child without mislabeling it (codex F002 finding).
    # Surface them so the operator can sharpen the AC; the child honestly
    # carries the union (see _build_children).
    multi_surface_acs = tuple(
        (ac, tuple(sorted(surfaces_in(ac))))
        for ac in criteria
        if len(surfaces_in(ac)) > 1
    )

    conservation_ok = _conserves(criteria, children)
    # Acceptance #3 — the partition is exhaustive and disjoint by construction,
    # so this guard never fires; it is an explicit raise (not a bare ``assert``,
    # which ``python -O`` would strip) so the invariant is always enforced.
    if not conservation_ok:
        raise SplitConservationError(
            f"conservation violated for {parent_id}: child ACs do not reproduce "
            "the parent's acceptance criteria exactly"
        )

    return SplitProposal(
        parent_id=parent_id,
        children=children,
        conservation_ok=conservation_ok,
        multi_surface_acs=multi_surface_acs,
    )


# ───────────────────────────── partition helpers ───────────────────────────


def _partition_by_surface(
    criteria: tuple[str, ...], parent_surfaces: tuple[str, ...]
) -> list[tuple[str, list[str]]]:
    """Partition criteria across the parent's F001-tagged surfaces.

    F001 tags ``over_surface`` from the union of a feature's description, steps,
    *and* acceptance text, so a feature can be multi-surface while its
    individual ACs name no surface at all (the surfaces live in steps/desc). A
    naive "route each AC to a surface it names" then collapses every generic AC
    onto one fallback child, defeating the split. To honor acceptance #2 — an
    ``over_surface`` feature yields children covering its surfaces — this:

      1. routes each AC to the first parent surface whose keywords it
         *specifically* matches (:func:`surfaces_in`, no ``core`` default), and
      2. spreads the generic (unmatched) ACs to cover the parent surfaces that
         received nothing yet, in deterministic sorted order, before
         3. dropping any remainder onto the first surface.

    The result covers as many distinct parent surfaces as the AC count allows
    (so a multi-surface feature with >= 2 ACs never collapses to one child),
    while staying exhaustive and disjoint — every AC lands in exactly one child.
    Surfaces that received at least one criterion are returned sorted by name.
    """
    ordered_surfaces = tuple(sorted(parent_surfaces)) or ("core",)
    grouped: dict[str, list[str]] = {}
    generic: list[str] = []
    for ac in criteria:
        ac_surfaces = set(surfaces_in(ac))
        chosen = next((s for s in ordered_surfaces if s in ac_surfaces), None)
        if chosen is None:
            generic.append(ac)
        else:
            grouped.setdefault(chosen, []).append(ac)

    # Cover parent surfaces that no AC explicitly claimed, one generic AC each,
    # so the proposal partitions across surfaces instead of collapsing.
    gi = 0
    for surface in ordered_surfaces:
        if gi >= len(generic):
            break
        if surface not in grouped:
            grouped[surface] = [generic[gi]]
            gi += 1

    # Remaining generics attach to the first surface so conservation holds.
    leftover = generic[gi:]
    if leftover:
        fallback = ordered_surfaces[0]
        grouped.setdefault(fallback, []).extend(leftover)

    return [(surface, grouped[surface]) for surface in sorted(grouped)]


def _partition_by_chunk(
    criteria: tuple[str, ...], parent_surfaces: tuple[str, ...]
) -> list[tuple[str, list[str]]]:
    """Slice criteria into sequential chunks on the parent's lone surface.

    Used for an ``over_ac`` feature that is *not* multi-surface: there is no
    surface axis to split on, so the criteria are chunked to keep each child
    inside one dispatch's comfort band (``_MAX_CHILD_ACS``).
    """
    surface = sorted(parent_surfaces)[0] if parent_surfaces else "core"
    buckets: list[tuple[str, list[str]]] = []
    for start in range(0, len(criteria), _MAX_CHILD_ACS):
        chunk = list(criteria[start : start + _MAX_CHILD_ACS])
        buckets.append((surface, chunk))
    return buckets


def _build_children(
    parent_id: str,
    buckets: list[tuple[str, list[str]]],
    parent_depends_on: tuple[str, ...],
) -> tuple[ChildFeature, ...]:
    """Assign provisional ids and a valid acyclic ``depends_on`` chain.

    Child ``i`` depends on child ``i-1`` (a linear chain — acyclic by
    construction, acceptance #4); the first child inherits the parent's own
    upstream dependencies so the partition slots into the plan's DAG.
    """
    children: list[ChildFeature] = []
    prev_id: str | None = None
    for index, (surface, acs) in enumerate(buckets):
        provisional_id = _provisional_id(parent_id, index)
        if prev_id is None:
            depends_on = parent_depends_on
        else:
            depends_on = (prev_id,)
        # A child normally touches exactly its bucket surface (acceptance #2).
        # If a routed AC is itself multi-surface, the child honestly carries
        # the union of every surface its criteria touch rather than claiming
        # the single bucket surface (codex F002 finding).
        child_surfaces = {surface}
        for ac in acs:
            child_surfaces.update(surfaces_in(ac))
        children.append(
            ChildFeature(
                provisional_id=provisional_id,
                surfaces=tuple(sorted(child_surfaces)),
                acceptance_subset=tuple(acs),
                depends_on=depends_on,
            )
        )
        prev_id = provisional_id
    return tuple(children)


def _provisional_id(parent_id: str, index: int) -> str:
    """``F016`` + index 0/1/2 → ``F016a`` / ``F016b`` / ``F016c``."""
    base = parent_id or "F"
    # Beyond 26 children fall back to a numeric suffix (no real split is this
    # large, but keep ids unique and deterministic regardless).
    suffix = chr(ord("a") + index) if index < 26 else f"_{index}"
    return f"{base}{suffix}"


# ───────────────────────────── invariant check ─────────────────────────────


def _conserves(
    parent_criteria: tuple[str, ...], children: tuple[ChildFeature, ...]
) -> bool:
    """True iff the multiset union of child ACs equals the parent's exactly.

    Uses a :class:`~collections.Counter` so duplicate criteria are compared by
    multiplicity — zero dropped *and* zero duplicated (acceptance #3).
    """
    parent_ms = Counter(parent_criteria)
    child_ms: Counter[str] = Counter()
    for child in children:
        child_ms.update(child.acceptance_subset)
    return parent_ms == child_ms


# ───────────────────────────────── utils ───────────────────────────────────


def _as_text(value: object) -> str:
    """Flatten an acceptance field (str | list[str] | None) to one string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(_as_text(v) for v in value)
    return str(value)


def _as_tuple(value: object) -> tuple[str, ...]:
    """Normalize a ``depends_on`` field (str | list[str] | None) to a tuple."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value if str(v))
    return ()
