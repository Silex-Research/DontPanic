"""Plan 2026-08-09-002 F004 — the copy contract carries the brief's own slots.

Before this feature the plain-language slot on an event-derived ActionItem was
aliased to ``rendered.detail`` (orchestration prose) and ``reversible`` was a
hardcoded ``False``. The three product-context fields had nowhere to live at
all. These tests hold the widened contract:

  1. RenderedEvent exposes what_changes / user_impact / affected_audience with
     None defaults, and every pre-F004 translation-table row still constructs.
  2. Three distinct briefs each round-trip through render() into ActionItem
     shape with their decision-consequence element preserved exactly — so the
     mapping is proven, not one fixture happening to match.
  3. For every renderable kind, plain_consequence differs from the rendered
     detail. This is the regression that fails if the aliasing comes back,
     asserted across the whole table rather than at one example.
  4. reversible tracks the brief across both True and False.
"""

from __future__ import annotations

import dataclasses
import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    decision_brief,
    event_copy,
    notify_event,
    operator_console,
)

BRIEF_COPY_FIELDS = ("what_changes", "user_impact", "affected_audience")

# Renderable == the dispositions render() actually produces output for.
# INBOX_ONLY / AUDIT_ONLY kinds return None and are outside this contract.
RENDERABLE_KINDS = sorted(
    kind
    for kind, disposition in event_copy.DISPOSITION_TABLE.items()
    if disposition
    in (event_copy.Disposition.LIVE, event_copy.Disposition.DASHBOARD_ACTION)
)


# Long-tail fields those kinds' templates interpolate. Pre-existing contract
# (D017): the emit site supplies them via technical_metadata, and _gather_fields
# does not default them — so a realistic event has to carry them here too.
KIND_METADATA: dict[str, dict[str, Any]] = {
    "quota_warn": {"agent": "claude", "percent_weekly": 82, "threshold": 80},
    "unit_mismatch": {
        "agent": "claude",
        "window": "weekly",
        "cap_unit": "tokens",
        "observed_unit": "percent",
    },
    "config_required": {"cause": "no_cap_for_signal"},
}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _feature(description: str, summary: str, audience: str) -> dict[str, Any]:
    return {
        "id": "F004",
        "description": description,
        "user_impact": {
            "audience": audience,
            "summary": summary,
            "surfaces": ["cli"],
            "description_hash": _digest(description),
        },
    }


def _brief(
    *,
    description: str,
    summary: str,
    audience: str = "operator",
    stage: str,
    gates: list[str],
    plan_title: str = "Decision brief at gates",
    feature_id: str | None = "F004",
) -> decision_brief.DecisionBrief:
    return decision_brief.build(
        plan_title=plan_title,
        feature_id=feature_id,
        feature=_feature(description, summary, audience),
        stage=stage,
        pending_gates=gates,
    )


# Three genuinely different briefs: different stages (so different
# decision-consequence text AND different reversibility), different audiences,
# different impact summaries.
BRIEF_PRE_IMPL = _brief(
    description="Widen the copy contract with distinct brief fields.",
    summary="Operators read what the change does before approving it.",
    stage="pre_impl",
    gates=["pre_impl"],
)
BRIEF_PRE_MERGE = _brief(
    description="Release the decision brief to the merge gate.",
    summary="Reviewers see the product claim at the last stop before landing.",
    audience="end_user",
    stage="pre_merge",
    gates=["pre_merge"],
)
# Deliberately rewrite-sensitive. Every text slot on this brief contains a
# string that event_copy.normalize_brand_drift would rewrite: the plan title
# carries "Jarvis [" and — because feature_id is None — it is also the subject
# interpolated into decision_consequence. Without this fixture the exact
# -preservation assertions below are vacuous, since normalization is a no-op on
# already-on-brand text and a re-introduced rewrite would go unnoticed.
BRIEF_UPFRONT = _brief(
    description="Run jarvis approve F004. to start the volley.",
    summary="Operators told to run jarvis resume see the volley continue.",
    audience="developer",
    stage="upfront",
    gates=["upfront", "pre_impl"],
    plan_title="Jarvis [orchestrate] decision brief at gates",
    feature_id=None,
)
DISTINCT_BRIEFS = (BRIEF_PRE_IMPL, BRIEF_PRE_MERGE, BRIEF_UPFRONT)

