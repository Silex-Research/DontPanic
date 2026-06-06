"""Plan 2026-06-05-004 F004 — disposition vocabulary + per-plan conventions ledger.

The accountability primitive: for each sufficiency-pack item applicable to a plan's
surfaces, the plan records a disposition. The ledger lives in a DEDICATED per-plan file
``docs/plans/<id>/conventions.json`` (kept out of features.json to avoid bloat).

Per-item validation status:
- ``disposed-ok``           — a valid disposition (with a reason / evidence where required)
- ``missing``               — applicable item has no ledger entry
- ``invalid``               — unknown disposition, or a non-applied disposition with no reason
- ``applied-without-evidence`` — applied but no evidence reference (a v0 WARN, not ok)
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

DISPOSITIONS: frozenset[str] = frozenset({"applied", "not-applicable", "deferred", "waived"})
# The three non-applied dispositions require a non-empty reason.
_REASON_REQUIRED: frozenset[str] = frozenset({"not-applicable", "deferred", "waived"})

LEDGER_FILENAME = "conventions.json"


@dataclass(frozen=True)
class LedgerEntry:
    """One disposition recorded by a plan for a pack item."""

    item_id: str
    disposition: str
    reason: str = ""
    evidence: str = ""


def ledger_path(plan_dir: Path) -> Path:
    """The conventions-ledger file path for a plan directory."""
    return Path(plan_dir) / LEDGER_FILENAME


def load_ledger(plan_dir: Path) -> dict[str, LedgerEntry]:
    """Load a plan's conventions ledger keyed by item id ({} when absent/empty)."""
    path = ledger_path(plan_dir)
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    out: dict[str, LedgerEntry] = {}
    for e in raw.get("entries", []):
        item_id = str(e.get("item_id", ""))
        if not item_id:
            continue
        out[item_id] = LedgerEntry(
            item_id=item_id,
            disposition=str(e.get("disposition", "")),
            reason=str(e.get("reason", "") or ""),
            evidence=str(e.get("evidence", "") or ""),
        )
    return out


def _status_for(entry: LedgerEntry) -> str:
    if entry.disposition not in DISPOSITIONS:
        return "invalid"
    if entry.disposition in _REASON_REQUIRED and not entry.reason.strip():
        return "invalid"
    if entry.disposition == "applied" and not entry.evidence.strip():
        return "applied-without-evidence"
    return "disposed-ok"


def validate_dispositions(
    pack_items: Iterable[object], ledger: Mapping[str, LedgerEntry]
) -> dict[str, str]:
    """Map each applicable pack item id to its validation status.

    ``pack_items`` are objects exposing an ``id`` attribute (e.g. PackItem).
    """
    statuses: dict[str, str] = {}
    for item in pack_items:
        item_id = getattr(item, "id")
        entry = ledger.get(item_id)
        statuses[item_id] = "missing" if entry is None else _status_for(entry)
    return statuses
