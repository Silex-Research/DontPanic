"""Plan 2026-05-19-002 F003 — smoke harness fixture tests.

>=8 cases pinning the F003 acceptance contract for
``dontpanic smoke --mode=mocked``:

  (1) ``run_smoke(mode='mocked')`` returns SmokeResult with exit_code=0
      and all NAMED supervisor surfaces present in the result.
  (2) The 8 acceptance-named surfaces are exactly the set the harness
      reports — no extras claimed, no spec drift.
  (3) Wall-clock under 30s on the mocked path (acceptance #2).
  (4) ``--mode=live`` (deferred) is rejected with operator-actionable
      error; the SUPPORTED_MODES tuple still contains only ``mocked``.
  (5) ``SyntheticPlanFixture`` class surface is importable and yields a
      throwaway plan_dir (matches the named class API per acceptance #1).
  (6) ``synthetic_plan_fixture`` function-form context manager still
      works for backward compatibility (cleans up on success AND on
      exception — surface (8) ``tmpdir_cleanup``).
  (7) The mocked path requires NO real claude/codex CLI on the host —
      ``MockClaudeExecutor`` / ``MockCodexExecutor`` are ``is_available()
      -> True`` regardless of ``shutil.which``. (no-real-CLI invariant)
  (8) Smoke JSON envelope schema is stable: ``schema_version='1.0.0'``,
      ``mode='mocked'``, ``plan_id``, ``elapsed_s``, ``exit_code``,
      ``supervisor_surfaces`` array. (Snapshot pin.)

Run:
    pytest scripts/dontpanic_orchestrate/tests/test_smoke_harness_f003.py -q
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from dontpanic_orchestrate import smoke as smoke_mod
from dontpanic_orchestrate.smoke import (
    DEFERRED_MODES,
    EXIT_PASS,
    SUPPORTED_MODES,
    SURFACE_NAMES,
    SYNTHETIC_PLAN_ID,
    MockClaudeExecutor,
    MockCodexExecutor,
    SmokeResult,
    SyntheticPlanFixture,
    run_smoke,
    smoke_main,
    synthetic_plan_fixture,
)


# ── (1) basic happy path: run_smoke returns exit=0 + all surfaces ────────


def test_run_smoke_mocked_returns_exit_zero_with_all_named_surfaces() -> None:
    """The mocked smoke run completes cleanly and reports every NAMED
    supervisor surface (acceptance #1 + #4)."""
    result = run_smoke(mode="mocked")
    assert isinstance(result, SmokeResult)
    assert result.exit_code == EXIT_PASS, (
        f"mocked smoke must exit 0 on a writable tmpdir host; got "
        f"{result.exit_code} with surfaces={[s.name for s in result.surfaces]}"
    )
    reported = {s.name for s in result.surfaces}
    # Every acceptance-named surface must be present in the result.
    for name in SURFACE_NAMES:
        assert name in reported, f"missing named surface: {name}"


# ── (2) named-surface set is exactly the bounded set (no drift) ──────────


def test_named_surfaces_exactly_match_acceptance_set() -> None:
    """The acceptance signal explicitly bounds the surface set. Drift
    in either direction (added surface not in spec, OR missing surface
    from spec) is a contract break."""
    expected = {
        "plan_load",
        "gate_evaluation",
        "mocked_claude_envelope_write",
        "audit_persist",
        "mocked_codex_envelope_write",
        "signoff_envelope_write",
        "inbox_append",
        "tmpdir_cleanup",
    }
    assert set(SURFACE_NAMES) == expected, (
        f"SURFACE_NAMES drifted from acceptance set: "
        f"extra={set(SURFACE_NAMES) - expected}, missing={expected - set(SURFACE_NAMES)}"
    )


# ── (3) wall-clock budget under 30s ───────────────────────────────────────


def test_mocked_smoke_under_thirty_second_budget() -> None:
    """Acceptance #2 caps mocked-mode wall clock at 30s. The bounded
    surface set + mocked executors should run well under this; this
    test is a regression guard against accidental costly work."""
    started = time.monotonic()
    result = run_smoke(mode="mocked")
    elapsed = time.monotonic() - started
    assert elapsed <= 30.0, (
        f"mocked smoke exceeded 30s budget: {elapsed:.2f}s "
        f"(elapsed_s={result.elapsed_s:.2f})"
    )


# ── (4) --mode=live (deferred) is rejected ────────────────────────────────


def test_mode_live_is_explicitly_deferred(capsys) -> None:
    """``--mode=live`` is deferred per acceptance #7. The CLI must reject
    it with an operator-actionable message — not silently fall through
    to mocked semantics."""
    assert "live" in DEFERRED_MODES
    assert "live" not in SUPPORTED_MODES
    # smoke_main accepts --mode=live in argparse so it can emit an
    # operator-actionable error rather than argparse's generic "invalid
    # choice" — but the run still terminates with EXIT_ENV_BLOCKER (2)
    # rather than EXIT_PASS (0). See SmokeEnvBlockerError catch in
    # smoke_main.
    from dontpanic_orchestrate.smoke import EXIT_ENV_BLOCKER
    exit_code = smoke_main(["--mode=live"])
    assert exit_code == EXIT_ENV_BLOCKER, (
        f"--mode=live must terminate with env_blocker exit code (2); got {exit_code}"
    )


# ── (5) SyntheticPlanFixture class surface ───────────────────────────────


def test_synthetic_plan_fixture_class_yields_plan_dir(tmp_path: Path) -> None:
    """Acceptance #1 names ``SyntheticPlanFixture`` as a class. The
    context-manager class form must yield the same plan_dir shape as
    the function-form helper."""
    fixture = SyntheticPlanFixture(parent=tmp_path)
    with fixture as plan_dir:
        assert plan_dir.exists()
        assert (plan_dir / "plan.md").exists()
        assert (plan_dir / "features.json").exists()
        # Plan id last segment is what synthetic_plan_fixture wrote.
        assert plan_dir.name == SYNTHETIC_PLAN_ID
    # Cleanup ran on context exit.
    assert not plan_dir.exists()


# ── (6) function-form fixture cleans up on success AND exception ─────────


def test_synthetic_plan_fixture_function_cleans_up_on_exception(tmp_path: Path) -> None:
    """Surface (8) ``tmpdir_cleanup`` requires cleanup on BOTH success
    AND exception paths. Function-form helper must honor this contract."""
    captured: dict[str, Path] = {}

    with pytest.raises(RuntimeError, match="synthetic boom"):
        with synthetic_plan_fixture(parent=tmp_path) as plan_dir:
            captured["plan_dir"] = plan_dir
            assert plan_dir.exists()
            raise RuntimeError("synthetic boom")

    # Even though the body raised, the tmpdir was removed.
    assert not captured["plan_dir"].exists()


# ── (7) no-real-CLI invariant — Mock*Executor.is_available always True ───


def test_mock_executors_are_available_without_real_clis(monkeypatch) -> None:
    """Acceptance #2 ("NO real CLI required") relies on the mock
    executors not consulting ``shutil.which`` for their availability
    answer. We monkeypatch ``shutil.which`` to a sentinel that returns
    None for EVERY name and assert the mocks still report available."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    claude = MockClaudeExecutor()
    codex = MockCodexExecutor()
    assert claude.is_available() is True, (
        "MockClaudeExecutor must not consult real CLI presence"
    )
    assert codex.is_available() is True, (
        "MockCodexExecutor must not consult real CLI presence"
    )


# ── (8) JSON envelope schema is stable ────────────────────────────────────


def test_smoke_result_json_envelope_schema_is_stable() -> None:
    """Acceptance #4: JSON output covers the NAMED supervisor surfaces.
    Pin the top-level shape so consumers (init --json embed, agent
    installers) can branch deterministically."""
    result = run_smoke(mode="mocked")
    payload = json.loads(result.to_json())
    # Top-level keys MUST be present.
    for key in (
        "schema_version",
        "mode",
        "plan_id",
        "elapsed_s",
        "exit_code",
        "supervisor_surfaces",
    ):
        assert key in payload, f"smoke JSON missing required top-level key: {key}"
    assert payload["schema_version"] == "1.0.0"
    assert payload["mode"] == "mocked"
    assert payload["plan_id"] == SYNTHETIC_PLAN_ID
    assert isinstance(payload["supervisor_surfaces"], list)
    # Every surface entry has the documented field set.
    for surface in payload["supervisor_surfaces"]:
        for field in ("name", "status", "elapsed_s"):
            assert field in surface, f"surface row missing field: {field}"
