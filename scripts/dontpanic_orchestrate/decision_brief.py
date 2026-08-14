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
from collections.abc import Iterable, Mapping, Sequence
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


# Plan 2026-08-09-002 F005 (audit i1 finding 1). Not every pause that asks the
# operator to act is a gate clearance. A tripped breaker, a stopped volley, a
# verdict the auditor contradicted itself about, a quota cap that no longer
# matches its unit — each reaches the operator through the same renderable
# ``needs_action`` band, and each needs a brief or the impact-first copy stays
# dead code on the live path. The stage templates above cannot describe them:
# "Clearing the pending gate lets the paused volley continue" is false when no
# gate is pending, and stating it at an approval prompt is the failure this
# plan exists to prevent.
#
# So: one deterministic template per emitting event kind, keyed by the INBOX
# ``event=`` value the supervisor writes. Same rules as the stage table — no
# generated prose (D002), each entry states only what the operator's next move
# actually sets in motion, and an entry naming ``{gates}`` may only be used
# when there really are gates to clear.
_EVENT_CONSEQUENCE: dict[str, str] = {
    "breaker_tripped": (
        "Clearing {gates} lets the paused volley continue on {subject}. "
        "The resulting patch is still reviewed before it merges."
    ),
    "verdict_blocked_reconciled": (
        "Clearing {gates} lets the paused volley continue on {subject}. "
        "The resulting patch is still reviewed before it merges."
    ),
    "environmental_blocker_short_circuit": (
        "Clearing {gates} lets the paused volley continue on {subject}. "
        "The resulting patch is still reviewed before it merges."
    ),
    "volley_terminal": (
        "The volley has already stopped on {subject}. Resuming starts another "
        "round; leaving it stopped leaves the work where the terminal left it."
    ),
    "no_progress_classification": (
        "The volley has already stopped on {subject}. Resuming starts another "
        "round; leaving it stopped leaves the work where the terminal left it."
    ),
    "verdict_mismatch": (
        "Nothing runs on {subject} until the auditor's narrative verdict and "
        "its structured status are reconciled by hand."
    ),
    "gate_state_reconciliation_failed": (
        "Dispatch on {subject} stays blocked until the persisted gate state "
        "and the plan's declared gates are made to agree by hand."
    ),
    "calibration_required": (
        "Recording a calibration sample lets the budget breaker convert local "
        "proxy units into percent-of-plan, and unblocks dispatch on {subject}."
    ),
    "unit_mismatch": (
        "Dispatch on {subject} stays blocked until the recorded cap unit and "
        "the unit quota_check.py observes are made to agree by hand."
    ),
    "config_required": (
        "Seeding the quota configuration unblocks dispatch on {subject}."
    ),
}

#: Used in place of a ``{gates}`` template when the event offers no gate to
#: clear — the global circuit breaker is the live case: it is a hard stop with
#: no operator clearance, and promising one would be worse than saying so.
_NO_CLEARANCE_CONSEQUENCE = (
    "No operator clearance is available for {subject}; the hard stop lifts "
    "when its window expires."
)


def _event_consequence(
    inbox_event: str, pending_gates: list[str], subject: str
) -> str:
    template = _EVENT_CONSEQUENCE[inbox_event]
    if "{gates}" in template and not pending_gates:
        template = _NO_CLEARANCE_CONSEQUENCE
    return template.format(gates=", ".join(pending_gates), subject=subject)


# --- construction ------------------------------------------------------------


