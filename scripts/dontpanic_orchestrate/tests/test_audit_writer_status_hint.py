"""Verdict-anchored status extraction (QuantRE F003 incident, 2026-07-30).

An auditor summary that ACCURATELY DESCRIBES a feature whose domain vocabulary
contains status words (e.g. a dispositions enum defining 'needs_changes') must
not be classified by bag-of-words scanning: four consecutive audits whose prose
said "Verdict: signed_off." were recorded audit_status=needs_changes, tripping
the iteration cap and then the global breaker.
"""
from dontpanic_orchestrate.audit_writer import _extract_status_hint


def test_explicit_verdict_wins_over_domain_vocabulary() -> None:
    summary = (
        "**Verdict: signed_off.** The module defines dispositions "
        "'recommend_to_ic', 'do_not_recommend', and 'needs_changes' as a "
        "closed vocabulary; applyUnderwritingDispositionPolicy maps blocked "
        "requests to needs_changes as designed."
    )
    assert _extract_status_hint(summary) == "signed_off"


def test_explicit_needs_changes_verdict_still_detected() -> None:
    summary = "Overall verdict: **needs_changes**. One medium correctness gap remains."
    assert _extract_status_hint(summary) == "needs_changes"


def test_last_verdict_declaration_is_authoritative() -> None:
    summary = (
        "i0's verdict: needs_changes flagged the wildcard bug. "
        "That is now fixed. Verdict: signed_off."
    )
    assert _extract_status_hint(summary) == "signed_off"


def test_bag_of_words_fallback_without_explicit_verdict() -> None:
    assert _extract_status_hint("everything looks good, signed off") == "signed_off"
    assert _extract_status_hint("no status language at all") is None
