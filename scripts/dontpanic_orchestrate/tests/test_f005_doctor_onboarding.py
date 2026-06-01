"""Plan 2026-05-30-001 F005 — doctor --agent / --project onboarding validation.

Covers the 8 acceptance criteria:
  (1) `doctor --agent` validates the machine layer + prints registered executors
  (2) `doctor --project NAME` validates one project + its managed block
  (3) unknown GLOBAL roles.* fail
  (4) unknown PROJECT roles.* fail
  (5) legacy implementer/auditor validation still works
  (6) stale/missing managed block -> remediation naming `projects add --onboard`
  (7) existing doctor tests stay compatible (covered by the full doctor suite)
  (8) `Grok-Builder` (not in AGENT_REGISTRY) is flagged unrunnable

Doctor lives at scripts/dontpanic_doctor.py and is loaded as a module (mirrors
test_f003_project_config.py). Home isolation (DONTPANIC_HOME / JARVIS_HOME) is
provided by the autouse conftest fixture, so registry / manifest / config
writes land in a temp home.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f005_doctor_onboarding.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
DOCTOR_PATH = SCRIPTS / "dontpanic_doctor.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def doctor():
    spec = importlib.util.spec_from_file_location("dontpanic_doctor", DOCTOR_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dontpanic_doctor"] = mod
    spec.loader.exec_module(mod)
    return mod


def _names(results) -> set[str]:
    return {r.name for r in results}


def _by_name(results, name):
    return next(r for r in results if r.name == name)


def _register_project(name: str, path: Path) -> None:
    from dontpanic_orchestrate import projects_registry as pr

    reg = pr.load_registry()
    reg.projects.append(
        pr.ProjectEntry(name=name, path=str(path), created_at="2026-05-31T00:00:00Z")
    )
    pr.save_registry(reg)


def _write_managed_agents_md(repo: Path, *, stale: bool = False) -> None:
    from dontpanic_orchestrate import repo_onboarding as ro

    if stale:
        # A managed block with a deliberately old generator version.
        body = "# DontPanic operating brief\n\n(stale body)\n"
        block = (
            f"<!-- DONTPANIC:BEGIN name={ro.BLOCK_AGENTS} generator=0.0 hash=deadbeef -->\n"
            f"{body}\n<!-- DONTPANIC:END -->\n"
        )
    else:
        block = ro.render_block(ro.BLOCK_AGENTS, "# DontPanic operating brief\n\n(generated body)\n")
    (repo / "AGENTS.md").write_text(block + "\n")


def _make_repo(tmp_path: Path, *, config: dict | None = None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    if config is not None:
        (repo / ".dontpanic").mkdir()
        (repo / ".dontpanic" / "dontpanic.json").write_text(json.dumps(config))
    return repo


# ───────────────────────────── AC1 + AC8: agent layer ─────────────────────────────


def test_agent_doctor_validates_machine_layer_and_lists_executors(doctor):
    results = doctor.check_agent_onboarding()
    names = _names(results)
    assert "agent:cli" in names
    assert "agent:executors" in names
    assert "agent:manifest" in names
    assert "agent:roles" in names
    # AC1: registered executors are printed.
    execs = _by_name(results, "agent:executors")
    assert execs.ok
    assert "claude" in execs.message and "codex" in execs.message
    # Machine layer is healthy in the isolated test home (no FAILs).
    assert all(r.ok for r in results), [r.name for r in results if not r.ok]


def test_agent_doctor_flags_unknown_global_roles(doctor, tmp_path):
    # AC3 + AC8: a global roles.implementer pointing at an unregistered
    # executor (Grok-Builder) must FAIL.
    from dontpanic_orchestrate import global_config as gc

    cfg_path = gc.config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"roles": {"implementer": "Grok-Builder"}}))

    results = doctor.check_agent_onboarding()
    roles = _by_name(results, "agent:roles")
    assert not roles.ok, "unknown global roles.implementer must FAIL"
    assert "Grok-Builder" in roles.message
    assert "AGENT_REGISTRY" in roles.message


def test_agent_doctor_accepts_known_global_roles(doctor):
    from dontpanic_orchestrate import global_config as gc

    cfg_path = gc.config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"roles": {"implementer": "claude", "auditor": "codex"}}))

    roles = _by_name(doctor.check_agent_onboarding(), "agent:roles")
    assert roles.ok
    assert "claude" in roles.message and "codex" in roles.message


# ───────────────────────────── AC2 + AC5 + AC6: project layer ─────────────────────────────


def test_project_doctor_validates_registered_project(doctor, tmp_path):
    repo = _make_repo(tmp_path, config={"implementer": "claude", "auditor": "codex"})
    _write_managed_agents_md(repo)
    _register_project("demo", repo)

    results = doctor.check_project_onboarding("demo")
    names = _names(results)
    assert "project:demo:path" in names
    assert "project:demo:agents" in names  # AC5: legacy implementer/auditor
    assert "project:demo:roles" in names  # AC4 layer present
    assert "project:demo:managed-block" in names  # AC6 layer present
    assert all(r.ok for r in results), [r.name for r in results if not r.ok]


def test_project_doctor_flags_unknown_project_roles(doctor, tmp_path):
    # AC4 + AC8: project roles.implementer=Grok-Builder FAILs even though the
    # legacy implementer/auditor fields are clean.
    repo = _make_repo(
        tmp_path,
        config={"implementer": "claude", "roles": {"implementer": "Grok-Builder"}},
    )
    _write_managed_agents_md(repo)
    _register_project("demo", repo)

    roles = _by_name(doctor.check_project_onboarding("demo"), "project:demo:roles")
    assert not roles.ok
    assert "Grok-Builder" in roles.message


def test_project_doctor_missing_managed_block_remediation(doctor, tmp_path):
    # AC6: a repo with no AGENTS.md managed block is REPORTED (advisory WARN,
    # since onboarding is opt-in) with the exact `projects add --onboard`
    # remediation. WARN keeps the sweep's all-projects-ok contract intact.
    repo = _make_repo(tmp_path, config={})  # no AGENTS.md written
    _register_project("demo", repo)

    block = _by_name(doctor.check_project_onboarding("demo"), "project:demo:managed-block")
    assert block.warn is True
    assert "missing" in block.message
    assert "--onboard" in block.remediation


def test_project_doctor_stale_managed_block_warns(doctor, tmp_path):
    # AC6: a present-but-stale managed block is a WARN (advisory) with the
    # same onboarding remediation — not a hard FAIL.
    repo = _make_repo(tmp_path, config={})
    _write_managed_agents_md(repo, stale=True)
    _register_project("demo", repo)

    block = _by_name(doctor.check_project_onboarding("demo"), "project:demo:managed-block")
    assert block.warn is True
    assert block.ok is True  # warn does not fail
    assert "--onboard" in block.remediation


def test_project_doctor_unregistered_path_validated_in_place(doctor, tmp_path):
    # AC2: a path that isn't registered is validated in place with a WARN that
    # it isn't registered (not a hard failure).
    repo = _make_repo(tmp_path, config={"implementer": "claude"})
    _write_managed_agents_md(repo)

    results = doctor.check_project_onboarding(str(repo))
    assert any(r.name.endswith(":registered") and r.warn for r in results)
    assert any(r.name.endswith(":managed-block") for r in results)


def test_project_doctor_unknown_name_or_path_fails(doctor):
    results = doctor.check_project_onboarding("no-such-thing-anywhere")
    assert len(results) == 1
    assert not results[0].ok
    assert results[0].name.endswith(":resolve")


# ───────────────────────────── CLI wiring (main) ─────────────────────────────


def test_doctor_main_agent_flag_exit_zero_when_healthy(doctor, capsys):
    rc = doctor.main(["--agent"])
    out = capsys.readouterr().out
    assert "agent:executors" in out
    assert rc == 0


def test_doctor_main_project_flag_unknown_exits_fail(doctor, capsys):
    rc = doctor.main(["--project", "definitely-not-registered"])
    assert rc == 2  # strict-exit FAIL
