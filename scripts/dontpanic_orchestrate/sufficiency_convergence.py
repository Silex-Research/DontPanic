"""Sufficiency-gate convergence — plan 2026-06-09-002.

Gives the pre-impl sufficiency gate a stopping condition. Four cooperating
surfaces, all offline (no auditor invocations anywhere in this module):

F006 — two-level finding identity. A stable SEMANTIC ``finding_id`` derived
from locator fields (journey_id + gap_class + sorted feature_refs + a
deterministic same-cell ordinal) so a reworded finding in the same cell keeps
its id across rounds; plus a content ``fingerprint`` over severity + class +
description + recommendation so a severity/class escalation is always a
material change. Fail-closed cell rule: any change to a cell's finding set
invalidates every disposition bound to that cell.

F001 — append-only rounds ledger (``sufficiency-rounds.jsonl`` beside
``sufficiency-findings.json``). Audit rounds are appended ONLY by
``run_sufficiency_audit`` (the one place the auditor actually runs); a
disposition-resolution lock pass never appends an audit round. Legacy
whole-plan overrides are logged as ``override_used`` events.

F002 — pure convergence policy over (ledger, dispositions). Branches:
(a) full clearance + every new finding medium/low/advisory AND classed in the
disposition-eligible set -> operator_disposition_required; (b) any high or
critical -> block; (c) plan_contract -> block, neutralizable only by
waived_with_reason or a clearing plan edit; (d) first round / no history ->
plain gate. Exhaustive over severity x class including the unclassified ->
plan_contract conservative fallback.

F003 — durable per-finding dispositions (``dispositions.json``), bound to
(finding_id, fingerprint, cell set), mirrored into the plan's decisions.jsonl,
strictly invalidated whenever the finding recurs materially changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.nested_orchestration import goal_governance_evidence_path

# ──────────────────────────────  constants  ──────────────────────────────

ROUNDS_LEDGER_ARTIFACT: str = "sufficiency-rounds.jsonl"
DISPOSITIONS_ARTIFACT: str = "dispositions.json"

FINDING_CLASSES: tuple[str, ...] = (
    "plan_contract",
    "implementation_detail",
    "editorial",
    "scope_guard",
    "matrix_pin",
)
"""Closed finding-class enum (F001)."""

CONSERVATIVE_FALLBACK_CLASS: str = "plan_contract"
"""Missing or invalid classifier data becomes plan_contract — blocking-
eligible, never silently disposition-eligible (operator invariant, D003)."""

DISPOSITION_ELIGIBLE_CLASSES: frozenset[str] = frozenset(
    {"matrix_pin", "implementation_detail", "editorial", "scope_guard"}
)

SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "advisory")
"""Full existing sufficiency severity vocabulary — advisory included."""

_HARD_BLOCK_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})
_GATE_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"critical", "high", "medium"})

WAIVED_MATRIX_PIN_HIGH: str = "waived_matrix_pin_high"
"""v1.1 (plan 2026-06-10-001): the ONLY kind that can suppress a HIGH
matrix_pin finding, and only once the ledger shows a full-clearance streak.
Requires explicit operator confirmation text — no default exists anywhere."""

MATRIX_PIN_STREAK_THRESHOLD: int = 2
"""v1.1 streak threshold N — the SINGLE source of truth consumed by
convergence_verdict, record_disposition validation, and the lock refusal
messaging alike (the three consumers cannot disagree)."""

MIN_CONFIRMATION_LENGTH: int = 20

CONFIRMATION_PLACEHOLDER: str = "<REPLACE WITH YOUR OPERATOR CONFIRMATION>"
"""Printed verbatim in the lock refusal's suggested command. Validation
REJECTS any reason containing this literal — copy-paste cannot mint a
canned confirmation."""

DISPOSITION_KINDS: tuple[str, ...] = (
    "accepted_into_plan",
    "deferred_to_impl",
    "waived_with_reason",
    "split_to_followup_plan",
    WAIVED_MATRIX_PIN_HIGH,
)
NO_AUDIT_DISPOSITION_KINDS: frozenset[str] = frozenset(
    {"deferred_to_impl", "waived_with_reason", "split_to_followup_plan",
     WAIVED_MATRIX_PIN_HIGH}
)
"""accepted_into_plan deliberately excluded: it means the operator will EDIT
the plan, which routes through the plain gate (fresh audit) by design."""

# Policy verdicts (F002).
VERDICT_PLAIN_GATE = "plain_gate"
VERDICT_BLOCK = "block"
VERDICT_DISPOSITION_REQUIRED = "operator_disposition_required"
VERDICT_PROCEED = "proceed"


class ConvergenceError(ValueError):
    """Raised on malformed ledger/disposition artifacts or invalid
    disposition requests. Subclasses ValueError for caller convenience."""


# ──────────────────────────────  F006: identity  ──────────────────────────────


def normalize_class(value: Any) -> str:
    """Conservative class normalization: a valid enum value passes through;
    anything missing or invalid becomes plan_contract (never a
    disposition-eligible class)."""
    if isinstance(value, str) and value.strip().lower() in FINDING_CLASSES:
        return value.strip().lower()
    return CONSERVATIVE_FALLBACK_CLASS


def cell_key(finding: dict[str, Any]) -> str:
    """Locator cell for a finding: journey x gap_class x feature_refs."""
    refs = ",".join(sorted(str(r) for r in finding.get("feature_refs") or []))
    return f"{finding.get('journey_id', '')}|{finding.get('gap_class', '')}|{refs}"


def finding_fingerprint(finding: dict[str, Any]) -> str:
    """Content fingerprint over severity + class + description +
    recommendation. A severity or class escalation is a material change."""
    parts = "\n".join(
        [
            str(finding.get("severity", "")).strip().lower(),
            normalize_class(finding.get("finding_class")),
            str(finding.get("description", "")),
            str(finding.get("recommendation") or ""),
        ]
    )
    return "fp-" + hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def assign_identities(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return enriched copies of ``findings`` with ``finding_id``,
    ``fingerprint``, ``finding_class`` (normalized), and ``cell_key``.

    Same-cell ordinals are assigned by a deterministic sort over the cell's
    content fingerprints — never by auditor output order — so reordering the
    auditor's output cannot change identity.
    """
    enriched: list[dict[str, Any]] = []
    by_cell: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        item = dict(f)
        item["finding_class"] = normalize_class(f.get("finding_class"))
        item["fingerprint"] = finding_fingerprint(item)
        item["cell_key"] = cell_key(item)
        by_cell.setdefault(item["cell_key"], []).append(item)
        enriched.append(item)
    for cell, members in by_cell.items():
        for ordinal, item in enumerate(sorted(members, key=lambda m: m["fingerprint"])):
            raw = f"{cell}#{ordinal}"
            item["finding_id"] = "f-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return enriched