# The slots F004 carries through render() verbatim, paired with the brief
# attribute each one is sourced from.
VERBATIM_SLOTS: tuple[tuple[str, str], ...] = (
    ("what_changes", "what_changes"),
    ("user_impact", "user_impact"),
    ("affected_audience", "affected_audience"),
    ("plain_consequence", "decision_consequence"),
)


def _event(
    inbox_event: str,
    *,
    brief: decision_brief.DecisionBrief | None,
    technical_metadata: dict[str, Any] | None = None,
) -> notify_event.NotifyEvent:
    return notify_event.NotifyEvent(
        kind=inbox_event,
        severity=notify_event.SEVERITY_ACTION_REQUIRED,
        plan_id="2026-08-09-002-feat-decision-brief-at-gates",
        feature_id="F004",
        body="synthetic pause",
        inbox_event=inbox_event,
        subtype="pre_impl",
        evidence_uri="file:///plan/INBOX.md",
        technical_metadata=(
            technical_metadata
            if technical_metadata is not None
            else dict(KIND_METADATA.get(inbox_event, {}))
        ),
        decision_brief=brief,
    )


def _entry(rendered: Any) -> dict[str, Any]:
    return operator_console._rendered_to_action_item_dict(
        rendered,
        source=operator_console.SOURCE_SUPERVISOR,
        updated_at="2026-08-09T00:00:00Z",
    )


# --- (1) the widened contract ------------------------------------------------


def test_rendered_event_exposes_brief_copy_fields_defaulting_to_none() -> None:
    """The three product-context fields exist and default to None."""
    defaults = {
        field.name: field.default
        for field in dataclasses.fields(event_copy.RenderedEvent)
    }
    for name in BRIEF_COPY_FIELDS:
        assert name in defaults, f"RenderedEvent is missing {name}"
        assert defaults[name] is None, f"RenderedEvent.{name} must default to None"

    # Constructible without them — the pre-F004 call shape still works.
    rendered = event_copy.RenderedEvent(
        band="needs_action",
        title="Approval needed",
        detail="Supervisor paused at gate pre_impl.",
        exact_command=None,
        evidence_uri=None,
        disposition=event_copy.Disposition.LIVE,
    )
    for name in BRIEF_COPY_FIELDS:
        assert getattr(rendered, name) is None


def test_every_translation_row_still_constructs_without_brief_fields() -> None:
    """Widening the row type kept every authored row compiling unchanged."""
    assert event_copy.TRANSLATION_TABLE, "translation table is empty"
    for kind, row in event_copy.TRANSLATION_TABLE.items():
        rebuilt = event_copy._Template(
            band=row.band,
            headline=row.headline,
            why=row.why,
            action=row.action,
        )
        assert rebuilt == row, f"{kind} row does not round-trip through the row type"
        for name in BRIEF_COPY_FIELDS:
            assert getattr(rebuilt, name) is None


def test_render_carries_the_brief_copy_fields_onto_the_rendered_event() -> None:
    rendered = event_copy.render(_event("gate_hit", brief=BRIEF_PRE_IMPL))
    assert rendered is not None
    assert rendered.what_changes == BRIEF_PRE_IMPL.what_changes
    assert rendered.user_impact == BRIEF_PRE_IMPL.user_impact
    assert rendered.affected_audience == BRIEF_PRE_IMPL.affected_audience


