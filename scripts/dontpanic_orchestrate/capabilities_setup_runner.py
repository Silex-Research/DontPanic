"""Plan 2026-05-22-004 F002 — governed automatable-step runner.

Adds the ``--automate-safe`` mode on top of the F001 planning surface.
Only steps marked ``automatable=true`` are eligible, and only when the
declared ``command_template`` passes a **positive allowlist**: the first
shlex token must be one of a small enumerated set of trusted binaries
(``npm install``, the project's own ``dontpanic`` CLI, ``echo``/``printf``
for synthetic test steps). Everything else — including syntactically
clean but dangerous commands like ``git push origin main``,
``gh repo delete owner/repo --yes``, or
``firebase deploy --only functions`` — is denied. Shell metacharacters,
unsubstituted ``<PLACEHOLDER>`` tokens, and env-prefix syntax are also
refused before the head check, so the per-step denial reason is the
most-specific failure cause.

Human-required steps are skipped with the manifest's
``human_required_reason``; capability status is rebuilt after every
attempted step so probe/requires changes are visible in the report.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from dontpanic_orchestrate.capabilities import CapabilityManifest, SetupStep
from dontpanic_orchestrate.capabilities_status import CapabilityStatusResult

# Shell metacharacters we refuse outright. They imply pipelines, redirection,
# command chaining, subshells, or globbing — none of which the v0 runner can
# evaluate safely from a manifest string.
_SHELL_METACHARS = re.compile(r"[|&;<>`$()*?\[\]\\\"']|&&|\|\|")

# Unsubstituted manifest placeholder, e.g. <YOUR_FIREBASE_PROJECT_ID>.
_PLACEHOLDER = re.compile(r"<[A-Za-z0-9_./-]+>")

# Positive allowlist: ``command_head -> {allowed second tokens}`` (or ``None``
# meaning any second token is acceptable). Heads not in this map are denied
# unconditionally. The set is intentionally tiny — F002 is a governed runner
# for the few setup steps an operator can reasonably opt into automating; any
# new entry here is a security-relevant change that warrants review.
#
#   npm        — package installs. Subcommands restricted so a manifest cannot
#                accidentally invoke ``npm publish`` or run arbitrary scripts.
#   dontpanic  — the project's own CLI; we own its semantics.
#   echo/printf — test/diagnostic only (synthetic manifests in tests).
#   true/false — used by some idempotency probes; trivially safe.
_ALLOWED_HEADS: Mapping[str, frozenset[str] | None] = {
    "npm": frozenset({"install", "ci", "ls", "list", "view", "doctor"}),
    "dontpanic": None,
    "echo": None,
    "printf": None,
    "true": None,
    "false": None,
}


@dataclass(frozen=True)
class AllowlistDecision:
    """Outcome of evaluating a command_template against the F002 policy."""

    allow: bool
    reason: str


@dataclass(frozen=True)
class CommandResult:
    """Captured stdout/stderr/exit_code from one executed command."""

    exit_code: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Strategy for executing an allowlisted command.

    Production wires :class:`SubprocessRunner`; tests inject a fixture that
    records calls without spawning processes. Both return :class:`CommandResult`.
    """

    def run(self, argv: Sequence[str]) -> CommandResult: ...


