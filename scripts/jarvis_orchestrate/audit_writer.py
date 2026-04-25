"""Build, validate, and persist Audit JSONs."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from jarvis_orchestrate.executors.base import DispatchResult
from jarvis_orchestrate.plan_loader import LoadedPlan

# Re-import via plan_loader sys.path.insert side effect
from models.audit_model import Audit  # noqa: E402


def build_audit(
    loaded: LoadedPlan,
    result: DispatchResult,
    feature_id: str,
    validation_performed: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose an audit dict. Validation happens in write()."""
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
        "audit_status": _derive_status(result, findings, status_hint=status_hint),
        "findings": findings,
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
    return {k: v for k, v in audit.items() if v is not None}


def _derive_status(
    result: DispatchResult,
    findings: list[dict[str, Any]],
    status_hint: str | None = None,
) -> str:
    if not result.success:
        return "blocked"
    has_critical = any(
        f.get("severity") in {"critical", "high"} for f in findings
    )
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


def write(audit: dict[str, Any], plan_dir: Path) -> Path:
    """Validate against audit.schema.json (via Pydantic) and persist."""
    try:
        Audit.model_validate(audit)
    except ValidationError as exc:
        msg = "; ".join(
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
            for e in exc.errors()[:5]
        )
        raise ValueError(f"Audit validation failed: {msg}") from exc

    audit_dir = plan_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    iteration = audit.get("iteration", 0)
    out = audit_dir / f"{audit['agent']}-{audit['agent_role']}-i{iteration}.json"
    out.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    )
    return out
