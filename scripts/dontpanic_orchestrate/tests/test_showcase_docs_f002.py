"""Plan 2026-05-19-005 F002 — showcase docs + wrapper fixture tests.

Covers the 7 acceptance shapes:
  (1) docs/showcase/README.md exists
  (2) repo-root README.md contains the 'See DontPanic on real repos' section
      linking to docs/showcase/README.md
  (3) docs/showcase/README.md links every committed artifact under
      docs/showcase/ (per-target HTML + JSON)
  (4) docs/showcase/README.md 'Coming soon' section references the three
      forward plans by plan ID — Plan 2 F004
      (2026-05-19-002-feat-install-ux-hardening-v0 F004), Plan 003
      (2026-05-09-003-feat-state-projection-v0), and Plan 4.5
      (the ``dontpanic new`` intake primitive, not yet locked)
  (5) docs/showcase/README.md 'Local integration — deferred' section
      enumerates the three concrete promotion triggers
  (6) scripts/showcase.sh is executable AND invokes
      ``python -m dontpanic_orchestrate showcase regen --all`` with
      arg-passthrough
  (7) Makefile has a ``showcase`` target wired to the same command

Run:
    pytest scripts/dontpanic_orchestrate/tests/test_showcase_docs_f002.py -q
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SHOWCASE_DIR = REPO_ROOT / "docs" / "showcase"
SHOWCASE_README = SHOWCASE_DIR / "README.md"
ROOT_README = REPO_ROOT / "README.md"
WRAPPER = REPO_ROOT / "scripts" / "showcase.sh"
MAKEFILE = REPO_ROOT / "Makefile"

# Make scripts/ importable so we can read the F001-authoritative
# showcase config and derive expected artifact filenames from it.
# Drift between F001's config and F002's docs surfaces as a test
# failure rather than a silent doc lie.
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from dontpanic_orchestrate.showcase import (  # noqa: E402
    TargetSpec,
    default_showcase_config,
)


def _expected_artifact_basenames(spec: TargetSpec) -> list[str]:
    """Mirror generator.py's filename convention. Kept in this test
    module (not imported from the generator) on purpose: the test is the
    contract between F001's config and F002's documentation, and an
    accidental rename inside the generator should surface here rather
    than silently re-route the contract."""
    names: list[str] = []
    if "architecture" in spec.supported_artifacts:
        names.append(f"{spec.repo_key}-architecture.html")
        names.append(f"{spec.repo_key}-architecture.json")
    if "validate_plans_strict" in spec.supported_artifacts:
        names.append(f"{spec.repo_key}-validate-plans.json")
    if "drift" in spec.supported_artifacts:
        names.append(f"{spec.repo_key}-drift.json")
    return names

# Artifact files F001 commits under docs/showcase/. The F002 README must
# link every one of these so the index page reflects what's actually
# shipped (per-target HTML + JSON). Drift here means either F001 added an
# artifact without updating the docs, or the docs reference a phantom
# file — both surface as a test failure.
COMMITTED_ARTIFACTS = (
    "dontpanic-architecture.html",
    "dontpanic-architecture.json",
    "dontpanic-validate-plans.json",
    "dontpanic-drift.json",
    "agent-conventions-architecture.html",
    "agent-conventions-architecture.json",
    "axiom-architecture.html",
    "axiom-architecture.json",
    "glam-architecture.html",
    "glam-architecture.json",
    "glam-validate-plans.json",
)


@pytest.fixture(scope="module")
def showcase_readme() -> str:
    assert SHOWCASE_README.is_file(), f"missing {SHOWCASE_README}"
    return SHOWCASE_README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def root_readme() -> str:
    assert ROOT_README.is_file(), f"missing {ROOT_README}"
    return ROOT_README.read_text(encoding="utf-8")


def test_showcase_readme_exists() -> None:
    assert SHOWCASE_README.is_file(), (
        f"{SHOWCASE_README.relative_to(REPO_ROOT)} must exist — F002 acceptance (1)"
    )
    body = SHOWCASE_README.read_text(encoding="utf-8")
    # Sanity: file isn't a stub. Use intro phrasing from the plan steps.
    assert "See DontPanic used on real repos" in body, (
        "docs/showcase/README.md must carry the intro phrase"
    )


def test_root_readme_links_to_showcase(root_readme: str) -> None:
    """Acceptance (2): repo-root README has a 'See DontPanic on real repos'
    section that links to docs/showcase/README.md."""
    assert "See DontPanic on real repos" in root_readme, (
        "README.md missing 'See DontPanic on real repos' section header"
    )
    # The section must point at the showcase index. Accept either the
    # './docs/showcase/' or './docs/showcase/README.md' form.
    assert re.search(
        r"\]\(\./docs/showcase/(?:README\.md)?\)", root_readme
    ), "README.md section must link to docs/showcase/README.md"


def test_showcase_readme_links_every_committed_artifact(showcase_readme: str) -> None:
    """Acceptance (3): the index page references each committed artifact
    file by its basename. If an artifact is committed but not linked, the
    operator landing on docs/showcase/README.md can't find it."""
    missing = [name for name in COMMITTED_ARTIFACTS if name not in showcase_readme]
    assert not missing, (
        f"docs/showcase/README.md does not reference committed artifacts: {missing}"
    )


