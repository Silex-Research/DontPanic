"""F009 — advisory CHANGELOG <-> manifest drift lint (warn-only, D008/D018).

The drift lint asserts that every operator-visible CHANGELOG dated section AFTER
the manifest baseline has a matching ``releases.json`` entry. It is WARN-ONLY in
v0 (D008): it returns advisory findings and never blocks, raises, or exits
non-zero. Sections at/before the baseline are intentionally exempt (D018).

Run: PYTHONPATH=scripts pytest \
        scripts/dontpanic_orchestrate/tests/test_upgrade_drift_lint_f009.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.release_manifest import (  # noqa: E402
    load_release_manifest,
)
from dontpanic_orchestrate.upgrade_drift_lint import (  # noqa: E402
    DEFAULT_CHANGELOG_RELPATH,
    DriftFinding,
    check_changelog_manifest_drift,
    format_findings,
    lint_repo,
    parse_changelog_sections,
)
from dontpanic_orchestrate.upgrade_releases_model import (  # noqa: E402
    UpgradeManifest,
    UpgradeRelease,
)

DOCS_SEED = REPO_ROOT / "docs" / "upgrade" / "releases.json"
REAL_CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def _manifest(baseline_date: str, release_dates: list[str]) -> UpgradeManifest:
    """Build an in-memory manifest with the given baseline + release dates."""
    return UpgradeManifest(
        baseline_release="baseline",
        baseline_date=baseline_date,
        releases=[
            UpgradeRelease(id=f"r-{d}-{i}", date=d, summary=f"release {d}", actions=[])
            for i, d in enumerate(release_dates)
        ],
    )


# ──────────────────────────────  parsing  ──────────────────────────────


def test_parse_changelog_sections_reads_dated_headers() -> None:
    text = (
        "# DontPanic Changelog\n\nPreamble.\n\n"
        "## 2026-06-17 — Experience Readiness Gate\n\n### Added\n- thing\n\n"
        "## 2026-06-06 — README rewrite\n\n### Changed\n- thing\n"
    )
    sections = parse_changelog_sections(text)
    dates = [s.date for s in sections]
    assert dates == ["2026-06-17", "2026-06-06"]
    assert "Experience Readiness" in sections[0].title
    # A real source line number is captured for the operator pointer.
    assert all(s.line_number > 0 for s in sections)


def test_parse_ignores_non_date_h2_and_format_block() -> None:
    text = (
        "## Format\n\nblah\n\n"
        "## Relationship to something\n\nblah\n\n"
        "## 2026-06-22 — real entry\n\n- x\n"
    )
    sections = parse_changelog_sections(text)
    assert [s.date for s in sections] == ["2026-06-22"]


# ──────────────────────────────  baseline scope  ──────────────────────────────


def test_section_at_or_before_baseline_is_exempt() -> None:
    # D018: sections at/before the baseline are intentionally not seeded; the lint
    # must never flag them.
    text = (
        "## 2026-06-13 — baseline-day change\n\n- x\n\n"
        "## 2026-06-05 — older change\n\n- y\n"
    )
    manifest = _manifest("2026-06-13", [])
    findings = check_changelog_manifest_drift(text, manifest)
    assert findings == []


def test_section_after_baseline_without_entry_is_flagged() -> None:
    text = "## 2026-06-22 — new operator surface\n\n- x\n"
    manifest = _manifest("2026-06-13", ["2026-06-17"])
    findings = check_changelog_manifest_drift(text, manifest)
    assert len(findings) == 1
    assert isinstance(findings[0], DriftFinding)
    assert findings[0].section_date == "2026-06-22"
    assert "new operator surface" in findings[0].section_title


def test_section_after_baseline_with_matching_entry_not_flagged() -> None:
    text = "## 2026-06-17 — covered surface\n\n- x\n"
    manifest = _manifest("2026-06-13", ["2026-06-17"])
    assert check_changelog_manifest_drift(text, manifest) == []


def test_multiple_sections_same_date_all_covered_by_one_entry() -> None:
    text = (
        "## 2026-06-17 — first rollup\n\n- a\n\n"
        "## 2026-06-17 — second rollup\n\n- b\n"
    )
    manifest = _manifest("2026-06-13", ["2026-06-17"])
    assert check_changelog_manifest_drift(text, manifest) == []


def test_only_uncovered_post_baseline_sections_flagged_in_mixed_file() -> None:
    text = (
        "## 2026-06-22 — uncovered new\n\n- a\n\n"
        "## 2026-06-17 — covered\n\n- b\n\n"
        "## 2026-06-05 — exempt pre-baseline\n\n- c\n"
    )
    manifest = _manifest("2026-06-13", ["2026-06-17"])
    findings = check_changelog_manifest_drift(text, manifest)
    assert [f.section_date for f in findings] == ["2026-06-22"]


# ──────────────────────────────  warn-only contract  ──────────────────────────────


def test_lint_repo_against_real_changelog_is_warn_only_list() -> None:
    # Warn-only (D008): linting the real repo returns a list and never raises.
    findings = lint_repo(changelog_path=REAL_CHANGELOG, manifest=load_release_manifest(DOCS_SEED))
    assert isinstance(findings, list)
    assert all(isinstance(f, DriftFinding) for f in findings)


def test_real_changelog_historical_section_is_covered() -> None:
    manifest = load_release_manifest(DOCS_SEED)
    findings = lint_repo(changelog_path=REAL_CHANGELOG, manifest=manifest)
    flagged_dates = {f.section_date for f in findings}
    # The 2026-06-17 Experience-Readiness section maps to the dated manifest entry,
    # so it is never flagged.
    assert "2026-06-17" not in flagged_dates
    # Every finding is strictly AFTER the baseline (pre-baseline sections exempt).
    for f in findings:
        assert f.section_date > manifest.baseline_date


def test_format_findings_is_human_readable_and_empty_safe() -> None:
    assert "no drift" in format_findings([]).lower()
    rendered = format_findings(
        [DriftFinding(section_date="2026-06-22", section_title="X", message="m", line_number=3)]
    )
    assert "2026-06-22" in rendered
    assert "advisory" in rendered.lower()


def test_default_changelog_relpath_points_at_root_changelog() -> None:
    assert DEFAULT_CHANGELOG_RELPATH.name == "CHANGELOG.md"
