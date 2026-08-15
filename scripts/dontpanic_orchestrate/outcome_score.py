"""Plan 2026-08-13-001 F002 — outcome / slices / proofs scorer.

Every locked plan is scored on three axes, printed as three lines at
``dontpanic plan lock``:

    outcome   present | inherited | missing
    slices    mece | overlap | single | n/a
    proofs    one-per-slice | inferred | accepted-gap | missing

**Only one thing refuses a lock** (D003, narrowed by D009): *no outcome is
reachable by any route* — no ``delivers[]``, no resolvable ``inherits``, and
no feature carrying its own proof. And then only for plans that opted into the
contract, i.e. ``schema_version >= 1.1`` on a substantive (``tier != trivial``)
plan. That is the same applicability predicate the plan validator uses for the
``delivers[]`` requirement (``validate.py._check_objective_contract``), so a
legacy plan can never hit a surprise refuse. Below the threshold the score
still prints; the refusal is downgraded to an advisory line.

Three routes to an outcome, checked in that order:

  1. ``delivers[]`` — an entry only counts when it actually states an outcome:
     ``audience``, ``kind``, a ``capability`` of at least ten characters, and
     one ``proof_refs`` id, mirroring ``objective_contract.schema.json`` (see
     :func:`slice_defects`). An entry that states none of that
     (``delivers: [{}]``) is reported as a note and does NOT clear the
     refusal, here or in an inherited parent.
  2. ``inherits`` — a sibling plan dir of that id that itself carries an
     outcome by any of these three routes.
  3. **A feature that carries its own proof** (D009). Slices are a sizing
     decision, not a ceremony: a feature in ``features.json`` carrying
     ``proof: {metric, method}`` — a ``metric`` of at least ten characters and
     a ``walk|request|named_test|probe`` method, both halves required, as
     ``features.schema.json`` declares them (see :func:`proof_defects`) — IS a
     slice, and one such feature is enough to state an outcome. A block that
     names a method and measures nothing is not a proof and does NOT clear the
     refusal; it is reported as a note.
     Its audience comes from the feature's ``user_impact.audience``; a
     feature-as-slice that declares none still locks and records an
     **accepted audience gap** naming what is absent (D009 — never a refusal).
     A feature already named by a scored ``delivers[]`` entry's ``proof_refs``
     is not counted twice.

Everything else — overlapping slices, a slice with no ``proof`` — is a
**gap**. Gaps are recorded at lock (``evidence/goal-governance/pre_impl/
outcome-score.json``) and paid at close:

    :func:`evaluate_close_proofs` returns one reason per obligation whose
    proof never ran. ``dontpanic plan close`` refuses on a non-empty list.
    The obligation set comes from the lock-time sidecar where there is one
    (:func:`close_obligations`), so editing or deleting a slice after the lock
    cannot retire its proof — the drift is named in the refusal instead.
    Lock-time and live slices are paired on the EXACT set of features they
    prove, never on position and never on a merely shared feature, so
    prepending or reordering ``delivers[]`` moves no obligation while
    replacing a slice — or re-pointing one at a different feature — keeps the
    old obligation and adds the new.
    Evidence is resolved by the ``(plan_id, feature_id)`` PAIR: a
    ``proof_refs`` entry carrying ``plan`` is answered from THAT plan's
    ``features.json``, never from a same-numbered local feature.

The sidecar is the lock's evidence, so its own loss is reportable (F005,
D013). Writing it appends a **receipt** to ``decisions.jsonl`` — an
append-only ledger the sidecar's deletion cannot reach — naming the artifact
and the sha256 of the bytes written. Together the two artifacts separate the
two cases the old code confused (:func:`read_lock_evidence`):

  * no sidecar and no receipt → ``legacy``: a plan locked before the artifact
    existed. Close reads the live contract, exactly as it did before, and
    never meets a surprise refusal.
  * sidecar present, readable, and shaped like THIS plan's score → ``intact``:
    the obligation set is the locked one.
  * receipt present, sidecar gone → ``missing``; sidecar present but
    unreadable, or readable and NOT shaped like this plan's score
    (:func:`score_payload_defect` — structure, per-slice records, and plan
    identity) → ``corrupt``; readable but not the bytes the receipt names →
    ``altered``. All three are destroyed lock evidence, NOT a legacy plan, and
    close refuses until the loss is acknowledged.

The structural check is drawn from what the close-time readers would otherwise
absorb in silence, since silence is the failure mode: a slice record with no
``index`` is dropped, a repeated ``index`` overwrites its twin, a ``proof_refs``
that is not a list of ids reads as "this slice promised nothing", and a
``plan_id`` naming another plan is never compared to anything. Each loses an
obligation while the record still reports as healthy (D015).

Two of those three need no receipt to be legible: a file that is present but
unreadable, or present and not a score, proves by its own existence that a
lock wrote something there. Only *deletion* needs the receipt, which is why
:func:`backfill_lock_receipt` exists (D014): the first write-capable command
to meet a sidecar with no receipt — ``dontpanic plan close`` — receipts it at
its current bytes, so a plan locked before receipts existed becomes
deletion-legible from that moment on. The one case that stays indistinguishable
from ``legacy`` is a pre-receipt sidecar deleted before any command ever saw
it: nothing on disk records that it existed, and inventing a refusal for it
would refuse every genuinely grandfathered plan (D014, AC1).

Four operator escapes, all in ``decisions.jsonl``:

  * ``{"kind": "proof_gap_accepted", "slice": ..., "reason": ...}`` — lock
    records the gap as *accepted* instead of inferring a method. Does NOT
    excuse close (D003: the gap is paid at close, not waived at lock).
  * ``{"kind": "proof_gap_deferred", "slice": ..., "reason": ...}`` — close
    accepts the slice without a run proof.
  * ``proof_gap_waived`` — synonym of ``proof_gap_deferred``.
  * ``{"kind": "lock_evidence_lost", "reason": ...}`` — close accepts that the
    lock record is gone and falls back to the live contract (D013). Deliberately
    an explicit, written act: it is the one way the proofs a lock recorded stop
    being owed, so the ``reason`` is REQUIRED and an entry without one waives
    nothing (:func:`loss_acknowledgement_defect`, D015).

``slice`` addresses a ``delivers[]`` item by 1-based index (``2``), by a
feature id it lists in ``proof_refs`` (``"F003"``), or by ``"*"`` / ``"all"``.

Proof inference (step 3): a user-facing slice with no declared proof infers
method ``walk`` (walk the path); everything else infers ``named_test``. The
inferred method is what close checks against.

Public surface::

    score_plan(plan_dir) -> OutcomeScore
    feature_proof_method(feature) -> str | None
    proof_defects(proof) -> tuple[str, ...]
    render_score_lines(score) -> list[str]
    write_score_sidecar(plan_dir, score) -> Path
    read_lock_evidence(plan_dir) -> LockEvidence
    score_payload_defect(data, *, plan_ids=()) -> str | None
    backfill_lock_receipt(plan_dir) -> dict | None
    lock_evidence_defect(plan_dir) -> str | None
    loss_acknowledgement_defect(entry) -> str | None
    evaluate_close_proofs(plan_dir) -> list[str]
    OUTCOME_SCORE_ARTIFACT
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dontpanic_orchestrate.nested_orchestration import goal_governance_evidence_path

# ──────────────────────────────  vocabulary  ──────────────────────────────

OUTCOME_PRESENT = "present"
OUTCOME_INHERITED = "inherited"
OUTCOME_MISSING = "missing"

SLICES_MECE = "mece"
SLICES_OVERLAP = "overlap"
SLICES_SINGLE = "single"
SLICES_NA = "n/a"

PROOFS_ONE_PER_SLICE = "one-per-slice"
PROOFS_INFERRED = "inferred"
PROOFS_ACCEPTED_GAP = "accepted-gap"
PROOFS_MISSING = "missing"

OUTCOME_SCORE_ARTIFACT = "outcome-score.json"
"""Filename under ``evidence/goal-governance/pre_impl/`` recording the score
and every gap the operator accepted (or that lock inferred) at lock time."""

_SCORE_SCHEMA_VERSION = 1

# The plan-authoring level at which delivers[] is REQUIRED, mirroring
# validate.py's _DELIVERS_REQUIRED_FROM. Below it the score is advisory.
_DELIVERS_REQUIRED_FROM = (1, 1)

_USER_FACING_AUDIENCES: frozenset[str] = frozenset({"end_user", "operator", "builder"})
"""Audiences whose slices are walked rather than unit-tested. Drives the
step-3 default: user-facing → ``walk``, everything else → ``named_test``."""

_INFERRED_METHOD_USER_FACING = "walk"
_INFERRED_METHOD_INTERNAL = "named_test"

_KNOWN_METHODS: frozenset[str] = frozenset({"walk", "request", "named_test", "probe"})

_METHOD_EVIDENCE_TYPES: dict[str, frozenset[str]] = {
    # A walk leaves a picture; a named test leaves test output. `request` and
    # `probe` have no unambiguous evidence *type*, so they can only be proven
    # by an explicit `proof:<method>` marker in the ref's note/uri. Deliberately
    # narrow: a rule that accepted any `file` ref would pass every close.
    "walk": frozenset({"screenshot"}),
    "named_test": frozenset({"test_output"}),
    "request": frozenset(),
    "probe": frozenset(),
}

_ACCEPT_KINDS: frozenset[str] = frozenset({"proof_gap_accepted"})
_DEFER_KINDS: frozenset[str] = frozenset({"proof_gap_deferred", "proof_gap_waived"})

LOCK_RECEIPT_KIND = "outcome_score_recorded"
"""``decisions.jsonl`` kind written when the lock-time sidecar lands. The
ledger is append-only and lives outside ``evidence/``, so it survives the
deletion of the artifact it describes — which is the whole point (D013)."""

_LOSS_KINDS: frozenset[str] = frozenset({"lock_evidence_lost"})
"""Operator acknowledgement that the lock record is gone for good. Close then
falls back to the live contract instead of refusing."""

LOCK_EVIDENCE_LEGACY = "legacy"
LOCK_EVIDENCE_INTACT = "intact"
LOCK_EVIDENCE_MISSING = "missing"
LOCK_EVIDENCE_CORRUPT = "corrupt"
LOCK_EVIDENCE_ALTERED = "altered"

_LOCK_EVIDENCE_DESTROYED: frozenset[str] = frozenset(
    {LOCK_EVIDENCE_MISSING, LOCK_EVIDENCE_CORRUPT, LOCK_EVIDENCE_ALTERED}
)
"""The three states that are NOT a legacy plan: this plan was locked with a
score, and the score is no longer the one it was locked with."""

_MIN_CAPABILITY_CHARS = 10
"""Mirrors ``objective_contract.schema.json``'s ``minLength`` on
``capability``: a statement shorter than this cannot say what an audience can
now do."""

_MIN_METRIC_CHARS = 10
"""Mirrors the ``minLength`` on ``proof.metric`` in BOTH proof schemas
(``features.schema.json`` and ``objective_contract.schema.json``, kept in
lockstep): a measurement shorter than this cannot tell a reader whether it was
met."""

_ALL_SLICES_TOKENS: frozenset[str] = frozenset({"*", "all"})

SLICE_FROM_DELIVERS = "delivers"
SLICE_FROM_FEATURE = "feature"
"""Where a slice came from — a ``delivers[]`` entry, or a feature that carries
its own proof (D009). Recorded per slice in the lock-time sidecar so the
operator can see which route stated the outcome."""

_UNKNOWN_AUDIENCE = "unknown"


def _slice_label(index: object, audience: str, kind: str, capability: str) -> str:
    """One human-readable slice line, shared by the live score and by the
    lock-time record close is held to."""
    cap = capability if len(capability) <= 60 else capability[:57] + "..."
    return f"slice {index} ({audience}/{kind}): {cap}"


class OutcomeScoreError(ValueError):
    """Raised when the scorer cannot read the plan at all (missing or
    malformed ``plan.md``). Malformed *contracts* are not fatal — they score
    as a missing outcome with a note, so lock refuses for the right reason."""


# ──────────────────────────────  data  ──────────────────────────────


@dataclass(frozen=True)
class SliceScore:
    """One slice, scored — a ``delivers[]`` item, or a feature that carries its
    own proof (``origin``)."""

    index: int  # 1-based, as the operator addresses it in decisions.jsonl
    audience: str
    kind: str
    capability: str
    feature_ids: tuple[str, ...]
    declared_method: str | None
    metric: str | None
    inferred_method: str
    accepted: bool = False
    accept_reason: str | None = None
    origin: str = SLICE_FROM_DELIVERS
    audience_gap: str | None = None
    """Set on a feature-as-slice that declares no ``user_impact`` audience.
    Recorded and accepted at lock, never a refusal (D009). Distinct from
    ``accepted``, which is about a missing *proof*."""

    @property
    def method(self) -> str:
        """The method close checks against: declared if any, else inferred."""
        return self.declared_method or self.inferred_method

    @property
    def has_proof(self) -> bool:
        return self.declared_method is not None

    def label(self) -> str:
        return _slice_label(self.index, self.audience, self.kind, self.capability)


@dataclass(frozen=True)
class OutcomeScore:
    """The three-axis score for one plan."""

    plan_id: str
    plan_dir: Path
    outcome: str
    slices: str
    proofs: str
    refuse: bool = False
    refusal: str | None = None
    slice_scores: tuple[SliceScore, ...] = ()
    overlaps: tuple[str, ...] = ()
    inherits: str | None = None
    inherits_resolved: bool = False
    delivers_required: bool = False
    contract_path: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def accepted_gaps(self) -> tuple[SliceScore, ...]:
        return tuple(s for s in self.slice_scores if s.accepted and not s.has_proof)

    @property
    def inferred_gaps(self) -> tuple[SliceScore, ...]:
        return tuple(s for s in self.slice_scores if not s.accepted and not s.has_proof)

    @property
    def explicit_proofs(self) -> tuple[SliceScore, ...]:
        return tuple(s for s in self.slice_scores if s.has_proof)

    @property
    def feature_slices(self) -> tuple[SliceScore, ...]:
        """Slices that came from a proof-carrying feature rather than
        ``delivers[]`` (D009)."""
        return tuple(s for s in self.slice_scores if s.origin == SLICE_FROM_FEATURE)

    @property
    def audience_gaps(self) -> tuple[SliceScore, ...]:
        """Slices locked with no declared audience. Accepted at lock and
        recorded in the sidecar; never a refusal."""
        return tuple(s for s in self.slice_scores if s.audience_gap)


# ──────────────────────────────  reading  ──────────────────────────────


def _read_frontmatter(plan_md: Path) -> dict[str, Any]:
    if not plan_md.is_file():
        raise OutcomeScoreError(f"plan.md not found at {plan_md}")
    text = plan_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise OutcomeScoreError(f"{plan_md}: missing frontmatter delimiter '---'")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise OutcomeScoreError(f"{plan_md}: malformed frontmatter")
    fm = yaml.safe_load(parts[1])
    if not isinstance(fm, dict):
        raise OutcomeScoreError(f"{plan_md}: frontmatter is not a mapping")
    return fm


def _parse_schema_version(raw: object) -> tuple[int, int]:
    """Mirror of ``validate.py._parse_schema_version``. Absent/malformed →
    (1, 0), i.e. legacy/grandfathered."""
    if not isinstance(raw, str):
        return (1, 0)
    parts = raw.split(".")
    try:
        return (int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return (1, 0)


def _contract_ref(plan_data: dict[str, Any]) -> str | None:
    links = plan_data.get("links")
    if not isinstance(links, dict):
        return None
    ref = links.get("objective_contract")
    return ref if isinstance(ref, str) and ref.strip() else None


def _load_contract(plan_dir: Path, plan_data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Return ``(contract, relative_ref, note)``.

    A declared-but-unreadable contract yields ``(None, ref, note)`` rather
    than raising: the score then reports a missing outcome, which is the
    honest reading and keeps the refusal message about the outcome.
    """
    ref = _contract_ref(plan_data)
    if ref is None:
        # Convention fallback: a sibling objective_contract.json with no link.
        default = plan_dir / "objective_contract.json"
        if not default.is_file():
            return None, None, None
        ref = "./objective_contract.json"
    path = (plan_dir / ref).resolve()
    if not path.is_file():
        return None, ref, f"objective contract not found at {ref}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, ref, f"objective contract at {ref} is unreadable: {exc}"
    if not isinstance(data, dict):
        return None, ref, f"objective contract at {ref} is not a JSON object"
    return data, ref, None


