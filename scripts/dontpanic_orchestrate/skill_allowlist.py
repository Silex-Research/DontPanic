"""Plan 2026-05-30-001 F015 — skill auto-run ALLOWLIST artifact + approval gating.

F011 built the pure skill-invocation engine and treats the auto-run allowlist
as an INJECTED predicate (``SkillInvocationContext.is_command_allowlisted``).
This module OWNS that allowlist: a versioned, auditable artifact plus the
predicate the F011 evaluator consults, and the doctor/reconcile/F008 visibility
of its missing/stale/conflicting state.

The artifact (``skill-autorun-allowlist.json`` under the DontPanic home) records,
per entry (AC5):

  * ``skill_name`` — the skill the entry authorizes.
  * EXACTLY ONE of ``command_template`` (exact match) or ``command_prefix``
    (prefix match) — the command shape cleared for unattended execution.
  * ``allowed_mode`` — an *auto* mode only (``auto_readonly`` / ``auto_safe``);
    an allowlist entry for a human-driven mode is meaningless and is rejected.
  * owner / approval metadata — ``owner``, ``approved_by``, ``approved_at``.
  * ``rationale`` — why this command is safe to auto-run.

The whole file carries ``schema_version``, a monotonically-bumpable ``version``,
and a ``content_hash`` over its entries. A hand-edit that does not re-stamp the
hash is detected as STALE (untrusted) so an un-reviewed allowlist never silently
authorizes auto-run (AC5).

Enforcement (AC4 / AC7):

  * :func:`build_predicate` returns ``Callable[[str], bool]`` for injection into
    F011. It clears a command ONLY when an entry matches AND that entry declares
    no auto-blocking risk flag. A *missing* allowlist yields a deny-all predicate
    — nothing auto-runs without an explicit, approved entry (safe default).
  * :func:`build_predicate` refuses to honor a STALE or CONFLICTING allowlist:
    its predicate denies everything until the operator re-reviews. Combined with
    the F011 engine (which already downgrades mutating/credentialed/networked/
    paid/external-write/indefinite-loop skills to approval_required/suggest), a
    risky skill is NEVER silently executed.

The artifact is a config surface, so it is reconcilable across the canonical
``~/.dontpanic`` and legacy ``~/.jarvis`` homes (F006) and surfaced by
``doctor --agent`` and the F008 config inventory.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dontpanic_orchestrate.skill_invocation import (
    _AUTO_MODES,
    InvocationMode,
    RiskFlag,
)

SCHEMA_VERSION = "1.0"

#: The artifact filename under the DontPanic home. Listed in
#: ``home_reconcile.RECONCILE_FILENAMES`` so reconcile surfaces a split between
#: the canonical and legacy homes (F006 / AC5 "doctor/reconcile … expose
#: missing/stale/conflicting allowlist state").
ALLOWLIST_FILENAME = "skill-autorun-allowlist.json"


# ─────────────────────────────── state enum ────────────────────────────────


class AllowlistStatus(str, Enum):
    """The classified state of the allowlist artifact (AC5).

    Consumed by doctor, reconcile, and the F008 inventory to report
    missing/stale/conflicting state — and by :func:`build_predicate` to refuse
    to honor an untrusted allowlist.
    """

    OK = "ok"                  # present, parses, hash matches, no conflicts
    MISSING = "missing"        # no allowlist file — auto-run disabled (safe)
    UNLOADABLE = "unloadable"  # present but invalid JSON / schema
    STALE = "stale"            # present + valid but content_hash mismatch
    CONFLICTING = "conflicting"  # present + valid but contradictory entries


#: Statuses where the allowlist must NOT authorize any auto-run. MISSING is a
#: safe deny-all zero-state; UNLOADABLE/STALE/CONFLICTING are untrusted and must
#: also deny until the operator fixes + re-approves them.
_UNTRUSTED_STATUSES: frozenset[AllowlistStatus] = frozenset(
    {
        AllowlistStatus.MISSING,
        AllowlistStatus.UNLOADABLE,
        AllowlistStatus.STALE,
        AllowlistStatus.CONFLICTING,
    }
)


# ───────────────────────────── pydantic models ─────────────────────────────


class AllowlistEntry(BaseModel):
    """One auditable auto-run authorization (AC5).

    ``extra='forbid'`` so a typo'd key surfaces as a validation error rather
    than being silently dropped — an un-validated authorization must never slip
    through. Exactly one of ``command_template`` / ``command_prefix`` is set.
    ``allowed_mode`` must be an auto mode: the allowlist exists to gate the
    auto-run path, and a human-driven mode never reaches it.
    """

    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(min_length=1)
    command_template: str | None = None
    command_prefix: str | None = None
    allowed_mode: InvocationMode
    owner: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved_at: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    risk_flags: list[RiskFlag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _exactly_one_command_shape(self) -> AllowlistEntry:
        has_template = bool(self.command_template and self.command_template.strip())
        has_prefix = bool(self.command_prefix and self.command_prefix.strip())
        if has_template == has_prefix:
            raise ValueError(
                "exactly one of command_template or command_prefix must be set "
                f"(skill_name={self.skill_name!r})"
            )
        return self

    @model_validator(mode="after")
    def _allowed_mode_is_auto(self) -> AllowlistEntry:
        if self.allowed_mode not in _AUTO_MODES:
            raise ValueError(
                f"allowed_mode must be an auto mode "
                f"({', '.join(sorted(m.value for m in _AUTO_MODES))}); got "
                f"{self.allowed_mode.value!r} for skill {self.skill_name!r}"
            )
        return self

    def matches(self, command: str) -> bool:
        """True iff ``command`` matches this entry's exact template or prefix."""
        if self.command_template is not None:
            return command == self.command_template
        if self.command_prefix is not None:
            return command.startswith(self.command_prefix)
        return False  # pragma: no cover — guarded by the validator

    @property
    def command_shape(self) -> str:
        """The matched command string, used for hashing + conflict detection."""
        return self.command_template or self.command_prefix or ""


