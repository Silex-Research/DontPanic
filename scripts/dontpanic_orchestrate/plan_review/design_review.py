"""Design-review volley (F005).

Layer-2 of the plan-review capability. Where the F001 deterministic lint is a
free, mechanical check, this is the *paid* red-team pass reserved for the plans
the lint cannot fully judge: it runs a **design-reviewer** auditor against a
**planner** implementer through the existing volley machinery (the executor
abstraction + the standard ``{verdict, findings}`` auditor envelope), red-teaming
a plan's feature decomposition for sizing, hidden coupling, testability traps,
dependency order, and missing prerequisites.

Closed design taxonomy (acceptance #2) — every finding is keyed to exactly one:

  * ``oversize``          — a feature too large for one dispatch (multi-surface / too many ACs)
  * ``hidden_coupling``   — an undeclared dependency between features
  * ``ac_underspecified`` — an exemplar/weak acceptance criterion (example, not invariant)
  * ``missing_prereq``    — a capability the plan never declares
  * ``reorder_deps``      — a dependency order that should be re-sequenced

Opt-in only (acceptance #3): :func:`should_run_design_volley` returns True only
when the F001 lint reports *uncertainty* (warn-severity flags — not clean, not a
clear block) OR the operator explicitly requests it. It is NEVER auto-run on
every plan; a clean plan skips it and a clearly-blocked plan is already refused
by the F004 pre-lock gate.

The volley loop here mirrors ``supervisor.dispatch_volley``'s structure — an
auditor slot reviewing, an optional implementer (planner) slot revising on
``needs_changes`` — but is decomposition-shaped rather than code-shaped, so it
neither touches a git diff nor runs patch-completeness. It reuses the
``BaseExecutor`` dispatch contract, which is what lets the synthetic test
(acceptance #4) drive it with a mock executor and zero live paid calls.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dontpanic_orchestrate.executors.base import (
    BaseExecutor,
    DispatchTask,
)
from dontpanic_orchestrate.plan_review.report import PlanScopeReport

# The closed design-review taxonomy (acceptance #2). A finding whose ``kind`` is
# outside this set is not a valid design finding and is quarantined out of the
# standard envelope.
DESIGN_TAXONOMY: frozenset[str] = frozenset(
    {"oversize", "hidden_coupling", "ac_underspecified", "missing_prereq", "reorder_deps"}
)

DesignFindingKind = Literal[
    "oversize", "hidden_coupling", "ac_underspecified", "missing_prereq", "reorder_deps"
]
Verdict = Literal["signed_off", "needs_changes", "blocked"]

DESIGN_REVIEWER_ROLE = "design-reviewer"
PLANNER_ROLE = "planner"


# ─────────────────────────────── public types ──────────────────────────────


@dataclass(frozen=True)
class DesignFinding:
    kind: DesignFindingKind
    severity: str
    feature_id: str
    evidence: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "feature_id": self.feature_id,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, blob: dict) -> DesignFinding:
        return cls(
            kind=blob["kind"],
            severity=str(blob.get("severity", "warn")),
            feature_id=str(blob.get("feature_id", "")),
            evidence=str(blob.get("evidence", "")),
        )


@dataclass
class DesignVolleyEnvelope:
    """The standard auditor envelope a design volley returns (acceptance #1).

    ``unrecognized`` holds any emitted finding whose ``kind`` fell outside the
    closed taxonomy — quarantined so ``findings`` is taxonomy-pure (acceptance
    #2) without silently discarding what the reviewer said."""

    verdict: Verdict
    findings: list[DesignFinding] = field(default_factory=list)
    rounds: int = 1
    unrecognized: list[dict] = field(default_factory=list)
    # Scoped re-review (convergence rule): findings on unchanged, already
    # reviewed features land here instead of ``findings`` and never block.
    out_of_scope: list[dict] = field(default_factory=list)
    scope_note: str = ""
    # False when the reviewer produced no parseable envelope (or the dispatch
    # failed / was skipped); such a run never advances the review ledger.
    reviewed: bool = True

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "findings": [f.to_dict() for f in self.findings],
            "rounds": self.rounds,
            "unrecognized": list(self.unrecognized),
            "out_of_scope": list(self.out_of_scope),
            "scope_note": self.scope_note,
        }

    def findings_of_kind(self, kind: str) -> list[DesignFinding]:
        return [f for f in self.findings if f.kind == kind]


# ─────────────────────────────── trigger ───────────────────────────────────


def _has_warn_flag(report: PlanScopeReport) -> bool:
    for fr in report.features:
        if any(flag.severity == "warn" for flag in fr.scope.flags):
            return True
    return False


def should_run_design_volley(
    report: PlanScopeReport, *, operator_requested: bool = False
) -> bool:
    """Opt-in trigger (acceptance #3). True iff the operator explicitly asked OR
    the F001 lint is *uncertain* — it surfaced warn-severity flags (the
    ambiguous middle the deterministic lint cannot resolve). A fully clean plan
    (no flags) never auto-triggers a paid volley."""
    if operator_requested:
        return True
    return _has_warn_flag(report)


# ─────────────────────────── convergence ledger ────────────────────────────

# The review ledger lives in the plan dir; it lets a re-lock review only what
# changed since the last design review instead of re-scanning the whole plan.
LEDGER_RELPATH = Path("evidence") / "design-review" / "ledger.json"
LEDGER_SCHEMA = 2

# Bump whenever the reviewer prompt (build_design_reviewer_prompt /
# _scope_block) changes meaning: a ledger written under another prompt version
# is ignored (full review).
PROMPT_VERSION = "design-review-prompt-2026-11-23.2"

# Only these verdicts are a completed review that may advance the ledger. A
# ``blocked`` verdict (including an unknown verdict coerced to blocked), a parse
# failure and a dispatch failure never do.
LEDGER_VERDICTS: frozenset[str] = frozenset({"signed_off", "needs_changes"})

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_LEDGER_KEYS: frozenset[str] = frozenset(
    {
        "schema",
        "plan_id",
        "reviewed_at",
        "mode",
        "feature_hashes",
        "objective_contract_digest",
        "reviewer",
        "prompt_version",
        "verdict",
        "open_findings",
        "out_of_scope_history",
        "digest",
    }
)
_FINDING_KEYS: frozenset[str] = frozenset({"kind", "severity", "feature_id", "evidence"})


@dataclass(frozen=True)
class ReviewScope:
    """What a design-review run looks at. ``mode == "full"`` reviews every
    feature (no usable ledger, or ``--design-review-full``). ``"scoped"``
    reviews only ``in_scope`` = changed/new features + features with prior
    open findings + every feature that depends (directly or transitively) on a
    changed, new or removed feature. ``feature_ids`` is the plan's current
    feature set: a finding whose ``feature_id`` is not in it is plan-level and
    always stays in scope."""

    mode: Literal["full", "scoped"]
    in_scope: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    prior_open_ids: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    prior_open: tuple[dict, ...] = ()
    last_reviewed_at: str = ""
    dependents: tuple[str, ...] = ()
    feature_ids: tuple[str, ...] = ()
    reason: str = ""

    @property
    def nothing_to_review(self) -> bool:
        return self.mode == "scoped" and not self.in_scope and not self.removed

    def describe(self) -> str:
        if self.mode == "full":
            return "full" + (f" ({self.reason})" if self.reason else "")
        parts = []
        if self.changed:
            parts.append(f"{','.join(self.changed)} (changed)")
        if self.dependents:
            parts.append(f"{','.join(self.dependents)} (depends on changed)")
        if self.prior_open_ids:
            parts.append(f"{','.join(self.prior_open_ids)} (prior open)")
        if self.removed:
            parts.append(f"{','.join(self.removed)} (removed)")
        return "scoped: " + (", ".join(parts) or "nothing changed")


FULL_SCOPE = ReviewScope(mode="full")


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def feature_hash(feature: dict) -> str:
    """sha256 of the canonical JSON of one feature dict."""
    return hashlib.sha256(_canonical(feature).encode("utf-8")).hexdigest()


def objective_contract_digest(contract: dict | None) -> str | None:
    """sha256 of the canonical objective_contract JSON, or None when absent."""
    if contract is None:
        return None
    return hashlib.sha256(_canonical(contract).encode("utf-8")).hexdigest()


def reviewer_identity(auditor: object) -> dict:
    """The reviewer a ledger is bound to: executor agent name + model if known."""
    model = getattr(auditor, "model", None)
    return {
        "agent": str(getattr(auditor, "agent_name", "") or type(auditor).__name__),
        "model": str(model) if model else None,
    }


@dataclass(frozen=True)
class LedgerBinding:
    """The inputs a ledger must match to be reused for a scoped re-review."""

    plan_id: str
    objective_contract: dict | None
    reviewer: dict


def _ledger_digest(blob: dict) -> str:
    """sha256 over the bound fields. This is INTEGRITY, not authentication:
    anyone who can write the ledger can recompute it. It catches torn, stale,
    hand-edited or schema-drifted ledgers; the zero-call shortcut additionally
    requires a ``signed_off`` ledger with no open findings."""
    bound = {
        "schema": blob.get("schema"),
        "plan_id": blob.get("plan_id"),
        "feature_hashes": blob.get("feature_hashes"),
        "objective_contract_digest": blob.get("objective_contract_digest"),
        "reviewer": blob.get("reviewer"),
        "prompt_version": blob.get("prompt_version"),
        "verdict": blob.get("verdict"),
        "open_findings": blob.get("open_findings"),
    }
    return hashlib.sha256(_canonical(bound).encode("utf-8")).hexdigest()


def _is_str_or_none(value: object) -> bool:
    return value is None or isinstance(value, str)


def _structure_error(blob: object) -> str | None:
    """Strict schema/type check of a ledger blob; a reason string or None."""
    if not isinstance(blob, dict):
        return "ledger is not a JSON object"
    keys = set(blob)
    if keys != _LEDGER_KEYS:
        missing = sorted(_LEDGER_KEYS - keys)
        extra = sorted(keys - _LEDGER_KEYS)
        return f"ledger fields differ (missing={missing}, unknown={extra})"
    if blob["schema"] != LEDGER_SCHEMA or isinstance(blob["schema"], bool):
        return f"ledger schema {blob['schema']!r} != {LEDGER_SCHEMA}"
    for key in ("plan_id", "reviewed_at", "prompt_version", "digest"):
        if not isinstance(blob[key], str):
            return f"ledger field {key!r} is not a string"
    if blob["mode"] not in ("full", "scoped"):
        return f"ledger mode {blob['mode']!r} is invalid"
    hashes = blob["feature_hashes"]
    if not isinstance(hashes, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and _SHA256_RE.match(v) for k, v in hashes.items()
    ):
        return "ledger feature_hashes is not a map of feature id -> sha256"
    contract = blob["objective_contract_digest"]
    if contract is not None and not (isinstance(contract, str) and _SHA256_RE.match(contract)):
        return "ledger objective_contract_digest is not a sha256 or null"
    reviewer = blob["reviewer"]
    if not (
        isinstance(reviewer, dict)
        and set(reviewer) == {"agent", "model"}
        and isinstance(reviewer["agent"], str)
        and _is_str_or_none(reviewer["model"])
    ):
        return "ledger reviewer is not {agent, model}"
    if blob["verdict"] not in LEDGER_VERDICTS:
        return f"ledger verdict {blob['verdict']!r} is not a completed review"
    findings = blob["open_findings"]
    if not isinstance(findings, list) or not all(
        isinstance(f, dict)
        and set(f) == _FINDING_KEYS
        and all(isinstance(f[k], str) for k in _FINDING_KEYS)
        for f in findings
    ):
        return "ledger open_findings is not a list of findings"
    if not isinstance(blob["out_of_scope_history"], list):
        return "ledger out_of_scope_history is not a list"
    return None


def ledger_rejection(blob: object, binding: LedgerBinding) -> str | None:
    """Why ``blob`` cannot be reused for ``binding`` (-> full review), or None."""
    error = _structure_error(blob)
    if error:
        return error
    if not isinstance(blob, dict):  # unreachable: _structure_error checked it
        return "ledger is not a JSON object"
    if blob["digest"] != _ledger_digest(blob):
        return "ledger digest mismatch (edited or torn)"
    if blob["plan_id"] != binding.plan_id:
        return f"ledger is for plan {blob['plan_id']!r}, not {binding.plan_id!r}"
    if blob["objective_contract_digest"] != objective_contract_digest(binding.objective_contract):
        return "objective_contract.json changed since the last review"
    if blob["reviewer"] != binding.reviewer:
        return f"reviewer changed ({blob['reviewer']} -> {binding.reviewer})"
    if blob["prompt_version"] != PROMPT_VERSION:
        return f"reviewer prompt version changed ({blob['prompt_version']} -> {PROMPT_VERSION})"
    return None


def load_ledger_checked(path: Path, binding: LedgerBinding) -> tuple[dict | None, str]:
    """``(ledger, "")`` when reusable, else ``(None, reason)`` -> full review."""
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return None, "no ledger"
    except OSError as exc:
        return None, f"ledger unreadable ({exc.__class__.__name__})"
    try:
        blob = json.loads(text)
    except ValueError:
        return None, "ledger is not valid JSON"
    reason = ledger_rejection(blob, binding)
    if reason:
        return None, reason
    return blob, ""


def load_ledger(path: Path, binding: LedgerBinding) -> dict | None:
    """The prior ledger, or None when absent/invalid/unbound (-> full review)."""
    return load_ledger_checked(path, binding)[0]


def _transitive_dependents(current: dict[str, dict], roots: set[str]) -> tuple[str, ...]:
    """Every current feature that depends, directly or transitively, on any of
    ``roots`` (excluding the roots themselves), in plan order."""
    reached: set[str] = set()
    frontier = set(roots)
    while frontier:
        nxt = {
            fid
            for fid, f in current.items()
            if fid not in reached
            and fid not in roots
            and set(map(str, f.get("depends_on") or [])) & frontier
        }
        reached |= nxt
        frontier = nxt
    return tuple(fid for fid in current if fid in reached)


def compute_scope(features: Sequence[dict], ledger: dict | None) -> ReviewScope:
    """Full scope without a usable ledger; otherwise the scoped re-review set.

    Full review is forced when a prior open finding is plan-level (its
    ``feature_id`` is not a current feature), so it is never silently dropped.
    The zero-call shortcut (nothing in scope) is only taken from a
    ``signed_off`` ledger with no open findings."""
    if ledger is None:
        return FULL_SCOPE
    prior_hashes: dict = ledger.get("feature_hashes") or {}
    current = {str(f.get("id", "")): f for f in features}
    prior_open = tuple(f for f in ledger.get("open_findings") or [] if isinstance(f, dict))
    plan_level = [f for f in prior_open if str(f.get("feature_id", "")) not in current]
    if plan_level:
        return ReviewScope(
            mode="full",
            reason=f"{len(plan_level)} open plan-level finding(s) from the last review",
        )
    changed = tuple(
        fid for fid, f in current.items() if prior_hashes.get(fid) != feature_hash(f)
    )
    removed = tuple(sorted(fid for fid in prior_hashes if fid not in current))
    prior_open_ids = tuple(
        dict.fromkeys(
            str(f.get("feature_id", ""))
            for f in prior_open
            if str(f.get("feature_id", "")) not in changed
        )
    )
    dependents = tuple(
        fid
        for fid in _transitive_dependents(current, set(changed) | set(removed))
        if fid not in changed
    )
    in_scope = tuple(dict.fromkeys(changed + dependents + prior_open_ids))
    if not in_scope and not removed and (ledger.get("verdict") != "signed_off" or prior_open):
        return ReviewScope(mode="full", reason="last review did not sign off")
    return ReviewScope(
        mode="scoped",
        in_scope=in_scope,
        changed=changed,
        prior_open_ids=prior_open_ids,
        removed=removed,
        prior_open=prior_open,
        last_reviewed_at=str(ledger.get("reviewed_at", "")),
        dependents=dependents,
        feature_ids=tuple(current),
    )


def apply_scope(envelope: DesignVolleyEnvelope, scope: ReviewScope) -> DesignVolleyEnvelope:
    """Move findings on out-of-scope (unchanged, already-reviewed, not
    dependent) features into ``out_of_scope``. Plan-level findings (feature id
    not a current feature) always stay in scope. When the reviewer said
    needs_changes and nothing in scope remains, the verdict is downgraded to
    signed_off (recorded in ``scope_note``)."""
    if scope.mode == "full":
        return envelope
    allowed = set(scope.in_scope)
    known = set(scope.feature_ids)

    def keep(f: DesignFinding) -> bool:
        return f.feature_id in allowed or f.feature_id not in known

    in_scope = [f for f in envelope.findings if keep(f)]
    out = [f.to_dict() for f in envelope.findings if not keep(f)]
    envelope.findings = in_scope
    envelope.out_of_scope.extend(out)
    if envelope.verdict == "needs_changes" and out and not in_scope:
        envelope.verdict = "signed_off"
        envelope.scope_note = (
            f"needs_changes downgraded to signed_off: all {len(out)} finding(s) "
            "were on unchanged, already-reviewed features (out of scope)"
        )
    return envelope


def ledger_advances(envelope: DesignVolleyEnvelope) -> bool:
    """Only a completed review (parsed ``signed_off`` / ``needs_changes``)
    advances the ledger; blocked / coerced / unparsed / skipped runs never do."""
    return bool(envelope.reviewed) and envelope.verdict in LEDGER_VERDICTS


def write_ledger(
    path: Path,
    features: Sequence[dict],
    envelope: DesignVolleyEnvelope,
    scope: ReviewScope,
    prior: dict | None,
    binding: LedgerBinding,
) -> bool:
    """Record this review, bound to ``binding``. Returns False (nothing
    written) unless :func:`ledger_advances`. ``open_findings`` = this run's
    in-scope findings incl. plan-level ones (prior open findings not re-raised
    are resolved); out-of-scope findings are appended to
    ``out_of_scope_history`` for audit. Raises OSError on write failure."""
    if not ledger_advances(envelope):
        return False
    reviewed_at = datetime.now(timezone.utc).isoformat()
    history = list((prior or {}).get("out_of_scope_history") or [])
    if envelope.out_of_scope:
        history.append({"reviewed_at": reviewed_at, "findings": list(envelope.out_of_scope)})
    blob = {
        "schema": LEDGER_SCHEMA,
        "plan_id": binding.plan_id,
        "reviewed_at": reviewed_at,
        "mode": scope.mode,
        "feature_hashes": {str(f.get("id", "")): feature_hash(f) for f in features},
        "objective_contract_digest": objective_contract_digest(binding.objective_contract),
        "reviewer": dict(binding.reviewer),
        "prompt_version": PROMPT_VERSION,
        "verdict": envelope.verdict,
        "open_findings": [f.to_dict() for f in envelope.findings],
        "out_of_scope_history": history,
    }
    blob["digest"] = _ledger_digest(blob)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, indent=2, sort_keys=True) + "\n")
    return True


