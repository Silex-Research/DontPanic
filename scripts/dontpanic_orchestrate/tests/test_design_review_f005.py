"""Tests for plan-review F005 — design-review volley.

Uses a mock executor (no live paid call, acceptance #4) to drive the
design-reviewer through the volley machinery and assert: a known-oversize
decomposition yields an ``oversize`` finding, a clean decomposition signs off,
the envelope is the standard ``{verdict, findings}`` keyed to the closed
taxonomy, and the opt-in trigger only fires on lint uncertainty / operator
request.
"""

from __future__ import annotations

import datetime as dt
import json

from dontpanic_orchestrate.executors.base import (
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)
from dontpanic_orchestrate.plan_review import design_review as dr
from dontpanic_orchestrate.plan_review.report import (
    build_default_resolvers,
    build_plan_scope_report,
)


def _iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _MockReviewer(BaseExecutor):
    """A scripted design reviewer — returns a canned JSON envelope per dispatch.
    No subprocess, no CLI: the whole point is a paid-call-free synthetic test."""

    def __init__(self, envelopes: list[dict]) -> None:
        super().__init__()
        self.agent_name = "mock-design-reviewer"
        self.cli_binary = None
        self._envelopes = list(envelopes)
        self._i = 0
        self.received_prompts: list[str] = []

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.received_prompts.append(
            str((task.extra_context or {}).get("prompt_override", ""))
        )
        env = self._envelopes[min(self._i, len(self._envelopes) - 1)]
        self._i += 1
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso(),
            completed_at=_iso(),
            success=True,
            summary="scripted design review",
            raw_response=json.dumps(env),
            quota_consumed={"tokens_in": 0, "tokens_out": 0},
        )


_OVERSIZE_FEATURES = [
    {
        "id": "F007",
        "description": "Add a cli subcommand AND a dashboard html view AND a doctor preflight warn",
        "steps": ["touch cli", "render dashboard", "doctor warn"],
        "acceptance": "(1) runs (2) renders (3) warns",
    }
]
_CLEAN_FEATURES = [
    {
        "id": "F015",
        "description": "Add a single cli subcommand",
        "steps": ["add subcommand"],
        "acceptance": "(1) the command runs and prints a report",
    }
]


# ─────────────────────────── envelope contract (acceptance #1/#2) ───────────


def test_run_design_volley_returns_standard_envelope_with_oversize_finding():
    reviewer = _MockReviewer(
        [
            {
                "verdict": "needs_changes",
                "findings": [
                    {
                        "kind": "oversize",
                        "severity": "block",
                        "feature_id": "F007",
                        "evidence": "spans cli + dashboard + doctor",
                    }
                ],
            }
        ]
    )
    env = dr.run_design_volley("p1", _OVERSIZE_FEATURES, auditor=reviewer)
    assert env.verdict == "needs_changes"
    assert len(env.findings_of_kind("oversize")) == 1
    assert env.findings[0].feature_id == "F007"
    # standard envelope shape
    blob = env.to_dict()
    assert set(blob) >= {"verdict", "findings"}
    assert blob["findings"][0]["kind"] == "oversize"
    # the reviewer actually saw the decomposition
    assert "F007" in reviewer.received_prompts[0]


def test_clean_decomposition_signs_off():
    reviewer = _MockReviewer([{"verdict": "signed_off", "findings": []}])
    env = dr.run_design_volley("p1", _CLEAN_FEATURES, auditor=reviewer)
    assert env.verdict == "signed_off"
    assert env.findings == []


def test_findings_outside_taxonomy_are_quarantined():
    reviewer = _MockReviewer(
        [
            {
                "verdict": "needs_changes",
                "findings": [
                    {"kind": "oversize", "severity": "block", "feature_id": "F007", "evidence": "e"},
                    {"kind": "made_up_kind", "severity": "warn", "feature_id": "F007", "evidence": "x"},
                ],
            }
        ]
    )
    env = dr.run_design_volley("p1", _OVERSIZE_FEATURES, auditor=reviewer)
    # taxonomy-pure findings list
    assert [f.kind for f in env.findings] == ["oversize"]
    assert env.unrecognized[0]["kind"] == "made_up_kind"
    assert all(f.kind in dr.DESIGN_TAXONOMY for f in env.findings)


def test_blocked_on_unparseable_response():
    reviewer = _MockReviewer([{}])  # no verdict key
    env = dr.run_design_volley("p1", _CLEAN_FEATURES, auditor=reviewer)
    assert env.verdict == "blocked"


# ─────────────────────────── planner revision round ────────────────────────


class _MockPlanner(BaseExecutor):
    def __init__(self, revised_features: list[dict]) -> None:
        super().__init__()
        self.agent_name = "mock-planner"
        self.cli_binary = None
        self._revised = revised_features

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso(),
            completed_at=_iso(),
            success=True,
            summary="scripted plan revision",
            raw_response=json.dumps(self._revised),
        )


def test_planner_revision_then_signoff():
    # round 0: needs_changes(oversize); planner revises; round 1: signed_off
    reviewer = _MockReviewer(
        [
            {
                "verdict": "needs_changes",
                "findings": [{"kind": "oversize", "severity": "block", "feature_id": "F007", "evidence": "e"}],
            },
            {"verdict": "signed_off", "findings": []},
        ]
    )
    planner = _MockPlanner(_CLEAN_FEATURES)
    env = dr.run_design_volley(
        "p1", _OVERSIZE_FEATURES, auditor=reviewer, planner=planner, max_iterations=2
    )
    assert env.verdict == "signed_off"
    assert env.rounds == 2


# ─────────────────────────── opt-in trigger (acceptance #3) ─────────────────


def _scope_report(features: list[dict]):
    return build_plan_scope_report("p1", features, build_default_resolvers())


def test_trigger_fires_on_operator_request_even_when_clean():
    report = _scope_report(_CLEAN_FEATURES)
    assert dr.should_run_design_volley(report, operator_requested=True) is True


def test_trigger_does_not_auto_fire_on_clean_plan():
    # A genuinely clean single-surface feature: no warn flags -> no auto-run.
    report = _scope_report(_CLEAN_FEATURES)
    assert dr.should_run_design_volley(report) is False


def test_trigger_auto_fires_on_lint_uncertainty():
    # A 2-surface feature yields a warn-severity over_surface flag (uncertainty).
    uncertain = [
        {
            "id": "FX",
            "description": "Add a cli subcommand AND a dashboard html view",
            "steps": [],
            "acceptance": "(1) runs (2) renders",
        }
    ]
    report = _scope_report(uncertain)
    assert dr.should_run_design_volley(report) is True
