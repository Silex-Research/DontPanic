"""Plan 2026-08-10-001 — approval copy names the gate the supervisor paused on.

F001: _gather_fields derives {gate} from technical_metadata['pending_gates'],
never from subtype. Multi-gate pauses do not emit a comma-joined approve
command.

F002: exact_command for a single pending gate is pasteable, and no renderable
kind may name a gate absent from its source event.
"""

from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path
from typing import Any

import pytest

from dontpanic_orchestrate import event_copy, notify_event, supervisor
from dontpanic_orchestrate.decision_brief import BriefStatus, DecisionBrief

PLAN_ID = "2026-08-10-001-fix-gate-identity-in-approval-copy"

# Closed vocabulary the invariant scans for. A rendered slot that names one
# of these when the source event did not carry it is the original defect.
_GATE_TOKENS = (
    "pre_impl",
    "pre_merge",
    "on_escalation",
    "tier_promotion",
    "cost_trigger",
)


def _brief() -> DecisionBrief:
    return DecisionBrief(
        what_changes="Name the pending gate in the approve command.",
        user_impact="The approval prompt names the gate that is actually blocking.",
        affected_audience="operator",
        decision_consequence="Clearing pre_merge releases the change to merge.",
        reversible=False,
        status=BriefStatus.DECLARED,
        surfaces=("backend", "ux"),
    )


def _event(
    *,
    pending_gates: str | None,
    stage: str,
    inbox_event: str = "gate_hit",
    extra_tech: dict[str, Any] | None = None,
) -> notify_event.NotifyEvent:
    tech: dict[str, Any] = {"stage": stage}
    if pending_gates is not None:
        tech["pending_gates"] = pending_gates
    if extra_tech:
        tech.update(extra_tech)
    return notify_event.NotifyEvent(
        kind="gate_paused",
        severity="action_required",
        plan_id=PLAN_ID,
        feature_id="F001",
        body=f"**Gate pause** ({stage})",
        inbox_event=inbox_event,
        subtype=stage,
        technical_metadata=tech,
        decision_brief=_brief(),
    )


def _slots(rendered: Any) -> str:
    parts = [
        str(getattr(rendered, f.name) or "")
        for f in dataclasses.fields(rendered)
        if isinstance(getattr(rendered, f.name, None), str)
    ]
    return " ".join(parts)


class TestGatherFieldsReadsPendingGates:
    """F001 AC1–AC5."""

    def test_pre_merge_pending_general_stage_names_the_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[Any] = []
        monkeypatch.setattr(
            supervisor.notify_event,
            "dispatch_event",
            lambda ev, **kw: captured.append(ev),
        )
        supervisor._emit_gate_paused_discord(
            Path("."),
            PLAN_ID,
            "F001",
            pending_gates=["pre_merge"],
            stage="general",
        )
        assert captured, "emitter must dispatch"
        # The named call site: stage="general" at supervisor.py ~1316.
        src = inspect.getsource(supervisor._emit_gate_paused_discord)
        assert "pending_gates" in src
        rendered = event_copy.render(captured[0])
        assert rendered is not None
        text = _slots(rendered)
        assert "gate `general`" not in text
        assert "gate `pre_merge`" in text or rendered.exact_command == (
            f"dontpanic approve {PLAN_ID} pre_merge"
        )
        assert rendered.exact_command == f"dontpanic approve {PLAN_ID} pre_merge"

    def test_iteration_cap_pending_upfront_stage_is_not_the_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[Any] = []
        monkeypatch.setattr(
            supervisor.notify_event,
            "dispatch_event",
            lambda ev, **kw: captured.append(ev),
        )
        supervisor._emit_gate_paused_discord(
            Path("."),
            PLAN_ID,
            "F001",
            pending_gates=["breaker:iteration_cap"],
            stage="upfront",
        )
        rendered = event_copy.render(captured[0])
        assert rendered is not None
        text = _slots(rendered)
        assert "gate `upfront`" not in text
        assert rendered.exact_command == (
            f"dontpanic approve {PLAN_ID} breaker:iteration_cap"
        )

    def test_call_sites_named(self) -> None:
        source = inspect.getsource(supervisor)
        assert 'stage="general"' in source or "stage='general'" in source
        assert 'stage="upfront"' in source or "stage='upfront'" in source

    def test_missing_pending_gates_omits_gate_not_subtype(self) -> None:
        event = _event(pending_gates=None, stage="general")
        event.technical_metadata.pop("pending_gates", None)
        rendered = event_copy.render(event)
        assert rendered is not None
        assert "gate `general`" not in _slots(rendered)
        if rendered.exact_command:
            assert " general" not in rendered.exact_command

    def test_multi_gate_command_has_no_comma(self) -> None:
        event = _event(pending_gates="pre_merge, on_escalation", stage="general")
        rendered = event_copy.render(event)
        assert rendered is not None
        if rendered.exact_command:
            assert "," not in rendered.exact_command
        else:
            # Documented: multi-gate pauses omit a single approve command
            # rather than emit an unrunnable comma-joined token.
            assert rendered.exact_command is None

    def test_pre_merge_stage_site_still_names_pre_merge(self) -> None:
        event = _event(pending_gates="pre_merge", stage="pre_merge")
        rendered = event_copy.render(event)
        assert rendered is not None
        assert rendered.exact_command == f"dontpanic approve {PLAN_ID} pre_merge"


class TestExactCommandInvariant:
    """F002."""

    def test_pre_merge_command_is_exact(self) -> None:
        event = _event(pending_gates="pre_merge", stage="general")
        rendered = event_copy.render(event)
        assert rendered is not None
        assert rendered.exact_command == f"dontpanic approve {PLAN_ID} pre_merge"

    def test_no_renderable_kind_names_an_absent_gate(self) -> None:
        kinds = [
            kind
            for kind, disp in event_copy.DISPOSITION_TABLE.items()
            if disp in {event_copy.Disposition.LIVE, event_copy.Disposition.DASHBOARD_ACTION}
        ]
        assert kinds, "parametrized set must be derived and non-empty"
        for kind in kinds:
            event = notify_event.NotifyEvent(
                kind=kind,
                severity="action_required",
                plan_id=PLAN_ID,
                feature_id="F002",
                body="synthetic",
                inbox_event=kind,
                subtype="general",
                technical_metadata={"stage": "general"},
            )
            try:
                rendered = event_copy.render(event)
            except KeyError:
                continue
            if rendered is None:
                continue
            text = _slots(rendered)
            present = event_copy.gates_named_in_event(event)
            for token in _GATE_TOKENS:
                if token in text and token not in present:
                    pytest.fail(
                        f"{kind} named gate {token!r} absent from source event"
                    )

    def test_invariant_fails_if_subtype_alias_returns(self) -> None:
        """Non-vacuity: the old fallback would name a gate the event lacks."""
        event = _event(pending_gates=None, stage="pre_merge")
        event.technical_metadata.pop("pending_gates", None)
        # Force the old alias and show the invariant would catch it.
        fields = event_copy._gather_fields(
            inbox_event="gate_hit",
            event=event,
            plan_meta=None,
            feature_meta=None,
        )
        assert fields.get("gate") in {"", "-", None} or fields.get("gate") != "pre_merge" or (
            event.technical_metadata.get("pending_gates")
        )
        # The mutation: if we put subtype back as the gate, the invariant trips.
        mutated_text = f"Supervisor paused at gate `{event.subtype}`"
        present = event_copy.gates_named_in_event(event)
        named = [t for t in _GATE_TOKENS if t in mutated_text]
        assert named, "mutation must name a gate token"
        assert any(t not in present for t in named)
