"""Plan 2026-05-22-004 F003 — setup-run evidence record.

Every governed ``--automate-safe --confirm`` run from F002 produces a
durable evidence record that summarizes what was attempted, what was
skipped, what was denied, and what the operator still has to do. The
record is written either to an operator-local DontPanic state path
(``$DONTPANIC_HOME/setup-runs/<capability_id>-<timestamp>.json``,
default ``~/.dontpanic/setup-runs/…``) or to an explicit ``evidence_dir``
when the runner is invoked during a plan and the supervisor wants the
record to live alongside the plan's other evidence.

**Secret discipline (acceptance #2).** The record carries only
identifiers, declared command templates (with their manifest
placeholders preserved), exit codes, and short, redacted summaries of
captured stdout/stderr. ``requires`` env tokens appear as names only —
never with their values. A best-effort secret-pattern scrubber is
applied to *every* free-text field that lands on disk —
``command_template``, ``argv`` elements, ``reason``,
``stdout_tail``, and ``stderr_tail`` — and redacts JWT-shaped tokens,
``sk_*``/``ghp_*``-style credential prefixes,
``Bearer …``/``Authorization`` headers, ``token=value``-shaped key=value
pairs, and ``NAME=value`` env-prefix syntax. F002 already refuses
unsubstituted ``<PLACEHOLDER>`` tokens at allowlist evaluation, but a
manifest whose ``command_template`` embeds a real credential (e.g. an
allowlisted ``npm install --token=ghp_…``) would otherwise round-trip
that value into ``argv`` and the evidence file; the scrubber is the
last line of defense against that leak.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.capabilities import CapabilityManifest
from dontpanic_orchestrate.capabilities_setup_runner import (
    AutomateSafeReport,
    StepOutcome,
)
from dontpanic_orchestrate.global_config import dontpanic_home

EVIDENCE_SCHEMA_VERSION = "1.0.0"
EVIDENCE_FILE_MODE = 0o600
EVIDENCE_DIR_MODE = 0o700
DEFAULT_EVIDENCE_SUBDIR = "setup-runs"

# Cap inline stdout/stderr summaries so a single chatty step cannot blow
# up the evidence file. The F002 runner already tail-truncates to
# ``tail_chars``; this is a defense-in-depth ceiling on what lands on disk.
_OUTPUT_TAIL_MAX_CHARS = 1000

# Best-effort secret patterns. The intent is *not* to be exhaustive
# (that's the secret-scanner's job) but to refuse to persist anything
# that obviously *looks* like a credential. Each pattern emits the same
# ``[redacted-secret]`` token so the resulting evidence is greppable.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # ``Authorization: Bearer <jwt-or-opaque>``. The header name is kept;
    # the value collapses to the redaction marker.
    re.compile(r"(Authorization\s*:\s*)[^\r\n]+", re.IGNORECASE),
    # ``Bearer <token>`` outside a header context.
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-+/=]{8,}\b"),
    # Stripe / GitHub / OpenAI style prefixed tokens (``<prefix>_<body>``).
    re.compile(r"\b(sk|pk|rk|whsec|ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_\-]{16,}\b"),
    # OpenAI project keys and similar dash-separated secret forms.
    re.compile(r"\b(sk|pk|rk|whsec)-[A-Za-z0-9_\-]{16,}\b"),
    # AWS access key ids.
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # Slack tokens — ``xoxb-…``/``xoxp-…`` use dashes, not underscores.
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{16,}\b"),
    # Anthropic key format.
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"),
    # JWT (three dot-separated base64url segments).
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    # Bare base64-ish credential dropped after ``token=`` / ``apikey=`` /
    # ``password=`` etc. — keeps the key, drops the value.
    re.compile(
        r"\b(token|api[_-]?key|apikey|password|passwd|secret|access[_-]?key|client[_-]?secret)\s*[=:]\s*[^\s\"',;&|]+",
        re.IGNORECASE,
    ),
    # ``NAME=value`` env-prefix syntax that survived the command (F002
    # denies these before execute, but a step rendered with a stale
    # value could still print one).
    re.compile(r"\b[A-Z][A-Z0-9_]{3,}=[^\s\"',;&|]{6,}"),
)


@dataclass(frozen=True)
class SetupRunEvidence:
    """Structured, sanitization-checked evidence for one setup run."""

    schema_version: str
    generated_at: str
    capability_id: str
    confirm: bool
    before_status: str
    after_status: str
    attempted_steps: tuple[dict[str, Any], ...]
    denied_steps: tuple[dict[str, Any], ...]
    skipped_human_required: tuple[dict[str, Any], ...]
    next_human_actions: tuple[dict[str, Any], ...]
    declared_requires: dict[str, tuple[str, ...]]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "capability_id": self.capability_id,
            "confirm": self.confirm,
            "before_status": self.before_status,
            "after_status": self.after_status,
            "attempted_steps": [dict(item) for item in self.attempted_steps],
            "denied_steps": [dict(item) for item in self.denied_steps],
            "skipped_human_required": [dict(item) for item in self.skipped_human_required],
            "next_human_actions": [dict(item) for item in self.next_human_actions],
            "declared_requires": {k: list(v) for k, v in self.declared_requires.items()},
        }


def build_evidence_record(
    report: AutomateSafeReport,
    manifest: CapabilityManifest,
    *,
    now: _dt.datetime | None = None,
) -> SetupRunEvidence:
    """Project an :class:`AutomateSafeReport` into the F003 evidence shape.

    Acceptance #1: the record names ``capability_id``, the attempted
    steps, the skipped human-required steps, before/after status, and
    the next human actions. Acceptance #2: no captured stdout/stderr,
    command line, or requires bucket value leaves this function without
    going through :func:`_sanitize_output`; ``requires`` is reported as
    declared names only — never values.
    """

    generated_at = (now if now is not None else _dt.datetime.now(_dt.timezone.utc)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    attempted: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []
    skipped_human: list[dict[str, Any]] = []
    for outcome in report.outcomes:
        if outcome.decision == "executed":
            attempted.append(_attempted_step_payload(outcome))
        elif outcome.decision in ("denied_unsafe", "skipped_no_command"):
            denied.append(_denied_step_payload(outcome))
        elif outcome.decision == "skipped_human_required":
            skipped_human.append(_skipped_human_payload(outcome))
        # The closed set above covers every value StepOutcome.decision
        # produces in F002; if a new decision is added without updating
        # the projection here, the value lands nowhere and the test
        # suite's shape assertions will catch the drift.

    next_actions = _next_human_actions(denied, skipped_human)

    declared_requires = {
        "commands": tuple(manifest.requires.commands),
        "env": tuple(manifest.requires.env),
        "files": tuple(manifest.requires.files),
        "services": tuple(manifest.requires.services),
        "auth": tuple(manifest.requires.auth),
        "config": tuple(manifest.requires.config),
    }

    return SetupRunEvidence(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        generated_at=generated_at,
        capability_id=report.capability_id,
        confirm=report.confirm,
        before_status=report.before_status,
        after_status=report.after_status,
        attempted_steps=tuple(attempted),
        denied_steps=tuple(denied),
        skipped_human_required=tuple(skipped_human),
        next_human_actions=tuple(next_actions),
        declared_requires=declared_requires,
    )


def _attempted_step_payload(outcome: StepOutcome) -> dict[str, Any]:
    return {
        "step_id": outcome.step_id,
        "decision": outcome.decision,
        "reason": _sanitize_text(outcome.reason),
        "command_template": _sanitize_text(outcome.command),
        "argv": _sanitize_argv(outcome.argv),
        "exit_code": outcome.exit_code,
        "stdout_tail": _sanitize_output(outcome.stdout_tail),
        "stderr_tail": _sanitize_output(outcome.stderr_tail),
        "status_after": outcome.status_after,
    }


def _denied_step_payload(outcome: StepOutcome) -> dict[str, Any]:
    return {
        "step_id": outcome.step_id,
        "decision": outcome.decision,
        "reason": _sanitize_text(outcome.reason),
        "command_template": _sanitize_text(outcome.command),
    }


def _skipped_human_payload(outcome: StepOutcome) -> dict[str, Any]:
    return {
        "step_id": outcome.step_id,
        "decision": outcome.decision,
        "reason": _sanitize_text(outcome.reason),
        "command_template": _sanitize_text(outcome.command),
    }


def _next_human_actions(
    denied: list[dict[str, Any]], skipped_human: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build the ``next_human_actions`` list.

    Two sources contribute: (a) every human-required skip — the
    operator must do it themselves; (b) every denied automatable step —
    the runner refused, so the operator must run it manually after
    substituting any ``<PLACEHOLDER>`` tokens. Each entry carries the
    step id, the reason the runner did not handle it, and the declared
    ``command_template`` (with placeholders preserved verbatim) so the
    operator can copy-paste once they've gathered the secrets.
    """

    actions: list[dict[str, Any]] = []
    for step in skipped_human:
        actions.append(
            {
                "step_id": step["step_id"],
                "reason": step["reason"],
                "kind": "human_required",
                "command_template": step["command_template"],
            }
        )
    for step in denied:
        actions.append(
            {
                "step_id": step["step_id"],
                "reason": step["reason"],
                "kind": "denied_unsafe",
                "command_template": step["command_template"],
            }
        )
    return actions


