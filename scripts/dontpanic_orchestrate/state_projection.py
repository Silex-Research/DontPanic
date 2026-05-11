"""Plan 2026-05-09-003 F002 — state projection (read-only).

`gather()` walks a plans-root and returns a StateSnapshot (F001 schema)
projecting seven streams: plans, gates, inbox, supervisors, quota,
decisions, evidence_refs. Pure-read by contract — never writes to
filesystem. Single entry point for adapters (dashboards, brokers, CI
runners) and the F004 CLI / F005 MCP tools.

Source-of-truth for each stream:
  - plans         : plan_loader.load(<plan_dir>) for every dir under
                    plans-root that has a plan.md
  - gates         : gate_pause.unmet_gates(plan_dir, declared_gates)
                    per plan — emits one entry per unmet gate. Cleared
                    gates are not emitted (consumers infer clearance
                    from absence per the F001 schema docstring).
  - inbox         : inbox.read_events(plan_dir) per plan, then merged
                    newest-first across all plans, capped at
                    INBOX_DEFAULT_LIMIT.
  - supervisors   : active_supervisors.list_active() — global registry
                    at ~/.jarvis/active_supervisors.jsonl.
  - quota         : ~/.jarvis/quota_state.json (F020-shaped). Window
                    mapping: rolling_7d → weekly, rolling_5h → daily.
  - decisions     : per-plan decisions.jsonl, merged newest-first
                    across all plans, capped at DECISIONS_DEFAULT_LIMIT.
  - evidence_refs : per-plan features.json — extract each feature's
                    evidence_refs list and project to EvidencePointer.
                    Pointers only — never file contents.

`redact_level` is accepted and threaded into the returned snapshot but
is otherwise a no-op in F002. F003 implements the actual redaction
policy as a post-gather pass.

Filter semantics:
  - `include` : subset of ALL_STREAMS. Unselected streams come back
                empty. Unknown stream names raise ValueError.
  - `plan_id` : when set, plans/gates/inbox/decisions/evidence_refs
                are scoped to that single plan; supervisors + quota
                are global and unfiltered.

Failure policy v0: fail-fast on malformed plans. plan_loader raises
on invalid frontmatter / features; we let that bubble up. F004 CLI
may add `--ignore-malformed` later. Missing optional artifacts
(INBOX.md, decisions.jsonl, gate-state.json, quota_state.json) are
handled gracefully — no error, just empty contributions.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import socket
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from dontpanic_orchestrate import (
    active_supervisors,
    circuit_breakers,
    gate_pause,
    inbox,
    plan_loader,
)

import sys as _sys

# Pydantic models live in the agent-conventions subtree.
_SUBTREE_MODELS = (
    Path(__file__).resolve().parents[2]
    / "claude"
    / "shared"
    / "schemas"
    / "v1.0"
    / "models"
)
if str(_SUBTREE_MODELS) not in _sys.path:
    _sys.path.insert(0, str(_SUBTREE_MODELS))

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
    SupervisorEntry as SnapshotSupervisorEntry,
)

_LOG = logging.getLogger(__name__)

ALL_STREAMS: Final[tuple[str, ...]] = (
    "plans",
    "gates",
    "inbox",
    "supervisors",
    "quota",
    "decisions",
    "evidence_refs",
)

_VALID_REDACT_LEVELS: Final[frozenset[str]] = frozenset(
    {"public", "operator", "full"}
)

INBOX_DEFAULT_LIMIT: Final[int] = 100
DECISIONS_DEFAULT_LIMIT: Final[int] = 100

# Map quota_state.json window kinds to the F001 schema enum.
# rolling_5h is the short-horizon Anthropic / OpenAI throttle window;
# rolling_7d is the weekly-cap window most vendors expose.
_WINDOW_MAPPING: Final[dict[str, str]] = {
    "rolling_5h": "daily",
    "rolling_7d": "weekly",
    "rolling_30d": "monthly",
}


# ─────────────────── public API ───────────────────


def gather(
    plans_root: Path,
    *,
    redact_level: str = "operator",
    include: Iterable[str] = ALL_STREAMS,
    plan_id: str | None = None,
    inbox_limit: int = INBOX_DEFAULT_LIMIT,
    decisions_limit: int = DECISIONS_DEFAULT_LIMIT,
    captured_at: dt.datetime | None = None,
    dontpanic_version: str | None = None,
    quota_state_path: Path | None = None,
) -> StateSnapshot:
    """Build a StateSnapshot from canonical local state.

    Pure-read: no writes. See module docstring for stream-by-stream
    source-of-truth.

    Raises:
        ValueError: invalid redact_level or unknown stream name in
            `include`.
        FileNotFoundError / pydantic.ValidationError: when a plan
            directory contains malformed plan.md or features.json
            (bubbled from plan_loader.load).
    """
    if redact_level not in _VALID_REDACT_LEVELS:
        raise ValueError(
            f"redact_level={redact_level!r} not in {sorted(_VALID_REDACT_LEVELS)}"
        )

    include_set = frozenset(include)
    unknown = include_set - frozenset(ALL_STREAMS)
    if unknown:
        raise ValueError(
            f"unknown stream(s) in include: {sorted(unknown)}; "
            f"valid: {list(ALL_STREAMS)}"
        )

    captured_at = captured_at or dt.datetime.now(dt.timezone.utc)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=dt.timezone.utc)

    quota_state_path = quota_state_path or circuit_breakers.QUOTA_STATE_PATH

    # Discover plan dirs under plans_root.
    plan_dirs = _discover_plan_dirs(plans_root, plan_id=plan_id)

    # Per-stream gather.
    plans_out: list[PlanSummary] = []
    gates_out: list[GateEntry] = []
    inbox_out: list[InboxEvent] = []
    decisions_out: list[DecisionEntry] = []
    evidence_out: list[EvidencePointer] = []

    if any(s in include_set for s in ("plans", "gates", "inbox", "decisions", "evidence_refs")):
        for plan_dir in plan_dirs:
            loaded = plan_loader.load(plan_dir)
            if "plans" in include_set:
                plans_out.append(_project_plan(loaded))
            if "gates" in include_set:
                gates_out.extend(_gather_gates(loaded))
            if "inbox" in include_set:
                inbox_out.extend(_gather_inbox(loaded))
            if "decisions" in include_set:
                decisions_out.extend(_gather_decisions(loaded))
            if "evidence_refs" in include_set:
                evidence_out.extend(_gather_evidence_refs(loaded))

    # Newest-first then cap.
    if inbox_out:
        inbox_out.sort(key=lambda e: e.captured_at, reverse=True)
        inbox_out = inbox_out[:inbox_limit]
    if decisions_out:
        decisions_out.sort(key=lambda d: d.ts, reverse=True)
        decisions_out = decisions_out[:decisions_limit]

    # Global streams: supervisors + quota. plan_id filter applied
    # to supervisors when set (quota stays global — operator-wide
    # budget signal, not per-plan).
    supervisors_out: list[SnapshotSupervisorEntry] = []
    if "supervisors" in include_set:
        supervisors_out = _gather_supervisors(plan_id=plan_id)

    quota_out: list[QuotaEntry] = []
    if "quota" in include_set:
        quota_out = _gather_quota(quota_state_path, captured_at=captured_at)

    return StateSnapshot(
        schema_version="1.0",
        captured_at=captured_at,
        dontpanic_version=dontpanic_version,
        redact_level=RedactLevel(redact_level),
        streams=Streams(
            plans=plans_out,
            gates=gates_out,
            inbox=inbox_out,
            supervisors=supervisors_out,
            quota=quota_out,
            decisions=decisions_out,
            evidence_refs=evidence_out,
        ),
    )


# ─────────────────── plan discovery ───────────────────


def _discover_plan_dirs(plans_root: Path, *, plan_id: str | None) -> list[Path]:
    """Return ordered list of plan dirs under plans_root.

    Excludes any dir that doesn't have a plan.md (so adapter plans-root
    can sit alongside unrelated subdirs without breaking gather).
    """
    if not plans_root.exists() or not plans_root.is_dir():
        return []
    if plan_id is not None:
        candidate = plans_root / plan_id
        if (candidate / "plan.md").is_file():
            return [candidate]
        return []
    out: list[Path] = []
    for child in sorted(plans_root.iterdir()):
        if child.is_dir() and (child / "plan.md").is_file():
            out.append(child)
    return out


# ─────────────────── plans stream ───────────────────


def _project_plan(loaded: plan_loader.LoadedPlan) -> PlanSummary:
    total = len(loaded.features.features)
    passing = sum(1 for f in loaded.features.features if f.passes)
    return PlanSummary(
        plan_id=loaded.plan_id,
        status=loaded.plan.status.value,
        title=loaded.plan.title,
        type=loaded.plan.type.value,
        tier=loaded.plan.tier.value if loaded.plan.tier else None,
        goal_type=loaded.plan.goal_type.value if loaded.plan.goal_type else None,
        surfaces=list(loaded.surfaces),
        features_summary={"total": total, "passing": passing},
        target_env=loaded.target_env,
        target_project=loaded.target_project,
        agents_required=[a for a in (loaded.plan.agents_required or [])],
        date=str(loaded.plan.date) if loaded.plan.date else None,
    )


# ─────────────────── gates stream ───────────────────


def _gather_gates(loaded: plan_loader.LoadedPlan) -> list[GateEntry]:
    declared = loaded.plan.human_gates or []
    if not declared:
        return []
    unmet = gate_pause.unmet_gates(loaded.plan_dir, list(declared))
    if not unmet:
        return []
    # Schema requires paused_at. Cleared-gate history lives in
    # gate-state.json but unmet entries have no recorded pause time.
    # Use plan dir mtime as a stable proxy; consumers treat
    # paused_at as "first observed unmet at" not "operator-paused-at".
    try:
        mtime = loaded.plan_dir.stat().st_mtime
        paused_at = dt.datetime.fromtimestamp(mtime, tz=dt.timezone.utc)
    except OSError:
        paused_at = dt.datetime.now(dt.timezone.utc)
    out: list[GateEntry] = []
    for gate_name in unmet:
        kind = _classify_gate_kind(gate_name)
        out.append(
            GateEntry(
                plan_id=loaded.plan_id,
                gate_name=gate_name,
                kind=kind,
                stage=gate_name if kind in ("pre_impl", "pre_merge") else None,
                reason="declared gate not cleared",
                paused_at=paused_at,
                approval_required=kind in ("pre_impl", "pre_merge", "breaker"),
                feature_id=None,
            )
        )
    return out


def _classify_gate_kind(gate_name: str) -> str:
    if gate_name == "pre_impl":
        return "pre_impl"
    if gate_name == "pre_merge":
        return "pre_merge"
    if gate_name.startswith("breaker:"):
        return "breaker"
    if gate_name.startswith("defer:"):
        return "defer"
    return "custom"


# ─────────────────── inbox stream ───────────────────


def _gather_inbox(loaded: plan_loader.LoadedPlan) -> list[InboxEvent]:
    try:
        entries = inbox.read_events(loaded.plan_dir)
    except FileNotFoundError:
        return []
    out: list[InboxEvent] = []
    for e in entries:
        ts = _parse_iso(e.timestamp) or dt.datetime.now(dt.timezone.utc)
        feature_id = e.headers.get("feature_id")
        # Empty string for feature_id slot when missing — matches the
        # event_id composite spec in the F001 schema ($defs/inbox_event).
        event_id = f"{loaded.plan_id}:{e.event}:{e.timestamp}:{feature_id or ''}"
        out.append(
            InboxEvent(
                plan_id=loaded.plan_id,
                event=e.event,
                event_id=event_id,
                captured_at=ts,
                feature_id=feature_id,
                body=e.body or None,
                headers={k: str(v) for k, v in e.headers.items()},
            )
        )
    return out


# ─────────────────── supervisors stream ───────────────────


def _gather_supervisors(*, plan_id: str | None) -> list[SnapshotSupervisorEntry]:
    try:
        # prune=False preserves the pure-read invariant. list_active
        # with prune=True rewrites the registry when dead entries are
        # filtered; state projection must never mutate operator state.
        entries = active_supervisors.list_active(prune=False)
    except Exception:
        # Registry malformed — surface empty rather than break the snapshot.
        _LOG.warning("active_supervisors.list_active() failed; emitting empty stream")
        return []
    host = socket.gethostname() or None
    out: list[SnapshotSupervisorEntry] = []
    for e in entries:
        if plan_id is not None and e.plan_id != plan_id:
            continue
        sid = f"{e.pid}:{e.started_at}"
        started = _parse_iso(e.started_at) or dt.datetime.now(dt.timezone.utc)
        out.append(
            SnapshotSupervisorEntry(
                supervisor_id=sid,
                plan_id=e.plan_id,
                feature_id=None,
                implementer_agent=None,
                auditor_agent=None,
                started_at=started,
                host=host,
                pid=e.pid,
            )
        )
    return out


# ─────────────────── quota stream ───────────────────


def _gather_quota(
    quota_state_path: Path, *, captured_at: dt.datetime
) -> list[QuotaEntry]:
    if not quota_state_path.is_file():
        return []
    try:
        data = json.loads(quota_state_path.read_text())
    except (OSError, json.JSONDecodeError):
        _LOG.warning("quota_state at %s unreadable; emitting empty stream", quota_state_path)
        return []
    out: list[QuotaEntry] = []
    vendors = data.get("vendors", {})
    for vendor_name, vblock in vendors.items():
        if vendor_name not in ("claude", "codex", "gemini", "grok"):
            continue
        windows = (vblock or {}).get("windows", {})
        for window_kind, wblock in windows.items():
            mapped = _WINDOW_MAPPING.get(window_kind)
            if mapped is None:
                continue
            wblock = wblock or {}
            status = wblock.get("status", "ok")
            if status not in (
                "ok",
                "warn",
                "exceeded",
                "calibration_required",
                "config_required",
                "unit_mismatch",
            ):
                status = "ok"
            out.append(
                QuotaEntry(
                    vendor=vendor_name,
                    window=mapped,
                    percent_of_cap=wblock.get("percent_of_cap"),
                    percent_threshold=wblock.get("percent_threshold"),
                    status=status,
                    captured_at=captured_at,
                )
            )
    return out


# ─────────────────── decisions stream ───────────────────


def _gather_decisions(loaded: plan_loader.LoadedPlan) -> list[DecisionEntry]:
    path = loaded.plan_dir / "decisions.jsonl"
    if not path.is_file():
        return []
    out: list[DecisionEntry] = []
    try:
        text = path.read_text()
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            _LOG.warning("decisions.jsonl line in %s is not valid JSON; skipping", path)
            continue
        if not isinstance(obj, dict):
            continue
        decision_id = obj.get("id") or obj.get("decision_id")
        ts_str = obj.get("ts") or obj.get("timestamp")
        title = obj.get("title")
        if not decision_id or not ts_str or not title:
            continue
        ts = _parse_iso(ts_str)
        if ts is None:
            continue
        out.append(
            DecisionEntry(
                plan_id=loaded.plan_id,
                decision_id=decision_id,
                ts=ts,
                by=obj.get("by") or "unknown",
                title=title,
                body=obj.get("body"),
            )
        )
    return out


# ─────────────────── evidence_refs stream ───────────────────


def _gather_evidence_refs(loaded: plan_loader.LoadedPlan) -> list[EvidencePointer]:
    out: list[EvidencePointer] = []
    for feat in loaded.features.features:
        refs = feat.evidence_refs or []
        for ref in refs:
            if isinstance(ref, dict):
                ref_dict = ref
            elif hasattr(ref, "model_dump"):
                # mode="json" serializes enums to their string values so
                # we can re-validate cleanly against state_snapshot_model's
                # independent Type enum (different class, same string set).
                ref_dict = ref.model_dump(mode="json")
            else:
                ref_dict = {}
            type_ = ref_dict.get("type")
            uri = ref_dict.get("uri")
            if not type_ or not uri:
                continue
            out.append(
                EvidencePointer(
                    plan_id=loaded.plan_id,
                    feature_id=feat.id,
                    type=type_,
                    uri=uri,
                    captured_at=None,
                    captured_by=None,
                    note=ref_dict.get("note"),
                )
            )
    return out


# ─────────────────── helpers ───────────────────


def _parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        # fromisoformat handles 'Z' suffix on 3.11+; pad for 3.10 by
        # swapping in +00:00.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(s)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return None


__all__ = [
    "ALL_STREAMS",
    "INBOX_DEFAULT_LIMIT",
    "DECISIONS_DEFAULT_LIMIT",
    "gather",
]
