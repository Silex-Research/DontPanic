"""Plan 2026-05-20-001 F001 — abstract PM-tool category models.

These are the **service-agnostic** shapes every PM-tool wrapper returns
into. The v0 minimum surface covers what all PM tools share:
issue + project + status + comment. Vendor-specific concepts ride along
on the raw MCP adapter as opaque pass-throughs and never enter this
module.

If a wrapper has to invent a field on a model below, that is a signal
the category contract itself needs to expand — file a v1 plan rather
than reaching into ``extra='allow'``.

Style:

- All models are frozen (``model_config = ConfigDict(frozen=True)``) so
  consumers never accidentally mutate state pulled from an external
  service. The wrapper rebuilds-and-returns a new instance for any
  update path.
- ``extra='forbid'`` rejects typos at parse time. Wrappers normalize
  service-shaped payloads via ``pm_tool_mapping`` *before* constructing
  PMIssue / PMProject — the abstract model never sees raw vendor JSON.
- Status is a closed enum: backlog / active / in_progress / done /
  cancelled. Each PM tool's status set is collapsed onto this through
  ``PMToolMappingConfig.status_enum_map``.

This module MUST stay vendor-agnostic. Acceptance item 6 forbids any
service-specific reference — no vendor names, no vendor-named fields.
Per-service examples live in the corresponding ``<service>_pm_tool.py``
wrapper and the mapping JSON.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class PMStatus(str, Enum):
    """Closed v0 status enum every PM tool collapses to.

    Service-specific statuses map onto these via
    ``PMToolMappingConfig.status_enum_map``. The enum is deliberately
    coarse: a v0 plan-close push only needs to flip
    ``in_progress -> done``; fine-grained workflow modeling is out of
    scope.
    """

    BACKLOG = "backlog"
    ACTIVE = "active"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class PMProject(BaseModel):
    """A project / workspace / team grouping in the source PM tool.

    Whatever the vendor calls the "group of issues" top-level container
    flattens onto this. v0 carries only the minimum fields the bridge
    needs to render or join (id + name + uri).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1, description="Vendor-native project identifier.")
    name: str = Field(..., min_length=1, description="Human-readable project label.")
    uri: str = Field(
        ...,
        min_length=1,
        description=(
            "Canonical reference URI in the form ``<service>://project/<id>``. "
            "F002 plan_loader.ExternalRef.uri validates against this shape."
        ),
    )


class PMComment(BaseModel):
    """A comment on a PM issue.

    v0 minimum surface: who wrote it (opaque author id), when, and the
    raw body. Threading + reactions + attachments are pass-through
    only (out of scope for the abstract contract; per-service wrappers
    can surface them through the raw MCP adapter).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1)
    author_id: str = Field(..., min_length=1, description="Vendor-native user identifier.")
    body: str = Field(..., description="Comment body as stored upstream; not redacted here.")
    created_at: datetime


class PMIssue(BaseModel):
    """The canonical PM-tool issue shape.

    Wrappers must produce this from vendor JSON via
    ``PMToolMappingConfig.translate_issue``. Consumers (lock-time
    validation, close-time status push) operate against this model and
    never touch vendor field names directly.

    ``project_id`` is a soft pointer to ``PMProject.id``; v0 does not
    enforce referential integrity (a wrapper might surface an issue
    whose project is not yet cached locally — that's fine for v0).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: str | None = None
    status: PMStatus
    uri: str = Field(
        ...,
        min_length=1,
        description=(
            "Canonical reference URI in the form ``<service>://issue/<id>``. "
            "F002 plan_loader.ExternalRef.uri validates against this shape."
        ),
    )
    assignee_id: str | None = Field(
        default=None,
        description=(
            "Opaque vendor-native user identifier; v0 does not resolve to email "
            "or display name (PII tiering is the redact module's job)."
        ),
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None
    comments: tuple[PMComment, ...] = Field(
        default=(),
        description=(
            "Tuple (not list) to preserve the frozen-model invariant. v0 surfaces "
            "comments read-only; no comment-write hook in this category contract."
        ),
    )


__all__ = ("PMStatus", "PMProject", "PMComment", "PMIssue")
