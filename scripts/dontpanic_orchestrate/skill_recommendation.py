"""Plan 2026-05-30-001 F016 — skill recommendation SURFACES + migration.

F011 built the pure :mod:`skill_invocation` evaluator (emits typed
:class:`~dontpanic_orchestrate.skill_invocation.SkillAction` records) and F015
owns the auto-run allowlist artifact. This slice is the *surface* layer over
both: it exposes the F011/F015 SkillAction set through ``dontpanic skills
recommend`` and the dashboard with IDENTICAL data, routes missing required
inputs through F007's :class:`~dontpanic_orchestrate.operations_guidance.\
ActionChoice` / dashboard-hint dedup as ONE concise action, uses the F008
config inventory to explain unavailable credentials/binaries/capabilities, and
adds a migration path that proposes starting rubrics for high-value skills that
lack invocation metadata — WITHOUT blocking core use.

Design:

* The CLI and the dashboard both serialize ONE :class:`RecommendationReport`
  via :meth:`RecommendationReport.to_dict`, so the two surfaces can never drift
  (AC9). :func:`collect` is the live wiring (reads the plan, the skills dir, the
  allowlist artifact, and the F008 inventory); the assembly is otherwise a set
  of pure functions that take resolved inputs so they are trivially testable.
* Missing inputs collapse to ONE :class:`ActionChoice` naming only the missing
  blocker (AC8) — never a per-skill prompting loop.
* F008 inventory items in a non-ok state explain WHY a risk-flagged skill is
  unavailable (AC10) instead of the skill being silently skipped.
* :func:`suggest_rubric` / :func:`skills_missing_rubrics` are the migration path
  (AC11): they propose a safe starting ``invocation:`` block and identify
  high-value metadata-less skills, advisory only.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import operations_guidance as og
from dontpanic_orchestrate.skill_invocation import (
    InvocationMode,
    Recommendation,
    RiskFlag,
    SkillAction,
    SkillInvocationContext,
    SkillRubric,
    load_rubric,
    parse_invocation,
    recommendations,
)

SCHEMA_VERSION = "1.0"

# Map each risk flag to the SPECIFIC F008 config-inventory item id(s) whose
# unavailability would block a skill carrying that flag (AC10). Narrow by design
# (audit finding, codex i0): a flag maps ONLY to the resource it genuinely
# depends on, so a blocked skill never blames an unrelated credential/capability
# (the prior code attached every unavailable secret row to any credential/network
# risk and every unavailable capability row to any external-write/CLI risk,
# misattributing the blocker). The item ids here are the canonical ones emitted
# by :mod:`config_inventory`'s providers.
_RISK_TO_RESOURCE_IDS: dict[RiskFlag, frozenset[str]] = {
    # A paid action dispatches the worker executor → the Anthropic/Claude worker
    # credential is the specific blocker.
    RiskFlag.PAID: frozenset({"secret_anthropic_auth"}),
    # A credentialed production read needs the GCP/Firebase service-account key.
    RiskFlag.CREDENTIALED_PRODUCTION_READ: frozenset({"secret_gcp_sa_key"}),
    # External writes / repo mutation route through a ready adapter — the
    # capabilities/adapters surface is the specific blocker.
    RiskFlag.EXTERNAL_WRITES: frozenset({"capabilities"}),
    RiskFlag.REPO_MUTATION: frozenset({"capabilities"}),
    # network_access alone is connectivity, not a single config credential, so it
    # maps to NO specific inventory item and never blames an unrelated secret. A
    # network skill that also needs a credential declares paid /
    # credentialed_production_read, which carry their own specific mapping above.
    RiskFlag.NETWORK_ACCESS: frozenset(),
    RiskFlag.INDEFINITE_LOOP: frozenset(),
}


def _row_mentions_binary(row: ResourceStatus, binary: str) -> bool:
    """True when an inventory ``row`` plausibly represents ``binary`` (an
    external CLI the skill needs), matched by the binary name appearing in the
    row id or title. Conservative: a coarse DontPanic surface (``capabilities``,
    ``mcp``, …) that does not name the binary is NOT matched, so an external-CLI
    skill never blames an unrelated capability row (AC10)."""
    needle = binary.strip().lower()
    if not needle:
        return False
    return needle in row.id.lower() or needle in row.title.lower()


def external_binary_id(binary: str) -> str:
    """Stable inventory-item id for an external CLI ``binary`` not on PATH.

    Used to synthesize a SPECIFIC capability/inventory blocker (AC10) when a
    skill declares ``applies_to.external_cli`` but the binary is absent and no
    config-inventory provider emits a row that names it — so the missing binary
    is never silently dropped."""
    slug = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in binary.strip().lower())
    return f"capability_external_cli_{slug}"


def _missing_binary_resource(binary: str) -> ResourceStatus:
    """A synthesized capability-scope :class:`ResourceStatus` standing in for an
    external CLI ``binary`` that is not on PATH (AC10). Marked unavailable so
    :func:`explain_blockers` attaches it as the SPECIFIC blocker for the skill."""
    return ResourceStatus(
        id=external_binary_id(binary),
        title=f"external CLI `{binary}`",
        scope="capability",
        status="missing",
        ok=False,
        summary=f"required external CLI `{binary}` not found on PATH",
        safe_command=f"install `{binary}` and ensure it is on your PATH",
    )


def _binary_on_path(binary: str) -> bool:
    """True iff ``binary`` resolves on the current PATH. Thin seam over
    :func:`shutil.which` so tests can drive the missing-binary path
    deterministically via ``binary_on_path`` injection."""
    return shutil.which(binary) is not None

# Stable id/kind for the single missing-input ActionChoice (AC8). Routed through
# the F007 ActionChoice vocabulary so the dashboard renders it like any other
# operations action and the dashboard-hint dedup applies.
MISSING_INPUT_CHOICE_ID = "skills-missing-inputs"
KIND_SKILL_MISSING_INPUT = "skill_missing_input"


# ───────────────────────────── resource (F008) side ─────────────────────────


@dataclass(frozen=True)
class ResourceStatus:
    """A single F008 config-inventory surface, reduced to what the recommender
    needs to explain a blocked skill. Decoupled from
    :class:`config_inventory.InventoryItem` so :func:`explain_blockers` stays a
    pure function tests can drive with hand-built inputs."""

    id: str
    title: str
    scope: str
    status: str
    ok: bool
    summary: str = ""
    safe_command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "scope": self.scope,
            "status": self.status,
            "ok": self.ok,
            "summary": self.summary,
            "safe_command": self.safe_command,
        }


def resources_from_inventory(inventory: Any) -> list[ResourceStatus]:
    """Reduce a :class:`config_inventory.Inventory` to :class:`ResourceStatus`
    rows. ``ok`` is true ONLY for an exactly-OK status — a present-but-
    unconfigured optional integration counts as unavailable so the recommender
    can explain why the dependent skill is blocked (AC10)."""
    from dontpanic_orchestrate import config_inventory as ci

    rows: list[ResourceStatus] = []
    for item in getattr(inventory, "items", ()) or ():
        rows.append(
            ResourceStatus(
                id=item.id,
                title=item.title,
                scope=item.scope.value,
                status=item.status.value,
                ok=item.status is ci.Status.OK,
                summary=item.current_value_summary,
                safe_command=item.safe_command,
            )
        )
    return rows


# ─────────────────────────────── report records ────────────────────────────


@dataclass(frozen=True)
class SkillBlocker:
    """Why one surfaced skill cannot run right now, explained from the F008
    inventory (unavailable credentials/binaries/capabilities) and/or its missing
    required inputs (AC10)."""

    skill_name: str
    missing_inputs: tuple[str, ...] = ()
    unavailable_resources: tuple[ResourceStatus, ...] = ()
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "missing_inputs": list(self.missing_inputs),
            "unavailable_resources": [r.to_dict() for r in self.unavailable_resources],
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class RubricSuggestion:
    """A proposed starting ``invocation:`` block for a metadata-less skill — the
    migration path (AC11). Always SAFE: it never proposes an auto mode, so a
    migrated skill is suggested/approval-gated, never silently auto-run."""

    skill_name: str
    already_has_metadata: bool
    proposed: dict[str, Any]
    yaml_block: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "already_has_metadata": self.already_has_metadata,
            "proposed": self.proposed,
            "yaml_block": self.yaml_block,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class RecommendationReport:
    """The full recommendation surface for one plan/stage. CLI and dashboard
    both serialize THIS via :meth:`to_dict`, guaranteeing identical data (AC9)."""

    plan_id: str | None
    stage: str | None
    actions: tuple[SkillAction, ...] = ()
    blockers: tuple[SkillBlocker, ...] = ()
    missing_input_action: og.ActionChoice | None = None
    affordance: og.DashboardAffordance | None = None
    migration_candidates: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "stage": self.stage,
            "actions": [a.to_dict() for a in self.actions],
            "blockers": [b.to_dict() for b in self.blockers],
            "missing_input_action": (
                self.missing_input_action.to_dict()
                if self.missing_input_action is not None
                else None
            ),
            "dashboard_affordance": (
                self.affordance.to_dict() if self.affordance is not None else None
            ),
            "migration_candidates": list(self.migration_candidates),
        }

    def to_action_items(self, *, updated_at: str | None = None) -> list[Any]:
        """Render the missing-input action (and the shared dashboard affordance)
        as ``operator_console.ActionItem`` envelopes, reusing F007's converter so
        the dashboard renders the SAME typed data the CLI prints (AC8/AC9)."""
        if self.missing_input_action is None:
            return []
        guidance = og.Guidance(
            plan_id=self.plan_id or "",
            feature_id=None,
            headline="skill inputs missing",
            choices=(self.missing_input_action,),
            affordance=self.affordance,
        )
        return guidance.to_action_items(updated_at=updated_at)


# ─────────────────────────────── pure assembly ─────────────────────────────


def explain_blockers(
    actions: Sequence[SkillAction],
    rubrics_by_name: Mapping[str, SkillRubric],
    resources: Sequence[ResourceStatus],
    *,
    external_clis: Mapping[str, str] | None = None,
    required_resource_ids: Mapping[str, Sequence[str]] | None = None,
    binary_on_path: Callable[[str], bool] | None = None,
) -> list[SkillBlocker]:
    """Explain each non-auto-run surfaced skill from the F008 inventory (AC10).

    For each surfaced skill we resolve the SPECIFIC config-inventory item id(s)
    it depends on — from its declared risk flags via :data:`_RISK_TO_RESOURCE_IDS`,
    from a backing external CLI matched by name, and from any explicit
    ``required_resource_ids[skill]`` override — and attach ONLY those item rows
    when they are unavailable. This is deliberately narrow (audit finding): a
    skill never blames an unrelated credential/capability the way attaching every
    unavailable secret/capability row by scope did. A skill is only given a
    blocker when it has missing inputs OR at least one of ITS specific resources
    is unavailable — a ready skill produces no noise.

    External-CLI specificity (AC10, codex finding): when a skill declares
    ``external_clis[skill] = <binary>`` and that binary is NOT on PATH, the skill
    is blocked even if NO config-inventory provider emits a row that names it — a
    SPECIFIC synthesized capability blocker is attached so the missing binary is
    never silently dropped. ``binary_on_path`` is the PATH probe seam (defaults to
    :func:`shutil.which`); a present binary contributes no blocker.
    """
    external_clis = external_clis or {}
    required_resource_ids = required_resource_ids or {}
    on_path = binary_on_path if binary_on_path is not None else _binary_on_path

    blockers: list[SkillBlocker] = []
    for action in actions:
        if action.recommendation in (
            Recommendation.AUTO_RUN,
            Recommendation.NOT_APPLICABLE,
        ):
            continue
        rubric = rubrics_by_name.get(action.skill_name)
        flags: frozenset[RiskFlag] = frozenset()
        if rubric is not None and rubric.invocation is not None:
            flags = frozenset(rubric.invocation.risk_flags)
        binary = external_clis.get(action.skill_name)
        has_external_cli = binary is not None

        # Resolve the SPECIFIC inventory item ids this skill depends on.
        wanted_ids: set[str] = set(required_resource_ids.get(action.skill_name, ()))
        for flag in flags:
            wanted_ids |= _RISK_TO_RESOURCE_IDS.get(flag, frozenset())
        # An absent external CLI is its own specific blocker. If a real
        # inventory row already names the binary, attach that row; otherwise
        # synthesize a capability row so the missing binary is surfaced (AC10).
        binary_missing = False
        synthetic_rows: list[ResourceStatus] = []
        if binary:
            named_rows = [
                r
                for r in resources
                if r.scope == "capability" and _row_mentions_binary(r, binary)
            ]
            for r in named_rows:
                wanted_ids.add(r.id)
            if not on_path(binary):
                binary_missing = True
                if not any(not r.ok for r in named_rows):
                    synth = _missing_binary_resource(binary)
                    synthetic_rows.append(synth)
                    wanted_ids.add(synth.id)

        # Attach ONLY the wanted rows that are unavailable, in resource order
        # (resource ids are unique, so this is already de-duplicated). The
        # synthesized missing-binary row is appended after the real rows.
        unavailable = tuple(
            r for r in (*resources, *synthetic_rows) if r.id in wanted_ids and not r.ok
        )

        if not unavailable and not action.missing_inputs:
            continue

        parts: list[str] = []
        if action.missing_inputs:
            parts.append(f"missing inputs {list(action.missing_inputs)}")
        if has_external_cli and binary_missing:
            # Only call out the CLI when the binary is actually absent — a
            # present external CLI is not a blocker (AC10 specificity).
            parts.append(f"requires the `{external_clis[action.skill_name]}` CLI (not on PATH)")
        if unavailable:
            res_txt = ", ".join(f"{r.title} ({r.status})" for r in unavailable)
            parts.append(f"unavailable config: {res_txt}")
        explanation = (
            f"{action.skill_name} is blocked: " + "; ".join(parts)
            if parts
            else f"{action.skill_name} is blocked"
        )
        blockers.append(
            SkillBlocker(
                skill_name=action.skill_name,
                missing_inputs=action.missing_inputs,
                unavailable_resources=unavailable,
                explanation=explanation,
            )
        )
    return blockers


def build_missing_input_action(
    actions: Sequence[SkillAction], *, plan_id: str | None
) -> og.ActionChoice | None:
    """Collapse every ``blocked_missing_inputs`` skill into ONE concise F007
    :class:`ActionChoice` naming only the missing blocker(s) (AC8).

    Returns ``None`` when nothing is blocked on inputs. The command is left
    ``None`` and ``requires_human`` is set: supplying a skill's input is a human
    decision, so there is no safe command to auto-run (mirrors F007's
    exact_command-when-safe rule)."""
    blocked = [
        a for a in actions if a.recommendation is Recommendation.BLOCKED_MISSING_INPUTS
    ]
    if not blocked:
        return None
    # Name ONLY the missing input blocker(s), de-duplicated and order-preserving —
    # not each blocked skill, and no prompting-loop prose (audit finding). AC8:
    # one concise action naming only the missing blocker.
    missing: list[str] = []
    seen: set[str] = set()
    for a in blocked:
        for inp in a.missing_inputs:
            if inp not in seen:
                seen.add(inp)
                missing.append(inp)
    rationale = "Missing skill input(s): " + ", ".join(missing) + "."
    return og.ActionChoice(
        id=MISSING_INPUT_CHOICE_ID,
        kind=KIND_SKILL_MISSING_INPUT,
        title="Provide missing skill inputs",
        rationale=rationale,
        risk=og.Risk.MEDIUM,
        exact_command=None,
        requires_human=True,
    )


def build_report(
    *,
    plan_id: str | None,
    stage: str | None,
    actions: Sequence[SkillAction],
    rubrics_by_name: Mapping[str, SkillRubric],
    resources: Sequence[ResourceStatus],
    external_clis: Mapping[str, str] | None = None,
    required_resource_ids: Mapping[str, Sequence[str]] | None = None,
    binary_on_path: Callable[[str], bool] | None = None,
    migration_candidates: Sequence[str] = (),
    dashboard_url: str | None = None,
) -> RecommendationReport:
    """Pure assembly of a :class:`RecommendationReport` from resolved inputs.

    The single dashboard affordance (F007 dedup, AC10) is attached only when the
    missing-input action requires human input; it carries the active URL when a
    dashboard is running, else the start command."""
    actions = tuple(actions)
    blockers = tuple(
        explain_blockers(
            actions,
            rubrics_by_name,
            resources,
            external_clis=external_clis,
            required_resource_ids=required_resource_ids,
            binary_on_path=binary_on_path,
        )
    )
    missing_action = build_missing_input_action(actions, plan_id=plan_id)
    affordance: og.DashboardAffordance | None = None
    if missing_action is not None and missing_action.requires_human:
        affordance = og.collect_dashboard_affordance(url=dashboard_url)
        from dataclasses import replace

        missing_action = replace(
            missing_action, references_affordance=affordance.affordance_id
        )
    return RecommendationReport(
        plan_id=plan_id,
        stage=stage,
        actions=actions,
        blockers=blockers,
        missing_input_action=missing_action,
        affordance=affordance,
        migration_candidates=tuple(migration_candidates),
    )


# ─────────────────────────────── migration (AC11) ──────────────────────────


def _heuristic_risk_flags(description: str, has_external_cli: bool) -> list[RiskFlag]:
    """Conservative risk-flag guess from a skill's description + whether it is
    backed by an external CLI. Errs toward MORE flags: a mistaken extra flag
    only downgrades the proposed rubric to a safer (human-gated) recommendation,
    never the reverse."""
    desc = description.lower()
    flags: set[RiskFlag] = set()
    if has_external_cli:
        flags.add(RiskFlag.NETWORK_ACCESS)
    if any(k in desc for k in ("web", "research", "search", "fetch", "online", "scrape", "network", "http")):
        flags.add(RiskFlag.NETWORK_ACCESS)
    if any(k in desc for k in ("paid", "credit", "billing", "cost", "spend")):
        flags.add(RiskFlag.PAID)
    if any(k in desc for k in ("deploy", "push", "publish", "commit", "write", "mutate", "delete", "modify", "release")):
        flags.add(RiskFlag.REPO_MUTATION)
    if any(k in desc for k in ("credential", "production", "secret", "prod ")):
        flags.add(RiskFlag.CREDENTIALED_PRODUCTION_READ)
    return sorted(flags, key=lambda f: f.value)


def _derive_required_inputs(frontmatter: Mapping[str, Any]) -> list[str]:
    """Derive a SAFE starting ``required_inputs`` list from a skill's
    frontmatter (AC11, codex finding).

    The evaluator treats every name in ``required_inputs`` as a gate the caller
    must satisfy, so over-listing only makes the proposal SAFER (a skill stays
    ``blocked_missing_inputs`` until the operator supplies the input). We harvest
    candidate input names from three documented sources, in priority order, and
    return them de-duplicated + order-preserving:

    1. ``argument-hint`` — the conventional ``<arg>`` / ``[--flag value]`` hint
       string. Bracketed/angle tokens become input names (``--flag`` → ``flag``).
    2. ``triggers`` — when a trigger is expressed as a mapping with a
       ``required_inputs`` / ``inputs`` / ``requires`` list, those names are taken
       verbatim.
    3. explicit ``required_inputs`` / ``required_arguments`` at the frontmatter
       root (some skills document them outside the ``invocation:`` block).

    Conservative: only names extractable from declared metadata are returned;
    free-prose in ``description`` is NOT parsed (that would over-trigger)."""
    import re

    names: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        if not isinstance(raw, str):
            return
        name = raw.strip().lstrip("-").strip()
        if not name or name in seen:
            return
        seen.add(name)
        names.append(name)

    # 1. argument-hint string → bracketed/angle tokens.
    hint = frontmatter.get("argument-hint") or frontmatter.get("argument_hint")
    if isinstance(hint, str) and hint.strip():
        # Tokens inside <...> or [...]; for "[--flag value]" take the flag.
        for token in re.findall(r"[<\[]([^<>\[\]]+)[>\]]", hint):
            first = token.strip().split()[0] if token.strip() else ""
            _add(first)

    # 2. triggers carrying explicit input requirements.
    triggers = frontmatter.get("triggers")
    trigger_seq: Sequence[Any]
    if isinstance(triggers, Mapping):
        trigger_seq = [triggers]
    elif isinstance(triggers, Sequence) and not isinstance(triggers, str):
        trigger_seq = triggers
    else:
        trigger_seq = ()
    for trig in trigger_seq:
        if not isinstance(trig, Mapping):
            continue
        for key in ("required_inputs", "inputs", "requires"):
            req = trig.get(key)
            if isinstance(req, Sequence) and not isinstance(req, str):
                for item in req:
                    _add(item)

    # 3. explicit root-level required inputs (documented outside invocation:).
    for key in ("required_inputs", "required_arguments", "requires"):
        req = frontmatter.get(key)
        if isinstance(req, Sequence) and not isinstance(req, str):
            for item in req:
                _add(item)

    return names


def suggest_rubric(skill_name: str, frontmatter: Mapping[str, Any]) -> RubricSuggestion:
    """Propose a SAFE starting ``invocation:`` block for ``skill_name`` from its
    current frontmatter/triggers/tool requirements/risk heuristics (AC11).

    Never proposes an auto mode: a skill with no declared risk gets ``suggest``;
    one with any heuristic risk flag gets ``approval_required``. Both are
    human-driven, so the proposed block needs no ``evidence_target`` and a
    migrated skill is never silently auto-run. The proposal is validated through
    :func:`parse_invocation` before it is returned, so it is guaranteed to be a
    parseable rubric."""
    import yaml

    existing, _ = parse_invocation(frontmatter)
    already = existing is not None

    description = str(frontmatter.get("description") or "")
    applies_to = frontmatter.get("applies_to")
    external_cli = (
        isinstance(applies_to, Mapping) and applies_to.get("external_cli") is not None
    )
    risk_flags = _heuristic_risk_flags(description, bool(external_cli))
    mode = InvocationMode.APPROVAL_REQUIRED if risk_flags else InvocationMode.SUGGEST

    # Derive a safe starting required_inputs set from the skill's own declared
    # argument-hint / triggers / documented inputs (AC11). Over-listing is safe:
    # an extra required input only keeps the skill human-gated until supplied.
    required_inputs = _derive_required_inputs(frontmatter)

    proposed: dict[str, Any] = {
        "mode": mode.value,
        "lifecycle_stages": [],
        "required_inputs": required_inputs,
        "risk_flags": [f.value for f in risk_flags],
    }
    # Validate the proposal so a suggestion is always a parseable rubric.
    invocation, reason = parse_invocation({"invocation": proposed})
    if invocation is None:  # pragma: no cover — defensive; proposal is well-formed
        raise ValueError(f"generated rubric failed validation: {reason}")

    yaml_block = yaml.safe_dump(
        {"invocation": proposed}, sort_keys=False, default_flow_style=False
    ).rstrip("\n")

    if already:
        rationale = (
            f"{skill_name} already declares an invocation rubric — no migration "
            f"needed. The block below is a reference baseline."
        )
    else:
        why = (
            f"declared risk flags {[f.value for f in risk_flags]}"
            if risk_flags
            else "no risk indicators detected"
        )
        rationale = (
            f"Proposed safe starting rubric for {skill_name}: mode={mode.value} "
            f"({why}). Review and tighten before committing; this never auto-runs."
        )
    return RubricSuggestion(
        skill_name=skill_name,
        already_has_metadata=already,
        proposed=proposed,
        yaml_block=yaml_block,
        rationale=rationale,
    )


def _read_skill_frontmatter(skills_dir: Path, name: str) -> dict[str, Any] | None:
    """Read ``<skills_dir>/<name>/SKILL.md`` frontmatter, reusing the
    applicability matcher's parser. Returns ``None`` when absent/malformed."""
    from dontpanic_orchestrate import skill_applicability

    skill_md = skills_dir / name / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        return skill_applicability._read_frontmatter(skill_md)
    except OSError:
        return None


