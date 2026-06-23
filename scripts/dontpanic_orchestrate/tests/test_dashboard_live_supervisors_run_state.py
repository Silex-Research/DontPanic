"""Regression: the dashboard build sites must join live supervisors into the
operator-triage ``run_state`` so the Cockpit / Work board running count is
non-zero during an active volley.

Root cause (fixed by this change): ``dashboard.build`` and
``projects_dashboard.build_fleet_what_now`` both called
``operator_triage.write_triage_state(...)`` WITHOUT ``live_supervisors=``, so
``derive_run_state`` defaulted to an empty registry and every item read
``idle`` ("0 running") even with a live supervisor on the plan. The CLI
``operator brief`` was correct because it passed
``operator_brief._live_supervisors()``.

The conftest autouse ``_isolate_jarvis_state`` fixture redirects the registry
to a per-test path via ``JARVIS_ACTIVE_SUPERVISORS_PATH``, so
``active_supervisors.register(..., pid=os.getpid())`` writes to a tmp registry
and the alive-pid filter passes.

Run targeted:
  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_dashboard_live_supervisors_run_state.py -q
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import active_supervisors  # noqa: E402
from dontpanic_orchestrate import operator_console  # noqa: E402
from dontpanic_orchestrate import projects_dashboard as pd  # noqa: E402

# A canonical plan-id (YYYY-MM-DD-NNN-...) that operator_triage._item_plan_id
# discovers via the _PLAN_ID_RE regex against id / dedupe_key / title.
PLAN_ID = "2026-06-22-001-fix-dashboard-live-agents-projection"


# ── live_supervisor_rows() unit ──────────────────────────────────────────


def test_live_supervisor_rows_empty_registry_is_empty() -> None:
    assert active_supervisors.live_supervisor_rows() == []


def test_live_supervisor_rows_returns_registered_alive_row() -> None:
    active_supervisors.register(
        plan_id=PLAN_ID,
        target_env="dev",
        target_project=None,
        supervisor_config_dir=None,
        pid=os.getpid(),  # alive so the pid filter keeps it
    )
    rows = active_supervisors.live_supervisor_rows()
    assert len(rows) == 1
    assert rows[0]["plan_id"] == PLAN_ID
    assert rows[0]["pid"] == os.getpid()


def test_live_supervisor_rows_filters_dead_pids() -> None:
    # PID 0 is never alive (and _is_pid_alive rejects pid <= 0).
    active_supervisors.register(
        plan_id=PLAN_ID,
        target_env="dev",
        target_project=None,
        supervisor_config_dir=None,
        pid=0,
    )
    assert active_supervisors.live_supervisor_rows() == []


# ── the real regression at the fleet surface ─────────────────────────────


def _make_report_with_item(tmp_path: Path, *, item_id: str) -> pd.ProjectBuildReport:
    """A ProjectBuildReport whose per-project what-now-cache.json carries one
    ActionItem whose id encodes PLAN_ID, so operator_triage._item_plan_id can
    join it to a registered supervisor. build_fleet_what_now reads items from
    ``ctx.dashboard_cache_path / 'what-now-cache.json'``."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    ctx = pd.ProjectContext(
        name="alpha",
        display_name="Alpha",
        repo_root=repo_root,
        plans_root=repo_root / "docs" / "plans",
        architecture_path=repo_root / "arch.json",
        dashboard_cache_path=cache_dir,
    )

    item = operator_console.ActionItem(
        id=item_id,
        # SOURCE_GATE is a project-scoped source so the fleet projection keeps it.
        source=operator_console.SOURCE_GATE,
        band=operator_console.Band.NEEDS_ACTION,
        title="Plan work in progress",
        detail=None,
        exact_command=None,
        automatable=False,
        human_required_reason="awaiting plan run",
        evidence_uri=None,
        updated_at="2026-06-22T00:00:00Z",
        dedupe_key=item_id,
    )
    envelope = {"items": [item.to_dict()]}
    (cache_dir / "what-now-cache.json").write_text(
        json.dumps(envelope), encoding="utf-8"
    )

    return pd.ProjectBuildReport(
        context=ctx,
        build_report=None,
        build_warnings_path=cache_dir / "build-warnings.json",
    )


def _plan_item_run_state(target: Path, *, item_id: str) -> str:
    """The run_state of the triage item matching our plan-scoped gate item.
    The fleet build also aggregates install-level capability items, so we
    locate ours by id rather than assuming it is the only item."""
    sibling = target.parent / pd.FLEET_TRIAGE_FILENAME
    model = json.loads(sibling.read_text(encoding="utf-8"))
    matches = [it for it in model["items"] if it.get("id") == item_id]
    assert len(matches) == 1, f"expected exactly one item id={item_id!r}, got {matches}"
    return matches[0]["run_state"]


def test_fleet_triage_run_state_running_with_live_supervisor(tmp_path: Path) -> None:
    # A live supervisor on the item's plan → run_state == "running".
    active_supervisors.register(
        plan_id=PLAN_ID,
        target_env="dev",
        target_project=None,
        supervisor_config_dir=None,
        pid=os.getpid(),
    )
    item_id = f"gate:{PLAN_ID}"
    report = _make_report_with_item(tmp_path, item_id=item_id)
    target = tmp_path / "out" / "fleet-what-now.json"
    pd.build_fleet_what_now([report], output_path=target)

    assert _plan_item_run_state(target, item_id=item_id) == "running"


def test_fleet_triage_run_state_idle_without_supervisor(tmp_path: Path) -> None:
    # No registration → honest zero: run_state == "idle". This negative also
    # proves the join is LIVE (it reads the registry), not hard-wired running.
    item_id = f"gate:{PLAN_ID}"
    report = _make_report_with_item(tmp_path, item_id=item_id)
    target = tmp_path / "out" / "fleet-what-now.json"
    pd.build_fleet_what_now([report], output_path=target)

    assert _plan_item_run_state(target, item_id=item_id) == "idle"


def test_fleet_triage_run_state_conflicted_with_two_supervisors(
    tmp_path: Path,
) -> None:
    # >1 live supervisor on the same plan → run_state == "conflicted".
    for _ in range(2):
        active_supervisors.register(
            plan_id=PLAN_ID,
            target_env="dev",
            target_project=None,
            supervisor_config_dir=None,
            pid=os.getpid(),
        )
    item_id = f"gate:{PLAN_ID}"
    report = _make_report_with_item(tmp_path, item_id=item_id)
    target = tmp_path / "out" / "fleet-what-now.json"
    pd.build_fleet_what_now([report], output_path=target)

    assert _plan_item_run_state(target, item_id=item_id) == "conflicted"
