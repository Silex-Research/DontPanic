"""Plan 2026-05-23-004 F001 — ActionItem provider model tests.

Covers:
  * Band mapping for each provider (gates, capabilities, reconcile,
    supervisors, architecture).
  * Deterministic ordering: needs_action → advisory → info → ready,
    then by source, then by id.
  * Empty-state — no inputs to any provider yields zero ActionItems
    and an empty stable JSON envelope.
  * Multi-source aggregation across all five providers.
  * No-secret invariant — the cache writer refuses to emit when any
    string in the envelope matches a known credential shape.
  * Cache file mode + parent dir tightening.

The providers all accept duck-typed inputs (Pydantic models, dataclasses,
plain dicts), so the tests intentionally use small dataclass / dict
fixtures rather than depending on the real upstream constructors.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import stat
from pathlib import Path

import pytest

from dontpanic_orchestrate import operator_console as oc

# ─── fixtures ───────────────────────────────────────────────────────────


@dataclasses.dataclass
class _FakeGate:
    plan_id: str
    gate_name: str
    kind: str
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
    target_project: str | None
    started_at: str
    supervisor_config_dir: str | None = None


_FIXED_NOW = _dt.datetime(2026, 5, 23, 12, 0, 0, tzinfo=_dt.timezone.utc)
_FIXED_NOW_ISO = "2026-05-23T12:00:00Z"


# ─── gate provider ──────────────────────────────────────────────────────


def test_gate_provider_unmet_gates_become_needs_action() -> None:
    gates = [
        _FakeGate(
            plan_id="2026-05-23-004-feat-operator-console-v0",
            gate_name="pre_impl",
            kind="pre_impl",
            reason="awaiting operator approval",
        ),
    ]
    items = oc.provide_gate_actions(gates, now=_FIXED_NOW)
    assert len(items) == 1
    item = items[0]
    assert item.source == oc.SOURCE_GATE
    assert item.band is oc.Band.NEEDS_ACTION
    assert item.id == "gate:2026-05-23-004-feat-operator-console-v0:pre_impl"
    assert "pre_impl" in item.title
    assert "2026-05-23-004" in item.title
    assert item.exact_command == (
        "dontpanic approve 2026-05-23-004-feat-operator-console-v0 pre_impl"
    )
    assert item.automatable is False
    assert item.human_required_reason == "gate approval"
    assert item.updated_at == _FIXED_NOW_ISO


def test_gate_provider_evidence_uri_points_at_plan_dir(tmp_path: Path) -> None:
    plan_dir = tmp_path / "plan-x"
    plan_dir.mkdir()
    items = oc.provide_gate_actions(
        [_FakeGate(plan_id="plan-x", gate_name="pre_merge", kind="pre_merge")],
        plan_dirs={"plan-x": plan_dir},
        now=_FIXED_NOW,
    )
    assert items[0].evidence_uri == str(plan_dir / "audit" / "gate-state.json")


def test_gate_provider_empty_input_is_empty_tuple() -> None:
    assert oc.provide_gate_actions([], now=_FIXED_NOW) == ()


# ─── capability provider ────────────────────────────────────────────────


def test_capability_band_mapping_covers_all_status_values() -> None:
    envelope = _FakeCapEnvelope(
        capabilities=(
            _FakeCap("cap-ready", "ready"),
            _FakeCap("cap-blocked", "blocked", missing=("gcloud",)),
            _FakeCap("cap-needs-setup", "needs_setup", missing=("env.FOO",)),
            _FakeCap("cap-not-installed", "not_installed"),
            _FakeCap("cap-optional", "optional"),
        ),
    )
    items = oc.provide_capability_actions(envelope, now=_FIXED_NOW)
    # ready + optional skipped; remaining three render
    by_id = {it.id: it for it in items}
    assert set(by_id) == {
        "capability:cap-blocked",
        "capability:cap-needs-setup",
        "capability:cap-not-installed",
    }
    assert by_id["capability:cap-blocked"].band is oc.Band.NEEDS_ACTION
    assert by_id["capability:cap-needs-setup"].band is oc.Band.NEEDS_ACTION
    assert by_id["capability:cap-not-installed"].band is oc.Band.ADVISORY
    # Missing tokens land in detail, never in the command string.
    assert "gcloud" in (by_id["capability:cap-blocked"].detail or "")
    assert all(it.automatable is False for it in items)


def test_capability_provider_none_envelope_is_empty() -> None:
    assert oc.provide_capability_actions(None, now=_FIXED_NOW) == ()


# ─── reconcile provider ─────────────────────────────────────────────────


def test_reconcile_clean_emits_nothing() -> None:
    assert oc.provide_reconcile_actions(
        _FakeReconcile(status="clean"), now=_FIXED_NOW
    ) == ()


def test_reconcile_missing_snapshot_is_advisory() -> None:
    items = oc.provide_reconcile_actions(
        _FakeReconcile(
            status="missing_snapshot",
            drift_kinds=("missing_snapshot",),
            snapshot_path="/home/op/.dontpanic/install-snapshot.json",
        ),
        now=_FIXED_NOW,
    )
    assert len(items) == 1
    assert items[0].band is oc.Band.ADVISORY
    assert items[0].id == "reconcile:missing_snapshot"
    assert items[0].exact_command == "dontpanic reconcile baseline --yes"
    assert items[0].evidence_uri == "/home/op/.dontpanic/install-snapshot.json"


def test_reconcile_drift_kinds_each_become_a_needs_action() -> None:
    items = oc.provide_reconcile_actions(
        _FakeReconcile(
            status="changed_capabilities",
            drift_kinds=("new_capabilities", "changed_capabilities"),
        ),
        now=_FIXED_NOW,
    )
    ids = {it.id for it in items}
    assert ids == {
        "reconcile:new_capabilities",
        "reconcile:changed_capabilities",
    }
    assert all(it.band is oc.Band.NEEDS_ACTION for it in items)


def test_reconcile_stale_status_cache_is_advisory() -> None:
    items = oc.provide_reconcile_actions(
        _FakeReconcile(status="stale_status_cache", drift_kinds=("stale_status_cache",)),
        now=_FIXED_NOW,
    )
    assert items[0].band is oc.Band.ADVISORY
    assert items[0].exact_command == "dontpanic capabilities status"


# ─── supervisor provider ────────────────────────────────────────────────


def test_supervisor_provider_emits_info_per_active_entry() -> None:
    items = oc.provide_supervisor_actions(
        [
            _FakeSupervisor(
                pid=4321,
                plan_id="plan-x",
                target_env="dev",
                target_project=None,
                started_at="2026-05-23T11:55:00Z",
            ),
        ],
        now=_FIXED_NOW,
    )
    assert len(items) == 1
    assert items[0].band is oc.Band.INFO
    assert items[0].id == "supervisor:4321:plan-x"
    assert items[0].automatable is True
    assert items[0].human_required_reason is None


def test_supervisor_provider_empty_is_empty() -> None:
    assert oc.provide_supervisor_actions([], now=_FIXED_NOW) == ()


# ─── architecture provider ──────────────────────────────────────────────


@pytest.mark.parametrize("state", ["stale", "absent"])
def test_architecture_provider_surfaces_stale_or_absent(state: str) -> None:
    items = oc.provide_architecture_actions(
        {"state": state, "output_path": "/repo/docs/architecture/architecture.json"},
        now=_FIXED_NOW,
    )
    assert len(items) == 1
    assert items[0].band is oc.Band.ADVISORY
    assert items[0].id == f"architecture:{state}"
    assert items[0].exact_command == "dontpanic architecture regen"


def test_architecture_provider_fresh_state_emits_nothing() -> None:
    assert oc.provide_architecture_actions(
        {"state": "fresh", "output_path": "/tmp/x"}, now=_FIXED_NOW
    ) == ()
    assert oc.provide_architecture_actions(None, now=_FIXED_NOW) == ()


# ─── aggregation + ordering ─────────────────────────────────────────────


def test_aggregate_orders_deterministically_across_sources() -> None:
    gates = [
        _FakeGate(plan_id="plan-a", gate_name="pre_impl", kind="pre_impl"),
        _FakeGate(plan_id="plan-b", gate_name="pre_merge", kind="pre_merge"),
    ]
    caps = _FakeCapEnvelope(
        capabilities=(_FakeCap("z-cap", "needs_setup"),),
    )
    rec = _FakeReconcile(
        status="new_capabilities", drift_kinds=("new_capabilities",)
    )
    sup = [
        _FakeSupervisor(
            pid=99,
            plan_id="plan-a",
            target_env="dev",
            target_project=None,
            started_at="2026-05-23T11:50:00Z",
        ),
    ]
    arch = {"state": "stale", "output_path": "/x.json"}

    merged = oc.aggregate(
        oc.provide_gate_actions(gates, now=_FIXED_NOW),
        oc.provide_capability_actions(caps, now=_FIXED_NOW),
        oc.provide_reconcile_actions(rec, now=_FIXED_NOW),
        oc.provide_supervisor_actions(sup, now=_FIXED_NOW),
        oc.provide_architecture_actions(arch, now=_FIXED_NOW),
    )

    # Band priority: needs_action first, then advisory, then info, then ready.
    # Within needs_action, source priority: gate < reconcile < capability.
    bands = [it.band for it in merged]
    assert bands == sorted(bands, key=lambda b: oc._BAND_PRIORITY[b])

    needs_action = [it for it in merged if it.band is oc.Band.NEEDS_ACTION]
    sources = [it.source for it in needs_action]
    assert sources == [
        oc.SOURCE_GATE,  # plan-a:pre_impl
        oc.SOURCE_GATE,  # plan-b:pre_merge
        oc.SOURCE_RECONCILE,
        oc.SOURCE_CAPABILITY,
    ]
    # Gates further sort by id.
    gate_ids = [it.id for it in merged if it.source == oc.SOURCE_GATE]
    assert gate_ids == sorted(gate_ids)

    # Same input → byte-identical envelope.
    a = oc.render_json(merged, captured_at=_FIXED_NOW)
    b = oc.render_json(merged, captured_at=_FIXED_NOW)
    assert a == b


def test_aggregate_empty_inputs_yield_stable_empty_envelope() -> None:
    merged = oc.aggregate(
        oc.provide_gate_actions([], now=_FIXED_NOW),
        oc.provide_capability_actions(None, now=_FIXED_NOW),
        oc.provide_reconcile_actions(None, now=_FIXED_NOW),
        oc.provide_supervisor_actions([], now=_FIXED_NOW),
        oc.provide_architecture_actions(None, now=_FIXED_NOW),
    )
    assert merged == ()
    payload = oc.render_envelope(merged, captured_at=_FIXED_NOW)
    assert payload == {
        "schema_version": oc.SCHEMA_VERSION,
        "captured_at": _FIXED_NOW_ISO,
        "items": [],
    }


def test_aggregate_dedupes_by_id_last_wins() -> None:
    first = oc.ActionItem(
        id="gate:plan-a:pre_impl",
        source=oc.SOURCE_GATE,
        band=oc.Band.NEEDS_ACTION,
        title="first",
        detail=None,
        exact_command="dontpanic approve plan-a pre_impl",
        automatable=False,
        human_required_reason="gate approval",
        evidence_uri=None,
        updated_at=_FIXED_NOW_ISO,
    )
    second = dataclasses.replace(first, title="second")
    merged = oc.aggregate((first,), (second,))
    assert len(merged) == 1
    assert merged[0].title == "second"


# ─── no-secret invariant ────────────────────────────────────────────────


def test_render_rejects_secret_shaped_string_in_action_field(tmp_path: Path) -> None:
    # AKIA + 16 uppercase alphanumerics → AWS access key shape.
    bad_item = oc.ActionItem(
        id="reconcile:custom",
        source=oc.SOURCE_RECONCILE,
        band=oc.Band.ADVISORY,
        title="harmless-looking title",
        # Embed a synthetic AWS access key id shape — should be rejected.
        detail="leaked AKIAIOSFODNN7EXAMPLE in detail",
        exact_command=None,
        automatable=False,
        human_required_reason="manual review",
        evidence_uri=None,
        updated_at=_FIXED_NOW_ISO,
    )
    with pytest.raises(ValueError, match="matched secret pattern"):
        oc.render_envelope((bad_item,), captured_at=_FIXED_NOW)


def test_render_clean_payload_passes_invariant() -> None:
    item = oc.ActionItem(
        id="gate:p:pre_impl",
        source=oc.SOURCE_GATE,
        band=oc.Band.NEEDS_ACTION,
        title="Gate pre_impl on p needs approval",
        detail=None,
        exact_command="dontpanic approve p pre_impl",
        automatable=False,
        human_required_reason="gate approval",
        evidence_uri=None,
        updated_at=_FIXED_NOW_ISO,
    )
    payload = oc.render_envelope((item,), captured_at=_FIXED_NOW)
    # Round-trip JSON to confirm it serializes cleanly.
    blob = json.dumps(payload, sort_keys=True)
    assert "AKIA" not in blob
    assert payload["items"][0]["id"] == "gate:p:pre_impl"


# ─── cache writer ───────────────────────────────────────────────────────


def test_write_cache_lands_at_dontpanic_dashboard_what_now_json(tmp_path: Path) -> None:
    # The autouse fixture in conftest already points DONTPANIC_HOME at a
    # per-test tmp path, so default_cache_path() resolves inside the
    # sandbox automatically.
    items = (
        oc.ActionItem(
            id="gate:p:pre_impl",
            source=oc.SOURCE_GATE,
            band=oc.Band.NEEDS_ACTION,
            title="Gate pre_impl on p needs approval",
            detail=None,
            exact_command="dontpanic approve p pre_impl",
            automatable=False,
            human_required_reason="gate approval",
            evidence_uri=None,
            updated_at=_FIXED_NOW_ISO,
        ),
    )
    target = oc.write_cache(items, captured_at=_FIXED_NOW)
    assert target.name == "what-now.json"
    assert target.parent.name == "dashboard"
    assert target.is_file()
    payload = json.loads(target.read_text())
    assert payload["schema_version"] == oc.SCHEMA_VERSION
    assert payload["items"][0]["id"] == "gate:p:pre_impl"
    # 0o600 file mode.
    assert stat.S_IMODE(target.stat().st_mode) == oc.CACHE_FILE_MODE


def test_write_cache_is_idempotent_for_same_inputs(tmp_path: Path) -> None:
    items = oc.aggregate(
        oc.provide_gate_actions(
            [_FakeGate(plan_id="p", gate_name="pre_impl", kind="pre_impl")],
            now=_FIXED_NOW,
        ),
    )
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    oc.write_cache(items, path=a, captured_at=_FIXED_NOW)
    oc.write_cache(items, path=b, captured_at=_FIXED_NOW)
    assert a.read_text() == b.read_text()


# ─── ActionItem invariants ──────────────────────────────────────────────


def test_action_item_human_required_reason_required_when_not_automatable() -> None:
    with pytest.raises(ValueError):
        oc.ActionItem(
            id="gate:p:pre_impl",
            source=oc.SOURCE_GATE,
            band=oc.Band.NEEDS_ACTION,
            title="t",
            detail=None,
            exact_command=None,
            automatable=False,
            human_required_reason=None,
            evidence_uri=None,
            updated_at=_FIXED_NOW_ISO,
        )


def test_action_item_human_required_reason_forbidden_when_automatable() -> None:
    with pytest.raises(ValueError):
        oc.ActionItem(
            id="supervisor:1:p",
            source=oc.SOURCE_SUPERVISOR,
            band=oc.Band.INFO,
            title="t",
            detail=None,
            exact_command=None,
            automatable=True,
            human_required_reason="not allowed",
            evidence_uri=None,
            updated_at=_FIXED_NOW_ISO,
        )


def test_action_item_rejects_unknown_source() -> None:
    with pytest.raises(ValueError):
        oc.ActionItem(
            id="other:1",
            source="other",
            band=oc.Band.INFO,
            title="t",
            detail=None,
            exact_command=None,
            automatable=True,
            human_required_reason=None,
            evidence_uri=None,
            updated_at=_FIXED_NOW_ISO,
        )
