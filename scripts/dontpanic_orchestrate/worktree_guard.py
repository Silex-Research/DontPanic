"""Guard-hardening F001 — wrong-worktree refusal (plan 2026-06-11-001).

ONE guard precondition shared by every plan-gate entry point (plan lock /
audit / close / disposition and the orchestrate dispatch seam), evaluated
BEFORE any gate side effect or evidence write:

* the registry loads via the STRICT path — a corrupt registry fails closed
  with :class:`worktrees.RegistryCorruptError` and is NEVER overridable
  (infrastructure corruption must be repaired, not waived);
* a bound plan must be invoked from inside its bound worktree — both sides
  realpath-resolved (symlinked or case-variant spellings of the same
  directory neither falsely refuse nor falsely pass);
* the binding must pass v0's canonical :func:`worktrees.binding_health`
  predicate (the guard CALLS it, never re-specifies health conditions).

Refusals carry a machine-readable ``refusal_class``. The override flag
(``--override-worktree-guard``, D011 disposition f-662edc459cc1) is
honoured for the JUDGMENT classes only — wrong invoking path, unhealthy
binding, indeterminate git state — and proceeds ONLY AFTER the override
record AND a binding snapshot are durably written (written, flushed, AND
fsynced: the crash-durability contract). A failed evidence write refuses
instead of proceeding un-evidenced.

Scoping (an explicit lock-round decision): the worktree MANAGEMENT
commands (worktree create / worktree remove) are deliberately OUTSIDE this
guard — they operate on bindings by plan id from any checkout and carry
their own preconditions.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import worktrees as wt

OVERRIDE_FLAG = "--override-worktree-guard"
OVERRIDE_FILENAME = "worktree-guard-overrides.jsonl"

CLASS_WRONG_PATH = "wrong_invoking_path"
CLASS_UNHEALTHY = "unhealthy_binding"
CLASS_INDETERMINATE = "indeterminate_git_state"
OVERRIDABLE_CLASSES = frozenset(
    {CLASS_WRONG_PATH, CLASS_UNHEALTHY, CLASS_INDETERMINATE}
)


class GuardRefusal(wt.WorktreeError):
    """Fail-closed refusal from the wrong-worktree guard. Carries the
    machine-readable ``refusal_class`` so callers and tests never parse
    prose to learn WHY the guard refused."""

    def __init__(self, message: str, *, refusal_class: str):
        super().__init__(message)
        self.refusal_class = refusal_class


def _append_durable(path: Path, record: dict[str, Any]) -> None:
    """Append one JSONL record written, flushed, AND fsynced — the
    crash-durability contract: a process crash immediately after the guard
    proceeds must leave the record readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _same_directory(a: Path, b: Path) -> bool:
    """Realpath-equivalent identity: resolve() equality first, then an
    inode-level samefile probe so symlinked or case-variant spellings of
    the same directory never falsely refuse."""
    ra, rb = a.resolve(), b.resolve()
    if ra == rb:
        return True
    try:
        return os.path.samefile(ra, rb)
    except OSError:
        return False