def read_decision_entries(plan_dir: Path) -> list[dict[str, Any]]:
    """Parse ``decisions.jsonl`` into a list of mappings. Unparseable or
    non-mapping lines are skipped — the ledger is operator-authored and a
    stray line must never crash a lock."""
    path = plan_dir / "decisions.jsonl"
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


def read_feature_records(plan_dir: Path) -> list[dict[str, Any]]:
    """The plan's ``features.json`` entries, in file order.

    Unreadable or malformed → empty list. Like the contract, a broken
    features.json must not crash a lock; it simply carries no slices, and the
    refusal (if any) stays about the missing outcome.
    """
    path = Path(plan_dir) / "features.json"
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    features = raw.get("features") if isinstance(raw, dict) else None
    if not isinstance(features, list):
        return []
    return [f for f in features if isinstance(f, dict) and isinstance(f.get("id"), str)]


# ──────────────────────────────  slice addressing  ──────────────────────────────


def _entry_targets(entry: dict[str, Any]) -> list[str]:
    """Normalize an entry's ``slice`` (or ``slices``) field to a token list."""
    raw = entry.get("slice", entry.get("slices"))
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    return [str(v).strip() for v in values if str(v).strip()]


def _entry_matches(entry: dict[str, Any], index: int, feature_ids: tuple[str, ...]) -> bool:
    """Does this decision entry address the slice at ``index`` (1-based)?"""
    targets = _entry_targets(entry)
    if not targets:
        # A gap entry with no slice field addresses the whole contract.
        return True
    # Both forms address a slice: the stored token ("<plan>:F001") and the bare
    # feature id ("F001"), so an operator need not qualify a cross-plan ref.
    upper_ids = {f.upper() for f in feature_ids}
    upper_ids |= {_split_feature_ref(f)[1].upper() for f in feature_ids}
    for token in targets:
        if token.lower() in _ALL_SLICES_TOKENS:
            return True
        if token.isdigit() and int(token) == index:
            return True
        if token.upper() in upper_ids:
            return True
    return False


def _gap_entry(
    entries: list[dict[str, Any]], kinds: frozenset[str], index: int, feature_ids: tuple[str, ...]
) -> dict[str, Any] | None:
    for entry in entries:
        kind = entry.get("kind")
        if not isinstance(kind, str) or kind not in kinds:
            continue
        if _entry_matches(entry, index, feature_ids):
            return entry
    return None


# ──────────────────────────────  scoring  ──────────────────────────────


def _feature_ids(item: dict[str, Any]) -> tuple[str, ...]:
    refs = item.get("proof_refs")
    if not isinstance(refs, list):
        return ()
    ids: list[str] = []
    for ref in refs:
        if isinstance(ref, dict) and isinstance(ref.get("id"), str):
            plan = ref.get("plan")
            ids.append(f"{plan}:{ref['id']}" if isinstance(plan, str) and plan else ref["id"])
    return tuple(ids)


def _infer_method(audience: str) -> str:
    return (
        _INFERRED_METHOD_USER_FACING
        if audience in _USER_FACING_AUDIENCES
        else _INFERRED_METHOD_INTERNAL
    )


