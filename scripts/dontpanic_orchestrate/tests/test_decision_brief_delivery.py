"""Plan 2026-08-09-002 F003 — the brief reaches the event on the real path.

The gap this feature closes is a delivery gap, not a copy gap, so the tests
are delivery tests: a pause is driven through ``supervisor.dispatch_volley``
with nothing stubbed on the notification path, and the assertion is that the
``NotifyEvent`` the dispatcher receives already carries a populated
``DecisionBrief`` — while ``event_copy.render`` is still called with the event
alone. That last assertion is the one that would have caught the original
mistake: a renderer reading ``plan_meta`` / ``feature_meta`` looks correct in
a unit test that passes them and is dead code in production.

Coverage maps to F003's acceptance:
  1. real supervisor path → populated brief, render() gets no metadata args
  2. the attached dataclass is frozen and equality-comparable
  3. status declared        — recorded digest matches the current description
  4. status possibly_stale  — digests differ
  5. status undeclared      — F001's user_impact block is absent
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    decision_brief,
    event_copy,
    notify,
    notify_event,
    supervisor,
)
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)

FEATURE_DESCRIPTION = (
    "Snapshot a typed brief onto NotifyEvent at pause-emission time."
)
IMPACT_SUMMARY = "Operators see what the change does for users before approving."


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- fixture plumbing --------------------------------------------------------


class _ScriptedExecutor(BaseExecutor):
    """Minimal executor so the volley reaches its gate checks. Every test
    here pauses before dispatch, so ``dispatch`` should never fire; it stays
    implemented (rather than raising) so a regression that skips the pause
    fails on the brief assertion instead of on a surprise exception."""

    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.dispatches: list[DispatchTask] = []

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.dispatches.append(task)
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=now,
            completed_at=now,
            success=True,
            summary="Overall verdict: signed_off.",
            raw_response="Overall verdict: signed_off.",
            error=None,
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _install_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize the admission / breaker surfaces so the only thing that can
    pause the volley is the declared human gate under test."""
    monkeypatch.setenv(notify.DISABLE_ENV, "1")
    monkeypatch.setitem(AGENT_REGISTRY, "claude", lambda: _ScriptedExecutor("claude"))
    monkeypatch.setitem(AGENT_REGISTRY, "codex", lambda: _ScriptedExecutor("codex"))
    monkeypatch.setattr(
        supervisor, "_quota_gate", lambda agent: (None, f"[quota] {agent}: bypassed")
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "evaluate_global",
        lambda: supervisor.circuit_breakers.GlobalBreakerState(False, 0),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_wall_clock",
        lambda *a, **k: (False, ""),
    )
    monkeypatch.setattr(
        supervisor.circuit_breakers,
        "check_budget_ceiling",
        lambda *a, **k: supervisor.circuit_breakers.BudgetCeilingResult(
            supervisor.circuit_breakers.BudgetCeilingKind.OK, False, ""
        ),
    )
    monkeypatch.setattr(
        supervisor.quota_admission,
        "evaluate",
        lambda *a, **k: supervisor.quota_admission.AdmissionCheck(
            supervisor.quota_admission.DispatchClass.AUTONOMOUS,
            supervisor.quota_admission.QuotaCheck(False, None, None, 90.0),
            supervisor.quota_admission.InteractiveCheck(False, None),
            frozenset(),
        ),
    )


def _make_plan(
    tmp_path: Path,
    plan_id: str,
    *,
    gates: list[str],
    user_impact: dict[str, Any] | None,
) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    gates_yaml = "\n".join(f"  - {gate}" for gate in gates)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: Decision brief delivery synthetic
type: infra
tier: trivial
status: draft
date: "2026-08-09"
description: Synthetic plan for the F003 decision-brief delivery tests.
agents_required:
  - claude
  - codex
