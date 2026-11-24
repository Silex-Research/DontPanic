"""MED-E (Sentinel review 6035083658): "step(s)" / "item(s)" are criterion
LABELS, not cross-reference words. With them counted as cross-references, a
second numbered list written as "Step (1) a Step (2) b ..." or "Item (1) f ..."
fell outside the longest ascending run, read as back-references, and dodged the
blocking ``over_ac`` count. The count must match base fcee35d (a plain split at
every ``(n)`` marker): 11 and 10.

``test_guard_*`` keep the earlier r2 guards pinned in one place.
"""

from __future__ import annotations

import re

import pytest

from dontpanic_orchestrate.plan_review.lint import lint_feature, split_acceptance


def _base_count(text: str) -> int:
    """Base fcee35d's documented algorithm: split at every ``(n)`` marker."""
    return len([p for p in re.split(r"\(\d+\)\s*", text.strip()) if p.strip()])


def _blocks(acceptance: str) -> bool:
    feature = {
        "id": "F002",
        "description": "Add a cli subcommand that enqueues jobs",
        "steps": ["write it"],
        "acceptance": acceptance,
    }
    return any(
        f.kind == "over_ac" and f.severity == "block" for f in lint_feature(feature).flags
    )


def _step_list(word: str) -> str:
    return " ".join(f"{word} ({i}) {c}" for i, c in enumerate("abcde", start=1))


def _item_tail(word: str) -> str:
    return " ".join(f"{word} ({i}) {c}" for i, c in enumerate("fghij", start=1))


@pytest.mark.parametrize("word", ["Step", "step", "STEPS", "steps"])
def test_two_step_labelled_lists_count_eleven_like_base(word: str) -> None:
    text = "Preamble " + _step_list(word) + " " + _step_list(word)
    assert _base_count(text) == 11
    assert len(split_acceptance(text)) == 11
    assert _blocks(text)


@pytest.mark.parametrize("word", ["Item", "item", "ITEMS", "items"])
def test_plain_list_then_item_labelled_list_counts_ten_like_base(word: str) -> None:
    text = "(1) a (2) b (3) c (4) d (5) e " + _item_tail(word)
    assert _base_count(text) == 10
    assert len(split_acceptance(text)) == 10
    assert _blocks(text)


def test_guard_in_range_reference_counts_seven() -> None:
    text = " ".join(f"({i}) criterion {i}" for i in range(1, 7)) + (
        " (7) dispatch order unchanged by steps in (2)–(6)."
    )
    assert len(split_acceptance(text)) == 7
    assert len(split_acceptance("Preamble " + text)) == 8


def test_guard_leading_see_reference_counts_eleven() -> None:
    text = "See (9) for the shared format. " + " ".join(
        f"({i}) criterion {i}." for i in range(1, 11)
    )
    assert len(split_acceptance(text)) == 11


def test_guard_skipped_number_typo_counts_eight() -> None:
    assert len(split_acceptance("(1) a (3) b (4) c (5) d (6) e (7) f (8) g (9) h")) == 8


def test_guard_split_child_starting_at_three_still_splits() -> None:
    assert split_acceptance("(3) C (4) D (5) E") == ("C", "D", "E")
