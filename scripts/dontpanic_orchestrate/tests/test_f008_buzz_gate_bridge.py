"""F008 i1 — Buzz → DontPanic gate bridge (verified signed approvals).

Contract under test (post-audit hardening):

  - Cryptographic verification IN-PROCESS: the payload carries a raw signed
    Nostr event; the bridge recomputes the NIP-01 event id and verifies the
    BIP-340 Schnorr signature itself. There is no transport attestation —
    the old ``sig_verified`` flat payload shape is rejected at parse time.
  - Binding: actor (event pubkey), plan, gate, and the approval ACTION are
    bound under the signature via the exact content ceremony
    ``dontpanic approve plan=<plan_id> gate=<gate>``; the channel is bound
    via the signed ``h``/``e`` tag.
  - Reactions never approve: kind-7 events refuse unconditionally
    (ECOSYSTEM.md locked non-goal — reactions/emoji never auto-confirm).
  - Fail-closed identity classification: a ``gate_bridge`` block without an
    explicit ``agent_pubkeys`` list is DISABLED; an agent key smuggled into
    ``approver_pubkeys`` still refuses (D006).
  - Freshness + replay: events outside ``max_event_age_seconds`` (or too
    far future-dated) refuse; consumed event ids are persisted in
    ``audit/buzz-gate-consumed.jsonl`` and replaying one refuses even after
    the gate state is reset/re-paused.
  - Webhook deliveries are HMAC-gated: source ``webhook`` requires a
    configured ``webhook_secret_ref`` AND a valid HMAC-SHA256 over the
    event id — fail closed when the secret is absent or unresolvable.
  - Poller adapter: ``poll_approvals`` shells out to the configured
    ``poll_command`` (the buzz CLI — DontPanic itself still has no relay
    or Nostr client), filters candidate approval events, and feeds each
    through the same verified path.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_f008_buzz_gate_bridge.py
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import buzz_gate_bridge as bridge  # noqa: E402
from dontpanic_orchestrate import gate_pause, nostr_event, notify_buzz  # noqa: E402

PLAN_ID = "2026-07-27-777-infra-test-f008-bridge"
CHANNEL = "11111111-2222-3333-4444-555555555555"
OTHER_CHANNEL = "99999999-8888-7777-6666-555555555555"

HUMAN_SK = 11
OTHER_SK = 22
AGENT_SK = 33
HUMAN_PUBKEY = nostr_event.pubkey_from_seckey(HUMAN_SK)
OTHER_PUBKEY = nostr_event.pubkey_from_seckey(OTHER_SK)
AGENT_PUBKEY = nostr_event.pubkey_from_seckey(AGENT_SK)

# Fixed clock for deterministic freshness checks.
NOW = 1_785_000_000

WEBHOOK_SECRET = "test-webhook-secret"

_BASE_BUZZ = {
    "relay_url": "wss://relay.example.com",
    "channels": [CHANNEL],
    "reporter_key_ref": "env:BUZZ_PRIVATE_KEY",
}


# ───────────────────────── event helpers ─────────────────────────


def _sign_event(
    seckey: int,
    content: str,
    *,
    created_at: int = NOW,
    kind: int = 9,
    tags: list[list[str]] | None = None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "pubkey": nostr_event.pubkey_from_seckey(seckey),
        "created_at": created_at,
        "kind": kind,
        "tags": tags if tags is not None else [["h", CHANNEL]],
        "content": content,
    }
    event_id = nostr_event.compute_event_id(event)
    event["id"] = event_id
    event["sig"] = nostr_event.schnorr_sign(bytes.fromhex(event_id), seckey).hex()
    return event


def _approval_event(
    seckey: int = HUMAN_SK,
    *,
    plan_id: str = PLAN_ID,
    gate: str = "pre_impl",
    channel: str | None = CHANNEL,
    created_at: int = NOW,
    kind: int = 9,
) -> dict[str, object]:
    tags = [["h", channel]] if channel is not None else []
    return _sign_event(
        seckey,
        bridge.approval_content(plan_id, gate),
        created_at=created_at,
        kind=kind,
        tags=tags,
    )


def _payload(
    event: dict[str, object],
    *,
    source: str = "poll",
    **extra: object,
) -> bridge.ApprovalPayload:
    data: dict[str, object] = {"event": event, "source": source}
    data.update(extra)
    return bridge.parse_approval_payload(data)


def _hmac_for(event: dict[str, object], secret: str = WEBHOOK_SECRET) -> str:
    return hmac_mod.new(
        secret.encode("utf-8"), str(event["id"]).encode("ascii"), hashlib.sha256
    ).hexdigest()


# ───────────────────────── fixtures ─────────────────────────


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DONTPANIC_BUZZ_CONFIG", raising=False)
    monkeypatch.delenv("BUZZ_GATE_WEBHOOK_SECRET", raising=False)


@pytest.fixture()
def buzz_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "buzz.json"
    monkeypatch.setenv("DONTPANIC_BUZZ_CONFIG", str(path))
    return path


def _write_buzz(path: Path, gate_bridge: object | None) -> None:
    data = dict(_BASE_BUZZ)
    if gate_bridge is not None:
        data["gate_bridge"] = gate_bridge
    path.write_text(json.dumps(data), encoding="utf-8")


def _enabled_block(**overrides: object) -> dict[str, object]:
    block: dict[str, object] = {
        "enabled": True,
        "approver_pubkeys": [HUMAN_PUBKEY],
        "agent_pubkeys": [AGENT_PUBKEY],
    }
    block.update(overrides)
    return block


@pytest.fixture()
def plan_dir(tmp_path: Path) -> Path:
    d = tmp_path / PLAN_ID
    d.mkdir(parents=True)
    (d / "plan.md").write_text(
        f"""---