def skills_missing_rubrics(
    skills_dir: Path, *, applicable_names: Iterable[str] | None = None
) -> list[str]:
    """Identify HIGH-VALUE skills that lack ``invocation:`` metadata (AC11).

    "High-value" = the skill declares ``applies_to`` (so it opts into plan
    matching) OR it is in ``applicable_names`` (matched the current plan), yet it
    has no invocation rubric. Advisory only — this never blocks core use; it
    simply tells the operator which skills would benefit from a rubric."""
    if not skills_dir.is_dir():
        return []
    applicable = set(applicable_names) if applicable_names is not None else None
    candidates: list[str] = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        frontmatter = _read_skill_frontmatter(skills_dir, name)
        if frontmatter is None:
            continue
        invocation, reason = parse_invocation(frontmatter)
        if invocation is not None or reason is not None:
            continue  # already has a (valid or invalid-but-present) rubric
        high_value = (
            "applies_to" in frontmatter
            or (applicable is not None and name in applicable)
        )
        if high_value:
            candidates.append(name)
    return candidates


@dataclass(frozen=True)
class RubricDoctorAdvisory:
    """Result of the non-blocking doctor advisory for missing rubrics (AC11).

    ``skill_names`` are the high-value skills lacking an ``invocation:`` rubric;
    ``suggest_commands`` is the parallel list of exact ``dontpanic skills rubric
    --suggest <skill>`` invocations the operator can run. ``message`` /
    ``remediation`` are pre-rendered so the doctor can emit ONE advisory WARN
    without re-deriving copy. Empty ``skill_names`` ⇒ nothing to advise (the
    doctor renders a PASS / skips)."""

    skill_names: tuple[str, ...]
    message: str
    remediation: str

    @property
    def has_findings(self) -> bool:
        return bool(self.skill_names)

    @property
    def suggest_commands(self) -> list[str]:
        return [f"dontpanic skills rubric --suggest {name}" for name in self.skill_names]


