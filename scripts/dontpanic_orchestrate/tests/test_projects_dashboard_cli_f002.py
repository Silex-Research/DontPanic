"""Plan 2026-05-23-005 F002 — dashboard project-selection CLI tests.

Acceptance coverage:

  (1) Dashboard build/serve consume projects registered through the
      existing ``dontpanic projects`` CLI.
  (2) ``dashboard build`` / ``dashboard serve`` accept ``--project
      <name>|all``.
  (3) Defaults are predictable for zero, one, cwd-matched, and many
      registered projects.
  (4) Unknown project names fail loud with the list of known names and
      the exact ``dontpanic projects add <name> <path>`` shape.
  (5) A running ``serve`` refreshes selector data after registry
      changes (no manual restart).
  (6) Feature requires no Firebase setup and exposes no remote
      interface by default (no firebase imports surface, default host
      is loopback).
  (7) Tests cover CLI help, cwd-match default behavior, explicit
      selection, ``all`` selection, unknown-name failure, registry
      refresh, and no-Firebase requirement.

Run targeted:
  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_projects_dashboard_cli_f002.py -q
"""

from __future__ import annotations

import http.client
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import dashboard  # noqa: E402
from dontpanic_orchestrate import projects_dashboard as pd  # noqa: E402
from dontpanic_orchestrate import projects_registry as pr  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def alpha_repo(tmp_path):
    d = tmp_path / "alpha-repo"
    d.mkdir()
    (d / "docs").mkdir()
    (d / "docs" / "plans").mkdir()
    return d


@pytest.fixture
def beta_repo(tmp_path):
    d = tmp_path / "beta-repo"
    d.mkdir()
    (d / "docs").mkdir()
    (d / "docs" / "plans").mkdir()
    return d


@pytest.fixture
def standalone_repo(tmp_path):
    """A directory that is NOT a registered project — used for cwd
    fall-through tests (cwd outside every registered repo)."""

    d = tmp_path / "outside-repo"
    d.mkdir()
    (d / "docs").mkdir()
    (d / "docs" / "plans").mkdir()
    return d


@contextmanager
def _running_server(handle: dashboard.ServeHandle):
    try:
        yield handle
    finally:
        handle.shutdown()


# ── (3) defaults: zero / one / cwd-match / multi ────────────────────────