def slice_defects(item: Any) -> tuple[str, ...]:
    """Why this ``delivers[]`` entry states no outcome. Empty tuple = it does.

    Mirrors the four ``required`` fields of ``objective_contract.schema.json``
    — ``audience``, ``kind``, ``capability``, ``proof_refs`` — and its
    10-character floor on ``capability``. An entry failing any of them is not
    an outcome, so it must not clear the missing-outcome refusal: ``delivers:
    [{}]`` names nobody and promises nothing, and a lock that accepted it
    would be exactly the surprise this score exists to prevent.

    Deliberately shape-checking, not enum-checking: an off-enum ``audience``
    is the plan validator's message to deliver with its own wording, not a
    second refusal from here.
    """
    if not isinstance(item, dict):
        return (f"not a JSON object (got {type(item).__name__})",)
    defects: list[str] = []
    audience = item.get("audience")
    if not isinstance(audience, str) or not audience.strip():
        defects.append("no 'audience' — name who can now do something they could not")
    kind = item.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        defects.append("no 'kind' — name the kind of capability delivered")
    capability = item.get("capability")
    if not isinstance(capability, str) or len(capability.strip()) < _MIN_CAPABILITY_CHARS:
        defects.append(
            f"'capability' is absent or shorter than {_MIN_CAPABILITY_CHARS} characters "
            "— say in plain language what this audience can now do"
        )
    refs = item.get("proof_refs")
    if not isinstance(refs, list) or not any(
        isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"].strip() for r in refs
    ):
        defects.append("no 'proof_refs' naming at least one feature that proves it")
    return tuple(defects)


def proof_defects(proof: Any) -> tuple[str, ...]:
    """Why this ``proof`` block states no measurement. Empty tuple = it does.

    Mirrors the two ``required`` fields both proof schemas declare —
    ``metric`` and ``method`` — and the 10-character floor on ``metric``.
    ``features.schema.json`` and ``objective_contract.schema.json`` carry the
    identical block and are kept in lockstep, so one reader serves both.

    A block that names a method and measures nothing is not a proof: the
    metric is what close would check, so without one there is nothing to hold
    the plan to. Counting it would clear the missing-outcome refusal with a
    promise nobody can be held to — exactly the surprise this score exists to
    prevent.

    Callers pass a proof that is *present*. An absent proof is not a defect:
    it is the gap the score infers a method for, or that the operator accepts.
    """
    if not isinstance(proof, dict):
        return (f"not a JSON object (got {type(proof).__name__})",)
    defects: list[str] = []
    metric = proof.get("metric")
    if not isinstance(metric, str) or len(metric.strip()) < _MIN_METRIC_CHARS:
        defects.append(
            f"'metric' is absent or shorter than {_MIN_METRIC_CHARS} characters — name "
            "the cheap measurement that would show this delivers"
        )
    method = proof.get("method")
    if not isinstance(method, str) or method not in _KNOWN_METHODS:
        defects.append(
            "'method' is absent or not one of "
            + "|".join(sorted(_KNOWN_METHODS))
            + " — name how the metric is taken"
        )
    return tuple(defects)


def _score_slices(
    delivers: list[Any], entries: list[dict[str, Any]]
) -> tuple[tuple[SliceScore, ...], tuple[str, ...], tuple[str, ...]]:
    """Return ``(scored slices, one note per entry that states no outcome, one
    note per entry whose ``proof`` block measures nothing)``.

    A malformed entry is dropped rather than scored, so an outcome is counted
    only where one was actually stated. A malformed *proof* on an otherwise
    good entry does not drop the slice — the entry still states an outcome —
    but it is not counted as a declared proof either, so the slice falls back
    to the accepted-gap / inferred path with the reason named.
    """
    scored: list[SliceScore] = []
    defect_notes: list[str] = []
    proof_notes: list[str] = []
    for offset, item in enumerate(delivers):
        index = offset + 1
        defects = slice_defects(item)
        if defects:
            defect_notes.append(
                f"delivers[{index}] states no outcome: " + "; ".join(defects)
            )
            continue
        audience = str(item.get("audience") or "unknown")
        kind = str(item.get("kind") or "unknown")
        capability = str(item.get("capability") or "")
        ids = _feature_ids(item)
        raw_proof = item.get("proof")
        declared_method = None
        metric = None
        if raw_proof is not None:
            proof_flaws = proof_defects(raw_proof)
            if proof_flaws:
                proof_notes.append(
                    f"delivers[{index}] declares a proof that measures nothing: "
                    + "; ".join(proof_flaws)
                    + " — not counted as a declared proof"
                )
            else:
                declared_method = str(raw_proof["method"])
                metric = str(raw_proof["metric"])
        accept = (
            None
            if declared_method is not None
            else _gap_entry(entries, _ACCEPT_KINDS, index, ids)
        )
        scored.append(
            SliceScore(
                index=index,
                audience=audience,
                kind=kind,
                capability=capability,
                feature_ids=ids,
                declared_method=declared_method,
                metric=metric,
                inferred_method=_infer_method(audience),
                accepted=accept is not None,
                accept_reason=(accept or {}).get("reason") if accept else None,
            )
        )
    return tuple(scored), tuple(defect_notes), tuple(proof_notes)


def feature_proof_method(feature: Any) -> str | None:
    """The proof method this feature carries on its own, or ``None``.

    A feature carries a proof when its ``proof`` block states BOTH halves the
    schema requires: a ``metric`` of at least ten characters and a ``method``
    naming one of the four cheap methods (see :func:`proof_defects`). That —
    and only that — makes it a slice in its own right (D009). Both halves are
    load-bearing: the method is how close checks, the metric is what close
    checks. A block naming a method and measuring nothing would otherwise
    clear the missing-outcome refusal while owing nothing at close.
    """
    if not isinstance(feature, dict):
        return None
    proof = feature.get("proof")
    if proof is None or proof_defects(proof):
        return None
    return str(proof["method"])


def _feature_audience(feature: dict[str, Any]) -> str | None:
    """The feature's declared ``user_impact.audience``, or ``None``.

    ``none`` is a complete declaration on its own (features.schema.json § the
    audience enum: "genuinely internal work with no external consequence"), so
    it is returned as declared rather than treated as a gap.
    """
    impact = feature.get("user_impact")
    if not isinstance(impact, dict):
        return None
    audience = impact.get("audience")
    return audience.strip() if isinstance(audience, str) and audience.strip() else None


def _feature_capability(feature: dict[str, Any]) -> str:
    """What this feature-as-slice claims, in the plainest language on hand:
    the declared impact summary if there is one, else the description."""
    impact = feature.get("user_impact")
    if isinstance(impact, dict):
        summary = impact.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
    description = feature.get("description")
    return description.strip() if isinstance(description, str) else ""


def _score_feature_slices(
    features: list[dict[str, Any]],
    *,
    claimed: set[str],
    start_index: int,
) -> tuple[tuple[SliceScore, ...], tuple[str, ...]]:
    """Score every proof-carrying feature not already claimed by a
    ``delivers[]`` entry as a slice of its own (D009).

    Returns ``(slices, notes)``. The notes name each accepted audience gap — a
    feature-as-slice with no ``user_impact`` locks and is recorded, never
    refused — and each feature that declared a ``proof`` block stating no
    measurement, so an author who wrote one and got no slice is told why
    rather than left to guess. No ``proof_gap_accepted`` lookup here: a feature
    is only a slice *because* it declares a proof, so it can never carry a
    proof gap.
    """
    scored: list[SliceScore] = []
    notes: list[str] = []
    index = start_index
    for feature in features:
        fid = feature["id"]
        method = feature_proof_method(feature)
        if method is None:
            raw_proof = feature.get("proof")
            if raw_proof is not None:
                notes.append(
                    f"{fid} declares a proof that measures nothing: "
                    + "; ".join(proof_defects(raw_proof))
                    + " — not counted as a slice"
                )
            continue
        if fid.upper() in claimed:
            # Already a slice by way of a delivers[] entry that names it.
            # Counting it twice would invent an overlap the plan doesn't have.
            continue
        proof = feature["proof"]
        metric = proof.get("metric") if isinstance(proof.get("metric"), str) else None
        declared_audience = _feature_audience(feature)
        audience = declared_audience or _UNKNOWN_AUDIENCE
        audience_gap = None
        if declared_audience is None:
            audience_gap = (
                f"{fid} is a slice by its own {method} proof but declares no "
                "user_impact — the audience is absent, so nobody is named as able "
                f"to do something new. Recorded as an accepted gap; the {method} "
                "proof is still owed at close. Name it with user_impact.audience "
                "in features.json when you know who this is for."
            )
            notes.append(f"slice {index} audience gap: {audience_gap}")
        scored.append(
            SliceScore(
                index=index,
                audience=audience,
                kind=str(feature.get("category") or "unknown"),
                capability=_feature_capability(feature),
                feature_ids=(fid,),
                declared_method=method,
                metric=metric,
                inferred_method=_infer_method(audience),
                accepted=False,
                accept_reason=None,
                origin=SLICE_FROM_FEATURE,
                audience_gap=audience_gap,
            )
        )
        index += 1
    return tuple(scored), tuple(notes)


def _claimed_feature_ids(slices: tuple[SliceScore, ...]) -> set[str]:
    """Feature ids already proven by a scored ``delivers[]`` entry, upper-cased
    and unqualified, so a cross-plan ref (``"<plan>:F001"``) still matches the
    local ``F001`` it names."""
    claimed: set[str] = set()
    for slc in slices:
        for fid in slc.feature_ids:
            claimed.add(fid.upper())
            claimed.add(_split_feature_ref(fid)[1].upper())
    return claimed


