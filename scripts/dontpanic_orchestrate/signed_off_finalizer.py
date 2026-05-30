"""signed_off_finalizer — no-paid finalization of a cleanly auditor-signed_off feature.

Plan 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 F007 AC(9)-(12) / D025.

The gap this closes: when an implementer/auditor volley converges to a
``signed_off`` verdict it PAUSES at the ``pre_merge`` human gate *before*
``supervisor._emit_volley_terminal`` runs, so no signoff envelope is written and
``features.json`` is never flipped. The only existing flip path lives in
``closeout.run_close_out`` behind the operator-resolved / no_progress closeout —
wrong semantics for a clean signed_off. Re-dispatching to finalize would re-run
paid implementer+auditor calls.

This module finalizes such a feature with ZERO paid agent calls: it consumes the
existing ``signed_off`` auditor envelope plus a cleared ``pre_merge`` gate,
repairs the signoff envelope if missing, and flips ONLY that feature's
``passes: true`` with an evidence ref. It never imports or calls
``supervisor.dispatch_volley`` / any executor.

Refusals (each a distinct ``FinalizeError.code`` for distinct CLI exit codes):
  - ``no_audit``            — no auditor envelope exists for the feature.
  - ``not_signed_off``      — latest auditor verdict is not ``signed_off``.
  - ``pre_merge_uncleared`` — the ``pre_merge`` gate has not been cleared.

Idempotent: re-running on an already-flipped feature is a no-op success.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import closeout, gate_pause, signoff_writer

SIGNED_OFF_VERDICT = "signed_off"
PRE_MERGE_GATE = "pre_merge"
FINALIZE_REASON = "signed_off_finalize"
_DEFAULT_TIER = "cross-cutting"
_TIER_RE = re.compile(r"^tier:\s*([A-Za-z0-9_-]+)\s*$", re.MULTILINE)


class FinalizeError(Exception):
    """Raised when finalization is refused. ``code`` names the refusal case so
    CLI surfaces can map it to a distinct exit code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class FinalizeResult:
    """Outcome of a successful finalize (or idempotent no-op)."""

    plan_id: str
    feature_id: str
    auditor: str
    iteration: int
    signoff_path: Path
    signoff_repaired: bool
    features_passes_flipped: bool
    already_finalized: bool


def _verdict_of(envelope: dict[str, Any]) -> str | None:
    """Read the auditor verdict from an envelope. Current envelopes use
    ``audit_status``; older shapes used ``verdict``. Returns None when absent."""
    for key in ("audit_status", "verdict"):
        val = envelope.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _read_plan_tier(plan_dir: Path) -> str:
    """Read ``tier:`` from plan.md frontmatter. Falls back to the cross-cutting
    default if absent so signoff-envelope repair never hard-fails on a missing
    optional field (signoff_writer validates the value against VALID_TIERS)."""
    plan_md = plan_dir / "plan.md"
    if plan_md.is_file():
        m = _TIER_RE.search(plan_md.read_text())
        if m and m.group(1) in signoff_writer.VALID_TIERS:
            return m.group(1)
    return _DEFAULT_TIER


def _agents_in_panel(audit_paths: list[Path]) -> list[str]:
    """Distinct agent names across the feature's audit envelopes, preserving
    first-seen order (implementer then auditor)."""
    seen: list[str] = []
    for p in audit_paths:
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        agent = data.get("agent")
        if isinstance(agent, str) and agent and agent not in seen:
            seen.append(agent)
    return seen


def finalize_signed_off_feature(
    plan_dir: Path,
    *,
    plan_id: str,
    feature_id: str,
) -> FinalizeResult:
    """Finalize a signed_off + pre_merge-cleared feature with no paid calls.

    Steps (stage-then-commit; signoff is made durable before the features flip):
      1. Require at least one auditor envelope (else ``no_audit``).
      2. Require the latest auditor verdict == ``signed_off`` (else
         ``not_signed_off``).
      3. Require ``pre_merge`` cleared (else ``pre_merge_uncleared``).
      4. Repair the signoff envelope if missing (the pre_merge pause skips
         ``_emit_volley_terminal``), reusing ``signoff_writer.write_signoff``.
      5. Flip ONLY this feature's ``passes: true`` + evidence ref, idempotently.

    Never invokes ``dispatch_volley`` or any executor.
    """
    plan_dir = Path(plan_dir).resolve()

    audit_paths = closeout._audit_paths_for_feature(plan_dir, feature_id)
    envelope = closeout._latest_auditor_envelope(audit_paths)
    if envelope is None:
        # No AUDITOR envelope specifically — an implementer-only envelope (or
        # an empty audit dir) means the volley never produced a verdict.
        raise FinalizeError(
            "no_audit",
            f"no auditor envelope found for {feature_id!r} in {plan_dir / 'audit'}; "
            f"finalize requires a converged signed_off volley.",
        )

    verdict = _verdict_of(envelope)
    if verdict != SIGNED_OFF_VERDICT:
        raise FinalizeError(
            "not_signed_off",
            f"latest auditor verdict for {feature_id!r} is {verdict!r}, not "
            f"'signed_off'; refuse to finalize. Address findings and re-audit first.",
        )

    if not gate_pause.is_gate_cleared(plan_dir, PRE_MERGE_GATE):
        raise FinalizeError(
            "pre_merge_uncleared",
            f"pre_merge gate is not cleared for {plan_id}; finalize requires the "
            f"human pre_merge approval first "
            f"(`dontpanic approve {plan_id} {PRE_MERGE_GATE}`).",
        )

    auditor = str(envelope.get("agent") or envelope.get("auditor") or "unknown")
    iteration = int(envelope.get("iteration", 0) or 0)

    # Step 4 — repair signoff envelope only if missing (the pre_merge pause
    # skipped _emit_volley_terminal). Never clobber an existing one.
    out_path = signoff_writer.signoff_path(plan_dir, plan_id)
    signoff_repaired = False
    if not out_path.is_file():
        out_path = signoff_writer.write_signoff(
            plan_id=plan_id,
            tier=_read_plan_tier(plan_dir),
            iteration=iteration,
            agents_in_panel=_agents_in_panel(audit_paths),
            audit_paths=audit_paths,
            plan_dir=plan_dir,
            volley_status=SIGNED_OFF_VERDICT,
            signoff_reason=(
                f"no-paid finalize of signed_off feature {feature_id} "
                f"(pre_merge cleared); F007 finalizer"
            ),
        )
        signoff_repaired = True

    # Step 5 — flip only this feature, idempotently, citing the signoff envelope.
    memo_rel = signoff_writer._audit_relpath(out_path, plan_dir)
    _features_json, flipped = closeout._flip_feature_passes(
        plan_dir,
        feature_id,
        reason_class=FINALIZE_REASON,
        memo_relpath=memo_rel,
    )

    already_finalized = not signoff_repaired and not flipped

    return FinalizeResult(
        plan_id=plan_id,
        feature_id=feature_id,
        auditor=auditor,
        iteration=iteration,
        signoff_path=out_path,
        signoff_repaired=signoff_repaired,
        features_passes_flipped=flipped,
        already_finalized=already_finalized,
    )


__all__ = [
    "FinalizeError",
    "FinalizeResult",
    "finalize_signed_off_feature",
    "SIGNED_OFF_VERDICT",
]
