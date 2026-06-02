"""F002 — suggested-split proposer.

Exercises :func:`propose_split` against the F001 lint core: a multi-surface
feature partitions into one-surface children, the conservation invariant holds
(no AC dropped or duplicated), child ``depends_on`` forms a valid acyclic
chain, and a single-surface in-budget feature yields no proposal.

Run:
    PYTHONPATH=scripts pytest \
        scripts/dontpanic_orchestrate/tests/test_plan_review_split_f002.py -q
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.plan_review.lint import (  # noqa: E402
    Resolvers,
    lint_feature,
)
from dontpanic_orchestrate.plan_review.split import (  # noqa: E402
    ChildFeature,
    SplitProposal,
    propose_split,
)

# A resolver set wide enough that no AC trips a missing_prereq flag; F002 keys
# only off over_surface / over_ac, but lint runs the full signal set.
RESOLVERS = Resolvers(
    commands=frozenset({"dontpanic"}),
    flags=frozenset({"--format"}),
    symbols=frozenset(),
)

# A genuinely multi-surface feature: each AC names exactly one surface (cli,
# dashboard, core), so F001 flags over_surface and the partition is clean.
MULTI_SURFACE_FEATURE = {
    "id": "F016",
    "description": "a sprawling feature spanning several surfaces",
    "steps": ["wire the cli", "render the dashboard", "score in the core"],
    "acceptance": (
        "(1) the cli subcommand writes results to stdout "
        "(2) the dashboard renders html for the operator "
        "(3) the pure function stays deterministic"
    ),
    "depends_on": ["F001"],
}

# An over_surface feature whose surfaces come from F001's description/steps
# tags, NOT from the acceptance text — every AC is generic (names no surface).
# Regression for the i0 finding: the proposer must still partition across the
# tagged surfaces instead of collapsing every generic AC onto one child.
STEPS_SURFACE_FEATURE = {
    "id": "F020",
    "description": "wire the cli and render the dashboard for the operator",
    "steps": ["add a cli subcommand", "render the dashboard html"],
    "acceptance": (
        "(1) the behavior is deterministic "
        "(2) the result is well typed "
        "(3) the output stays stable across runs"
    ),
    "depends_on": ["F001"],
}

# A single-surface, over-budget feature: 10 plain core ACs trip over_ac with no
# surface axis to split on, so F002 chunks them sequentially.
OVER_AC_FEATURE = {
    "id": "F011",
    "description": "a pure deterministic core module with too many criteria",
    "acceptance": "".join(f"({i}) criterion number {i} holds " for i in range(1, 11)),
    "depends_on": ["F001"],
}

# A clean single-surface, in-budget feature: no over_surface / over_ac flag.
CLEAN_FEATURE = {
    "id": "F015",
    "description": "a pure deterministic core module",
    "acceptance": "(1) it scores correctly (2) it stays pure (3) it is typed",
}


def _report(feature: dict):
    return lint_feature(feature, RESOLVERS)


# ─────────────────────────── purity (acceptance #1) ─────────────────────────


def test_propose_split_returns_typed_proposal_or_none():
    proposal = propose_split(MULTI_SURFACE_FEATURE, _report(MULTI_SURFACE_FEATURE))
    assert isinstance(proposal, SplitProposal)
    assert proposal.parent_id == "F016"
    assert all(isinstance(c, ChildFeature) for c in proposal.children)


def test_propose_split_does_not_mutate_inputs():
    feature = dict(MULTI_SURFACE_FEATURE)
    feature["depends_on"] = list(MULTI_SURFACE_FEATURE["depends_on"])
    before = {k: (list(v) if isinstance(v, list) else v) for k, v in feature.items()}
    report = _report(feature)
    flags_before = report.flags

    propose_split(feature, report)

    assert feature == before
    assert report.flags == flags_before  # report untouched


# ────────────────── multi-surface split (acceptance #2, #6) ─────────────────


def test_multi_surface_feature_yields_at_least_two_children():
    proposal = propose_split(MULTI_SURFACE_FEATURE, _report(MULTI_SURFACE_FEATURE))
    assert proposal is not None
    assert len(proposal.children) >= 2


def test_each_child_touches_exactly_one_surface():
    proposal = propose_split(MULTI_SURFACE_FEATURE, _report(MULTI_SURFACE_FEATURE))
    assert proposal is not None
    for child in proposal.children:
        assert len(child.surfaces) == 1
    # And the children together cover the distinct surfaces, one apiece.
    surfaces = [c.surfaces[0] for c in proposal.children]
    assert sorted(surfaces) == ["cli", "core", "dashboard"]


def test_over_surface_from_steps_partitions_across_surfaces():
    # Regression (i0 high finding): the feature is over_surface only because its
    # description/steps tag cli + dashboard; its ACs are generic. The proposal
    # must still cover the tagged surfaces, not collapse onto one fallback child.
    report = _report(STEPS_SURFACE_FEATURE)
    assert report.flags_of_kind("over_surface")  # F001 flagged it
    assert "cli" in report.surfaces and "dashboard" in report.surfaces

    proposal = propose_split(STEPS_SURFACE_FEATURE, report)
    assert proposal is not None
    # Not collapsed: more than one child, spanning more than one surface.
    assert len(proposal.children) >= 2
    child_surfaces = sorted(c.surfaces[0] for c in proposal.children)
    assert child_surfaces == ["cli", "core", "dashboard"]
    for child in proposal.children:
        assert len(child.surfaces) == 1  # acceptance #2

    # Conservation still holds with generic ACs spread across surfaces.
    from dontpanic_orchestrate.plan_review.lint import split_acceptance

    parent = Counter(split_acceptance(STEPS_SURFACE_FEATURE["acceptance"]))
    union: Counter[str] = Counter()
    for child in proposal.children:
        union.update(child.acceptance_subset)
    assert union == parent


def test_over_surface_with_fewer_acs_than_surfaces_still_splits():
    # Two generic ACs, three tagged surfaces (the auditor's exact probe shape):
    # cannot cover all three, but must not collapse to a single child either.
    feature = {
        "id": "FX",
        "description": "wire the cli and dashboard surfaces",
        "steps": ["add a cli command", "render the dashboard"],
        "acceptance": "(1) the behavior is deterministic (2) the result is typed",
        "depends_on": [],
    }
    report = _report(feature)
    assert report.flags_of_kind("over_surface")
    proposal = propose_split(feature, report)
    assert proposal is not None
    assert len(proposal.children) >= 2  # was 1 before the fix
    assert len({c.surfaces[0] for c in proposal.children}) >= 2


# ───────────────────── conservation invariant (acceptance #3) ───────────────


def test_conservation_multiset_union_equals_parent():
    report = _report(MULTI_SURFACE_FEATURE)
    proposal = propose_split(MULTI_SURFACE_FEATURE, report)
    assert proposal is not None
    assert proposal.conservation_ok is True

    from dontpanic_orchestrate.plan_review.lint import split_acceptance

    parent = Counter(split_acceptance(MULTI_SURFACE_FEATURE["acceptance"]))
    union: Counter[str] = Counter()
    for child in proposal.children:
        union.update(child.acceptance_subset)
    assert union == parent  # zero dropped, zero duplicated


def test_conservation_holds_for_chunked_over_ac_split():
    report = _report(OVER_AC_FEATURE)
    proposal = propose_split(OVER_AC_FEATURE, report)
    assert proposal is not None
    assert proposal.conservation_ok is True
    assert len(proposal.children) >= 2  # 10 ACs chunked into >= 2 children

    from dontpanic_orchestrate.plan_review.lint import split_acceptance

    parent = Counter(split_acceptance(OVER_AC_FEATURE["acceptance"]))
    union: Counter[str] = Counter()
    for child in proposal.children:
        union.update(child.acceptance_subset)
    assert union == parent


def test_conservation_handles_duplicate_criteria_by_multiplicity():
    # Two identical ACs must both survive — multiset, not set, semantics.
    feature = {
        "id": "FDUP",
        "description": "a feature spanning cli and dashboard surfaces",
        "acceptance": (
            "(1) the cli writes to stdout "
            "(2) the dashboard renders html "
            "(3) the cli writes to stdout"
        ),
        "depends_on": [],
    }
    report = _report(feature)
    proposal = propose_split(feature, report)
    assert proposal is not None
    union: Counter[str] = Counter()
    for child in proposal.children:
        union.update(child.acceptance_subset)
    assert union["the cli writes to stdout"] == 2


# ───────────────────── dependency validity (acceptance #4) ──────────────────


def _is_valid_acyclic_chain(proposal: SplitProposal) -> bool:
    """Every child's depends_on references only earlier ids — no cycle."""
    seen: set[str] = set()
    known = {c.provisional_id for c in proposal.children}
    for child in proposal.children:
        for dep in child.depends_on:
            # A dep is either an earlier sibling or an external (parent) dep.
            if dep in known and dep not in seen:
                return False  # forward / self reference → would risk a cycle
        seen.add(child.provisional_id)
    return True


