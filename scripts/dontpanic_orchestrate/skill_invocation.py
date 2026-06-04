"""Plan 2026-05-30-001 F011 — skill-invocation rubric CORE engine (D060 split).

Two layers, both pure-by-design:

1. **Frontmatter schema** — an optional ``invocation:`` block in a skill's
   ``SKILL.md`` declaring how DontPanic may invoke it (``mode``, lifecycle
   stages, required inputs, risk flags, evidence target, optional command
   template). :func:`parse_invocation` validates the block via Pydantic and is
   a strict no-op for skills that lack it — adding the schema never breaks a
   metadata-less skill (AC1).

2. **Pure evaluator** — :func:`evaluate` reads an injected
   :class:`SkillInvocationContext` (applicable-skills output, per-skill
   invocation metadata, plan/goal metadata, changed files, config-inventory
   summaries, budget state, lifecycle stage, available commands, and an
   *injected* ``is_command_allowlisted`` predicate owned by F015) and emits
   typed :class:`SkillAction` records. It performs **no I/O, no network, no
   execution** — recommendation only (AC2).

Deterministic risk precedence (AC6), in strict evaluation order — the order
below is exactly the order :func:`_evaluate_one` applies, so the documented rule
and the code never diverge:

  1. F007 inapplicable → ``not_applicable``. Present-but-invalid metadata →
     diagnostic ``approval_required`` (invalid metadata is NEVER treated as "no
     metadata").
  2. Metadata-less applicable skill → ``suggest`` (never ``auto_run``) (AC3).
  3. ``never_suggest`` opt-out wins outright — the skill never surfaces
     (``not_applicable``); the noisy/toolkit opt-out (AC12).
  4. Lifecycle-stage gating → ``not_applicable`` outside declared stages.
  5. Contradictory metadata: an *auto* mode declared alongside an auto-blocking
     risk flag (external writes, paid actions, indefinite loops, credentialed
     production reads, network access, repo mutation) → diagnostic
     ``approval_required`` rather than silently trusting the unsafe declaration.
  6. ``never_auto`` → ``suggest`` (never ``auto_run``). The acceptance rule
     "explicit never_auto/never_suggest wins" is taken literally: ``never_auto``
     resolves BEFORE the missing-input check, so it downgrades to ``suggest``
     even when required inputs are absent (the missing inputs are still surfaced
     on the action for the operator, but the recommendation is ``suggest``, not
     ``blocked_missing_inputs``). This mirrors ``never_suggest`` winning outright
     in rule 3.
  7. Missing required inputs → ``blocked_missing_inputs`` for the remaining
     execution-capable modes (``auto_*``, ``approval_required``, ``suggest``):
     a skill that cannot obtain its required inputs cannot run, so the missing
     input is surfaced rather than a misleading "ready to suggest".
  8. ``approval_required`` → ``approval_required``.
  9. ``suggest`` → ``suggest``.
 10. Auto mode, no unsafe flags, inputs satisfied → ``auto_run`` ONLY when
     budget permits AND F015's injected allowlist predicate clears the exact
     command; anything short downgrades to ``suggest``.

Every declared risk flag blocks ``auto_run`` regardless of declared mode: a risk
flag on a non-auto mode is already non-auto, and a risk flag on an auto mode is
contradictory (rule 5). ``exact_command`` is populated ONLY on the ``auto_run``
path — the single point where the command is verified safe to surface for
execution (allowlisted, budget-ok, no risk, inputs present); every other path
leaves it ``None`` so an unsafe/un-allowlisted command is never handed out
(``exact_command``-when-safe, AC2).

Skills without invocation metadata default to ``suggest`` (when applicable) or
``not_applicable`` and are **never** ``auto_run`` (AC3).

The allowlist itself is NOT owned here — F015 supplies
``SkillInvocationContext.is_command_allowlisted``; this engine only classifies
``auto_run``-eligible vs ``suggest`` based on that predicate's result.

Purity contract (auditor verifies via source grep): no ``subprocess`` import,
no ``logging.getLogger`` call, no ``print(`` call, no network, no execution.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1.0"


# ───────────────────────────  enums  ───────────────────────────


class InvocationMode(str, Enum):
    """Declared invocation mode in ``invocation.mode``."""

    AUTO_READONLY = "auto_readonly"
    AUTO_SAFE = "auto_safe"
    SUGGEST = "suggest"
    APPROVAL_REQUIRED = "approval_required"
    NEVER_AUTO = "never_auto"
    NEVER_SUGGEST = "never_suggest"


#: Modes that claim eligibility for unattended auto-run.
_AUTO_MODES: frozenset[InvocationMode] = frozenset(
    {InvocationMode.AUTO_READONLY, InvocationMode.AUTO_SAFE}
)


class RiskFlag(str, Enum):
    """Risk declarations in ``invocation.risk_flags``. Every one of these
    blocks ``auto_run`` (AC6) — they are the auto-blocking flag set."""

    EXTERNAL_WRITES = "external_writes"
    PAID = "paid"
    INDEFINITE_LOOP = "indefinite_loop"
    CREDENTIALED_PRODUCTION_READ = "credentialed_production_read"
    NETWORK_ACCESS = "network_access"
    REPO_MUTATION = "repo_mutation"


#: Every risk flag blocks auto_run regardless of declared mode (AC6).
_AUTO_BLOCKING_FLAGS: frozenset[RiskFlag] = frozenset(RiskFlag)


class Recommendation(str, Enum):
    """The five recommendation values the evaluator may emit (AC2)."""

    AUTO_RUN = "auto_run"
    SUGGEST = "suggest"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED_MISSING_INPUTS = "blocked_missing_inputs"
    NOT_APPLICABLE = "not_applicable"


class Risk(str, Enum):
    """Coarse risk band attached to a :class:`SkillAction`."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ───────────────────────────  Pydantic frontmatter side  ───────────────────────────


