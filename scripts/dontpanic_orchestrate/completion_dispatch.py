"""Plan F2 F002 — cross-vendor goal-audit dispatcher.

Wires F1's :func:`sufficiency_auditor._resolve_goal_auditor_agent` into a real
production dispatch path that actually invokes the resolved auditor against a
plan-level completion-audit prompt. F1's F003 left this as an explicit seam
(``DispatchFn``); F1's F005 dogfood ran with
``DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR=1`` set because production dispatch
wasn't wired. F2/F002 closes that caveat for the post-impl boundary.

Public surface::

    dispatch_completion_audit(
        plan_dir, *, findings, implementer_agent=None,
        iteration=1, dispatch=None,
    ) -> CompletionAuditTranscript

    SameVendorRefused (Exception, subclass of SufficiencyAuditError —
                       callers can catch the F1 base)
    CompletionDispatchError (executor unavailable / dispatch failure)
    CompletionAuditTranscript (Pydantic envelope)
    FindingDisposition (Pydantic per-finding disposition)
    DispatchFn (test-injection seam Callable[[str, str], str])

    DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR — preserved from F1 (override
                                              the cross-vendor refusal)
    DONTPANIC_GOAL_AUDITOR_OFFLINE — F2/F002 addition; skips real
                                    executor invocation and returns a
                                    synthetic ``dispatch_skipped_offline``
                                    envelope for air-gapped contexts.

Cross-vendor invariant (D003 / Goal Governance V1 §5): same-vendor refusal
preserved by default. Override is the operator's deliberate choice
(``DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR=1``); F002 does NOT relax this.

Capture-only invariant (Plan G D002 / F2 D009): the dispatcher only READS
the evidence manifest produced by F001's auditor. It does not invoke any
``runtime_evidence/{web,ios,android,backend,harness}.py`` session class.

This module is library-only; F003 will add the CLI surface.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import socket
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dontpanic_orchestrate.codex_stream import (
    extract_codex_streaming_payload as _extract_codex_streaming_payload,
)
from dontpanic_orchestrate.completion_auditor import (
    POST_IMPL_DIR,
    CompletionAuditError,
    CompletionFinding,
    _build_evidence_manifest,
    _load_objective_contract,
)
from dontpanic_orchestrate.executors import get_executor
from dontpanic_orchestrate.executors.base import DispatchTask
from dontpanic_orchestrate.sufficiency_auditor import (
    SufficiencyAuditError,
    _is_truthy_env,
    _resolve_goal_auditor_agent,
)

# ──────────────────────────────  constants  ──────────────────────────────


_SAME_VENDOR_OVERRIDE_ENV: str = "DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR"
"""Re-export of F1's override env name. Read here purely as a fail-fast
sanity check; the actual enforcement happens inside
:func:`_resolve_goal_auditor_agent`."""

_OFFLINE_ENV: str = "DONTPANIC_GOAL_AUDITOR_OFFLINE"
"""F2/F002 addition. When truthy, dispatch returns a synthetic
``dispatch_skipped_offline`` envelope without invoking any executor.
F003's plan-close gate refuses status flip when this is set unless the
operator supplies ``--ignore-completion-findings <reason>``."""

_PROMPT_TEMPLATE_PATH: Path = Path(__file__).parent / "prompts" / "completion_audit_prompt.md"
"""Path to the auditor prompt markdown template. Embeds ``{contract}``,
``{features}``, ``{findings}``, ``{evidence_manifest}`` placeholders."""

_EXPERIENCE_PROMPT_TEMPLATE_PATH: Path = (
    Path(__file__).parent / "prompts" / "experience_audit_prompt.md"
)
"""Plan 2026-07-27-001 F004 — experience-kind sibling of the goal template.
Same four placeholders, but the review subject is the consumer-journey
surface (``ObjectiveContract.user_journeys`` + journey_gap findings), not
goal-contract coverage."""

_AUDIT_DIR_NAME: str = "audit"
"""Subdirectory under ``POST_IMPL_DIR`` for envelope + transcript files.
Filename pattern: ``audit-<auditor>-<iter>.json`` /
``audit-<auditor>-<iter>.transcript.txt``."""

_AUDITOR_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
"""Auditor agent names go into filenames; pin the shape to lowercase
ascii + dash/underscore so we can never write a path-traversal filename."""


# _RECOGNIZED_CODEX_STREAM_TYPES now lives in codex_stream (imported above) so
# the pre-impl sufficiency path can reuse the SAME shape gate (plan 2026-06-08-006).

_DISPATCH_FEATURE_ID: str = "F002"
"""F2/F002 is the plan-level dispatcher; the dispatched executor task
carries this feature_id so downstream tooling that keys on feature_id
(env registry, target-context cross-check) sees a stable identifier."""


_AuditStatus = Literal[
    "agree",
    "disagree",
    "dispatch_skipped_offline",
    "dispatch_response_malformed",
]


_SEVERITY_DISPOSITIONS: tuple[str, ...] = ("agree", "lower", "higher", "no_finding")


# ──────────────────────────────  exceptions  ──────────────────────────────


class SameVendorRefused(SufficiencyAuditError):
    """Raised by :func:`dispatch_completion_audit` when the resolved
    auditor matches the implementer and
    :data:`_SAME_VENDOR_OVERRIDE_ENV` is unset.

    Subclasses :class:`sufficiency_auditor.SufficiencyAuditError` so
    callers (F003 plan-close gate) can catch the F1 base for one
    ``except`` clause across both pre-impl and post-impl boundaries."""


class CompletionDispatchError(RuntimeError):
    """Raised when the dispatcher cannot complete a real dispatch run
    for reasons unrelated to vendor resolution: resolved executor not
    on PATH, prompt template missing, etc. Distinct from
    :class:`SameVendorRefused` (which is a vendor-policy refusal,
    not an availability failure)."""


class ConfigNotReady(CompletionDispatchError):
    """Plan 2026-06-01-001 F009 — raised when the pre-flight config-readiness
    check (quota caps + role config) fails BEFORE the plan-close goal-completion
    audit spends a paid call. Carries the actionable readiness message (the
    file, the precise reason, and a runnable remediation command) so the
    operator is never stranded by a raw ``{}``-style schema crash at plan-close,
    mirroring the dispatch-from-plan readiness gate."""


# ──────────────────────────────  pydantic models  ──────────────────────────────


class FindingDisposition(BaseModel):
    """One auditor disposition keyed to a v1 :class:`CompletionFinding`.

    The auditor responds with a list of these — one per v1 finding,
    plus optional ``auditor-overlay-NNN`` entries when it spots a
    coverage gap the v1 heuristic missed entirely (allowed because
    v1 is intentionally simple per D002)."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(..., min_length=1)
    agree: bool
    severity_disposition: str = Field(..., min_length=1)
    comment: str = Field(..., min_length=1)

    @field_validator("severity_disposition")
    @classmethod
    def _validate_severity_disposition(cls, value: str) -> str:
        if value not in _SEVERITY_DISPOSITIONS:
            raise ValueError(
                f"unknown severity_disposition: {value!r}; must be one of {_SEVERITY_DISPOSITIONS}"
            )
        return value


