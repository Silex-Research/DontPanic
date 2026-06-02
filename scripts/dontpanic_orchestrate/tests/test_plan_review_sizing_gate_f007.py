"""F007 — pre-dispatch sizing gate (plan 2026-06-01-001).

Wires the F001 scope lint into ``dispatch-from-plan`` so an over-budget feature
cannot start a paid volley without an explicit ``--allow-oversize`` override.

Coverage (acceptance #5):
  * an over-budget feature is refused pre-dispatch (exit 5) with the F002 split
    proposal surfaced as remediation, and dispatch_volley is NOT called;
  * an ``--allow-oversize <reason>`` override records the rationale to an
    evidence sidecar and proceeds to dispatch_volley;
  * an in-budget feature dispatches unchanged (no override file, exit 0).

Plus the pure-module contracts (evaluate_feature size-flag selection,
record_override sidecar shape) and acceptance #1 (the lint runs in the
pre-flight in dry-run too).

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_plan_review_sizing_gate_f007.py -q
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

# Bootstrap import path — same convention as sibling test modules.
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import cli  # noqa: E402
from dontpanic_orchestrate.plan_review import sizing_gate  # noqa: E402

_PLAN_MD_TEMPLATE = """---
id: {plan_id}
title: Synthetic sizing-gate test
type: feat
tier: trivial
status: active
date: "2026-06-01"
description: Synthetic plan exercising the F007 pre-dispatch sizing gate.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
loop_caps:
  max_iterations: 2
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# Sizing-gate synthetic

Used by tests/test_plan_review_sizing_gate_f007.py — no real CLI dispatch.

## Target

