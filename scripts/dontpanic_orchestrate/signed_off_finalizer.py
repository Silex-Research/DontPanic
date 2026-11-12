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
  - ``charter_unchecked`` / ``child_charter_violation`` — child plan whose
    charter compliance cannot be checked / fails on repair.
  - ``signoff_unreadable`` / ``signoff_wrong_plan`` / ``signoff_not_success`` /
    ``signoff_stale`` / ``child_signoff_missing`` — an EXISTING signoff envelope
    (or its required child compliance side-car) is not a durable successful
    signoff for this verdict; see :func:`_validate_existing_signoff`.

Idempotent: re-running on an already-flipped feature is a no-op success.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import (
    closeout,
    gate_pause,
    nested_orchestration,
    plan_loader,
    signoff_writer,
)

SIGNED_OFF_VERDICT = "signed_off"
PRE_MERGE_GATE = "pre_merge"
FINALIZE_REASON = "signed_off_finalize"
_DEFAULT_TIER = "cross-cutting"
_TIER_RE = re.compile(r"^tier:\s*([A-Za-z0-9_-]+)\s*$", re.MULTILINE)
# nested_orchestration.ReturnConditionStatus — the statuses a passing
# check_child_charter_compliance records (a violation raises instead).
_RETURN_CONDITION_STATUSES = frozenset({"satisfied", "blocked", "superseded"})


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


def _latest_auditor_path(audit_paths: list[Path]) -> Path | None:
    """Path of the freshest auditor envelope, ranked exactly like
    :func:`closeout._latest_auditor_envelope` (mtime, then iteration index) so
    the evidence ref points at the SAME artifact whose verdict authorized the
    flip (F007 AC9)."""
    best: Path | None = None
    best_key: tuple[float, int] | None = None
    for path in audit_paths:
        if "auditor" not in path.name:
            continue
        try:
            mtime = path.stat().st_mtime
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        key = (mtime, closeout._auditor_iteration_of(path))
        if best_key is None or key > best_key:
            best_key = key
            best = path
    return best


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


def _load_charter_context(plan_dir: Path, plan_id: str) -> tuple[Any, Any, Any]:
    """Return ``(child_charter, commit_policy, orchestration)`` for the plan.

    Tolerant for legacy top-level plans that fail to load (all None), but a
    plan that DECLARES a ``child_charter`` and cannot be loaded refuses with
    ``charter_unchecked`` — its compliance cannot be verified."""
    try:
        loaded = plan_loader.load(plan_dir)
    except Exception as exc:  # noqa: BLE001 — legacy tolerant tier read
        plan_md = plan_dir / "plan.md"
        text = plan_md.read_text() if plan_md.is_file() else ""
        if re.search(r"^child_charter\s*:", text, re.MULTILINE):
            raise FinalizeError(
                "charter_unchecked",
                f"plan {plan_id} declares a child_charter but could not be "
                f"loaded to check compliance; refusing to finalize: {exc}",
            ) from exc
        return None, None, None
    return loaded.child_charter, loaded.commit_policy, loaded.orchestration


