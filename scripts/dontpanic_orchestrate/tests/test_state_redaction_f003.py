"""Plan 2026-05-09-003 F003 — redaction policy tests.

Three levels: public / operator / full.

  - full      = no redaction; local-CLI-only escape hatch
  - operator  = full state, secret-shape strings replaced with [REDACTED]
                (single-source-of-truth: SECRET_REGEXES from
                sanitization_check.py)
  - public    = operator-level scrubbing PLUS per-stream stripping
                (supervisor pid/host → None, decision/inbox body → None,
                gate reason → None, quota stream → empty)

Tests use synthetic plans whose state contains known-secret literals;
assert the literals are present in `full` and absent in `public` /
`operator`. SECRET_REGEXES is imported from sanitization_check so a
single test fixture is the source-of-truth check.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "claude" / "shared" / "schemas" / "v1.0" / "models"))

from dontpanic_orchestrate import state_projection  # noqa: E402
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
    SupervisorEntry as SnapSup,
)


# Importing the canonical regex set rather than re-defining ensures the
# redactor stays in lockstep with sanitization_check if either side adds
# a new pattern.
SANITIZATION_PATH = ROOT / "scripts" / "sanitization_check.py"
sys.path.insert(0, str(ROOT / "scripts"))
from sanitization_check import SECRET_REGEXES  # noqa: E402


# Synthetic secret values matching each pattern in SECRET_REGEXES. Each
# is constructed to satisfy the corresponding regex EXACTLY so test
# assertions are deterministic.
SECRET_SAMPLES: tuple[str, ...] = (
    "AKIAIOSFODNN7EXAMPLE",                                          # AWS
    "ghp_" + "A" * 36,                                                # GitHub PAT
    "ghs_" + "B" * 36,                                                # GitHub fine-grained (server-to-server)
    "sk-ant-api03-" + "C" * 93 + "AA",                                # Anthropic
    "sk-" + "A" * 21 + "T3BlbkFJ" + "B" * 21,                         # OpenAI
    "xoxb-" + "abcdefghij1234567890",                                 # Slack
    "-----BEGIN RSA PRIVATE KEY-----",                                # PEM
    "eyJ" + "A" * 11 + "." + "B" * 11 + "." + "C" * 11,               # JWT
    "https://discord.com/api/webhooks/" + "1" * 18 + "/" + "x" * 64,  # Discord webhook (17-20 digit channel ID)
)


def _populated_snapshot_with_secrets(secret: str) -> StateSnapshot:
    """Build a snapshot whose every text field carries the synthetic
    secret so redact_to_level coverage is detectable per field."""
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    return StateSnapshot(
        schema_version="1.0",
        captured_at=now,
        redact_level=RedactLevel.full,
        streams=Streams(
            plans=[
                PlanSummary(
                    plan_id="2026-05-10-001-feat-fixture",
                    status="active",
                    title=f"Plan with secret: {secret}",
                    type="feat",
                    tier="local",
                    goal_type="infra",
                    surfaces=["infra"],
                    features_summary={"total": 1, "passing": 0},
                    target_env="dev",
                    target_project=None,
                    agents_required=["claude"],
                    date="2026-05-10",
                )
            ],
            gates=[
                GateEntry(
                    plan_id="2026-05-10-001-feat-fixture",
                    gate_name="pre_impl",
                    kind="pre_impl",
                    stage="pre_impl",
                    reason=f"Operator note leaked {secret}",
                    paused_at=now,
                    approval_required=True,
                    feature_id="F001",
                )
            ],
            inbox=[
                InboxEvent(
                    plan_id="2026-05-10-001-feat-fixture",
                    event="volley_start",
                    event_id="2026-05-10-001-feat-fixture:volley_start:1:F001",
                    captured_at=now,
                    feature_id="F001",
                    body=f"Body containing {secret}",
                    headers={"feature_id": "F001", "leaked": secret},
                )
            ],
            supervisors=[
                SnapSup(
                    supervisor_id="12345:2026-05-10T00:00:00Z",
                    plan_id="2026-05-10-001-feat-fixture",
                    feature_id="F001",
                    implementer_agent="claude",
                    auditor_agent="codex",
                    started_at=now,
                    host="operator-laptop",
                    pid=12345,
                )
            ],
            quota=[
                QuotaEntry(
                    vendor="claude",
                    window="weekly",
                    percent_of_cap=42.0,
                    percent_threshold=90.0,
                    status="ok",
                    captured_at=now,
                )
            ],
            decisions=[
                DecisionEntry(
                    plan_id="2026-05-10-001-feat-fixture",
                    decision_id="D001",
                    ts=now,
                    by="operator",
                    title=f"Decision: {secret}",
                    body=f"Body referencing {secret}",
                )
            ],
            evidence_refs=[
                EvidencePointer(
                    plan_id="2026-05-10-001-feat-fixture",
                    feature_id="F001",
                    type="file",
                    uri="evidence/F001.log",
                    captured_at=now,
                    captured_by="claude",
                    note=f"Note with {secret}",
                )
            ],
        ),
    )


# ─────────────────── 1. full level is a no-op ───────────────────


class TestFullLevel:
    @pytest.mark.parametrize("secret", SECRET_SAMPLES)
    def test_full_keeps_secrets(self, secret: str) -> None:
        snap = _populated_snapshot_with_secrets(secret)
        redacted = state_projection.redact_to_level(snap, "full")
        js = redacted.model_dump_json()
        assert secret in js, f"full level dropped a literal: {secret[:30]}..."
        # All secret-pattern regexes match somewhere
        assert any(rx.search(js) for rx in SECRET_REGEXES), (
            "no secret-pattern regex matched the snapshot at full level"
        )


# ─────────────────── 2. operator level scrubs secret shapes ───────────────────


class TestOperatorLevel:
    @pytest.mark.parametrize("secret", SECRET_SAMPLES)
    def test_operator_strips_each_secret_shape(self, secret: str) -> None:
        snap = _populated_snapshot_with_secrets(secret)
        redacted = state_projection.redact_to_level(snap, "operator")
        js = redacted.model_dump_json()
        # No SECRET_REGEX should match anywhere in the serialized output
        for rx in SECRET_REGEXES:
            assert rx.search(js) is None, (
                f"operator-level output still matches {rx.pattern!r}: "
                f"sample secret was {secret[:30]}..."
            )

    def test_operator_keeps_non_secret_data(self) -> None:
        snap = _populated_snapshot_with_secrets(SECRET_SAMPLES[0])
        redacted = state_projection.redact_to_level(snap, "operator")
        # Stream entries survive — only secret substrings are scrubbed
        assert len(redacted.streams.plans) == 1
        assert len(redacted.streams.gates) == 1
        assert len(redacted.streams.inbox) == 1
        assert len(redacted.streams.supervisors) == 1
        assert len(redacted.streams.quota) == 1
        assert len(redacted.streams.decisions) == 1
        assert len(redacted.streams.evidence_refs) == 1
        # Identifying fields untouched
        assert redacted.streams.plans[0].plan_id == "2026-05-10-001-feat-fixture"
        assert redacted.streams.supervisors[0].plan_id == "2026-05-10-001-feat-fixture"


# ─────────────────── 3. public level strips per-stream fields ───────────────────


class TestPublicLevel:
    @pytest.mark.parametrize("secret", SECRET_SAMPLES)
    def test_public_strips_each_secret_shape(self, secret: str) -> None:
        snap = _populated_snapshot_with_secrets(secret)
        redacted = state_projection.redact_to_level(snap, "public")
        js = redacted.model_dump_json()
        for rx in SECRET_REGEXES:
            assert rx.search(js) is None

    def test_public_strips_supervisor_pid_and_host(self) -> None:
        snap = _populated_snapshot_with_secrets(SECRET_SAMPLES[0])
        redacted = state_projection.redact_to_level(snap, "public")
        assert redacted.streams.supervisors[0].pid is None
        assert redacted.streams.supervisors[0].host is None

    def test_public_strips_decision_body(self) -> None:
        snap = _populated_snapshot_with_secrets(SECRET_SAMPLES[0])
        redacted = state_projection.redact_to_level(snap, "public")
        assert redacted.streams.decisions[0].body is None
        # Title survives (publicly relevant)
        assert redacted.streams.decisions[0].title is not None

    def test_public_strips_inbox_body(self) -> None:
        snap = _populated_snapshot_with_secrets(SECRET_SAMPLES[0])
        redacted = state_projection.redact_to_level(snap, "public")
        assert redacted.streams.inbox[0].body is None
        # event + plan_id survive
        assert redacted.streams.inbox[0].event == "volley_start"

    def test_public_strips_gate_reason(self) -> None:
        snap = _populated_snapshot_with_secrets(SECRET_SAMPLES[0])
        redacted = state_projection.redact_to_level(snap, "public")
        # Reason gets nulled at public; gate_name survives
        assert redacted.streams.gates[0].reason is None
        assert redacted.streams.gates[0].gate_name == "pre_impl"

    def test_public_drops_quota_stream(self) -> None:
        snap = _populated_snapshot_with_secrets(SECRET_SAMPLES[0])
        redacted = state_projection.redact_to_level(snap, "public")
        # quota agent breakdown forbidden at public per F001 schema doc
        assert redacted.streams.quota == []

    def test_public_redact_level_metadata_set(self) -> None:
        snap = _populated_snapshot_with_secrets(SECRET_SAMPLES[0])
        redacted = state_projection.redact_to_level(snap, "public")
        assert redacted.redact_level == RedactLevel.public


# ─────────────────── 4. integration with gather() ───────────────────


class TestGatherIntegration:
    """gather(...) accepts redact_level and applies the policy in-line."""

    def test_gather_redact_level_threaded_to_redactor(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from dontpanic_orchestrate import active_supervisors
        monkeypatch.setattr(
            active_supervisors,
            "REGISTRY_PATH",
            tmp_path / "active_supervisors.jsonl",
        )
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        snap = state_projection.gather(
            plans_root,
            quota_state_path=tmp_path / "missing.json",
            redact_level="public",
        )
        assert snap.redact_level == RedactLevel.public

    def test_gather_invalid_redact_level_raises(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from dontpanic_orchestrate import active_supervisors
        monkeypatch.setattr(
            active_supervisors,
            "REGISTRY_PATH",
            tmp_path / "active_supervisors.jsonl",
        )
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        with pytest.raises(ValueError):
            state_projection.gather(
                plans_root,
                quota_state_path=tmp_path / "missing.json",
                redact_level="bogus",
            )


# ─────────────────── 5. invariants ───────────────────


class TestRedactionInvariants:
    def test_redactor_invalid_level_raises(self) -> None:
        snap = _populated_snapshot_with_secrets(SECRET_SAMPLES[0])
        with pytest.raises(ValueError, match="redact_level"):
            state_projection.redact_to_level(snap, "BOGUS")

    def test_redactor_is_pure(self) -> None:
        """redact_to_level returns a new object; original is untouched."""
        snap = _populated_snapshot_with_secrets(SECRET_SAMPLES[0])
        before = snap.model_dump_json()
        _ = state_projection.redact_to_level(snap, "public")
        after = snap.model_dump_json()
        assert before == after, "redact_to_level mutated the input"

    def test_round_trip_at_each_level(self) -> None:
        snap = _populated_snapshot_with_secrets(SECRET_SAMPLES[0])
        for level in ("public", "operator", "full"):
            redacted = state_projection.redact_to_level(snap, level)
            js = redacted.model_dump_json()
            parsed = StateSnapshot.model_validate_json(js)
            assert parsed.redact_level.value == level
