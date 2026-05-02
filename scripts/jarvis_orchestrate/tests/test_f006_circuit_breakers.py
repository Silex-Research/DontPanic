"""F006 — 7 loop termination triggers.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_f006_circuit_breakers.py
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import (  # noqa: E402
    circuit_breakers as cb,
)
from jarvis_orchestrate import (  # noqa: E402
    gate_pause,
    inbox,
    notify,
    supervisor,
)
from jarvis_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from jarvis_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ──────────────────────────────  pure-function checks  ──────────────────────────────


def test_check_wall_clock() -> None:
    print("\n[test] check_wall_clock ...")
    long_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    tripped, reason = cb.check_wall_clock(long_ago, max_hours=1.0)
    assert tripped and "exceeds wall_clock_hours" in reason
    just_now = dt.datetime.now(dt.timezone.utc)
    assert not cb.check_wall_clock(just_now, max_hours=1.0)[0]
    print("  ✓ wall_clock fires when elapsed > max, passes when fresh")


def test_check_budget_ceiling_reads_quota_state_file() -> None:
    """F006 fix#1: budget_ceiling now reads the F020-populated
    ~/.jarvis/quota_state.json, not a phantom field on audit JSONs."""
    print("\n[test] check_budget_ceiling_reads_quota_state_file ...")
    with tempfile.TemporaryDirectory() as td:
        ad = Path(td) / "audits"
        ad.mkdir()
        # Real-shape audit (no percent_weekly — the bug the fix closes).
        (ad / "claude-implementer-i0.json").write_text(
            json.dumps(
                {
                    "task_id": "t",
                    "audit_id": "t#claude#0",
                    "agent": "claude",
                    "agent_role": "implementer",
                    "iteration": 0,
                    "started_at": _iso_now(),
                    "completed_at": _iso_now(),
                    "audit_status": "needs_changes",
                    "quota_consumed": {"tokens_in": 100, "tokens_out": 50, "api_calls": 1},
                }
            )
        )
        # quota_state.json supplied via the new explicit kwarg
        qs = Path(td) / "quota_state.json"
        qs.write_text(json.dumps({"models": {"claude": {"percent_weekly": 80.0, "plan": "x"}}}))
        # No caps → no trip
        result = cb.check_budget_ceiling(sorted(ad.glob("*.json")), None, quota_state_path=qs)
        assert not result.tripped
        assert result.fallback_used  # legacy state shape (no vendors{})
        # Cap=50 → trip (state says 80%)
        result = cb.check_budget_ceiling(
            sorted(ad.glob("*.json")),
            {"claude": 50.0},
            quota_state_path=qs,
        )
        assert result.tripped, result.reason
        assert result.kind == cb.BudgetCeilingKind.TRIPPED
        assert result.fallback_used
        assert "claude" in result.reason and "80" in result.reason
        # Cap=90 → no trip
        result = cb.check_budget_ceiling(
            sorted(ad.glob("*.json")),
            {"claude": 90.0},
            quota_state_path=qs,
        )
        assert not result.tripped
        # Agent absent from this volley's audits → no trip even at over-cap state
        empty = Path(td) / "empty"
        empty.mkdir()
        result = cb.check_budget_ceiling(
            sorted(empty.glob("*.json")),
            {"claude": 50.0},
            quota_state_path=qs,
        )
        assert not result.tripped
    print(
        "  ✓ legacy fallback: budget_ceiling reads models{}.percent_weekly + scoped to participating agents"
    )


# ──────────────────────  F006a budget_ceiling v2-path tests  ──────────────────────
#
# Each scenario builds a v2-shape quota_state.json (vendors{} block present)
# in the env-isolated path and a matching/missing/wrong caps file. Exercises
# the five non-OK BudgetCeilingKind values + the legacy-fallback boundary.


def _write_v2_state(
    qs: Path, *, claude_7d_observed: float, codex_5h_observed: int, claude_calibration: dict | None
) -> None:
    """Build a minimal v2 vendors{} state file the breaker can read."""
    state = {
        "schema_version": 2,
        "generated": _iso_now(),
        "vendors": {
            "claude": {
                "tier": "max_20x",
                "windows": {
                    "rolling_7d": {
                        "kind": "rolling_7d",
                        "observed_native": claude_7d_observed,
                        "observed_unit": "weighted_tokens_local_proxy",
                        "calibration": claude_calibration
                        or {
                            "ratio": None,
                            "confidence": "uncalibrated",
                            "source": None,
                            "stamped_at": None,
                        },
                    },
                },
            },
            "codex": {
                "tier": "plus",
                "windows": {
                    "rolling_5h": {
                        "kind": "rolling_5h",
                        "observed_native": codex_5h_observed,
                        "observed_unit": "tokens_local_proxy",
                    },
                },
            },
        },
        "models": {  # legacy mirror, ignored by v2 path
            "claude": {"used": 0, "limit": None, "percent_weekly": None, "plan": "x"},
            "codex": {"used": 0, "limit": None, "percent_weekly": None, "plan": "x"},
        },
    }
    qs.write_text(json.dumps(state))


def _write_audit(ad: Path, agent: str = "claude") -> Path:
    p = ad / f"{agent}-implementer-i0.json"
    p.write_text(
        json.dumps(
            {
                "task_id": "t",
                "audit_id": f"t#{agent}#0",
                "agent": agent,
                "agent_role": "implementer",
                "iteration": 0,
                "started_at": _iso_now(),
                "completed_at": _iso_now(),
                "audit_status": "needs_changes",
                "quota_consumed": {"tokens_in": 100, "tokens_out": 50, "api_calls": 1},
            }
        )
    )
    return p


def test_v2_config_required_when_caps_file_missing(tmp_path: Path) -> None:
    """F006a refinement #1: missing operator caps file is a first-class
    config_required pause, not a silent quiet-skip."""
    print("\n[test] v2_config_required_when_caps_file_missing ...")
    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    _write_v2_state(
        qs, claude_7d_observed=500_000_000, codex_5h_observed=200_000_000, claude_calibration=None
    )
    ad = tmp_path / "audits"
    ad.mkdir()
    _write_audit(ad, "claude")

    # No caps file written → JARVIS_QUOTA_CAPS_PATH points at a non-existent file
    result = cb.check_budget_ceiling(sorted(ad.glob("*.json")), None)
    assert result.tripped
    assert result.kind == cb.BudgetCeilingKind.CONFIG_REQUIRED
    assert "caps file" in result.reason.lower() or "not found" in result.reason.lower()
    assert "quota-caps init" in result.reason
    print("  ✓ missing caps file → CONFIG_REQUIRED with init guidance")


def test_v2_calibration_required_for_uncalibrated_claude(tmp_path: Path) -> None:
    """F006a refinement #3: percent_of_plan cap + uncalibrated calibration
    halts with calibration_required, NOT a silent skip and NOT a false-trip
    against weighted_tokens / 100."""
    print("\n[test] v2_calibration_required_for_uncalibrated_claude ...")
    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    _write_v2_state(
        qs, claude_7d_observed=500_000_000, codex_5h_observed=0, claude_calibration=None
    )
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "defaults": {"claude_tier": "max_20x"},
                "claude": {
                    "max_20x": {
                        "rolling_7d": {"cap": 100, "unit": "percent_of_plan"},
                    }
                },
            }
        )
    )
    ad = tmp_path / "audits"
    ad.mkdir()
    _write_audit(ad, "claude")

    result = cb.check_budget_ceiling(sorted(ad.glob("*.json")), None)
    assert result.tripped
    assert result.kind == cb.BudgetCeilingKind.CALIBRATION_REQUIRED
    assert result.agent == "claude"
    assert result.window == "rolling_7d"
    assert result.confidence == "uncalibrated"
    assert "calibrate-claude" in result.reason
    assert "percent_of_plan" in result.reason
    print("  ✓ uncalibrated Claude with percent_of_plan cap → CALIBRATION_REQUIRED")


def test_v2_calibrated_claude_trips_on_excess(tmp_path: Path) -> None:
    """Sanity: with valid manual calibration, the breaker correctly trips when
    the calibrated effective value exceeds the cap."""
    print("\n[test] v2_calibrated_claude_trips_on_excess ...")
    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    # ratio chosen so observed * ratio = 110 > cap 100
    _write_v2_state(
        qs,
        claude_7d_observed=550_000_000,
        codex_5h_observed=0,
        claude_calibration={
            "ratio": 2.0e-7,  # 550M * 2e-7 = 110
            "confidence": "manual",
            "source": "operator_dashboard_sample",
            "stamped_at": _iso_now(),
        },
    )
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "defaults": {"claude_tier": "max_20x"},
                "claude": {
                    "max_20x": {
                        "rolling_7d": {"cap": 100, "unit": "percent_of_plan"},
                    }
                },
            }
        )
    )
    ad = tmp_path / "audits"
    ad.mkdir()
    _write_audit(ad, "claude")

    result = cb.check_budget_ceiling(sorted(ad.glob("*.json")), None)
    assert result.tripped
    assert result.kind == cb.BudgetCeilingKind.TRIPPED
    assert result.agent == "claude"
    assert result.window == "rolling_7d"
    assert result.confidence == "manual"
    assert result.cap == 100
    assert result.cap_unit == "percent_of_plan"
    assert "110" in result.reason
    print("  ✓ calibrated Claude trips at observed * ratio > cap")


def test_v2_unit_mismatch_halts_for_non_claude(tmp_path: Path) -> None:
    """F006a refinement #3: cap.unit != observed_unit on a non-Claude vendor
    is a hard configuration signal, not a quiet skip. Operator must fix
    quota_caps.json."""
    print("\n[test] v2_unit_mismatch_halts_for_non_claude ...")
    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    _write_v2_state(
        qs, claude_7d_observed=0, codex_5h_observed=200_000_000, claude_calibration=None
    )
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "defaults": {"claude_tier": "max_20x"},
                "codex": {
                    "plus": {
                        "rolling_5h": {"cap": 100, "unit": "requests"},  # WRONG: observed is tokens
                    }
                },
            }
        )
    )
    ad = tmp_path / "audits"
    ad.mkdir()
    _write_audit(ad, "codex")

    result = cb.check_budget_ceiling(sorted(ad.glob("*.json")), None)
    assert result.tripped
    assert result.kind == cb.BudgetCeilingKind.UNIT_MISMATCH
    assert result.agent == "codex"
    assert result.cap_unit == "requests"
    assert result.observed_unit == "tokens_local_proxy"
    assert "Fix" in result.reason and "quota_caps.json" in result.reason
    print("  ✓ codex cap unit≠observed unit → UNIT_MISMATCH halt")


def test_v2_no_cap_for_signal_returns_config_required(tmp_path: Path, capsys) -> None:
    """F006a fix#1: when a participating agent has signal in some window but
    NO cap+signal window exists anywhere for that agent, the breaker returns
    CONFIG_REQUIRED — not OK. Closes the gap where Codex with no cap entry
    silently returned OK and let dispatch proceed unguarded.

    The warn-once still fires for diagnostic depth, and details.cause
    distinguishes this from caps-file-missing CONFIG_REQUIRED."""
    print("\n[test] v2_no_cap_for_signal_returns_config_required ...")
    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    _write_v2_state(
        qs, claude_7d_observed=0, codex_5h_observed=200_000_000, claude_calibration=None
    )
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    # Caps file has Claude but no Codex entry — Codex is uncovered.
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "defaults": {"claude_tier": "max_20x"},
                "claude": {
                    "max_20x": {
                        "rolling_7d": {"cap": 100, "unit": "percent_of_plan"},
                    }
                },
            }
        )
    )
    ad = tmp_path / "audits"
    ad.mkdir()
    _write_audit(ad, "codex")

    result1 = cb.check_budget_ceiling(sorted(ad.glob("*.json")), None)
    assert result1.tripped
    assert result1.kind == cb.BudgetCeilingKind.CONFIG_REQUIRED
    assert result1.details.get("cause") == "no_cap_for_signal"
    assert result1.details.get("cause_per_agent", {}).get("codex") == "no_cap_for_signal"
    assert "codex" in result1.details.get("uncovered_agents", [])
    assert "codex.plus.rolling_5h" in result1.reason
    assert "quota-caps init" in result1.reason

    captured1 = capsys.readouterr()
    assert "no cap for codex" in captured1.err.lower() or "rolling_5h" in captured1.err

    # Second call: warn-once dedup means no repeat stderr line, but the
    # terminal verdict is still CONFIG_REQUIRED (idempotent).
    result2 = cb.check_budget_ceiling(sorted(ad.glob("*.json")), None)
    assert result2.tripped
    assert result2.kind == cb.BudgetCeilingKind.CONFIG_REQUIRED

    captured2 = capsys.readouterr()
    assert "rolling_5h" not in captured2.err  # warn-once dedup held
    print("  ✓ no cap+signal window for participating agent → CONFIG_REQUIRED (no false-OK)")


def test_v2_no_cap_for_secondary_window_ok_when_primary_covers(tmp_path: Path) -> None:
    """If an agent has signal in two windows but cap entry exists for only
    one, that's OK — the agent is covered by the capped window. Real example:
    Codex emits both rolling_5h (F006 primary) and rolling_7d (mirror parity)
    but the F004 starter caps only rolling_5h. Operator-intentional, not a
    config gap."""
    print("\n[test] v2_no_cap_for_secondary_window_ok_when_primary_covers ...")
    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    state = {
        "schema_version": 2,
        "vendors": {
            "codex": {
                "tier": "plus",
                "windows": {
                    "rolling_5h": {
                        "kind": "rolling_5h",
                        "observed_native": 100_000_000,
                        "observed_unit": "tokens_local_proxy",
                    },
                    "rolling_7d": {
                        "kind": "rolling_7d",
                        "observed_native": 300_000_000,
                        "observed_unit": "tokens_local_proxy",
                    },
                },
            },
        },
    }
    qs.write_text(json.dumps(state))
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    # Cap only on rolling_5h (matches F004 starter shape)
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "codex": {
                    "plus": {
                        "rolling_5h": {"cap": 1_000_000_000, "unit": "tokens_local_proxy"},
                    }
                },
            }
        )
    )
    ad = tmp_path / "audits"
    ad.mkdir()
    _write_audit(ad, "codex")

    result = cb.check_budget_ceiling(sorted(ad.glob("*.json")), None)
    assert not result.tripped, (
        f"expected OK because rolling_5h covers codex; got {result.kind} reason={result.reason}"
    )
    assert result.kind == cb.BudgetCeilingKind.OK
    print("  ✓ secondary uncapped window does NOT escalate when primary covers")


def test_v2_evaluate_window_pure_helper(tmp_path: Path) -> None:
    """The shared evaluate_window helper (used by check_budget_ceiling and
    F006b consumers) is pure and exposes the per-window outcome + structured
    fields. Verify each terminal + non-terminal outcome via direct calls."""
    print("\n[test] v2_evaluate_window_pure_helper ...")
    # NO_SIGNAL: observed=0
    ev = cb.evaluate_window(
        agent="claude",
        tier="max_20x",
        window_name="rolling_7d",
        window={"observed_native": 0, "observed_unit": "weighted_tokens_local_proxy"},
        cap_block={"cap": 100, "unit": "percent_of_plan"},
    )
    assert ev.outcome == cb.WindowOutcome.NO_SIGNAL

    # NO_CAP: signal but no cap_block
    ev = cb.evaluate_window(
        agent="codex",
        tier="plus",
        window_name="rolling_5h",
        window={"observed_native": 1_000_000, "observed_unit": "tokens_local_proxy"},
        cap_block=None,
    )
    assert ev.outcome == cb.WindowOutcome.NO_CAP
    assert ev.observed_native == 1_000_000

    # CALIBRATION_REQUIRED: Claude % cap + uncalibrated
    ev = cb.evaluate_window(
        agent="claude",
        tier="max_20x",
        window_name="rolling_7d",
        window={
            "observed_native": 500_000_000,
            "observed_unit": "weighted_tokens_local_proxy",
            "calibration": {"ratio": None, "confidence": "uncalibrated"},
        },
        cap_block={"cap": 100, "unit": "percent_of_plan"},
    )
    assert ev.outcome == cb.WindowOutcome.CALIBRATION_REQUIRED

    # UNIT_MISMATCH: codex with wrong cap unit
    ev = cb.evaluate_window(
        agent="codex",
        tier="plus",
        window_name="rolling_5h",
        window={"observed_native": 1_000, "observed_unit": "tokens_local_proxy"},
        cap_block={"cap": 100, "unit": "requests"},
    )
    assert ev.outcome == cb.WindowOutcome.UNIT_MISMATCH

    # OK: codex with matching unit, under cap; pct_of_cap surfaced for F006b
    ev = cb.evaluate_window(
        agent="codex",
        tier="plus",
        window_name="rolling_5h",
        window={"observed_native": 80_000_000, "observed_unit": "tokens_local_proxy"},
        cap_block={"cap": 100_000_000, "unit": "tokens_local_proxy"},
    )
    assert ev.outcome == cb.WindowOutcome.OK
    assert ev.pct_of_cap == 0.8
    assert ev.effective == 80_000_000

    # TRIPPED: same shape, over cap
    ev = cb.evaluate_window(
        agent="codex",
        tier="plus",
        window_name="rolling_5h",
        window={"observed_native": 150_000_000, "observed_unit": "tokens_local_proxy"},
        cap_block={"cap": 100_000_000, "unit": "tokens_local_proxy"},
    )
    assert ev.outcome == cb.WindowOutcome.TRIPPED
    assert ev.pct_of_cap == 1.5

    # OK + STALE: Claude % cap, manual calibration, stamped >7d ago, under cap
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
    ev = cb.evaluate_window(
        agent="claude",
        tier="max_20x",
        window_name="rolling_7d",
        window={
            "observed_native": 100_000_000,
            "observed_unit": "weighted_tokens_local_proxy",
            "calibration": {
                "ratio": 1.0e-7,  # 100M * 1e-7 = 10 < 100
                "confidence": "manual",
                "source": "operator_dashboard_sample",
                "stamped_at": old,
            },
        },
        cap_block={"cap": 100, "unit": "percent_of_plan"},
    )
    assert ev.outcome == cb.WindowOutcome.OK
    assert ev.stale is True  # advisory; ratio applied anyway
    assert ev.effective == 10
    print("  ✓ evaluate_window covers 6 outcomes + stale advisory; pure (no I/O)")


def test_v2_codex_with_percent_of_plan_cap_returns_unit_mismatch(tmp_path: Path) -> None:
    """F006a fix#2: only Claude can have percent_of_plan caps (calibration
    bridges weighted_tokens → percent). A non-Claude vendor with
    cap.unit=percent_of_plan (operator typo) must return UNIT_MISMATCH, NOT
    a misleading CALIBRATION_REQUIRED with calibrate-claude guidance for
    codex."""
    print("\n[test] v2_codex_with_percent_of_plan_cap_returns_unit_mismatch ...")
    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    _write_v2_state(
        qs, claude_7d_observed=0, codex_5h_observed=200_000_000, claude_calibration=None
    )
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    # Codex cap with percent_of_plan unit — operator typo (should be tokens_local_proxy)
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "codex": {
                    "plus": {
                        "rolling_5h": {"cap": 80, "unit": "percent_of_plan"},
                    }
                },
            }
        )
    )
    ad = tmp_path / "audits"
    ad.mkdir()
    _write_audit(ad, "codex")

    result = cb.check_budget_ceiling(sorted(ad.glob("*.json")), None)
    assert result.tripped
    assert result.kind == cb.BudgetCeilingKind.UNIT_MISMATCH
    assert result.agent == "codex"
    # Codex with percent_of_plan cap → falls through to else branch since
    # agent != "claude" → UNIT_MISMATCH because observed_unit ≠ percent_of_plan
    assert result.cap_unit == "percent_of_plan"
    assert result.observed_unit == "tokens_local_proxy"
    assert "calibrate-claude" not in result.reason  # no misleading guidance
    print("  ✓ codex with percent_of_plan cap → UNIT_MISMATCH (no calibrate-claude noise)")


def test_v2_validator_rejects_zero_cap(tmp_path: Path) -> None:
    """F006a fix#2: cap=0 is rejected at validate-time. Aligns the loader
    with evaluate_window's defensive cap_value <= 0 check (was cap_value < 0
    in validator vs cap_value <= 0 in evaluator — inconsistent semantics)."""
    print("\n[test] v2_validator_rejects_zero_cap ...")
    from jarvis_orchestrate import quota_caps_loader as qcl

    bad = {
        "schema_version": 1,
        "codex": {
            "plus": {
                "rolling_5h": {"cap": 0, "unit": "tokens_local_proxy"},
            }
        },
    }
    errors = qcl.validate(bad)
    assert any("must be positive" in e for e in errors), errors

    # Negative cap also rejected
    bad["codex"]["plus"]["rolling_5h"]["cap"] = -1
    errors = qcl.validate(bad)
    assert any("must be positive" in e for e in errors), errors

    # Tiny positive cap is fine
    bad["codex"]["plus"]["rolling_5h"]["cap"] = 1
    errors = qcl.validate(bad)
    assert errors == []
    print("  ✓ cap=0 rejected; cap<0 rejected; cap=1 accepted")


def test_v2_missing_vendor_block_returns_config_required(tmp_path: Path) -> None:
    """F006a fix#2: a participating agent with NO vendor block in
    quota_state.json (state corruption / quota_check.py crash / pre-F002
    state) used to silently skip and return OK. Now: known-vendor agents
    without a vblock escalate to CONFIG_REQUIRED with
    details.cause='missing_vendor_block' so dispatch doesn't proceed
    unguarded."""
    print("\n[test] v2_missing_vendor_block_returns_config_required ...")
    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    # vendors{} block present BUT only contains gemini — claude/codex omitted
    state = {
        "schema_version": 2,
        "vendors": {
            "gemini": {
                "tier": "code_assist_individuals",
                "windows": {
                    "rolling_24h": {
                        "kind": "rolling_24h",
                        "observed_native": 0,
                        "observed_unit": "requests",
                    },
                },
            },
        },
    }
    qs.write_text(json.dumps(state))
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "claude": {
                    "max_20x": {
                        "rolling_7d": {"cap": 100, "unit": "percent_of_plan"},
                    }
                },
            }
        )
    )
    ad = tmp_path / "audits"
    ad.mkdir()
    _write_audit(ad, "claude")  # Claude participated but has no vblock

    result = cb.check_budget_ceiling(sorted(ad.glob("*.json")), None)
    assert result.tripped, "missing vblock for participating known agent must escalate"
    assert result.kind == cb.BudgetCeilingKind.CONFIG_REQUIRED
    assert result.details.get("cause") == "missing_vendor_block"
    assert "claude" in result.details.get("cause_per_agent", {})
    assert result.details["cause_per_agent"]["claude"] == "missing_vendor_block"
    assert "stale or corrupt" in result.reason or "vendor block" in result.reason
    print("  ✓ participating known-agent without vblock → CONFIG_REQUIRED missing_vendor_block")


def test_v2_starter_caps_omits_claude_rolling_5h(tmp_path: Path) -> None:
    """F006a fix#2: F004 starter no longer seeds Claude rolling_5h with
    percent_of_plan. Each percent_of_plan cap requires its own dashboard
    sample (weekly bar vs session bar); seeding both forced a dual-calibrate
    before the breaker stopped halting on rolling_5h CALIBRATION_REQUIRED.
    Operator opts in explicitly via hand-edit after running calibrate-claude
    --window rolling_5h."""
    print("\n[test] v2_starter_caps_omits_claude_rolling_5h ...")
    from jarvis_orchestrate import quota_caps_loader as qcl

    data = qcl.starter_caps()
    claude_windows = data["claude"]["max_20x"]
    assert "rolling_7d" in claude_windows
    assert "rolling_5h" not in claude_windows, (
        "rolling_5h was seeded; would force operator to calibrate twice "
        "before first dispatch could succeed"
    )
    note = claude_windows["rolling_7d"]["_note"]
    assert "rolling_5h" in note  # operator told how to add it
    assert "calibrate-claude --window rolling_5h" in note
    print("  ✓ starter omits rolling_5h; rolling_7d _note tells operator how to extend")


def test_v2_caps_init_honors_env_path(tmp_path: Path, monkeypatch) -> None:
    """F006a fix#1: init_starter_file must honor JARVIS_QUOTA_CAPS_PATH or the
    CLI guidance ('run quota-caps init') refers to a file the loader doesn't
    actually read. Test isolates by setting JARVIS_QUOTA_CAPS_PATH and
    verifying init writes there, not to ~/.jarvis/quota_caps.json."""
    print("\n[test] v2_caps_init_honors_env_path ...")
    from jarvis_orchestrate import quota_caps_loader as qcl

    target = tmp_path / "env_override.json"
    monkeypatch.setenv("JARVIS_QUOTA_CAPS_PATH", str(target))

    # Path arg=None must resolve to env override
    qcl.init_starter_file(codex_observed_5h=100)
    assert target.is_file(), "init should have written to env-overridden path"
    assert qcl.effective_caps_path() == target

    # Loader reads the same place
    loaded = qcl.load()
    assert loaded["schema_version"] == 1

    # show() also resolves to the env-overridden path
    rendered = qcl.show()
    assert str(target) in rendered
    print("  ✓ init_starter_file + load + show all honor JARVIS_QUOTA_CAPS_PATH")


def test_v2_stale_calibration_warns_but_applies(tmp_path: Path, capsys) -> None:
    """Stale calibration is a stderr warn-once, NOT a halt. The breaker
    applies the ratio anyway because no-action is more dangerous than
    slightly-aged-action."""
    print("\n[test] v2_stale_calibration_warns_but_applies ...")
    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
    _write_v2_state(
        qs,
        claude_7d_observed=100_000_000,
        codex_5h_observed=0,
        claude_calibration={
            "ratio": 1.0e-7,  # 100M * 1e-7 = 10 (well under cap 100)
            "confidence": "manual",
            "source": "operator_dashboard_sample",
            "stamped_at": old,
        },
    )
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "defaults": {"claude_tier": "max_20x"},
                "claude": {
                    "max_20x": {
                        "rolling_7d": {"cap": 100, "unit": "percent_of_plan"},
                    }
                },
            }
        )
    )
    ad = tmp_path / "audits"
    ad.mkdir()
    _write_audit(ad, "claude")

    result = cb.check_budget_ceiling(sorted(ad.glob("*.json")), None)
    # Under cap (10 < 100) → OK, but stale warning fires
    assert not result.tripped
    assert result.kind == cb.BudgetCeilingKind.OK

    captured = capsys.readouterr()
    assert "stale" in captured.err.lower()
    assert "applying ratio anyway" in captured.err
    print("  ✓ stale calibration warns but applies; not a halt")


def test_v2_legacy_fallback_when_vendors_block_missing(tmp_path: Path, capsys) -> None:
    """When state.vendors{} is missing (pre-F002 state file), the breaker
    falls back to the legacy models{}.percent_weekly path with plan.quota_caps
    as the authority. fallback_used=True surfaces the path taken."""
    print("\n[test] v2_legacy_fallback_when_vendors_block_missing ...")
    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    qs.write_text(
        json.dumps(
            {
                # NO vendors{} block — legacy F020 v1 shape only
                "models": {"claude": {"percent_weekly": 80.0, "plan": "x"}},
            }
        )
    )
    ad = tmp_path / "audits"
    ad.mkdir()
    _write_audit(ad, "claude")

    # Legacy fallback honors plan-level per_agent_caps (v2 ignores them)
    result = cb.check_budget_ceiling(sorted(ad.glob("*.json")), {"claude": 50.0})
    assert result.tripped
    assert result.kind == cb.BudgetCeilingKind.TRIPPED
    assert result.fallback_used  # legacy path
    assert "legacy mirror" in result.reason

    # Single deprecation warning emitted on first call
    captured = capsys.readouterr()
    assert "vendors{} block missing" in captured.err
    print("  ✓ vendors-missing falls back to legacy with deprecation warn")


def test_v2_ignores_plan_level_caps(tmp_path: Path) -> None:
    """F006a refinement #2: in v2 path, plan.quota_caps are IGNORED. Only the
    operator caps file decides. (Plan-level remains active on legacy fallback;
    that's covered by the existing fallback test.)"""
    print("\n[test] v2_ignores_plan_level_caps ...")
    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    _write_v2_state(
        qs,
        claude_7d_observed=550_000_000,
        codex_5h_observed=0,
        claude_calibration={
            "ratio": 2.0e-7,  # 550M * 2e-7 = 110 > cap 100
            "confidence": "manual",
            "source": "operator_dashboard_sample",
            "stamped_at": _iso_now(),
        },
    )
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "defaults": {"claude_tier": "max_20x"},
                "claude": {
                    "max_20x": {
                        "rolling_7d": {"cap": 100, "unit": "percent_of_plan"},
                    }
                },
            }
        )
    )
    ad = tmp_path / "audits"
    ad.mkdir()
    _write_audit(ad, "claude")

    # Pass an absurdly-large per_agent_caps to prove it's ignored on v2 path
    # (if v2 honored plan caps, claude:99999 would prevent the trip).
    result = cb.check_budget_ceiling(sorted(ad.glob("*.json")), {"claude": 99999.0})
    assert result.tripped, (
        "v2 path must trip on operator caps file regardless of plan.quota_caps; "
        "ignoring this would reintroduce the broken-percent_weekly bug for "
        "older plans declaring quota_caps"
    )
    assert result.kind == cb.BudgetCeilingKind.TRIPPED
    assert not result.fallback_used  # confirms v2 path
    print("  ✓ v2 path ignores plan-level quota_caps; only operator caps file authoritative")


