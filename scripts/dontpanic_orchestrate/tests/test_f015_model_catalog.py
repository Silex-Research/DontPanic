"""F015 — model catalog discovery (Track D4).

Covers the acceptance surface end to end:

  - Catalog: per-harness ``list_models()`` optional interface on
    BaseExecutor (default None = documented pass-through); ``ollama``
    discovery via the local CLI; ``openrouter`` discovery via the models
    API with an offline-safe cache under ``~/.dontpanic/cache/models/``;
    unknown harness ids raise UnknownHarnessError. Catalog entries are
    DATA — never AGENT_REGISTRY keys (D010).
  - Aliases: ``model_aliases`` in global + project config (project wins
    per key); resolution is single-hop; a freeform model string that is
    not an alias passes through unchanged (no code change required).
  - CLI: ``dontpanic models list --harness <id>`` works for a
    discoverable harness, documents pass-through for claude/codex, exits
    2 on unknown harness; ``dontpanic models aliases`` shows the merged
    table.
  - Dispatch wiring: supervisor._run_round resolves aliases on the
    effective model before threading it onto the DispatchTask.
  - Doctor: configured model unknown to a discoverable catalog → WARN;
    harness probe rejects → FAIL; pass-through harness → PASS.

Home-dir isolation comes from the conftest autouse fixture that redirects
DONTPANIC_HOME/JARVIS_HOME to per-test tmp dirs.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_f015_model_catalog.py
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import global_config as gc  # noqa: E402
from dontpanic_orchestrate import model_catalog as mc  # noqa: E402
from dontpanic_orchestrate import plan_loader, supervisor  # noqa: E402
from dontpanic_orchestrate import project_config as pc  # noqa: E402
from dontpanic_orchestrate import sufficiency_auditor as _sa  # noqa: E402
from dontpanic_orchestrate import worker_profiles as wp  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)
from dontpanic_orchestrate.models_cli import models_main  # noqa: E402

# The conftest paid-auditor guard replaces the module attribute
# ``sufficiency_auditor._production_sufficiency_dispatch`` per-test — capture
# the real builder at import time (mirrors test_f012_model_passthrough).
_REAL_SUFFICIENCY_DISPATCH_BUILDER = _sa._production_sufficiency_dispatch

REPO_ROOT = HERE.parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"


def _save_global(payload: dict) -> None:
    gc.save_config(gc.GlobalConfig.model_validate(payload))


def _write_project_cfg(project_dir: Path, payload: dict) -> None:
    cfg_path = pc.project_config_path(project_dir)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(payload))


# ── model_aliases config surface ──────────────────────────────────────────


def test_global_and_project_configs_accept_model_aliases():
    g = gc.GlobalConfig.model_validate({"model_aliases": {"sonnet": "claude-sonnet-5"}})
    assert g.model_aliases == {"sonnet": "claude-sonnet-5"}
    p = pc.ProjectConfig.model_validate({"model_aliases": {"fast": "gpt-5.2-mini"}})
    assert p.model_aliases == {"fast": "gpt-5.2-mini"}


def test_load_model_aliases_project_wins_per_key(tmp_path):
    _save_global({"model_aliases": {"sonnet": "claude-sonnet-5", "fast": "global-fast"}})
    _write_project_cfg(tmp_path, {"model_aliases": {"fast": "project-fast"}})
    merged = mc.load_model_aliases(tmp_path)
    assert merged == {"sonnet": "claude-sonnet-5", "fast": "project-fast"}


def test_resolve_alias_single_hop_and_freeform_pass_through(tmp_path):
    _save_global({"model_aliases": {"sonnet": "claude-sonnet-5", "a": "b", "b": "c"}})
    assert mc.resolve_alias("sonnet", tmp_path) == "claude-sonnet-5"
    # Single-hop: an alias target that is itself an alias key does NOT chain.
    assert mc.resolve_alias("a", tmp_path) == "b"
    # Freeform model strings pass through unchanged — no code change needed.
    assert mc.resolve_alias("some-brand-new-model-2027", tmp_path) == "some-brand-new-model-2027"
    assert mc.resolve_alias(None, tmp_path) is None


# ── Per-harness list_models() optional interface ──────────────────────────


def test_base_executor_list_models_defaults_to_pass_through():
    class _Bare(BaseExecutor):
        agent_name = "bare"

        def dispatch(self, task):  # pragma: no cover — interface stub
            raise NotImplementedError

    assert _Bare().list_models() is None


def test_registered_harnesses_are_documented_pass_through():
    for name in ("claude", "codex", "claude_cli", "codex_cli"):
        catalog = mc.get_catalog(name)
        assert catalog.models is None
        assert catalog.source == "pass_through"


def test_unknown_harness_raises():
    with pytest.raises(mc.UnknownHarnessError):
        mc.get_catalog("gpt-5.2-codex")  # a model id is never a harness (D010)


# ── ollama discovery (local CLI — offline-safe) ───────────────────────────

_OLLAMA_LIST_OUTPUT = """NAME                ID              SIZE      MODIFIED
llama3.2:latest     a80c4f17acd5    2.0 GB    3 weeks ago
qwen2.5-coder:7b    2b0e0b0e0b0e    4.7 GB    5 days ago
"""


def test_ollama_discovery_parses_cli_output(monkeypatch):
    monkeypatch.setattr(mc.shutil, "which", lambda _: "/usr/local/bin/ollama")

    def _fake_run(argv, **kwargs):
        # S607 fix: the executable is the absolute path shutil.which returned.
        assert argv == ["/usr/local/bin/ollama", "list"]
        return subprocess.CompletedProcess(argv, 0, stdout=_OLLAMA_LIST_OUTPUT, stderr="")

    monkeypatch.setattr(mc.subprocess, "run", _fake_run)
    catalog = mc.get_catalog("ollama")
    assert catalog.models == ("llama3.2:latest", "qwen2.5-coder:7b")
    assert catalog.source == "ollama_cli"


def test_ollama_missing_binary_is_unavailable(monkeypatch):
    monkeypatch.setattr(mc.shutil, "which", lambda _: None)
    with pytest.raises(mc.CatalogUnavailableError):
        mc.get_catalog("ollama")


# ── openrouter discovery (network + offline-safe cache) ───────────────────


def test_openrouter_fetch_writes_cache_then_serves_offline(monkeypatch):
    monkeypatch.setattr(mc, "_fetch_openrouter_ids", lambda: ["openai/gpt-5.2", "x-ai/grok-4.5"])
    catalog = mc.get_catalog("openrouter", refresh=True)
    assert catalog.models == ("openai/gpt-5.2", "x-ai/grok-4.5")
    assert catalog.source == "openrouter_api"
    assert mc._openrouter_cache_path().is_file()

    # Network gone: refresh falls back to the cache instead of failing.
    def _boom():
        raise OSError("network down")

    monkeypatch.setattr(mc, "_fetch_openrouter_ids", _boom)
    cached = mc.get_catalog("openrouter", refresh=True)
    assert cached.models == ("openai/gpt-5.2", "x-ai/grok-4.5")
    assert cached.source == "openrouter_cache"
    assert cached.stale is True

    # Offline mode (doctor path) never touches the network at all.
    offline = mc.get_catalog("openrouter", allow_network=False)
    assert offline.models == ("openai/gpt-5.2", "x-ai/grok-4.5")


def test_openrouter_no_cache_no_network_is_unavailable(monkeypatch):
    def _boom():  # pragma: no cover — must not be called offline
        raise AssertionError("network fetch attempted with allow_network=False")

    monkeypatch.setattr(mc, "_fetch_openrouter_ids", _boom)
    with pytest.raises(mc.CatalogUnavailableError):
        mc.get_catalog("openrouter", allow_network=False)


# ── probe_model: ok / unknown / rejected / pass_through / unverifiable ────


def test_probe_pass_through_for_registered_harness():
    assert mc.probe_model("claude", "any-freeform-model").status == "pass_through"


def test_probe_ok_when_model_in_catalog(monkeypatch):
    monkeypatch.setattr(mc.shutil, "which", lambda _: "/usr/local/bin/ollama")
    monkeypatch.setattr(
        mc.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(
            argv, 0, stdout=_OLLAMA_LIST_OUTPUT, stderr=""
        ),
    )
    assert mc.probe_model("ollama", "llama3.2:latest").status == "ok"


def test_probe_rejected_when_harness_probe_fails(monkeypatch):
    monkeypatch.setattr(mc.shutil, "which", lambda _: "/usr/local/bin/ollama")

    def _fake_run(argv, **kwargs):
        assert argv[0] == "/usr/local/bin/ollama"  # S607 fix: absolute path
        if argv[1] == "list":
            return subprocess.CompletedProcess(argv, 0, stdout=_OLLAMA_LIST_OUTPUT, stderr="")
        assert argv[1] == "show"
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="model 'nope' not found")

    monkeypatch.setattr(mc.subprocess, "run", _fake_run)
    probe = mc.probe_model("ollama", "nope")
    assert probe.status == "rejected"


def test_probe_unknown_when_no_authoritative_probe(monkeypatch):
    monkeypatch.setattr(mc, "_fetch_openrouter_ids", lambda: ["openai/gpt-5.2"])
    mc.get_catalog("openrouter", refresh=True)  # seed cache
    probe = mc.probe_model("openrouter", "vendor/mystery-model", allow_network=False)
    assert probe.status == "unknown"


def test_probe_unverifiable_when_catalog_unavailable(monkeypatch):
    monkeypatch.setattr(mc.shutil, "which", lambda _: None)
    assert mc.probe_model("ollama", "llama3.2:latest").status == "unverifiable"


# ── CLI: dontpanic models list / aliases ──────────────────────────────────


def test_models_cli_list_discoverable_harness_json(monkeypatch, capsys):
    monkeypatch.setattr(mc.shutil, "which", lambda _: "/usr/local/bin/ollama")
    monkeypatch.setattr(
        mc.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(
            argv, 0, stdout=_OLLAMA_LIST_OUTPUT, stderr=""
        ),
    )
    assert models_main(["list", "--harness", "ollama", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["harness"] == "ollama"
    assert payload["models"] == ["llama3.2:latest", "qwen2.5-coder:7b"]


def test_models_cli_pass_through_documented(capsys):
    assert models_main(["list", "--harness", "claude"]) == 0
    out = capsys.readouterr().out
    assert "pass-through" in out


def test_models_cli_unknown_harness_exit_2(capsys):
    assert models_main(["list", "--harness", "grok-4.5"]) == 2


def test_models_cli_catalog_unavailable_exit_1(monkeypatch, capsys):
    monkeypatch.setattr(mc.shutil, "which", lambda _: None)
    assert models_main(["list", "--harness", "ollama"]) == 1


def test_models_cli_aliases_shows_merged_table(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    _save_global({"model_aliases": {"sonnet": "claude-sonnet-5"}})
    assert models_main(["aliases", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["model_aliases"] == {"sonnet": "claude-sonnet-5"}


def test_models_command_advertised_on_operator_surface():
    """Codex i1 advisory — `models` is routed in ``_run_cli`` so it must also
    appear on the operator-facing surface: the top-level help block and the
    architecture command catalog (the lockstep contract in
    ``TestCommandCatalogCoversCliSurface``)."""
    import io

    from dontpanic_orchestrate import architecture_view_state as avs
    from dontpanic_orchestrate import cli as cli_mod

    buf = io.StringIO()
    cli_mod._print_top_level_help(file=buf)
    assert "models list|aliases" in buf.getvalue()

    catalog_names = {entry["name"] for entry in avs._COMMAND_CATALOG}
    assert {"dontpanic models list", "dontpanic models aliases"} <= catalog_names


# ── Dispatch wiring: aliases resolve on the effective model ───────────────


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
title: F015 model-alias synthetic
type: infra
tier: trivial
status: active
date: "2026-07-28"
description: Synthetic plan for F015 alias wiring test.
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

# F015 synthetic

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
                "description": "Synthetic feature for F015 wiring test.",
                "steps": ["scripted"],
                "acceptance": "Task carries the alias-resolved model.",
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


def test_run_round_resolves_alias_on_profile_model(tmp_path):
    _save_global(
        {
            "worker_profiles": {"impl": {"harness": "claude", "model": "sonnet"}},
            "model_aliases": {"sonnet": "claude-sonnet-5"},
        }
    )
    plan_dir = _make_plan(tmp_path, "2026-07-28-010-infra-f015-alias-profile")
    loaded = plan_loader.load(plan_dir)
    worker = wp.resolve_worker(plan_dir, "implementer", "impl")
    ex = _CapturingExecutor()
    supervisor._run_round(
        loaded=loaded,
        executor=ex,
        agent_name=worker.harness,
        role="implementer",
        iteration=0,
        feature=_FEATURE,
        prompt="synthetic prompt",
        extra_validation=[],
        target_env="dev",
        target_project=None,
        worker=worker,
    )
    assert ex.tasks[0].model == "claude-sonnet-5"


def test_run_round_freeform_model_unchanged(tmp_path):
    # Freeform model string with no alias entry dispatches verbatim — a new
    # model version never requires a code (or alias) change.
    _save_global({"worker_profiles": {"impl": {"harness": "claude", "model": "claude-6-preview"}}})
    plan_dir = _make_plan(tmp_path, "2026-07-28-011-infra-f015-freeform")
    loaded = plan_loader.load(plan_dir)
    worker = wp.resolve_worker(plan_dir, "implementer", "impl")
    ex = _CapturingExecutor()
    supervisor._run_round(
        loaded=loaded,
        executor=ex,
        agent_name=worker.harness,
        role="implementer",
        iteration=0,
        feature=_FEATURE,
        prompt="synthetic prompt",
        extra_validation=[],
        target_env="dev",
        target_project=None,
        worker=worker,
    )
    assert ex.tasks[0].model == "claude-6-preview"


# ── Doctor: unknown → WARN, rejected → FAIL, pass-through → PASS ─────────


def _load_doctor():
    spec = importlib.util.spec_from_file_location("jarvis_doctor_f015", DOCTOR_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_doctor_f015"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def doctor():
    return _load_doctor()


def test_doctor_pass_through_harness_default_is_ok(doctor):
    # Zero config: roles fall back to claude/codex with no model override.
    results = doctor.check_model_catalog()
    assert results, "expected one result per canonical role"
    assert all(r.ok and not r.warn for r in results)


def test_doctor_unknown_model_warns_rejected_fails(doctor, monkeypatch):
    from dontpanic_orchestrate.config import resolvers

    monkeypatch.setattr(resolvers, "resolve_model", lambda *a, **k: "vendor/mystery-model")
    monkeypatch.setattr(
        mc, "probe_model", lambda *a, **k: mc.ModelProbe(status="unknown", detail="not in catalog")
    )
    results = doctor.check_model_catalog()
    assert all(r.ok for r in results)
    assert all(r.warn for r in results)

    monkeypatch.setattr(
        mc,
        "probe_model",
        lambda *a, **k: mc.ModelProbe(status="rejected", detail="model not found"),
    )
    results = doctor.check_model_catalog()
    assert all(not r.ok for r in results)


def test_doctor_alias_resolves_before_probe(doctor, monkeypatch):
    from dontpanic_orchestrate.config import resolvers

    _save_global({"model_aliases": {"sonnet": "claude-sonnet-5"}})
    monkeypatch.setattr(resolvers, "resolve_model", lambda *a, **k: "sonnet")
    seen: list[str] = []

    def _probe(harness, model, **kw):
        seen.append(model)
        return mc.ModelProbe(status="pass_through", detail="")

    monkeypatch.setattr(mc, "probe_model", _probe)
    results = doctor.check_model_catalog()
    assert all(r.ok for r in results)
    assert seen and all(m == "claude-sonnet-5" for m in seen)


# ── i1 finding 3: the probe uses the RESOLVED harness, not the role name ──
# The configured role value may be a D015 harness alias (claude_cli) or an
# F013 worker-profile id; resolve_model's atomic harness check must receive
# the harness the role actually dispatches to, else role-level models are
# silently suppressed and the doctor probes the wrong identity.


def _capture_probe(monkeypatch) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []

    def _probe(harness, model, **kw):
        seen.append((harness, model))
        return mc.ModelProbe(status="pass_through", detail="")

    monkeypatch.setattr(mc, "probe_model", _probe)
    return seen


def test_doctor_probes_role_model_bound_to_harness_alias(doctor, monkeypatch):
    _save_global(
        {
            "roles": {"implementer": {"name": "claude_cli", "model": "sonnet"}},
            "model_aliases": {"sonnet": "claude-sonnet-5"},
        }
    )
    seen = _capture_probe(monkeypatch)
    results = doctor.check_model_catalog()
    assert all(r.ok for r in results)
    assert ("claude", "claude-sonnet-5") in seen


def test_doctor_probes_role_model_bound_to_worker_profile(doctor, monkeypatch):
    _save_global(
        {
            "worker_profiles": {"impl": {"harness": "claude"}},
            "roles": {"implementer": {"name": "impl", "model": "vendor/custom-model"}},
        }
    )
    seen = _capture_probe(monkeypatch)
    results = doctor.check_model_catalog()
    assert all(r.ok for r in results)
    assert ("claude", "vendor/custom-model") in seen


# ── i1 finding 2: model checks are project-root parameterized ─────────────


def test_doctor_model_catalog_reads_project_config(doctor, tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    _write_project_cfg(
        project,
        {
            "roles": {"implementer": {"name": "claude", "model": "proj-model"}},
            "model_aliases": {"proj-model": "vendor/project-pinned"},
        },
    )
    seen = _capture_probe(monkeypatch)
    results = doctor.check_model_catalog(project, name_prefix="project:p1:")
    assert results and all(r.name.startswith("project:p1:models:") for r in results)
    assert ("claude", "vendor/project-pinned") in seen


def test_doctor_registered_project_includes_model_checks(doctor, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _write_project_cfg(
        project, {"roles": {"implementer": {"name": "claude", "model": "proj-model"}}}
    )

    class _Entry:
        name = "p1"
        path = str(project)

    results = doctor.check_registered_project(_Entry())
    model_checks = [r for r in results if r.name.startswith("project:p1:models:")]
    assert {r.name for r in model_checks} == {
        "project:p1:models:implementer",
        "project:p1:models:auditor",
        "project:p1:models:goal_auditor",
    }
    impl = next(r for r in model_checks if r.name.endswith(":implementer"))
    assert impl.ok and "proj-model" in impl.message


# ── i1 finding 1: goal-audit dispatch paths resolve aliases ───────────────
# (sufficiency_auditor._production_sufficiency_dispatch and
# completion_dispatch._dispatch_via_executor passed worker.model /
# resolve_goal_audit_model output into DispatchTask without going through
# model_catalog.resolve_alias.)


def _available_capturing_executor() -> _CapturingExecutor:
    ex = _CapturingExecutor()
    ex.is_available = lambda: True  # type: ignore[method-assign]
    return ex


def test_completion_dispatch_resolves_role_model_alias(monkeypatch, tmp_path):
    from dontpanic_orchestrate import completion_dispatch

    _save_global(
        {
            "models": {"goal_auditor": "fast-audit"},
            "model_aliases": {"fast-audit": "gpt-5.2-codex"},
        }
    )
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    ex = _available_capturing_executor()
    monkeypatch.setattr(completion_dispatch, "get_executor", lambda name: ex)
    completion_dispatch._dispatch_via_executor("codex", "prompt", plan_dir=project_dir)
    assert ex.tasks[0].model == "gpt-5.2-codex"


def test_completion_dispatch_resolves_profile_model_alias(monkeypatch, tmp_path):
    from dontpanic_orchestrate import completion_dispatch

    _save_global(
        {
            "worker_profiles": {"aud": {"harness": "codex", "model": "fast-audit"}},
            "model_aliases": {"fast-audit": "gpt-5.2-codex"},
        }
    )
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    ex = _available_capturing_executor()
    monkeypatch.setattr(completion_dispatch, "get_executor", lambda name: ex)
    completion_dispatch._dispatch_via_executor("aud", "prompt", plan_dir=project_dir)
    assert ex.tasks[0].model == "gpt-5.2-codex"


def test_completion_dispatch_freeform_model_passes_through(monkeypatch, tmp_path):
    from dontpanic_orchestrate import completion_dispatch

    _save_global(
        {
            "models": {"goal_auditor": "brand-new-model-2027"},
            "model_aliases": {"unrelated": "x"},
        }
    )
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    ex = _available_capturing_executor()
    monkeypatch.setattr(completion_dispatch, "get_executor", lambda name: ex)
    completion_dispatch._dispatch_via_executor("codex", "prompt", plan_dir=project_dir)
    assert ex.tasks[0].model == "brand-new-model-2027"


def test_sufficiency_dispatch_resolves_role_model_alias(monkeypatch, tmp_path):
    from dontpanic_orchestrate import executors as executors_pkg

    _save_global(
        {
            "models": {"goal_auditor": "fast-audit"},
            "model_aliases": {"fast-audit": "gpt-5.2-codex"},
        }
    )
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    ex = _available_capturing_executor()
    monkeypatch.setattr(executors_pkg, "get_executor", lambda name: ex)
    dispatch = _REAL_SUFFICIENCY_DISPATCH_BUILDER(project_dir)
    dispatch("codex", "prompt")
    assert ex.tasks[0].model == "gpt-5.2-codex"


def test_sufficiency_dispatch_resolves_profile_model_alias(monkeypatch, tmp_path):
    from dontpanic_orchestrate import executors as executors_pkg

    _save_global(
        {
            "worker_profiles": {"aud": {"harness": "codex", "model": "fast-audit"}},
            "model_aliases": {"fast-audit": "gpt-5.2-codex"},
        }
    )
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    ex = _available_capturing_executor()
    monkeypatch.setattr(executors_pkg, "get_executor", lambda name: ex)
    dispatch = _REAL_SUFFICIENCY_DISPATCH_BUILDER(project_dir)
    dispatch("aud", "prompt")
    assert ex.tasks[0].model == "gpt-5.2-codex"
