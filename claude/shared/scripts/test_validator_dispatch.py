"""Validator dispatch test — agent-conventions v1.3.1.

Locks the artifact-classification contract for the plan validator at
``schemas/v1.0/validate.py``. Four cases:

  1. ``signoff*.json``                  -> Signoff model, exit 0
  2. ``*-i\\d+.json``                    -> Audit envelope, exit 0
  3. ``gate-state.json`` (auxiliary)    -> skip + ``⊘`` info-line, exit 0
  4. anything else under ``audit/``     -> warn + ``⚠`` info-line, exit 0
                                           (NOT exit 1 — D005)

Each fixture lives under ``tests/validator/_fixture_*/`` and is a
minimal-but-real plan dir (plan.md frontmatter + features.json + an
``audit/`` directory with the artifact under test).

Usage:

    python3 scripts/test_validator_dispatch.py

Exit 0 if all four cases pass; 1 otherwise.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "schemas" / "v1.0" / "validate.py"
FIXTURES_DIR = REPO_ROOT / "tests" / "validator"


def _run_validator(plan_dir: Path) -> tuple[int, str]:
    """Subprocess the validator against a single plan dir; return (exit, stdout)."""
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), str(plan_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def _case(name: str, fixture: str, expected_exit: int, expected_substrings: list[str], forbidden_substrings: list[str]) -> tuple[bool, str]:
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
            "case 1: signoff*.json dispatches to Signoff model",
            "_fixture_signoff",
            0,
            ["✓ audit/signoff-fixture.json"],
            ["⚠", "⊘", "✗ audit/signoff-fixture.json"],
        ),
        (
            "case 2: *-i\\d+.json dispatches to Audit model",
            "_fixture_audit_envelope",
            0,
            ["✓ audit/claude-implementer-i0.json"],
            ["⚠", "⊘", "✗ audit/claude-implementer-i0.json"],
        ),
        (
            "case 3: gate-state.json skipped as known auxiliary",
            "_fixture_aux_gate_state",
            0,
            ["⊘ audit/gate-state.json", "auxiliary, skipped"],
            ["✓ audit/gate-state.json", "✗ audit/gate-state.json"],
        ),
        (
            "case 4: unknown audit JSON warned + skipped (NOT error)",
            "_fixture_unknown_audit",
            0,  # D005: warn but do not fail
            ["⚠ audit/breaker-state.json", "unknown audit artifact, skipped"],
            ["✗ audit/breaker-state.json", "✓ audit/breaker-state.json"],
        ),
    ]

    print("validator dispatch tests")
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