def test_v2_collect_agent_coverage_covered_path() -> None:
    """F006b shared helper: agent with cap + signal + OK outcome on the
    primary window. report.terminal None, config_cause None, primary present
    with .pct_of_cap for soft-warn / defer thresholds."""
    print("\n[test] v2_collect_agent_coverage_covered_path ...")
    vendors = {
        "codex": {
            "tier": "plus",
            "windows": {
                "rolling_5h": {
                    "kind": "rolling_5h",
                    "observed_native": 80_000_000,
                    "observed_unit": "tokens_local_proxy",
                },
            },
        },
    }
    caps = {
        "schema_version": 1,
        "codex": {"plus": {"rolling_5h": {"cap": 100_000_000, "unit": "tokens_local_proxy"}}},
    }
    report = cb.collect_agent_coverage(agent="codex", vendors=vendors, caps=caps)
    assert report.terminal is None
    assert report.config_cause is None
    assert report.primary is not None
    assert report.primary.window == "rolling_5h"
    assert report.primary.outcome == cb.WindowOutcome.OK
    assert report.primary.pct_of_cap == 0.8
    print("  ✓ covered agent: terminal None, primary on rolling_5h with .pct_of_cap=0.8")


def test_v2_collect_agent_coverage_window_priority_picks_rolling_5h() -> None:
    """Deterministic window selection per DEFAULT_WINDOW_PRIORITY (was dict
    iteration order — flagged in the F006a review). With both rolling_5h
    and rolling_7d having OK outcomes, rolling_5h wins because it's
    higher priority, regardless of dict insertion order."""
    print("\n[test] v2_collect_agent_coverage_window_priority_picks_rolling_5h ...")
    # Insert rolling_7d FIRST in the dict to verify priority overrides order
    vendors = {
        "codex": {
            "tier": "plus",
            "windows": {
                "rolling_7d": {
                    "kind": "rolling_7d",
                    "observed_native": 700_000_000,
                    "observed_unit": "tokens_local_proxy",
                },
                "rolling_5h": {
                    "kind": "rolling_5h",
                    "observed_native": 50_000_000,
                    "observed_unit": "tokens_local_proxy",
                },
            },
        },
    }
    caps = {
        "schema_version": 1,
        "codex": {
            "plus": {
                "rolling_7d": {"cap": 1_000_000_000, "unit": "tokens_local_proxy"},
                "rolling_5h": {"cap": 100_000_000, "unit": "tokens_local_proxy"},
            }
        },
    }
    report = cb.collect_agent_coverage(agent="codex", vendors=vendors, caps=caps)
    # rolling_5h is higher in DEFAULT_WINDOW_PRIORITY, so it wins as primary
    assert report.primary is not None
    assert report.primary.window == "rolling_5h"
    assert report.primary.pct_of_cap == 0.5
    print("  ✓ rolling_5h selected as primary regardless of dict insertion order")


