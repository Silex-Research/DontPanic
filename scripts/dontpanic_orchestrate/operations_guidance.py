"""operations_guidance — turn operational blockers into a short decision set.

Plan 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 F007 AC(1)-(8).

A human or interactive agent should not spend multiple reasoning cycles deciding
whether to wait, redispatch, raise a ceiling, finalize a cleared ``pre_merge``
signoff, resume, close, onboard, reconcile, open the dashboard, or answer a
human-required setup question. This module is the single decision engine: it
consumes already-evaluated quota / admission / iteration / gate / project /
doctor state and emits typed :class:`ActionChoice` records — a recommended
action plus alternatives, an exact command when (and only when) one is safe and
validated, a rationale, a risk band, and whether a human must confirm.

Both the CLI (``dontpanic what-now``) and the dashboard ActionItems render from
the SAME typed data: :meth:`Guidance.to_action_items` converts the choices into
``operator_console.ActionItem`` envelopes the dashboard already knows how to
display, so budget/iteration guidance never drifts between the two surfaces.

Dashboard affordance (AC6): when any choice requires human input, the *response*
carries exactly one :class:`DashboardAffordance` — the active URL when a
dashboard is running, otherwise the exact start command. Individual choices
reference it by id (``references_affordance``) but never repeat the full text.

The engine is pure: builders take typed inputs and mutate nothing. The live
collector (:func:`collect_state`) is the only part that touches the filesystem.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

# ─────────────────────────────── vocabulary ────────────────────────────────


class Risk(str, Enum):
    """Risk band of taking a choice. Consumers branch on these values."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Stable choice ``kind`` vocabulary (id prefix + dashboard grouping).
KIND_WAIT_REDISPATCH = "wait_redispatch"
KIND_RAISE_CEILING = "raise_ceiling"
KIND_RAISE_THRESHOLD = "raise_threshold"
KIND_CONTINUE_ITERATION = "continue_iteration"
KIND_FINALIZE = "finalize"
KIND_APPROVE_GATE = "approve_gate"
KIND_RESUME = "resume"
KIND_CLOSE = "close"
KIND_ONBOARD = "onboard"
KIND_RECONCILE = "reconcile"
KIND_REFRESH_BRIEF = "refresh_brief"
KIND_DOCTOR = "doctor"
KIND_PROJECT_DOCTOR = "project_doctor"
KIND_ROLE = "role"

# Canonical home for editable quota ceilings. There is no one-shot CLI setter
# (`quota-caps` exposes only init|show), so raising a ceiling/threshold is a
# human edit — guidance never emits a fabricated `quota-caps set ...` command.
QUOTA_CAPS_FILE = "~/.jarvis/quota_caps.json"
ADMISSION_THRESHOLD_ENV = "JARVIS_QUOTA_DEFER_THRESHOLD"

DASHBOARD_AFFORDANCE_ID = "dashboard"
DASHBOARD_START_COMMAND = "dontpanic dashboard serve"

# Stable id for the single response-level dashboard affordance ActionItem the
# dashboard cache carries (AC7d). One per rendered cache, regardless of how many
# operations items reference it.
DASHBOARD_AFFORDANCE_ITEM_ID = "operations:dashboard-affordance"


# ─────────────────────────── response-level affordance ─────────────────────


@dataclass(frozen=True)
class DashboardAffordance:
    """The single response-level dashboard pointer (AC6).

    Exactly one of these is attached to a :class:`Guidance` when any choice
    requires human input. ``is_running`` selects which text the renderer shows:
    the active URL (running) or the start command (not running). Individual
    choices reference it by :data:`DASHBOARD_AFFORDANCE_ID`; they never embed
    this text themselves.
    """

    is_running: bool
    url: str | None = None
    start_command: str = DASHBOARD_START_COMMAND
    affordance_id: str = DASHBOARD_AFFORDANCE_ID

    def as_status(self) -> Any:
        """Adapt this affordance to a :class:`dashboard.DashboardStatus` so the
        response-level hint routes through the shared once-per-response renderer
        (codex F010 i1 architecture finding)."""
        from dontpanic_orchestrate import dashboard

        return dashboard.DashboardStatus(
            is_running=self.is_running,
            url=self.url,
            start_command=self.start_command,
        )

    def text(self) -> str:
        # Single-sourced wording: delegate to the canonical dashboard helper
        # rather than re-spelling the hint here (codex F010 i1).
        from dontpanic_orchestrate import dashboard

        return dashboard.render_hint_line(
            is_running=self.is_running,
            url=self.url,
            start_command=self.start_command,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "affordance_id": self.affordance_id,
            "is_running": self.is_running,
            "url": self.url,
            "start_command": self.start_command,
            "text": self.text(),
        }

    def to_action_item(self, *, updated_at: str | None = None) -> Any:
        """Render this response-level affordance as a single ``ActionItem`` so it
        is actually PRESENT in the dashboard cache (AC7d), not merely named in
        another item's detail text.

        When the dashboard is running the active URL is the affordance (no
        runnable command, so the item is non-automatable / human-pointer). When
        it is not running the start command IS the affordance and the item is
        automatable. The id is stable so the cache carries exactly one.
        """
        from dontpanic_orchestrate import operator_console

        ts = updated_at or operator_console._now_iso()
        if self.is_running:
            return operator_console.ActionItem(
                id=DASHBOARD_AFFORDANCE_ITEM_ID,
                source=operator_console.SOURCE_SUPERVISOR,
                band=operator_console.Band.INFO,
                title="Dashboard is running",
                detail=self.text(),
                exact_command=None,
                automatable=False,
                human_required_reason="dashboard pointer",
                evidence_uri=self.url,
                updated_at=ts,
            )
        return operator_console.ActionItem(
            id=DASHBOARD_AFFORDANCE_ITEM_ID,
            source=operator_console.SOURCE_SUPERVISOR,
            band=operator_console.Band.ADVISORY,
            title="Start the dashboard to act on these items",
            detail=self.text(),
            exact_command=self.start_command,
            automatable=True,
            human_required_reason=None,
            evidence_uri=None,
            updated_at=ts,
        )


# ──────────────────────────────── ActionChoice ─────────────────────────────


@dataclass(frozen=True)
class ActionChoice:
    """One recommended operational move.

    ``exact_command`` is populated ONLY when the command is safe to emit and
    fully determined from validated state (AC7). When a human must decide the
    value (raise a ceiling, assign a role, answer a setup question) the command
    may still be emitted as a concrete next step but ``requires_human`` is set;
    when no safe command exists at all, ``exact_command`` is ``None`` and the
    rationale says human action is required.

    ``recommended`` marks the default within a group of mutually-exclusive
    choices (e.g. wait-then-redispatch is recommended over raise-ceiling).
    ``references_affordance`` carries the shared dashboard affordance id (never
    the full text) so the dashboard pointer is shown once per response.
    """

    id: str
    kind: str
    title: str
    rationale: str
    risk: Risk
    recommended: bool = False
    exact_command: str | None = None
    requires_human: bool = False
    references_affordance: str | None = None
    # When True the choice is about ONE specific feature (iteration cap, signoff
    # finalize), so its dashboard ActionItem id is feature-scoped — two distinct
    # blocked features sharing a choice kind then produce two distinct items
    # instead of collapsing. Plan-level blockers (quota / setup / no-progress)
    # leave this False so they intentionally dedup across the plan's features.
    feature_scoped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "rationale": self.rationale,
            "risk": self.risk.value,
            "recommended": self.recommended,
            "exact_command": self.exact_command,
            "requires_human": self.requires_human,
            "references_affordance": self.references_affordance,
            "feature_scoped": self.feature_scoped,
        }