human_gates:
{gates_yaml}
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# Decision brief delivery synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""
    )
    feature: dict[str, Any] = {
        "id": "F001",
        "category": "test",
        "phase": 0,
        "description": FEATURE_DESCRIPTION,
        "steps": ["scripted"],
        "acceptance": "The pause carries a brief.",
        "passes": False,
        "depends_on": [],
    }
    if user_impact is not None:
        feature["user_impact"] = user_impact
    (plan_dir / "features.json").write_text(
        json.dumps(
            {"task_id": plan_id, "schema_version": "1.0", "features": [feature]},
            indent=2,
        )
        + "\n"
    )
    return plan_dir


def _impact(*, description_hash: str) -> dict[str, Any]:
    return {
        "audience": "operator",
        "summary": IMPACT_SUMMARY,
        "surfaces": ["ux"],
        "description_hash": description_hash,
    }


class _Capture:
    """Records what the notification path actually received."""

    def __init__(self) -> None:
        self.events: list[notify_event.NotifyEvent] = []
        self.render_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []


def _instrument(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    """Wrap — do not replace — dispatch_event and event_copy.render, so the
    real dispatcher still runs and the render call it makes is observed as it
    is actually made."""
    cap = _Capture()
    real_dispatch = notify_event.dispatch_event
    real_render = event_copy.render

    def spy_dispatch(event: notify_event.NotifyEvent, **kwargs: Any) -> dict[str, bool]:
        cap.events.append(event)
        return real_dispatch(event, **kwargs)

    def spy_render(*args: Any, **kwargs: Any) -> Any:
        cap.render_calls.append((args, kwargs))
        return real_render(*args, **kwargs)

    monkeypatch.setattr(notify_event, "dispatch_event", spy_dispatch)
    monkeypatch.setattr(event_copy, "render", spy_render)
    return cap


def _pause_and_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plan_id: str,
    *,
    user_impact: dict[str, Any] | None,
    gates: list[str],
) -> tuple[_Capture, Any]:
    _install_runtime(monkeypatch)
    plan_dir = _make_plan(tmp_path, plan_id, gates=gates, user_impact=user_impact)
    cap = _instrument(monkeypatch)
    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
    assert result.final_status == "paused_on_gate", result
    return cap, result


def _sole_gate_event(cap: _Capture) -> notify_event.NotifyEvent:
    gate_events = [e for e in cap.events if e.kind == "gate_paused"]
    assert len(gate_events) == 1, [e.kind for e in cap.events]
    return gate_events[0]


# --- acceptance 1: real path, populated brief, no metadata args to render -----


def test_real_supervisor_pause_carries_populated_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cap, _ = _pause_and_capture(
        tmp_path,
        monkeypatch,
        "2026-08-09-910-infra-brief-real-path",
        user_impact=_impact(description_hash=_digest(FEATURE_DESCRIPTION)),
        gates=["pre_impl"],
    )

    event = _sole_gate_event(cap)
    brief = event.decision_brief
    assert brief is not None, "the real supervisor path emitted no brief"

    # All three elements are populated from data that only exists at the
    # emit site — none of it is reachable from the NotifyEvent alone.
    assert brief.what_changes == FEATURE_DESCRIPTION
    assert brief.user_impact == IMPACT_SUMMARY
    assert brief.affected_audience == "operator"
    assert brief.surfaces == ("ux",)
    assert "pre_impl" in brief.decision_consequence
    assert brief.reversible is True
    assert brief.status is decision_brief.BriefStatus.DECLARED

    # The point of the snapshot: render() ran on this path and was handed the
    # event and nothing else. A renderer reading plan_meta / feature_meta
    # would have received None for both.
    assert cap.render_calls, "event_copy.render was never called on the live path"
    for args, kwargs in cap.render_calls:
        assert len(args) == 1, f"render() got positional metadata: {args[1:]!r}"
        assert kwargs == {}, f"render() got keyword metadata: {kwargs!r}"


