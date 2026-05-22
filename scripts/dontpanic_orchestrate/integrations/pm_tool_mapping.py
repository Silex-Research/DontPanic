"""Plan 2026-05-20-001 F001 — PM-tool semantic mapping config.

Each PM-tool wrapper carries one operator-authored JSON at
``~/.dontpanic/adapters/<service>.json`` that translates the service's
field names + status enum onto the abstract category contract in
``pm_tool_models``. This module defines the schema + the validation
rules.

The split is sharp: the *adapter* (PP-generated MCP binary) speaks the
service's raw API. The *mapping config* is how a hand-authored JSON
collapses that vendor shape onto ``PMIssue`` / ``PMStatus`` without
adding a single line of service-specific Python. Adding a second PM
tool means writing one of these JSONs + copying the reference wrapper —
never editing this module.

This module MUST stay vendor-agnostic. Acceptance item 6 forbids any
service-specific reference — no vendor names, no vendor-named fields.
Worked examples live in the corresponding ``<service>_pm_tool.py``
wrapper and the mapping JSON committed to the plan's ``evidence/``
directory.

Key invariants:

- Every member of :class:`PMStatus` must appear in
  ``status_enum_map.values()`` — a partial mapping leaves a plan in a
  state where ``push_status`` cannot translate one of its own statuses
  outbound. The validator fails loud on this.
- ``status_enum_map`` keys must be unique (case-insensitive). Two
  distinct upstream labels collapsing onto the same ``PMStatus`` is
  fine and common (e.g. a vendor's ``"Triage"`` and ``"Backlog"`` both
  → ``BACKLOG``); two case-equivalent upstream labels mapping to
  different ``PMStatus`` values is a config error and rejected.
- ``field_name_map`` is keyed by abstract-contract field path
  (``"PMIssue.title"``) and valued by the vendor's field path
  (``"<vendor_object>.title"``). v0 supports dotted paths; deeper
  joins are handled by the wrapper, not by the mapping resolver.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dontpanic_orchestrate.integrations.pm_tool_models import PMStatus

# Required field paths every PM-tool mapping must declare. Per-service
# wrappers compose ``translate_issue`` against this set; missing any
# entry would leave the wrapper unable to populate the corresponding
# ``PMIssue`` field.
REQUIRED_ISSUE_FIELD_PATHS: frozenset[str] = frozenset(
    {
        "PMIssue.id",
        "PMIssue.project_id",
        "PMIssue.title",
        "PMIssue.status",
        "PMIssue.uri",
    }
)


class PMToolMappingConfig(BaseModel):
    """Operator-authored config that wires one PM tool to the category
    contract.

    Lives on disk at ``~/.dontpanic/adapters/<service>.json``. The
    redacted example committed under each plan's ``evidence/`` folder
    is the canonical reference shape.

    ``extra='ignore'`` — the per-service JSON is multi-purpose: the
    same file commonly carries ``pp_version`` (PP binary pin),
    ``api_key_env`` (env-var pointer for the operator's token), and
    other operator metadata that's not part of the mapping itself.
    Silently dropping unknown keys keeps the mapping schema focused
    while letting the broader adapter config live in one place per
    the printing-press skill's per-service-config convention.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    service_name: str = Field(
        ...,
        min_length=1,
        description=(
            "Slug matching the PP-generated adapter directory under "
            "``~/.dontpanic/adapters/<service>/``. Used as the URI scheme."
        ),
    )
    uri_scheme: str = Field(
        ...,
        min_length=1,
        description=(
            "URI scheme used in ``<scheme>://issue/<id>`` and "
            "``<scheme>://project/<id>``. Usually equal to service_name."
        ),
    )
    field_name_map: dict[str, str] = Field(
        ...,
        description=(
            "Abstract-contract field path (e.g. 'PMIssue.title') → vendor "
            "field path (e.g. '<vendor_object>.title'). Must cover the "
            "REQUIRED_ISSUE_FIELD_PATHS set; extras are fine."
        ),
    )
    status_enum_map: dict[str, PMStatus] = Field(
        ...,
        description=(
            "Upstream status label → PMStatus. Must collectively cover "
            "every PMStatus value so push_status can translate any "
            "DontPanic status outbound. Multiple upstream labels mapping "
            "to one PMStatus is fine."
        ),
    )
    priority_map: dict[str, int] | None = Field(
        default=None,
        description=(
            "Optional upstream priority label → integer rank. The category "
            "contract does not model priority in v0, so wrappers may surface "
            "this as a pass-through annotation on PMIssue.description or "
            "ignore it entirely."
        ),
    )
    push_status_tool: str = Field(
        ...,
        min_length=1,
        description=(
            "Name of the MCP tool the wrapper invokes to flip an issue's "
            "status. The wrapper passes (issue_id, vendor_status_label) "
            "to this tool."
        ),
    )
    read_issue_tool: str = Field(
        ...,
        min_length=1,
        description=(
            "Name of the MCP tool the wrapper invokes to fetch one issue "
            "by id. The wrapper passes (issue_id) and translates the "
            "response through translate_issue."
        ),
    )
    capability_id: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Plan 2026-05-21-001 F003 — optional binding to a "
            "``capabilities/<id>.json`` manifest. When set, the adapter "
            "registry validates the ID resolves through the F001 loader "
            "and that the manifest category is compatible with the "
            "adapter kind (PM-tool adapters require category 'pm-tool'). "
            "Legacy records without ``capability_id`` continue to parse "
            "and register unchanged."
        ),
    )

    @model_validator(mode="after")
    def _check_status_enum_map_covers_every_pmstatus(self) -> PMToolMappingConfig:
        present = set(self.status_enum_map.values())
        missing = set(PMStatus) - present
        if missing:
            missing_labels = sorted(s.value for s in missing)
            raise ValueError(
                "PMToolMappingConfig.status_enum_map is missing PMStatus members: "
                f"{missing_labels}. Every PMStatus value must appear as the "
                "target of at least one upstream label so push_status can "
                "translate any DontPanic status outbound."
            )
        return self

    @model_validator(mode="after")
    def _check_status_enum_map_keys_unique(self) -> PMToolMappingConfig:
        # Pydantic's dict already collapses duplicate keys at JSON parse
        # time (last-write-wins). We add a separate guard against
        # case-insensitive duplicates because PM-tool status labels are
        # commonly case-mismatched and a silent collapse would be a
        # footgun.
        lowered = Counter(k.lower() for k in self.status_enum_map.keys())
        duplicates = sorted(label for label, count in lowered.items() if count > 1)
        if duplicates:
            raise ValueError(
                "PMToolMappingConfig.status_enum_map contains "
                f"case-insensitive duplicate keys: {duplicates}. Each upstream "
                "status label must appear exactly once."
            )
        return self

    @model_validator(mode="after")
    def _check_required_field_paths_present(self) -> PMToolMappingConfig:
        missing = sorted(REQUIRED_ISSUE_FIELD_PATHS - set(self.field_name_map.keys()))
        if missing:
            raise ValueError(
                "PMToolMappingConfig.field_name_map is missing required "
                f"abstract-contract paths: {missing}. Each entry in "
                "REQUIRED_ISSUE_FIELD_PATHS must be declared."
            )
        return self

    def translate_status(self, upstream_label: str) -> PMStatus:
        """Map a vendor status label onto :class:`PMStatus`.

        Case-insensitive match — operators commonly author status maps
        in the canonical vendor casing while the live API returns
        whatever the operator typed at the time. Raises ``KeyError``
        on an unmapped label so the caller cannot silently coerce an
        unknown vendor status to BACKLOG.
        """

        for label, mapped in self.status_enum_map.items():
            if label.lower() == upstream_label.lower():
                return mapped
        raise KeyError(
            f"Upstream status label {upstream_label!r} not present in "
            f"status_enum_map for service {self.service_name!r}."
        )

    def reverse_translate_status(self, target: PMStatus) -> str:
        """Pick a representative vendor label for an outbound status push.

        If multiple upstream labels map to ``target``, the first one
        declared in ``status_enum_map`` (Python dicts preserve insertion
        order ≥3.7) wins. Operators who care which label gets pushed
        outbound should author the preferred label first.
        """

        for label, mapped in self.status_enum_map.items():
            if mapped == target:
                return label
        raise KeyError(
            f"PMStatus {target.value!r} not present in status_enum_map "
            f"for service {self.service_name!r}."
        )


def load_mapping_config(payload: dict[str, Any]) -> PMToolMappingConfig:
    """Parse a JSON-decoded mapping config dict into the Pydantic model.

    Thin wrapper around the model constructor so callers can pass
    ``json.loads(path.read_text())`` directly without importing the
    class. Existence-check + read happens at the call site; this helper
    is purely a validation seam.
    """

    return PMToolMappingConfig.model_validate(payload)


__all__ = (
    "PMToolMappingConfig",
    "REQUIRED_ISSUE_FIELD_PATHS",
    "load_mapping_config",
)
