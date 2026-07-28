"""Plan 2026-07-27-001 F004 (D001 B1) — operator-attached external goal/experience audits.

Gemini (and any other operator-only vendor) can review a plan's goal
contract or experience surface interactively, but has NO executor in
:data:`executors.AGENT_REGISTRY` — it cannot be dispatched, and
``roles set goal_auditor gemini`` / ``agent register-worker gemini``
correctly refuse. D001 resolved this as B1-first: instead of registering
a worker, the OPERATOR runs the audit in the vendor's own surface and
attaches the JSON disposition response here as first-class evidence.

The attach path deliberately reuses the dispatched pipeline's machinery
so the artifact is indistinguishable in shape from a dispatched audit:

  - same v1 findings (``completion_auditor.compute_completion_findings``,
    the pure no-write form of the dispatched path's audit) key the
    disposition validation;
  - same response parser (``completion_dispatch._parse_audit_response``)
    — fenced JSON tolerated, unknown finding_ids rejected;
  - same append-only sanitizing writer + per-vendor iteration counter,
    producing ``evidence/goal-governance/post_impl/audit/
    audit-<vendor>-<iter>.{json,transcript.txt}`` — exactly the files
    :func:`completion_gate._load_latest_audit_envelope` and the
    post-completion backstop consume.

Honesty invariants (F004 acceptance):

  - A vendor WITH a registered executor is refused — the dispatched
    path (``dontpanic plan audit``) is canonical there; external attach
    must not become a bypass that fabricates same-shape evidence for a
    dispatchable agent.
  - The envelope carries ``provenance='external'`` + ``audit_kind`` so
    downstream tooling can always tell an attached audit from a
    dispatched one.
  - The cross-vendor invariant (Goal Governance V1 §5) still applies:
    vendor == effective implementer refuses unless the operator sets
    the same F1 override env used by the dispatched path.
  - A malformed response REFUSES (nothing written): unlike the paid
    dispatch path — where the money is already spent and the malformed
    transcript is itself evidence — an attach costs nothing to retry,
    and the append-only trail should not accumulate operator typos.

Prompt for the external run: give the vendor the same context blocks the
dispatched path embeds (contract, features, findings, evidence manifest —
see ``prompts/completion_audit_prompt.md``) and ask for the JSON
disposition array. ``dontpanic plan attach-goal-audit --show-prompt``
renders it for copy/paste.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dontpanic_orchestrate import project_config as pc
from dontpanic_orchestrate.completion_auditor import (
    CompletionAuditError,
    _build_evidence_manifest,
    _load_objective_contract,
    compute_completion_findings,
)
from dontpanic_orchestrate.completion_dispatch import (
    _AUDITOR_NAME_RE,
    _SAME_VENDOR_OVERRIDE_ENV,
    CompletionAuditTranscript,
    _build_audit_prompt,
    _envelope_path,
    _load_features,
    _next_iteration,
    _parse_audit_response,
    _transcript_path,
    _utc_now_iso,
    _write_envelope,
    external_audit_fingerprint,
    sanitize_capture,
)
from dontpanic_orchestrate.executors import AGENT_REGISTRY
from dontpanic_orchestrate.sufficiency_auditor import _is_truthy_env

AuditKind = Literal["goal", "experience"]

# The vendors D001 names for the B1 path today. Advisory (any operator-only
# vendor with a well-formed name is attachable); doctor + docs surface this
# list so operators know the intended first-class citizen. When a vendor
# later gains an executor (B2 / F014), attach refuses it and the dispatched
# path takes over — no dual write.
KNOWN_EXTERNAL_AUDIT_VENDORS: tuple[str, ...] = ("gemini",)

AUDIT_KINDS: tuple[AuditKind, ...] = ("goal", "experience")


class ExternalGoalAuditError(ValueError):
    """Raised when an external audit attach is refused: vendor has a
    registered executor (use the dispatched path), malformed vendor name,
    cross-vendor violation, unparseable response, or missing plan
    artifacts. The CLI maps this to a refusal exit code; nothing is
    written on refusal."""


def _effective_implementer(plan_dir: Path, implementer_agent: str | None) -> str:
    """Resolve the implementer the cross-vendor check compares against:
    explicit caller override, else the same D004 precedence walk the
    dispatched path uses (project config → global config → fallback)."""
    if implementer_agent:
        return implementer_agent.strip().lower()
    project = pc.find_project_for_plan_dir(Path(plan_dir).resolve())
    project_path = project[0] if project is not None else None
    return str(pc.resolve_dispatch_defaults(project_path)["implementer"]).strip().lower()


def _validate_vendor(vendor: str) -> str:
    """Normalize + validate the vendor name; refuse registered executors.

    Returns the normalized name. The refusal message distinguishes the
    two failure modes so the operator always knows the next command."""
    norm = vendor.strip().lower()
    if not _AUDITOR_NAME_RE.fullmatch(norm):
        raise ExternalGoalAuditError(
            f"vendor name {vendor!r} does not match {_AUDITOR_NAME_RE.pattern!r}; "
            "vendor names become audit filenames and must be lowercase "
            "ascii + dash/underscore"
        )
    if norm in AGENT_REGISTRY:
        raise ExternalGoalAuditError(
            f"vendor {norm!r} has a registered executor in AGENT_REGISTRY — use the "
            f"dispatched goal-audit path instead (`dontpanic plan audit <plan-dir>`). "
            "External attach is reserved for operator-only vendors with no executor "
            "(D001 B1), so dispatched evidence can never be hand-fabricated for a "
            "dispatchable agent."
        )
    return norm


def experience_surface_findings(findings) -> list:
    """The experience-audit subset of the v1 findings: ``journey_gap``
    findings are the ones asserting a declared consumer journey lacks
    proof — exactly the surface an external experience audit reviews
    and dispositions. Goal audits grade the FULL findings list."""
    return [f for f in findings if f.gap_class == "journey_gap"]


def _findings_for_kind(plan_dir: Path, kind: AuditKind) -> list:
    """Resolve the finding set the given audit kind grades, refusing an
    experience audit against a plan with no experience surface.

    Read-only (F004 i1 codex finding): uses the PURE
    :func:`compute_completion_findings` — never
    ``run_completion_audit``, whose envelope write would make
    ``--show-prompt`` a mutation and let a malformed attach leave
    ``completion_findings.json`` behind before refusing. Expected
    plan-artifact failures (missing/invalid contract, unreadable files)
    are translated into :class:`ExternalGoalAuditError` so every caller
    refuses cleanly instead of leaking a traceback.

    An experience audit on a contract that declares no ``user_journeys``
    would be a vacuous always-agree envelope — a label with nothing
    behind it — so it refuses instead (F004 must-not-silently-accept)."""
    try:
        findings = compute_completion_findings(plan_dir)
        contract = _load_objective_contract(plan_dir) if kind == "experience" else None
    except (CompletionAuditError, OSError) as exc:
        raise ExternalGoalAuditError(
            f"cannot build the plan's v1 findings: {exc}"
        ) from exc
    if kind != "experience":
        return findings
    if contract is None or not contract.user_journeys:
        raise ExternalGoalAuditError(
            "experience audit refused: the plan's objective contract declares no "
            "user_journeys, so there is no consumer-experience surface to review. "
            "Declare the journeys (with `consumer`) in objective_contract.json, "
            "or run a --kind goal audit instead."
        )
    return experience_surface_findings(findings)


def render_external_audit_prompt(plan_dir: Path, kind: AuditKind = "goal") -> str:
    """Render the prompt for the external run, for the operator to paste
    into the external vendor's surface. Read-only. ``kind='goal'`` renders
    the SAME completion-audit prompt the dispatched path sends;
    ``kind='experience'`` renders the consumer-journey review prompt over
    the journey_gap findings subset (F004 i1 — the experience path grades
    the experience surface, not a relabeled goal audit)."""
    plan_dir = Path(plan_dir).resolve()
    if not plan_dir.is_dir():
        raise ExternalGoalAuditError(f"plan_dir does not exist: {plan_dir}")
    if kind not in AUDIT_KINDS:
        raise ExternalGoalAuditError(
            f"unknown audit kind {kind!r}; expected one of {AUDIT_KINDS}"
        )
    findings = _findings_for_kind(plan_dir, kind)
    try:
        contract = _load_objective_contract(plan_dir)
        features = _load_features(plan_dir)
        manifest = _build_evidence_manifest(plan_dir)
        fingerprint = external_audit_fingerprint(plan_dir, findings)
    except (CompletionAuditError, OSError) as exc:
        raise ExternalGoalAuditError(
            f"cannot render the audit prompt: {exc}"
        ) from exc
    body = _build_audit_prompt(
        contract, features, findings, manifest, plan_dir=plan_dir, kind=kind
    )
    # F004 i2 codex finding: bind the external response to the prompt it
    # audited. Attachment refuses unless the returned source_fingerprint
    # matches the current content hash (findings + contract + features +
    # evidence manifest). A stale response with recycled finding_ids cannot
    # silently vouch for drifted content.
    return (
        f"{body}\n\n"
        f"## Source fingerprint (required)\n\n"
        f"`SOURCE_FINGERPRINT: {fingerprint}`\n\n"
        "Return a JSON **object** (not a bare array):\n"
        "```json\n"
        "{\n"
        f'  "source_fingerprint": "{fingerprint}",\n'
        '  "dispositions": [\n'
        '    {\n'
        '      "finding_id": "<v1 finding id>",\n'
        '      "agree": true,\n'
        '      "severity_disposition": "no_finding",\n'
        '      "comment": "..."\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "```\n"
        "The `source_fingerprint` value MUST match the fingerprint above "
        "exactly. One disposition per v1 finding is required.\n"
    )


def attach_external_goal_audit(
    plan_dir: Path,
    *,
    vendor: str,
    response_text: str,
    kind: AuditKind = "goal",
    implementer_agent: str | None = None,
    note: str | None = None,
) -> CompletionAuditTranscript:
    """Attach an externally-captured goal/experience audit response as a
    first-class audit envelope (D001 B1).

    Validates vendor (operator-only, well-formed name), enforces the
    cross-vendor invariant against the effective implementer, parses the
    response against the plan's REAL v1 findings, and writes the same
    append-only ``audit-<vendor>-<iter>.{json,transcript.txt}`` pair the
    dispatched path produces — which the plan-close gate and the
    post-completion backstop already consume. Refuses (writes nothing)
    on any validation failure, including a malformed response.
    """
    plan_dir = Path(plan_dir).resolve()
    if not plan_dir.is_dir():
        raise ExternalGoalAuditError(f"plan_dir does not exist: {plan_dir}")
    if kind not in AUDIT_KINDS:
        raise ExternalGoalAuditError(
            f"unknown audit kind {kind!r}; expected one of {AUDIT_KINDS}"
        )

    norm_vendor = _validate_vendor(vendor)

    effective_implementer = _effective_implementer(plan_dir, implementer_agent)
    if norm_vendor == effective_implementer and not _is_truthy_env(
        os.environ.get(_SAME_VENDOR_OVERRIDE_ENV)
    ):
        raise ExternalGoalAuditError(
            f"cross-vendor invariant: external audit vendor {norm_vendor!r} matches the "
            f"effective implementer {effective_implementer!r}. Same-vendor adversarial "
            "review is banned by default (Goal Governance V1 §5); set "
            f"{_SAME_VENDOR_OVERRIDE_ENV}=1 to deliberately override."
        )

    if not (response_text or "").strip():
        raise ExternalGoalAuditError(
            "response text is empty — paste the vendor's JSON object with "
            "source_fingerprint + dispositions (one disposition per v1 finding)"
        )

    findings = _findings_for_kind(plan_dir, kind)
    expected_fp = external_audit_fingerprint(plan_dir, findings)
    dispositions_payload, claimed_fp = _extract_external_payload(response_text)
    if claimed_fp is None:
        raise ExternalGoalAuditError(
            "refusing to attach: response must be a JSON object with "
            f"'source_fingerprint' (expected {expected_fp!r}) and "
            "'dispositions' array. Re-run `dontpanic plan attach-goal-audit "
            "--show-prompt` and return the fingerprint it embeds so the "
            "response is bound to the content that was audited."
        )
    if claimed_fp != expected_fp:
        raise ExternalGoalAuditError(
            f"refusing to attach: source_fingerprint mismatch "
            f"(response={claimed_fp!r}, current={expected_fp!r}). "
            "Plan content drifted after the external audit ran — re-render "
            "the prompt and re-run the vendor review (nothing was written)."
        )

    status, dispositions = _parse_audit_response(dispositions_payload, findings)
    if status == "dispatch_response_malformed":
        detail = dispositions[0].comment if dispositions else "unparseable response"
        raise ExternalGoalAuditError(
            f"refusing to attach: response failed validation — {detail}. Fix the "
            "response and re-attach (nothing was written); the external-attach "
            "contract requires one disposition per v1 finding under "
            "'dispositions'."
        )

    iteration = _next_iteration(plan_dir, norm_vendor)
    sanitized_response = sanitize_capture(response_text)
    transcript = CompletionAuditTranscript(
        auditor_agent=norm_vendor,
        implementer_agent=effective_implementer,
        status=status,
        iteration=iteration,
        findings_dispositions=dispositions,
        transcript_path=sanitize_capture(str(_transcript_path(plan_dir, norm_vendor, iteration))),
        envelope_path=sanitize_capture(str(_envelope_path(plan_dir, norm_vendor, iteration))),
        generated_at=_utc_now_iso(),
        raw_response=sanitized_response,
        provenance="external",
        audit_kind=kind,
        external_note=sanitize_capture(note) if note else None,
        source_fingerprint=expected_fp,
    )
    _write_envelope(plan_dir, transcript, response_text)
    return transcript


def _extract_external_payload(response_text: str) -> tuple[str, str | None]:
    """Parse external attach body into (dispositions_json, fingerprint_or_none).

    Accepts:
      - ``{"source_fingerprint": "...", "dispositions": [...]}`` (preferred)
      - bare disposition array (fingerprint=None — attach refuses)

    Fence-stripping matches the dispatched parser so operators can paste
    fenced model output."""
    import json as _json

    raw = (response_text or "").strip()
    # Reuse the same fence strip as the completion parser without importing
    # the private helper name drift — strip a single leading ``` fence.
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        payload = _json.loads(raw)
    except _json.JSONDecodeError:
        return response_text, None
    if isinstance(payload, list):
        return _json.dumps(payload), None
    if not isinstance(payload, dict):
        return response_text, None
    fp = payload.get("source_fingerprint")
    disps = payload.get("dispositions")
    if disps is None:
        disps = payload.get("findings_dispositions")
    if not isinstance(disps, list):
        return response_text, str(fp) if fp is not None else None
    return _json.dumps(disps), str(fp) if fp is not None else None


__all__ = [
    "AUDIT_KINDS",
    "AuditKind",
    "ExternalGoalAuditError",
    "KNOWN_EXTERNAL_AUDIT_VENDORS",
    "attach_external_goal_audit",
    "experience_surface_findings",
    "render_external_audit_prompt",
]