class SubprocessRunner:
    """Default runner — ``subprocess.run`` with ``shell=False`` and tail capture."""

    def __init__(self, tail_chars: int = 2000) -> None:
        self._tail_chars = tail_chars

    def run(self, argv: Sequence[str]) -> CommandResult:
        try:
            completed = subprocess.run(  # noqa: S603 — argv is shell=False
                list(argv),
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            # ``FileNotFoundError``, ``PermissionError`` and friends — the
            # spawn never produced a CompletedProcess. Surface the failure
            # as a non-zero ``CommandResult`` so the F002 report still
            # records the attempt and the post-step status probe still runs.
            # Exit code 127 mirrors the conventional Unix "command not found"
            # signal so downstream parsers do not need a special case.
            return CommandResult(
                exit_code=127,
                stdout="",
                stderr=_tail(f"failed to spawn {argv[0]!r}: {exc}", self._tail_chars),
            )
        return CommandResult(
            exit_code=completed.returncode,
            stdout=_tail(completed.stdout or "", self._tail_chars),
            stderr=_tail(completed.stderr or "", self._tail_chars),
        )


StatusProbe = Callable[[CapabilityManifest], CapabilityStatusResult]


# ── allowlist evaluation ─────────────────────────────────────────────────


def evaluate_command_template(template: str | None) -> AllowlistDecision:
    """Decide whether ``template`` is eligible for governed execution.

    Acceptance #3: unsafe templates are denied with an explanation. The
    policy is **default-deny**: a template must (1) contain no shell
    features or unsubstituted placeholders and (2) have its first shlex
    token enumerated in :data:`_ALLOWED_HEADS`. Heads with a non-``None``
    sub-allowlist (currently ``npm``) must also match an allowed
    sub-command. Anything else — including syntactically clean dangerous
    commands like ``git push origin main`` or ``firebase deploy …`` — is
    denied.
    """

    if template is None:
        return AllowlistDecision(
            allow=False,
            reason="no command_template declared in manifest",
        )
    stripped = template.strip()
    if not stripped:
        return AllowlistDecision(
            allow=False,
            reason="command_template is empty",
        )
    if _PLACEHOLDER.search(stripped):
        return AllowlistDecision(
            allow=False,
            reason="command_template contains unsubstituted <PLACEHOLDER> token",
        )
    if _SHELL_METACHARS.search(stripped):
        return AllowlistDecision(
            allow=False,
            reason="command_template contains shell metacharacters or quoting",
        )
    try:
        argv = shlex.split(stripped)
    except ValueError as exc:
        return AllowlistDecision(
            allow=False,
            reason=f"command_template failed shell tokenization: {exc}",
        )
    if not argv:
        return AllowlistDecision(
            allow=False,
            reason="command_template tokenized to empty argv",
        )
    head = argv[0]
    if "=" in head:
        # Bare VAR=value prefixes imply env-injection semantics that
        # subprocess.run with shell=False will not honor — reject so the
        # operator does not silently get a broken invocation.
        return AllowlistDecision(
            allow=False,
            reason="command_template uses VAR=value env-prefix syntax",
        )
    if head not in _ALLOWED_HEADS:
        return AllowlistDecision(
            allow=False,
            reason=(
                f"command head {head!r} is not on the F002 allowlist "
                f"(allowed heads: {sorted(_ALLOWED_HEADS)!r})"
            ),
        )
    allowed_subs = _ALLOWED_HEADS[head]
    if allowed_subs is not None:
        sub = argv[1] if len(argv) > 1 else None
        if sub is None or sub not in allowed_subs:
            return AllowlistDecision(
                allow=False,
                reason=(
                    f"{head} subcommand {sub!r} is not on the allowlist "
                    f"(allowed: {sorted(allowed_subs)!r})"
                ),
            )
    return AllowlistDecision(allow=True, reason="passes allowlist policy")


# ── step outcome + report ────────────────────────────────────────────────


@dataclass(frozen=True)
class StepOutcome:
    """Per-step record for the run report.

    ``decision`` is a closed set: ``executed`` | ``denied_unsafe`` |
    ``skipped_human_required`` | ``skipped_no_command``.
    """

    step_id: str
    automatable: bool
    decision: str
    reason: str
    command: str | None
    argv: tuple[str, ...] = ()
    exit_code: int | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None
    status_after: str | None = None


@dataclass(frozen=True)
class AutomateSafeReport:
    """Summary of a single ``--automate-safe --confirm`` run."""

    capability_id: str
    confirm: bool
    before_status: str
    after_status: str
    outcomes: tuple[StepOutcome, ...] = field(default_factory=tuple)


# ── runner ───────────────────────────────────────────────────────────────


def run_automate_safe(
    manifest: CapabilityManifest,
    *,
    confirm: bool,
    command_runner: CommandRunner,
    status_probe: StatusProbe,
) -> AutomateSafeReport:
    """Execute allowlisted automatable steps and skip the rest.

    Acceptance covered here:
      #1 ``--automate-safe`` requires ``--confirm`` — enforced by the
         caller, but we also raise if ``confirm`` is False so the runner
         is safe to import without going through the CLI.
      #2 Human-required steps never execute.
      #3 Unsafe templates are denied with an explanation in ``StepOutcome``.
      #4 Allowlisted steps run via the injected ``command_runner``.
      #5 ``status_probe`` is invoked once before the sweep and once after
         each executed step so the report reflects requires/probe changes.
    """

    if not confirm:
        raise ValueError(
            "run_automate_safe requires confirm=True; --automate-safe must "
            "be paired with --confirm at the CLI layer"
        )

    before = status_probe(manifest)
    outcomes: list[StepOutcome] = []
    latest_status_value = before.status.value

    for step in manifest.setup_steps:
        outcome = _process_step(
            step,
            command_runner=command_runner,
            status_probe=status_probe,
            manifest=manifest,
            latest_status_value=latest_status_value,
        )
        outcomes.append(outcome)
        # Track latest observed status so a later denied/skipped step still
        # reports the most-recent post-execution status.
        if outcome.status_after is not None:
            latest_status_value = outcome.status_after

    after = status_probe(manifest)
    return AutomateSafeReport(
        capability_id=manifest.id,
        confirm=confirm,
        before_status=before.status.value,
        after_status=after.status.value,
        outcomes=tuple(outcomes),
    )


def _process_step(
    step: SetupStep,
    *,
    command_runner: CommandRunner,
    status_probe: StatusProbe,
    manifest: CapabilityManifest,
    latest_status_value: str,
) -> StepOutcome:
    if not step.automatable:
        reason = step.human_required_reason or "step is marked automatable=false"
        return StepOutcome(
            step_id=step.id,
            automatable=False,
            decision="skipped_human_required",
            reason=reason,
            command=step.command_template,
        )
    decision = evaluate_command_template(step.command_template)
    if not decision.allow:
        return StepOutcome(
            step_id=step.id,
            automatable=True,
            decision="denied_unsafe" if step.command_template else "skipped_no_command",
            reason=decision.reason,
            command=step.command_template,
        )
    argv = tuple(shlex.split(step.command_template or ""))
    result = command_runner.run(argv)
    status_after = status_probe(manifest)
    return StepOutcome(
        step_id=step.id,
        automatable=True,
        decision="executed",
        reason=decision.reason,
        command=step.command_template,
        argv=argv,
        exit_code=result.exit_code,
        stdout_tail=result.stdout,
        stderr_tail=result.stderr,
        status_after=status_after.status.value,
    )


# ── rendering ────────────────────────────────────────────────────────────


_DECISION_LABEL = {
    "executed": "executed",
    "denied_unsafe": "denied (unsafe)",
    "skipped_human_required": "skipped (human-required)",
    "skipped_no_command": "skipped (no command)",
}


def render_report(report: AutomateSafeReport) -> str:
    """Render an :class:`AutomateSafeReport` as a human-readable summary."""

    lines: list[str] = []
    lines.append(f"capability: {report.capability_id}")
    lines.append(f"before_status: {report.before_status}")
    lines.append(f"after_status:  {report.after_status}")
    lines.append("")
    lines.append("Setup run outcomes:")
    for index, outcome in enumerate(report.outcomes, start=1):
        label = _DECISION_LABEL.get(outcome.decision, outcome.decision)
        lines.append(f"  {index:>2}. [{label}] {outcome.step_id}")
        if outcome.command is not None:
            lines.append(f"      command: {outcome.command}")
        lines.append(f"      reason:  {outcome.reason}")
        if outcome.decision == "executed":
            lines.append(f"      exit_code: {outcome.exit_code}")
            if outcome.stdout_tail:
                lines.append(f"      stdout: {_inline(outcome.stdout_tail)}")
            if outcome.stderr_tail:
                lines.append(f"      stderr: {_inline(outcome.stderr_tail)}")
            if outcome.status_after:
                lines.append(f"      status_after: {outcome.status_after}")
    return "\n".join(lines) + "\n"


# ── helpers ──────────────────────────────────────────────────────────────


def _tail(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return "…" + text[-max_chars:]


def _inline(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= 200:
        return collapsed
    return collapsed[:197] + "..."


__all__ = [
    "AllowlistDecision",
    "AutomateSafeReport",
    "CommandResult",
    "CommandRunner",
    "StatusProbe",
    "StepOutcome",
    "SubprocessRunner",
    "evaluate_command_template",
    "render_report",
    "run_automate_safe",
]
