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

Failure policy v0: fail-fast on malformed plans by default. plan_loader
raises on invalid frontmatter / features; we let that bubble up so
strict callers (CI gates, state_cli) see the failure. Callers that
serve operator-local UX (dashboard build) may opt into per-plan
tolerance via ``tolerate_malformed_plans=True`` — see the gather()
signature — which skips offending plans with a callback so one bad
plan never zeros out the entire snapshot. Missing optional artifacts
(INBOX.md, decisions.jsonl, gate-state.json, quota_state.json) are
always handled gracefully — no error, just empty contributions.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import socket
import sys as _sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Final

from dontpanic_orchestrate import (
    active_supervisors,
    circuit_breakers,
    gate_pause,
    inbox,
    plan_loader,
)

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
)
from state_snapshot_model import (  # noqa: E402
    SupervisorEntry as SnapshotSupervisorEntry,
)

# Import secret-shape regexes from sanitization_check as the single
# source of truth. F003 redactor matches operator-level scrubbing
# coverage to what the OSS sanitization gate already enforces.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_DIR))
from sanitization_check import SECRET_REGEXES as _SECRET_REGEXES  # noqa: E402

_REDACT_PLACEHOLDER: Final[str] = "[REDACTED]"

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

# Plan 2026-06-04-004 F001 — real provenance: the actual upstream source each
# stream is projected FROM, declared as data on the manifest (not a hardcoded
# footer string). The canonical projection NEVER cites the legacy
# tasks.json / agents.json / activity.json adapters — those predate the
# state-snapshot projection and must not appear in provenance.
STREAM_PROVENANCE: Final[dict[str, str]] = {
    # plan-derived streams: plan_loader.load(<dir>) over docs/plans/**
    "plans": "docs/plans/**/plan.md + features.json (plan_loader)",
    "gates": "docs/plans/**/plan.md human_gates + audit/gate-state.json",
    "inbox": "docs/plans/**/INBOX.md (plan_loader)",
    "decisions": "docs/plans/**/decisions.jsonl (plan_loader)",
    "evidence_refs": "docs/plans/**/features.json evidence_refs (plan_loader)",
    # registry / state streams
    "supervisors": "active-supervisor registry (~/.dontpanic/active_supervisors.jsonl)",
    "quota": "quota_state.json (per-model rolling windows)",
}

# The legacy single-tenant adapters the canonical projection replaced. F001
# asserts none of these are ever cited as provenance or rendered.
LEGACY_SOURCES: Final[frozenset[str]] = frozenset(
    {"tasks.json", "agents.json", "activity.json"}
)


# Plan 2026-06-04-004 F003 — freshness contract. A view older than this is
# visibly flagged stale and the operator is given the exact refresh trigger.
DASHBOARD_STALENESS_THRESHOLD_SECONDS: Final[int] = 900  # 15 minutes
DASHBOARD_REFRESH_COMMAND: Final[str] = "dontpanic dashboard build"


def freshness_status(
    generated_at: dt.datetime,
    *,
    now: dt.datetime,
    threshold_seconds: int = DASHBOARD_STALENESS_THRESHOLD_SECONDS,
) -> dict[str, object]:
    """Plan 2026-06-04-004 F003 — compute the freshness envelope for a page.

    Returns ``generated_at`` (ISO), ``data_age_seconds`` (>= 0), ``is_stale``
    (age > threshold), ``staleness_threshold_seconds`` and the exact
    ``refresh_command`` so a stale view is both visibly stale AND re-fetchable.
    """
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    age = (now - generated_at).total_seconds()
    age = max(0.0, age)  # clock skew must never report a negative age
    return {
        "generated_at": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_age_seconds": age,
        "staleness_threshold_seconds": threshold_seconds,
        "is_stale": age > threshold_seconds,
        "refresh_command": DASHBOARD_REFRESH_COMMAND,
    }