def doctor_missing_rubric_advisory(
    skills_dir: Path, *, applicable_names: Iterable[str] | None = None
) -> RubricDoctorAdvisory:
    """Build the doctor's NON-BLOCKING advisory for high-value skills that lack
    an invocation rubric (AC11).

    Wraps :func:`skills_missing_rubrics` and renders operator-facing copy + the
    exact ``dontpanic skills rubric --suggest <skill>`` remediation commands. It
    is advisory ONLY: the doctor must surface this as a WARN that never fails the
    battery — a metadata-less skill is a migration nudge, not a broken install.
    A missing/empty skills dir yields an empty advisory (no finding)."""
    names = tuple(skills_missing_rubrics(skills_dir, applicable_names=applicable_names))
    if not names:
        return RubricDoctorAdvisory(
            skill_names=(),
            message="all high-value skills declare an invocation rubric",
            remediation="",
        )
    listed = ", ".join(names)
    commands = "; ".join(f"dontpanic skills rubric --suggest {n}" for n in names)
    return RubricDoctorAdvisory(
        skill_names=names,
        message=(
            f"{len(names)} high-value skill(s) lack an invocation rubric "
            f"(advisory — core use is not blocked): {listed}"
        ),
        remediation=f"run: {commands}",
    )


# ─────────────────────────────── live collector ────────────────────────────


