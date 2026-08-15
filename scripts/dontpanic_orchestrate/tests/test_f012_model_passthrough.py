"""F012 — model pass-through (D1 / D011 / D016).

Covers:

  - ``DispatchTask.model`` defaults to None (back-compat: every existing
    construction site keeps harness-CLI-default behavior).
  - Executor argv translation: unset model preserves the pre-F012 argv
    shape exactly (no ``--model`` token anywhere); set model adds the
    vendor model flag (``--model <id>`` for both Claude and Codex).
  - ``RoleModelsConfig`` shape on global + project config (extra='forbid').
  - ``resolve_model`` precedence (D016 subset shipped in F012 — role-level
    override without full profiles): per-call > project.models.<role> >
    global.models.<role> > None (harness CLI default).
  - Unknown roles resolve to None rather than raising — model override is
    optional metadata, not a dispatch precondition.
  - Supervisor ``_run_round`` threads the resolved model onto the
    DispatchTask it builds (wiring, not just unit shape).

i1 additions (codex audit i0 findings):

  - Canonical plan-locked ``roles.<role>.model`` shape: roles entries
    accept plain strings (back-compat) or ``{"name", "model"}`` objects;
    canonical shape wins over the ``models.<role>`` compat block within
    a layer.
  - Goal-audit production dispatch paths (completion + sufficiency)
    resolve and forward the model; auditor-model fall-through applies
    only when no explicit ``roles.goal_auditor`` is configured
    (vendor-safety).

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_f012_model_passthrough.py
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
from dontpanic_orchestrate import sufficiency_auditor as _sa  # noqa: E402
from dontpanic_orchestrate.config import resolvers  # noqa: E402
from dontpanic_orchestrate.config.roles import RoleModelsConfig, RoleSpec  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)
from dontpanic_orchestrate.executors.claude_cli import ClaudeCLIExecutor  # noqa: E402
from dontpanic_orchestrate.executors.codex_cli import CodexCLIExecutor  # noqa: E402
from dontpanic_orchestrate.subprocess_runner import SubprocessResult  # noqa: E402

# The conftest paid-auditor guard replaces the module attribute
# ``sufficiency_auditor._production_sufficiency_dispatch`` per-test
# (fail-closed against accidental live calls). The i1 regression tests below
# exercise the REAL builder offline — ``get_executor`` is monkeypatched, so no
# executor subprocess ever runs — which requires capturing the original here
# at import time, before the autouse guard patches the symbol.
_REAL_SUFFICIENCY_DISPATCH_BUILDER = _sa._production_sufficiency_dispatch


@pytest.fixture(autouse=True)
def _isolate_dontpanic_home(tmp_path, monkeypatch):
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "some-project"
    d.mkdir()
    return d


def _make_task(tmp_path: Path, *, model: str | None = None) -> DispatchTask:
    return DispatchTask(
        plan_id="p",
        plan_dir=tmp_path,
        feature_id="F001",
        feature_description="d",
        feature_acceptance="a",
        feature_steps=[],
        agent_role="implementer",
        cwd=tmp_path,
        permission_policy="implementer",
        model=model,
    )


def _fake_runner_factory(captured: dict, stdout: bytes):
    def _fake_runner(argv, **kwargs):
        captured["argv"] = list(argv)
        return SubprocessResult(
            exit_code=0,
            stdout=stdout,
            stderr=b"",
            timed_out=False,
            timeout_seconds=600,
            grace_period_used=False,
            captured_stdout_bytes=len(stdout),
            captured_stderr_bytes=0,
            worktree_changed=False,
            pgid=123,
        )

    return _fake_runner


_CLAUDE_STDOUT = b'{"result":"ok","is_error":false,"usage":{},"modelUsage":{"v1":{}}}'
_CODEX_STDOUT = (
    b'{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}\n'
    b'{"type":"turn.completed","usage":{}}\n'
)


# ── DispatchTask back-compat ──────────────────────────────────────────────


def test_dispatch_task_model_defaults_to_none(tmp_path):
    task = DispatchTask(
        plan_id="p",
        plan_dir=tmp_path,
        feature_id="F001",
        feature_description="d",
        feature_acceptance="a",
        feature_steps=[],
        agent_role="implementer",
    )
    assert task.model is None


# ── Executor argv: unset model preserves pre-F012 shape ───────────────────


def test_claude_argv_without_model_has_no_model_flag(monkeypatch, tmp_path):
    from dontpanic_orchestrate.executors import claude_cli

    captured: dict = {}
    monkeypatch.setattr(
        claude_cli, "run_subprocess", _fake_runner_factory(captured, _CLAUDE_STDOUT)
    )
    ClaudeCLIExecutor(binary="/bin/echo").dispatch(_make_task(tmp_path))
    argv = captured["argv"]
    assert "--model" not in argv
    # Exact legacy shape (binary + base flags + implementer permission flags).
    assert argv[1:] == [
        "-p",
        "--output-format",
        "json",
        "--exclude-dynamic-system-prompt-sections",
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "Read Edit Write Bash",
    ]


def test_codex_argv_without_model_has_no_model_flag(monkeypatch, tmp_path):
    from dontpanic_orchestrate.executors import codex_cli

    captured: dict = {}
    monkeypatch.setattr(codex_cli, "run_subprocess", _fake_runner_factory(captured, _CODEX_STDOUT))
    CodexCLIExecutor(binary="/bin/echo").dispatch(_make_task(tmp_path))
    argv = captured["argv"]
    assert "--model" not in argv
    assert argv[1:5] == ["--ask-for-approval", "never", "--sandbox", "workspace-write"]
    assert argv[5:7] == ["exec", "--json"]


# ── Executor argv: set model forwards the vendor flag ─────────────────────


def test_claude_argv_with_model_appends_model_flag(monkeypatch, tmp_path):
    from dontpanic_orchestrate.executors import claude_cli

    captured: dict = {}
    monkeypatch.setattr(
        claude_cli, "run_subprocess", _fake_runner_factory(captured, _CLAUDE_STDOUT)
    )
    ClaudeCLIExecutor(binary="/bin/echo").dispatch(_make_task(tmp_path, model="claude-opus-5"))
    argv = captured["argv"]
    i = argv.index("--model")
    assert argv[i : i + 2] == ["--model", "claude-opus-5"]


def test_codex_argv_with_model_inside_exec_subcommand(monkeypatch, tmp_path):
    from dontpanic_orchestrate.executors import codex_cli

    captured: dict = {}
    monkeypatch.setattr(codex_cli, "run_subprocess", _fake_runner_factory(captured, _CODEX_STDOUT))
    CodexCLIExecutor(binary="/bin/echo").dispatch(_make_task(tmp_path, model="gpt-5.2-codex"))
    argv = captured["argv"]
    i = argv.index("--model")
    assert argv[i : i + 2] == ["--model", "gpt-5.2-codex"]
    # Flag is scoped to the `exec` subcommand (after `exec`), before the prompt
    # (the prompt is always the final positional arg).
    assert argv.index("exec") < i < len(argv) - 1


# ── Config shape: models block on both tiers ──────────────────────────────


def test_global_config_accepts_models_block():
    cfg = gc.GlobalConfig.model_validate(
        {"models": {"implementer": "claude-opus-5", "auditor": "gpt-5.2-codex"}}
    )
    assert cfg.models is not None
    assert cfg.models.implementer == "claude-opus-5"
    assert cfg.models.auditor == "gpt-5.2-codex"


def test_project_config_accepts_models_block(project_dir):
    cfg_path = pc.project_config_path(project_dir)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"models": {"implementer": "claude-sonnet-5"}}))
    cfg = pc.load_project_config(project_dir)
    assert cfg is not None
    assert cfg.models is not None
    assert cfg.models.implementer == "claude-sonnet-5"


def test_models_block_rejects_unknown_role_key():
    with pytest.raises(ValidationError):
        RoleModelsConfig.model_validate({"stranger": "some-model"})


# ── resolve_model precedence ──────────────────────────────────────────────


def test_resolve_model_none_when_all_layers_unset(project_dir):
    assert resolvers.resolve_model(project_dir, "implementer") is None
    assert resolvers.resolve_model(project_dir, "auditor") is None


def test_resolve_model_global_layer(project_dir):
    gc.save_config(gc.GlobalConfig(models=RoleModelsConfig(implementer="global-model")))
    assert resolvers.resolve_model(project_dir, "implementer") == "global-model"
    # Only the configured role resolves; the other stays harness-default.
    assert resolvers.resolve_model(project_dir, "auditor") is None


def test_resolve_model_project_wins_over_global(project_dir):
    gc.save_config(gc.GlobalConfig(models=RoleModelsConfig(implementer="global-model")))
    cfg_path = pc.project_config_path(project_dir)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"models": {"implementer": "project-model"}}))
    assert resolvers.resolve_model(project_dir, "implementer") == "project-model"


def test_resolve_model_per_call_wins_over_all(project_dir):
    gc.save_config(gc.GlobalConfig(models=RoleModelsConfig(implementer="global-model")))
    cfg_path = pc.project_config_path(project_dir)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"models": {"implementer": "project-model"}}))
    assert (
        resolvers.resolve_model(project_dir, "implementer", per_call="call-model") == "call-model"
    )


def test_resolve_model_unknown_role_returns_none(project_dir):
    # Unlike resolve_role, unknown roles must NOT raise — model override is
    # optional metadata and supervisor roles include verifier/security/etc.
    assert resolvers.resolve_model(project_dir, "verifier") is None


# ── Supervisor wiring: _run_round threads resolved model onto the task ────


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
title: F012 model pass-through synthetic
type: infra
tier: trivial
status: active
date: "2026-07-28"
description: Synthetic plan for F012 wiring test.
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

# F012 synthetic

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
                "description": "Synthetic feature for F012 wiring test.",
                "steps": ["scripted"],
                "acceptance": "Task carries resolved model.",
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


def test_run_round_passes_resolved_model_to_task(tmp_path):
    gc.save_config(gc.GlobalConfig(models=RoleModelsConfig(implementer="claude-opus-5")))
    plan_dir = _make_plan(tmp_path, "2026-07-28-001-infra-f012-model-wiring")
    loaded = plan_loader.load(plan_dir)
    feature = {
        "id": "F001",
        "description": "d",
        "acceptance": "a",
        "steps": [],
    }
    ex = _CapturingExecutor()
    supervisor._run_round(
        loaded=loaded,
        executor=ex,
        agent_name="claude",
        role="implementer",
        iteration=0,
        feature=feature,
        prompt="synthetic prompt",
        extra_validation=[],
        target_env="dev",
        target_project=None,
    )
    assert len(ex.tasks) == 1
    assert ex.tasks[0].model == "claude-opus-5"


# ── i1: canonical roles.*.model shape (plan D1 lock; codex audit i0) ──────


def test_roles_entry_accepts_object_with_name_and_model(project_dir):
    cfg = gc.GlobalConfig.model_validate(
        {"roles": {"auditor": {"name": "codex", "model": "gpt-5.2-codex"}}}
    )
    gc.save_config(cfg)
    assert resolvers.resolve_role(project_dir, "auditor") == "codex"
    assert resolvers.resolve_model(project_dir, "auditor") == "gpt-5.2-codex"


def test_roles_entry_plain_string_still_valid(project_dir):
    gc.save_config(gc.GlobalConfig.model_validate({"roles": {"auditor": "codex"}}))
    assert resolvers.resolve_role(project_dir, "auditor") == "codex"
    assert resolvers.resolve_model(project_dir, "auditor") is None


def test_roles_entry_model_only_name_falls_through(project_dir):
    gc.save_config(gc.GlobalConfig(roles=gc.RolesConfig(implementer=RoleSpec(model="m1"))))
    # Name unset in the object entry → hardcoded fallback; model still pins.
    assert resolvers.resolve_role(project_dir, "implementer") == "claude"
    assert resolvers.resolve_model(project_dir, "implementer") == "m1"


def test_roles_entry_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        gc.GlobalConfig.model_validate({"roles": {"auditor": {"name": "codex", "extra": "x"}}})


def test_canonical_roles_model_wins_over_models_block_same_layer(project_dir):
    gc.save_config(
        gc.GlobalConfig.model_validate(
            {
                "roles": {"implementer": {"name": "claude", "model": "canonical-model"}},
                "models": {"implementer": "compat-model"},
            }
        )
    )
    assert resolvers.resolve_model(project_dir, "implementer") == "canonical-model"


def test_project_roles_model_wins_over_global_models_block(project_dir):
    gc.save_config(gc.GlobalConfig(models=RoleModelsConfig(implementer="global-model")))
    cfg_path = pc.project_config_path(project_dir)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"roles": {"implementer": {"model": "project-roles-model"}}}))
    assert resolvers.resolve_model(project_dir, "implementer") == "project-roles-model"


def test_role_assignment_reads_object_shaped_roles_entry(project_dir):
    # role_assignment._layer_role_value must normalize RoleSpec entries the
    # same way resolvers does (both are roles-block readers).
    from dontpanic_orchestrate import role_assignment

    cfg = gc.GlobalConfig.model_validate(
        {"roles": {"auditor": {"name": "codex", "model": "gpt-5.2-codex"}}}
    )
    res = role_assignment.resolve_role_with_source("auditor", project_cfg=None, global_cfg=cfg)
    assert res.value == "codex"


# ── i1: goal-audit production dispatch paths carry the model ──────────────
# (codex audit i0 high finding: completion_dispatch._dispatch_via_executor
# and sufficiency_auditor._production_sufficiency_dispatch built their
# DispatchTask without `model`, silently suppressing configured overrides.)


def _make_available_capturing_executor() -> _CapturingExecutor:
    ex = _CapturingExecutor()
    ex.is_available = lambda: True  # type: ignore[method-assign]
    return ex


def test_completion_dispatch_forwards_goal_auditor_model(monkeypatch, project_dir):
    from dontpanic_orchestrate import completion_dispatch

    gc.save_config(gc.GlobalConfig(models=RoleModelsConfig(goal_auditor="goal-model")))
    ex = _make_available_capturing_executor()
    monkeypatch.setattr(completion_dispatch, "get_executor", lambda name: ex)
    completion_dispatch._dispatch_via_executor("codex", "prompt", plan_dir=project_dir)
    assert len(ex.tasks) == 1
    assert ex.tasks[0].model == "goal-model"


def test_completion_dispatch_model_none_when_unconfigured(monkeypatch, project_dir):
    from dontpanic_orchestrate import completion_dispatch

    ex = _make_available_capturing_executor()
    monkeypatch.setattr(completion_dispatch, "get_executor", lambda name: ex)
    completion_dispatch._dispatch_via_executor("codex", "prompt", plan_dir=project_dir)
    assert ex.tasks[0].model is None


def test_completion_dispatch_falls_through_to_auditor_model(monkeypatch, project_dir):
    # No explicit roles.goal_auditor → the goal audit runs on the resolved
    # auditor agent, so the auditor-role model applies (vendor-safe).
    from dontpanic_orchestrate import completion_dispatch

    gc.save_config(gc.GlobalConfig(models=RoleModelsConfig(auditor="auditor-model")))
    ex = _make_available_capturing_executor()
    monkeypatch.setattr(completion_dispatch, "get_executor", lambda name: ex)
    completion_dispatch._dispatch_via_executor("codex", "prompt", plan_dir=project_dir)
    assert ex.tasks[0].model == "auditor-model"


def test_no_auditor_model_fallthrough_when_explicit_goal_auditor(project_dir):
    # An explicit goal_auditor agent may be a different vendor than the
    # auditor; reusing the auditor's model id there would be wrong. The
    # goal audit falls back to the harness CLI default instead.
    gc.save_config(
        gc.GlobalConfig(
            roles=gc.RolesConfig(goal_auditor="gemini"),
            models=RoleModelsConfig(auditor="auditor-model"),
        )
    )
    assert resolvers.resolve_goal_audit_model(project_dir) is None


def test_sufficiency_dispatch_forwards_goal_auditor_model(monkeypatch, project_dir):
    from dontpanic_orchestrate import executors as executors_pkg

    gc.save_config(gc.GlobalConfig(models=RoleModelsConfig(goal_auditor="goal-model")))
    ex = _make_available_capturing_executor()
    monkeypatch.setattr(executors_pkg, "get_executor", lambda name: ex)
    dispatch = _REAL_SUFFICIENCY_DISPATCH_BUILDER(project_dir)
    dispatch("codex", "prompt")
    assert len(ex.tasks) == 1
    assert ex.tasks[0].model == "goal-model"


def test_sufficiency_dispatch_model_none_when_unconfigured(monkeypatch, project_dir):
    from dontpanic_orchestrate import executors as executors_pkg

    ex = _make_available_capturing_executor()
    monkeypatch.setattr(executors_pkg, "get_executor", lambda name: ex)
    dispatch = _REAL_SUFFICIENCY_DISPATCH_BUILDER(project_dir)
    dispatch("codex", "prompt")
    assert ex.tasks[0].model is None


# ── i2: atomic harness/model resolution (codex audit i1 high finding) ─────
# A model configured for one vendor's harness must never be forwarded to
# another vendor's CLI. With `harness=` (the actually-dispatched agent), a
# layer's model applies only when the harness that layer was configured
# against — its own entry's name, else name resolution from that layer
# downward, else the hardcoded fallback — matches.


def _write_project_cfg(project_dir: Path, payload: dict) -> None:
    cfg_path = pc.project_config_path(project_dir)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(payload))


def test_model_suppressed_when_project_changes_harness(project_dir):
    # Auditor i1 evidence case: global pairs claude + claude-opus-5; the
    # project overrides the implementer to codex (name only). The inherited
    # claude model must NOT reach the codex CLI.
    gc.save_config(
        gc.GlobalConfig(
            roles=gc.RolesConfig(implementer=RoleSpec(name="claude", model="claude-opus-5"))
        )
    )
    _write_project_cfg(project_dir, {"roles": {"implementer": "codex"}})
    assert resolvers.resolve_role(project_dir, "implementer") == "codex"
    assert resolvers.resolve_model(project_dir, "implementer", harness="codex") is None


def test_plan_agents_required_override_suppresses_config_model(project_dir):
    # Plan-level agents_required pick (per-call harness override) must not
    # inherit a model the config paired with a different vendor.
    gc.save_config(
        gc.GlobalConfig(
            roles=gc.RolesConfig(implementer=RoleSpec(name="claude", model="claude-opus-5"))
        )
    )
    assert resolvers.resolve_model(project_dir, "implementer", harness="codex") is None
    assert resolvers.resolve_model(project_dir, "implementer", harness="claude") == "claude-opus-5"


def test_model_applies_when_harness_matches_across_layers(project_dir):
    # Project pins model-only; global names the same harness the dispatch
    # uses → the cross-layer pair is vendor-consistent and applies.
    gc.save_config(gc.GlobalConfig.model_validate({"roles": {"implementer": "claude"}}))
    _write_project_cfg(project_dir, {"roles": {"implementer": {"model": "claude-sonnet-5"}}})
    assert (
        resolvers.resolve_model(project_dir, "implementer", harness="claude") == "claude-sonnet-5"
    )


def test_mismatched_layer_skipped_deeper_matching_layer_applies(project_dir):
    # Each layer pairs its own vendor. Whichever harness is dispatched gets
    # the model configured FOR that harness, never the other one's.
    gc.save_config(
        gc.GlobalConfig(
            roles=gc.RolesConfig(implementer=RoleSpec(name="claude", model="claude-opus-5"))
        )
    )
    _write_project_cfg(
        project_dir,
        {"roles": {"implementer": {"name": "codex", "model": "gpt-5.2-codex"}}},
    )
    assert resolvers.resolve_model(project_dir, "implementer", harness="codex") == "gpt-5.2-codex"
    assert resolvers.resolve_model(project_dir, "implementer", harness="claude") == "claude-opus-5"


def test_model_only_entry_bound_to_fallback_harness(project_dir):
    # No name anywhere → a model-only entry is implicitly configured for the
    # fallback harness (claude for implementer); a per-call override to
    # another vendor suppresses it.
    gc.save_config(gc.GlobalConfig(roles=gc.RolesConfig(implementer=RoleSpec(model="m1"))))
    assert resolvers.resolve_model(project_dir, "implementer", harness="claude") == "m1"
    assert resolvers.resolve_model(project_dir, "implementer", harness="codex") is None


def test_no_harness_keeps_display_behavior(project_dir):
    # Inventory/display callers pass no harness → no suppression (pre-i2
    # resolve order), so config surfacing keeps showing what is configured.
    gc.save_config(
        gc.GlobalConfig(
            roles=gc.RolesConfig(implementer=RoleSpec(name="claude", model="claude-opus-5"))
        )
    )
    _write_project_cfg(project_dir, {"roles": {"implementer": "codex"}})
    assert resolvers.resolve_model(project_dir, "implementer") == "claude-opus-5"


def test_goal_audit_model_harness_aware(project_dir):
    # Auditor-role model falls through to the goal audit only when the goal
    # audit dispatches to the harness that model was configured against.
    gc.save_config(
        gc.GlobalConfig(roles=gc.RolesConfig(auditor=RoleSpec(name="codex", model="gpt-5.2-codex")))
    )
    assert resolvers.resolve_goal_audit_model(project_dir, harness="codex") == "gpt-5.2-codex"
    assert resolvers.resolve_goal_audit_model(project_dir, harness="claude") is None


def test_completion_dispatch_suppresses_cross_vendor_model(monkeypatch, project_dir):
    # Wiring: _dispatch_via_executor passes its actual auditor harness, so a
    # model paired with codex never rides along on a claude dispatch.
    from dontpanic_orchestrate import completion_dispatch

    gc.save_config(
        gc.GlobalConfig(roles=gc.RolesConfig(auditor=RoleSpec(name="codex", model="gpt-5.2-codex")))
    )
    ex = _make_available_capturing_executor()
    monkeypatch.setattr(completion_dispatch, "get_executor", lambda name: ex)
    completion_dispatch._dispatch_via_executor("claude", "prompt", plan_dir=project_dir)
    assert ex.tasks[0].model is None
    completion_dispatch._dispatch_via_executor("codex", "prompt", plan_dir=project_dir)
    assert ex.tasks[1].model == "gpt-5.2-codex"


def test_run_round_suppresses_cross_vendor_model(tmp_path):
    # Wiring: _run_round dispatching codex (e.g. a plan agents_required pick)
    # must not carry the claude-paired model onto the task.
    gc.save_config(
        gc.GlobalConfig(
            roles=gc.RolesConfig(implementer=RoleSpec(name="claude", model="claude-opus-5"))
        )
    )
    plan_dir = _make_plan(tmp_path, "2026-07-28-003-infra-f012-model-mismatch")
    loaded = plan_loader.load(plan_dir)
    feature = {
        "id": "F001",
        "description": "d",
        "acceptance": "a",
        "steps": [],
    }
    ex = _CapturingExecutor()
    supervisor._run_round(
        loaded=loaded,
        executor=ex,
        agent_name="codex",
        role="implementer",
        iteration=0,
        feature=feature,
        prompt="synthetic prompt",
        extra_validation=[],
        target_env="dev",
        target_project=None,
    )
    assert ex.tasks[0].model is None


def test_run_round_model_none_when_unconfigured(tmp_path):
    plan_dir = _make_plan(tmp_path, "2026-07-28-002-infra-f012-model-unset")
    loaded = plan_loader.load(plan_dir)
    feature = {
        "id": "F001",
        "description": "d",
        "acceptance": "a",
        "steps": [],
    }
    ex = _CapturingExecutor()
    supervisor._run_round(
        loaded=loaded,
        executor=ex,
        agent_name="claude",
        role="implementer",
        iteration=0,
        feature=feature,
        prompt="synthetic prompt",
        extra_validation=[],
        target_env="dev",
        target_project=None,
    )
    assert ex.tasks[0].model is None
