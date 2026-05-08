"""Build, validate, and persist Audit JSONs.

Persisted filename pattern (plan 2026-05-02-002 F001):
``audit/{agent}-{role}-{feature_id}-i{n}.json``. ``feature_id`` is
required and validated against the agent-conventions feature-id regex
(`^F\\d{3}$`) before any disk I/O — invalid values raise ``ValueError``
and no envelope file lands. The legacy filename (``{agent}-{role}-i{n}.json``,
F005a-1) remains readable when supervisor read paths receive a Path
to it; readers consume Path objects, not filename globs.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

# Single source of truth: agent-conventions/schemas/v1.0/features.schema.json
# uses this exact regex. Changing it here requires a coordinated schema bump
# (see D002 of plan 2026-05-02-002).
_FEATURE_ID_RE = re.compile(r"^F\d{3}$")

# Resolve agent-conventions schemas dir so `from models.*` works regardless
# of which sibling module imported first. Same candidate list as
# plan_loader.py / environments_loader.py — kept inline rather than
# extracted to keep the bootstrap surface flat.
_SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[2] / ".claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[3] / "agent-conventions" / "schemas" / "v1.0",
]
for _candidate in _SCHEMA_CANDIDATES:
    if (_candidate / "models").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from models.audit_model import Audit  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from dontpanic_orchestrate import git_state  # noqa: E402
from dontpanic_orchestrate.ec5_classifier import (  # noqa: E402
    apply_ec5_classifier_to_findings,
)
from dontpanic_orchestrate.executors.base import DispatchResult  # noqa: E402
from dontpanic_orchestrate.plan_loader import LoadedPlan  # noqa: E402
from dontpanic_orchestrate.target_context_prelude import (  # noqa: E402
    TargetContextError,
    parse_prelude_block,
    render_prelude,
    resolve_repo,
    validate_target_context,
)

_LOGGER = logging.getLogger(__name__)

_PRELUDE_HEADER = "## Target context\n"


def build_audit(
    loaded: LoadedPlan,
    result: DispatchResult,
    feature_id: str,
    validation_performed: list[str],
    extra: dict[str, Any] | None = None,
    target_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose an audit dict. Validation happens in write().

    F023 EC6: when target_context is provided, embed it in the audit and
    populate target_context.commands_run by parsing `$ <cmd>` lines from
    the agent's prose summary. Supervisor performs the cross-check of
    declared env/project + forbidden-command detection post-build.

    Plan 2026-05-04-003 F002: when ``result.subprocess_result`` indicates a
    subprocess timeout, layer in diagnostic evidence WITHIN the existing
    schema (no new top-level fields, no new ``audit_status`` enum value):

    - structured timeout block prepended to ``summary``
    - timeout markers + sidecar references appended to ``validation_performed``
    - ``correctness/medium`` finding appended when timeout AND worktree
      changed (``timed_out=true AND worktree_changed=true``)
    - partial stdout/stderr written under
      ``<plan_dir>/audit/partials/<audit_id>.{stdout,stderr}.{txt,bin}``
      (referenced from ``validation_performed`` only — never inline)

    Non-timeout dispatches and successful runs are byte-stable: the
    timeout helpers no-op and ``validation_performed`` / ``summary`` /
    ``findings`` are unchanged.
    """
    audit_id = f"{loaded.plan_id}#{result.agent}#{result.iteration}"
    findings = (extra or {}).get("findings") or []
    status_hint = None
    if result.agent_role == "auditor" and result.summary:
        status_hint = _extract_status_hint(result.summary)
        if not findings:
            findings = _extract_findings(result.summary, feature_id)

    # Plan 2026-05-04-003 F002: timeout evidence layered in within existing
    # schema. All four helpers are no-ops when subprocess_result is None or
    # when the run did not time out, preserving byte-stability.
    spr = result.subprocess_result
    timeout_markers = _timeout_markers(spr)
    if timeout_markers:
        sidecar_markers = _write_partial_sidecars(loaded.plan_dir, audit_id, spr)
        validation_performed = [*validation_performed, *timeout_markers, *sidecar_markers]
        timeout_finding = _timeout_finding(spr, feature_id)
        if timeout_finding is not None:
            findings = [*findings, timeout_finding]

    audit: dict[str, Any] = {
        "task_id": loaded.plan_id,
        "audit_id": audit_id,
        "agent": result.agent,
        "agent_role": result.agent_role,
        "model_version": result.model_version,
        "iteration": result.iteration,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        # `audit_status` is derived AFTER F003 EC5 classification (below) so
        # downgrades to advisory propagate into the status decision.
        "validation_performed": validation_performed,
        "quota_consumed": {
            k: v
            for k, v in {
                "tokens_in": result.quota_consumed.get("tokens_in"),
                "tokens_out": result.quota_consumed.get("tokens_out"),
                "api_calls": 1 if result.success else 0,
            }.items()
            if v is not None
        },
        "summary": _summary(result, feature_id),
    }
    if target_context is not None:
        commands_run = list(target_context.get("commands_run") or [])
        if not commands_run and result.summary:
            commands_run = extract_commands_run(result.summary)
        audit["target_context"] = {
            "env": target_context["env"],
            "project": target_context.get("project"),
            "commands_run": commands_run,
        }

    # F003 / D005 / D008: defensively re-apply the EC5 narrow-downgrade rule
    # at finding-aggregation. `apply_ec5_classifier_to_findings` drops EC5
    # findings whose envelope is golden ('none'), downgrades 'i0' findings to
    # advisory while preserving description, and leaves 'i1' findings as
    # authored. Non-EC5 findings pass through untouched. The classifier needs
    # the envelope's `target_context` + `summary`, both already populated
    # above — that's why the call sits here, after both are set, and BEFORE
    # `_derive_status` so downgrades affect the audit_status decision.
    findings = apply_ec5_classifier_to_findings(findings, audit)
    audit["findings"] = findings
    audit["audit_status"] = _derive_status(result, findings, status_hint=status_hint)

    return {k: v for k, v in audit.items() if v is not None}


