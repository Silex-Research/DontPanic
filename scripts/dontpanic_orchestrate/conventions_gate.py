"""Plan 2026-06-05-004 F006 — end-to-end conventions-disposition gate.

Wires F001-F005 into one entry point and bridges the skill-applicability matcher's
output into the ledger's expected items (awareness → accountability): a skill the
matcher deems applicable becomes an expected ledger item the plan must dispose of.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from dontpanic_orchestrate.conventions_ledger import (
    LedgerEntry,
    load_ledger,
    validate_dispositions,
)
from dontpanic_orchestrate.plan_review.disposition_check import (
    DispositionFinding,
    check_plan_dispositions,
)


@dataclass(frozen=True)
class _SkillExpectation:
    """A matched skill turned into an expected (disposable) ledger item."""

    id: str


def _skill_items(matched_skills: Iterable[str]) -> list[_SkillExpectation]:
    return [_SkillExpectation(f"skill:{name}") for name in matched_skills]


def evaluate_plan_dispositions(
    *,
    plan_dir: Path | None = None,
    declared: Iterable[str] = (),
    matched_skills: Iterable[str] = (),
    ledger: Mapping[str, LedgerEntry] | None = None,
) -> list[DispositionFinding]:
    """Advisory findings for a plan, from its surface packs + matched skills.

    ``ledger`` may be passed directly (tests); otherwise it is loaded from
    ``plan_dir`` (``conventions.json``). Warn-only — never raises / blocks.
    """
    if ledger is None:
        ledger = load_ledger(plan_dir) if plan_dir is not None else {}
    ledger = dict(ledger)

    findings = list(check_plan_dispositions(declared=declared, ledger=ledger))

    # Bridge: matched skills become expected ledger items (the explicit
    # awareness->accountability step the proposal calls for).
    skill_items = _skill_items(matched_skills)
    if skill_items:
        for item_id, status in validate_dispositions(skill_items, ledger).items():
            if status != "disposed-ok":
                findings.append(DispositionFinding("skill", item_id, status))
    return findings