def source_freshness(
    source_id: str,
    eval_map: "dict[str, dict[str, object]] | None",
    *,
    now: dt.datetime,
    threshold_seconds: int = DASHBOARD_STALENESS_THRESHOLD_SECONDS,
) -> dict[str, object]:
    """Plan 2026-06-04-005 F003 — per-source freshness (NOT snapshot-wide).

    ``eval_map`` is keyed by source id; each entry carries when that source last
    evaluated (``evaluated_at`` ISO) and whether the evaluation succeeded
    (``eval_ok``). Returns ``{source, evaluated_at, age, is_stale, eval_ok}`` for
    one source, computed from THAT source's own stamp so a stale/failed producer
    cannot poison fresh siblings. An unknown source fails closed
    (``is_stale=True, eval_ok=False``): the render gate (F001 step 2) then demotes
    only that source's cards. ``eval_ok=False`` (recompute failed/skipped) is
    distinct from ``is_stale`` (old-but-evaluated) — both fail step 2, but for
    different, separately-reportable reasons.
    """
    entry = (eval_map or {}).get(source_id)
    if not entry:
        return {
            "source": source_id,
            "evaluated_at": None,
            "age": None,
            "is_stale": True,
            "eval_ok": False,
        }
    raw = entry.get("evaluated_at")
    eval_ok = bool(entry.get("eval_ok", True))
    evaluated_at: dt.datetime | None = None
    if isinstance(raw, dt.datetime):
        evaluated_at = raw
    elif isinstance(raw, str) and raw:
        try:
            evaluated_at = dt.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=dt.timezone.utc
            )
        except ValueError:
            evaluated_at = None
    if evaluated_at is None:
        # Stamp present but unparseable → cannot prove freshness → fail closed.
        return {
            "source": source_id,
            "evaluated_at": raw if isinstance(raw, str) else None,
            "age": None,
            "is_stale": True,
            "eval_ok": False,
        }
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    age = max(0.0, (now - evaluated_at).total_seconds())  # clamp clock skew
    return {
        "source": source_id,
        "evaluated_at": evaluated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "age": age,
        "is_stale": age > threshold_seconds,
        "eval_ok": eval_ok,
    }


def card_source_freshness(
    card: object,
    eval_map: "dict[str, dict[str, object]] | None",
    *,
    now: dt.datetime,
    threshold_seconds: int = DASHBOARD_STALENESS_THRESHOLD_SECONDS,
) -> dict[str, object]:
    """Per-source freshness for a card, keyed by its ``source`` attribute."""
    return source_freshness(
        getattr(card, "source", None),
        eval_map,
        now=now,
        threshold_seconds=threshold_seconds,
    )


def activity_summary(snapshot: "StateSnapshot") -> dict[str, object]:
    """Plan 2026-06-04-004 F002 — lifecycle vs activity as SEPARATE axes,
    each pinned to a DISTINCT source so no label conflates plan lifecycle with
    live agent execution.

    * ``active_plans`` — plans whose lifecycle status == "active" (a property of
      the plan ledger; says nothing about whether an agent is running).
    * ``live_now`` — count of active supervisors from the registry (the ONLY
      source that may claim live execution).

    The old "Running N" label conflated these (it counted status==active plans
    but implied N live agents). Consumers render ``active_plans`` as "Active
    Plans" and ``live_now`` as "Live Now"; when ``live_now == 0`` nothing on the
    board may claim live execution.
    """
    plans = snapshot.streams.plans
    supervisors = snapshot.streams.supervisors

    def _status_str(p: object) -> object:
        # PlanSummary.status may be a Status enum (live model) or a plain str
        # (dict form / stubs). Coerce so the comparison never silently fails —
        # the same enum-vs-string trap that bit the gate predicate.
        s = getattr(p, "status", None)
        return s.value if hasattr(s, "value") else s

    active_plans = sum(1 for p in plans if _status_str(p) == "active")
    return {
        "active_plans": active_plans,
        "active_plans_source": STREAM_PROVENANCE["plans"],
        "live_now": len(supervisors),
        "live_now_source": STREAM_PROVENANCE["supervisors"],
        # Explicit honesty flag the renderer keys off: only TRUE when the live
        # registry actually reports a running supervisor.
        "claims_live_execution": len(supervisors) > 0,
    }