def _derive_provided_inputs(
    loaded: Any, changed_files: Sequence[str]
) -> tuple[str, ...]:
    """Conservatively derive which named inputs are currently satisfiable.

    Only inputs DontPanic can vouch for are listed; everything else is treated
    as missing so the recommender errs toward surfacing a missing-input action
    rather than a misleading "ready". ``changed_files`` is provided when the
    working tree has changes."""
    provided: set[str] = {"plan"}
    if changed_files:
        provided.add("changed_files")
    return tuple(sorted(provided))


def collect(
    plan_dir: Path,
    skills_dir: Path,
    *,
    stage: str | None = None,
    project: str | None = None,
    dashboard_url: str | None = None,
    provided_inputs: Sequence[str] | None = None,
    changed_files: Sequence[str] = (),
) -> RecommendationReport:
    """Live wiring for ``dontpanic skills recommend`` and the dashboard.

    Reads (never writes): the plan + its surfaces/goal_type, every skill's
    ``invocation:`` rubric, the F007 applicability report, the F015 auto-run
    allowlist predicate, and the F008 config inventory. Builds the pure
    :class:`SkillInvocationContext`, evaluates it, and assembles the report.
    Every external read is defensive so a fresh/degraded environment still
    produces a usable surface (never blocks core use, AC11)."""
    from dontpanic_orchestrate import plan_loader, skill_allowlist, skill_applicability

    loaded = plan_loader.load(plan_dir)
    plan_id = getattr(loaded, "plan_id", None)
    goal_type = _resolve_goal_type(loaded)
    surfaces = tuple(getattr(loaded, "surfaces", []) or [])

    # Applicability (F007): which skills match this plan, plus external-CLI hints.
    applicable_names: set[str] = set()
    external_clis: dict[str, str] = {}
    try:
        report = skill_applicability.match(loaded, skills_dir)
        for m in report.matches:
            applicable_names.add(m.skill_name)
            if m.external_cli is not None:
                external_clis[m.skill_name] = m.external_cli.command
    except Exception:  # noqa: BLE001, S110 — advisory matcher must never block; a degraded/missing skills dir simply yields no applicability hints
        pass

    # Per-skill rubrics from SKILL.md frontmatter.
    rubrics: list[SkillRubric] = []
    rubrics_by_name: dict[str, SkillRubric] = {}
    if skills_dir.is_dir():
        for entry in sorted(skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            name = entry.name
            frontmatter = _read_skill_frontmatter(skills_dir, name)
            if frontmatter is None:
                continue
            rubric = load_rubric(
                name, frontmatter, applicable=name in applicable_names
            )
            rubrics.append(rubric)
            rubrics_by_name[name] = rubric

    # F015 allowlist predicate (deny-all when missing/untrusted).
    try:
        is_allowlisted = skill_allowlist.build_predicate()
    except Exception:  # noqa: BLE001 — never block on a degraded allowlist
        is_allowlisted = lambda _command: False  # noqa: E731

    provided = (
        tuple(provided_inputs)
        if provided_inputs is not None
        else _derive_provided_inputs(loaded, changed_files)
    )

    ctx = SkillInvocationContext(
        skills=tuple(rubrics),
        lifecycle_stage=stage,
        goal_type=goal_type,
        plan_surfaces=surfaces,
        changed_files=tuple(changed_files),
        provided_inputs=provided,
        budget_ok=True,
        is_command_allowlisted=is_allowlisted,
    )
    actions = recommendations(ctx)

    # F008 inventory → resources that explain blocked skills (AC10).
    resources: list[ResourceStatus] = []
    try:
        from dontpanic_orchestrate import config_inventory as ci

        inventory = ci.collect_inventory(project=project, dashboard_url=dashboard_url)
        resources = resources_from_inventory(inventory)
    except Exception:  # noqa: BLE001 — inventory is advisory here, never blocks
        resources = []

    migration = skills_missing_rubrics(
        skills_dir, applicable_names=applicable_names or None
    )

    return build_report(
        plan_id=plan_id,
        stage=stage,
        actions=actions,
        rubrics_by_name=rubrics_by_name,
        resources=resources,
        external_clis=external_clis,
        migration_candidates=migration,
        dashboard_url=dashboard_url,
    )


def _resolve_goal_type(loaded: Any) -> str | None:
    plan_obj = getattr(loaded, "plan", None)
    raw = getattr(plan_obj, "goal_type", None) if plan_obj is not None else None
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


# ─────────────────────────────── text rendering ────────────────────────────


def render_text(report: RecommendationReport) -> str:
    """Human-readable render of the recommendation report (CLI default).

    Renders the SAME fields the JSON/dashboard surface carries (AC9): skill,
    recommendation, reason, risk, command, approval requirement, evidence
    target — plus the one missing-input action and the dashboard affordance."""
    lines: list[str] = []
    head = f"skills recommend: {report.plan_id or '(unknown plan)'}"
    if report.stage:
        head += f" / stage={report.stage}"
    lines.append(head)
    if not report.actions:
        lines.append("  No applicable skill recommendations.")
    else:
        lines.append("")
        for a in report.actions:
            approval = " [approval required]" if a.approval_required else ""
            lines.append(
                f"  • {a.skill_name}: {a.recommendation.value}"
                f"  (risk: {a.risk.value}){approval}"
            )
            lines.append(f"      reason: {a.reason}")
            if a.exact_command:
                lines.append(f"      command: {a.exact_command}")
            if a.evidence_target:
                lines.append(f"      evidence: {a.evidence_target}")
            if a.missing_inputs:
                lines.append(f"      missing: {list(a.missing_inputs)}")
    for b in report.blockers:
        lines.append(f"  ! {b.explanation}")
        for r in b.unavailable_resources:
            cmd = f" — fix: {r.safe_command}" if r.safe_command else ""
            lines.append(f"      blocked by {r.id} [{r.status}]{cmd}")
    if report.missing_input_action is not None:
        c = report.missing_input_action
        lines.append("")
        lines.append(f"  → {c.title}: {c.rationale}")
    if report.affordance is not None:
        lines.append(f"  Dashboard: {report.affordance.text()}")
    if report.migration_candidates:
        lines.append("")
        lines.append(
            "  Migration: these high-value skills lack an invocation rubric "
            "(advisory — core use is not blocked):"
        )
        for name in report.migration_candidates:
            lines.append(
                f"      {name} — run `dontpanic skills rubric --suggest {name}`"
            )
    return "\n".join(lines) + "\n"


def render_rubric_text(suggestion: RubricSuggestion) -> str:
    """Human-readable render of a single :class:`RubricSuggestion`."""
    lines = [
        f"skills rubric --suggest {suggestion.skill_name}",
        f"  {suggestion.rationale}",
        "",
        "  Paste into the skill's SKILL.md frontmatter:",
    ]
    for ln in suggestion.yaml_block.splitlines():
        lines.append(f"    {ln}")
    return "\n".join(lines) + "\n"


__all__ = [
    "SCHEMA_VERSION",
    "MISSING_INPUT_CHOICE_ID",
    "KIND_SKILL_MISSING_INPUT",
    "ResourceStatus",
    "SkillBlocker",
    "RubricSuggestion",
    "RubricDoctorAdvisory",
    "RecommendationReport",
    "resources_from_inventory",
    "explain_blockers",
    "external_binary_id",
    "build_missing_input_action",
    "build_report",
    "suggest_rubric",
    "skills_missing_rubrics",
    "doctor_missing_rubric_advisory",
    "collect",
    "render_text",
    "render_rubric_text",
]