def cell_fingerprint_sets(enriched: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Map cell_key -> sorted fingerprints of that cell's findings. Used by
    the fail-closed cell-invalidation rule."""
    cells: dict[str, list[str]] = {}
    for item in enriched:
        cells.setdefault(item["cell_key"], []).append(item["fingerprint"])
    return {k: sorted(v) for k, v in cells.items()}


# ──────────────────────────────  F001: rounds ledger  ──────────────────────────────


def _ledger_path(plan_dir: Path) -> Path:
    return goal_governance_evidence_path(plan_dir, "pre_impl", ROUNDS_LEDGER_ARTIFACT)


def read_ledger(plan_dir: Path) -> list[dict[str, Any]]:
    path = _ledger_path(Path(plan_dir).resolve())
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ConvergenceError(f"{path}:{line_no}: malformed ledger line: {exc}") from exc
    return records


def audit_rounds(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in ledger if r.get("type") == "audit_round"]


def latest_round(ledger: list[dict[str, Any]]) -> dict[str, Any] | None:
    rounds = audit_rounds(ledger)
    return rounds[-1] if rounds else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_round_record(
    findings: list[dict[str, Any]],
    *,
    prior: dict[str, Any] | None,
    input_fingerprint: str,
    round_number: int,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Pure round-record construction (separated from I/O for the fixture
    replay tests).

    Clearance accounting is by (finding_id, fingerprint): a finding PERSISTS
    only when both match. A same-cell finding with CHANGED content is a
    cleared-old + new-finding pair — the prior finding was resolved and a
    materially different one took the cell (the matrix-enumeration pattern
    this plan governs). Disposition safety is unaffected: dispositions bind
    the fingerprint, so the new occupant is blocking until disposed.
    """
    enriched = assign_identities(findings)
    new_pairs = {(item["finding_id"], item["fingerprint"]) for item in enriched}
    prior_findings = prior.get("findings", []) if prior is not None else []
    prior_ids = {f["finding_id"] for f in prior_findings}
    persisted = {
        f["finding_id"]
        for f in prior_findings
        if (f["finding_id"], f["fingerprint"]) in new_pairs
    }
    return {
        "type": "audit_round",
        "round": round_number,
        "input_fingerprint": input_fingerprint,
        "generated_at": generated_at or _utc_now(),
        "finding_count": len(enriched),
        "findings": [
            {
                "finding_id": item["finding_id"],
                "fingerprint": item["fingerprint"],
                "severity": str(item.get("severity", "")).strip().lower(),
                "finding_class": item["finding_class"],
                "journey_id": item.get("journey_id", ""),
                "gap_class": item.get("gap_class", ""),
                "feature_refs": list(item.get("feature_refs") or []),
                "cell_key": item["cell_key"],
                "description": item.get("description", ""),
            }
            for item in enriched
        ],
        "cleared_ids": sorted(prior_ids - persisted),
        "persisted_ids": sorted(persisted),
        "prior_finding_count": len(prior_ids) if prior is not None else None,
    }


def append_audit_round(
    plan_dir: Path,
    findings: list[dict[str, Any]],
    *,
    input_fingerprint: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Append an audit round to the ledger. Called ONLY from
    ``run_sufficiency_audit`` — the one place the auditor actually runs."""
    plan_dir = Path(plan_dir).resolve()
    ledger = read_ledger(plan_dir)
    record = build_round_record(
        findings,
        prior=latest_round(ledger),
        input_fingerprint=input_fingerprint,
        round_number=len(audit_rounds(ledger)) + 1,
        generated_at=generated_at,
    )
    path = _ledger_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def append_override_event(plan_dir: Path, *, reason: str, approved_by: str) -> dict[str, Any]:
    """Log a legacy --ignore-sufficiency-findings override into the ledger.
    The override itself lives in override.json exactly as before — this is
    the required usage log, nothing more."""
    plan_dir = Path(plan_dir).resolve()
    record = {
        "type": "override_used",
        "recorded_at": _utc_now(),
        "reason": reason,
        "approved_by": approved_by,
    }
    path = _ledger_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def full_clearance(record: dict[str, Any]) -> bool:
    """True iff this round cleared 100% of the prior round's findings (and a
    prior round existed)."""
    return record.get("prior_finding_count") is not None and not record.get("persisted_ids")


def clearance_streak(ledger: list[dict[str, Any]]) -> int:
    """v1.1 — count consecutive full-clearance AUDIT rounds ending at the
    latest round. Override events are excluded by construction
    (:func:`audit_rounds`). The FIRST round of any ledger is never
    full-clearance (nothing preceded it to clear), so a ledger whose rounds
    each cleared their predecessor has streak == round_count - 1.
    Pinned worked example (C0 live rounds): streak at round 3 is exactly 2,
    at round 2 exactly 1, at round 1 exactly 0."""
    rounds = audit_rounds(ledger)
    streak = 0
    for record in reversed(rounds):
        if full_clearance(record):
            streak += 1
        else:
            break
    return streak


# ──────────────────────────────  F003: dispositions  ──────────────────────────────


def _dispositions_path(plan_dir: Path) -> Path:
    return goal_governance_evidence_path(plan_dir, "pre_impl", DISPOSITIONS_ARTIFACT)


def load_dispositions(plan_dir: Path) -> dict[str, dict[str, Any]]:
    path = _dispositions_path(Path(plan_dir).resolve())
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConvergenceError(f"{path}: malformed dispositions file: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("dispositions"), dict):
        raise ConvergenceError(f"{path}: expected mapping with 'dispositions' object")
    return data["dispositions"]


def record_disposition(
    plan_dir: Path,
    *,
    finding_id: str,
    kind: str,
    reason: str | None = None,
    followup_plan: str | None = None,
    recorded_by: str = "operator",
    streak_threshold: int = MATRIX_PIN_STREAK_THRESHOLD,
) -> dict[str, Any]:
    """Record one per-finding disposition against the LATEST audit round.

    Validation (all fail-closed):
    - the finding must exist in the latest round;
    - kind must be one of the registered kinds;
    - waived_with_reason REQUIRES a non-empty reason;
    - split_to_followup_plan REQUIRES a follow-up plan reference;
    - deferred_to_impl / split_to_followup_plan are REFUSED for
      plan_contract findings (only a waiver or a plan edit neutralizes those);
    - v1.1: waived_matrix_pin_high is accepted ONLY for a finding whose
      latest-round severity is high AND class is matrix_pin AND whose ledger
      streak satisfies clearance_streak >= streak_threshold, with operator
      confirmation text of at least MIN_CONFIRMATION_LENGTH characters that
      does not contain the literal CONFIRMATION_PLACEHOLDER.

    The disposition binds the finding's fingerprint AND its cell's
    fingerprint set, so any material change re-surfaces it as blocking.
    Mirrored into the plan's decisions.jsonl for the audit trail.
    """
    plan_dir = Path(plan_dir).resolve()
    if kind not in DISPOSITION_KINDS:
        raise ConvergenceError(f"unknown disposition kind {kind!r}; expected one of {DISPOSITION_KINDS}")
    if kind == "waived_with_reason" and not (reason and reason.strip()):
        raise ConvergenceError("waived_with_reason requires a non-empty --reason")
    if kind == "split_to_followup_plan" and not (followup_plan and followup_plan.strip()):
        raise ConvergenceError("split_to_followup_plan requires a --followup plan reference")

    ledger = read_ledger(plan_dir)
    current = latest_round(ledger)
    if current is None:
        raise ConvergenceError(f"{_ledger_path(plan_dir)}: no audit rounds recorded — nothing to disposition")
    by_id = {f["finding_id"]: f for f in current.get("findings", [])}
    finding = by_id.get(finding_id)
    if finding is None:
        known = ", ".join(sorted(by_id)) or "<none>"
        raise ConvergenceError(
            f"finding {finding_id!r} not present in the latest audit round; known ids: {known}"
        )
    if finding["finding_class"] == "plan_contract" and kind in (
        "deferred_to_impl",
        "split_to_followup_plan",
    ):
        raise ConvergenceError(
            f"finding {finding_id} is classed plan_contract — only waived_with_reason "
            "(or an actual plan edit that clears it) neutralizes a plan_contract finding"
        )
    if kind == WAIVED_MATRIX_PIN_HIGH:
        if finding.get("severity") != "high":
            raise ConvergenceError(
                f"finding {finding_id} is {finding.get('severity')!r} — "
                f"{WAIVED_MATRIX_PIN_HIGH} applies ONLY to high-severity findings"
            )
        if finding.get("finding_class") != "matrix_pin":
            raise ConvergenceError(
                f"finding {finding_id} is classed {finding.get('finding_class')!r} — "
                f"{WAIVED_MATRIX_PIN_HIGH} applies ONLY to auditor-classed matrix_pin findings"
            )
        streak = clearance_streak(ledger)
        if streak < streak_threshold:
            raise ConvergenceError(
                f"clearance streak is {streak} but {WAIVED_MATRIX_PIN_HIGH} requires "
                f">= {streak_threshold} consecutive full-clearance rounds — "
                "the eligibility is not unlocked yet"
            )
        text = (reason or "").strip()
        if CONFIRMATION_PLACEHOLDER in text:
            raise ConvergenceError(
                f"{WAIVED_MATRIX_PIN_HIGH} refuses the literal placeholder text — "
                "replace it with your own operator confirmation"
            )
        if len(text) < MIN_CONFIRMATION_LENGTH:
            raise ConvergenceError(
                f"{WAIVED_MATRIX_PIN_HIGH} requires explicit operator confirmation "
                f"text of at least {MIN_CONFIRMATION_LENGTH} characters"
            )

    cells = {}
    for f in current.get("findings", []):
        cells.setdefault(f["cell_key"], []).append(f["fingerprint"])
    entry = {
        "kind": kind,
        "reason": reason,
        "followup_plan": followup_plan,
        "fingerprint": finding["fingerprint"],
        "cell_key": finding["cell_key"],
        "cell_set": sorted(cells[finding["cell_key"]]),
        "round": current.get("round"),
        "input_fingerprint": current.get("input_fingerprint"),
        "recorded_at": _utc_now(),
        "recorded_by": recorded_by,
    }

    path = _dispositions_path(plan_dir)
    existing = load_dispositions(plan_dir)
    existing[finding_id] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "dispositions": existing}, indent=2, ensure_ascii=False)
        + "\n"
    )

    decisions = plan_dir / "decisions.jsonl"
    mirror = {
        "id": f"DSP-{finding_id}",
        "decision": (
            f"Sufficiency finding {finding_id} ({finding['severity']}/"
            f"{finding['finding_class']}, cell {finding['cell_key']}) dispositioned "
            f"{kind} by {recorded_by} at round {current.get('round')}."
            + (f" Follow-up: {followup_plan}." if followup_plan else "")
        ),
        "rationale": reason or kind,
    }
    with decisions.open("a") as fh:
        fh.write(json.dumps(mirror, ensure_ascii=False) + "\n")
    return entry


def effective_dispositions(
    plan_dir: Path, current: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    """Dispositions still VALID against the latest round. Strict invalidation:

    - the finding id must still exist in the latest round;
    - its fingerprint must equal the bound one (severity/class escalation or
      any content change re-surfaces it);
    - the cell's fingerprint SET must equal the bound one (fail-closed cell
      rule — any insertion/removal/change in the cell invalidates every
      disposition bound to that cell).
    """
    plan_dir = Path(plan_dir).resolve()
    if current is None:
        current = latest_round(read_ledger(plan_dir))
    if current is None:
        return {}
    recorded = load_dispositions(plan_dir)
    by_id = {f["finding_id"]: f for f in current.get("findings", [])}
    cells: dict[str, list[str]] = {}
    for f in current.get("findings", []):
        cells.setdefault(f["cell_key"], []).append(f["fingerprint"])
    valid: dict[str, dict[str, Any]] = {}
    for fid, entry in recorded.items():
        finding = by_id.get(fid)
        if finding is None:
            continue  # finding gone — disposition moot
        if finding["fingerprint"] != entry.get("fingerprint"):
            continue  # material change — re-surfaces as blocking
        if sorted(cells.get(entry.get("cell_key", ""), [])) != entry.get("cell_set"):
            continue  # cell set changed — fail-closed invalidation
        valid[fid] = entry
    return valid


# ──────────────────────────────  F002: convergence policy  ──────────────────────────────


@dataclass(frozen=True)
class PolicyVerdict:
    verdict: str
    branch: str
    detail: str
    undisposed_ids: tuple[str, ...] = field(default_factory=tuple)
    # v1.1 — high matrix_pin finding ids whose streak eligibility is
    # unlocked but which carry no valid waived_matrix_pin_high yet.
    streak_unlocked_ids: tuple[str, ...] = field(default_factory=tuple)


def _streak_eligible(finding: dict[str, Any], *, streak_ok: bool) -> bool:
    """v1.1 eligibility cell: HIGH severity + auditor-emitted matrix_pin +
    unlocked streak. Critical, plan_contract (any severity), and
    conservative-fallback classifications are never eligible."""
    return (
        streak_ok
        and finding.get("severity") == "high"
        and finding.get("finding_class") == "matrix_pin"
    )


def _suppressed(
    finding: dict[str, Any],
    disposition: dict[str, Any] | None,
    *,
    streak_ok: bool = False,
) -> bool:
    """A blocking finding is suppressed iff a VALID disposition of a
    permitted kind covers it. plan_contract only yields to a waiver;
    accepted_into_plan never suppresses (it demands a plan edit + fresh
    audit by design). v1.1: a HIGH matrix_pin yields ONLY to the dedicated
    waived_matrix_pin_high kind and ONLY when the streak is unlocked; the
    dedicated kind suppresses nothing else."""
    if disposition is None:
        return False
    kind = disposition.get("kind")
    if kind not in NO_AUDIT_DISPOSITION_KINDS:
        return False  # accepted_into_plan (or junk) — still blocking
    if finding.get("severity") in _HARD_BLOCK_SEVERITIES:
        return (
            kind == WAIVED_MATRIX_PIN_HIGH
            and _streak_eligible(finding, streak_ok=streak_ok)
        )
    if kind == WAIVED_MATRIX_PIN_HIGH:
        return False  # the dedicated kind never covers non-high-matrix-pin cells
    if finding["finding_class"] == "plan_contract":
        return kind == "waived_with_reason"
    return True


def convergence_verdict(
    ledger: list[dict[str, Any]],
    dispositions: dict[str, dict[str, Any]],
    *,
    streak_threshold: int = MATRIX_PIN_STREAK_THRESHOLD,
) -> PolicyVerdict:
    """Pure, deterministic policy verdict for the latest round.

    No I/O beyond the arguments. Same inputs -> same verdict.
    """
    rounds = audit_rounds(ledger)
    if len(rounds) < 2:
        return PolicyVerdict(
            VERDICT_PLAIN_GATE,
            "d_first_round",
            "no prior-round history — the plain gate applies unchanged",
        )

    current = rounds[-1]
    streak = clearance_streak(ledger)
    streak_ok = streak >= streak_threshold
    findings = current.get("findings", [])
    blocking = [f for f in findings if f.get("severity") in _GATE_BLOCKING_SEVERITIES]
    # High/critical findings are not suppressible by per-finding disposition
    # — with ONE v1.1 exception: a high matrix_pin under an unlocked
    # full-clearance streak yields to waived_matrix_pin_high (and nothing
    # else). Critical and plan_contract highs keep the plain hard block;
    # only the legacy whole-plan override bypasses them.
    remaining = [
        f
        for f in blocking
        if not _suppressed(f, dispositions.get(f["finding_id"]), streak_ok=streak_ok)
    ]

    if not remaining:
        return PolicyVerdict(
            VERDICT_PROCEED,
            "resolved_by_disposition",
            "every blocking finding of the latest round is covered by a valid "
            "no-audit disposition — zero further auditor invocations required",
        )

    hard = [f for f in remaining if f.get("severity") in _HARD_BLOCK_SEVERITIES]
    if hard:
        ids = ", ".join(f["finding_id"] for f in hard)
        unlocked = tuple(
            f["finding_id"] for f in hard if _streak_eligible(f, streak_ok=streak_ok)
        )
        detail = f"new high/critical finding(s) keep the hard block: {ids}"
        if unlocked:
            detail += (
                f"; streak-unlocked eligibility ({streak} consecutive full-"
                f"clearance rounds >= {streak_threshold}): "
                + ", ".join(unlocked)
                + f" — resolvable via the {WAIVED_MATRIX_PIN_HIGH} disposition"
            )
        return PolicyVerdict(
            VERDICT_BLOCK,
            "b_high_severity",
            detail,
            tuple(f["finding_id"] for f in remaining),
            unlocked,
        )

    contracts = [f for f in remaining if f.get("finding_class") == "plan_contract"]
    if contracts:
        ids = ", ".join(f["finding_id"] for f in contracts)
        return PolicyVerdict(
            VERDICT_BLOCK,
            "c_plan_contract",
            f"plan_contract finding(s) block unless explicitly waived: {ids}",
            tuple(f["finding_id"] for f in remaining),
        )

    eligible = all(
        f.get("severity") in ("medium", "low", "advisory")
        and f.get("finding_class") in DISPOSITION_ELIGIBLE_CLASSES
        for f in current.get("findings", [])
    )
    if full_clearance(current) and eligible:
        ids = tuple(f["finding_id"] for f in remaining)
        return PolicyVerdict(
            VERDICT_DISPOSITION_REQUIRED,
            "a_full_clearance_pins",
            "this round fully cleared the prior round and every new finding is a "
            "medium/low/advisory disposition-eligible pin — record per-finding "
            f"dispositions instead of another paid re-lock: {', '.join(ids)}",
            ids,
        )

    ids = ", ".join(f["finding_id"] for f in remaining)
    return PolicyVerdict(
        VERDICT_BLOCK,
        "default_plain_block",
        f"blocking finding(s) without convergence conditions met: {ids}",
        tuple(f["finding_id"] for f in remaining),
    )


def verdict_for(
    severity: str, finding_class: str | None, *, streak_ok: bool = False
) -> str:
    """Single-finding verdict cell — the exhaustive severity x class matrix
    (test surface for F002). advisory/low never hard-block on their own.
    v1.1 adds the ONE streak-conditional cell: high + matrix_pin becomes
    disposition-eligible when the caller's ledger streak is unlocked; every
    other cell is identical in both streak contexts."""
    sev = (severity or "").strip().lower()
    cls = normalize_class(finding_class)
    if sev not in SEVERITIES:
        raise ConvergenceError(f"unknown severity {sev!r}; expected one of {SEVERITIES}")
    if sev in ("low", "advisory"):
        return "pass"
    if sev in _HARD_BLOCK_SEVERITIES:
        if sev == "high" and cls == "matrix_pin" and streak_ok:
            return "disposition_eligible_with_streak"
        return "block"
    # medium:
    if cls == "plan_contract":
        return "block_unless_waived"
    return "disposition_eligible"


def gate_decision(plan_dir: Path) -> PolicyVerdict:
    """Convenience wrapper for the lock path (F005): read ledger +
    effective dispositions from disk and return the policy verdict.
    Performs NO auditor invocation under any circumstance."""
    plan_dir = Path(plan_dir).resolve()
    ledger = read_ledger(plan_dir)
    current = latest_round(ledger)
    dispositions = effective_dispositions(plan_dir, current)
    return convergence_verdict(ledger, dispositions)


__all__ = [
    "CONFIRMATION_PLACEHOLDER",
    "CONSERVATIVE_FALLBACK_CLASS",
    "DISPOSITIONS_ARTIFACT",
    "DISPOSITION_ELIGIBLE_CLASSES",
    "DISPOSITION_KINDS",
    "FINDING_CLASSES",
    "MATRIX_PIN_STREAK_THRESHOLD",
    "MIN_CONFIRMATION_LENGTH",
    "NO_AUDIT_DISPOSITION_KINDS",
    "ROUNDS_LEDGER_ARTIFACT",
    "SEVERITIES",
    "WAIVED_MATRIX_PIN_HIGH",
    "ConvergenceError",
    "PolicyVerdict",
    "append_audit_round",
    "append_override_event",
    "assign_identities",
    "audit_rounds",
    "build_round_record",
    "cell_fingerprint_sets",
    "cell_key",
    "clearance_streak",
    "convergence_verdict",
    "effective_dispositions",
    "finding_fingerprint",
    "full_clearance",
    "gate_decision",
    "latest_round",
    "load_dispositions",
    "normalize_class",
    "read_ledger",
    "record_disposition",
    "verdict_for",
]
