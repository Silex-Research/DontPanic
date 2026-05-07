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

import json
import os
import re
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

_AUDIT_DIR_NAME: str = "audit"
"""Subdirectory under ``POST_IMPL_DIR`` for envelope + transcript files.
Filename pattern: ``audit-<auditor>-<iter>.json`` /
``audit-<auditor>-<iter>.transcript.txt``."""

_AUDITOR_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
"""Auditor agent names go into filenames; pin the shape to lowercase
ascii + dash/underscore so we can never write a path-traversal filename."""


_RECOGNIZED_CODEX_STREAM_TYPES: frozenset[str] = frozenset(
    {
        "thread.started",
        "turn.started",
        "turn.completed",
        "item.started",
        "item.completed",
    }
)
"""D008(a) shape gate. The codex CLI emits its turn as line-delimited
JSON; each event has a top-level ``type`` field. This frozenset is the
positive recognition signal — :func:`_extract_codex_streaming_payload`
returns ``None`` unless at least one parsed line carries a ``type`` in
this set. Arbitrary JSONL whose objects happen to be parseable per-line
but carry no recognized event ``type`` is NOT treated as a codex stream
(it falls through to the existing raw-JSON path)."""

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
      treats this as block; operator overrides or fixes."""

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


def _read_prompt_template() -> str:
    """Read the markdown template once per call.

    Re-reading is cheap (small file, infrequent call) and avoids the
    test-time hazard of caching a file the test fixture replaced."""
    if not _PROMPT_TEMPLATE_PATH.is_file():
        raise CompletionDispatchError(
            f"completion-audit prompt template missing at {_PROMPT_TEMPLATE_PATH}"
        )
    return _PROMPT_TEMPLATE_PATH.read_text()


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


def _serialize_manifest(manifest) -> str:
    """Sorted-key JSON dump of the rebuilt evidence manifest. Each
    EvidenceRef serializes via its Pydantic model_dump."""
    payload = [ref.model_dump(mode="json", exclude_none=True) for ref in manifest]
    payload.sort(key=lambda r: (r.get("uri") or "", r.get("hash") or ""))
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def _build_audit_prompt(
    contract,
    features: list[dict],
    findings: Iterable[CompletionFinding],
    manifest,
) -> str:
    """Render the prompt template by substituting the four context
    blocks. Uses ``str.replace`` rather than ``str.format`` so embedded
    ``{`` / ``}`` characters in the JSON payloads do not collide with
    the template's placeholders."""
    template = _read_prompt_template()
    return (
        template.replace("{contract}", _serialize_contract(contract))
        .replace("{features}", _serialize_features(features))
        .replace("{findings}", _serialize_findings(findings))
        .replace("{evidence_manifest}", _serialize_manifest(manifest))
    )


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