class CompletionAuditTranscript(BaseModel):
    """Envelope returned by :func:`dispatch_completion_audit` and serialized
    to ``evidence/goal-governance/post_impl/audit/audit-<auditor>-<iter>.json``.

    ``status`` is the load-bearing decision field consumed by F003's
    plan-close gate:

    - ``agree``: every disposition's ``agree=True`` — F2 findings are
      authoritative.
    - ``disagree``: at least one disposition disagrees — F003 refuses
      status flip until the operator either resolves the disagreement
      or invokes the input-bound override.
    - ``dispatch_skipped_offline``: synthetic envelope produced when
      :data:`_OFFLINE_ENV` is set; no executor was invoked.
    - ``dispatch_response_malformed``: auditor responded with text the
      parser could not interpret as a JSON disposition list. F003
      treats this as block; operator overrides or fixes.

    Plan 2026-07-27-001 F004 (D001 B1): ``provenance`` distinguishes an
    operator-attached external audit (``'external'`` — vendor has NO
    executor; response captured outside DontPanic and attached via
    ``dontpanic plan attach-goal-audit``) from the dispatched path
    (``'dispatched'`` or absent on pre-F004 envelopes). ``audit_kind``
    records whether the external run reviewed the goal contract or the
    experience surface; ``external_note`` carries the operator's
    attach-time rationale. All three are optional so historical
    envelopes still validate."""

    model_config = ConfigDict(extra="forbid")

    auditor_agent: str = Field(..., min_length=1)
    implementer_agent: str | None = None
    status: _AuditStatus
    iteration: int = Field(..., ge=0)
    findings_dispositions: list[FindingDisposition] = Field(default_factory=list)
    transcript_path: str = Field(..., min_length=1)
    envelope_path: str = Field(..., min_length=1)
    generated_at: str = Field(..., min_length=1)
    raw_response: str | None = None
    provenance: Literal["dispatched", "external"] | None = None
    audit_kind: Literal["goal", "experience"] | None = None
    external_note: str | None = None
    source_fingerprint: str | None = None
    """Plan 2026-07-27-001 F004 i1 — content hash binding an EXTERNAL
    envelope to the exact findings/contract/features/evidence it graded (see
    :func:`external_audit_fingerprint`). Freshness selection requires an
    exact match, so finding-content drift after attach (same ordinal
    finding_ids, different substance) stales the envelope instead of
    silently passing. Absent on dispatched and historical envelopes."""