class InvocationModel(BaseModel):
    """Pydantic shape of the optional ``invocation:`` SKILL.md block.

    ``extra='forbid'`` so a typo'd key surfaces as a validation error rather
    than being silently ignored — contradictory/garbled metadata must never be
    trusted (AC6).

    ``evidence_target`` is REQUIRED for the auto-eligible modes
    (``auto_readonly``/``auto_safe``): those are the only modes the evaluator can
    classify as ``auto_run``, and an unattended run must declare where its
    evidence lands. The human-in-the-loop modes (``suggest``,
    ``approval_required``, ``never_auto``, ``never_suggest``) may omit it — these
    are the narrow modes where omission is allowed (AC1)."""

    model_config = ConfigDict(extra="forbid")

    mode: InvocationMode
    lifecycle_stages: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    evidence_target: str | None = None
    command_template: str | None = None

    @field_validator("lifecycle_stages", "required_inputs")
    @classmethod
    def _no_blank_strings(cls, value: list[str]) -> list[str]:
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("entries must be non-empty strings")
        return value

    @model_validator(mode="after")
    def _auto_modes_require_evidence_target(self) -> InvocationModel:
        if self.mode in _AUTO_MODES and (
            self.evidence_target is None or not self.evidence_target.strip()
        ):
            raise ValueError(
                "evidence_target is required for auto-eligible modes "
                f"({', '.join(sorted(m.value for m in _AUTO_MODES))})"
            )
        return self


# ───────────────────────────  evaluator dataclasses  ───────────────────────────


@dataclass(frozen=True)
class Invocation:
    """Validated, hashable invocation rubric for a single skill. Built from an
    :class:`InvocationModel`; carried inside the injected context."""

    mode: InvocationMode
    lifecycle_stages: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    risk_flags: tuple[RiskFlag, ...] = ()
    evidence_target: str | None = None
    command_template: str | None = None

    @classmethod
    def from_model(cls, model: InvocationModel) -> Invocation:
        return cls(
            mode=model.mode,
            lifecycle_stages=tuple(model.lifecycle_stages),
            required_inputs=tuple(model.required_inputs),
            risk_flags=tuple(model.risk_flags),
            evidence_target=model.evidence_target,
            command_template=model.command_template,
        )