# ─────────────────────────────── prompts ───────────────────────────────────


def _scope_block(scope: ReviewScope | None) -> str:
    if scope is None or scope.mode == "full":
        return ""
    lines = [
        "",
        "SCOPED RE-REVIEW. Every feature below was already reviewed in full on",
        f"{scope.last_reviewed_at or 'a previous lock'}. Review ONLY these in-scope features:",
        f"  in-scope: {', '.join(scope.in_scope) or '(none)'}",
        f"  changed since last review: {', '.join(scope.changed) or '(none)'}",
    ]
    if scope.dependents:
        lines.append(
            f"  depend on a changed feature: {', '.join(scope.dependents)}"
        )
    if scope.removed:
        lines.append(f"  removed since last review: {', '.join(scope.removed)}")
    if scope.prior_open:
        lines.append("Prior open findings to re-check (re-raise only if still open):")
        lines.extend(
            f"  - [{f.get('kind')}/{f.get('severity')}] {f.get('feature_id')}: "
            f"{f.get('evidence')}"
            for f in scope.prior_open
        )
    lines.append(
        "Unchanged features outside that list were already reviewed in full; do "
        "not raise new findings on them unless the changed text causes them. "
        "Findings on out-of-scope features are recorded as advisory only."
    )
    return "\n".join(lines) + "\n"


