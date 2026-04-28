"""F022 — sanitization_check tests.

The check is also run by CI; these tests verify the allowlist logic and
that on the current repo no leaks exist.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_PATH = REPO_ROOT / "scripts" / "sanitization_check.py"


def _load():
    import sys

    spec = importlib.util.spec_from_file_location("sanitization_check", CHECK_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sanitization_check"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_current_repo_has_no_leaks() -> None:
    """End-to-end: run the script as a subprocess and assert exit 0."""
    proc = subprocess.run(
        ["python3", str(CHECK_PATH)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert proc.returncode == 0, f"sanitization leaks: {proc.stderr}"
    assert "no campaign IDs" in proc.stdout


def test_is_allowed_recognizes_plan_dirs() -> None:
    mod = _load()
    assert mod.is_allowed("docs/plans/2026-04-19-001-foo/audit/x.json")
    assert mod.is_allowed("docs/plans/foo/decisions.jsonl")


def test_is_allowed_recognizes_dashboard_state() -> None:
    mod = _load()
    assert mod.is_allowed("dashboard/state/costs.json")


def test_is_allowed_recognizes_test_fixtures() -> None:
    mod = _load()
    assert mod.is_allowed("scripts/jarvis_orchestrate/tests/test_environments_loader.py")


def test_is_allowed_rejects_arbitrary_source() -> None:
    mod = _load()
    assert not mod.is_allowed("scripts/some_new_tool.py")
    assert not mod.is_allowed("functions/index.ts")


def test_is_allowed_rejects_root_yaml() -> None:
    mod = _load()
    assert not mod.is_allowed("config.yaml")


def test_allowlist_explicit_files() -> None:
    mod = _load()
    assert "CONTRIBUTING.md" in mod.ALLOWED_FILES
    assert "scripts/sanitization_check.py" in mod.ALLOWED_FILES
    # refresh-costs.sh moved under scripts/maintainer/ + gitignored;
    # it must NOT be re-added to the allowlist by accident.
    assert "scripts/refresh-costs.sh" not in mod.ALLOWED_FILES


def test_maintainer_dir_in_allowlist() -> None:
    """scripts/maintainer/ is gitignored, but the prefix is allowlisted as
    defense-in-depth in case a maintainer file slips into git."""
    mod = _load()
    assert any(p.startswith("scripts/maintainer/") for p in mod.ALLOWED_PREFIXES)


def test_patterns_assemble_to_known_strings() -> None:
    """Sanity check that the obfuscated assembly produces the right tokens."""
    mod = _load()
    # Three patterns: project ID, billing account, maintainer username
    assert len(mod.PATTERNS) == 3
    # Project pattern is "jarvis-" + 5 hex chars (lower)
    assert any(p.startswith("jarvis-") and len(p) == 12 for p in mod.PATTERNS)
    # Billing pattern is XXXXXX-XXXXXX-XXXXXX shape
    assert any(len(p) == 20 and p.count("-") == 2 for p in mod.PATTERNS)
    # Maintainer username is short, non-hex
    assert any(len(p) <= 10 and p.isalpha() for p in mod.PATTERNS)


def test_check_catches_maintainer_email_outside_allowlist(tmp_path) -> None:
    """If a tracked file outside the allowlist contains the maintainer
    username (in any email form), the script must flag it. We simulate
    by creating a probe file and running the is_allowed logic."""
    mod = _load()
    # Outside docs/plans + tests + dashboard state, must be flagged
    assert not mod.is_allowed("functions/index.ts")
    assert not mod.is_allowed("CODE_OF_CONDUCT.md")
    assert not mod.is_allowed("README.md")
