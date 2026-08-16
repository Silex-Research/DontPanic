# Hand-maintained twin of claim.schema.json (plan 2026-08-12-001 F001).
# datamodel-codegen drops JSON Schema conditionals, so admitted/rejected/stale
# rules live in model_validators rather than generated field constraints.

from __future__ import annotations

from enum import Enum

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    constr,
    model_validator,
)


class Type(Enum):
    screenshot = "screenshot"
    log = "log"
    test_output = "test_output"
    diff = "diff"
    audit_json = "audit_json"
    commit = "commit"
    url = "url"
    file = "file"


class Status(Enum):
    proposed = "proposed"
    admitted = "admitted"
    rejected = "rejected"
    stale = "stale"


class EvidenceRef(BaseModel):
    """Pointer grammar copied from features.schema.json $defs/evidence_ref."""

    model_config = ConfigDict(extra="forbid")
    type: Type
    uri: str = Field(
        ..., description="Relative path, git SHA, or Firebase Storage signed URL"
    )
    hash: str | None = Field(None, description="SHA-256 of content for integrity")
    captured_at: AwareDatetime | None = None
    captured_by: str | None = Field(
        None, description="Agent or tool that captured the evidence"
    )
    note: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, data: object) -> object:
        if isinstance(data, dict):
            for key in ("hash", "captured_at", "captured_by", "note"):
                if key in data and data[key] is None:
                    raise ValueError(f"{key} must be omitted rather than set to null")
        return data


class Claim(BaseModel):
    """A finding, failed hypothesis, or binding constraint.

    status admitted requires non-empty evidence_refs plus admitted_by and
    admitted_at. rejected and stale require a reason. The JSON Schema and
    this model must return the same verdict.
    """

    model_config = ConfigDict(extra="forbid")
    id: constr(pattern=r"^C\d{3}$") = Field(..., description="C001, C002, ...")
    statement: constr(min_length=1)
    status: Status
    evidence_refs: list[EvidenceRef]
    content_hash: constr(pattern=r"^[a-f0-9]{64}$")
    admitted_by: constr(min_length=1) | None = None
    admitted_at: AwareDatetime | None = None
    reason: constr(min_length=1) | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, data: object) -> object:
        if isinstance(data, dict):
            for key in (
                "admitted_by",
                "admitted_at",
                "reason",
                "evidence_refs",
                "statement",
                "status",
                "content_hash",
                "id",
            ):
                if key in data and data[key] is None:
                    raise ValueError(f"{key} must be omitted rather than set to null")
        return data

    @model_validator(mode="after")
    def _check_status_conditional(self) -> Claim:
        if self.status is Status.admitted:
            if not self.evidence_refs:
                raise ValueError(
                    "status 'admitted' requires a non-empty evidence_refs list"
                )
            if not self.admitted_by:
                raise ValueError("status 'admitted' requires admitted_by")
            if self.admitted_at is None:
                raise ValueError("status 'admitted' requires admitted_at")
        if self.status in (Status.rejected, Status.stale) and not self.reason:
            raise ValueError(f"status '{self.status.value}' requires a reason")
        return self