def build_design_reviewer_prompt(
    plan_id: str,
    features: Sequence[dict],
    objective_contract: dict | None = None,
    scope: ReviewScope | None = None,
) -> str:
    """The design-reviewer auditor prompt: consumes the plan's features +
    objective_contract and instructs the reviewer to emit a strict JSON envelope
    keyed to the closed design taxonomy. A scoped ``scope`` keeps the full
    features.json as context but names the in-scope features and prior open
    findings to re-check."""
    contract_block = (
        json.dumps(objective_contract, indent=2)
        if objective_contract
        else "(no objective_contract provided)"
    )
    feature_block = json.dumps(list(features), indent=2)
    taxonomy = ", ".join(sorted(DESIGN_TAXONOMY))
    return f"""You are the DESIGN REVIEWER for plan {plan_id}.

Red-team this plan's FEATURE DECOMPOSITION (not its code) for:
  - oversize: a feature too large for one ~600s dispatch (spans >1 surface, or too many ACs)
  - hidden_coupling: a feature depending on another's output without declaring depends_on
  - ac_underspecified: an acceptance criterion that gives an example instead of an invariant
  - missing_prereq: a capability (command/flag/symbol) the plan relies on but never declares
  - reorder_deps: a dependency order that should be re-sequenced

objective_contract:
{contract_block}

features.json:
{feature_block}
{_scope_block(scope)}
Return ONLY a JSON object:
  {{"verdict": "signed_off" | "needs_changes" | "blocked",
    "findings": [{{"kind": <one of: {taxonomy}>, "severity": "block"|"warn",
                   "feature_id": "<id>", "evidence": "<one line>"}}]}}
Sign off only when the decomposition has no design defect. Every finding's
"kind" MUST be one of the closed taxonomy values above."""


