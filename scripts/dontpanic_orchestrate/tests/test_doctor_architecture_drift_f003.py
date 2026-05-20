"""Plan 2026-05-19-004 F003 — architecture-drift doctor probe fixture tests.

Covers the acceptance criteria:

  (a) fresh state when fingerprint matches
  (b) stale_minor when <5% of files differ (1 file changed in a 50-file tree)
  (c) stale_major when ≥5% of files differ (5+ files changed in 50)
  (d) ABSENT when architecture.json is missing
  (e) --strict (--architecture-drift-strict) blocker for stale_major + ABSENT
  (f) JSON output carries state + changed_files + recommendation in details

The probe reuses F001's :class:`Crawler` for the current fingerprint; the
synthetic repo tree mirrors :mod:`test_architecture_crawler_f001` so the
doctor sees a tractable surface (Crawler walks
``scripts/dontpanic_orchestrate``, ``claude/shared``, ``docs/plans``).

Run:
    pytest scripts/dontpanic_orchestrate/tests/test_doctor_architecture_drift_f003.py -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"


def _load_doctor():
    """Load the doctor module under a unique name so we don't collide
    with ``dontpanic_doctor`` if another test already imported it."""
    spec = importlib.util.spec_from_file_location(
        "dontpanic_doctor_f003_drift", DOCTOR_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dontpanic_doctor_f003_drift"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doctor():
    return _load_doctor()


# ── Synthetic repo builders ───────────────────────────────────────────────


def _build_module_files(modules_dir: Path, count: int) -> None:
    """Lay down ``count`` Python module files under ``modules_dir``.

    Files are deterministic: ``mod_001.py`` … ``mod_NNN.py`` so the test
    can flip a known subset to drive stale_minor / stale_major.
    """
    modules_dir.mkdir(parents=True, exist_ok=True)
    (modules_dir / "__init__.py").write_text(
        '"""Synthetic package."""\n', encoding="utf-8"
    )
    for idx in range(1, count + 1):
        (modules_dir / f"mod_{idx:03d}.py").write_text(
            f'"""mod {idx}."""\n\n'
            f"def helper_{idx}():\n    return {idx}\n",
            encoding="utf-8",
        )


def _build_repo(root: Path, *, module_count: int = 50) -> None:
    """Build a synthetic DontPanic-shaped tree with ``module_count`` modules.

    Layout matches what F001's Crawler walks: ``scripts/dontpanic_orchestrate``,
    ``claude/shared/schemas/v1.0``, ``docs/plans/`` (with one plan dir).
    """
    modules_root = root / "scripts" / "dontpanic_orchestrate"
    _build_module_files(modules_root, module_count)

    schemas_root = root / "claude" / "shared" / "schemas" / "v1.0"
    schemas_root.mkdir(parents=True, exist_ok=True)
    (schemas_root / "plan.schema.json").write_text(
        json.dumps({"$id": "plan", "type": "object"}, sort_keys=True),
        encoding="utf-8",
    )
    (schemas_root / "validate.py").write_text("# stub\n", encoding="utf-8")
    (root / "claude" / "shared" / "VERSION").write_text("1.0.0\n", encoding="utf-8")

    plans_root = root / "docs" / "plans"
    plan_dir = plans_root / "2026-05-19-100-feat-fixture"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        "id: 2026-05-19-100-feat-fixture\n"
        "title: Fixture plan\n"
        "status: active\n"
        "---\n",
        encoding="utf-8",
    )
    (plan_dir / "features.json").write_text(
        json.dumps({"task_id": "2026-05-19-100-feat-fixture", "features": [{"id": "F001"}]}),
        encoding="utf-8",
    )


def _regen_architecture_json(repo_root: Path) -> Path:
    """Call F001's regen() against the synthetic repo to lay down the
    architecture.json baseline."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import architecture as arch
    finally:
        sys.path.pop(0)
    return arch.regen(repo_root, with_html=False)


def _arch_path(repo_root: Path) -> Path:
    return repo_root / "docs" / "architecture" / "architecture.json"


# ── (a) fresh state when fingerprint matches ──────────────────────────────


def test_fresh_state_when_fingerprint_matches(doctor, tmp_path):
    _build_repo(tmp_path, module_count=30)
    _regen_architecture_json(tmp_path)
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=False
    )
    assert result.ok is True
    assert result.warn is False
    assert result.name == "architecture-drift"
    assert result.details is not None and len(result.details) == 1
    payload = result.details[0]
    assert payload["state"] == "fresh"
    assert payload["changed_files"] == {"added": [], "removed": [], "modified": []}
    assert payload["unchanged_files"] > 0
    assert "no action" in payload["recommendation"].lower()


# ── (b) stale_minor when 1 file changed in a 50-file tree ─────────────────


