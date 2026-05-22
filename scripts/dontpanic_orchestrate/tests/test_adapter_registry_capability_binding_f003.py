"""Plan 2026-05-21-001 F003 — capability_id binding on adapter registry records.

Acceptance covered:
  (1) Adapter registry records accept optional capability_id.
  (2) capability_id validates against manifests.
  (3) PM-tool adapter category compatibility is enforced.
  (4) Existing records without capability_id still parse.
  (5) Linear examples/fixtures use ``capability_id: linear``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import capabilities as cap  # noqa: E402
from dontpanic_orchestrate.integrations import adapter_registry as ar  # noqa: E402
from dontpanic_orchestrate.integrations.pm_tool_mapping import (  # noqa: E402
    load_mapping_config,
)

REPO_ROOT = HERE.parents[3]
LINEAR_EXAMPLE = (
    REPO_ROOT
    / "docs"
    / "plans"
    / "2026-05-20-001-infra-external-integrations-bridge-v0"
    / "evidence"
    / "linear-mapping-example.json"
)


# ── helpers ──────────────────────────────────────────────────────────────


def _linear_payload(*, capability_id: str | None = "linear") -> dict:
    """Minimal valid Linear mapping payload, capability_id optional."""

    payload: dict = {
        "service_name": "linear",
        "uri_scheme": "linear",
        "field_name_map": {
            "PMIssue.id": "id",
            "PMIssue.project_id": "team.id",
            "PMIssue.title": "title",
            "PMIssue.status": "state.name",
            "PMIssue.uri": "url",
        },
        "status_enum_map": {
            "Triage": "backlog",
            "Backlog": "backlog",
            "Todo": "active",
            "In Progress": "in_progress",
            "Done": "done",
            "Cancelled": "cancelled",
        },
        "push_status_tool": "issueUpdate",
        "read_issue_tool": "issue",
    }
    if capability_id is not None:
        payload["capability_id"] = capability_id
    return payload


# ── (1) registry record accepts optional capability_id ──────────────────


def test_mapping_config_accepts_capability_id() -> None:
    config = load_mapping_config(_linear_payload(capability_id="linear"))
    assert config.capability_id == "linear"


def test_mapping_config_default_capability_id_is_none() -> None:
    """(4) Legacy records that don't declare capability_id still parse."""
    config = load_mapping_config(_linear_payload(capability_id=None))
    assert config.capability_id is None


# ── (2) + (3) validator behavior on bound mappings ──────────────────────


def test_validate_accepts_real_linear_capability() -> None:
    """Linear capability resolves and its category 'pm-tool' matches."""
    index = cap.load_capabilities(REPO_ROOT)
    config = load_mapping_config(_linear_payload(capability_id="linear"))
    ar.validate_adapter_capability_binding(config, capability_index=index, adapter_kind="pm-tool")


def test_validate_rejects_unknown_capability_id() -> None:
    """(2) capability_id that doesn't match any manifest fails loud."""
    index = cap.load_capabilities(REPO_ROOT)
    config = load_mapping_config(_linear_payload(capability_id="not-a-capability"))
    with pytest.raises(ar.AdapterCapabilityBindingError, match="unknown capability_id"):
        ar.validate_adapter_capability_binding(
            config, capability_index=index, adapter_kind="pm-tool"
        )


def test_validate_rejects_incompatible_category() -> None:
    """(3) PM-tool adapter pointing at a non-pm-tool manifest is rejected.

    ``firebase-dashboard`` has category ``dashboard-realtime``. A PM-tool
    mapping declaring it as ``capability_id`` is a config error.
    """
    index = cap.load_capabilities(REPO_ROOT)
    config = load_mapping_config(_linear_payload(capability_id="firebase-dashboard"))
    with pytest.raises(
        ar.AdapterCapabilityBindingError,
        match="manifest category is 'dashboard-realtime'",
    ):
        ar.validate_adapter_capability_binding(
            config, capability_index=index, adapter_kind="pm-tool"
        )


def test_validate_unbound_mapping_is_noop() -> None:
    """(4) Mappings without capability_id are skipped — backwards-compat
    means the validator may be called against any record without error."""
    empty_index = cap.CapabilityIndex([])
    config = load_mapping_config(_linear_payload(capability_id=None))
    ar.validate_adapter_capability_binding(
        config, capability_index=empty_index, adapter_kind="pm-tool"
    )


