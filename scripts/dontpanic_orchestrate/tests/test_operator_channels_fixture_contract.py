"""Plan 2026-06-14-001 F010 — Python producer↔fixture contract (QA-sufficiency).

Guards the real-state journey: the JS Operator Channels panel boots against
``dashboard/tests/fixtures/real-state/operator-channels.json``, which is VERBATIM
output of the F009 producer (operator_channels.build_channel_view). This test
asserts the live producer STILL emits that exact object for the pinned scenario,
so the fixture can never silently drift from the producer the panel consumes.

Regenerate the fixture after an intentional producer change:
    DONTPANIC_REGEN_CHANNELS=1 pytest tests/test_operator_channels_fixture_contract.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.operator_channels import build_channel_view  # noqa: E402

FIXTURE = HERE.parents[2].parent / "dashboard" / "tests" / "fixtures" / "real-state" / "operator-channels.json"

# Pinned scenario exercising every bucket the panel renders. Timestamps are fixed
# so the JS journey's `now` (2026-06-14T12:05:00Z, within the 15-min active window
# of the 12:00 records) deterministically splits active vs stale.
SCENARIO = {
    "invocation_records": [
        # two ACTIVE records, same repo + same plan -> same_plan_conflict
        {"operator_surface": "cursor", "agent_runtime": "claude", "role": "implementer",
         "execution_locality": "plan_worktree", "locality": "plan_worktree",
         "repo": {"path_display": "<home>/proj", "path_key": "repo-main"}, "worktree": {"path_display": "<home>/wt-a", "path_key": "wt-a"},
         "branch": "feat/x", "plan": "2026-06-14-001", "last_seen": "2026-06-14T12:00:00Z", "result": "ok"},
        {"operator_surface": "codex_app", "agent_runtime": "codex", "role": "auditor",
         "execution_locality": "local_mac", "locality": "local_mac",
         "repo": {"path_display": "<home>/proj", "path_key": "repo-main"}, "worktree": None,
         "branch": "feat/y", "plan": "2026-06-14-001", "last_seen": "2026-06-14T12:01:00Z", "result": "ok"},
        # a STALE record
        {"operator_surface": "terminal", "agent_runtime": "claude", "role": "implementer",
         "execution_locality": "local_mac", "locality": "local_mac",
         "repo": {"path_display": "<home>/old", "path_key": "repo-old"}, "worktree": None,
         "branch": "main", "plan": None, "last_seen": "2020-01-01T00:00:00Z", "result": "error"},
        # an ACTIVE remote record whose repo matches an unhealthy worktree binding
        {"operator_surface": "github_agent_hq", "agent_runtime": "claude", "role": "implementer",
         "execution_locality": "github_vm", "locality": "github_vm",
         "repo": {"path_display": "<home>/wt-bad", "path_key": "wt-bad"}, "worktree": {"path_display": "<home>/wt-bad", "path_key": "wt-bad"},
         "branch": "feat/remote", "plan": "2026-06-12-001", "last_seen": "2026-06-14T12:02:00Z", "result": "ok"},
    ],
    "capability_ids": ["cursor", "claude_desktop", "codex_app", "antigravity"],
    "worktree_bindings": [
        {"path_key": "wt-a", "path_display": "<home>/wt-a", "plan": "2026-06-14-001", "branch": "feat/x", "healthy": True},
        {"path_key": "wt-bad", "path_display": "<home>/wt-bad", "plan": "2026-06-12-001", "branch": "feat/remote", "healthy": False},
    ],
    "operator_roles_map": {
        "primary_operator": {"value": "cursor", "scope": "global"},
        "auditor": {"value": "codex", "scope": "global"},
        "researcher": {"value": "gemini", "scope": "global"},  # gemini: operator-role value, NOT dispatchable
    },
    "agent_registry": ["claude", "codex"],
}


def _produced() -> dict:
    return build_channel_view(**SCENARIO)


def test_fixture_is_verbatim_producer_output() -> None:
    produced = _produced()
    if os.environ.get("DONTPANIC_REGEN_CHANNELS"):
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(produced, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    assert FIXTURE.exists(), "real-state channel-view fixture missing; regenerate with DONTPANIC_REGEN_CHANNELS=1"
    on_disk = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert on_disk == produced, "fixture drifted from the F009 producer — regenerate with DONTPANIC_REGEN_CHANNELS=1"


def test_consumed_shape_keys_present() -> None:
    produced = _produced()
    assert set(produced) >= {
        "schema", "records", "runtimes", "dispatchable_agents",
        "worktree_bindings", "operator_roles", "data_quality", "state_revision",
    }
    # the exact record fields operator-channels-logic.js reads
    for r in produced["records"]:
        assert {"locality", "repo", "branch", "plan", "last_seen"} <= set(r)
        assert "path_key" in r["repo"]
    # no home leak in the producer output the panel renders
    assert "/Users/" not in json.dumps(produced)
