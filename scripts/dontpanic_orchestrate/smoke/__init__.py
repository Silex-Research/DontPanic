"""Plan 2026-05-19-002 F003 — `dontpanic smoke --mode=mocked` synthetic
supervisor-plumbing test.

Drives a synthetic 1-feature throwaway plan through
:func:`supervisor.dispatch_volley` with MockClaudeExecutor +
MockCodexExecutor. Validates that the supervisor's named surfaces are
plumbed correctly without depending on real CLIs, paid APIs, or network.

Real-CLI presence validation lives in doctor profile probes (F001), NOT
here. Smoke is supervisor-plumbing only.

NAMED supervisor surfaces (bounded set — acceptance does NOT claim
every supervisor branch):

  1. ``plan_load``                       — :func:`plan_loader.load`
  2. ``gate_evaluation``                 — :func:`gate_pause.reconcile_gate_state`
  3. ``mocked_claude_envelope_write``    — implementer audit JSON persisted
  4. ``audit_persist``                   — at least one audit envelope on disk
  5. ``mocked_codex_envelope_write``     — auditor audit JSON persisted
  6. ``signoff_envelope_write``          — :func:`signoff_writer.write_signoff`
  7. ``inbox_append``                    — :func:`inbox.append_event`
  8. ``tmpdir_cleanup``                  — ExecutionEnvironment cleanup ran

Exit codes:
  0  mocked-supervisor-plumbing-pass
  1  supervisor plumbing defect (escalate — real defect)
  2  env blocker (install issue — run `dontpanic doctor --profile=core`)

v0 ships ``--mode=mocked`` only; ``--mode=live`` is deferred to a future
plan (Roadmap Plan 2 non_goals).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.executors.base import (
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)

SCHEMA_VERSION = "1.0.0"

# Synthetic plan ID. Acceptance text reads `2026-05-19-901-smoke-feat-synthetic`
# but the plan-id regex enforces `(feat|fix|refactor|migration|infra)` as the
# 4th segment (claude/shared/schemas/v1.0/plan.schema.json L11), so the
# closest schema-valid form is `feat-smoke-synthetic`. The 901 ordinal is
# deliberately above any production plan ordinal to avoid collisions.
# Decision recorded in docs/plans/2026-05-19-002-.../decisions.jsonl (D-smoke-id).
SYNTHETIC_PLAN_ID = "2026-05-19-901-feat-smoke-synthetic"
SMOKE_FEATURE_ID = "F001"
WALL_CLOCK_LIMIT_S = 30.0

# Exit codes (mirrors module docstring + acceptance #3).
EXIT_PASS = 0
EXIT_SUPERVISOR_DEFECT = 1
EXIT_ENV_BLOCKER = 2

# v0 — only mocked mode ships. --mode=live is reserved.
SUPPORTED_MODES = ("mocked",)
DEFERRED_MODES = ("live",)

# Bounded, ordered named-surface set. Acceptance #4 + #5: the smoke
# harness exercises exactly these — nothing more is claimed.
SURFACE_NAMES: tuple[str, ...] = (
    "plan_load",
    "gate_evaluation",
    "mocked_claude_envelope_write",
    "audit_persist",
    "mocked_codex_envelope_write",
    "signoff_envelope_write",
    "inbox_append",
    "tmpdir_cleanup",
)


# ── errors ────────────────────────────────────────────────────────────────


class SmokeEnvBlockerError(RuntimeError):
    """Raised when the host environment can't support a mocked smoke run.

    Examples: ``tempfile.gettempdir()`` not writable, Python interpreter
    too old, missing schemas dir. Maps to exit code 2 — the install is
    broken; smoke can't even start. Operator should run
    ``dontpanic doctor --profile=core``.
    """


# ── result dataclasses ────────────────────────────────────────────────────


@dataclass
class SurfaceResult:
    """Per-surface outcome row."""

    name: str
    status: str  # "pass" | "fail" | "skipped"
    elapsed_s: float = 0.0
    error: str | None = None
    evidence: str | None = None  # path or marker

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "elapsed_s": round(self.elapsed_s, 4),
            "error": self.error,
            "evidence": self.evidence,
        }


@dataclass
class SmokeResult:
    """Aggregate smoke harness output."""

    mode: str
    plan_id: str
    elapsed_s: float
    exit_code: int
    surfaces: list[SurfaceResult] = field(default_factory=list)
    volley_status: str | None = None
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "mode": self.mode,
                "plan_id": self.plan_id,
                "elapsed_s": round(self.elapsed_s, 4),
                "exit_code": self.exit_code,
                "volley_status": self.volley_status,
                "error": self.error,
                "supervisor_surfaces": [s.to_dict() for s in self.surfaces],
            },
            indent=2,
        )


# ── mock executors ────────────────────────────────────────────────────────


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MockClaudeExecutor(BaseExecutor):
    """Synthetic implementer executor.

    Returns a fixed, schema-valid envelope without touching the real
    ``claude`` CLI. ``is_available()`` returns True unconditionally — the
    smoke harness's whole point is to exercise supervisor plumbing
    regardless of whether the real CLI is on PATH (F003 step 4 + test
    invariant #2).

    Module-level class so tests can import it directly and assert the
    no-real-CLI invariant on the type, not on a per-instance closure.
    """

    agent_name = "claude"
    cli_binary = None  # bypass shutil.which default

    def is_available(self) -> bool:  # noqa: D401 — overrides BaseExecutor
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=(
                f"[smoke mock {self.agent_name}/{task.agent_role}] "
                f"synthetic implementer envelope for {task.feature_id} "
                f"(iter={task.iteration}). No real CLI invoked."
            ),
            model_version="smoke-mock",
            raw_response="signed_off",
            quota_consumed={"tokens_in": 0, "tokens_out": 0},
        )


class MockCodexExecutor(BaseExecutor):
    """Synthetic auditor executor.

    Returns a signed_off verdict via the prose marker so
    :func:`audit_writer._derive_status` resolves to ``signed_off``
    deterministically without a status override.

    Module-level class so tests can import it directly and assert the
    no-real-CLI invariant on the type, not on a per-instance closure.
    """

    agent_name = "codex"
    cli_binary = None

    def is_available(self) -> bool:  # noqa: D401 — overrides BaseExecutor
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=(
                "Overall verdict: signed_off.\n"
                f"[smoke mock {self.agent_name}/{task.agent_role}] "
                f"synthetic auditor envelope for {task.feature_id} "
                f"(iter={task.iteration}). No findings; no real CLI invoked."
            ),
            model_version="smoke-mock",
            raw_response="signed_off",
            quota_consumed={"tokens_in": 0, "tokens_out": 0},
        )


# ── synthetic plan fixture ────────────────────────────────────────────────


_SYNTHETIC_PLAN_MD = """---
id: {plan_id}
title: Smoke harness synthetic plan
type: infra
tier: trivial
status: active
date: "2026-05-19"
description: |
  Synthetic supervisor-plumbing exercise. Created by `dontpanic smoke
  --mode=mocked`. NOT a real plan — does not represent shipping work
  and is deleted on smoke exit (success or failure).
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 1
  hard_stop: true
privacy_tier: internal
goal_type: mechanical
links:
  features: ./features.json
---

# Smoke harness synthetic plan

Used by `dontpanic smoke --mode=mocked` only. Never dispatched against
real CLIs. Throwaway tmpdir, cleaned on exit.

## Target

```yaml
target_env: dev
target_project: none
```
"""


_SYNTHETIC_FEATURES = {
    "schema_version": "1.0",
    "task_id": SYNTHETIC_PLAN_ID,
    "features": [
        {
            "id": SMOKE_FEATURE_ID,
            "category": "test",
            "phase": 0,
            "description": (
                "Synthetic supervisor-plumbing exercise; mocked executors "
                "produce signed_off envelopes without touching real CLIs."
            ),
            "steps": ["mocked implementer dispatch", "mocked auditor dispatch"],
            "acceptance": "Volley terminates signed_off via mocked executors.",
            "passes": False,
            "depends_on": [],
        }
    ],
}


class SyntheticPlanFixture:
    """Context-manager class wrapping :func:`synthetic_plan_fixture`.

    The feature spec names ``SyntheticPlanFixture`` explicitly as a class
    surface (alongside ``MockClaudeExecutor`` / ``MockCodexExecutor``).
    Use ``with SyntheticPlanFixture() as plan_dir:`` for the same lifecycle
    as the function-form helper. Implementation delegates to the existing
    ``synthetic_plan_fixture`` context manager — no behavior change.
    """

    def __init__(
        self,
        *,
        parent: Path | None = None,
        plan_id: str = SYNTHETIC_PLAN_ID,
    ) -> None:
        self.parent = parent
        self.plan_id = plan_id
        self._cm: Any = None
        self.plan_dir: Path | None = None

    def __enter__(self) -> Path:
        self._cm = synthetic_plan_fixture(parent=self.parent, plan_id=self.plan_id)
        self.plan_dir = self._cm.__enter__()
        return self.plan_dir

    def __exit__(self, *exc_info: Any) -> None:
        if self._cm is not None:
            self._cm.__exit__(*exc_info)
            self._cm = None


@contextmanager
def synthetic_plan_fixture(
    *,
    parent: Path | None = None,
    plan_id: str = SYNTHETIC_PLAN_ID,
) -> Iterator[Path]:
    """Yields a freshly-created synthetic plan_dir; cleans up on exit.

    The tmpdir is removed in ``finally`` so cleanup runs on success AND
    on exception, satisfying F003 step 5 surface (8) ("tmpdir cleanup
    runs on success AND on exception").

    The plan ID conforms to plan.schema.json's id regex
    (``\\d{4}-\\d{2}-\\d{2}-\\d{3}-(feat|fix|refactor|migration|infra)-...``)
    so ``plan_loader.load`` can parse it. Caller-provided plan_id is
    accepted but defaults to the canonical throwaway constant.
    """
    try:
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix="dontpanic-smoke-", dir=str(parent)))
        else:
            tmp = Path(tempfile.mkdtemp(prefix="dontpanic-smoke-"))
    except OSError as exc:
        raise SmokeEnvBlockerError(
            f"cannot create tmpdir under {parent or tempfile.gettempdir()!s}: {exc}. "
            "Run `dontpanic doctor --profile=core` to diagnose."
        ) from exc

    try:
        plan_dir = tmp / "docs" / "plans" / plan_id
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan.md").write_text(_SYNTHETIC_PLAN_MD.format(plan_id=plan_id))
        features = dict(_SYNTHETIC_FEATURES)
        features["task_id"] = plan_id
        (plan_dir / "features.json").write_text(
            json.dumps(features, indent=2, ensure_ascii=False) + "\n"
        )
        # decisions.jsonl is optional but the directory layout claims it —
        # write an empty file so consumers that probe for its presence
        # don't treat it as missing.
        (plan_dir / "decisions.jsonl").write_text("")
        yield plan_dir
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── isolated state ───────────────────────────────────────────────────────


@contextmanager
def _isolated_supervisor_state(state_root: Path) -> Iterator[Path]:
    """Redirect operator-state env vars + bypass the quota gate.

    Mirrors the pytest conftest fixture (``_isolate_jarvis_state``) so
    the standalone CLI doesn't inherit the operator's
    ``~/.jarvis/quota_state.json`` etc. — those would otherwise trip
    F006/F007 gates and produce supervisor-defect false positives.

    Restoration runs in ``finally`` even on exception so the operator's
    real env is never left mutated.
    """
    from dontpanic_orchestrate import supervisor as sup

    state_root.mkdir(parents=True, exist_ok=True)

    overrides = {
        "JARVIS_BREAKER_HISTORY_PATH": str(state_root / "breaker_history.jsonl"),
        "JARVIS_ACTIVE_SUPERVISORS_PATH": str(state_root / "active_supervisors.jsonl"),
        "JARVIS_INTERACTIVE_STATE_PATH": str(state_root / "interactive_state.json"),
        "JARVIS_QUOTA_STATE_PATH": str(state_root / "quota_state.json"),
        "JARVIS_QUOTA_CAPS_PATH": str(state_root / "quota_caps.json"),
        "DONTPANIC_HOME": str(state_root / "dontpanic_home"),
        "JARVIS_HOME": str(state_root / "jarvis_home"),
    }
    saved_env: dict[str, str | None] = {k: os.environ.get(k) for k in overrides}
    saved_quota_gate = getattr(sup, "_quota_gate", None)

    try:
        os.environ.update(overrides)
        # Bypass quota lookups — mocked executors don't consume tokens.
        sup._quota_gate = lambda agent: (None, f"[smoke] {agent}: bypassed (mocked)")
        yield state_root
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if saved_quota_gate is not None:
            sup._quota_gate = saved_quota_gate


@contextmanager
def _patched_agent_registry(impl_executor: Any, aud_executor: Any) -> Iterator[None]:
    """Swap AGENT_REGISTRY's claude/codex entries for the smoke run.

    F005a's registry pattern (test_volley_synthetic.py L215-216): replace
    the class with a lambda returning a pre-built executor instance.
    Restored in ``finally`` regardless of outcome so other tests / a
    later supervisor call don't inherit the mocks.
    """
    from dontpanic_orchestrate.executors import AGENT_REGISTRY

    saved = dict(AGENT_REGISTRY)
    try:
        AGENT_REGISTRY["claude"] = lambda i=impl_executor: i  # type: ignore[assignment]
        AGENT_REGISTRY["codex"] = lambda a=aud_executor: a  # type: ignore[assignment]
        yield
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved)


# ── core driver ───────────────────────────────────────────────────────────


def _safe_plan_id_prefix(plan_id: str) -> str:
    """Mirror ExecutionEnvironment's safe-prefix sanitization."""
    return "".join(c if c.isalnum() or c in "._-" else "-" for c in plan_id)


def _supervisor_tmpdirs_for(plan_id: str) -> list[Path]:
    """Return all ``/tmp/jarvis-exec-<plan_id>-*`` directories present.

    Smoke uses the synthetic plan_id (unique 901- ordinal) so this list
    is empty under normal operation; non-empty after a volley implies
    the ExecutionEnvironment cleanup never ran.
    """
    safe = _safe_plan_id_prefix(plan_id)
    tmp_root = Path(tempfile.gettempdir())
    prefix = f"jarvis-exec-{safe}-"
    try:
        return [p for p in tmp_root.iterdir() if p.name.startswith(prefix)]
    except OSError:
        return []


def _attest_surfaces(
    plan_dir: Path,
    *,
    plan_id: str,
    volley_result: Any,
    started_at: float,
) -> list[SurfaceResult]:
    """Build the per-surface result list from the post-volley plan_dir."""

    audit_dir = plan_dir / "audit"
    audit_files = sorted(audit_dir.glob("*.json")) if audit_dir.is_dir() else []

    surfaces: list[SurfaceResult] = []

    # 1. plan_load — VolleyResult exists implies plan_loader.load succeeded.
    surfaces.append(
        SurfaceResult(
            name="plan_load",
            status="pass",
            elapsed_s=time.monotonic() - started_at,
            evidence=str(plan_dir / "plan.md"),
        )
    )

    # 2. gate_evaluation — supervisor's volley wrapper calls
    # gate_pause.reconcile_gate_state via _reconcile_gate_state_or_raise.
    # A returned VolleyResult implies that call ran without raising
    # GateStateReconciliationError. For plans with no human_gates the
    # file may not exist, so we attest by VolleyResult presence + read
    # the (optional) gate-state.json as evidence when present.
    gate_state = plan_dir / "audit" / "gate-state.json"
    surfaces.append(
        SurfaceResult(
            name="gate_evaluation",
            status="pass" if volley_result is not None else "fail",
            evidence=(
                str(gate_state) if gate_state.exists() else "volley_result_returned"
            ),
            error=None if volley_result is not None else "volley returned no result",
        )
    )

    # 3. mocked_claude_envelope_write — claude implementer audit on disk.
    claude_files = [
        p for p in audit_files if "claude-implementer" in p.name
    ]
    surfaces.append(
        SurfaceResult(
            name="mocked_claude_envelope_write",
            status="pass" if claude_files else "fail",
            evidence=str(claude_files[0]) if claude_files else None,
            error=None if claude_files else "no claude-implementer-*.json envelope",
        )
    )

    # 4. audit_persist — at least one audit envelope persisted.
    surfaces.append(
        SurfaceResult(
            name="audit_persist",
            status="pass" if audit_files else "fail",
            evidence=str(audit_dir) if audit_files else None,
            error=None if audit_files else "audit/ directory empty",
        )
    )

    # 5. mocked_codex_envelope_write — codex auditor audit on disk.
    codex_files = [p for p in audit_files if "codex-auditor" in p.name]
    surfaces.append(
        SurfaceResult(
            name="mocked_codex_envelope_write",
            status="pass" if codex_files else "fail",
            evidence=str(codex_files[0]) if codex_files else None,
            error=None if codex_files else "no codex-auditor-*.json envelope",
        )
    )

    # 6. signoff_envelope_write — signoff envelope persisted by
    # signoff_writer.write_signoff at audit/signoff-<plan_id>.json.
    from dontpanic_orchestrate import signoff_writer as _sw

    signoff_path = _sw.signoff_path(plan_dir, plan_id)
    surfaces.append(
        SurfaceResult(
            name="signoff_envelope_write",
            status="pass" if signoff_path.exists() else "fail",
            evidence=str(signoff_path) if signoff_path.exists() else None,
            error=None if signoff_path.exists() else f"{signoff_path.name} not written",
        )
    )

    # 7. inbox_append — INBOX.md contains volley_terminal event.
    inbox_path = plan_dir / "INBOX.md"
    inbox_has_terminal = (
        inbox_path.is_file() and "volley_terminal" in inbox_path.read_text()
    )
    surfaces.append(
        SurfaceResult(
            name="inbox_append",
            status="pass" if inbox_has_terminal else "fail",
            evidence=str(inbox_path) if inbox_has_terminal else None,
            error=None if inbox_has_terminal else "INBOX.md missing volley_terminal event",
        )
    )

    # 8. tmpdir_cleanup — no leftover /tmp/jarvis-exec-<plan_id>-*.
    leaked = _supervisor_tmpdirs_for(plan_id)
    surfaces.append(
        SurfaceResult(
            name="tmpdir_cleanup",
            status="pass" if not leaked else "fail",
            evidence="no-leaks" if not leaked else None,
            error=None if not leaked else f"leaked tmpdirs: {[str(p) for p in leaked]}",
        )
    )

    return surfaces


def run_smoke(
    *,
    mode: str = "mocked",
    plan_dir: Path | None = None,
    state_root: Path | None = None,
) -> SmokeResult:
    """Exercise the named supervisor surfaces with mocked executors.

    Bounded <=30s wall clock (acceptance #2). On any unexpected
    exception, the synthetic-plan fixture's ``finally`` still runs and
    removes the tmpdir — surface (8) is verified afterward against the
    supervisor's own /tmp/jarvis-exec-*.

    Raises :class:`SmokeEnvBlockerError` for env-blocker conditions
    (mode reserved, Python too old, tmpdir unavailable). Callers should
    catch this and map to exit code 2 — :func:`smoke_main` does so.
    """
    if mode in DEFERRED_MODES:
        raise SmokeEnvBlockerError(
            f"--mode={mode} is reserved for a future plan; "
            "v0 ships --mode=mocked only."
        )
    if mode not in SUPPORTED_MODES:
        raise SmokeEnvBlockerError(
            f"unknown --mode={mode!r}; supported: {SUPPORTED_MODES}"
        )

    started = time.monotonic()
    plan_id = SYNTHETIC_PLAN_ID

    # Pre-flight env-blocker check: Python >=3.10 (matches doctor core probe).
    if sys.version_info < (3, 10):
        raise SmokeEnvBlockerError(
            f"Python 3.10+ required; got {sys.version_info.major}."
            f"{sys.version_info.minor}. Run `dontpanic doctor --profile=core`."
        )

    # Drive the supervisor.
    from dontpanic_orchestrate import supervisor

    impl = MockClaudeExecutor()
    aud = MockCodexExecutor()

    use_existing_plan = plan_dir is not None
    if not use_existing_plan:
        fixture_cm = synthetic_plan_fixture()
    else:
        fixture_cm = _existing_plan_passthrough(plan_dir)  # type: ignore[arg-type]

    # state_root creation can fail when /tmp is unwritable, Python's tmp
    # candidates all reject mkdir, or the operator overrode TMPDIR to a
    # bogus path. Treat that as an env blocker (exit 2) — the install is
    # broken; the supervisor isn't.
    if state_root is None:
        # Snapshot the tmp-root candidate BEFORE the mkdtemp call so we
        # don't re-invoke gettempdir() from the exception handler — that
        # call can itself raise FileNotFoundError when every tmp candidate
        # is bogus (auditor F003-i1 finding #1). Falls back to the literal
        # 'unknown' if gettempdir() also blows up.
        try:
            tmp_root_hint = tempfile.gettempdir()
        except (OSError, FileNotFoundError):
            tmp_root_hint = "<no usable temp directory>"
        try:
            state_root = Path(tempfile.mkdtemp(prefix="dontpanic-smoke-state-"))
        except (OSError, FileNotFoundError) as exc:
            raise SmokeEnvBlockerError(
                f"cannot create smoke state tmpdir under "
                f"{tmp_root_hint}: {exc}. "
                "Run `dontpanic doctor --profile=core` to diagnose."
            ) from exc
        own_state_root = True
    else:
        own_state_root = False

    try:
        with _isolated_supervisor_state(state_root), fixture_cm as resolved_plan_dir, \
                _patched_agent_registry(impl, aud):
            try:
                volley_result = supervisor.dispatch_volley(
                    resolved_plan_dir,
                    SMOKE_FEATURE_ID,
                    max_iterations=1,
                )
            except Exception as exc:  # noqa: BLE001 — supervisor defect surface
                # Even on supervisor exception, the synthetic-plan fixture
                # cleanup runs in `finally` below. We surface the failure
                # as exit 1 with the offending surface enumerated.
                surfaces = _failed_surfaces(error=f"{type(exc).__name__}: {exc}")
                return SmokeResult(
                    mode=mode,
                    plan_id=plan_id,
                    elapsed_s=time.monotonic() - started,
                    exit_code=EXIT_SUPERVISOR_DEFECT,
                    surfaces=surfaces,
                    volley_status=None,
                    error=traceback.format_exc(limit=8),
                )

            surfaces = _attest_surfaces(
                resolved_plan_dir,
                plan_id=plan_id,
                volley_result=volley_result,
                started_at=started,
            )
            elapsed = time.monotonic() - started
            volley_status = getattr(volley_result, "final_status", None)

            # Volley must terminate signed_off for a healthy mocked run.
            volley_pass = volley_status == "signed_off"
            all_surfaces_pass = all(s.status == "pass" for s in surfaces)
            within_budget = elapsed <= WALL_CLOCK_LIMIT_S

            if not within_budget:
                surfaces.append(
                    SurfaceResult(
                        name="wall_clock_budget",
                        status="fail",
                        elapsed_s=elapsed,
                        error=(
                            f"smoke exceeded {WALL_CLOCK_LIMIT_S}s budget "
                            f"(elapsed={elapsed:.2f}s)"
                        ),
                    )
                )
            exit_code = (
                EXIT_PASS
                if (volley_pass and all_surfaces_pass and within_budget)
                else EXIT_SUPERVISOR_DEFECT
            )
            error_msg: str | None = None
            if not volley_pass:
                error_msg = f"volley final_status={volley_status!r}; expected 'signed_off'"
            return SmokeResult(
                mode=mode,
                plan_id=plan_id,
                elapsed_s=elapsed,
                exit_code=exit_code,
                surfaces=surfaces,
                volley_status=volley_status,
                error=error_msg,
            )
    finally:
        if own_state_root:
            shutil.rmtree(state_root, ignore_errors=True)


@contextmanager
def _existing_plan_passthrough(plan_dir: Path) -> Iterator[Path]:
    """Pass-through context manager for caller-provided plan_dir.

    Used by tests that want to reuse a synthetic plan they constructed
    themselves (e.g. for read-only assertions). The caller owns
    cleanup; smoke does NOT remove caller-provided dirs.
    """
    yield plan_dir


def _failed_surfaces(*, error: str) -> list[SurfaceResult]:
    """Build a surface list marking every surface 'fail' with a shared error.

    Used on supervisor-exception paths where we can't introspect per-
    surface evidence — the caller couldn't even get far enough to
    distinguish which surface failed. The error message is identical on
    each so post-hoc filtering / aggregation behaves consistently.
    """
    return [
        SurfaceResult(name=n, status="fail", error=error) for n in SURFACE_NAMES
    ]


# ── rendering ─────────────────────────────────────────────────────────────


def render_smoke_text(result: SmokeResult) -> str:
    """Human-friendly per-surface chip rendering."""
    lines: list[str] = []
    lines.append(
        f"`dontpanic smoke --mode={result.mode}` plan={result.plan_id}"
    )
    lines.append(
        f"  elapsed={result.elapsed_s:.2f}s "
        f"volley={result.volley_status!s} exit={result.exit_code}"
    )
    if result.error:
        lines.append(f"  error: {result.error}")
    for surface in result.surfaces:
        marker = {"pass": "✓", "fail": "✗", "skipped": "○"}.get(surface.status, "?")
        lines.append(
            f"  {marker} [{surface.status:>4s}] {surface.name:<32s} "
            f"elapsed={surface.elapsed_s:.3f}s"
        )
        if surface.error:
            lines.append(f"        error: {surface.error}")
    if result.exit_code == EXIT_ENV_BLOCKER:
        lines.append(
            "  → env blocker detected; run `dontpanic doctor --profile=core`."
        )
    elif result.exit_code == EXIT_SUPERVISOR_DEFECT:
        lines.append(
            "  → supervisor plumbing defect — escalate (real bug, NOT install env)."
        )
    return "\n".join(lines)


def _env_blocker_result(*, mode: str, message: str) -> SmokeResult:
    """Build a SmokeResult representing an env-blocker outcome (exit 2).

    Single source of truth so `smoke_main`, `dontpanic init`, and any
    downstream consumer that catches :class:`SmokeEnvBlockerError`
    produce the same JSON shape — full named-surface array marked
    `fail`, exit_code=2, doctor pointer in the error string.
    """
    return SmokeResult(
        mode=mode,
        plan_id=SYNTHETIC_PLAN_ID,
        elapsed_s=0.0,
        exit_code=EXIT_ENV_BLOCKER,
        surfaces=_failed_surfaces(error=message),
        volley_status=None,
        error=message,
    )


# ── CLI entry ─────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dontpanic smoke",
        description=(
            "Synthetic supervisor-plumbing test. Exercises the named "
            "supervisor surfaces with mocked executors. Bounded <=30s "
            "wall clock. NO real CLI required, NO paid API, NO network."
        ),
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="mocked",
        choices=list(SUPPORTED_MODES) + list(DEFERRED_MODES),
        help=(
            "Smoke mode. v0 ships --mode=mocked only; --mode=live is "
            "reserved for a future plan."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON output (stable schema, schema_version='%s')."
        % SCHEMA_VERSION,
    )
    return parser


def smoke_main(argv: list[str] | None = None) -> int:
    """Console entry point for ``dontpanic smoke``."""

    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else [])

    try:
        result = run_smoke(mode=args.mode)
    except SmokeEnvBlockerError as exc:
        result = _env_blocker_result(mode=args.mode, message=str(exc))

    if args.json:
        print(result.to_json())
    else:
        print(render_smoke_text(result))
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(smoke_main(sys.argv[1:]))
