"""F009 (Plan 2026-06-01-001) — actionable config-readiness pre-flight.

DontPanic must never abort a dispatch (or a plan-close goal-completion audit)
with a low-level schema crash because a config file is invalid/empty or a role
is misconfigured. This module is the single, reusable pre-flight check that runs
BEFORE any paid work and turns those failure modes into a clean, actionable
readiness result: the offending file, the precise reason, a VALIDATED
remediation command (one that passes ``command_validation.validate_command_tokens``
so it is runnable), and a dashboard pointer.

Born from the onboarding-v0 caps-file hard-stop (D039) and the D065
Grok-Builder/Codex-Auditor role split-brain.

Pure: no network, no mutation. The only I/O is reading the config files it
validates (via ``quota_caps_loader``); callers pass role values + the registered
executor set explicitly so the check stays testable and side-effect free.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from dontpanic_orchestrate import command_validation, quota_caps_loader

# A role value must be a registered-executor id: lowercase, starts with a
# letter, then lowercase/digit/_/-. The D065 split-brain values
# ("Grok-Builder", "Codex-Auditor") fail this (uppercase) — that is the bug
# this check surfaces instead of letting it crash mid-volley.
ROLE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

# Dashboard affordance pointer (acceptance #4). Kept as one runnable command so
# the operator has a single place to inspect/fix config.
DASHBOARD_POINTER = (
    "Dashboard: run `python -m dontpanic_orchestrate dashboard serve` and open "
    "the config panel."
)


@dataclass(frozen=True)
class ConfigReadinessResult:
    """Outcome of a config-readiness pre-flight.

    ``ok=True`` means all checked config is usable. On failure, ``file`` names
    the offending config file (or ``"<roles>"`` for a role-config failure),
    ``reason`` is the precise human cause, ``remediation_tokens`` is the
    post-``dontpanic`` argv of a command that passes
    ``command_validation.validate_command_tokens`` (so it is runnable), and
    ``remediation`` is its full human-facing string.
    """

    ok: bool
    file: str | None = None
    reason: str | None = None
    remediation: str | None = None
    remediation_tokens: tuple[str, ...] = field(default_factory=tuple)
    dashboard: str = DASHBOARD_POINTER

    def render(self) -> str:
        """Operator-facing multi-line failure message (empty for ok)."""
        if self.ok:
            return ""
        return (
            f"Config not ready: {self.file}\n"
            f"  reason: {self.reason}\n"
            f"  remediation: {self.remediation}\n"
            f"  {self.dashboard}"
        )


def _command_string(tokens: tuple[str, ...]) -> str:
    return "python -m dontpanic_orchestrate " + " ".join(tokens)


def _readiness_failure(
    *, file: str, reason: str, remediation_tokens: tuple[str, ...]
) -> ConfigReadinessResult:
    """Build a failure result, asserting the remediation command is runnable.

    The validated-remediation invariant (acceptance #3) is enforced at
    construction: if a caller wires a remediation that does not pass
    ``validate_command_tokens`` that is a programming error surfaced loudly in
    tests, never a stranded operator."""
    res = command_validation.validate_command_tokens(list(remediation_tokens))
    if not res.ok:
        raise ValueError(
            f"config_readiness remediation {remediation_tokens!r} is not a "
            f"runnable dontpanic command: {res.errors}"
        )
    return ConfigReadinessResult(
        ok=False,
        file=file,
        reason=reason,
        remediation=_command_string(remediation_tokens),
        remediation_tokens=remediation_tokens,
    )


def check_quota_caps_readiness(caps_path: Path | None = None) -> ConfigReadinessResult:
    """Validate the quota-caps config file. A missing/empty/invalid file is a
    clean readiness failure (the D039 ``{}`` hard-stop), never a raised
    ``QuotaCapsError`` escaping into a volley."""
    caps_file = str(quota_caps_loader.effective_caps_path(caps_path))
    try:
        caps = quota_caps_loader.load(caps_path)
    except quota_caps_loader.QuotaCapsError as exc:
        return _readiness_failure(
            file=caps_file,
            reason=f"quota caps config is invalid: {exc}",
            remediation_tokens=("quota-caps", "init"),
        )
    # The caps file is vendor-keyed at the top level (claude/codex/gemini/grok),
    # NOT a vendors{} block (that's quota_STATE). "Empty" = no recognized vendor
    # cap entry — the D039 literal `{}` hard-stop case.
    if not isinstance(caps, dict) or not any(
        v in caps for v in quota_caps_loader.KNOWN_VENDORS
    ):
        return _readiness_failure(
            file=caps_file,
            reason="quota caps config is empty or has no per-vendor caps "
            "(an empty `{}` cannot gate any paid agent).",
            remediation_tokens=("quota-caps", "init"),
        )
    return ConfigReadinessResult(ok=True)


def check_role_readiness(
    roles: Iterable[str], *, registered_executors: Iterable[str]
) -> ConfigReadinessResult:
    """Validate role values against the registered-executor id pattern + set.

    Surfaces the D065 split-brain (e.g. ``Grok-Builder`` / ``Codex-Auditor``):
    a role that is not a registered executor id matching ``ROLE_ID_RE`` is a
    clean readiness failure with a runnable remediation, not a mid-volley
    KeyError when the registry lookup misses."""
    registered = set(registered_executors)
    for role in roles:
        if not isinstance(role, str) or not ROLE_ID_RE.match(role):
            return _readiness_failure(
                file="<roles>",
                reason=(
                    f"role {role!r} is not a valid executor id "
                    f"(must match {ROLE_ID_RE.pattern} — lowercase, no spaces "
                    f"or capitals; the D065 Grok-Builder/Codex-Auditor shape "
                    f"fails this)."
                ),
                remediation_tokens=("roles", "show"),
            )
        if role not in registered:
            return _readiness_failure(
                file="<roles>",
                reason=(
                    f"role {role!r} is not a registered executor "
                    f"(registered: {sorted(registered)})."
                ),
                remediation_tokens=("roles", "show"),
            )
    return ConfigReadinessResult(ok=True)


def check_config_readiness(
    *,
    roles: Iterable[str],
    registered_executors: Iterable[str],
    caps_path: Path | None = None,
) -> ConfigReadinessResult:
    """Single pre-flight entry point: validate quota caps THEN role config.

    Returns the first failure (caps first — it blocks every paid call; then
    roles), or ``ok`` when both are usable. Call this before any paid work
    (dispatch OR plan-close goal-completion audit), distinct from the in-loop
    budget breaker (which handles a *tripped* quota at runtime, not a
    *malformed* config at pre-flight)."""
    caps_result = check_quota_caps_readiness(caps_path)
    if not caps_result.ok:
        return caps_result
    return check_role_readiness(roles, registered_executors=registered_executors)


__all__ = [
    "DASHBOARD_POINTER",
    "ROLE_ID_RE",
    "ConfigReadinessResult",
    "check_config_readiness",
    "check_quota_caps_readiness",
    "check_role_readiness",
]
