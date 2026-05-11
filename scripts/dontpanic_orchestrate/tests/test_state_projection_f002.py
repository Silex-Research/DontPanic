"""Plan 2026-05-09-003 F002 — state_projection.gather() tests.

Pins the gather() contract:
  - Returns a StateSnapshot (F001 schema) for an arbitrary plan_dir_root.
  - Empty plans dir returns valid envelope with empty arrays (not error).
  - All 7 streams gather correctly from canonical sources.
  - `include` filter skips unselected streams.
  - `plan_id` filter scopes to a single plan.
  - Pure-read invariant: filesystem mtime/size hash unchanged after gather.
  - Round-trips through Pydantic + JSON.
  - redact_level threaded but no-op in F002 (F003 owns the actual policy).
  - Newest-first sorting on inbox + decisions.
  - Missing optional artifacts (gate-state.json, INBOX.md, decisions.jsonl,
    quota_state.json) handled gracefully — never raise.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import textwrap
from collections.abc import Iterable
from pathlib import Path

import pytest

# Make state_projection importable from this test module.
HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

# Pydantic model subtree
SUBTREE = ROOT / "claude" / "shared" / "schemas" / "v1.0"
sys.path.insert(0, str(SUBTREE / "models"))

from dontpanic_orchestrate import (  # noqa: E402
    active_supervisors,
    state_projection,
)
from state_snapshot_model import StateSnapshot  # noqa: E402


# ─────────────────────────── helpers ───────────────────────────


def _fingerprint_tree(root: Path) -> str:
    """Hash every file's (relative-path, size, mtime_ns) under root.

    Used to assert gather() is pure-read: fingerprint pre-call equals
    fingerprint post-call. If gather touches any file, mtime_ns shifts.
    """
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            rel = p.relative_to(root).as_posix()
            h.update(f"{rel}|{st.st_size}|{st.st_mtime_ns}".encode())
    return h.hexdigest()


def _write_plan(
    plans_root: Path,
    plan_id: str,
    *,
    title: str = "Test plan",
    type_: str = "feat",
    tier: str = "local",
    status: str = "active",
    date: str = "2026-05-10",
    goal_type: str = "infra",
    surfaces: list[str] | None = None,
    agents_required: list[str] | None = None,
    human_gates: list[str] | None = None,
    features: list[dict] | None = None,
    decisions: list[dict] | None = None,
    inbox_events: list[dict] | None = None,
    cleared_gates: list[str] | None = None,
) -> Path:
    """Write a minimal valid plan dir. Returns the plan dir path."""
    plan_dir = plans_root / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)

    surfaces = surfaces or ["infra"]
    agents = agents_required or ["claude", "codex"]
    gates = human_gates or ["pre_impl", "pre_merge"]

    surfaces_yaml = "\n".join(f"  - {s}" for s in surfaces)
    agents_yaml = "\n".join(f"  - {a}" for a in agents)
    gates_yaml = "\n".join(f"  - {g}" for g in gates)

    frontmatter = (
        "---\n"
        f"id: {plan_id}\n"
        f"title: {title}\n"
        f"type: {type_}\n"
        f"tier: {tier}\n"
        f"status: {status}\n"
        f"date: \"{date}\"\n"
        f"goal_type: {goal_type}\n"
        "surfaces:\n"
        f"{surfaces_yaml}\n"
        "agents_required:\n"
        f"{agents_yaml}\n"
        "human_gates:\n"
        f"{gates_yaml}\n"
        "loop_caps:\n"
        "  max_iterations: 3\n"
        "  no_progress_threshold: 2\n"
        "  wall_clock_hours: 4\n"
        "  hard_stop: false\n"
        "privacy_tier: internal\n"
        "links:\n"
        "  features: ./features.json\n"
        "  decisions: ./decisions.jsonl\n"
        "  evidence_dir: ./evidence/\n"
        "description: |\n"
        f"  Synthetic test plan {plan_id}.\n"
        "motivation: |\n"
        "  Fixture for state_projection tests.\n"
        "---\n"
        "\n"
        f"# {title}\n"
        "\n"
        "## Target\n"
        "\n"
        "```yaml\n"
        "target_env: dev\n"
        "target_project: none\n"
        "```\n"
        "\n"
        "## Acceptance Summary\n"
        "\n"
        "- Fixture.\n"
    )
    (plan_dir / "plan.md").write_text(frontmatter)

    features = features if features is not None else [
        {
            "id": "F001",
            "category": "infra",
            "phase": 1,
            "description": "Fixture feature.",
            "steps": ["Do the thing."],
            "acceptance": "Thing done.",
            "passes": False,
            "depends_on": [],
        }
    ]
    (plan_dir / "features.json").write_text(
        json.dumps(
            {"task_id": plan_id, "schema_version": "1.0", "features": features},
            indent=2,
        )
    )

    if decisions is not None:
        with (plan_dir / "decisions.jsonl").open("w") as f:
            for d in decisions:
                f.write(json.dumps(d) + "\n")

    if inbox_events is not None:
        # Use the canonical INBOX writer to match the parser's expected
        # shape (preamble + per-event blocks). Avoids fixture/format drift.
        from dontpanic_orchestrate import inbox as _inbox_mod
        for ev in inbox_events:
            _inbox_mod.append_event(
                plan_dir,
                ev["event"],
                plan_id=plan_id,
                body=ev.get("body", ""),
                timestamp=ev["timestamp"],
                **ev.get("headers", {}),
            )

    if cleared_gates is not None:
        audit_dir = plan_dir / "audit"
        audit_dir.mkdir(exist_ok=True)
        gate_state = {
            "plan_id": plan_id,
            "cleared_gates": cleared_gates,
            "history": [
                {
                    "action": "approve",
                    "gate": g,
                    "at": "2026-05-10T00:00:00Z",
                    "actor": "operator",
                }
                for g in cleared_gates
            ],
        }
        (audit_dir / "gate-state.json").write_text(json.dumps(gate_state, indent=2))

    (plan_dir / "evidence").mkdir(exist_ok=True)
    return plan_dir


@pytest.fixture
def empty_quota_state(tmp_path: Path) -> Path:
    """Empty quota_state.json — valid shape, no vendors with data yet."""
    p = tmp_path / "quota_state.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "generated": "2026-05-10T00:00:00+00:00",
                "week_start": "2026-05-04T00:00:00+00:00",
                "vendors": {},
                "models": {},
            }
        )
    )
    return p


@pytest.fixture
def realistic_quota_state(tmp_path: Path) -> Path:
    p = tmp_path / "quota_state.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "generated": "2026-05-10T00:00:00+00:00",
                "week_start": "2026-05-04T00:00:00+00:00",
                "vendors": {
                    "claude": {
                        "tier": "max_20x",
                        "tier_signal": "operator_config",
                        "windows": {
                            "rolling_7d": {
                                "kind": "rolling_7d",
                                "observed_native": 1_000_000.0,
                                "observed_unit": "weighted_tokens",
                                "models": {},
                                "percent_of_cap": 42.0,
                                "status": "ok",
                            },
                            "rolling_5h": {
                                "kind": "rolling_5h",
                                "observed_native": 50_000.0,
                                "status": "ok",
                            },
                        },
                    },
                    "codex": {
                        "tier": "free",
                        "windows": {
                            "rolling_7d": {
                                "kind": "rolling_7d",
                                "observed_native": 0,
                                "status": "calibration_required",
                            },
                        },
                    },
                },
            }
        )
    )
    return p


@pytest.fixture
def isolated_supervisors_registry(tmp_path: Path, monkeypatch):
    """Redirect active_supervisors registry to a tmp file so we don't
    contaminate the real ~/.jarvis/active_supervisors.jsonl during tests."""
    reg = tmp_path / "active_supervisors.jsonl"
    monkeypatch.setattr(active_supervisors, "REGISTRY_PATH", reg)
    return reg


# ─────────────────────────── 1. envelope shape ───────────────────────────


class TestGatherEnvelope:
    def test_empty_plans_root_returns_valid_envelope(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        assert isinstance(snap, StateSnapshot)
        assert snap.schema_version == "1.0"
        assert snap.streams.plans == []
        assert snap.streams.gates == []
        assert snap.streams.inbox == []
        assert snap.streams.supervisors == []
        assert snap.streams.decisions == []
        assert snap.streams.evidence_refs == []

    def test_captured_at_is_tz_aware_utc(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        assert snap.captured_at.tzinfo is not None
        assert snap.captured_at.utcoffset() == dt.timedelta(0)

    def test_round_trip_through_json(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        js = snap.model_dump_json()
        parsed = StateSnapshot.model_validate_json(js)
        assert parsed.streams.plans == []


# ─────────────────────────── 2. plans stream ───────────────────────────


class TestPlansStream:
    def test_single_plan_surfaces(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(plans_root, "2026-05-10-001-feat-fixture", title="Fixture A")
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        assert len(snap.streams.plans) == 1
        p = snap.streams.plans[0]
        assert p.plan_id == "2026-05-10-001-feat-fixture"
        assert p.title == "Fixture A"
        assert p.features_summary.total == 1
        assert p.features_summary.passing == 0

    def test_multi_plan_aggregation(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(plans_root, "2026-05-10-001-feat-alpha", title="Alpha")
        _write_plan(plans_root, "2026-05-10-002-feat-beta", title="Beta")
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        ids = sorted(p.plan_id for p in snap.streams.plans)
        assert ids == [
            "2026-05-10-001-feat-alpha",
            "2026-05-10-002-feat-beta",
        ]

    def test_features_passing_count(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(
            plans_root,
            "2026-05-10-003-feat-mixed",
            features=[
                {
                    "id": "F001",
                    "category": "infra",
                    "phase": 1,
                    "description": "Fixture feature one.",
                    "steps": ["s"],
                    "acceptance": "a",
                    "passes": True,
                    "verified_by": ["claude"],
                    "verified_at": "2026-05-10T00:00:00Z",
                    "evidence_refs": [
                        {
                            "type": "test_output",
                            "uri": "evidence/x.log",
                            "note": "n",
                        }
                    ],
                    "depends_on": [],
                },
                {
                    "id": "F002",
                    "category": "infra",
                    "phase": 2,
                    "description": "Fixture feature two.",
                    "steps": ["s"],
                    "acceptance": "a",
                    "passes": False,
                    "depends_on": [],
                },
            ],
        )
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        assert snap.streams.plans[0].features_summary.total == 2
        assert snap.streams.plans[0].features_summary.passing == 1


# ─────────────────────────── 3. gates stream ───────────────────────────


class TestGatesStream:
    def test_unmet_gates_surface(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(
            plans_root,
            "2026-05-10-001-feat-gated",
            cleared_gates=[],
        )
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        unmet_names = {g.gate_name for g in snap.streams.gates}
        assert unmet_names == {"pre_impl", "pre_merge"}

    def test_cleared_gates_are_omitted(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(
            plans_root,
            "2026-05-10-001-feat-half-cleared",
            cleared_gates=["pre_impl"],
        )
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        unmet = [g.gate_name for g in snap.streams.gates]
        assert unmet == ["pre_merge"]


# ─────────────────────────── 4. inbox stream ───────────────────────────


class TestInboxStream:
    def test_inbox_events_surface(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(
            plans_root,
            "2026-05-10-001-feat-inboxed",
            inbox_events=[
                {
                    "timestamp": "2026-05-10T00:01:00Z",
                    "event": "volley_start",
                    "headers": {"feature_id": "F001"},
                    "body": "Volley begins",
                },
                {
                    "timestamp": "2026-05-10T00:02:00Z",
                    "event": "gate_hit",
                    "headers": {"gate": "pre_impl"},
                    "body": "Paused at pre_impl",
                },
            ],
        )
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        events = [(e.event, e.captured_at.isoformat()) for e in snap.streams.inbox]
        # Newest-first
        assert events[0][0] == "gate_hit"
        assert events[1][0] == "volley_start"

    def test_inbox_event_id_is_composite(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(
            plans_root,
            "2026-05-10-001-feat-stable-id",
            inbox_events=[
                {
                    "timestamp": "2026-05-10T00:01:00Z",
                    "event": "volley_start",
                    "headers": {"feature_id": "F001"},
                    "body": "x",
                }
            ],
        )
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        eid = snap.streams.inbox[0].event_id
        # Format: <plan_id>:<event>:<captured_at>:<feature_id-or-empty>
        assert eid.startswith("2026-05-10-001-feat-stable-id:volley_start:")
        assert eid.endswith(":F001")


# ─────────────────────────── 5. supervisors stream ───────────────────────────


class TestSupervisorsStream:
    def test_active_supervisors_surface(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry: Path
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(plans_root, "2026-05-10-001-feat-with-supervisor")
        # Register a synthetic supervisor entry. Use os.getpid() so it
        # passes the _is_pid_alive() filter inside list_active().
        active_supervisors.register(
            plan_id="2026-05-10-001-feat-with-supervisor",
            target_env="dev",
            target_project=None,
            supervisor_config_dir=str(tmp_path),
            pid=os.getpid(),
        )
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        assert len(snap.streams.supervisors) == 1
        sup = snap.streams.supervisors[0]
        assert sup.plan_id == "2026-05-10-001-feat-with-supervisor"
        # supervisor_id is composite <pid>:<started_at>
        assert sup.supervisor_id.startswith(f"{os.getpid()}:")

    def test_supervisor_host_populated(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry: Path
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(plans_root, "2026-05-10-001-feat-host")
        active_supervisors.register(
            plan_id="2026-05-10-001-feat-host",
            target_env="dev",
            target_project=None,
            supervisor_config_dir=None,
            pid=os.getpid(),
        )
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        # host should be the operator's hostname at operator/full redact level
        assert snap.streams.supervisors[0].host is not None


# ─────────────────────────── 6. quota stream ───────────────────────────


class TestQuotaStream:
    def test_quota_vendors_project_to_entries(
        self,
        tmp_path: Path,
        realistic_quota_state: Path,
        isolated_supervisors_registry,
    ) -> None:
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        snap = state_projection.gather(
            plans_root, quota_state_path=realistic_quota_state
        )
        # Two vendors × two windows = 3 entries (codex only has rolling_7d)
        # claude × {rolling_7d, rolling_5h} → 2; codex × {rolling_7d} → 1
        vendor_windows = sorted(
            (q.vendor.value, q.window.value) for q in snap.streams.quota
        )
        assert ("claude", "weekly") in vendor_windows  # rolling_7d → weekly
        assert ("codex", "weekly") in vendor_windows

    def test_missing_quota_file_yields_empty_stream(
        self, tmp_path: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        snap = state_projection.gather(
            plans_root, quota_state_path=tmp_path / "nonexistent.json"
        )
        assert snap.streams.quota == []


# ─────────────────────────── 7. decisions stream ───────────────────────────


class TestDecisionsStream:
    def test_decisions_aggregate_newest_first(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(
            plans_root,
            "2026-05-10-001-feat-decided",
            decisions=[
                {
                    "id": "D001",
                    "ts": "2026-05-10T00:01:00Z",
                    "by": "operator",
                    "title": "First",
                    "body": "Body 1",
                },
                {
                    "id": "D002",
                    "ts": "2026-05-10T00:02:00Z",
                    "by": "claude",
                    "title": "Second",
                    "body": "Body 2",
                },
            ],
        )
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        titles = [d.title for d in snap.streams.decisions]
        # Newest-first
        assert titles == ["Second", "First"]


# ─────────────────────────── 8. evidence_refs stream ───────────────────────────


class TestEvidenceRefsStream:
    def test_evidence_refs_extracted_from_features(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(
            plans_root,
            "2026-05-10-001-feat-with-evidence",
            features=[
                {
                    "id": "F001",
                    "category": "infra",
                    "phase": 1,
                    "description": "Fixture feature one.",
                    "steps": ["s"],
                    "acceptance": "a",
                    "passes": True,
                    "verified_by": ["claude"],
                    "verified_at": "2026-05-10T00:00:00Z",
                    "evidence_refs": [
                        {
                            "type": "test_output",
                            "uri": "evidence/run.log",
                            "note": "passed",
                        },
                        {
                            "type": "commit",
                            "uri": "abc1234",
                            "note": "F001 close-out",
                        },
                    ],
                    "depends_on": [],
                }
            ],
        )
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        assert len(snap.streams.evidence_refs) == 2
        types = sorted(e.type.value for e in snap.streams.evidence_refs)
        assert types == ["commit", "test_output"]
        feat_ids = {e.feature_id for e in snap.streams.evidence_refs}
        assert feat_ids == {"F001"}


# ─────────────────────────── 9. include filter ───────────────────────────


class TestIncludeFilter:
    def test_include_only_plans_skips_other_streams(
        self,
        tmp_path: Path,
        realistic_quota_state: Path,
        isolated_supervisors_registry,
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(
            plans_root,
            "2026-05-10-001-feat-include-filter",
            decisions=[
                {
                    "id": "D001",
                    "ts": "2026-05-10T00:00:00Z",
                    "by": "operator",
                    "title": "x",
                    "body": "y",
                }
            ],
        )
        snap = state_projection.gather(
            plans_root,
            quota_state_path=realistic_quota_state,
            include=("plans",),
        )
        assert len(snap.streams.plans) == 1
        # All other streams must be empty
        assert snap.streams.gates == []
        assert snap.streams.inbox == []
        assert snap.streams.supervisors == []
        assert snap.streams.quota == []
        assert snap.streams.decisions == []
        assert snap.streams.evidence_refs == []

    def test_include_unknown_stream_raises(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        with pytest.raises(ValueError, match="unknown stream"):
            state_projection.gather(
                plans_root,
                quota_state_path=empty_quota_state,
                include=("plans", "bogus_stream"),
            )


# ─────────────────────────── 10. plan_id filter ───────────────────────────


class TestPlanIdFilter:
    def test_plan_id_filter_scopes_aggregation(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(
            plans_root,
            "2026-05-10-001-feat-target",
            decisions=[
                {
                    "id": "D001",
                    "ts": "2026-05-10T00:00:00Z",
                    "by": "operator",
                    "title": "target-decision",
                    "body": "x",
                }
            ],
        )
        _write_plan(
            plans_root,
            "2026-05-10-002-feat-other",
            decisions=[
                {
                    "id": "D001",
                    "ts": "2026-05-10T00:00:00Z",
                    "by": "operator",
                    "title": "other-decision",
                    "body": "y",
                }
            ],
        )
        snap = state_projection.gather(
            plans_root,
            quota_state_path=empty_quota_state,
            plan_id="2026-05-10-001-feat-target",
        )
        plan_ids = [p.plan_id for p in snap.streams.plans]
        assert plan_ids == ["2026-05-10-001-feat-target"]
        # Decisions also scoped
        titles = [d.title for d in snap.streams.decisions]
        assert titles == ["target-decision"]


# ─────────────────────────── 11. pure-read invariant ───────────────────────────


class TestPureRead:
    def test_gather_does_not_mutate_filesystem(
        self,
        tmp_path: Path,
        realistic_quota_state: Path,
        isolated_supervisors_registry,
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(
            plans_root,
            "2026-05-10-001-feat-pure",
            decisions=[
                {
                    "id": "D001",
                    "ts": "2026-05-10T00:00:00Z",
                    "by": "operator",
                    "title": "x",
                    "body": "y",
                }
            ],
            inbox_events=[
                {
                    "timestamp": "2026-05-10T00:01:00Z",
                    "event": "volley_start",
                    "headers": {"feature_id": "F001"},
                    "body": "x",
                }
            ],
            cleared_gates=["pre_impl"],
        )
        before = _fingerprint_tree(plans_root)
        snap = state_projection.gather(
            plans_root, quota_state_path=realistic_quota_state
        )
        after = _fingerprint_tree(plans_root)
        assert before == after, (
            "state_projection.gather() mutated the plans tree; "
            "this violates the pure-read invariant in plan 2026-05-09-003"
        )
        # And the snapshot must still be well-formed
        assert isinstance(snap, StateSnapshot)


# ─────────────────────────── 12. redact_level threading ───────────────────────────


class TestRedactLevel:
    def test_redact_level_threaded_into_snapshot(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        for level in ("public", "operator", "full"):
            snap = state_projection.gather(
                plans_root,
                quota_state_path=empty_quota_state,
                redact_level=level,
            )
            assert snap.redact_level.value == level

    def test_redact_level_invalid_raises(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        with pytest.raises(ValueError, match="redact_level"):
            state_projection.gather(
                plans_root,
                quota_state_path=empty_quota_state,
                redact_level="bogus",
            )


# ─────────────────────────── 13. graceful missing artifacts ───────────────────────────


class TestGracefulMissing:
    def test_missing_inbox_does_not_raise(
        self, tmp_path: Path, empty_quota_state: Path, isolated_supervisors_registry
    ) -> None:
        plans_root = tmp_path / "plans"
        _write_plan(plans_root, "2026-05-10-001-feat-no-inbox")
        # No INBOX.md, no decisions.jsonl, no gate-state.json
        snap = state_projection.gather(
            plans_root, quota_state_path=empty_quota_state
        )
        # Plan still surfaces; inbox/decisions empty
        assert len(snap.streams.plans) == 1
        assert snap.streams.inbox == []
        assert snap.streams.decisions == []