def test_stale_minor_when_one_file_changed_in_fifty(doctor, tmp_path):
    _build_repo(tmp_path, module_count=50)
    _regen_architecture_json(tmp_path)
    # Modify exactly one module file → 1/total << 5%.
    target = tmp_path / "scripts" / "dontpanic_orchestrate" / "mod_007.py"
    target.write_text(target.read_text() + "\n# bumped\n", encoding="utf-8")
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=False
    )
    assert result.ok is True
    assert result.warn is True, "stale_minor must surface as WARN, not PASS"
    payload = result.details[0]
    assert payload["state"] == "stale_minor"
    assert payload["changed_files_total"] == 1
    assert "scripts/dontpanic_orchestrate/mod_007.py" in payload["changed_files"]["modified"]
    assert payload["drift_pct"] < 5.0
    assert "minor drift" in payload["recommendation"].lower()


def test_stale_minor_stays_advisory_even_in_strict_mode(doctor, tmp_path):
    """Acceptance step 4: stale_minor stays advisory in both modes."""
    _build_repo(tmp_path, module_count=50)
    _regen_architecture_json(tmp_path)
    target = tmp_path / "scripts" / "dontpanic_orchestrate" / "mod_012.py"
    target.write_text(target.read_text() + "\n# bumped\n", encoding="utf-8")
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=True
    )
    # Even with strict=True the minor finding stays a WARN (ok=True).
    assert result.ok is True
    assert result.warn is True
    assert result.details[0]["state"] == "stale_minor"


# ── (c) stale_major when ≥5% files differ ─────────────────────────────────


def test_stale_major_when_five_files_changed_in_fifty(doctor, tmp_path):
    _build_repo(tmp_path, module_count=50)
    _regen_architecture_json(tmp_path)
    # Modify 5 files → 5/total ≥ 5% (use a margin since the fingerprint
    # also covers the plan + VERSION files).
    for idx in (1, 5, 10, 25, 40):
        target = tmp_path / "scripts" / "dontpanic_orchestrate" / f"mod_{idx:03d}.py"
        target.write_text(target.read_text() + "\n# bumped\n", encoding="utf-8")
    # Add a couple more to comfortably clear the 5% floor regardless of
    # the exact union cardinality.
    for idx in (15, 33, 47):
        target = tmp_path / "scripts" / "dontpanic_orchestrate" / f"mod_{idx:03d}.py"
        target.write_text(target.read_text() + "\n# bumped2\n", encoding="utf-8")
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=False
    )
    # Advisory mode → WARN, not FAIL.
    assert result.ok is True
    assert result.warn is True
    payload = result.details[0]
    assert payload["state"] == "stale_major"
    assert payload["drift_pct"] >= 5.0
    assert "major drift" in payload["recommendation"].lower()


# ── (d) ABSENT when architecture.json is missing ──────────────────────────


def test_absent_when_architecture_json_missing(doctor, tmp_path):
    _build_repo(tmp_path, module_count=10)
    # Intentionally do NOT call _regen_architecture_json — the path is
    # missing on purpose.
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=False
    )
    # Advisory mode: WARN, not FAIL.
    assert result.ok is True
    assert result.warn is True
    payload = result.details[0]
    assert payload["state"] == "absent"
    assert "missing" in result.message.lower()
    assert "regen" in payload["recommendation"].lower()


# ── (e) --strict (--architecture-drift-strict) blocker for stale_major + ABSENT


def test_strict_mode_promotes_stale_major_to_fail(doctor, tmp_path):
    _build_repo(tmp_path, module_count=50)
    _regen_architecture_json(tmp_path)
    # Flip 8/50 files → comfortably > 5%.
    for idx in (1, 5, 10, 15, 20, 25, 30, 35):
        target = tmp_path / "scripts" / "dontpanic_orchestrate" / f"mod_{idx:03d}.py"
        target.write_text(target.read_text() + "\n# bumped\n", encoding="utf-8")
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=True
    )
    assert result.ok is False, "strict mode must promote stale_major to FAIL"
    assert result.details[0]["state"] == "stale_major"


def test_strict_mode_promotes_absent_to_fail(doctor, tmp_path):
    _build_repo(tmp_path, module_count=10)
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=True
    )
    assert result.ok is False, "strict mode must promote ABSENT to FAIL"
    assert result.details[0]["state"] == "absent"