```yaml
target_env: dev
target_project: none
```
"""

# An F001 feature whose description/steps/acceptance touch THREE surfaces
# (cli + dashboard + doctor) — F001 fires a block-severity `over_surface`
# (>= 3 surfaces) plus `likely_timeout`. This is the F016 "spans CLI +
# dashboard + doctor" over-scope shape the gate exists to catch.
_OVERSIZE_FEATURE = {
    "id": "F001",
    "category": "tooling",
    "phase": 0,
    "description": (
        "Spans three surfaces: a CLI subcommand, a dashboard html render, and "
        "a doctor preflight warn — over-scoped for one dispatch."
    ),
    "steps": [
        "Add the CLI subcommand.",
        "Render the dashboard html view.",
        "Add the doctor preflight warn.",
    ],
    "acceptance": (
        "(1) The CLI subcommand prints. (2) The dashboard html renders. "
        "(3) The doctor preflight warn fires."
    ),
    "passes": False,
    "depends_on": [],
}

# A clean single-surface feature: no block-severity size flag → in-budget.
_INBUDGET_FEATURE = {
    "id": "F001",
    "category": "tooling",
    "phase": 0,
    "description": "A pure deterministic scoring core module.",
    "steps": ["Compute the score.", "Return the typed report."],
    "acceptance": "(1) The scorer returns a typed report for the input.",
    "passes": False,
    "depends_on": [],
}


def _write_plan(repo: Path, plan_id: str, feature: dict) -> Path:
    """Write a minimal valid plan dir whose F001 is ``feature``."""
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_PLAN_MD_TEMPLATE.format(plan_id=plan_id))
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "schema_version": "1.0",
                "features": [feature],
            },
            indent=2,
        )
        + "\n"
    )
    return plan_dir


def _seed_caps_ok() -> None:
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


class _FakeVolleyResult:
    def __init__(self) -> None:
        self.final_status = "signed_off"
        self.rounds = 1
        self.reason = "synthetic ok"
        self.audit_paths: list[Path] = []


# ─────────────────────────────  pure module  ─────────────────────────────


def test_evaluate_feature_flags_only_size_kinds() -> None:
    """The gate fires only on block-severity SIZE flags (acceptance #4 — the
    gate adds only the size check). A multi-surface feature is blocked; its
    block flags are all in SIZE_FLAG_KINDS."""
    print("\n[test] evaluate_feature_flags_only_size_kinds ...")
    result = sizing_gate.evaluate_feature(_OVERSIZE_FEATURE)
    assert result.is_blocked
    assert result.block_size_flags
    for flag in result.block_size_flags:
        assert flag.severity == "block"
        assert flag.kind in sizing_gate.SIZE_FLAG_KINDS
    # over_surface (>= 3 surfaces) must be among them.
    kinds = {f.kind for f in result.block_size_flags}
    assert "over_surface" in kinds, kinds
    print("  ✓ block flags are size-only; over_surface present")


def test_evaluate_feature_inbudget_not_blocked() -> None:
    """A clean single-surface feature is not blocked (acceptance #5 no-op)."""
    print("\n[test] evaluate_feature_inbudget_not_blocked ...")
    result = sizing_gate.evaluate_feature(_INBUDGET_FEATURE)
    assert not result.is_blocked
    assert result.block_size_flags == ()
    print("  ✓ in-budget feature yields no size block")


def test_record_override_writes_sidecar(tmp_path) -> None:
    """record_override persists the verbatim reason + overridden flags to the
    evidence sidecar (acceptance #3)."""
    print("\n[test] record_override_writes_sidecar ...")
    result = sizing_gate.evaluate_feature(_OVERSIZE_FEATURE)
    reason = "operator accepts the over-scope for a spike"
    path = sizing_gate.record_override(
        tmp_path,
        plan_id="2026-06-01-777-synthetic",
        feature_id="F001",
        reason=reason,
        result=result,
    )
    assert path.is_file()
    assert path.parent == tmp_path / "evidence" / "plan-review" / "pre_dispatch"
    payload = json.loads(path.read_text())
    assert payload["gate"] == "pre_dispatch_sizing"
    assert payload["feature_id"] == "F001"
    assert payload["reason"] == reason
    assert payload["overridden_flags"], "must record the flags it overrode"
    assert all(
        f["kind"] in sizing_gate.SIZE_FLAG_KINDS for f in payload["overridden_flags"]
    )
    print("  ✓ sidecar written with verbatim reason + size flags")


# ─────────────────────────────  CLI: refusal  ─────────────────────────────


def test_confirm_oversize_refused_with_split_proposal(tmp_path) -> None:
    """Acceptance #2: a block-severity size feature is refused at confirm-
    dispatch (exit 5), dispatch_volley is NOT called, and the F002 split
    proposal is surfaced as remediation."""
    print("\n[test] confirm_oversize_refused_with_split_proposal ...")
    plan_id = "2026-06-01-101-feat-oversize"
    _write_plan(tmp_path, plan_id, _OVERSIZE_FEATURE)
    _seed_state_ok()
    _seed_caps_ok()

    buf_err = io.StringIO()
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch("dontpanic_orchestrate.cli.supervisor.dispatch_volley") as spy,
        redirect_stdout(io.StringIO()),
        redirect_stderr(buf_err),
    ):
        rc = cli.main(["dispatch-from-plan", plan_id, "--confirm"])

    assert rc == 5, rc
    assert spy.call_count == 0, "must not dispatch an over-budget feature"
    err = buf_err.getvalue()
    assert "sizing gate" in err.lower()
    assert "over_surface" in err
    # The F002 split proposal must be surfaced (provisional child ids F001a/…).
    assert "F001a" in err, err
    assert "--allow-oversize" in err
    print("  ✓ over-budget feature refused (exit 5) with split proposal shown")


# ─────────────────────────────  CLI: override  ─────────────────────────────


