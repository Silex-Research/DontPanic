"""Plan 2026-05-20-001 F001 — sync hook interface + ExternalSyncRecord.

This module is the seam between DontPanic plan close-out (F002) and
each per-service wrapper. The contract is intentionally narrow:

- ``read_issue(uri) -> PMIssue`` — lock-time validation hits this once
  per ``external_refs[]`` entry. Wrappers translate vendor JSON through
  :class:`PMToolMappingConfig` and return a frozen ``PMIssue``.
- ``push_status(uri, new_status, dry_run=False) -> ExternalSyncRecord``
  — close-time push. ``dry_run=True`` MUST never call the real
  vendor; it returns a ``status=pending`` record so F002's
  ``dontpanic plan close --dry-run`` can preview without side-effects.

The wrapper composes the raw PP-emitted MCP adapter to implement
these hooks. The category contract owns no service-specific code.

``ExternalSyncRecord`` lives here (not in plan_loader) because the
record shape is the *output* of the sync layer; F002 will import it
back into plan_loader to write into ``evidence/external_sync.json``.
Defining it on the producer side keeps the dependency direction
correct (loader → integrations, never the other way).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dontpanic_orchestrate.integrations.pm_tool_models import PMIssue, PMStatus


class ExternalSyncStatus(str, Enum):
    """Closed evidence-record status. F002's
    ``evidence/external_sync.json`` records exactly these.
    """

    PENDING = "pending"
    PUSHED = "pushed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExternalSyncRecord(BaseModel):
    """Durable evidence row written for every plan-close external push.

    The record is the *only* signal F002 surfaces about an external
    write — a successful push, a 404'd push target, a vendor 5xx, and
    an operator-skipped sync (``sync: none``) all produce one of these.
    Silent failure is a defect; the F002 validator explicitly asserts
    record presence per attempted ref.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref_uri: str = Field(..., min_length=1)
    kind: str = Field(
        ...,
        min_length=1,
        description=(
            "Category tag matching plan.frontmatter.external_refs[].kind "
            "(e.g. 'pm_issue'). The bridge accepts any tag; v0 only "
            "uses 'pm_issue', but ExternalSyncRecord is category-agnostic."
        ),
    )
    attempted_at: datetime
    status: ExternalSyncStatus
    intended_status: PMStatus | None = Field(
        default=None,
        description=(
            "The DontPanic-side status the push attempted to write. "
            "Recorded so a later resync can replay the same intent."
        ),
    )
    response: dict[str, Any] | None = Field(
        default=None,
        description="Wrapper-shaped response payload on PUSHED. None otherwise.",
    )
    error: str | None = Field(
        default=None,
        description=(
            "Human-readable failure summary on FAILED. None otherwise. "
            "Never carries raw vendor tokens — adapter sanitization runs "
            "before the record is constructed."
        ),
    )

    @field_validator("attempted_at")
    @classmethod
    def _require_tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError(
                "ExternalSyncRecord.attempted_at must be timezone-aware "
                "(UTC preferred)."
            )
        return value


def utcnow() -> datetime:
    """tz-aware UTC now. Centralized so tests can monkeypatch one symbol."""

    return datetime.now(timezone.utc)


@runtime_checkable
class PMToolSyncHook(Protocol):
    """Structural contract every per-service wrapper satisfies.

    Wrappers don't subclass this; ``runtime_checkable`` lets F002's
    plan-close walker confirm a wrapper module exposes the hooks
    without imposing inheritance on the wrapper.
    """

    service_name: str
    uri_scheme: str

    def read_issue(self, uri: str) -> PMIssue:
        """Fetch and normalize one issue. Raises on transport failure.

        Lock-time uses this to validate every ``external_refs[]`` uri
        is reachable. F002 caches the response per uri.
        """
        ...

    def push_status(
        self,
        uri: str,
        new_status: PMStatus,
        dry_run: bool = False,
    ) -> ExternalSyncRecord:
        """Push a status flip outbound.

        ``dry_run=True`` MUST NOT call the vendor. The wrapper still
        returns an ExternalSyncRecord but with ``status=PENDING`` and
        ``response`` populated with the *intended* payload so F002 can
        surface the payload in close --dry-run output without touching
        the real PM tool.
        """
        ...


def make_pending_record(
    ref_uri: str,
    kind: str,
    intended_status: PMStatus,
    payload: dict[str, Any] | None = None,
) -> ExternalSyncRecord:
    """Construct a ``status=PENDING`` record without a vendor call.

    Used by ``push_status(dry_run=True)`` paths and by F002's
    pre-call placeholder write (where the record is upgraded to
    PUSHED / FAILED after the vendor call returns).
    """

    return ExternalSyncRecord(
        ref_uri=ref_uri,
        kind=kind,
        attempted_at=utcnow(),
        status=ExternalSyncStatus.PENDING,
        intended_status=intended_status,
        response=payload,
        error=None,
    )


def make_failed_record(
    ref_uri: str,
    kind: str,
    intended_status: PMStatus,
    error: str,
) -> ExternalSyncRecord:
    """Construct a ``status=FAILED`` record. Adapter callers use this
    after catching a vendor exception so the failure cannot vanish
    into a log line."""

    return ExternalSyncRecord(
        ref_uri=ref_uri,
        kind=kind,
        attempted_at=utcnow(),
        status=ExternalSyncStatus.FAILED,
        intended_status=intended_status,
        response=None,
        error=error,
    )


def make_pushed_record(
    ref_uri: str,
    kind: str,
    intended_status: PMStatus,
    response: dict[str, Any] | None,
) -> ExternalSyncRecord:
    """Construct a ``status=PUSHED`` record after a vendor success."""

    return ExternalSyncRecord(
        ref_uri=ref_uri,
        kind=kind,
        attempted_at=utcnow(),
        status=ExternalSyncStatus.PUSHED,
        intended_status=intended_status,
        response=response,
        error=None,
    )


__all__ = (
    "ExternalSyncStatus",
    "ExternalSyncRecord",
    "PMToolSyncHook",
    "make_pending_record",
    "make_failed_record",
    "make_pushed_record",
    "utcnow",
)