def test_v2_collect_agent_coverage_missing_vblock() -> None:
    """Missing vendor block → config_cause='missing_vendor_block', no primary."""
    print("\n[test] v2_collect_agent_coverage_missing_vblock ...")
    vendors = {"gemini": {"tier": "code_assist_individuals", "windows": {}}}
    caps = {"schema_version": 1}
    report = cb.collect_agent_coverage(agent="claude", vendors=vendors, caps=caps)
    assert report.config_cause == "missing_vendor_block"
    assert report.terminal is None
    assert report.primary is None
    assert report.evaluations == ()
    print("  ✓ missing vblock → config_cause=missing_vendor_block")


def test_v2_collect_agent_coverage_terminal_short_circuits() -> None:
    """Terminal outcome (UNIT_MISMATCH here) flows into report.terminal —
    consumers can branch on it without aggregating other windows."""
    print("\n[test] v2_collect_agent_coverage_terminal_short_circuits ...")
    vendors = {
        "codex": {
            "tier": "plus",
            "windows": {
                "rolling_5h": {
                    "kind": "rolling_5h",
                    "observed_native": 1_000,
                    "observed_unit": "tokens_local_proxy",
                },
            },
        },
    }
    caps = {
        "schema_version": 1,
        "codex": {"plus": {"rolling_5h": {"cap": 80, "unit": "requests"}}},  # mismatch
    }
    report = cb.collect_agent_coverage(agent="codex", vendors=vendors, caps=caps)
    assert report.terminal is not None
    assert report.terminal.outcome == cb.WindowOutcome.UNIT_MISMATCH
    assert report.config_cause is None
    print("  ✓ terminal flows into report.terminal for caller to route on")


