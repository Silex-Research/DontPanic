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
  - ``plan_unloadable``     — the plan cannot be loaded, so charter
    compliance cannot be checked (fails closed; no writes).
  - ``child_charter_violation`` — child plan whose charter compliance fails
    on repair.
  - ``signoff_unreadable`` / ``signoff_wrong_plan`` / ``signoff_not_success`` /
    ``signoff_stale`` / ``child_signoff_missing`` / ``child_signoff_stale`` —
    an EXISTING signoff envelope (or its required child compliance side-car) is
    not a durable successful signoff for this verdict; see
    :func:`_validate_existing_signoff`.
  - ``child_not_satisfied`` — a child plan whose recorded return condition is
    ``blocked``, or ``superseded`` without a satisfied successor.

``REFUSAL_EXIT_CODES`` maps every refusal code to a distinct, stable
``dontpanic finalize`` exit code.

Idempotent: re-running on an already-flipped feature is a no-op success.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

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


# Stable, documented ``dontpanic finalize`` exit code per refusal code (each
# distinct). 0 = success, 2 = usage, 6 = plan drift (CLI-level refusal before
# the finalizer runs) are reserved and never reused here.
REFUSAL_EXIT_CODES: dict[str, int] = {
    "not_signed_off": 3,
    "pre_merge_uncleared": 4,
    "no_audit": 5,
    "plan_unloadable": 7,
    "child_charter_violation": 8,
    "signoff_unreadable": 9,
    "signoff_wrong_plan": 10,
    "signoff_not_success": 11,
    "signoff_stale": 12,
    "child_signoff_missing": 13,
    "child_signoff_stale": 14,
    "child_not_satisfied": 15,
}
# Fallback for an unmapped code (should never happen; covered by a test).
UNKNOWN_REFUSAL_EXIT_CODE = 1


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

    Fails closed (Sentinel r3b / F4): if the plan cannot be loaded, its charter
    compliance cannot be verified, so finalization is refused with
    ``plan_unloadable`` — no signoff write, no ``passes`` flip. There is no
    text-sniffing fallback: an unloadable plan is never treated as a legacy
    top-level plan."""
    try:
        loaded = plan_loader.load(plan_dir)
    except Exception as exc:  # noqa: BLE001 — any load failure refuses
        raise FinalizeError(
            "plan_unloadable",
            f"plan {plan_id} could not be loaded ({type(exc).__name__}: {exc}); "
            f"its charter compliance cannot be checked, refusing to finalize.",
        ) from exc
    return loaded.child_charter, loaded.commit_policy, loaded.orchestration


def _parse_iso(value: Any) -> dt.datetime | None:
    """Parse an ISO-8601 timestamp that carries an explicit UTC offset or
    ``Z``. Returns None (unparseable) for anything else — including a naive
    date-time and a date-only value — so a zone-less timestamp is never
    silently read as UTC (the audit/signoff schemas require aware values)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _freshness_problem(
    envelope: dict[str, Any], signoff: dict[str, Any], auditor_path: Path | None
) -> str | None:
    """The single freshness rule shared by the ordinary finalizer
    (:func:`_validate_existing_signoff`) and the successor path
    (:func:`_successor_signoff_is_current`). Returns a human-readable reason
    when ``signoff`` is not at least as new as ``envelope``, else None:

      * the envelope's ``completed_at`` is missing / unparseable / zone-less;
      * the signoff's ``decided_at`` is missing / unparseable / zone-less;
      * ``decided_at`` is earlier than ``completed_at`` (second granularity).

    Sentinel 5870049314 HIGH-2 — freshness is never skipped: a missing or
    unparseable timestamp on either side means freshness cannot be proven
    (fail closed)."""
    completed = _parse_iso(envelope.get("completed_at"))
    decided = _parse_iso(signoff.get("decided_at"))
    if completed is None:
        return (
            f"signed_off auditor envelope {auditor_path} has a missing or "
            f"unparseable completed_at ({envelope.get('completed_at')!r}); "
            f"signoff freshness cannot be verified"
        )
    if decided is None:
        return (
            f"signoff decided_at {signoff.get('decided_at')!r} is missing or "
            f"unparseable; signoff freshness cannot be verified"
        )
    if decided < completed.replace(microsecond=0):
        return (
            f"signoff decided_at {signoff.get('decided_at')} predates the "
            f"signed_off auditor envelope completed_at {envelope.get('completed_at')}"
        )
    return None


