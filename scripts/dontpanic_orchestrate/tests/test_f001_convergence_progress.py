"""Plan 2026-05-30-002 F001 — convergence breakers treat shrinking/changing
blocking-finding sets as PROGRESS (D029 fix, Design B "strictly-shrinking
carve-out").

The bug (surfaced + re-diagnosed dogfooding 2026-05-30-001): a volley whose
auditor findings genuinely shrink round-over-round (e.g. 3 → 1 → signoff) was
terminated at round 2 — ``check_diminishing_returns`` trips because its
signature-INTERSECTION is non-empty whenever *any* finding persists, and
``check_no_progress`` (pre-fix) trips on bare verdict-string equality. Both
killed real progress.

Design B (operator-approved): keep each breaker's existing trip semantics, but
add a shared carve-out — when the blocking-finding COUNT strictly decreases
across the convergence window, the rounds are making progress and NEITHER
breaker trips, even if some findings persist. This fixes convergence while
preserving every existing breaker test (distinct-but-flat findings still trip
no_progress; identical findings still trip diminishing_returns).

──────────────────────────────────────────────────────────────────────────────
Plan 2026-06-02-002 F001 (D003 — operator-confirmed 2026-06-02) SUPERSEDES the
count-based carve-out above AND 2026-05-04-003 F003 AC#6's "distinct-but-flat
findings trip no_progress" contract. New rule:

    no_progress trips ONLY when no prior blocking-finding signature is resolved.

Resolving one finding and exposing a new one (flat or even growing count,
complete turnover) is PROGRESS and does NOT trip. New-finding churn — every
prior signature persisting — still trips. The dogfood (plan-review F001-F007)
showed the old distinct-but-flat rule was wrong for audit-driven convergence.

SUBSUMPTION CONSEQUENCE (flagged for the batched codex audit): for sound-
signature envelopes the no_progress trip condition (nothing resolved → every
prior signature persists) is now a strict SUBSET of diminishing_returns'
condition (non-empty signature intersection, non-decreasing), and the supervisor
checks diminishing_returns FIRST. So `stopped_no_progress` is unreachable for
signed findings — it is subsumed by `stopped_diminishing_returns`. no_progress
remains independently reachable ONLY via the LEGACY VERDICT-STRING fallback,
which D003 preserves unchanged: when any finding lacks usable issue text,
``compute_audit_finding_signature`` returns None, the signature carve-out is
skipped, and no_progress falls back to verdict-string equality. The
``test_no_progress_fallback_*`` tests below pin that preserved path.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f001_convergence_progress.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import circuit_breakers as cb  # noqa: E402


def _iso() -> str:
    return dt.datetime(2026, 5, 31, tzinfo=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_auditor(ad: Path, iteration: int, *, status: str, n_findings: int,
                   issue_offset: int = 0) -> Path:
    """Auditor envelope with ``n_findings`` distinct-signature findings starting
    at ``issue_offset``. A shrinking set with the same offset is a strict subset
    (e.g. offset 0, n=1 ⊂ offset 0, n=3)."""
    p = ad / f"codex-auditor-i{iteration}.json"
    p.write_text(json.dumps({
        "task_id": "t", "audit_id": f"t#codex#{iteration}", "agent": "codex",
        "agent_role": "auditor", "iteration": iteration,
        "started_at": _iso(), "completed_at": _iso(), "audit_status": status,
        "findings": [
            {"severity": "high", "category": "correctness",
             "issue": f"finding {i + issue_offset}-aaaaaaa"}
            for i in range(n_findings)
        ],
    }))
    return p


# ──────────────────────────────  diminishing_returns carve-out  ──────────────────────────────


def test_dr_does_not_trip_when_findings_shrink_strict_subset() -> None:
    """THE convergence case: findings 3 → 1 (a strict subset, finding #0 persists).
    Pre-fix DR trips because the intersection {0} is non-empty. Post-fix: strictly
    shrinking count = progress → no trip."""
    with tempfile.TemporaryDirectory() as td:
        ad = Path(td)
        _write_auditor(ad, 0, status="needs_changes", n_findings=3)
        _write_auditor(ad, 1, status="needs_changes", n_findings=1)
        tripped, reason = cb.check_diminishing_returns(sorted(ad.glob("*.json")))
        assert not tripped, f"shrinking finding set must NOT trip diminishing_returns; reason={reason!r}"


def test_dr_does_not_trip_when_findings_shrink_disjoint() -> None:
    """Findings shrink 3 → 1 with a fully different finding — also progress."""
    with tempfile.TemporaryDirectory() as td:
        ad = Path(td)
        _write_auditor(ad, 0, status="needs_changes", n_findings=3, issue_offset=0)
        _write_auditor(ad, 1, status="needs_changes", n_findings=1, issue_offset=100)
        tripped, _ = cb.check_diminishing_returns(sorted(ad.glob("*.json")))
        assert not tripped


def test_dr_still_trips_when_findings_identical() -> None:
    """Preserved contract: the SAME finding set both rounds (no shrink) still
    trips diminishing_returns."""
    with tempfile.TemporaryDirectory() as td:
        ad = Path(td)
        _write_auditor(ad, 0, status="needs_changes", n_findings=2)
        _write_auditor(ad, 1, status="needs_changes", n_findings=2)
        tripped, reason = cb.check_diminishing_returns(sorted(ad.glob("*.json")))
        assert tripped, "identical finding set must still trip diminishing_returns"
        assert "signature-based" in reason


def test_dr_still_trips_when_count_flat_with_persisted_finding() -> None:
    """Flat count (2 → 2) where a finding persists is NOT progress → still trips."""
    with tempfile.TemporaryDirectory() as td:
        ad = Path(td)
        # round 0: {0,1}; round 1: {0,2} — count flat, finding 0 persists.
        ad0 = ad / "codex-auditor-i0.json"
        ad0.write_text(json.dumps({
            "agent": "codex", "agent_role": "auditor", "iteration": 0,
            "audit_status": "needs_changes",
            "findings": [
                {"severity": "high", "category": "correctness", "issue": "finding 0-aaaa"},
                {"severity": "high", "category": "correctness", "issue": "finding 1-aaaa"},
            ],
        }))
        ad1 = ad / "codex-auditor-i1.json"
        ad1.write_text(json.dumps({
            "agent": "codex", "agent_role": "auditor", "iteration": 1,
            "audit_status": "needs_changes",
            "findings": [
                {"severity": "high", "category": "correctness", "issue": "finding 0-aaaa"},
                {"severity": "high", "category": "correctness", "issue": "finding 2-aaaa"},
            ],
        }))
        tripped, _ = cb.check_diminishing_returns(sorted(ad.glob("*.json")))
        assert tripped, "flat count with a persisted finding is not progress → must trip"


# ──────────────────────────────  no_progress preserved + carve-out  ──────────────────────────────


def test_no_progress_still_trips_on_identical_verdict_strings() -> None:
    """Backward-compat: the legacy bare-verdict-string call path still trips on
    two identical needs_changes verdicts (existing supervisor fallback)."""
    tripped, _ = cb.check_no_progress("needs_changes", "needs_changes")
    assert tripped


def test_no_progress_first_round_does_not_trip() -> None:
    tripped, _ = cb.check_no_progress(None, "needs_changes")
    assert tripped is False


def test_no_progress_signed_off_does_not_trip() -> None:
    tripped, _ = cb.check_no_progress("signed_off", "signed_off")
    assert tripped is False


def _aud_env(n_findings: int, *, status: str = "needs_changes", issue_offset: int = 0) -> dict:
    return {
        "agent": "codex", "agent_role": "auditor", "audit_status": status,
        "findings": [
            {"severity": "high", "category": "correctness",
             "issue": f"finding {i + issue_offset}-aaaaaaa"}
            for i in range(n_findings)
        ],
    }


def test_no_progress_envelope_shrinking_does_not_trip() -> None:
    """Plan 2026-05-30-002 F001 — when check_no_progress is given prior+current
    auditor ENVELOPES and the blocking-finding count strictly shrinks (3 → 1),
    it must NOT trip even though both verdicts are needs_changes. This is the
    precedence-mask fix: no_progress no longer kills a progress-making round."""
    tripped, _ = cb.check_no_progress(_aud_env(3), _aud_env(1))
    assert tripped is False


def test_no_progress_complete_turnover_is_progress() -> None:
    """Plan 2026-06-02-002 F001 (D003 — SUPERSEDES 2026-05-04-003 F003 AC#6).

    Complete turnover at a flat count (prior {finding 0} -> current {finding 100})
    means the prior blocking finding was RESOLVED and a new one exposed. The old
    rule (AC#6) treated 'same count, different finding' as no-progress and
    tripped — the dogfood (plan-review F001-F007) showed that is WRONG for
    audit-driven convergence. New rule: no_progress trips ONLY when no prior
    blocking-finding signature is resolved; here finding 0 is resolved, so this
    is PROGRESS and must NOT trip.
    """
    tripped, _ = cb.check_no_progress(
        _aud_env(1, issue_offset=0), _aud_env(1, issue_offset=100)
    )
    assert tripped is False


def test_no_progress_one_resolved_one_new_is_progress() -> None:
    """{0,1} -> {1,2}: finding 0 resolved (absent), finding 2 new. A prior
    signature was resolved -> progress -> must NOT trip (D003)."""
    tripped, _ = cb.check_no_progress(
        _aud_env(2, issue_offset=0), _aud_env(2, issue_offset=1)
    )
    assert tripped is False


def test_no_progress_persist_plus_new_finding_trips() -> None:
    """{0} -> {0,1}: finding 0 PERSISTS, finding 1 is new. NOTHING was resolved
    -> new findings alone are not progress -> still trips (D003 acceptance #2)."""
    tripped, _ = cb.check_no_progress(
        _aud_env(1, issue_offset=0), _aud_env(2, issue_offset=0)
    )
    assert tripped is True


def test_no_progress_reworded_identical_finding_trips() -> None:
    """A finding reworded only in case/whitespace yields the SAME normalized
    signature (compute_finding_signature normalizes), so nothing is resolved
    -> trips (D003 acceptance #3: a reworded-but-identical finding is not
    progress)."""
    prior = {
        "agent": "codex", "agent_role": "auditor", "audit_status": "needs_changes",
        "findings": [{"severity": "high", "category": "correctness",
                      "issue": "finding 0-aaaaaaa"}],
    }
    current = {
        "agent": "codex", "agent_role": "auditor", "audit_status": "needs_changes",
        "findings": [{"severity": "high", "category": "correctness",
                      "issue": "  FINDING   0-AAAAAAA  "}],
    }
    tripped, _ = cb.check_no_progress(prior, current)
    assert tripped is True


def test_no_progress_envelope_identical_still_trips() -> None:
    """Identical finding set, same verdict → no progress → trips."""
    tripped, _ = cb.check_no_progress(_aud_env(2), _aud_env(2))
    assert tripped is True


# ──────────────────────────────  D003 subsumption: legacy fallback path  ──────────────────────────────


def _unsigned_env(n_findings: int, *, status: str = "needs_changes") -> dict:
    """Auditor envelope whose findings carry NO usable issue text, so
    compute_audit_finding_signature returns None and the D003 signature
    carve-out is skipped — check_no_progress falls back to verdict-string
    equality (the path D003 preserves)."""
    return {
        "agent": "codex", "agent_role": "auditor", "audit_status": status,
        "findings": [
            {"severity": "high", "category": "correctness", "issue": ""}
            for _ in range(n_findings)
        ],
    }


def test_no_progress_fallback_unsigned_findings_trips_on_verdict() -> None:
    """D003 subsumption note: for sound-signature envelopes no_progress is
    subsumed by diminishing_returns (nothing-resolved ⊂ non-empty-intersection,
    and the supervisor checks DR first). no_progress stays independently
    reachable ONLY via the legacy verdict-string fallback — when findings lack
    usable issue text. Two identical needs_changes verdicts whose findings have
    empty issue text MUST still trip no_progress via that preserved path."""
    tripped, reason = cb.check_no_progress(_unsigned_env(1), _unsigned_env(1))
    assert tripped is True
    assert "needs_changes" in reason


def test_no_progress_fallback_decreasing_unsigned_counts_still_trips() -> None:
    """The fallback path is verdict-only: it ignores finding COUNT entirely.
    Even with a strictly-decreasing unsigned count (2 → 1) — which keeps the
    diminishing-returns count-fallback quiet — no_progress still trips on the
    identical needs_changes verdict. This is the exact shape
    TestPriorAudStatusCarryOver.test_timeout_with_work_round_does_not_advance_baseline
    relies on to isolate no_progress under D003."""
    tripped, _ = cb.check_no_progress(_unsigned_env(2), _unsigned_env(1))
    assert tripped is True


def test_no_progress_fallback_signed_off_does_not_trip() -> None:
    """The preserved fallback keeps the signed_off / blocked exclusion: an
    unsigned signed_off pair must not trip."""
    tripped, _ = cb.check_no_progress(
        _unsigned_env(1, status="signed_off"), _unsigned_env(1, status="signed_off")
    )
    assert tripped is False