def test_showcase_readme_has_coming_soon_with_forward_plan_ids(showcase_readme: str) -> None:
    """Acceptance (4): 'Coming soon' section references each of the three
    forward plans by plan ID so reviewers can trace which plan owns each
    deferred artifact. Plan 4.5 isn't locked yet so it only carries the
    roadmap label + Plan 4.5 designation."""
    assert "Coming soon" in showcase_readme, (
        "docs/showcase/README.md missing 'Coming soon' section"
    )
    # Install report — Plan 2 F004.
    assert "Plan 2 F004" in showcase_readme, "missing 'Plan 2 F004' reference"
    assert "2026-05-19-002-feat-install-ux-hardening-v0" in showcase_readme, (
        "missing Plan 2 install-ux plan ID under Coming soon"
    )
    # State projection — Plan 003.
    assert "Plan 003" in showcase_readme, "missing 'Plan 003' reference"
    assert "2026-05-09-003-feat-state-projection-v0" in showcase_readme, (
        "missing Plan 003 state-projection plan ID under Coming soon"
    )
    # Work-request / intake — Plan 4.5 (not yet locked; roadmap label).
    assert "Plan 4.5" in showcase_readme, "missing 'Plan 4.5' reference"
    assert "intake" in showcase_readme.lower(), (
        "Plan 4.5 row must describe the intake primitive context"
    )


def test_showcase_readme_has_local_integration_deferred_section(showcase_readme: str) -> None:
    """Acceptance (5): 'Local integration — deferred' section codifies the
    3 concrete triggers from this plan's forbidden_decisions. Body must
    name each trigger clearly enough that the team can recognize one when
    it fires."""
    assert "Local integration" in showcase_readme and "deferred" in showcase_readme, (
        "missing 'Local integration — deferred' section"
    )
    # Trigger 1: committed architecture.json in target repo.
    assert re.search(r"committed `architecture\.json`", showcase_readme, re.IGNORECASE), (
        "missing trigger 1 — committed architecture.json"
    )
    # Trigger 2: target-repo CI drift checks (the cited phrase in the plan).
    assert re.search(r"target.repo CI", showcase_readme, re.IGNORECASE), (
        "missing trigger 2 — target-repo CI drift checks"
    )
    # Trigger 3: non-DontPanic contributors needing the map in-repo.
    assert re.search(r"non.DontPanic contributors", showcase_readme, re.IGNORECASE), (
        "missing trigger 3 — non-DontPanic contributors"
    )


