"""F001 tests for event_copy: RenderedEvent + DISPOSITION_TABLE.

Covers plan ``2026-05-24-004-feat-event-messaging-v1`` F001 acceptance:

  (1) RenderedEvent frozen invariant (mutation raises).
  (3) Translation disposition table covers all 27 INBOX event kinds with
      exactly one verdict per kind; totality enforced here.
  (6) Sanitization clean — tests live in F004 for end-to-end channel
      coverage; this file owns the contract-level checks only.
"""

from __future__ import annotations

import dataclasses

import pytest

from dontpanic_orchestrate import event_copy
from dontpanic_orchestrate.event_copy import (
    DISPOSITION_TABLE,
    INBOX_EVENT_KINDS,
    Disposition,
    RenderedEvent,
    disposition_for,
)


# ── RenderedEvent dataclass invariants ──────────────────────────────────────


def _make_event(**overrides) -> RenderedEvent:
    defaults = dict(
        band="needs_action",
        title="Approval needed for gate pre_impl",
        detail="Operator must clear the pre_impl gate before dispatch.",
        exact_command="dontpanic approve 2026-05-24-001-feat-foo pre_impl",
        evidence_uri="file:///plan/INBOX.md",
        disposition=Disposition.LIVE,
        technical_metadata={"feature_id": "F002", "stage": "pre_impl"},
    )
    defaults.update(overrides)
    return RenderedEvent(**defaults)


def test_rendered_event_is_frozen_dataclass() -> None:
    """Frozen invariant — attribute assignment raises FrozenInstanceError."""
    rendered = _make_event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rendered.title = "mutated"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rendered.disposition = Disposition.AUDIT_ONLY  # type: ignore[misc]


def test_rendered_event_headline_returns_title() -> None:
    """Headline accessor returns the title — terminal-notifier Layer 1."""
    rendered = _make_event(title="Approval needed")
    assert rendered.headline == "Approval needed"


def test_rendered_event_technical_metadata_is_read_only_view() -> None:
    """technical_metadata is wrapped in MappingProxyType — cannot be mutated."""
    rendered = _make_event(technical_metadata={"feature_id": "F002"})
    with pytest.raises(TypeError):
        rendered.technical_metadata["feature_id"] = "FXXX"  # type: ignore[index]


def test_rendered_event_technical_metadata_copies_source_dict() -> None:
    """Mutating the source dict after construction does not leak through."""
    src = {"feature_id": "F002"}
    rendered = _make_event(technical_metadata=src)
    src["feature_id"] = "FXXX"
    assert rendered.technical_metadata["feature_id"] == "F002"


def test_rendered_event_rejects_unknown_band() -> None:
    with pytest.raises(ValueError, match="band"):
        _make_event(band="not_a_band")


def test_rendered_event_rejects_empty_title() -> None:
    with pytest.raises(ValueError, match="title"):
        _make_event(title="")


def test_rendered_event_rejects_non_disposition_enum() -> None:
    with pytest.raises(TypeError, match="disposition"):
        _make_event(disposition="live")  # type: ignore[arg-type]


def test_rendered_event_allows_none_optional_fields() -> None:
    """detail / exact_command / evidence_uri all accept None per D008."""
    rendered = _make_event(detail=None, exact_command=None, evidence_uri=None)
    assert rendered.exact_command is None
    assert rendered.headline == "Approval needed for gate pre_impl"


# ── Disposition enum closed-set ─────────────────────────────────────────────


def test_disposition_enum_has_exactly_four_members() -> None:
    """Closed v1 vocabulary per plan.md § Translation Disposition."""
    assert {d.value for d in Disposition} == {
        "live",
        "dashboard_action",
        "inbox_only",
        "audit_only",
    }


# ── DISPOSITION_TABLE totality (F001 acceptance #3) ─────────────────────────


def test_disposition_table_covers_every_inbox_event_kind() -> None:
    """All 27 INBOX kinds from evidence/f001-inventory-draft.md present."""
    assert set(DISPOSITION_TABLE.keys()) == set(INBOX_EVENT_KINDS)


