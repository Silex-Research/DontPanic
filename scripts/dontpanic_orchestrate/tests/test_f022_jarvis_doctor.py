"""F022 — jarvis_doctor unit tests with simulated failure paths.

Imports the module directly so we can call individual checks. Uses
monkeypatch to simulate missing CLIs, missing files, bad project state.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
# Plan 2026-05-04-001 renamed scripts/jarvis_doctor.py → scripts/dontpanic_doctor.py
# (jarvis_doctor.py remains as a thin alias). Tests load the canonical file
# directly; the alias is exercised via subprocess in
# test_legacy_doctor_alias_runs.
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"


def _load_doctor():
    spec = importlib.util.spec_from_file_location("jarvis_doctor", DOCTOR_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve forward refs via sys.modules
    sys.modules["jarvis_doctor"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def doctor():
    return _load_doctor()


# ── individual checks ──────────────────────────────────────────────────────


def test_python_version_passes_on_current(doctor) -> None:
    r = doctor.check_python_version()
    assert r.ok is True


def test_clis_returns_one_result_per_cli(doctor) -> None:
    results = doctor.check_clis()
    names = {r.name for r in results}
    assert "cli:gcloud" in names
    assert "cli:firebase" in names
    assert "cli:git" in names


def test_target_project_uses_env_var(doctor, monkeypatch) -> None:
    monkeypatch.setenv("DONTPANIC_FIREBASE_PROJECT", "from-env-id")
    monkeypatch.setenv("JARVIS_FIREBASE_PROJECT", "legacy-id")
    result, project = doctor.check_target_project()
    assert result.ok and project == "from-env-id"
    assert "from-env-id" in result.message


def test_target_project_uses_legacy_env_var(doctor, monkeypatch) -> None:
    monkeypatch.delenv("DONTPANIC_FIREBASE_PROJECT", raising=False)
    monkeypatch.setenv("JARVIS_FIREBASE_PROJECT", "from-legacy-id")
    result, project = doctor.check_target_project()
    assert result.ok and project == "from-legacy-id"
    assert "from-legacy-id" in result.message


def test_target_project_falls_back_to_environments_json(
    doctor, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DONTPANIC_FIREBASE_PROJECT", raising=False)
    monkeypatch.delenv("JARVIS_FIREBASE_PROJECT", raising=False)
    env = tmp_path / "environments.json"
    env.write_text(json.dumps({"repo": "X", "dev": {"firebase_project": "from-file-id"}}))
    monkeypatch.setattr(doctor, "ENV_FILE", env)
    result, project = doctor.check_target_project()
    assert result.ok and project == "from-file-id"


def test_target_project_rejects_placeholder(doctor, monkeypatch, tmp_path: Path) -> None:
    """If environments.json still has the example placeholder, fail clearly."""
    monkeypatch.delenv("DONTPANIC_FIREBASE_PROJECT", raising=False)
    monkeypatch.delenv("JARVIS_FIREBASE_PROJECT", raising=False)
    env = tmp_path / "environments.json"
    env.write_text(
        json.dumps({"repo": "X", "dev": {"firebase_project": "your-firebase-project-id"}})
    )
    monkeypatch.setattr(doctor, "ENV_FILE", env)
    result, project = doctor.check_target_project()
    assert not result.ok
    assert project is None
    assert "placeholder" in result.message


def test_target_project_aborts_when_neither_set(doctor, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DONTPANIC_FIREBASE_PROJECT", raising=False)
    monkeypatch.delenv("JARVIS_FIREBASE_PROJECT", raising=False)
    monkeypatch.setattr(doctor, "ENV_FILE", tmp_path / "does-not-exist.json")
    result, project = doctor.check_target_project()
    assert not result.ok and project is None
    assert "DONTPANIC_FIREBASE_PROJECT" in result.message
    assert "scripts/bootstrap.sh" in result.remediation


def test_secrets_dir_missing_with_gitignore_is_green(doctor, monkeypatch, tmp_path: Path) -> None:
    """Fresh clone state: .secrets/ does not exist on disk yet, but the
    repo's gitignore would catch it. Must be green — bootstrap creates
    the dir on demand under --create-key. CI relies on this."""
    fresh_repo = tmp_path / "repo"
    fresh_repo.mkdir()
    (fresh_repo / ".gitignore").write_text(".secrets/\n")
    import subprocess as _sp

    _sp.run(["git", "init", "-q", str(fresh_repo)], check=True)
    # Note: .secrets/ deliberately not created
    monkeypatch.setattr(doctor, "SECRETS_DIR", fresh_repo / ".secrets")
    monkeypatch.setattr(doctor, "REPO_ROOT", fresh_repo)
    result = doctor.check_secrets_dir(project=None)
    assert result.ok, f"fresh clone should pass: {result}"
    assert "not present yet" in result.message


def test_secrets_dir_missing_without_gitignore_fails(doctor, monkeypatch, tmp_path: Path) -> None:
    """If .secrets/ doesn't exist AND gitignore wouldn't protect it,
    that's the actually-dangerous state — bootstrap --create-key would
    silently land a key in a tracked dir."""
    bad_repo = tmp_path / "repo"
    bad_repo.mkdir()
    (bad_repo / ".gitignore").write_text("node_modules/\n")
    # Initialize a tiny git repo so check-ignore can run
    import subprocess as _sp

    _sp.run(["git", "init", "-q", str(bad_repo)], check=True)
    monkeypatch.setattr(doctor, "SECRETS_DIR", bad_repo / ".secrets")
    monkeypatch.setattr(doctor, "REPO_ROOT", bad_repo)
    result = doctor.check_secrets_dir(project=None)
    assert not result.ok
    assert "not gitignored" in result.message


def test_secrets_dir_present_but_not_ignored_fails(doctor, monkeypatch, tmp_path: Path) -> None:
    """Catastrophic-if-missed case: .secrets/ exists but isn't ignored."""
    bad_repo = tmp_path / "repo"
    bad_repo.mkdir()
    (bad_repo / ".gitignore").write_text("# nothing about secrets here\nnode_modules/\n")
    secrets = bad_repo / ".secrets"
    secrets.mkdir()
    import subprocess as _sp

    _sp.run(["git", "init", "-q", str(bad_repo)], check=True)
    monkeypatch.setattr(doctor, "SECRETS_DIR", secrets)
    monkeypatch.setattr(doctor, "REPO_ROOT", bad_repo)
    result = doctor.check_secrets_dir(project=None)
    assert not result.ok
    assert "leaking SA keys" in result.remediation