def test_showcase_sh_is_executable_and_invokes_regen_with_passthrough() -> None:
    """Acceptance (6): scripts/showcase.sh exists, has the executable bit,
    invokes the CLI with --all, and forwards extra args via "$@"."""
    assert WRAPPER.is_file(), f"missing {WRAPPER.relative_to(REPO_ROOT)}"
    mode = WRAPPER.stat().st_mode
    assert mode & 0o111, "scripts/showcase.sh must be executable"
    body = WRAPPER.read_text(encoding="utf-8")
    assert body.startswith("#!/bin/bash") or body.startswith("#!/usr/bin/env bash"), (
        "scripts/showcase.sh must declare a bash shebang"
    )
    assert "set -euo pipefail" in body, "scripts/showcase.sh must use strict mode"
    assert "python -m dontpanic_orchestrate showcase regen --all" in body, (
        "scripts/showcase.sh must invoke the canonical regen command"
    )
    assert '"$@"' in body, (
        "scripts/showcase.sh must forward extra args via quoted \"$@\""
    )


def test_makefile_has_showcase_target() -> None:
    """Acceptance (7): Makefile carries a ``showcase`` target that maps to
    the canonical regen command. .PHONY declaration prevents collision
    with a hypothetical ./showcase file."""
    assert MAKEFILE.is_file(), f"missing {MAKEFILE.relative_to(REPO_ROOT)}"
    body = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^\.PHONY:.*\bshowcase\b", body, re.MULTILINE), (
        "Makefile missing '.PHONY: showcase' declaration"
    )
    assert re.search(r"^showcase:\s*$", body, re.MULTILINE), (
        "Makefile missing 'showcase:' target line"
    )
    assert "python -m dontpanic_orchestrate showcase regen --all" in body, (
        "Makefile 'showcase' target must invoke the canonical regen command"
    )


def test_showcase_readme_matches_f001_supported_artifacts_matrix(
    showcase_readme: str,
) -> None:
    """F002 iteration 1 (D005 reconciliation): the index page must reflect
    F001's authoritative per-target ``supported_artifacts`` declaration,
    not a hardcoded artifact list. For each TargetSpec in
    ``default_showcase_config()``:

      - every expected artifact basename (derived from supported_artifacts)
        MUST appear in docs/showcase/README.md;
      - if a target lacks ``validate_plans_strict``, the doc MUST carry an
        explicit reason near the target's section (so omissions read as
        intentional and not as a missing entry).

    This protects against the F002 iter-0 failure mode (the docs page
    silently omitting a required entry because the step text and the
    config disagreed). If F001 later flips ``has_dontpanic_plans=True``
    on agent-conventions, the resulting ``agent-conventions-validate-plans.json``
    requirement automatically becomes a test failure until the doc is
    updated."""
    config = default_showcase_config()
    assert config, "default_showcase_config() returned empty list"

    missing_per_target: dict[str, list[str]] = {}
    for spec in config:
        absent = [
            basename
            for basename in _expected_artifact_basenames(spec)
            if basename not in showcase_readme
        ]
        if absent:
            missing_per_target[spec.repo_key] = absent
    assert not missing_per_target, (
        "docs/showcase/README.md is missing per-target artifacts required by "
        f"default_showcase_config() supported_artifacts: {missing_per_target}"
    )

    # Reconciliation invariant: any target that doesn't carry
    # ``validate_plans_strict`` should have a near-by explanation in the
    # docs so reviewers can tell the omission apart from a doc bug.
    # We look for a description anywhere in the same H2 section as the
    # target's label. ``re.split`` on the H2 marker preserves section
    # boundaries; we find the section whose body links the target's
    # architecture artifact, then assert a reason is present.
    sections = re.split(r"^## ", showcase_readme, flags=re.MULTILINE)
    for spec in config:
        if "validate_plans_strict" in spec.supported_artifacts:
            continue
        arch_basename = f"{spec.repo_key}-architecture.json"
        owning_sections = [s for s in sections if arch_basename in s]
        assert owning_sections, (
            f"could not locate the H2 section for target {spec.repo_key!r} "
            f"(looked for {arch_basename})"
        )
        section_body = owning_sections[0].lower()
        reason_signals = (
            "has_dontpanic_plans=false",
            "no dontpanic-style plan dirs",
            "no docs/plans/",
            "architecture-only",
            "no plan dirs",
        )
        assert any(signal in section_body for signal in reason_signals), (
            f"target {spec.repo_key!r} lacks validate_plans_strict but its "
            "section does not explain why. Add a reconciliation sentence "
            "(e.g. 'architecture-only because ...') so an omission can be "
            "distinguished from a doc bug."
        )
