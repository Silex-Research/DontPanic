"""F008 Item 4 — signoff.json closeout writer.

When dispatch_volley reaches a terminal state (signed_off, blocked,
stopped_quota, stopped_no_progress, stopped_max_iterations, paused_on_gate),
this module aggregates the per-iteration audit JSONs into a single closeout
artifact at <plan_dir>/audit/signoff-<task_id>.json that validates against
agent-conventions Signoff schema.

Per the F008 AC, signoff.json is required on signed_off; for non-signoff
terminal states the writer can still produce a record (with signoff=false
and an appropriate next_action) so operators get a single artifact summary
of the volley regardless of outcome.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .agent_conventions.schemas.v1_0.models.signoff_model import Signoff  # noqa: E402
from pydantic import ValidationError  # noqa: E402

VALID_TIERS = {"trivial", "local", "cross-cutting", "architectural", "p0"}


class SignoffWriteError(RuntimeError):
    pass


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_action_for(volley_status: str, signed_off: bool) -> str:
    if signed_off:
        return "merge"
    if volley_status == "blocked":
        return "blocked_awaiting_human"
    if volley_status == "paused_on_gate":
        return "blocked_awaiting_human"
    # Plan 2026-05-12-001 v4 F002 — auditor returned verdict=blocked with
    # an empty findings list. Operator must inspect manually; we don't
    # auto-promote to environmental because there's no advisory signal.
    if volley_status == "blocked_no_findings":
        return "blocked_awaiting_human"
    # supervisor.dispatch_volley emits "stopped_cap" when iteration cap is
    # reached; the legacy "stopped_max_iterations" alias is kept for callers
    # that may emit it directly.
    if volley_status in {
        "stopped_quota",
        "stopped_cap",
        "stopped_max_iterations",
        "stopped_no_progress",
        "stopped_budget",
        "stopped_wall_clock",
        "stopped_diminishing_returns",
        "stopped_convergence_collapse",
        # Plan 2026-05-09-002 F003 — env-only first-round short-circuit.
        # Operator runs the cited verification locally on a host with the
        # missing capability, attaches evidence, then approves the breaker.
        "stopped_environmental_blocker",
    }:
        return "remediate"
    if volley_status == "stopped_global_breaker":
        # Global circuit breaker is hard stop; operator can't approve, must
        # wait. Closeout marks blocked_awaiting_human + signoff=false.
        return "blocked_awaiting_human"
    return "defer"


def _audit_relpath(audit_path: Path, plan_dir: Path) -> str:
    """Render audit path relative to plan_dir if possible, else absolute."""
    try:
        return str(audit_path.relative_to(plan_dir))
    except ValueError:
        return str(audit_path)


def _summarize_votes(audit_paths: list[Path]) -> dict[str, int]:
    counts = {
        "signed_off_count": 0,
        "needs_changes_count": 0,
        "blocked_count": 0,
        "inconclusive_count": 0,
    }
    for ap in audit_paths:
        try:
            data = json.loads(ap.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        status = data.get("audit_status")
        key = f"{status}_count" if status else None
        if key in counts:
            counts[key] += 1
    return counts


def _quota_totals(audit_paths: list[Path]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for ap in audit_paths:
        try:
            data = json.loads(ap.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        agent = data.get("agent")
        qc = data.get("quota_consumed") or {}
        pct = qc.get("percent_weekly")
        if agent and isinstance(pct, (int, float)):
            key = f"{agent}_percent"
            totals[key] = max(totals.get(key, 0.0), float(pct))
    # Filter to fields the schema knows about (claude_percent / codex_percent /
    # gemini_percent only; grok_calls counted separately).
    keep = {
        k: v
        for k, v in totals.items()
        if k in {"claude_percent", "codex_percent", "gemini_percent"}
    }
    return keep


def build_signoff_dict(
    *,
    plan_id: str,
    tier: str,
    iteration: int,
    agents_in_panel: list[str],
    audit_paths: list[Path],
    plan_dir: Path,
    volley_status: str,
    signoff_reason: str | None = None,
    patch_completeness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not audit_paths:
        raise SignoffWriteError("cannot write signoff: no audit paths")
    if tier not in VALID_TIERS:
        raise SignoffWriteError(f"tier {tier!r} not in {sorted(VALID_TIERS)}")
    signed_off = volley_status == "signed_off"
    audits_rel = [_audit_relpath(p, plan_dir) for p in audit_paths]

    payload: dict[str, Any] = {
        "task_id": plan_id,
        "signoff_id": f"{plan_id}#signoff#{iteration}",
        "iteration": iteration,
        "tier": tier,
        "agents_in_panel": list(agents_in_panel),
        "audits": audits_rel,
        "vote_summary": _summarize_votes(audit_paths),
        "signoff": signed_off,
        "signoff_reason": signoff_reason
        or (f"volley_status={volley_status}; final iteration={iteration}"),
        "next_action": _next_action_for(volley_status, signed_off),
        "decided_at": _now_iso(),
    }
    quota = _quota_totals(audit_paths)
    if quota:
        payload["quota_consumed_total"] = quota

    # Strict validation — surfaces drift between code + schema early.
    # Plan 2026-05-01-004 F003: ``patch_completeness`` is recorded in
    # signoff.json as a sibling key, but the canonical agent-conventions
    # Signoff schema is NOT bumped here (D004 defers v1.4.0). We validate
    # the payload WITHOUT the extra block, then attach it post-validation.
    # This satisfies acceptance #11's "validator-level acceptance only".
    try:
        Signoff.model_validate(payload)
    except ValidationError as exc:
        raise SignoffWriteError(f"signoff payload failed validation: {exc}") from exc
    if patch_completeness is not None:
        payload["patch_completeness"] = patch_completeness
    # DPN-011 — bind the signoff to the exact bytes of every envelope it
    # lists (same post-validation sibling-key pattern as patch_completeness;
    # the vendored Signoff schema is unchanged). An in-place overwrite of a
    # listed ``-iN`` envelope changes its digest even within the same second.
    payload["audit_digests"] = _audit_digests(audit_paths, audits_rel)
    return payload


def _audit_digest(path: Path) -> str:
    """``"sha256:<hex>"`` of ``path``'s bytes."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _audit_digests(audit_paths: list[Path], audits_rel: list[str]) -> dict[str, str]:
    """Map each ``audits`` entry to the sha256 digest of its file's bytes at
    signoff time. An unreadable file gets no entry (a consumer that requires
    the entry then fails closed)."""
    digests: dict[str, str] = {}
    for path, rel in zip(audit_paths, audits_rel, strict=True):
        try:
            digests[rel] = _audit_digest(path)
        except OSError:
            continue
    return digests


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    """Write ``obj`` as JSON to ``path`` atomically: a same-directory temp file
    is fully written then ``os.replace``d over the target, so readers never
    see a torn file. The temp file is removed if any step fails; the original
    error (e.g. ``IsADirectoryError`` when a directory occupies ``path``)
    propagates unchanged."""
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Byte-exact atomic restore helper (temp + ``os.replace``) used only by
    :func:`_commit_signoff_pair` rollback."""
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def _read_bytes_if_file(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _restore(path: Path, previous: bytes | None) -> None:
    """Put ``path`` back to ``previous`` (``None`` = absent). Never raises; a
    failed restore of a file falls back to removing it so no half-state
    survives."""
    try:
        if previous is None:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        else:
            _atomic_write_bytes(path, previous)
    except OSError:
        with contextlib.suppress(OSError):
            path.unlink()


def _commit_signoff_pair(
    out: Path,
    payload: dict[str, Any],
    side_car: Path | None,
    compliance: dict[str, Any] | None,
) -> None:
    """Write the signoff (and, for child plans, its compliance side-car) as one
    all-or-nothing transaction (DP-003 + Sentinel 5870049314 HIGH-3).

    Order: snapshot the previous signoff/side-car bytes, RETIRE the previous
    signoff (unlink) so it can never be read as the new one, write the
    side-car, then write the signoff LAST — each atomically (temp +
    ``os.replace``). If any step fails, roll back to the exact previous pair
    (or to absence when there was none) and re-raise the original error.

    Outcomes therefore are exactly: the new signoff + its bound side-car, or
    the previous state unchanged. Never a valid-looking new signoff without
    its side-car, never a new side-car paired with the old signoff, never a
    torn file. If a rollback restore itself fails, that file is removed
    (absence is never treated as success by any consumer)."""
    prev_signoff = _read_bytes_if_file(out)
    prev_side_car = _read_bytes_if_file(side_car) if side_car is not None else None
    try:
        if prev_signoff is not None:
            out.unlink()
        if side_car is not None and compliance is not None:
            _atomic_write_json(side_car, compliance)
        _atomic_write_json(out, payload)
    except BaseException:
        if side_car is not None:
            _restore(side_car, prev_side_car)
        _restore(out, prev_signoff)
        raise


def signoff_path(plan_dir: Path, plan_id: str) -> Path:
    return plan_dir / "audit" / f"signoff-{plan_id}.json"


def charter_compliance_path(plan_dir: Path, plan_id: str) -> Path:
    """Plan 2026-05-02-003 F002: side-car compliance file path. Lives next
    to the signoff envelope so operators see both artifacts together."""
    return plan_dir / "audit" / f"charter-compliance-{plan_id}.json"


def write_signoff(
    *,
    plan_id: str,
    tier: str,
    iteration: int,
    agents_in_panel: list[str],
    audit_paths: list[Path],
    plan_dir: Path,
    volley_status: str,
    signoff_reason: str | None = None,
    child_charter: Any = None,
    commit_policy: Any = None,
    modified_files: list[str] | None = None,
    orchestration: Any = None,
    patch_completeness: dict[str, Any] | None = None,
) -> Path:
    """Build, validate, and write the signoff.json closeout. Returns the path.

    Plan 2026-05-02-003 F002: when both ``child_charter`` and ``commit_policy``
    are passed, runs ``check_child_charter_compliance`` BEFORE persisting any
    artifact. On ``ChildCharterViolation`` neither the signoff envelope nor
    the side-car compliance file is written (no-partial-artifact, mirrors
    plan 005 F002 acceptance #5). On compliance pass, writes the side-car
    file at ``audit/charter-compliance-{plan_id}.json`` recording the parsed
    return-condition status + satisfied requires items.

    The Signoff schema (agent-conventions v1.0) is unchanged — compliance
    output lives in the side-car, matching F001's pop-orchestration-block
    schema-discipline pattern (D006-style).
    """
    payload = build_signoff_dict(
        plan_id=plan_id,
        tier=tier,
        iteration=iteration,
        agents_in_panel=agents_in_panel,
        audit_paths=audit_paths,
        plan_dir=plan_dir,
        volley_status=volley_status,
        signoff_reason=signoff_reason,
        patch_completeness=patch_completeness,
    )

    compliance: dict[str, Any] | None = None
    if child_charter is not None and commit_policy is not None:
        # Late import to avoid a load-time cycle (nested_orchestration imports
        # nothing from signoff_writer, but plan_loader imports both).
        from dontpanic_orchestrate.nested_orchestration import (
            check_child_charter_compliance,
        )

        compliance = check_child_charter_compliance(
            plan_dir=plan_dir,
            child_charter=child_charter,
            commit_policy=commit_policy,
            signoff_data=payload,
            modified_files=modified_files,
        )

    out = signoff_path(plan_dir, plan_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    _commit_signoff_pair(
        out,
        payload,
        charter_compliance_path(plan_dir, plan_id) if compliance is not None else None,
        compliance,
    )

    # Plan 2026-05-02-003 F003: when this signoff is for a child plan,
    # record a best-effort volley.return_to_parent trace on the child's
    # events.jsonl. Parent reads its own trace + the child's compliance
    # side-car when operator invokes `approve pre_resume_after_child`.
    # NEVER raises (D006 — events.jsonl is best-effort).
    if orchestration is not None and getattr(orchestration, "parent_plan_id", None):
        from dontpanic_orchestrate.nested_orchestration import record_event

        return_status = compliance.get("return_condition_status") if compliance else None
        record_event(
            plan_dir,
            kind="volley.return_to_parent",
            payload={
                "child_plan_id": plan_id,
                "parent_plan_id": orchestration.parent_plan_id,
                "child_final_status": volley_status,
                "return_condition_status": return_status,
            },
            plan_id=plan_id,
        )

    return out


__all__ = [
    "SignoffWriteError",
    "VALID_TIERS",
    "build_signoff_dict",
    "charter_compliance_path",
    "signoff_path",
    "write_signoff",
]
