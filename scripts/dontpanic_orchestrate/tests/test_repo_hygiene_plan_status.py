"""Plan 2026-08-09-001 F004 — plan-status drift, operationally honest commands.

A fixture tree with an all-passing active plan, all-passing draft, all-passing
blocked, all-passing completed, partially-passing active, and schema-invalid
plan yields: one command-resolvable item (active; exact_command passes token
validation AND close_plan dry-run), two explanation-only status items (draft,
blocked), zero for completed and partial, and one plan_unparseable advisory.

Run: PYTHONPATH=scripts /opt/homebrew/bin/pytest \\
  scripts/dontpanic_orchestrate/tests/test_repo_hygiene_plan_status.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import completion_gate
from dontpanic_orchestrate import operator_console as oc
from dontpanic_orchestrate import repo_hygiene as rh
from dontpanic_orchestrate.command_validation import validate_command_tokens


def _feature(fid: str, *, passes: bool) -> dict:
    feature: dict = {
        "id": fid,
        "category": "test",
        "phase": 0,
        "description": "synthetic plan-status fixture feature",
        "steps": ["scripted"],
        "acceptance": "ok",
        "passes": passes,
        "depends_on": [],
    }
    if passes:
        feature |= {
            "verified_by": ["codex"],
            "verified_at": "2026-08-09T00:00:00Z",
            "evidence_refs": [
                {"type": "audit_json", "uri": f"./audit/codex-auditor-{fid}-i0.json"}
            ],
        }
    return feature


def _write_plan(
    plans_root: Path,
    plan_id: str,
    *,
    status: str,
    features: list[dict] | None = None,
    invalid: bool = False,
) -> Path:
    plan_dir = plans_root / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: Synthetic {plan_id}
description: Synthetic plan-status fixture.
type: infra
tier: trivial
status: {status}
date: "2026-08-09"
agents_required:
  - claude
human_gates: []
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# Synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""
    )
    if invalid:
        (plan_dir / "features.json").write_text("{this is not json\n")
    else:
        (plan_dir / "features.json").write_text(
            json.dumps(
                {
                    "task_id": plan_id,
                    "schema_version": "1.0",
                    "features": features
                    or [_feature("F001", passes=True), _feature("F002", passes=True)],
                },
                indent=2,
            )
            + "\n"
        )
    return plan_dir


def _fixture_tree(tmp_path: Path) -> Path:
    plans = tmp_path / "docs" / "plans"
    _write_plan(plans, "2026-08-09-100-feat-active-done", status="active")
    _write_plan(plans, "2026-08-09-101-feat-draft-done", status="draft")
    _write_plan(plans, "2026-08-09-102-feat-blocked-done", status="blocked")
    _write_plan(plans, "2026-08-09-103-feat-completed-done", status="completed")
    _write_plan(
        plans,
        "2026-08-09-104-feat-active-partial",
        status="active",
        features=[_feature("F001", passes=True), _feature("F002", passes=False)],
    )
    _write_plan(plans, "2026-08-09-105-feat-unparseable", status="active", invalid=True)
    return plans


def test_plan_status_fixture_yields_expected_items(tmp_path: Path) -> None:
    plans = _fixture_tree(tmp_path)
    findings = rh.observe_plans(plans)
    items = oc.provide_repo_hygiene_actions(findings=findings, now="2026-08-09T00:00:00Z")

    by_plan: dict[str, oc.ActionItem] = {}
    unparseable: list[oc.ActionItem] = []
    for it in items:
        if "plan_unparseable" in it.id:
            unparseable.append(it)
            continue
        if it.plan_id:
            by_plan[it.plan_id] = it

    active = by_plan["2026-08-09-100-feat-active-done"]
    assert active.exact_command == "dontpanic plan close 2026-08-09-100-feat-active-done"
    tokens = active.exact_command.removeprefix("dontpanic ").split()
    assert validate_command_tokens(tokens).ok
    result = completion_gate.close_plan(
        plans / "2026-08-09-100-feat-active-done", dry_run=True
    )
    assert result.status_flipped is False
    assert active.resolution_class == "command_resolvable"

    draft = by_plan["2026-08-09-101-feat-draft-done"]
    assert draft.exact_command is None
    assert "lock" in (draft.detail or "").lower()

    blocked = by_plan["2026-08-09-102-feat-blocked-done"]
    assert blocked.exact_command is None
    assert "block" in (blocked.detail or "").lower()

    assert "2026-08-09-103-feat-completed-done" not in by_plan
    assert "2026-08-09-104-feat-active-partial" not in by_plan

    assert len(unparseable) == 1
    assert unparseable[0].exact_command is None
    assert unparseable[0].band == oc.Band.ADVISORY
    assert "2026-08-09-105-feat-unparseable" in unparseable[0].id

    command_resolvable = [it for it in items if it.exact_command]
    assert len(command_resolvable) == 1


def test_ready_for_audit_and_in_audit_are_explanation_only(tmp_path: Path) -> None:
    plans = tmp_path / "docs" / "plans"
    _write_plan(plans, "2026-08-09-106-feat-rfa", status="ready_for_audit")
    _write_plan(plans, "2026-08-09-107-feat-inaudit", status="in_audit")
    items = oc.provide_repo_hygiene_actions(
        findings=rh.observe_plans(plans), now="2026-08-09T00:00:00Z"
    )
    assert len(items) == 2
    assert all(it.exact_command is None for it in items)
    details = " ".join((it.detail or "") + it.title for it in items).lower()
    assert "audit" in details