def test_reversibility_reflects_the_stage_not_a_hardcoded_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An upfront pause is undoable — the patch it unblocks still faces
    review. pre_merge is the last stop before the change lands, so the brief
    must not claim that decision is undoable."""
    cap, _ = _pause_and_capture(
        tmp_path,
        monkeypatch,
        "2026-08-09-911-infra-brief-upfront-stage",
        user_impact=_impact(description_hash=_digest(FEATURE_DESCRIPTION)),
        gates=["tier_promotion"],
    )
    upfront = _sole_gate_event(cap).decision_brief
    assert upfront is not None
    assert upfront.reversible is True

    pre_merge = decision_brief.build(
        plan_title="Decision brief delivery synthetic",
        feature_id="F001",
        feature={"description": FEATURE_DESCRIPTION},
        stage="pre_merge",
        pending_gates=["pre_merge"],
    )
    assert pre_merge.reversible is False
    assert "merge" in pre_merge.decision_consequence


# --- acceptance 2: frozen + equality-comparable -------------------------------


def test_attached_brief_is_frozen_and_equality_comparable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cap, _ = _pause_and_capture(
        tmp_path,
        monkeypatch,
        "2026-08-09-912-infra-brief-frozen",
        user_impact=_impact(description_hash=_digest(FEATURE_DESCRIPTION)),
        gates=["tier_promotion"],
    )
    brief = _sole_gate_event(cap).decision_brief
    assert brief is not None

    assert dataclasses.is_dataclass(brief)
    with pytest.raises(dataclasses.FrozenInstanceError):
        brief.user_impact = "rewritten downstream"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        brief.status = decision_brief.BriefStatus.UNDECLARED  # type: ignore[misc]

    # Equality is by value, which is what F007's parity test needs: two
    # surfaces reading the same snapshot compare equal field by field.
    twin = dataclasses.replace(brief)
    assert twin == brief
    assert twin is not brief
    assert dataclasses.replace(brief, reversible=not brief.reversible) != brief
    # Immutable all the way down — a list member would make the snapshot
    # mutable through the back door.
    assert isinstance(brief.surfaces, tuple)


# --- acceptance 3 / 4 / 5: the three statuses ---------------------------------


def test_status_is_declared_when_recorded_digest_matches_description(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cap, _ = _pause_and_capture(
        tmp_path,
        monkeypatch,
        "2026-08-09-913-infra-brief-declared",
        user_impact=_impact(description_hash=_digest(FEATURE_DESCRIPTION)),
        gates=["tier_promotion"],
    )
    brief = _sole_gate_event(cap).decision_brief
    assert brief is not None
    assert brief.status is decision_brief.BriefStatus.DECLARED
    assert brief.user_impact == IMPACT_SUMMARY


def test_status_is_possibly_stale_when_digests_differ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The declaration was written against different description text. D005:
    say the claim may be stale; do not present it as current, and do not drop
    it either — the operator still sees what was claimed."""
    cap, _ = _pause_and_capture(
        tmp_path,
        monkeypatch,
        "2026-08-09-914-infra-brief-stale",
        user_impact=_impact(
            description_hash=_digest("an older description this was written against")
        ),
        gates=["tier_promotion"],
    )
    brief = _sole_gate_event(cap).decision_brief
    assert brief is not None
    assert brief.status is decision_brief.BriefStatus.POSSIBLY_STALE
    assert brief.user_impact == IMPACT_SUMMARY
    assert brief.what_changes == FEATURE_DESCRIPTION


def test_status_is_undeclared_when_impact_block_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No block, no claim. The brief reports what it does not know rather
    than synthesizing an impact line — the fallback copy itself is F006."""
    cap, _ = _pause_and_capture(
        tmp_path,
        monkeypatch,
        "2026-08-09-915-infra-brief-undeclared",
        user_impact=None,
        gates=["tier_promotion"],
    )
    brief = _sole_gate_event(cap).decision_brief
    assert brief is not None
    assert brief.status is decision_brief.BriefStatus.UNDECLARED
    assert brief.user_impact is None
    assert brief.affected_audience is None
    assert brief.surfaces == ()
    # Element one and element three do not depend on the declaration, so
    # they are still present and honest.
    assert brief.what_changes == FEATURE_DESCRIPTION
    assert brief.decision_consequence
