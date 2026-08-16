"""Plan 2026-08-09-005 — regression vs capability suites."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.graders import (
    GraderResult,
    GraderVerdict,
    TrialArtifacts,
    TrialRecord as GradeTrial,
    evidence_grader,
    gate_agreement_grader,
    operational_validity_grader,
    schema_grader,
    target_boundary_grader,
)
from dontpanic_orchestrate.smoke.corpus import discover_scenarios
from dontpanic_orchestrate.smoke.loader import Scenario
from dontpanic_orchestrate.smoke.runner import run_scenario

DEFAULT_PROMOTION_N = 3
DURATION_FLAG_RATIO = 2.0


class ModelCallGuard(RuntimeError):
    """Raised if a regression run attempts a model call."""


def _forbid_model(*_a: object, **_k: object) -> None:
    raise ModelCallGuard("regression suite forbids model calls")


_DETERMINISTIC_GRADERS = (
    schema_grader,
    evidence_grader,
    gate_agreement_grader,
    target_boundary_grader,
    operational_validity_grader,
)


def _grade(scenario: Scenario) -> list[GraderResult]:
    artifacts = TrialArtifacts(root=scenario.plan_fixture.parent)
    trial = GradeTrial(id=scenario.id, expected_terminal=scenario.expected.terminal_state)
    results: list[GraderResult] = []
    for grader in _DETERMINISTIC_GRADERS:
        results.extend(grader(trial, artifacts))
    return results


@dataclass
class ScenarioOutcome:
    scenario_id: str
    suite: str
    passed: bool
    grader_id: str | None
    reason: str
    duration_s: float = 0.0
    tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class SuiteRun:
    suite: str
    outcomes: list[ScenarioOutcome] = field(default_factory=list)
    duration_s: float = 0.0
    exit_code: int = 0
    text: str = ""
    judge_evaluated: bool = False

    @property
    def passed_count(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "duration_s": self.duration_s,
            "exit_code": self.exit_code,
            "passed": self.passed_count,
            "total": len(self.outcomes),
            "judge_evaluated": self.judge_evaluated,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "text": self.text,
        }


def _run_suite(
    suite: str,
    *,
    root: Path | None = None,
    execute: bool = True,
    model_hook: Callable[..., Any] | None = None,
    fail_on_miss: bool = True,
    judge: bool = False,
) -> SuiteRun:
    started = time.monotonic()
    from dontpanic_orchestrate import graders

    previous_judge = graders._invoke_judge_model
    try:
        if suite == "regression":
            if model_hook is not None:
                model_hook()
            else:
                graders._invoke_judge_model = _forbid_model  # type: ignore[method-assign]
        return _run_suite_body(
            suite,
            root=root,
            execute=execute,
            fail_on_miss=fail_on_miss,
            judge=judge,
            started=started,
        )
    finally:
        graders._invoke_judge_model = previous_judge  # type: ignore[method-assign]


def _run_suite_body(
    suite: str,
    *,
    root: Path | None,
    execute: bool,
    fail_on_miss: bool,
    judge: bool,
    started: float,
) -> SuiteRun:
    scenarios = [s for s in discover_scenarios(root) if s.suite == suite]
    outcomes: list[ScenarioOutcome] = []
    for scenario in scenarios:
        t0 = time.monotonic()
        grades = _grade(scenario)
        failed_grade = next((g for g in grades if g.verdict is GraderVerdict.FAIL), None)
        reached = True
        if execute and failed_grade is None:
            result = run_scenario(scenario, n=1)
            reached = bool(result.trials and result.trials[0].reached_expected)
            if scenario.expected_to_fail:
                reached = True  # expected miss is not a regression failure
        passed = failed_grade is None and reached
        reason = (
            failed_grade.reason
            if failed_grade is not None
            else ("reached expected terminal" if reached else "missed expected terminal")
        )
        outcomes.append(
            ScenarioOutcome(
                scenario_id=scenario.id,
                suite=suite,
                passed=passed,
                grader_id=failed_grade.grader_id if failed_grade else "terminal",
                reason=reason,
                duration_s=time.monotonic() - t0,
            )
        )
    duration = time.monotonic() - started
    failed = [o for o in outcomes if not o.passed]
    exit_code = 1 if (fail_on_miss and failed) else 0
    lines = [
        f"{suite} suite: {sum(o.passed for o in outcomes)}/{len(outcomes)} "
        f"in {duration:.3f}s"
    ]
    if not judge:
        lines.append("judge dimensions not evaluated: rationale, audit summary")
    for item in failed:
        lines.append(
            f"FAIL {item.scenario_id} grader={item.grader_id} reason={item.reason}"
        )
    return SuiteRun(
        suite=suite,
        outcomes=outcomes,
        duration_s=duration,
        exit_code=exit_code,
        text="\n".join(lines) + "\n",
        judge_evaluated=judge,
    )


def run_regression(root: Path | None = None, **kwargs: Any) -> SuiteRun:
    return _run_suite("regression", root=root, fail_on_miss=True, judge=False, **kwargs)


def run_capability(root: Path | None = None, **kwargs: Any) -> SuiteRun:
    kwargs.setdefault("fail_on_miss", False)
    kwargs.setdefault("judge", False)
    return _run_suite("capability", root=root, **kwargs)


def persist_run(run: SuiteRun, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"id": f"{run.suite}-{int(time.time())}", **run.to_dict()}
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def promotion_eligible(
    records: list[dict[str, Any]],
    scenario_id: str,
    *,
    n: int = DEFAULT_PROMOTION_N,
) -> bool:
    relevant = [
        rec
        for rec in records
        if any(o.get("scenario_id") == scenario_id for o in rec.get("outcomes") or [])
    ]
    if len(relevant) < n:
        return False
    last = relevant[-n:]
    for rec in last:
        outcome = next(
            o for o in rec["outcomes"] if o.get("scenario_id") == scenario_id
        )
        if not outcome.get("passed"):
            return False
    return True


def promote(
    scenario_path: Path,
    *,
    run_ids: list[str],
    actor: str,
    decisions_path: Path,
) -> None:
    payload = json.loads(scenario_path.read_text())
    payload["suite"] = "regression"
    scenario_path.write_text(json.dumps(payload, indent=2) + "\n")
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": "DPROM",
        "date": time.strftime("%Y-%m-%d"),
        "question": f"Promote {payload.get('id')} to regression?",
        "answer": "promoted",
        "status": "resolved",
        "rationale": f"{actor} promoted on runs {', '.join(run_ids)}",
        "actor": actor,
        "run_ids": run_ids,
        "scenario": payload.get("id"),
    }
    with decisions_path.open("a") as handle:
        handle.write(json.dumps(entry) + "\n")


def drift_report(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    duration_threshold: float = DURATION_FLAG_RATIO,
) -> dict[str, Any]:
    if previous is None:
        return {
            "comparison": False,
            "note": "no previous run available; no comparison was possible",
            "classifications": {},
        }
    prev_map = {o["scenario_id"]: o for o in previous.get("outcomes") or []}
    curr_map = {o["scenario_id"]: o for o in current.get("outcomes") or []}
    classes: dict[str, str] = {}
    flagged: list[str] = []
    for sid, curr in curr_map.items():
        prev = prev_map.get(sid)
        if prev is None:
            classes[sid] = "unchanged"
            continue
        if not prev.get("passed") and not curr.get("passed"):
            classes[sid] = "still-failing"
        elif prev.get("passed") and not curr.get("passed"):
            classes[sid] = "newly-failing"
        elif not prev.get("passed") and curr.get("passed"):
            classes[sid] = "newly-passing"
        else:
            classes[sid] = "unchanged"
            prev_d = float(prev.get("duration_s") or 0)
            curr_d = float(curr.get("duration_s") or 0)
            if prev_d > 0 and curr_d / prev_d >= duration_threshold:
                flagged.append(sid)
    return {
        "comparison": True,
        "classifications": classes,
        "duration_flagged": flagged,
        "suites": [current.get("suite"), previous.get("suite")],
    }
