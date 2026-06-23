"""F009 — advisory CHANGELOG <-> upgrade-manifest drift lint (warn-only, D008/D018).

The upgrade release manifest (``docs/upgrade/releases.json``) is the MACHINE
contract for upgrade intent; the root ``CHANGELOG.md`` is the human, prose record
of operator-visible change. They can drift: a release can add an operator-visible
CHANGELOG section without a matching manifest entry, so ``dontpanic doctor
--upgrade`` would stay silent about a change the operator actually saw in the
changelog.

This lint catches that drift. It asserts that every operator-visible CHANGELOG
*dated section* AFTER the manifest baseline has a matching ``releases.json`` entry
(matched by date). It is deliberately scoped two ways:

* **Baseline scope (D018 / D039).** Only sections dated STRICTLY AFTER
  ``baseline_date`` are checked. Sections at/before the baseline are intentionally
  not seeded into the manifest (the manifest seeds the rollout history forward
  from the baseline), so flagging them would be noise.

* **Warn-only in v0 (D008).** This module only ever RETURNS advisory findings. It
  never raises on drift, never blocks a build, and its ``main`` entry point always
  exits 0. A hard gate would over-constrain before the manifest format settles;
  drift is surfaced as advice the author confirms, not a wall.

Matching is by DATE, not title: the CHANGELOG rolls several plans up into one
dated section (e.g. the 2026-06-17 Experience-Readiness section covers three
plans), so a section is considered covered iff ANY manifest release shares its
date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dontpanic_orchestrate.release_manifest import load_release_manifest
from dontpanic_orchestrate.upgrade_releases_model import UpgradeManifest

# Repo-relative location of the human-authored root changelog. Resolved up from
# this module's package dir (scripts/dontpanic_orchestrate -> repo root).
_PKG_DIR = Path(__file__).resolve().parent
DEFAULT_CHANGELOG_RELPATH = _PKG_DIR.parents[1] / "CHANGELOG.md"

# A dated CHANGELOG section header: ``## YYYY-MM-DD — title`` (the em-dash and
# title are optional). Non-dated H2 headers ("## Format", "## Relationship …")
# are intentionally NOT matched, so only real release sections are linted.
_SECTION_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\b[ \t]*[—\-–:]*[ \t]*(.*?)\s*$")


@dataclass(frozen=True)
class ChangelogSection:
    """A dated section parsed from the root CHANGELOG."""

    date: str
    title: str
    line_number: int


@dataclass(frozen=True)
class DriftFinding:
    """One advisory drift finding: a post-baseline section with no manifest entry."""

    section_date: str
    section_title: str
    message: str
    line_number: int


def parse_changelog_sections(text: str) -> list[ChangelogSection]:
    """Parse the dated ``## YYYY-MM-DD`` sections out of CHANGELOG text.

    Order is preserved (reverse-chronological, as authored). Non-dated H2 headers
    are ignored, so the ``## Format`` / ``## Relationship …`` preamble blocks never
    register as releases.
    """
    sections: list[ChangelogSection] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        match = _SECTION_RE.match(raw)
        if match is None:
            continue
        section_date, title = match.group(1), match.group(2).strip()
        sections.append(
            ChangelogSection(date=section_date, title=title, line_number=lineno)
        )
    return sections


def check_changelog_manifest_drift(
    changelog_text: str, manifest: UpgradeManifest
) -> list[DriftFinding]:
    """Return advisory drift findings for ``changelog_text`` against ``manifest``.

    A finding is raised for every CHANGELOG dated section whose date is STRICTLY
    AFTER ``manifest.baseline_date`` (D018) and for which NO manifest release shares
    that date. Sections at/before the baseline are exempt. This function is pure and
    never raises on drift — it only collects findings (warn-only, D008).
    """
    try:
        baseline = date.fromisoformat(manifest.baseline_date)
    except ValueError:
        # Defensive: the manifest model normally guarantees an ISO baseline_date,
        # but warn-only means we never raise — if it is somehow malformed we
        # cannot compute drift, so report none (D008).
        return []
    covered_dates = {release.date for release in manifest.releases}

    findings: list[DriftFinding] = []
    for section in parse_changelog_sections(changelog_text):
        try:
            section_day = date.fromisoformat(section.date)
        except ValueError:
            continue  # malformed CHANGELOG date -> skip this section, never raise (D008)
        if section_day <= baseline:
            continue  # at/before baseline -> intentionally not seeded (D018)
        if section.date in covered_dates:
            continue  # a manifest release shares this date -> covered
        title = section.title or "(untitled)"
        findings.append(
            DriftFinding(
                section_date=section.date,
                section_title=title,
                message=(
                    f"CHANGELOG section dated {section.date} ({title}) has no matching "
                    f"docs/upgrade/releases.json entry; add a manifest release so "
                    f"`dontpanic doctor --upgrade` reflects this operator-visible change."
                ),
                line_number=section.line_number,
            )
        )
    return findings


def lint_repo(
    changelog_path: Path | str | None = None,
    manifest: UpgradeManifest | None = None,
) -> list[DriftFinding]:
    """Convenience: lint the real repo CHANGELOG against the loaded manifest.

    Warn-only (D008): returns the advisory findings list and never raises on drift.
    ``changelog_path`` defaults to the repo root ``CHANGELOG.md``; ``manifest``
    defaults to the packaged release manifest.
    """
    path = Path(changelog_path) if changelog_path is not None else DEFAULT_CHANGELOG_RELPATH
    loaded_manifest = manifest if manifest is not None else load_release_manifest()
    text = path.read_text(encoding="utf-8")
    return check_changelog_manifest_drift(text, loaded_manifest)


def format_findings(findings: list[DriftFinding]) -> str:
    """Render findings as a human-readable advisory block (empty-safe)."""
    if not findings:
        return "CHANGELOG <-> manifest drift lint: no drift (all post-baseline sections covered)."
    lines = [
        f"CHANGELOG <-> manifest drift lint (advisory, warn-only): "
        f"{len(findings)} section(s) lack a manifest entry:",
    ]
    for finding in findings:
        lines.append(
            f"  - CHANGELOG.md:{finding.line_number} "
            f"[{finding.section_date}] {finding.section_title}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Warn-only CLI entry point: print the advisory and ALWAYS exit 0 (D008).

    Never raises: any failure loading the manifest or reading the CHANGELOG
    (missing/unreadable file, malformed JSON) is degraded to an advisory line and
    a 0 exit, so the lint can never block a build (the F009 warn-only invariant).
    """
    try:
        findings = lint_repo()
    except Exception as exc:  # noqa: BLE001 — warn-only: degrade, never block (D008)
        print(
            "CHANGELOG <-> manifest drift lint: skipped (could not run: "
            f"{type(exc).__name__}). Advisory-only; not a failure."
        )
        return 0
    print(format_findings(findings))
    return 0


__all__ = [
    "DEFAULT_CHANGELOG_RELPATH",
    "ChangelogSection",
    "DriftFinding",
    "check_changelog_manifest_drift",
    "format_findings",
    "lint_repo",
    "main",
    "parse_changelog_sections",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
