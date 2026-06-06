"""Dashboard state-output dir must be relocatable so test runs never write into
the repo working tree (the `<cwd>/dashboard/state` pollution that put pytest tmp
homes into the served dashboard).
"""

from __future__ import annotations

from pathlib import Path

from dontpanic_orchestrate import dashboard


def test_dashboard_dir_honors_env_override(monkeypatch, tmp_path):
    override = tmp_path / "iso" / "dashboard"
    monkeypatch.setenv("DONTPANIC_DASHBOARD_DIR", str(override))
    assert dashboard.default_dashboard_dir() == override
    assert dashboard.default_state_out_dir() == override / "state"


def test_explicit_cwd_still_wins_over_env(monkeypatch, tmp_path):
    # A caller that passes cwd explicitly has already isolated itself; the env
    # override is only for the Path.cwd() default.
    monkeypatch.setenv("DONTPANIC_DASHBOARD_DIR", str(tmp_path / "env"))
    repo = tmp_path / "repo"
    assert dashboard.default_dashboard_dir(cwd=repo) == repo / "dashboard"


def test_no_env_no_cwd_falls_back_to_process_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("DONTPANIC_DASHBOARD_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert dashboard.default_dashboard_dir() == tmp_path / "dashboard"


def test_conftest_isolates_dashboard_dir_off_the_repo():
    # The autouse fixture sets DONTPANIC_DASHBOARD_DIR to a per-test tmp dir, so
    # any dashboard build under a test writes there, never the repo.
    out = dashboard.default_dashboard_dir()
    repo_dashboard = Path(__file__).resolve().parents[2] / "dashboard"
    assert out != repo_dashboard
    assert "dashboard" in str(out)
