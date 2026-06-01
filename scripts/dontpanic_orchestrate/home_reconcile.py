"""Config-home reconciliation — Plan 2026-05-30-001 F006.

DontPanic resolves a single per-user state directory via
:func:`global_config.dontpanic_home` (``$DONTPANIC_HOME`` → ``$JARVIS_HOME`` →
``~/.dontpanic`` → ``~/.jarvis``). That single-home resolution silently picks a
winner when BOTH ``~/.dontpanic`` (canonical) and ``~/.jarvis`` (legacy) exist —
a split-brain that can strand an operator's ``agent-manifest.json`` /
``config.json`` / ``projects.json`` in the home the resolver didn't choose.

This module makes the split explicit and reconcilable:

  * :func:`classify_homes` compares the canonical and legacy homes file-by-file
    and classifies each as ``identical`` / ``legacy_only`` / ``canonical_only``
    / ``divergent`` / ``absent``.
  * :func:`plan_reconcile` turns that into a migration plan: ``legacy_only``
    files migrate into the canonical home; ``divergent`` same-name files are
    REFUSED (never silently merged or picked); everything else is a no-op.
  * :func:`apply_reconcile` performs the plan, copying (never deleting — the
    legacy home stays as read-through compatibility) and backing up only if a
    canonical file would be overwritten (which the plan never does).

The CLI surface is ``dontpanic reconcile homes [--dry-run|--confirm]`` and the
doctor surfaces split-brain via the ``agent:config-home`` check.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

# Canonical vs legacy home env-var names (mirror global_config). We resolve the
# two homes EXPLICITLY here rather than via dontpanic_home(), which collapses
# them to a single winner — reconciliation needs to see both at once.
CANONICAL_HOME_ENV = "DONTPANIC_HOME"
LEGACY_HOME_ENV = "JARVIS_HOME"
CANONICAL_DIRNAME = ".dontpanic"
LEGACY_DIRNAME = ".jarvis"

# The config files reconciliation knows how to classify + migrate. These are the
# durable per-user config artifacts; volatile/env-redirected state (quota,
# breaker history, dashboard cache) is intentionally out of scope for v0.
RECONCILE_FILENAMES: tuple[str, ...] = (
    "config.json",
    "projects.json",
    "agent-manifest.json",
)

# Classification states.
IDENTICAL = "identical"
LEGACY_ONLY = "legacy_only"
CANONICAL_ONLY = "canonical_only"
DIVERGENT = "divergent"
ABSENT = "absent"


def canonical_home() -> Path:
    """The canonical home: ``$DONTPANIC_HOME`` or ``~/.dontpanic``."""
    override = os.environ.get(CANONICAL_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / CANONICAL_DIRNAME


def legacy_home() -> Path:
    """The legacy home: ``$JARVIS_HOME`` or ``~/.jarvis``."""
    override = os.environ.get(LEGACY_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / LEGACY_DIRNAME


@dataclass(frozen=True)
class FileState:
    """Classification of one config file across the two homes."""

    name: str
    status: str  # one of IDENTICAL / LEGACY_ONLY / CANONICAL_ONLY / DIVERGENT / ABSENT
    canonical_path: Path
    legacy_path: Path

    @property
    def migratable(self) -> bool:
        """True iff this file can be migrated canonical-ward with no conflict."""
        return self.status == LEGACY_ONLY

    @property
    def conflicting(self) -> bool:
        """True iff both homes hold a differing copy — an ambiguous merge that
        must never be resolved silently."""
        return self.status == DIVERGENT


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def classify_homes(
    *, canonical: Path | None = None, legacy: Path | None = None
) -> list[FileState]:
    """Classify each reconcilable config file across the two homes. ``canonical``
    / ``legacy`` override the resolved homes (used by tests). Files absent from
    BOTH homes are reported as ``absent`` so callers get a complete picture."""
    chome = canonical if canonical is not None else canonical_home()
    lhome = legacy if legacy is not None else legacy_home()

    out: list[FileState] = []
    for name in RECONCILE_FILENAMES:
        cpath = chome / name
        lpath = lhome / name
        cbytes = _read_bytes(cpath) if cpath.is_file() else None
        lbytes = _read_bytes(lpath) if lpath.is_file() else None

        if cbytes is None and lbytes is None:
            status = ABSENT
        elif cbytes is not None and lbytes is None:
            status = CANONICAL_ONLY
        elif cbytes is None and lbytes is not None:
            status = LEGACY_ONLY
        elif cbytes == lbytes:
            status = IDENTICAL
        else:
            status = DIVERGENT
        out.append(FileState(name=name, status=status, canonical_path=cpath, legacy_path=lpath))
    return out


@dataclass(frozen=True)
class ReconcileAction:
    """A single planned migration (legacy → canonical)."""

    name: str
    src: Path
    dst: Path


@dataclass(frozen=True)
class ReconcilePlan:
    """The outcome of planning a reconcile pass."""

    migrations: list[ReconcileAction]
    conflicts: list[FileState]  # divergent files — refused, never auto-merged
    states: list[FileState]

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    @property
    def is_empty(self) -> bool:
        return not self.migrations and not self.conflicts


def plan_reconcile(states: list[FileState]) -> ReconcilePlan:
    """Plan the reconcile: ``legacy_only`` files migrate canonical-ward;
    ``divergent`` files are collected as conflicts (refused). ``identical`` /
    ``canonical_only`` / ``absent`` are no-ops."""
    migrations = [
        ReconcileAction(name=s.name, src=s.legacy_path, dst=s.canonical_path)
        for s in states
        if s.migratable
    ]
    conflicts = [s for s in states if s.conflicting]
    return ReconcilePlan(migrations=migrations, conflicts=conflicts, states=states)


@dataclass(frozen=True)
class ReconcileResult:
    """The outcome of applying (or dry-running) a reconcile plan."""

    migrated: list[str]
    refused: list[str]  # divergent file names left untouched
    dry_run: bool


def apply_reconcile(plan: ReconcilePlan, *, confirm: bool) -> ReconcileResult:
    """Apply the plan. Without ``confirm`` this is a dry run that writes nothing.
    Migrations copy legacy → canonical (the legacy file is preserved for
    read-through compatibility — never deleted). Divergent conflicts are always
    refused; a destructive merge is never performed here."""
    refused = [s.name for s in plan.conflicts]
    if not confirm:
        return ReconcileResult(migrated=[], refused=refused, dry_run=True)

    migrated: list[str] = []
    for action in plan.migrations:
        action.dst.parent.mkdir(parents=True, exist_ok=True)
        # The plan only migrates legacy_only files, so dst should not exist; if
        # it raced into existence, back it up rather than clobber.
        if action.dst.exists():
            backup = action.dst.with_suffix(action.dst.suffix + ".bak")
            shutil.copy2(action.dst, backup)
        shutil.copy2(action.src, action.dst)  # copy, NOT move — legacy stays put
        migrated.append(action.name)
    return ReconcileResult(migrated=migrated, refused=refused, dry_run=False)


def split_brain_summary(states: list[FileState]) -> tuple[list[str], list[str]]:
    """Return (legacy_only_names, divergent_names) — the split-brain signal the
    doctor surfaces. Empty/empty means the homes are reconciled."""
    legacy_only = [s.name for s in states if s.status == LEGACY_ONLY]
    divergent = [s.name for s in states if s.status == DIVERGENT]
    return legacy_only, divergent
