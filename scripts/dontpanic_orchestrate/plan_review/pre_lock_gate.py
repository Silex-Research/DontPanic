"""Pre-lock design gate (F004).

Wires the F001 scope lint into ``dontpanic plan lock`` so a plan cannot
transition ``draft -> active`` while any feature carries a *block-severity*
scope flag, unless the operator overrides with a recorded rationale that lands
in the plan's ``decisions.jsonl``. This is the shift-left enforcement point for
feature sizing and AC precision: the cheap-to-prevent over-scope / exemplar-AC
/ missing-prereq class is caught at lock time, before any paid implementation
round is spent.

Relationship to the F007 pre-*dispatch* sizing gate
----------------------------------------------------
F007 (:mod:`plan_review.sizing_gate`) gates a single feature at dispatch on the
*size* flags only (``over_surface`` / ``over_ac`` / ``likely_timeout``). F004 is
broader and earlier: it gates the *whole plan* at lock on **any** block-severity
flag — size, precision (``exemplar_ac``), and coupling (``missing_prereq``) —
because lock is the moment to refuse an under-specified decomposition wholesale,
not just an over-sized one. The step's named kinds
(``over_surface`` / ``over_ac`` / ``exemplar_ac`` / ``missing_prereq``) are all
block-severity; gating on ``severity == "block"`` covers them and the composite
``likely_timeout`` signal too, satisfying acceptance #2's "any block-severity
scope flag".

Purity
------
Everything except :func:`record_override` is pure: :func:`evaluate_plan` runs
the pure F001 lint (via the F003 :func:`build_plan_scope_report`) and never
touches the filesystem. ``record_override`` is the one I/O seam — it appends the
operator's verbatim rationale to the plan's ``decisions.jsonl`` (acceptance #3)
so the override is auditable in the same ledger as every other plan decision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dontpanic_orchestrate.plan_review.lint import Resolvers
from dontpanic_orchestrate.plan_review.report import (
    FeatureScopeReport,
    PlanScopeReport,
    build_plan_scope_report,
)

# ─────────────────────────────── public types ──────────────────────────────

# The block-severity flag kinds the step names explicitly. Kept as a documented
# constant for callers/tests that want to reason about the named set; the gate
# itself refuses on ANY block-severity flag (acceptance #2), which is a superset
# (it also catches the composite ``likely_timeout`` signal).
NAMED_BLOCK_FLAG_KINDS: frozenset[str] = frozenset(
    {"over_surface", "over_ac", "exemplar_ac", "missing_prereq"}
)

# Minimum non-whitespace length of an ``--allow-oversize`` override reason
# (acceptance #3). Mirrors patch_completeness_gate.MIN_REASON_LEN so all
# operator-override surfaces share one bar.
MIN_REASON_LEN = 8


@dataclass(frozen=True)
class PreLockGateResult:
    """The pre-lock scope verdict for a whole plan.

    ``blocking_features`` is the subset of feature reports that carry at least
    one block-severity flag — i.e. exactly the features that refuse the lock.
    """

    plan_id: str
    report: PlanScopeReport
    blocking_features: tuple[FeatureScopeReport, ...]

    @property
    def is_blocked(self) -> bool:
        """True iff any feature carries a block-severity scope flag."""
        return bool(self.blocking_features)

    def flag_names(self) -> tuple[str, ...]:
        """The distinct ``feature_id:kind`` labels of every blocking flag.

        Used by callers that want a compact, deterministic naming of what
        refused the lock (acceptance #2 — "the flags named").
        """
        names: list[str] = []
        seen: set[str] = set()
        for fr in self.blocking_features:
            for flag in fr.scope.flags:
                if flag.severity != "block":
                    continue
                label = f"{fr.scope.feature_id or '(unnamed)'}:{flag.kind}"
                if label not in seen:
                    seen.add(label)
                    names.append(label)
        return tuple(names)


# ─────────────────────────────── public API ────────────────────────────────


def evaluate_plan(
    plan_id: str,
    features: list[dict],
    resolvers: Resolvers | None = None,
) -> PreLockGateResult:
    """Run the F001 lint over every feature and decide the pre-lock verdict.

    Pure: no network, no filesystem, no mutation of ``features``. The plan is
    blocked iff any feature carries a block-severity flag.
    """
    report = build_plan_scope_report(plan_id, features, resolvers)
    blocking = tuple(fr for fr in report.features if fr.scope.has_block())
    return PreLockGateResult(
        plan_id=plan_id,
        report=report,
        blocking_features=blocking,
    )


def render_block_message(result: PreLockGateResult) -> str:
    """The refusal message shown when a plan is blocked at lock.

    Names every block-severity flag per feature (acceptance #2) and points at
    the ``--allow-oversize`` override affordance (acceptance #3). The full
    split-proposal remediation lives in ``dontpanic plan-review`` (F003); this
    message stays a compact lock-time refusal.
    """
    pid = result.plan_id or "(unnamed)"
    lines = [
        f"[plan lock] BLOCKED by pre-lock design gate: plan {pid} carries "
        "block-severity scope flag(s); refusing the draft → active transition.",
    ]
    for fr in result.blocking_features:
        scope = fr.scope
        lines.append(
            f"  {scope.feature_id or '(unnamed)'} "
            f"[{', '.join(scope.surfaces)}] — {scope.ac_count} AC(s):"
        )
        for flag in scope.flags:
            if flag.severity != "block":
                continue
            lines.append(f"    [{flag.severity}] {flag.kind}: {flag.evidence}")
    lines.append(
        "  remediation — run `dontpanic plan-review <plan>` for the full scope "
        "report and suggested splits, then sharpen/split the flagged features."
    )
    lines.append(
        "  override — re-run `dontpanic plan lock <plan> --allow-oversize "
        "<reason>` (>=8 non-whitespace chars) to record a rationale in "
        "decisions.jsonl and lock anyway."
    )
    return "\n".join(lines)


def record_override(
    plan_dir: Path,
    *,
    plan_id: str,
    reason: str,
    result: PreLockGateResult,
    now: datetime | None = None,
) -> Path:
    """Append an oversize-override decision to the plan's ``decisions.jsonl``.

    Records the operator's ``reason`` **verbatim** (acceptance #3) under a
    dedicated ``reason`` field, alongside the named flags it overrode, so the
    decision ledger carries an auditable rationale for the lock. Returns the
    path written (``<plan_dir>/decisions.jsonl``).

    The new entry's ``id`` is the next ``D<n>`` after the highest existing
    decision id (``D001`` when the ledger is absent/empty), matching the plan's
    decision-numbering convention.
    """
    decisions_path = plan_dir / "decisions.jsonl"
    next_id = _next_decision_id(decisions_path)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")

    entry = {
        "id": next_id,
        "by": "operator",
        "ts": stamp,
        "title": "Pre-lock design gate override (--allow-oversize)",
        "reason": reason,
        "overridden_flags": list(result.flag_names()),
        "body": (
            "Operator overrode the F004 pre-lock design gate to lock this plan "
            "despite block-severity scope flag(s) "
            f"[{', '.join(result.flag_names()) or '(none)'}]. "
            f"Recorded rationale (verbatim): {reason}"
        ),
    }

    # Append-only: preserve every prior decision line untouched.
    with decisions_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return decisions_path


def validate_reason(reason: str) -> str:
    """Layer-B re-check that ``reason`` has >=8 non-whitespace chars.

    Defense-in-depth mirror of the CLI argparse layer-A validator (so a caller
    invoking :func:`record_override` directly cannot smuggle a too-short
    reason). Raises ``ValueError`` on rejection.
    """
    stripped = (reason or "").strip()
    if len(stripped) < MIN_REASON_LEN:
        raise ValueError(
            f"--allow-oversize reason must be at least {MIN_REASON_LEN} "
            f"non-whitespace characters; got {len(stripped)} ({reason!r})."
        )
    return reason


# ───────────────────────────────── utils ───────────────────────────────────


def _next_decision_id(decisions_path: Path) -> str:
    """Return the next ``D<n>`` id after the highest existing one in the ledger.

    Tolerant of an absent/empty file (returns ``D001``) and of malformed lines
    (skipped). Duplicate ids in the existing ledger are fine — the max wins.
    """
    highest = 0
    if decisions_path.is_file():
        for line in decisions_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw = str(obj.get("id", ""))
            if raw.startswith("D") and raw[1:].isdigit():
                highest = max(highest, int(raw[1:]))
    return f"D{highest + 1:03d}"