@dataclass(frozen=True)
class SkillRubric:
    """One skill as seen by the evaluator: its name, whether F007 marked it
    applicable, and its parsed invocation metadata.

    * ``invocation is None`` → the skill declared no ``invocation:`` block.
    * ``invalid_reason`` set → the skill declared a block that FAILED schema
      validation; the evaluator emits a diagnostic rather than trusting it.
    """

    skill_name: str
    applicable: bool = True
    invocation: Invocation | None = None
    invalid_reason: str | None = None


@dataclass(frozen=True)
class SkillInvocationContext:
    """Pure, injected input to :func:`evaluate`. No live handles, no I/O — the
    caller resolves applicable-skills output, config-inventory summaries,
    budget state, and the F015 allowlist predicate up front and passes the
    resolved values in.

    Fields:
      * ``skills`` — per-skill rubrics (applicability + invocation metadata).
      * ``lifecycle_stage`` — the current orchestration stage (e.g.
        ``"implementation"``); used to gate stage-scoped skills.
      * ``goal_type`` / ``plan_surfaces`` / ``changed_files`` — plan metadata
        carried for reason text and future scoring (advisory).
      * ``available_commands`` — commands the current surface can run.
      * ``provided_inputs`` — named inputs currently satisfiable; a skill's
        ``required_inputs`` not in this set are ``missing_inputs``.
      * ``config_summaries`` — F008 config-inventory summaries (advisory).
      * ``budget_ok`` — whether budget state permits an auto-run at all; a
        false value blocks auto_run (paid/looping skills downgrade).
      * ``is_command_allowlisted`` — INJECTED F015 predicate. The engine does
        not own the allowlist; it consults this to decide auto_run vs suggest
        for an otherwise-safe command.
    """

    skills: tuple[SkillRubric, ...] = ()
    lifecycle_stage: str | None = None
    goal_type: str | None = None
    plan_surfaces: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    available_commands: tuple[str, ...] = ()
    provided_inputs: tuple[str, ...] = ()
    config_summaries: Mapping[str, Any] = field(default_factory=dict)
    budget_ok: bool = True
    is_command_allowlisted: Callable[[str], bool] = lambda _command: False


@dataclass(frozen=True)
class SkillAction:
    """Typed recommendation record emitted per skill (AC2)."""

    skill_name: str
    recommendation: Recommendation
    reason: str
    risk: Risk
    missing_inputs: tuple[str, ...] = ()
    #: Populated ONLY on the ``auto_run`` path — the one place the command is
    #: verified safe to surface for execution (allowlisted, budget-ok, no risk
    #: flags, inputs satisfied). Every other recommendation leaves this ``None``
    #: so an unsafe or un-allowlisted command is never handed out
    #: (``exact_command``-when-safe, AC2).
    exact_command: str | None = None
    evidence_target: str | None = None
    approval_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["recommendation"] = self.recommendation.value
        data["risk"] = self.risk.value
        data["missing_inputs"] = list(self.missing_inputs)
        return data


# ───────────────────────────  frontmatter parsing (no-op safe)  ───────────────────────────


def parse_invocation(
    frontmatter: Mapping[str, Any],
) -> tuple[Invocation | None, str | None]:
    """Validate the optional ``invocation:`` block in a SKILL.md frontmatter
    mapping.

    Returns:
      * ``(None, None)`` when no ``invocation:`` key is present — the strict
        no-op path that keeps metadata-less skills working (AC1).
      * ``(Invocation, None)`` when the block validates.
      * ``(None, reason)`` when a block IS present but fails validation. The
        caller MUST treat this as a contradictory/untrusted declaration (the
        evaluator emits a diagnostic), never as "no metadata".
    """

    if "invocation" not in frontmatter:
        return None, None
    block = frontmatter["invocation"]
    if not isinstance(block, Mapping):
        return None, f"invocation is not a mapping (got {type(block).__name__})"
    try:
        model = InvocationModel.model_validate(dict(block))
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ()))
        msg = first.get("msg", "validation failed")
        suffix = f" at {loc}" if loc else ""
        return None, f"invocation failed validation{suffix}: {msg}"
    return Invocation.from_model(model), None


