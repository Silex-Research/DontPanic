"""Plan 2026-06-17-001 F003 — ledger adapter + registry adapter + pure reconcile.

This module is the **logic core** of usage-driven canonical-repo discovery. It has
three pieces and NO presentation layer (F004 owns the CLI / formatting):

* :func:`observed_canonical_from_ledger` — the explicit ledger IO adapter. It reads
  already-parsed ``invocations.jsonl`` records into ``observed_canonical`` rows,
  aggregating by ``canonical_repo.path_key``: it sums ``observed_count`` (legacy /
  no-field rows count as ``1``), takes the max valid ``last_seen``, preserves the
  scrubbed ``path_display`` and ``durable_checkout`` / ``origin_key``, and **never**
  reads ``record.command`` (C6). Records without a durable ``canonical_repo``, or
  marked ``canonical_compaction_conflict=true``, are skipped (C2/C3). A contributing
  record whose ``last_seen`` is missing or unparseable is skipped from the max
  rather than poisoning the whole aggregate; if no contributing record has a valid
  ``last_seen`` the row emits ``last_seen=None`` and fails the recency threshold
  (fail-closed, C5).

* :func:`registered_canonical_from_registry` — the registry-side IO adapter. For
  each :class:`~dontpanic_orchestrate.projects_registry.ProjectEntry` it checks path
  existence and canonicalizes (via the same F001 ``canonicalize_repo`` the ledger
  writer uses) into an enriched row. Missing / unresolved paths emit
  ``canonical_repo_key=None`` plus a ``registry_path_key`` fallback. Dedup is applied
  ONLY to entries eligible for a registered_active/registered_stale row (active,
  path-exists, canonicalized); the lexicographically-first ``registry_name`` wins and
  the collision is surfaced via ``registry_conflict`` / ``conflicting_registry_names``.
  An inactive / path-missing / unresolved entry is EXCLUDED from the dedup and can
  never suppress an active entry for the same key (C5).

* :func:`reconcile` — the PURE join. Given enriched registered rows, aggregated
  observed rows, ``now``, and a :class:`DiscoveryPolicy`, it returns the five-state
  projection ``{used_unregistered, registered_active, registered_stale,
  registered_path_missing, registered_unresolved}``. It performs NO filesystem or git
  IO and reads only structured metadata + timestamps (C6). C5 thresholds
  (``window_days=14``, ``min_count=2``, ``last_seen``, inclusive boundaries) and the
  pinned registered active/stale truth table are applied here, temp / non-durable
  usage is gated out of recommendations (C3), and deterministic, regex-safe,
  collision-safe ``suggested_name`` values are derived for the unregistered
  candidates.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dontpanic_orchestrate import invocation_ledger as il
from dontpanic_orchestrate.completion_dispatch import sanitize_capture
from dontpanic_orchestrate.projects_registry import PROJECT_NAME_PATTERN, ProjectEntry

_LOG = logging.getLogger(__name__)

# Canonicalization status values for a registered entry (C5 matrix).
CANON_OK = "ok"
CANON_MISSING = "missing"
CANON_UNRESOLVED = "unresolved"

_DEFAULT_SUGGESTED_NAME = "project"
_MAX_NAME_LEN = 64


# ──────────────────────────────  policy (C5)  ──────────────────────────────


@dataclass(frozen=True)
class DiscoveryPolicy:
    """Pinned C5 decay / threshold policy. ``window_days`` and ``min_count`` are
    overridable by the F004 command; the timestamp field is fixed to ``last_seen``
    and both boundaries are inclusive."""

    window_days: int = 14
    min_count: int = 2


# ──────────────────────────────  timestamp helpers  ──────────────────────────────


def _parse_iso(value: Any) -> datetime.datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC datetime, or ``None`` when the
    value is missing / not a string / unparseable. A trailing ``Z`` is normalized to
    ``+00:00``; a naive timestamp is assumed UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _coerce_now(now: Any) -> datetime.datetime:
    """Normalize the caller's ``now`` (a datetime or ISO string) to aware UTC."""
    if isinstance(now, datetime.datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=datetime.timezone.utc)
        return now.astimezone(datetime.timezone.utc)
    parsed = _parse_iso(now)
    if parsed is None:
        raise ValueError(f"reconcile() requires a valid `now`; got {now!r}")
    return parsed