@dataclass(frozen=True)
class Guidance:
    """The full decision set for one blocked unit of work."""

    plan_id: str
    feature_id: str | None
    headline: str
    choices: tuple[ActionChoice, ...]
    affordance: DashboardAffordance | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "feature_id": self.feature_id,
            "headline": self.headline,
            "choices": [c.to_dict() for c in self.choices],
            "affordance": self.affordance.to_dict() if self.affordance else None,
        }

    def to_action_items(self, *, updated_at: str | None = None) -> list[Any]:
        """Convert each choice into an ``operator_console.ActionItem`` so the
        dashboard renders the SAME typed data the CLI prints (AC3).

        Imported lazily so importing this module stays cheap for callers that
        only want the pure engine.
        """
        from dontpanic_orchestrate import operator_console

        ts = updated_at or operator_console._now_iso()
        items: list[Any] = []
        for choice in self.choices:
            automatable = bool(choice.exact_command) and not choice.requires_human
            human_reason = None if automatable else (
                "operations decision" if choice.requires_human else "no safe command"
            )
            detail = choice.rationale
            if choice.references_affordance and self.affordance is not None:
                # Reference the shared affordance by id; do NOT repeat its text.
                detail = f"{detail} (see dashboard affordance)"
            # AC4: feature-scoped choices carry the feature_id in their id so two
            # distinct blocked features with the same choice kind do not collapse
            # to one item; plan-level choices omit it so their intentional
            # plan-level dedup is preserved.
            if choice.feature_scoped and self.feature_id:
                item_id = f"operations:{self.plan_id}:{self.feature_id}:{choice.id}"
            else:
                item_id = f"operations:{self.plan_id}:{choice.id}"
            items.append(
                operator_console.ActionItem(
                    id=item_id,
                    source=operator_console.SOURCE_SUPERVISOR,
                    band=(
                        operator_console.Band.NEEDS_ACTION
                        if not automatable
                        else operator_console.Band.ADVISORY
                    ),
                    title=choice.title,
                    detail=detail,
                    exact_command=choice.exact_command,
                    automatable=automatable,
                    human_required_reason=human_reason,
                    evidence_uri=None,
                    updated_at=ts,
                )
            )
        return items


# ─────────────────────────────── input states ──────────────────────────────


@dataclass(frozen=True)
class IterationState:
    """Loop-cap state for the blocked feature."""

    max_iterations: int
    iterations_used: int

    @property
    def remaining(self) -> int:
        return max(0, self.max_iterations - self.iterations_used)

    @property
    def next_within_cap(self) -> bool:
        return self.remaining > 0

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    def summary(self) -> str:
        if self.exhausted:
            return (
                f"max_iterations exhausted: {self.iterations_used}/"
                f"{self.max_iterations} fix iterations used; the next fix "
                f"iteration is OVER cap."
            )
        return (
            f"{self.remaining} fix iteration(s) remain under "
            f"max_iterations={self.max_iterations} "
            f"({self.iterations_used} used); the next fix iteration is within cap."
        )


@dataclass(frozen=True)
class QuotaCooldownState:
    agent: str
    observed_pct: float | None
    threshold: float
    wait_until: str | None = None
    cause: str | None = None
    raise_target_pct: float | None = None


@dataclass(frozen=True)
class BudgetCeilingState:
    agent: str
    observed_native: float | None
    cap: float | None
    unit: str | None
    window: str | None = None


@dataclass(frozen=True)
class AdmissionThresholdState:
    agent: str
    observed_pct: float | None
    threshold: float
    wait_until: str | None = None


@dataclass(frozen=True)
class SignoffState:
    feature_id: str
    verdict: str
    pre_merge_cleared: bool
    # AC7 "respects current state": the CLI's `approve` path refuses a lifecycle
    # gate (exit 2) unless the supervisor recorded it as currently pending. Only
    # when ``pre_merge_pending`` is True is `approve <plan> pre_merge` a runnable
    # invocation; otherwise guidance must fall back to human-required advisory
    # text with no exact_command. ``collect_state`` derives this from
    # ``gate_pause.is_gate_currently_pending`` / the persisted pending_stage.
    pre_merge_pending: bool = False


@dataclass(frozen=True)
class NoProgressState:
    breaker_name: str
    detail: str


@dataclass(frozen=True)
class SetupNeeds:
    missing_project: bool = False
    project_name: str | None = None
    project_path: str | None = None
    stale_onboarding: bool = False
    stale_brief: bool = False
    unsupported_role: str | None = None  # the operator-only agent requested
    unsupported_role_name: str | None = None  # the role it was requested for
    split_config_homes: bool = False
    stale_project_config: bool = False  # project onboarding/config needs validation
    human_required_config: str | None = None  # description of the open question


# ──────────────────────────────── builders ─────────────────────────────────


def _redispatch_command(plan_id: str) -> str:
    return f"dontpanic orchestrate {plan_id} --confirm"


def _redispatch_command_if_within_cap(
    plan_id: str, iteration: IterationState | None
) -> str | None:
    """AC7a: a redispatch/orchestrate command is emitted ONLY when the next fix
    iteration is within ``max_iterations``. When the cap is exhausted the
    blocker is no longer "wait then redispatch" — a redispatch would exceed the
    cap — so no command is emitted and the caller marks the choice
    human-required with close/finalize advice instead."""
    if iteration is not None and iteration.exhausted:
        return None
    return _redispatch_command(plan_id)


# Appended to a wait/redispatch rationale when the iteration cap is exhausted so
# the recommended path pivots from redispatch to close/finalize (AC7a).
_EXHAUSTED_REDISPATCH_NOTE = (
    " However, max_iterations is exhausted, so a redispatch would exceed the "
    "cap — finalize/close the feature or raise the cap before redispatching. "
    "Human action required."
)