def test_v2_supervisor_quota_gate_v2_routes_through_collect_agent_coverage(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end: supervisor._quota_gate against v2 state + caps file uses
    the shared collect_agent_coverage helper. Verifies (pct, line) shape
    with .pct_of_cap-derived percent and operator-cap reference."""
    print("\n[test] v2_supervisor_quota_gate_v2_routes_through_collect_agent_coverage ...")
    from jarvis_orchestrate import supervisor

    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    qs.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "vendors": {
                    "codex": {
                        "tier": "plus",
                        "windows": {
                            "rolling_5h": {
                                "kind": "rolling_5h",
                                "observed_native": 95_000_000,  # 95% of 100M cap
                                "observed_unit": "tokens_local_proxy",
                            },
                        },
                    },
                },
            }
        )
    )
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "codex": {
                    "plus": {"rolling_5h": {"cap": 100_000_000, "unit": "tokens_local_proxy"}}
                },
            }
        )
    )

    pct, line = supervisor._quota_gate("codex")
    assert pct is not None
    assert 94.5 <= pct <= 95.5  # 95% within rounding
    assert "rolling_5h" in line
    assert "soft threshold" in line  # crossed 90% soft threshold
    assert "tier=plus" in line
    print("  ✓ _quota_gate v2 surfaces .pct_of_cap percent + window + soft-warn")


def test_v2_quota_admission_threshold_uses_collect_agent_coverage(
    tmp_path: Path, monkeypatch
) -> None:
    """quota_admission.evaluate_quota_threshold v2 path defers when primary
    window pct > threshold/100 percent. Same shared collector as breaker +
    supervisor."""
    print("\n[test] v2_quota_admission_threshold_uses_collect_agent_coverage ...")
    from jarvis_orchestrate import quota_admission

    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    # Codex at 80% — above default 70% defer threshold
    qs.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "vendors": {
                    "codex": {
                        "tier": "plus",
                        "windows": {
                            "rolling_5h": {
                                "kind": "rolling_5h",
                                "observed_native": 80_000_000,
                                "observed_unit": "tokens_local_proxy",
                            },
                        },
                    },
                },
            }
        )
    )
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "codex": {
                    "plus": {"rolling_5h": {"cap": 100_000_000, "unit": "tokens_local_proxy"}}
                },
            }
        )
    )

    result = quota_admission.evaluate_quota_threshold(["codex"])
    assert result.over_threshold
    assert result.offending_agent == "codex"
    assert result.observed_pct is not None
    assert 79.5 <= result.observed_pct <= 80.5
    assert result.cause is None  # numeric defer, not config issue

    # Caps file unloadable → defer with cause
    caps.unlink()
    result2 = quota_admission.evaluate_quota_threshold(["codex"])
    assert result2.over_threshold
    assert result2.cause == "caps_file_missing"
    print("  ✓ quota_admission v2 defers numeric + surfaces cause for config issues")


def test_v2_supervisor_admission_reason_handles_cause_path() -> None:
    """F006b fix#1: supervisor._format_admission_quota_reason must not crash
    on observed_pct=None when QuotaCheck carries a cause (caps_file_missing,
    calibration_required, unit_mismatch, missing_vendor_block, no_cap_for_signal).
    The pre-fix code formatted with :.1f and would TypeError under any of
    these conditions during F007 dogfood."""
    print("\n[test] v2_supervisor_admission_reason_handles_cause_path ...")
    from jarvis_orchestrate import quota_admission, supervisor

    # Numeric path — preserves the historical 'percent_weekly N% > threshold M%' shape
    numeric = quota_admission.QuotaCheck(
        over_threshold=True,
        offending_agent="codex",
        observed_pct=85.0,
        threshold=70.0,
    )
    line = supervisor._format_admission_quota_reason(numeric)
    assert "codex" in line
    assert "85.0%" in line
    assert "threshold 70.0%" in line

    # Cause path — observed_pct is None, no crash, surfaces structured cause
    cause = quota_admission.QuotaCheck(
        over_threshold=True,
        offending_agent="codex",
        observed_pct=None,
        threshold=70.0,
        cause="caps_file_missing",
    )
    line = supervisor._format_admission_quota_reason(cause)
    assert "codex" in line
    assert "defer:caps_file_missing" in line
    assert "quota-caps init" in line
    print("  ✓ admission reason builder handles both numeric and cause paths")


def test_v2_quota_admission_tripped_returns_numeric() -> None:
    """F006b fix#1: TRIPPED outcome surfaces .pct_of_cap as observed_pct
    (numeric path), not a cause. CALIBRATION_REQUIRED / UNIT_MISMATCH stay
    on the cause path. Distinguishes truly numeric over-threshold from
    config-issue defers in admission telemetry."""
    print("\n[test] v2_quota_admission_tripped_returns_numeric ...")
    from jarvis_orchestrate import quota_admission

    qs = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    # Codex at 150% of cap — TRIPPED outcome
    qs.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "vendors": {
                    "codex": {
                        "tier": "plus",
                        "windows": {
                            "rolling_5h": {
                                "kind": "rolling_5h",
                                "observed_native": 150_000_000,
                                "observed_unit": "tokens_local_proxy",
                            },
                        },
                    },
                },
            }
        )
    )
    caps = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    caps.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "codex": {
                    "plus": {"rolling_5h": {"cap": 100_000_000, "unit": "tokens_local_proxy"}}
                },
            }
        )
    )

    result = quota_admission.evaluate_quota_threshold(["codex"])
    assert result.over_threshold
    assert result.offending_agent == "codex"
    # F006b fix#1: TRIPPED carries numeric observed_pct (150%), no cause
    assert result.observed_pct is not None
    assert 149.9 <= result.observed_pct <= 150.1
    assert result.cause is None  # numeric path
    print("  ✓ TRIPPED outcome → numeric observed_pct, no cause (admission telemetry preserved)")


def test_v2_emit_budget_kind_specific_event_calibration_required(tmp_path: Path) -> None:
    """F006b fix#1: dispatch_volley emits a kind-specific INBOX event before
    the generic breaker_tripped event. Verifies the calibration_required
    branch writes the right event name + actionable body. Same pattern
    covers unit_mismatch + config_required (next two tests)."""
    print("\n[test] v2_emit_budget_kind_specific_event_calibration_required ...")
    from jarvis_orchestrate import inbox, supervisor

    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "audit").mkdir()

    bd_result = cb.BudgetCeilingResult(
        kind=cb.BudgetCeilingKind.CALIBRATION_REQUIRED,
        tripped=True,
        reason="claude.max_20x.rolling_7d cap is percent_of_plan but uncalibrated",
        agent="claude",
        tier="max_20x",
        window="rolling_7d",
        confidence="uncalibrated",
    )
    supervisor._emit_budget_kind_specific_event(
        plan_dir,
        "test-plan",
        bd_result,
        feature_id="F001",
    )
    inbox_text = (plan_dir / inbox.INBOX_FILENAME).read_text()
    assert "calibration_required" in inbox_text
    assert "calibrate-claude" in inbox_text
    assert "rolling_7d" in inbox_text
    print("  ✓ CALIBRATION_REQUIRED → calibration_required event + calibrate-claude command")


def test_v2_emit_budget_kind_specific_event_unit_mismatch(tmp_path: Path) -> None:
    print("\n[test] v2_emit_budget_kind_specific_event_unit_mismatch ...")
    from jarvis_orchestrate import inbox, supervisor

    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "audit").mkdir()

    bd_result = cb.BudgetCeilingResult(
        kind=cb.BudgetCeilingKind.UNIT_MISMATCH,
        tripped=True,
        reason="codex cap.unit='requests' != observed_unit='tokens_local_proxy'",
        agent="codex",
        tier="plus",
        window="rolling_5h",
        cap_unit="requests",
        observed_unit="tokens_local_proxy",
    )
    supervisor._emit_budget_kind_specific_event(
        plan_dir,
        "test-plan",
        bd_result,
        feature_id="F001",
    )
    inbox_text = (plan_dir / inbox.INBOX_FILENAME).read_text()
    assert "unit_mismatch" in inbox_text
    assert "quota_caps.json" in inbox_text
    assert "codex" in inbox_text
    print("  ✓ UNIT_MISMATCH → unit_mismatch event + caps-edit guidance")


def test_v2_emit_budget_kind_specific_event_config_required(tmp_path: Path) -> None:
    print("\n[test] v2_emit_budget_kind_specific_event_config_required ...")
    from jarvis_orchestrate import inbox, supervisor

    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "audit").mkdir()

    bd_result = cb.BudgetCeilingResult(
        kind=cb.BudgetCeilingKind.CONFIG_REQUIRED,
        tripped=True,
        reason="caps file unavailable: caps file not found",
        details={"cause": "caps_file_missing"},
    )
    supervisor._emit_budget_kind_specific_event(
        plan_dir,
        "test-plan",
        bd_result,
        feature_id="F001",
    )
    inbox_text = (plan_dir / inbox.INBOX_FILENAME).read_text()
    assert "config_required" in inbox_text
    assert "caps_file_missing" in inbox_text
    assert "quota-caps init" in inbox_text
    print("  ✓ CONFIG_REQUIRED → config_required event + cause + remediation")


def test_v2_emit_budget_kind_specific_event_tripped_no_extra_event(tmp_path: Path) -> None:
    """TRIPPED is not given a kind-specific event — the generic
    breaker_tripped event from _trip_breaker carries enough. Verifies the
    helper is a no-op for TRIPPED so we don't double-emit."""
    print("\n[test] v2_emit_budget_kind_specific_event_tripped_no_extra_event ...")
    from jarvis_orchestrate import inbox, supervisor

    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "audit").mkdir()

    bd_result = cb.BudgetCeilingResult(
        kind=cb.BudgetCeilingKind.TRIPPED,
        tripped=True,
        reason="claude rolling_7d 110% > 100%",
        agent="claude",
        tier="max_20x",
        window="rolling_7d",
    )
    supervisor._emit_budget_kind_specific_event(
        plan_dir,
        "test-plan",
        bd_result,
        feature_id="F001",
    )
    inbox_path = plan_dir / inbox.INBOX_FILENAME
    # No event written — _trip_breaker handles the breaker_tripped emit
    assert not inbox_path.exists() or "calibration_required" not in inbox_path.read_text()
    print("  ✓ TRIPPED is a no-op in the helper (breaker_tripped is the operative event)")


