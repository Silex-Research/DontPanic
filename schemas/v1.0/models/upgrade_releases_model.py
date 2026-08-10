# Hand-authored mirror of upgrade-releases.schema.json (plan
# 2026-06-21-001-feat-upgrade-readiness-doctor F001). NOT codegen output: the
# cross-field invariants (required-action D021/D029/D036/D047, id-uniqueness
# D030) are not expressible in plain JSON Schema, so they live here as
# model_validators and are enforced wherever the model validates.

from __future__ import annotations

from datetime import date as _date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Kind(str, Enum):
    required = "required"
    advisory = "advisory"


class Severity(str, Enum):
    critical = "critical"
    recommended = "recommended"
    optional = "optional"


class CommandLabel(str, Enum):
    preview = "preview"
    apply = "apply"
    verify = "verify"
    run = "run"


# Canonical checklist order. A required action's commands[] must be non-decreasing
# in this rank (preview optional, must precede apply -> verify), D036.
_LABEL_RANK: dict[CommandLabel, int] = {
    CommandLabel.preview: 0,
    CommandLabel.apply: 1,
    CommandLabel.verify: 2,
    CommandLabel.run: 3,
}


def _validate_calendar_date(value: str) -> str:
    """Reject a YYYY-MM-DD-shaped string that is not a real calendar date."""
    try:
        _date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{value!r} is not a valid YYYY-MM-DD date") from exc
    return value


class UpgradeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: CommandLabel = Field(..., description="Closed label enum (preview|apply|verify|run).")
    command: str = Field(..., description="Exact copyable command string (non-blank, D047).")
    description: str | None = Field(None, description="Optional human description of the step.")

    @field_validator("command")
    @classmethod
    def _command_non_blank(cls, value: str) -> str:
        # D047: every command string must be a non-blank exact string. A blank /
        # whitespace-only command can never be copy-pasted, so reject it in any
        # commands[] entry, not just required actions.
        if not value.strip():
            raise ValueError("command must be a non-blank string")
        return value


class UpgradeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="Action id (unique within its release, D030).")
    kind: Kind = Field(..., description="required|advisory (closed enum).")
    severity: Severity | None = Field(None, description="Optional severity (closed enum).")
    title: str = Field(..., min_length=1)
    detail: str = Field(..., min_length=1, description="The WHY.")
    commands: list[UpgradeCommand] = Field(
        default_factory=list,
        description="Ordered exact commands (D017). Empty for advisories.",
    )
    introduced_commands: list[str] | None = Field(
        None, description="Optional new CLI surfaces this release adds."
    )
    applies_when: str | None = Field(
        None, description="Optional applicability predicate key. null = always applies."
    )
    status_probe: str | None = Field(
        None,
        description="Optional satisfaction predicate key. null = advisory/no probe (D004).",
    )
    success_message: str | None = None
    failure_message: str | None = None
    human_next_step: str | None = None
    docs_url: str | None = None
    evidence_uri: str | None = None

    @model_validator(mode="after")
    def _validate_required_action_invariants(self) -> UpgradeAction:
        if self.kind is not Kind.required:
            # Advisory actions may omit status_probe and may have empty commands.
            return self

        # D021 — required-action invariant: a required action must name a
        # non-null, non-empty status_probe (else it could never be cleared by a
        # live probe).
        if self.status_probe is None or not self.status_probe.strip():
            raise ValueError(
                f"required action {self.id!r} must name a non-empty status_probe (D021)"
            )

        # D029 — required-command invariant: non-empty commands[] with at least
        # an apply-labeled command.
        if not self.commands:
            raise ValueError(
                f"required action {self.id!r} must have a non-empty commands[] (D029)"
            )

        labels = [c.label for c in self.commands]
        if CommandLabel.apply not in labels:
            raise ValueError(
                f"required action {self.id!r} must include an apply-labeled command (D029)"
            )

        # D036 — ordered-checklist invariant: must include apply AND verify, and
        # the command labels must appear in canonical (non-decreasing) order.
        if CommandLabel.verify not in labels:
            raise ValueError(
                f"required action {self.id!r} must include a verify-labeled command (D036)"
            )

        ranks = [_LABEL_RANK[label] for label in labels]
        if any(earlier > later for earlier, later in zip(ranks, ranks[1:], strict=False)):
            raise ValueError(
                f"required action {self.id!r} commands[] are out of label order; expected "
                f"preview -> apply -> verify -> run order (D036)"
            )

        return self


class UpgradeRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="Stable release id (unique manifest-wide, D030).")
    date: str = Field(..., description="Release date YYYY-MM-DD.")
    plan_refs: list[str] = Field(default_factory=list)
    summary: str = Field(..., min_length=1)
    show_on_first_run: bool = Field(
        False, description="First-run advisory policy (F004)."
    )
    actions: list[UpgradeAction] = Field(default_factory=list)

    _validate_date = field_validator("date")(staticmethod(_validate_calendar_date))

    @model_validator(mode="after")
    def _validate_action_id_uniqueness(self) -> UpgradeRelease:
        # D030 — action ids must be unique within a single release so the stable
        # id upgrade:<release>:<action> never collides.
        seen: set[str] = set()
        for action in self.actions:
            if action.id in seen:
                raise ValueError(
                    f"release {self.id!r} has duplicate action id {action.id!r} (D030)"
                )
            seen.add(action.id)
        return self


class UpgradeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_release: str = Field(..., min_length=1, description="Baseline release id (D018).")
    baseline_date: str = Field(..., description="Baseline date YYYY-MM-DD (D018).")
    releases: list[UpgradeRelease] = Field(default_factory=list)

    _validate_baseline_date = field_validator("baseline_date")(
        staticmethod(_validate_calendar_date)
    )

    @model_validator(mode="after")
    def _validate_release_id_uniqueness(self) -> UpgradeManifest:
        # D030 — release ids must be unique manifest-wide so releases_since is
        # unambiguous.
        seen: set[str] = set()
        for release in self.releases:
            if release.id in seen:
                raise ValueError(f"duplicate release id {release.id!r} (D030)")
            seen.add(release.id)
        return self


__all__ = [
    "CommandLabel",
    "Kind",
    "Severity",
    "UpgradeAction",
    "UpgradeCommand",
    "UpgradeManifest",
    "UpgradeRelease",
]
