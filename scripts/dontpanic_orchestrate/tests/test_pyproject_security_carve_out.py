"""F002 acceptance — pyproject.toml security carve-out is locked to an exact tuple.

Plan 2026-05-08-001 D007: the `**/tests/**` per-file-ignore list MAY include
ONLY the four rules whose test-side count is materially larger than runtime
AND whose pattern is genuinely test-idiomatic: S101, S607, S108, S603. Plus
the pre-existing B011 (bugbear false-positive on test-style asserts).

Adding any rule to this list requires updating this test, which surfaces the
change in the diff and forces a fresh decision rather than silent growth.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_pyproject_security_carve_out.py
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover — Python 3.10 falls back to tomli (already in env)
    import tomli as tomllib  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "pyproject.toml"


# Locked set per D007. Order does not matter for ruff's behavior, but pin a
# canonical sorted form so the assertion message is deterministic.
LOCKED_TESTS_IGNORE = frozenset({"B011", "S101", "S603", "S607", "S108"})


def _load_per_file_ignores() -> dict[str, list[str]]:
    with PYPROJECT.open("rb") as f:
        data = tomllib.load(f)
    return data["tool"]["ruff"]["lint"]["per-file-ignores"]


def test_tests_per_file_ignore_matches_locked_tuple() -> None:
    """The `**/tests/**` ignore list must equal the locked four-rule + B011 set.

    If this fails because a new rule was added: update LOCKED_TESTS_IGNORE
    here AND record a D-entry on plan 2026-05-08-001 (or its successor)
    citing the new rule's test-idiom rationale. Do NOT just add to the list
    — the test exists to force the conversation.
    """
    per_file = _load_per_file_ignores()
    actual = frozenset(per_file.get("**/tests/**", []))
    assert actual == LOCKED_TESTS_IGNORE, (
        f"tests/** per-file-ignore drift detected.\n"
        f"  locked: {sorted(LOCKED_TESTS_IGNORE)}\n"
        f"  actual: {sorted(actual)}\n"
        f"  diff:   {sorted(actual ^ LOCKED_TESTS_IGNORE)}\n"
        f"  Update LOCKED_TESTS_IGNORE + record a D-entry citing the new rule's "
        f"test-idiom rationale; do not silently expand the carve-out."
    )


def test_no_other_per_file_ignore_paths_added_silently() -> None:
    """Only `**/tests/**` is allowed in per-file-ignores. Adding new path
    globs (e.g. for runtime trees) requires explicit operator approval per
    D004 — surface as a scope-change request, not a silent edit."""
    per_file = _load_per_file_ignores()
    expected_paths = {"**/tests/**"}
    actual_paths = set(per_file.keys())
    assert actual_paths == expected_paths, (
        f"per-file-ignores path drift detected.\n"
        f"  locked: {sorted(expected_paths)}\n"
        f"  actual: {sorted(actual_paths)}\n"
        f"  Adding a new path glob requires a D-entry and explicit approval — "
        f"see D004 of plan 2026-05-08-001."
    )
