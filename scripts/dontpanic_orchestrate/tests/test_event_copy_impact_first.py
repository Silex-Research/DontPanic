"""Plan 2026-08-09-002 F005 — the renderable approval templates lead with impact.

Before this feature every approval prompt opened with the orchestrator's own
vocabulary — ``Approval needed on 2026-08-08-001`` — and the person being
asked to decide learned nothing about the change. F005 rewrites the
*renderable* approval-class copy so the declared product impact leads and the
plan label / gate / stage demote to a supporting reference line (USER.md:15).

Scope is deliberately narrow: only ``LIVE`` and ``DASHBOARD_ACTION`` kinds
reach :func:`event_copy.render` at all, and only their ``needs_action`` band
is an approval prompt. ``INBOX_ONLY`` / ``AUDIT_ONLY`` kinds never render and
are outside this feature.

The eight acceptance criteria, one section each:

  1. All 27 INBOX kinds still resolve to exactly one disposition, and the
     pre-existing totality tests still pass.
  2. Every kind that rendered before still renders.
  3. Every renderable ``needs_action`` variant carries a brief.
  4. Featureless / plan-level events get a distinct fallback, not a
     feature-shaped one.
  5. Rendered ``needs_action`` headlines carry the impact line and do not open
     with the plan identifier.
  6. A field-level diff against the pre-change render shows no previously
     present fact absent.
  7. Every exact command is byte-identical before and after.
  8. This file covers all seven and passes.

## The pre-change baseline

``fixtures/f005_prechange_render.json`` is a capture of ``render()`` over
every INBOX kind × every brief variant, taken against the tree as it stood
*before* this feature. Criteria 2, 6 and 7 diff against it, so it is evidence
rather than a convenience fixture.

Regenerating it is a destructive act — it would silently redefine "before" as
"after" and make those three criteria vacuous. It is written only by:

    git stash && python3 scripts/dontpanic_orchestrate/tests/\\
        test_event_copy_impact_first.py --write-baseline && git stash pop

and should not be re-run once F005 has landed.

``fixtures/f005_prechange_emitter_commands.json`` is the second half of that
evidence and exists because the first half has a blind spot. The capture above
renders events *this module* builds, whose ``technical_metadata`` deliberately
supplies more than production does — so a change made at an **emit site**
rather than in the templates moves the live command while the baseline stays
put. Audit i0 caught that happening. The second fixture is produced by
``tools/f005_emitter_command_probe.py`` driving the real emitters inside a
worktree of the pre-change tree; see that module for the command.
"""

from __future__ import annotations

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
    notify_event,
)

BASELINE_PATH = HERE.parent / "fixtures" / "f005_prechange_render.json"


