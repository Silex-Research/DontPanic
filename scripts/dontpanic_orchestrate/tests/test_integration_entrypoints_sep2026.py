"""Public command proofs for the September integration follow-ups."""

import json
import sys

import pytest

from dontpanic_orchestrate import cli, command_validation
from dontpanic_orchestrate.tests.test_plan_review_cli_f003 import (
    _CLEAN_FEATURE,
    _make_plan,
    _snapshot,
)


def test_plan_review_includes_goal_only_skill_and_is_read_only(tmp_path, capsys):
    plan = _make_plan(tmp_path, "2026-09-06-990-feat-skill-proof", [_CLEAN_FEATURE])
    md = plan / "plan.md"
    md.write_text(md.read_text().replace("type: feat", "goal_type: infra\ntype: feat"))
    skill = tmp_path / "claude/skills/local-proof/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: local-proof\napplies_to:\n  goal_types: [infra]\n---\n")
    before = _snapshot(plan)
    assert cli.main(["plan-review", str(plan)]) == 0
    assert "skill:local-proof" in capsys.readouterr().out
    assert _snapshot(plan) == before
    (plan / "conventions.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "item_id": "skill:local-proof",
                        "disposition": "deferred",
                        "reason": "not needed for this slice",
                    }
                ]
            }
        )
    )
    assert cli.main(["plan-review", str(plan)]) == 0
    assert "skill:local-proof" not in capsys.readouterr().out


def _isolate_doctor(monkeypatch):
    import dontpanic_doctor as doctor

    from dontpanic_orchestrate.config import doctor_registry

    monkeypatch.setitem(sys.modules, "jarvis_doctor", doctor)
    list_checks = {
        "check_clis",
        "check_python_deps",
        "check_quota_caps",
        "check_registered_projects",
        "check_plan_cohesion",
        "check_dashboard_readiness",
        "check_skill_rubrics_advisory",
        "check_model_catalog",
    }
    for name in dir(doctor):
        if name.startswith("check_") and name != "check_runtime_evidence":
            if name in list_checks:
                monkeypatch.setattr(doctor, name, lambda *a, **k: [])
            else:
                monkeypatch.setattr(
                    doctor, name, lambda *a, **k: doctor._ok("unrelated", "fixture")
                )
    monkeypatch.setattr(doctor, "validate_plans_strict", lambda **k: [])
    monkeypatch.setattr(doctor_registry, "_REGISTRY", {})
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    return doctor


def test_doctor_opt_in_registers_adapters_without_blocking_core(monkeypatch, capsys):
    _isolate_doctor(monkeypatch)
    assert cli.main(["doctor", "--skip-auth", "--runtime-evidence", "--json"]) == 0
    checks = json.loads(capsys.readouterr().out)["checks"]
    names = {c["name"] for c in checks}
    assert {
        "runtime-evidence:ios_simctl",
        "runtime-evidence:android_adb",
        "runtime-evidence:evidence_harness",
    } <= names
    assert "runtime-evidence:backend_firebase" not in names
    assert command_validation.validate_command_tokens(["doctor", "--runtime-evidence"]).ok


def test_plain_doctor_does_not_probe_capture_adapters(monkeypatch, capsys):
    doctor = _isolate_doctor(monkeypatch)

    def forbidden(**kwargs):
        raise AssertionError("capture probes must be opt-in")

    monkeypatch.setattr(doctor, "check_runtime_evidence", forbidden, raising=False)
    assert cli.main(["doctor", "--skip-auth", "--json"]) == 0
    assert "runtime-evidence:" not in capsys.readouterr().out


@pytest.mark.parametrize("confirm", [False, True])
def test_operator_preference_cannot_grant_dispatch(monkeypatch, tmp_path, capsys, confirm):
    from dontpanic_orchestrate import supervisor
    from dontpanic_orchestrate.tests.test_dispatch_from_plan import _write_plan

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DONTPANIC_HOME", str(home))
    (home / "config.json").write_text(
        json.dumps({"roles": {"implementer": "cursor", "auditor": "codex"}})
    )
    (home / "operator_roles.json").write_text(json.dumps({"primary_operator": "cursor"}))
    plan = _write_plan(tmp_path / "repo", "2026-09-06-991-feat-dispatch-proof")

    def forbidden(**kwargs):
        raise AssertionError("non-executor cannot dispatch")

    monkeypatch.setattr(supervisor, "dispatch_volley", forbidden)
    argv = ["dispatch-from-plan", str(plan), "--implementer", "cursor"]
    if confirm:
        argv.append("--confirm")
    assert cli.main(argv) == 3
    assert "REFUSED" in capsys.readouterr().err


def test_skip_auth_excludes_firebase_probe_before_execution(monkeypatch, capsys):
    _isolate_doctor(monkeypatch)
    from dontpanic_orchestrate.runtime_evidence import backend

    calls = []

    def forbidden():
        calls.append("firebase")
        raise AssertionError("skip-auth must not invoke this check")

    monkeypatch.setattr(backend, "_backend_firebase_check", forbidden)
    assert cli.main(["doctor", "--skip-auth", "--runtime-evidence", "--json"]) == 0
    capsys.readouterr()
    assert calls == []


@pytest.mark.parametrize(
    "mode",
    [["--agent"], ["--project", "demo"], ["--upgrade"], ["--acknowledge"], ["--channel", "cursor"]],
)
def test_runtime_probe_mode_cannot_be_silently_ignored(monkeypatch, capsys, mode):
    _isolate_doctor(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["doctor", "--runtime-evidence", *mode])
    assert exc.value.code == 2
    assert "cannot be combined" in capsys.readouterr().err
