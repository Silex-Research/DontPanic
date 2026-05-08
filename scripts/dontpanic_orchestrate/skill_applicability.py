"""Plan 2026-05-08-002 F002 — lock-time advisory skill-applicability matcher.

Pure-function ``match(plan, skills_dir) -> ApplicabilityReport``. Reads each
``<skills_dir>/<skill>/SKILL.md`` frontmatter, parses the optional
``applies_to:`` block via Pydantic, intersects with the plan's ``surfaces``
and ``goal_type``, and emits an advisory report.

Design constraints (see plan 2026-05-08-002 decisions D001 — D004 + D007):

* **Decentralized self-declaration** — skills opt in via SKILL.md frontmatter.
  No central router.
* **Lock-time only** — D003 forbids mid-volley re-probe in v0.
* **Advisory only** — D004 forbids any blocking semantics. Callers MUST NOT
  use Match presence/absence to gate any flow.
* **External CLI metadata is inert** — D007 carries provider/name/command/
  version_pin through unmodified; the matcher never installs, invokes,
  allowlists, hashes, verifies, or scores the command.

Purity contract (auditor verifies via source grep): no ``subprocess`` import,
no ``logging.getLogger`` call, no ``print(`` call. File I/O (reading SKILL.md
frontmatter + writing the sidecar) is permitted by the spec.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

SCHEMA_VERSION = "1.0"

SURFACE_VALUES: frozenset[str] = frozenset(
    {
        "web",
        "ios",
        "android",
        "backend",
        "infra",
        "security",
        "data",
        "ux",
        "ml",
        "docs",
    }
)

GOAL_TYPE_VALUES: frozenset[str] = frozenset(
    {
        "mechanical",
        "infra",
        "refactor",
        "parity",
        "new_feature",
        "migration",
        "incident",
    }
)


# ───────────────────────────  Pydantic frontmatter side  ───────────────────────────


class ExternalCliModel(BaseModel):
    """Pydantic shape of the optional ``applies_to.external_cli`` block."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    command: str = Field(..., min_length=1)
    version_pin: str = Field(..., min_length=1)


class AppliesToModel(BaseModel):
    """Pydantic shape of the ``applies_to:`` SKILL.md frontmatter block."""

    model_config = ConfigDict(extra="forbid")

    surfaces: list[str] = Field(default_factory=list)
    goal_types: list[str] = Field(default_factory=list)
    external_cli: ExternalCliModel | None = None


# ───────────────────────────  report dataclasses  ───────────────────────────


@dataclass(frozen=True)
class ExternalCli:
    """Inert metadata about an external CLI backing a skill (D007)."""

    provider: str
    name: str
    command: str
    version_pin: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalCli:
        return cls(
            provider=data["provider"],
            name=data["name"],
            command=data["command"],
            version_pin=data["version_pin"],
        )


@dataclass(frozen=True)
class Match:
    skill_name: str
    matched_surfaces: list[str]
    matched_goal_types: list[str]
    rationale: str
    provenance: Literal["internal", "external"]
    external_cli: ExternalCli | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "matched_surfaces": list(self.matched_surfaces),
            "matched_goal_types": list(self.matched_goal_types),
            "rationale": self.rationale,
            "provenance": self.provenance,
            "external_cli": (
                self.external_cli.to_dict() if self.external_cli is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Match:
        ext = data.get("external_cli")
        return cls(
            skill_name=data["skill_name"],
            matched_surfaces=list(data["matched_surfaces"]),
            matched_goal_types=list(data["matched_goal_types"]),
            rationale=data["rationale"],
            provenance=data["provenance"],
            external_cli=ExternalCli.from_dict(ext) if ext is not None else None,
        )


@dataclass(frozen=True)
class Skip:
    skill_name: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skip:
        return cls(skill_name=data["skill_name"], reason=data["reason"])


@dataclass(frozen=True)
class ApplicabilityReport:
    schema_version: str
    plan_id: str
    plan_surfaces: list[str]
    plan_goal_type: str | None
    matches: list[Match]
    skipped: list[Skip]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "plan_surfaces": list(self.plan_surfaces),
            "plan_goal_type": self.plan_goal_type,
            "matches": [m.to_dict() for m in self.matches],
            "skipped": [s.to_dict() for s in self.skipped],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplicabilityReport:
        return cls(
            schema_version=data["schema_version"],
            plan_id=data["plan_id"],
            plan_surfaces=list(data.get("plan_surfaces", [])),
            plan_goal_type=data.get("plan_goal_type"),
            matches=[Match.from_dict(m) for m in data.get("matches", [])],
            skipped=[Skip.from_dict(s) for s in data.get("skipped", [])],
        )


# ───────────────────────────  internals  ───────────────────────────


def _read_frontmatter(skill_md_path: Path) -> dict[str, Any] | None:
    """Read SKILL.md frontmatter as a dict. Returns ``None`` when the file
    is missing the leading ``---`` delimiter, lacks a closing delimiter, or
    contains malformed YAML. The matcher reports such cases as Skips with a
    rationale rather than crashing — D004 advisory contract."""

    text = skill_md_path.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        loaded = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _parse_applies_to(
    frontmatter: dict[str, Any],
) -> tuple[AppliesToModel | None, str | None]:
    """Validate the ``applies_to:`` block via Pydantic. Returns
    ``(model, None)`` on success; ``(None, reason)`` when the block is
    absent or fails validation. Reason is suitable as a Skip rationale."""

    block = frontmatter.get("applies_to")
    if block is None:
        return None, "skill has no applies_to declaration"
    if not isinstance(block, dict):
        return None, (
            f"applies_to is not a mapping (got {type(block).__name__})"
        )
    try:
        model = AppliesToModel.model_validate(block)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ()))
        msg = first.get("msg", "validation failed")
        suffix = f" at {loc}" if loc else ""
        return None, f"applies_to failed validation{suffix}: {msg}"
    return model, None