def test_child_depends_on_forms_valid_acyclic_chain():
    proposal = propose_split(MULTI_SURFACE_FEATURE, _report(MULTI_SURFACE_FEATURE))
    assert proposal is not None
    assert _is_valid_acyclic_chain(proposal)

    # First child inherits the parent's upstream deps; each later child chains
    # onto its immediate predecessor.
    assert proposal.children[0].depends_on == ("F001",)
    for prev, nxt in zip(proposal.children, proposal.children[1:], strict=False):
        assert nxt.depends_on == (prev.provisional_id,)

    # Provisional ids are unique and derived from the parent id.
    ids = [c.provisional_id for c in proposal.children]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("F016") for i in ids)


# ──────────────────────────── no-op (acceptance #5) ─────────────────────────


def test_single_surface_in_budget_feature_yields_none():
    proposal = propose_split(CLEAN_FEATURE, _report(CLEAN_FEATURE))
    assert proposal is None


def test_empty_acceptance_yields_none():
    feature = {"id": "FE", "description": "engine and cli and dashboard"}
    # Multi-surface description flags over_surface, but no ACs to partition.
    proposal = propose_split(feature, _report(feature))
    assert proposal is None


# ─────────── multi-surface AC honesty (codex F002 finding, operator-fix) ─────


def test_multi_surface_ac_is_not_mislabeled_single_surface():
    # An AC that itself touches cli AND dashboard cannot be routed to a clean
    # single-surface child. Acceptance #2 must not be violated by silently
    # labeling that child with one surface: the child honestly carries the
    # union, and the offending AC is reported on multi_surface_acs.
    feature = {
        "id": "FZ",
        "description": "engine plus cli plus dashboard",
        "steps": [],
        "acceptance": (
            "(1) the cli command and dashboard render agree on output; "
            "(2) the core scoring is deterministic"
        ),
    }
    proposal = propose_split(feature, _report(feature))
    assert proposal is not None
    # The child holding the multi-surface AC reflects BOTH surfaces, not one.
    holder = next(
        c
        for c in proposal.children
        if any("cli command and dashboard" in ac for ac in c.acceptance_subset)
    )
    assert set(holder.surfaces) == {"cli", "dashboard"}
    # And the proposal surfaces the offending AC for the operator to sharpen.
    assert proposal.multi_surface_acs
    flagged_text, flagged_surfaces = proposal.multi_surface_acs[0]
    assert "cli command and dashboard" in flagged_text
    assert set(flagged_surfaces) == {"cli", "dashboard"}


def test_clean_single_surface_acs_keep_single_surface_children():
    # When every AC is genuinely single-surface, acceptance #2 holds exactly:
    # each child touches one surface and nothing is flagged as multi-surface.
    proposal = propose_split(MULTI_SURFACE_FEATURE, _report(MULTI_SURFACE_FEATURE))
    assert proposal is not None
    assert all(len(c.surfaces) == 1 for c in proposal.children)
    assert proposal.multi_surface_acs == ()