def test_v2_warn_cache_resets_between_tests() -> None:
    """The autouse fixture in conftest.py calls cb.reset_warning_cache() on
    every test. Verify the cache itself has been emptied as we enter this
    test (i.e., no stale entries from earlier tests leak in)."""
    print("\n[test] v2_warn_cache_resets_between_tests ...")
    assert cb._warned_once == set(), (
        f"warn cache should be empty at test start, got {cb._warned_once!r}"
    )
    cb._warn_once("budget_ceiling", "claude", "test_condition", "msg")
    assert ("budget_ceiling", "claude", "test_condition") in cb._warned_once
    cb.reset_warning_cache()
    assert cb._warned_once == set()
    print("  ✓ reset_warning_cache empties dedup state; autouse fixture isolates per test")


def test_check_no_progress() -> None:
    print("\n[test] check_no_progress ...")
    assert cb.check_no_progress("needs_changes", "needs_changes")[0]
    assert not cb.check_no_progress(None, "needs_changes")[0]
    assert not cb.check_no_progress("needs_changes", "blocked")[0]
    # signed_off / blocked don't count as "stuck"
    assert not cb.check_no_progress("signed_off", "signed_off")[0]
    assert not cb.check_no_progress("blocked", "blocked")[0]
    print("  ✓ no_progress fires on identical non-terminal verdicts only")


