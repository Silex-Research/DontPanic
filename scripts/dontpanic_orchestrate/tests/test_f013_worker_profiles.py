"""F013 — worker profiles (Track D2).

Covers the acceptance surface end to end:

  - Schema: D015 harness-alias normalization at parse time, unknown
    allowed_roles rejected, extra keys forbidden, capability overrides
    restrict-only (effective / widened / missing-for-role helpers).
  - Resolution: legacy harness names (and aliases) resolve with
    profile_id=None; profile ids bind harness + model; project layer wins
    per id; a profile that shadows a harness name is inert; unknown names
    raise UnknownWorkerError with an operator-fixable message.
  - Gates: allowed_roles refusal, capability refusal (auditor-only /
    restricted profile assigned implementer), unregistered-harness
    refusal — all typed WorkerProfileError subclasses, refused clearly.
  - Goal-audit provenance: inherited goal audit gates on ``auditor`` (an
    auditor-only profile stays dispatchable); an explicit
    ``roles.goal_auditor`` gates on ``goal_auditor``.
  - CLI: ``dontpanic workers add|set|list|show`` mutations + listing;
    refusals exit 3 BEFORE any config write; usage errors exit 2.
  - Dispatch wiring: supervisor._run_round threads the profile model onto
    the DispatchTask (profile model > F012 role-level model), and the
    audit evidence records the resolved profile_id + harness + model.

Home-dir isolation comes from the conftest autouse fixture that redirects
DONTPANIC_HOME/JARVIS_HOME to per-test tmp dirs.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_f013_worker_profiles.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import global_config as gc  # noqa: E402
from dontpanic_orchestrate import plan_loader, supervisor  # noqa: E402
from dontpanic_orchestrate import project_config as pc  # noqa: E402
from dontpanic_orchestrate import worker_profiles as wp  # noqa: E402
from dontpanic_orchestrate.config import resolvers  # noqa: E402
from dontpanic_orchestrate.config.worker_profiles import (  # noqa: E402
    WorkerProfile,
    WorkerProfileCapabilities,
    effective_capabilities,
    harness_capabilities,
    missing_capabilities_for_role,
    normalize_harness,
    widened_capabilities,
)
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)
from dontpanic_orchestrate.workers_cli import workers_main  # noqa: E402


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "some-project"
    d.mkdir()
    return d


def _write_project_cfg(project_dir: Path, payload: dict) -> None:
    cfg_path = pc.project_config_path(project_dir)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(payload))


def _save_global(payload: dict) -> None:
    gc.save_config(gc.GlobalConfig.model_validate(payload))


_HONEY = {
    "display_name": "Honey",
    "harness": "codex_cli",
    "model": "gpt-5.2-codex",
    "allowed_roles": ["auditor"],
}


# ── Schema (config.worker_profiles) ───────────────────────────────────────


def test_harness_alias_normalizes_at_parse():
    assert WorkerProfile.model_validate({"harness": "codex_cli"}).harness == "codex"
    assert WorkerProfile.model_validate({"harness": "claude_cli"}).harness == "claude"
    assert WorkerProfile.model_validate({"harness": "claude"}).harness == "claude"
    assert normalize_harness("gemini_cli") == "gemini"


def test_unknown_allowed_role_rejected():
    with pytest.raises(ValidationError):
        WorkerProfile.model_validate({"harness": "claude", "allowed_roles": ["stranger"]})


def test_extra_keys_forbidden():
    with pytest.raises(ValidationError):
        WorkerProfile.model_validate({"harness": "claude", "vendor": "anthropic"})


def test_capability_override_restricts():
    profile = WorkerProfile(
        harness="claude",
        capabilities=WorkerProfileCapabilities(file_edit=False),
    )
    assert effective_capabilities(profile) == frozenset({"tool_use", "non_interactive"})
    assert missing_capabilities_for_role(profile, "implementer") == ["file_edit"]
    assert missing_capabilities_for_role(profile, "auditor") == []


def test_capability_override_never_widens():
    # An unlisted harness defaults to non_interactive only; asserting
    # file_edit=true claims more than the harness provides.
    assert harness_capabilities("gemini") == frozenset({"non_interactive"})
    profile = WorkerProfile(
        harness="gemini",
        capabilities=WorkerProfileCapabilities(file_edit=True),
    )
    assert widened_capabilities(profile) == ["file_edit"]
    # Asserting a flag the harness DOES have is not widening.
    assert (
        widened_capabilities(
            WorkerProfile(harness="codex", capabilities=WorkerProfileCapabilities(file_edit=True))
        )
        == []
    )


# ── Resolution: legacy names + aliases ────────────────────────────────────


def test_legacy_harness_name_resolves_without_profile(project_dir):
    worker = wp.resolve_worker(project_dir, "implementer", "claude")
    assert worker.profile_id is None
    assert worker.harness == "claude"
    assert worker.model is None


def test_legacy_alias_resolves_to_registry_key(project_dir):
    assert wp.resolve_worker(project_dir, "implementer", "claude_cli").harness == "claude"
    assert wp.resolve_worker(project_dir, "auditor", "codex_cli").harness == "codex"


def test_unknown_name_raises_unknown_worker(project_dir):
    with pytest.raises(wp.UnknownWorkerError, match="neither a registered harness"):
        wp.resolve_worker(project_dir, "implementer", "nobody")


# ── Resolution: profiles (acceptance case: honey) ─────────────────────────


def test_profile_resolves_harness_and_model(project_dir):
    _save_global({"worker_profiles": {"honey": _HONEY}})
    worker = wp.resolve_worker(project_dir, "auditor", "honey")
    assert worker.profile_id == "honey"
    assert worker.display_name == "Honey"
    assert worker.harness == "codex"
    assert worker.model == "gpt-5.2-codex"


def test_project_profile_wins_over_global(project_dir):
    _save_global({"worker_profiles": {"honey": _HONEY}})
    _write_project_cfg(
        project_dir,
        {"worker_profiles": {"honey": {"harness": "claude", "allowed_roles": ["auditor"]}}},
    )
    worker = wp.resolve_worker(project_dir, "auditor", "honey")
    assert worker.harness == "claude"
    assert worker.model is None


def test_profile_shadowing_harness_name_is_inert(project_dir):
    # A hand-edited config may define worker_profiles.claude; the harness
    # name still wins (D009 — registry membership is the dispatch authority).
    _save_global(
        {"worker_profiles": {"claude": {"harness": "codex", "model": "gpt-5.2-codex"}}}
    )
    worker = wp.resolve_worker(project_dir, "implementer", "claude")
    assert worker.profile_id is None
    assert worker.harness == "claude"
    assert worker.model is None


# ── Gates: role + capability refusals ─────────────────────────────────────


def test_auditor_only_profile_refused_for_implementer(project_dir):
    _save_global({"worker_profiles": {"honey": _HONEY}})
    with pytest.raises(wp.ProfileRoleRefusedError, match="not allowed to hold role 'implementer'"):
        wp.resolve_worker(project_dir, "implementer", "honey")


def test_capability_restricted_profile_refused_for_implementer(project_dir):
    _save_global(
        {
            "worker_profiles": {
                "readonly": {
                    "harness": "claude",
                    "capabilities": {"file_edit": False},
                }
            }
        }
    )
    with pytest.raises(wp.ProfileCapabilityRefusedError, match="missing capabilities"):
        wp.resolve_worker(project_dir, "implementer", "readonly")
    # The same profile still holds audit-style roles.
    assert wp.resolve_worker(project_dir, "auditor", "readonly").harness == "claude"


def test_unregistered_harness_profile_refused(project_dir):
    _save_global({"worker_profiles": {"gem": {"harness": "gemini"}}})
    with pytest.raises(wp.ProfileHarnessUnknownError, match="no executor in AGENT_REGISTRY"):
        wp.resolve_worker(project_dir, "auditor", "gem")


def test_is_dispatchable_name(project_dir):
    _save_global({"worker_profiles": {"honey": _HONEY}})
    assert wp.is_dispatchable_name("claude", project_path=project_dir)
    assert wp.is_dispatchable_name("codex_cli", project_path=project_dir)
    assert wp.is_dispatchable_name("honey", project_path=project_dir, role="auditor")
    assert not wp.is_dispatchable_name("honey", project_path=project_dir, role="implementer")
    assert not wp.is_dispatchable_name("nobody", project_path=project_dir)


def test_validate_profile_reports_operator_problems():
    profile = WorkerProfile.model_validate(
        {"harness": "claude", "allowed_roles": ["implementer"], "capabilities": {"tool_use": False}}
    )
    problems = wp.validate_profile("BadId", profile)
    assert any("lowercase slug" in p for p in problems)
    assert any("can never be held" in p for p in problems)
    assert wp.validate_profile("honey", WorkerProfile.model_validate(_HONEY)) == []
    assert any(
        "shadows a registered harness" in p
        for p in wp.validate_profile("codex_cli", WorkerProfile.model_validate(_HONEY))
    )


# ── Goal-audit provenance gating ──────────────────────────────────────────


def test_inherited_goal_audit_gates_on_auditor_role(project_dir):
    # No explicit roles.goal_auditor → the goal audit inherits the auditor
    # assignment, so an auditor-only profile stays dispatchable.
    _save_global({"worker_profiles": {"honey": _HONEY}})
    worker = wp.resolve_goal_audit_worker(project_dir, "honey")
    assert worker.harness == "codex"
    assert worker.model == "gpt-5.2-codex"


def test_explicit_goal_auditor_gates_on_goal_auditor_role(project_dir):
    _save_global(
        {"roles": {"goal_auditor": "honey"}, "worker_profiles": {"honey": _HONEY}}
    )
    with pytest.raises(wp.ProfileRoleRefusedError, match="'goal_auditor'"):
        wp.resolve_goal_audit_worker(project_dir, "honey")


# ── i1 (codex audit i0): resolve_model resolves role values through the ──
# profile table before the harness/model vendor comparison. A roles entry
# may name a profile id; the F012 expected-harness check must compare the
# harness that profile DISPATCHES AS, not the raw configured string.

_HONEY_NO_MODEL = {"harness": "codex", "allowed_roles": ["auditor"]}


def test_role_model_applies_when_profile_binds_dispatch_harness(project_dir):
    # Auditor i0 evidence case: honey has no model of its own, so the
    # canonical roles.auditor.model must survive — 'honey' resolves to the
    # codex harness, which IS the dispatched harness.
    _save_global(
        {
            "roles": {"auditor": {"name": "honey", "model": "gpt-role"}},
            "worker_profiles": {"honey": _HONEY_NO_MODEL},
        }
    )
    worker = wp.resolve_worker(project_dir, "auditor", "honey")
    assert (worker.harness, worker.model) == ("codex", None)
    assert resolvers.resolve_model(project_dir, "auditor", harness="codex") == "gpt-role"


def test_role_model_suppressed_when_profile_harness_differs(project_dir):
    # Vendor safety still holds through the profile indirection: a per-call
    # dispatch to a different harness never inherits the profile-paired model.
    _save_global(
        {
            "roles": {"auditor": {"name": "honey", "model": "gpt-role"}},
            "worker_profiles": {"honey": _HONEY_NO_MODEL},
        }
    )
    assert resolvers.resolve_model(project_dir, "auditor", harness="claude") is None


def test_role_model_applies_through_harness_alias(project_dir):
    # A D015 alias in the roles entry counts as its registry key, not as a
    # mismatching literal string.
    _save_global({"roles": {"auditor": {"name": "codex_cli", "model": "gpt-role"}}})
    assert resolvers.resolve_model(project_dir, "auditor", harness="codex") == "gpt-role"


def test_project_profile_override_still_suppresses_cross_vendor_model(project_dir):
    # Cross-layer safety is unchanged: global pairs claude + claude model;
    # the project reassigns the role to a codex-backed profile. The claude
    # model must not ride along to the codex CLI.
    _save_global(
        {
            "roles": {"auditor": {"name": "claude", "model": "claude-opus-5"}},
            "worker_profiles": {"honey": _HONEY_NO_MODEL},
        }
    )
    _write_project_cfg(project_dir, {"roles": {"auditor": "honey"}})
    assert resolvers.resolve_model(project_dir, "auditor", harness="codex") is None


def test_project_profile_shadowing_global_id_suppresses_global_model(project_dir):
    # Codex audit i1 high finding: the GLOBAL layer pairs its model with its
    # OWN honey profile (→ codex); the project shadows the same profile id
    # with a claude-backed profile, so dispatch goes to claude. The global
    # model was never configured against claude — it must be suppressed, not
    # forwarded through the merged profile table.
    _save_global(
        {
            "roles": {"auditor": {"name": "honey", "model": "gpt-global"}},
            "worker_profiles": {"honey": _HONEY_NO_MODEL},
        }
    )
    _write_project_cfg(
        project_dir,
        {"worker_profiles": {"honey": {"harness": "claude", "allowed_roles": ["auditor"]}}},
    )
    worker = wp.resolve_worker(project_dir, "auditor", "honey")
    assert worker.harness == "claude"
    assert resolvers.resolve_model(project_dir, "auditor", harness="claude") is None
    # The pairing stays valid for the vendor it was written against: a
    # per-call/plan dispatch to codex still gets the global model.
    assert resolvers.resolve_model(project_dir, "auditor", harness="codex") == "gpt-global"


# ── CLI: workers add|set|list|show ────────────────────────────────────────


def _global_profiles() -> dict:
    return json.loads(gc.config_path().read_text()).get("worker_profiles", {})


def test_workers_add_writes_normalized_profile(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    rc = workers_main(
        [
            "add",
            "honey",
            "--harness",
            "codex_cli",
            "--model",
            "gpt-5.2-codex",
            "--display-name",
            "Honey",
            "--roles",
            "auditor",
        ]
    )
    assert rc == 0
    stored = _global_profiles()["honey"]
    assert stored["harness"] == "codex"  # alias normalized before write
    assert stored["model"] == "gpt-5.2-codex"
    assert stored["allowed_roles"] == ["auditor"]


def test_workers_add_refuses_unknown_harness_without_writing(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    rc = workers_main(["add", "gem", "--harness", "gemini"])
    assert rc == 3
    assert "no executor in AGENT_REGISTRY" in capsys.readouterr().err
    assert not gc.config_path().is_file()  # refusal happens before any write


def test_workers_add_refuses_id_shadowing_harness(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    rc = workers_main(["add", "codex_cli", "--harness", "codex"])
    assert rc == 3
    assert "shadows a registered harness" in capsys.readouterr().err
    assert not gc.config_path().is_file()


def test_workers_add_refuses_unholdable_role_combo(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    rc = workers_main(
        ["add", "clerk", "--harness", "claude", "--roles", "implementer", "--cap", "file_edit=false"]
    )
    assert rc == 3
    assert "can never be held" in capsys.readouterr().err
    assert not gc.config_path().is_file()


def test_workers_add_malformed_cap_is_usage_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert workers_main(["add", "x", "--harness", "claude", "--cap", "file_edit=maybe"]) == 2
    assert not gc.config_path().is_file()


def test_workers_list_json_reports_holdable_roles(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert (
        workers_main(
            ["add", "honey", "--harness", "codex", "--model", "gpt-5.2-codex", "--roles", "auditor"]
        )
        == 0
    )
    capsys.readouterr()
    assert workers_main(["list", "--json"]) == 0
    payloads = json.loads(capsys.readouterr().out)["worker_profiles"]
    assert [p["id"] for p in payloads] == ["honey"]
    assert payloads[0]["holdable_roles"] == ["auditor"]
    assert payloads[0]["valid"] is True


def test_workers_show_json_and_unknown_id(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert workers_main(["add", "honey", "--harness", "codex", "--roles", "auditor"]) == 0
    capsys.readouterr()
    assert workers_main(["show", "honey", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["harness"] == "codex"
    assert payload["allowed_roles"] == ["auditor"]
    assert workers_main(["show", "nobody"]) == 2


def test_workers_set_updates_field(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert workers_main(["add", "honey", "--harness", "codex"]) == 0
    assert workers_main(["set", "honey", "model", "gpt-5.2-codex"]) == 0
    assert _global_profiles()["honey"]["model"] == "gpt-5.2-codex"


def test_workers_set_missing_profile_is_usage_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert workers_main(["set", "nobody", "model", "m"]) == 2


# ── Dispatch wiring: model propagation + evidence identity ────────────────


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _CapturingExecutor(BaseExecutor):
    agent_name = "claude"
    cli_binary = None

    def __init__(self) -> None:
        self.tasks: list[DispatchTask] = []

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.tasks.append(task)
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary="ok",
            raw_response="ok",
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _make_plan(tmp: Path, plan_id: str) -> Path:
    plan_dir = tmp / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    plan_md = f"""---
