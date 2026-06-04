"""Plan 2026-06-02-001 F001 — ActionItem control-plane spine acceptance.

The spine makes :class:`operator_console.ActionItem` the single canonical
control-plane action contract. This module is the parametrized acceptance test
the feature names: it loads ActionItems from EVERY producer path and asserts the
four acceptance clauses:

  (a) every item carries audience, dedupe_key, reversible, plain_consequence,
      dashboard_url;
  (b) no ``safe_command`` field exists and exact_command + automatable encode
      command safety;
  (c) dedupe_key is producer-set and dedup (merge_with_event_sidecar + fleet
      aggregation) keys on dedupe_key, not the id-prefix;
  (d) ActionItem rejects an unvalidated exact_command at construction.

Producer paths covered (CP-D001 / CP-D002):
  * provider functions — gate / capability / reconcile / supervisor /
    architecture (operator_console);
  * Guidance.to_action_items (operations: id scheme, source=supervisor);
  * _rendered_to_action_item_dict → _action_item_from_sidecar_dict
    (supervisor: id scheme, source=supervisor);
  * dashboard_relevance.build_warning_action_items (architecture: build-warning);
  * DashboardAffordance.to_action_item (operations:dashboard-affordance).
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import dashboard_relevance as dr
from dontpanic_orchestrate import operations_guidance as og
from dontpanic_orchestrate import operator_console as oc

_FIXED_NOW = _dt.datetime(2026, 6, 2, 12, 0, 0, tzinfo=_dt.timezone.utc)
_FIXED_NOW_ISO = "2026-06-02T12:00:00Z"

# The five control-plane spine fields every ActionItem must carry (acceptance a).
_SPINE_FIELDS = (
    "audience",
    "dedupe_key",
    "reversible",
    "plain_consequence",
    "dashboard_url",
)


# ─── fixtures: minimal duck-typed inputs for the provider functions ─────────


@dataclasses.dataclass
class _FakeGate:
    plan_id: str
    gate_name: str
    kind: str | None = None
    reason: str | None = None


@dataclasses.dataclass
class _FakeCap:
    capability_id: str
    status: str
    missing: tuple[str, ...] = ()


@dataclasses.dataclass
class _FakeCapEnvelope:
    capabilities: tuple[_FakeCap, ...]


@dataclasses.dataclass
class _FakeReconcile:
    status: str
    drift_kinds: tuple[str, ...] = ()
    snapshot_path: str | None = None
    next_commands: tuple[str, ...] = ()


@dataclasses.dataclass
class _FakeSupervisor:
    pid: int
    plan_id: str
    target_env: str
    target_project: str | None = None
    started_at: str | None = None


@dataclasses.dataclass
class _FakeRendered:
    """Stand-in for event_copy.RenderedEvent fields the projection reads."""

    band: str
    title: str
    detail: str | None
    exact_command: str | None
    evidence_uri: str | None
    technical_metadata: dict


def _all_producer_items() -> list[tuple[str, oc.ActionItem]]:
    """Build one ActionItem from every producer path. Returns (label, item)."""
    items: list[tuple[str, oc.ActionItem]] = []

    # provider: gate
    for it in oc.provide_gate_actions(
        [_FakeGate(plan_id="p1", gate_name="pre_merge", reason="awaiting approval")],
        now=_FIXED_NOW,
    ):
        items.append(("provider:gate", it))

    # provider: capability
    for it in oc.provide_capability_actions(
        _FakeCapEnvelope(capabilities=(_FakeCap("git", "blocked", missing=("git",)),)),
        now=_FIXED_NOW,
    ):
        items.append(("provider:capability", it))

    # provider: reconcile
    for it in oc.provide_reconcile_actions(
        _FakeReconcile(status="drift", drift_kinds=("new_capabilities",)),
        now=_FIXED_NOW,
    ):
        items.append(("provider:reconcile", it))

    # provider: supervisor
    for it in oc.provide_supervisor_actions(
        [_FakeSupervisor(pid=4242, plan_id="p1", target_env="dev")],
        now=_FIXED_NOW,
    ):
        items.append(("provider:supervisor", it))

    # provider: architecture
    for it in oc.provide_architecture_actions(
        {"state": "stale", "output_path": "/tmp/arch.json"}, now=_FIXED_NOW
    ):
        items.append(("provider:architecture", it))

    # Guidance.to_action_items (operations: scheme, source=supervisor)
    guidance = og.build_guidance(
        "p1",
        feature_id="F001",
        signoff=og.SignoffState(
            feature_id="F001", verdict="signed_off", pre_merge_cleared=True
        ),
    )
    for it in guidance.to_action_items(updated_at=_FIXED_NOW_ISO):
        items.append(("guidance:to_action_items", it))

    # _rendered_to_action_item_dict → rehydrate (supervisor: scheme)
    rendered = _FakeRendered(
        band="needs_action",
        title="Approval needed on p1",
        detail="Operator must approve before dispatch continues.",
        exact_command="dontpanic approve p1 pre_merge",
        evidence_uri="/tmp/INBOX.md",
        technical_metadata={"plan_id": "p1", "feature_id": "F001", "inbox_event": "gate_hit"},
    )
    entry = oc._rendered_to_action_item_dict(
        rendered, source=oc.SOURCE_SUPERVISOR, updated_at=_FIXED_NOW_ISO
    )
    rehydrated = oc._action_item_from_sidecar_dict(entry)
    assert rehydrated is not None
    items.append(("rendered:sidecar_roundtrip", rehydrated))

    # dashboard_relevance build warnings
    for it in dr.build_warning_action_items(
        project_name="proj",
        display_name="Proj",
        warnings=["repo_root missing"],
        skipped=True,
        skipped_reason="repo_root does not exist",
        now_iso=_FIXED_NOW_ISO,
    ):
        items.append(("dashboard_relevance:build_warning", it))

    # DashboardAffordance.to_action_item (both running / not-running variants)
    items.append(
        (
            "affordance:not_running",
            og.DashboardAffordance(is_running=False).to_action_item(
                updated_at=_FIXED_NOW_ISO
            ),
        )
    )
    items.append(
        (
            "affordance:running",
            og.DashboardAffordance(
                is_running=True, url="http://127.0.0.1:8787"
            ).to_action_item(updated_at=_FIXED_NOW_ISO),
        )
    )
    return items


# ─── (a) every item carries the five spine fields ───────────────────────────


@pytest.mark.parametrize(
    "label, item", _all_producer_items(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_every_producer_item_carries_spine_fields(label: str, item: oc.ActionItem) -> None:
    d = item.to_dict()
    for field in _SPINE_FIELDS:
        assert field in d, f"{label}: to_dict missing {field!r}"
        assert hasattr(item, field), f"{label}: ActionItem missing attr {field!r}"
    # audience is a non-empty subset of the closed role set.
    assert item.audience, f"{label}: audience must be non-empty"
    assert set(item.audience).issubset(oc._VALID_AUDIENCES), (
        f"{label}: audience {item.audience!r} escapes the closed role set"
    )
    # dedupe_key is always present and non-empty.
    assert item.dedupe_key, f"{label}: dedupe_key must be non-empty"
    # reversible is a real bool.
    assert isinstance(item.reversible, bool), f"{label}: reversible must be bool"


# ─── (b) no safe_command; exact_command + automatable encode safety ─────────


@pytest.mark.parametrize(
    "label, item", _all_producer_items(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_no_safe_command_field_anywhere(label: str, item: oc.ActionItem) -> None:
    d = item.to_dict()
    assert "safe_command" not in d, f"{label}: safe_command leaked into to_dict"
    assert not hasattr(item, "safe_command"), f"{label}: ActionItem grew safe_command"
    # The command-safety model is exact_command + automatable, both present.
    assert "exact_command" in d
    assert "automatable" in d
    assert isinstance(item.automatable, bool)


def test_actionitem_dataclass_has_no_safe_command_field() -> None:
    names = {f.name for f in dataclasses.fields(oc.ActionItem)}
    assert "safe_command" not in names
    # The spine fields ARE declared.
    for field in _SPINE_FIELDS:
        assert field in names


# ─── (c) dedupe_key is producer-set + the dedup authority ───────────────────


def test_dedupe_key_is_producer_set_to_explicit_value() -> None:
    # Each producer sets dedupe_key explicitly (== id for current producers),
    # not derived by parsing the id-prefix.
    for label, item in _all_producer_items():
        assert item.dedupe_key == item.id, (
            f"{label}: dedupe_key {item.dedupe_key!r} != id {item.id!r}"
        )


def test_actionitem_rejects_empty_dedupe_key() -> None:
    # CP-D002: dedupe_key is the producer-set identity authority. Construction
    # must reject an empty value rather than silently aliasing it to id, so a
    # producer that forgets to set it fails loudly instead of weakening dedup.
    with pytest.raises(ValueError, match="dedupe_key is required"):
        oc.ActionItem(
            id="gate:p1:pre_merge",
            source=oc.SOURCE_GATE,
            band=oc.Band.NEEDS_ACTION,
            title="t",
            detail=None,
            exact_command=None,
            automatable=False,
            human_required_reason="x",
            evidence_uri=None,
            updated_at=_FIXED_NOW_ISO,
            # dedupe_key omitted → defaults to "" → rejected
        )


def test_merge_with_event_sidecar_dedups_on_dedupe_key(tmp_path: Path) -> None:
    # A provider item and a sidecar entry that share a dedupe_key but differ in
    # nothing-else collapse to ONE — and provider wins. We give the sidecar a
    # DIFFERENT id but the SAME dedupe_key to prove the authority is dedupe_key,
    # not id.
    provider = oc.ActionItem(
        id="gate:p1:pre_merge",
        source=oc.SOURCE_GATE,
        band=oc.Band.NEEDS_ACTION,
        title="provider-wins",
        detail=None,
        exact_command="dontpanic approve p1 pre_merge",
        automatable=False,
        human_required_reason="gate approval",
        evidence_uri=None,
        updated_at=_FIXED_NOW_ISO,
        dedupe_key="shared-key",
    )
    sidecar_entry = {
        "id": "supervisor:gate_hit:p1",  # DIFFERENT id …
        "source": oc.SOURCE_SUPERVISOR,
        "band": "needs_action",
        "title": "sidecar-loses",
        "detail": None,
        "exact_command": "dontpanic approve p1 pre_merge",
        "automatable": False,
        "human_required_reason": "operator action surfaced by dispatch_event",
        "evidence_uri": None,
        "updated_at": _FIXED_NOW_ISO,
        "dedupe_key": "shared-key",  # … but the SAME dedupe_key
    }
    sidecar = tmp_path / "event-actions.jsonl"
    sidecar.write_text(json.dumps(sidecar_entry) + "\n", encoding="utf-8")

    merged = oc.merge_with_event_sidecar([provider], sidecar_path=sidecar)
    assert len(merged) == 1, "shared dedupe_key must collapse to one item"
    assert merged[0].title == "provider-wins", "provider must win on dedupe_key conflict"


def test_merge_keeps_items_with_distinct_dedupe_keys(tmp_path: Path) -> None:
    provider = oc.ActionItem(
        id="gate:p1:pre_merge",
        source=oc.SOURCE_GATE,
        band=oc.Band.NEEDS_ACTION,
        title="g",
        detail=None,
        exact_command="dontpanic approve p1 pre_merge",
        automatable=False,
        human_required_reason="gate approval",
        evidence_uri=None,
        updated_at=_FIXED_NOW_ISO,
        dedupe_key="gate:p1:pre_merge",
    )
    sidecar_entry = {
        "id": "supervisor:gate_hit:p2",
        "source": oc.SOURCE_SUPERVISOR,
        "band": "needs_action",
        "title": "s",
        "detail": None,
        "exact_command": None,
        "automatable": False,
        "human_required_reason": "operator action surfaced by dispatch_event",
        "evidence_uri": None,
        "updated_at": _FIXED_NOW_ISO,
        "dedupe_key": "supervisor:gate_hit:p2",
    }
    sidecar = tmp_path / "event-actions.jsonl"
    sidecar.write_text(json.dumps(sidecar_entry) + "\n", encoding="utf-8")
    merged = oc.merge_with_event_sidecar([provider], sidecar_path=sidecar)
    assert len(merged) == 2


def test_aggregate_coalesces_on_dedupe_key() -> None:
    a = oc.ActionItem(
        id="id-a",
        source=oc.SOURCE_GATE,
        band=oc.Band.NEEDS_ACTION,
        title="first",
        detail=None,
        exact_command=None,
        automatable=False,
        human_required_reason="x",
        evidence_uri=None,
        updated_at=_FIXED_NOW_ISO,
        dedupe_key="same",
    )
    b = dataclasses.replace(a, id="id-b", title="second")
    merged = oc.aggregate([a], [b])
    assert len(merged) == 1
    assert merged[0].title == "second"  # last writer wins on dedupe_key


def test_fleet_aggregation_dedups_on_dedupe_key(tmp_path: Path, monkeypatch) -> None:
    # Two project caches emit items that share a dedupe_key within the SAME
    # project scope → collapse to one. Across projects (different project_name
    # scope) they are kept. This exercises projects_dashboard.build_fleet_what_now.
    from dontpanic_orchestrate import projects_dashboard as pd

    def _write_cache(dirpath: Path, item_id: str) -> Path:
        dirpath.mkdir(parents=True, exist_ok=True)
        cache = dirpath / "what-now-cache.json"
        env = {
            "schema_version": "1.0.0",
            "captured_at": _FIXED_NOW_ISO,
            "items": [
                {
                    "id": item_id,
                    "source": oc.SOURCE_GATE,
                    "band": "needs_action",
                    "title": "gate",
                    "detail": None,
                    "exact_command": "dontpanic approve p1 pre_merge",
                    "automatable": False,
                    "human_required_reason": "gate approval",
                    "evidence_uri": None,
                    "updated_at": _FIXED_NOW_ISO,
                    "dedupe_key": item_id,
                }
            ],
        }
        cache.write_text(json.dumps(env), encoding="utf-8")
        return cache

    @dataclasses.dataclass
    class _Ctx:
        name: str
        display_name: str
        dashboard_cache_path: Path
        plans_root: Path
        active: bool = True

    @dataclasses.dataclass
    class _Report:
        context: _Ctx
        skipped: bool = False
        skipped_reason: str | None = None
        warnings: tuple = ()
        build_warnings_path: Path | None = None

    cache_a = tmp_path / "a"
    _write_cache(cache_a, "gate:p1:pre_merge")
    plans_a = tmp_path / "plans_a"
    plans_a.mkdir()
    rep_a1 = _Report(context=_Ctx("projA", "Proj A", cache_a, plans_a))
    # Same project name + same dedupe_key in a second sweep → one item.
    out = tmp_path / "fleet.json"
    pd.build_fleet_what_now([rep_a1, rep_a1], captured_at=_FIXED_NOW, output_path=out)
    payload = json.loads(out.read_text())
    gate_items = [i for i in payload["items"] if i["source"] == oc.SOURCE_GATE]
    assert len(gate_items) == 1
    assert gate_items[0]["dedupe_key"] == "gate:p1:pre_merge"


# ─── (d) boundary rejection of an unvalidated exact_command ──────────────────


def test_actionitem_rejects_unvalidated_exact_command() -> None:
    with pytest.raises(ValueError, match="command validation"):
        oc.ActionItem(
            id="gate:p1:pre_merge",
            source=oc.SOURCE_GATE,
            band=oc.Band.NEEDS_ACTION,
            title="t",
            detail=None,
            exact_command="dontpanic frobnicate --nonexistent-flag",
            automatable=False,
            human_required_reason="x",
            evidence_uri=None,
            updated_at=_FIXED_NOW_ISO,
            dedupe_key="gate:p1:pre_merge",
        )


def test_actionitem_rejects_unparseable_exact_command() -> None:
    with pytest.raises(ValueError):
        oc.ActionItem(
            id="x",
            source=oc.SOURCE_GATE,
            band=oc.Band.NEEDS_ACTION,
            title="t",
            detail=None,
            exact_command="dontpanic approve 'unterminated",
            automatable=False,
            human_required_reason="x",
            evidence_uri=None,
            updated_at=_FIXED_NOW_ISO,
            dedupe_key="x",
        )


def test_actionitem_accepts_validated_exact_command() -> None:
    # A real, well-formed command constructs cleanly and strips both prefixes.
    for cmd in (
        "dontpanic approve p1 pre_merge",
        "python -m dontpanic_orchestrate calibrate-claude --window weekly --dashboard-pct 0",
    ):
        item = oc.ActionItem(
            id="gate:p1:pre_merge",
            source=oc.SOURCE_GATE,
            band=oc.Band.NEEDS_ACTION,
            title="t",
            detail=None,
            exact_command=cmd,
            automatable=False,
            human_required_reason="x",
            evidence_uri=None,
            updated_at=_FIXED_NOW_ISO,
            dedupe_key="gate:p1:pre_merge",
        )
        assert item.exact_command == cmd


def test_actionitem_allows_none_exact_command() -> None:
    item = oc.ActionItem(
        id="x",
        source=oc.SOURCE_GATE,
        band=oc.Band.NEEDS_ACTION,
        title="t",
        detail=None,
        exact_command=None,
        automatable=False,
        human_required_reason="x",
        evidence_uri=None,
        updated_at=_FIXED_NOW_ISO,
        dedupe_key="x",
    )
    assert item.exact_command is None


def test_all_producer_commands_pass_boundary_validation() -> None:
    # By construction every producer item already passed __post_init__; this
    # asserts the producers DO emit boundary-valid commands (no producer relies
    # on a command the validator would reject).
    for label, item in _all_producer_items():
        if item.exact_command is not None:
            # Re-running the validator must not raise.
            oc._validate_exact_command_or_raise(item.exact_command, item_id=item.id)
