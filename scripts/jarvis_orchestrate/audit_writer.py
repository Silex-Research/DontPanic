"""Build, validate, and persist Audit JSONs."""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

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

from jarvis_orchestrate.ec5_classifier import (  # noqa: E402
    apply_ec5_classifier_to_findings,
)
from jarvis_orchestrate.executors.base import DispatchResult  # noqa: E402
from jarvis_orchestrate.plan_loader import LoadedPlan  # noqa: E402
from jarvis_orchestrate.target_context_prelude import (  # noqa: E402
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
    """
    audit_id = f"{loaded.plan_id}#{result.agent}#{result.iteration}"
    findings = (extra or {}).get("findings") or []
    status_hint = None
    if result.agent_role == "auditor" and result.summary:
        status_hint = _extract_status_hint(result.summary)
        if not findings:
            findings = _extract_findings(result.summary, feature_id)
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
    return f"[{feature_id}] DISPATCH FAILED: {result.error or 'unknown error'}"


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


def write(audit: dict[str, Any], plan_dir: Path) -> Path:
    """Validate against audit.schema.json (via Pydantic) and persist.

    F002: ``_normalize_summary`` runs first — it validates the structured
    ``target_context`` (raises ``TargetContextError`` on shape failure
    BEFORE any disk I/O so the envelope file does not land) and
    prepends the canonical prelude when the summary lacks it.
    """
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
    out = audit_dir / f"{audit['agent']}-{audit['agent_role']}-i{iteration}.json"
    out.write_text(json.dumps(audit, indent=2, ensure_ascii=False, sort_keys=False) + "\n")
    return out
