"""Plan 2026-06-14-001 F009 (producer half) — channel-view producer.

A build-time producer derives a channel-view object ONLY from the enumerated
source set (D015): the invocation ledger (F003), capabilities incl operator-
surface manifests (F008), worktree bindings, operator_roles (F004), and
AGENT_REGISTRY (the sole dispatchability source). Conflict/equality uses path_key
(F003), never path_display; derivation reads only compaction-retained fields. No
agent-channels.json. supports_dispatch/dispatchability for a known runtime derive
from capabilities + AGENT_REGISTRY, not hardcoded.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import operator_channels as oc  # noqa: E402

# A raw ledger record carries non-retained fields (command, started_at, finished_at)
# that compaction drops — the producer must read ONLY the retained fields.
_RAW_RECORD = {
    "operator_surface": "cursor",
    "agent_runtime": "claude",
    "role": "implementer",
    "execution_locality": "plan_worktree",
    "locality": "plan_worktree",
    "repo": {"path_display": "<home>/r", "path_key": "repo-key-1"},
    "worktree": {"path_display": "<home>/wt", "path_key": "wt-key-1"},
    "branch": "feat/x",
    "plan": "2026-06-14-001-feat-agent-channel-interop-v0",
    "last_seen": "2026-06-14T12:00:00Z",
    "result": "ok",
    # NON-retained (must be dropped):
    "command": "plan lock --secret [REDACTED]",
    "started_at": "2026-06-14T11:59:00Z",
    "finished_at": "2026-06-14T12:00:00Z",
}

_OPERATOR_ROLES = {
    "primary_operator": {"value": "cursor", "scope": "global"},
    "researcher": {"value": "gemini", "scope": "global"},  # gemini: operator agent, NOT dispatchable
}
_BINDINGS = [
    {"path_key": "wt-key-1", "path_display": "<home>/wt", "plan": "p1", "branch": "feat/x", "healthy": True},
    {"path_key": "wt-key-2", "path_display": "<home>/wt2", "plan": "p2", "branch": "feat/y", "healthy": False},
]


def _build(agent_registry=("claude", "codex"), capability_ids=("cursor", "claude_desktop")):
    return oc.build_channel_view(
        invocation_records=[_RAW_RECORD],
        capability_ids=set(capability_ids),
        worktree_bindings=_BINDINGS,
        operator_roles_map=_OPERATOR_ROLES,
        agent_registry=set(agent_registry),
    )


def test_record_projection_keeps_only_compaction_retained_fields() -> None:
    view = _build()
    rec = view["records"][0]
    # retained axis + bucket fields present
    for k in ("operator_surface", "agent_runtime", "role", "execution_locality", "locality",
              "repo", "worktree", "branch", "plan", "last_seen", "result"):
        assert k in rec
    # non-retained raw fields dropped (never read raw deleted records)
    assert "command" not in rec
    assert "started_at" not in rec and "finished_at" not in rec


def test_conflict_equality_uses_path_key_not_display() -> None:
    view = _build()
    rec = view["records"][0]
    # repo carries a stable path_key distinct from the scrubbed display string
    assert rec["repo"]["path_key"] == "repo-key-1"
    assert rec["repo"]["path_key"] != rec["repo"]["path_display"]


def test_dispatchability_derives_from_agent_registry_not_hardcoded() -> None:
    with_codex = _build(agent_registry=("claude", "codex"))
    without_codex = _build(agent_registry=("claude",))
    rt_with = {r["id"]: r for r in with_codex["runtimes"]}
    rt_without = {r["id"]: r for r in without_codex["runtimes"]}
    # codex flips supports_dispatch purely by changing AGENT_REGISTRY — not hardcoded
    assert rt_with["codex"]["supports_dispatch"] is True
    assert rt_without["codex"]["supports_dispatch"] is False
    # AGENT_REGISTRY is the sole dispatchability source
    assert with_codex["dispatchable_agents"] == ["claude", "codex"]
    assert without_codex["dispatchable_agents"] == ["claude"]


def test_operator_role_value_runtime_surfaced_as_non_dispatchable() -> None:
    # gemini is an operator-role value but not in AGENT_REGISTRY -> a runtime row
    # exists and is supports_dispatch=False (drives operator_only_runtime_not_dispatchable)
    view = _build(agent_registry=("claude", "codex"))
    rt = {r["id"]: r for r in view["runtimes"]}
    assert "gemini" in rt
    assert rt["gemini"]["supports_dispatch"] is False


def test_embeds_operator_role_matrix_and_worktree_bindings() -> None:
    view = _build()
    assert "operator_roles" in view["operator_roles"]  # F005 matrix shape
    assert view["operator_roles"]["operator_roles"]["dispatch_authority"] is False
    keys = {b["path_key"] for b in view["worktree_bindings"]}
    assert keys == {"wt-key-1", "wt-key-2"}
    unhealthy = [b for b in view["worktree_bindings"] if not b["healthy"]]
    assert len(unhealthy) == 1


def test_schema_and_state_revision_present() -> None:
    view = _build()
    assert view["schema"] == "operator-channels/v0"
    assert isinstance(view["state_revision"], str) and len(view["state_revision"]) >= 8


def test_write_channel_view_state_emits_scrubbed_json(tmp_path) -> None:
    out = tmp_path / "operator-channels.json"
    oc.write_channel_view_state(out)
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["schema"] == "operator-channels/v0"
    assert "/Users/" not in out.read_text()  # no home-path leak in the emitted state


def test_no_agent_channels_json_introduced() -> None:
    repo_root = HERE.parents[2].parent
    offenders = [str(p) for p in repo_root.rglob("agent-channels.json")]
    assert offenders == []
