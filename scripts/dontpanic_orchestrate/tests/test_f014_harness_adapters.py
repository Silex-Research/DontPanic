"""Plan 2026-07-27-001 F014 — additional harness adapters (ollama, openrouter).

Covers the four F014 invariants:

  1. New harnesses register under STABLE ids — no model version string is
     ever an AGENT_REGISTRY key (D010/D012).
  2. Each adapter declares capability flags, and the declaration on the
     executor class agrees with the authoritative HARNESS_CAPABILITIES
     table (no drift between the two surfaces).
  3. The implementer role is REFUSED for harnesses that lack
     file_edit + tool_use + non_interactive — on the profile path (F013,
     already gated), on the legacy bare-harness path (resolve_worker /
     assert_registrable, new in F014), and as defense-in-depth inside the
     adapters' dispatch().
  4. Dispatch + availability probes work with mocks only — no live API,
     binary, or network in this module.

gemini_cli (D001 B2) is deliberately NOT registered here: B2 requires
proven non-interactive CLI smoke, which this plan has not captured yet.
"""

from __future__ import annotations

import re

import pytest

from dontpanic_orchestrate import agent_surface, completion_dispatch
from dontpanic_orchestrate import global_config as gc
from dontpanic_orchestrate import sufficiency_auditor as _sa
from dontpanic_orchestrate import worker_profiles as wp
from dontpanic_orchestrate.config.roles import RoleSpec
from dontpanic_orchestrate.config.worker_profiles import (
    CAPABILITY_FLAGS,
    HARNESS_CAPABILITIES,
    WorkerProfile,
    WorkerProfileCapabilities,
    harness_capabilities,
    harness_missing_capabilities_for_role,
    widened_capabilities,
)
from dontpanic_orchestrate.executors import (
    AGENT_REGISTRY,
    get_executor,
    ollama_cli,
    openrouter_api,
)
from dontpanic_orchestrate.executors.base import DispatchTask
from dontpanic_orchestrate.subprocess_runner import SubprocessResult

# The conftest paid-auditor guard replaces
# ``sufficiency_auditor._production_sufficiency_dispatch`` per-test
# (fail-closed against accidental live calls). The i1 raw_response tests
# below exercise the REAL builder offline — ``_post_chat`` is mocked, so
# no network call ever happens — which requires capturing the original
# here at import time, before the autouse guard patches the symbol.
_REAL_SUFFICIENCY_DISPATCH_BUILDER = _sa._production_sufficiency_dispatch


FULL_CAPS = frozenset(CAPABILITY_FLAGS)
AUDIT_ONLY = frozenset({"non_interactive"})


def _task(role: str = "auditor", model: str | None = "llama3.2:latest", **kw) -> DispatchTask:
    from pathlib import Path

    defaults = dict(
        plan_id="p-test",
        plan_dir=Path("/tmp/plan"),
        feature_id="F014",
        feature_description="desc",
        feature_acceptance="acc",
        feature_steps=["step one"],
        agent_role=role,
        model=model,
    )
    defaults.update(kw)
    return DispatchTask(**defaults)


def _proc(stdout: bytes = b"", exit_code: int = 0, timed_out: bool = False) -> SubprocessResult:
    return SubprocessResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=b"",
        timed_out=timed_out,
        timeout_seconds=600,
        grace_period_used=False,
        captured_stdout_bytes=len(stdout),
        captured_stderr_bytes=0,
        worktree_changed=None,
        pgid=0,
    )


# ── 1. registry ids ────────────────────────────────────────────────────────


def test_new_harnesses_registered_under_stable_ids():
    assert "ollama" in AGENT_REGISTRY
    assert "openrouter" in AGENT_REGISTRY
    assert isinstance(get_executor("ollama"), ollama_cli.OllamaCLIExecutor)
    assert isinstance(get_executor("openrouter"), openrouter_api.OpenRouterAPIExecutor)


def test_no_registry_key_is_a_model_version_string():
    # Model ids carry digits, dots, colons or slashes (grok-4.5,
    # llama3.2:latest, openai/gpt-5.2). Harness ids never do (D010).
    for key in AGENT_REGISTRY:
        assert re.fullmatch(r"[a-z][a-z_]*", key), (
            f"registry key {key!r} looks like a model version, not a stable harness id"
        )


# ── 2. capability declarations ─────────────────────────────────────────────


