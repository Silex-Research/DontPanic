"""F001 — operator triage model: the single source of truth.

A pure, total classifier assigns every operator item exactly one ``operator_bucket``,
derived from the item's own fields plus a reconciled gate-state and a safety_class
consumed from the repair projection. The model also derives read-only concurrency/scope
metadata (scope, run_state, state_revision) by joining each item to the live
active-supervisors registry, and emits a canonical serialization + a data_quality
envelope. No producer asserts ``operator_bucket``; no renderer is referenced here.

See docs/plans/2026-06-06-001-feat-operator-triage-surface-v0/ (D003-D005, D022).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from enum import Enum

# Bands that are never operator ACTIONS — surfaced only on demand.
_QUIET_BANDS = frozenset({"info", "advisory"})

# safety_class values (consumed from the repair projection) that permit auto_safe.
# auto_safe is a STRICT subset of automatable: a command exists AND DontPanic may
# reversibly apply it. Without an asserted safety_class, an automatable item is
# merely agent_runnable (a human/agent runs it), never auto_safe.
_AUTO_SAFE_SAFETY = frozenset({"auto_safe"})

_PLAN_ID_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}-\d{3}-[a-z0-9-]+)\b")


class OperatorBucket(str, Enum):
    """Who must act on an item now. Closed enum; ``uncertain`` is fail-closed."""

    NEEDS_AUTH = "needs_auth"          # a human with credentials
    NEEDS_DECISION = "needs_decision"  # a human must judge (a live gate)
    AGENT_RUNNABLE = "agent_runnable"  # a command resolves it, no judgment
    AUTO_SAFE = "auto_safe"            # reversible derived-state DontPanic may apply
    QUIET = "quiet"                    # info/advisory; suppressed, inspectable
    UNCERTAIN = "uncertain"            # cannot classify confidently; surfaced


def _is_gate(item: Mapping[str, object]) -> bool:
    title = str(item.get("title") or "").lower()
    if "approval" in title or "gate " in title or title.startswith("gate"):
        return True
    clears = item.get("clears_when")
    if isinstance(clears, Mapping) and clears.get("predicate") == "gate_cleared":
        return True
    return str(item.get("id") or "").startswith("gate:")


def classify(
    item: Mapping[str, object],
    *,
    gate_live: bool,
    plan_status: str | None,
    safety_class: str | None,
) -> OperatorBucket:
    """Assign exactly one bucket. Pure and total: any input returns a bucket,
    defaulting to ``uncertain`` when the inputs do not support a confident call.

    ``gate_live`` is the reconciled liveness of a gate item (F003 produces it);
    ``safety_class`` is consumed from the repair projection (F001 does not own it).
    """
    band = item.get("band")
    if band in _QUIET_BANDS:
        return OperatorBucket.QUIET
    if item.get("resolution_class") == "operator_attested":
        return OperatorBucket.NEEDS_AUTH
    if _is_gate(item):
        return OperatorBucket.NEEDS_DECISION if gate_live else OperatorBucket.QUIET
    if item.get("automatable") is True and safety_class in _AUTO_SAFE_SAFETY:
        return OperatorBucket.AUTO_SAFE
    if item.get("resolution_class") == "command_resolvable":
        return OperatorBucket.AGENT_RUNNABLE
    return OperatorBucket.UNCERTAIN


def _item_plan_id(item: Mapping[str, object]) -> str | None:
    clears = item.get("clears_when")
    if isinstance(clears, Mapping):
        params = clears.get("params")
        if isinstance(params, Mapping) and params.get("plan_id"):
            return str(params["plan_id"])
    for field in ("id", "dedupe_key", "title"):
        m = _PLAN_ID_RE.search(str(item.get(field) or ""))
        if m:
            return m.group(1)
    return None


def derive_run_state(
    item: Mapping[str, object],
    *,
    live_supervisors: Sequence[Mapping[str, object]],
) -> str:
    """idle / running / conflicted — derived read-only by joining the item's plan_id
    to the live active-supervisors registry. conflicted = >1 live supervisor on the
    same plan. No claim/lease is written (D023)."""
    plan_id = _item_plan_id(item)
    if plan_id is None:
        return "idle"
    matches = sum(1 for s in live_supervisors if str(s.get("plan_id")) == plan_id)
    if matches > 1:
        return "conflicted"
    if matches == 1:
        return "running"
    return "idle"


def derive_scope(item: Mapping[str, object]) -> tuple[str, str | None]:
    """('project', name) when the item carries a project; ('global', None) otherwise
    (a null target = global/install-config work)."""
    project = item.get("project_name")
    if project:
        return ("project", str(project))
    return ("global", None)


def _actor_label(item: Mapping[str, object], live_supervisors: Sequence[Mapping[str, object]]) -> str | None:
    """Coarse actor label for a running item. Uses agent+session when the registry
    has been enriched, else a pid/started-at fallback. None when not running."""
    plan_id = _item_plan_id(item)
    if plan_id is None:
        return None
    for s in live_supervisors:
        if str(s.get("plan_id")) == plan_id:
            agent = s.get("agent")
            session = s.get("session")
            if agent:
                return f"{agent}{f' · {session}' if session else ''}"
            pid, started = s.get("pid"), s.get("started_at")
            if pid is not None:
                return f"pid {pid}{f' since {started}' if started else ''}"
    return None


# Plan statuses whose gates are terminally stale (F003).
_TERMINAL_PLAN_STATUS = frozenset({"completed", "abandoned"})


def is_stale_gate(*, plan_status: str | None, all_features_pass: bool) -> bool:
    """F003 — a gate is stale (reconcile to cleared) when its plan is terminal
    (completed/abandoned) OR all its features already pass."""
    return plan_status in _TERMINAL_PLAN_STATUS or bool(all_features_pass)


def _richness(item: Mapping[str, object]) -> tuple[str, int]:
    return (str(item.get("updated_at") or ""), len(str(item.get("evidence_uri") or "")))


def dedupe_items(items: Sequence[Mapping[str, object]]) -> list[dict]:
    """F002 — collapse items sharing a ``dedupe_key`` to one representative (freshest
    updated_at, then most evidence), carrying a ``duplicate_count``. Items without a
    dedupe_key pass through unchanged. Deterministic; preserves first-seen order."""
    groups: dict[str, list[Mapping[str, object]]] = {}
    order: list[str] = []
    passthrough: list[dict] = []
    for it in items:
        key = it.get("dedupe_key")
        if not key:
            passthrough.append(dict(it))
            continue
        key = str(key)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(it)
    result: list[dict] = []
    for key in order:
        group = groups[key]
        rep = dict(max(group, key=_richness))
        rep["duplicate_count"] = len(group)
        result.append(rep)
    return result + passthrough


def _fingerprint(model: Mapping[str, object]) -> str:
    payload = {k: v for k, v in model.items() if k != "state_revision"}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def build_triage(
    items: Sequence[Mapping[str, object]],
    *,
    safety_class_for: Callable[[Mapping[str, object]], str | None],
    live_supervisors: Sequence[Mapping[str, object]],
    gate_live_for: Callable[[Mapping[str, object]], bool] | None = None,
    dedupe: bool = False,
) -> dict:
    """Build the canonical triage serialization: every item gets its bucket + derived
    concurrency/scope fields, plus a data_quality envelope and a stable state_revision
    fingerprint. This serialization is the parity anchor every consumer reads.

    ``gate_live_for`` defaults to treating gates as live (F003 supplies reconciled
    liveness later); ``safety_class_for`` is the repair-projection lookup.
    """
    gate_live_for = gate_live_for or (lambda _it: True)
    if dedupe:
        items = dedupe_items(items)
    out_items: list[dict] = []
    for it in items:
        scope, project = derive_scope(it)
        bucket = classify(
            it,
            gate_live=gate_live_for(it),
            plan_status=None,
            safety_class=safety_class_for(it),
        )
        out_items.append(
            {
                "id": it.get("id"),
                "operator_bucket": bucket.value,
                "scope": scope,
                "project_name": project,
                "run_state": derive_run_state(it, live_supervisors=live_supervisors),
                "actor_label": _actor_label(it, live_supervisors),
                "dedupe_key": it.get("dedupe_key"),
                "duplicate_count": it.get("duplicate_count", 1),
                "exact_command": it.get("exact_command"),
            }
        )
    counts = Counter(i["operator_bucket"] for i in out_items)
    data_quality = {
        "total": len(out_items),
        "counts": dict(counts),
        "uncertain": counts.get(OperatorBucket.UNCERTAIN.value, 0),
    }
    model = {
        "schema": "operator-triage/v0",
        "item_count": len(out_items),
        "items": out_items,
        "data_quality": data_quality,
    }
    model["state_revision"] = _fingerprint(model)
    return model