def build(
    *,
    plan_title: str,
    feature_id: str | None,
    feature: Mapping[str, Any] | None,
    stage: str,
    pending_gates: list[str],
    inbox_event: str | None = None,
) -> DecisionBrief:
    """Build the snapshot from already-loaded plan + feature data.

    ``feature`` is ``None`` for plan-level pauses that name no feature; the
    brief then describes the plan and reports ``UNDECLARED`` impact rather
    than borrowing a feature-shaped claim from somewhere else.

    ``inbox_event`` names the emitting event kind when the pause is not a gate
    clearance (a tripped breaker, a stopped volley, a quota cap that drifted).
    Its consequence then comes from ``_EVENT_CONSEQUENCE`` instead of the stage
    table, and ``reversible`` stays ``False``: none of those events offers an
    undo, and overclaiming reversibility at an approval prompt is the failure
    that matters.
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

    if inbox_event in _EVENT_CONSEQUENCE:
        consequence = _event_consequence(str(inbox_event), pending_gates, subject)
        reversible = False
    else:
        consequence = _consequence(stage, pending_gates, subject)
        reversible = stage in _REVERSIBLE_STAGES

    return DecisionBrief(
        what_changes=what_changes,
        user_impact=summary,
        affected_audience=audience,
        decision_consequence=consequence,
        reversible=reversible,
        status=status,
        surfaces=surfaces,
    )


def build_for_gate_pause(
    loaded: Any,
    feature_id: str | None,
    *,
    stage: str,
    pending_gates: list[str],
    inbox_event: str | None = None,
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
        inbox_event=inbox_event,
    )


# --- F006: the plan-lock advisory ---------------------------------------------
#
# D004: a feature that declares no impact on a plan whose surfaces are felt
# outside the team is worth saying out loud at lock, and is never worth refusing
# the lock over — blocking on a field introduced in the same change would strand
# every plan written before it. So this is a lint that prints and exits 0.
#
# Everything below is pure: it takes already-loaded plan surfaces and feature
# records and returns what to say. The CLI owns reading the plan and printing.


#: The plan-level ``surfaces`` values whose audience is outside the team, per
#: ``plan.md`` § acceptance 4 ("a plan whose features touch ux/ios/web/android
#: surfaces without ``user_impact``"). ``backend`` / ``infra`` / ``data`` and
#: friends are deliberately absent: they describe where work lands, not who
#: feels it, and warning on them would make the advisory noise that gets tuned
#: out — which costs more than the warning it would have delivered.
USER_FACING_SURFACES: frozenset[str] = frozenset({"android", "ios", "ux", "web"})


@dataclass(frozen=True)
class UndeclaredImpactFeature:
    """One feature the advisory names, with enough context to act on it."""

    feature_id: str
    description: str


@dataclass(frozen=True)
class UndeclaredImpactAdvisory:
    """What the lock-time lint found. Empty ``features`` means nothing to say.

    ``user_facing_surfaces`` is carried so the printed advisory can state why
    it fired — an operator who sees "declares ux" understands the rule; one who
    sees only a list of feature ids has to go find it.
    """

    user_facing_surfaces: tuple[str, ...]
    features: tuple[UndeclaredImpactFeature, ...]

    @property
    def applies(self) -> bool:
        """Whether there is anything to print at all."""
        return bool(self.user_facing_surfaces and self.features)


def _feature_field(feature: Any, name: str) -> Any:
    """Read a field off either a Pydantic feature record or a plain dict.

    ``LoadedPlan.features.features`` holds model objects; ``LoadedPlan.feature()``
    and hand-built test fixtures hand back dicts. Both are legitimate inputs, as
    they already are for :func:`classify_status`.
    """
    if isinstance(feature, Mapping):
        return feature.get(name)
    return getattr(feature, name, None)


def feature_declares_impact(feature: Any) -> bool:
    """Whether this feature carries a ``user_impact`` block at all.

    Only presence is asked. ``audience: none`` is a complete declaration (D003)
    and so counts as declared — the whole point of that escape hatch is that
    answering "nobody" is answering.
    """
    block = _feature_field(feature, "user_impact")
    if block is None:
        return False
    if isinstance(block, Mapping):
        return bool(block)
    return True


def undeclared_impact_advisory(
    *,
    plan_surfaces: Iterable[Any],
    features: Iterable[Any],
) -> UndeclaredImpactAdvisory:
    """Find the features that owe an impact declaration and do not carry one.

    Fires only when the *plan* declares a user-facing surface: the feature
    contract has no surface field of its own outside ``user_impact``, so the
    plan's declaration is the only statement on record about who is downstream
    of this work, and an undeclared feature under it is the gap worth naming.
    """
    surfaces = tuple(
        sorted(
            {
                value
                for value in (_enum_value(s) for s in plan_surfaces or ())
                if isinstance(value, str) and value in USER_FACING_SURFACES
            }
        )
    )
    if not surfaces:
        return UndeclaredImpactAdvisory(user_facing_surfaces=(), features=())

    missing: list[UndeclaredImpactFeature] = []
    for feature in features or ():
        if feature_declares_impact(feature):
            continue
        feature_id = str(_feature_field(feature, "id") or "(unidentified feature)")
        description = str(_feature_field(feature, "description") or "").strip()
        missing.append(
            UndeclaredImpactFeature(feature_id=feature_id, description=description)
        )
    return UndeclaredImpactAdvisory(
        user_facing_surfaces=surfaces, features=tuple(missing)
    )


#: How much of a feature description the advisory echoes back. Long enough to
#: recognize the feature without the list scrolling off a terminal.
_ADVISORY_DESCRIPTION_CHARS: int = 72


def render_undeclared_impact_advisory(
    advisory: UndeclaredImpactAdvisory, *, features_path: str
) -> tuple[str, ...]:
    """The advisory as printable lines — empty when there is nothing to say.

    ``features_path`` is stated in full because "add a user_impact block" is
    not actionable without knowing which file holds the block; the operator
    should not have to go looking for the artifact the lint is complaining
    about.
    """
    if not advisory.applies:
        return ()
    surfaces = ", ".join(advisory.user_facing_surfaces)
    count = len(advisory.features)
    lines = [
        f"[user-impact] advisory: this plan declares user-facing surface(s) "
        f"{surfaces}; {count} feature(s) carry no user_impact block:"
    ]
    for item in advisory.features:
        description = item.description
        if len(description) > _ADVISORY_DESCRIPTION_CHARS:
            description = description[: _ADVISORY_DESCRIPTION_CHARS - 1].rstrip() + "…"
        lines.append(
            f"  - {item.feature_id}" + (f" — {description}" if description else "")
        )
    lines.append(
        f"  Edit {features_path} and add a user_impact block "
        "(audience + summary + surfaces + description_hash) to each feature "
        "above, or declare audience: none where nothing outside the team feels "
        "the change."
    )
    lines.append(
        "  Advisory only — the lock succeeded and nothing was written (D004)."
    )
    return tuple(lines)


def build_for_attention(
    loaded: Any,
    feature_id: str | None,
    *,
    inbox_event: str,
    pending_gates: Sequence[str] = (),
) -> DecisionBrief:
    """Plan 2026-08-09-002 F005 — the snapshot for a non-gate attention event.

    Same construction as :func:`build_for_gate_pause`, and deliberately the
    same call shape, because the operator-facing question is the same one: a
    tripped breaker and a `pre_merge` gate both stop the work and both ask a
    human what should happen to *this feature*. The difference is only in what
    the answer sets in motion, which is what ``inbox_event`` selects.

    ``pending_gates`` is the gate the operator would clear, when the event
    offers one (the six approval breakers do; the global hard stop does not).
    """
    return build_for_gate_pause(
        loaded,
        feature_id,
        stage="",
        pending_gates=list(pending_gates),
        inbox_event=inbox_event,
    )


__all__ = [
    "USER_FACING_SURFACES",
    "BriefStatus",
    "DecisionBrief",
    "UndeclaredImpactAdvisory",
    "UndeclaredImpactFeature",
    "build",
    "build_for_attention",
    "build_for_gate_pause",
    "classify_status",
    "description_digest",
    "feature_declares_impact",
    "render_undeclared_impact_advisory",
    "undeclared_impact_advisory",
]