def build_quota_cooldown_choices(
    plan_id: str,
    state: QuotaCooldownState,
    *,
    iteration: IterationState | None = None,
) -> list[ActionChoice]:
    """Recommended wait-until + redispatch, plus a raise-ceiling alternative
    when a concrete target is known (AC1).

    AC7a: when ``iteration`` is exhausted the recommended choice emits NO
    redispatch command (it would exceed the cap) and becomes human-required.
    """
    wait_phrase = (
        f"wait until {state.wait_until}, then redispatch"
        if state.wait_until
        else "wait for the cooldown to clear, then redispatch"
    )
    obs = (
        f"{state.agent} is at {state.observed_pct:.0f}% of its quota window "
        f"(defer threshold {state.threshold:.0f}%)"
        if state.observed_pct is not None
        else f"{state.agent} quota is cooling down"
        + (f" ({state.cause})" if state.cause else "")
    )
    iter_note = f" {iteration.summary()}" if iteration is not None else ""
    exhausted = iteration is not None and iteration.exhausted
    redispatch = _redispatch_command_if_within_cap(plan_id, iteration)
    choices = [
        ActionChoice(
            id="quota-wait-redispatch",
            kind=KIND_WAIT_REDISPATCH,
            title=f"Wait out {state.agent} cooldown, then redispatch (recommended)",
            rationale=(
                f"{obs}. Recommended: {wait_phrase}.{iter_note}"
                + (_EXHAUSTED_REDISPATCH_NOTE if exhausted else "")
            ),
            risk=Risk.LOW,
            recommended=True,
            exact_command=redispatch,
            requires_human=exhausted,
        )
    ]
    if state.raise_target_pct is not None:
        choices.append(
            ActionChoice(
                id="quota-raise-ceiling",
                kind=KIND_RAISE_CEILING,
                title=f"Raise {state.agent} budget ceiling instead",
                rationale=(
                    f"Alternative: raise {state.agent}'s cap toward "
                    f"{state.raise_target_pct:.0f}% so dispatch admits now — there is "
                    f"no one-shot CLI setter, so edit the cap in {QUOTA_CAPS_FILE} by "
                    f"hand. This spends more of the quota window, a human judgment "
                    f"call. Human action required."
                ),
                risk=Risk.MEDIUM,
                # AC7: no safe `quota-caps set` exists (CLI is init|show only) —
                # emit no command rather than a non-runnable one.
                exact_command=None,
                requires_human=True,
            )
        )
    return choices


def build_budget_ceiling_choices(
    plan_id: str,
    state: BudgetCeilingState,
    *,
    iteration: IterationState | None = None,
) -> list[ActionChoice]:
    """Budget ceiling exceeded: wait/redispatch (safer default) + raise-ceiling
    (AC1, AC4-style both-paths)."""
    cap_txt = (
        f"{state.observed_native:.0f}/{state.cap:.0f} {state.unit or 'tokens'}"
        if state.observed_native is not None and state.cap is not None
        else "over the configured budget ceiling"
    )
    iter_note = f" {iteration.summary()}" if iteration is not None else ""
    exhausted = iteration is not None and iteration.exhausted
    redispatch = _redispatch_command_if_within_cap(plan_id, iteration)
    return [
        ActionChoice(
            id="budget-wait-redispatch",
            kind=KIND_WAIT_REDISPATCH,
            title=f"Wait for {state.agent} budget window to roll over (recommended)",
            rationale=(
                f"{state.agent} budget ceiling reached ({cap_txt}). Safer default: "
                f"wait for the window to roll over, then redispatch.{iter_note}"
                + (_EXHAUSTED_REDISPATCH_NOTE if exhausted else "")
            ),
            risk=Risk.LOW,
            recommended=True,
            exact_command=redispatch,
            requires_human=exhausted,
        ),
        ActionChoice(
            id="budget-raise-ceiling",
            kind=KIND_RAISE_CEILING,
            title=f"Raise {state.agent} budget ceiling",
            rationale=(
                f"Alternative: raise {state.agent}'s budget ceiling so dispatch "
                f"admits now — edit the cap in {QUOTA_CAPS_FILE} (no one-shot CLI "
                f"setter exists). Spends more budget; confirm before raising. "
                f"Human action required."
            ),
            risk=Risk.MEDIUM,
            # AC7: `quota-caps` is init|show only — no validated set command.
            exact_command=None,
            requires_human=True,
        ),
    ]


def build_admission_threshold_choices(
    plan_id: str,
    state: AdmissionThresholdState,
    *,
    iteration: IterationState | None = None,
) -> list[ActionChoice]:
    """Admission threshold mismatch: wait/redispatch + raise-threshold (AC1).

    AC7a: when ``iteration`` is exhausted the recommended choice emits NO
    redispatch command (it would exceed the cap) and becomes human-required,
    exactly like quota/budget blockers do.
    """
    wait_phrase = (
        f"wait until {state.wait_until}, then redispatch"
        if state.wait_until
        else "wait for usage to drop below threshold, then redispatch"
    )
    obs = (
        f"{state.agent} at {state.observed_pct:.0f}% exceeds the admission "
        f"threshold of {state.threshold:.0f}%"
        if state.observed_pct is not None
        else f"{state.agent} is above the admission threshold"
    )
    iter_note = f" {iteration.summary()}" if iteration is not None else ""
    exhausted = iteration is not None and iteration.exhausted
    redispatch = _redispatch_command_if_within_cap(plan_id, iteration)
    return [
        ActionChoice(
            id="admission-wait-redispatch",
            kind=KIND_WAIT_REDISPATCH,
            title=f"Wait below admission threshold, then redispatch (recommended)",
            rationale=(
                f"{obs}. Recommended: {wait_phrase}.{iter_note}"
                + (_EXHAUSTED_REDISPATCH_NOTE if exhausted else "")
            ),
            risk=Risk.LOW,
            recommended=True,
            exact_command=redispatch,
            requires_human=exhausted,
        ),
        ActionChoice(
            id="admission-raise-threshold",
            kind=KIND_RAISE_THRESHOLD,
            title="Raise the admission threshold",
            rationale=(
                f"Alternative: raise the defer threshold above "
                f"{state.threshold:.0f}% so dispatch admits now by exporting "
                f"{ADMISSION_THRESHOLD_ENV} (the percentage is yours to choose) "
                f"before redispatching. This relaxes the guard for everyone — "
                f"confirm before changing. Human action required."
            ),
            risk=Risk.MEDIUM,
            # AC7: the threshold value is a human decision; emit no command with a
            # placeholder pct. The env var is named in the rationale instead.
            exact_command=None,
            requires_human=True,
        ),
    ]


def build_iteration_choices(
    plan_id: str,
    feature_id: str,
    state: IterationState,
) -> list[ActionChoice]:
    """max_iterations guidance (AC2). Within cap → continue; exhausted →
    approve/close."""
    if state.next_within_cap:
        return [
            ActionChoice(
                id="iteration-continue",
                kind=KIND_CONTINUE_ITERATION,
                title="Run the next fix iteration (within cap)",
                rationale=state.summary(),
                risk=Risk.LOW,
                recommended=True,
                exact_command=_redispatch_command(plan_id),
                feature_scoped=True,
            )
        ]
    return [
        ActionChoice(
            id="iteration-close",
            kind=KIND_CLOSE,
            title="Close the feature — iterations exhausted",
            rationale=(
                f"{state.summary()} Redispatch would exceed the cap. "
                f"If the work is acceptable, operator-resolve the close-out with "
                f"`dontpanic close --operator-resolved {plan_id} {feature_id} "
                f"--reason <class>`, choosing the <class> yourself. Human action "
                f"required."
            ),
            risk=Risk.MEDIUM,
            # AC7: the close <class> is a human judgment call, so the command is
            # NOT fully determined — emit no exact_command (only a hint in the
            # rationale) rather than a non-runnable placeholder.
            exact_command=None,
            requires_human=True,
            feature_scoped=True,
        ),
        ActionChoice(
            id="iteration-approve",
            kind=KIND_APPROVE_GATE,
            title="Raise the cap to allow one more iteration",
            rationale=(
                "Alternative: if a defect is fixable in one more pass, raise "
                "loop_caps.max_iterations in the plan, then redispatch. There is "
                "no single gate to resume here — `dontpanic resume` requires a "
                "specific `--gate <name>` or `--all`, and neither applies to an "
                "exhausted cap — so no command is emitted. Confirm the extra spend "
                "is worth it. Human action required."
            ),
            risk=Risk.MEDIUM,
            # AC7b: no bare `dontpanic resume <plan>` — an exhausted cap has no
            # specific gate to clear, so emit no command rather than an invalid one.
            exact_command=None,
            requires_human=True,
            feature_scoped=True,
        ),
    ]