# ──────────────────────────────  test-injection seam  ──────────────────────────────


DispatchFn = Callable[[str, str], str]
"""Test-injection seam for :func:`dispatch_completion_audit`.

Signature: ``dispatch(auditor_agent, prompt) -> raw_response``.

Mirrors F1's :data:`sufficiency_auditor.DispatchFn` shape so test
stubs can be reused across both audit boundaries. When ``dispatch`` is
``None`` (production), the dispatcher uses
:func:`executors.get_executor` against
:data:`executors.AGENT_REGISTRY` to invoke the resolved auditor's CLI.
"""


# ──────────────────────────────  helpers  ──────────────────────────────


def _utc_now_iso() -> str:
    """Deterministic ISO8601 UTC timestamp (suffix ``+00:00``)."""
    return datetime.now(timezone.utc).isoformat()


def _resolve_auditor_or_translate_same_vendor(
    plan_dir: Path,
    implementer_agent: str | None,
) -> str:
    """Wrap :func:`_resolve_goal_auditor_agent` and translate F1's
    same-vendor :class:`SufficiencyAuditError` into the cleaner
    :class:`SameVendorRefused` subclass for caller ergonomics.

    All other configuration errors propagate as
    :class:`SufficiencyAuditError` (no goal_auditor configured, etc.),
    so F003 can map a single base exception to its exit-5 vendor-error
    bucket without ambiguity."""
    try:
        return _resolve_goal_auditor_agent(plan_dir, implementer_agent=implementer_agent)
    except SufficiencyAuditError as exc:
        if "cross-vendor invariant" in str(exc):
            raise SameVendorRefused(str(exc)) from exc
        raise