def _write_auditor_audit(ad: Path, iteration: int, *, status: str, findings: int) -> Path:
    p = ad / f"codex-auditor-i{iteration}.json"
    p.write_text(
        json.dumps(
            {
                "task_id": "t",
                "audit_id": f"t#codex#{iteration}",
                "agent": "codex",
                "agent_role": "auditor",
                "iteration": iteration,
                "started_at": _iso_now(),
                "completed_at": _iso_now(),
                "audit_status": status,
                "findings": [
                    {"severity": "low", "category": "style", "issue": f"finding {i}-aaaaaaa"}
                    for i in range(findings)
                ],
            }
        )
    )
    return p


def test_check_diminishing_returns() -> None:
    print("\n[test] check_diminishing_returns ...")
    with tempfile.TemporaryDirectory() as td:
        ad = Path(td)
        # First single audit — not enough rounds
        _write_auditor_audit(ad, 0, status="needs_changes", findings=3)
        assert not cb.check_diminishing_returns(sorted(ad.glob("*.json")))[0]
        # Second audit — same finding count, same status → diminishing
        _write_auditor_audit(ad, 1, status="needs_changes", findings=3)
        tripped, reason = cb.check_diminishing_returns(sorted(ad.glob("*.json")))
        assert tripped and "non-decreasing" in reason
        # Replace last with fewer findings → no trip
        _write_auditor_audit(ad, 1, status="needs_changes", findings=1)
        assert not cb.check_diminishing_returns(sorted(ad.glob("*.json")))[0]
    print("  ✓ diminishing_returns fires on non-decreasing findings across needs_changes rounds")


def test_check_convergence_collapse() -> None:
    print("\n[test] check_convergence_collapse ...")
    with tempfile.TemporaryDirectory() as td:
        ad = Path(td)
        _write_auditor_audit(ad, 0, status="needs_changes", findings=2)
        _write_auditor_audit(ad, 1, status="inconclusive", findings=2)
        _write_auditor_audit(ad, 2, status="needs_changes", findings=2)
        tripped, reason = cb.check_convergence_collapse(sorted(ad.glob("*.json")))
        assert tripped and "oscillate" in reason
        # Same status thrice → not collapse (no_progress fires instead)
        ad2 = Path(td) / "uniform"
        ad2.mkdir()
        for i in range(3):
            _write_auditor_audit(ad2, i, status="needs_changes", findings=2)
        assert not cb.check_convergence_collapse(sorted(ad2.glob("*.json")))[0]
    print("  ✓ convergence_collapse fires on verdict ping-pong, not on uniform stuck")


# ──────────────────────────────  global breaker  ──────────────────────────────


def test_global_breaker_threshold() -> None:
    """conftest's autouse fixture redirects JARVIS_BREAKER_HISTORY_PATH per-test;
    cb._effective_history_path() returns it. No manual monkeypatching needed."""
    print("\n[test] global_breaker_threshold ...")
    history = cb._effective_history_path()
    # Empty → not tripped
    assert not cb.evaluate_global().tripped
    # Two hits → not tripped
    cb.record_global_hit("p1", cb.BreakerKind.ITERATION_CAP)
    cb.record_global_hit("p2", cb.BreakerKind.ITERATION_CAP)
    assert not cb.evaluate_global().tripped
    # Third → tripped
    cb.record_global_hit("p3", cb.BreakerKind.ITERATION_CAP)
    state = cb.evaluate_global()
    assert state.tripped and state.hits_in_window == 3
    # Other breaker kinds don't count toward the threshold
    history.unlink()
    for _ in range(5):
        cb.record_global_hit("p", cb.BreakerKind.NO_PROGRESS)
    assert not cb.evaluate_global().tripped
    print("  ✓ global breaker fires at 3+ iteration_cap hits; other kinds ignored for threshold")