def build_signoff_choices(
    plan_id: str,
    state: SignoffState,
) -> list[ActionChoice]:
    """signed_off paused at pre_merge (AC4). Pending → approve; cleared → offer
    the no-paid-call finalization instead of a fresh paid dispatch."""
    if not state.pre_merge_cleared:
        if state.pre_merge_pending:
            return [
                ActionChoice(
                    id="signoff-approve-pre-merge",
                    kind=KIND_APPROVE_GATE,
                    title="Clear the pre_merge gate to finish",
                    rationale=(
                        f"{state.feature_id} is auditor-{state.verdict} but paused at the "
                        f"pre_merge human gate. Gate state: pre_merge PENDING. Approve it "
                        f"to unblock finalization."
                    ),
                    risk=Risk.MEDIUM,
                    exact_command=f"dontpanic approve {plan_id} pre_merge",
                    requires_human=True,
                    feature_scoped=True,
                )
            ]
        # AC7 (respects current state): signed_off but pre_merge is neither
        # cleared nor currently pending — the supervisor has not paused on it,
        # so `approve <plan> pre_merge` would exit 2 (lifecycle gates may only
        # be cleared once pending). Emit no command; point the human at the
        # gate instead.
        return [
            ActionChoice(
                id="signoff-approve-pre-merge",
                kind=KIND_APPROVE_GATE,
                title="Wait for the pre_merge gate to pause",
                rationale=(
                    f"{state.feature_id} is auditor-{state.verdict} but the pre_merge "
                    f"gate is not currently pending (the supervisor has not paused on "
                    f"it). Approving now is a usage error — a lifecycle gate may only "
                    f"be cleared once it is pending. Re-run when the pre_merge pause is "
                    f"active, or inspect gate-state. Human action required."
                ),
                risk=Risk.MEDIUM,
                exact_command=None,
                requires_human=True,
                feature_scoped=True,
            )
        ]
    return [
        ActionChoice(
            id="signoff-finalize",
            kind=KIND_FINALIZE,
            title="Finalize with no paid agent calls (recommended)",
            rationale=(
                f"{state.feature_id} is auditor-{state.verdict} and pre_merge is "
                f"CLEARED. Finalize consumes the existing signed_off audit artifact "
                f"and flips passes:true — no fresh paid dispatch required."
            ),
            risk=Risk.LOW,
            recommended=True,
            exact_command=f"dontpanic finalize {plan_id} --feature {state.feature_id}",
            feature_scoped=True,
        )
    ]


def build_no_progress_choices(
    plan_id: str,
    feature_id: str | None,
    state: NoProgressState,
) -> list[ActionChoice]:
    """no-progress / breaker stop (AC5-style): approve / resume / close."""
    feat = feature_id or "<feature>"
    return [
        ActionChoice(
            id="no-progress-resume",
            kind=KIND_RESUME,
            title=f"Resume past {state.breaker_name} after a fix",
            rationale=(
                f"{state.breaker_name} tripped: {state.detail}. If you have a fix "
                f"that breaks the stall, resume past this specific gate. Risk: "
                f"re-tripping if nothing changed."
            ),
            risk=Risk.MEDIUM,
            recommended=True,
            # AC7b: name the gate explicitly — `dontpanic resume <plan>` is a
            # usage error (exit 2). The breaker name IS the gate, so emit the
            # validated `--gate <name>` form.
            exact_command=f"dontpanic resume {plan_id} --gate {state.breaker_name}",
            requires_human=True,
        ),
        ActionChoice(
            id="no-progress-close",
            kind=KIND_CLOSE,
            title="Close the feature as operator-resolved",
            rationale=(
                "Alternative: if the remaining work is acceptable or out of scope, "
                "close it out with `dontpanic close --operator-resolved "
                f"{plan_id} {feat} --reason <class>`, choosing the <class> "
                "yourself. Confirm the classification. Human action required."
            ),
            risk=Risk.MEDIUM,
            # AC7: the <class> (and the feature id when unknown) are human
            # decisions — emit no exact_command, only a hint in the rationale.
            exact_command=None,
            requires_human=True,
        ),
    ]