def test_render_without_a_brief_leaves_the_slots_empty() -> None:
    """No brief means no claim — nothing is substituted in from other copy."""
    rendered = event_copy.render(_event("gate_hit", brief=None))
    assert rendered is not None
    for name in BRIEF_COPY_FIELDS:
        assert getattr(rendered, name) is None
    assert rendered.plain_consequence is None
    assert rendered.plain_consequence != rendered.detail
    assert rendered.reversible is False


# --- (2) round-trip: brief → render → ActionItem ------------------------------


@pytest.mark.parametrize(
    "brief", DISTINCT_BRIEFS, ids=["pre_impl", "pre_merge", "upfront"]
)
def test_decision_consequence_survives_the_round_trip(
    brief: decision_brief.DecisionBrief,
) -> None:
    """plain_consequence is the brief's decision-consequence element, exactly."""
    rendered = event_copy.render(_event("gate_hit", brief=brief))
    assert rendered is not None
    assert rendered.plain_consequence == brief.decision_consequence

    entry = _entry(rendered)
    assert entry["plain_consequence"] == brief.decision_consequence
    assert entry["plain_consequence"] != entry["detail"]


def test_the_three_briefs_are_genuinely_distinct() -> None:
    """Guards the round-trip test above from passing on identical fixtures."""
    consequences = {b.decision_consequence for b in DISTINCT_BRIEFS}
    assert len(consequences) == len(DISTINCT_BRIEFS)


def test_one_fixture_brief_is_actually_rewrite_sensitive() -> None:
    """Without this the exact-preservation assertions below prove nothing.

    Brand normalization is a no-op on on-brand text, so a brief made only of
    on-brand text round-trips byte-for-byte whether or not render() rewrites
    it. BRIEF_UPFRONT is the fixture that can tell the difference, and this
    test fails if it ever stops being able to.
    """
    for _slot, attr in VERBATIM_SLOTS:
        value = getattr(BRIEF_UPFRONT, attr)
        assert value, f"BRIEF_UPFRONT.{attr} is empty"
        if attr == "affected_audience":
            continue  # an enum value; no prose to rewrite
        assert event_copy.normalize_brand_drift(value) != value, (
            f"BRIEF_UPFRONT.{attr} carries no rewrite-sensitive text, so the "
            "exact-preservation regression cannot fail"
        )


@pytest.mark.parametrize(
    "brief", DISTINCT_BRIEFS, ids=["pre_impl", "pre_merge", "upfront"]
)
@pytest.mark.parametrize("slot,attr", VERBATIM_SLOTS, ids=[s for s, _ in VERBATIM_SLOTS])
def test_brief_slots_reach_the_action_item_byte_for_byte(
    slot: str, attr: str, brief: decision_brief.DecisionBrief
) -> None:
    """render() copies the brief snapshot; it does not rewrite it.

    The brief was snapshotted upstream where plan and feature data were in
    scope. Applying D010 brand normalization here mutated operator-visible
    text on the way to ActionItem — this is the regression that catches it.
    """
    expected = getattr(brief, attr)
    rendered = event_copy.render(_event("gate_hit", brief=brief))
    assert rendered is not None
    assert getattr(rendered, slot) == expected

    entry = _entry(rendered)
    if slot in entry:
        assert entry[slot] == expected


def test_table_fallback_copy_is_still_brand_normalized() -> None:
    """Dropping the rewrite for brief copy did not drop it for table copy.

    Rows authored in this repo's translation table are what D010 governs, so
    the no-brief path keeps normalizing.
    """
    template = event_copy._Template(
        band="needs_action",
        headline="x",
        why="y",
        action=None,
        what_changes="Run jarvis approve {feature_id}.",
    )
    slots = event_copy._brief_fields(
        _event("gate_hit", brief=None), template, {"feature_id": "F004"}
    )
    assert slots["what_changes"] == "Run dontpanic approve F004."