class TestDefaultResolution:
    def test_zero_registry_resolves_to_current_repo(self, tmp_path):
        sel = pd.resolve_selection(None, cwd=tmp_path)
        assert sel.kind == "current_repo"
        assert sel.is_default is True
        assert sel.cwd_match is False

    def test_one_registered_project_defaults_to_it_when_cwd_outside(
        self, alpha_repo, standalone_repo
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        sel = pd.resolve_selection(None, cwd=standalone_repo)
        assert sel.kind == "project"
        assert sel.project_name == "alpha"
        assert sel.is_default is True
        # cwd is outside alpha_repo, so it's not a cwd-match.
        assert sel.cwd_match is False

    def test_cwd_inside_registered_project_wins(self, alpha_repo, beta_repo):
        pr.add_project(name="alpha", path=str(alpha_repo))
        pr.add_project(name="beta", path=str(beta_repo))
        # cwd inside beta — beta wins even though alpha was registered first.
        sel = pd.resolve_selection(None, cwd=beta_repo)
        assert sel.kind == "project"
        assert sel.project_name == "beta"
        assert sel.cwd_match is True
        assert sel.is_default is True

    def test_cwd_inside_subdir_of_registered_project_matches(self, alpha_repo):
        pr.add_project(name="alpha", path=str(alpha_repo))
        sub = alpha_repo / "docs" / "plans"
        sel = pd.resolve_selection(None, cwd=sub)
        assert sel.kind == "project"
        assert sel.project_name == "alpha"
        assert sel.cwd_match is True

    def test_multi_project_default_outside_any_repo_is_all(
        self, alpha_repo, beta_repo, standalone_repo
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        pr.add_project(name="beta", path=str(beta_repo))
        sel = pd.resolve_selection(None, cwd=standalone_repo)
        assert sel.kind == "all"
        assert sel.is_default is True
        assert sel.cwd_match is False


# ── (2) explicit --project name|all selection ──────────────────────────


class TestExplicitSelection:
    def test_explicit_all_returns_all(self, alpha_repo, beta_repo):
        pr.add_project(name="alpha", path=str(alpha_repo))
        pr.add_project(name="beta", path=str(beta_repo))
        sel = pd.resolve_selection("all", cwd=beta_repo)
        assert sel.kind == "all"
        assert sel.is_default is False
        # cwd_match irrelevant when explicit
        assert sel.cwd_match is False

    def test_explicit_project_name_returns_that_project(
        self, alpha_repo, beta_repo
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        pr.add_project(name="beta", path=str(beta_repo))
        # Explicit alpha even though cwd is inside beta.
        sel = pd.resolve_selection("alpha", cwd=beta_repo)
        assert sel.kind == "project"
        assert sel.project_name == "alpha"
        assert sel.is_default is False


# ── (4) unknown name fails loud ────────────────────────────────────────


class TestUnknownProjectName:
    def test_unknown_name_raises_with_known_names_and_add_command(
        self, alpha_repo, beta_repo
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        pr.add_project(name="beta", path=str(beta_repo))
        with pytest.raises(pd.UnknownProjectError) as ei:
            pd.resolve_selection("gamma", cwd=alpha_repo)
        msg = str(ei.value)
        assert "gamma" in msg
        # Known names listed.
        assert "alpha" in msg and "beta" in msg
        # Add command template uses the operator-friendly shape.
        assert "dontpanic projects add gamma" in msg
        assert ei.value.add_command() == "dontpanic projects add gamma <path>"
        assert ei.value.known_names == ("alpha", "beta")

    def test_unknown_name_against_empty_registry_message(self, tmp_path):
        with pytest.raises(pd.UnknownProjectError) as ei:
            pd.resolve_selection("gamma", cwd=tmp_path)
        msg = str(ei.value)
        assert "no projects are registered" in msg
        assert "dontpanic projects add gamma" in msg

    def test_build_cli_unknown_name_exits_with_code_2(
        self, alpha_repo, capsys
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        rc = dashboard.main(
            [
                "build",
                "--project",
                "gamma",
                "--plans-root",
                str(alpha_repo / "docs" / "plans"),
            ]
        )
        err = capsys.readouterr().err
        assert rc == 2
        assert "unknown project" in err
        assert "alpha" in err
        assert "dontpanic projects add gamma" in err

    def test_serve_cli_unknown_name_exits_with_code_2(
        self, alpha_repo, tmp_path, capsys
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        dashboard_dir = tmp_path / "dashboard"
        dashboard_dir.mkdir()
        (dashboard_dir / "index.html").write_text("<html/>")
        rc = dashboard.main(
            [
                "serve",
                "--project",
                "gamma",
                "--dashboard-dir",
                str(dashboard_dir),
                "--plans-root",
                str(alpha_repo / "docs" / "plans"),
                "--state-out",
                str(tmp_path / "state"),
                "--no-watch",
                "--once",
                "--port",
                "0",
            ]
        )
        err = capsys.readouterr().err
        assert rc == 2
        assert "unknown project" in err


# ── (1, 2) build --project all + per-project ───────────────────────────


class TestBuildSelected:
    def test_build_all_writes_fleet_summary_and_per_project_state(
        self, alpha_repo, beta_repo
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        pr.add_project(name="beta", path=str(beta_repo))

        result = pd.build_selected("all", cwd=alpha_repo)
        assert result.selection.kind == "all"
        assert result.selection.is_default is False
        # Fleet summary on disk.
        assert result.fleet_summary_path is not None
        assert result.fleet_summary_path.is_file()
        # Per-project caches populated.
        for name in ("alpha", "beta"):
            cache = pd.project_dashboard_dir(name)
            assert (cache / "state-snapshot.json").is_file()
            assert (cache / "build-warnings.json").is_file()

    def test_build_one_project_writes_focused_state_plus_fleet_summary(
        self, alpha_repo, beta_repo
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        pr.add_project(name="beta", path=str(beta_repo))

        result = pd.build_selected("alpha", cwd=alpha_repo)
        assert result.selection.kind == "project"
        assert result.selection.project_name == "alpha"
        focused = result.focused_project()
        assert focused is not None and focused.context.name == "alpha"

        # Alpha rebuilt fully; beta got a stub so the selector still
        # has its entry but no fresh state.
        alpha_cache = pd.project_dashboard_dir("alpha")
        beta_cache = pd.project_dashboard_dir("beta")
        assert (alpha_cache / "state-snapshot.json").is_file()
        assert (beta_cache / "build-warnings.json").is_file()
        # Fleet summary lists both projects.
        assert result.fleet_summary_path is not None
        envelope = json.loads(result.fleet_summary_path.read_text())
        names = {p["name"] for p in envelope["projects"]}
        assert names == {"alpha", "beta"}

    def test_build_current_repo_when_registry_empty(self, tmp_path):
        out_dir = tmp_path / "out"
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        result = pd.build_selected(
            None, plans_root=plans_root, out_dir=out_dir, cwd=tmp_path
        )
        assert result.selection.kind == "current_repo"
        assert result.current_repo_report is not None
        assert (out_dir / "state-snapshot.json").is_file()
        # No fleet summary in current-repo mode.
        assert result.fleet_summary_path is None

    def test_build_cli_all_mirrors_fleet_summary_into_state_out(
        self, alpha_repo, beta_repo, tmp_path, capsys
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        pr.add_project(name="beta", path=str(beta_repo))
        out_dir = tmp_path / "state"

        rc = dashboard.main(
            [
                "build",
                "--project",
                "all",
                "--out",
                str(out_dir),
            ]
        )
        assert rc == 0
        # Mirrored summary in the served state dir + the operator cache.
        assert (out_dir / pd.FLEET_SUMMARY_FILENAME).is_file()
        assert pd.fleet_summary_path().is_file()
        out = capsys.readouterr().out
        assert "All Projects" in out
        assert "fleet summary" in out

    def test_build_cli_no_project_defaults_to_all_for_multi_project(
        self, alpha_repo, beta_repo, standalone_repo, tmp_path, capsys, monkeypatch
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        pr.add_project(name="beta", path=str(beta_repo))
        # Point cwd outside any registered repo so the default falls
        # through to 'all'.
        monkeypatch.chdir(standalone_repo)
        out_dir = tmp_path / "state"

        rc = dashboard.main(["build", "--out", str(out_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "defaulted to All Projects" in out
        assert (out_dir / pd.FLEET_SUMMARY_FILENAME).is_file()

    def test_build_cli_cwd_match_default_selects_that_project(
        self, alpha_repo, beta_repo, tmp_path, capsys, monkeypatch
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        pr.add_project(name="beta", path=str(beta_repo))
        monkeypatch.chdir(alpha_repo)
        out_dir = tmp_path / "state"

        rc = dashboard.main(["build", "--out", str(out_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "defaulted to project 'alpha'" in out
        # Mirror puts the focused project under projects/alpha/.
        assert (out_dir / "projects" / "alpha" / "state-snapshot.json").is_file()


# ── (5) serve refreshes selector data after registry changes ───────────


class TestServeRegistryRefresh:
    def test_registry_change_triggers_rebuild(
        self, alpha_repo, beta_repo, tmp_path
    ):
        """Acceptance (5): a newly-registered project must appear in the
        fleet summary mirrored under state_out_dir without restart."""

        pr.add_project(name="alpha", path=str(alpha_repo))
        dashboard_dir = tmp_path / "dashboard"
        dashboard_dir.mkdir()
        (dashboard_dir / "index.html").write_text("<html/>")
        state_out_dir = dashboard_dir / "state"

        handle = dashboard.serve_start(
            host=dashboard.DEFAULT_HOST,
            port=0,
            dashboard_dir=dashboard_dir,
            plans_root=alpha_repo / "docs" / "plans",
            state_out_dir=state_out_dir,
            watch=True,
            watch_interval=0.1,
            project="all",
        )
        with _running_server(handle):
            summary_path = state_out_dir / pd.FLEET_SUMMARY_FILENAME
            assert summary_path.is_file()
            initial = json.loads(summary_path.read_text())
            assert {p["name"] for p in initial["projects"]} == {"alpha"}

            # Register a new project mid-run. The watcher fingerprints
            # the registry file, so this must trigger a rebuild.
            time.sleep(0.2)
            pr.add_project(name="beta", path=str(beta_repo))

            deadline = time.time() + 5
            refreshed = None
            while time.time() < deadline:
                payload = json.loads(summary_path.read_text())
                if {p["name"] for p in payload["projects"]} == {"alpha", "beta"}:
                    refreshed = payload
                    break
                time.sleep(0.1)
            assert refreshed is not None, (
                "fleet summary did not refresh after `projects add beta`; "
                "watcher must fingerprint the registry file"
            )

    def test_serve_unknown_project_at_start_fails_before_binding(
        self, alpha_repo, tmp_path
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        dashboard_dir = tmp_path / "dashboard"
        dashboard_dir.mkdir()
        (dashboard_dir / "index.html").write_text("<html/>")

        with pytest.raises(pd.UnknownProjectError):
            dashboard.serve_start(
                host=dashboard.DEFAULT_HOST,
                port=0,
                dashboard_dir=dashboard_dir,
                plans_root=alpha_repo / "docs" / "plans",
                state_out_dir=dashboard_dir / "state",
                watch=False,
                project="gamma",
            )


# ── (6) no Firebase / no remote interface by default ───────────────────


class TestNoFirebaseAndLoopbackOnly:
    def test_no_firebase_module_imported_by_project_selection(self):
        """Acceptance (6): the project-selector path must not pull in
        Firebase. We import the F002 surface explicitly and assert no
        firebase_client / firebase_admin modules appear in sys.modules."""

        # Drop any cached entries from earlier tests in the same session
        # so this is a fair measurement; if they re-enter via another
        # path the assertion below will detect it.
        # (Don't actually del — just record what was loaded before/after.)
        before = {
            name
            for name in sys.modules
            if name.startswith("firebase") or "firebase_admin" in name
        }
        # Re-exercise the F002 selection helpers.
        pd.resolve_selection(None, cwd=Path.cwd())
        pd.build_selected(None, cwd=Path.cwd())
        after = {
            name
            for name in sys.modules
            if name.startswith("firebase") or "firebase_admin" in name
        }
        # Firebase already-loaded modules (none expected in tests) are
        # tolerated; the contract is that *exercising F002* must not
        # introduce any.
        new_firebase_modules = after - before
        assert new_firebase_modules == set(), (
            f"project selection imported firebase modules: {new_firebase_modules}"
        )

    def test_serve_with_project_arg_still_binds_loopback_by_default(
        self, alpha_repo, tmp_path
    ):
        pr.add_project(name="alpha", path=str(alpha_repo))
        dashboard_dir = tmp_path / "dashboard"
        dashboard_dir.mkdir()
        (dashboard_dir / "index.html").write_text("<html/>")
        handle = dashboard.serve_start(
            host=dashboard.DEFAULT_HOST,
            port=0,
            dashboard_dir=dashboard_dir,
            plans_root=alpha_repo / "docs" / "plans",
            state_out_dir=dashboard_dir / "state",
            watch=False,
            project="alpha",
        )
        with _running_server(handle):
            assert handle.host == dashboard.DEFAULT_HOST
            conn = http.client.HTTPConnection(handle.host, handle.port, timeout=5)
            try:
                conn.request("GET", "/")
                resp = conn.getresponse()
                assert resp.status == 200
            finally:
                conn.close()


# ── (7) CLI help mentions --project ────────────────────────────────────


class TestCLIHelp:
    def test_dashboard_build_help_mentions_project_flag(self, capsys):
        with pytest.raises(SystemExit) as ei:
            dashboard.main(["build", "--help"])
        assert ei.value.code == 0
        out = capsys.readouterr().out
        assert "--project" in out

    def test_dashboard_serve_help_mentions_project_flag(self, capsys):
        with pytest.raises(SystemExit) as ei:
            dashboard.main(["serve", "--help"])
        assert ei.value.code == 0
        out = capsys.readouterr().out
        assert "--project" in out

    def test_dashboard_help_does_not_advertise_firebase(self, capsys):
        with pytest.raises(SystemExit) as ei:
            dashboard.main(["build", "--help"])
        assert ei.value.code == 0
        out = capsys.readouterr().out
        assert "firebase" not in out.lower()