def _extract_codex_streaming_payload(response: str) -> str | None:
    """Conservative codex JSONL streaming-output extractor (Plan F2C-D008).

    Walk ``response`` line-by-line. Track two pieces of state:

    - ``saw_recognized_shape``: flips True the first time a line parses
      as a JSON object whose ``type`` field is in
      :data:`_RECOGNIZED_CODEX_STREAM_TYPES`. This is the D008(a)
      positive recognition gate — without it we would silently
      misidentify arbitrary line-delimited JSON (or even single-line
      raw JSON arrays) as codex streams.
    - ``agent_message_texts``: every ``item.completed`` event whose
      ``item.type == 'agent_message'`` contributes its non-empty
      ``item.text`` to this list, in stream order. D008(b) — partial
      ``item.started`` events without matching completion are ignored;
      non-``agent_message`` ``item.type`` values (``tool_use``,
      ``function_call``, ``reasoning``, ``command_execution``, ...)
      are ignored.

    Lines that fail :func:`json.loads` are skipped (per-line tolerance —
    a single malformed line MUST NOT abort the scan; partial-write lines
    have been observed in real codex streams). Lines that parse but are
    not dicts, or are dicts whose ``type`` is unknown, are skipped.

    Return rules (deterministic):

    1. ``saw_recognized_shape == False`` → ``None``. Input is not a
       codex stream; caller falls through to existing raw-JSON path.
    2. Recognized shape seen but ``agent_message_texts`` is empty →
       ``None``. The stream had codex events but no completion text;
       caller falls through.
    3. Otherwise → ``agent_message_texts[-1]``. D008(c) deterministic
       last-wins ambiguity resolution.

    The return value, when non-None, is always a string that the
    downstream :func:`_strip_code_fence` + JSON parser can consume.
    Helper returning ``None`` NEVER short-circuits the pipeline — the
    raw path runs on the original ``response`` and surfaces an explicit
    ``dispatch_response_malformed`` envelope status if both fail.
    NO silent empty result. (D008(d).)"""
    if not response:
        return None

    saw_recognized_shape = False
    agent_message_texts: list[str] = []

    for line in response.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type not in _RECOGNIZED_CODEX_STREAM_TYPES:
            continue
        saw_recognized_shape = True
        if event_type != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "agent_message":
            continue
        text = item.get("text", "")
        if not isinstance(text, str) or not text.strip():
            continue
        agent_message_texts.append(text)

    if not saw_recognized_shape:
        return None
    if not agent_message_texts:
        return None
    return agent_message_texts[-1]


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


def _envelope_path(plan_dir: Path, auditor: str, iteration: int) -> Path:
    return _audit_dir(plan_dir) / f"audit-{auditor}-{iteration}.json"


def _transcript_path(plan_dir: Path, auditor: str, iteration: int) -> Path:
    return _audit_dir(plan_dir) / f"audit-{auditor}-{iteration}.transcript.txt"


def _write_envelope(
    plan_dir: Path,
    transcript: CompletionAuditTranscript,
    raw_response: str,
) -> None:
    """Write transcript + envelope to disk. The transcript is the raw
    auditor response (verbatim); the envelope is the parsed
    :class:`CompletionAuditTranscript` JSON."""
    out_dir = _audit_dir(plan_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    Path(transcript.transcript_path).write_text(raw_response)
    Path(transcript.envelope_path).write_text(
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
        transcript_path=str(transcript_path),
        envelope_path=str(envelope_path),
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
    executor = get_executor(auditor)
    if not executor.is_available():
        raise CompletionDispatchError(
            f"resolved auditor {auditor!r} is not available — {executor.availability_hint()}"
        )

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
    )
    result = executor.dispatch(task)
    return result.raw_response or ""


def dispatch_completion_audit(
    plan_dir: Path,
    *,
    findings: list[CompletionFinding],
    implementer_agent: str | None = None,
    iteration: int = 1,
    dispatch: DispatchFn | None = None,
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
    _validate_auditor_name(auditor)

    if _is_truthy_env(os.environ.get(_OFFLINE_ENV)):
        return _emit_offline_envelope(plan_dir, auditor, iteration, implementer_agent)

    contract = _load_objective_contract(plan_dir)
    features = _load_features(plan_dir)
    manifest = _build_evidence_manifest(plan_dir)
    prompt = _build_audit_prompt(contract, features, findings, manifest)

    if dispatch is not None:
        raw_response = dispatch(auditor, prompt)
    else:
        raw_response = _dispatch_via_executor(auditor, prompt, plan_dir=plan_dir)

    status, dispositions = _parse_audit_response(raw_response, findings)

    transcript_path = _transcript_path(plan_dir, auditor, iteration)
    envelope_path = _envelope_path(plan_dir, auditor, iteration)
    transcript = CompletionAuditTranscript(
        auditor_agent=auditor,
        implementer_agent=implementer_agent,
        status=status,
        iteration=iteration,
        findings_dispositions=dispositions,
        transcript_path=str(transcript_path),
        envelope_path=str(envelope_path),
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