def test_new_harnesses_declare_audit_only_capabilities():
    assert harness_capabilities("ollama") == AUDIT_ONLY
    assert harness_capabilities("openrouter") == AUDIT_ONLY
    # Explicit table entries, not the conservative fall-through default.
    assert "ollama" in HARNESS_CAPABILITIES
    assert "openrouter" in HARNESS_CAPABILITIES


def test_executor_class_declaration_matches_capability_table():
    # Every registered harness declares its flags on the adapter class and
    # the authoritative table agrees — no drift between the two surfaces.
    for name in AGENT_REGISTRY:
        assert get_executor(name).capabilities == harness_capabilities(name), name


def test_coding_harnesses_keep_full_capabilities():
    assert harness_capabilities("claude") == FULL_CAPS
    assert harness_capabilities("codex") == FULL_CAPS


# ── 3. implementer refusal ─────────────────────────────────────────────────


@pytest.mark.parametrize("harness", ["ollama", "openrouter"])
def test_resolve_worker_refuses_implementer_for_audit_only_harness(harness):
    with pytest.raises(wp.HarnessCapabilityRefusedError) as exc:
        wp.resolve_worker(None, "implementer", harness)
    msg = str(exc.value)
    assert "file_edit" in msg and "tool_use" in msg


@pytest.mark.parametrize("harness", ["ollama", "openrouter"])
@pytest.mark.parametrize("role", ["auditor", "goal_auditor"])
def test_resolve_worker_allows_audit_roles_for_audit_only_harness(harness, role):
    resolved = wp.resolve_worker(None, role, harness)
    assert resolved.harness == harness
    assert resolved.profile_id is None
    assert resolved.model is None  # models stay data — no baked-in default


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_resolve_worker_still_allows_implementer_for_coding_harnesses(harness):
    assert wp.resolve_worker(None, "implementer", harness).harness == harness


def test_assert_registrable_refuses_implementer_slot_for_audit_only_harness():
    with pytest.raises(agent_surface.RegisterWorkerError):
        agent_surface.assert_registrable("ollama", role="implementer")
    # Role-less registration and audit slots stay allowed.
    agent_surface.assert_registrable("ollama")
    agent_surface.assert_registrable("ollama", role="auditor")
    agent_surface.assert_registrable("openrouter", role="goal_auditor")


def test_is_dispatchable_name_is_role_aware_for_harnesses():
    assert wp.is_dispatchable_name("ollama", role="auditor")
    assert not wp.is_dispatchable_name("ollama", role="implementer")
    assert wp.is_dispatchable_name("ollama")  # holds at least one role
    assert wp.is_dispatchable_name("claude", role="implementer")


def test_harness_missing_capabilities_for_role_helper():
    assert harness_missing_capabilities_for_role("ollama", "implementer") == [
        "file_edit",
        "tool_use",
    ]
    assert harness_missing_capabilities_for_role("ollama", "auditor") == []
    assert harness_missing_capabilities_for_role("codex", "implementer") == []


def test_profile_cannot_widen_audit_only_harness():
    profile = WorkerProfile(
        harness="ollama",
        capabilities=WorkerProfileCapabilities(file_edit=True, tool_use=True),
    )
    assert widened_capabilities(profile) == ["file_edit", "tool_use"]
    with pytest.raises(wp.ProfileCapabilityRefusedError):
        wp.assert_profile_dispatchable("local-llm", profile)


# ── 4a. ollama adapter (mocked subprocess) ─────────────────────────────────


def test_ollama_dispatch_success_parses_stdout(monkeypatch):
    seen: dict = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _proc(stdout=b"The audit found no drift.\n")

    monkeypatch.setattr(ollama_cli, "run_subprocess", fake_run)
    ex = ollama_cli.OllamaCLIExecutor(binary="ollama")
    result = ex.dispatch(_task(role="auditor", model="llama3.2:latest"))
    assert result.success
    assert result.summary == "The audit found no drift."
    assert result.agent == "ollama"
    # model is data forwarded as argv, never part of the harness identity
    assert "llama3.2:latest" in seen["argv"]
    assert seen["argv"][1] == "run"


