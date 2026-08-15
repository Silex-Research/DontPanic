"""Run the plan's declared regression on the host, between implementer and auditor.

The auditor runs under `codex --sandbox read-only` (D012) so the *kernel*, not
a prompt, guarantees it cannot mutate the repo. The price is that it can
`--collect-only` but never execute: five consecutive audits on plan
2026-08-13-001 reported "no executed regression evidence … this read-only
environment could collect but not execute tests because no writable temporary
directory exists". Nothing else in the harness ran tests either, so a feature
could sign off with zero executed proof.

This module keeps D012 intact and moves execution to the only participant that
was always trusted with the real filesystem: the supervisor. It runs the
plan-declared command, persists raw output under ``evidence/``, and hands the
auditor a path plus a bounded tail to judge.

Making the supervisor an executor of plan-declared commands is a real change
in what the harness will do, so the safety posture is deliberately narrow:

* **Opt-in.** No ``verification`` block in ``plan.md`` means nothing runs.
* **Guarded.** Every command passes through :mod:`command_guard` first — the
  same policy that governs what agents may run governs what the supervisor
  runs on their behalf. A rejected command never reaches a subprocess.
* **Contained.** ``cwd`` must resolve inside the repo root.
* **Honest.** "refused", "error" (could not run), "timed_out", and "failed"
  (ran, came back red) are four distinct statuses. Collapsing them would let
  a broken runner read downstream as a passing suite — the exact failure this
  module exists to prevent.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dontpanic_orchestrate import command_guard

DEFAULT_TIMEOUT_SECONDS = 1800
"""Half an hour. Long enough for a real suite, short enough that a hung
runner surfaces as `timed_out` inside one volley rather than wedging it."""

TAIL_CHARS = 4000
"""How much of the output rides into the auditor prompt. The full log always
lands on disk; the auditor is given the path and can read it."""


@dataclass(frozen=True)
class VerificationSpec:
    """What ``plan.md`` declared. ``cwd`` is relative to the repo root."""

    command: str
    cwd: str = "."


@dataclass(frozen=True)
class VerificationResult:
    status: str  # passed | failed | timed_out | error | refused
    command: str
    exit_code: int | None
    output_path: Path | None
    tail: str
    reason: str | None = None

    @property
    def ran(self) -> bool:
        return self.status in {"passed", "failed", "timed_out"}


def spec_from_plan(plan: object) -> VerificationSpec | None:
    """Read the optional ``verification`` block off a plan dict or model.

    Returns None whenever a command is absent — verification is opt-in, and a
    half-declared block must never be guessed at.
    """
    block = _get(plan, "verification")
    if block is None:
        return None
    command = _get(block, "command")
    if not command or not str(command).strip():
        return None
    cwd = _get(block, "cwd") or "."
    return VerificationSpec(command=str(command), cwd=str(cwd))


def run_verification(
    plan_dir: Path,
    spec: VerificationSpec,
    *,
    iteration: int,
    repo_root: Path,
    role: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    env: dict[str, str] | None = None,
) -> VerificationResult:
    """Execute ``spec`` and persist the result. Never raises on a red suite."""
    output_path = plan_dir / "evidence" / f"regression-{iteration}-{role}.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cwd, cwd_error = _resolve_cwd(repo_root, spec.cwd)
    if cwd_error is not None:
        return _refuse(spec, output_path, cwd_error, iteration, plan_dir, role)

    guard = command_guard.check_command(spec.command, env)
    if not guard.allowed:
        return _refuse(spec, output_path, guard.reason, iteration, plan_dir, role)

    try:
        argv = shlex.split(spec.command)
    except ValueError as exc:  # unbalanced quotes — guard already parsed, belt+braces
        return _refuse(spec, output_path, str(exc), iteration, plan_dir, role)

    try:
        proc = subprocess.run(  # noqa: S603 — argv list, shell=False, guard-checked above
            argv,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        body = _decode(exc.stdout) + _decode(exc.stderr)
        return _finish(
            "timed_out",
            spec,
            output_path,
            None,
            f"$ {spec.command}\n[timed out after {timeout_seconds}s]\n{body}",
            iteration,
            plan_dir,
            role,
            reason=f"exceeded {timeout_seconds}s",
        )
    except OSError as exc:
        # Binary missing, not executable, cwd vanished. "Could not run" is not
        # "the tests failed" — conflating them is how a broken runner reads as
        # a green suite.
        return _finish(
            "error",
            spec,
            output_path,
            None,
            f"$ {spec.command}\n[could not execute] {exc}",
            iteration,
            plan_dir,
            role,
            reason=str(exc),
        )

    body = f"$ {spec.command}\n{proc.stdout}{proc.stderr}"
    status = "passed" if proc.returncode == 0 else "failed"
    return _finish(
        status, spec, output_path, proc.returncode, body, iteration, plan_dir, role
    )


def render_context_block(result: VerificationResult | None) -> str:
    """The paragraph handed to the auditor. Silence must never read as green."""
    if result is None:
        return (
            "## Regression run\n\n"
            "No verification command is declared for this plan, so the supervisor "
            "ran nothing. Treat executed-test evidence as ABSENT — do not infer "
            "that the suite is green.\n"
        )

    lines = [
        "## Regression run (executed by the supervisor, not by you)",
        "",
        f"- command: `{result.command}`",
        f"- status: **{result.status}**",
        f"- exit code: {result.exit_code if result.exit_code is not None else 'n/a'}",
    ]
    if result.output_path is not None:
        lines.append(f"- full output: `{result.output_path}`")
    if result.reason:
        lines.append(f"- note: {result.reason}")
    lines += ["", "Tail of output:", "", "```", result.tail[-TAIL_CHARS:], "```", ""]
    if result.status != "passed":
        lines.append(
            "This run did not pass. Do not sign off on the strength of the "
            "implementer's narrative alone."
        )
    return "\n".join(lines)


def _refuse(
    spec: VerificationSpec,
    output_path: Path,
    reason: str,
    iteration: int,
    plan_dir: Path,
    role: str,
) -> VerificationResult:
    body = f"$ {spec.command}\n[refused before execution] {reason}"
    return _finish(
        "refused", spec, output_path, None, body, iteration, plan_dir, role, reason=reason
    )


def _finish(
    status: str,
    spec: VerificationSpec,
    output_path: Path,
    exit_code: int | None,
    body: str,
    iteration: int,
    plan_dir: Path,
    role: str,
    *,
    reason: str | None = None,
) -> VerificationResult:
    output_path.write_text(body)
    sidecar = output_path.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "status": status,
                "command": spec.command,
                "cwd": spec.cwd,
                "exit_code": exit_code,
                "iteration": iteration,
                "role": role,
                "output_path": str(output_path),
                "reason": reason,
            },
            indent=2,
        )
        + "\n"
    )
    return VerificationResult(
        status=status,
        command=spec.command,
        exit_code=exit_code,
        output_path=output_path,
        tail=body[-TAIL_CHARS:],
        reason=reason,
    )


def _resolve_cwd(repo_root: Path, cwd: str) -> tuple[Path, str | None]:
    root = repo_root.resolve()
    target = (root / cwd).resolve()
    if target != root and root not in target.parents:
        return target, f"cwd {cwd!r} resolves outside the repo root {root}"
    if not target.is_dir():
        return target, f"cwd {cwd!r} is not a directory"
    return target, None


def _decode(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


def _get(obj: object, name: str):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "VerificationResult",
    "VerificationSpec",
    "render_context_block",
    "run_verification",
    "spec_from_plan",
]