_COMMAND_LINE_RE = re.compile(r"^[ \t]*\$[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def extract_commands_run(summary: str) -> list[str]:
    """Parse `$ <cmd>` line markers from an agent's prose summary.

    Used by build_audit to populate target_context.commands_run when
    callers pass target_context without an explicit list. Convention is
    standard shell prompt prefix; agents are instructed via prompt to
    list every side-effect command this way (F023 EC5).
    """
    return [m.group(1) for m in _COMMAND_LINE_RE.finditer(summary or "")]


def _derive_status(
    result: DispatchResult,
    findings: list[dict[str, Any]],
    status_hint: str | None = None,
) -> str:
    if not result.success:
        return "blocked"
    has_critical = any(f.get("severity") in {"critical", "high"} for f in findings)
    if has_critical:
        return "needs_changes"
    if status_hint in {"needs_changes", "blocked", "inconclusive", "redaction_required"}:
        return status_hint
    return "signed_off"


def _extract_status_hint(summary: str) -> str | None:
    """Best-effort status parser for auditor prose."""
    text = summary.lower().replace("-", "_")
    for status in ("redaction_required", "needs_changes", "signed_off", "blocked", "inconclusive"):
        if status in text:
            return status
    if "needs changes" in text:
        return "needs_changes"
    if "signed off" in text or "sign off" in text:
        return "signed_off"
    return None


def _extract_findings(summary: str, feature_id: str) -> list[dict[str, Any]]:
    """Extract `FINDING (severity, category): issue` snippets from auditor prose."""
    findings: list[dict[str, Any]] = []
    pattern = re.compile(
        r"FINDING\s*\(\s*"
        r"(?P<severity>critical|high|medium|low|advisory)\s*,\s*"
        r"(?P<category>correctness|security|performance|architecture|style|currency|redaction|test_coverage|documentation)"
        r"\s*\)\s*:\s*(?P<issue>.+?)(?=(?:\s+FINDING\s*\()|$)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(summary):
        issue = " ".join(match.group("issue").split()).strip()
        if len(issue) < 10:
            continue
        findings.append(
            {
                "severity": match.group("severity").lower(),
                "category": match.group("category").lower(),
                "feature_id": feature_id,
                "issue": issue[:500],
                "evidence": "Extracted from auditor summary.",
            }
        )
    return findings


def _summary(result: DispatchResult, feature_id: str) -> str:
    if result.success:
        prefix = f"[{feature_id}] "
        body = result.summary or "(no summary returned)"
        return prefix + body[:1500]
    spr = getattr(result, "subprocess_result", None)
    if spr is not None and getattr(spr, "timed_out", False):
        return f"[{feature_id}] {_timeout_summary_block(spr)}"
    return f"[{feature_id}] DISPATCH FAILED: {result.error or 'unknown error'}"


# Plan 2026-05-04-003 F002 — timeout evidence helpers.
# These helpers are no-ops when ``subprocess_result`` is None or when the
# subprocess did not time out, preserving byte-stability for non-timeout
# envelopes (D004, AC #11).


def _render_worktree_value(worktree_changed: bool | None) -> str:
    """Render the ternary worktree state for marker / finding text."""
    if worktree_changed is None:
        return "unknown"
    return "true" if worktree_changed else "false"


def _timeout_summary_block(spr: Any) -> str:
    """Structured timeout context — replaces the bare ``DISPATCH FAILED:``
    text when the subprocess hit the wrapper timeout.

    Schema-wise this is just a longer ``summary`` string; no new fields. The
    block lists timeout duration, captured byte counts, worktree delta, and
    grace-period state — all observable from outside the subprocess
    (Plan C D001).
    """
    lines = [
        f"DISPATCH TIMED OUT after {spr.timeout_seconds}s",
        f"  captured stdout: {spr.captured_stdout_bytes} bytes",
        f"  captured stderr: {spr.captured_stderr_bytes} bytes",
        f"  worktree changed: {_render_worktree_value(spr.worktree_changed)}",
        f"  grace period used: {str(spr.grace_period_used).lower()}",
    ]
    env_markers = list(getattr(spr, "env_markers", []) or [])
    if env_markers:
        lines.append("  env fallbacks:")
        lines.extend(f"    - {m}" for m in env_markers)
    return "\n".join(lines)


def _timeout_markers(spr: Any) -> list[str]:
    """Render ``validation_performed`` markers when subprocess timed out.

    Returns ``[]`` when ``spr`` is None or did not time out, so the caller
    can unconditionally splat the result into validation_performed without
    branching.
    """
    if spr is None or not getattr(spr, "timed_out", False):
        return []
    markers = [
        f"subprocess_timeout_seconds={spr.timeout_seconds}",
        f"timeout_stdout_bytes={spr.captured_stdout_bytes}",
        f"timeout_stderr_bytes={spr.captured_stderr_bytes}",
        f"worktree_changed={_render_worktree_value(spr.worktree_changed)}",
        f"grace_period_used={str(spr.grace_period_used).lower()}",
    ]
    env_markers = list(getattr(spr, "env_markers", []) or [])
    markers.extend(env_markers)
    return markers


def _timeout_finding(spr: Any, feature_id: str) -> dict[str, Any] | None:
    """Structured ``correctness/medium`` finding when subprocess timed out
    AND ``worktree_changed=true``.

    Returns None for the three non-firing cases (no timeout, timeout without
    worktree change, timeout with ``worktree_changed=unknown``) so the
    caller can append unconditionally — never a false positive (D006, D007).
    Category stays ``correctness`` per D007 (existing schema-locked enum).
    """
    if spr is None or not getattr(spr, "timed_out", False):
        return None
    if getattr(spr, "worktree_changed", None) is not True:
        return None
    return {
        "severity": "medium",
        "category": "correctness",
        "feature_id": feature_id,
        "issue": (
            "executor timed out after observable worktree changes; partial work landed on disk"
        ),
        "evidence": (
            f"{spr.timeout_seconds}s timeout exceeded; "
            f"{spr.captured_stdout_bytes} stdout bytes captured; "
            "git status --porcelain=v1 differs before/after"
        ),
        "recommendation": (
            "audit the working-tree changes and either re-dispatch or accept on direct review"
        ),
    }


def _write_partial_sidecars(plan_dir: Path, audit_id: str, spr: Any) -> list[str]:
    """Write captured stdout/stderr to ``audit/partials/`` sidecars.

    Layout per D004:

    - ``<plan_dir>/audit/partials/<audit_id>.stdout.txt`` (UTF-8) OR
      ``<plan_dir>/audit/partials/<audit_id>.stdout.bin`` (raw bytes when
      stdout cannot be UTF-8 decoded)
    - same for stderr

    The path is referenced ONLY from ``validation_performed`` markers
    (returned here as marker strings), never as a top-level audit JSON
    field — schema has ``additionalProperties: false``.

    Empty captured streams produce no file and no marker (AC #8).
    """
    if spr is None or not getattr(spr, "timed_out", False):
        return []

    markers: list[str] = []
    partials_dir = plan_dir / "audit" / "partials"
    safe_audit_id = audit_id.replace("/", "_").replace(os.sep, "_")

    for stream_name, raw_bytes, byte_count in (
        ("stdout", spr.stdout, spr.captured_stdout_bytes),
        ("stderr", spr.stderr, spr.captured_stderr_bytes),
    ):
        if byte_count <= 0 or not raw_bytes:
            continue
        try:
            text = raw_bytes.decode("utf-8")
            ext = f".{stream_name}.txt"
            partials_dir.mkdir(parents=True, exist_ok=True)
            (partials_dir / f"{safe_audit_id}{ext}").write_text(text)
        except UnicodeDecodeError:
            ext = f".{stream_name}.bin"
            partials_dir.mkdir(parents=True, exist_ok=True)
            (partials_dir / f"{safe_audit_id}{ext}").write_bytes(raw_bytes)
        markers.append(f"partial_{stream_name}_path=audit/partials/{safe_audit_id}{ext}")
    return markers


def _normalize_summary(audit: dict[str, Any]) -> dict[str, Any]:
    """F002 write-side gate — validate target_context, then inject the
    canonical D001 prelude into `summary` if it isn't already present.

    Returns a NEW audit dict (shallow-copied; the input is not mutated)
    with `summary` updated when injection fires; returns the input
    audit untouched when validation passes and the canonical prelude
    header is already present (no-op idempotence).

    Raises ``TargetContextError`` (wrapped with audit_id + plan_id
    context) when ``validate_target_context`` rejects the struct shape
    OR when a header is present but the prelude body is structurally
    malformed (wrong field order, mistyped labels, missing line, missing
    trailing blank). Caller MUST NOT persist on raise — F002 acceptance
    #5 is no-partial.

    Presence detection uses ``parse_prelude_block`` so that only a FULL
    canonical block (header + 4 well-formed field lines + trailing blank)
    qualifies as "present." A header-only or otherwise malformed block
    no longer false-positive no-ops (codex i1 MEDIUM finding from the
    F002 confirmation volley). Case-g (header + 4 well-formed lines whose
    VALUES disagree with struct) still no-ops because parse_prelude_block
    returns the parsed dict — F002 only checks structural presence, not
    value correctness; F003's classifier files the value-mismatch i1.
    """
    audit_id = audit.get("audit_id") or "<unknown>"
    plan_id = audit.get("task_id") or "<unknown>"
    tc = audit.get("target_context")

    try:
        validate_target_context(tc)
    except TargetContextError as exc:
        wrapped = TargetContextError(f"envelope {audit_id} for plan {plan_id}: {exc}")
        _LOGGER.warning("audit_writer: %s", wrapped)
        raise wrapped from exc

    # validate_target_context guarantees tc is a dict here; satisfy type
    # checkers and guard against a future change to the validator.
    if not isinstance(tc, dict):
        raise TargetContextError(
            f"envelope {audit_id} for plan {plan_id}: target_context not a dict after validate"
        )

    summary = audit.get("summary") or ""
    try:
        parsed = parse_prelude_block(summary)
    except TargetContextError as exc:
        wrapped = TargetContextError(
            f"envelope {audit_id} for plan {plan_id}: malformed prelude block: {exc}"
        )
        _LOGGER.warning("audit_writer: %s", wrapped)
        raise wrapped from exc

    if parsed is not None:
        return audit  # no-op (case-c golden, case-g value-mismatch, idempotent re-persist)

    repo = resolve_repo(tc)
    rendered = render_prelude({**tc, "repo": repo})

    new_audit = dict(audit)
    new_audit["summary"] = rendered + summary
    _LOGGER.info("audit_writer: injected target-context prelude for %s", audit_id)
    return new_audit


def write(audit: dict[str, Any], plan_dir: Path, *, feature_id: str) -> Path:
    """Validate against audit.schema.json (via Pydantic) and persist.

    Filename: ``{agent}-{role}-{feature_id}-i{n}.json`` under
    ``plan_dir/audit/``. ``feature_id`` is required and validated against
    `^F\\d{3}$` (the agent-conventions feature-id regex) BEFORE any disk
    I/O — invalid values raise ``ValueError`` and no envelope file lands.
    Including ``feature_id`` in the filename prevents within-plan
    multi-feature collision (plan 2026-05-02-002 F001).

    F002: ``_normalize_summary`` runs first — it validates the structured
    ``target_context`` (raises ``TargetContextError`` on shape failure
    BEFORE any disk I/O so the envelope file does not land) and
    prepends the canonical prelude when the summary lacks it.
    """
    if not isinstance(feature_id, str) or not _FEATURE_ID_RE.fullmatch(feature_id):
        raise ValueError(
            f"feature_id must match {_FEATURE_ID_RE.pattern!r} (e.g. 'F001'); got {feature_id!r}"
        )

    audit = _normalize_summary(audit)

    try:
        Audit.model_validate(audit)
    except ValidationError as exc:
        msg = "; ".join(
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
        raise ValueError(f"Audit validation failed: {msg}") from exc

    audit_dir = plan_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    iteration = audit.get("iteration", 0)
    out = audit_dir / f"{audit['agent']}-{audit['agent_role']}-{feature_id}-i{iteration}.json"
    out.write_text(json.dumps(audit, indent=2, ensure_ascii=False, sort_keys=False) + "\n")

    # Plan 2026-05-01-004 F001: capture git state alongside each envelope as
    # evidence for the F002 patch-completeness analyzer. Best-effort — failure
    # to capture (not a git repo, git missing, etc.) logs a warning and does
    # not affect the envelope write.
    _write_git_state_sidecar(plan_dir, iteration=iteration, role=audit["agent_role"])

    return out


def _write_git_state_sidecar(plan_dir: Path, *, iteration: int, role: str) -> None:
    """F001 sidecar: ``<plan_dir>/evidence/git-state-{iteration}-{role}.json``.

    Capture runs against ``plan_dir`` — ``git_state.capture`` walks up to the
    repo toplevel via ``rev-parse --show-toplevel``, so any plan dir nested in
    a git repo resolves correctly. Returns silently on any failure.
    """
    try:
        state = git_state.capture(plan_dir)
    except Exception as exc:  # defensive — capture is documented best-effort
        _LOGGER.warning("audit_writer: git_state.capture raised %s; skipping sidecar", exc)
        return

    if state is None:
        return

    evidence_dir = plan_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    sidecar = evidence_dir / f"git-state-{iteration}-{role}.json"
    sidecar.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