def _sanitize_output(value: str | None) -> str | None:
    """Cap length and redact secret-looking substrings.

    Returns ``None`` unchanged so the evidence does not invent an empty
    string where the runner saw no output. The cap is applied *before*
    redaction so a very long line cannot make the secret-pattern regex
    walk an unbounded buffer.
    """

    if value is None:
        return None
    if not value:
        return value
    if len(value) > _OUTPUT_TAIL_MAX_CHARS:
        truncated = value[-_OUTPUT_TAIL_MAX_CHARS:]
    else:
        truncated = value
    return _apply_secret_patterns(truncated)


def _sanitize_text(value: str | None) -> str | None:
    """Redact secret-looking substrings without truncation.

    Used for short evidence fields (``command_template``, ``reason``)
    where surface-area is the manifest author's responsibility but a
    leaked credential in the rendered template must still not survive.
    The output cap from :func:`_sanitize_output` is intentionally not
    applied — these fields are bounded by manifest semantics, not by
    runtime stdout volume.
    """

    if value is None:
        return None
    if not value:
        return value
    return _apply_secret_patterns(value)


def _sanitize_argv(argv: Sequence[str]) -> list[str]:
    """Apply :func:`_sanitize_text` to every argv element.

    ``argv`` is derived from ``shlex.split(command_template)`` for
    executed steps; any credential that survived
    :func:`_sanitize_text` on the template would otherwise land here
    as a bare positional token (e.g. ``--token=ghp_…``).
    """

    return [_sanitize_text(item) or "" for item in argv]


