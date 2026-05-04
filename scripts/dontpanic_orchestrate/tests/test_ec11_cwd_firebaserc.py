"""F023 EC11 — cwd discipline + .firebaserc invariant + prompt --project rule.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_ec11_cwd_firebaserc.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import prompts  # noqa: E402
from dontpanic_orchestrate.environments_loader import (  # noqa: E402
    EnvironmentsTargetMismatchError,
    EnvironmentsValidationError,
    check_firebaserc_consistency,
)
from dontpanic_orchestrate.executors.base import DispatchTask  # noqa: E402


def _glam_payload() -> dict:
    return {
        "repo": "Glam",
        "dev": {"firebase_project": "<glam-dev-firebase-project-id>", "gcp_project": "<glam-dev-firebase-project-id>"},
        "prod": {"firebase_project": "<glam-firebase-project-id>", "gcp_project": "<glam-firebase-project-id>"},
    }


def _firebaserc(repo: Path, projects: dict) -> Path:
    fr = repo / ".firebaserc"
    fr.write_text(json.dumps({"projects": projects}, indent=2) + "\n")
    return fr


# ──────────────────────────────  DispatchTask cwd field  ──────────────────────────────


def test_dispatch_task_carries_cwd() -> None:
    print("\n[test] dispatch_task_carries_cwd ...")
    t = DispatchTask(
        plan_id="p",
        plan_dir=Path("/tmp/p"),
        feature_id="F001",
        feature_description="d",
        feature_acceptance="a",
        feature_steps=[],
        agent_role="implementer",
        cwd=Path("/tmp/repo"),
    )
    assert t.cwd == Path("/tmp/repo"), t.cwd
    # Default is None
    t2 = DispatchTask(
        plan_id="p",
        plan_dir=Path("/tmp/p"),
        feature_id="F001",
        feature_description="d",
        feature_acceptance="a",
        feature_steps=[],
        agent_role="implementer",
    )
    assert t2.cwd is None
    print("  ✓ DispatchTask.cwd carries Path or None")


# ──────────────────────────────  firebaserc invariant  ──────────────────────────────


def test_firebaserc_skip_when_absent() -> None:
    print("\n[test] firebaserc_skip_when_absent ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        result = check_firebaserc_consistency(repo, "any-proj")
        assert result is None
    print("  ✓ no .firebaserc → skip silently")


def test_firebaserc_happy_path() -> None:
    print("\n[test] firebaserc_happy_path ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _firebaserc(repo, {"default": "<glam-dev-firebase-project-id>", "prod": "<glam-firebase-project-id>"})
        assert "<glam-dev-firebase-project-id>" in (check_firebaserc_consistency(repo, "<glam-dev-firebase-project-id>") or "")
        assert "<glam-firebase-project-id>" in (check_firebaserc_consistency(repo, "<glam-firebase-project-id>") or "")
    print("  ✓ project ID present as alias value → success")


def test_firebaserc_mismatch_raises() -> None:
    print("\n[test] firebaserc_mismatch_raises ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _firebaserc(repo, {"default": "<glam-dev-firebase-project-id>", "prod": "<glam-firebase-project-id>"})
        try:
            check_firebaserc_consistency(repo, "wrong-project")
        except EnvironmentsTargetMismatchError as exc:
            assert "wrong-project" in str(exc) and ".firebaserc" in str(exc)
            print("  ✓ project not in .firebaserc → EnvironmentsTargetMismatchError")
            return
    raise AssertionError("expected EnvironmentsTargetMismatchError")


def test_firebaserc_malformed_raises() -> None:
    print("\n[test] firebaserc_malformed_raises ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".firebaserc").write_text("{not json")
        try:
            check_firebaserc_consistency(repo, "x")
        except EnvironmentsValidationError as exc:
            assert "malformed JSON" in str(exc)
            print("  ✓ malformed .firebaserc → EnvironmentsValidationError")
            return
    raise AssertionError("expected EnvironmentsValidationError")


def test_firebaserc_empty_projects_skip() -> None:
    print("\n[test] firebaserc_empty_projects_skip ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".firebaserc").write_text(json.dumps({"projects": {}}))
        assert check_firebaserc_consistency(repo, "x") is None
    print("  ✓ empty projects block → skip silently")


# ──────────────────────────────  prompt rule wiring  ──────────────────────────────


def test_prompt_target_block_has_required_flag_section() -> None:
    print("\n[test] prompt_target_block_has_required_flag_section ...")
    out = prompts.implementer_prompt(
        plan_id="2026-04-26-200-infra-cwd-prompt",
        plan_dir=Path("/tmp/p"),
        feature={"id": "F001", "description": "d", "acceptance": "a", "steps": []},
        iteration=0,
        target_env="dev",
        target_project="<firebase-project-id>",
    )
    assert "Required-flag command shapes" in out, out[:500]
    assert "firebase deploy" in out and "--project" in out
    assert "xcodebuild" in out and "-scheme" in out
    print("  ✓ implementer prompt embeds REQUIRED_FLAG_PATTERNS section")


def test_prompt_required_flag_patterns_module_export() -> None:
    print("\n[test] prompt_required_flag_patterns_module_export ...")
    assert hasattr(prompts, "REQUIRED_FLAG_PATTERNS")
    assert any("firebase deploy" in p for p in prompts.REQUIRED_FLAG_PATTERNS)
    assert any("xcodebuild" in p for p in prompts.REQUIRED_FLAG_PATTERNS)
    print("  ✓ REQUIRED_FLAG_PATTERNS module-level list exported")
