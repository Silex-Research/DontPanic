"""Plan 2026-07-27-001 F008 — optional Buzz → DontPanic gate bridge.

Maps an allowlisted HUMAN approval (a signed Nostr event whose content is
the explicit ceremony ``dontpanic approve plan=<id> gate=<gate>``) onto
:func:`gate_pause.approve_gate` with durable actor ``buzz:<pubkey>``.

Cryptography is in-process (BIP-340 / NIP-01 via :mod:`nostr_event`).
There is no trust in caller-supplied ``sig_verified`` — that flat shape is
rejected at parse time. Reactions (kind 7) never approve (ECOSYSTEM.md).

OFF BY DEFAULT. Requires ``buzz.json`` ``gate_bridge`` with
``enabled: true``, a non-empty human allowlist, and an *explicit*
``agent_pubkeys`` list (empty list is OK — missing key is fail-closed).
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from dontpanic_orchestrate import gate_pause, global_config, inbox, nostr_event

CONFIG_KEY: Final[str] = "gate_bridge"
_CONFIG_FILENAME: Final[str] = "buzz.json"
_CONFIG_PATH_ENV: Final[str] = "DONTPANIC_BUZZ_CONFIG"
_CONSUMED_LEDGER: Final[str] = "buzz-gate-consumed.jsonl"

DEFAULT_GATE_KINDS: Final[frozenset[str]] = frozenset(gate_pause.LIFECYCLE_STAGES)
DEFAULT_MAX_EVENT_AGE_SECONDS: Final[int] = 900  # 15 minutes
_SYNTHETIC_PREFIXES: Final[tuple[str, ...]] = (
    "breaker:",
    "defer:",
    "pre_resume_after_child:",
    "drift:",
)
_CEREMONY_RE: Final[re.Pattern[str]] = re.compile(
    r"^dontpanic approve plan=(?P<plan>[^\s]+) gate=(?P<gate>[^\s]+)$"
)
_REACTION_KIND: Final[int] = 7

APPROVED: Final[str] = "approved"
NOOP_ALREADY_CLEARED: Final[str] = "noop_already_cleared"
REFUSED_DISABLED: Final[str] = "refused_disabled"
REFUSED_UNVERIFIED: Final[str] = "refused_unverified"
REFUSED_AGENT_KEY: Final[str] = "refused_agent_key"
REFUSED_NOT_ALLOWLISTED: Final[str] = "refused_not_allowlisted"
REFUSED_CHANNEL: Final[str] = "refused_channel"
REFUSED_PLAN_MISMATCH: Final[str] = "refused_plan_mismatch"
REFUSED_GATE_KIND: Final[str] = "refused_gate_kind"
REFUSED_NOT_PENDING: Final[str] = "refused_not_pending"
REFUSED_REACTION: Final[str] = "refused_reaction"
REFUSED_CEREMONY: Final[str] = "refused_ceremony"
REFUSED_STALE: Final[str] = "refused_stale"
REFUSED_REPLAY: Final[str] = "refused_replay"
REFUSED_WEBHOOK_HMAC: Final[str] = "refused_webhook_hmac"


@dataclass(frozen=True)
class GateBridgeConfig:
    enabled: bool
    approver_pubkeys: frozenset[str]
    agent_pubkeys: frozenset[str]
    channel: str | None
    gate_kinds: frozenset[str]
    max_event_age_seconds: int = DEFAULT_MAX_EVENT_AGE_SECONDS
    webhook_secret_ref: str | None = None
    poll_command: tuple[str, ...] | None = None


DISABLED_CONFIG: Final[GateBridgeConfig] = GateBridgeConfig(
    enabled=False,
    approver_pubkeys=frozenset(),
    agent_pubkeys=frozenset(),
    channel=None,
    gate_kinds=DEFAULT_GATE_KINDS,
)


@dataclass(frozen=True)
class ApprovalPayload:
    """Parsed transport payload carrying a raw signed Nostr event."""

    event: dict[str, Any]
    source: str = "cli"
    hmac: str | None = None


@dataclass(frozen=True)
class BridgeDecision:
    outcome: str
    approved: bool
    gate: str
    reason: str
    actor: str | None = None
    event_id: str | None = None


def bridge_config_path() -> Path:
    override = os.environ.get(_CONFIG_PATH_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return global_config.dontpanic_home() / _CONFIG_FILENAME


def approval_content(plan_id: str, gate: str) -> str:
    """Exact content ceremony bound under the event signature."""
    return f"dontpanic approve plan={plan_id} gate={gate}"


def _normalize_pubkey(value: str) -> str:
    return value.strip().lower()


def _pubkey_set(raw: Any) -> frozenset[str]:
    if not isinstance(raw, list):
        return frozenset()
    keys: set[str] = set()
    for entry in raw:
        if isinstance(entry, str) and entry.strip() and not any(c.isspace() for c in entry.strip()):
            keys.add(_normalize_pubkey(entry))
    return frozenset(keys)


def _resolve_secret_ref(ref: str) -> str | None:
    """Resolve ``env:VAR`` style secret refs. Returns None if unresolvable."""
    if not isinstance(ref, str) or not ref.strip():
        return None
    ref = ref.strip()
    if ref.startswith("env:"):
        name = ref[4:].strip()
        if not name:
            return None
        value = os.environ.get(name)
        if value is None or value == "":
            return None
        return value
    return None


def load_bridge_config(config_path: Path | None = None) -> GateBridgeConfig:
    """Load + validate ``gate_bridge``. Fail-soft → DISABLED."""
    path = config_path if config_path is not None else bridge_config_path()
    try:
        if not path.is_file():
            return DISABLED_CONFIG
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return DISABLED_CONFIG
    if not isinstance(data, dict):
        return DISABLED_CONFIG
    block = data.get(CONFIG_KEY)
    if not isinstance(block, dict) or block.get("enabled") is not True:
        return DISABLED_CONFIG

    approvers = _pubkey_set(block.get("approver_pubkeys"))
    if not approvers:
        return DISABLED_CONFIG

    # Fail-closed: agent_pubkeys must be present (list, possibly empty).
    if "agent_pubkeys" not in block or not isinstance(block.get("agent_pubkeys"), list):
        return DISABLED_CONFIG
    agents = _pubkey_set(block.get("agent_pubkeys"))

    raw_kinds = block.get("gate_kinds")
    if isinstance(raw_kinds, list):
        kinds = frozenset(k.strip() for k in raw_kinds if isinstance(k, str) and k.strip())
        gate_kinds = kinds or DEFAULT_GATE_KINDS
    else:
        gate_kinds = DEFAULT_GATE_KINDS

    raw_channel = block.get("channel")
    channel = (
        raw_channel.strip()
        if isinstance(raw_channel, str) and raw_channel.strip()
        else None
    )

    raw_age = block.get("max_event_age_seconds", DEFAULT_MAX_EVENT_AGE_SECONDS)
    if not isinstance(raw_age, int) or isinstance(raw_age, bool) or raw_age <= 0:
        return DISABLED_CONFIG
    max_age = raw_age

    raw_secret = block.get("webhook_secret_ref")
    webhook_secret_ref = (
        raw_secret.strip()
        if isinstance(raw_secret, str) and raw_secret.strip()
        else None
    )

    raw_poll = block.get("poll_command")
    poll_command: tuple[str, ...] | None = None
    if isinstance(raw_poll, list) and raw_poll and all(isinstance(x, str) and x for x in raw_poll):
        poll_command = tuple(raw_poll)

    return GateBridgeConfig(
        enabled=True,
        approver_pubkeys=approvers,
        agent_pubkeys=agents,
        channel=channel,
        gate_kinds=gate_kinds,
        max_event_age_seconds=max_age,
        webhook_secret_ref=webhook_secret_ref,
        poll_command=poll_command,
    )


def is_enabled(config_path: Path | None = None) -> bool:
    return load_bridge_config(config_path).enabled


def parse_approval_payload(raw: str | bytes | dict[str, Any]) -> ApprovalPayload:
    """Parse a payload that wraps a raw signed event. Raises ValueError on bad shapes."""
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError(f"payload is not valid JSON: {exc}") from exc
    else:
        data = raw
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")
    # Reject the legacy attested flat shape (no raw event).
    if "event" not in data:
        raise ValueError("payload must carry a signed Nostr 'event' object")
    event = data.get("event")
    if not isinstance(event, dict):
        raise ValueError("payload 'event' must be an object")
    structure_err = nostr_event.validate_event_structure(event)
    if structure_err is not None:
        raise ValueError(structure_err)
    source = data.get("source")
    source_s = source.strip() if isinstance(source, str) and source.strip() else "cli"
    raw_hmac = data.get("hmac")
    hmac_s = raw_hmac.strip() if isinstance(raw_hmac, str) and raw_hmac.strip() else None
    return ApprovalPayload(event=event, source=source_s, hmac=hmac_s)


def _refuse(
    outcome: str, gate: str, reason: str, *, event_id: str | None = None
) -> BridgeDecision:
    return BridgeDecision(
        outcome=outcome,
        approved=False,
        gate=gate,
        reason=reason,
        event_id=event_id,
    )


def _channel_from_event(event: dict[str, Any]) -> str | None:
    tags = event.get("tags") or []
    for tag in tags:
        if isinstance(tag, list) and len(tag) >= 2 and tag[0] in ("h", "e") and tag[1]:
            return str(tag[1])
    return None


def _parse_ceremony(content: str) -> tuple[str, str] | None:
    match = _CEREMONY_RE.match(content.strip())
    if not match:
        return None
    return match.group("plan"), match.group("gate")


def _consumed_path(plan_dir: Path) -> Path:
    return plan_dir / "audit" / _CONSUMED_LEDGER


def _event_already_consumed(plan_dir: Path, event_id: str) -> bool:
    path = _consumed_path(plan_dir)
    if not path.is_file():
        return False
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("event_id") == event_id:
                return True
    except OSError:
        return False
    return False


def _record_consumed(plan_dir: Path, *, event_id: str, gate: str, actor: str) -> None:
    path = _consumed_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "event_id": event_id,
        "gate": gate,
        "actor": actor,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _append_decision_note(
    plan_dir: Path,
    *,
    plan_id: str,
    gate: str,
    actor: str,
    source: str,
    event_id: str,
) -> None:
    decisions_path = plan_dir / "decisions.jsonl"
    highest = 0
    if decisions_path.is_file():
        for line in decisions_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_id = str(obj.get("id", ""))
            if raw_id.startswith("D") and raw_id[1:].isdigit():
                highest = max(highest, int(raw_id[1:]))
    entry = {
        "id": f"D{highest + 1:03d}",
        "by": actor,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": "Gate cleared via Buzz gate bridge (F008)",
        "gate": gate,
        "plan_id": plan_id,
        "source": source,
        "event_id": event_id,
        "body": (
            f"Allowlisted human approval from Buzz ({source}) cleared gate "
            f"{gate!r}; durable actor {actor!r}; signed event {event_id}."
        ),
    }
    with decisions_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _verify_webhook_hmac(
    cfg: GateBridgeConfig, payload: ApprovalPayload, event_id: str
) -> bool:
    if cfg.webhook_secret_ref is None:
        return False
    secret = _resolve_secret_ref(cfg.webhook_secret_ref)
    if secret is None:
        return False
    if not payload.hmac:
        return False
    expected = hmac_mod.new(
        secret.encode("utf-8"), event_id.encode("ascii"), hashlib.sha256
    ).hexdigest()
    try:
        return hmac_mod.compare_digest(expected.lower(), payload.hmac.strip().lower())
    except (TypeError, ValueError):
        return False


def process_approval(
    plan_dir: Path,
    *,
    plan_id: str,
    payload: ApprovalPayload | None = None,
    event: ApprovalPayload | None = None,  # legacy alias unused
    config: GateBridgeConfig | None = None,
    now: int | None = None,
) -> BridgeDecision:
    """Verify a signed approval payload and clear the gate when policy passes."""
    if payload is None:
        raise TypeError("process_approval requires payload=")
    cfg = config if config is not None else load_bridge_config()
    raw_event = payload.event
    event_id = str(raw_event.get("id", ""))
    ceremony = _parse_ceremony(str(raw_event.get("content", "")))
    gate = ceremony[1] if ceremony else str(raw_event.get("kind", ""))

    if not cfg.enabled:
        return _refuse(
            REFUSED_DISABLED,
            gate if ceremony else "?",
            "gate bridge is disabled (off-by-default; enable via buzz.json gate_bridge).",
            event_id=event_id or None,
        )

    # Cryptographic verification in-process — never trust transport attestation.
    if not nostr_event.verify_event(raw_event):
        return _refuse(
            REFUSED_UNVERIFIED,
            gate if ceremony else "?",
            "Nostr event signature/id verification failed.",
            event_id=event_id or None,
        )

    kind = int(raw_event["kind"])
    if kind == _REACTION_KIND:
        return _refuse(
            REFUSED_REACTION,
            gate if ceremony else "?",
            "reactions (kind 7) never auto-confirm (ECOSYSTEM.md non-goal).",
            event_id=event_id,
        )

    if ceremony is None:
        return _refuse(
            REFUSED_CEREMONY,
            "?",
            "event content is not the exact 'dontpanic approve plan=… gate=…' ceremony.",
            event_id=event_id,
        )
    content_plan, gate = ceremony

    clock = int(time.time()) if now is None else int(now)
    created_at = int(raw_event["created_at"])
    if created_at > clock + 60 or (clock - created_at) > cfg.max_event_age_seconds:
        return _refuse(
            REFUSED_STALE,
            gate,
            "event created_at outside allowed freshness window.",
            event_id=event_id,
        )

    if payload.source == "webhook":
        if not _verify_webhook_hmac(cfg, payload, event_id):
            return _refuse(
                REFUSED_WEBHOOK_HMAC,
                gate,
                "webhook HMAC missing, invalid, or secret unresolvable.",
                event_id=event_id,
            )

    pubkey = _normalize_pubkey(str(raw_event["pubkey"]))
    if pubkey in cfg.agent_pubkeys:
        return _refuse(
            REFUSED_AGENT_KEY,
            gate,
            "pubkey is a configured agent identity; agent keys are never "
            "human approvers for human gates (D006).",
            event_id=event_id,
        )
    if pubkey not in cfg.approver_pubkeys:
        return _refuse(
            REFUSED_NOT_ALLOWLISTED,
            gate,
            "pubkey is not in the approver allowlist.",
            event_id=event_id,
        )

    event_channel = _channel_from_event(raw_event)
    if cfg.channel is not None and event_channel != cfg.channel:
        return _refuse(
            REFUSED_CHANNEL,
            gate,
            "approval channel tag does not match configured gate channel.",
            event_id=event_id,
        )

    if content_plan != plan_id:
        return _refuse(
            REFUSED_PLAN_MISMATCH,
            gate,
            f"ceremony plan_id {content_plan!r} does not match target plan {plan_id!r}.",
            event_id=event_id,
        )

    if gate.startswith(_SYNTHETIC_PREFIXES) or gate not in cfg.gate_kinds:
        return _refuse(
            REFUSED_GATE_KIND,
            gate,
            "gate kind is not bridge-approvable (synthetic gates and kinds "
            "outside gate_kinds stay on the operator CLI).",
            event_id=event_id,
        )

    if gate_pause.is_gate_cleared(plan_dir, gate):
        return _refuse(
            NOOP_ALREADY_CLEARED,
            gate,
            "gate already cleared; redelivery ignored (idempotent).",
            event_id=event_id,
        )

    if _event_already_consumed(plan_dir, event_id):
        return _refuse(
            REFUSED_REPLAY,
            gate,
            "signed event id was already consumed; refusing replay.",
            event_id=event_id,
        )

    # Every bridge-cleared gate must be currently pending — never pre-clear
    # a future stage (lifecycle or otherwise).
    if not gate_pause.is_gate_currently_pending(plan_dir, gate):
        return _refuse(
            REFUSED_NOT_PENDING,
            gate,
            "gate is not currently pending; the bridge never pre-clears "
            "a future stage.",
            event_id=event_id,
        )

    actor = f"buzz:{pubkey}"
    changed = gate_pause.approve_gate(plan_dir, gate, plan_id=plan_id, actor=actor)
    if not changed:
        return _refuse(
            NOOP_ALREADY_CLEARED,
            gate,
            "gate already cleared; no state change.",
            event_id=event_id,
        )
    _record_consumed(plan_dir, event_id=event_id, gate=gate, actor=actor)
    inbox.append_event(
        plan_dir,
        event="gate_cleared",
        plan_id=plan_id,
        body=(
            f"Gate '{gate}' cleared via Buzz gate bridge (F008): allowlisted "
            f"human approval from {actor} ({payload.source}); event {event_id}."
        ),
        gate=gate,
        actor=actor,
        source=f"buzz-{payload.source}",
    )
    _append_decision_note(
        plan_dir,
        plan_id=plan_id,
        gate=gate,
        actor=actor,
        source=payload.source,
        event_id=event_id,
    )
    return BridgeDecision(
        outcome=APPROVED,
        approved=True,
        gate=gate,
        reason="allowlisted human approval accepted.",
        actor=actor,
        event_id=event_id,
    )


def _extract_events_from_poll_output(raw: str) -> list[dict[str, Any]]:
    """Accept a JSON array of events, a single event, or NDJSON."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        events: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                events.append(obj)
        return events
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("events"), list):
            return [e for e in data["events"] if isinstance(e, dict)]
        return [data]
    return []