def _load_features(plan_dir: Path) -> list[dict]:
    """Read ``features.json`` and return the ``features`` list. Mirrors
    F1's helper of the same name; kept inline rather than importing to
    keep the boundary explicit (F2 does not depend on F1's private
    helper surface)."""
    features_json = plan_dir / "features.json"
    if not features_json.is_file():
        raise CompletionAuditError(f"features.json not found at {features_json}")
    try:
        raw = json.loads(features_json.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CompletionAuditError(f"{features_json}: failed to read: {exc}") from exc
    items = raw.get("features") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise CompletionAuditError(
            f"{features_json}: expected top-level mapping with 'features' list"
        )
    return items


def _read_prompt_template(kind: str = "goal") -> str:
    """Read the markdown template once per call, selected by audit kind
    (``'goal'`` → completion template, ``'experience'`` → journey/experience
    template).

    Re-reading is cheap (small file, infrequent call) and avoids the
    test-time hazard of caching a file the test fixture replaced."""
    path = _EXPERIENCE_PROMPT_TEMPLATE_PATH if kind == "experience" else _PROMPT_TEMPLATE_PATH
    if not path.is_file():
        raise CompletionDispatchError(f"{kind}-audit prompt template missing at {path}")
    return path.read_text()


def _serialize_contract(contract) -> str:
    """Deterministic JSON-ish serialization of the ObjectiveContract for
    the prompt body. ``model_dump_json`` returns sorted keys when we
    pass through ``json.dumps(sort_keys=True)``."""
    raw = contract.model_dump(mode="json", exclude_none=True)
    return json.dumps(raw, indent=2, sort_keys=True, ensure_ascii=False)


def _serialize_features(features: list[dict]) -> str:
    """Sorted-key JSON dump of the features list."""
    return json.dumps(features, indent=2, sort_keys=True, ensure_ascii=False)


def _serialize_findings(findings: Iterable[CompletionFinding]) -> str:
    """Sorted-key JSON dump of the v1 findings."""
    payload = [f.model_dump(mode="json", exclude_none=True) for f in findings]
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def _plan_dir_repo_prefix(plan_dir: Path) -> str | None:
    """Repo-root-relative prefix for the plan dir (e.g.
    ``docs/plans/<id>``), found by walking up to the nearest ``.git``
    entry (dir in a primary checkout, FILE in a linked worktree). None
    when the plan dir is not inside a repository."""
    plan_dir = Path(plan_dir).resolve()
    for ancestor in plan_dir.parents:
        if (ancestor / ".git").exists():
            return str(plan_dir.relative_to(ancestor))
    return None


def _serialize_manifest(manifest, *, uri_prefix: str | None = None) -> str:
    """Sorted-key JSON dump of the rebuilt evidence manifest. Each
    EvidenceRef serializes via its Pydantic model_dump.

    ``uri_prefix`` rewrites uris for the PROMPT only: EvidenceRef.uri is
    plan-dir-relative by contract (manifest signatures and envelopes are
    unchanged), but the auditor subprocess runs with cwd at the repo
    root — the audit-codex-1 transcript on plan 2026-06-11-001 showed
    every artifact read failing on the bare plan-relative path and the
    verdict silently degrading to manifest-shape-only review."""
    payload = [ref.model_dump(mode="json", exclude_none=True) for ref in manifest]
    if uri_prefix:
        for ref in payload:
            if ref.get("uri"):
                ref["uri"] = f"{uri_prefix}/{ref['uri']}"
    payload.sort(key=lambda r: (r.get("uri") or "", r.get("hash") or ""))
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def _build_audit_prompt(
    contract,
    features: list[dict],
    findings: Iterable[CompletionFinding],
    manifest,
    *,
    plan_dir: Path | None = None,
    kind: str = "goal",
) -> str:
    """Render the prompt template by substituting the four context
    blocks. Uses ``str.replace`` rather than ``str.format`` so embedded
    ``{`` / ``}`` characters in the JSON payloads do not collide with
    the template's placeholders. When ``plan_dir`` is given, evidence
    uris are rendered repo-root-relative so the auditor (cwd = repo
    root) can actually open them. ``kind`` selects the template (goal
    completion vs consumer-experience review — F004 i1)."""
    template = _read_prompt_template(kind)
    uri_prefix = _plan_dir_repo_prefix(plan_dir) if plan_dir is not None else None
    return (
        template.replace("{contract}", _serialize_contract(contract))
        .replace("{features}", _serialize_features(features))
        .replace("{findings}", _serialize_findings(findings))
        .replace(
            "{evidence_manifest}",
            _serialize_manifest(manifest, uri_prefix=uri_prefix),
        )
    )


def external_audit_fingerprint(
    plan_dir: Path,
    findings: Iterable[CompletionFinding],
) -> str:
    """Plan 2026-07-27-001 F004 i1/i2 — content hash over exactly what an
    external audit graded: the full serialized findings (content, not just
    ordinal ids), the objective contract, the features list (i2 — feature
    descriptions/acceptance are embedded in the reviewed prompt, so their
    drift must stale the envelope too), and the evidence-manifest
    ``uri|hash`` signature.

    Stamped onto the envelope at attach time and recomputed at selection
    time; any drift in finding substance, contract text, feature content,
    or captured evidence makes the attached envelope stale instead of
    letting an audit of old content silently vouch for new content."""
    contract = _load_objective_contract(plan_dir)
    features = _load_features(plan_dir)
    manifest = _build_evidence_manifest(plan_dir)
    pairs = sorted((ref.uri or "", ref.hash or "") for ref in manifest)
    manifest_signature = "\n".join(f"{uri}|{hsh}" for uri, hsh in pairs)
    body = "\x00".join(
        [
            _serialize_findings(findings),
            _serialize_contract(contract),
            _serialize_features(features),
            manifest_signature,
        ]
    )
    return f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"


def _strip_code_fence(text: str) -> str:
    """Tolerate ``` fenced output the same way F1's parser does. The
    prompt asks for raw JSON; agents commonly fence anyway."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            inner = stripped[first_newline + 1 :]
            if inner.endswith("```"):
                inner = inner[: -len("```")]
            return inner.strip()
    return stripped


# _extract_codex_streaming_payload now lives in codex_stream and is imported at
# the top of this module (back-compat alias). The pre-impl sufficiency path
# reuses the SAME implementation — single source of truth (plan 2026-06-08-006).


def _parse_audit_response(
    response: str,
    findings: list[CompletionFinding],
) -> tuple[_AuditStatus, list[FindingDisposition]]:
    """Best-effort parse: return ``(status, dispositions)``.

    Malformed responses do NOT raise — they collapse to a single
    synthetic disposition with ``finding_id='dispatch_response_malformed'``
    and the envelope status is ``dispatch_response_malformed``. F003
    treats that status as a hard block; operator either fixes the
    auditor or invokes the override. Raising here would force F003 to
    handle two error modes (refusal + parse-fail) when one suffices.

    Input transform (Plan F2C-D008): before fence-stripping, attempt
    :func:`_extract_codex_streaming_payload`. If it returns a non-None
    string, the codex JSONL stream's last completed ``agent_message``
    text becomes the ``cleaned`` candidate. If it returns ``None``
    (input is not a codex stream, or stream has no agent_message), the
    original ``response`` is fence-stripped and parsed unchanged —
    preserving backward compat for stub / manual / non-streaming
    inputs (D004)."""
    raw = response or ""
    streaming_payload = _extract_codex_streaming_payload(raw)
    cleaned = _strip_code_fence(streaming_payload if streaming_payload is not None else raw)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return "dispatch_response_malformed", [
            FindingDisposition(
                finding_id="dispatch_response_malformed",
                agree=False,
                severity_disposition="no_finding",
                comment=(
                    "auditor response is not valid JSON; raw response preserved in transcript file"
                ),
            )
        ]

    if not isinstance(payload, list):
        return "dispatch_response_malformed", [
            FindingDisposition(
                finding_id="dispatch_response_malformed",
                agree=False,
                severity_disposition="no_finding",
                comment=(f"auditor response must be a JSON array; got {type(payload).__name__}"),
            )
        ]

    dispositions: list[FindingDisposition] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            return "dispatch_response_malformed", [
                FindingDisposition(
                    finding_id="dispatch_response_malformed",
                    agree=False,
                    severity_disposition="no_finding",
                    comment=(
                        f"auditor response element [{index}] must be a JSON "
                        f"object; got {type(item).__name__}"
                    ),
                )
            ]
        try:
            dispositions.append(FindingDisposition.model_validate(item))
        except Exception:
            return "dispatch_response_malformed", [
                FindingDisposition(
                    finding_id="dispatch_response_malformed",
                    agree=False,
                    severity_disposition="no_finding",
                    comment=(f"auditor response element [{index}] failed schema validation"),
                )
            ]

    valid_finding_ids = {f.finding_id for f in findings}
    valid_finding_ids.add("dispatch_response_malformed")
    for disp in dispositions:
        if disp.finding_id.startswith("auditor-overlay-"):
            continue
        if disp.finding_id not in valid_finding_ids:
            return "dispatch_response_malformed", [
                FindingDisposition(
                    finding_id="dispatch_response_malformed",
                    agree=False,
                    severity_disposition="no_finding",
                    comment=(
                        f"auditor disposition references unknown finding_id "
                        f"{disp.finding_id!r}; not in v1 findings list"
                    ),
                )
            ]

    if not dispositions:
        if findings:
            # Prompt contract requires one disposition per v1 finding.
            # Empty-array response when findings is non-empty means the
            # auditor refused to grade; treat as malformed so F003's
            # plan-close gate blocks rather than silently passing.
            return "dispatch_response_malformed", [
                FindingDisposition(
                    finding_id="dispatch_response_malformed",
                    agree=False,
                    severity_disposition="no_finding",
                    comment=(
                        f"auditor returned empty disposition list against "
                        f"{len(findings)} v1 finding(s); expected one "
                        "disposition per finding"
                    ),
                )
            ]
        return "agree", dispositions

    # Plan 2026-07-27-001 F004 — completeness: the prompt contract requires
    # exactly one disposition per v1 finding. Without this check a partial
    # response (grading F-1 but silent on F-2) collapsed to `agree`, letting
    # an auditor — dispatched or externally attached — skip findings.
    graded = [d.finding_id for d in dispositions if not d.finding_id.startswith("auditor-overlay-")]
    duplicated = sorted({fid for fid in graded if graded.count(fid) > 1})
    if duplicated:
        return "dispatch_response_malformed", [
            FindingDisposition(
                finding_id="dispatch_response_malformed",
                agree=False,
                severity_disposition="no_finding",
                comment=(
                    f"auditor response grades finding_id(s) more than once: "
                    f"{', '.join(duplicated)}; expected exactly one disposition "
                    "per v1 finding"
                ),
            )
        ]
    missing = sorted({f.finding_id for f in findings} - set(graded))
    if missing:
        return "dispatch_response_malformed", [
            FindingDisposition(
                finding_id="dispatch_response_malformed",
                agree=False,
                severity_disposition="no_finding",
                comment=(
                    f"auditor response omits disposition(s) for v1 finding_id(s): "
                    f"{', '.join(missing)}; expected exactly one disposition "
                    "per finding"
                ),
            )
        ]

    all_agree = all(d.agree for d in dispositions)
    return ("agree" if all_agree else "disagree"), dispositions


def _validate_auditor_name(auditor: str) -> None:
    """Auditor names go into filenames; pin the shape so we cannot
    write a path-traversal filename if some future executor registers
    under a non-conforming name."""
    if not _AUDITOR_NAME_RE.fullmatch(auditor):
        raise CompletionDispatchError(
            f"auditor agent name {auditor!r} does not match "
            f"{_AUDITOR_NAME_RE.pattern!r}; refusing to write transcript"
        )


def _audit_dir(plan_dir: Path) -> Path:
    return plan_dir / POST_IMPL_DIR / _AUDIT_DIR_NAME


def sanitize_capture(text: str) -> str:
    """Plan 2026-06-12-001 F001 — capture-time sanitizer for audit evidence.

    Pure + idempotent: the operator's home directory becomes ``<home>``,
    ``user@host`` becomes ``<operator>@<host>``, and remaining bare
    username tokens become ``<operator>``. Applied by the evidence writer
    BEFORE the first byte is persisted (committed envelopes are immutable,
    so the writer is the only correct fix point). Exported so the pre-impl
    sufficiency writer can adopt the same sanitizer."""
    home = str(Path.home())
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 — no resolvable user: nothing to scrub
        user = ""
    host = socket.gethostname()
    out = text.replace(home, "<home>")
    if user:
        out = out.replace(f"{user}@{host}", "<operator>@<host>")
        out = out.replace(user, "<operator>")
    return out


_ENVELOPE_FILE_RE = re.compile(r"^audit-(.+)-(\d+)\.json$")


def _next_iteration(plan_dir: Path, auditor: str) -> int:
    """Plan 2026-06-12-001 F002 — derive the next free iteration for this
    auditor from the audit directory (1 when none exist). Per-auditor:
    a foreign auditor's envelopes never bump this auditor's counter."""
    audit_dir = _audit_dir(plan_dir)
    if not audit_dir.is_dir():
        return 1
    highest = 0
    for entry in audit_dir.iterdir():
        m = _ENVELOPE_FILE_RE.match(entry.name)
        if m and m.group(1) == auditor:
            try:
                highest = max(highest, int(m.group(2)))
            except ValueError:
                continue
    return highest + 1


def _envelope_path(plan_dir: Path, auditor: str, iteration: int) -> Path:
    return _audit_dir(plan_dir) / f"audit-{auditor}-{iteration}.json"


def _transcript_path(plan_dir: Path, auditor: str, iteration: int) -> Path:
    return _audit_dir(plan_dir) / f"audit-{auditor}-{iteration}.transcript.txt"


def _write_envelope(
    plan_dir: Path,
    transcript: CompletionAuditTranscript,
    raw_response: str,
) -> None:
    """Write transcript + envelope to disk, refusing to overwrite an
    existing envelope (append-only audit trail — F002) and sanitizing at
    capture time (F001). The REAL output paths are recomputed from
    plan_dir/auditor/iteration because the transcript's recorded path
    strings are the sanitized placeholder forms."""
    out_dir = _audit_dir(plan_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    envelope_file = _envelope_path(plan_dir, transcript.auditor_agent, transcript.iteration)
    if envelope_file.exists():
        raise CompletionDispatchError(
            f"refusing to overwrite existing audit envelope {envelope_file.name} "
            f"in {out_dir} — the audit trail is append-only; omit the explicit "
            "iteration (or pass a free one) to write the next iteration instead"
        )
    transcript_file = _transcript_path(plan_dir, transcript.auditor_agent, transcript.iteration)
    transcript_file.write_text(sanitize_capture(raw_response))
    envelope_file.write_text(
        json.dumps(
            transcript.model_dump(mode="json", exclude_none=True),
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


def _emit_offline_envelope(
    plan_dir: Path,
    auditor: str,
    iteration: int,
    implementer_agent: str | None,
) -> CompletionAuditTranscript:
    """Synthetic envelope for ``DONTPANIC_GOAL_AUDITOR_OFFLINE=1``.

    No executor is invoked. The transcript file records the offline
    decision; the envelope's status is ``dispatch_skipped_offline`` so
    F003 can refuse the close-out unless the operator supplies an
    explicit ``--ignore-completion-findings`` reason."""
    _validate_auditor_name(auditor)
    transcript_path = _transcript_path(plan_dir, auditor, iteration)
    envelope_path = _envelope_path(plan_dir, auditor, iteration)
    raw = (
        f"# Offline dispatch placeholder ({_OFFLINE_ENV} truthy)\n"
        f"\n"
        f"resolved auditor: {auditor}\n"
        f"implementer: {implementer_agent or '<unspecified>'}\n"
        f"iteration: {iteration}\n"
        f"\n"
        "No executor was invoked. Operator must either re-run with the\n"
        "offline env unset OR record an --ignore-completion-findings\n"
        "override at plan-close time (F003).\n"
    )
    transcript = CompletionAuditTranscript(
        auditor_agent=auditor,
        implementer_agent=implementer_agent,
        status="dispatch_skipped_offline",
        iteration=iteration,
        findings_dispositions=[],
        transcript_path=sanitize_capture(str(transcript_path)),
        envelope_path=sanitize_capture(str(envelope_path)),
        generated_at=_utc_now_iso(),
        raw_response=None,
    )
    _write_envelope(plan_dir, transcript, raw)
    return transcript


# ──────────────────────────────  entry point  ──────────────────────────────


def _dispatch_via_executor(auditor: str, prompt: str, *, plan_dir: Path) -> str:
    """Production dispatch path. Resolves the executor via
    :data:`executors.AGENT_REGISTRY`, refuses if the CLI is not
    available (operator-actionable :class:`CompletionDispatchError`),
    and returns the raw stdout. Subprocess failures surface as
    ``DispatchResult(success=False)``; we still return ``raw_response``
    so the auditor's prose (often an error message) lands in the
    transcript."""
    # F013 i1 — the resolved auditor may be a worker-profile id (or a D015
    # alias); map to (harness, model) through the profile gates before
    # touching the registry. Lazy import mirrors the resolver import below.
    from dontpanic_orchestrate import worker_profiles as _wp

    try:
        worker = _wp.resolve_goal_audit_worker(plan_dir, auditor)
    except _wp.WorkerProfileError as exc:
        raise CompletionDispatchError(str(exc)) from exc
    executor = get_executor(worker.harness)
    if not executor.is_available():
        raise CompletionDispatchError(
            f"resolved auditor {auditor!r} (harness {worker.harness!r}) is not "
            f"available — {executor.availability_hint()}"
        )

    # F012 i1 (codex audit i0 high finding) — forward the configured
    # goal-audit model override; None keeps the harness CLI default.
    # F013: the profile-level model wins over the role-level override.
    # Lazy import mirrors sufficiency_auditor's F006-package decoupling.
    from dontpanic_orchestrate.config.resolvers import resolve_goal_audit_model

    plan_id = plan_dir.name
    task = DispatchTask(
        plan_id=plan_id,
        plan_dir=plan_dir,
        feature_id=_DISPATCH_FEATURE_ID,
        feature_description=("post-impl completion audit (cross-vendor adversarial review)"),
        feature_acceptance="auditor returns JSON disposition array",
        feature_steps=[],
        agent_role="auditor",
        iteration=0,
        extra_context={"prompt_override": prompt},
        permission_policy="auditor",
        model=worker.model or resolve_goal_audit_model(plan_dir, harness=worker.harness),
    )
    result = executor.dispatch(task)
    return result.raw_response or ""


def _assert_config_ready_for_completion(
    *,
    implementer_agent: str | None,
    auditor: str,
    caps_path: Path | None = None,
    plan_dir: Path | None = None,
) -> None:
    """Plan 2026-06-01-001 F009 — raise :class:`ConfigNotReady` if the quota-caps
    config or the resolved role values are not usable, BEFORE the plan-close
    goal-completion audit spends a paid call. Reuses the same readiness module
    as the dispatch-from-plan gate so the actionable message + runnable
    remediation are identical at both pre-flight sites.

    F013 i1: role values may be worker-profile ids or D015 aliases; readiness
    validates the resolved HARNESS (profiles are validated by their own gates
    at dispatch), so a valid ``roles.auditor=honey`` no longer fails the
    registered-executor check."""
    from dontpanic_orchestrate import config_readiness, worker_profiles
    from dontpanic_orchestrate.executors import AGENT_REGISTRY

    def _to_harness(name: str) -> str:
        peeked = worker_profiles.peek_worker(plan_dir, name)
        return peeked.harness if peeked is not None else name

    roles = [_to_harness(r) for r in (implementer_agent, auditor) if r]
    result = config_readiness.check_config_readiness(
        roles=roles,
        registered_executors=set(AGENT_REGISTRY),
        caps_path=caps_path,
    )
    if not result.ok:
        raise ConfigNotReady(result.render())


def dispatch_completion_audit(
    plan_dir: Path,
    *,
    findings: list[CompletionFinding],
    implementer_agent: str | None = None,
    iteration: int | None = None,
    dispatch: DispatchFn | None = None,
    caps_path: Path | None = None,
) -> CompletionAuditTranscript:
    """Run a cross-vendor goal audit on a v1 completion-findings list.

    Resolution order (mirrors F1's resolver):

    1. :func:`_resolve_goal_auditor_agent` walks
       project-config → global-config → fallback per D004 of Plan G F006
       and returns the resolved ``roles.goal_auditor``.
    2. Same-vendor refusal (``effective_implementer == auditor`` AND
       :data:`_SAME_VENDOR_OVERRIDE_ENV` unset) fail-fast as
       :class:`SameVendorRefused` BEFORE building any prompt or writing
       any disk surface.
    3. :data:`_OFFLINE_ENV` truthy → synthetic
       ``dispatch_skipped_offline`` envelope; no executor invoked.
    4. Otherwise: build prompt + dispatch via injected ``dispatch=``
       (test seam) OR :func:`get_executor` (production) → parse
       response → write transcript + envelope.

    The ``dispatch=`` seam is the test boundary; production path always
    routes through :data:`executors.AGENT_REGISTRY` so the resolved
    agent IS the agent invoked.
    """
    plan_dir = Path(plan_dir).resolve()
    if not plan_dir.is_dir():
        raise CompletionDispatchError(f"plan_dir does not exist: {plan_dir}")

    auditor = _resolve_auditor_or_translate_same_vendor(plan_dir, implementer_agent)

    _offline = _is_truthy_env(os.environ.get(_OFFLINE_ENV))
    # Plan 2026-06-01-001 F009 — config-readiness pre-flight runs BEFORE the
    # lower-level auditor-name validation on the real paid path, so a bad role
    # (e.g. the D065 `Codex-Auditor` split-brain) surfaces the actionable
    # ConfigNotReady (file/reason/remediation/dashboard) rather than the raw
    # name-format CompletionDispatchError (codex F009 audit i0, acceptance
    # #1/#2). Offline + the injected ``dispatch=`` test seam are not paid work
    # and intentionally bypass the gate.
    if dispatch is None and not _offline:
        _assert_config_ready_for_completion(
            implementer_agent=implementer_agent,
            auditor=auditor,
            caps_path=caps_path,
            plan_dir=plan_dir,
        )
    _validate_auditor_name(auditor)

    # F002 — append-only iterations: derive the next free slot when the
    # caller did not pin one; a pinned-but-colliding iteration is refused
    # by the writer (overwrite impossible by construction).
    if iteration is None:
        iteration = _next_iteration(plan_dir, auditor)

    if _offline:
        return _emit_offline_envelope(plan_dir, auditor, iteration, implementer_agent)

    contract = _load_objective_contract(plan_dir)
    features = _load_features(plan_dir)
    manifest = _build_evidence_manifest(plan_dir)
    prompt = _build_audit_prompt(contract, features, findings, manifest, plan_dir=plan_dir)

    if dispatch is not None:
        raw_response = dispatch(auditor, prompt)
    else:
        # Real paid path. Config-readiness was already enforced above (F009),
        # before auditor-name validation.
        raw_response = _dispatch_via_executor(auditor, prompt, plan_dir=plan_dir)

    # F001 — sanitize BEFORE parsing so the in-memory transcript the gate
    # consumes is exactly what disk holds (no divergence).
    raw_response = sanitize_capture(raw_response)
    status, dispositions = _parse_audit_response(raw_response, findings)

    transcript_path = _transcript_path(plan_dir, auditor, iteration)
    envelope_path = _envelope_path(plan_dir, auditor, iteration)
    transcript = CompletionAuditTranscript(
        auditor_agent=auditor,
        implementer_agent=implementer_agent,
        status=status,
        iteration=iteration,
        findings_dispositions=dispositions,
        transcript_path=sanitize_capture(str(transcript_path)),
        envelope_path=sanitize_capture(str(envelope_path)),
        generated_at=_utc_now_iso(),
        raw_response=raw_response,
    )
    _write_envelope(plan_dir, transcript, raw_response)
    return transcript


__all__ = [
    "CompletionAuditTranscript",
    "CompletionDispatchError",
    "DispatchFn",
    "FindingDisposition",
    "SameVendorRefused",
    "dispatch_completion_audit",
]
