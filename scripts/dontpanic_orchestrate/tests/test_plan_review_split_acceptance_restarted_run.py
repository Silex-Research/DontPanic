"""F2 (Sentinel review 6048538810): a restarted numbered list written after a
cue word ("Criterion (1) f Criterion (2) g ...", "See (1) ...", "Per (1) ...")
fell outside the longest ascending run, read as back-references, and dodged
the blocking ``over_ac`` count.

Rule: an out-of-run marker is a cross-reference only when it is part of a
range (``(2)-(6)``, ``(2) to (6)``), or follows a cue word AND is not part of a
restarted ascending run (>= 2 out-of-run markers whose numbers go up by one).
Markers in a restarted run are criteria, so the count is conservative (never
below base fcee35d's plain split at every ``(n)`` marker). ``criterion`` /
``criteria`` are no longer cue words.
"""

from __future__ import annotations

import re

import pytest

from dontpanic_orchestrate.plan_review.lint import lint_feature, split_acceptance

CUES = ["Criterion", "In", "Of", "See", "Per", "From", "Under"]
CUE_WORDS = CUES + [c.lower() for c in CUES]
BASE = "(1) a (2) b (3) c (4) d (5) e"


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


def _cued(word: str, letters: str) -> str:
    return " ".join(f"{word} ({i}) {c}" for i, c in enumerate(letters, start=1))


def _plain(letters: str) -> str:
    return " ".join(f"({i}) {c}" for i, c in enumerate(letters, start=1))


def _strip_cues(text: str) -> str:
    pattern = r"\b(?:" + "|".join(CUE_WORDS) + r")\s+(?=\(\d+\))"
    return re.sub(pattern, "", text)


def test_sentinel_probe_criterion_counts_ten_and_blocks() -> None:
    text = (
        "(1) a (2) b (3) c (4) d (5) e Criterion (1) f Criterion (2) g "
        "Criterion (3) h Criterion (4) i Criterion (5) j"
    )
    assert _base_count(text) == 10
    assert len(split_acceptance(text)) == 10
    assert _blocks(text)


@pytest.mark.parametrize("word", CUE_WORDS)
def test_cue_restarted_list_counts_base_plain_split(word: str) -> None:
    text = f"{BASE} {_cued(word, 'fghij')}"
    assert _base_count(text) == 10
    assert len(split_acceptance(text)) == 10
    assert _blocks(text)


@pytest.mark.parametrize(
    "text",
    [
        # base list, then a list cued only on its first marker, then another
        f"{BASE} See {_plain('fghij')} Per {_plain('klmno')}",
        # base list, then two lists cued on every marker
        f"{BASE} {_cued('See', 'fghij')} {_cued('Per', 'klmno')}",
        # mixed cue words inside one restarted list
        f"{BASE} See (1) f Per (2) g In (3) h Of (4) i Under (5) j "
        f"{_cued('From', 'klmno')}",
    ],
    ids=["first-marker-cued", "every-marker-cued", "mixed-cues"],
)
def test_two_restarted_lists_count_base_plain_split(text: str) -> None:
    assert _base_count(text) == 15
    assert len(split_acceptance(text)) == 15
    assert _blocks(text)


_PROPERTY_CASES = [
    f"{BASE} {_cued(w, 'fghij')}" for w in CUE_WORDS
] + [
    f"{BASE} See {_plain('fghij')} Per {_plain('klmno')}",
    f"{BASE} {_cued('See', 'fghij')} {_cued('Per', 'klmno')}",
    f"{BASE} {_cued('criteria', 'fg')}",
    f"(1) a (2) b {_cued('see', 'cd')}",
]


@pytest.mark.parametrize("text", _PROPERTY_CASES)
def test_cue_words_never_lower_the_count(text: str) -> None:
    stripped = _strip_cues(text)
    assert stripped != text or "criteria" in text
    assert len(split_acceptance(text)) >= len(split_acceptance(stripped))
    assert len(split_acceptance(text)) >= _base_count(text)


def test_criterion_word_is_not_a_cue_for_a_single_marker() -> None:
    text = f"{BASE} Criterion (1) f"
    assert len(split_acceptance(text)) == 6


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(1) a (2) b, see (1) to (2) (3) c", ("a", "b, see (1) to (2)", "c")),
        ("(1) a (2) b in (1)-(2) (3) c in (1)–(2)", ("a", "b in (1)-(2)", "c in (1)–(2)")),
        # The opening markers of two "to" ranges, (1) then (2), must not read
        # as a restarted run: a "(n) to (m)" range is a cross-reference.
        (
            "(1) a (2) b (3) c in (1) to (2) (4) d in (2) through (3)",
            ("a", "b", "c in (1) to (2)", "d in (2) through (3)"),
        ),
    ],
)
def test_ranges_stay_cross_references(text: str, expected: tuple[str, ...]) -> None:
    assert split_acceptance(text) == expected
