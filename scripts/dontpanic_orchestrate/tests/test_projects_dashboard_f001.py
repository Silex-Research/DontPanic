"""Plan 2026-05-23-005 F001 — projects-dashboard substrate tests.

Acceptance items covered:
  (1) ``ProjectEntry.name`` remains the stable identity through the
      ProjectContext projection.
  (2) Per-project state lands under ``~/.dontpanic/dashboard/projects/<name>/``
      and never inside the registered target repo.
  (3) Fleet summary JSON exists at
      ``~/.dontpanic/dashboard/fleet-summary.json`` after a build.
  (4) Single-repo dashboard.build() still works when no registry exists
      (load_project_contexts returns empty list, callers fall back).
  (5) Legacy registry files without the additive dashboard fields load
      unchanged and project_context_from_entry defaults them sensibly.
  (6) Same-version assumption — the fleet envelope stamps
      ``dontpanic_version`` once at envelope scope.
  (7) No secret-shape strings ever land in the per-project caches or
      the fleet summary (the operator_console secret guard refuses).

Run targeted:
  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_projects_dashboard_f001.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import global_config as gc  # noqa: E402
from dontpanic_orchestrate import (  # noqa: E402
    dashboard,
    projects_dashboard as pd,
    projects_registry as pr,
)


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "alpha-repo"
    d.mkdir()
    (d / "docs").mkdir()
    (d / "docs" / "plans").mkdir()
    return d


@pytest.fixture
def project_dir_b(tmp_path):
    d = tmp_path / "beta-repo"
    d.mkdir()
    (d / "docs").mkdir()
    (d / "docs" / "plans").mkdir()
    return d


# ── 1. stable name through projection ───────────────────────────────────


class TestStableNameProjection:
    def test_project_context_name_matches_registry_entry(self, project_dir):
        pr.add_project(name="alpha", path=str(project_dir))
        entry = pr.find_project("alpha")
        assert entry is not None
        ctx = pd.project_context_from_entry(entry)
        assert ctx.name == "alpha"
        assert ctx.name == entry.name

    def test_display_name_defaults_to_name_when_unset(self, project_dir):
        pr.add_project(name="alpha", path=str(project_dir))
        ctx = pd.project_context_from_entry(pr.find_project("alpha"))
        assert ctx.display_name == "alpha"

    def test_display_name_overrides_when_set(self, project_dir):
        pr.add_project(
            name="alpha",
            path=str(project_dir),
            display_name="Alpha Mobile App",
        )
        ctx = pd.project_context_from_entry(pr.find_project("alpha"))
        assert ctx.display_name == "Alpha Mobile App"
        # Stable identity is still the name field.
        assert ctx.name == "alpha"

    def test_load_project_contexts_preserves_registry_order(
        self, project_dir, project_dir_b
    ):
        pr.add_project(name="alpha", path=str(project_dir))
        pr.add_project(name="beta", path=str(project_dir_b))
        ctxs = pd.load_project_contexts()
        assert [c.name for c in ctxs] == ["alpha", "beta"]


# ── 2. cache layout: no write inside target repo ────────────────────────


class TestCacheLayout:
    def test_dashboard_dir_rooted_under_dontpanic_home(self, project_dir, tmp_path):
        # The conftest fixture already pinned DONTPANIC_HOME under tmp.
        ctx = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        cache = ctx.dashboard_cache_path
        assert cache == gc.dontpanic_home() / "dashboard" / "projects" / "alpha"
        assert str(cache).startswith(str(gc.dontpanic_home()))
        # And critically: not inside the registered repo.
        assert str(project_dir.resolve()) not in str(cache.resolve())

    def test_build_writes_into_operator_cache_not_target_repo(
        self, project_dir, tmp_path
    ):
        ctx = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        report = pd.build_project_state(ctx)
        # Per-project state files land flat under the cache dir, per
        # plan §Data Shape — no nested `state/` subdir.
        cache_dir = ctx.dashboard_cache_path
        assert (cache_dir / "state-snapshot.json").is_file()
        # Build warnings sit alongside state-snapshot.json.
        assert report.build_warnings_path.is_file()
        assert report.build_warnings_path == cache_dir / pd.BUILD_WARNINGS_FILENAME
        # No write inside the target repo (only the pre-existing
        # docs/plans/ scaffold we created in the fixture).
        repo_files = {
            p.relative_to(project_dir).as_posix()
            for p in project_dir.rglob("*")
            if p.is_file()
        }
        assert not any(
            "dashboard" in part for part in repo_files
        ), f"unexpected dashboard write in target repo: {repo_files}"
        # And nothing under docs/plans was generated.
        assert repo_files == set()

    def test_per_project_build_does_not_clobber_global_caches(
        self, project_dir, project_dir_b
    ):
        """Two per-project builds in a row must each land their
        capabilities-status / what-now caches under the project's own
        cache dir. The single-repo operator-global cache paths
        (``~/.dontpanic/capabilities-status.json`` and
        ``~/.dontpanic/dashboard/what-now.json``) must stay untouched —
        otherwise a fleet build is last-project-wins for those files."""
        global_caps = gc.dontpanic_home() / "capabilities-status.json"
        global_what_now = gc.dontpanic_home() / "dashboard" / "what-now.json"
        # Pre-condition: neither global path exists yet.
        assert not global_caps.exists()
        assert not global_what_now.exists()

        ctx_a = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        ctx_b = pd.project_context_from_entry(
            pr.add_project(name="beta", path=str(project_dir_b))
        )
        pd.build_project_state(ctx_a)
        pd.build_project_state(ctx_b)

        # Per-project caches land under each project's own dir. The
        # what-now cache is always written; the capabilities cache is
        # best-effort (a project with no capability index just skips
        # it with a warning), so we only require the what-now copy.
        assert (ctx_a.dashboard_cache_path / "what-now-cache.json").is_file()
        assert (ctx_b.dashboard_cache_path / "what-now-cache.json").is_file()
        # Operator-global paths are untouched — single-repo behavior
        # remains owned by single-repo callers. This is the bug the
        # auditor flagged: previously, every per-project build
        # rewrote the global single-repo caches.
        assert not global_caps.exists()
        assert not global_what_now.exists()

    def test_dashboard_build_warnings_are_not_double_counted(
        self, project_dir, monkeypatch
    ):
        """dashboard.build owns warning collection. The per-project
        wrapper may forward those warnings to the caller, but must not
        append them a second time into build-warnings.json or the fleet
        summary warning_count."""
        ctx = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        forwarded: list[str] = []

        def _fake_build(**kwargs):
            callback = kwargs.get("warn") or (lambda _m: None)
            callback("same warning")
            return dashboard.BuildReport(
                out_dir=kwargs["out_dir"],
                state_files=(),
                what_now_cache_path=None,
                capability_cache_path=None,
                reconcile_status_path=None,
                architecture_status_path=None,
                warnings=("same warning",),
            )

        monkeypatch.setattr(dashboard, "build", _fake_build)
        report = pd.build_project_state(ctx, warn=forwarded.append)
        payload = json.loads(report.build_warnings_path.read_text())

        assert forwarded == ["same warning"]
        assert report.warnings == ("same warning",)
        assert payload["warnings"] == ["same warning"]

        fleet = json.loads(pd.build_fleet_summary([report]).read_text())
        assert fleet["projects"][0]["warning_count"] == 1


# ── 3. fleet summary exists for All Projects ────────────────────────────


class TestFleetSummary:
    def test_fleet_summary_written_to_canonical_path(
        self, project_dir, project_dir_b
    ):
        ctx_a = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        ctx_b = pd.project_context_from_entry(
            pr.add_project(name="beta", path=str(project_dir_b))
        )
        reports = [pd.build_project_state(ctx_a), pd.build_project_state(ctx_b)]
        path = pd.build_fleet_summary(reports, dontpanic_version="test-0.1")
        assert path == pd.fleet_summary_path()
        assert path == gc.dontpanic_home() / "dashboard" / "fleet-summary.json"
        assert path.is_file()

    def test_fleet_summary_stamps_single_dontpanic_version(self, project_dir):
        ctx = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        report = pd.build_project_state(ctx)
        path = pd.build_fleet_summary([report], dontpanic_version="0.42.0")
        payload = json.loads(path.read_text())
        assert payload["dontpanic_version"] == "0.42.0"
        # Per-entry dontpanic_version is the registry's value (None here).
        assert payload["projects"][0]["dontpanic_version"] is None

    def test_fleet_summary_lists_each_project_by_name(
        self, project_dir, project_dir_b
    ):
        pr.add_project(name="alpha", path=str(project_dir))
        pr.add_project(name="beta", path=str(project_dir_b))
        ctxs = pd.load_project_contexts()
        reports = [pd.build_project_state(c) for c in ctxs]
        path = pd.build_fleet_summary(reports)
        payload = json.loads(path.read_text())
        names = [e["name"] for e in payload["projects"]]
        assert names == ["alpha", "beta"]
        assert payload["project_count"] == 2
        assert payload["active_count"] == 2
        # Schema versioned so a stale cache fails loud later.
        assert payload["schema_version"] == pd.FLEET_SUMMARY_SCHEMA_VERSION

    def test_fleet_summary_includes_cache_paths_and_data_age(self, project_dir):
        ctx = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        report = pd.build_project_state(ctx)
        path = pd.build_fleet_summary([report])
        payload = json.loads(path.read_text())
        entry = payload["projects"][0]
        assert entry["dashboard_cache_path"] == str(ctx.dashboard_cache_path)
        assert entry["state_snapshot_path"].endswith("state-snapshot.json")
        assert entry["data_age_seconds"] is not None
        assert entry["data_age_seconds"] >= 0
        assert entry["warning_count"] == len(report.warnings)


# ── 4. single-repo fallback when no registry ────────────────────────────


class TestSingleRepoFallback:
    def test_load_project_contexts_empty_when_no_registry(self):
        # Conftest isolation gives us a fresh DONTPANIC_HOME each test.
        assert pd.load_project_contexts() == []

    def test_single_repo_dashboard_build_still_works(self, tmp_path):
        # No registry, no projects_dashboard call — the existing
        # dashboard.build() continues to operate on a cwd-style root.
        repo = tmp_path / "lonely-repo"
        repo.mkdir()
        plans = repo / "docs" / "plans"
        plans.mkdir(parents=True)
        out = tmp_path / "out"
        report = dashboard.build(
            plans_root=plans,
            out_dir=out,
            repo_root=repo,
        )
        assert (out / "state-snapshot.json").is_file()
        assert report.state_files


# ── 5. legacy registry compat ───────────────────────────────────────────


class TestLegacyRegistryCompat:
    def test_legacy_entry_without_new_fields_loads(self, project_dir):
        # Simulate a registry file written by an older DontPanic that
        # didn't know about display_name / profile / active /
        # dontpanic_version. We hand-write the JSON so the absence is
        # genuine (excluding the fields, not setting them to None).
        gc.ensure_dontpanic_home()
        pr.registry_path().write_text(
            json.dumps(
                {
                    "projects": [
                        {
                            "name": "alpha",
                            "path": str(project_dir.resolve()),
                            "created_at": "2026-05-03T00:00:00Z",
                            "notes": "legacy",
                        }
                    ]
                }
            )
        )
        # Direct load round-trips without warnings.
        reg = pr.load_registry()
        assert len(reg.projects) == 1
        e = reg.projects[0]
        assert e.display_name is None
        assert e.profile is None
        assert e.active is None
        assert e.dontpanic_version is None
        # Projection treats absent active as True (legacy compat).
        ctx = pd.project_context_from_entry(e)
        assert ctx.active is True
        # And display_name falls back to name.
        assert ctx.display_name == "alpha"

    def test_save_legacy_compatible_entry_omits_new_fields(self, project_dir):
        # When new fields are unset they must be omitted from JSON so
        # the on-disk shape stays diff-friendly for operators inspecting
        # the file and so legacy DontPanic installs can keep reading.
        pr.add_project(name="alpha", path=str(project_dir))
        raw = json.loads(pr.registry_path().read_text())
        entry = raw["projects"][0]
        assert "display_name" not in entry
        assert "profile" not in entry
        assert "active" not in entry
        assert "dontpanic_version" not in entry


# ── 6. same-version assumption ──────────────────────────────────────────


class TestSameVersionAssumption:
    def test_dontpanic_version_is_envelope_level_not_per_project(
        self, project_dir, project_dir_b
    ):
        pr.add_project(name="alpha", path=str(project_dir))
        pr.add_project(name="beta", path=str(project_dir_b))
        ctxs = pd.load_project_contexts()
        reports = [pd.build_project_state(c) for c in ctxs]
        path = pd.build_fleet_summary(reports, dontpanic_version="0.5.0")
        payload = json.loads(path.read_text())
        # One envelope-scope version, not duplicated per entry.
        assert payload["dontpanic_version"] == "0.5.0"
        for entry in payload["projects"]:
            # Per-entry version comes from the registry, not the
            # envelope. The fleet summary deliberately does not
            # propagate the envelope-level value down.
            assert entry["dontpanic_version"] is None


# ── 7. inactive + missing repo handling ─────────────────────────────────


class TestInactiveAndMissingRepo:
    def test_inactive_project_is_skipped_with_reason(self, project_dir):
        pr.add_project(
            name="alpha",
            path=str(project_dir),
            active=False,
        )
        ctx = pd.project_context_from_entry(pr.find_project("alpha"))
        report = pd.build_project_state(ctx)
        assert report.skipped
        assert report.skipped_reason == "inactive"
        # No state-snapshot written; only build-warnings.json.
        assert not (ctx.dashboard_cache_path / "state-snapshot.json").is_file()
        assert report.build_warnings_path.is_file()

    def test_missing_repo_is_skipped_with_reason(self, project_dir):
        pr.add_project(name="alpha", path=str(project_dir))
        # Delete the repo after registration.
        for child in list(project_dir.rglob("*")):
            if child.is_file():
                child.unlink()
        for child in sorted(project_dir.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        project_dir.rmdir()
        ctx = pd.project_context_from_entry(pr.find_project("alpha"))
        report = pd.build_project_state(ctx)
        assert report.skipped
        assert report.skipped_reason == "repo_root missing"
        # Warning surfaced in the persisted build-warnings.json.
        payload = json.loads(report.build_warnings_path.read_text())
        assert payload["skipped"] is True
        assert any("does not exist" in w for w in payload["warnings"])

    def test_fleet_summary_inactive_excluded_from_active_count_and_rollup(
        self, project_dir, project_dir_b
    ):
        pr.add_project(name="alpha", path=str(project_dir))
        pr.add_project(name="beta", path=str(project_dir_b), active=False)
        ctxs = pd.load_project_contexts()
        reports = [pd.build_project_state(c) for c in ctxs]
        path = pd.build_fleet_summary(reports)
        payload = json.loads(path.read_text())
        assert payload["project_count"] == 2
        assert payload["active_count"] == 1
        # Beta entry still listed (so the UI can render it muted) but
        # marked inactive + skipped.
        beta = next(e for e in payload["projects"] if e["name"] == "beta")
        assert beta["active"] is False
        assert beta["skipped"] is True
        assert beta["health_band"] == "quiet"


# ── 8. no-secret invariant ──────────────────────────────────────────────


class TestNoSecretOutput:
    def test_build_warnings_refuses_secret_shape(self, project_dir, monkeypatch):
        # If a warning string ever carries a secret-shape token, the
        # operator_console guard must refuse the write rather than
        # silently leaking it into the operator-local cache.
        ctx = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        # Monkeypatch dashboard.build to inject a secret-shape warning.
        from dontpanic_orchestrate import dashboard as _dash

        def _fake_build(**kwargs):
            warn = kwargs.get("warn") or (lambda _m: None)
            warn("dummy")
            return _dash.BuildReport(
                out_dir=kwargs["out_dir"],
                state_files=(),
                what_now_cache_path=None,
                capability_cache_path=None,
                reconcile_status_path=None,
                architecture_status_path=None,
                # AWS-shape token to trigger the secret regex guard.
                warnings=("AKIAIOSFODNN7EXAMPLE leaked here",),
            )

        monkeypatch.setattr(_dash, "build", _fake_build)
        with pytest.raises(ValueError, match="secret pattern"):
            pd.build_project_state(ctx)

    def test_fleet_summary_is_clean_on_normal_path(self, project_dir):
        # Happy path: no exception raised + no secret-shape tokens
        # appear in any string in the payload.
        ctx = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        report = pd.build_project_state(ctx)
        path = pd.build_fleet_summary([report])
        text = path.read_text()
        # Sanity: a couple of high-signal secret prefixes that the
        # operator_console regex set covers.
        for needle in ("AKIA", "BEGIN PRIVATE KEY", "ghp_"):
            assert needle not in text

    def test_no_secret_shapes_anywhere_in_per_project_cache(
        self, project_dir, project_dir_b
    ):
        """Scan every JSON file under each project's cache dir against
        the full operator_console secret regex set. ``_assert_no_secret_
        shapes`` runs at write time, but a regression that bypasses one
        of the writers (e.g. a new sub-cache landed without the guard)
        would slip through. This is the post-hoc invariant: nothing in
        the on-disk cache may match any sanitization secret regex."""
        from dontpanic_orchestrate import operator_console as _oc

        ctx_a = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        ctx_b = pd.project_context_from_entry(
            pr.add_project(name="beta", path=str(project_dir_b))
        )
        reports = [pd.build_project_state(ctx_a), pd.build_project_state(ctx_b)]
        pd.build_fleet_summary(reports, dontpanic_version="0.1.0")

        regexes = _oc._load_secret_regexes()  # noqa: SLF001
        scanned = 0
        for cache_dir in (
            ctx_a.dashboard_cache_path,
            ctx_b.dashboard_cache_path,
            pd.fleet_summary_path().parent,
        ):
            for path in cache_dir.rglob("*"):
                if not path.is_file():
                    continue
                scanned += 1
                text = path.read_text(encoding="utf-8")
                for rx in regexes:
                    match = rx.search(text)
                    assert match is None, (
                        f"secret-shape match in {path}: pattern={rx.pattern!r} "
                        f"matched {match.group(0)!r}"
                    )
        # Sanity: we actually scanned something. The fleet summary
        # alone is 1 file; two project caches together produce a dozen
        # files minimum (state-snapshot + per-stream files + manifest +
        # what-now + capabilities + reconcile + architecture-status +
        # build-warnings + per-project what-now/capabilities caches).
        assert scanned >= 10, f"scanned only {scanned} files — coverage too low"


# ── 9. mutable path / re-registration ───────────────────────────────────


class TestMutablePathBehavior:
    def test_re_register_same_name_to_new_path_updates_repo_root(
        self, project_dir, project_dir_b
    ):
        """``ProjectEntry.name`` is the stable identity; the path is a
        mutable implementation detail (plan §Data Shape). Re-registering
        an existing name with ``force=True`` must update ``repo_root``
        and the projection while keeping the cache-dir path stable so
        prior per-project cache entries remain addressable."""
        pr.add_project(name="alpha", path=str(project_dir))
        ctx_before = pd.project_context_from_entry(pr.find_project("alpha"))
        cache_before = ctx_before.dashboard_cache_path
        assert ctx_before.repo_root == project_dir.resolve()

        # Re-register the same name pointing at a different repo on
        # disk (e.g. operator moved the working tree).
        pr.add_project(name="alpha", path=str(project_dir_b), force=True)
        ctx_after = pd.project_context_from_entry(pr.find_project("alpha"))

        # Identity is preserved; only the mutable path moved.
        assert ctx_after.name == "alpha" == ctx_before.name
        assert ctx_after.repo_root == project_dir_b.resolve()
        assert ctx_after.repo_root != ctx_before.repo_root
        # Cache dir is keyed by the stable name, so it stays put even
        # though the repo path changed — any prior cache entries the
        # operator built remain addressable under the same dir.
        assert ctx_after.dashboard_cache_path == cache_before
