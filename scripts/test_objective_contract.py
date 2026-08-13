"""Validator objective_contract dispatch test — agent-conventions v1.4.0.

Locks the Goal Governance V1 §4 applicability rule for the plan validator
at ``schemas/v1.0/validate.py``. Seven fixture cases:

  1. parity + valid contract                  -> exit 0, ✓ objective_contract
  2. new_feature + valid contract             -> exit 0, ✓
  3. migration + valid contract               -> exit 0, ✓
  4. incident + valid contract                -> exit 0, ✓
  5. no goal_type (existing-style)            -> exit 0, no contract line (backward compat)
  6. goal_type=parity, no links.objective_contract -> exit 1, ✗ objective_contract — required by goal_type=parity
  7. goal_type=mechanical, no contract        -> exit 0, no contract line (mechanical doesn't require it)

Cases 13-14 (plan 2026-08-13-001 F001) carry the additive contract fields
end-to-end through the validator, not just through the schema:

 13. delivers[] item with a cheap ``proof`` (walk) -> exit 0, ✓
 14. fix plan with ``inherits`` + a ONE-ITEM delta delivers[] -> exit 0, ✓

Case 14 is the load-bearing one: ``inherits`` licenses omitting the parent's
FULL outcome set, not the ``delivers[]`` block, so the v1.1 non-empty rule must
still be satisfied by a single delta slice.

Each fixture lives under ``tests/objective_contract/_fixture_*/`` and is a
minimal-but-real plan dir (plan.md frontmatter + features.json + an
``objective_contract.json`` for the cases that need one).

Usage:

    python3 scripts/test_objective_contract.py

Exit 0 if all seven cases pass; 1 otherwise.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "schemas" / "v1.0" / "validate.py"
FIXTURES_DIR = REPO_ROOT / "tests" / "objective_contract"


def _run_validator(plan_dir: Path) -> tuple[int, str]:
    """Subprocess the validator against a single plan dir; return (exit, stdout)."""
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), str(plan_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def _case(
    name: str,
    fixture: str,
    expected_exit: int,
    expected_substrings: list[str],
    forbidden_substrings: list[str],
) -> tuple[bool, str]:
    plan_dir = FIXTURES_DIR / fixture
    rc, out = _run_validator(plan_dir)

    failures: list[str] = []
    if rc != expected_exit:
        failures.append(f"exit code: got {rc}, expected {expected_exit}")
    for substr in expected_substrings:
        if substr not in out:
            failures.append(f"missing expected substring: {substr!r}")
    for substr in forbidden_substrings:
        if substr in out:
            failures.append(f"forbidden substring present: {substr!r}")

    if failures:
        detail = "\n      ".join(failures)
        return False, f"  ✗ {name}\n      {detail}\n      stdout was:\n{out}"
    return True, f"  ✓ {name}"


def main() -> int:
    cases = [
        (
            "case 1: parity + valid contract dispatches green",
            "_fixture_parity_with_contract",
            0,
            ["✓ plan.md frontmatter", "✓ objective_contract"],
            ["✗ objective_contract"],
        ),
        (
            "case 2: new_feature + valid contract dispatches green",
            "_fixture_new_feature_with_contract",
            0,
            ["✓ plan.md frontmatter", "✓ objective_contract"],
            ["✗ objective_contract"],
        ),
        (
            "case 3: migration + valid contract dispatches green",
            "_fixture_migration_with_contract",
            0,
            ["✓ plan.md frontmatter", "✓ objective_contract"],
            ["✗ objective_contract"],
        ),
        (
            "case 4: incident + valid contract dispatches green",
            "_fixture_incident_with_contract",
            0,
            ["✓ plan.md frontmatter", "✓ objective_contract"],
            ["✗ objective_contract"],
        ),
        (
            "case 5: no goal_type (existing-style) — backward compat, no contract check",
            "_fixture_no_goal_type",
            0,
            ["✓ plan.md frontmatter"],
            ["objective_contract"],  # no contract line at all
        ),
        (
            "case 6: goal_type=parity + missing contract MUST fail",
            "_fixture_parity_missing_contract",
            1,
            [
                "✗ objective_contract",
                "required by goal_type=parity",
                "missing or empty",
            ],
            ["✓ objective_contract"],
        ),
        (
            "case 7: goal_type=mechanical + no contract — allowed",
            "_fixture_mechanical_no_contract",
            0,
            ["✓ plan.md frontmatter"],
            ["objective_contract"],  # no contract line
        ),
        (
            "case 8: schema_version 1.1 + contract WITH delivers dispatches green",
            "_fixture_v11_with_delivers",
            0,
            ["✓ plan.md frontmatter", "✓ objective_contract"],
            ["✗ objective_contract", "advisory"],
        ),
        (
            "case 9: schema_version 1.1 + contract MISSING delivers MUST fail",
            "_fixture_v11_no_delivers",
            1,
            ["✗ objective_contract", "requires a non-empty delivers[]"],
            ["✓ objective_contract"],
        ),
        (
            "case 10: schema_version 1.1 substantive + NO contract MUST fail",
            "_fixture_v11_no_contract",
            1,
            [
                "✗ objective_contract",
                "schema_version>=1.1 (substantive plan)",
                "missing or empty",
            ],
            ["✓ objective_contract"],
        ),
        (
            "case 11: schema_version 1.1 trivial — carve-out, no contract needed",
            "_fixture_v11_trivial_no_contract",
            0,
            ["✓ plan.md frontmatter"],
            ["objective_contract"],  # no contract line at all
        ),
        (
            "case 12: v1.0 grandfathering — contract without delivers passes with advisory",
            "_fixture_parity_with_contract",
            0,
            ["✓ objective_contract", "advisory"],
            ["✗ objective_contract"],
        ),
        (
            "case 13: delivers item carrying a cheap walk proof validates end-to-end",
            "_fixture_v11_proof_walk",
            0,
            ["✓ plan.md frontmatter", "✓ objective_contract"],
            ["✗ objective_contract", "advisory"],
        ),
        (
            "case 14: fix plan with inherits + a one-item delta delivers[] validates",
            "_fixture_v11_inherits_delta",
            0,
            ["✓ plan.md frontmatter", "✓ objective_contract"],
            ["✗ objective_contract", "advisory"],
        ),
    ]

    print("validator objective_contract dispatch tests")
    failures = 0
    for name, fixture, exit_code, expected, forbidden in cases:
        ok, line = _case(name, fixture, exit_code, expected, forbidden)
        print(line)
        if not ok:
            failures += 1

    print()
    if failures == 0:
        print(f"✓ all {len(cases)} dispatch cases pass")
        return 0
    print(f"✗ {failures} of {len(cases)} cases failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