def build_setup_choices(needs: SetupNeeds) -> list[ActionChoice]:
    """Setup-friction guidance (AC5): onboard / doctor / brief / reconcile /
    role. Risky/judgment cases get no exact command (AC7)."""
    choices: list[ActionChoice] = []
    # `projects add ... --onboard` is only a runnable command when BOTH the
    # registry name and the path are known. With either missing the value is a
    # human decision, so AC7 forbids emitting a placeholder command. When both
    # are known, the name/path are shell-quoted so a repo path containing spaces
    # (or other shell metacharacters) still renders a runnable command.
    have_project_args = needs.project_name is not None and needs.project_path is not None
    if have_project_args:
        q_name = shlex.quote(str(needs.project_name))
        q_path = shlex.quote(str(needs.project_path))
        add_cmd = f"dontpanic projects add {q_name} {q_path} --onboard"
        readd_cmd = f"{add_cmd} --force --yes"
    else:
        add_cmd = None
        readd_cmd = None
    if needs.missing_project:
        choices.append(
            ActionChoice(
                id="setup-register-project",
                kind=KIND_ONBOARD,
                title="Register and onboard this repo",
                rationale=(
                    "This repo is not a registered DontPanic project. Register it "
                    "and write the managed onboarding block before dispatching."
                    + ("" if have_project_args else
                       " Supply the registry name and repo path to run it.")
                ),
                risk=Risk.LOW,
                recommended=True,
                exact_command=add_cmd,
                requires_human=not have_project_args,
            )
        )
    if needs.stale_onboarding:
        choices.append(
            ActionChoice(
                id="setup-refresh-onboarding",
                kind=KIND_ONBOARD,
                title="Refresh the stale onboarding block",
                rationale=(
                    "The repo's managed onboarding block is missing or stale "
                    "(absent AGENTS.md/block, generator version/hash drift, or "
                    "tamper). Re-run onboarding to (re)write the marked block. "
                    "Because the project is ALREADY registered, the registry "
                    "refuses a bare re-add — the command carries `--force --yes` "
                    "to overwrite the existing entry."
                    + ("" if have_project_args else
                       " Supply the registry name and repo path to run it.")
                ),
                risk=Risk.LOW,
                # AC7e: re-onboarding an already-registered project requires
                # `--force --yes` — `projects_registry.add_project` raises
                # ProjectsRegistryError on an existing name without it (a bare
                # `--onboard` would not run). Emit the validated re-add form.
                exact_command=readd_cmd,
                requires_human=not have_project_args,
            )
        )
    if needs.stale_project_config:
        # `doctor --project` validates ONE project's onboarding/config/roles
        # surface. Safe to emit when the project name is known.
        name = needs.project_name
        choices.append(
            ActionChoice(
                id="setup-project-doctor",
                kind=KIND_PROJECT_DOCTOR,
                title="Validate this project's onboarding/config",
                rationale=(
                    "The project's onboarding/config (config / agents / roles.* / "
                    "managed AGENTS.md block) may be stale or mismatched. Run the "
                    "project doctor to see the exact PASS/WARN/FAIL surface before "
                    "dispatching."
                    + ("" if name else " Supply the project name or path to run it.")
                ),
                risk=Risk.LOW,
                exact_command=(f"dontpanic doctor --project {name}" if name else None),
                requires_human=name is None,
            )
        )
    if needs.stale_brief:
        choices.append(
            ActionChoice(
                id="setup-refresh-brief",
                kind=KIND_REFRESH_BRIEF,
                title="Refresh the agent operating brief",
                rationale=(
                    "The cached agent brief predates the current command/executor "
                    "set. Regenerate it so operators read current facts."
                ),
                risk=Risk.LOW,
                exact_command="dontpanic agent brief",
            )
        )
    if needs.split_config_homes:
        choices.append(
            ActionChoice(
                id="setup-reconcile-homes",
                kind=KIND_RECONCILE,
                title="Reconcile split config homes",
                rationale=(
                    "Both ~/.dontpanic and ~/.jarvis hold state. The dry-run "
                    "below names the `homes` subcommand and writes nothing — "
                    "review the migration plan, then re-run with `--confirm` to "
                    "migrate. Ambiguous (divergent same-name) merges are always "
                    "refused. Human action required before the confirmed migration."
                ),
                risk=Risk.MEDIUM,
                # AC7c: bare `dontpanic reconcile` exits 2 (it needs a subcommand).
                # Emit the validated, write-nothing `reconcile homes --dry-run`;
                # the actual migration (`--confirm`) stays a human decision.
                exact_command="dontpanic reconcile homes --dry-run",
                requires_human=True,
            )
        )
    if needs.unsupported_role is not None:
        role = needs.unsupported_role_name or "worker"
        choices.append(
            ActionChoice(
                id="setup-unsupported-role",
                kind=KIND_ROLE,
                title=f"{needs.unsupported_role} cannot be a worker executor",
                rationale=(
                    f"{needs.unsupported_role} has no registered executor, so it "
                    f"cannot be assigned to the {role} role. It can OPERATE "
                    f"DontPanic but cannot be DISPATCHED. Pick a registered "
                    f"executor (claude/codex) for {role}. Human action required — "
                    f"no safe command auto-assigns an unsupported agent."
                ),
                risk=Risk.HIGH,
                exact_command=None,
                requires_human=True,
            )
        )
    if needs.human_required_config is not None:
        choices.append(
            ActionChoice(
                id="setup-human-config",
                kind=KIND_DOCTOR,
                title="Resolve a human-required configuration question",
                rationale=(
                    f"{needs.human_required_config} Run doctor to see the exact "
                    f"surface, then make the call. Human action required."
                ),
                risk=Risk.MEDIUM,
                exact_command="dontpanic doctor --agent",
                requires_human=True,
            )
        )
    return choices


# ───────────────────────────── top-level assembly ──────────────────────────


def build_guidance(
    plan_id: str,
    *,
    feature_id: str | None = None,
    headline: str = "",
    quota_cooldown: QuotaCooldownState | None = None,
    budget_ceiling: BudgetCeilingState | None = None,
    admission_threshold: AdmissionThresholdState | None = None,
    iteration: IterationState | None = None,
    signoff: SignoffState | None = None,
    no_progress: NoProgressState | None = None,
    setup: SetupNeeds | None = None,
    dashboard: DashboardAffordance | None = None,
) -> Guidance:
    """Compose the full decision set for one blocked unit of work.

    Choices are appended in a deterministic order (quota → budget → admission →
    iteration → signoff → no-progress → setup). The single dashboard affordance
    (AC6) is attached only when at least one choice requires human input; every
    such choice references it by id and never repeats its text.
    """
    choices: list[ActionChoice] = []

    if quota_cooldown is not None:
        choices.extend(build_quota_cooldown_choices(plan_id, quota_cooldown, iteration=iteration))
    if budget_ceiling is not None:
        choices.extend(build_budget_ceiling_choices(plan_id, budget_ceiling, iteration=iteration))
    if admission_threshold is not None:
        choices.extend(build_admission_threshold_choices(plan_id, admission_threshold, iteration=iteration))
    # Iteration-only guidance (no quota/budget/admission blocker carrying it already).
    if (
        iteration is not None
        and quota_cooldown is None
        and budget_ceiling is None
        and admission_threshold is None
    ):
        choices.extend(build_iteration_choices(plan_id, feature_id or "<feature>", iteration))
    if signoff is not None:
        choices.extend(build_signoff_choices(plan_id, signoff))
    if no_progress is not None:
        choices.extend(build_no_progress_choices(plan_id, feature_id, no_progress))
    if setup is not None:
        choices.extend(build_setup_choices(setup))

    needs_human = any(c.requires_human for c in choices)
    affordance = dashboard if (needs_human and dashboard is not None) else None

    # Attach the shared affordance id to every human-required choice (dedup:
    # the full text lives on the response affordance, not on each choice).
    if affordance is not None:
        choices = _reattach_affordance(choices, affordance.affordance_id)

    if not headline:
        headline = _derive_headline(
            quota_cooldown, budget_ceiling, admission_threshold, iteration, signoff, no_progress, setup
        )

    return Guidance(
        plan_id=plan_id,
        feature_id=feature_id,
        headline=headline,
        choices=tuple(choices),
        affordance=affordance,
    )


def _reattach_affordance(choices: list[ActionChoice], affordance_id: str) -> list[ActionChoice]:
    """Return choices with the affordance id set on every human-required one.

    ActionChoice is frozen; rebuild via the constructor rather than mutating.
    """
    from dataclasses import replace

    out: list[ActionChoice] = []
    for c in choices:
        if c.requires_human and c.references_affordance is None:
            out.append(replace(c, references_affordance=affordance_id))
        else:
            out.append(c)
    return out


def _derive_headline(*states: Any) -> str:
    parts: list[str] = []
    quota, budget, admission, iteration, signoff, no_progress, setup = states
    if quota is not None:
        parts.append(f"{quota.agent} quota cooling down")
    if budget is not None:
        parts.append(f"{budget.agent} budget ceiling reached")
    if admission is not None:
        parts.append(f"{admission.agent} above admission threshold")
    if signoff is not None:
        parts.append(
            f"{signoff.feature_id} signed_off"
            + (" / pre_merge cleared" if signoff.pre_merge_cleared else " / pre_merge pending")
        )
    if no_progress is not None:
        parts.append(f"{no_progress.breaker_name} tripped")
    if setup is not None:
        parts.append("setup action needed")
    if not parts and iteration is not None:
        parts.append("iteration-cap decision")
    return "; ".join(parts) if parts else "no blockers"