def _format_rationale(
    matched_surfaces: list[str], matched_goal_types: list[str]
) -> str:
    surface_part = (
        f"surfaces={matched_surfaces}" if matched_surfaces else "surfaces=[]"
    )
    goal_part = (
        f"goal_types={matched_goal_types}"
        if matched_goal_types
        else "goal_types=[]"
    )
    return f"matched on {surface_part} + {goal_part}"


def _resolve_plan_goal_type(plan: Any) -> str | None:
    plan_obj = getattr(plan, "plan", None)
    raw = getattr(plan_obj, "goal_type", None) if plan_obj is not None else None
    if raw is None:
        return None
    if hasattr(raw, "value"):
        return str(raw.value)
    return str(raw)


# ───────────────────────────  public API  ───────────────────────────


def match(plan: Any, skills_dir: Path) -> ApplicabilityReport:
    """Pure matcher. Iterates ``<skills_dir>/<name>/SKILL.md`` in sorted
    order, reads frontmatter, validates the optional ``applies_to:`` block,
    and emits a Match when the plan/skill share at least one surface OR
    one goal_type. Skills without ``applies_to:`` (or with malformed
    frontmatter) become Skips with a one-line rationale; skills whose
    intersection sets are both empty are silently omitted (no false-
    positive noise per D004).

    The ``plan`` argument is duck-typed: any object exposing ``plan_id``,
    ``surfaces`` (list[str]), and ``plan.goal_type`` is accepted. This
    keeps the matcher decoupled from ``LoadedPlan`` for pure-function
    testing.
    """

    plan_surfaces = list(getattr(plan, "surfaces", []) or [])
    plan_goal_type = _resolve_plan_goal_type(plan)

    plan_surface_set = set(plan_surfaces)
    plan_goal_set: set[str] = (
        {plan_goal_type} if plan_goal_type is not None else set()
    )

    matches: list[Match] = []
    skipped: list[Skip] = []

    if not skills_dir.is_dir():
        return ApplicabilityReport(
            schema_version=SCHEMA_VERSION,
            plan_id=getattr(plan, "plan_id", ""),
            plan_surfaces=plan_surfaces,
            plan_goal_type=plan_goal_type,
            matches=matches,
            skipped=skipped,
        )

    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        skill_name = entry.name

        try:
            frontmatter = _read_frontmatter(skill_md)
        except OSError as exc:
            skipped.append(
                Skip(
                    skill_name=skill_name,
                    reason=f"SKILL.md read error: {exc.strerror or exc!s}",
                )
            )
            continue

        if frontmatter is None:
            skipped.append(
                Skip(
                    skill_name=skill_name,
                    reason="SKILL.md missing or malformed YAML frontmatter",
                )
            )
            continue

        applies_to, skip_reason = _parse_applies_to(frontmatter)
        if applies_to is None:
            assert skip_reason is not None  # narrows for type checker
            skipped.append(Skip(skill_name=skill_name, reason=skip_reason))
            continue

        skill_surface_set = set(applies_to.surfaces)
        skill_goal_set = set(applies_to.goal_types)
        matched_surface_set = plan_surface_set & skill_surface_set
        matched_goal_set = plan_goal_set & skill_goal_set

        if not matched_surface_set and not matched_goal_set:
            continue

        external_cli = (
            ExternalCli(
                provider=applies_to.external_cli.provider,
                name=applies_to.external_cli.name,
                command=applies_to.external_cli.command,
                version_pin=applies_to.external_cli.version_pin,
            )
            if applies_to.external_cli is not None
            else None
        )
        provenance: Literal["internal", "external"] = (
            "external" if external_cli is not None else "internal"
        )

        matched_surfaces = sorted(matched_surface_set)
        matched_goal_types = sorted(matched_goal_set)
        matches.append(
            Match(
                skill_name=skill_name,
                matched_surfaces=matched_surfaces,
                matched_goal_types=matched_goal_types,
                rationale=_format_rationale(matched_surfaces, matched_goal_types),
                provenance=provenance,
                external_cli=external_cli,
            )
        )

    return ApplicabilityReport(
        schema_version=SCHEMA_VERSION,
        plan_id=getattr(plan, "plan_id", ""),
        plan_surfaces=plan_surfaces,
        plan_goal_type=plan_goal_type,
        matches=matches,
        skipped=skipped,
    )


def write_report(report: ApplicabilityReport, plan_dir: Path) -> Path:
    """Persist an :class:`ApplicabilityReport` to
    ``<plan_dir>/evidence/applicable-skills.json``. Caller is responsible
    for any operator-facing summary; this function emits no stdout."""

    evidence_dir = plan_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    sidecar = evidence_dir / "applicable-skills.json"
    sidecar.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    )
    return sidecar