def load_rubric(
    skill_name: str,
    frontmatter: Mapping[str, Any],
    *,
    applicable: bool = True,
) -> SkillRubric:
    """Convenience: build a :class:`SkillRubric` from a skill's frontmatter,
    routing a validation failure into ``invalid_reason`` (so the evaluator can
    emit a diagnostic) rather than discarding it as metadata-less."""

    invocation, reason = parse_invocation(frontmatter)
    return SkillRubric(
        skill_name=skill_name,
        applicable=applicable,
        invocation=invocation,
        invalid_reason=reason,
    )


# ───────────────────────────  evaluator internals  ───────────────────────────


def _risk_band(flags: Sequence[RiskFlag]) -> Risk:
    return Risk.HIGH if flags else Risk.LOW


def _missing_inputs(inv: Invocation, ctx: SkillInvocationContext) -> tuple[str, ...]:
    provided = set(ctx.provided_inputs)
    return tuple(i for i in inv.required_inputs if i not in provided)


def _evaluate_one(rubric: SkillRubric, ctx: SkillInvocationContext) -> SkillAction:
    name = rubric.skill_name

    # (0) F007 says this skill does not apply to the plan/surface at all.
    if not rubric.applicable:
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.NOT_APPLICABLE,
            reason="not in applicable-skills output for this plan",
            risk=Risk.LOW,
        )

    # (1) Present-but-invalid metadata is a contradiction, not "no metadata".
    #     Never silently trust it — emit a diagnostic requiring approval (AC6).
    if rubric.invalid_reason is not None:
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.APPROVAL_REQUIRED,
            reason=f"contradictory metadata: {rubric.invalid_reason}",
            risk=Risk.HIGH,
            approval_required=True,
        )

    inv = rubric.invocation

    # (2) Metadata-less applicable skill → suggest; NEVER auto_run (AC3).
    if inv is None:
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.SUGGEST,
            reason="no invocation metadata; defaulting to suggest (never auto-run)",
            risk=Risk.LOW,
        )

    # (3) never_suggest opt-out wins outright — the skill never surfaces (AC12).
    if inv.mode is InvocationMode.NEVER_SUGGEST:
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.NOT_APPLICABLE,
            reason="opted out of recommendations via never_suggest",
            risk=Risk.LOW,
            evidence_target=inv.evidence_target,
        )

    # (4) Lifecycle-stage gating: a stage-scoped skill outside its stage is
    #     not applicable right now (advisory, deterministic).
    if (
        inv.lifecycle_stages
        and ctx.lifecycle_stage is not None
        and ctx.lifecycle_stage not in inv.lifecycle_stages
    ):
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.NOT_APPLICABLE,
            reason=(
                f"lifecycle stage {ctx.lifecycle_stage!r} not in declared "
                f"stages {list(inv.lifecycle_stages)}"
            ),
            risk=Risk.LOW,
            evidence_target=inv.evidence_target,
        )

    unsafe_flags = tuple(f for f in inv.risk_flags if f in _AUTO_BLOCKING_FLAGS)
    missing = _missing_inputs(inv, ctx)
    declared_auto = inv.mode in _AUTO_MODES

    # (5) Contradictory metadata: an auto mode declared alongside an
    #     auto-blocking risk flag. Emit a diagnostic rather than trusting the
    #     unsafe declaration (AC6).
    if declared_auto and unsafe_flags:
        flag_names = [f.value for f in unsafe_flags]
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.APPROVAL_REQUIRED,
            reason=(
                f"contradictory metadata: mode={inv.mode.value} declares "
                f"auto-run but risk flags {flag_names} block auto-run"
            ),
            risk=Risk.HIGH,
            missing_inputs=missing,
            evidence_target=inv.evidence_target,
            approval_required=True,
        )

    # (6) Explicit never_auto wins outright (AC6: "explicit never_auto/
    #     never_suggest wins"). It resolves BEFORE the missing-input check and
    #     downgrades to suggest (never auto_run), mirroring never_suggest in
    #     rule 3. Missing inputs are still surfaced on the action so the operator
    #     sees them, but the recommendation stays suggest rather than
    #     blocked_missing_inputs. exact_command stays None: a suggestion is
    #     human-driven, and surfacing a possibly-unsafe command would violate
    #     exact_command-when-safe.
    if inv.mode is InvocationMode.NEVER_AUTO:
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.SUGGEST,
            reason="declared never_auto; suggesting rather than auto-running",
            risk=_risk_band(unsafe_flags),
            missing_inputs=missing,
            evidence_target=inv.evidence_target,
        )

    # (7) Missing required inputs block execution for the remaining
    #     execution-capable modes (auto_*, approval_required, suggest) (AC6).
    if missing:
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.BLOCKED_MISSING_INPUTS,
            reason=f"missing required inputs: {list(missing)}",
            risk=_risk_band(unsafe_flags),
            missing_inputs=missing,
            evidence_target=inv.evidence_target,
        )

    # (8) Explicit approval_required mode. No exact_command — the command is not
    #     cleared for execution, so it is not surfaced as runnable.
    if inv.mode is InvocationMode.APPROVAL_REQUIRED:
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.APPROVAL_REQUIRED,
            reason="declared approval_required",
            risk=_risk_band(unsafe_flags),
            evidence_target=inv.evidence_target,
            approval_required=True,
        )

    # (9) Explicit suggest mode. No exact_command (see rule 7).
    if inv.mode is InvocationMode.SUGGEST:
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.SUGGEST,
            reason="declared suggest",
            risk=_risk_band(unsafe_flags),
            evidence_target=inv.evidence_target,
        )

    # (10) Auto mode, no unsafe flags, no missing inputs. Auto-run is only
    #      reachable when budget permits AND F015's allowlist predicate clears
    #      the exact command. Anything short of that downgrades to suggest —
    #      the engine never auto-runs an un-allowlisted command (AC6/D060).
    #      (declared_auto is necessarily True here; all other modes returned.)
    command = inv.command_template
    if command is None:
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.SUGGEST,
            reason="auto mode but no command_template to allowlist; suggesting",
            risk=Risk.LOW,
            evidence_target=inv.evidence_target,
        )
    if not ctx.budget_ok:
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.SUGGEST,
            reason="auto mode but budget state forbids auto-run; suggesting",
            risk=Risk.LOW,
            evidence_target=inv.evidence_target,
        )
    if not ctx.is_command_allowlisted(command):
        return SkillAction(
            skill_name=name,
            recommendation=Recommendation.SUGGEST,
            reason="command not on the F015 auto-run allowlist; suggesting",
            risk=Risk.LOW,
            evidence_target=inv.evidence_target,
        )
    return SkillAction(
        skill_name=name,
        recommendation=Recommendation.AUTO_RUN,
        reason=f"{inv.mode.value} + inputs satisfied + command allowlisted",
        risk=Risk.LOW,
        exact_command=command,
        evidence_target=inv.evidence_target,
    )


# ───────────────────────────  public API  ───────────────────────────


def evaluate(ctx: SkillInvocationContext) -> list[SkillAction]:
    """Pure evaluator (AC2). Emits one :class:`SkillAction` per skill in the
    context, in name-sorted order for determinism. No I/O, no network, no
    execution — recommendation only."""

    actions = [_evaluate_one(r, ctx) for r in ctx.skills]
    actions.sort(key=lambda a: a.skill_name)
    return actions


def recommendations(ctx: SkillInvocationContext) -> list[SkillAction]:
    """Convenience over :func:`evaluate` returning only surfaceable actions —
    ``not_applicable`` (including ``never_suggest`` opt-outs) is filtered out so
    F016 surfaces never render noisy/inapplicable skills (AC12)."""

    return [
        a
        for a in evaluate(ctx)
        if a.recommendation is not Recommendation.NOT_APPLICABLE
    ]