# ─────────────────────────────── text render ───────────────────────────────


def render_text(guidance: Guidance) -> str:
    lines: list[str] = []
    lines.append(f"what-now: {guidance.plan_id}" + (f" / {guidance.feature_id}" if guidance.feature_id else ""))
    if guidance.headline:
        lines.append(f"  {guidance.headline}")
    if not guidance.choices:
        lines.append("  No operational blockers — proceed with the normal workflow.")
        return "\n".join(lines) + "\n"
    lines.append("")
    for i, c in enumerate(guidance.choices, 1):
        tag = " [recommended]" if c.recommended else ""
        lines.append(f"  {i}. {c.title}{tag}  (risk: {c.risk.value})")
        lines.append(f"     {c.rationale}")
        if c.exact_command:
            lines.append(f"     $ {c.exact_command}")
        elif c.requires_human:
            lines.append("     (human action required — no safe command to auto-run)")
        if c.references_affordance:
            lines.append(f"     → see dashboard affordance [{c.references_affordance}]")
    if guidance.affordance is not None:
        # Emit the dashboard pointer exactly once per response through the shared
        # dedup helper, keyed on how many choices need a human (AC5 / codex F010
        # i1). The helper returns None when nothing needs a human, so an all-clear
        # response shows no pointer.
        from dontpanic_orchestrate import dashboard

        human_required = sum(1 for c in guidance.choices if c.requires_human)
        hint = dashboard.render_dashboard_hint_once(
            guidance.affordance.as_status(), human_required_count=human_required
        )
        if hint is not None:
            lines.append("")
            lines.append(f"  Dashboard: {hint}")
    return "\n".join(lines) + "\n"


# ─────────────────────────────── live collector ────────────────────────────


def collect_dashboard_affordance(*, url: str | None = None) -> DashboardAffordance:
    """Build the response-level affordance. ``url`` (when a dashboard singleton
    is known to be running) yields the active-URL form; otherwise the start
    command form.

    F010 step 6: when the caller does not thread a ``url``, this routes through
    the single :func:`dashboard.dashboard_status` helper to auto-detect a running
    singleton — rather than re-implementing dashboard discovery here — so the
    what-now affordance and the config-inventory hint agree on whether a
    dashboard is live. Detection is best-effort: any failure degrades to the
    not-running (start-command) form."""
    if not url:
        try:
            from dontpanic_orchestrate import dashboard

            status = dashboard.dashboard_status()
            if status.is_running and status.url:
                url = status.url
        except Exception:  # noqa: BLE001 — detection is advisory; degrade to "not running"
            url = None
    if url:
        return DashboardAffordance(is_running=True, url=url)
    return DashboardAffordance(is_running=False)


def blocked_feature_ids(plan_dir: Path) -> list[str]:
    """Return the feature IDs the dashboard/CLI should evaluate for guidance.

    Finding 1: the dashboard must surface guidance for the ACTUAL blocked
    feature(s), not a hard-coded ``F001``. Reads ``features.json`` and returns
    every feature whose ``passes`` is not ``True`` (still in flight), preserving
    file order. Falls back to ``["F001"]`` when features.json is missing or
    unreadable so the collector always has at least one feature to evaluate.
    """
    import json

    feats_path = Path(plan_dir) / "features.json"
    try:
        data = json.loads(feats_path.read_text())
    except (OSError, ValueError):
        return ["F001"]
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        return ["F001"]
    ids = [
        str(f["id"])
        for f in features
        if isinstance(f, dict) and f.get("id") and f.get("passes") is not True
    ]
    return ids or ["F001"]


def collect_state(
    plan_dir: Path,
    *,
    plan_id: str,
    feature_id: str | None = None,
    dashboard_url: str | None = None,
) -> Guidance:
    """Gather live state for ``dontpanic what-now`` and build the guidance.

    Reads (never writes): gate-state for pre_merge, the latest auditor verdict,
    loop-cap iteration counts, quota admission / budget ceiling, and split
    config-home setup state. Anything it cannot determine safely is simply
    omitted rather than guessed (AC7).
    """
    from dontpanic_orchestrate import closeout, gate_pause, plan_loader

    plan_dir = Path(plan_dir).resolve()
    loaded = plan_loader.load(plan_dir)
    feat = feature_id or "F001"

    signoff: SignoffState | None = None
    iteration: IterationState | None = None
    no_progress: NoProgressState | None = None

    # signed_off / pre_merge finalization state.
    audit_paths = closeout._audit_paths_for_feature(plan_dir, feat)
    envelope = closeout._latest_auditor_envelope(audit_paths)
    if envelope is not None:
        verdict = str(envelope.get("audit_status") or envelope.get("verdict") or "")
        if verdict == "signed_off":
            cleared = gate_pause.is_gate_cleared(plan_dir, "pre_merge")
            # AC7 (respects current state): only emit the `approve pre_merge`
            # command when the gate is actually pending — mirror the CLI's
            # acceptance rule (currently in pause_gates OR the canonical gate of
            # the persisted pending_stage). Otherwise approve would exit 2.
            compat = gate_pause.load_gate_state_compat(plan_dir)
            pending = gate_pause.is_gate_currently_pending(plan_dir, "pre_merge") or (
                compat.pending_stage is not None
                and "pre_merge" == compat.pending_stage
            )
            signoff = SignoffState(
                feature_id=feat,
                verdict=verdict,
                pre_merge_cleared=cleared,
                pre_merge_pending=bool(pending) and not cleared,
            )

    # iteration / loop-cap state.
    max_iters = _read_max_iterations(loaded)
    if max_iters is not None and signoff is None:
        used = _count_fix_iterations(audit_paths)
        iteration = IterationState(max_iterations=max_iters, iterations_used=used)

    # quota-family blocker (Finding 3): a single hard budget ceiling, soft
    # admission-threshold mismatch, or config-cause cooldown — at most one.
    quota_cooldown, budget_ceiling, admission_threshold = _collect_quota_family(
        loaded, audit_paths
    )

    # setup/doctor state (F012): the full setup surface F007's builder can
    # emit — missing registration, stale onboarding, unsupported roles,
    # doctor --agent / --project, agent brief, and split config homes — all
    # derived deterministically and read-only, without a paid call.
    setup = _collect_setup(plan_dir)

    # active breakers → no-progress style guidance.
    for breaker in gate_pause.active_breakers(plan_dir):
        if "no_progress" in breaker or "diminishing" in breaker:
            no_progress = NoProgressState(
                breaker_name=breaker,
                detail="repeated rounds produced no new progress signal.",
            )
            break

    dashboard = collect_dashboard_affordance(url=dashboard_url)
    return build_guidance(
        plan_id=plan_id,
        feature_id=feat,
        quota_cooldown=quota_cooldown,
        budget_ceiling=budget_ceiling,
        admission_threshold=admission_threshold,
        iteration=iteration,
        signoff=signoff,
        no_progress=no_progress,
        setup=setup,
        dashboard=dashboard,
    )


