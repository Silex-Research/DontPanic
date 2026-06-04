"""Plan 2026-05-30-001 F001 — single generated operating brief.

Acceptance covered:

1. ``agent_brief`` renders deterministic text from live manifest + executor
   registry data.
2. Brief contains the operator-vs-worker distinction.
3. Brief warns DontPanic is local CLI workflow orchestration, not
   Kubernetes/Airflow/IT orchestration.
4. Brief lists current supported commands sourced from ``agent_manifest``.
5. Brief lists current worker executors from ``AGENT_REGISTRY`` and includes no
   unsupported labels in the executor list.
6. Brief exposes a generator version and a content hash.
7. Tests mutate fake command/executor inputs and prove the rendered brief
   tracks source data rather than hand-edited strings.

All tests redirect ``$DONTPANIC_HOME`` to ``tmp_path`` so the operator's real
home is never read or written.

Run: PYTHONPATH=scripts pytest \
  scripts/dontpanic_orchestrate/tests/test_f001_agent_brief.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import agent_brief as ab  # noqa: E402
from dontpanic_orchestrate import executors  # noqa: E402
from dontpanic_orchestrate import global_config as gc  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_dontpanic_home(tmp_path, monkeypatch):
    """Reroute ``$DONTPANIC_HOME`` to a tmp dir so the operator's real
    ``~/.dontpanic`` is never touched. Unset ``$JARVIS_HOME`` so home
    resolution is deterministic per test."""
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))


def _inputs(**overrides):
    base = {
        "dontpanic_version": "9.9.9",
        "supported_commands": ["projects", "doctor", "manifest"],
        "worker_executors": ["claude", "codex"],
        "config_home": "/tmp/home/.dontpanic",
        "using_legacy_home": False,
        "legacy_home_present": False,
    }
    base.update(overrides)
    return ab.BriefInputs(**base)


# ──────────────────────────────  acceptance (1): determinism  ──────────────────────────────


def test_render_is_deterministic_for_same_inputs():
    inputs = _inputs()
    a = ab.render_brief(inputs)
    b = ab.render_brief(inputs)
    assert a.text == b.text
    assert a.content_hash == b.content_hash


def test_generate_brief_from_live_facts_renders():
    brief = ab.generate_brief()
    assert brief.text
    # version + executor names come from live source-of-truth modules.
    from dontpanic_orchestrate import __version__ as live_version

    assert live_version in brief.text
    for name in executors.AGENT_REGISTRY:
        assert name in brief.text


# ──────────────────────────────  acceptance (2): operator vs worker  ──────────────────────────────


def test_brief_contains_operator_vs_worker_distinction():
    text = ab.render_brief(_inputs()).text
    assert "Operator" in text
    assert "Worker executor" in text
    # The distinction is explicit: operate by running commands vs dispatched
    # only when listed as a worker.
    assert "operator-only" in text


# ──────────────────────────────  acceptance (3): not Kubernetes/Airflow/IT  ──────────────────────────────


def test_brief_warns_not_kubernetes_airflow_or_it_orchestration():
    text = ab.render_brief(_inputs()).text
    assert "not Kubernetes, Airflow, or IT" in text
    assert "Kubernetes" in text
    assert "Airflow" in text
    # canonical clarification string is present verbatim.
    assert ab.NOT_IT_ORCHESTRATION in text


def test_brief_includes_canonical_workflow():
    text = ab.render_brief(_inputs()).text
    assert ab.CANONICAL_WORKFLOW in text
    # F001 AC requires the literal CLI verbs, not prose labels (codex audit i0).
    assert "projects add" in text
    assert "plan lock" in text
    assert "approve/resume/close" in text
    assert "orchestrate/dispatch-from-plan" in text


# ──────────────────────────────  acceptance (4): commands track manifest  ──────────────────────────────


def test_supported_commands_sourced_from_manifest():
    from dontpanic_orchestrate import agent_manifest as am

    inputs = ab.collect_brief_inputs()
    assert inputs.supported_commands == am.bootstrap_manifest().supported_commands


def test_fake_command_changes_propagate_to_brief():
    """Acceptance (7): mutate command inputs and prove the brief tracks them."""
    base = ab.render_brief(_inputs(supported_commands=["projects", "doctor"]))
    mutated = ab.render_brief(
        _inputs(supported_commands=["projects", "doctor", "orchestrate", "agent"])
    )
    # Scope to the SUPPORTED COMMANDS list — "orchestrate" also appears in the
    # canonical workflow line, so a bare substring check would be ambiguous.
    assert "  - orchestrate" not in base.text
    assert "  - orchestrate" in mutated.text
    assert "  - agent" in mutated.text
    assert base.content_hash != mutated.content_hash


# ──────────────────────────────  acceptance (5): executors from registry  ──────────────────────────────


def test_worker_executors_sourced_from_registry():
    inputs = ab.collect_brief_inputs()
    assert inputs.worker_executors == sorted(executors.AGENT_REGISTRY)


def test_unsupported_labels_not_in_executor_list():
    """Grok/Gemini are named only in the operate-only paragraph, never in the
    WORKER EXECUTORS list."""
    text = ab.render_brief(_inputs(worker_executors=["claude", "codex"])).text
    worker_section = text.split("WORKER EXECUTORS", 1)[1].split("CANONICAL", 1)[0]
    assert "Grok" not in worker_section
    assert "Gemini" not in worker_section
    assert "  - claude" in worker_section
    assert "  - codex" in worker_section


def test_fake_executor_changes_propagate_to_brief():
    """Acceptance (7): mutate executor inputs and prove the brief tracks them."""
    base = ab.render_brief(_inputs(worker_executors=["claude", "codex"]))
    mutated = ab.render_brief(
        _inputs(worker_executors=["claude", "codex", "gemini-builder"])
    )
    assert "gemini-builder" not in base.text
    assert "gemini-builder" in mutated.text
    assert base.content_hash != mutated.content_hash


# ──────────────────────────────  acceptance (6): version + hash  ──────────────────────────────


def test_brief_exposes_generator_version_and_content_hash():
    brief = ab.render_brief(_inputs())
    assert brief.generator_version == ab.GENERATOR_VERSION
    assert len(brief.content_hash) == 64  # sha256 hex digest
    assert int(brief.content_hash, 16) >= 0  # valid hex
    # version is also surfaced in the rendered text for downstream blocks.
    assert ab.GENERATOR_VERSION in brief.text


def test_content_hash_changes_when_text_changes():
    a = ab.render_brief(_inputs(dontpanic_version="1.0.0"))
    b = ab.render_brief(_inputs(dontpanic_version="2.0.0"))
    assert a.text != b.text
    assert a.content_hash != b.content_hash


# ──────────────────────────────  config-home status  ──────────────────────────────


def test_config_home_status_rendered():
    plain = ab.render_brief(_inputs()).text
    assert "/tmp/home/.dontpanic" in plain

    legacy = ab.render_brief(_inputs(using_legacy_home=True)).text
    assert "legacy ~/.jarvis home in use" in legacy

    coexist = ab.render_brief(_inputs(legacy_home_present=True)).text
    assert "split-brain" in coexist