id: {PLAN_ID}
title: F008 bridge synthetic
type: infra
tier: trivial
status: active
date: "2026-07-28"
description: Synthetic plan for F008 Buzz gate-bridge tests.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# F008 bridge synthetic

## Target

```yaml
target_env: dev
target_project: none
```
""",
        encoding="utf-8",
    )
    (d / "features.json").write_text(
        json.dumps(
            {
                "task_id": PLAN_ID,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "test",
                        "phase": 0,
                        "description": "Synthetic feature.",
                        "steps": ["scripted"],
                        "acceptance": "ok",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return d


def _pause_on(plan_dir: Path, gate: str, stage: str | None = None) -> None:
    gate_pause.record_pause(plan_dir, plan_id=PLAN_ID, pause_gates=[gate], stage=stage)


def _process(
    plan_dir: Path,
    payload: bridge.ApprovalPayload,
    *,
    now: int = NOW,
) -> bridge.BridgeDecision:
    return bridge.process_approval(
        plan_dir, plan_id=PLAN_ID, payload=payload, now=now
    )


def _history_actors(plan_dir: Path) -> list[str]:
    state_path = plan_dir / "audit" / "gate-state.json"
    if not state_path.is_file():
        return []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    return [h.get("actor", "") for h in state.get("history", []) if h.get("action") == "approve"]


# ───────────────────────── nostr_event primitives ─────────────────────────


class TestNostrEvent:
    def test_bip340_official_vector_0(self) -> None:
        # BIP-340 test vector 0: seckey 3, aux 0x00…00, msg 0x00…00.
        msg = bytes(32)
        pub = bytes.fromhex(
            "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9"
        )
        # BIP-340 test-vectors.csv index 0 (note: earlier drafts had a
        # single-nibble typo 2DBA…; current BIP uses 2DCA…).
        sig = bytes.fromhex(
            "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA8215"
            "25F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0"
        )
        assert nostr_event.pubkey_from_seckey(3) == pub.hex()
        assert nostr_event.schnorr_sign(msg, 3) == sig
        assert nostr_event.schnorr_verify(msg, pub, sig) is True
        # Flipping one bit must fail.
        bad = bytearray(sig)
        bad[0] ^= 1
        assert nostr_event.schnorr_verify(msg, pub, bytes(bad)) is False

    def test_verify_event_accepts_signed_and_rejects_tampered(self) -> None:
        event = _sign_event(HUMAN_SK, "hello")
        assert nostr_event.verify_event(event) is True
        tampered = dict(event)
        tampered["content"] = "hello!"
        assert nostr_event.verify_event(tampered) is False

    def test_verify_event_rejects_wrong_id(self) -> None:
        event = _sign_event(HUMAN_SK, "hello")
        event["id"] = "0" * 64
        assert nostr_event.verify_event(event) is False

    def test_structure_validation_messages(self) -> None:
        assert nostr_event.validate_event_structure({"id": 1}) is not None
        assert nostr_event.validate_event_structure(_sign_event(HUMAN_SK, "x")) is None


# ───────────────────────── config loading ─────────────────────────


class TestLoadBridgeConfig:
    def test_missing_file_is_disabled(self, buzz_config: Path) -> None:
        assert bridge.load_bridge_config().enabled is False

    def test_no_gate_bridge_key_is_disabled(self, buzz_config: Path) -> None:
        _write_buzz(buzz_config, None)
        assert bridge.load_bridge_config().enabled is False

    def test_enabled_false_is_disabled(self, buzz_config: Path) -> None:
        _write_buzz(buzz_config, _enabled_block(enabled=False))
        assert bridge.load_bridge_config().enabled is False

    def test_invalid_json_is_disabled(self, buzz_config: Path) -> None:
        buzz_config.write_text("{not json", encoding="utf-8")
        assert bridge.load_bridge_config().enabled is False

    def test_enabled_without_approvers_is_disabled(self, buzz_config: Path) -> None:
        _write_buzz(buzz_config, {"enabled": True, "approver_pubkeys": [], "agent_pubkeys": []})
        assert bridge.load_bridge_config().enabled is False

    def test_missing_agent_pubkeys_is_disabled_fail_closed(self, buzz_config: Path) -> None:
        # Identity classification incomplete → the bridge must NOT enable.
        _write_buzz(buzz_config, {"enabled": True, "approver_pubkeys": [HUMAN_PUBKEY]})
        assert bridge.load_bridge_config().enabled is False

    def test_explicit_empty_agent_pubkeys_enables(self, buzz_config: Path) -> None:
        # An explicit empty list is an affirmative "no agent identities here".
        _write_buzz(
            buzz_config,
            {"enabled": True, "approver_pubkeys": [HUMAN_PUBKEY], "agent_pubkeys": []},
        )
        cfg = bridge.load_bridge_config()
        assert cfg.enabled is True
        assert cfg.agent_pubkeys == frozenset()

    def test_valid_block_loads_with_defaults(self, buzz_config: Path) -> None:
        _write_buzz(buzz_config, _enabled_block(channel=CHANNEL, gate_kinds=["pre_impl"]))
        cfg = bridge.load_bridge_config()
        assert cfg.enabled is True
        assert HUMAN_PUBKEY in cfg.approver_pubkeys
        assert AGENT_PUBKEY in cfg.agent_pubkeys
        assert cfg.channel == CHANNEL
        assert cfg.gate_kinds == frozenset({"pre_impl"})
        assert cfg.max_event_age_seconds == bridge.DEFAULT_MAX_EVENT_AGE_SECONDS
        assert cfg.webhook_secret_ref is None
        assert cfg.poll_command is None

    def test_invalid_max_event_age_is_disabled_fail_closed(self, buzz_config: Path) -> None:
        _write_buzz(buzz_config, _enabled_block(max_event_age_seconds="soon"))
        assert bridge.load_bridge_config().enabled is False
        _write_buzz(buzz_config, _enabled_block(max_event_age_seconds=0))
        assert bridge.load_bridge_config().enabled is False

    def test_poll_command_and_secret_ref_load(self, buzz_config: Path) -> None:
        _write_buzz(
            buzz_config,
            _enabled_block(
                poll_command=["buzz", "timeline", "--json"],
                webhook_secret_ref="env:BUZZ_GATE_WEBHOOK_SECRET",
            ),
        )
        cfg = bridge.load_bridge_config()
        assert cfg.poll_command == ("buzz", "timeline", "--json")
        assert cfg.webhook_secret_ref == "env:BUZZ_GATE_WEBHOOK_SECRET"

    def test_notify_sink_tolerates_gate_bridge_key(self, buzz_config: Path) -> None:
        _write_buzz(buzz_config, _enabled_block())
        assert notify_buzz._load_config() is not None


# ───────────────────────── payload parsing ─────────────────────────


class TestParsePayload:
    def test_parses_signed_event_payload(self) -> None:
        event = _approval_event()
        payload = bridge.parse_approval_payload(
            json.dumps({"event": event, "source": "webhook", "hmac": "aa"})
        )
        assert payload.event["id"] == event["id"]
        assert payload.source == "webhook"
        assert payload.hmac == "aa"

    def test_source_defaults_to_cli(self) -> None:
        payload = bridge.parse_approval_payload({"event": _approval_event()})
        assert payload.source == "cli"

    @pytest.mark.parametrize(
        "payload",
        [
            "not json",
            json.dumps(["list"]),
            {},  # no event
            # The i0 attested flat shape must be rejected, not silently trusted.
            {"plan_id": PLAN_ID, "gate": "pre_impl", "pubkey": HUMAN_PUBKEY, "sig_verified": True},
            {"event": "not-a-dict"},
            {"event": {"pubkey": HUMAN_PUBKEY}},  # structurally incomplete
        ],
    )
    def test_malformed_payload_raises(self, payload: object) -> None:
        with pytest.raises(ValueError):
            bridge.parse_approval_payload(payload)  # type: ignore[arg-type]

    def test_structurally_broken_event_raises(self) -> None:
        event = _approval_event()
        event["created_at"] = "yesterday"
        with pytest.raises(ValueError):
            bridge.parse_approval_payload({"event": event})


# ───────────────────────── approval processing ─────────────────────────


class TestProcessApproval:
    def test_disabled_bridge_refuses(self, buzz_config: Path, plan_dir: Path) -> None:
        _write_buzz(buzz_config, None)
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        decision = _process(plan_dir, _payload(_approval_event()))
        assert decision.outcome == bridge.REFUSED_DISABLED
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_allowlisted_human_clears_gate_with_durable_actor(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        event = _approval_event()
        decision = _process(plan_dir, _payload(event))
        assert decision.outcome == bridge.APPROVED
        assert decision.approved is True
        assert decision.actor == f"buzz:{HUMAN_PUBKEY}"
        assert decision.event_id == event["id"]
        assert gate_pause.is_gate_cleared(plan_dir, "pre_impl")
        assert f"buzz:{HUMAN_PUBKEY}" in _history_actors(plan_dir)
        inbox_text = (plan_dir / "INBOX.md").read_text(encoding="utf-8")
        assert "gate_cleared" in inbox_text
        assert f"buzz:{HUMAN_PUBKEY}" in inbox_text
        lines = [
            json.loads(line)
            for line in (plan_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert any(entry.get("by") == f"buzz:{HUMAN_PUBKEY}" for entry in lines)
        # Consumed-event ledger records the signed event id.
        ledger = (plan_dir / "audit" / "buzz-gate-consumed.jsonl").read_text(encoding="utf-8")
        assert event["id"] in ledger

    def test_tampered_content_refused_unverified(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        event = _approval_event(plan_id="victim-plan")
        # Attacker rewrites the signed ceremony to target OUR plan/gate.
        event["content"] = bridge.approval_content(PLAN_ID, "pre_impl")
        event["id"] = nostr_event.compute_event_id(event)
        decision = _process(plan_dir, _payload(event))
        assert decision.outcome == bridge.REFUSED_UNVERIFIED
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_signature_from_wrong_key_refused(self, buzz_config: Path, plan_dir: Path) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        event = _approval_event(OTHER_SK)
        # Claim the allowlisted human's pubkey over the other key's signature.
        event["pubkey"] = HUMAN_PUBKEY
        event["id"] = nostr_event.compute_event_id(event)
        decision = _process(plan_dir, _payload(event))
        assert decision.outcome == bridge.REFUSED_UNVERIFIED
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_reaction_kind_never_approves(self, buzz_config: Path, plan_dir: Path) -> None:
        # ECOSYSTEM locked non-goal: reactions/emoji never auto-confirm —
        # even a reaction whose content IS the exact ceremony refuses.
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        event = _sign_event(
            HUMAN_SK, bridge.approval_content(PLAN_ID, "pre_impl"), kind=7
        )
        decision = _process(plan_dir, _payload(event))
        assert decision.outcome == bridge.REFUSED_REACTION
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_non_ceremony_content_refused(self, buzz_config: Path, plan_dir: Path) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        event = _sign_event(HUMAN_SK, "looks good to me, approve!")
        decision = _process(plan_dir, _payload(event))
        assert decision.outcome == bridge.REFUSED_CEREMONY
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_agent_key_refused_even_when_allowlisted(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(
            buzz_config,
            _enabled_block(approver_pubkeys=[HUMAN_PUBKEY, AGENT_PUBKEY]),
        )
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        decision = _process(plan_dir, _payload(_approval_event(AGENT_SK)))
        assert decision.outcome == bridge.REFUSED_AGENT_KEY
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_non_allowlisted_pubkey_refused(self, buzz_config: Path, plan_dir: Path) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        decision = _process(plan_dir, _payload(_approval_event(OTHER_SK)))
        assert decision.outcome == bridge.REFUSED_NOT_ALLOWLISTED
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")
        assert not (plan_dir / "decisions.jsonl").exists()

    def test_channel_mismatch_refused(self, buzz_config: Path, plan_dir: Path) -> None:
        _write_buzz(buzz_config, _enabled_block(channel=CHANNEL))
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        decision = _process(plan_dir, _payload(_approval_event(channel=OTHER_CHANNEL)))
        assert decision.outcome == bridge.REFUSED_CHANNEL
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_missing_channel_tag_refused_when_channel_pinned(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block(channel=CHANNEL))
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        decision = _process(plan_dir, _payload(_approval_event(channel=None)))
        assert decision.outcome == bridge.REFUSED_CHANNEL

    def test_plan_mismatch_refused(self, buzz_config: Path, plan_dir: Path) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        decision = _process(plan_dir, _payload(_approval_event(plan_id="some-other-plan")))
        assert decision.outcome == bridge.REFUSED_PLAN_MISMATCH
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    @pytest.mark.parametrize(
        "gate",
        [
            "breaker:budget_ceiling",
            "defer:quota",
            "pre_resume_after_child:2026-01-01-001-x",
            "drift:scope",
        ],
    )
    def test_synthetic_gates_always_refused(
        self, buzz_config: Path, plan_dir: Path, gate: str
    ) -> None:
        _write_buzz(buzz_config, _enabled_block(gate_kinds=[gate]))
        _pause_on(plan_dir, gate)
        decision = _process(plan_dir, _payload(_approval_event(gate=gate)))
        assert decision.outcome == bridge.REFUSED_GATE_KIND
        assert not gate_pause.is_gate_cleared(plan_dir, gate)

    def test_gate_outside_configured_kinds_refused(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block(gate_kinds=["pre_merge"]))
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        decision = _process(plan_dir, _payload(_approval_event()))
        assert decision.outcome == bridge.REFUSED_GATE_KIND

    def test_stale_event_refused(self, buzz_config: Path, plan_dir: Path) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        stale = _approval_event(created_at=NOW - bridge.DEFAULT_MAX_EVENT_AGE_SECONDS - 1)
        decision = _process(plan_dir, _payload(stale))
        assert decision.outcome == bridge.REFUSED_STALE
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_future_dated_event_refused(self, buzz_config: Path, plan_dir: Path) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        future = _approval_event(created_at=NOW + 3_600)
        decision = _process(plan_dir, _payload(future))
        assert decision.outcome == bridge.REFUSED_STALE

    def test_replayed_event_id_refused_after_gate_reset(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        event = _approval_event()
        assert _process(plan_dir, _payload(event)).outcome == bridge.APPROVED
        # Gate state is reset and the same stage pauses again — replaying the
        # already-consumed signed event must NOT clear it a second time.
        gate_pause.reset_for_test(plan_dir)
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        decision = _process(plan_dir, _payload(event))
        assert decision.outcome == bridge.REFUSED_REPLAY
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_redelivery_of_cleared_gate_is_noop(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        event = _approval_event()
        assert _process(plan_dir, _payload(event)).outcome == bridge.APPROVED
        second = _process(plan_dir, _payload(event))
        assert second.outcome == bridge.NOOP_ALREADY_CLEARED
        assert second.approved is False
        decision_lines = [
            line
            for line in (plan_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(decision_lines) == 1
        inbox_text = (plan_dir / "INBOX.md").read_text(encoding="utf-8")
        assert inbox_text.count("event: gate_cleared") == 1

    def test_lifecycle_gate_not_pending_refused(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block())
        decision = _process(plan_dir, _payload(_approval_event()))
        assert decision.outcome == bridge.REFUSED_NOT_PENDING
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_allowlist_matching_is_case_insensitive(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block(approver_pubkeys=[HUMAN_PUBKEY.upper()]))
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        decision = _process(plan_dir, _payload(_approval_event()))
        assert decision.outcome == bridge.APPROVED
        assert decision.actor == f"buzz:{HUMAN_PUBKEY}"


# ───────────────────────── webhook HMAC gating ─────────────────────────


class TestWebhookHmac:
    def test_webhook_without_configured_secret_refused(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        event = _approval_event()
        decision = _process(plan_dir, _payload(event, source="webhook", hmac=_hmac_for(event)))
        assert decision.outcome == bridge.REFUSED_WEBHOOK_HMAC
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_webhook_with_valid_hmac_approves(
        self, buzz_config: Path, plan_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BUZZ_GATE_WEBHOOK_SECRET", WEBHOOK_SECRET)
        _write_buzz(
            buzz_config, _enabled_block(webhook_secret_ref="env:BUZZ_GATE_WEBHOOK_SECRET")
        )
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        event = _approval_event()
        decision = _process(plan_dir, _payload(event, source="webhook", hmac=_hmac_for(event)))
        assert decision.outcome == bridge.APPROVED

    def test_webhook_with_wrong_or_missing_hmac_refused(
        self, buzz_config: Path, plan_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BUZZ_GATE_WEBHOOK_SECRET", WEBHOOK_SECRET)
        _write_buzz(
            buzz_config, _enabled_block(webhook_secret_ref="env:BUZZ_GATE_WEBHOOK_SECRET")
        )
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        event = _approval_event()
        wrong = _process(plan_dir, _payload(event, source="webhook", hmac="00" * 32))
        assert wrong.outcome == bridge.REFUSED_WEBHOOK_HMAC
        missing = _process(plan_dir, _payload(event, source="webhook"))
        assert missing.outcome == bridge.REFUSED_WEBHOOK_HMAC
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_webhook_with_unresolvable_secret_refused(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        # Secret configured but env var unset → fail closed.
        _write_buzz(
            buzz_config, _enabled_block(webhook_secret_ref="env:BUZZ_GATE_WEBHOOK_SECRET")
        )
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        event = _approval_event()
        decision = _process(plan_dir, _payload(event, source="webhook", hmac=_hmac_for(event)))
        assert decision.outcome == bridge.REFUSED_WEBHOOK_HMAC


# ───────────────────────── poller adapter ─────────────────────────


def _poll_command_for(tmp_path: Path, events: list[dict[str, object]]) -> list[str]:
    """A fake buzz CLI: prints the canned event list as JSON."""
    events_file = tmp_path / "poll-events.json"
    events_file.write_text(json.dumps(events), encoding="utf-8")
    return [
        sys.executable,
        "-c",
        "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())",
        str(events_file),
    ]


class TestPollAdapter:
    def test_poll_processes_candidates_and_clears_gate(
        self, buzz_config: Path, plan_dir: Path, tmp_path: Path
    ) -> None:
        chatter = _sign_event(HUMAN_SK, "how is the run going?")
        approval = _approval_event()
        intruder = _approval_event(OTHER_SK, gate="pre_merge")
        cmd = _poll_command_for(tmp_path, [chatter, approval, intruder])
        _write_buzz(buzz_config, _enabled_block(poll_command=cmd))
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        decisions = bridge.poll_approvals(plan_dir, plan_id=PLAN_ID, now=NOW)
        # Chatter is filtered before processing; the two ceremony events run.
        assert len(decisions) == 2
        outcomes = {d.outcome for d in decisions}
        assert bridge.APPROVED in outcomes
        assert bridge.REFUSED_NOT_ALLOWLISTED in outcomes
        assert gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_poll_without_command_raises(self, buzz_config: Path, plan_dir: Path) -> None:
        _write_buzz(buzz_config, _enabled_block())
        with pytest.raises(ValueError):
            bridge.poll_approvals(plan_dir, plan_id=PLAN_ID, now=NOW)

    def test_poll_command_failure_raises(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(
            buzz_config,
            _enabled_block(poll_command=[sys.executable, "-c", "import sys; sys.exit(3)"]),
        )
        with pytest.raises(ValueError):
            bridge.poll_approvals(plan_dir, plan_id=PLAN_ID, now=NOW)

    def test_poll_disabled_bridge_raises(self, buzz_config: Path, plan_dir: Path) -> None:
        _write_buzz(buzz_config, None)
        with pytest.raises(ValueError):
            bridge.poll_approvals(plan_dir, plan_id=PLAN_ID, now=NOW)


# ───────────────────────── CLI surface ─────────────────────────


class TestBuzzGateCli:
    def _run(self, argv: list[str]) -> int:
        from dontpanic_orchestrate.cli import main

        return main(argv)

    def test_cli_approves_from_payload_file(
        self, buzz_config: Path, plan_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_buzz(buzz_config, _enabled_block(max_event_age_seconds=10**9))
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        payload = tmp_path / "payload.json"
        payload.write_text(json.dumps({"event": _approval_event()}), encoding="utf-8")
        rc = self._run(["buzz-gate", str(plan_dir), "--payload", str(payload)])
        assert rc == 0
        assert gate_pause.is_gate_cleared(plan_dir, "pre_impl")
        out = capsys.readouterr().out
        assert f"buzz:{HUMAN_PUBKEY}" in out

    def test_cli_refusal_exits_2(
        self, buzz_config: Path, plan_dir: Path, tmp_path: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block(max_event_age_seconds=10**9))
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        payload = tmp_path / "payload.json"
        payload.write_text(json.dumps({"event": _approval_event(OTHER_SK)}), encoding="utf-8")
        rc = self._run(["buzz-gate", str(plan_dir), "--payload", str(payload)])
        assert rc == 2
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_cli_malformed_payload_exits_2(
        self, buzz_config: Path, plan_dir: Path, tmp_path: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block())
        payload = tmp_path / "payload.json"
        payload.write_text("{not json", encoding="utf-8")
        rc = self._run(["buzz-gate", str(plan_dir), "--payload", str(payload)])
        assert rc == 2

    def test_cli_legacy_attested_payload_exits_2(
        self, buzz_config: Path, plan_dir: Path, tmp_path: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block())
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        payload = tmp_path / "payload.json"
        payload.write_text(
            json.dumps(
                {
                    "plan_id": PLAN_ID,
                    "gate": "pre_impl",
                    "pubkey": HUMAN_PUBKEY,
                    "sig_verified": True,
                }
            ),
            encoding="utf-8",
        )
        rc = self._run(["buzz-gate", str(plan_dir), "--payload", str(payload)])
        assert rc == 2
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")

    def test_cli_poll_mode(
        self, buzz_config: Path, plan_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd = _poll_command_for(tmp_path, [_approval_event()])
        _write_buzz(
            buzz_config, _enabled_block(poll_command=cmd, max_event_age_seconds=10**9)
        )
        _pause_on(plan_dir, "pre_impl", stage="pre_impl")
        rc = self._run(["buzz-gate", str(plan_dir), "--poll"])
        assert rc == 0
        assert gate_pause.is_gate_cleared(plan_dir, "pre_impl")
        assert "approved" in capsys.readouterr().out

    def test_cli_poll_unconfigured_exits_2(
        self, buzz_config: Path, plan_dir: Path
    ) -> None:
        _write_buzz(buzz_config, _enabled_block())
        rc = self._run(["buzz-gate", str(plan_dir), "--poll"])
        assert rc == 2