def _detect_overlaps(slices: tuple[SliceScore, ...]) -> tuple[str, ...]:
    """Cheap MECE proxy. Two slices overlap when they claim the same audience
    AND name a common proving feature, or when they restate the same
    capability. Neither refuses a lock — overlap is a recorded gap."""
    overlaps: list[str] = []
    for i, left in enumerate(slices):
        for right in slices[i + 1 :]:
            shared = set(left.feature_ids) & set(right.feature_ids)
            if left.audience == right.audience and shared:
                overlaps.append(
                    f"slices {left.index} and {right.index} both claim audience "
                    f"'{left.audience}' and share proof_refs {sorted(shared)}"
                )
            elif (
                left.capability
                and left.capability.strip().lower() == right.capability.strip().lower()
            ):
                overlaps.append(
                    f"slices {left.index} and {right.index} restate the same capability"
                )
    return tuple(overlaps)


def _resolve_inherits(plan_dir: Path, inherits: str, depth: int = 0) -> bool:
    """Is the inherited parent resolvable — does a sibling plan dir of that id
    exist and does it carry an outcome by ANY of the three routes (its own
    delivers[], a proof-carrying feature, or a resolvable inherits of its own)?

    The parent is held to exactly the bar the child is held to, so "inherit a
    parent that states an outcome" means the same thing at every depth.
    Depth-capped so an inheritance cycle terminates.
    """
    if depth > 4:
        return False
    parent_dir = plan_dir.parent / inherits
    if not (parent_dir / "plan.md").is_file():
        return False
    try:
        parent_data = _read_frontmatter(parent_dir / "plan.md")
    except OutcomeScoreError:
        return False
    contract, _ref, _note = _load_contract(parent_dir, parent_data)
    delivers = (contract or {}).get("delivers")
    # Same bar as the local plan's: a parent whose delivers[] holds only
    # malformed entries carries no outcome to inherit.
    if isinstance(delivers, list) and any(not slice_defects(item) for item in delivers):
        return True
    if any(feature_proof_method(f) for f in read_feature_records(parent_dir)):
        return True
    parent_inherits = (contract or {}).get("inherits")
    if isinstance(parent_inherits, str) and parent_inherits:
        return _resolve_inherits(parent_dir, parent_inherits, depth + 1)
    return False


def score_plan(plan_dir: Path) -> OutcomeScore:
    """Score one plan's outcome / slices / proofs. Read-only."""
    plan_dir = Path(plan_dir).resolve()
    plan_data = _read_frontmatter(plan_dir / "plan.md")
    plan_id = str(plan_data.get("id") or plan_dir.name)

    schema_version = _parse_schema_version(plan_data.get("schema_version"))
    tier = plan_data.get("tier")
    delivers_required = schema_version >= _DELIVERS_REQUIRED_FROM and tier != "trivial"

    contract, ref, note = _load_contract(plan_dir, plan_data)
    notes: list[str] = [note] if note else []

    raw_delivers = (contract or {}).get("delivers")
    delivers = raw_delivers if isinstance(raw_delivers, list) else []
    raw_inherits = (contract or {}).get("inherits")
    inherits = raw_inherits if isinstance(raw_inherits, str) and raw_inherits else None
    inherits_resolved = bool(inherits) and _resolve_inherits(plan_dir, inherits or "")
    if inherits and not inherits_resolved:
        notes.append(
            f"inherits '{inherits}' does not resolve — no sibling plan dir of that id "
            "carrying an outcome"
        )

    entries = read_decision_entries(plan_dir)
    delivers_slices, slice_defect_notes, slice_proof_notes = _score_slices(delivers, entries)
    notes.extend(slice_defect_notes)
    notes.extend(slice_proof_notes)

    # ── third route: a feature that carries its own proof IS a slice (D009) ──
    feature_slices, audience_gap_notes = _score_feature_slices(
        read_feature_records(plan_dir),
        claimed=_claimed_feature_ids(delivers_slices),
        start_index=len(delivers_slices) + 1,
    )
    notes.extend(audience_gap_notes)
    slice_scores = delivers_slices + feature_slices

    # ── outcome ──
    if inherits_resolved:
        outcome = OUTCOME_INHERITED
    elif slice_scores:
        outcome = OUTCOME_PRESENT
    else:
        outcome = OUTCOME_MISSING

    # ── slices ──
    overlaps = _detect_overlaps(slice_scores)
    if not slice_scores:
        slices = SLICES_NA
    elif len(slice_scores) == 1:
        slices = SLICES_SINGLE
    elif overlaps:
        slices = SLICES_OVERLAP
    else:
        slices = SLICES_MECE

    # ── proofs ──
    if not slice_scores:
        proofs = PROOFS_MISSING
    elif all(s.has_proof for s in slice_scores):
        proofs = PROOFS_ONE_PER_SLICE
    elif any(s.accepted for s in slice_scores):
        proofs = PROOFS_ACCEPTED_GAP
    else:
        proofs = PROOFS_INFERRED

    # ── the one refusal (D003) ──
    refuse = False
    refusal = None
    if outcome == OUTCOME_MISSING and delivers_required:
        refuse = True
        where = ref or "objective_contract.json"
        if slice_defect_notes:
            n = len(slice_defect_notes)
            declared = (
                f"declares {n} delivers[] entr{'y' if n == 1 else 'ies'} in {where} that "
                f"state no outcome ({slice_defect_notes[0]}"
                + (f"; and {n - 1} more" if n > 1 else "")
                + ")"
            )
        else:
            declared = f"declares no delivers[] outcome in {where}"
        refusal = (
            f"plan lock refused — outcome is missing. {plan_id} {declared}, inherits "
            + (
                f"'{inherits}' does not resolve to a parent that carries one"
                if inherits
                else "is absent"
            )
            + ", and no feature in features.json carries its own proof — so no "
            "outcome is reachable by any route.\nAny ONE of these three clears it:\n"
            '  1. Name what becomes true, for whom — one delivers[] item is enough:\n'
            '     {"audience": "operator", "kind": "reliability", "capability": '
            '"<what this audience can now do>", "proof_refs": [{"type": "feature", '
            '"id": "F001"}]}\n'
            "  2. If this is a fix that deltas a parent plan's outcome, set the "
            'contract-level "inherits": "<parent-plan-id>".\n'
            "  3. Give one feature its own proof in features.json — a feature that "
            "stands on its own IS a slice:\n"
            '     "proof": {"metric": "<what you would measure>", "method": '
            '"walk|request|named_test|probe"}\n'
            "Nothing else about this plan blocks the lock: missing proofs, an "
            "undeclared audience, and overlapping slices are recorded as gaps and "
            "checked at close."
        )
    elif outcome == OUTCOME_MISSING:
        notes.append(
            "outcome missing but advisory only — this plan is below the "
            "schema_version 1.1 / substantive-tier threshold at which delivers[] "
            "is required, so the lock is not refused"
        )

    return OutcomeScore(
        plan_id=plan_id,
        plan_dir=plan_dir,
        outcome=outcome,
        slices=slices,
        proofs=proofs,
        refuse=refuse,
        refusal=refusal,
        slice_scores=slice_scores,
        overlaps=overlaps,
        inherits=inherits,
        inherits_resolved=inherits_resolved,
        delivers_required=delivers_required,
        contract_path=ref,
        notes=tuple(notes),
    )


# ──────────────────────────────  rendering  ──────────────────────────────


def _slice_sources(score: OutcomeScore) -> str:
    """Where the slices came from — named so the operator can see that a
    proof-carrying feature counted (D009), not just ``delivers[]``."""
    from_features = len(score.feature_slices)
    from_delivers = len(score.slice_scores) - from_features
    parts = []
    if from_delivers:
        parts.append(f"{from_delivers} in {score.contract_path or 'the contract'}")
    if from_features:
        parts.append(f"{from_features} from proof-carrying feature(s)")
    return ", ".join(parts)


def _outcome_detail(score: OutcomeScore) -> str:
    if score.outcome == OUTCOME_INHERITED:
        delta = len(score.slice_scores)
        return (
            f"from {score.inherits}"
            + (
                f"; {delta} delta slice(s) declared here ({_slice_sources(score)})"
                if delta
                else "; no delta declared"
            )
        )
    if score.outcome == OUTCOME_PRESENT:
        return f"{len(score.slice_scores)} slice(s): {_slice_sources(score)}"
    return "no delivers[], nothing inherited, no feature carrying its own proof"


def _slices_detail(score: OutcomeScore) -> str:
    n = len(score.slice_scores)
    if score.slices == SLICES_NA:
        return "no slices declared"
    if score.slices == SLICES_SINGLE:
        return "one slice — the size of a fix"
    if score.slices == SLICES_OVERLAP:
        return f"{n} slices; {score.overlaps[0]}"
    return f"{n} slices, no overlap detected"


def _proofs_detail(score: OutcomeScore) -> str:
    if not score.slice_scores:
        return "nothing to prove until a slice is named"
    explicit = len(score.explicit_proofs)
    accepted = len(score.accepted_gaps)
    inferred = len(score.inferred_gaps)
    bits = [f"{explicit} declared"]
    if accepted:
        bits.append(f"{accepted} accepted gap(s)")
    if inferred:
        methods = sorted({s.inferred_method for s in score.inferred_gaps})
        bits.append(f"{inferred} inferred ({'/'.join(methods)})")
    audience_gaps = len(score.audience_gaps)
    if audience_gaps:
        bits.append(f"{audience_gaps} accepted audience gap(s)")
    return ", ".join(bits) + " — unrun proofs are checked at close"


def render_score_lines(score: OutcomeScore, *, prefix: str = "[outcome-score]") -> list[str]:
    """The three-line score (step 1), plus one line per note."""
    # 13 = len("one-per-slice"), the widest value in any of the three axes.
    lines = [
        f"{prefix} outcome: {score.outcome:<13} — {_outcome_detail(score)}",
        f"{prefix} slices:  {score.slices:<13} — {_slices_detail(score)}",
        f"{prefix} proofs:  {score.proofs:<13} — {_proofs_detail(score)}",
    ]
    lines.extend(f"{prefix}   note: {n}" for n in score.notes)
    return lines


