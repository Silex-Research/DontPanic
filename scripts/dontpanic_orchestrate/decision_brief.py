"""Plan 2026-08-09-002 F003 — the DecisionBrief snapshot taken at pause time.

Why a snapshot rather than a render-time lookup
-----------------------------------------------
``event_copy.render()`` accepts ``plan_meta`` / ``feature_meta``, but the
production dispatcher in ``notify_event.dispatch_event`` calls
``render(event)`` and supplies neither — see ``notify_event.py`` where the
only argument is the event. Any feature that reads those parameters alone is
dead code on the live path, and every real gate would keep reporting
"impact undeclared".

So the brief is built once, at the supervisor's pause-emission site where the
``LoadedPlan`` and the feature record are genuinely in scope, and carried on
the ``NotifyEvent`` as an immutable snapshot. One snapshot then serves every
sink (CLI, INBOX, notify, dashboard) instead of each re-deriving at a
different moment against a plan file that may have moved underneath them.

What the brief carries (plan.md § Proposed Approach)
----------------------------------------------------
=====================  ==========================================
Element                Field
=====================  ==========================================
What changes           ``what_changes``
Who feels it           ``user_impact`` + ``affected_audience`` (+ ``surfaces``)
What approving does    ``decision_consequence`` + ``reversible``
=====================  ==========================================

Plus ``status``, which states how much the brief itself can be trusted:
``declared`` / ``possibly_stale`` / ``undeclared``.

This module stops at the snapshot. It never synthesizes an impact claim —
when F001's ``user_impact`` block is absent the impact fields stay ``None``
and ``status`` is ``undeclared``; writing the honest fallback copy for that
case is F006's job, and reading the brief in a sink is F006 / F007 / F008.
Everything here is a pure function of already-loaded data: no IO, no model
calls, no interpolation of generated prose.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class BriefStatus(Enum):
    """How far the brief's impact claim can be trusted.

    ``DECLARED``       — F001's ``user_impact`` block is present and its
                         recorded digest matches the feature description as
                         it reads now (or the declaration is ``audience:
                         none``, which carries no claim that can go stale).
    ``POSSIBLY_STALE`` — the block is present but its ``description_hash``
                         was taken against different description text. D005:
                         say so rather than present old copy as current.
    ``UNDECLARED``     — no block. Nothing is known, and nothing is invented.
    """

    DECLARED = "declared"
    POSSIBLY_STALE = "possibly_stale"
    UNDECLARED = "undeclared"


@dataclass(frozen=True)
class DecisionBrief:
    """Immutable, equality-comparable snapshot of what the operator is deciding.

    Frozen because every sink reads the same instance and none of them owns
    it; equality-comparable because F007's parity test compares the brief
    rendered on one surface against the brief rendered on another field by
    field. ``surfaces`` is a tuple rather than a list for the same reason —
    a mutable member would make the "immutable snapshot" claim untrue.
    """

    #: Element one. The feature description; the plan title on plan-level
    #: pauses where no feature record is in scope.
    what_changes: str
    #: Element two. F001's declared ``user_impact.summary``. ``None`` when
    #: undeclared, or when the declaration is ``audience: none`` (which
    #: asserts no external consequence and so carries no summary).
    user_impact: str | None
    #: Element two. F001's declared ``user_impact.audience``.
    affected_audience: str | None
    #: Element three. What clearing this gate sets in motion.
    decision_consequence: str
    #: Element three. Whether what approving sets in motion can be undone
    #: without a second operator decision.
    reversible: bool
    #: Trust level of the impact claim above.
    status: BriefStatus
    #: Element two. F001's declared ``user_impact.surfaces``, normalized to
    #: their string values. Empty when undeclared or ``audience: none``.
    surfaces: tuple[str, ...] = ()


# --- staleness ---------------------------------------------------------------


def description_digest(description: str | None) -> str:
    """SHA-256 hex digest of a feature description, matching F001's
    ``user_impact.description_hash`` construction (UTF-8, no normalization).

    Shared so the writer of a declaration and the reader of one can never
    disagree about what was hashed.
    """
    return hashlib.sha256((description or "").encode("utf-8")).hexdigest()


def _enum_value(raw: Any) -> Any:
    """Accept either a Pydantic enum member or a plain string.

    ``LoadedPlan.feature()`` returns ``model_dump()`` output, which keeps
    enums as enum members; a hand-built dict in a test carries strings.
    Both are legitimate inputs here.
    """
    return raw.value if hasattr(raw, "value") else raw


def _impact_block(feature: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not feature:
        return None
    block = feature.get("user_impact")
    return block if isinstance(block, Mapping) and block else None


def classify_status(feature: Mapping[str, Any] | None) -> BriefStatus:
    """Compare the digest F001 recorded against the description as it reads now.

    An absent ``description_hash`` is only legal under ``audience: none``
    (the schema requires the digest for every other audience), and that
    declaration carries no claim that can go stale — so it reads as
    ``DECLARED`` rather than inventing a fourth "digest unknown" state.
    """
    block = _impact_block(feature)
    if block is None:
        return BriefStatus.UNDECLARED
    recorded = block.get("description_hash")
    if not recorded:
        return BriefStatus.DECLARED
    current = description_digest((feature or {}).get("description"))
    return BriefStatus.DECLARED if recorded == current else BriefStatus.POSSIBLY_STALE


# --- what approving does -----------------------------------------------------

# Deterministic templates keyed by the pause stage the supervisor names at
# its emit site. No generated prose reaches this text — D002 keeps the
# render boundary strictly non-generative, and that starts here.
_STAGE_CONSEQUENCE: dict[str, str] = {
    "general": (
        "Clearing {gates} starts the single-agent run on {subject}. "
        "The resulting patch is still reviewed before it merges."
    ),
    "upfront": (
        "Clearing {gates} starts the volley on {subject}. "
        "The resulting patch is still reviewed before it merges."
    ),
    "pre_impl": (
        "Clearing {gates} lets the implementer run on {subject}. "
        "The resulting patch is still reviewed before it merges."
    ),
    "pre_merge": (
        "Clearing {gates} writes the success signoff for {subject} and "
        "releases it to merge. This is the last stop before the change lands."
    ),
}

_UNKNOWN_STAGE_CONSEQUENCE = (
    "Clearing {gates} lets the paused volley continue on {subject}."
)

# Stages whose consequence is undoable without a second operator decision:
# the work they unblock still faces review before anything lands. Any stage
# not listed here — including one added later that nobody classified — reads
# as NOT reversible, because overclaiming reversibility at an approval
# prompt is the failure that matters.
_REVERSIBLE_STAGES: frozenset[str] = frozenset({"general", "upfront", "pre_impl"})


def _consequence(stage: str, pending_gates: list[str], subject: str) -> str:
    template = _STAGE_CONSEQUENCE.get(stage, _UNKNOWN_STAGE_CONSEQUENCE)
    gates = ", ".join(pending_gates) if pending_gates else "the pending gate"
    return template.format(gates=gates, subject=subject)


# --- construction ------------------------------------------------------------


def build(
    *,
    plan_title: str,
    feature_id: str | None,
    feature: Mapping[str, Any] | None,
    stage: str,
    pending_gates: list[str],
) -> DecisionBrief:
    """Build the snapshot from already-loaded plan + feature data.

    ``feature`` is ``None`` for plan-level pauses that name no feature; the
    brief then describes the plan and reports ``UNDECLARED`` impact rather
    than borrowing a feature-shaped claim from somewhere else.
    """
    description = (feature or {}).get("description") or ""
    what_changes = description.strip() or plan_title
    subject = feature_id or plan_title

    block = _impact_block(feature)
    status = classify_status(feature)
    audience: str | None = None
    summary: str | None = None
    surfaces: tuple[str, ...] = ()
    if block is not None:
        audience = _enum_value(block.get("audience"))
        summary = block.get("summary") or None
        surfaces = tuple(
            _enum_value(s) for s in (block.get("surfaces") or ())
        )

    return DecisionBrief(
        what_changes=what_changes,
        user_impact=summary,
        affected_audience=audience,
        decision_consequence=_consequence(stage, pending_gates, subject),
        reversible=stage in _REVERSIBLE_STAGES,
        status=status,
        surfaces=surfaces,
    )


def build_for_gate_pause(
    loaded: Any,
    feature_id: str | None,
    *,
    stage: str,
    pending_gates: list[str],
) -> DecisionBrief:
    """Convenience wrapper over :func:`build` taking a ``plan_loader.LoadedPlan``.

    Typed loosely on purpose: importing ``plan_loader`` here would pull the
    schema stack into the notification path for no gain. Never raises — a
    plan whose feature id has drifted out of ``features.json`` still gets a
    plan-level brief instead of taking down the pause notification, which is
    advisory by contract.
    """
    plan_title = str(getattr(getattr(loaded, "plan", None), "title", "") or "")
    if not plan_title:
        plan_title = str(getattr(loaded, "plan_id", "") or "")

    feature: Mapping[str, Any] | None = None
    if feature_id:
        try:
            feature = loaded.feature(feature_id)
        except (KeyError, AttributeError):
            feature = None

    return build(
        plan_title=plan_title,
        feature_id=feature_id,
        feature=feature,
        stage=stage,
        pending_gates=pending_gates,
    )


__all__ = [
    "BriefStatus",
    "DecisionBrief",
    "build",
    "build_for_gate_pause",
    "classify_status",
    "description_digest",
]