def poll_approvals(
    plan_dir: Path,
    *,
    plan_id: str,
    config: GateBridgeConfig | None = None,
    now: int | None = None,
) -> list[BridgeDecision]:
    """Shell out to ``poll_command`` (buzz CLI), filter ceremony candidates,
    and process each through the verified approval path."""
    cfg = config if config is not None else load_bridge_config()
    if not cfg.enabled:
        raise ValueError("gate bridge is disabled; cannot poll")
    if not cfg.poll_command:
        raise ValueError("gate_bridge.poll_command is not configured")
    try:
        proc = subprocess.run(
            list(cfg.poll_command),
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"poll_command failed to start: {exc}") from exc
    if proc.returncode != 0:
        raise ValueError(
            f"poll_command exited {proc.returncode}: {(proc.stderr or '')[:200]}"
        )
    decisions: list[BridgeDecision] = []
    for event in _extract_events_from_poll_output(proc.stdout or ""):
        # Only feed events that look like the approval ceremony (or reactions
        # that must still be refused). Chatter is filtered out.
        content = event.get("content") if isinstance(event.get("content"), str) else ""
        kind = event.get("kind")
        is_ceremony = _parse_ceremony(content) is not None
        is_reaction = kind == _REACTION_KIND
        if not is_ceremony and not is_reaction:
            continue
        try:
            payload = parse_approval_payload({"event": event, "source": "poll"})
        except ValueError:
            continue
        decisions.append(
            process_approval(plan_dir, plan_id=plan_id, payload=payload, config=cfg, now=now)
        )
    return decisions


__all__ = [
    "APPROVED",
    "ApprovalPayload",
    "BridgeDecision",
    "CONFIG_KEY",
    "DEFAULT_GATE_KINDS",
    "DEFAULT_MAX_EVENT_AGE_SECONDS",
    "DISABLED_CONFIG",
    "GateBridgeConfig",
    "NOOP_ALREADY_CLEARED",
    "REFUSED_AGENT_KEY",
    "REFUSED_CEREMONY",
    "REFUSED_CHANNEL",
    "REFUSED_DISABLED",
    "REFUSED_GATE_KIND",
    "REFUSED_NOT_ALLOWLISTED",
    "REFUSED_NOT_PENDING",
    "REFUSED_PLAN_MISMATCH",
    "REFUSED_REACTION",
    "REFUSED_REPLAY",
    "REFUSED_STALE",
    "REFUSED_UNVERIFIED",
    "REFUSED_WEBHOOK_HMAC",
    "approval_content",
    "bridge_config_path",
    "is_enabled",
    "load_bridge_config",
    "parse_approval_payload",
    "poll_approvals",
    "process_approval",
]
