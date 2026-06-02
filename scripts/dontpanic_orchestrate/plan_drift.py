"""plan_drift — active-run plan drift reconciliation.

Plan 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 F009 AC(1)-(7).

While DontPanic is running a volley, the plan artifacts it dispatched against
can change underneath it — one interactive agent edits ``features.json`` or the
plan frontmatter while another agent (or a worker volley) is still operating
from the context captured at dispatch. Continuing to spend paid agent calls on
stale context silently is the failure mode this module prevents.

The contract:

  * At dispatch start the supervisor records a *plan-run fingerprint* — a
    content hash + semantic projection of every artifact that affects dispatch
    semantics (:func:`compute_fingerprint`, :func:`record_baseline`).
  * Before each expensive/policy-relevant step (implementer call, auditor call,
    signoff finalization) the supervisor recomputes the fingerprint and compares
    (:func:`check_and_reconcile`).
  * Drift is classified into three bands (:class:`DriftClass`):
      - ``ADDITIVE_LEDGER`` — a new ``decisions.jsonl`` note and nothing else.
        Reconciled WITHOUT stopping: the baseline is advanced and an INBOX
        event is recorded, then the volley continues.
      - ``CONTEXT_REFRESH`` — acceptance / feature-list / gate / role /
        loop-cap / objective-contract drift. The volley PAUSES before the next
        paid call and the operator is told how to refresh + redispatch.
      - ``BLOCKING_POLICY`` — scope / policy drift (``allowed_paths``,
        ``forbidden_decisions``, ``protected_paths``). The volley pauses and a
        human MUST acknowledge before continuing.
  * One concise :class:`operations_guidance.Guidance` (a single ActionChoice)
    is emitted for a refresh/blocking drift, not a repeated stream of warnings
    (AC6). The additive path advances the baseline so the same note is never
    re-reported.

The fingerprint + classifier are pure (no IO beyond reading the tracked files).
``record_baseline`` / ``read_baseline`` / ``check_and_reconcile`` are the thin
IO layer the supervisor wires in.

``audit/gate-state.json`` IS tracked, but via a *stable semantic projection*
(``cleared_gates`` + ``completed_stages``), not a raw hash. The supervisor
mutates gate-state during a normal run (record_pause appends volatile history;
auto-clear flips a gate), so hashing the whole file would manufacture phantom
drift on every check. Two safeguards keep the projection honest without
false positives:
  * The projection drops the volatile ``history`` / timestamp fields, so a
    record_pause that only appends history is invisible.
  * When the supervisor performs its OWN legitimate gate mutation (e.g.
    auto-clearing ``pre_impl``) it calls :func:`advance_gate_baseline`, which
    folds the new gate projection into the persisted baseline. The next check
    therefore only flags gate-state changes made by *another* process — exactly
    the mid-run human tamper (clearing a gate to bypass a pause) we must catch.
Gate *configuration* drift — a human editing the plan's declared
``human_gates`` — is still detected separately through the ``plan.md``
frontmatter projection, which is the source of truth for declared gates.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

# ─────────────────────────────── tracked files ─────────────────────────────

# Relative paths (under plan_dir) whose content/semantics affect dispatch.
# Order is stable so ``changed_files`` reads deterministically.
PLAN_MD = "plan.md"
FEATURES_JSON = "features.json"
DECISIONS_JSONL = "decisions.jsonl"
OBJECTIVE_CONTRACT_JSON = "objective_contract.json"
GATE_STATE_JSON = "audit/gate-state.json"

TRACKED_FILES: tuple[str, ...] = (
    PLAN_MD,
    FEATURES_JSON,
    DECISIONS_JSONL,
    OBJECTIVE_CONTRACT_JSON,
    GATE_STATE_JSON,
)

# Baseline fingerprint persisted at dispatch start, under audit/.
BASELINE_FILENAME = "plan-run-fingerprint.json"


def baseline_path(plan_dir: Path) -> Path:
    return Path(plan_dir) / "audit" / BASELINE_FILENAME


# ───────────────────────────────── vocabulary ──────────────────────────────


class DriftBaselineMissingError(RuntimeError):
    """Raised when a drift check is asked to compare against an active-run
    baseline that is absent or corrupt.

    F009 codex #1 — a missing/corrupt baseline means the true dispatch-start
    disk state has been LOST, so drift can no longer be detected against it.
    A safety mechanism must FAIL CLOSED: rather than silently recording the
    *current* (possibly already-drifted) state as a fresh baseline and
    proceeding — which would bless stale context as if it were the original —
    the check raises so the supervisor pauses the volley before the next paid
    call. Recovery is operator-driven: verify the plan files on disk and
    redispatch so a clean dispatch-start baseline is recorded."""


class DriftClass(str, Enum):
    """Severity bands, ordered NONE < ADDITIVE < REFRESH < BLOCKING."""

    NONE = "none"
    ADDITIVE_LEDGER = "additive_ledger"
    CONTEXT_REFRESH = "context_refresh"
    BLOCKING_POLICY = "blocking_policy"


_PRECEDENCE: dict[DriftClass, int] = {
    DriftClass.NONE: 0,
    DriftClass.ADDITIVE_LEDGER: 1,
    DriftClass.CONTEXT_REFRESH: 2,
    DriftClass.BLOCKING_POLICY: 3,
}


def _max_class(a: DriftClass, b: DriftClass) -> DriftClass:
    return a if _PRECEDENCE[a] >= _PRECEDENCE[b] else b


# Stage labels — where in the volley a check fires (for the INBOX/guidance text).
STAGE_DISPATCH = "dispatch"
STAGE_IMPLEMENTER = "before_implementer_call"
STAGE_AUDITOR = "before_auditor_call"
STAGE_SIGNOFF = "before_signoff_finalization"


# ───────────────────────────── helpers (pure IO read) ──────────────────────


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text_or_none(path: Path) -> str | None:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def _mtime_or_none(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _frontmatter_dict(plan_md_text: str | None) -> dict[str, Any]:
    """Parse the YAML frontmatter block from plan.md text. Tolerant: returns
    an empty dict when the file is missing or malformed (the file-hash diff
    still flags the change; the projection just contributes nothing)."""
    if not plan_md_text or not plan_md_text.startswith("---"):
        return {}
    parts = plan_md_text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        loaded = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _plan_semantics(fm: dict[str, Any]) -> dict[str, Any]:
    """Project the dispatch-relevant plan.md frontmatter fields. Scope/policy
    fields (allowed_paths / forbidden_decisions / protected_paths) and
    refresh-relevant fields (status / roles / gates / loop_caps / deps) only."""
    charter = fm.get("child_charter") or {}
    if not isinstance(charter, dict):
        charter = {}
    return {
        "status": fm.get("status"),
        "agents_required": fm.get("agents_required"),
        "human_gates": fm.get("human_gates"),
        "loop_caps": fm.get("loop_caps"),
        "dependencies": fm.get("dependencies"),
        "protected_paths": fm.get("protected_paths"),
        "allowed_paths": charter.get("allowed_paths"),
        "forbidden_decisions": charter.get("forbidden_decisions"),
    }


def _features_semantics(features_text: str | None) -> dict[str, Any]:
    """Project per-feature acceptance + dependency + gate/role surface from
    features.json. Tolerant of malformed JSON (returns empty projection; the
    file hash still flags the raw change)."""
    if not features_text:
        return {"feature_ids": [], "by_id": {}}
    try:
        data = json.loads(features_text)
    except json.JSONDecodeError:
        return {"feature_ids": [], "by_id": {}}
    feats = data.get("features") if isinstance(data, dict) else data
    if not isinstance(feats, list):
        return {"feature_ids": [], "by_id": {}}
    by_id: dict[str, Any] = {}
    ids: list[str] = []
    for f in feats:
        if not isinstance(f, dict):
            continue
        fid = f.get("id")
        if fid is None:
            continue
        ids.append(str(fid))
        by_id[str(fid)] = {
            "acceptance": f.get("acceptance"),
            "depends_on": f.get("depends_on"),
            "agents_required": f.get("agents_required"),
            "passes": f.get("passes"),
        }
    return {"feature_ids": ids, "by_id": by_id}


_DEC_SEP = "\x1f"  # unit separator — joins a decision's id with its content hash


def _decision_lines(decisions_text: str | None) -> list[str]:
    """Per-line fingerprints of decisions.jsonl, ordered.

    Each entry is ``"<id>\\x1f<content_hash>"`` so a change to a decision's BODY
    (not just its id) is visible. Tracking ids alone would let a rewritten
    existing decision pass as additive whenever a NEW decision was appended in
    the same edit (ids ``("D001",) -> ("D001","D002")`` look like a clean
    append even if D001's body was rewritten). Folding the content hash into the
    fingerprint closes that hole: an append is only additive when every existing
    line is byte-identical (its full ``id\\x1fhash`` token is unchanged)."""
    if not decisions_text:
        return []
    out: list[str] = []
    for idx, line in enumerate(decisions_text.splitlines()):
        line = line.strip()
        if not line:
            continue
        content_hash = _sha256_text(line)
        try:
            obj = json.loads(line)
            did = str(obj.get("id", f"_pos{idx}"))
        except json.JSONDecodeError:
            did = f"_bad{idx}"
        out.append(f"{did}{_DEC_SEP}{content_hash}")
    return out


def _decision_id_of(token: str) -> str:
    """Extract the decision id from a ``"<id>\\x1f<hash>"`` line fingerprint."""
    return token.split(_DEC_SEP, 1)[0]


def _gate_semantics(gate_text: str | None) -> dict[str, Any]:
    """Stable projection of audit/gate-state.json: the cleared-gate set and the
    completed-stage set ONLY. The volatile ``history`` list and any timestamps
    are deliberately excluded so the supervisor's normal record_pause history
    appends do not manufacture drift — only an externally-changed cleared/
    completed set (e.g. a human clearing a gate mid-run to bypass a pause)
    registers. Sorted so set-equal states with different insertion order
    compare equal. Tolerant of a missing/malformed file (empty projection; the
    file hash still flags the raw change)."""
    if not gate_text:
        return {"cleared_gates": [], "completed_stages": []}
    try:
        data = json.loads(gate_text)
    except json.JSONDecodeError:
        return {"cleared_gates": [], "completed_stages": []}
    if not isinstance(data, dict):
        return {"cleared_gates": [], "completed_stages": []}
    cleared = data.get("cleared_gates")
    completed = data.get("completed_stages")
    return {
        "cleared_gates": sorted(str(g) for g in cleared) if isinstance(cleared, list) else [],
        "completed_stages": (
            sorted(str(s) for s in completed) if isinstance(completed, list) else []
        ),
    }


# ────────────────────────────── fingerprint ────────────────────────────────


@dataclass(frozen=True)
class PlanFingerprint:
    """Content hashes + semantic projection of the tracked plan artifacts."""

    file_hashes: dict[str, str | None]
    file_mtimes: dict[str, float | None]
    plan_semantics: dict[str, Any]
    features_semantics: dict[str, Any]
    gate_semantics: dict[str, Any]
    decision_lines: tuple[str, ...]
    objective_hash: str | None
    captured_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_hashes": self.file_hashes,
            "file_mtimes": self.file_mtimes,
            "plan_semantics": self.plan_semantics,
            "features_semantics": self.features_semantics,
            "gate_semantics": self.gate_semantics,
            "decision_lines": list(self.decision_lines),
            "objective_hash": self.objective_hash,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanFingerprint:
        return cls(
            file_hashes=dict(data.get("file_hashes") or {}),
            file_mtimes=dict(data.get("file_mtimes") or {}),
            plan_semantics=dict(data.get("plan_semantics") or {}),
            features_semantics=dict(data.get("features_semantics") or {}),
            gate_semantics=dict(data.get("gate_semantics") or {}),
            decision_lines=tuple(data.get("decision_lines") or ()),
            objective_hash=data.get("objective_hash"),
            captured_at=data.get("captured_at") or "",
        )


def compute_fingerprint(plan_dir: Path) -> PlanFingerprint:
    """Read the tracked artifacts and build a :class:`PlanFingerprint`. Pure
    apart from reading files; never raises on a missing/malformed file (the
    corresponding projection is empty and the hash is ``None``)."""
    plan_dir = Path(plan_dir)
    texts: dict[str, str | None] = {}
    hashes: dict[str, str | None] = {}
    mtimes: dict[str, float | None] = {}
    for rel in TRACKED_FILES:
        p = plan_dir / rel
        text = _read_text_or_none(p)
        texts[rel] = text
        hashes[rel] = _sha256_text(text) if text is not None else None
        mtimes[rel] = _mtime_or_none(p)

    fm = _frontmatter_dict(texts.get(PLAN_MD))
    objective_text = texts.get(OBJECTIVE_CONTRACT_JSON)
    return PlanFingerprint(
        file_hashes=hashes,
        file_mtimes=mtimes,
        plan_semantics=_plan_semantics(fm),
        features_semantics=_features_semantics(texts.get(FEATURES_JSON)),
        gate_semantics=_gate_semantics(texts.get(GATE_STATE_JSON)),
        decision_lines=tuple(_decision_lines(texts.get(DECISIONS_JSONL))),
        objective_hash=_sha256_text(objective_text) if objective_text is not None else None,
        captured_at=_now_iso(),
    )


# ───────────────────────────────── classify ────────────────────────────────


@dataclass(frozen=True)
class ChangeNote:
    """One structured change observed between two fingerprints."""

    dimension: str  # e.g. "allowed_paths", "features.acceptance", "decisions"
    drift_class: DriftClass
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "drift_class": self.drift_class.value,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class DriftReport:
    """Result of comparing the baseline fingerprint to the current one."""

    drift_class: DriftClass
    changed_files: tuple[str, ...]
    changes: tuple[ChangeNote, ...]
    stage: str = STAGE_DISPATCH

    @property
    def has_drift(self) -> bool:
        return self.drift_class is not DriftClass.NONE

    @property
    def budget_protected(self) -> bool:
        """True when this drift caused (or would cause) a pause BEFORE the next
        paid agent call — i.e. refresh/blocking. Additive drift does not pause,
        so it does not "protect budget" (none needed)."""
        return _PRECEDENCE[self.drift_class] >= _PRECEDENCE[DriftClass.CONTEXT_REFRESH]

    def headline(self, plan_id: str) -> str:
        files = ", ".join(self.changed_files) or "plan artifacts"
        if self.drift_class is DriftClass.ADDITIVE_LEDGER:
            return (
                f"Plan {plan_id}: additive decisions.jsonl note detected "
                f"({files}) — reconciled without stopping."
            )
        if self.drift_class is DriftClass.CONTEXT_REFRESH:
            return (
                f"Plan {plan_id}: context-refresh drift in {files} — paused "
                f"before the next paid call; redispatch with refreshed context."
            )
        if self.drift_class is DriftClass.BLOCKING_POLICY:
            return (
                f"Plan {plan_id}: scope/policy drift in {files} — paused; "
                f"human acknowledgement required before continuing."
            )
        return f"Plan {plan_id}: no plan drift."

    def to_dict(self) -> dict[str, Any]:
        return {
            "drift_class": self.drift_class.value,
            "changed_files": list(self.changed_files),
            "changes": [c.to_dict() for c in self.changes],
            "stage": self.stage,
            "budget_protected": self.budget_protected,
        }


def _decisions_change(
    before: tuple[str, ...], after: tuple[str, ...]
) -> ChangeNote | None:
    """Classify a decisions.jsonl change.

    ``before``/``after`` are tuples of ``"<id>\\x1f<content_hash>"`` line
    fingerprints. Pure-append (every existing line byte-identical AND ``after``
    is strictly longer) is ADDITIVE_LEDGER. Any other mutation — a decision
    body OR id rewritten, removed, or reordered — is CONTEXT_REFRESH, because an
    edited decision can change operating context, not merely add a note. The
    content hash is what makes a rewrite-plus-append ("D001" body changed AND
    "D002" appended) fall through to CONTEXT_REFRESH instead of masquerading as
    a clean append.
    """
    if before == after:
        return None
    if len(after) > len(before) and tuple(after[: len(before)]) == before:
        added_ids = [_decision_id_of(t) for t in after[len(before):]]
        return ChangeNote(
            dimension="decisions",
            drift_class=DriftClass.ADDITIVE_LEDGER,
            summary=f"appended {len(added_ids)} decision(s): {', '.join(added_ids)}",
        )
    return ChangeNote(
        dimension="decisions",
        drift_class=DriftClass.CONTEXT_REFRESH,
        summary=(
            "decisions.jsonl was edited non-additively (a decision was "
            "removed, reordered, or rewritten) — context may have changed"
        ),
    )


# Plan-semantics fields that are scope/policy (blocking) vs refresh-required.
_SCOPE_FIELDS = ("allowed_paths", "forbidden_decisions", "protected_paths")
_REFRESH_PLAN_FIELDS = (
    "status",
    "agents_required",
    "human_gates",
    "loop_caps",
    "dependencies",
)


def classify_drift(
    before: PlanFingerprint, after: PlanFingerprint, *, stage: str = STAGE_DISPATCH
) -> DriftReport:
    """Compare two fingerprints and produce a classified :class:`DriftReport`.

    Precedence: BLOCKING_POLICY > CONTEXT_REFRESH > ADDITIVE_LEDGER > NONE.
    A single change in a higher band dominates lower-band changes.
    """
    changes: list[ChangeNote] = []
    changed_files: list[str] = []
    for rel in TRACKED_FILES:
        if before.file_hashes.get(rel) != after.file_hashes.get(rel):
            changed_files.append(rel)

    # ── plan.md frontmatter: scope/policy (blocking) ──
    for fld in _SCOPE_FIELDS:
        if before.plan_semantics.get(fld) != after.plan_semantics.get(fld):
            changes.append(
                ChangeNote(
                    dimension=fld,
                    drift_class=DriftClass.BLOCKING_POLICY,
                    summary=(
                        f"scope/policy field '{fld}' changed — a human must "
                        f"acknowledge the new boundary before work continues"
                    ),
                )
            )

    # ── plan.md frontmatter: refresh-required ──
    for fld in _REFRESH_PLAN_FIELDS:
        if before.plan_semantics.get(fld) != after.plan_semantics.get(fld):
            changes.append(
                ChangeNote(
                    dimension=fld,
                    drift_class=DriftClass.CONTEXT_REFRESH,
                    summary=f"plan field '{fld}' changed — refresh context before next call",
                )
            )

    # ── features.json: list / acceptance / deps / roles → refresh ──
    b_feats = before.features_semantics
    a_feats = after.features_semantics
    if b_feats.get("feature_ids") != a_feats.get("feature_ids"):
        changes.append(
            ChangeNote(
                dimension="features.list",
                drift_class=DriftClass.CONTEXT_REFRESH,
                summary="the feature list changed (features added/removed/renamed)",
            )
        )
    else:
        b_by = b_feats.get("by_id") or {}
        a_by = a_feats.get("by_id") or {}
        for fid in a_by:
            if fid in b_by and b_by[fid] != a_by[fid]:
                changes.append(
                    ChangeNote(
                        dimension=f"features.{fid}",
                        drift_class=DriftClass.CONTEXT_REFRESH,
                        summary=(
                            f"feature {fid} changed (acceptance / depends_on / "
                            f"roles) — refresh context before next call"
                        ),
                    )
                )

    # ── objective_contract.json → refresh ──
    if before.objective_hash != after.objective_hash:
        changes.append(
            ChangeNote(
                dimension="objective_contract",
                drift_class=DriftClass.CONTEXT_REFRESH,
                summary="objective_contract.json changed — acceptance signals may differ",
            )
        )

    # ── gate-state.json (cleared/completed projection) → refresh ──
    # A change to the cleared-gate or completed-stage set that the supervisor
    # did not itself author (see advance_gate_baseline) means a gate was
    # cleared/uncleared mid-run from outside — e.g. a human hand-edited
    # gate-state.json to bypass a pause. That changes which gates DontPanic
    # believes are satisfied, so the operator must refresh before the next call.
    if before.gate_semantics != after.gate_semantics:
        b_cleared = (before.gate_semantics or {}).get("cleared_gates") or []
        a_cleared = (after.gate_semantics or {}).get("cleared_gates") or []
        changes.append(
            ChangeNote(
                dimension="gate_state",
                drift_class=DriftClass.CONTEXT_REFRESH,
                summary=(
                    f"gate-state cleared/completed set changed mid-run "
                    f"(cleared_gates {b_cleared} → {a_cleared}) — a gate may have "
                    f"been cleared outside DontPanic; refresh before next call"
                ),
            )
        )

    # ── decisions.jsonl → additive or refresh ──
    dec = _decisions_change(before.decision_lines, after.decision_lines)
    if dec is not None:
        changes.append(dec)

    overall = DriftClass.NONE
    for c in changes:
        overall = _max_class(overall, c.drift_class)

    return DriftReport(
        drift_class=overall,
        changed_files=tuple(changed_files),
        changes=tuple(changes),
        stage=stage,
    )


# ───────────────────────────── baseline persistence ────────────────────────


def record_baseline(plan_dir: Path, fingerprint: PlanFingerprint | None = None) -> Path:
    """Persist the dispatch-start (or advanced) fingerprint under audit/.
    Returns the written path. AC(1): dispatch records a plan-run fingerprint
    before work starts."""
    fp = fingerprint or compute_fingerprint(plan_dir)
    path = baseline_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fp.to_dict(), indent=2, sort_keys=True) + "\n")
    return path


def advance_gate_baseline(plan_dir: Path) -> PlanFingerprint | None:
    """Fold the CURRENT gate-state projection into the persisted baseline,
    leaving every other tracked dimension untouched.

    The supervisor calls this immediately after IT performs a legitimate
    gate-state mutation (e.g. auto-clearing ``pre_impl`` for an active-plan
    direct dispatch). Without it, the supervisor's own gate clear would look
    like external drift at the next implementer/auditor check and falsely pause
    the volley. Only the gate-state hash/mtime and ``gate_semantics`` are
    advanced — a concurrent edit to features/decisions/plan/objective made in
    the same window is still caught. Returns the updated fingerprint, or None
    when no baseline exists yet (nothing to advance)."""
    from dataclasses import replace

    base = read_baseline(plan_dir)
    if base is None:
        return None
    cur = compute_fingerprint(plan_dir)
    merged = replace(
        base,
        gate_semantics=cur.gate_semantics,
        file_hashes={**base.file_hashes, GATE_STATE_JSON: cur.file_hashes.get(GATE_STATE_JSON)},
        file_mtimes={**base.file_mtimes, GATE_STATE_JSON: cur.file_mtimes.get(GATE_STATE_JSON)},
    )
    record_baseline(plan_dir, merged)
    return merged


def read_baseline(plan_dir: Path) -> PlanFingerprint | None:
    """Read the persisted baseline fingerprint, or None when absent/corrupt."""
    path = baseline_path(plan_dir)
    text = _read_text_or_none(path)
    if text is None:
        return None
    try:
        return PlanFingerprint.from_dict(json.loads(text))
    except (json.JSONDecodeError, TypeError):
        return None


# ─────────────────────────────── guidance build ────────────────────────────


def build_guidance(plan_id: str, feature_id: str | None, report: DriftReport) -> Any:
    """Build ONE concise :class:`operations_guidance.Guidance` for a
    refresh/blocking drift (AC6 — a single reconciliation action, not repeated
    warnings). Additive drift produces no guidance (it never pauses).

    Imported lazily so the pure engine stays cheap for callers that only
    fingerprint/classify.
    """
    from dontpanic_orchestrate import operations_guidance as og

    files = ", ".join(report.changed_files) or "plan artifacts"
    detail_changes = "; ".join(c.summary for c in report.changes)
    redispatch_cmd = f"dontpanic orchestrate {plan_id} --confirm"
    ack_cmd = f"dontpanic resume {plan_id} --all"

    if report.drift_class is DriftClass.CONTEXT_REFRESH:
        choice = og.ActionChoice(
            id="plan-drift-refresh",
            kind=og.KIND_RECONCILE,
            title="Plan changed mid-run — refresh context and redispatch",
            rationale=(
                f"Detected context-refresh drift in {files} ({detail_changes}). "
                f"DontPanic paused BEFORE the next paid agent call so the volley "
                f"does not continue on stale context. Re-read the changed plan "
                f"artifacts, then redispatch to pick up the refreshed context."
            ),
            risk=og.Risk.MEDIUM,
            recommended=True,
            exact_command=redispatch_cmd,
            requires_human=False,
            feature_scoped=bool(feature_id),
        )
    elif report.drift_class is DriftClass.BLOCKING_POLICY:
        choice = og.ActionChoice(
            id="plan-drift-policy-ack",
            kind=og.KIND_RECONCILE,
            title="Scope/policy changed mid-run — human acknowledgement required",
            rationale=(
                f"Detected scope/policy drift in {files} ({detail_changes}). "
                f"This changes what the agents are allowed to touch, so DontPanic "
                f"paused and will NOT continue until a human acknowledges the new "
                f"boundary. Review the change, then acknowledge to resume or "
                f"redispatch with the new scope."
            ),
            risk=og.Risk.HIGH,
            recommended=True,
            exact_command=ack_cmd,
            requires_human=True,
            feature_scoped=bool(feature_id),
        )
    else:
        # NONE / ADDITIVE — no operator action.
        return og.Guidance(
            plan_id=plan_id,
            feature_id=feature_id,
            headline=report.headline(plan_id),
            choices=(),
        )

    return og.Guidance(
        plan_id=plan_id,
        feature_id=feature_id,
        headline=report.headline(plan_id),
        choices=(choice,),
    )


# ───────────────────────── orchestrator-facing entry ───────────────────────


@dataclass(frozen=True)
class ReconcileDecision:
    """What the supervisor should do after a drift check.

    ``proceed`` True  → continue the volley (no drift, or additive reconciled).
    ``proceed`` False → pause; ``report`` + ``guidance`` describe the action.
    ``advanced_baseline`` carries the new fingerprint when the baseline was
    advanced (additive reconcile) so the caller can keep its in-memory copy in
    sync; None otherwise.
    """

    proceed: bool
    report: DriftReport
    guidance: Any | None = None
    advanced_baseline: PlanFingerprint | None = None
    pause_reason: str | None = None


def check_and_reconcile(
    plan_dir: Path,
    *,
    plan_id: str,
    feature_id: str | None,
    stage: str,
    baseline: PlanFingerprint | None = None,
    current: PlanFingerprint | None = None,
    emit: bool = True,
) -> ReconcileDecision:
    """Recompute the fingerprint, compare against the baseline, classify, and
    (optionally) emit the operator-facing INBOX event + dashboard sidecar.

    Behaviour by class:
      * NONE       → proceed, no event.
      * ADDITIVE   → record a ``plan_drift_reconciled`` INBOX event, advance the
                     baseline (so the same note never re-reports), proceed.
      * REFRESH    → record a ``plan_drift_detected`` INBOX event + one concise
                     dashboard ActionChoice, do NOT proceed.
      * BLOCKING   → record a ``plan_drift_blocked`` INBOX event + one concise
                     dashboard ActionChoice (human ack required), do NOT proceed.

    ``baseline``/``current`` may be supplied to keep the function pure for
    tests; otherwise they are read/computed from ``plan_dir``. ``emit=False``
    suppresses all IO (used by tests that assert classification only).

    Raises :class:`DriftBaselineMissingError` (FAIL CLOSED, codex #1) when no
    baseline is supplied AND none can be read from disk — a missing/corrupt
    active-run baseline must pause, never silently re-baseline and proceed.
    """
    plan_dir = Path(plan_dir)
    base = baseline if baseline is not None else read_baseline(plan_dir)
    cur = current if current is not None else compute_fingerprint(plan_dir)

    # FAIL CLOSED (codex #1): a missing/corrupt active-run baseline means the
    # true dispatch-start disk state is gone, so we can no longer detect drift
    # against it. Recording the CURRENT state as a fresh baseline and proceeding
    # would silently bless possibly-already-drifted context as the original —
    # the exact fail-open this safety mechanism must not do. Raise instead so
    # the caller pauses before the next paid call. The supervisor records the
    # baseline at dispatch start (before plan load), so a baseline absent HERE
    # is an anomaly (deleted/corrupted mid-run), not a normal bootstrap.
    if base is None:
        raise DriftBaselineMissingError(
            f"no readable plan-run drift baseline at {baseline_path(plan_dir)} "
            f"for stage {stage!r}; failing closed — verify the plan files on "
            "disk and redispatch so a clean dispatch-start baseline is recorded"
        )

    report = classify_drift(base, cur, stage=stage)

    if report.drift_class is DriftClass.NONE:
        return ReconcileDecision(proceed=True, report=report)

    if report.drift_class is DriftClass.ADDITIVE_LEDGER:
        if emit:
            _emit_inbox(
                plan_dir,
                plan_id=plan_id,
                feature_id=feature_id,
                event="plan_drift_reconciled",
                report=report,
                budget_protected=False,
            )
            record_baseline(plan_dir, cur)
        return ReconcileDecision(proceed=True, report=report, advanced_baseline=cur)

    # CONTEXT_REFRESH or BLOCKING_POLICY → pause.
    guidance = build_guidance(plan_id, feature_id, report)
    event = (
        "plan_drift_blocked"
        if report.drift_class is DriftClass.BLOCKING_POLICY
        else "plan_drift_detected"
    )
    if emit:
        _emit_inbox(
            plan_dir,
            plan_id=plan_id,
            feature_id=feature_id,
            event=event,
            report=report,
            budget_protected=report.budget_protected,
        )
        _emit_sidecar(plan_dir, guidance)
    reason = report.headline(plan_id)
    return ReconcileDecision(
        proceed=False, report=report, guidance=guidance, pause_reason=reason
    )


# ───────────────────────────── emit helpers (IO) ───────────────────────────


def _emit_inbox(
    plan_dir: Path,
    *,
    plan_id: str,
    feature_id: str | None,
    event: str,
    report: DriftReport,
    budget_protected: bool,
) -> None:
    """Append a single concise INBOX event describing the drift + action."""
    from dontpanic_orchestrate import inbox

    body_lines = [
        report.headline(plan_id),
        "",
        f"Stage: {report.stage}",
        f"Changed files: {', '.join(report.changed_files) or '(none)'}",
        f"Budget protected (paused before next paid call): {budget_protected}",
        "",
        "Changes:",
    ]
    for c in report.changes:
        body_lines.append(f"  - [{c.drift_class.value}] {c.dimension}: {c.summary}")
    inbox.append_event(
        plan_dir,
        event=event,
        plan_id=plan_id,
        body="\n".join(body_lines),
        feature_id=feature_id,
        drift_class=report.drift_class.value,
        changed_files=",".join(report.changed_files),
        budget_protected=str(budget_protected),
        stage=report.stage,
    )


def _emit_sidecar(plan_dir: Path, guidance: Any) -> None:
    """Best-effort: project the guidance into the dashboard event sidecar so
    the SAME concise ActionChoice the CLI prints also renders in the dashboard
    (AC6). The Guidance ActionItems already match the sidecar reader's dict
    shape (``operator_console._action_item_from_sidecar_dict``), so they are
    appended directly. Never raises — a notification failure must not orphan
    the pause."""
    if guidance is None or not getattr(guidance, "choices", None):
        return
    try:
        from dontpanic_orchestrate import operator_console

        target = operator_console.default_event_sidecar_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            for item in guidance.to_action_items():
                entry = item.to_dict()
                operator_console._assert_no_secret_shapes(entry)
                f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 — advisory render, never fatal
        return


__all__ = [
    "BASELINE_FILENAME",
    "ChangeNote",
    "DriftBaselineMissingError",
    "DriftClass",
    "DriftReport",
    "GATE_STATE_JSON",
    "PlanFingerprint",
    "ReconcileDecision",
    "STAGE_AUDITOR",
    "STAGE_DISPATCH",
    "STAGE_IMPLEMENTER",
    "STAGE_SIGNOFF",
    "TRACKED_FILES",
    "advance_gate_baseline",
    "baseline_path",
    "build_guidance",
    "check_and_reconcile",
    "classify_drift",
    "compute_fingerprint",
    "read_baseline",
    "record_baseline",
]
