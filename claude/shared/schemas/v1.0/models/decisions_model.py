# Hand-maintained twin of decisions.schema.json (plan 2026-08-12-001 F002).
# Accepts both DontPanic line shapes already on disk. datamodel-codegen
# drops anyOf, so date-or-ts and question-or-title live in model_validators.

from __future__ import annotations

from datetime import date as Date
from enum import Enum

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    constr,
    model_validator,
)


class Status(Enum):
    open = "open"
    resolved = "resolved"
    deferred = "deferred"


class Decision(BaseModel):
    """One decisions.jsonl line.

    Current shape: id / date / question / answer / status.
    Legacy shape: id / ts / by / title / body.
    id matches ^D\\d{3}$. A line needs date or ts, and question or title.
    """

    model_config = ConfigDict(extra="forbid")
    id: constr(pattern=r"^D\d{3}$") = Field(..., description="D001, D002, ...")
    date: Date | None = None
    ts: AwareDatetime | None = None
    question: constr(min_length=1) | None = None
    answer: str | None = None
    title: constr(min_length=1) | None = None
    body: str | None = None
    status: Status | None = None
    rationale: str | None = None
    by: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, data: object) -> object:
        if isinstance(data, dict):
            for key in (
                "date",
                "ts",
                "question",
                "answer",
                "title",
                "body",
                "status",
                "rationale",
                "by",
                "id",
            ):
                if key in data and data[key] is None:
                    raise ValueError(f"{key} must be omitted rather than set to null")
        return data

    @model_validator(mode="after")
    def _require_pairs(self) -> Decision:
        if self.date is None and self.ts is None:
            raise ValueError("a decision line requires date or ts")
        if not self.question and not self.title:
            raise ValueError("a decision line requires question or title")
        return self
