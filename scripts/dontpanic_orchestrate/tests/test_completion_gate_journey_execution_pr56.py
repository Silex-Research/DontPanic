"""PR56 follow-ups through the PUBLIC completion path.

The two CodeRabbit findings on merged PR56 (r3422558988, r3422558994) were
reproduced against the pure honesty checker in
``test_experience_readiness_honesty_f004.py``. These tests drive the same
defects through :func:`completion_gate.audit_plan` — the production consumer
behind ``dontpanic plan audit`` / ``plan close`` — so the fix is proven where
an operator would feel it, not only in the checker.

Run::

    PYTHONPATH=scripts python3 -m pytest \\
        scripts/dontpanic_orchestrate/tests/test_completion_gate_journey_execution_pr56.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import completion_gate as cg  # noqa: E402
from dontpanic_orchestrate.experience_readiness_gate import (  # noqa: E402
    GAP_CONSUMER_OUTCOME_PENDING,
    GAP_CONSUMER_OUTCOME_UNPROVEN,
    OutcomeClass,
)
from dontpanic_orchestrate.experience_readiness_honesty import (  # noqa: E402
    EXECUTION_DATA_SOURCE,
)

JOURNEY = "agent-lists-tools"
POST_IMPL = "evidence/goal-governance/post_impl"


def _typed_ref(
    *,
    surface_class: str,
    data_source: str,
    evidence_class: str,
    consumer_family: str,
    availability: str = "available",
    provenance: str = "real",
    name: str,
) -> dict[str, Any]:
    """A fully typed EvidenceRef row bound to JOURNEY via its uri."""
    return {
        "type": "log",
        "uri": f"{POST_IMPL}/{surface_class}/{JOURNEY}/{name}.json",
        "data_source": data_source,
        "consumer_family": consumer_family,
        "availability": availability,
        "data_provenance": provenance,
        "evidence_class": evidence_class,
        "surface_class": surface_class,
    }


def _write_plan(plan_dir: Path, *, surfaces: list[str], consumer: str, refs: list[dict]) -> None:
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        "id: 2026-09-05-pr56-fixture\n"
        "title: PR56 journey-execution fixture\n"
        "type: feat\n"
        "tier: local\n"
        "status: active\n"
        'date: "2026-09-05"\n'
        "goal_type: new_feature\n"
        "description: Fixture plan proving the journey-execution discriminator at the gate.\n"
        "agents_required: [claude]\n"
        "human_gates: []\n"
        "privacy_tier: internal\n"
        "links:\n"
        "  objective_contract: ./objective_contract.json\n"
        "---\n\n# fixture\n",
        encoding="utf-8",
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": "2026-09-05-pr56-fixture",
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "tooling",
                        "phase": 0,
                        "description": "fixture feature carrying the typed evidence refs",
                        "steps": ["step one"],
                        "acceptance": "machine checkable acceptance for fixture feature",
                        "passes": True,
                        "depends_on": [],
                        "evidence_refs": refs,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (plan_dir / "objective_contract.json").write_text(
        json.dumps(
            {
                "goal_type": "new_feature",
                "source_of_truth": "fixture contract for the PR56 journey-execution regression",
                "completion_test": "fixture completion test string long enough for schema",
                "user_journeys": [
                    {
                        "name": JOURNEY,
                        "description": "an agent lists the available tools over MCP and reads status",
                        "surfaces": surfaces,
                        "states": ["ok"],
                        "acceptance_signals": ["tools/list returns the fixture tool set"],
                        "consumer": consumer,
                    }
                ],
                "required_evidence": [],
                "non_goals": [],
            }
        ),
        encoding="utf-8",
    )


def _agree_dispatch(_agent: str, _prompt: str) -> str:
    # Goal-audit stub: agree with whatever v1 findings exist so ONLY the
    # experience gate decides blocking in these tests.
    return "[]"


def _journey_outcome(result: cg.AuditPlanResult) -> OutcomeClass:
    """Recover JOURNEY's outcome class from the gate's findings: unproven
    emits a blocking finding, pending an advisory one, satisfied none."""
    gate = result.experience_gate
    assert gate is not None
    mine = [f for f in gate.findings if f.journey == JOURNEY]
    if not mine:
        return OutcomeClass.satisfied
    assert len(mine) == 1, mine
    if mine[0].gap_class == GAP_CONSUMER_OUTCOME_UNPROVEN:
        assert mine[0].severity == "blocking"
        return OutcomeClass.unproven
    assert mine[0].gap_class == GAP_CONSUMER_OUTCOME_PENDING, mine
    return OutcomeClass.pending


DEPENDENCY_REF = _typed_ref(
    surface_class="agent_mcp_tool",
    data_source="mcp:tools/list",
    evidence_class="tool_call_transcript",
    consumer_family="agent",
    name="tools-list",
)
EXECUTION_REF = _typed_ref(
    surface_class="agent_mcp_tool",
    data_source=EXECUTION_DATA_SOURCE,
    evidence_class="tool_call_transcript",
    consumer_family="agent",
    name="journey-walk",
)


def test_dependency_transcript_alone_does_not_prove_the_journey(tmp_path: Path) -> None:
    """r3422558988 at the gate: a real, available MCP dependency transcript
    satisfies typing but is not journey execution — the gate must block."""
    plan_dir = tmp_path / "plan"
    _write_plan(plan_dir, surfaces=["mcp_tool"], consumer="agent", refs=[DEPENDENCY_REF])

    result = cg.audit_plan(plan_dir, dispatch=_agree_dispatch, implementer_agent="claude")

    assert _journey_outcome(result) is OutcomeClass.unproven
    assert result.blocking is True
    reason = next(r for r in result.reasons if "real_execution=False" in r)
    # The blocking reason names the exact gap and how to fill it.
    assert 'data_source="journey_execution"' in reason
    assert "dependency transcript is not execution proof" in reason
    assert "missing required families" not in reason  # agent-only journey: families are covered


def test_journey_execution_ref_alongside_dependency_satisfies(tmp_path: Path) -> None:
    """Positive control: the same plan plus a journey_execution-keyed real
    transcript is satisfied, and the execution key is NOT treated as a
    dependency source that would then demand its own family coverage."""
    plan_dir = tmp_path / "plan"
    _write_plan(
        plan_dir, surfaces=["mcp_tool"], consumer="agent", refs=[DEPENDENCY_REF, EXECUTION_REF]
    )

    result = cg.audit_plan(plan_dir, dispatch=_agree_dispatch, implementer_agent="claude")

    assert _journey_outcome(result) is OutcomeClass.satisfied
    assert not any(r.startswith("experience gate") for r in result.reasons), result.reasons


def test_both_family_journey_with_agent_only_evidence_is_not_satisfied(tmp_path: Path) -> None:
    """r3422558994 at the gate: a journey spanning human + agent surfaces whose
    dependency source is typed by the agent family only must not be satisfied,
    even with a real journey-execution ref present."""
    plan_dir = tmp_path / "plan"
    _write_plan(
        plan_dir,
        surfaces=["web", "mcp_tool"],
        consumer="both",
        refs=[DEPENDENCY_REF, EXECUTION_REF],
    )

    result = cg.audit_plan(plan_dir, dispatch=_agree_dispatch, implementer_agent="claude")

    assert _journey_outcome(result) is not OutcomeClass.satisfied
    # Pending is advisory, so the gate does not block; the journey's honesty
    # result still names the uncovered family for whoever reads the detail.
    from dontpanic_orchestrate import experience_readiness_honesty as h

    honesty = h.check_degraded_honesty(
        [h.RequiredDataSource("mcp:tools/list", frozenset({h.Fam.human, h.Fam.agent}))],
        {},
        cg._typed_evidence_refs(plan_dir),
    )
    assert honesty.missing_families == ["mcp:tools/list:human"]
    assert honesty.execution_evidence is True


@pytest.mark.parametrize("key", ["payments", "mcp:tools/list"])
def test_execution_class_under_dependency_key_is_not_execution(tmp_path: Path, key: str) -> None:
    plan_dir = tmp_path / "plan"
    walk_under_dependency_key = _typed_ref(
        surface_class="agent_mcp_tool",
        data_source=key,
        evidence_class="contract_check",
        consumer_family="agent",
        name="contract-check",
    )
    _write_plan(
        plan_dir,
        surfaces=["mcp_tool"],
        consumer="agent",
        refs=[DEPENDENCY_REF, walk_under_dependency_key],
    )

    result = cg.audit_plan(plan_dir, dispatch=_agree_dispatch, implementer_agent="claude")

    assert _journey_outcome(result) is OutcomeClass.unproven
