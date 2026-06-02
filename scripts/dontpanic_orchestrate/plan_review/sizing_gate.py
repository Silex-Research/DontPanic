"""Pre-dispatch sizing gate (F007).

Wires the F001 scope lint into ``dispatch-from-plan`` so a feature that
currently violates the *size* budget cannot start a paid volley without an
explicit operator override. This catches scope drift at the exact moment it
would otherwise cause a 600s-timeout stall, converting the expensive
``stall -> operator splits -> re-volley`` path into the cheap
``blocked pre-flight -> split proposed -> dispatch clean`` one.

The gate is deliberately **narrow** (acceptance #4 — it adds *only* the size
check): it fires solely on block-severity *size* flags
(:data:`SIZE_FLAG_KINDS`). The precision (``exemplar_ac`` / ``weak_test``) and
coupling (``missing_prereq``) signals F001 also emits are surfaced by
``plan-review`` (F003) and the pre-lock gate (F004), not here — keeping this
feature's single (orchestration) surface honest under the plan's own
surface-count discipline.

Everything except :func:`record_override` is pure: :func:`evaluate_feature`
runs the pure F001 lint + F002 proposer and never touches the filesystem.
``record_override`` is the one I/O seam — it writes the operator's rationale to
an evidence sidecar (mirroring the goal-governance / patch-completeness
override-recording convention) so the override is auditable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dontpanic_orchestrate.plan_review.lint import (
    Resolvers,
    ScopeFlag,
    ScopeReport,
    lint_feature,
)
from dontpanic_orchestrate.plan_review.split import SplitProposal, propose_split

# ─────────────────────────────── public types ──────────────────────────────

# The block-severity flag kinds that represent over-scope (the "size budget").
# Mirrors F001's ``_size_flags``: surface-count (``over_surface``), AC-count
# (``over_ac``), and the composite ``likely_timeout`` signal. These — and only
# these — gate dispatch. ``exemplar_ac`` / ``weak_test`` (precision) and
# ``missing_prereq`` (coupling) are intentionally NOT size flags.
SIZE_FLAG_KINDS: frozenset[str] = frozenset(
    {"over_surface", "over_ac", "likely_timeout"}
)


@dataclass(frozen=True)
class SizingGateResult:
    """The pre-dispatch sizing verdict for a single feature.

    ``block_size_flags`` is the subset of the feature's flags that both have
    ``block`` severity and are a size kind — i.e. exactly the flags that refuse
    dispatch. ``split`` is F002's remediation proposal (``None`` when the
    feature is not ``over_surface`` / ``over_ac``, e.g. a bare ``likely_timeout``
    that F002 cannot partition).
    """

    feature_id: str
    report: ScopeReport
    split: SplitProposal | None
    block_size_flags: tuple[ScopeFlag, ...]

    @property
    def is_blocked(self) -> bool:
        """True iff the feature carries a block-severity size flag."""
        return bool(self.block_size_flags)


# ─────────────────────────────── public API ────────────────────────────────


def evaluate_feature(
    feature: dict, resolvers: Resolvers | None = None
) -> SizingGateResult:
    """Run the F001 sizing lint over one ``feature`` and propose a split.

    Pure: no network, no filesystem, no mutation of ``feature``. The gate
    decision depends only on the *size* flags, which F001 derives from surface-
    count and AC-count and so are independent of ``resolvers`` (those only
    affect the coupling ``missing_prereq`` signal the gate ignores) — ``None``
    is therefore a fine default.
    """
    report = lint_feature(feature, resolvers)
    block_size_flags = tuple(
        f
        for f in report.flags
        if f.severity == "block" and f.kind in SIZE_FLAG_KINDS
    )
    # Surface F002's remediation whenever the feature is partition-able
    # (over_surface / over_ac). propose_split returns None otherwise.
    split = propose_split(feature, report)
    return SizingGateResult(
        feature_id=report.feature_id,
        report=report,
        split=split,
        block_size_flags=block_size_flags,
    )


def render_preflight(result: SizingGateResult) -> str:
    """Concise sizing-lint block for the dispatch-from-plan pre-flight.

    Printed in BOTH dry-run and confirm modes (acceptance #1 — the lint runs in
    the pre-flight). Shows the feature's surfaces + AC count and a one-line OK /
    BLOCK verdict; the full split proposal is reserved for the refusal message.
    """
    scope = result.report
    verdict = "BLOCK" if result.is_blocked else "OK"
    lines = [
        "[dispatch-from-plan] sizing-lint (F001)",
        f"  feature:   {scope.feature_id or '(unnamed)'}",
        f"  surfaces:  {', '.join(scope.surfaces)}",
        f"  ac_count:  {scope.ac_count}",
        f"  verdict:   {verdict}",
    ]
    for flag in result.block_size_flags:
        lines.append(f"    [{flag.severity}] {flag.kind}: {flag.evidence}")
    return "\n".join(lines)


def render_block_message(result: SizingGateResult) -> str:
    """The refusal message shown when an over-budget feature is blocked.

    Names every block-severity size flag and surfaces the F002 split proposal
    as the remediation (acceptance #2), plus the ``--allow-oversize`` override
    affordance (acceptance #3).
    """
    fid = result.feature_id or "(unnamed)"
    lines = [
        f"[dispatch-from-plan] BLOCKED by pre-dispatch sizing gate: feature {fid} "
        "exceeds the size budget; refusing to start a paid volley.",
    ]
    for flag in result.block_size_flags:
        lines.append(f"  [{flag.severity}] {flag.kind}: {flag.evidence}")

    if result.split is not None and result.split.children:
        split = result.split
        lines.append(
            f"  remediation — suggested split into {len(split.children)} "
            "feature(s) (run `dontpanic plan-review` for the full report):"
        )
        for child in split.children:
            deps = ", ".join(child.depends_on) or "(none)"
            lines.append(
                f"    {child.provisional_id} [{', '.join(child.surfaces)}] "
                f"— {len(child.acceptance_subset)} AC(s), depends_on: {deps}"
            )
        if split.multi_surface_acs:
            lines.append("  multi-surface AC(s) to sharpen first:")
            for text, surfaces in split.multi_surface_acs:
                clipped = text if len(text) <= 80 else text[:79] + "…"
                lines.append(f"    [{', '.join(surfaces)}] {clipped}")
    else:
        lines.append(
            "  remediation — split this feature so each child touches a single "
            "surface within one dispatch's budget."
        )

    lines.append(
        "  override — re-run with `--allow-oversize <reason>` (>=8 chars) to "
        "record a rationale and dispatch anyway."
    )
    return "\n".join(lines)


def record_override(
    plan_dir: Path,
    *,
    plan_id: str,
    feature_id: str,
    reason: str,
    result: SizingGateResult,
    now: datetime | None = None,
) -> Path:
    """Persist an oversize-override rationale to an evidence sidecar.

    Mirrors the codebase's override-recording convention (goal-governance
    ``override.json``, patch-completeness ``signoff.json``): the operator's
    verbatim ``reason`` plus the flags it overrode land in a JSON file under
    ``<plan_dir>/evidence/plan-review/pre_dispatch/`` so the override is
    auditable after the fact. Returns the path written.
    """
    out_dir = plan_dir / "evidence" / "plan-review" / "pre_dispatch"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{feature_id}-oversize-override.json"

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "gate": "pre_dispatch_sizing",
        "plan_id": plan_id,
        "feature_id": feature_id,
        "reason": reason,
        "surfaces": list(result.report.surfaces),
        "ac_count": result.report.ac_count,
        "overridden_flags": [
            {"kind": f.kind, "severity": f.severity, "evidence": f.evidence}
            for f in result.block_size_flags
        ],
        "recorded_at": stamp,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path