def test_validate_rejects_unknown_adapter_kind() -> None:
    """Authoring error: registering a future adapter kind that the kind→
    category table doesn't know about must fail clearly rather than
    silently passing the binding check."""
    index = cap.load_capabilities(REPO_ROOT)
    config = load_mapping_config(_linear_payload(capability_id="linear"))
    with pytest.raises(ar.AdapterCapabilityBindingError, match="unknown adapter_kind"):
        ar.validate_adapter_capability_binding(
            config, capability_index=index, adapter_kind="not-an-adapter-kind"
        )


# ── (5) Linear fixture/example uses capability_id ───────────────────────


def test_linear_mapping_example_declares_capability_id() -> None:
    """The bridge plan's evidence fixture is the canonical Linear shape."""
    payload = json.loads(LINEAR_EXAMPLE.read_text(encoding="utf-8"))
    assert payload.get("capability_id") == "linear"


def test_linear_mapping_example_parses_and_validates() -> None:
    """End-to-end fixture sanity: the example file loads into a
    PMToolMappingConfig and the binding resolves against the real
    capability index."""
    payload = json.loads(LINEAR_EXAMPLE.read_text(encoding="utf-8"))
    config = load_mapping_config(payload)
    assert config.capability_id == "linear"
    index = cap.load_capabilities(REPO_ROOT)
    ar.validate_adapter_capability_binding(config, capability_index=index, adapter_kind="pm-tool")


# ── default_resolver wiring ─────────────────────────────────────────────


def _write_adapter_config(adapters_dir: Path, service: str, payload: dict) -> None:
    adapters_dir.mkdir(parents=True, exist_ok=True)
    (adapters_dir / f"{service}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_default_resolver_registers_linear_record_with_capability_id(
    tmp_path: Path,
) -> None:
    """Happy path: a valid Linear mapping with ``capability_id: linear``
    registers a wrapper just like the legacy unbound record."""

    adapters_dir = tmp_path / "adapters"
    _write_adapter_config(adapters_dir, "linear", _linear_payload(capability_id="linear"))
    resolver = ar.default_resolver(adapters_dir=adapters_dir)
    # AdapterResolver exposes scheme membership via ``_by_scheme`` — the
    # public API is ``resolve``/``register``, but the internal dict is the
    # tightest assertion seam available without spinning up a fake hook.
    assert "linear" in resolver._by_scheme


def test_default_resolver_skips_record_with_unknown_capability_id(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A typo'd capability_id must not bring down the resolver. The
    affected adapter is logged + skipped; other adapters keep loading."""

    adapters_dir = tmp_path / "adapters"
    _write_adapter_config(
        adapters_dir,
        "linear",
        _linear_payload(capability_id="not-a-real-capability"),
    )
    with caplog.at_level("WARNING", logger="dontpanic_orchestrate.integrations.adapter_registry"):
        resolver = ar.default_resolver(adapters_dir=adapters_dir)
    assert "linear" not in resolver._by_scheme
    assert any("not-a-real-capability" in record.message for record in caplog.records)


def test_default_resolver_skips_record_with_incompatible_category(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A PM-tool mapping bound to a non-pm-tool capability is skipped."""

    adapters_dir = tmp_path / "adapters"
    _write_adapter_config(
        adapters_dir,
        "linear",
        _linear_payload(capability_id="firebase-dashboard"),
    )
    with caplog.at_level("WARNING", logger="dontpanic_orchestrate.integrations.adapter_registry"):
        resolver = ar.default_resolver(adapters_dir=adapters_dir)
    assert "linear" not in resolver._by_scheme
    assert any("dashboard-realtime" in record.message for record in caplog.records)


def test_default_resolver_accepts_legacy_record_without_capability_id(
    tmp_path: Path,
) -> None:
    """(4) Backwards-compat — a record without capability_id continues to
    register, with no capability lookup performed."""

    adapters_dir = tmp_path / "adapters"
    _write_adapter_config(
        adapters_dir,
        "linear",
        _linear_payload(capability_id=None),
    )
    resolver = ar.default_resolver(adapters_dir=adapters_dir)
    assert "linear" in resolver._by_scheme