def test_disposition_table_has_exactly_27_kinds() -> None:
    """Inventory Section 2 enumerates exactly 27 INBOX event names."""
    assert len(DISPOSITION_TABLE) == 27
    assert len(INBOX_EVENT_KINDS) == 27


def test_disposition_table_values_are_disposition_enum_members() -> None:
    for kind, verdict in DISPOSITION_TABLE.items():
        assert isinstance(verdict, Disposition), (
            f"{kind!r} disposition is {type(verdict).__name__}, expected Disposition"
        )


def test_disposition_table_is_read_only_mapping() -> None:
    """MappingProxyType prevents accidental runtime mutation."""
    with pytest.raises(TypeError):
        DISPOSITION_TABLE["new_kind"] = Disposition.LIVE  # type: ignore[index]


def test_disposition_table_no_duplicate_kinds() -> None:
    """A Python dict can't have duplicate keys, but we still assert the
    canonical kind-list itself contains no duplicates (catches typos in
    INBOX_EVENT_KINDS).
    """
    canonical_list = [
        "architecture_regen_failed",
        "architecture_regenerated",
        "auto_cleared_pre_impl",
        "blocked_no_findings",
        "breaker:patch_incomplete",
        "breaker_tripped",
        "calibration_required",
        "config_required",
        "defer_cleared",
        "defer_tripped",
        "environmental_blocker_short_circuit",
        "error",
        "feature_operator_resolved",
        "gate_cleared",
        "gate_hit",
        "gate_state_reconciliation_failed",
        "nested_child_pending",
        "no_progress_classification",
        "pre_impl_status_synced",
        "quota_warn",
        "resumed",
        "unit_mismatch",
        "verdict_blocked_reconciled",
        "verdict_mismatch",
        "volley_crash_caught",
        "volley_start",
        "volley_terminal",
    ]
    assert len(canonical_list) == len(set(canonical_list))
    assert set(canonical_list) == set(INBOX_EVENT_KINDS)


def test_breaker_colon_patch_incomplete_is_a_distinct_kind() -> None:
    """D009 keeps the colon-separated INBOX event name for backward compat;
    rendering normalizes internally to breaker_tripped + breaker_kind. The
    disposition table must list both kinds.
    """
    assert "breaker:patch_incomplete" in DISPOSITION_TABLE
    assert "breaker_tripped" in DISPOSITION_TABLE


def test_disposition_for_returns_enum_for_known_kind() -> None:
    assert disposition_for("gate_hit") is Disposition.LIVE
    assert disposition_for("gate_cleared") is Disposition.AUDIT_ONLY


def test_disposition_for_raises_on_unknown_kind() -> None:
    with pytest.raises(KeyError):
        disposition_for("not_an_event")


# ── F002 emit-site alignment ────────────────────────────────────────────────


def test_existing_notify_event_kinds_are_live() -> None:
    """Existing NotifyEvent emit sites (per inventory Section 2) all surface
    on live channels today — disposition table preserves that invariant.
    """
    for kind in (
        "breaker_tripped",
        "calibration_required",
        "gate_hit",
        "volley_start",
        "volley_terminal",
    ):
        assert DISPOSITION_TABLE[kind] is Disposition.LIVE, (
            f"{kind!r} has existing NotifyEvent emit; must be live"
        )


def test_f002_new_emit_sites_are_live() -> None:
    """F002 adds NotifyEvent dispatch at these six currently-silent sites;
    each must be marked live so F003's renderer routes them to Discord +
    terminal + sidecar per plan.md § Implementation Strategy.
    """
    for kind in (
        "architecture_regen_failed",
        "environmental_blocker_short_circuit",
        "gate_state_reconciliation_failed",
        "no_progress_classification",
        "verdict_blocked_reconciled",
        "verdict_mismatch",
    ):
        assert DISPOSITION_TABLE[kind] is Disposition.LIVE, (
            f"{kind!r} is named in F002 as a new live emit site"
        )


def test_module_exports_match_documented_api() -> None:
    """Smoke check that the F003-facing API stays available."""
    for name in ("RenderedEvent", "Disposition", "DISPOSITION_TABLE", "disposition_for"):
        assert hasattr(event_copy, name), f"event_copy missing {name}"