def _parse_iso(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _signoff_lists_audit(audits: list[Any], auditor_path: Path, plan_dir: Path) -> bool:
    """True when one of the signoff's ``audits`` entries (plan-relative or
    absolute) resolves to ``auditor_path``."""
    target = auditor_path.resolve()
    for entry in audits:
        if not isinstance(entry, str) or not entry:
            continue
        p = Path(entry)
        if not p.is_absolute():
            p = plan_dir / p
        if p.resolve() == target:
            return True
    return False


def _validate_existing_signoff(
    out_path: Path,
    *,
    plan_dir: Path,
    plan_id: str,
    iteration: int,
    auditor_path: Path | None,
    child_charter: Any,
    commit_policy: Any,
) -> None:
    """Refuse (``FinalizeError``) unless the existing signoff envelope is a
    durable, successful signoff for THIS plan and THIS signed_off verdict.

    Read-only: never writes. Checks, in order (each a distinct stable code):

      * ``signoff_unreadable``  — empty, torn/unparseable JSON, not an object,
        or fails the agent-conventions ``Signoff`` schema (the post-validation
        ``patch_completeness`` sibling key is ignored for the schema check).
      * ``signoff_wrong_plan``  — ``task_id`` != the plan being finalized.
      * ``signoff_not_success`` — ``signoff`` is not ``true`` or
        ``next_action`` != ``merge`` (a non-success terminal record).
      * ``signoff_stale``       — the signoff does not correspond to the
        signed_off auditor envelope this finalizer selected. Stale means ANY of:
          - ``signoff.iteration`` != the selected envelope's ``iteration``;
          - the selected auditor envelope is not listed in ``signoff.audits``;
          - the envelope carries ``completed_at`` and ``signoff.decided_at`` is
            earlier than it (second granularity) — the signoff predates the
            verdict, e.g. a re-dispatch rewrote the same ``-iN`` filename.
      * ``child_signoff_missing`` — the plan declares a ``child_charter`` and
        the charter-compliance side-car written by ``signoff_writer`` is
        missing, unreadable, for another plan, has an unknown
        ``return_condition_status``, records a different commit-policy mode,
        or does not list every ``commit_policy.requires`` item as satisfied.
    """
    from dontpanic_orchestrate.agent_conventions.schemas.v1_0.models.signoff_model import (
        Signoff,
    )
    from pydantic import ValidationError

    try:
        raw = out_path.read_text()
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalizeError(
            "signoff_unreadable",
            f"existing signoff {out_path} is empty or unparseable ({exc}); "
            f"refusing to finalize on a torn signoff.",
        ) from exc
    if not isinstance(data, dict):
        raise FinalizeError(
            "signoff_unreadable",
            f"existing signoff {out_path} is not a JSON object; refusing to finalize.",
        )
    try:
        Signoff.model_validate({k: v for k, v in data.items() if k != "patch_completeness"})
    except ValidationError as exc:
        raise FinalizeError(
            "signoff_unreadable",
            f"existing signoff {out_path} fails the Signoff schema; refusing to "
            f"finalize: {exc}",
        ) from exc

    if data.get("task_id") != plan_id:
        raise FinalizeError(
            "signoff_wrong_plan",
            f"existing signoff {out_path} is for plan {data.get('task_id')!r}, "
            f"not {plan_id!r}; refusing to finalize.",
        )

    if data.get("signoff") is not True or data.get("next_action") != "merge":
        raise FinalizeError(
            "signoff_not_success",
            f"existing signoff {out_path} is not a success signoff "
            f"(signoff={data.get('signoff')!r}, next_action={data.get('next_action')!r}); "
            f"refusing to finalize.",
        )

    stale_reason: str | None = None
    if data.get("iteration") != iteration:
        stale_reason = (
            f"signoff iteration {data.get('iteration')!r} != signed_off auditor "
            f"envelope iteration {iteration}"
        )
    elif auditor_path is None or not _signoff_lists_audit(
        list(data.get("audits") or []), auditor_path, plan_dir
    ):
        stale_reason = (
            f"signoff audits {data.get('audits')!r} do not include the signed_off "
            f"auditor envelope {auditor_path}"
        )
    else:
        try:
            envelope = json.loads(auditor_path.read_text())
        except (OSError, json.JSONDecodeError):
            envelope = {}
        completed = _parse_iso(envelope.get("completed_at") if isinstance(envelope, dict) else None)
        decided = _parse_iso(data.get("decided_at"))
        if completed is not None and decided is not None:
            if decided < completed.replace(microsecond=0):
                stale_reason = (
                    f"signoff decided_at {data.get('decided_at')} predates the "
                    f"signed_off auditor envelope completed_at {envelope.get('completed_at')}"
                )
    if stale_reason is not None:
        raise FinalizeError(
            "signoff_stale",
            f"existing signoff {out_path} is stale: {stale_reason}; refusing to finalize.",
        )

    if child_charter is not None:
        side_car = signoff_writer.charter_compliance_path(plan_dir, plan_id)
        problem: str | None = None
        compliance: Any = None
        if not side_car.is_file():
            problem = "side-car is missing"
        else:
            try:
                compliance = json.loads(side_car.read_text())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                problem = f"side-car is unparseable ({exc})"
        if problem is None and not isinstance(compliance, dict):
            problem = "side-car is not a JSON object"
        if problem is None:
            satisfied = compliance.get("compliance_checks_satisfied")
            required = list(getattr(commit_policy, "requires", None) or [])
            expected_mode = getattr(commit_policy, "mode", None)
            if compliance.get("task_id") != plan_id:
                problem = f"side-car task_id {compliance.get('task_id')!r} != {plan_id!r}"
            elif compliance.get("return_condition_status") not in _RETURN_CONDITION_STATUSES:
                problem = (
                    f"side-car return_condition_status "
                    f"{compliance.get('return_condition_status')!r} is not a recorded result"
                )
            elif expected_mode is not None and compliance.get("commit_policy_mode") != expected_mode:
                problem = (
                    f"side-car commit_policy_mode {compliance.get('commit_policy_mode')!r} "
                    f"!= plan commit_policy.mode {expected_mode!r}"
                )
            elif not isinstance(satisfied, list) or not set(required) <= set(satisfied):
                problem = (
                    f"side-car compliance_checks_satisfied {satisfied!r} does not "
                    f"cover commit_policy.requires {required!r}"
                )
        if problem is not None:
            raise FinalizeError(
                "child_signoff_missing",
                f"plan {plan_id} declares a child_charter but its required child "
                f"charter-compliance signoff ({side_car}) is not passing: {problem}; "
                f"refusing to finalize.",
            )


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
    auditor_path = _latest_auditor_path(audit_paths)

    # DP-003 — a child plan's signoff (repaired or existing) must carry the
    # same charter compliance as the supervisor path. Load once for both.
    child_charter, commit_policy, orchestration = _load_charter_context(plan_dir, plan_id)

    # Step 4 — repair signoff envelope only if missing (the pre_merge pause
    # skipped _emit_volley_terminal). Never clobber an existing one, but never
    # trust it blindly either: an existing envelope must validate against the
    # selected signed_off audit envelope before anything is flipped.
    out_path = signoff_writer.signoff_path(plan_dir, plan_id)
    signoff_repaired = False
    if out_path.is_file():
        _validate_existing_signoff(
            out_path,
            plan_dir=plan_dir,
            plan_id=plan_id,
            iteration=iteration,
            auditor_path=auditor_path,
            child_charter=child_charter,
            commit_policy=commit_policy,
        )
    else:
        # A violation refuses finalization (no signoff, no passes flip)
        # instead of writing an unchecked one.
        try:
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
                child_charter=child_charter,
                commit_policy=commit_policy,
                orchestration=orchestration,
            )
        except nested_orchestration.ChildCharterViolation as exc:
            raise FinalizeError(
                "child_charter_violation",
                f"child charter compliance failed for {plan_id}; refusing to "
                f"repair the signoff or flip passes: {exc}",
            ) from exc
        signoff_repaired = True

    # Step 5 — flip only this feature, idempotently. The PRIMARY evidence ref
    # (AC9) is the signed_off auditor envelope that authorized the flip; the
    # repaired/existing signoff envelope is recorded alongside it.
    memo_rel = signoff_writer._audit_relpath(out_path, plan_dir)
    extra_refs: list[dict[str, Any]] = []
    if auditor_path is not None:
        extra_refs.append(
            {
                "type": "file",
                "uri": signoff_writer._audit_relpath(auditor_path, plan_dir),
                "note": (
                    f"signed_off auditor envelope ({auditor}, iteration {iteration}) "
                    f"that authorized the no-paid finalize"
                ),
            }
        )
    _features_json, flipped = closeout._flip_feature_passes(
        plan_dir,
        feature_id,
        reason_class=FINALIZE_REASON,
        memo_relpath=memo_rel,
        extra_refs=extra_refs,
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