def test_doctor_cli_exit_2_on_architecture_drift_strict(doctor, tmp_path, monkeypatch):
    """The doctor's --architecture-drift-strict flag implicitly opts into
    the strict-codes exit matrix and must return 2 when architecture.json
    is missing (ABSENT → FAIL → exit 2)."""
    _build_repo(tmp_path, module_count=10)
    # Patch the resolved architecture.json path so the probe reads the
    # synthetic tree even though run_all_checks is rooted at REPO_ROOT.
    # We monkey-patch check_architecture_drift to use our tmp paths.
    real_check = doctor.check_architecture_drift

    def _scoped(*, repo_root=None, architecture_path=None, strict=False):
        return real_check(
            repo_root=tmp_path,
            architecture_path=_arch_path(tmp_path),
            strict=strict,
        )

    monkeypatch.setattr(doctor, "check_architecture_drift", _scoped)
    rc = doctor.main(["--skip-auth", "--architecture-drift-strict", "--json"])
    assert rc == 2, f"expected exit 2 on ABSENT under --architecture-drift-strict, got {rc}"


# ── (f) JSON output carries state + changed_files + recommendation ────────


def test_json_render_carries_architecture_drift_details(doctor, tmp_path):
    """F003 acceptance #3: doctor's existing --json output includes the
    new probe with state + changed_files + recommendation."""
    _build_repo(tmp_path, module_count=50)
    _regen_architecture_json(tmp_path)
    target = tmp_path / "scripts" / "dontpanic_orchestrate" / "mod_002.py"
    target.write_text(target.read_text() + "\n# bumped\n", encoding="utf-8")
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=False
    )
    raw = doctor.render_json([result])
    payload = json.loads(raw)
    entry = next(c for c in payload["checks"] if c["name"] == "architecture-drift")
    assert "details" in entry
    detail = entry["details"][0]
    assert detail["state"] in {"fresh", "stale_minor", "stale_major", "absent"}
    assert "changed_files" in detail
    assert "recommendation" in detail
    assert isinstance(detail["changed_files"], dict)
    assert set(detail["changed_files"].keys()) >= {"added", "removed", "modified"}


# ── Performance: probe runs in <2s on this codebase ───────────────────────


def test_probe_runs_fast_on_live_repo(doctor):
    """F003 acceptance #5: probe runs in <2s on this codebase. Asserts the
    acceptance budget directly — the timer must come in under 2.0s on a
    warm cache. If a future change makes the probe slower, this test fails
    loudly so we can find the regression instead of letting the budget
    silently slip past 2s."""
    start = time.perf_counter()
    result = doctor.check_architecture_drift(
        repo_root=REPO_ROOT,
        architecture_path=REPO_ROOT / "docs" / "architecture" / "architecture.json",
        strict=False,
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, (
        f"probe took {elapsed:.2f}s — acceptance #5 budget is <2s on this codebase"
    )
    assert result.name == "architecture-drift"
    # Don't pin the state — depends on whether the operator just regen'd.


# ── changed_files truncation cap ──────────────────────────────────────────


def test_changed_files_list_truncated_to_cap(doctor, tmp_path):
    """Acceptance step 5: JSON output truncates changed_files to ~20. When
    a refactor flips a huge subset of files, the doctor payload stays
    bounded with a "+ N more" marker."""
    _build_repo(tmp_path, module_count=100)
    _regen_architecture_json(tmp_path)
    # Flip 50/100 files → all should appear in modified, but the JSON
    # payload must truncate to 20 + marker.
    for idx in range(1, 51):
        target = tmp_path / "scripts" / "dontpanic_orchestrate" / f"mod_{idx:03d}.py"
        target.write_text(target.read_text() + "\n# bumped\n", encoding="utf-8")
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=False
    )
    modified = result.details[0]["changed_files"]["modified"]
    assert len(modified) <= doctor.ARCHITECTURE_DRIFT_CHANGED_FILES_CAP + 1
    assert any("more" in entry for entry in modified), (
        f"expected '+N more' truncation marker in modified list; got {modified}"
    )


# ── Top-level architecture_drift JSON section (audit finding #1) ──────────


def test_render_json_emits_top_level_architecture_drift_section(doctor, tmp_path):
    """Audit i0 finding #1: ``render_json`` must surface a stable top-level
    ``architecture_drift`` section so consumers don't have to scan
    ``checks[]`` and string-match on the probe name. The section carries
    state + flat changed_files list + recommendation."""
    _build_repo(tmp_path, module_count=50)
    _regen_architecture_json(tmp_path)
    target = tmp_path / "scripts" / "dontpanic_orchestrate" / "mod_009.py"
    target.write_text(target.read_text() + "\n# bumped\n", encoding="utf-8")
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=False
    )
    payload = json.loads(doctor.render_json([result]))
    assert "architecture_drift" in payload, (
        "render_json() must emit a top-level architecture_drift section"
    )
    section = payload["architecture_drift"]
    assert section["state"] == "stale_minor"
    # changed_files MUST be a flat list per the acceptance contract.
    assert isinstance(section["changed_files"], list)
    assert any(
        "scripts/dontpanic_orchestrate/mod_009.py" in entry
        for entry in section["changed_files"]
    ), section["changed_files"]
    # Recommendation + counters still come along for the ride.
    assert "recommendation" in section
    assert section["changed_files_total"] == 1
    assert section["unchanged_files"] > 0


