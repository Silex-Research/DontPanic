"""F005 pre-lock design-volley wiring (operator decision D019).

Exercises the bounded opt-in hook `_run_pre_lock_design_volley`: it runs the
design volley only on lint uncertainty OR an explicit operator request, is
advisory (never blocks the lock), and uses injectable executor / run_volley
seams so there is NO live paid call.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from dontpanic_orchestrate import cli
from dontpanic_orchestrate.plan_review.design_review import DesignVolleyEnvelope

_PLAN_MD = """---
id: {pid}
title: design-volley wiring test
type: feat
tier: trivial
status: draft
date: "2026-06-01"
description: F005 pre-lock design-volley wiring test.
agents_required: [claude, codex]
loop_caps: {{max_iterations: 1, hard_stop: false}}
privacy_tier: internal
links: {{features: ./features.json}}
---
# design-volley wiring test
## Target
```yaml
target_env: dev
target_project: none
```
"""


def _make_plan(tmp_path, pid, features):
    plan_dir = tmp_path / "docs" / "plans" / pid
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_PLAN_MD.format(pid=pid))
    (plan_dir / "features.json").write_text(
        json.dumps({"task_id": pid, "schema_version": "1.0", "features": features}, indent=2)
        + "\n"
    )
    return plan_dir


_CLEAN = {
    "id": "F001",
    "category": "tooling",
    "phase": 0,
    "description": "a small single-surface helper",
    "steps": ["write it"],
    "acceptance": "(1) the helper returns a typed result",
    "passes": False,
    "depends_on": [],
}
# 2 surfaces -> a warn-severity over_surface flag = lint uncertainty.
_UNCERTAIN = {
    **_CLEAN,
    "description": "a cli subcommand that also renders a dashboard html view",
    "acceptance": "(1) the cli runs (2) the dashboard renders",
}


def _stub_runner(plan_id, features, **kwargs):
    # Records the call + returns a canned envelope; NO executor dispatch.
    _stub_runner.called = True
    _stub_runner.auditor = kwargs.get("auditor")
    return DesignVolleyEnvelope(verdict="signed_off", findings=[], rounds=1)


def test_clean_plan_skips_design_volley(tmp_path):
    plan_dir = _make_plan(tmp_path, "2026-06-01-905-feat-clean", [_CLEAN])
    _stub_runner.called = False
    out = io.StringIO()
    with redirect_stdout(out):
        cli._run_pre_lock_design_volley(
            plan_dir,
            operator_requested=False,
            executor=object(),
            run_volley=_stub_runner,
        )
    assert _stub_runner.called is False
    assert "skipped" in out.getvalue()


def test_operator_requested_runs_design_volley_with_injected_executor(tmp_path):
    plan_dir = _make_plan(tmp_path, "2026-06-01-906-feat-req", [_CLEAN])
    _stub_runner.called = False
    sentinel = object()
    out = io.StringIO()
    with redirect_stdout(out):
        cli._run_pre_lock_design_volley(
            plan_dir,
            operator_requested=True,  # explicit request forces the run
            executor=sentinel,
            run_volley=_stub_runner,
        )
    assert _stub_runner.called is True
    assert _stub_runner.auditor is sentinel  # injected executor used, no live call
    assert "verdict=signed_off" in out.getvalue()


def test_lint_uncertainty_auto_runs_design_volley(tmp_path):
    plan_dir = _make_plan(tmp_path, "2026-06-01-907-feat-uncertain", [_UNCERTAIN])
    _stub_runner.called = False
    out = io.StringIO()
    with redirect_stdout(out):
        cli._run_pre_lock_design_volley(
            plan_dir,
            operator_requested=False,  # not requested, but lint is uncertain
            executor=object(),
            run_volley=_stub_runner,
        )
    assert _stub_runner.called is True


def test_recommends_when_uncertain_but_no_executor(tmp_path, monkeypatch):
    plan_dir = _make_plan(tmp_path, "2026-06-01-908-feat-noexec", [_UNCERTAIN])
    # Force "no executor available" deterministically (codex may be installed
    # in this env, so pin the resolver to None).
    monkeypatch.setattr(cli, "_resolve_design_executor", lambda plan_dir: None)
    out = io.StringIO()
    with redirect_stdout(out):
        cli._run_pre_lock_design_volley(
            plan_dir, operator_requested=True, executor=None, run_volley=_stub_runner
        )
    assert "RECOMMENDED" in out.getvalue()