# ──────────────────────────────  sidecar  ──────────────────────────────


def score_payload(score: OutcomeScore) -> dict[str, Any]:
    return {
        "schema_version": _SCORE_SCHEMA_VERSION,
        "plan_id": score.plan_id,
        "outcome": score.outcome,
        "slices": score.slices,
        "proofs": score.proofs,
        "inherits": score.inherits,
        "inherits_resolved": score.inherits_resolved,
        "delivers_required": score.delivers_required,
        "objective_contract": score.contract_path,
        "overlaps": list(score.overlaps),
        "notes": list(score.notes),
        "slice_scores": [
            {
                "index": s.index,
                "audience": s.audience,
                "kind": s.kind,
                "capability": s.capability,
                "proof_refs": list(s.feature_ids),
                "declared_method": s.declared_method,
                "metric": s.metric,
                "method_checked_at_close": s.method,
                "origin": s.origin,
                "gap": not s.has_proof,
                "gap_accepted": s.accepted,
                "gap_accept_reason": s.accept_reason,
                # An absent audience on a feature-as-slice is a recorded,
                # accepted gap — never a refusal (D009).
                "audience_gap": s.audience_gap is not None,
                "audience_gap_reason": s.audience_gap,
            }
            for s in score.slice_scores
        ],
    }


_SIDECAR_REQUIRED_KEYS: tuple[str, ...] = ("schema_version", "plan_id", "slice_scores")
"""The keys :func:`score_payload` always writes and that every reader of a
lock record depends on. Their absence is what tells a score sidecar apart from
any other JSON object that happens to occupy the artifact's path."""

_SLICE_TEXT_FIELDS: tuple[str, ...] = (
    "audience",
    "kind",
    "capability",
    "declared_method",
    "method_checked_at_close",
)
"""Per-slice fields the close-time readers coerce with ``str()``. A non-string
there is not a typo the reader can absorb — ``str({})`` is a label and an
inferred method nobody wrote — so it is corruption, reported as such."""


def _slice_record_defect(record: Any, position: int) -> str | None:
    """Why this ``slice_scores[]`` entry is not a slice record; ``None`` = it is.

    The readers downstream (:func:`_locked_slice_records`, :func:`_record_refs`)
    are deliberately forgiving — they drop what they cannot use. That is right
    for a *reader* and wrong for a *validator*: dropping a record drops the
    obligation it carried, so ``slice_scores: [{}]`` read as "this plan was
    locked owing nothing" and close fell back to the live contract while
    reporting the lock record intact. Anything the reader would silently
    discard must therefore be a defect here.

    ``proof_refs`` is checked only when present: a sidecar written before slices
    recorded their proving features carries none, and that record legitimately
    holds the empty identity (see :func:`_pair_locked_with_live`). Present and
    malformed is a different thing from absent, and only the first is damage.
    """
    if not isinstance(record, dict):
        return f"slice_scores[{position}] is not a slice object (got {type(record).__name__})"
    index = record.get("index")
    if not isinstance(index, int) or isinstance(index, bool):
        return (
            f"slice_scores[{position}] carries no integer 'index' — that is the number "
            "close holds the obligation under, and a record without one is dropped"
        )
    refs = record.get("proof_refs")
    if refs is not None and (
        not isinstance(refs, list)
        or any(not isinstance(ref, str) or not ref.strip() for ref in refs)
    ):
        return (
            f"slice {index} has a 'proof_refs' that is not a list of feature ids — the "
            "features it promised to prove cannot be read, so the obligation cannot be "
            "paired with the live contract"
        )
    for name in _SLICE_TEXT_FIELDS:
        value = record.get(name)
        if value is not None and not isinstance(value, str):
            return f"slice {index} has a non-string '{name}' (got {type(value).__name__})"
    return None


def score_payload_defect(data: Any, *, plan_ids: Iterable[str] = ()) -> str | None:
    """Why this JSON is not THIS plan's outcome-score sidecar; ``None`` = it is.

    Structure and identity, never content: the point is to catch a file that
    parses as JSON but says nothing about the obligations lock recorded — an
    empty object, a hand-edited stub, half a file that happened to close its
    braces, an unrelated artifact copied over the path, another plan's sidecar.
    Without this check any receiptless ``{}`` read as ``intact`` and close held
    the plan to zero obligations while reporting the record healthy, which is
    exactly the "artifact confidently asserting something untrue about itself"
    failure this feature exists to remove (D014, D015).

    Every check is one the readers would otherwise absorb in silence, which is
    the rule for what belongs here: a malformed slice entry is DROPPED by
    :func:`_locked_slice_records`, a repeated ``index`` OVERWRITES its twin, and
    a ``plan_id`` naming another plan is never compared to anything. Each of
    those loses an obligation without saying so.

    ``plan_ids`` is the set of names this plan answers to — its ``plan.md`` id
    and its directory name. Empty (the default) skips the identity check, which
    is what the caller wants when the bytes are already vouched for by a
    receipt: those ARE what lock wrote, so a renamed plan is a rename and not a
    corruption.

    It is NOT a schema validator: an unknown ``schema_version`` or an extra key
    is a newer writer, not a corruption, and refusing those would make every
    forward-compatible change a fleet-wide close outage.
    """
    if not isinstance(data, dict):
        return f"not a JSON object (got {type(data).__name__})"
    missing = [key for key in _SIDECAR_REQUIRED_KEYS if key not in data]
    if missing:
        return "missing required key(s) " + ", ".join(missing)
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        return "'schema_version' is not an integer"
    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id.strip():
        return "'plan_id' is absent or empty"
    scores = data.get("slice_scores")
    if not isinstance(scores, list):
        return "'slice_scores' is not a list of slice objects"
    seen: dict[int, int] = {}
    for position, record in enumerate(scores):
        defect = _slice_record_defect(record, position)
        if defect is not None:
            return defect
        index = record["index"]
        if index in seen:
            return (
                f"slice_scores names index {index} twice (entries {seen[index]} and "
                f"{position}) — one of the two obligations would be silently dropped"
            )
        seen[index] = position
    wanted = {name.strip() for name in plan_ids if isinstance(name, str) and name.strip()}
    if wanted and plan_id.strip() not in wanted:
        return (
            f"'plan_id' is {plan_id.strip()!r}, which is not this plan "
            f"({' or '.join(sorted(wanted))}) — these are another plan's obligations"
        )
    return None


def _plan_identity_tokens(plan_dir: Path) -> frozenset[str]:
    """Every name this plan answers to: its ``plan.md`` id and its directory
    name, exactly the pair :func:`score_plan` chooses between.

    An unreadable ``plan.md`` falls back to the directory name alone rather
    than raising: the caller is classifying a lock record, and a plan whose
    ``plan.md`` is broken has a louder problem to report than its sidecar's
    identity.
    """
    plan_dir = Path(plan_dir)
    tokens = {plan_dir.name}
    try:
        data = _read_frontmatter(plan_dir / "plan.md")
    except (OutcomeScoreError, OSError, yaml.YAMLError):
        return frozenset(tokens)
    declared = data.get("id")
    if isinstance(declared, str) and declared.strip():
        tokens.add(declared.strip())
    return frozenset(tokens)


def write_score_sidecar(plan_dir: Path, score: OutcomeScore) -> Path:
    """Record the score — and every gap — under the pre_impl evidence dir, and
    receipt it in ``decisions.jsonl``.

    Written atomically (temp file + ``os.replace``): lock refuses when this
    write fails, so a half-written sidecar must never be mistaken for a
    recorded gap set. Bytes, not text, so the sha256 in the receipt names
    exactly what landed on disk regardless of platform newline translation.

    The receipt is written second and is equally required (F005/D013): a lock
    that cannot leave a trace of what it recorded is a lock whose record can
    later be deleted with nothing to show it existed, which is the failure
    this feature removes. Either write raising ``OSError`` refuses the lock,
    so the plan stays draft.
    """
    path = goal_governance_evidence_path(Path(plan_dir), "pre_impl", OUTCOME_SCORE_ARTIFACT)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(score_payload(score), indent=2, ensure_ascii=False) + "\n"
    raw = payload.encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(raw)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    append_lock_receipt(
        Path(plan_dir),
        plan_id=score.plan_id,
        digest=_digest(raw),
        slice_count=len(score.slice_scores),
    )
    return path


