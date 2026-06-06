"""Plan 2026-06-05-004 F004 — disposition vocabulary + per-plan ledger + validator."""

from __future__ import annotations

import json

from dontpanic_orchestrate.conventions_ledger import (
    DISPOSITIONS,
    LEDGER_FILENAME,
    LedgerEntry,
    ledger_path,
    load_ledger,
    validate_dispositions,
)
from dontpanic_orchestrate.sufficiency_packs import get_pack


def _frontend_item_ids() -> list[str]:
    return [it.id for it in get_pack("frontend-ui")]


def test_disposition_vocabulary_is_closed() -> None:
    assert DISPOSITIONS == {"applied", "not-applicable", "deferred", "waived"}


def test_fully_disposed_with_evidence_is_ok() -> None:
    ledger = {
        i: LedgerEntry(i, "applied", evidence="tests/x.test.js") for i in _frontend_item_ids()
    }
    statuses = validate_dispositions(get_pack("frontend-ui"), ledger)
    assert set(statuses.values()) == {"disposed-ok"}


def test_missing_item_is_flagged_missing() -> None:
    ledger = {}  # nothing disposed
    statuses = validate_dispositions(get_pack("frontend-ui"), ledger)
    assert set(statuses.values()) == {"missing"}


def test_reasonless_waiver_is_invalid() -> None:
    items = get_pack("frontend-ui")
    ledger = {items[0].id: LedgerEntry(items[0].id, "waived", reason="")}
    statuses = validate_dispositions(items, ledger)
    assert statuses[items[0].id] == "invalid"


def test_deferred_with_reason_is_ok() -> None:
    items = get_pack("frontend-ui")
    ledger = {items[0].id: LedgerEntry(items[0].id, "deferred", reason="no UI claim this slice")}
    statuses = validate_dispositions(items, ledger)
    assert statuses[items[0].id] == "disposed-ok"


def test_applied_without_evidence_is_a_warn_not_ok() -> None:
    items = get_pack("frontend-ui")
    ledger = {items[0].id: LedgerEntry(items[0].id, "applied", evidence="")}
    statuses = validate_dispositions(items, ledger)
    assert statuses[items[0].id] == "applied-without-evidence"


def test_ledger_storage_path_and_load(tmp_path) -> None:
    assert LEDGER_FILENAME == "conventions.json"
    plan_dir = tmp_path / "docs" / "plans" / "X"
    plan_dir.mkdir(parents=True)
    assert ledger_path(plan_dir).name == "conventions.json"
    (plan_dir / "conventions.json").write_text(
        json.dumps(
            {
                "entries": [
                    {"item_id": "design-system-consistency", "disposition": "applied", "evidence": "t.js"}
                ]
            }
        ),
        encoding="utf-8",
    )
    led = load_ledger(plan_dir)
    assert led["design-system-consistency"].disposition == "applied"
    assert load_ledger(tmp_path / "nope") == {}  # absent -> empty
