"""Plan 2026-08-09-004 F007 — walk on-disk scenarios as a corpus.

Adding a scenario is a data change under smoke/scenarios/. This module
does not need a source edit to pick a new file up.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.smoke.loader import Scenario, load_scenario
from dontpanic_orchestrate.smoke.runner import run_scenario

SCENARIOS_ROOT = Path(__file__).resolve().parent / "scenarios"


@dataclass(frozen=True)
class CorpusRow:
    scenario_id: str
    suite: str | None
    source_incident: str | None
    source_date: str | None
    intended_behavior: str | None
    expected_current_behavior: str | None
    expected_to_fail: bool
    reached_expected: bool | None
    errored: bool
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class CorpusReport:
    rows: tuple[CorpusRow, ...]
    largest_source_share: float
    largest_source: str | None
    text: str


def discover_scenarios(root: Path | None = None) -> tuple[Scenario, ...]:
    base = root or SCENARIOS_ROOT
    found: list[Scenario] = []
    for path in sorted(base.rglob("scenario.json")):
        found.append(load_scenario(path))
    return tuple(found)


def _source_key(scenario: Scenario) -> str:
    if scenario.source_incident and scenario.source_date:
        return f"{scenario.source_date}:{scenario.source_incident}"
    return "(no incident)"


def run_corpus(root: Path | None = None, *, execute: bool = True) -> CorpusReport:
    scenarios = discover_scenarios(root)
    rows: list[CorpusRow] = []
    for scenario in scenarios:
        reached: bool | None = None
        errored = False
        error: str | None = None
        if execute:
            result = run_scenario(scenario, n=1)
            trial = result.trials[0]
            reached = trial.reached_expected
            # expected-to-fail is a legitimate miss, not a harness error
            if trial.errored and not scenario.expected_to_fail:
                errored = True
                error = trial.error
            elif scenario.expected_to_fail:
                reached = False
        rows.append(
            CorpusRow(
                scenario_id=scenario.id,
                suite=scenario.suite,
                source_incident=scenario.source_incident,
                source_date=scenario.source_date,
                intended_behavior=scenario.intended_behavior,
                expected_current_behavior=scenario.expected_current_behavior,
                expected_to_fail=scenario.expected_to_fail,
                reached_expected=reached,
                errored=errored,
                error=error,
            )
        )
    sourced = [s for s in scenarios if s.source_incident]
    counts = Counter(_source_key(s) for s in sourced)
    largest_source, largest_n = (None, 0)
    if counts:
        largest_source, largest_n = counts.most_common(1)[0]
    share = (largest_n / len(sourced)) if sourced else 0.0
    lines = [
        f"corpus: {len(rows)} scenarios, "
        f"largest source share {share:.0%} ({largest_source or 'n/a'})",
    ]
    for row in rows:
        mark = "FAIL-OK" if row.expected_to_fail else ("ERR" if row.errored else "OK")
        lines.append(f"  {mark} {row.scenario_id} suite={row.suite or '-'}")
    return CorpusReport(
        rows=tuple(rows),
        largest_source_share=share,
        largest_source=largest_source,
        text="\n".join(lines) + "\n",
    )


def provenance_ok(scenarios: Iterable[Scenario]) -> list[str]:
    """Corpus scenarios (those with a suite of capability or a source) must
    name an incident and keep intended behavior distinct from current."""
    problems: list[str] = []
    for scenario in scenarios:
        if not scenario.source_incident:
            continue
        if not scenario.source_date:
            problems.append(f"{scenario.id}: missing source_date")
        if not scenario.intended_behavior:
            problems.append(f"{scenario.id}: missing intended_behavior")
        if not scenario.expected_current_behavior:
            problems.append(f"{scenario.id}: missing expected_current_behavior")
        elif (
            scenario.intended_behavior
            and scenario.intended_behavior.strip()
            == scenario.expected_current_behavior.strip()
        ):
            problems.append(f"{scenario.id}: intended equals current")
    return problems
