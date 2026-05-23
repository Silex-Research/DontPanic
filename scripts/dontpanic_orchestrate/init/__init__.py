"""Plan 2026-05-19-002 F002 — `dontpanic init` interactive installer.

Walks the F001 :mod:`prereq_registry` probe sweep for a selected profile
(default ``core``), surfaces FAIL + WARN items with per-probe operator
confirmation, and executes safe auto-fixes via a STRICT ARGV ALLOWLIST
(``subprocess.run(argv: list[str], shell=False)`` — never shell strings).

Contract invariants (mirror plan acceptance):

  1. Default profile is ``core`` (NOT undefined; F001's doctor keeps no
     default — init is the operator-friendly entry point that picks one).
  2. Walker prompts per-probe for fail+warn; advisory items NEVER prompt.
  3. Auto-fix execution uses argv lists only. Shell-string ``fix_command``
     values are rejected at validator startup (``RegistryValidationError``)
     — fail fast, NOT at exec time.
  4. NO ``--auto-fix-safe-all`` batch flag in v0. Each fix is a per-probe
     confirmation. Operator can decline any individual fix and the walker
     continues with the next item.
  5. Package-manager installs (brew, pip) ship with ``auto_install_safe=
     False`` by default in the F001 registry. Promotion to ``True``
     requires per-probe opt-in (deferred to v1).
  6. ``--non-interactive`` exits 1 with structured JSON listing every
     fail+warn probe + its ``fix_command`` and activation context. No
     prompts, no auto-execution.
  7. Idempotent re-runs: each invocation calls ProbeRunner fresh. No
     state file. Re-run picks up new probe results automatically.
  8. NEVER auto-creates GitHub PATs. NEVER auto-generates Firebase SA
     keys. NEVER runs sudo or system-Python modifications.
  9. ``init_main(argv: list[str]) -> int`` returns exit codes:
       0   = ready
       1   = remaining fixes after the walk (or non-interactive with
             fail+warn present)
       2   = blocked (unrecoverable — e.g. invalid registry)
       130 = operator-aborted (Ctrl-C in interactive mode)

Public surface:

  * :func:`init_main`     — argparse + walker driver, console entry.
  * :class:`Walker`       — pure-Python walker, dependency-injected for
                            tests. ``subprocess_runner``, ``prompt_fn``,
                            ``output_fn``, and ``probe_runner`` are all
                            swappable.
  * :func:`validate_registry` — fail-fast registry validator. Rejects
                            non-list-of-string ``fix_command`` values.
  * :class:`RegistryValidationError` — raised by the validator.
  * :class:`WalkAction` / :class:`WalkResult` — structured walker output.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import prereq_registry as pr

DEFAULT_PROFILE = "core"

# Walker exit-code matrix (mirrors module docstring).
EXIT_READY = 0
EXIT_REMAINING = 1
EXIT_BLOCKED = 2
EXIT_ABORTED = 130


# ── errors ────────────────────────────────────────────────────────────────


class RegistryValidationError(ValueError):
    """Raised when the probe registry violates a walker invariant.

    The walker validates the registry at module-load time (NOT at exec
    time) so authoring mistakes — most notably shell-string
    ``fix_command`` values — surface at startup before any probe runs.
    """


def validate_registry(probes: list[pr.PrereqProbe]) -> None:
    """Walker startup validator. Fails fast on shell-string fix_command.

    The :class:`pr.PrereqProbe` dataclass already enforces this at
    ``__post_init__`` for probes constructed normally. The validator
    here catches probes that bypass the dataclass invariant (e.g. test
    fixtures that mutate ``__dict__`` directly, or future refactors).
    The double-check is the documented "validator rejects shell-string
    fix_command at startup" acceptance.
    """
    for probe in probes:
        cmd = probe.fix_command
        if not isinstance(cmd, list) or not all(isinstance(s, str) for s in cmd):
            raise RegistryValidationError(
                f"probe {probe.name!r} fix_command must be list[str] (strict argv "
                f"allowlist — shell strings rejected); got {type(cmd).__name__} "
                f"value {cmd!r}"
            )


# ── walker primitives ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class WalkAction:
    """Record of a single operator interaction during the walk."""

    probe_name: str
    decision: str  # "ran" | "declined" | "manual_acknowledged" | "skipped_pass"
    fix_command: list[str]
    return_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    elapsed_s: float = 0.0


@dataclass
class WalkResult:
    """Aggregate walker output."""

    profile: str
    initial: pr.SweepResult
    final: pr.SweepResult
    actions: list[WalkAction] = field(default_factory=list)
    non_interactive: bool = False
    aborted: bool = False

    def exit_code(self) -> int:
        # F002 walker exit-code matrix is NOT the doctor's strict 0/1/2
        # SweepResult shape (which returns 2 for FAIL). Walker reserves
        # EXIT_BLOCKED=2 for unrecoverable startup errors (invalid
        # registry) raised in init_main; any remaining fail/warn maps
        # to EXIT_REMAINING=1 regardless of interactive vs non-interactive.
        if self.aborted:
            return EXIT_ABORTED
        sweep = self.initial if self.non_interactive else self.final
        has_blocker = any(
            p.status in (pr.ProbeStatus.FAIL, pr.ProbeStatus.WARN)
            for p in sweep.probes
        )
        return EXIT_REMAINING if has_blocker else EXIT_READY


PromptFn = Callable[[str], str]
OutputFn = Callable[[str], None]
SubprocessRunner = Callable[..., subprocess.CompletedProcess]
ProbeRunnerFn = Callable[..., pr.SweepResult]


def _default_prompt(message: str) -> str:
    return input(message)


def _default_output(line: str) -> None:
    print(line)


# ── walker ────────────────────────────────────────────────────────────────


class Walker:
    """Drives the per-probe operator confirmation loop.

    Dependency-injected so tests can replace ``prompt_fn`` (input),
    ``output_fn`` (print), ``subprocess_runner`` (``subprocess.run``)
    and ``probe_runner`` (``pr.run_sweep``).

    Walker uses dependency injection rather than module-level mocking
    so the strict-argv invariant test can wrap the runner once and
    inspect every argv passed in. See ``test_init_walker_f002.py``.
    """

    def __init__(
        self,
        *,
        profile: str = DEFAULT_PROFILE,
        non_interactive: bool = False,
        repo_root: Path | None = None,
        probes: list[pr.PrereqProbe] | None = None,
        prompt_fn: PromptFn = _default_prompt,
        output_fn: OutputFn = _default_output,
        subprocess_runner: SubprocessRunner = subprocess.run,
        probe_runner: ProbeRunnerFn = pr.run_sweep,
        activation_context: pr.ActivationContext | None = None,
    ) -> None:
        if profile not in pr.PROFILE_NAMES:
            raise ValueError(
                f"Unknown profile {profile!r}; valid: {pr.PROFILE_NAMES}"
            )
        self.profile = profile
        self.non_interactive = non_interactive
        self.repo_root = repo_root or Path.cwd()
        self.probes = probes if probes is not None else pr.default_probes()
        # Fail fast on bad fix_command shapes — acceptance #4.
        validate_registry(self.probes)
        self.prompt_fn = prompt_fn
        self.output_fn = output_fn
        self.subprocess_runner = subprocess_runner
        self.probe_runner = probe_runner
        self.activation_context = activation_context

    # ── helpers ──────────────────────────────────────────────────────────

    def _run_sweep(self) -> pr.SweepResult:
        ctx = self.activation_context
        if ctx is None:
            ctx = pr.build_activation_context(self.repo_root)
        return self.probe_runner(
            profile=self.profile,
            probes=self.probes,
            activation_context=ctx,
        )

    def _probe_by_name(self, name: str) -> pr.PrereqProbe | None:
        for p in self.probes:
            if p.name == name:
                return p
        return None

    def _execute_argv(self, argv: list[str]) -> subprocess.CompletedProcess:
        # STRICT ARGV ALLOWLIST. Re-validate at exec time as defense in
        # depth — never pass a truthy shell kwarg, never join argv into
        # a shell string. Always invoke subprocess.run with shell=False.
        if not isinstance(argv, list) or not all(isinstance(s, str) for s in argv):
            raise RegistryValidationError(
                f"refusing to exec non-argv fix_command: {argv!r}"
            )
        return self.subprocess_runner(
            argv,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
        )

    def _prompt_yes_no(self, question: str) -> bool:
        """Operator confirms with Y/y/<enter>; declines with n/N/anything
        else. Ctrl-C / EOF surfaces as :class:`KeyboardInterrupt` for
        the caller to convert into exit 130."""
        answer = (self.prompt_fn(question) or "").strip().lower()
        if answer in ("", "y", "yes"):
            return True
        return False

    # ── public ───────────────────────────────────────────────────────────

    def run(self) -> WalkResult:
        initial = self._run_sweep()
        if self.non_interactive:
            return WalkResult(
                profile=self.profile,
                initial=initial,
                final=initial,
                actions=[],
                non_interactive=True,
            )

        actions: list[WalkAction] = []
        # Per-probe recheck (auditor F002-i1 finding #1): track the
        # latest known status for each probe name so that a fix to
        # probe A that incidentally clears probe B does not result in
        # B being prompted on its (stale) initial result.
        latest_status: dict[str, pr.ProbeStatus] = {
            p.name: p.status for p in initial.probes
        }
        try:
            for probe_result in initial.probes:
                # Re-evaluate status against latest_status — a prior
                # action may have flipped this probe from FAIL/WARN to PASS.
                current_status = latest_status.get(probe_result.name, probe_result.status)
                if current_status is pr.ProbeStatus.ADVISORY:
                    # Advisory items surface as info but NEVER prompt
                    # (acceptance #3 + auditor F002-i0 finding #2).
                    self._render_advisory(probe_result)
                    continue
                if current_status not in (
                    pr.ProbeStatus.FAIL,
                    pr.ProbeStatus.WARN,
                ):
                    continue
                probe = self._probe_by_name(probe_result.name)
                if probe is None:  # pragma: no cover — defensive
                    continue
                action = self._handle_probe(probe, probe_result)
                if action is not None:
                    actions.append(action)
                # After every operator action (ran / manual_acknowledged /
                # declined), re-sweep so the next loop iteration sees the
                # current state. A decline still triggers the sweep so
                # incidental fixes from a SIBLING probe are picked up.
                resweep = self._run_sweep()
                latest_status = {p.name: p.status for p in resweep.probes}
        except KeyboardInterrupt:
            self.output_fn("\nAborted by operator. Re-run `dontpanic init` to resume.")
            return WalkResult(
                profile=self.profile,
                initial=initial,
                final=initial,
                actions=actions,
                non_interactive=False,
                aborted=True,
            )

        # Idempotent: re-sweep to pick up any fixes the operator applied.
        final = self._run_sweep()
        return WalkResult(
            profile=self.profile,
            initial=initial,
            final=final,
            actions=actions,
            non_interactive=False,
        )

    def _render_advisory(self, result: pr.ProbeResult) -> None:
        """Surface an advisory probe as informational output.

        Advisory probes (e.g. codex-cli when auditor_codex_selected is
        False under --profile=core) are NOT blockers and NEVER prompt
        the operator, but they SHOULD surface so the operator knows the
        capability exists. Mirrors the doctor's advisory rendering.
        """
        self.output_fn("")
        self.output_fn(f"[advisory] {result.name}: {result.severity_reason}")
        if result.fix_url:
            self.output_fn(f"  docs: {result.fix_url}")

    # ── single-probe interaction ─────────────────────────────────────────

    def _handle_probe(
        self, probe: pr.PrereqProbe, result: pr.ProbeResult
    ) -> WalkAction | None:
        marker = "FAIL" if result.status is pr.ProbeStatus.FAIL else "WARN"
        self.output_fn("")
        self.output_fn(f"[{marker}] {probe.name}")
        self.output_fn(f"  why: {probe.why_needed}")
        self.output_fn(f"  fix_command (argv): {probe.fix_command!r}")
        if probe.fix_url:
            self.output_fn(f"  docs: {probe.fix_url}")

        if probe.auto_install_safe:
            ran = self._prompt_yes_no(
                f"  Run `{' '.join(probe.fix_command)}` now? [Y/n] "
            )
            if not ran:
                self.output_fn("  → declined; continuing with next probe.")
                return WalkAction(
                    probe_name=probe.name,
                    decision="declined",
                    fix_command=list(probe.fix_command),
                )
            start = time.monotonic()
            proc = self._execute_argv(list(probe.fix_command))
            elapsed = time.monotonic() - start
            self.output_fn(f"  → exec exit={proc.returncode} elapsed={elapsed:.2f}s")
            return WalkAction(
                probe_name=probe.name,
                decision="ran",
                fix_command=list(probe.fix_command),
                return_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                elapsed_s=elapsed,
            )

        # auto_install_safe=False — copy-paste contract.
        self.prompt_fn(
            "  Press Enter when you've applied the fix above (or Ctrl-C to abort). "
        )
        return WalkAction(
            probe_name=probe.name,
            decision="manual_acknowledged",
            fix_command=list(probe.fix_command),
        )


# ── rendering ─────────────────────────────────────────────────────────────


def render_walk_json(result: WalkResult) -> str:
    """Render the structured non-interactive / --json envelope.

    Schema (v1.0.0, mirrors the F001 envelope conventions but scoped
    to the walker):

      {
        "schema_version": "1.0.0",
        "profile": "core",
        "mode": "non_interactive" | "interactive",
        "exit_code": 0|1|2|130,
        "fail_warn_probes": [
          {
            "name": ...,
            "status": "fail"|"warn",
            "severity_reason": ...,
            "fix_command": [...],
            "fix_url": ...,
            "activation_condition": ...,
            "activation_resolved": ...
          },
          ...
        ],
        "actions": [
          {"probe_name", "decision", "fix_command", "return_code", "elapsed_s"},
          ...
        ]
      }
    """

    def _serialize_probes(sweep: pr.SweepResult) -> list[dict[str, Any]]:
        return [
            {
                "name": p.name,
                "status": p.status.value,
                "severity_reason": p.severity_reason,
                "fix_command": list(p.fix_command),
                "fix_url": p.fix_url,
                "activation_condition": p.activation_condition,
                "activation_resolved": p.activation_resolved,
            }
            for p in sweep.probes
            if p.status in (pr.ProbeStatus.FAIL, pr.ProbeStatus.WARN)
        ]

    return json.dumps(
        {
            "schema_version": "1.0.0",
            "profile": result.profile,
            "mode": "non_interactive" if result.non_interactive else "interactive",
            "exit_code": result.exit_code(),
            "fail_warn_probes": _serialize_probes(
                result.initial if result.non_interactive else result.final
            ),
            "actions": [
                {
                    "probe_name": a.probe_name,
                    "decision": a.decision,
                    "fix_command": list(a.fix_command),
                    "return_code": a.return_code,
                    "elapsed_s": round(a.elapsed_s, 4),
                }
                for a in result.actions
            ],
            "aborted": result.aborted,
        },
        indent=2,
    )


def render_walk_text(result: WalkResult) -> str:
    """Human-friendly summary of the walk."""

    lines: list[str] = []
    lines.append(f"`dontpanic init` profile={result.profile}")
    sweep = result.initial if result.non_interactive else result.final
    fail_warn = [
        p for p in sweep.probes
        if p.status in (pr.ProbeStatus.FAIL, pr.ProbeStatus.WARN)
    ]
    advisory = [p for p in sweep.probes if p.status is pr.ProbeStatus.ADVISORY]
    if not fail_warn:
        if advisory:
            lines.append("  ✓ required probes green — environment ready.")
        else:
            lines.append("  ✓ all probes green — environment ready.")
    else:
        lines.append(f"  {len(fail_warn)} probe(s) still need attention:")
        for p in fail_warn:
            lines.append(
                f"    - [{p.status.value}] {p.name}: {p.severity_reason}"
            )
            lines.append(f"        fix: {p.fix_command}")
            if p.fix_url:
                lines.append(f"        docs: {p.fix_url}")
    if advisory:
        lines.append(f"  {len(advisory)} advisory probe(s) (informational, non-blocking):")
        for p in advisory:
            lines.append(f"    - [advisory] {p.name}: {p.severity_reason}")
            if p.fix_url:
                lines.append(f"        docs: {p.fix_url}")
    if result.actions:
        lines.append(f"  operator actions: {len(result.actions)}")
        for a in result.actions:
            lines.append(f"    - {a.probe_name}: {a.decision}")
    code = result.exit_code()
    lines.append(f"  → exit_code={code}")
    return "\n".join(lines)


# ── CLI entry ─────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dontpanic init",
        description=(
            "Interactive installer for new-user onboarding. Runs the "
            "prereq-probe sweep for the selected profile (default "
            "`core`), surfaces fail+warn items, and walks per-probe "
            "operator confirmation. Auto-fix execution uses a strict "
            "argv allowlist (subprocess.run(argv, shell=False))."
        ),
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=DEFAULT_PROFILE,
        choices=pr.PROFILE_NAMES,
        help=(
            "Prereq profile to install. Defaults to `core`. The same "
            "profile set as `dontpanic doctor --profile=<name>`."
        ),
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Agent-installer mode. No prompts. Exits 1 with structured "
            "JSON listing every fail+warn probe instead of walking."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable JSON output in any mode.",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help=(
            "Skip the post-walk supervisor-plumbing smoke test. By default "
            "`dontpanic init` runs `dontpanic smoke --mode=mocked` as the "
            "final step after all probes pass (Plan 2 F003 step 9)."
        ),
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help=(
            "Plan 2026-05-19-002 F004: also write docs/install-report.html "
            "after the walk (and smoke, when smoke ran). The report mirrors "
            "the doctor + smoke JSON envelopes into a single-page HTML "
            "artifact. Output is gitignored."
        ),
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help=(
            "Override the install-report output path. Default = "
            "<repo>/docs/install-report.html. Only honored with --report."
        ),
    )
    return parser


def init_main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m dontpanic_orchestrate init`` and the
    top-level ``dontpanic init`` console script."""

    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else [])

    try:
        walker = Walker(
            profile=args.profile,
            non_interactive=args.non_interactive,
        )
    except RegistryValidationError as exc:
        print(f"[init] BLOCKED: registry invalid — {exc}", file=sys.stderr)
        return EXIT_BLOCKED

    result = walker.run()
    walk_exit = result.exit_code()

    # Plan 2 F003 acceptance #6: `dontpanic init` automatically runs smoke
    # as final step after probes pass. Auditor F003-i1 finding #3 caught
    # an earlier gate that skipped smoke under --non-interactive; that
    # broke the acceptance contract. Smoke runs whenever the walk is
    # all-green AND the operator did not opt out via --skip-smoke —
    # interactive vs non-interactive is irrelevant to whether smoke runs.
    # JSON consumers get smoke embedded as a top-level ``smoke`` field on
    # the walk envelope (single parseable document) instead of two JSON
    # blocks back-to-back.
    smoke_result = None
    if walk_exit == EXIT_READY and not args.skip_smoke:
        import contextlib
        import io as _io

        from dontpanic_orchestrate import smoke as _smoke

        # When the operator wants structured output (--json or
        # --non-interactive), suppress supervisor.dispatch_volley's
        # prose logs so the only stdout is the combined JSON envelope.
        # In interactive text mode, let the supervisor logs through —
        # they're the visible progress signal during a walk.
        wants_json = args.json or args.non_interactive
        log_buffer = _io.StringIO() if wants_json else None
        ctx = (
            contextlib.redirect_stdout(log_buffer)
            if log_buffer is not None
            else contextlib.nullcontext()
        )
        try:
            with ctx:
                smoke_result = _smoke.run_smoke(mode="mocked")
        except _smoke.SmokeEnvBlockerError as exc:
            # run_smoke can raise before returning a SmokeResult when the
            # env can't host a smoke run (tmpdir unwritable, Python too
            # old). Surface as exit 1 (EXIT_REMAINING) so init re-enters
            # the doctor fix loop — the install is broken, not the
            # supervisor.
            smoke_result = _smoke._env_blocker_result(
                mode="mocked", message=str(exc)
            )

    # Emit output. Non-interactive AND --json paths emit a single JSON
    # envelope with embedded smoke; interactive text mode prints walk
    # then smoke as separate sections.
    if args.non_interactive or args.json:
        walk_envelope = json.loads(render_walk_json(result))
        if smoke_result is not None:
            walk_envelope["smoke"] = json.loads(smoke_result.to_json())
        print(json.dumps(walk_envelope, indent=2))
    else:
        print(render_walk_text(result))
        if smoke_result is not None:
            from dontpanic_orchestrate import smoke as _smoke
            print(_smoke.render_smoke_text(smoke_result))

    # Plan 2026-05-19-002 F004: emit the install-report HTML when
    # --report is set. The doctor envelope used here is built from the
    # walker's FINAL sweep (post-fix) so the report reflects the state
    # the operator is actually leaving the install in.
    if args.report:
        from dontpanic_orchestrate.init.report_html import write_install_report
        doctor_envelope = pr.envelope_for_sweep(
            result.final if not result.non_interactive else result.initial
        )
        smoke_envelope = (
            json.loads(smoke_result.to_json()) if smoke_result is not None else None
        )
        repo_root = Path(__file__).resolve().parents[3]
        out_path = args.report_path or (repo_root / "docs" / "install-report.html")
        written = write_install_report(doctor_envelope, smoke_envelope, out_path)
        print(f"[report] wrote {written}", file=sys.stderr)

    # Exit-code resolution.
    if smoke_result is None:
        return walk_exit
    from dontpanic_orchestrate import smoke as _smoke
    if smoke_result.exit_code == _smoke.EXIT_PASS:
        # Plan 2026-05-23-002 F001: write the install-snapshot anchor
        # at ~/.dontpanic/install-snapshot.json now that the walk and
        # smoke both passed. The snapshot is the reconciliation anchor
        # F002 (`dontpanic reconcile check`) reads. Surface a write
        # failure as install failure (EXIT_REMAINING) rather than
        # silently swallowing it — operator must know the anchor is
        # missing before relying on `reconcile check`.
        try:
            from dontpanic_orchestrate import install_snapshot as _snap

            snapshot = _snap.build_snapshot(profile=args.profile)
            written = _snap.write_snapshot(snapshot)
            if not (args.non_interactive or args.json):
                print(f"[install-snapshot] wrote {written} (mode 0600).")
        except (_snap.CapabilityLoadError, OSError) as exc:
            print(
                f"[install-snapshot] BLOCKED: could not write snapshot ({exc}). "
                "Re-run `dontpanic reconcile baseline --yes` after fixing the "
                "underlying issue.",
                file=sys.stderr,
            )
            return EXIT_REMAINING
        # Plan 2026-05-23-004 F005: point successful operators at the
        # local operator console. JSON / non-interactive callers parse
        # the envelope and don't want the prose; only the human
        # interactive path gets the hand-off line.
        if not (args.non_interactive or args.json):
            print(
                "[dashboard] install ready. "
                "Open the local operator console with `dontpanic dashboard open` "
                "(or `dontpanic dashboard serve` for a localhost-only HTTP "
                "session with live refresh)."
            )
        return EXIT_READY
    if smoke_result.exit_code == _smoke.EXIT_ENV_BLOCKER:
        # Operator-actionable — doctor profile probes own the diag.
        return EXIT_REMAINING
    # EXIT_SUPERVISOR_DEFECT — escalate, not a doctor issue.
    return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(init_main(sys.argv[1:]))