def test_schemas_check_finds_promoted_set(doctor) -> None:
    """The current repo has all 5 promoted v1.0 schemas."""
    result = doctor.check_schemas()
    assert result.ok, result.message


def test_schemas_check_fails_when_dir_missing(doctor, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doctor, "SCHEMAS_DIR", tmp_path / "no-schemas")
    result = doctor.check_schemas()
    assert not result.ok
    assert "missing" in result.message


def test_python_deps_return_per_dep_results(doctor) -> None:
    results = doctor.check_python_deps()
    names = {r.name for r in results}
    assert names == {"py:pydantic", "py:yaml", "py:firebase_admin"}


# ── runner integration ─────────────────────────────────────────────────────


def test_run_all_checks_produces_results(doctor) -> None:
    results = doctor.run_all_checks()
    assert len(results) > 5
    # Every result has the four expected fields
    for r in results:
        assert isinstance(r.name, str) and r.name
        assert isinstance(r.ok, bool)
        assert isinstance(r.message, str)
        assert isinstance(r.remediation, str)


def test_render_text_contains_summary_line(doctor) -> None:
    results = doctor.run_all_checks()
    rendered = doctor.render_text(results)
    assert "checks passed" in rendered or "checks failed" in rendered


def test_render_json_is_valid(doctor) -> None:
    results = doctor.run_all_checks()
    rendered = doctor.render_json(results)
    payload = json.loads(rendered)
    assert "checks" in payload
    assert "passed" in payload
    assert "failed" in payload
    assert payload["passed"] + payload["failed"] == len(payload["checks"])


def test_main_exits_nonzero_when_checks_fail(doctor, monkeypatch) -> None:
    """Force a check to fail and verify main() returns 1."""

    def fake_run_all(skip_auth: bool = False, include_projects: bool = False, **kw) -> list:
        return [doctor.CheckResult(name="forced", ok=False, message="x", remediation="y")]

    monkeypatch.setattr(doctor, "run_all_checks", fake_run_all)
    rc = doctor.main(["--json"])
    assert rc == 1


def test_main_returns_zero_when_all_green(doctor, monkeypatch) -> None:
    def fake_run_all(skip_auth: bool = False, include_projects: bool = False, **kw) -> list:
        return [doctor.CheckResult(name="forced", ok=True, message="x")]

    monkeypatch.setattr(doctor, "run_all_checks", fake_run_all)
    # Capture stdout away from the test
    rc = doctor.main(["--json"])
    assert rc == 0


def test_main_handles_argv_none(doctor, monkeypatch) -> None:
    """When called with argv=None, argparse uses sys.argv. Avoid that here."""
    monkeypatch.setattr(sys, "argv", ["jarvis_doctor", "--json"])
    monkeypatch.setattr(
        doctor, "run_all_checks", lambda **kw: [doctor.CheckResult("x", True, "ok")]
    )
    assert doctor.main() == 0


def test_skip_auth_omits_auth_checks(doctor) -> None:
    """run_all_checks(skip_auth=True) must not include gcloud-auth /
    firebase-auth result rows. CI relies on this — gcloud CLI is present
    but not authenticated, and we don't want green-when-fresh to depend
    on environmental auth state."""
    full = {r.name for r in doctor.run_all_checks(skip_auth=False)}
    skipped = {r.name for r in doctor.run_all_checks(skip_auth=True)}
    assert "gcloud-auth" in full
    assert "firebase-auth" in full
    assert "gcloud-auth" not in skipped
    assert "firebase-auth" not in skipped
    # Every other check is still present
    assert (full - {"gcloud-auth", "firebase-auth"}) == skipped


def test_skip_auth_propagates_through_main(doctor, monkeypatch) -> None:
    """`jarvis_doctor.py --skip-auth` must reach run_all_checks with
    skip_auth=True. Captured via monkeypatch."""
    captured: dict[str, bool] = {}

    def fake_run_all(skip_auth: bool = False, include_projects: bool = False, **kw) -> list:
        captured["skip_auth"] = skip_auth
        return [doctor.CheckResult("forced-ok", True, "x")]

    monkeypatch.setattr(doctor, "run_all_checks", fake_run_all)
    assert doctor.main(["--skip-auth"]) == 0
    assert captured["skip_auth"] is True

    captured.clear()
    assert doctor.main([]) == 0
    assert captured["skip_auth"] is False