def _apply_secret_patterns(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_redaction_marker, redacted)
    return redacted


def _redaction_marker(match: re.Match[str]) -> str:
    """Replacement function that preserves the key half of ``key=value``.

    ``token=abc123`` becomes ``token=[redacted-secret]`` so the operator
    still sees *which* token was elided. Patterns without an ``=``/``:``
    boundary collapse to the bare marker.
    """

    text = match.group(0)
    for sep in ("=", ":"):
        if sep in text:
            head, _, _ = text.partition(sep)
            return f"{head}{sep}[redacted-secret]"
    return "[redacted-secret]"


def default_evidence_dir() -> Path:
    """``$DONTPANIC_HOME/setup-runs`` — operator-local, per-user."""

    return dontpanic_home() / DEFAULT_EVIDENCE_SUBDIR


def evidence_filename(capability_id: str, generated_at: str) -> str:
    """Build a stable, sortable filename for one setup-run record.

    The capability id is sanitized to ``[A-Za-z0-9._-]`` so a malformed
    or operator-typo'd id (e.g. embedded ``..``) cannot escape the
    target directory. ``generated_at`` is the ISO-8601 stamp from
    :class:`SetupRunEvidence`.
    """

    # Disallow path separators *and* leading dots / dot-runs so a typo'd
    # capability id like ``../../etc/passwd`` cannot reach a sibling
    # directory via the filename component. Trailing/leading separators
    # are stripped, then any ``..`` substring is collapsed to ``_``.
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", capability_id)
    safe_id = safe_id.strip("_-") or "unknown"
    safe_ts = generated_at.replace(":", "").replace("-", "")
    return f"{safe_id}-{safe_ts}.json"


def write_evidence(
    evidence: SetupRunEvidence,
    *,
    evidence_dir: Path | None = None,
) -> Path:
    """Persist the evidence JSON; return the path written.

    ``evidence_dir`` overrides the default operator-local
    ``$DONTPANIC_HOME/setup-runs`` location — the supervisor wires this
    to the plan's ``evidence/`` directory when a setup run is dispatched
    inside a plan. The parent directory is created mode 0700 and the
    file mode 0600 to match the rest of the DontPanic state surface.
    """

    target_dir = evidence_dir if evidence_dir is not None else default_evidence_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target_dir, EVIDENCE_DIR_MODE)
    except OSError:
        # Best-effort tightening — some filesystems (e.g. shared CI mounts)
        # refuse mode changes; the absence of tight perms is non-fatal
        # because evidence does not carry secret values by construction.
        pass
    target = target_dir / evidence_filename(
        evidence.capability_id, evidence.generated_at
    )
    payload = json.dumps(evidence.to_json_dict(), indent=2, sort_keys=True) + "\n"
    target.write_text(payload, encoding="utf-8")
    try:
        os.chmod(target, EVIDENCE_FILE_MODE)
        mode_bits = stat.S_IMODE(target.stat().st_mode)
        if mode_bits != EVIDENCE_FILE_MODE:
            os.chmod(target, EVIDENCE_FILE_MODE)
    except OSError:
        pass
    return target


__all__ = [
    "EVIDENCE_DIR_MODE",
    "EVIDENCE_FILE_MODE",
    "EVIDENCE_SCHEMA_VERSION",
    "SetupRunEvidence",
    "build_evidence_record",
    "default_evidence_dir",
    "evidence_filename",
    "write_evidence",
]
