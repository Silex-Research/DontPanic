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


def test_no_progress_envelope_flat_count_still_trips() -> None:
    """Flat finding count across rounds (same verdict, not shrinking) → no
    progress → still trips, matching the existing distinct-findings contract
    (plan 2026-05-04-003 F003 AC#6)."""
    tripped, _ = cb.check_no_progress(
        _aud_env(1, issue_offset=0), _aud_env(1, issue_offset=100)
    )
    assert tripped is True


def test_no_progress_envelope_identical_still_trips() -> None:
    """Identical finding set, same verdict → no progress → trips."""
    tripped, _ = cb.check_no_progress(_aud_env(2), _aud_env(2))
    assert tripped is True