def build_planner_prompt(
    plan_id: str,
    features: Sequence[dict],
    prior_findings: Sequence[DesignFinding],
) -> str:
    """The planner implementer prompt for a revision round: addresses the
    design-reviewer's prior findings by re-decomposing the plan."""
    findings_block = "\n".join(
        f"  - [{f.kind}/{f.severity}] {f.feature_id}: {f.evidence}"
        for f in prior_findings
    ) or "  (none)"
    feature_block = json.dumps(list(features), indent=2)
    return f"""You are the PLANNER for plan {plan_id}.

The design reviewer raised these decomposition findings:
{findings_block}

Current features.json:
{feature_block}

Revise the decomposition to resolve every finding (split oversize features,
declare missing depends_on, sharpen exemplar ACs into invariants, declare
prerequisites, reorder dependencies). Return the revised features as JSON."""


# ─────────────────────────────── parsing ───────────────────────────────────


_JSON_FENCE_RE = re.compile(r"\A```(?:json)?\s*\n(.*)\n```\Z", re.DOTALL)


def _load_envelope_blob(raw: object) -> dict | None:
    """``raw`` as a JSON object carrying a ``verdict``, else None. Tolerates
    one surrounding ```json fence."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    fenced = _JSON_FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        blob = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(blob, dict) or "verdict" not in blob:
        return None
    return blob


def parse_design_envelope(raw: str, *, rounds: int = 1) -> DesignVolleyEnvelope:
    """Parse a design-reviewer's raw response into the standard envelope.

    Findings whose ``kind`` is outside the closed taxonomy are quarantined into
    ``unrecognized`` so the returned ``findings`` list is taxonomy-pure. A
    response that is not valid JSON or lacks a verdict is treated as
    ``blocked`` (the reviewer failed to produce a usable envelope)."""
    blob = _load_envelope_blob(raw)
    if blob is None:
        return DesignVolleyEnvelope(verdict="blocked", rounds=rounds, reviewed=False)

    verdict = blob.get("verdict")
    # An unknown verdict is coerced to blocked and is NOT a completed review
    # (it never advances the convergence ledger).
    coerced = verdict not in ("signed_off", "needs_changes", "blocked")
    if coerced:
        verdict = "blocked"

    findings: list[DesignFinding] = []
    unrecognized: list[dict] = []
    for raw_finding in blob.get("findings") or []:
        if not isinstance(raw_finding, dict):
            continue
        if raw_finding.get("kind") in DESIGN_TAXONOMY:
            findings.append(DesignFinding.from_dict(raw_finding))
        else:
            unrecognized.append(dict(raw_finding))
    return DesignVolleyEnvelope(
        verdict=verdict,
        findings=findings,
        rounds=rounds,
        unrecognized=unrecognized,
        reviewed=not coerced,
    )


# ─────────────────────────────── the volley ────────────────────────────────


def _dispatch_review(
    auditor: BaseExecutor,
    *,
    plan_id: str,
    plan_dir,
    features: Sequence[dict],
    objective_contract: dict | None,
    iteration: int,
    scope: ReviewScope | None = None,
) -> str:
    prompt = build_design_reviewer_prompt(plan_id, features, objective_contract, scope)
    task = DispatchTask(
        plan_id=plan_id,
        plan_dir=plan_dir,
        feature_id="(plan-decomposition)",
        feature_description="Design review of the whole plan decomposition.",
        feature_acceptance="No design defect in the decomposition.",
        feature_steps=[],
        agent_role=DESIGN_REVIEWER_ROLE,
        iteration=iteration,
        extra_context={"prompt_override": prompt},
    )
    result = auditor.dispatch(task)
    if not result.success:
        return ""  # parse_design_envelope → blocked
    # The executor's ``summary`` is the reviewer's final message; for Codex
    # ``raw_response`` is the whole ``exec --json`` event stream, which never
    # parses as an envelope. Take the first candidate that does.
    candidates = (result.summary, result.raw_response)
    for candidate in candidates:
        if _load_envelope_blob(candidate) is not None:
            return candidate
    return result.raw_response or result.summary or ""


def run_design_volley(
    plan_id: str,
    features: Sequence[dict],
    *,
    auditor: BaseExecutor,
    planner: BaseExecutor | None = None,
    objective_contract: dict | None = None,
    plan_dir=None,
    max_iterations: int = 2,
    scope: ReviewScope | None = None,
) -> DesignVolleyEnvelope:
    """Run the design-reviewer auditor (optionally against a planner implementer
    that revises on ``needs_changes``) and return the standard envelope.

    Mirrors ``dispatch_volley``'s loop shape: round 0 the auditor reviews; on
    ``needs_changes`` with a ``planner`` supplied it revises and the auditor
    re-reviews, up to ``max_iterations`` rounds. Terminates immediately on
    ``signed_off`` / ``blocked`` or when no planner can make progress. Pure
    w.r.t. the filesystem beyond what the injected executors do — which is
    nothing in the synthetic test (acceptance #4).

    ``scope`` (from :func:`compute_scope`) narrows a re-review to what changed
    since the ledger's last review; a scoped run with nothing in scope returns
    signed_off without dispatching (zero paid calls)."""
    scope = scope or FULL_SCOPE
    if scope.nothing_to_review:
        return DesignVolleyEnvelope(
            verdict="signed_off",
            rounds=0,
            scope_note="unchanged since last full review",
            reviewed=False,
        )
    current_features = list(features)
    last: DesignVolleyEnvelope | None = None
    for iteration in range(max(1, max_iterations)):
        raw = _dispatch_review(
            auditor,
            plan_id=plan_id,
            plan_dir=plan_dir,
            features=current_features,
            objective_contract=objective_contract,
            iteration=iteration,
            scope=scope,
        )
        last = apply_scope(parse_design_envelope(raw, rounds=iteration + 1), scope)
        if last.verdict != "needs_changes" or planner is None:
            return last
        # Planner revises to resolve the findings, then we re-review.
        plan_prompt = build_planner_prompt(plan_id, current_features, last.findings)
        task = DispatchTask(
            plan_id=plan_id,
            plan_dir=plan_dir,
            feature_id="(plan-decomposition)",
            feature_description="Revise the plan decomposition per design findings.",
            feature_acceptance="Every design finding resolved.",
            feature_steps=[],
            agent_role=PLANNER_ROLE,
            iteration=iteration,
            extra_context={"prompt_override": plan_prompt},
        )
        revised = planner.dispatch(task)
        if revised.success and revised.raw_response:
            try:
                parsed = json.loads(revised.raw_response)
                if isinstance(parsed, list):
                    current_features = parsed
                elif isinstance(parsed, dict) and isinstance(parsed.get("features"), list):
                    current_features = parsed["features"]
            except json.JSONDecodeError:
                pass  # keep prior features; auditor will re-review unchanged
    return last if last is not None else DesignVolleyEnvelope(verdict="blocked")