def _read_max_iterations(loaded: Any) -> int | None:
    plan = getattr(loaded, "plan", loaded)
    caps = getattr(plan, "loop_caps", None)
    if caps is None:
        return None
    v = caps.get("max_iterations") if isinstance(caps, dict) else getattr(caps, "max_iterations", None)
    return int(v) if isinstance(v, int) else None


def _count_fix_iterations(audit_paths: list[Path]) -> int:
    """Highest auditor iteration index seen = fix iterations consumed."""
    import json

    highest = -1
    for p in audit_paths:
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if data.get("agent_role") == "auditor":
            it = data.get("iteration")
            if isinstance(it, int):
                highest = max(highest, it)
    return highest + 1 if highest >= 0 else 0


def _collect_quota_family(
    loaded: Any, audit_paths: list[Path]
) -> tuple[
    QuotaCooldownState | None, BudgetCeilingState | None, AdmissionThresholdState | None
]:
    """Resolve the single live quota-family blocker (Finding 3).

    Reads the same ``quota_state.json`` three consumers share and classifies it
    into AT MOST ONE typed state, by priority:

      1. **Budget ceiling** — a hard per-window cap was TRIPPED
         (``check_budget_ceiling``). Surfaces the native observed/cap figures.
      2. **Admission threshold** — usage exceeds the soft defer threshold with a
         numeric observed_pct and no terminal config cause. This is the
         admission-threshold mismatch case.
      3. **Cooldown** — a config-cause defer (caps_file_missing /
         calibration_required / unit_mismatch …) where the percentage is not the
         operative signal.

    Returning one (not several) avoids double-emitting overlapping guidance for
    the same agent. AC7: no fabricated wait-until / raise targets — the live
    ``QuotaCheck`` exposes neither, so they stay unset.
    """
    from dontpanic_orchestrate import circuit_breakers, quota_admission

    agents = (
        getattr(getattr(loaded, "plan", loaded), "agents_required", None)
        or ["claude", "codex"]
    )

    # 1. hard budget ceiling (TRIPPED window).
    try:
        ceiling = circuit_breakers.check_budget_ceiling(audit_paths, None)
    except Exception:
        ceiling = None
    if (
        ceiling is not None
        and ceiling.kind == circuit_breakers.BudgetCeilingKind.TRIPPED
        and ceiling.agent is not None
    ):
        return (
            None,
            BudgetCeilingState(
                agent=ceiling.agent,
                observed_native=ceiling.observed_native,
                cap=ceiling.cap,
                unit=ceiling.observed_unit or ceiling.cap_unit,
                window=ceiling.window,
            ),
            None,
        )

    # 2/3. soft threshold vs config-cause cooldown.
    try:
        check = quota_admission.evaluate_quota_threshold(agents)
    except Exception:
        return None, None, None
    if not check.over_threshold or check.offending_agent is None:
        return None, None, None
    if check.cause:
        return (
            QuotaCooldownState(
                agent=check.offending_agent,
                observed_pct=check.observed_pct,
                threshold=check.threshold,
                cause=check.cause,
            ),
            None,
            None,
        )
    # Numeric over-threshold with no terminal cause → admission-threshold mismatch.
    return (
        None,
        None,
        AdmissionThresholdState(
            agent=check.offending_agent,
            observed_pct=check.observed_pct,
            threshold=check.threshold,
        ),
    )


def _collect_setup(plan_dir: Path) -> SetupNeeds | None:
    """Derive the FULL setup/doctor surface F007's builder can emit (F012).

    Every signal is read-only and deterministic — nothing here spends a paid
    agent call or mutates the filesystem, and anything that cannot be resolved
    safely is omitted (AC7) rather than guessed:

    - **split config homes** — global ``~/.dontpanic`` vs ``~/.jarvis``
      split-brain via :func:`home_reconcile.classify_homes`.
    - **doctor --agent** — a HARD-failing registered doctor check
      (:func:`config.doctor_registry.run_all_checks`); soft ``warn`` results
      (e.g. the Python-version advisory) are intentionally ignored so guidance
      is not noisy.
    - project-scoped signals, resolved through the registry
      (:func:`project_config.find_project_for_plan_dir`):
        * **stale onboarding** — the project's managed ``AGENTS.md`` block has
          drifted in onboarding generator version or was tampered.
        * **agent brief** — the managed block's embedded brief body no longer
          matches the freshly generated brief (its facts drifted) while the
          onboarding layout is current.
        * **doctor --project** — the per-project config exists but fails to
          load (invalid / degraded), so it needs validation.
        * **unsupported roles** — a resolved role maps to an operator-only
          agent with no executor.
    - **missing registration** — the plan lives in a git repo that is NOT a
      registered project; the repo root supplies the path (and a name when the
      directory name is a valid project name).
    """
    missing_project = False
    project_name: str | None = None
    project_path: str | None = None
    stale_onboarding = False
    stale_brief = False
    stale_project_config = False
    unsupported_role: str | None = None
    unsupported_role_name: str | None = None

    split_config_homes = _detect_split_homes()
    human_required_config = _detect_agent_doctor()

    resolved = _resolve_project_for_plan(plan_dir)
    if resolved is not None:
        proj_path, project_name = resolved
        project_path = str(proj_path)
        stale_onboarding, stale_brief = _detect_onboarding_drift(proj_path)
        stale_project_config = _detect_stale_project_config(proj_path)
        unsupported_role, unsupported_role_name = _detect_unsupported_role(proj_path)
    else:
        missing = _detect_missing_project(plan_dir)
        if missing is not None:
            missing_project = True
            miss_path, project_name = missing
            project_path = str(miss_path)

    if not (
        split_config_homes
        or human_required_config
        or missing_project
        or stale_onboarding
        or stale_brief
        or stale_project_config
        or unsupported_role
    ):
        return None
    return SetupNeeds(
        missing_project=missing_project,
        project_name=project_name,
        project_path=project_path,
        stale_onboarding=stale_onboarding,
        stale_brief=stale_brief,
        unsupported_role=unsupported_role,
        unsupported_role_name=unsupported_role_name,
        split_config_homes=split_config_homes,
        stale_project_config=stale_project_config,
        human_required_config=human_required_config,
    )


def _detect_split_homes() -> bool:
    """Global ``~/.dontpanic`` vs ``~/.jarvis`` split-brain (the original
    Finding-3 signal). True when the legacy home strands files the single-home
    resolver won't pick (``legacy_only``) or the two homes diverged."""
    from dontpanic_orchestrate import home_reconcile

    try:
        states = home_reconcile.classify_homes()
        legacy_only, divergent = home_reconcile.split_brain_summary(states)
    except Exception:
        return False
    return bool(legacy_only or divergent)