# Post-validation sibling keys the signoff writer attaches outside the
# vendored Signoff schema (ignored for the schema check only).
_SIGNOFF_SIBLING_KEYS = frozenset({"patch_completeness", "audit_digests"})


def _listed_entries(audits: list[Any], auditor_path: Path, plan_dir: Path) -> list[str]:
    """The signoff ``audits`` entries (plan-relative or absolute) that
    resolve to ``auditor_path``."""
    target = auditor_path.resolve()
    found: list[str] = []
    for entry in audits:
        if not isinstance(entry, str) or not entry:
            continue
        p = Path(entry)
        if not p.is_absolute():
            p = plan_dir / p
        if p.resolve() == target:
            found.append(entry)
    return found


def _signoff_lists_audit(audits: list[Any], auditor_path: Path, plan_dir: Path) -> bool:
    """True when one of the signoff's ``audits`` entries (plan-relative or
    absolute) resolves to ``auditor_path``."""
    return bool(_listed_entries(audits, auditor_path, plan_dir))


def _validate_existing_signoff(
    out_path: Path,
    *,
    plan_dir: Path,
    plan_id: str,
    iteration: int,
    auditor_path: Path | None,
    child_charter: Any,
    commit_policy: Any,
    parent_plan_id: str | None = None,
) -> None:
    """Refuse (``FinalizeError``) unless the existing signoff envelope is a
    durable, successful signoff for THIS plan and THIS signed_off verdict.

    Read-only: never writes. Checks, in order (each a distinct stable code):

      * ``signoff_unreadable``  — empty, torn/unparseable JSON, not an object,
        or fails the agent-conventions ``Signoff`` schema (the post-validation
        ``patch_completeness`` / ``audit_digests`` sibling keys are ignored for
        the schema check).
      * ``signoff_wrong_plan``  — ``task_id`` != the plan being finalized.
      * ``signoff_not_success`` — ``signoff`` is not ``true`` or
        ``next_action`` != ``merge`` (a non-success terminal record).
      * ``signoff_stale``       — the signoff does not correspond to the
        signed_off auditor envelope this finalizer selected. Stale means ANY of:
          - ``signoff.iteration`` != the selected envelope's ``iteration``;
          - the selected auditor envelope is not listed in ``signoff.audits``;
          - the envelope's ``completed_at`` or the signoff's ``decided_at`` is
            missing, unparseable or zone-less (freshness unverifiable — fail
            closed);
          - ``signoff.decided_at`` is earlier than the envelope's
            ``completed_at`` (second granularity) — the signoff predates the
            verdict, e.g. a re-dispatch rewrote the same ``-iN`` filename.
      * ``child_signoff_missing`` — the plan declares a ``child_charter`` and
        the charter-compliance side-car written by ``signoff_writer`` is
        missing, unreadable, for another plan, has an unknown
        ``return_condition_status``, records a different commit-policy mode,
        or does not list every ``commit_policy.requires`` item as satisfied.
      * ``child_signoff_stale`` — the side-car is not bound to THIS signoff,
        selected audit and current charter (see
        :func:`_side_car_binding_problem`).
      * ``child_not_satisfied`` — the bound side-car records ``blocked``, or
        ``superseded`` with no satisfied successor (see
        :func:`_require_child_satisfied`).
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
        Signoff.model_validate({k: v for k, v in data.items() if k not in _SIGNOFF_SIBLING_KEYS})
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
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            envelope = {}
        if not isinstance(envelope, dict):
            envelope = {}
        stale_reason = _freshness_problem(envelope, data, auditor_path)
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

        binding_problem = _side_car_binding_problem(
            compliance,
            signoff=data,
            iteration=iteration,
            auditor_path=auditor_path,
            plan_dir=plan_dir,
            child_charter=child_charter,
            commit_policy=commit_policy,
        )
        if binding_problem is not None:
            raise FinalizeError(
                "child_signoff_stale",
                f"plan {plan_id} charter-compliance side-car ({side_car}) is not "
                f"bound to this signoff: {binding_problem}; refusing to finalize.",
            )

        _require_child_satisfied(
            plan_dir,
            plan_id=plan_id,
            status=compliance.get("return_condition_status"),
            child_charter=child_charter,
            parent_plan_id=parent_plan_id,
        )


def _side_car_binding_problem(
    compliance: dict[str, Any],
    *,
    signoff: dict[str, Any],
    iteration: int,
    auditor_path: Path | None,
    plan_dir: Path,
    child_charter: Any,
    commit_policy: Any,
) -> str | None:
    """Sentinel 5870049314 HIGH-1 — side-car binding rule.

    A charter-compliance side-car authorizes a child signoff ONLY when it was
    computed for exactly that signoff, the selected verdict, and the charter
    in force now. ALL of the following must hold (else the side-car is stale
    and finalization is refused with ``child_signoff_stale``):

      * ``side_car.iteration``  == the selected signed_off envelope's iteration
        (== ``signoff.iteration``, already enforced upstream);
      * ``side_car.signoff_id`` == ``signoff.signoff_id``;
      * ``side_car.audits`` lists the selected signed_off auditor envelope;
      * ``side_car.charter_digest`` == :func:`nested_orchestration.charter_digest`
        of the plan's CURRENT ``child_charter`` + ``commit_policy``.

    Side-cars predating these fields carry no binding and are refused (fail
    closed). Returns a human-readable problem, or None when bound."""
    side_iter = compliance.get("iteration")
    if isinstance(side_iter, bool) or side_iter != iteration:
        return f"side-car iteration {side_iter!r} != signed_off iteration {iteration}"
    if compliance.get("signoff_id") != signoff.get("signoff_id"):
        return (
            f"side-car signoff_id {compliance.get('signoff_id')!r} != signoff "
            f"signoff_id {signoff.get('signoff_id')!r}"
        )
    side_audits = compliance.get("audits")
    if (
        auditor_path is None
        or not isinstance(side_audits, list)
        or not _signoff_lists_audit(side_audits, auditor_path, plan_dir)
    ):
        return (
            f"side-car audits {side_audits!r} do not include the selected signed_off "
            f"auditor envelope {auditor_path}"
        )
    if child_charter is None or commit_policy is None:
        return "plan charter/commit_policy unavailable; cannot verify charter_digest"
    expected = nested_orchestration.charter_digest(child_charter, commit_policy)
    if compliance.get("charter_digest") != expected:
        return (
            f"side-car charter_digest {compliance.get('charter_digest')!r} != current "
            f"charter digest {expected!r} (charter changed since the side-car was written)"
        )
    return None


def _frontmatter(plan_dir: Path) -> dict[str, Any] | None:
    plan_md = plan_dir / "plan.md"
    try:
        text = plan_md.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    parts = text.split("---", 2)
    if not text.startswith("---") or len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def _is_satisfied_successor(sibling_dir: Path, *, parent_plan_id: str, acceptance_item: str) -> bool:
    """True when ``sibling_dir`` is a child plan of the same parent for the same
    ``parent_acceptance_item`` whose CURRENT success signoff carries a bound
    side-car recording ``return_condition_status: satisfied``. Read-only;
    any unreadable/malformed artifact means "not a successor"."""
    fm = _frontmatter(sibling_dir)
    if fm is None:
        return False
    orch = fm.get("orchestration")
    charter_block = fm.get("child_charter")
    sib_id = fm.get("id")
    if not isinstance(orch, dict) or not isinstance(charter_block, dict) or not isinstance(sib_id, str):
        return False
    if orch.get("parent_plan_id") != parent_plan_id:
        return False
    if charter_block.get("parent_acceptance_item") != acceptance_item:
        return False
    try:
        sib_charter = nested_orchestration.ChildCharter.model_validate(charter_block)
        sib_policy = nested_orchestration.CommitPolicy.model_validate(fm.get("commit_policy") or {})
        signoff = json.loads(signoff_writer.signoff_path(sibling_dir, sib_id).read_text())
        side = json.loads(signoff_writer.charter_compliance_path(sibling_dir, sib_id).read_text())
    except Exception:  # noqa: BLE001 — any unreadable artifact disqualifies
        return False
    if not isinstance(signoff, dict) or not isinstance(side, dict):
        return False
    return (
        signoff.get("task_id") == sib_id
        and signoff.get("signoff") is True
        and signoff.get("next_action") == "merge"
        and side.get("task_id") == sib_id
        and side.get("return_condition_status") == "satisfied"
        and side.get("iteration") == signoff.get("iteration")
        and side.get("signoff_id") == signoff.get("signoff_id")
        and side.get("charter_digest") == nested_orchestration.charter_digest(sib_charter, sib_policy)
        and _successor_signoff_is_current(sibling_dir, signoff)
    )


class _NoLatestAuditor(Exception):
    """A feature's latest auditor envelope cannot be determined (an auditor
    envelope that cannot be read, is not valid UTF-8, is not valid JSON or is
    not a JSON object; one with a missing/unparseable/zone-less
    ``completed_at``; or two different envelopes sharing the newest
    ``completed_at`` second)."""


def _utc_second(t: dt.datetime) -> dt.datetime:
    return t.astimezone(dt.timezone.utc).replace(microsecond=0)


def _latest_auditor_by_completed_at(audit_paths: list[Path]) -> tuple[Path, dict[str, Any]] | None:
    """The latest auditor envelope among ``audit_paths`` and its parsed JSON,
    ranked by the envelope's own ``completed_at`` (:func:`_parse_iso`), then
    the iteration index from the file name, then the file name — highest
    wins. File timestamps (mtime) are never consulted, so a touch, same-bytes
    rewrite, copy, clone or branch switch cannot reorder envelopes, and a
    redispatch that reuses an ``-iN`` filename is ordered by when the verdict
    was actually made. Returns None when there is no auditor envelope.

    Raises :class:`_NoLatestAuditor` (fail closed) when ANY auditor envelope
    cannot be read (``OSError``), is not valid UTF-8 (decoded explicitly as
    UTF-8, never the platform locale encoding), is not valid JSON (e.g. a torn
    or truncated in-place write) or is not a JSON object — that envelope may
    be the latest verdict, so the latest verdict is unknown and such files are
    NEVER skipped; when ANY auditor envelope has a missing or unparseable
    ``completed_at``; or when the highest ``completed_at`` (whole second,
    UTC) is shared by two or more DIFFERENT auditor envelope paths — the
    latest verdict is then ambiguous, so iteration / name never break a tie at
    the newest second (ties among older envelopes are harmless). Used only by
    :func:`_successor_signoff_is_current`."""
    best: tuple[Path, dict[str, Any]] | None = None
    best_key: tuple[dt.datetime, int, str] | None = None
    at_second: dict[dt.datetime, set[Path]] = {}
    for path in audit_paths:
        if "auditor" not in path.name:
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise _NoLatestAuditor(f"{path} cannot be read: {exc}") from exc
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _NoLatestAuditor(f"{path} is not valid UTF-8: {exc}") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _NoLatestAuditor(f"{path} is not valid JSON (torn/truncated?): {exc}") from exc
        if not isinstance(data, dict):
            raise _NoLatestAuditor(f"{path} is not a JSON object ({type(data).__name__})")
        completed = _parse_iso(data.get("completed_at"))
        if completed is None:
            raise _NoLatestAuditor(f"{path} has a missing or unparseable completed_at")
        at_second.setdefault(_utc_second(completed), set()).add(path.resolve())
        key = (completed, closeout._auditor_iteration_of(path), path.name)
        if best_key is None or key > best_key:
            best_key = key
            best = (path, data)
    if at_second:
        newest = max(at_second)
        if len(at_second[newest]) > 1:
            raise _NoLatestAuditor(
                f"{len(at_second[newest])} auditor envelopes share the newest "
                f"completed_at second {newest.isoformat()}; latest is ambiguous"
            )
    return best


def _digest_binds(signoff: dict[str, Any], entries: list[str], path: Path) -> bool:
    """True when the signoff's ``audit_digests`` records, for every
    ``audits`` entry in ``entries`` (at least one), the sha256 of ``path``'s
    CURRENT bytes. Missing ``audit_digests``, a missing entry, a malformed
    value, an unreadable file or a mismatch → False (fail closed)."""
    digests = signoff.get("audit_digests")
    if not isinstance(digests, dict) or not entries:
        return False
    try:
        current = signoff_writer._audit_digest(path)
    except OSError:
        return False
    return all(isinstance(digests.get(e), str) and digests.get(e) == current for e in entries)


def _successor_feature_ids(sibling_dir: Path) -> list[str] | None:
    """Every feature id in the successor's ``features.json``; None when it is
    missing/unreadable/malformed or lists no features."""
    try:
        data = json.loads((sibling_dir / "features.json").read_text())
    except Exception:  # noqa: BLE001 — unreadable features.json disqualifies
        return None
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list) or not features:
        return None
    ids: list[str] = []
    for f in features:
        fid = f.get("id") if isinstance(f, dict) else None
        if not isinstance(fid, str) or not fid:
            return None
        ids.append(fid)
    return ids


def _successor_signoff_is_current(sibling_dir: Path, signoff: dict[str, Any]) -> bool:
    """True when the successor's success signoff is still backed by current
    auditor verdicts. Volleys run per feature and each volley's signoff lists
    only its OWN feature's envelopes, so:

      * for EVERY feature in the successor's ``features.json``, that feature's
        latest auditor envelope must exist and be ``signed_off``;
      * the signoff's own feature(s) — the feature(s) with an auditor envelope
        listed in the signoff's ``audits`` (at least one, else not a
        successor) — must each have their LATEST auditor envelope listed, and
        that envelope's ``iteration`` must equal the signoff's ``iteration``.

    For each own feature's latest (listed) envelope the signoff must also be
    FRESH (:func:`_freshness_problem` — the same rule as the ordinary
    finalizer: ``decided_at`` not earlier than ``completed_at``, both present,
    parseable and zone-aware) and DIGEST-BOUND (:func:`_digest_binds` — its
    ``audit_digests`` entry for that listed path equals the sha256 of the
    file's current bytes, so an in-place overwrite of the same ``-iN`` path is
    caught even within the same second; a legacy signoff without
    ``audit_digests`` is not a successor).

    "Latest" is ranked by the envelope's ``completed_at``, then iteration
    index, then file name (:func:`_latest_auditor_by_completed_at`); file
    timestamps are never used, a missing/unparseable/zone-less
    ``completed_at`` on any auditor envelope disqualifies, an auditor
    envelope that cannot be read, is not valid UTF-8, is not valid JSON
    (torn/truncated) or is not a JSON object disqualifies (it is never
    skipped — it may be the latest verdict), and a tie at the
    newest ``completed_at`` second disqualifies. A later blocked / needs_changes audit
    for ANY feature (e.g. after the writer refused a blocked rewrite and left
    the old pair on disk), or a feature with no auditor envelope, therefore
    disqualifies the successor. Read-only; fails closed."""
    audits = signoff.get("audits")
    iteration = signoff.get("iteration")
    if not isinstance(audits, list) or not isinstance(iteration, int) or isinstance(iteration, bool):
        return False
    feature_ids = _successor_feature_ids(sibling_dir)
    if feature_ids is None:
        return False
    own_features = 0
    for fid in feature_ids:
        try:
            paths = closeout._audit_paths_for_feature(sibling_dir, fid)
            latest = _latest_auditor_by_completed_at(paths)
            listed_any = any(
                "auditor" in p.name and _signoff_lists_audit(audits, p, sibling_dir) for p in paths
            )
        except Exception:  # noqa: BLE001 — missing/unreadable/undatable audit disqualifies
            return False
        if latest is None:
            return False
        latest_path, envelope = latest
        if _verdict_of(envelope) != SIGNED_OFF_VERDICT:
            return False
        if not listed_any:
            continue
        own_features += 1
        entries = _listed_entries(audits, latest_path, sibling_dir)
        if not entries:
            return False
        env_iter = envelope.get("iteration")
        if isinstance(env_iter, bool) or env_iter != iteration:
            return False
        if _freshness_problem(envelope, signoff, latest_path) is not None:
            return False
        if not _digest_binds(signoff, entries, latest_path):
            return False
    return own_features > 0


def _satisfied_successor(
    plan_dir: Path, *, plan_id: str, child_charter: Any, parent_plan_id: str | None
) -> Path | None:
    """Locate a satisfied successor for a ``superseded`` child: a sibling plan
    directory (same plans root) that is a child of the same parent for the
    same ``parent_acceptance_item`` and is durably ``satisfied`` (see
    :func:`_is_satisfied_successor`). Returns its directory, or None."""
    acceptance_item = getattr(child_charter, "parent_acceptance_item", None)
    if not parent_plan_id or not isinstance(acceptance_item, str):
        return None
    plans_root = plan_dir.parent
    try:
        candidates = sorted(p for p in plans_root.iterdir() if p.is_dir())
    except OSError:
        return None
    for sibling in candidates:
        if sibling.resolve() == plan_dir.resolve() or sibling.name == plan_id:
            continue
        if _is_satisfied_successor(
            sibling, parent_plan_id=parent_plan_id, acceptance_item=acceptance_item
        ):
            return sibling
    return None


def _require_child_satisfied(
    plan_dir: Path,
    *,
    plan_id: str,
    status: Any,
    child_charter: Any,
    parent_plan_id: str | None,
) -> None:
    """Thanos guard (Sentinel 5870049314 HIGH-2): finalization of a child plan
    succeeds only when the child is satisfied. Recording is unchanged — this
    only reads the recorded ``return_condition_status``:

      * ``satisfied``  → accepted;
      * ``superseded`` → accepted only when a satisfied successor exists
        (:func:`_satisfied_successor`);
      * ``blocked`` (or anything else) → refused.

    Refusal code: ``child_not_satisfied``."""
    if status == "satisfied":
        return
    if status == "superseded":
        if _satisfied_successor(
            plan_dir, plan_id=plan_id, child_charter=child_charter, parent_plan_id=parent_plan_id
        ) is not None:
            return
        raise FinalizeError(
            "child_not_satisfied",
            f"child plan {plan_id} is superseded but no satisfied successor (a "
            f"sibling child of parent {parent_plan_id!r} for the same "
            f"parent_acceptance_item with a durable satisfied signoff) exists; "
            f"refusing to finalize.",
        )
    raise FinalizeError(
        "child_not_satisfied",
        f"child plan {plan_id} return_condition_status is {status!r}, not "
        f"'satisfied'; a {status!r} child is not success, refusing to finalize.",
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
    parent_plan_id = getattr(orchestration, "parent_plan_id", None)

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
            parent_plan_id=parent_plan_id,
        )
    else:
        # Thanos guard on the repair path: read the recorded return condition
        # (the same memo write_signoff records) BEFORE any write so a blocked /
        # unsuperseded child never gets a signoff written or passes flipped.
        # A missing/malformed memo falls through to write_signoff, which
        # raises the real ChildCharterViolation below.
        if child_charter is not None:
            try:
                recorded = nested_orchestration.parse_return_condition_section(
                    plan_dir / "evidence" / "closeout-memo.md"
                )
            except nested_orchestration.ReturnConditionError:
                recorded = None
            if recorded is not None:
                _require_child_satisfied(
                    plan_dir,
                    plan_id=plan_id,
                    status=recorded,
                    child_charter=child_charter,
                    parent_plan_id=parent_plan_id,
                )
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
    "REFUSAL_EXIT_CODES",
    "UNKNOWN_REFUSAL_EXIT_CODE",
    "FinalizeError",
    "FinalizeResult",
    "finalize_signed_off_feature",
    "SIGNED_OFF_VERDICT",
]
