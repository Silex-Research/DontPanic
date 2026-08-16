"""Multi-trial scenario runner (plan 2026-08-09-003 F004).

Each trial gets its own tmp plan_dir (a copy of the scenario fixture)
and its own isolated supervisor state. Trials run sequentially. A trial
that raises is recorded as errored; remaining trials still run.

Default N=1 so existing callers see no behavior change.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.smoke.artifact import write_run_artifact
from dontpanic_orchestrate.smoke.chaos import ChaosInjector
from dontpanic_orchestrate.smoke.executors import MockClaudeExecutor, MockCodexExecutor
from dontpanic_orchestrate.smoke.loader import Scenario


@dataclass
class TrialRecord:
    trial_index: int
    terminal_state: str | None
    expected_terminal_state: str
    reached_expected: bool
    errored: bool
    error: str | None
    iteration_count: int
    perturbations_fired: list[str]
    duration_s: float
    tokens_in: int
    tokens_out: int
    scenario_id: str = ""
    reason: str | None = None
    plan_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_index": self.trial_index,
            "terminal_state": self.terminal_state,
            "expected_terminal_state": self.expected_terminal_state,
            "reached_expected": self.reached_expected,
            "errored": self.errored,
            "error": self.error,
            "iteration_count": self.iteration_count,
            "perturbations_fired": list(self.perturbations_fired),
            "duration_s": round(self.duration_s, 6),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "scenario_id": self.scenario_id,
            "reason": self.reason,
        }


@dataclass
class MultiTrialResult:
    scenario_id: str
    trials: list[TrialRecord] = field(default_factory=list)


@contextmanager
def _materialize_plan(scenario: Scenario) -> Iterator[Path]:
    tmp = Path(tempfile.mkdtemp(prefix="dontpanic-sim-"))
    try:
        plan_dir = tmp / "docs" / "plans" / scenario.plan_id
        plan_dir.mkdir(parents=True)
        shutil.copy2(scenario.plan_fixture, plan_dir / "plan.md")
        shutil.copy2(scenario.features_fixture, plan_dir / "features.json")
        (plan_dir / "decisions.jsonl").write_text("")
        yield plan_dir
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _collect_tokens(plan_dir: Path) -> tuple[int, int]:
    tokens_in = 0
    tokens_out = 0
    audit_dir = plan_dir / "audit"
    if not audit_dir.is_dir():
        return 0, 0
    for path in audit_dir.glob("*.json"):
        if path.name.startswith("signoff") or path.name in {
            "gate-state.json",
        }:
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        quota = data.get("quota_consumed") or {}
        if not isinstance(quota, dict):
            continue
        tokens_in += int(quota.get("tokens_in") or 0)
        tokens_out += int(quota.get("tokens_out") or 0)
    return tokens_in, tokens_out


def _write_exhausted_quota_state() -> None:
    raw = os.environ.get("JARVIS_QUOTA_STATE_PATH")
    if not raw:
        return
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "models": {
                    "claude": {"percent_weekly": 99.0, "plan": "pro"},
                    "codex": {"percent_weekly": 99.0, "plan": "pro"},
                }
            },
            indent=2,
        )
        + "\n"
    )


def _errored_record(
    scenario: Scenario,
    *,
    trial_index: int,
    started: float,
    error: str,
    fired: list[str] | None = None,
) -> TrialRecord:
    return TrialRecord(
        trial_index=trial_index,
        terminal_state=None,
        expected_terminal_state=scenario.expected.terminal_state,
        reached_expected=False,
        errored=True,
        error=error,
        iteration_count=0,
        perturbations_fired=list(fired or []),
        duration_s=time.monotonic() - started,
        tokens_in=0,
        tokens_out=0,
        scenario_id=scenario.id,
    )


def run_one_trial(scenario: Scenario, *, trial_index: int = 0) -> TrialRecord:
    """Execute one isolated trial. Never reaches the network."""
    from dontpanic_orchestrate.auditor_taxonomy import VerdictMismatchError
    from dontpanic_orchestrate.smoke import (
        _isolated_supervisor_state,
        _patched_agent_registry,
    )

    started = time.monotonic()
    chaos = ChaosInjector(scenario.perturbations)
    impl = MockClaudeExecutor(scenario, chaos=chaos)
    aud = MockCodexExecutor(scenario, chaos=chaos)
    has_quota = bool(chaos.quota_perturbations())

    try:
        state_root = Path(tempfile.mkdtemp(prefix="dontpanic-sim-state-"))
    except OSError as exc:
        return _errored_record(
            scenario,
            trial_index=trial_index,
            started=started,
            error=f"state tmpdir: {exc}",
        )

    try:
        with (
            _isolated_supervisor_state(state_root, bypass_quota=not has_quota),
            _materialize_plan(scenario) as plan_dir,
            _patched_agent_registry(impl, aud),
        ):
            if has_quota:
                chaos.fire_quota_at_admission()
                _write_exhausted_quota_state()
            try:
                from dontpanic_orchestrate import supervisor

                volley = supervisor.dispatch_volley(
                    plan_dir,
                    scenario.feature_id,
                    max_iterations=scenario.max_iterations,
                )
            except VerdictMismatchError as exc:
                tokens_in, tokens_out = _collect_tokens(plan_dir)
                return TrialRecord(
                    trial_index=trial_index,
                    terminal_state="verdict_mismatch",
                    expected_terminal_state=scenario.expected.terminal_state,
                    reached_expected=scenario.expected.terminal_state
                    == "verdict_mismatch",
                    errored=False,
                    error=str(exc),
                    iteration_count=0,
                    perturbations_fired=list(chaos.fired_kinds),
                    duration_s=time.monotonic() - started,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    scenario_id=scenario.id,
                    reason=str(exc),
                    plan_dir=str(plan_dir),
                )
            except Exception as exc:  # noqa: BLE001 — trial error surface
                return _errored_record(
                    scenario,
                    trial_index=trial_index,
                    started=started,
                    error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}",
                    fired=chaos.fired_kinds,
                )

            tokens_in, tokens_out = _collect_tokens(plan_dir)
            terminal = getattr(volley, "final_status", None)
            reason = getattr(volley, "reason", None)
            rounds = int(getattr(volley, "rounds", 0) or 0)
            return TrialRecord(
                trial_index=trial_index,
                terminal_state=terminal,
                expected_terminal_state=scenario.expected.terminal_state,
                reached_expected=terminal == scenario.expected.terminal_state,
                errored=False,
                error=None,
                iteration_count=rounds,
                perturbations_fired=list(chaos.fired_kinds),
                duration_s=time.monotonic() - started,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                scenario_id=scenario.id,
                reason=None if reason is None else str(reason),
                plan_dir=str(plan_dir),
            )
    finally:
        shutil.rmtree(state_root, ignore_errors=True)


def run_scenario(
    scenario: Scenario,
    *,
    n: int = 1,
    artifact_path: Path | None = None,
) -> MultiTrialResult:
    """Run ``n`` sequential isolated trials. Default n=1."""
    if n < 1:
        raise ValueError("trial count must be >= 1")
    trials: list[TrialRecord] = []
    for index in range(n):
        try:
            trials.append(run_one_trial(scenario, trial_index=index))
        except Exception as exc:  # noqa: BLE001 — do not abort remaining
            trials.append(
                _errored_record(
                    scenario,
                    trial_index=index,
                    started=time.monotonic(),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    result = MultiTrialResult(scenario_id=scenario.id, trials=trials)
    if artifact_path is not None:
        write_run_artifact(result, artifact_path)
    return result