class AutoRunAllowlist(BaseModel):
    """The full allowlist artifact (AC5). Versioned + content-hashed."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    version: int = 1
    content_hash: str | None = None
    entries: list[AllowlistEntry] = Field(default_factory=list)

    def compute_hash(self) -> str:
        """Deterministic sha256 over the entries (excludes ``content_hash``
        itself, so re-stamping is idempotent). A hand-edit that does not call
        :meth:`stamped` leaves the recorded hash mismatched → detected STALE."""
        payload = {
            "schema_version": self.schema_version,
            "version": self.version,
            "entries": [
                e.model_dump(mode="json", exclude_none=True)
                for e in self.entries
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def stamped(self) -> AutoRunAllowlist:
        """Return a copy with ``content_hash`` set to the freshly-computed hash —
        the only sanctioned way to produce a trusted (non-stale) artifact."""
        return self.model_copy(update={"content_hash": self.compute_hash()})

    def is_hash_fresh(self) -> bool:
        return self.content_hash is not None and self.content_hash == self.compute_hash()

    def find_conflicts(self) -> list[str]:
        """Detect contradictory entries (AC5 "conflicting"):

          * the same ``skill_name`` authorized under more than one ``allowed_mode``;
          * the same command shape claimed by more than one ``skill_name``.

        Returns human-readable conflict descriptions (empty when consistent).
        """
        conflicts: list[str] = []

        modes_by_skill: dict[str, set[InvocationMode]] = {}
        skills_by_command: dict[str, set[str]] = {}
        for e in self.entries:
            modes_by_skill.setdefault(e.skill_name, set()).add(e.allowed_mode)
            skills_by_command.setdefault(e.command_shape, set()).add(e.skill_name)

        for skill, modes in sorted(modes_by_skill.items()):
            if len(modes) > 1:
                conflicts.append(
                    f"skill {skill!r} authorized under multiple modes: "
                    f"{', '.join(sorted(m.value for m in modes))}"
                )
        for command, skills in sorted(skills_by_command.items()):
            if len(skills) > 1:
                conflicts.append(
                    f"command {command!r} claimed by multiple skills: "
                    f"{', '.join(sorted(skills))}"
                )
        return conflicts


# ─────────────────────────────── classification ────────────────────────────


@dataclass(frozen=True)
class AllowlistState:
    """Classified allowlist state for doctor / reconcile / F008 (AC5)."""

    status: AllowlistStatus
    path: Path
    entry_count: int = 0
    detail: str = ""
    conflicts: tuple[str, ...] = ()
    allowlist: AutoRunAllowlist | None = None

    @property
    def is_trusted(self) -> bool:
        """True iff the allowlist may authorize auto-run (status OK)."""
        return self.status not in _UNTRUSTED_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "path": str(self.path),
            "entry_count": self.entry_count,
            "detail": self.detail,
            "conflicts": list(self.conflicts),
        }


# ─────────────────────────────────── paths ─────────────────────────────────


def allowlist_path() -> Path:
    """Resolve the allowlist artifact path under the canonical DontPanic home."""
    from dontpanic_orchestrate import global_config as gc

    return gc.dontpanic_home() / ALLOWLIST_FILENAME


def load_allowlist(path: Path | None = None) -> AutoRunAllowlist | None:
    """Load + validate the allowlist artifact.

    Returns the model when it parses + validates, or ``None`` for BOTH an absent
    file and a present-but-unloadable one — :func:`classify_allowlist` is the
    surface that distinguishes those cases. The loader never raises so the CLI
    keeps starting on a malformed artifact.
    """
    target = path if path is not None else allowlist_path()
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return AutoRunAllowlist.model_validate(raw)
    except ValidationError:
        return None


def classify_allowlist(path: Path | None = None) -> AllowlistState:
    """Classify the allowlist into missing / unloadable / stale / conflicting /
    ok (AC5). This is the single source of truth doctor, reconcile, F008, and
    the predicate all consult."""
    target = path if path is not None else allowlist_path()

    if not target.is_file():
        return AllowlistState(
            status=AllowlistStatus.MISSING,
            path=target,
            detail=(
                "no auto-run allowlist — skill auto-run is disabled (the safe "
                "default; create one to opt specific commands in)"
            ),
        )

    allowlist = load_allowlist(target)
    if allowlist is None:
        return AllowlistState(
            status=AllowlistStatus.UNLOADABLE,
            path=target,
            detail=(
                f"{target.name} present but invalid (bad JSON or schema); "
                "auto-run is denied until it is fixed + re-approved"
            ),
        )

    count = len(allowlist.entries)
    if not allowlist.is_hash_fresh():
        return AllowlistState(
            status=AllowlistStatus.STALE,
            path=target,
            entry_count=count,
            detail=(
                "content_hash does not match entries — the allowlist was edited "
                "without re-approval; auto-run is denied until it is re-stamped"
            ),
            allowlist=allowlist,
        )

    conflicts = allowlist.find_conflicts()
    if conflicts:
        return AllowlistState(
            status=AllowlistStatus.CONFLICTING,
            path=target,
            entry_count=count,
            detail="contradictory allowlist entries; auto-run is denied",
            conflicts=tuple(conflicts),
            allowlist=allowlist,
        )

    return AllowlistState(
        status=AllowlistStatus.OK,
        path=target,
        entry_count=count,
        detail=f"{count} approved auto-run command(s)",
        allowlist=allowlist,
    )


# ─────────────────────────────── the predicate ─────────────────────────────


def build_predicate(
    state: AllowlistState | None = None, *, path: Path | None = None
) -> Callable[[str], bool]:
    """Build the ``is_command_allowlisted`` predicate F011 injects (AC4 / AC7).

    A command is allowlisted ONLY when:

      * the allowlist is TRUSTED (status OK — a MISSING/UNLOADABLE/STALE/
        CONFLICTING allowlist authorizes nothing), AND
      * an entry matches the exact command (template or prefix), AND
      * that entry declares NO auto-blocking risk flag (a risky entry never
        clears auto-run, regardless of how it was written — AC7).

    The F011 engine separately downgrades risky/mutating skills before the
    predicate is even consulted; this is the artifact-side belt-and-braces so a
    mutating/credentialed/networked/paid/external-write/indefinite-loop command
    is never silently authorized by the allowlist itself.
    """
    resolved = state if state is not None else classify_allowlist(path)
    if not resolved.is_trusted or resolved.allowlist is None:
        return lambda _command: False

    entries = resolved.allowlist.entries

    def is_command_allowlisted(command: str) -> bool:
        for entry in entries:
            if entry.risk_flags:
                continue  # a risky entry never clears auto-run (AC7)
            if entry.matches(command):
                return True
        return False

    return is_command_allowlisted


__all__ = [
    "ALLOWLIST_FILENAME",
    "SCHEMA_VERSION",
    "AllowlistEntry",
    "AllowlistState",
    "AllowlistStatus",
    "AutoRunAllowlist",
    "allowlist_path",
    "build_predicate",
    "classify_allowlist",
    "load_allowlist",
]