def _passes_recency(last_seen: str | None, now: datetime.datetime, window_days: int) -> bool:
    """True iff ``last_seen`` parses and is within the inclusive recency window.
    Missing / invalid timestamps fail closed (C5)."""
    seen = _parse_iso(last_seen)
    if seen is None:
        return False
    cutoff = now - datetime.timedelta(days=window_days)
    return seen >= cutoff


# ──────────────────────────────  ledger adapter (observed_canonical)  ──────────────────────────────


def _record_observed_count(record: Mapping[str, Any]) -> int:
    """Observation count contributed by ``record``. Legacy / no-field rows count as
    ``1``; rows carrying a valid non-negative ``observed_count`` int use it (so sums
    stay correct across ledger compaction). Mirrors the ledger writer's rule."""
    value = record.get("observed_count")
    if isinstance(value, bool):  # bool is an int subclass — treat as legacy
        return 1
    if isinstance(value, int) and value >= 0:
        return value
    return 1


def _canonical_of(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The durable ``canonical_repo`` mapping to attribute this record to, or
    ``None`` when the record carries no durable canonical attribution (C2/C3):

    * ``canonical_compaction_conflict=true`` -> skip (mixed-attribution row);
    * no ``canonical_repo`` mapping, or no string ``path_key`` -> skip;
    * ``durable_checkout`` not exactly ``True`` -> skip (only durable repos are
      ever discovery candidates, C3).
    """
    if record.get("canonical_compaction_conflict") is True:
        return None
    canonical = record.get("canonical_repo")
    if not isinstance(canonical, Mapping):
        return None
    key = canonical.get("path_key")
    if not isinstance(key, str) or not key:
        return None
    if canonical.get("durable_checkout") is not True:
        return None
    return canonical


def observed_canonical_from_ledger(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate parsed ledger ``records`` into ``observed_canonical`` rows (C2/C5).

    Each returned row is keyed on ``canonical_repo_key`` (``canonical_repo.path_key``)
    and carries ``{canonical_repo_key, path_display, durable_checkout, observed_count,
    last_seen, origin_key?}``:

    * ``observed_count`` is the SUM of contributing ``observed_count`` values
      (legacy / no-field rows count as ``1``);
    * ``last_seen`` is the MAX valid ISO-8601 ``last_seen`` across contributors —
      contributors whose ``last_seen`` is missing / unparseable are skipped from the
      max (an invalid timestamp never poisons the aggregate), and a row with no valid
      contributor emits ``last_seen=None``;
    * ``path_display`` / ``durable_checkout`` / ``origin_key`` are taken from the
      contributing canonical metadata (all contributors share one canonical key).

    ``record.command`` is NEVER read (C6)."""
    rows: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        canonical = _canonical_of(record)
        if canonical is None:
            continue
        key = str(canonical["path_key"])
        row = rows.get(key)
        if row is None:
            row = {
                "canonical_repo_key": key,
                "path_display": canonical.get("path_display"),
                "durable_checkout": True,
                "observed_count": 0,
                "last_seen": None,
                "_last_seen_dt": None,
            }
            origin = canonical.get("origin_key")
            if isinstance(origin, str) and origin:
                row["origin_key"] = origin
            rows[key] = row

        row["observed_count"] += _record_observed_count(record)

        seen_dt = _parse_iso(record.get("last_seen"))
        if seen_dt is not None and (
            row["_last_seen_dt"] is None or seen_dt > row["_last_seen_dt"]
        ):
            row["_last_seen_dt"] = seen_dt
            row["last_seen"] = record.get("last_seen")

    out: list[dict[str, Any]] = []
    for row in rows.values():
        row.pop("_last_seen_dt", None)
        out.append(row)
    out.sort(key=lambda r: r["canonical_repo_key"])
    return out


# ──────────────────────────────  registry adapter (registered_canonical)  ──────────────────────────────


def _registry_path_key(stored_path: str) -> str:
    """``sha256(normalized stored registry path)[:16]`` — the fallback identity for
    a registered entry whose path is missing or unresolved (so it can never be keyed
    on a canonical_repo_key it does not have, C5)."""
    norm = os.path.abspath(os.path.expanduser(str(stored_path)))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _enrich_entry(entry: ProjectEntry) -> dict[str, Any]:
    """Enrich one registry entry with path existence + canonicalization (C5 matrix).

    Returns ``{name, active, path_display, canonical_repo_key, path_exists,
    canonicalization_status, registry_path_key}``. ``active`` is ``True`` unless the
    entry is explicitly ``active=false`` (legacy ``None`` is treated as active).
    ``registry_path_key`` is always present; ``canonical_repo_key`` is ``None`` for
    missing / unresolved paths."""
    stored_path = str(entry.path)
    active = entry.active is not False
    registry_path_key = _registry_path_key(stored_path)
    base: dict[str, Any] = {
        "name": entry.name,
        "active": active,
        "registry_path_key": registry_path_key,
    }

    if not os.path.isdir(stored_path):
        # Missing path: cannot be probed/canonicalized.
        return {
            **base,
            "path_display": sanitize_capture(stored_path) or stored_path,
            "canonical_repo_key": None,
            "path_exists": False,
            "canonicalization_status": CANON_MISSING,
        }

    try:
        resolved = il.canonicalize_repo(stored_path)
    except Exception as exc:  # noqa: BLE001 — a canonicalization failure is "unresolved"
        _LOG.warning("registry canonicalization failed for %s: %s", entry.name, exc)
        resolved = {"canonical_root": None}

    canonical_root = resolved.get("canonical_root")
    pair = il.make_path_pair(canonical_root) if canonical_root is not None else None
    if canonical_root is None or pair is None:
        # Path exists but canonicalization failed (e.g. resolves under a temp prefix).
        return {
            **base,
            "path_display": sanitize_capture(stored_path) or stored_path,
            "canonical_repo_key": None,
            "path_exists": True,
            "canonicalization_status": CANON_UNRESOLVED,
        }

    return {
        **base,
        "path_display": pair["path_display"],
        "canonical_repo_key": pair["path_key"],
        "path_exists": True,
        "canonicalization_status": CANON_OK,
    }


def registered_canonical_from_registry(entries: Sequence[ProjectEntry]) -> list[dict[str, Any]]:
    """Enrich + dedupe registry ``entries`` into ``registered_canonical`` rows (C5).

    Entries eligible for a registered_active/registered_stale row (``active=True``,
    ``path_exists=True``, canonicalization ``ok``) are deduped per
    ``canonical_repo_key`` BEFORE any inactive / missing / unresolved entry is
    considered, so an ineligible entry can NEVER suppress an active entry for the same
    key regardless of name order. When two or more eligible entries collide on one key
    the lexicographically-first ``registry_name`` wins; the surviving row carries
    ``registry_conflict=True`` and ``conflicting_registry_names`` (the sorted colliding
    active names). A single eligible entry sets ``registry_conflict=False``.

    Inactive / missing / unresolved entries pass through individually (one row each,
    ``registry_conflict=False``) so the reconcile matrix can classify them on their
    own terms."""
    enriched = [_enrich_entry(e) for e in entries]

    eligible: dict[str, list[dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in enriched:
        is_eligible = (
            row["active"]
            and row["path_exists"]
            and row["canonicalization_status"] == CANON_OK
            and row["canonical_repo_key"] is not None
        )
        if is_eligible:
            eligible.setdefault(row["canonical_repo_key"], []).append(row)
        else:
            passthrough.append({**row, "registry_conflict": False, "conflicting_registry_names": []})

    out: list[dict[str, Any]] = []
    for _key, group in eligible.items():
        names = sorted(r["name"] for r in group)
        winner = min(group, key=lambda r: r["name"])
        out.append(
            {
                **winner,
                "registry_conflict": len(group) > 1,
                "conflicting_registry_names": names if len(group) > 1 else [],
            }
        )
    out.extend(passthrough)
    return out


# ──────────────────────────────  suggested_name (C5)  ──────────────────────────────


def _basename_of_display(path_display: str) -> str:
    """Basename of a scrubbed ``path_display`` (``<home>/src/DontPanic`` ->
    ``DontPanic``)."""
    trimmed = str(path_display).rstrip("/")
    return os.path.basename(trimmed) or trimmed


def _slugify(raw: str) -> str:
    """Lowercase, replace every non-``[a-z0-9-]`` char with ``-``, collapse repeated
    hyphens, trim leading/trailing hyphens; empty -> ``project`` (C5)."""
    lowered = raw.lower()
    hyphenated = re.sub(r"[^a-z0-9-]", "-", lowered)
    collapsed = re.sub(r"-+", "-", hyphenated).strip("-")
    return collapsed or _DEFAULT_SUGGESTED_NAME


def derive_suggested_name(
    path_display: str, canonical_repo_key: str, taken: set[str]
) -> str:
    """Deterministic, regex-safe, collision-safe project name for an unregistered
    candidate (C5).

    Derived from the scrubbed ``path_display`` basename; on collision with a name in
    ``taken`` the ``-<canonical_repo_key[:8]>`` suffix is appended (truncating the base
    so the whole name stays within 64 chars). If that hash-suffixed name is ITSELF
    already in ``taken``, the suffix is deterministically widened (more of the hash)
    and finally disambiguated with a numeric counter, so the returned name is always
    unique with respect to ``taken``. The result always matches
    :data:`projects_registry.PROJECT_NAME_PATTERN`."""
    base = _slugify(_basename_of_display(path_display))[:_MAX_NAME_LEN]
    if not PROJECT_NAME_PATTERN.fullmatch(base):
        base = _DEFAULT_SUGGESTED_NAME
    if base not in taken:
        return base

    key = str(canonical_repo_key)
    # Build deterministic, increasingly-specific suffixes: first the canonical-key
    # hash at growing widths, then a numeric disambiguator on the 8-char hash. The
    # numeric tail guarantees termination against any finite ``taken`` set.
    suffixes = ["-" + key[:width] for width in (8, 12, 16, len(key)) if 0 < width]
    suffixes += ["-" + key[:8] + "-" + str(n) for n in range(1, len(taken) + 2)]
    for suffix in suffixes:
        head = base[: _MAX_NAME_LEN - len(suffix)].rstrip("-") or _DEFAULT_SUGGESTED_NAME
        candidate = head + suffix
        if PROJECT_NAME_PATTERN.fullmatch(candidate) and candidate not in taken:
            return candidate

    # Defensive fallback: a bare hashed name is always regex-safe and ≤64 chars.
    return (_DEFAULT_SUGGESTED_NAME + "-" + key[:8])[:_MAX_NAME_LEN]


# ──────────────────────────────  reconcile (pure)  ──────────────────────────────


def reconcile(
    registered_canonical: Sequence[Mapping[str, Any]],
    observed_canonical: Sequence[Mapping[str, Any]],
    now: Any,
    policy: DiscoveryPolicy | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Pure registry-vs-observed join -> five-state projection (C5). No filesystem or
    git IO; reads only structured metadata + timestamps (C6).

    Returns ``{used_unregistered, registered_active, registered_stale,
    registered_path_missing, registered_unresolved}``:

    * ``used_unregistered`` / ``registered_active`` / ``registered_stale`` rows are
      keyed on ``canonical_repo_key``;
    * ``registered_path_missing`` / ``registered_unresolved`` rows are keyed by
      ``registry_name`` + ``registry_path_key`` with ``canonical_repo_key=None``.

    Zero-state inputs yield empty arrays."""
    policy = policy or DiscoveryPolicy()
    now_dt = _coerce_now(now)

    observed_by_key: dict[str, Mapping[str, Any]] = {
        str(row["canonical_repo_key"]): row
        for row in observed_canonical
        if row.get("canonical_repo_key")
    }

    used_unregistered: list[dict[str, Any]] = []
    registered_active: list[dict[str, Any]] = []
    registered_stale: list[dict[str, Any]] = []
    registered_path_missing: list[dict[str, Any]] = []
    registered_unresolved: list[dict[str, Any]] = []

    # Every canonical key a registered entry resolves to (active OR inactive) — an
    # observed repo matching any of these is already registered, so it can never be a
    # used_unregistered recommendation.
    registered_keys: set[str] = set()

    for row in registered_canonical:
        status = row.get("canonicalization_status")
        canonical_key = row.get("canonical_repo_key")
        if canonical_key:
            registered_keys.add(str(canonical_key))

        if status == CANON_MISSING:
            registered_path_missing.append(_null_keyed_row(row, CANON_MISSING))
            continue
        if status == CANON_UNRESOLVED:
            registered_unresolved.append(_null_keyed_row(row, CANON_UNRESOLVED))
            continue
        # canonicalization ok from here.
        if not row.get("active", True):
            # Explicitly inactive -> inventory only, no active/stale row (C5).
            continue

        observed = observed_by_key.get(str(canonical_key))
        classified = _classify_registered(row, observed, now_dt, policy)
        if classified["_state"] == "active":
            registered_active.append(classified["row"])
        else:
            registered_stale.append(classified["row"])

    # used_unregistered: durable observed repos with no registered entry, passing the
    # C5 thresholds. Deterministic order (by canonical_repo_key) keeps suggested_name
    # assignment stable.
    taken_names: set[str] = {str(r["name"]) for r in registered_canonical if r.get("name")}
    for observed in sorted(observed_canonical, key=lambda r: str(r["canonical_repo_key"])):
        key = str(observed["canonical_repo_key"])
        if key in registered_keys:
            continue
        if observed.get("durable_checkout") is not True:  # C3 belt-and-suspenders
            continue
        if int(observed.get("observed_count", 0)) < policy.min_count:
            continue
        if not _passes_recency(observed.get("last_seen"), now_dt, policy.window_days):
            continue
        path_display = str(observed.get("path_display") or "")
        suggested = derive_suggested_name(path_display, key, taken_names)
        taken_names.add(suggested)
        used_unregistered.append(
            {
                "canonical_repo_key": key,
                "path_display": observed.get("path_display"),
                "observed_count": int(observed.get("observed_count", 0)),
                "last_seen": observed.get("last_seen"),
                "suggested_name": suggested,
            }
        )

    registered_active.sort(key=lambda r: str(r["canonical_repo_key"]))
    registered_stale.sort(key=lambda r: str(r["canonical_repo_key"]))
    registered_path_missing.sort(key=lambda r: (str(r["registry_name"]), str(r["registry_path_key"])))
    registered_unresolved.sort(key=lambda r: (str(r["registry_name"]), str(r["registry_path_key"])))

    return {
        "used_unregistered": used_unregistered,
        "registered_active": registered_active,
        "registered_stale": registered_stale,
        "registered_path_missing": registered_path_missing,
        "registered_unresolved": registered_unresolved,
    }


def _null_keyed_row(row: Mapping[str, Any], status: str) -> dict[str, Any]:
    """Shape a registered_path_missing / registered_unresolved row: keyed by
    ``registry_name`` + ``registry_path_key``, ``canonical_repo_key=None``, and NO
    observed_count/last_seen (there is no canonical key to join usage to, C5)."""
    return {
        "canonical_repo_key": None,
        "registry_name": row.get("name"),
        "registry_path_key": row.get("registry_path_key"),
        "path_display": row.get("path_display"),
        "canonicalization_status": status,
    }


def _classify_registered(
    row: Mapping[str, Any],
    observed: Mapping[str, Any] | None,
    now: datetime.datetime,
    policy: DiscoveryPolicy,
) -> dict[str, Any]:
    """Classify a canonicalized, active registered entry as active vs stale (C5).

    A row with NO observed canonical row emits ``observed_count=0`` and
    ``last_seen=None`` (never a fabricated count/recency). Otherwise it is
    ``registered_active`` iff ``observed_count >= min_count`` AND ``last_seen`` is
    within the inclusive recency window; any other case is ``registered_stale``."""
    if observed is None:
        observed_count = 0
        last_seen: str | None = None
        is_active = False
    else:
        observed_count = int(observed.get("observed_count", 0))
        last_seen = observed.get("last_seen")
        is_active = observed_count >= policy.min_count and _passes_recency(
            last_seen, now, policy.window_days
        )

    out_row = {
        "canonical_repo_key": row.get("canonical_repo_key"),
        "registry_name": row.get("name"),
        "path_display": row.get("path_display"),
        "observed_count": observed_count,
        "last_seen": last_seen,
        "registry_conflict": bool(row.get("registry_conflict", False)),
        "conflicting_registry_names": list(row.get("conflicting_registry_names", [])),
    }
    return {"_state": "active" if is_active else "stale", "row": out_row}


__all__ = [
    "CANON_MISSING",
    "CANON_OK",
    "CANON_UNRESOLVED",
    "DiscoveryPolicy",
    "derive_suggested_name",
    "observed_canonical_from_ledger",
    "reconcile",
    "registered_canonical_from_registry",
]
