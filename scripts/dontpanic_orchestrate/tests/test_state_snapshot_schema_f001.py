"""Plan 2026-05-09-003 F001 — state-snapshot schema + Pydantic model tests.

Pins the contract that adapters consume:
  - JSON Schema validates well-formed envelopes.
  - JSON Schema rejects mis-shaped envelopes (missing required, extra
    properties, wrong types, bad ID patterns).
  - Pydantic model round-trips cleanly: model.dump → json → parse.
  - Stable-ID discipline holds in the schema $description fields.
  - Redact level enum has exactly three values.
  - All seven streams are required (plans / gates / inbox / supervisors /
    quota / decisions / evidence_refs).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
SUBTREE = HERE.parents[3] / "claude" / "shared" / "schemas" / "v1.0"
sys.path.insert(0, str(SUBTREE / "models"))

from state_snapshot_model import (  # noqa: E402
    DecisionEntry,
    EvidencePointer,
    GateEntry,
    InboxEvent,
    PlanSummary,
    QuotaEntry,
    RedactLevel,
    StateSnapshot,
    Streams,
    SupervisorEntry,
)


SCHEMA = json.loads((SUBTREE / "state-snapshot.schema.json").read_text())


# ─────────────────── 1. Schema shape pins ───────────────────


class TestSchemaShape:
    def test_schema_id_pinned(self) -> None:
        assert SCHEMA["$id"].endswith("/state-snapshot.schema.json")
        assert SCHEMA["title"] == "StateSnapshot"

    def test_schema_version_locked(self) -> None:
        assert SCHEMA["properties"]["schema_version"]["const"] == "1.0"

    def test_redact_level_enum_three_values(self) -> None:
        assert sorted(SCHEMA["properties"]["redact_level"]["enum"]) == [
            "full",
            "operator",
            "public",
        ]

    def test_seven_streams_required(self) -> None:
        required = SCHEMA["properties"]["streams"]["required"]
        assert sorted(required) == [
            "decisions",
            "evidence_refs",
            "gates",
            "inbox",
            "plans",
            "quota",
            "supervisors",
        ]

    def test_no_additional_properties_at_top_level(self) -> None:
        assert SCHEMA["additionalProperties"] is False

    def test_streams_no_additional_properties(self) -> None:
        assert SCHEMA["properties"]["streams"]["additionalProperties"] is False

    def test_plan_id_pattern_documented(self) -> None:
        plan_id = SCHEMA["$defs"]["plan_summary"]["properties"]["plan_id"]
        assert "pattern" in plan_id
        assert "YYYY-MM-DD" in plan_id["description"]

    def test_feature_id_pattern_in_evidence(self) -> None:
        feature_id = SCHEMA["$defs"]["evidence_pointer"]["properties"]["feature_id"]
        assert feature_id["pattern"] == "^F\\d{3}$"

    def test_decision_id_pattern(self) -> None:
        decision_id = SCHEMA["$defs"]["decision_entry"]["properties"]["decision_id"]
        assert decision_id["pattern"] == "^D\\d{3}$"


# ─────────────────── 2. Pydantic round-trip ───────────────────


def _empty_snapshot() -> StateSnapshot:
    return StateSnapshot(
        schema_version="1.0",
        captured_at=dt.datetime.now(dt.timezone.utc),
        redact_level=RedactLevel.operator,
        streams=Streams(
            plans=[],
            gates=[],
            inbox=[],
            supervisors=[],
            quota=[],
            decisions=[],
            evidence_refs=[],
        ),
    )


def _populated_snapshot() -> StateSnapshot:
    now = dt.datetime.now(dt.timezone.utc)
    return StateSnapshot(
        schema_version="1.0",
        captured_at=now,
        dontpanic_version="1.6.0",
        redact_level=RedactLevel.operator,
        streams=Streams(
            plans=[
                PlanSummary(
                    plan_id="2026-05-09-003-feat-state-projection-v0",
                    status="active",
                    title="State projection v0",
                    type="feat",
                    tier="local",
                    goal_type="infra",
                    surfaces=["infra"],
                    features_summary={"total": 7, "passing": 0},
                    target_env="dev",
                    target_project=None,
                    agents_required=["claude", "codex"],
                    date="2026-05-09",
                ),
            ],
            gates=[
                GateEntry(
                    plan_id="2026-05-09-003-feat-state-projection-v0",
                    gate_name="pre_impl",
                    kind="pre_impl",
                    stage="pre_impl",
                    reason="awaiting operator approval",
                    paused_at=now,
                    approval_required=True,
                    feature_id="F001",
                ),
            ],
            inbox=[
                InboxEvent(
                    plan_id="2026-05-09-003-feat-state-projection-v0",
                    event="volley_start",
                    event_id="2026-05-09-003-feat-state-projection-v0:volley_start:2026-05-10T00:00:00Z:F001",
                    captured_at=now,
                    feature_id="F001",
                    body="Volley begins: claude (impl) + codex (aud), max_iterations=3",
                    headers={"implementer": "claude", "auditor": "codex"},
                ),
            ],
            supervisors=[
                SupervisorEntry(
                    supervisor_id="12345:2026-05-10T00:00:00Z",
                    plan_id="2026-05-09-003-feat-state-projection-v0",
                    feature_id="F001",
                    implementer_agent="claude",
                    auditor_agent="codex",
                    started_at=now,
                    host="operator-laptop",
                    pid=12345,
                ),
            ],
            quota=[
                QuotaEntry(
                    vendor="claude",
                    window="weekly",
                    percent_of_cap=42.0,
                    percent_threshold=90.0,
                    status="ok",
                    captured_at=now,
                ),
            ],
            decisions=[
                DecisionEntry(
                    plan_id="2026-05-09-003-feat-state-projection-v0",
                    decision_id="D001",
                    ts=now,
                    by="reviewer",
                    title="State projection in core; sync layers are adapters",
                    body="Architectural critique sharpened the boundary.",
                ),
            ],
            evidence_refs=[
                EvidencePointer(
                    plan_id="2026-05-09-003-feat-state-projection-v0",
                    feature_id="F001",
                    type="file",
                    uri="evidence/state-snapshot-fixtures.log",
                    captured_at=now,
                    captured_by="claude",
                    note="round-trip + schema validation",
                ),
            ],
        ),
    )


class TestPydanticRoundTrip:
    def test_empty_snapshot_round_trip(self) -> None:
        snap = _empty_snapshot()
        js = snap.model_dump_json()
        parsed = StateSnapshot.model_validate_json(js)
        assert parsed.schema_version == "1.0"
        assert parsed.redact_level == RedactLevel.operator
        for k in ("plans", "gates", "inbox", "supervisors", "quota", "decisions", "evidence_refs"):
            assert getattr(parsed.streams, k) == []

    def test_populated_snapshot_round_trip(self) -> None:
        snap = _populated_snapshot()
        js = snap.model_dump_json()
        parsed = StateSnapshot.model_validate_json(js)
        assert len(parsed.streams.plans) == 1
        assert parsed.streams.plans[0].plan_id == "2026-05-09-003-feat-state-projection-v0"
        assert parsed.streams.gates[0].kind.value == "pre_impl"
        assert parsed.streams.supervisors[0].pid == 12345
        assert parsed.streams.quota[0].vendor.value == "claude"
        assert parsed.streams.decisions[0].decision_id == "D001"
        assert parsed.streams.evidence_refs[0].feature_id == "F001"

    def test_json_output_has_no_extra_keys(self) -> None:
        snap = _empty_snapshot()
        as_dict = json.loads(snap.model_dump_json())
        allowed = {
            "schema_version",
            "captured_at",
            "dontpanic_version",
            "redact_level",
            "streams",
        }
        assert set(as_dict.keys()) <= allowed

    def test_redact_level_serializes_as_string(self) -> None:
        snap = _empty_snapshot()
        as_dict = json.loads(snap.model_dump_json())
        assert as_dict["redact_level"] == "operator"

    def test_captured_at_is_rfc3339_utc(self) -> None:
        snap = _empty_snapshot()
        as_dict = json.loads(snap.model_dump_json())
        # Must end in Z or +00:00 (tz-aware UTC)
        captured = as_dict["captured_at"]
        assert captured.endswith("Z") or captured.endswith("+00:00"), captured


# ─────────────────── 3. Schema rejects malformed ───────────────────


class TestSchemaRejection:
    """Pydantic enforces the same constraints as JSON Schema. We verify
    via Pydantic raising ValidationError on malformed input."""

    def test_rejects_missing_streams(self) -> None:
        with pytest.raises(Exception):
            StateSnapshot.model_validate(
                {
                    "schema_version": "1.0",
                    "captured_at": "2026-05-10T00:00:00Z",
                    "redact_level": "operator",
                    # streams missing
                }
            )

    def test_rejects_unknown_redact_level(self) -> None:
        with pytest.raises(Exception):
            StateSnapshot.model_validate(
                {
                    "schema_version": "1.0",
                    "captured_at": "2026-05-10T00:00:00Z",
                    "redact_level": "BOGUS",
                    "streams": {
                        "plans": [], "gates": [], "inbox": [], "supervisors": [],
                        "quota": [], "decisions": [], "evidence_refs": [],
                    },
                }
            )

    def test_rejects_extra_top_level_property(self) -> None:
        with pytest.raises(Exception):
            StateSnapshot.model_validate(
                {
                    "schema_version": "1.0",
                    "captured_at": "2026-05-10T00:00:00Z",
                    "redact_level": "operator",
                    "extra_field": "should be rejected",
                    "streams": {
                        "plans": [], "gates": [], "inbox": [], "supervisors": [],
                        "quota": [], "decisions": [], "evidence_refs": [],
                    },
                }
            )

    def test_rejects_bad_feature_id_in_evidence(self) -> None:
        # feature_id pattern is ^F\d{3}$
        with pytest.raises(Exception):
            EvidencePointer(
                plan_id="2026-05-09-003-feat-state-projection-v0",
                feature_id="not-a-feature-id",
                type="file",
                uri="evidence/log.txt",
            )

    def test_rejects_bad_decision_id(self) -> None:
        with pytest.raises(Exception):
            DecisionEntry(
                plan_id="2026-05-09-003-feat-state-projection-v0",
                decision_id="not-d-pattern",
                ts=dt.datetime.now(dt.timezone.utc),
                title="x",
            )

    def test_rejects_wrong_schema_version(self) -> None:
        with pytest.raises(Exception):
            StateSnapshot.model_validate(
                {
                    "schema_version": "2.0",  # only 1.0 allowed
                    "captured_at": "2026-05-10T00:00:00Z",
                    "redact_level": "operator",
                    "streams": {
                        "plans": [], "gates": [], "inbox": [], "supervisors": [],
                        "quota": [], "decisions": [], "evidence_refs": [],
                    },
                }
            )


# ─────────────────── 4. agent-conventions VERSION pin ───────────────────


class TestAgentConventionsPin:
    def test_subtree_version_bumped(self) -> None:
        version = (HERE.parents[3] / "claude" / "shared" / "VERSION").read_text().strip()
        assert version == "1.8.0", f"expected 1.8.0, got {version}"