def test_ollama_dispatch_requires_model(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("subprocess must not run without a model")

    monkeypatch.setattr(ollama_cli, "run_subprocess", boom)
    result = ollama_cli.OllamaCLIExecutor().dispatch(_task(model=None))
    assert not result.success
    assert "model" in (result.error or "")


def test_ollama_dispatch_refuses_implementer(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("implementer dispatch must be refused before subprocess")

    monkeypatch.setattr(ollama_cli, "run_subprocess", boom)
    result = ollama_cli.OllamaCLIExecutor().dispatch(_task(role="implementer"))
    assert not result.success
    assert "implementer" in (result.error or "")


def test_ollama_dispatch_reports_failure(monkeypatch):
    monkeypatch.setattr(
        ollama_cli, "run_subprocess", lambda *a, **k: _proc(exit_code=1, stdout=b"")
    )
    result = ollama_cli.OllamaCLIExecutor().dispatch(_task())
    assert not result.success
    assert result.error


def test_ollama_availability_is_binary_probe(monkeypatch):
    monkeypatch.setattr(ollama_cli.shutil, "which", lambda _: None)
    assert not ollama_cli.OllamaCLIExecutor().is_available()
    monkeypatch.setattr(ollama_cli.shutil, "which", lambda _: "/usr/local/bin/ollama")
    assert ollama_cli.OllamaCLIExecutor().is_available()


# ── 4b. openrouter adapter (mocked HTTP) ───────────────────────────────────


def test_openrouter_dispatch_success_parses_response(monkeypatch):
    seen: dict = {}

    def fake_post(payload, api_key, timeout):
        seen["payload"] = payload
        seen["api_key"] = api_key
        return {
            "model": "openai/gpt-5.2",
            "choices": [{"message": {"content": "Goal audit: PASS."}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }

    monkeypatch.setattr(openrouter_api, "_post_chat", fake_post)
    monkeypatch.setenv(openrouter_api.API_KEY_ENV, "sk-or-test")
    ex = openrouter_api.OpenRouterAPIExecutor()
    result = ex.dispatch(_task(role="goal_auditor", model="openai/gpt-5.2"))
    assert result.success
    assert result.summary == "Goal audit: PASS."
    assert result.model_version == "openai/gpt-5.2"
    assert result.quota_consumed == {"tokens_in": 11, "tokens_out": 7}
    assert seen["payload"]["model"] == "openai/gpt-5.2"
    assert seen["api_key"] == "sk-or-test"


def test_openrouter_dispatch_requires_model(monkeypatch):
    monkeypatch.setenv(openrouter_api.API_KEY_ENV, "sk-or-test")
    result = openrouter_api.OpenRouterAPIExecutor().dispatch(_task(model=None))
    assert not result.success
    assert "model" in (result.error or "")


def test_openrouter_dispatch_requires_api_key(monkeypatch):
    monkeypatch.delenv(openrouter_api.API_KEY_ENV, raising=False)
    result = openrouter_api.OpenRouterAPIExecutor().dispatch(_task(model="openai/gpt-5.2"))
    assert not result.success
    assert openrouter_api.API_KEY_ENV in (result.error or "")


def test_openrouter_dispatch_refuses_implementer(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("implementer dispatch must be refused before HTTP")

    monkeypatch.setattr(openrouter_api, "_post_chat", boom)
    monkeypatch.setenv(openrouter_api.API_KEY_ENV, "sk-or-test")
    result = openrouter_api.OpenRouterAPIExecutor().dispatch(
        _task(role="implementer", model="openai/gpt-5.2")
    )
    assert not result.success
    assert "implementer" in (result.error or "")


def test_openrouter_dispatch_survives_transport_error(monkeypatch):
    def fail(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(openrouter_api, "_post_chat", fail)
    monkeypatch.setenv(openrouter_api.API_KEY_ENV, "sk-or-test")
    result = openrouter_api.OpenRouterAPIExecutor().dispatch(_task(model="openai/gpt-5.2"))
    assert not result.success
    assert "network down" in (result.error or "")


def test_openrouter_availability_is_env_probe(monkeypatch):
    monkeypatch.delenv(openrouter_api.API_KEY_ENV, raising=False)
    ex = openrouter_api.OpenRouterAPIExecutor()
    assert not ex.is_available()
    assert openrouter_api.API_KEY_ENV in ex.availability_hint()
    monkeypatch.setenv(openrouter_api.API_KEY_ENV, "sk-or-test")
    assert ex.is_available()


# ── 4c. raw_response carries the model's text (i1 — codex audit i0 high) ──
# Completion + sufficiency callers consume ``DispatchResult.raw_response``
# as the auditor's response text (the CLI-harness contract: raw stdout IS
# the model's reply). Placing the vendor JSON envelope there made a valid
# assistant reply of ``[]`` parse as ``dispatch_response_malformed``.


def _openrouter_env(monkeypatch, tmp_path, *, content: str) -> None:
    """Shared harness setup: isolated home, an auditor role bound to
    openrouter (so the goal-audit model resolves for that harness), the
    env-key probe satisfied, and a mocked vendor response."""
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))
    gc.save_config(
        gc.GlobalConfig(
            roles=gc.RolesConfig(auditor=RoleSpec(name="openrouter", model="openai/gpt-5.2"))
        )
    )
    monkeypatch.setenv(openrouter_api.API_KEY_ENV, "sk-or-test")
    monkeypatch.setattr(
        openrouter_api,
        "_post_chat",
        lambda *a, **k: {
            "model": "openai/gpt-5.2",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        },
    )


def test_openrouter_raw_response_is_assistant_content_not_envelope(monkeypatch):
    monkeypatch.setenv(openrouter_api.API_KEY_ENV, "sk-or-test")
    monkeypatch.setattr(
        openrouter_api,
        "_post_chat",
        lambda *a, **k: {"choices": [{"message": {"content": "[]"}}]},
    )
    result = openrouter_api.OpenRouterAPIExecutor().dispatch(
        _task(role="goal_auditor", model="openai/gpt-5.2")
    )
    assert result.success
    assert result.raw_response == "[]"


def test_completion_dispatch_via_openrouter_yields_parseable_auditor_text(monkeypatch, tmp_path):
    _openrouter_env(monkeypatch, tmp_path, content="[]")
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    raw = completion_dispatch._dispatch_via_executor("openrouter", "prompt", plan_dir=plan_dir)
    assert raw == "[]"
    status, _ = completion_dispatch._parse_audit_response(raw, [])
    assert status == "agree"  # NOT dispatch_response_malformed


def test_sufficiency_dispatch_via_openrouter_returns_assistant_content(monkeypatch, tmp_path):
    _openrouter_env(monkeypatch, tmp_path, content='[{"category": "scope"}]')
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    dispatch = _REAL_SUFFICIENCY_DISPATCH_BUILDER(plan_dir)
    assert dispatch("openrouter", "prompt") == '[{"category": "scope"}]'


# ── 5. model catalog keeps its discovery surfaces ──────────────────────────


def test_get_catalog_prefers_discovery_over_registered_executor(monkeypatch):
    # Registering the ollama harness must NOT regress F015's discovery
    # surface to pass-through: the dedicated discovery source still answers.
    from dontpanic_orchestrate import model_catalog as mc

    monkeypatch.setattr(mc.shutil, "which", lambda _: "/usr/local/bin/ollama")

    def fake_run(argv, **kwargs):
        class P:
            returncode = 0
            stdout = "NAME ID SIZE MODIFIED\nllama3.2:latest abc 2GB now\n"
            stderr = ""

        return P()

    monkeypatch.setattr(mc.subprocess, "run", fake_run)
    catalog = mc.get_catalog("ollama")
    assert catalog.source == "ollama_cli"
    assert catalog.models == ("llama3.2:latest",)


# ── 6. doc honesty — stale negative claims (auditor F014-i1 finding 2) ─────
#
# F002's guard is one-way: it catches an UNREGISTERED agent claimed as
# shipped, but not a REGISTERED harness still described as planned or
# operator-only — the exact drift README carried after ollama/openrouter
# landed in the registry. scan_text_stale is the reverse direction, and the
# acceptance case asserts the committed docs against the LIVE registry.

from pathlib import Path as _Path  # noqa: E402

from dontpanic_orchestrate import doc_drift  # noqa: E402

_REPO_ROOT = _Path(__file__).resolve().parents[3]

# The registry as F014 ships it — pinned so fixture tests stay valid if more
# harnesses register later. Only the acceptance case uses the live registry.
F014_REGISTRY = frozenset({"claude", "codex", "ollama", "openrouter"})

# The exact README wording the F014-i1 auditor flagged as stale.
STALE_CHECKLIST = (
    "- [x] Single-agent and volley dispatch (registered executors today: "
    "Claude and Codex — Gemini and Grok are operator-only runtimes, Ollama "
    "support is planned; `dontpanic agent status` is the source of truth)\n"
)
STALE_OLLAMA_BULLET = (
    "- **ollama** — local OSS models for safety and embeddings "
    "(operator-side tooling; not a dispatchable executor)\n"
)
# Pre-fix CONFIGURATION style: registered harnesses still labeled planned.
# (Status disclaimer must not share a claim-word segment — claim wins same
# segment — so this is the shape the reverse guard actually flags.)
STALE_CONFIGURATION_PLANNED = (
    "`openrouter` and `ollama` support is planned; add a gemini_cli later.\n"
)


def test_stale_guard_flags_registered_harness_described_as_planned():
    violations = doc_drift.scan_text_stale(STALE_CHECKLIST, registered=F014_REGISTRY)
    assert [v.agent for v in violations] == ["ollama"]
    assert violations[0].line == 1


def test_stale_guard_flags_sole_harness_bullet_with_unowned_disclaimer():
    violations = doc_drift.scan_text_stale(STALE_OLLAMA_BULLET, registered=F014_REGISTRY)
    assert [v.agent for v in violations] == ["ollama"]


def test_stale_guard_flags_configuration_planned_openrouter_ollama():
    # Auditor F014-i2: CONFIGURATION listed openrouter/ollama under a planned
    # disclaimer with gemini_cli. Reverse scan must catch registered names.
    violations = doc_drift.scan_text_stale(
        STALE_CONFIGURATION_PLANNED, registered=F014_REGISTRY
    )
    assert {v.agent for v in violations} >= {"ollama", "openrouter"}


def test_configuration_md_is_on_doc_allowlist():
    assert "docs/CONFIGURATION.md" in doc_drift.DOC_ALLOWLIST
    # Live file must stay clean under both directions after the F014 rewrite.
    cfg = (_REPO_ROOT / "docs/CONFIGURATION.md").read_text(encoding="utf-8")
    assert doc_drift.scan_text_stale(cfg, path="docs/CONFIGURATION.md") == []
    assert doc_drift.scan_text(cfg, path="docs/CONFIGURATION.md") == []


def test_stale_guard_flags_weakly_conjoined_disclaimer_subject():
    text = "Openrouter and Ollama are operator-only runtimes today.\n"
    violations = doc_drift.scan_text_stale(text, registered=F014_REGISTRY)
    assert [v.agent for v in violations] == ["ollama", "openrouter"]


def test_stale_guard_ignores_disclaimers_about_unregistered_agents():
    text = (
        "`gemini` and `grok` are known operator-only runtimes and cannot be "
        "dispatched as workers.\n"
    )
    assert doc_drift.scan_text_stale(text, registered=F014_REGISTRY) == []


def test_stale_guard_is_registry_driven_not_name_driven():
    # Before F014 registered ollama, "Ollama support is planned" was honest.
    assert doc_drift.scan_text_stale(STALE_CHECKLIST, registered={"claude", "codex"}) == []


def test_stale_guard_accepts_corrected_multi_agent_wording():
    # The corrected phrasings this iteration ships: registered harnesses in
    # claim/neutral segments, disclaimers scoped to unregistered agents. The
    # `gemini_cli` disclaimer must not bleed onto the registered mentions.
    corrected = (
        "Its keys are harnesses (`claude`, `codex`, `openrouter`, `ollama` "
        "today; `gemini_cli` is planned), never model names.\n"
        "\n"
        "- [x] Single-agent and volley dispatch (registered executors today: "
        "Claude and Codex as coding harnesses, plus OpenRouter and Ollama as "
        "audit-only harnesses — Gemini and Grok are operator-only runtimes; "
        "`dontpanic agent status` is the source of truth)\n"
        "\n"
        "- **ollama** — local OSS models as a dispatchable audit-only "
        "harness (needs the `ollama` binary and a pulled model tag)\n"
    )
    assert doc_drift.scan_text_stale(corrected, registered=F014_REGISTRY) == []
    # The same wording stays clean under the FORWARD guard too.
    assert doc_drift.scan_text(corrected, registered=F014_REGISTRY) == []


def test_repo_docs_carry_no_stale_negative_claims_against_live_registry():
    violations = doc_drift.scan_allowlisted_docs_stale(_REPO_ROOT)
    assert violations == [], "\n".join(str(v) for v in violations)