id: {plan_id}
title: F013 worker-profile synthetic
type: infra
tier: trivial
status: active
date: "2026-07-28"
description: Synthetic plan for F013 wiring test.
agents_required:
  - claude
  - codex
human_gates: []
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# F013 synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001",
                "category": "test",
                "phase": 0,
                "description": "Synthetic feature for F013 wiring test.",
                "steps": ["scripted"],
                "acceptance": "Task carries the profile model.",
                "passes": False,
                "depends_on": [],
            }
        ],
    }
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(
        json.dumps(features, indent=2, ensure_ascii=False) + "\n"
    )
    return plan_dir


_FEATURE = {"id": "F001", "description": "d", "acceptance": "a", "steps": []}


def _run_round_with(loaded, worker, agent_name: str, role: str) -> tuple[_CapturingExecutor, Path]:
    ex = _CapturingExecutor()
    audit_path = supervisor._run_round(
        loaded=loaded,
        executor=ex,
        agent_name=agent_name,
        role=role,
        iteration=0,
        feature=_FEATURE,
        prompt="synthetic prompt",
        extra_validation=[],
        target_env="dev",
        target_project=None,
        worker=worker,
    )
    return ex, audit_path


def test_run_round_profile_model_wins_over_role_model(tmp_path):
    # Acceptance: honey (codex + gpt model, auditor-only) assigned to
    # roles.auditor dispatches with the profile's harness + model even when
    # an F012 role-level model is also configured.
    _save_global(
        {"worker_profiles": {"honey": _HONEY}, "models": {"auditor": "role-model"}}
    )
    plan_dir = _make_plan(tmp_path, "2026-07-28-004-infra-f013-profile-model")
    loaded = plan_loader.load(plan_dir)
    worker = wp.resolve_worker(plan_dir, "auditor", "honey")
    ex, audit_path = _run_round_with(loaded, worker, agent_name=worker.harness, role="auditor")
    assert ex.tasks[0].model == "gpt-5.2-codex"
    # Evidence records the resolved dispatch identity.
    assert (
        "worker: profile_id=honey harness=codex model=gpt-5.2-codex"
        in audit_path.read_text()
    )


