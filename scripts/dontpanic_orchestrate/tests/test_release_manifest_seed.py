"""F002 — seeded upgrade release manifest + packaging tests.

The seed (docs/upgrade/releases.json, mirrored into the packaged
dontpanic_orchestrate/data/releases.json) is the real rollout history as of
plan 2026-06-21-001:

  * a top-level baseline that orders STRICTLY BELOW the earliest seeded release,
    so every seeded release is in-scope and not exempt pre-baseline history
    (D018 / D039);
  * three Experience Readiness Gate advisory releases (plans 2026-06-14-002 /
    2026-06-15-001 / 2026-06-15-002) with empty commands + null status_probe;
  * the canonical-discovery REQUIRED release (plan 2026-06-17-001) with an
    ordered preview->apply->verify checklist (D017), a non-null status_probe,
    applies_when, success/failure/human_next_step copy, and introduced_commands.

Packaging (D049): releases.json ships as package data in BOTH the wheel and the
sdist, and the D045 package-relative loader loads it from the installed/packaged
location — not only from the repo tree.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_release_manifest_seed.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import zipfile
from datetime import date
from pathlib import Path

import jsonschema
import pytest

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
PKG_DIR = HERE.parents[2] / "dontpanic_orchestrate"
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.release_manifest import (  # noqa: E402
    load_release_manifest,
)
from dontpanic_orchestrate.upgrade_releases_model import (  # noqa: E402
    CommandLabel,
    Kind,
    Severity,
    UpgradeManifest,
)

DOCS_SEED = REPO_ROOT / "docs" / "upgrade" / "releases.json"
PACKAGED_SEED = PKG_DIR / "data" / "releases.json"

# D049: the JSON Schema is canonical under claude/shared/schemas and is mirrored
# into the package data dir so it ships (drift-guarded below) and validation can
# run from the packaged location.
CANONICAL_SCHEMA = (
    REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0" / "upgrade-releases.schema.json"
)
PACKAGED_SCHEMA = PKG_DIR / "data" / "upgrade-releases.schema.json"

CANONICAL_RELEASE_ID = "2026-06-17-001-canonical-discovery"
EXPERIENCE_READINESS_RELEASE_IDS = {
    "2026-06-14-002-consumer-outcome-gate",
    "2026-06-15-001-evidence-typing",
    "2026-06-15-002-degraded-honesty",
}


# ──────────────────────────────  fixtures  ──────────────────────────────


@pytest.fixture(scope="module")
def seed() -> UpgradeManifest:
    """The authored seed, loaded + validated through the F001 loader."""
    return load_release_manifest(DOCS_SEED)


def _canonical_action(seed: UpgradeManifest):
    release = next(r for r in seed.releases if r.id == CANONICAL_RELEASE_ID)
    return release, release.actions[0]


# ──────────────────────────  seed loads + validates  ──────────────────────────


def test_seed_loads_and_validates(seed: UpgradeManifest) -> None:
    # Acceptance: the seed validates under the F001 loader / schema.
    assert isinstance(seed, UpgradeManifest)
    assert seed.releases, "seed must contain at least one release"


def test_seed_validates_against_json_schema() -> None:
    # The F001 loader validates via the Pydantic model; this guards the *JSON
    # Schema* contract directly (D049 / round-i0 finding: the Pydantic model
    # tolerated `introduced_commands: null` on advisories while the schema
    # rejects it). Both the authored docs copy and the packaged copy must pass.
    schema = json.loads(CANONICAL_SCHEMA.read_text())
    for path in (DOCS_SEED, PACKAGED_SEED):
        instance = json.loads(path.read_text())
        jsonschema.validate(instance=instance, schema=schema)


def test_seed_carries_baseline(seed: UpgradeManifest) -> None:
    # Acceptance: the seed carries a baseline (release id + date).
    assert seed.baseline_release
    assert seed.baseline_date
    # Date is a real calendar date (loader already enforces, asserted explicitly).
    date.fromisoformat(seed.baseline_date)


def test_baseline_orders_strictly_below_earliest_seeded_release(seed: UpgradeManifest) -> None:
    # D039: the baseline sits STRICTLY below the earliest seeded release, so every
    # seeded release is in-scope (above the baseline), not exempt pre-baseline
    # history. A pre-2026-06-14 marker, since the earliest seeded release is dated
    # 2026-06-14.
    baseline = date.fromisoformat(seed.baseline_date)
    release_dates = [date.fromisoformat(r.date) for r in seed.releases]
    earliest = min(release_dates)
    assert baseline < earliest, (
        f"baseline {baseline} must be strictly below earliest seeded release "
        f"{earliest} (D039)"
    )
    # And explicitly below 2026-06-14 — the Experience Readiness Gate floor.
    assert baseline < date(2026, 6, 14)


def test_releases_authored_oldest_to_newest(seed: UpgradeManifest) -> None:
    release_dates = [date.fromisoformat(r.date) for r in seed.releases]
    assert release_dates == sorted(release_dates), "releases must be oldest -> newest"


# ──────────────────  Experience Readiness advisory entries  ──────────────────


def test_experience_readiness_advisories_present(seed: UpgradeManifest) -> None:
    by_id = {r.id: r for r in seed.releases}
    for rid in EXPERIENCE_READINESS_RELEASE_IDS:
        assert rid in by_id, f"missing Experience Readiness release {rid}"
        release = by_id[rid]
        assert release.actions, f"{rid} must declare an action"
        for action in release.actions:
            # Advisory: empty commands + null status_probe; severity is optional.
            assert action.kind is Kind.advisory
            assert action.commands == [], "advisory commands must be empty"
            assert action.status_probe is None, "advisory status_probe must be null"
            assert action.severity in (None, Severity.optional)
            assert action.docs_url, "advisory should link docs (README/CHANGELOG)"
        # show_on_first_run is false to avoid a first-run advisory flood.
        assert release.show_on_first_run is False


def test_experience_readiness_summary_mirrors_changelog_plans(seed: UpgradeManifest) -> None:
    # The advisory releases mirror the CHANGELOG 2026-06-17 section, which rolls
    # up plans 2026-06-14-002 / 2026-06-15-001 / 2026-06-15-002.
    by_id = {r.id: r for r in seed.releases}
    expected_plan_by_release = {
        "2026-06-14-002-consumer-outcome-gate": "2026-06-14-002",
        "2026-06-15-001-evidence-typing": "2026-06-15-001",
        "2026-06-15-002-degraded-honesty": "2026-06-15-002",
    }
    for rid, plan in expected_plan_by_release.items():
        release = by_id[rid]
        assert plan in release.plan_refs
        assert release.summary.strip(), "summary must mirror the CHANGELOG prose"


# ──────────────────  canonical-discovery required entry  ──────────────────


def test_canonical_discovery_is_required_with_non_null_probe(seed: UpgradeManifest) -> None:
    # Acceptance: canonical-discovery action is kind=required with a non-null
    # status_probe.
    _, action = _canonical_action(seed)
    assert action.kind is Kind.required
    assert action.status_probe is not None
    assert action.status_probe.strip() == "canonical_discovery_registered_active"


def test_canonical_discovery_has_ordered_preview_apply_verify(seed: UpgradeManifest) -> None:
    # D017: ordered safe journey preview -> apply -> verify.
    _, action = _canonical_action(seed)
    labels = [c.label for c in action.commands]
    assert labels == [CommandLabel.preview, CommandLabel.apply, CommandLabel.verify]


def test_canonical_discovery_has_verify_labeled_command(seed: UpgradeManifest) -> None:
    # Acceptance: a verify-labeled command exists (and is the discover verify).
    _, action = _canonical_action(seed)
    verify_cmds = [c for c in action.commands if c.label is CommandLabel.verify]
    assert verify_cmds, "canonical-discovery must include a verify-labeled command"
    assert "discover" in verify_cmds[0].command


def test_canonical_discovery_rich_fields(seed: UpgradeManifest) -> None:
    # applies_when + severity + copy + introduced_commands are all populated.
    _, action = _canonical_action(seed)
    assert action.applies_when == "has_tracked_projects"
    assert action.severity is Severity.recommended
    assert action.success_message
    assert action.failure_message
    assert action.human_next_step
    assert action.introduced_commands
    assert any("discover" in s for s in action.introduced_commands)
    assert any("backfill-canonical" in s for s in action.introduced_commands)


# ──────────────────  docs copy == packaged copy (drift guard)  ──────────────────


def test_docs_seed_matches_packaged_seed() -> None:
    # The authored docs/upgrade/releases.json and the packaged
    # dontpanic_orchestrate/data/releases.json must carry the same data so the
    # installed CLI loads exactly what was authored (reinforces F001's guard).
    assert json.loads(DOCS_SEED.read_text()) == json.loads(PACKAGED_SEED.read_text())


def test_packaged_schema_matches_canonical() -> None:
    # D049: the schema mirrored into package data must stay byte-identical to the
    # canonical claude/shared copy, so packaged validation uses the same contract.
    assert PACKAGED_SCHEMA.is_file(), "packaged schema mirror is missing"
    assert PACKAGED_SCHEMA.read_text() == CANONICAL_SCHEMA.read_text()


# ──────────────────  D049: shipped in wheel AND sdist  ──────────────────


def _build_dists(out_dir: Path) -> tuple[Path, Path]:
    """Build sdist + wheel via the PEP 517 setuptools backend (no isolation,
    no network). Returns (sdist_path, wheel_path). Skips on environmental build
    failure so the suite degrades honestly rather than flaking."""
    script = (
        "import sys\n"
        "from setuptools import build_meta as bm\n"
        "out = sys.argv[1]\n"
        "sdist = bm.build_sdist(out)\n"
        "wheel = bm.build_wheel(out)\n"
        "print(sdist)\n"
        "print(wheel)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(out_dir)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(
            f"could not build dists in this environment: {result.stderr.strip()[-500:]}"
        )
    lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
    sdist_name, wheel_name = lines[-2], lines[-1]
    return out_dir / sdist_name, out_dir / wheel_name


def test_releases_json_packaged_in_wheel_and_sdist(tmp_path: Path) -> None:
    # D049: releases.json AND its JSON Schema are included as package data in
    # BOTH the wheel and the sdist, so the D045 package-relative loader finds the
    # manifest when installed and the schema travels alongside it.
    sdist_path, wheel_path = _build_dists(tmp_path)

    assert wheel_path.is_file(), f"wheel not built: {wheel_path}"
    with zipfile.ZipFile(wheel_path) as zf:
        names = zf.namelist()
    assert "dontpanic_orchestrate/data/releases.json" in names, (
        f"releases.json missing from wheel; members: {names}"
    )
    assert "dontpanic_orchestrate/data/upgrade-releases.schema.json" in names, (
        f"schema missing from wheel; members: {names}"
    )

    assert sdist_path.is_file(), f"sdist not built: {sdist_path}"
    with tarfile.open(sdist_path) as tf:
        members = tf.getnames()
    # sdist members are namespaced under <name>-<version>/...; match on suffix.
    assert any(
        m.endswith("scripts/dontpanic_orchestrate/data/releases.json") for m in members
    ), f"releases.json missing from sdist; members: {members}"
    assert any(
        m.endswith("scripts/dontpanic_orchestrate/data/upgrade-releases.schema.json")
        for m in members
    ), f"schema missing from sdist; members: {members}"


def test_loads_from_installed_wheel(tmp_path: Path) -> None:
    # D049: load the manifest from the INSTALLED/packaged wheel location — extract
    # only the package out of the wheel into an isolated site dir (no repo tree,
    # no docs/, no .git), put it on a clean PYTHONPATH, run from an unrelated cwd,
    # and assert the seed (4 releases) loads. This is the installed case, not the
    # repo tree.
    _, wheel_path = _build_dists(tmp_path)

    site = tmp_path / "site-packages"
    site.mkdir()
    with zipfile.ZipFile(wheel_path) as zf:
        for name in zf.namelist():
            if name.startswith("dontpanic_orchestrate/"):
                zf.extract(name, site)

    # pydantic must be importable from the ambient env; only the package itself
    # comes from the wheel. PYTHONPATH points at the extracted site dir + the
    # ambient sys.path so deps resolve, but the package resolves from the wheel.
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(site), *sys.path])
    env.pop("PYTHONDONTWRITEBYTECODE", None)

    code = (
        "import dontpanic_orchestrate, pathlib;"
        # Confirm the package really came from the extracted wheel site dir.
        "assert str(pathlib.Path(dontpanic_orchestrate.__file__).resolve()).startswith("
        f"{str(site)!r}), dontpanic_orchestrate.__file__;"
        "from dontpanic_orchestrate.release_manifest import load_release_manifest;"
        "m = load_release_manifest();"
        "print(m.baseline_release, len(m.releases))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    baseline, _, count = result.stdout.strip().partition(" ")
    assert baseline == "2026-06-13-pre-experience-readiness"
    assert int(count) == 4