def test_round_trip_entry_rehydrates_into_an_action_item() -> None:
    """The projected dict is still ActionItem-shaped after the widening."""
    rendered = event_copy.render(_event("gate_hit", brief=BRIEF_PRE_MERGE))
    assert rendered is not None
    entry = _entry(rendered)
    item = operator_console.ActionItem(
        id=entry["id"],
        source=entry["source"],
        band=operator_console.Band(entry["band"]),
        title=entry["title"],
        detail=entry["detail"],
        exact_command=entry["exact_command"],
        automatable=entry["automatable"],
        human_required_reason=entry["human_required_reason"],
        evidence_uri=entry["evidence_uri"],
        updated_at=entry["updated_at"],
        dedupe_key=entry["dedupe_key"],
        reversible=entry["reversible"],
        plain_consequence=entry["plain_consequence"],
    )
    assert item.plain_consequence == BRIEF_PRE_MERGE.decision_consequence
    assert item.reversible is BRIEF_PRE_MERGE.reversible


# --- (3) the aliasing regression, across the whole table ---------------------


@pytest.mark.parametrize("kind", RENDERABLE_KINDS)
def test_plain_consequence_is_never_the_rendered_detail(kind: str) -> None:
    """Every renderable kind: the plain-language slot is not orchestration prose."""
    rendered = event_copy.render(_event(kind, brief=BRIEF_PRE_IMPL))
    assert rendered is not None, f"{kind} is renderable but render() returned None"
    assert rendered.detail, f"{kind} rendered no detail"
    assert rendered.plain_consequence == BRIEF_PRE_IMPL.decision_consequence
    assert rendered.plain_consequence != rendered.detail

    entry = _entry(rendered)
    assert entry["plain_consequence"] != entry["detail"]
    assert entry["plain_consequence"] == BRIEF_PRE_IMPL.decision_consequence


def test_signed_off_terminal_branch_also_keeps_the_slots_separate() -> None:
    """volley_terminal's signed-off variant builds its copy on a separate path."""
    rendered = event_copy.render(
        _event(
            "volley_terminal",
            brief=BRIEF_PRE_MERGE,
            technical_metadata={"final_status": "signed_off", "rounds": 2},
        )
    )
    assert rendered is not None
    assert rendered.band == "ready"
    assert rendered.plain_consequence == BRIEF_PRE_MERGE.decision_consequence
    assert rendered.plain_consequence != rendered.detail


# --- (4) reversible tracks the brief -----------------------------------------


def test_reversible_tracks_the_brief_in_both_directions() -> None:
    """Not a hardcoded False: True and False both come from the brief."""
    assert BRIEF_PRE_IMPL.reversible is True
    assert BRIEF_PRE_MERGE.reversible is False

    reversible_entry = _entry(event_copy.render(_event("gate_hit", brief=BRIEF_PRE_IMPL)))
    irreversible_entry = _entry(
        event_copy.render(_event("gate_hit", brief=BRIEF_PRE_MERGE))
    )

    assert reversible_entry["reversible"] is True
    assert irreversible_entry["reversible"] is False


@pytest.mark.parametrize("kind", RENDERABLE_KINDS)
def test_reversible_is_carried_for_every_renderable_kind(kind: str) -> None:
    for brief in (BRIEF_PRE_IMPL, BRIEF_PRE_MERGE):
        rendered = event_copy.render(_event(kind, brief=brief))
        assert rendered is not None
        assert rendered.reversible is brief.reversible
        assert _entry(rendered)["reversible"] is brief.reversible


# --- technical_metadata stays untouched --------------------------------------


def test_technical_metadata_gains_no_brief_keys() -> None:
    """F004 step 5 — the brief lives in first-class fields, not the long tail."""
    with_brief = event_copy.render(_event("gate_hit", brief=BRIEF_PRE_IMPL))
    without_brief = event_copy.render(_event("gate_hit", brief=None))
    assert with_brief is not None and without_brief is not None
    assert dict(with_brief.technical_metadata) == dict(without_brief.technical_metadata)