def test_run_round_profile_without_model_falls_through_to_role_model(tmp_path):
    _save_global(
        {
            "worker_profiles": {"impl": {"harness": "claude"}},
            "models": {"implementer": "role-model"},
        }
    )
    plan_dir = _make_plan(tmp_path, "2026-07-28-005-infra-f013-model-fallthrough")
    loaded = plan_loader.load(plan_dir)
    worker = wp.resolve_worker(plan_dir, "implementer", "impl")
    assert worker.model is None
    ex, audit_path = _run_round_with(loaded, worker, agent_name=worker.harness, role="implementer")
    assert ex.tasks[0].model == "role-model"
    assert "worker: profile_id=impl harness=claude model=role-model" in audit_path.read_text()


def test_run_round_role_model_rides_profile_dispatch(tmp_path):
    # i1 wiring regression (codex audit i0): a model-less profile assigned
    # through the canonical roles shape still dispatches with the
    # roles.auditor.model — the expected-harness check resolves the profile
    # id to its harness instead of suppressing the model.
    _save_global(
        {
            "roles": {"auditor": {"name": "honey", "model": "gpt-role"}},
            "worker_profiles": {"honey": {"harness": "codex", "allowed_roles": ["auditor"]}},
        }
    )
    plan_dir = _make_plan(tmp_path, "2026-07-28-007-infra-f013-role-model-profile")
    loaded = plan_loader.load(plan_dir)
    worker = wp.resolve_worker(plan_dir, "auditor", "honey")
    assert worker.model is None
    ex, audit_path = _run_round_with(loaded, worker, agent_name=worker.harness, role="auditor")
    assert ex.tasks[0].model == "gpt-role"
    assert "worker: profile_id=honey harness=codex model=gpt-role" in audit_path.read_text()


def test_run_round_legacy_worker_records_no_profile(tmp_path):
    plan_dir = _make_plan(tmp_path, "2026-07-28-006-infra-f013-legacy")
    loaded = plan_loader.load(plan_dir)
    worker = wp.resolve_worker(plan_dir, "implementer", "claude")
    ex, audit_path = _run_round_with(loaded, worker, agent_name=worker.harness, role="implementer")
    assert ex.tasks[0].model is None
    assert (
        "worker: profile_id=None harness=claude model=(harness default)"
        in audit_path.read_text()
    )