def test_confirm_oversize_override_proceeds_and_records(tmp_path) -> None:
    """Acceptance #3: an --allow-oversize reason records the rationale and
    allows dispatch (dispatch_volley IS called)."""
    print("\n[test] confirm_oversize_override_proceeds_and_records ...")
    plan_id = "2026-06-01-102-feat-oversize-override"
    plan_dir = _write_plan(tmp_path, plan_id, _OVERSIZE_FEATURE)
    _seed_state_ok()
    _seed_caps_ok()

    reason = "spike: operator explicitly accepts over-scope for this round"
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch(
            "dontpanic_orchestrate.cli.supervisor.dispatch_volley",
            return_value=_FakeVolleyResult(),
        ) as spy,
        redirect_stdout(io.StringIO()),
    ):
        rc = cli.main(
            ["dispatch-from-plan", plan_id, "--confirm", "--allow-oversize", reason]
        )

    assert rc == 0, rc
    assert spy.call_count == 1, "override must allow dispatch"
    override_path = (
        plan_dir
        / "evidence"
        / "plan-review"
        / "pre_dispatch"
        / "F001-oversize-override.json"
    )
    assert override_path.is_file(), "override rationale must be recorded"
    payload = json.loads(override_path.read_text())
    assert payload["reason"] == reason
    print("  ✓ --allow-oversize records rationale and dispatches")


def test_confirm_oversize_short_reason_rejected_by_argparse(tmp_path) -> None:
    """An override reason under 8 non-whitespace chars is rejected by the
    argparse layer-A validator (exit 2), before any dispatch."""
    print("\n[test] confirm_oversize_short_reason_rejected ...")
    plan_id = "2026-06-01-103-feat-short-reason"
    _write_plan(tmp_path, plan_id, _OVERSIZE_FEATURE)
    _seed_state_ok()
    _seed_caps_ok()

    # argparse raises SystemExit(2) on a type-validator rejection before the
    # handler ever runs — the standard argparse usage-error path (exit 2).
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch("dontpanic_orchestrate.cli.supervisor.dispatch_volley") as spy,
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
        pytest.raises(SystemExit) as excinfo,
    ):
        cli.main(
            ["dispatch-from-plan", plan_id, "--confirm", "--allow-oversize", "short"]
        )
    assert excinfo.value.code == 2
    assert spy.call_count == 0
    print("  ✓ short override reason rejected (exit 2)")


# ─────────────────────────────  CLI: in-budget  ─────────────────────────────


def test_confirm_inbudget_dispatches_unchanged(tmp_path) -> None:
    """Acceptance #5: an in-budget feature dispatches unchanged — the sizing
    gate is additive and does not interfere, no override file is written."""
    print("\n[test] confirm_inbudget_dispatches_unchanged ...")
    plan_id = "2026-06-01-104-feat-inbudget"
    plan_dir = _write_plan(tmp_path, plan_id, _INBUDGET_FEATURE)
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
        rc = cli.main(["dispatch-from-plan", plan_id, "--confirm"])

    assert rc == 0, rc
    assert spy.call_count == 1, "in-budget feature must dispatch"
    assert not (plan_dir / "evidence" / "plan-review").exists(), (
        "no override sidecar for an in-budget dispatch"
    )
    print("  ✓ in-budget feature dispatches unchanged; no override recorded")


# ─────────────────────────────  CLI: dry-run lint  ─────────────────────────────


def test_dry_run_runs_sizing_lint_without_refusing(tmp_path) -> None:
    """Acceptance #1: the F001 sizing lint runs in the pre-flight (dry-run
    prints the BLOCK verdict) but dry-run never refuses — exit 0, no dispatch."""
    print("\n[test] dry_run_runs_sizing_lint_without_refusing ...")
    plan_id = "2026-06-01-105-feat-dryrun-lint"
    _write_plan(tmp_path, plan_id, _OVERSIZE_FEATURE)
    _seed_state_ok()
    _seed_caps_ok()

    buf_out = io.StringIO()
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch("dontpanic_orchestrate.cli.supervisor.dispatch_volley") as spy,
        redirect_stdout(buf_out),
    ):
        rc = cli.main(["dispatch-from-plan", plan_id])

    assert rc == 0, rc
    assert spy.call_count == 0
    out = buf_out.getvalue()
    assert "sizing-lint (F001)" in out
    assert "verdict:   BLOCK" in out, out
    print("  ✓ dry-run runs the sizing lint, prints BLOCK, exits 0")