def test_global_breaker_window_pruning() -> None:
    print("\n[test] global_breaker_window_pruning ...")
    history = cb._effective_history_path()
    history.parent.mkdir(parents=True, exist_ok=True)
    stale = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with history.open("w") as f:
        for _ in range(5):
            f.write(
                json.dumps(
                    {
                        "plan_id": "old",
                        "kind": "iteration_cap",
                        "at": stale,
                    }
                )
                + "\n"
            )
    # Even 5 stale hits don't trip the breaker
    assert not cb.evaluate_global().tripped
    # One fresh hit alone doesn't either
    cb.record_global_hit("new", cb.BreakerKind.ITERATION_CAP)
    assert not cb.evaluate_global().tripped
    print("  ✓ entries older than the 24h window don't count")


# ──────────────────────────────  gate-pause integration  ──────────────────────────────


def test_breaker_blocks_dispatch_via_gate_pause() -> None:
    print("\n[test] breaker_blocks_dispatch_via_gate_pause ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        gate_pause.add_breaker(
            pd, cb.gate_name(cb.BreakerKind.WALL_CLOCK), plan_id="p", reason="elapsed > 1h"
        )
        check = gate_pause.evaluate(pd, ["pre_impl"])
        assert check.paused
        assert "breaker:wall_clock" in check.unmet
        assert "pre_impl" in check.unmet
        # Approve the breaker — only plan-gate left
        gate_pause.approve_gate(pd, "breaker:wall_clock", plan_id="p")
        check2 = gate_pause.evaluate(pd, ["pre_impl"])
        assert check2.unmet == ["pre_impl"]
        # State file: active_breakers cleaned + breaker not in cleared_gates
        state = json.loads(gate_pause.gate_state_path(pd).read_text())
        assert "active_breakers" not in state or not state.get("active_breakers")
        assert all(not c.startswith("breaker:") for c in (state.get("cleared_gates") or []))
        # Re-tripping the same breaker must pause again
        gate_pause.add_breaker(
            pd, cb.gate_name(cb.BreakerKind.WALL_CLOCK), plan_id="p", reason="re-hit"
        )
        assert "breaker:wall_clock" in gate_pause.evaluate(pd, ["pre_impl"]).unmet
    print("  ✓ breakers union with plan.human_gates, approve clears, re-trip pauses again")


def test_resume_all_clears_breakers() -> None:
    print("\n[test] resume_all_clears_breakers ...")
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        gate_pause.add_breaker(
            pd, cb.gate_name(cb.BreakerKind.NO_PROGRESS), plan_id="p", reason="x"
        )
        gate_pause.add_breaker(pd, cb.gate_name(cb.BreakerKind.WALL_CLOCK), plan_id="p", reason="y")
        gate_pause.resume_all(pd, plan_id="p", declared_gates=["pre_impl"])
        check = gate_pause.evaluate(pd, ["pre_impl"])
        assert not check.paused, check
    print("  ✓ resume_all clears every active breaker plus declared gates")


# ──────────────────────────────  supervisor end-to-end  ──────────────────────────────


_PLAN_TEMPLATE = """---
id: {plan_id}
title: F006 synthetic
type: infra
tier: trivial
status: active
date: "2026-04-26"
description: Synthetic plan for F006 circuit-breaker tests.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
loop_caps:
  max_iterations: {cap}
  hard_stop: false
  wall_clock_hours: {wall_clock_hours}
privacy_tier: internal
links:
  features: ./features.json
---

# F006 synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""


def _make_plan(repo: Path, plan_id: str, *, cap: int = 1, wall_clock_hours: float = 1.0) -> Path:
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        _PLAN_TEMPLATE.format(
            plan_id=plan_id,
            cap=cap,
            wall_clock_hours=wall_clock_hours,
        )
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "test",
                        "phase": 0,
                        "description": "Synthetic feature for F006 tests.",
                        "steps": ["scripted"],
                        "acceptance": "Volley terminates per breaker.",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return plan_dir


class _ScriptedExecutor(BaseExecutor):
    """Returns scripted summaries with an optional findings-count knob (auditor)."""

    def __init__(
        self, agent: str, *, role: str, summaries: list[str], statuses: list[str] | None = None
    ) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.role = role
        self.summaries = list(summaries)
        self.statuses = list(statuses) if statuses else []
        self.idx = 0

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        i = self.idx
        self.idx += 1
        s = self.summaries[i] if i < len(self.summaries) else self.summaries[-1]
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=s,
            raw_response=s,
            quota_consumed={"tokens_in": 1, "tokens_out": 1},
        )


def _bypass_quota():
    saved = supervisor._quota_gate
    supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")
    return saved


def _force_auditor_status(force: str):
    """Wrap supervisor._run_round so the auditor returns the forced status."""
    orig = supervisor._run_round

    def maybe_force(*args, **kwargs):
        path = orig(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            data = json.loads(path.read_text())
            data["audit_status"] = force
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return path

    supervisor._run_round = maybe_force
    return orig


def test_supervisor_iteration_cap_pauses_via_breaker() -> None:
    """Global history is isolated per-test by the conftest autouse fixture."""
    print("\n[test] supervisor_iteration_cap_pauses_via_breaker ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-400-infra-f006-cap", cap=0)
        gate_pause.resume_all(
            plan_dir, plan_id="2026-04-26-400-infra-f006-cap", declared_gates=["pre_impl"]
        )
        impl = _ScriptedExecutor(
            "claude", role="implementer", summaries=["Synthetic implementer summary."]
        )
        aud = _ScriptedExecutor("codex", role="auditor", summaries=["Synthetic auditor summary."])
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = _bypass_quota()
        saved_run = _force_auditor_status("needs_changes")
        AGENT_REGISTRY["claude"] = lambda: impl
        AGENT_REGISTRY["codex"] = lambda: aud
        os.environ[notify.DISABLE_ENV] = "1"
        try:
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=0)
            assert result.final_status == "stopped_cap", result
            # Synthetic gate present
            check = gate_pause.evaluate(plan_dir, ["pre_impl"])
            assert "breaker:iteration_cap" in check.unmet
            # INBOX entry recorded
            events = inbox.read_events(plan_dir)
            assert any(e.event == "breaker_tripped" for e in events)
            # Global history bumped
            assert cb.evaluate_global().hits_in_window == 1
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota
            supervisor._run_round = saved_run
            os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ iteration_cap → breaker_tripped INBOX + synthetic gate + global history hit")


def test_supervisor_global_breaker_hard_stops() -> None:
    print("\n[test] supervisor_global_breaker_hard_stops ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-401-infra-f006-global")
        gate_pause.resume_all(
            plan_dir, plan_id="2026-04-26-401-infra-f006-global", declared_gates=["pre_impl"]
        )
        # Pre-load 3 iteration_cap hits
        for i in range(3):
            cb.record_global_hit(f"p{i}", cb.BreakerKind.ITERATION_CAP)
        impl = _ScriptedExecutor("claude", role="implementer", summaries=["x"])
        aud = _ScriptedExecutor("codex", role="auditor", summaries=["x"])
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = _bypass_quota()
        AGENT_REGISTRY["claude"] = lambda: impl
        AGENT_REGISTRY["codex"] = lambda: aud
        os.environ[notify.DISABLE_ENV] = "1"
        try:
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert result.final_status == "stopped_global_breaker", result
            # Critical: no executor was called (hard stop before dispatch loop)
            assert impl.idx == 0 and aud.idx == 0
            events = inbox.read_events(plan_dir)
            tripped = [e for e in events if e.event == "breaker_tripped"]
            assert tripped and tripped[-1].headers.get("breaker_kind") == "global_circuit_breaker"
            assert tripped[-1].headers.get("approval_required") == "false"
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota
            os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ global breaker hard-stops dispatch — no executors called, no clearance offered")


# ──────────────────────────────  AC-honesty fixes (D074-amend)  ──────────────────────────────


def test_global_breaker_evaluates_before_executor_resolution() -> None:
    """Fix#2: global breaker must trip BEFORE _resolve_executor; an empty
    AGENT_REGISTRY with a tripped global breaker should produce
    stopped_global_breaker, not KeyError."""
    print("\n[test] global_breaker_evaluates_before_executor_resolution ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-410-infra-f006-order")
        gate_pause.resume_all(
            plan_dir, plan_id="2026-04-26-410-infra-f006-order", declared_gates=["pre_impl"]
        )
        for _ in range(3):
            cb.record_global_hit("p", cb.BreakerKind.ITERATION_CAP)
        # Critically: clear AGENT_REGISTRY so executor resolution would KeyError
        # if reached before the global breaker check.
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = _bypass_quota()
        AGENT_REGISTRY.clear()
        os.environ[notify.DISABLE_ENV] = "1"
        try:
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert result.final_status == "stopped_global_breaker", result
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota
            os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ tripped global breaker halts dispatch before executor resolution")


def test_cli_approve_breaker_no_false_warning() -> None:
    """Fix#3a: jarvis approve <plan-id> breaker:<kind> must not warn that the
    name isn't in plan.human_gates."""
    print("\n[test] cli_approve_breaker_no_false_warning ...")
    from contextlib import redirect_stderr

    from jarvis_orchestrate import cli

    buf_out = io.StringIO()
    buf_err = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-411-infra-f006-cli-approve")
        # Trip the breaker so it's in active_breakers (gives the CLI two
        # parallel paths to recognize the name as valid: known BreakerKind +
        # currently active).
        gate_pause.add_breaker(
            plan_dir, "breaker:wall_clock", plan_id="2026-04-26-411-infra-f006-cli-approve"
        )
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = cli.main(["approve", str(plan_dir), "breaker:wall_clock"])
        assert rc == 0
        assert "WARNING" not in buf_err.getvalue(), buf_err.getvalue()
        # Sanity: a totally bogus name still warns.
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            cli.main(["approve", str(plan_dir), "breaker:totally_made_up_kind"])
        # That name IS in BreakerKind only if the kind name matches; "totally_made_up_kind"
        # doesn't, so it should warn. Active_breakers also doesn't have it.
        assert "WARNING" in buf_err.getvalue() or "totally_made_up_kind" in buf_err.getvalue()
    print("  ✓ CLI approve recognizes breaker:* as a valid declared name; bogus names still warn")


