"""split_acceptance never under-counts on adversarial text (Sentinel r2 MED 5).

The count feeds the blocking ``over_ac`` check (>= 10). The r1 rule anchored
the sequence at the FIRST marker, so a leading "See (9)" or a skipped number
let ten real criteria count as 3 or 1. The longest ascending run is now the
boundary set, and any out-of-run marker that does not read as a
cross-reference makes the count conservative (never below the plain split).

Guards (pass on base fcee35d by design, red against f2ba0d70's first-marker
anchor) are named ``test_guard_*``.
"""

from __future__ import annotations

import pytest

from dontpanic_orchestrate.plan_review.lint import lint_feature, split_acceptance

TEN = " ".join(f"({i}) criterion {i}." for i in range(1, 11))


def _feature(acceptance: str) -> dict:
    return {
        "id": "F002",
        "description": "Add a cli subcommand that enqueues jobs",
        "steps": ["write it"],
        "acceptance": acceptance,
    }


def _blocks(acceptance: str) -> bool:
    report = lint_feature(_feature(acceptance))
    return any(f.kind == "over_ac" and f.severity == "block" for f in report.flags)


def test_guard_leading_see_reference_still_blocks_ten_criteria():
    text = "See (9) for the shared format. " + TEN
    assert len(split_acceptance(text)) >= 11
    assert _blocks(text)


def test_guard_leading_unprefixed_marker_counts_like_base():
    text = "Rule (9) applies throughout. " + TEN
    assert len(split_acceptance(text)) >= 12
    assert _blocks(text)


def test_guard_skipped_number_typo_never_counts_below_base():
    text = "(1) a (3) b (4) c (5) d (6) e (7) f (8) g (9) h"
    assert len(split_acceptance(text)) >= 8


def test_guard_restarted_numbering_counts_both_lists():
    text = " ".join(f"({i}) first {i}." for i in range(1, 6)) + " " + " ".join(
        f"({i}) second {i}." for i in range(1, 6)
    )
    assert len(split_acceptance(text)) >= 10
    assert _blocks(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(1) a (2) b per (1) (3) c", ("a", "b per (1)", "c")),
        ("(1) a (2) b (3) c as in (1) (4) d", ("a", "b", "c as in (1)", "d")),
        ("(1) a (2) b (3) c, see steps (1)–(2) (4) d", ("a", "b", "c, see steps (1)–(2)", "d")),
        ("(3) C (4) D, cf. (3) (5) E", ("C", "D, cf. (3)", "E")),
    ],
)
def test_cross_references_outside_the_run_do_not_add_criteria(text, expected):
    assert split_acceptance(text) == expected


def test_seven_with_en_dash_range_is_seven_not_nine():
    text = " ".join(f"({i}) criterion {i}" for i in range(1, 7)) + (
        " (7) dispatch order unchanged by steps in (2)–(6)."
    )
    assert len(split_acceptance(text)) == 7
    assert not _blocks(text)