def agent_attribution(snapshot: "StateSnapshot") -> dict[str, object]:
    """Plan 2026-06-04-004 F004 — read-only agent attribution: when supervisors
    are live, who is working which plan/feature, sourced ONLY from the
    active-supervisor registry. When none are live, ``none`` is True and the
    board says "none" (it must never invent attribution).

    ``live_count`` equals ``activity_summary.live_now`` by construction (both are
    the supervisor count) — the F005 invariant pins them together.
    """
    sups = snapshot.streams.supervisors
    attributions = [
        {
            "supervisor_id": getattr(s, "supervisor_id", None),
            "plan_id": getattr(s, "plan_id", None),
            "feature_id": getattr(s, "feature_id", None),
            "implementer_agent": getattr(s, "implementer_agent", None),
            "auditor_agent": getattr(s, "auditor_agent", None),
        }
        for s in sups
    ]
    return {
        "live_count": len(attributions),
        "attributions": attributions,
        "none": len(attributions) == 0,
        "source": STREAM_PROVENANCE["supervisors"],
    }

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
    tolerate_malformed_plans: bool = False,
    on_malformed_plan: Callable[[Path, Exception], None] | None = None,
) -> StateSnapshot:
    """Build a StateSnapshot from canonical local state.

    Pure-read: no writes. See module docstring for stream-by-stream
    source-of-truth.

    Args (selected):
        tolerate_malformed_plans: when True, plan_loader failures on a
            single plan_dir are caught and that plan is skipped instead
            of aborting the snapshot. Default False preserves the
            strict CI/state_cli contract. Dashboard build opts in so
            an unrelated bad plan (e.g. legacy ``target_env: local``)
            cannot zero out the operator's state-snapshot.json.
        on_malformed_plan: optional callback invoked as
            ``on_malformed_plan(plan_dir, exc)`` whenever
            ``tolerate_malformed_plans`` swallows a load failure.
            Useful for surfacing the skipped plan as a build warning.

    Raises:
        ValueError: invalid redact_level or unknown stream name in
            `include`.
        FileNotFoundError / pydantic.ValidationError: when a plan
            directory contains malformed plan.md or features.json
            and ``tolerate_malformed_plans`` is False (bubbled from
            plan_loader.load).
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
            try:
                loaded = plan_loader.load(plan_dir)
            except Exception as exc:  # noqa: BLE001 — opt-in tolerance only
                if not tolerate_malformed_plans:
                    raise
                if on_malformed_plan is not None:
                    on_malformed_plan(plan_dir, exc)
                else:
                    _LOG.warning(
                        "state_projection.gather skipping malformed plan %s: %s",
                        plan_dir,
                        exc,
                    )
                continue
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

    snapshot = StateSnapshot(
        schema_version="1.0",
        captured_at=captured_at,
        dontpanic_version=dontpanic_version,
        # Gather always builds at `full` internally; redact_to_level
        # applies the requested policy as a pure post-pass so callers
        # see exactly the level they asked for.
        redact_level=RedactLevel.full,
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
    return redact_to_level(snapshot, redact_level)


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


def scrub_secrets(s: str | None) -> str | None:
    """Replace every secret-shape match in ``s`` with ``[REDACTED]``.

    Single source-of-truth: SECRET_REGEXES from scripts/
    sanitization_check.py. New patterns added there propagate here
    automatically. Returns the input unchanged when no match.

    Plan 2026-05-24-004 F004 (D020): promoted from the private
    ``_scrub_secrets`` to a public symbol so the live notification
    sinks (Discord / terminal-notifier / INBOX rendered annotation)
    can bind to this helper without coupling to a private name. The
    private alias below is retained for any pre-F004 callers.
    """
    if not s:
        return s
    out = s
    for rx in _SECRET_REGEXES:
        out = rx.sub(_REDACT_PLACEHOLDER, out)
    return out


# Backward-compat alias for callers that bound to the pre-D020 private name.
_scrub_secrets = scrub_secrets


def _redact_plan(p: PlanSummary) -> PlanSummary:
    return p.model_copy(update={"title": _scrub_secrets(p.title)})


def _redact_gate(g: GateEntry, *, level: str) -> GateEntry:
    if level == "public":
        return g.model_copy(update={"reason": None})
    return g.model_copy(update={"reason": _scrub_secrets(g.reason)})


def _redact_inbox(e: InboxEvent, *, level: str) -> InboxEvent:
    if level == "public":
        # Drop body + headers entirely; event/event_id/feature_id stay
        # as stable surface IDs for adapters.
        return e.model_copy(update={"body": None, "headers": None})
    headers = e.headers or {}
    scrubbed_headers = {k: _scrub_secrets(v) or "" for k, v in headers.items()}
    return e.model_copy(
        update={
            "body": _scrub_secrets(e.body),
            "headers": scrubbed_headers,
        }
    )


def _redact_supervisor(s: SnapshotSupervisorEntry, *, level: str) -> SnapshotSupervisorEntry:
    if level == "public":
        return s.model_copy(update={"pid": None, "host": None})
    return s


def _redact_decision(d: DecisionEntry, *, level: str) -> DecisionEntry:
    if level == "public":
        return d.model_copy(update={"body": None, "title": _scrub_secrets(d.title)})
    return d.model_copy(
        update={
            "title": _scrub_secrets(d.title),
            "body": _scrub_secrets(d.body),
        }
    )


def _redact_evidence(ev: EvidencePointer, *, level: str) -> EvidencePointer:
    # URIs are relative paths / SHAs / public URLs by F006 contract —
    # never tokens. Only the free-form `note` field can carry secrets.
    return ev.model_copy(update={"note": _scrub_secrets(ev.note)})


def redact_to_level(snapshot: StateSnapshot, level: str) -> StateSnapshot:
    """Apply the per-level redaction policy and return a new snapshot.

    Pure: never mutates the input.

      - `full`     : returned as-is with redact_level metadata set
      - `operator` : every string field scrubbed for secret shapes via
                     SECRET_REGEXES; per-stream entries kept
      - `public`   : operator scrubbing plus
                     supervisor.pid/host → None,
                     decision.body → None, inbox.body/headers → None,
                     gate.reason → None,
                     quota stream → []

    Raises ValueError for any other level name.
    """
    if level not in _VALID_REDACT_LEVELS:
        raise ValueError(
            f"redact_level={level!r} not in {sorted(_VALID_REDACT_LEVELS)}"
        )
    if level == "full":
        return snapshot.model_copy(update={"redact_level": RedactLevel.full})

    s = snapshot.streams
    new_streams = Streams(
        plans=[_redact_plan(p) for p in s.plans],
        gates=[_redact_gate(g, level=level) for g in s.gates],
        inbox=[_redact_inbox(e, level=level) for e in s.inbox],
        supervisors=[_redact_supervisor(sup, level=level) for sup in s.supervisors],
        # F001 schema doc: "no quota agent breakdown" at public.
        quota=[] if level == "public" else s.quota,
        decisions=[_redact_decision(d, level=level) for d in s.decisions],
        evidence_refs=[_redact_evidence(e, level=level) for e in s.evidence_refs],
    )
    return snapshot.model_copy(
        update={
            "redact_level": RedactLevel(level),
            "streams": new_streams,
        }
    )


__all__ = [
    "ALL_STREAMS",
    "INBOX_DEFAULT_LIMIT",
    "DECISIONS_DEFAULT_LIMIT",
    "gather",
    "redact_to_level",
    "scrub_secrets",
]