def _detect_agent_doctor() -> str | None:
    """Return a human-required-config description when the AGENT-level
    onboarding doctor HARD-fails, else ``None``.

    This derives from the SAME surface the CLI ``dontpanic doctor --agent`` runs
    — :func:`dontpanic_doctor.check_agent_onboarding` — so the live what-now/
    dashboard path and the doctor command never disagree (codex F012-i1
    finding). That surface covers CLI invocability, agent-manifest validity,
    worker executors, supported-command coverage, global ``roles.*`` validity,
    and the config-home split. ``skip_auth=True`` keeps it read-only/fast (no
    auth probes run in this check anyway).

    Only a HARD fail (``not ok and not warn``) escalates to a doctor choice.
    Soft ``warn`` results — the config-home split (which has its own
    :func:`_detect_split_homes` reconcile choice) and the advisory
    command-set drift — must not raise a doctor choice on every invocation."""
    import dontpanic_doctor

    try:
        results = dontpanic_doctor.check_agent_onboarding(skip_auth=True)
    except Exception:
        return None
    failing = [
        r
        for r in results
        if not getattr(r, "ok", True) and not getattr(r, "warn", False)
    ]
    if not failing:
        return None
    first = failing[0]
    detail = (getattr(first, "message", "") or "").strip()
    return (
        f"Agent-level doctor check {first.name!r} reported FAIL"
        + (f": {detail}." if detail else ".")
    )


def _resolve_project_for_plan(plan_dir: Path) -> tuple[Path, str] | None:
    """Registry-driven resolution of the project containing ``plan_dir`` (path,
    registered name), or ``None``. Read-only; never raises."""
    from dontpanic_orchestrate import project_config

    try:
        return project_config.find_project_for_plan_dir(plan_dir)
    except Exception:
        return None


def _detect_onboarding_drift(project_path: Path) -> tuple[bool, bool]:
    """Classify the project's managed ``AGENTS.md`` block staleness into
    ``(stale_onboarding, stale_brief)``.

    A present-and-fresh block yields ``(False, False)``. Otherwise the project
    needs (re-)onboarding, mirroring what ``dontpanic doctor --project`` reports
    for the same project (codex F012-i1 finding):

    - **Missing ``AGENTS.md``** or **absent managed block** — the repo was never
      onboarded; ``projects add ... --onboard --force --yes`` writes the block.
      doctor --project surfaces this as an onboarding WARN with that exact
      remediation, so the live path must derive ``stale_onboarding`` too rather
      than stay silent → ``(True, False)``.
    - **Generator-version mismatch** (or an in-marker tamper where the stored
      hash still matches the current body) is onboarding-layout drift →
      ``stale_onboarding``.
    - An otherwise-current block whose stored hash no longer matches the freshly
      rendered brief body means the embedded brief's facts drifted →
      ``stale_brief``.

    ``stale_onboarding`` and ``stale_brief`` are kept mutually exclusive so
    guidance emits one remediation, not two. An unreadable file (genuine I/O
    error) is doctor's hard FAIL ("check file permissions"), not a re-onboard —
    no builder choice covers it, so it is omitted (AC7) → ``(False, False)``."""
    from dontpanic_orchestrate import agent_brief
    from dontpanic_orchestrate import repo_onboarding as ro

    agents_md = project_path / ro.AGENTS_FILENAME
    if not agents_md.is_file():
        return True, False  # not onboarded — re-onboard writes AGENTS.md + block
    try:
        raw = agents_md.read_bytes()
    except OSError:
        return False, False  # unreadable I/O error — doctor's hard FAIL, not re-onboard
    match = ro._find_block_bytes(raw, ro.BLOCK_AGENTS)
    if match is None:
        return True, False  # no managed block — repo not onboarded
    try:
        body = ro._agents_body(agent_brief.generate_brief())
    except Exception:
        return False, False
    if ro._block_is_fresh_bytes(match, body):
        return False, False
    # Not fresh — classify the drift.
    if match.group("generator") != ro.ONBOARDING_GENERATOR_VERSION.encode("ascii"):
        return True, False  # onboarding layout/version drift → re-onboard
    expected = ro._body_hash(body.strip("\n")).encode("ascii")
    if match.group("hash") != expected:
        return False, True  # block built for an older brief → brief facts drifted
    return True, False  # generator + hash current but body integrity failed → tamper


def _detect_stale_project_config(project_path: Path) -> bool:
    """True when the per-project config FILE exists but fails to load (invalid
    / schema-violating, degraded to ``None``) — it needs ``doctor --project``
    validation. An absent config is the valid zero state, not stale."""
    from dontpanic_orchestrate import project_config

    try:
        cfg_path = project_config.project_config_path(project_path)
        legacy_path = project_config.legacy_project_config_path(project_path)
        present = cfg_path.is_file() or legacy_path.is_file()
        if not present:
            return False
        return project_config.load_project_config(project_path) is None
    except Exception:
        return False


def _detect_unsupported_role(project_path: Path) -> tuple[str | None, str | None]:
    """Return ``(agent, role)`` for the first resolved role whose effective
    agent has no executor (operator-only — cannot be dispatched), else
    ``(None, None)``. Defaults resolve to registered executors, so this only
    fires when the project config explicitly assigns an operator-only agent."""
    from dontpanic_orchestrate import agent_surface

    try:
        roles = agent_surface.resolve_roles(project_path)
    except Exception:
        return None, None
    for role, agent in roles.items():
        try:
            if not agent_surface.is_worker_capable(agent):
                return agent, role
        except Exception:
            continue
    return None, None


def _detect_missing_project(plan_dir: Path) -> tuple[Path, str | None] | None:
    """When no registered project contains ``plan_dir``, locate the enclosing
    git repo root (walking up for ``.git``) and report it as an unregistered
    project: ``(repo_root, name_or_None)``. The name is the repo directory name
    only when it is a valid project name (so ``projects add`` is runnable);
    otherwise ``None`` so the builder marks the choice human-required. Returns
    ``None`` when no git repo encloses the plan (nothing safe to suggest)."""
    from dontpanic_orchestrate import projects_registry

    try:
        candidate = Path(plan_dir).resolve()
        repo_root: Path | None = None
        for parent in (candidate, *candidate.parents):
            if (parent / ".git").exists():
                repo_root = parent
                break
        if repo_root is None:
            return None
        name = repo_root.name
        if not projects_registry.PROJECT_NAME_PATTERN.fullmatch(name):
            name = None
        return repo_root, name
    except Exception:
        return None


__all__ = [
    "ActionChoice",
    "AdmissionThresholdState",
    "BudgetCeilingState",
    "DASHBOARD_AFFORDANCE_ITEM_ID",
    "DASHBOARD_START_COMMAND",
    "DashboardAffordance",
    "Guidance",
    "IterationState",
    "NoProgressState",
    "QuotaCooldownState",
    "Risk",
    "SetupNeeds",
    "SignoffState",
    "build_admission_threshold_choices",
    "build_budget_ceiling_choices",
    "build_guidance",
    "build_iteration_choices",
    "build_no_progress_choices",
    "build_quota_cooldown_choices",
    "build_setup_choices",
    "build_signoff_choices",
    "blocked_feature_ids",
    "collect_dashboard_affordance",
    "collect_state",
    "render_text",
]
