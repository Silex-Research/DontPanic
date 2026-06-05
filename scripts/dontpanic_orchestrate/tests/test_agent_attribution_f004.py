"""Plan 2026-06-04-004 F004 — agent attribution from the live registry."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from dontpanic_orchestrate import state_cli, state_projection


@dataclasses.dataclass
class _Sup:
    supervisor_id: str
    plan_id: str
    feature_id: str | None = None
    implementer_agent: str | None = None
    auditor_agent: str | None = None


@dataclasses.dataclass
class _Streams:
    plans: list
    supervisors: list


@dataclasses.dataclass
class _Snap:
    streams: _Streams


def test_no_supervisors_says_none():
    snap = _Snap(_Streams(plans=[], supervisors=[]))
    attr = state_projection.agent_attribution(snap)
    assert attr["none"] is True
    assert attr["live_count"] == 0
    assert attr["attributions"] == []
    assert attr["source"] == state_projection.STREAM_PROVENANCE["supervisors"]


def test_live_supervisors_attribute_agent_to_plan():
    sups = [
        _Sup("11:t", "2026-06-04-001-x", feature_id="F002", implementer_agent="claude", auditor_agent="codex"),
        _Sup("12:t", "2026-06-04-002-y", implementer_agent="codex"),
    ]
    snap = _Snap(_Streams(plans=[], supervisors=sups))
    attr = state_projection.agent_attribution(snap)
    assert attr["none"] is False
    assert attr["live_count"] == 2
    a0 = attr["attributions"][0]
    assert a0["plan_id"] == "2026-06-04-001-x"
    assert a0["feature_id"] == "F002"
    assert a0["implementer_agent"] == "claude"
    assert a0["auditor_agent"] == "codex"


def test_attribution_live_count_equals_activity_live_now():
    # F005 will pin these together; assert the invariant holds at the source.
    @dataclasses.dataclass
    class _P:
        status: str

    sups = [_Sup("a", "p1"), _Sup("b", "p2"), _Sup("c", "p3")]
    snap = _Snap(_Streams(plans=[_P("active")], supervisors=sups))
    attr = state_projection.agent_attribution(snap)
    activity = state_projection.activity_summary(snap)
    assert attr["live_count"] == activity["live_now"] == 3


def test_manifest_attribution_block_is_none_with_isolated_home(tmp_path: Path):
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    out_dir = tmp_path / "state"
    assert (
        state_cli._export_dashboard_main(
            ["--out", str(out_dir), "--plans-root", str(plans_root)]
        )
        == 0
    )
    manifest = json.loads((out_dir / "manifest.json").read_text())
    attr = manifest["attribution"]
    assert attr["none"] is True  # no live supervisors in isolated test home
    assert attr["live_count"] == 0