def test_render_json_top_level_section_absent_state(doctor, tmp_path):
    """The top-level section must still appear when the probe surfaces
    ABSENT — consumers gate downstream behavior on the state field."""
    _build_repo(tmp_path, module_count=10)
    # No regen → architecture.json missing on purpose.
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=False
    )
    payload = json.loads(doctor.render_json([result]))
    assert payload["architecture_drift"]["state"] == "absent"
    assert payload["architecture_drift"]["changed_files"] == []


# ── Missing required surfaces promote to stale_major (audit finding #2) ───


def test_missing_required_plans_root_promotes_to_stale_major(doctor, tmp_path):
    """Audit i0 finding #2: when a required surface vanishes (here:
    docs/plans/ entirely), classification must promote to stale_major
    regardless of the file-ratio threshold. The ratio classifier alone
    would call this stale_minor on a small repo because removed plan
    files are <5% of the union — but losing the entire plans surface
    is structural drift."""
    _build_repo(tmp_path, module_count=200)
    _regen_architecture_json(tmp_path)
    # Wipe the entire plans surface — only 2 files (plan.md + features.json),
    # which on a 200-module tree is well under the 5% ratio threshold.
    import shutil as _shutil

    _shutil.rmtree(tmp_path / "docs" / "plans")
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=False
    )
    payload = result.details[0]
    assert payload["state"] == "stale_major", (
        f"missing plans surface must promote to stale_major regardless of "
        f"ratio; got {payload['state']} with drift_pct={payload.get('drift_pct')}"
    )
    assert "docs/plans/" in payload["missing_required"]
    # The human-facing message must call out the missing surface.
    assert "missing required surface" in result.message.lower()


def test_missing_required_modules_root_promotes_to_stale_major(doctor, tmp_path):
    """Same shape as the plans test, but for the modules surface — losing
    the orchestrate module tree is also structural drift."""
    _build_repo(tmp_path, module_count=200)
    _regen_architecture_json(tmp_path)
    import shutil as _shutil

    _shutil.rmtree(tmp_path / "scripts" / "dontpanic_orchestrate")
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=False
    )
    payload = result.details[0]
    # With 200/202 files removed the ratio path would also flag this as
    # stale_major; the test pins that the prefix-presence check fires too
    # (recorded in missing_required) and that strict mode would block it.
    assert payload["state"] == "stale_major"
    assert "scripts/dontpanic_orchestrate/" in payload["missing_required"]


def test_missing_required_version_file_promotes_to_stale_major(doctor, tmp_path):
    """Deleting just ``claude/shared/VERSION`` — a single file — flips
    state to stale_major because it's an explicitly required surface
    even though one file is <5% of any reasonable tree."""
    _build_repo(tmp_path, module_count=300)
    _regen_architecture_json(tmp_path)
    (tmp_path / "claude" / "shared" / "VERSION").unlink()
    result = doctor.check_architecture_drift(
        repo_root=tmp_path, architecture_path=_arch_path(tmp_path), strict=False
    )
    payload = result.details[0]
    assert payload["state"] == "stale_major"
    assert "claude/shared/VERSION" in payload["missing_required"]
    assert payload["drift_pct"] < 5.0, (
        "sanity: the ratio is sub-5% — the promotion must come from "
        "missing_required, not the ratio classifier"
    )


def test_classify_helper_returns_missing_required(doctor):
    """Direct unit test of ``_classify_architecture_drift`` to lock the
    contract independent of probe wiring. With one missing required
    prefix in the stored map, state must be stale_major and the helper
    must list that prefix in its 5th return value."""
    stored = {
        "scripts/dontpanic_orchestrate/foo.py": "hash-a",
        "scripts/dontpanic_orchestrate/bar.py": "hash-b",
        "docs/plans/plan-x/plan.md": "hash-c",
        "claude/shared/VERSION": "hash-d",
    }
    # Drop the docs/plans surface entirely.
    current = {
        "scripts/dontpanic_orchestrate/foo.py": "hash-a",
        "scripts/dontpanic_orchestrate/bar.py": "hash-b",
        "claude/shared/VERSION": "hash-d",
    }
    state, changes, unchanged, total, missing = doctor._classify_architecture_drift(
        stored_map=stored, current_map=current
    )
    assert state == "stale_major"
    assert "docs/plans/" in missing
    # Sanity: the ratio classifier alone would call this stale_minor on a
    # bigger tree, but here removed=1/total=4 = 25% so it's already major
    # via the ratio path too. The point of the test is missing_required
    # surfaces in the return tuple — ratio path is incidental.
    assert changes["removed"] == ["docs/plans/plan-x/plan.md"]