# ─────────────────────────────  lock evidence (F005)  ─────────────────────────────


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def append_lock_receipt(
    plan_dir: Path,
    *,
    plan_id: str,
    digest: str,
    slice_count: int,
    backfilled: bool = False,
) -> None:
    """Append the ``outcome_score_recorded`` receipt to ``decisions.jsonl``.

    Idempotent on content: re-locking a plan whose score has not changed adds
    no second line, so the ledger records lock *events*, not lock *attempts*.

    ``backfilled`` marks a receipt written by :func:`backfill_lock_receipt`
    rather than by the lock itself. It is recorded because the two say
    different things: a lock-time receipt names the bytes lock wrote, a
    backfilled one names the bytes that were on disk when the plan was first
    read by a command that could write. The second still catches a later
    deletion or edit — which is its whole job — but cannot vouch for anything
    that happened before it.
    """
    artifact = f"evidence/goal-governance/pre_impl/{OUTCOME_SCORE_ARTIFACT}"
    if backfilled:
        decision = (
            f"Receipted an existing outcome score ({slice_count} slice "
            "obligation(s)) that carried no lock-time receipt — the plan was "
            "locked before receipts existed. The sha256 is of the bytes found on "
            "disk at this reading, NOT of what lock wrote: any edit before this "
            "point is invisible. From here on a deletion or alteration of the "
            "artifact reads as destroyed lock evidence rather than as a plan "
            "locked before the artifact existed (D014)."
        )
    else:
        decision = (
            f"Lock recorded the outcome score and its {slice_count} slice "
            "obligation(s). This receipt outlives the artifact: if the score is "
            "later deleted or altered, close reports destroyed lock evidence "
            "rather than treating the plan as one locked before the artifact "
            "existed (D013)."
        )
    receipt = {
        "id": f"OSC-{'BF-' if backfilled else ''}{digest[:12]}",
        "kind": LOCK_RECEIPT_KIND,
        "plan_id": plan_id,
        "artifact": artifact,
        "sha256": digest,
        "slice_count": slice_count,
        "backfilled": backfilled,
        "decision": decision,
    }
    existing = read_lock_receipt(plan_dir)
    if existing is not None and existing.get("sha256") == digest:
        return
    with (Path(plan_dir) / "decisions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False) + "\n")


def backfill_lock_receipt(plan_dir: Path) -> dict[str, Any] | None:
    """Receipt a sidecar that has none, and return the receipt (else ``None``).

    The migration for plans locked between the sidecar landing (F002) and the
    receipt landing (F005). Their record is real but unreceipted, so deleting
    it would read as ``legacy`` — a plan locked before the artifact existed —
    and every proof it recorded would quietly stop being owed. Receipting it at
    first sight bounds that hole: from the first write-capable command that
    meets the plan, the deletion is legible.

    Deliberately narrow, because a receipt is an assertion and a wrong one is
    worse than none:

      * a plan with a receipt already is left alone (``None``);
      * an ABSENT sidecar is left alone. There is nothing on disk to say
        whether one ever existed, and writing a receipt for a file we cannot
        see would manufacture the very loss report AC1 forbids;
      * an unreadable, non-score, or wrong-plan sidecar is left alone. Those
        already read as ``corrupt`` on their own evidence, and receipting the
        corrupt bytes would freeze the damage in as if it were what lock wrote.

    Idempotent, and safe to call on every plan: the common case is a no-op.
    ``OSError`` propagates — a caller that cannot write the ledger should hear
    about it rather than silently skip the migration.
    """
    plan_dir = Path(plan_dir)
    if read_lock_receipt(plan_dir) is not None:
        return None
    path = goal_governance_evidence_path(plan_dir, "pre_impl", OUTCOME_SCORE_ARTIFACT)
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if score_payload_defect(data, plan_ids=_plan_identity_tokens(plan_dir)) is not None:
        return None
    append_lock_receipt(
        plan_dir,
        plan_id=str(data.get("plan_id") or plan_dir.name),
        digest=_digest(raw),
        slice_count=len(data.get("slice_scores") or []),
        backfilled=True,
    )
    return read_lock_receipt(plan_dir)


def read_lock_receipt(plan_dir: Path) -> dict[str, Any] | None:
    """The LATEST lock receipt in ``decisions.jsonl``, or ``None``.

    Latest, because a re-lock supersedes: the plan is held to the score it was
    most recently locked with.
    """
    receipts = [
        entry
        for entry in read_decision_entries(Path(plan_dir))
        if entry.get("kind") == LOCK_RECEIPT_KIND
    ]
    return receipts[-1] if receipts else None


@dataclass(frozen=True)
class LockEvidence:
    """What the plan can still show of what it was locked with.

    ``payload`` is the lock-time score, and is populated for exactly one
    state — ``intact``. Every other state either has no score to read or has
    one close must not trust, and close falls back to the live contract in
    both cases; the difference is that ``legacy`` is silent and the three
    destroyed states are reported.
    """

    state: str
    payload: dict[str, Any] | None
    receipt: dict[str, Any] | None
    detail: str | None  # operator-facing, set for the destroyed states only

    @property
    def is_destroyed(self) -> bool:
        return self.state in _LOCK_EVIDENCE_DESTROYED


def read_lock_evidence(plan_dir: Path) -> LockEvidence:
    """Classify the lock record: legacy absence, intact, or destroyed.

    The distinction this function exists to make (F005 AC2) is between a plan
    locked BEFORE the sidecar existed and a plan locked WITH one that has
    since been deleted or corrupted. Two independent artifacts answer it:

      * the sidecar itself — its mere presence proves a lock wrote one, so an
        unreadable file is destroyed evidence and needs no receipt to say so;
      * the ``decisions.jsonl`` receipt — append-only and outside
        ``evidence/``, so deleting the sidecar (or the whole pre_impl dir)
        cannot erase the fact that one was written.

    Neither present is the only honest reading of "grandfathered", and it is
    the one state that behaves exactly as it did before this function existed.
    """
    plan_dir = Path(plan_dir)
    path = goal_governance_evidence_path(plan_dir, "pre_impl", OUTCOME_SCORE_ARTIFACT)
    receipt = read_lock_receipt(plan_dir)
    relpath = f"evidence/goal-governance/pre_impl/{OUTCOME_SCORE_ARTIFACT}"

    if not path.is_file():
        if receipt is None:
            return LockEvidence(LOCK_EVIDENCE_LEGACY, None, None, None)
        return LockEvidence(
            LOCK_EVIDENCE_MISSING,
            None,
            receipt,
            f"the lock record {relpath} is gone. {plan_dir.name} WAS locked with "
            f"one — decisions.jsonl entry {receipt.get('id')} receipts "
            f"{receipt.get('slice_count')} slice obligation(s) at sha256 "
            f"{str(receipt.get('sha256'))[:12]} — so this is a deleted record, not "
            "a plan locked before the artifact existed. Restore the file from "
            "version control, re-lock the plan, or record "
            '{"kind": "lock_evidence_lost", "reason": ...} in decisions.jsonl to '
            "close against the live contract instead",
        )

    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return LockEvidence(
            LOCK_EVIDENCE_CORRUPT,
            None,
            receipt,
            f"the lock record {relpath} is unreadable ({exc}). The file exists, so "
            "the plan was locked with a score; a corrupt one is not the same as "
            "never having had one, and its obligations cannot be read. Restore it, "
            're-lock, or record {"kind": "lock_evidence_lost", "reason": ...} in '
            "decisions.jsonl to close against the live contract instead",
        )
    if not isinstance(data, dict):
        return LockEvidence(
            LOCK_EVIDENCE_CORRUPT,
            None,
            receipt,
            f"the lock record {relpath} is not a JSON object, so it carries no "
            "slice obligations to hold close to. Restore it, re-lock, or record "
            '{"kind": "lock_evidence_lost", "reason": ...} in decisions.jsonl',
        )

    expected = receipt.get("sha256") if receipt else None
    actual = _digest(raw)
    vouched = isinstance(expected, str) and bool(expected) and expected == actual
    if isinstance(expected, str) and expected and expected != actual:
        return LockEvidence(
            LOCK_EVIDENCE_ALTERED,
            None,
            receipt,
            f"the lock record {relpath} is not the one this plan was locked with: "
            f"decisions.jsonl entry {receipt.get('id') if receipt else '?'} receipts "
            f"sha256 {expected[:12]} and the file on disk is {actual[:12]}. The "
            "obligations it now states are not the ones the operator was shown at "
            "lock. Restore it, re-lock, or record "
            '{"kind": "lock_evidence_lost", "reason": ...} in decisions.jsonl',
        )
    # Identity is checked only where the bytes are NOT vouched for by a receipt.
    # A file whose sha256 the receipt names IS what lock wrote, so a plan_id
    # that no longer matches the directory is a renamed plan, not a corrupted
    # record — and refusing it would be the manufactured refusal AC1 forbids.
    defect = score_payload_defect(data, plan_ids=() if vouched else _plan_identity_tokens(plan_dir))
    if defect is not None:
        return LockEvidence(
            LOCK_EVIDENCE_CORRUPT,
            None,
            receipt,
            f"the lock record {relpath} parses as JSON but is not an outcome "
            f"score for this plan: {defect}. The file exists, so a lock wrote one there; what "
            "is there now states no obligations, and reading it as an empty set "
            "would retire every proof the lock recorded. Restore it, re-lock, or "
            'record {"kind": "lock_evidence_lost", "reason": ...} in '
            "decisions.jsonl to close against the live contract instead",
        )

    # No receipt and a readable, well-shaped file: a plan locked between the
    # sidecar landing and the receipt landing. The sidecar IS the record, so it
    # is intact — and backfill_lock_receipt() is what makes its LATER deletion
    # legible, since nothing else would.
    return LockEvidence(LOCK_EVIDENCE_INTACT, data, receipt, None)


def loss_acknowledgement_defect(entry: Any) -> str | None:
    """Why this ``lock_evidence_lost`` entry does not acknowledge anything;
    ``None`` = it does.

    The one required field is ``reason``, and requiring it is the whole point of
    the escape hatch. ``lock_evidence_lost`` is the single way the proofs a lock
    recorded stop being owed, so an entry that names no reason is a kind string
    that waives them and says nothing — the operator who reads the ledger a
    month later learns only that somebody wanted the refusal gone (D013, D015).

    Deliberately its own validator rather than the generic gap matcher, which
    checks ``kind`` and target only: a deferral says which proof is being put
    off and can be reconstructed from the contract, while a loss is unrecoverable
    and the reason is the only trace of why.
    """
    if not isinstance(entry, dict):
        return f"not a JSON object (got {type(entry).__name__})"
    reason = entry.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return (
            "states no 'reason' — this is the one entry that retires proofs a lock "
            "recorded, so it must say why the record is gone for good"
        )
    return None


def _loss_acknowledgements(plan_dir: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """``(the entry that waives the loss, the entries that tried and failed)``.

    One valid acknowledgement is enough; the rejects are carried back so the
    refusal can name them rather than reading as though nobody wrote anything.
    """
    rejected: list[dict[str, Any]] = []
    for entry in read_decision_entries(Path(plan_dir)):
        kind = entry.get("kind")
        if not isinstance(kind, str) or kind not in _LOSS_KINDS:
            continue
        if not _entry_matches(entry, 0, ()):
            continue
        if loss_acknowledgement_defect(entry) is None:
            return entry, rejected
        rejected.append(entry)
    return None, rejected


def lock_evidence_defect(plan_dir: Path) -> str | None:
    """One close-refusal reason when the lock record was destroyed after the
    lock and the loss is not acknowledged; ``None`` otherwise.

    ``{"kind": "lock_evidence_lost", "reason": ...}`` in ``decisions.jsonl`` is
    the escape, and it is deliberately a written act rather than a flag: it is
    the only way the proofs a lock recorded stop being owed, so it should read
    back later as a decision somebody made, with the reason they made it (D013,
    D015). An entry missing the reason does not waive the loss — it is named in
    the refusal instead, so the operator fixes the entry rather than wondering
    why theirs had no effect.
    """
    evidence = read_lock_evidence(plan_dir)
    if not evidence.is_destroyed:
        return None
    accepted, rejected = _loss_acknowledgements(plan_dir)
    if accepted is not None:
        return None
    reason = f"plan lock evidence ({evidence.state}): {evidence.detail}"
    if rejected:
        ids = ", ".join(str(entry.get("id") or "?") for entry in rejected)
        reason += (
            f". decisions.jsonl entry {ids} records kind 'lock_evidence_lost' but "
            f"{loss_acknowledgement_defect(rejected[0])}, so it does not waive the loss"
        )
    return reason


# ──────────────────────────────  close-time proof check  ──────────────────────────────


def _split_feature_ref(fid: str) -> tuple[str | None, str]:
    """Split a stored proof ref into ``(plan_id, feature_id)``.

    ``_feature_ids`` renders a cross-plan ref as ``"<plan-id>:F001"`` and a
    same-plan ref as ``"F001"``. Plan ids carry no colon, so the last colon is
    the separator.
    """
    plan, sep, feature = fid.rpartition(":")
    if not sep:
        return None, fid
    return (plan.strip() or None), feature.strip()


def _evidence_refs_by_feature(plan_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Map feature id → its ``evidence_refs``. Unreadable features.json →
    empty map (close then fails loudly on the proof, which is correct: no
    evidence file means no evidence)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for feature in read_feature_records(plan_dir):
        refs = feature.get("evidence_refs")
        out[feature["id"]] = (
            [r for r in refs if isinstance(r, dict)] if isinstance(refs, list) else []
        )
    return out


def evidence_ref_runs_method(ref: dict[str, Any], method: str) -> bool:
    """Does this evidence_ref show the declared method was actually taken?

    Two ways: an explicit ``proof:<method>`` marker in the note or uri (works
    for every method), or an evidence ``type`` that can only come from that
    method (``screenshot`` for a walk, ``test_output`` for a named test).
    """
    text = f"{ref.get('note', '')} {ref.get('uri', '')}".lower()
    if f"proof:{method}" in text:
        return True
    return ref.get("type") in _METHOD_EVIDENCE_TYPES.get(method, frozenset())


def _feature_evidence_resolver(plan_dir: Path, plan_id: str):
    """Return ``lookup(fid) -> list[ref] | None`` resolving a proof ref by the
    ``(plan_id, feature_id)`` PAIR, not by feature id alone.

    A cross-plan ref (``"<other-plan>:F001"``) is answered from that plan's
    own ``features.json`` under the shared plans dir — never from the local
    one, where an unrelated local ``F001`` would otherwise satisfy it. ``None``
    means the referenced plan dir does not resolve, which close reports as an
    unresolved ref rather than silently treating it as proven.
    """
    cache: dict[Path, dict[str, list[dict[str, Any]]]] = {}

    def lookup(fid: str) -> list[dict[str, Any]] | None:
        plan_token, feature_id = _split_feature_ref(fid)
        if plan_token is None or plan_token in {plan_id, plan_dir.name}:
            target = plan_dir
        else:
            target = plan_dir.parent / plan_token
            if not (target / "features.json").is_file():
                return None
        if target not in cache:
            cache[target] = _evidence_refs_by_feature(target)
        return cache[target].get(feature_id, [])

    return lookup


@dataclass(frozen=True)
class ProofObligation:
    """One proof close is held to.

    Sourced from the lock-time sidecar wherever there is one, so the set of
    obligations is what the operator was told at lock — not whatever the
    contract happens to say now.
    """

    index: int
    label: str
    method: str
    feature_ids: tuple[str, ...]
    origin: str  # "declared" | "inferred"
    locked: bool  # recorded at lock, hence survives a later contract edit
    drift: str | None  # how the live contract has moved since the lock


def read_score_sidecar(plan_dir: Path) -> dict[str, Any] | None:
    """The lock-time score when it is the one the plan was locked with, else
    ``None``.

    ``None`` no longer means one thing. It means "there are no locked
    obligations to read", which covers both a plan locked before the artifact
    existed and one whose record was destroyed — two cases that close must
    tell apart. :func:`read_lock_evidence` is the function that does; this one
    stays narrow because every caller of it wants the payload or nothing.
    """
    return read_lock_evidence(plan_dir).payload


def _locked_slice_records(plan_dir: Path) -> dict[int, dict[str, Any]] | None:
    """Lock-time slice records by index, or ``None`` when no trustworthy
    sidecar exists.

    ``None`` sends close to the live contract. That is right for a legacy plan
    and it is right for an acknowledged loss; for an unacknowledged one it is
    :func:`lock_evidence_defect` that refuses the close, so the fallback is
    never reached silently.
    """
    payload = read_score_sidecar(plan_dir)
    if payload is None:
        return None
    raw = payload.get("slice_scores")
    if not isinstance(raw, list):
        return None
    records: dict[int, dict[str, Any]] = {}
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("index"), int):
            records[item["index"]] = item
    return records


def _record_method(record: dict[str, Any]) -> str:
    method = record.get("method_checked_at_close") or record.get("declared_method")
    if isinstance(method, str) and method in _KNOWN_METHODS:
        return method
    return _infer_method(str(record.get("audience") or "unknown"))


def _record_refs(record: dict[str, Any]) -> tuple[str, ...]:
    raw = record.get("proof_refs")
    if not isinstance(raw, list):
        return ()
    return tuple(r.strip() for r in raw if isinstance(r, str) and r.strip())


def _slice_identity(refs: Iterable[str], plan_id: str, plan_name: str) -> frozenset[str]:
    """What a slice IS at close: the features it promises to prove, as
    canonical ``"<plan-id>:<FEATURE>"`` tokens.

    Identity, not position. Prepend a slice, reorder the list, renumber the
    whole contract — the same features are still owed the same proofs, so this
    is what pairs a lock-time record to its live slice. Same-plan refs are
    qualified with ``plan_id`` so a bare ``"F001"`` and an explicitly
    self-qualified ``"<this-plan>:F001"`` are one identity, and a cross-plan
    ``"<parent>:F001"`` is never confused with the local F001.
    """
    ids: set[str] = set()
    for ref in refs:
        plan_token, feature_id = _split_feature_ref(ref)
        if not feature_id.strip():
            continue
        if plan_token is None or plan_token in {plan_id, plan_name}:
            plan_token = plan_id
        ids.add(f"{plan_token}:{feature_id.strip().upper()}")
    return frozenset(ids)


def _pair_locked_with_live(
    records: dict[int, dict[str, Any]],
    slices: tuple[SliceScore, ...],
    plan_id: str,
    plan_name: str,
) -> tuple[dict[int, SliceScore | None], tuple[SliceScore, ...]]:
    """Pair each lock-time record with the live slice proving the same
    features, and return ``(pairing, live slices no record claimed)``.

    ``None`` in the pairing means no live slice proves the same features —
    still an obligation, now a drifted one. The unclaimed live slices are
    obligations in their own right: replacing a slice does not let the
    replacement inherit the proof of what it displaced.

    Identity is matched EXACTLY, never on a shared feature. A locked
    ``{F001, F002}`` and a live ``{F001, F003}`` are two different promises:
    pairing them on the shared F001 would consume the live slice, so F003's
    proof would be owed by nobody while the locked pair silently reported as a
    ref edit. The honest reading is a delete plus an add — the locked pair is
    owed in full, and ``{F001, F003}`` is owed on its own. The same rule keeps
    a contract that splits ``{F001, F002}`` into two slices from having the
    locked record claim whichever happened to be scored first.

    The numeric index is never consulted, not even as a fallback. A record that
    names no feature at all — a pre-``proof_refs`` sidecar — carries the EMPTY
    identity, and so pairs only with a live slice that likewise names none. A
    live slice that does name features is a different promise: the legacy
    record is owed as a drifted obligation and the live slice is owed on its
    own. Falling back to position for those records would reintroduce exactly
    the defect this function exists to remove — the obligation set would change
    when nothing but a slice's number did.

    Several slices may legitimately name the SAME proving features — two
    sittings against one feature, for two audiences, or one feature proved
    twice by different capabilities. Identity alone cannot tell those apart, so
    within an identity group **capability text is the tiebreak**, and only
    where it too is equal does live order decide. The passes run in that
    order: capability (and, among equal capabilities, method as well), then
    capability alone, then whatever is left in lock-index × live order.

    Capability comes strictly before method, and that ordering is
    load-bearing. Two records reading (alpha/walk, beta/named_test) against
    live slices reading (beta/walk, alpha/named_test) have each swapped
    position AND changed method; pairing on "nothing drifted at all" finds no
    exact twin for either and falls to live order, pairing alpha with beta and
    reporting a capability edit nobody made. Capability-first pairs alpha with
    alpha and names the method change, which is what actually happened.
    Matching greedily in live order has the same failure for a plain swap.

    The method pass is a refinement WITHIN a capability group, never a way
    around it: it only chooses between live slices already agreed to carry the
    same capability, so it can invent no drift — it can only avoid inventing
    some. Two slices identical in identity AND capability therefore reorder to
    nothing whether or not their methods differ.

    Where identity AND capability match, the slices are interchangeable in the
    sense that matters: the contract carries no further way to tell them apart,
    so *which* record pairs with *which* live slice of that group is not a
    question the data answers, and every pairing the passes above can produce
    yields the same obligations and the same drift. This function invents no
    further tiebreak — audience and index are both to hand, and both would
    manufacture a distinction the contract never made.
    """
    identities = [_slice_identity(s.feature_ids, plan_id, plan_name) for s in slices]
    claimed: set[int] = set()
    paired: dict[int, SliceScore | None] = {index: None for index in records}

    def _same_capability(record: dict[str, Any], live: SliceScore) -> bool:
        return str(record.get("capability") or "").strip().lower() == (
            live.capability.strip().lower()
        )

    def _same_capability_and_method(record: dict[str, Any], live: SliceScore) -> bool:
        return _same_capability(record, live) and _record_method(record) == live.method

    def _any_of_this_identity(record: dict[str, Any], live: SliceScore) -> bool:
        return True

    def _claim(index: int, accepts) -> None:
        record = records[index]
        wanted = _slice_identity(_record_refs(record), plan_id, plan_name)
        for pos, identity in enumerate(identities):
            if pos in claimed or identity != wanted:
                continue
            if not accepts(record, slices[pos]):
                continue
            claimed.add(pos)
            paired[index] = slices[pos]
            return

    for accepts in (_same_capability_and_method, _same_capability, _any_of_this_identity):
        for index in sorted(records):
            if paired[index] is None:
                _claim(index, accepts)

    return paired, tuple(s for pos, s in enumerate(slices) if pos not in claimed)


def _drift_note(record: dict[str, Any], live: SliceScore | None) -> str | None:
    """How the contract has moved under a locked obligation. ``None`` = it
    hasn't."""
    if live is None:
        return (
            "the slice was recorded at lock but is no longer in the contract as "
            "locked — no live slice proves the same features. A slice cannot be "
            "deleted, nor re-pointed at different features, out of its own proof"
        )
    diffs: list[str] = []
    locked_method = _record_method(record)
    if live.method != locked_method:
        diffs.append(f"proof method changed after lock ({locked_method} → {live.method})")
    locked_capability = str(record.get("capability") or "").strip().lower()
    if locked_capability and locked_capability != live.capability.strip().lower():
        diffs.append("capability text changed after lock")
    # No proof_refs drift to report: pairing is identity, so a record that has
    # a live slice at all has the same features it locked. A ref edit is a
    # delete plus an add, reported by the `live is None` branch above and by
    # the new slice's own obligation.
    return "; ".join(diffs) or None


def close_obligations(plan_dir: Path, score: OutcomeScore) -> list[ProofObligation]:
    """The proofs close is held to, keyed by the features each slice proves.

    Identity, not position (F004). A slice IS the exact set of features it
    promised to prove, so prepending a slice, reordering the list, or
    renumbering the whole contract leaves every locked obligation exactly where
    it was. Keying on the numeric index instead would let a replacement slice
    inherit the proof of whatever used to sit at its number — the locked
    obligation would silently vanish and the new slice would owe nothing. The
    same holds one feature at a time: a live slice sharing only *some* features
    with a locked one is a different promise, so both are owed. Where several
    slices share one identity, capability text separates them and, failing
    that, they are interchangeable — see :func:`_pair_locked_with_live`.

    With a lock-time sidecar, every recorded slice is an obligation whether or
    not it is still in the contract — otherwise deleting a slice would delete
    its proof, and the gap lock accepted could be erased on the way to close.
    Slices added to the contract *after* the lock are obligations too, taken
    from the live score. With no sidecar (any plan locked before the artifact
    existed) the live score is the whole obligation set, as before.

    Locked obligations keep their lock-time index, which is the number the
    operator was told at lock and the one a ``decisions.jsonl`` deferral
    addresses.
    """
    records = _locked_slice_records(plan_dir)

    def _from_live(slc: SliceScore, *, drift: str | None = None) -> ProofObligation:
        return ProofObligation(
            index=slc.index,
            label=slc.label(),
            method=slc.method,
            feature_ids=slc.feature_ids,
            origin="declared" if slc.has_proof else "inferred",
            locked=False,
            drift=drift,
        )

    if records is None:
        return [_from_live(slc) for slc in score.slice_scores]

    paired, unclaimed = _pair_locked_with_live(
        records, score.slice_scores, score.plan_id, plan_dir.name
    )
    obligations = [
        ProofObligation(
            index=index,
            label=_slice_label(
                index,
                str(record.get("audience") or "unknown"),
                str(record.get("kind") or "unknown"),
                str(record.get("capability") or ""),
            ),
            method=_record_method(record),
            feature_ids=_record_refs(record),
            origin="declared" if record.get("declared_method") else "inferred",
            locked=True,
            drift=_drift_note(record, paired.get(index)),
        )
        for index, record in sorted(records.items())
    ]
    obligations.extend(_from_live(slc) for slc in unclaimed)
    # Lock-time index first, and a locked obligation ahead of a live one that
    # landed on the same number — the operator reads the proof they were held
    # to before the one the contract has since grown.
    obligations.sort(key=lambda o: (o.index, not o.locked))
    return obligations


def evaluate_close_proofs(plan_dir: Path) -> list[str]:
    """Step 4 — one reason per obligation whose proof is neither run nor
    deferred, preceded by one for destroyed lock evidence.

    Empty list means close may proceed. Silent (empty) for every plan that
    declares no slices and locked none, which is every plan authored before
    this contract — including one locked before the sidecar existed, whose
    absent record is a legacy absence and not a loss (F005 AC1).

    The lock-evidence reason comes first and stands on its own: a plan whose
    record was deleted or corrupted after the lock may well have every live
    proof run, and closing it on that basis would be closing against a
    contract the operator never locked.
    """
    plan_dir = Path(plan_dir).resolve()
    try:
        score = score_plan(plan_dir)
    except OutcomeScoreError:
        return []  # unreadable plan.md is the caller's error to report, not ours

    defect = lock_evidence_defect(plan_dir)
    obligations = close_obligations(plan_dir, score)
    if not obligations:
        return [defect] if defect else []

    entries = read_decision_entries(plan_dir)
    lookup = _feature_evidence_resolver(plan_dir, score.plan_id)
    reasons: list[str] = [defect] if defect else []

    for obligation in obligations:
        deferral = _gap_entry(
            entries, _DEFER_KINDS, obligation.index, obligation.feature_ids
        )
        if deferral is not None:
            continue
        method = obligation.method
        matched = False
        unresolved: list[str] = []
        for fid in obligation.feature_ids:
            refs = lookup(fid)
            if refs is None:
                unresolved.append(fid)
                continue
            if any(evidence_ref_runs_method(ref, method) for ref in refs):
                matched = True
                break
        if matched:
            continue
        unresolved_note = (
            f" Cross-plan proof_refs {unresolved} do not resolve — no sibling plan "
            "dir of that id carries a features.json, so nothing there can prove this "
            "slice."
            if unresolved
            else ""
        )
        drift_note = (
            f" This obligation was recorded at lock and {obligation.drift}. Restore "
            "the slice and run the proof it named, or defer the gap in decisions.jsonl "
            "— editing the contract after the lock does not retire a proof."
            if obligation.drift
            else ""
        )
        reasons.append(
            f"{obligation.label} — {obligation.origin} proof method '{method}' never "
            f"ran: no evidence_ref of that method on "
            f"{list(obligation.feature_ids) or 'any feature'}. "
            f"Run it and attach the evidence (type "
            f"{sorted(_METHOD_EVIDENCE_TYPES.get(method, frozenset())) or 'any'}, or any "
            f"ref whose note carries 'proof:{method}'), or defer the gap with a "
            f'decisions.jsonl entry: {{"kind": "proof_gap_deferred", "slice": '
            f'{obligation.index}, "reason": "<why>"}}' + unresolved_note + drift_note
        )
    return reasons


__all__ = [
    "LOCK_EVIDENCE_ALTERED",
    "LOCK_EVIDENCE_CORRUPT",
    "LOCK_EVIDENCE_INTACT",
    "LOCK_EVIDENCE_LEGACY",
    "LOCK_EVIDENCE_MISSING",
    "LOCK_RECEIPT_KIND",
    "OUTCOME_INHERITED",
    "OUTCOME_MISSING",
    "OUTCOME_PRESENT",
    "OUTCOME_SCORE_ARTIFACT",
    "PROOFS_ACCEPTED_GAP",
    "PROOFS_INFERRED",
    "PROOFS_MISSING",
    "PROOFS_ONE_PER_SLICE",
    "SLICES_MECE",
    "SLICES_NA",
    "SLICES_OVERLAP",
    "SLICES_SINGLE",
    "SLICE_FROM_DELIVERS",
    "SLICE_FROM_FEATURE",
    "LockEvidence",
    "OutcomeScore",
    "OutcomeScoreError",
    "ProofObligation",
    "SliceScore",
    "append_lock_receipt",
    "backfill_lock_receipt",
    "close_obligations",
    "evaluate_close_proofs",
    "evidence_ref_runs_method",
    "feature_proof_method",
    "lock_evidence_defect",
    "loss_acknowledgement_defect",
    "proof_defects",
    "read_decision_entries",
    "read_feature_records",
    "read_lock_evidence",
    "read_lock_receipt",
    "read_score_sidecar",
    "render_score_lines",
    "score_payload",
    "score_payload_defect",
    "score_plan",
    "slice_defects",
    "write_score_sidecar",
]