def test_cli_resume_clears_active_breakers_with_no_human_gates() -> None:
    """Fix#3b: jarvis resume must continue past the no-declared-gates short-circuit
    when active_breakers is non-empty."""
    print("\n[test] cli_resume_clears_active_breakers_with_no_human_gates ...")
    from jarvis_orchestrate import cli

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        # Plan with empty human_gates list
        plan_id = "2026-04-26-412-infra-f006-resume-no-gates"
        plan_dir = repo / "docs" / "plans" / plan_id
        plan_dir.mkdir(parents=True)
        plan_md = f"""---
id: {plan_id}
title: F006 fix synthetic
type: infra
tier: trivial
status: active
date: "2026-04-26"
description: Synthetic plan for fix#3b — no human_gates, only breakers.
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

# F006 fix synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""
        (plan_dir / "plan.md").write_text(plan_md)
        (plan_dir / "features.json").write_text(
            json.dumps(
                {
                    "task_id": plan_id,
                    "schema_version": "1.0",
                    "features": [
                        {
                            "id": "F001",
                            "category": "test",
                            "phase": 0,
                            "description": "Synthetic feature for F006 fix#3b.",
                            "steps": ["scripted"],
                            "acceptance": "resume clears active breakers.",
                            "passes": False,
                            "depends_on": [],
                        }
                    ],
                },
                indent=2,
            )
            + "\n"
        )
        # Trip a breaker but leave human_gates empty
        gate_pause.add_breaker(plan_dir, "breaker:wall_clock", plan_id=plan_id)
        assert "breaker:wall_clock" in gate_pause.active_breakers(plan_dir)
        buf = io.StringIO()
        # Plan 2026-05-02-001 F001: bare `resume <plan>` now exits 2; the
        # bulk-clear semantic this test exercises is now `resume --all`.
        with redirect_stdout(buf):
            rc = cli.main(["resume", str(plan_dir), "--all"])
        assert rc == 0
        # After resume, active breakers must be cleared
        assert "breaker:wall_clock" not in gate_pause.active_breakers(plan_dir), (
            gate_pause.active_breakers(plan_dir)
        )
    print("  ✓ resume clears active breakers even when plan declares no human_gates")


# ──────────────────────────────  D074-amend2 fixes  ──────────────────────────────


def test_active_breaker_preempts_executor_resolution() -> None:
    """D074-amend2 Fix#1: an active breaker:* gate must pause dispatch BEFORE
    _resolve_executor runs. Reproduces the reviewer's case: with breaker:wall_clock
    active and AGENT_REGISTRY empty, dispatch must return paused_on_gate, not
    KeyError."""
    print("\n[test] active_breaker_preempts_executor_resolution ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-413-infra-f006-preempt")
        gate_pause.resume_all(
            plan_dir, plan_id="2026-04-26-413-infra-f006-preempt", declared_gates=["pre_impl"]
        )
        # Plant the breaker explicitly so dispatch hits an unmet gate from start.
        gate_pause.add_breaker(
            plan_dir, "breaker:wall_clock", plan_id="2026-04-26-413-infra-f006-preempt"
        )
        # Empty registry → KeyError if executor resolution runs before gate-pause.
        saved_registry = dict(AGENT_REGISTRY)
        saved_quota = _bypass_quota()
        AGENT_REGISTRY.clear()
        os.environ[notify.DISABLE_ENV] = "1"
        try:
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
            assert result.final_status == "paused_on_gate", result
            assert "breaker:wall_clock" in result.reason
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(saved_registry)
            supervisor._quota_gate = saved_quota
            os.environ.pop(notify.DISABLE_ENV, None)
    print("  ✓ active breaker pauses dispatch even with empty AGENT_REGISTRY")


def test_cli_approve_refuses_global_breaker() -> None:
    """D074-amend2 Fix#2: the global circuit breaker is hard-stop with no
    operator clearance. `jarvis approve <plan> breaker:global_circuit_breaker`
    must refuse with a non-zero exit code rather than print 'cleared gate'."""
    print("\n[test] cli_approve_refuses_global_breaker ...")
    from contextlib import redirect_stderr

    from jarvis_orchestrate import cli

    buf_out = io.StringIO()
    buf_err = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-414-infra-f006-no-global-clear")
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = cli.main(["approve", str(plan_dir), "breaker:global_circuit_breaker"])
        assert rc != 0, "approve must fail for the global breaker"
        assert "REFUSED" in buf_err.getvalue() or "hard-stop" in buf_err.getvalue()
        assert "cleared gate" not in buf_out.getvalue()
    print("  ✓ approve refuses breaker:global_circuit_breaker")


def test_breaker_approve_is_idempotent() -> None:
    """D074-amend2 Fix#3: approve_gate's idempotency contract must hold for
    breaker:* gates too. After a breaker is approved (popped from
    active_breakers), a second approve of the same gate must return False
    and append no second history entry."""
    print("\n[test] breaker_approve_is_idempotent ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-04-26-415-infra-f006-idem")
        plan_id = "2026-04-26-415-infra-f006-idem"
        gate_pause.add_breaker(plan_dir, "breaker:wall_clock", plan_id=plan_id)
        first = gate_pause.approve_gate(plan_dir, "breaker:wall_clock", plan_id=plan_id)
        assert first is True
        second = gate_pause.approve_gate(plan_dir, "breaker:wall_clock", plan_id=plan_id)
        assert second is False, "second approve of cleared breaker must be a no-op"
        # And a third, just to be sure
        third = gate_pause.approve_gate(plan_dir, "breaker:wall_clock", plan_id=plan_id)
        assert third is False
        # History should hold exactly one approve entry for this breaker
        state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
        approves = [
            h
            for h in state.get("history", [])
            if h.get("action") == "approve" and h.get("gate") == "breaker:wall_clock"
        ]
        assert len(approves) == 1, approves
    print("  ✓ second approve of cleared breaker is no-op (idempotent)")
