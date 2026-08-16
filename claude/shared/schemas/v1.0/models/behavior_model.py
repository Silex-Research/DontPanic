# Hand-maintained twin of behavior.schema.json (plan 2026-08-12-001 F003).
# Behavior specs are hidden from worker prompts. datamodel-codegen drops
# JSON Schema conditionals, so violated-requires-evidence lives here.

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


class OwnerRole(Enum):
    implementer = "implementer"
    auditor = "auditor"
    supervisor = "supervisor"


class Adherence(Enum):
    expected = "expected"
    n_a = "n/a"
    violated = "violated"


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


class Behavior(BaseModel):
    """Process-behavior verdict judged off an existing audit envelope.

    Hidden from worker prompts. adherence violated requires at least one
    evidence_ref; n/a with no evidence_refs validates.
    """

    model_config = ConfigDict(extra="forbid")
    id: constr(min_length=1)
    trigger: constr(min_length=1)
    owner_role: OwnerRole
    adherence: Adherence
    evidence_refs: list[EvidenceRef] | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, data: object) -> object:
        if isinstance(data, dict):
            for key in ("id", "trigger", "owner_role", "adherence", "evidence_refs"):
                if key in data and data[key] is None:
                    raise ValueError(f"{key} must be omitted rather than set to null")
        return data

    @model_validator(mode="after")
    def _violated_requires_evidence(self) -> Behavior:
        if self.adherence is Adherence.violated and not self.evidence_refs:
            raise ValueError("adherence 'violated' requires at least one evidence_ref")
        return self
