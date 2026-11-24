"""split_acceptance: the first "(n)" anchors the sequence; after it, "(n)"
opens a criterion only when n is the previous number + 1.

Real case (Spin plan F002): seven criteria whose (7) says "in (2)-(6)." were
counted as 10, tripping the over_ac block at >= 10.
"""

from __future__ import annotations

import pytest

from dontpanic_orchestrate.plan_review.lint import lint_feature, split_acceptance

SEVEN_WITH_RANGE_XREF = (
    "(1) the jobs table exists "
    "(2) enqueue writes a row "
    "(3) the worker claims one row "
    "(4) a claimed row is not re-claimed "
    "(5) a failed job is retried once "
    "(6) a retried job records its attempt count "
    "(7) the dispatch order is unchanged by the steps in (2)-(6). Jobs lock unchanged."
)


def _feature(acceptance: str) -> dict:
    return {
        "id": "F002",
        "description": "Add a cli subcommand that enqueues jobs",
        "steps": ["write it"],
        "acceptance": acceptance,
    }


def test_range_cross_reference_stays_inside_its_criterion():
    criteria = split_acceptance(SEVEN_WITH_RANGE_XREF)
    assert len(criteria) == 7
    assert "(2)-(6)" in criteria[6]
    assert criteria[6].endswith("Jobs lock unchanged.")


def test_lint_counts_seven_not_ten_so_no_over_ac_block():
    report = lint_feature(_feature(SEVEN_WITH_RANGE_XREF))
    assert report.ac_count == 7
    over_ac = [f for f in report.flags if f.kind == "over_ac"]
    # 7 > the warn band (6) is a legitimate warn; the bug was the false block.
    assert all(f.severity != "block" for f in over_ac), over_ac


def test_ten_real_sequential_criteria_still_block():
    acceptance = " ".join(f"({i}) criterion number {i} holds" for i in range(1, 11))
    report = lint_feature(_feature(acceptance))
    assert report.ac_count == 10
    assert any(f.kind == "over_ac" and f.severity == "block" for f in report.flags)


def test_back_reference_does_not_split():
    criteria = split_acceptance("(1) a (2) b (3) c (4) d (5) e, see (4) for the shape (6) f")
    assert criteria == ("a", "b", "c", "d", "e, see (4) for the shape", "f")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(1) a (2) b (3) c", ("a", "b", "c")),
        ("just one criterion", ("just one criterion",)),
        ("   ", ()),
        ("", ()),
        ("Preamble here. (1) a (2) b", ("Preamble here.", "a", "b")),
        ("(1)a(2)b(12)c", ("a", "b(12)c")),
        # The first marker anchors the sequence whatever its number (split
        # children keep their parent's numbering).
        ("(3) C", ("C",)),
        ("(4) D (5) E", ("D", "E")),
        ("(3) C see (1)", ("C see (1)",)),
    ],
)
def test_existing_numbered_and_fallback_behavior(text, expected):
    assert split_acceptance(text) == expected
