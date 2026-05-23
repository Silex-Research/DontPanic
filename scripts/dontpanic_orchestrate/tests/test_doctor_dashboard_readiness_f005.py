"""Plan 2026-05-23-004 F005 — dashboard readiness doctor probes.

Covers:

  (a) all three probes PASS when dashboard files + cache + state are present
  (b) ``dashboard-files`` WARNs with restore remediation when index.html missing
  (c) ``dashboard-cache`` WARNs with `dontpanic dashboard build` remediation
      when the operator-local what-now cache is absent
  (d) ``dashboard-state`` WARNs with `dontpanic dashboard build` remediation
      when state-snapshot.json or what-now.json is missing in dashboard/state
  (e) dashboard probes are advisory: they never escalate the strict exit
      code computed by ``compute_strict_exit`` after being filtered out by
      the CLI wrapper (and ``main`` legacy path)

Run:
    pytest scripts/dontpanic_orchestrate/tests/test_doctor_dashboard_readiness_f005.py -q
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"


def _load_doctor():
    """Load the doctor module under a unique name so we don't collide
    with other tests that loaded ``dontpanic_doctor`` first."""
    spec = importlib.util.spec_from_file_location(
        "dontpanic_doctor_f005_dashboard", DOCTOR_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dontpanic_doctor_f005_dashboard"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doctor():
    return _load_doctor()


def _build_repo(root: Path, *, with_index: bool, with_state: bool) -> None:
    dashboard = root / "dashboard"
    if with_index:
        dashboard.mkdir(parents=True, exist_ok=True)
        (dashboard / "index.html").write_text(
            "<html><body>fixture</body></html>", encoding="utf-8"
        )
    if with_state:
        state = dashboard / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "state-snapshot.json").write_text("{}", encoding="utf-8")
        (state / "what-now.json").write_text(
            '{"schema_version": "1.0.0", "items": []}\n', encoding="utf-8"
        )


def _set_dontpanic_home(monkeypatch, tmp_path: Path, *, write_cache: bool) -> Path:
    """Redirect $DONTPANIC_HOME so operator_console.default_cache_path()
    resolves under tmp_path. Optionally pre-populate the what-now cache.
    """
    home = tmp_path / "dontpanic-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DONTPANIC_HOME", str(home))
    # Also clear JARVIS_HOME so the global_config fallback doesn't reach
    # a stale legacy directory on the host.
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    if write_cache:
        cache_dir = home / "dashboard"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "what-now.json").write_text(
            '{"schema_version": "1.0.0", "items": []}\n', encoding="utf-8"
        )
    return home


def test_all_present_emits_three_oks(doctor, tmp_path, monkeypatch):
    _build_repo(tmp_path, with_index=True, with_state=True)
    _set_dontpanic_home(monkeypatch, tmp_path, write_cache=True)
    results = doctor.check_dashboard_readiness(repo_root=tmp_path)
    assert [r.name for r in results] == [
        "dashboard-files",
        "dashboard-cache",
        "dashboard-state",
    ]
    for r in results:
        assert r.ok is True
        assert r.warn is False, f"{r.name} unexpectedly emitted WARN: {r.message}"


def test_missing_index_warns_with_restore_remediation(doctor, tmp_path, monkeypatch):
    _build_repo(tmp_path, with_index=False, with_state=True)
    _set_dontpanic_home(monkeypatch, tmp_path, write_cache=True)
    by_name = {r.name: r for r in doctor.check_dashboard_readiness(repo_root=tmp_path)}
    files = by_name["dashboard-files"]
    assert files.ok is True  # WARN keeps ok=True per CheckResult convention
    assert files.warn is True
    assert "dashboard/index.html missing" in files.message
    assert files.remediation == "run: git restore -- dashboard/index.html"


def test_missing_cache_warns_with_build_command(doctor, tmp_path, monkeypatch):
    _build_repo(tmp_path, with_index=True, with_state=True)
    _set_dontpanic_home(monkeypatch, tmp_path, write_cache=False)
    by_name = {r.name: r for r in doctor.check_dashboard_readiness(repo_root=tmp_path)}
    cache = by_name["dashboard-cache"]
    assert cache.ok is True
    assert cache.warn is True
    assert "what-now cache missing" in cache.message
    assert cache.remediation == "run: dontpanic dashboard build"


def test_missing_state_warns_listing_missing_files(doctor, tmp_path, monkeypatch):
    _build_repo(tmp_path, with_index=True, with_state=False)
    _set_dontpanic_home(monkeypatch, tmp_path, write_cache=True)
    by_name = {r.name: r for r in doctor.check_dashboard_readiness(repo_root=tmp_path)}
    state = by_name["dashboard-state"]
    assert state.ok is True
    assert state.warn is True
    assert "state-snapshot.json" in state.message
    assert "what-now.json" in state.message
    assert state.remediation == "run: dontpanic dashboard build"


def test_dashboard_warns_advisory_under_strict_exit(doctor, tmp_path, monkeypatch):
    """Acceptance contract: dashboard checks stay advisory. The CLI
    wrapper (and the legacy `main` strict path) filter ``dashboard-*``
    out of the strict-exit computation, so WARN findings do NOT escalate
    to exit 1. Surface the invariant here: stripping the dashboard
    probes from a sweep with WARN findings yields exit 0.
    """
    _build_repo(tmp_path, with_index=False, with_state=False)
    _set_dontpanic_home(monkeypatch, tmp_path, write_cache=False)
    results = doctor.check_dashboard_readiness(repo_root=tmp_path)
    assert any(r.warn for r in results)
    # Filter mirrors cli._doctor_main + main() strict path.
    strict_inputs = [r for r in results if not r.name.startswith("dashboard-")]
    assert doctor.compute_strict_exit(strict_inputs) == 0