def _invoking_toplevel(cwd: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise GuardRefusal(
            f"invoking directory {cwd} is not inside a git worktree "
            f"({proc.stderr.strip() or 'git probe failed'}) — the guard cannot "
            "determine the invoking checkout; run from inside the plan's bound "
            f"worktree, or pass {OVERRIDE_FLAG} \"<reason>\" to proceed with a "
            "recorded override",
            refusal_class=CLASS_INDETERMINATE,
        )
    return Path(proc.stdout.strip())


def _guidance(binding: dict[str, Any]) -> str:
    return (
        f"\n  bound worktree: {binding['worktree_path']} (branch {binding['branch']})"
        f"\n  to work in it:  cd {binding['worktree_path']}"
        f"\n  to recreate it: dontpanic plan worktree create <plan-dir>"
        f"\n  to override:    re-run with {OVERRIDE_FLAG} \"<reason>\" "
        "(recorded to the plan's audit evidence)"
    )


def _evaluate(
    binding: dict[str, Any], invoking_cwd: Path
) -> tuple[str, str] | None:
    """Returns (refusal_class, message) or None when the guard passes.

    Health is evaluated FIRST: a deleted/swapped/drifted worktree refuses
    with the canonical predicate's failed conjunct regardless of where the
    command was invoked from; path identity only matters once the binding
    itself is sound."""
    bound = Path(binding["worktree_path"])
    healthy, reason = wt.binding_health(binding)
    if not healthy:
        return (
            CLASS_UNHEALTHY,
            f"plan {binding['plan_id']} binding failed the health check: "
            f"{reason}." + _guidance(binding),
        )
    toplevel = _invoking_toplevel(invoking_cwd)  # raises CLASS_INDETERMINATE
    if not _same_directory(toplevel, bound):
        return (
            CLASS_WRONG_PATH,
            f"plan {binding['plan_id']} is bound to a dedicated worktree but was "
            f"invoked from {toplevel.resolve()} — wrong invoking path."
            + _guidance(binding),
        )
    return None


def guard_plan_command(
    plan_dir: Path,
    command: str,
    *,
    invoking_cwd: Path | None = None,
    override_reason: str | None = None,
) -> dict[str, Any] | None:
    """The shared guard precondition. Returns None for unbound plans
    (backward-compatible passthrough), a ``{"guard": "pass"}`` record when
    the binding checks out, or a ``{"guard": "override"}`` record after
    durable override evidence lands. Raises :class:`GuardRefusal` (or
    :class:`worktrees.RegistryCorruptError`) fail-closed otherwise."""
    plan_dir = Path(plan_dir).resolve()
    plan_id = plan_dir.name
    cwd = Path(invoking_cwd) if invoking_cwd is not None else Path.cwd()

    if override_reason is not None and not override_reason.strip():
        raise GuardRefusal(
            f"{OVERRIDE_FLAG} requires a non-empty reason",
            refusal_class=CLASS_INDETERMINATE,
        )

    # STRICT load — a corrupt registry is never the unbound passthrough and
    # is NEVER overridable.
    try:
        bindings = wt.load_registry_strict()
    except wt.RegistryCorruptError as exc:
        if override_reason is not None:
            raise wt.RegistryCorruptError(
                f"{exc}\n  {OVERRIDE_FLAG} is REJECTED for a corrupt registry: "
                "a corrupt registry is never overridable — infrastructure "
                "corruption must be repaired, not waived"
            ) from exc
        raise

    binding = bindings.get(plan_id)
    if binding is None:
        return None  # unbound plans behave exactly as before

    try:
        refusal = _evaluate(binding, cwd)
    except GuardRefusal as exc:
        refusal = (exc.refusal_class, str(exc))

    if refusal is None:
        return {
            "guard": "pass",
            "plan_id": plan_id,
            "command": command,
            "worktree_path": binding["worktree_path"],
        }

    refusal_class, message = refusal
    if override_reason is None:
        raise GuardRefusal(message, refusal_class=refusal_class)
    if refusal_class not in OVERRIDABLE_CLASSES:
        raise GuardRefusal(
            f"{message}\n  {OVERRIDE_FLAG} is rejected for refusal class "
            f"{refusal_class!r}",
            refusal_class=refusal_class,
        )

    # Override path: BOTH artifacts durably written BEFORE proceeding.
    audit_dir = plan_dir / "audit"
    record = {
        "plan_id": plan_id,
        "command": command,
        "refusal_class": refusal_class,
        "refusal_message": message,
        "invoking_path": str(cwd.resolve()),
        "bound_path": binding["worktree_path"],
        "reason": override_reason,
        "actor": wt.resolve_actor(),
        "recorded_at": wt._utc_now(),
    }
    snapshot = {
        "command": f"{command} ({OVERRIDE_FLAG})",
        "plan_id": binding["plan_id"],
        "worktree_path": binding["worktree_path"],
        "base_ref": binding["base_ref"],
        "base_sha": binding["base_sha"],
        "branch": binding["branch"],
        "owner_actor": binding["owner_actor"],
        "captured_at": wt._utc_now(),
        "override": True,
    }
    try:
        _append_durable(audit_dir / OVERRIDE_FILENAME, record)
        _append_durable(audit_dir / wt.SNAPSHOT_FILENAME, snapshot)
    except OSError as exc:
        raise GuardRefusal(
            f"override evidence write failed ({exc}); refusing to proceed "
            "un-evidenced — the guarded command never runs without a durable "
            "override record and binding snapshot",
            refusal_class=refusal_class,
        ) from exc
    return {
        "guard": "override",
        "plan_id": plan_id,
        "command": command,
        "refusal_class": refusal_class,
        "record": record,
    }


__all__ = [
    "CLASS_INDETERMINATE",
    "CLASS_UNHEALTHY",
    "CLASS_WRONG_PATH",
    "GuardRefusal",
    "OVERRIDABLE_CLASSES",
    "OVERRIDE_FILENAME",
    "OVERRIDE_FLAG",
    "guard_plan_command",
]
