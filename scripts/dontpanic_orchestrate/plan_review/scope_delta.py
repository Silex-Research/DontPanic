"""Mid-development scope-delta lint (F006).

Keeps scope honest as a plan *evolves* — the moment most drift is introduced.
On any change to ``features.json`` / ``objective_contract``, this re-runs the
F001 lint on the **changed features only** (the diff, not the whole plan),
classifies each change, and enforces the scope-change protocol:

  * **sharpen** — an AC was narrowed / concretised with no new surface and no
    new exemplar. Passes without friction (acceptance #5).
  * **expand** — an AC or surface was *added* to a feature. When the feature is
    locked AND the expand pushes it past the size budget, it is **refused**
    until either a recorded rationale is supplied or the feature is split
    (acceptance #3).
  * **split** — one feature became several (children carry the parent's ACs).
    Accepted only when AC conservation holds; a **lossy** split is refused,
    naming the dropped / duplicated criteria (acceptance #4).

Relationship to the other plan-review gates
-------------------------------------------
F004 (pre-lock) and F007 (pre-dispatch) gate a *static* snapshot. F006 gates a
*transition* between two snapshots: it is the only gate that reasons about what
changed, so it is the one that can tell a benign sharpen from a budget-busting
expand and a clean split from a lossy one.

Purity: everything here is a pure function over the prior + current feature
lists. No network, no filesystem, no mutation. The CLI / edit hook that calls
it owns reading the two snapshots and recording any rationale.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from dontpanic_orchestrate.plan_review.lint import (
    Resolvers,
    ScopeReport,
    lint_feature,
    split_acceptance,
)
from dontpanic_orchestrate.plan_review.sizing_gate import SIZE_FLAG_KINDS

# Minimum non-whitespace length of a scope-change rationale that unblocks a
# budget-busting expand. Mirrors the F004 / F007 / patch-completeness bar.
MIN_REASON_LEN = 8

ChangeKind = Literal["sharpen", "expand", "split"]


# ─────────────────────────────── public types ──────────────────────────────


@dataclass(frozen=True)
class ScopeDelta:
    """The classification + verdict for one changed feature.

    ``refused`` is True only for a budget-busting expand without a rationale or
    a lossy split — exactly the two scope-change-protocol refusal paths
    (acceptance #3 / #4). A sharpen is never refused (#5).
    """

    feature_id: str
    kind: ChangeKind
    refused: bool
    reason: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "kind": self.kind,
            "refused": self.refused,
            "reason": self.reason,
            "evidence": dict(self.evidence),
        }


@dataclass
class ScopeDeltaReport:
    deltas: tuple[ScopeDelta, ...]

    @property
    def refusals(self) -> tuple[ScopeDelta, ...]:
        return tuple(d for d in self.deltas if d.refused)

    @property
    def is_blocked(self) -> bool:
        return bool(self.refusals)

    def to_dict(self) -> dict:
        return {"deltas": [d.to_dict() for d in self.deltas]}


# ─────────────────────────────── helpers ───────────────────────────────────


def _by_id(features: list[dict]) -> dict[str, dict]:
    return {str(f["id"]): f for f in features if f.get("id")}


def _acceptance_criteria(feature: dict) -> tuple[str, ...]:
    """The feature's acceptance criteria as a normalized tuple (reuses F001's
    ``split_acceptance`` so conservation is compared the same way F002 does)."""
    acc = feature.get("acceptance")
    if isinstance(acc, (list, tuple)):
        acc = "\n".join(str(a) for a in acc)
    return split_acceptance(str(acc or ""))


def _has_block_size_flag(report: ScopeReport) -> bool:
    return any(
        f.severity == "block" and f.kind in SIZE_FLAG_KINDS for f in report.flags
    )


def _has_exemplar(report: ScopeReport) -> bool:
    return any(f.kind == "exemplar_ac" for f in report.flags)


def changed_feature_ids(prior: list[dict], current: list[dict]) -> set[str]:
    """Ids whose record differs between the two snapshots, plus ids present in
    only one snapshot. This is the set the lint re-runs on (acceptance #1 — the
    changed features only, never the whole plan)."""
    prior_map, cur_map = _by_id(prior), _by_id(current)
    changed: set[str] = set()
    for fid in prior_map.keys() | cur_map.keys():
        if prior_map.get(fid) != cur_map.get(fid):
            changed.add(fid)
    return changed


# ─────────────────────────────── classifiers ───────────────────────────────


def _classify_modify(
    prior_feat: dict,
    cur_feat: dict,
    *,
    locked: bool,
    rationale: str | None,
    resolvers: Resolvers | None,
) -> ScopeDelta:
    """Classify a feature present in BOTH snapshots as sharpen or expand, and
    decide the expand refusal."""
    fid = str(cur_feat.get("id") or prior_feat.get("id") or "(unnamed)")
    prior_report = lint_feature(prior_feat, resolvers)
    cur_report = lint_feature(cur_feat, resolvers)

    added_surfaces = sorted(set(cur_report.surfaces) - set(prior_report.surfaces))
    added_acs = cur_report.ac_count - prior_report.ac_count
    new_exemplar = _has_exemplar(cur_report) and not _has_exemplar(prior_report)

    is_expand = bool(added_surfaces) or added_acs > 0
    evidence = {
        "added_surfaces": added_surfaces,
        "added_acs": added_acs,
        "prior_ac_count": prior_report.ac_count,
        "current_ac_count": cur_report.ac_count,
        "new_exemplar": new_exemplar,
    }

    if not is_expand:
        # sharpen — narrowed/concretised, no new surface, no added ACs.
        return ScopeDelta(
            feature_id=fid,
            kind="sharpen",
            refused=False,
            reason=(
                f"{fid}: sharpen — no surface added, AC count "
                f"{prior_report.ac_count}→{cur_report.ac_count}; passes without friction."
            ),
            evidence=evidence,
        )

    # expand. Refuse only when it pushes a LOCKED feature past the size budget
    # and no rationale was recorded (acceptance #3).
    crosses_budget = _has_block_size_flag(cur_report)
    evidence["crosses_size_budget"] = crosses_budget
    has_rationale = rationale is not None and len(rationale.strip()) >= MIN_REASON_LEN
    if has_rationale:
        evidence["scope_change_rationale"] = rationale

    refused = locked and crosses_budget and not has_rationale
    if refused:
        reason = (
            f"{fid}: expand REFUSED — a locked feature was pushed past the size "
            f"budget (added surfaces={added_surfaces or '∅'}, added ACs={added_acs}). "
            "Scope-change protocol: add a recorded rationale (>=8 chars) OR split "
            "the feature before this expand can land."
        )
    elif locked and crosses_budget and has_rationale:
        reason = (
            f"{fid}: expand allowed with recorded rationale despite crossing the "
            f"size budget (added surfaces={added_surfaces or '∅'}, added ACs={added_acs})."
        )
    else:
        reason = (
            f"{fid}: expand within budget (added surfaces={added_surfaces or '∅'}, "
            f"added ACs={added_acs})."
        )
    return ScopeDelta(
        feature_id=fid, kind="expand", refused=refused, reason=reason, evidence=evidence
    )


def _classify_split(
    parent_feat: dict,
    children: list[dict],
) -> ScopeDelta:
    """Classify a parent feature that became several children, verifying AC
    conservation (acceptance #4). A lossy split is refused, naming the dropped
    and duplicated criteria."""
    parent_id = str(parent_feat.get("id") or "(unnamed)")
    parent_ms = Counter(_acceptance_criteria(parent_feat))
    child_ms: Counter[str] = Counter()
    for child in children:
        child_ms.update(_acceptance_criteria(child))

    dropped = sorted((parent_ms - child_ms).elements())
    duplicated = sorted((child_ms - parent_ms).elements())
    conserved = parent_ms == child_ms

    child_ids = [str(c.get("id") or "(unnamed)") for c in children]
    evidence = {
        "child_ids": child_ids,
        "dropped": dropped,
        "duplicated": duplicated,
        "conservation_ok": conserved,
    }
    if conserved:
        reason = (
            f"{parent_id}: split into {len(children)} feature(s) "
            f"[{', '.join(child_ids)}] — AC conservation holds (zero dropped, "
            "zero duplicated)."
        )
        return ScopeDelta(
            feature_id=parent_id,
            kind="split",
            refused=False,
            reason=reason,
            evidence=evidence,
        )
    reason = (
        f"{parent_id}: split REFUSED — lossy partition. "
        f"dropped={dropped or '∅'}; duplicated={duplicated or '∅'}. "
        "A split must reproduce the parent's acceptance criteria exactly."
    )
    return ScopeDelta(
        feature_id=parent_id,
        kind="split",
        refused=True,
        reason=reason,
        evidence=evidence,
    )


# ─────────────────────────────── public API ────────────────────────────────


def review_scope_delta(
    prior_features: list[dict],
    current_features: list[dict],
    *,
    locked_ids: frozenset[str] | set[str] = frozenset(),
    rationales: dict[str, str] | None = None,
    resolvers: Resolvers | None = None,
) -> ScopeDeltaReport:
    """Classify every changed feature between two plan snapshots and apply the
    scope-change protocol.

    A **split** is signalled by child features carrying a ``split_of: <parent>``
    annotation whose parent is absent from ``current_features`` — the conserving
    set is then verified. A feature present in both snapshots is classified as
    sharpen or expand. ``rationales`` maps a feature id to an operator-supplied
    scope-change rationale that unblocks a budget-busting expand.
    """
    rationales = rationales or {}
    prior_map = _by_id(prior_features)
    cur_map = _by_id(current_features)

    # Group split children by their declared parent.
    split_children: dict[str, list[dict]] = {}
    for feat in current_features:
        parent = feat.get("split_of")
        if parent:
            split_children.setdefault(str(parent), []).append(feat)

    deltas: list[ScopeDelta] = []
    handled: set[str] = set()

    # 1. Splits: a prior feature gone from current, with declared children.
    for parent_id, children in split_children.items():
        if parent_id in prior_map and parent_id not in cur_map:
            deltas.append(_classify_split(prior_map[parent_id], children))
            handled.add(parent_id)

    # 2. Modified features present in both snapshots.
    for fid in changed_feature_ids(prior_features, current_features):
        if fid in handled:
            continue
        prior_feat = prior_map.get(fid)
        cur_feat = cur_map.get(fid)
        if prior_feat is None or cur_feat is None:
            # A pure add (child of a split is handled above) or a pure removal
            # is not one of the three in-scope change classes; skip silently.
            continue
        deltas.append(
            _classify_modify(
                prior_feat,
                cur_feat,
                locked=fid in locked_ids,
                rationale=rationales.get(fid),
                resolvers=resolvers,
            )
        )

    deltas.sort(key=lambda d: d.feature_id)
    return ScopeDeltaReport(deltas=tuple(deltas))


def render_block_message(report: ScopeDeltaReport) -> str:
    """Refusal message naming every refused delta (the scope-change-protocol
    violations) — the budget-busting expands and the lossy splits."""
    if not report.is_blocked:
        return "[scope-delta] no scope-change-protocol violations."
    lines = [
        "[scope-delta] BLOCKED by the scope-change protocol — the following "
        "changes are refused:",
    ]
    for delta in report.refusals:
        lines.append(f"  [{delta.kind}] {delta.reason}")
    return "\n".join(lines)
