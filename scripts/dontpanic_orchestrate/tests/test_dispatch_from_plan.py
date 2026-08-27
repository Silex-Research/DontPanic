"""F002 — `python -m dontpanic_orchestrate dispatch-from-plan` CLI subcommand.

Strict-dry-run by default; `--confirm` calls supervisor.dispatch_volley
in-process. Tests cover: 10-field block contents + ordering, dry-run never
dispatches, --confirm-with-blocked-readiness exits 3 with kind-specific
remediation, --confirm=ok dispatches in-process, plan resolution errors
exit 2, target_env/target_project source = `## Target` section, flag
forwarding to dispatch_volley.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_dispatch_from_plan.py
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

# Bootstrap import path — same convention as sibling test modules.
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import cli  # noqa: E402

_PLAN_ID = "2026-05-01-002-feat-dispatch-from-plan"

_PLAN_MD_TEMPLATE = """---
id: {plan_id}
title: Synthetic dispatch-from-plan test
type: feat
tier: trivial
status: active
date: "2026-05-01"
description: Synthetic plan exercising dispatch-from-plan dry-run + confirm paths.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# Dispatch-from-plan synthetic

Used by tests/test_dispatch_from_plan.py — no real CLI dispatch.

## Target

```yaml
target_env: {target_env}
target_project: {target_project}
```
"""


def _write_plan(
    repo: Path,
    plan_id: str = _PLAN_ID,
    *,
    target_env: str = "dev",
    target_project: str = "none",
) -> Path:
    """Write a minimal valid plan dir under repo/docs/plans/<plan_id>."""
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        _PLAN_MD_TEMPLATE.format(
            plan_id=plan_id, target_env=target_env, target_project=target_project
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
                        "description": "Synthetic feature for dispatch-from-plan tests.",
                        "steps": ["dry-run preflight", "confirm dispatch"],
                        "acceptance": "Pre-flight block prints 10 fields; --confirm forwards to dispatch_volley.",
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


def _seed_caps_ok() -> None:
    """Write a quota_caps.json file (env-isolated path) with valid claude+codex
    entries — `_compute_readiness` walks both agents, so both must have caps
    OR neither must have signal."""
    caps_path = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    caps_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "defaults": {"claude_tier": "max_20x"},
                "claude": {"max_20x": {"rolling_7d": {"cap": 100, "unit": "percent_of_plan"}}},
                "codex": {
                    "plus": {"rolling_5h": {"cap": 1_000_000_000, "unit": "tokens_local_proxy"}}
                },
            }
        )
    )


def _seed_state_ok() -> None:
    """Write a v2-shape quota_state.json with calibrated Claude + light Codex
    so collect_agent_coverage returns OK for both agents."""
    state_path = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "vendors": {
                    "claude": {
                        "tier": "max_20x",
                        "windows": {
                            "rolling_7d": {
                                "kind": "rolling_7d",
                                "observed_native": 100_000_000,
                                "observed_unit": "weighted_tokens_local_proxy",
                                "calibration": {
                                    "ratio": 1.0e-7,
                                    "confidence": "manual",
                                    "source": "operator_dashboard_sample",
                                    "stamped_at": "2026-04-30T00:00:00Z",
                                },
                            }
                        },
                    },
                    "codex": {
                        "tier": "plus",
                        "windows": {
                            "rolling_5h": {
                                "kind": "rolling_5h",
                                "observed_native": 50_000_000,
                                "observed_unit": "tokens_local_proxy",
                            }
                        },
                    },
                },
            }
        )
    )


def _seed_state_uncalibrated_claude() -> None:
    state_path = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "vendors": {
                    "claude": {
                        "tier": "max_20x",
                        "windows": {
                            "rolling_7d": {
                                "kind": "rolling_7d",
                                "observed_native": 500_000_000,
                                "observed_unit": "weighted_tokens_local_proxy",
                                "calibration": {
                                    "ratio": None,
                                    "confidence": "uncalibrated",
                                    "source": None,
                                    "stamped_at": None,
                                },
                            }
                        },
                    },
                    "codex": {
                        "tier": "plus",
                        "windows": {
                            "rolling_5h": {
                                "kind": "rolling_5h",
                                "observed_native": 0,
                                "observed_unit": "tokens_local_proxy",
                            }
                        },
                    },
                },
            }
        )
    )


def _seed_state_unit_mismatch_codex() -> None:
    state_path = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "vendors": {
                    "claude": {
                        "tier": "max_20x",
                        "windows": {
                            "rolling_7d": {
                                "kind": "rolling_7d",
                                "observed_native": 0,
                                "observed_unit": "weighted_tokens_local_proxy",
                                "calibration": {
                                    "ratio": None,
                                    "confidence": "uncalibrated",
                                    "source": None,
                                    "stamped_at": None,
                                },
                            }
                        },
                    },
                    "codex": {
                        "tier": "plus",
                        "windows": {
                            "rolling_5h": {
                                "kind": "rolling_5h",
                                "observed_native": 50_000_000,
                                "observed_unit": "tokens_local_proxy",
                            }
                        },
                    },
                },
            }
        )
    )


def _seed_caps_unit_mismatch() -> None:
    """Codex cap.unit = `requests` (wrong) when observed_unit = `tokens_local_proxy`."""
    caps_path = Path(os.environ["JARVIS_QUOTA_CAPS_PATH"])
    caps_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "codex": {"plus": {"rolling_5h": {"cap": 100, "unit": "requests"}}},
            }
        )
    )


# ───────────────────────────  dry-run path  ───────────────────────────


def test_dry_run_prints_ten_fields_in_order(tmp_path) -> None:
    """Acceptance (1) + (2): the pre-flight block contains exactly the 10
    declared labels in order, and dry-run exits 0 without dispatching."""
    print("\n[test] dry_run_prints_ten_fields_in_order ...")
    _write_plan(tmp_path)
    _seed_state_ok()
    _seed_caps_ok()

    buf_out = io.StringIO()
    monkeyed_cwd = tmp_path
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=monkeyed_cwd),
        redirect_stdout(buf_out),
    ):
        rc = cli.main(["dispatch-from-plan", _PLAN_ID])
    assert rc == 0
    out = buf_out.getvalue()

    # Required field labels in declared order. Each must appear exactly once
    # and the offset of label N+1 must be > label N's offset.
    labels = [
        "plan_path:",
        "feature:",
        "tier:",
        "target_env:",
        "target_project:",
        "implementer:",
        "auditor:",
        "human_gates:",
        "max_iterations:",
        "quota_readiness:",
    ]
    offsets: list[int] = []
    for label in labels:
        idx = out.find(label)
        assert idx != -1, f"missing label {label!r} in output:\n{out}"
        offsets.append(idx)
    for i in range(len(offsets) - 1):
        assert offsets[i] < offsets[i + 1], (
            f"label {labels[i + 1]!r} appears before {labels[i]!r}; offsets={offsets}\nout:\n{out}"
        )

    # Spot-check values
    assert "F001" in out
    assert "trivial" in out
    assert "dev" in out
    assert "(none)" in out  # target_project=none → printed as (none)
    assert "claude" in out
    assert "codex" in out
    assert "pre_impl,pre_merge" in out
    assert "quota_readiness: ok" in out
    # OK readiness adds the claude=N% / codex=N% summary line
    assert "claude=" in out and "codex=" in out and "%" in out
    print("  ✓ 10 fields present in declared order; dry-run exit 0")


def test_dry_run_prints_global_breaker_tripped(tmp_path) -> None:
    """Dry-run prints TRIPPED / hard stop and still exits 0 (same as blocked quota_readiness)."""
    from dontpanic_orchestrate import circuit_breakers as cb

    print("\n[test] dry_run_prints_global_breaker_tripped ...")
    _write_plan(tmp_path)
    _seed_state_ok()
    _seed_caps_ok()
    for i in range(3):
        cb.record_global_hit(f"p{i}", cb.BreakerKind.ITERATION_CAP)

    buf_out = io.StringIO()
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        redirect_stdout(buf_out),
    ):
        rc = cli.main(["dispatch-from-plan", _PLAN_ID])
    assert rc == 0
    out = buf_out.getvalue()
    assert "TRIPPED" in out, out
    assert "hard stop" in out, out
    print("  ✓ dry-run prints global_breaker TRIPPED and still exits 0")


def test_dry_run_never_dispatches_regardless_of_tty(tmp_path) -> None:
    """Acceptance (1): without --confirm the CLI must NOT invoke
    supervisor.dispatch_volley. Spy on the function and assert zero calls."""
    print("\n[test] dry_run_never_dispatches_regardless_of_tty ...")
    _write_plan(tmp_path)
    _seed_state_ok()
    _seed_caps_ok()

    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch("dontpanic_orchestrate.cli.supervisor.dispatch_volley") as spy,
        redirect_stdout(io.StringIO()),
    ):
        rc = cli.main(["dispatch-from-plan", _PLAN_ID])
    assert rc == 0
    assert spy.call_count == 0, (
        f"dispatch_volley must not be called in dry-run; got {spy.call_count} calls"
    )
    print("  ✓ dispatch_volley not invoked under dry-run")


def test_dry_run_prints_readiness_label_even_when_blocked(tmp_path) -> None:
    """Acceptance (4) + step (e) note: dry-run prints the same readiness
    label as --confirm without refusing. So a blocked-readiness state in
    dry-run still exits 0; the label is just informational."""
    print("\n[test] dry_run_prints_readiness_label_even_when_blocked ...")
    _write_plan(tmp_path)
    _seed_state_uncalibrated_claude()
    _seed_caps_ok()  # Claude has cap=percent_of_plan but state is uncalibrated

    buf_out = io.StringIO()
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        redirect_stdout(buf_out),
    ):
        rc = cli.main(["dispatch-from-plan", _PLAN_ID])
    assert rc == 0
    out = buf_out.getvalue()
    assert "quota_readiness: calibration_required" in out, out
    print("  ✓ blocked readiness shown but dry-run still exits 0")


# ───────────────────────────  --confirm blocked paths  ───────────────────────────


def test_confirm_blocked_calibration_required_exits_3(tmp_path) -> None:
    """Acceptance (5): calibration_required → exit 3 with calibrate-claude
    remediation pointer."""
    print("\n[test] confirm_blocked_calibration_required_exits_3 ...")
    _write_plan(tmp_path)
    _seed_state_uncalibrated_claude()
    _seed_caps_ok()

    buf_err = io.StringIO()
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch("dontpanic_orchestrate.cli.supervisor.dispatch_volley") as spy,
        redirect_stdout(io.StringIO()),
        redirect_stderr(buf_err),
    ):
        rc = cli.main(["dispatch-from-plan", _PLAN_ID, "--confirm"])
    assert rc == 3, rc
    assert spy.call_count == 0, "must not dispatch when readiness blocked"
    err = buf_err.getvalue()
    assert "calibration_required" in err
    assert "calibrate-claude" in err
    print("  ✓ calibration_required → exit 3 + calibrate-claude pointer")


def test_confirm_blocked_unit_mismatch_exits_3(tmp_path) -> None:
    """Acceptance (5): unit_mismatch → exit 3 with quota_caps.json edit pointer."""
    print("\n[test] confirm_blocked_unit_mismatch_exits_3 ...")
    _write_plan(tmp_path)
    _seed_state_unit_mismatch_codex()
    _seed_caps_unit_mismatch()

    buf_err = io.StringIO()
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch("dontpanic_orchestrate.cli.supervisor.dispatch_volley") as spy,
        redirect_stdout(io.StringIO()),
        redirect_stderr(buf_err),
    ):
        rc = cli.main(["dispatch-from-plan", _PLAN_ID, "--confirm"])
    assert rc == 3
    assert spy.call_count == 0
    err = buf_err.getvalue()
    assert "unit_mismatch" in err
    assert "quota_caps.json" in err
    print("  ✓ unit_mismatch → exit 3 + quota_caps.json edit pointer")


def test_confirm_blocked_config_required_exits_3(tmp_path) -> None:
    """Acceptance (5): missing caps file → config_required → exit 3 with
    quota-caps init pointer."""
    print("\n[test] confirm_blocked_config_required_exits_3 ...")
    _write_plan(tmp_path)
    _seed_state_ok()
    # caps file intentionally NOT created — env var points at a non-existent path

    buf_err = io.StringIO()
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch("dontpanic_orchestrate.cli.supervisor.dispatch_volley") as spy,
        redirect_stdout(io.StringIO()),
        redirect_stderr(buf_err),
    ):
        rc = cli.main(["dispatch-from-plan", _PLAN_ID, "--confirm"])
    assert rc == 3
    assert spy.call_count == 0
    err = buf_err.getvalue()
    assert "config_required" in err
    assert "quota-caps init" in err
    print("  ✓ config_required → exit 3 + quota-caps init pointer")


def test_confirm_blocked_missing_state_exits_3(tmp_path) -> None:
    """Acceptance (5): missing quota_state.json → missing_state → exit 3 with
    quota_check.py pointer. JARVIS_QUOTA_STATE_PATH is set but file untouched."""
    print("\n[test] confirm_blocked_missing_state_exits_3 ...")
    _write_plan(tmp_path)
    # state path env var set by conftest but file not written
    state_path = Path(os.environ["JARVIS_QUOTA_STATE_PATH"])
    assert not state_path.is_file()
    _seed_caps_ok()

    buf_err = io.StringIO()
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch("dontpanic_orchestrate.cli.supervisor.dispatch_volley") as spy,
        redirect_stdout(io.StringIO()),
        redirect_stderr(buf_err),
    ):
        rc = cli.main(["dispatch-from-plan", _PLAN_ID, "--confirm"])
    assert rc == 3
    assert spy.call_count == 0
    err = buf_err.getvalue()
    assert "missing_state" in err
    assert "quota_check.py" in err
    print("  ✓ missing_state → exit 3 + quota_check.py pointer")


# ───────────────────────────  --confirm ok path  ───────────────────────────


class _FakeVolleyResult:
    """Minimal stand-in for VolleyResult — supervisor.dispatch_volley is the
    mocked target; we just need the attributes the CLI prints back."""

    def __init__(self) -> None:
        self.final_status = "signed_off"
        self.rounds = 1
        self.reason = "synthetic ok"
        self.audit_paths: list[Path] = []


def test_confirm_ok_calls_dispatch_volley_in_process(tmp_path) -> None:
    """Acceptance (6) + (9): with readiness=ok, --confirm calls
    supervisor.dispatch_volley IN-PROCESS (no subprocess), and forwards
    `--feature`, `--implementer`, `--auditor`, `--max-iterations`, `--mode`
    verbatim. Spy verifies kwargs."""
    print("\n[test] confirm_ok_calls_dispatch_volley_in_process ...")
    plan_dir = _write_plan(tmp_path)
    _seed_state_ok()
    _seed_caps_ok()

    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch(
            "dontpanic_orchestrate.cli.supervisor.dispatch_volley",
            return_value=_FakeVolleyResult(),
        ) as spy,
        mock.patch("subprocess.run") as subproc_spy,
        mock.patch("subprocess.Popen") as popen_spy,
        redirect_stdout(io.StringIO()),
    ):
        rc = cli.main(
            [
                "dispatch-from-plan",
                _PLAN_ID,
                "--feature",
                "F001",
                "--implementer",
                "claude",
                "--auditor",
                "codex",
                "--max-iterations",
                "5",
                "--mode",
                "autonomous",
                "--confirm",
            ]
        )

    assert rc == 0, rc
    assert spy.call_count == 1
    # NO subprocess shell-out — CLI must hand off in the same interpreter.
    assert subproc_spy.call_count == 0, "must not subprocess.run"
    assert popen_spy.call_count == 0, "must not subprocess.Popen"

    kwargs = spy.call_args.kwargs
    assert kwargs["plan_dir"] == plan_dir.resolve()
    assert kwargs["feature_id"] == "F001"
    assert kwargs["implementer_agent"] == "claude"
    assert kwargs["auditor_agent"] == "codex"
    assert kwargs["max_iterations"] == 5
    assert kwargs["mode"] == "autonomous"
    print("  ✓ readiness=ok dispatches in-process; all five flags forwarded")


def test_confirm_ok_default_flags_propagate_as_none(tmp_path) -> None:
    """Acceptance (9): when CLI flags are omitted, dispatch_volley sees None
    for each so the supervisor's own plan-default fallback applies. The CLI
    must not silently substitute its own defaults at this layer."""
    print("\n[test] confirm_ok_default_flags_propagate_as_none ...")
    _write_plan(tmp_path)
    _seed_state_ok()
    _seed_caps_ok()

    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch(
            "dontpanic_orchestrate.cli.supervisor.dispatch_volley",
            return_value=_FakeVolleyResult(),
        ) as spy,
        redirect_stdout(io.StringIO()),
    ):
        rc = cli.main(["dispatch-from-plan", _PLAN_ID, "--confirm"])

    assert rc == 0
    kwargs = spy.call_args.kwargs
    # --feature defaults to F001 in argparse; the others stay None so
    # dispatch_volley's plan-derived fallbacks apply.
    assert kwargs["feature_id"] == "F001"
    assert kwargs["implementer_agent"] is None
    assert kwargs["auditor_agent"] is None
    assert kwargs["max_iterations"] is None
    assert kwargs["mode"] is None
    print("  ✓ omitted flags forward as None; only --feature has a CLI-layer default")


# ───────────────────────────  plan resolution / schema errors  ───────────────────────────


def test_missing_plan_exits_2(tmp_path) -> None:
    """Acceptance (7): non-existent plan id → exit 2 with `docs/plans/` pointer."""
    print("\n[test] missing_plan_exits_2 ...")
    buf_err = io.StringIO()
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        redirect_stderr(buf_err),
        redirect_stdout(io.StringIO()),
    ):
        rc = cli.main(["dispatch-from-plan", "2026-99-99-999-does-not-exist"])
    assert rc == 2
    err = buf_err.getvalue()
    assert "plan not found" in err.lower() or "not found" in err.lower()
    assert "docs/plans" in err
    print("  ✓ missing plan exits 2 with docs/plans pointer")


def test_schema_invalid_plan_exits_2(tmp_path) -> None:
    """Acceptance (8): plan that fails plan.schema.json validation → exit 2
    with the validator's error message. Reproduce by writing a plan.md whose
    frontmatter is missing required fields (e.g. agents_required)."""
    print("\n[test] schema_invalid_plan_exits_2 ...")
    plan_id = "2026-05-01-003-feat-schema-bad"
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        f"id: {plan_id}\n"
        "title: malformed\n"
        # missing tier, type, status, date, description, agents_required, …
        "---\n\n# malformed\n\n## Target\n\n```yaml\n"
        "target_env: dev\ntarget_project: none\n```\n"
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
                        "description": "x",
                        "steps": ["x"],
                        "acceptance": "x",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            }
        )
    )

    buf_err = io.StringIO()
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        redirect_stderr(buf_err),
        redirect_stdout(io.StringIO()),
    ):
        rc = cli.main(["dispatch-from-plan", plan_id])
    assert rc == 2, rc
    err = buf_err.getvalue()
    # validator's error message surfaces; we just check the prefix tag
    assert "plan validation failed" in err.lower() or "validation" in err.lower()
    print("  ✓ schema-invalid plan exits 2 with validator message")


def test_target_env_and_project_pulled_from_target_section(tmp_path) -> None:
    """Acceptance (3): `## Target` section is the source of truth (NOT
    frontmatter). Plant a non-default target_env in the Target block and
    assert the dry-run block prints that value."""
    print("\n[test] target_env_and_project_pulled_from_target_section ...")
    # Use staging here to make the test value distinct from the dev default.
    _write_plan(
        tmp_path,
        plan_id="2026-05-01-004-feat-target-section",
        target_env="staging",
        target_project="my-staging-proj",
    )
    _seed_state_ok()
    _seed_caps_ok()

    buf_out = io.StringIO()
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        redirect_stdout(buf_out),
    ):
        rc = cli.main(["dispatch-from-plan", "2026-05-01-004-feat-target-section"])
    assert rc == 0
    out = buf_out.getvalue()
    assert "target_env:     staging" in out, out
    assert "target_project: my-staging-proj" in out, out
    print("  ✓ target_env/target_project pulled from ## Target section")
