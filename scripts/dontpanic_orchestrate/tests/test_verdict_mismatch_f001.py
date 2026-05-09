"""Plan 2026-05-09-002 F001 — auditor verdict-mismatch detection tests.

Five fixture cases pinning the parser + detector + supervisor wiring:

  (A) Mismatch — SpinDine F001-i1 case: summary says
      ``**Verdict: signed_off**`` but ``audit_status`` field is
      ``needs_changes``. detect_verdict_mismatch returns a populated
      VerdictMismatchError; supervisor raises + writes INBOX
      ``verdict_mismatch`` event.
  (B) Agreement — narrative + structured both signed_off: returns None.
  (C) Narrative-only — canonical verdict line present, structured field
      absent (defaults to "inconclusive" downstream): returns None
      (no disagreement when structured is missing/malformed).
  (D) Structured-only — no canonical narrative line: returns None
      (existing structured-field-canonical behavior preserved).
  (E) Phrasing variants — three regex shapes (``Verdict:``,
      ``**Verdict:**``, ``Overall verdict:.``) all parse correctly;
      mid-sentence "Verdict:" prose does NOT match.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    auditor_taxonomy,
    inbox,
    notify,
    supervisor,
)
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)


# ───────────────────────── 1. Parser unit tests ─────────────────────────


class TestParseNarrativeVerdict:
    @pytest.mark.parametrize(
        "summary,expected",
        [
            ("**Verdict: signed_off**", "signed_off"),
            ("**Verdict: needs_changes**", "needs_changes"),
            ("Overall verdict: signed_off.", "signed_off"),
            ("Overall verdict: blocked.", "blocked"),
            ("Verdict: inconclusive", "inconclusive"),
            ("Verdict: redaction_required", "redaction_required"),
            (
                "Repo: x\nEnv: dev\n\n**Verdict: signed_off**\n\nMore prose.",
                "signed_off",
            ),
        ],
        ids=[
            "bold-signed-off",
            "bold-needs-changes",
            "overall-signed-off-period",
            "overall-blocked-period",
            "plain-inconclusive",
            "plain-redaction-required",
            "embedded-bold-line",
        ],
    )
    def test_canonical_patterns_match(self, summary: str, expected: str) -> None:
        assert auditor_taxonomy.parse_narrative_verdict(summary) == expected

    @pytest.mark.parametrize(
        "summary",
        [
            "",
            None,
            "No verdict line at all here.",
            "The auditor said Verdict: signed_off in passing.",  # mid-line
            "Verdict: maybe_later",  # unknown token
            "Verdict: great",  # not in audit_status enum
            "Verdict:",  # missing token
        ],
        ids=[
            "empty",
            "none",
            "no-canonical-line",
            "mid-sentence-prose",
            "unknown-token",
            "non-enum-word",
            "missing-token",
        ],
    )
    def test_non_matching_returns_none(self, summary: str | None) -> None:
        assert auditor_taxonomy.parse_narrative_verdict(summary) is None


# ───────────────────────── 2. detect_verdict_mismatch ─────────────────────────


class TestDetectVerdictMismatch:
    def _make(
        self,
        *,
        summary: str | None,
        structured: str | None = None,
        plan_id: str = "test-plan",
        feature_id: str = "F001",
    ) -> auditor_taxonomy.VerdictMismatchError | None:
        envelope: dict[str, Any] = {}
        if summary is not None:
            envelope["summary"] = summary
        if structured is not None:
            envelope["audit_status"] = structured
        return auditor_taxonomy.detect_verdict_mismatch(
            plan_id=plan_id,
            feature_id=feature_id,
            iteration=0,
            audit_path=Path("/tmp/x.json"),
            audit_envelope=envelope,
        )

    def test_mismatch_signed_off_narrative_with_needs_changes_structured(self) -> None:
        """Case A — the SpinDine F001-i1 regression: narrative claims
        signed_off but the structured field is needs_changes. Must raise
        with all six named fields populated."""
        err = self._make(
            summary="**Verdict: signed_off**\n\nThe implementer addressed both i0 findings cleanly.",
            structured="needs_changes",
        )
        assert err is not None
        assert err.narrative_verdict == "signed_off"
        assert err.structured_status == "needs_changes"
        assert err.plan_id == "test-plan"
        assert err.feature_id == "F001"
        assert err.iteration == 0
        assert err.audit_path == Path("/tmp/x.json")
        assert "Reconcile the auditor's verdict" in err.remediation

    def test_agreement_returns_none(self) -> None:
        """Case B — both fields say signed_off."""
        assert (
            self._make(
                summary="Repo: x\n\nOverall verdict: signed_off.\n",
                structured="signed_off",
            )
            is None
        )

    def test_narrative_only_no_structured_returns_none(self) -> None:
        """Case C — structured field is missing/non-string. Existing
        behavior (caller defaults to 'inconclusive') is preserved."""
        assert self._make(summary="Verdict: signed_off", structured=None) is None

    def test_structured_only_no_narrative_returns_none(self) -> None:
        """Case D — no canonical narrative line. Structured field is
        canonical, no mismatch."""
        assert (
            self._make(summary="Just regular prose with no canonical verdict line.", structured="needs_changes")
            is None
        )

    def test_phrasing_variants_all_detect_mismatch(self) -> None:
        """Case E — all three canonical phrasings flag the mismatch."""
        for narrative_line, expected in (
            ("**Verdict: signed_off**", "signed_off"),
            ("Overall verdict: signed_off.", "signed_off"),
            ("Verdict: signed_off", "signed_off"),
        ):
            err = self._make(summary=narrative_line, structured="needs_changes")
            assert err is not None, narrative_line
            assert err.narrative_verdict == expected

    def test_unknown_status_in_summary_returns_none(self) -> None:
        """Case E (negative) — non-enum tokens in canonical position do
        not spoof the verdict check."""
        assert self._make(summary="Verdict: maybe_later", structured="needs_changes") is None

    def test_inbox_body_format(self) -> None:
        """Operator-readable INBOX body names both verdicts and gives
        remediation."""
        err = self._make(
            summary="**Verdict: signed_off**",
            structured="needs_changes",
            plan_id="p1",
            feature_id="F001",
        )
        assert err is not None
        body = auditor_taxonomy.format_verdict_mismatch_inbox_body(err)
        assert "verdict mismatch" in body.lower()
        assert "signed_off" in body
        assert "needs_changes" in body
        assert "Plan: p1" in body
        assert "Feature: F001" in body


# ───────────────────────── 3. Supervisor end-to-end ─────────────────────────


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _MismatchedAuditorExecutor(BaseExecutor):
    """Auditor that returns a summary asserting signed_off; the audit
    envelope's structured ``audit_status`` will be derived as signed_off
    by audit_writer's substring match. We then post-process the envelope
    via a wrapper to flip ``audit_status`` to needs_changes — producing
    exactly the SpinDine F001-i1 disagreement shape."""

    def __init__(self, agent: str, role: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.role = role

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        if self.role == "auditor":
            summary = (
                "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "## Target context\nRepo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "**Verdict: signed_off**\n\n"
                "The implementer addressed both substantive i0 findings cleanly."
            )
        else:
            summary = (
                "Repo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "## Target context\nRepo: synthetic\nEnv: dev\nProject: (none)\n\n"
                "[F001] Implementer landed the change."
            )
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=summary,
            raw_response=summary,
            error=None,
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _make_plan(tmp_path: Path, plan_id: str) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: F001 verdict-mismatch synthetic
type: infra
tier: trivial
status: draft
date: "2026-05-09"
description: Synthetic plan for F001 verdict-mismatch tests.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 2
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# F001 verdict-mismatch synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "test",
                        "phase": 0,
                        "description": "Synthetic feature.",
                        "steps": ["scripted"],
                        "acceptance": "ok",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return plan_dir


def _install_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    impl = _MismatchedAuditorExecutor("claude", "implementer")
    aud = _MismatchedAuditorExecutor("codex", "auditor")
    monkeypatch.setenv(notify.DISABLE_ENV, "1")
    monkeypatch.setitem(AGENT_REGISTRY, "claude", lambda: impl)
    monkeypatch.setitem(AGENT_REGISTRY, "codex", lambda: aud)
    monkeypatch.setattr(
        supervisor,
        "_quota_gate",
        lambda agent: (None, f"[quota] {agent}: bypassed"),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "evaluate_global",
        lambda: supervisor.circuit_breakers.GlobalBreakerState(False, 0),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_wall_clock",
        lambda *args, **kwargs: (False, ""),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_budget_ceiling",
        lambda *args, **kwargs: supervisor.circuit_breakers.BudgetCeilingResult(
            supervisor.circuit_breakers.BudgetCeilingKind.OK, False, ""
        ),
    )
    monkeypatch.setattr(
        supervisor.quota_admission,
        "evaluate",
        lambda *args, **kwargs: supervisor.quota_admission.AdmissionCheck(
            supervisor.quota_admission.DispatchClass.AUTONOMOUS,
            supervisor.quota_admission.QuotaCheck(False, None, None, 90.0),
            supervisor.quota_admission.InteractiveCheck(False, None),
            frozenset(),
        ),
    )


def _flip_audit_status_after_run_round(
    monkeypatch: pytest.MonkeyPatch, new_status: str
) -> None:
    """Force a post-build mismatch — audit_writer derives signed_off from
    the summary, then this wrapper flips audit_status to new_status,
    leaving the narrative line untouched. Mirrors the SpinDine F001-i1
    disagreement shape that F001 of plan 2026-05-09-002 catches."""
    original = supervisor._run_round

    def wrapped(*args: Any, **kwargs: Any) -> Path:
        path = original(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            data = json.loads(path.read_text())
            data["audit_status"] = new_status
            # Intentionally do NOT rewrite the summary — this is exactly
            # the test_fixture-vs-real-bug shape we want to flag.
            path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    monkeypatch.setattr(supervisor, "_run_round", wrapped)


class TestSupervisorWiring:
    def test_supervisor_raises_on_mismatch_and_writes_inbox(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: dispatch_volley raises VerdictMismatchError when
        the auditor envelope's narrative says signed_off but the
        structured field is needs_changes. INBOX records the classified
        event before the raise."""
        _install_runtime(monkeypatch)
        _flip_audit_status_after_run_round(monkeypatch, "needs_changes")
        plan_id = "2026-05-09-960-fix-verdict-mismatch-raises"
        plan_dir = _make_plan(tmp_path, plan_id)

        with pytest.raises(auditor_taxonomy.VerdictMismatchError) as excinfo:
            supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
        err = excinfo.value
        assert err.narrative_verdict == "signed_off"
        assert err.structured_status == "needs_changes"
        assert err.iteration == 0
        # INBOX classification event landed before the raise.
        events = inbox.read_events(plan_dir)
        mismatch_events = [e for e in events if e.event == "verdict_mismatch"]
        assert len(mismatch_events) == 1
        ev = mismatch_events[0]
        assert ev.headers["narrative_verdict"] == "signed_off"
        assert ev.headers["structured_status"] == "needs_changes"
        assert ev.headers["iteration"] == "0"
        assert ev.headers["feature_id"] == "F001"

    def test_supervisor_proceeds_when_narrative_and_structured_agree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When narrative says signed_off AND audit_writer derives
        signed_off (no flip), the supervisor proceeds normally — no
        mismatch fired."""
        _install_runtime(monkeypatch)
        # No _flip_audit_status — audit_writer's substring match on the
        # summary already produces "signed_off".
        plan_id = "2026-05-09-961-fix-verdict-agreement"
        plan_dir = _make_plan(tmp_path, plan_id)

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

        # No VerdictMismatchError; volley reaches signed_off terminal.
        assert result.final_status == "signed_off", result
        events = inbox.read_events(plan_dir)
        assert not any(e.event == "verdict_mismatch" for e in events)
