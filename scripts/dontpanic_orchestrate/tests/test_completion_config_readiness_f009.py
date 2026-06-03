"""F009 plan-close-wiring gap (D015/D016).

F009 acceptance #1 names the plan-close goal-completion audit — not just
dispatch-from-plan — as a config-readiness pre-flight site. These tests prove
the readiness check is wired into ``completion_dispatch`` BEFORE the real paid
executor call: a malformed `{}` caps file (D039) or an invalid role (D065)
raises a clean ``ConfigNotReady`` with a runnable remediation, and a valid
config lets the audit proceed to dispatch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import completion_dispatch, quota_caps_loader


def _write(p: Path, obj) -> Path:
    p.write_text(json.dumps(obj))
    return p


def _valid_caps(tmp_path: Path) -> Path:
    return _write(tmp_path / "quota_caps.json", quota_caps_loader.starter_caps())


# ─────────────────────── the readiness helper (the wired logic) ─────────────


def test_helper_raises_config_not_ready_on_empty_caps(tmp_path):
    caps = _write(tmp_path / "quota_caps.json", {})  # the D039 `{}` hard-stop
    with pytest.raises(completion_dispatch.ConfigNotReady) as exc:
        completion_dispatch._assert_config_ready_for_completion(
            implementer_agent="claude", auditor="codex", caps_path=caps
        )
    msg = str(exc.value)
    assert str(caps) in msg
    assert "quota-caps init" in msg  # runnable remediation


def test_helper_raises_config_not_ready_on_invalid_role(tmp_path):
    caps = _valid_caps(tmp_path)
    # D065 split-brain: a capitalised/spaced role is not a registered executor id.
    with pytest.raises(completion_dispatch.ConfigNotReady) as exc:
        completion_dispatch._assert_config_ready_for_completion(
            implementer_agent="Grok-Builder", auditor="Codex-Auditor", caps_path=caps
        )
    assert "Grok-Builder" in str(exc.value)


def test_helper_passes_on_valid_caps_and_roles(tmp_path):
    caps = _valid_caps(tmp_path)
    # codex/claude are registered executors; valid caps -> no raise.
    completion_dispatch._assert_config_ready_for_completion(
        implementer_agent="claude", auditor="codex", caps_path=caps
    )


# ─────────────────────── integration: gate fires before paid work ──────────


def test_completion_audit_blocks_before_executor_on_bad_caps(tmp_path, monkeypatch):
    """dispatch=None is the real paid path; the readiness gate must raise
    ConfigNotReady BEFORE _dispatch_via_executor is ever reached."""
    caps = _write(tmp_path / "quota_caps.json", {})  # empty -> not ready
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()

    # Resolve a clean auditor + stub the prompt-build inputs so we reach the
    # dispatch branch without a full plan on disk.
    monkeypatch.setattr(
        completion_dispatch,
        "_resolve_auditor_or_translate_same_vendor",
        lambda plan_dir, impl: "codex",
    )
    monkeypatch.setattr(completion_dispatch, "_validate_auditor_name", lambda a: None)
    monkeypatch.setattr(completion_dispatch, "_load_objective_contract", lambda d: {})
    monkeypatch.setattr(completion_dispatch, "_load_features", lambda d: [])
    monkeypatch.setattr(completion_dispatch, "_build_evidence_manifest", lambda d: {})
    monkeypatch.setattr(
        completion_dispatch, "_build_audit_prompt", lambda *a, **k: "prompt"
    )

    def _must_not_run(*args, **kwargs):
        raise AssertionError("paid executor reached despite unready config")

    monkeypatch.setattr(completion_dispatch, "_dispatch_via_executor", _must_not_run)

    with pytest.raises(completion_dispatch.ConfigNotReady):
        completion_dispatch.dispatch_completion_audit(
            plan_dir,
            findings=[],
            implementer_agent="claude",
            dispatch=None,
            caps_path=caps,
        )


def test_completion_audit_bad_role_raises_config_not_ready_before_name_check(
    tmp_path, monkeypatch
):
    """codex F009 audit i0: a bad ROLE at plan-close must surface the actionable
    ConfigNotReady BEFORE the lower-level auditor-name validation and before the
    paid executor. Driven through dispatch_completion_audit with valid caps so
    only the role check fails."""
    caps = _valid_caps(tmp_path)
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()

    # Resolve a structurally-bad auditor (the D065 split-brain shape).
    monkeypatch.setattr(
        completion_dispatch,
        "_resolve_auditor_or_translate_same_vendor",
        lambda plan_dir, impl: "Codex-Auditor",
    )

    def _name_check_must_not_run(_a):
        raise AssertionError("auditor-name validation ran before readiness gate")

    monkeypatch.setattr(completion_dispatch, "_validate_auditor_name", _name_check_must_not_run)

    def _executor_must_not_run(*a, **k):
        raise AssertionError("paid executor reached despite invalid role")

    monkeypatch.setattr(completion_dispatch, "_dispatch_via_executor", _executor_must_not_run)

    with pytest.raises(completion_dispatch.ConfigNotReady) as exc:
        completion_dispatch.dispatch_completion_audit(
            plan_dir,
            findings=[],
            implementer_agent="claude",
            dispatch=None,
            caps_path=caps,
        )
    assert "Codex-Auditor" in str(exc.value)


def test_completion_audit_proceeds_when_config_ready(tmp_path, monkeypatch):
    """A valid caps file + valid roles lets the audit reach the executor (the
    readiness gate did not raise)."""
    caps = _valid_caps(tmp_path)
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()

    monkeypatch.setattr(
        completion_dispatch,
        "_resolve_auditor_or_translate_same_vendor",
        lambda plan_dir, impl: "codex",
    )
    monkeypatch.setattr(completion_dispatch, "_validate_auditor_name", lambda a: None)
    monkeypatch.setattr(completion_dispatch, "_load_objective_contract", lambda d: {})
    monkeypatch.setattr(completion_dispatch, "_load_features", lambda d: [])
    monkeypatch.setattr(completion_dispatch, "_build_evidence_manifest", lambda d: {})
    monkeypatch.setattr(
        completion_dispatch, "_build_audit_prompt", lambda *a, **k: "prompt"
    )

    reached = {"executor": False}

    def _fake_dispatch(auditor, prompt, *, plan_dir):
        reached["executor"] = True
        return json.dumps({"status": "pass", "dispositions": []})

    monkeypatch.setattr(completion_dispatch, "_dispatch_via_executor", _fake_dispatch)
    monkeypatch.setattr(
        completion_dispatch, "_parse_audit_response", lambda raw, findings: ("agree", [])
    )
    monkeypatch.setattr(completion_dispatch, "_write_envelope", lambda *a, **k: None)

    completion_dispatch.dispatch_completion_audit(
        plan_dir,
        findings=[],
        implementer_agent="claude",
        dispatch=None,
        caps_path=caps,
    )
    assert reached["executor"] is True