def _emitter_command_probe() -> Any:
    """Load ``tools/f005_emitter_command_probe.py`` by path.

    By path rather than as a package import because the probe is deliberately
    standalone: the same file has to run inside a throwaway worktree of the
    pre-change tree, where ``tests/tools/`` is not a package and this module
    does not exist at all.
    """
    import importlib.util

    path = HERE.parent / "tools" / "f005_emitter_command_probe.py"
    spec = importlib.util.spec_from_file_location("f005_emitter_command_probe", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── fixture data ────────────────────────────────────────────────────────────

PLAN_ID = "2026-08-09-002-feat-decision-brief-at-gates"
PLAN_TITLE = (
    "Decision brief at gates — ask for approval in product terms, "
    "not orchestration terms"
)
FEATURE_ID = "F005"
FEATURE_DESCRIPTION = (
    "Rewrite the renderable approval-class templates so product outcome leads "
    "and orchestration identifiers demote to a supporting reference line"
)
IMPACT_SUMMARY = (
    "Operators reading an approval prompt see what the change does to the "
    "product before they see the plan id"
)

RENDERABLE_KINDS: tuple[str, ...] = tuple(
    sorted(
        kind
        for kind, disposition in event_copy.DISPOSITION_TABLE.items()
        if disposition
        in (event_copy.Disposition.LIVE, event_copy.Disposition.DASHBOARD_ACTION)
    )
)
ALL_KINDS: tuple[str, ...] = tuple(sorted(event_copy.INBOX_EVENT_KINDS))

# Long-tail values the per-kind templates interpolate. Pre-existing contract
# (D017): the emit site supplies these through technical_metadata, so a
# realistic event has to carry them here too. Values are >= 2 characters on
# purpose — the fact-diff below matches on substrings, and a one-character
# value would match everywhere and prove nothing.
KIND_METADATA: dict[str, dict[str, Any]] = {
    "gate_hit": {"gate": "pre_merge", "stage": "implement"},
    "gate_state_reconciliation_failed": {
        "contradiction_kind": "cleared_gate_still_pending",
        "gate": "pre_impl",
        "stage": "implement",
    },
    "verdict_mismatch": {
        "narrative_verdict": "blocked",
        "structured_status": "signed_off",
    },
    "volley_terminal": {"final_status": "stopped_no_progress", "rounds": 12},
    "calibration_required": {"agent": "claude", "window": "weekly"},
    "architecture_regen_failed": {"error_type": "SubprocessTimeout"},
    "no_progress_classification": {},
    "verdict_blocked_reconciled": {},
    "quota_warn": {"agent": "claude", "percent_weekly": 82, "threshold": 80},
    "unit_mismatch": {
        "agent": "claude",
        "window": "weekly",
        "cap_unit": "tokens",
        "observed_unit": "percent",
    },
    "config_required": {"cause": "no_cap_for_signal"},
    "volley_start": {"implementer": "claude", "auditor": "codex"},
}

# First-class NotifyEvent fields some kinds carry instead of technical_metadata.
KIND_EVENT_FIELDS: dict[str, dict[str, Any]] = {
    "breaker_tripped": {"breaker_kind": "iteration_cap"},
    "no_progress_classification": {
        "aggregate_class": "environmental_reproduction_failure",
        "blocking": False,
        "iteration_count": 12,
    },
    "verdict_blocked_reconciled": {"aggregate_class": "advisory_only"},
    "verdict_mismatch": {"iteration_count": 12},
    "volley_start": {"iteration_count": 12},
}


def _digest(text: str) -> str:
    return decision_brief.description_digest(text)


def _declared_feature() -> dict[str, Any]:
    return {
        "id": FEATURE_ID,
        "description": FEATURE_DESCRIPTION,
        "user_impact": {
            "audience": "operator",
            "summary": IMPACT_SUMMARY,
            "surfaces": ["cli"],
            "description_hash": _digest(FEATURE_DESCRIPTION),
        },
    }


def _undeclared_feature() -> dict[str, Any]:
    return {"id": FEATURE_ID, "description": FEATURE_DESCRIPTION}


def _stale_feature() -> dict[str, Any]:
    feature = _declared_feature()
    feature["user_impact"]["description_hash"] = _digest("an earlier description")
    return feature


BRIEF_DECLARED = decision_brief.build(
    plan_title=PLAN_TITLE,
    feature_id=FEATURE_ID,
    feature=_declared_feature(),
    stage="pre_merge",
    pending_gates=["pre_merge"],
)
BRIEF_UNDECLARED = decision_brief.build(
    plan_title=PLAN_TITLE,
    feature_id=FEATURE_ID,
    feature=_undeclared_feature(),
    stage="pre_impl",
    pending_gates=["pre_impl"],
)
BRIEF_STALE = decision_brief.build(
    plan_title=PLAN_TITLE,
    feature_id=FEATURE_ID,
    feature=_stale_feature(),
    stage="pre_impl",
    pending_gates=["pre_impl"],
)
BRIEF_PLAN_LEVEL = decision_brief.build(
    plan_title=PLAN_TITLE,
    feature_id=None,
    feature=None,
    stage="upfront",
    pending_gates=["upfront"],
)

# Every variant the baseline pins. "no_brief" is the pre-F003 shape that legacy
# emit sites still produce; the other three are what the supervisor's pause
# path now attaches.
VARIANTS: dict[str, decision_brief.DecisionBrief | None] = {
    "no_brief": None,
    "declared": BRIEF_DECLARED,
    "undeclared": BRIEF_UNDECLARED,
    "stale": BRIEF_STALE,
    "plan_level": BRIEF_PLAN_LEVEL,
}
VARIANT_NAMES: tuple[str, ...] = tuple(VARIANTS)
BRIEF_VARIANTS: tuple[str, ...] = tuple(v for v in VARIANTS if v != "no_brief")

# The RenderedEvent fields the baseline pins and the diff reads.
SNAPSHOT_FIELDS: tuple[str, ...] = (
    "band",
    "title",
    "detail",
    "exact_command",
    "evidence_uri",
    "what_changes",
    "user_impact",
    "affected_audience",
    "plain_consequence",
    "reversible",
)
# The subset that carries operator-visible prose — the haystack for the
# fact-diff in criterion 6.
TEXT_FIELDS: tuple[str, ...] = (
    "title",
    "detail",
    "exact_command",
    "evidence_uri",
    "what_changes",
    "user_impact",
    "affected_audience",
    "plain_consequence",
)


def build_event(kind: str, variant: str) -> notify_event.NotifyEvent:
    """A realistic NotifyEvent for ``kind`` under ``variant``."""
    return notify_event.NotifyEvent(
        kind=kind,
        severity=notify_event.SEVERITY_ACTION_REQUIRED,
        plan_id=PLAN_ID,
        feature_id=None if variant == "plan_level" else FEATURE_ID,
        body="synthetic pause",
        inbox_event=kind,
        subtype="pre_merge",
        evidence_uri="file:///plan/INBOX.md",
        technical_metadata=dict(KIND_METADATA.get(kind, {})),
        decision_brief=VARIANTS[variant],
        **KIND_EVENT_FIELDS.get(kind, {}),
    )


def snapshot(rendered: Any) -> dict[str, Any] | None:
    """Project a RenderedEvent into the pinned shape (``None`` passes through)."""
    if rendered is None:
        return None
    return {name: getattr(rendered, name) for name in SNAPSHOT_FIELDS}


def render_snapshot(kind: str, variant: str) -> dict[str, Any] | None:
    return snapshot(event_copy.render(build_event(kind, variant)))


def _text(entry: dict[str, Any] | None) -> str:
    if entry is None:
        return ""
    return "\n".join(str(entry[name]) for name in TEXT_FIELDS if entry.get(name))


# ── baseline ────────────────────────────────────────────────────────────────


def _capture_baseline() -> dict[str, Any]:
    return {
        "note": (
            "render() output captured before plan 2026-08-09-002 F005. Do not "
            "regenerate after F005 landed — criteria 2, 6 and 7 diff against it."
        ),
        "kinds": {
            kind: {variant: render_snapshot(kind, variant) for variant in VARIANTS}
            for kind in ALL_KINDS
        },
    }


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    assert BASELINE_PATH.is_file(), (
        f"pre-change baseline missing at {BASELINE_PATH} — see this module's "
        "docstring for how it was captured"
    )
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["kinds"]


def _baseline_needs_action_kinds(baseline: dict[str, Any]) -> list[str]:
    """Renderable kinds whose pre-change band was ``needs_action``.

    Read off the baseline rather than hardcoded, so a disposition or band
    change shows up as a diff instead of silently shrinking the matrix.
    """
    out = []
    for kind in RENDERABLE_KINDS:
        entry = baseline[kind]["declared"]
        if entry is not None and entry["band"] == "needs_action":
            out.append(kind)
    return out


# ── (1) disposition totality ────────────────────────────────────────────────


def test_all_27_inbox_kinds_resolve_to_exactly_one_disposition() -> None:
    assert set(event_copy.DISPOSITION_TABLE) == set(event_copy.INBOX_EVENT_KINDS)
    assert len(event_copy.DISPOSITION_TABLE) == 27
    for kind, disposition in event_copy.DISPOSITION_TABLE.items():
        assert isinstance(disposition, event_copy.Disposition), kind
        assert event_copy.disposition_for(kind) is disposition


def test_the_existing_totality_tests_still_pass() -> None:
    """F005 changes prose; the disposition table is untouched.

    Calling the pre-existing assertions directly (rather than trusting that
    another file happens to run) keeps this acceptance criterion honest even
    when this module is the only one executed.
    """
    from dontpanic_orchestrate.tests import test_event_copy_f001 as f001

    f001.test_disposition_table_covers_every_inbox_event_kind()
    f001.test_disposition_table_has_exactly_27_kinds()
    f001.test_disposition_table_values_are_disposition_enum_members()
    f001.test_disposition_table_no_duplicate_kinds()


# ── (2) render coverage is unchanged ────────────────────────────────────────


@pytest.mark.parametrize("kind", ALL_KINDS)
@pytest.mark.parametrize("variant", VARIANT_NAMES)
def test_every_kind_that_rendered_before_still_renders(
    kind: str, variant: str, baseline: dict[str, Any]
) -> None:
    before = baseline[kind][variant]
    after = render_snapshot(kind, variant)
    assert (after is None) == (before is None), (
        f"{kind}/{variant}: render() flipped between None and a RenderedEvent"
    )
    if before is not None:
        assert after is not None
        assert after["band"] == before["band"], f"{kind}/{variant} changed band"


def test_non_renderable_kinds_still_return_none() -> None:
    for kind in ALL_KINDS:
        if kind in RENDERABLE_KINDS:
            continue
        assert event_copy.render(build_event(kind, "declared")) is None, kind


# ── (3) every renderable needs_action variant carries a brief ───────────────


@pytest.mark.parametrize("variant", BRIEF_VARIANTS)
def test_every_renderable_needs_action_variant_carries_a_brief(
    variant: str, baseline: dict[str, Any]
) -> None:
    kinds = _baseline_needs_action_kinds(baseline)
    assert kinds, "baseline holds no renderable needs_action kinds"
    brief = VARIANTS[variant]
    assert brief is not None
    for kind in kinds:
        rendered = event_copy.render(build_event(kind, variant))
        assert rendered is not None, kind
        assert rendered.what_changes == brief.what_changes, kind
        assert rendered.plain_consequence == brief.decision_consequence, kind
        assert rendered.what_changes, kind
        assert rendered.plain_consequence, kind
        assert rendered.reversible is brief.reversible, kind


def test_both_volley_terminal_variants_carry_the_brief() -> None:
    """The signed-off branch builds its copy on a separate path in render()."""
    for final_status, expected_band in (
        ("signed_off", "ready"),
        ("stopped_no_progress", "needs_action"),
    ):
        event = build_event("volley_terminal", "declared")
        rendered = event_copy.render(
            notify_event.NotifyEvent(
                kind="volley_terminal",
                severity=notify_event.SEVERITY_ACTION_REQUIRED,
                plan_id=PLAN_ID,
                feature_id=FEATURE_ID,
                body=event.body,
                inbox_event="volley_terminal",
                subtype="pre_merge",
                evidence_uri=event.evidence_uri,
                technical_metadata={"final_status": final_status, "rounds": 12},
                decision_brief=BRIEF_DECLARED,
            )
        )
        assert rendered is not None
        assert rendered.band == expected_band
        assert rendered.what_changes == BRIEF_DECLARED.what_changes
        assert rendered.plain_consequence == BRIEF_DECLARED.decision_consequence


# ── (4) featureless / plan-level events get a distinct fallback ─────────────


def test_plan_level_events_get_a_plan_shaped_reference_not_a_feature_one(
    baseline: dict[str, Any],
) -> None:
    for kind in _baseline_needs_action_kinds(baseline):
        plan_level = event_copy.render(build_event(kind, "plan_level"))
        feature_scoped = event_copy.render(build_event(kind, "undeclared"))
        assert plan_level is not None and feature_scoped is not None

        plan_detail = plan_level.detail or ""
        feature_detail = feature_scoped.detail or ""

        assert event_copy.PLAN_LEVEL_REFERENCE_MARKER in plan_detail, kind
        assert event_copy.PLAN_LEVEL_REFERENCE_MARKER not in feature_detail, kind
        assert f"feature `{FEATURE_ID}`" in feature_detail, kind
        assert f"feature `{FEATURE_ID}`" not in plan_detail, kind
        assert plan_detail != feature_detail, kind


def test_the_reference_line_states_each_value_once(baseline: dict[str, Any]) -> None:
    """One value under two names reads as two facts and is only one.

    ``gate`` and ``stage`` both fall back to ``subtype``, so the quota kinds —
    which declare neither — would otherwise say ``gate `pre_merge`, stage
    `pre_merge```.
    """
    for kind in _baseline_needs_action_kinds(baseline):
        detail = (event_copy.render(build_event(kind, "declared")) or "").detail or ""
        reference = detail.split("Reference: ", 1)[-1]
        quoted = [part.split("`")[1] for part in reference.split(", ") if "`" in part]
        assert len(quoted) == len(set(quoted)), f"{kind}: {reference!r} repeats a value"


def test_a_plan_level_brief_describes_the_plan_not_a_feature() -> None:
    """No feature in scope means no feature-shaped claim is borrowed."""
    assert BRIEF_PLAN_LEVEL.what_changes == PLAN_TITLE
    assert BRIEF_PLAN_LEVEL.user_impact is None
    assert BRIEF_PLAN_LEVEL.affected_audience is None

    rendered = event_copy.render(build_event("gate_hit", "plan_level"))
    assert rendered is not None
    assert rendered.what_changes == PLAN_TITLE
    assert FEATURE_DESCRIPTION not in (rendered.detail or "")
    assert FEATURE_ID not in (rendered.detail or "")


# ── (5) headlines lead with impact, not with the plan identifier ────────────


def test_needs_action_headlines_carry_the_impact_line(
    baseline: dict[str, Any],
) -> None:
    kinds = _baseline_needs_action_kinds(baseline)
    assert kinds
    lead = IMPACT_SUMMARY
    for kind in kinds:
        rendered = event_copy.render(build_event(kind, "declared"))
        assert rendered is not None
        assert lead in rendered.title, (
            f"{kind}: headline does not carry the declared impact — {rendered.title!r}"
        )


def test_needs_action_headlines_do_not_open_with_the_plan_identifier(
    baseline: dict[str, Any],
) -> None:
    for kind in _baseline_needs_action_kinds(baseline):
        rendered = event_copy.render(build_event(kind, "declared"))
        assert rendered is not None
        assert not rendered.title.startswith(PLAN_ID), kind
        assert PLAN_ID not in rendered.title, kind
        # Demoted, not dropped.
        assert PLAN_ID in (rendered.detail or ""), kind


def test_the_headline_names_who_feels_the_change(baseline: dict[str, Any]) -> None:
    for kind in _baseline_needs_action_kinds(baseline):
        rendered = event_copy.render(build_event(kind, "declared"))
        assert rendered is not None
        assert rendered.title.startswith("Operators:"), (
            f"{kind}: headline does not lead with who feels it — {rendered.title!r}"
        )
        assert rendered.affected_audience == "operator"


def test_undeclared_and_stale_impact_fall_back_to_the_current_headline(
    baseline: dict[str, Any],
) -> None:
    """No declaration means no claim — the old headline shape stands.

    Stale declarations fall back too: presenting a summary written against
    different description text as if it were current is exactly what D005
    forbids. Marking it stale is F006's job, not a synthesized lead here.
    """
    for kind in _baseline_needs_action_kinds(baseline):
        for variant in ("undeclared", "stale", "plan_level"):
            rendered = event_copy.render(build_event(kind, variant))
            assert rendered is not None
            assert rendered.title == baseline[kind][variant]["title"], (
                f"{kind}/{variant}: fallback headline drifted"
            )
            assert IMPACT_SUMMARY not in rendered.title


def test_no_brief_events_render_byte_identically(baseline: dict[str, Any]) -> None:
    """Legacy emit sites that carry no brief keep their exact prior copy."""
    for kind in RENDERABLE_KINDS:
        before = baseline[kind]["no_brief"]
        after = render_snapshot(kind, "no_brief")
        assert after == before, f"{kind}: no-brief render changed"


# ── (6) field-level diff: no previously-present fact went missing ───────────


def _interpolated_facts(kind: str, variant: str) -> set[str]:
    """Every value the templates could have interpolated for this event.

    A "fact" is a datum, not prose: the values ``_gather_fields`` assembles
    from the event (plan id, gate, stage, breaker kind, verdicts, quota
    numbers...). Prose wording is what F005 is allowed to change; a value that
    reached the operator before and does not now is a dropped fact.
    """
    normalized, override = event_copy._normalize_inbox_event(kind)
    fields = event_copy._gather_fields(
        inbox_event=normalized,
        event=build_event(kind, variant),
        plan_meta=None,
        feature_meta=None,
    )
    if override is not None:
        fields["breaker_kind"] = override
    return {
        str(value)
        for value in fields.values()
        if value is not None and len(str(value)) >= 2 and str(value) != "-"
    }


@pytest.mark.parametrize("kind", RENDERABLE_KINDS)
@pytest.mark.parametrize("variant", VARIANT_NAMES)
def test_no_previously_present_fact_is_absent_after_the_rewrite(
    kind: str, variant: str, baseline: dict[str, Any]
) -> None:
    before = baseline[kind][variant]
    after = render_snapshot(kind, variant)
    if before is None:
        pytest.skip(f"{kind} did not render before")
    assert after is not None

    before_text = _text(before)
    after_text = _text(after)
    facts = _interpolated_facts(kind, variant)
    present_before = {fact for fact in facts if fact in before_text}
    assert present_before, f"{kind}/{variant}: no facts to diff — fixture is inert"

    missing = sorted(fact for fact in present_before if fact not in after_text)
    assert not missing, (
        f"{kind}/{variant}: facts dropped by the rewrite: {missing}\n"
        f"before: {before_text!r}\nafter: {after_text!r}"
    )


# The fixed factual clauses each renderable ``needs_action`` kind's body
# carried before the rewrite. ``_interpolated_facts`` above only diffs *values*
# (gate names, verdicts, quota numbers), so a rewrite that silently dropped a
# fixed clause — "Supervisor paused", "There is no canonical reconcile
# subcommand" — would pass it. Prose may be reordered or relocated to the
# headline; a factual clause may not vanish.
#
# ``test_the_clause_inventory_is_read_off_the_baseline`` below pins every entry
# against the pre-change fixture, so this table cannot drift into asserting
# something the old copy never said.
BASELINE_CLAUSES: dict[str, tuple[str, ...]] = {
    "gate_hit": (
        "Supervisor paused",
        "Operator must approve before dispatch continues.",
    ),
    "gate_state_reconciliation_failed": (
        "Persisted gate state contradicts plan declaration",
        "`cleared_gate_still_pending`",
        "There is no canonical reconcile subcommand; inspect the persisted "
        "state file and INBOX entry before re-dispatching.",
    ),
    "verdict_mismatch": (
        "Auditor narrative verdict (`blocked`) disagrees with structured "
        "`audit_status` (`signed_off`) on iteration 12.",
        "No automated re-audit command; open the audit envelope and reconcile "
        "manually.",
    ),
    "volley_terminal": (
        "Volley terminated after 12 round(s) with status `stopped_no_progress`.",
        "Review the audit envelope before deciding next step.",
    ),
    "breaker_tripped": (
        "Circuit breaker `iteration_cap` tripped.",
        "Operator clearance required before dispatch continues.",
    ),
    "breaker:patch_incomplete": (
        "Circuit breaker `patch_incomplete` tripped.",
        "Operator clearance required before dispatch continues.",
    ),
    "calibration_required": (
        "Calibration sample required for `claude.weekly` so the breaker can "
        "convert local proxy units into percent-of-plan.",
    ),
    "no_progress_classification": (
        "Auditor verdict taxonomy `environmental_reproduction_failure` "
        "(blocking=false); recommended: review the audit envelope before "
        "re-dispatch.",
    ),
    "verdict_blocked_reconciled": (
        "Auditor said `blocked` but every finding classified as advisory "
        "(`advisory_only`); supervisor promoted the terminal to "
        "`stopped_environmental_blocker`.",
    ),
    "environmental_blocker_short_circuit": (
        "Every auditor finding classified as "
        "`environmental_reproduction_failure`; volley short-circuited without "
        "another paid implementer round.",
    ),
    "unit_mismatch": (
        "Quota cap unit drift for `claude.weekly`: cap.unit=`tokens` ≠ "
        "observed=`percent`.",
        "Edit `~/.jarvis/quota_caps.json` so cap.unit matches what "
        "quota_check.py emits.",
    ),
    "config_required": (
        "Quota config required (`no_cap_for_signal`).",
        "Run `python -m dontpanic_orchestrate quota-caps init` to seed "
        "defaults, hand-edit `~/.jarvis/quota_caps.json` for "
        "`no_cap_for_signal`, or re-run `scripts/quota_check.py` for "
        "`missing_vendor_block`.",
    ),
}


def test_the_clause_inventory_is_read_off_the_baseline(
    baseline: dict[str, Any],
) -> None:
    """The inventory covers every rewritten kind and quotes the old copy.

    Without this guard the clause test could pass by asserting clauses the
    baseline never carried, or by quietly omitting the kind whose clause the
    rewrite dropped.
    """
    assert set(BASELINE_CLAUSES) == set(_baseline_needs_action_kinds(baseline)), (
        "clause inventory and the baseline's needs_action kinds disagree"
    )
    for kind, clauses in BASELINE_CLAUSES.items():
        assert clauses, f"{kind}: inventory entry is empty"
        for variant in VARIANT_NAMES:
            before = baseline[kind][variant]
            if before is None:
                continue
            for clause in clauses:
                assert clause in (before["detail"] or ""), (
                    f"{kind}/{variant}: inventory quotes a clause the baseline "
                    f"does not carry: {clause!r}"
                )


@pytest.mark.parametrize("kind", tuple(sorted(BASELINE_CLAUSES)))
@pytest.mark.parametrize("variant", VARIANT_NAMES)
def test_no_baseline_factual_clause_is_dropped(
    kind: str, variant: str, baseline: dict[str, Any]
) -> None:
    """Every fixed clause the old body carried still reaches the operator.

    Matched against the whole rendered text rather than ``detail`` alone: a
    clause that moved into the headline was relocated, which is what this
    feature is for, and only a clause that appears nowhere is a dropped fact.
    """
    before = baseline[kind][variant]
    if before is None:
        pytest.skip(f"{kind} did not render before")
    after = render_snapshot(kind, variant)
    assert after is not None
    after_text = _text(after)
    missing = [c for c in BASELINE_CLAUSES[kind] if c not in after_text]
    assert not missing, (
        f"{kind}/{variant}: factual clauses dropped by the rewrite: {missing}\n"
        f"after: {after_text!r}"
    )


@pytest.mark.parametrize("kind", RENDERABLE_KINDS)
@pytest.mark.parametrize("variant", VARIANT_NAMES)
def test_the_copy_map_label_survives_the_rewrite(
    kind: str, variant: str, baseline: dict[str, Any]
) -> None:
    """The IA vocabulary token ("Approval needed", "Blocked work", ...) is
    itself a fact about what kind of attention this needs, so demoting the
    plan id must not take it with it."""
    before = baseline[kind][variant]
    if before is None:
        pytest.skip(f"{kind} did not render before")
    labels = (
        "Approval needed",
        "Blocked work",
        "Setup drift",
        "Budget guardrail",
        "System warning",
        "Active AI work",
        "AI work finished",
    )
    before_labels = [label for label in labels if label in before["title"]]
    assert before_labels, f"{kind}: baseline title carries no IA label"
    after = render_snapshot(kind, variant)
    assert after is not None
    for label in before_labels:
        assert label in after["title"], f"{kind}/{variant}: lost label {label!r}"


# ── (7) exact commands are byte-identical ───────────────────────────────────


@pytest.mark.parametrize("kind", ALL_KINDS)
@pytest.mark.parametrize("variant", VARIANT_NAMES)
def test_every_exact_command_is_byte_identical(
    kind: str, variant: str, baseline: dict[str, Any]
) -> None:
    before = baseline[kind][variant]
    after = render_snapshot(kind, variant)
    if before is None:
        assert after is None
        return
    assert after is not None
    assert after["exact_command"] == before["exact_command"], (
        f"{kind}/{variant}: exact_command changed — F005 is a prose-only feature"
    )


def test_the_action_templates_are_untouched() -> None:
    """The honest-commands rule (D008) is unchanged: the impact-first copy
    reuses each row's own ``action`` template rather than authoring a new one."""
    for kind in event_copy.TRANSLATION_TABLE:
        impact = event_copy.IMPACT_FIRST_TABLE.get(kind)
        if impact is None:
            continue
        assert not hasattr(impact, "action"), (
            f"{kind}: the impact-first overlay must not carry its own command"
        )
    # Kinds whose canonical remediation is None stay None.
    for kind in ("gate_state_reconciliation_failed", "verdict_mismatch", "unit_mismatch"):
        rendered = event_copy.render(build_event(kind, "declared"))
        assert rendered is not None
        assert rendered.exact_command is None, kind


def test_the_impact_first_overlay_only_covers_renderable_needs_action_kinds(
    baseline: dict[str, Any],
) -> None:
    covered = set(event_copy.IMPACT_FIRST_TABLE)
    assert covered <= set(RENDERABLE_KINDS), (
        "overlay covers a kind that never reaches render()"
    )
    expected = set(_baseline_needs_action_kinds(baseline))
    # breaker:patch_incomplete normalizes onto breaker_tripped (D009) and so
    # has no overlay row of its own.
    expected.discard("breaker:patch_incomplete")
    assert covered == expected


# ── (9) the production path ─────────────────────────────────────────────────
#
# Everything above renders events this module builds itself, which proves the
# overlay is correct and proves nothing about whether it ever runs. The i1
# audit found exactly that gap: `render()` requires a brief, and only the
# gate-pause emitter attached one, so nine of the ten renderable needs_action
# kinds kept plan-first copy in production while the suite stayed green.
#
# These tests read the emitters instead of the templates.

#: The ``NotifyEvent.subtype`` each renderable ``needs_action`` kind's real
#: emit site sets, read off supervisor.py. Most set none. Only the gate-pause
#: emitter puts the *stage* there; ``verdict_mismatch`` puts the auditor's
#: structured status and ``gate_state_reconciliation_failed`` the contradiction
#: kind, neither of which is a gate or a stage.
#:
#: ``gate_hit`` is the stage — ``_emit_gate_paused_discord(stage=...)`` — and
#: naming it ``pre_merge`` here would model a pause whose stage and gate happen
#: to coincide, which is the one shape where dropping the gate is invisible.
#: The pair below is deliberately distinct for that reason: the i2 audit found
#: the pause dropping its gate entirely, and a coincident pair would have hidden
#: it.
PRODUCTION_SUBTYPE: dict[str, str | None] = {
    "gate_hit": "implement",
    "gate_state_reconciliation_failed": "cleared_gate_still_pending",
    "verdict_mismatch": "signed_off",
    "volley_terminal": None,
    "breaker_tripped": None,
    "breaker:patch_incomplete": None,
    "calibration_required": None,
    "no_progress_classification": None,
    "verdict_blocked_reconciled": None,
    "environmental_blocker_short_circuit": None,
    "unit_mismatch": None,
    "config_required": None,
}

#: The ``technical_metadata`` each real emit site passes. ``KIND_METADATA``
#: above is the synthetic long-tail used for the fact-diff and deliberately
#: supplies more than production does; this table must not — it is the shape
#: the emitters actually produce.
#:
#: ``gate_hit`` publishes the gate under ``pending_gates``, never under
#: ``gate``. The distinction is load-bearing rather than cosmetic: the
#: reference line reads ``pending_gates`` first, so the gate is named; the
#: ``{gate}`` format field is derived from ``gate`` / ``subtype`` only, so the
#: approval command is untouched. Writing ``gate`` here instead would move the
#: live command and break acceptance 7 —
#: ``test_the_live_emitters_render_the_same_commands_as_before`` is what
#: catches that, and this table is what keeps the two honest with each other.
PRODUCTION_METADATA: dict[str, dict[str, Any]] = {
    "gate_hit": {"pending_gates": "pre_merge", "stage": "implement"},
    "gate_state_reconciliation_failed": {
        "gate": "pre_impl",
        "stage": "implement",
        "persisted_state_path": "/plan/gate-state.json",
    },
    "verdict_mismatch": {
        "narrative_verdict": "blocked",
        "structured_status": "signed_off",
        "audit_path": "/plan/audit/a.json",
        "iteration": 12,
    },
    "volley_terminal": {"final_status": "stopped_no_progress", "rounds": 12},
    "breaker_tripped": {},
    "breaker:patch_incomplete": {},
    "calibration_required": {"agent": "claude", "window": "weekly"},
    "no_progress_classification": {},
    "verdict_blocked_reconciled": {"original_verdict": "blocked"},
    "environmental_blocker_short_circuit": {},
    "unit_mismatch": {
        "agent": "claude",
        "window": "weekly",
        "cap_unit": "tokens",
        "observed_unit": "percent",
    },
    "config_required": {"cause": "no_cap_for_signal"},
}

#: The first-class ``NotifyEvent`` fields each real emit site sets.
PRODUCTION_EVENT_FIELDS: dict[str, dict[str, Any]] = {
    "breaker_tripped": {"breaker_kind": "iteration_cap"},
    "breaker:patch_incomplete": {"breaker_kind": "patch_incomplete"},
    "volley_terminal": {"iteration_count": 12},
    "verdict_mismatch": {"iteration_count": 12},
    "no_progress_classification": {
        "aggregate_class": "environmental_reproduction_failure",
        "blocking": False,
    },
    "verdict_blocked_reconciled": {
        "aggregate_class": "advisory_only",
        "blocking": False,
        "iteration_count": 12,
    },
    "environmental_blocker_short_circuit": {
        "aggregate_class": "environmental_reproduction_failure",
        "blocking": False,
        "iteration_count": 12,
    },
}


class _FakePlan:
    def __init__(self, title: str) -> None:
        self.title = title


class _FakeLoadedPlan:
    """The narrow slice of ``plan_loader.LoadedPlan`` a brief reads.

    ``decision_brief`` is typed loosely on purpose (its docstring says so), so
    a stub is the honest test double here: loading a real plan would exercise
    the schema stack, not the emitters.
    """

    def __init__(self) -> None:
        self.plan_id = PLAN_ID
        self.plan = _FakePlan(PLAN_TITLE)
        self.plan_dir = HERE.parent

    def feature(self, feature_id: str) -> dict[str, Any]:
        if feature_id != FEATURE_ID:
            raise KeyError(feature_id)
        return _declared_feature()


def _needs_action_emitter_kinds(baseline: dict[str, Any]) -> set[str]:
    """The INBOX ``event=`` values a production emitter must attach a brief to.

    ``breaker:patch_incomplete`` is dropped: D009 normalizes it onto
    ``breaker_tripped`` at render, and no emit site writes the colon form.
    """
    kinds = set(_baseline_needs_action_kinds(baseline))
    kinds.discard("breaker:patch_incomplete")
    return kinds


def _notify_event_calls(module_path: Path) -> list[tuple[int, str, set[str]]]:
    """(line, inbox_event, kwarg names) for every ``NotifyEvent(...)`` built."""
    import ast

    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    out: list[tuple[int, str, set[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "NotifyEvent":
            continue
        names = {kw.arg for kw in node.keywords if kw.arg}
        inbox_event = ""
        for kw in node.keywords:
            if kw.arg == "inbox_event" and isinstance(kw.value, ast.Constant):
                inbox_event = str(kw.value.value)
        out.append((node.lineno, inbox_event, names))
    return out


def test_every_renderable_needs_action_emitter_attaches_a_brief(
    baseline: dict[str, Any],
) -> None:
    """No renderable approval prompt may be dispatched without a brief.

    Asserted against the emitters rather than against ``render()``: this is
    the property that was false in i1, and it is invisible from any test that
    constructs its own event.
    """
    supervisor_path = HERE.parents[1] / "supervisor.py"
    assert supervisor_path.is_file()
    wanted = _needs_action_emitter_kinds(baseline)
    seen: set[str] = set()
    missing: list[str] = []
    for lineno, inbox_event, kwargs in _notify_event_calls(supervisor_path):
        if inbox_event not in wanted:
            continue
        seen.add(inbox_event)
        if "decision_brief" not in kwargs:
            missing.append(f"supervisor.py:{lineno} ({inbox_event})")
    assert not missing, f"emit sites dispatch without a brief: {missing}"
    assert seen == wanted, f"no emit site found for: {sorted(wanted - seen)}"


def test_the_supervisor_emits_a_brief_that_renders_impact_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive three real emitters and render what they actually dispatch."""
    from dontpanic_orchestrate import (
        circuit_breakers,
        gate_pause,
        inbox,
        notify,
        supervisor,
    )

    captured: list[Any] = []
    monkeypatch.setattr(
        notify_event, "dispatch_event", lambda ev, **kw: captured.append(ev)
    )
    monkeypatch.setattr(
        supervisor.notify_event, "dispatch_event", lambda ev, **kw: captured.append(ev)
    )
    monkeypatch.setattr(inbox, "append_event", lambda *a, **k: None)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: True)
    monkeypatch.setattr(circuit_breakers, "record_global_hit", lambda *a, **k: None)
    monkeypatch.setattr(gate_pause, "add_breaker", lambda *a, **k: None)

    loaded = _FakeLoadedPlan()
    supervisor._trip_breaker(
        loaded.plan_dir,
        PLAN_ID,
        FEATURE_ID,
        circuit_breakers.BreakerKind.ITERATION_CAP,
        "cap reached",
        loaded=loaded,
    )
    assert len(captured) == 1
    event = captured[0]
    assert event.decision_brief is not None, "emit site dispatched without a brief"

    rendered = event_copy.render(event)
    assert rendered is not None
    assert rendered.band == "needs_action"
    assert rendered.title.startswith(f"Operators: {IMPACT_SUMMARY}"), rendered.title
    assert PLAN_ID not in rendered.title
    assert PLAN_ID in (rendered.detail or "")
    assert rendered.plain_consequence == event.decision_brief.decision_consequence
    # The gate the operator would clear is named, and it is a real gate.
    assert "breaker:iteration_cap" in rendered.plain_consequence


def _emit_live_pause(
    monkeypatch: pytest.MonkeyPatch, *, pending_gates: list[str], stage: str
) -> Any:
    """Drive the real pause emitter and return the event it dispatched."""
    from dontpanic_orchestrate import notify, supervisor

    captured: list[Any] = []
    monkeypatch.setattr(
        supervisor.notify_event, "dispatch_event", lambda ev, **kw: captured.append(ev)
    )
    monkeypatch.setattr(notify, "notify", lambda *a, **k: True)

    loaded = _FakeLoadedPlan()
    supervisor._emit_gate_paused_discord(
        loaded.plan_dir,
        PLAN_ID,
        FEATURE_ID,
        pending_gates=pending_gates,
        stage=stage,
        loaded=loaded,
    )
    assert len(captured) == 1
    return captured[0]


def test_the_live_gate_pause_relocates_both_its_gate_and_its_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Demotion means relocated, never dropped — from the emitter, not a stub.

    Driven with a gate and a stage that differ, so the assertions can tell the
    two apart. Audit i2 found this exact case dropping the gate: the emitter
    published only ``subtype`` (the stage), so the operator was asked to clear
    a gate the rendered event never named. The emitter now publishes the
    pending gate too, and both facts land in the reference line under their own
    names.

    The approval command stays byte-identical through that change, which is the
    whole reason the gate is published as ``pending_gates`` rather than
    ``gate``. It still names the *stage*, which is a real defect — plan
    2026-08-10-001 F001/F002 owns changing it, because changing it here would
    violate acceptance 7 (audit i0 finding 1).
    """
    event = _emit_live_pause(monkeypatch, pending_gates=["pre_merge"], stage="implement")
    assert event.decision_brief is not None

    rendered = event_copy.render(event)
    assert rendered is not None
    detail = rendered.detail or ""
    reference = detail.split("Reference: ", 1)[-1]
    assert "gate `pre_merge`" in reference, reference
    assert "stage `implement`" in reference, reference
    # The subtype alias in ``_gather_fields`` would have reported the stage
    # under the gate's name. The reference line does not inherit that alias.
    assert "gate `implement`" not in reference, reference
    # Relocated, not duplicated: the headline leads with impact and the body no
    # longer names the stage inline.
    assert rendered.title.startswith(f"Operators: {IMPACT_SUMMARY}"), rendered.title
    assert PLAN_ID not in rendered.title
    assert "pre_merge" not in rendered.title
    before_reference = detail.split("Reference: ", 1)[0]
    assert "implement" not in before_reference, before_reference
    # Plan 2026-08-10-001 F001: the command now names the pending gate, not
    # the stage. F005 left this unmoved on purpose; 010 is the change.
    assert rendered.exact_command == f"dontpanic approve {PLAN_ID} pre_merge"


def test_a_multi_gate_reference_names_every_pending_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two unmet gates are two facts; neither may be swallowed by the other.

    A pause can block on more than one gate, and the emitter joins them into a
    single value. Printing that inside one pair of backticks would name a gate
    called ``pre_impl, pre_merge``, which does not exist. Driven through the
    real emitter so the joined form under test is the one production builds.
    """
    event = _emit_live_pause(
        monkeypatch, pending_gates=["pre_impl", "pre_merge"], stage="implement"
    )
    rendered = event_copy.render(event)
    assert rendered is not None
    reference = (rendered.detail or "").split("Reference: ", 1)[-1]
    assert "gates `pre_impl`, `pre_merge`" in reference, reference
    assert "stage `implement`" in reference, reference
    # Plan 2026-08-10-001 F001: a two-gate pause has no single runnable
    # approve command (a comma-joined token is not a gate).
    assert rendered.exact_command is None


def test_a_pause_with_no_unmet_gate_names_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty gate list is published as nothing, not as an empty gate name.

    The emitter omits absent values rather than passing ``""`` through, so the
    reference line stays quiet instead of rendering an empty pair of backticks.
    """
    event = _emit_live_pause(monkeypatch, pending_gates=[], stage="implement")
    assert "pending_gates" not in dict(event.technical_metadata or {})
    rendered = event_copy.render(event)
    assert rendered is not None
    reference = (rendered.detail or "").split("Reference: ", 1)[-1]
    assert "gate `" not in reference, reference
    assert "gates `" not in reference, reference
    assert "stage `implement`" in reference, reference


def test_the_live_emitters_render_the_same_commands_as_before() -> None:
    """Acceptance 7, asserted against the **emitters** rather than the templates.

    ``test_every_exact_command_is_byte_identical`` above diffs synthetic events
    against ``f005_prechange_render.json``. Those events hand the renderer more
    ``technical_metadata`` than production does, so a change made at an emit
    site moves the live command without moving that baseline. Audit i0 finding
    2 caught exactly that: 549 tests stayed green while the real approval
    command changed from ``dontpanic approve <plan> implement`` to
    ``dontpanic approve <plan> pre_merge``.

    ``f005_prechange_emitter_commands.json`` was captured by running the probe
    below inside a worktree of the pre-change tree, so this is a genuine
    before/after comparison of the payloads the emitters really build.
    """
    fixture = HERE.parent / "fixtures" / "f005_prechange_emitter_commands.json"
    before = json.loads(fixture.read_text(encoding="utf-8"))["probes"]
    after = _emitter_command_probe().capture()
    assert before, "the pre-change emitter capture is empty"
    # Plan 2026-08-10-001 F001 deliberately moves the three gate-pause
    # commands (they used to name the stage). Every other emitter stays
    # byte-identical to the F005 capture.
    expected = dict(before)
    expected["gate_pause.default_stage"] = {
        "exact_command": f"dontpanic approve {PLAN_ID} pre_merge",
        "inbox_event": "gate_hit",
    }
    expected["gate_pause.single_gate"] = {
        "exact_command": f"dontpanic approve {PLAN_ID} pre_merge",
        "inbox_event": "gate_hit",
    }
    expected["gate_pause.two_gates"] = {
        "exact_command": None,
        "inbox_event": "gate_hit",
    }
    assert after == expected, (
        "a live emitter's exact_command changed outside 010's gate-pause set.\n"
        f"before: {json.dumps(before, indent=2, sort_keys=True)}\n"
        f"after:  {json.dumps(after, indent=2, sort_keys=True)}"
    )


def test_a_hard_stop_brief_promises_no_clearance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The global breaker offers no gate; the consequence may not invent one."""
    from dontpanic_orchestrate import (
        circuit_breakers,
        gate_pause,
        inbox,
        notify,
        supervisor,
    )

    captured: list[Any] = []
    monkeypatch.setattr(
        supervisor.notify_event, "dispatch_event", lambda ev, **kw: captured.append(ev)
    )
    monkeypatch.setattr(inbox, "append_event", lambda *a, **k: None)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: True)
    monkeypatch.setattr(circuit_breakers, "record_global_hit", lambda *a, **k: None)
    monkeypatch.setattr(gate_pause, "add_breaker", lambda *a, **k: None)

    loaded = _FakeLoadedPlan()
    supervisor._trip_breaker(
        loaded.plan_dir,
        PLAN_ID,
        FEATURE_ID,
        circuit_breakers.BreakerKind.GLOBAL_CIRCUIT_BREAKER,
        "3 hits in 24h",
        loaded=loaded,
    )
    brief = captured[0].decision_brief
    assert brief is not None
    assert "No operator clearance is available" in brief.decision_consequence
    assert "Clearing" not in brief.decision_consequence
    assert brief.reversible is False


def test_an_emitter_without_a_loaded_plan_still_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Notifications are advisory: a missing LoadedPlan degrades, never raises.

    The brief is then ``None`` and the renderer keeps the pre-existing copy —
    honest, because a brief built from nothing would report the plan id as
    "what changes".
    """
    from dontpanic_orchestrate import (
        circuit_breakers,
        gate_pause,
        inbox,
        notify,
        supervisor,
    )

    captured: list[Any] = []
    monkeypatch.setattr(
        supervisor.notify_event, "dispatch_event", lambda ev, **kw: captured.append(ev)
    )
    monkeypatch.setattr(inbox, "append_event", lambda *a, **k: None)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: True)
    monkeypatch.setattr(circuit_breakers, "record_global_hit", lambda *a, **k: None)
    monkeypatch.setattr(gate_pause, "add_breaker", lambda *a, **k: None)

    supervisor._trip_breaker(
        HERE.parent,
        PLAN_ID,
        FEATURE_ID,
        circuit_breakers.BreakerKind.ITERATION_CAP,
        "cap reached",
    )
    assert len(captured) == 1
    assert captured[0].decision_brief is None
    rendered = event_copy.render(captured[0])
    assert rendered is not None
    assert rendered.title.startswith("Blocked work on ")


def _production_event(kind: str, brief: Any) -> notify_event.NotifyEvent:
    """An event shaped the way ``kind``'s real emit site shapes it."""
    return notify_event.NotifyEvent(
        kind=kind,
        severity=notify_event.SEVERITY_ACTION_REQUIRED,
        plan_id=PLAN_ID,
        feature_id=FEATURE_ID,
        body="",
        inbox_event=kind,
        subtype=PRODUCTION_SUBTYPE[kind],
        technical_metadata=dict(PRODUCTION_METADATA[kind]),
        decision_brief=brief,
        **PRODUCTION_EVENT_FIELDS.get(kind, {}),
    )


@pytest.mark.parametrize("kind", tuple(sorted(PRODUCTION_SUBTYPE)))
def test_a_non_gate_subtype_never_becomes_a_gate_reference(kind: str) -> None:
    """``subtype`` is a per-kind discriminator, not a gate name.

    ``_gather_fields`` aliases it into ``{gate}`` / ``{stage}`` so a template
    referencing either never KeyErrors. The reference line must not inherit
    that alias: the real ``verdict_mismatch`` subtype is the auditor's
    structured status, and rendering ``gate `signed_off`` states an
    orchestration fact the event never carried.
    """
    subtype = PRODUCTION_SUBTYPE[kind]
    rendered = event_copy.render(_production_event(kind, BRIEF_DECLARED))
    assert rendered is not None
    detail = rendered.detail or ""
    reference = detail.split("Reference: ", 1)[-1] if "Reference: " in detail else ""
    if subtype is None:
        assert "gate `" not in reference, reference
        assert "stage `" not in reference, reference
        return
    declared = event_copy._SUBTYPE_IS_STAGE
    if kind in declared:
        # The pause emitter documents subtype as the stage — named as one.
        assert f"stage `{subtype}`" in reference, reference
        assert f"gate `{subtype}`" not in reference, reference
    else:
        assert subtype not in reference, (
            f"{kind}: subtype {subtype!r} leaked into the reference line as an "
            f"orchestration fact — {reference!r}"
        )


@pytest.mark.parametrize("kind", tuple(sorted(PRODUCTION_SUBTYPE)))
def test_production_shaped_events_still_lead_with_impact(kind: str) -> None:
    """The overlay fires on the emitters' own event shape, not just ours."""
    rendered = event_copy.render(_production_event(kind, BRIEF_DECLARED))
    assert rendered is not None
    if rendered.band != "needs_action":
        pytest.skip(f"{kind} does not resolve to needs_action on this shape")
    assert rendered.title.startswith(f"Operators: {IMPACT_SUMMARY}"), rendered.title
    assert PLAN_ID not in rendered.title
    assert f"plan `{PLAN_ID}" in (rendered.detail or "")


# ── baseline capture (see the module docstring — destructive) ───────────────


def main(argv: list[str]) -> int:
    if "--write-baseline" not in argv:
        print(__doc__)
        return 2
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(_capture_baseline(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {BASELINE_PATH}")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main(sys.argv[1:]))
