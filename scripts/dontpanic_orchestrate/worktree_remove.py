"""Guard-hardening F002 — explicit, audited, safe worktree removal
(plan 2026-06-11-001, operator-directed numbered algorithm D010).

:func:`remove_worktree` executes EXACTLY the locked 7-step sequence, in
order, with each step's failure behavior pinned at the step. The step
bodies call small module-level seams (``_append_intent`` / ``_git_remove``
/ ``_registry_delete`` / ``_append_outcome``) so the ORDER is checkable
from the source and each failure arm is testable in isolation.

Operator policy (D003): gitignored files are still local human/workspace
state — their presence BLOCKS removal (git worktree remove would delete
them); preservation applies recursively into registered submodules. There
is NO force flag anywhere on this surface, and ``plan close`` never
removes — cleanup is always an explicit, separately-audited command.

The audit log is install-level (``$DONTPANIC_HOME/worktree-audit.jsonl``):
removal evidence must survive the plan worktree it describes. Every append
is written, flushed, AND fsynced.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import global_config as gc
from dontpanic_orchestrate import worktrees as wt

AUDIT_LOG_FILENAME = "worktree-audit.jsonl"


class RemoveRefusal(wt.WorktreeError):
    """Pre-destruction refusal (steps 1-4): nothing was removed and the
    registry binding is untouched."""

    def __init__(self, message: str, *, step: int):
        super().__init__(message)
        self.step = step


class RemoveError(wt.WorktreeError):
    """Mid-sequence failure (steps 5-6): the message states exactly what
    happened, what survived, and how to recover."""

    def __init__(self, message: str, *, step: int):
        super().__init__(message)
        self.step = step


class RemoveDegraded(wt.WorktreeError):
    """Step-7 degraded state: the removal SUCCEEDED but its outcome record
    could not be written. Loud, never silent success — the intent entry
    plus the absent worktree remain the durable evidence."""

    step = 7


def audit_log_path() -> Path:
    return gc.dontpanic_home() / AUDIT_LOG_FILENAME


def _append_durable(record: dict[str, Any]) -> None:
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _read_entries() -> list[dict[str, Any]]:
    path = audit_log_path()
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn trailing line never hides earlier evidence
    return entries


def _has_intent_entry(plan_id: str) -> bool:
    return any(
        e.get("event") == "removal_intent" and e.get("plan_id") == plan_id
        for e in _read_entries()
    )


# ── step seams (module-level so order is source-checkable and each failure
#    arm is injectable in tests) ──


def _append_intent(plan_id: str, binding: dict[str, Any]) -> None:
    """Step 4 — the removal-INTENT record. Never a success claim."""
    _append_durable(
        {
            "event": "removal_intent",
            "plan_id": plan_id,
            "worktree_path": binding["worktree_path"],
            "branch": binding["branch"],
            "owner_actor": binding["owner_actor"],
            "removed_by": wt.resolve_actor(),
            "intent_at": wt._utc_now(),
        }
    )


def _git_remove(binding: dict[str, Any]) -> None:
    """Step 5 — git worktree remove WITHOUT any force flag."""
    wt._git(
        binding["repo_root"], "worktree", "remove", binding["worktree_path"]
    )


def _registry_delete(plan_id: str) -> None:
    """Step 6 — delete the registry binding."""
    wt.remove_binding(plan_id)


def _append_outcome(
    plan_id: str,
    binding: dict[str, Any],
    *,
    status: str,
    completion: bool = False,
    error: str | None = None,
) -> None:
    """Step 7 — the removal-OUTCOME record. The completion path uses this
    SAME writer with completion=True (D011: one writer, one shape)."""
    record: dict[str, Any] = {
        "event": "removal_outcome",
        "plan_id": plan_id,
        "worktree_path": binding["worktree_path"],
        "branch": binding["branch"],
        "removed_by": wt.resolve_actor(),
        "status": status,
        "completion": completion,
        "outcome_at": wt._utc_now(),
    }
    if error:
        record["error"] = error
    _append_durable(record)


# ── step 3 cleanliness probes ──


def _porcelain(repo: Path, *extra: str) -> list[str]:
    out = wt._git(repo, "status", "--porcelain", *extra)
    return [ln for ln in out.splitlines() if ln.strip()]


def _submodule_paths(repo: Path) -> list[str]:
    gitmodules = Path(repo) / ".gitmodules"
    if not gitmodules.is_file():
        return []
    try:
        out = wt._git(
            repo, "config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"
        )
    except wt.WorktreeError:
        return []
    return [line.split(" ", 1)[1] for line in out.splitlines() if " " in line]


def _cleanliness_violations(wt_path: Path) -> list[str]:
    """Full-policy cleanliness: porcelain (modified/staged/untracked),
    gitignored content, registered submodules recursively, and nested
    non-submodule .git directories. Returns human-readable violation lines
    naming the offending paths; empty list = clean."""
    violations: list[str] = []

    tracked_or_untracked = _porcelain(wt_path)
    if tracked_or_untracked:
        listing = ", ".join(ln.strip() for ln in tracked_or_untracked[:20])
        violations.append(
            f"modified/staged/untracked content present: {listing}"
        )

    ignored = [
        ln[3:].strip()
        for ln in _porcelain(wt_path, "--ignored")
        if ln.startswith("!!")
    ]
    if ignored:
        violations.append(
            "gitignored content present (preserved by default — removal would "
            "delete it): " + ", ".join(ignored[:20])
        )

    # registered submodules, recursively: any modified/staged/untracked/
    # gitignored content inside refuses with the submodule path.
    def _probe_submodules(root: Path, prefix: str) -> None:
        for rel in _submodule_paths(root):
            sub = root / rel
            label = f"{prefix}{rel}"
            if not (sub / ".git").exists():
                continue  # not initialized — nothing checked out to lose
            offending = [ln.strip() for ln in _porcelain(sub, "--ignored")]
            if offending:
                violations.append(
                    f"submodule {label} contains uncommitted/ignored content: "
                    + ", ".join(offending[:20])
                )
            _probe_submodules(sub, f"{label}/")

    _probe_submodules(wt_path, "")

    # nested NON-submodule .git directories (an ignored embedded repo hides
    # from porcelain entirely)
    submodules = {str((wt_path / rel).resolve()) for rel in _submodule_paths(wt_path)}
    for dirpath, dirnames, _filenames in os.walk(wt_path):
        if str(Path(dirpath).resolve()) in submodules:
            dirnames.clear()  # submodules are probed above, recursively
            continue
        if ".git" in dirnames and Path(dirpath).resolve() != wt_path.resolve():
            violations.append(
                f"nested non-submodule git repository at {dirpath}"
            )
            dirnames.remove(".git")
    return violations


# ── the numbered algorithm ──


def remove_worktree(plan_id: str) -> dict[str, Any]:
    """The locked 7-step removal sequence (D010), one step per block."""

    # STEP 1 — strict registry load (corrupt refuses before anything else and
    # is NEVER overridable) and binding resolution.
    bindings = wt.load_registry_strict()  # raises RegistryCorruptError
    binding = bindings.get(plan_id)
    if binding is None:
        raise RemoveRefusal(
            f"plan {plan_id} has no worktree binding — nothing to remove "
            "(see `dontpanic plan worktree list`)",
            step=1,
        )
    wt_path = Path(binding["worktree_path"])

    # STEP 2 — canonical binding_health (v0's predicate, never re-specified).
    # SOLE exception: the registry-only completion path — missing worktree
    # path + this plan's prior removal-INTENT entry → delete only the
    # registry entry (touching no filesystem), append a completion OUTCOME
    # via the SAME writer, and exit. Every other unhealthy state refuses;
    # remove has NO override flag.
    healthy, reason = wt.binding_health(binding)
    if not healthy:
        if not wt_path.exists() and _has_intent_entry(plan_id):
            _registry_delete(plan_id)
            _append_outcome(
                plan_id, binding, status="completed_registry_only", completion=True
            )
            return {"path": "completion", "plan_id": plan_id}
        raise RemoveRefusal(
            f"plan {plan_id} binding failed the health check: {reason} — "
            "refusing to remove (no override exists for removal; repair the "
            "worktree or, if it was already physically removed after a prior "
            "audited attempt, re-run to take the registry-only completion path)",
            step=2,
        )

    # STEP 3 — full-policy cleanliness: dirty/staged/untracked, gitignored
    # (preserved by default), submodules recursively, nested git repos.
    violations = _cleanliness_violations(wt_path)
    if violations:
        raise RemoveRefusal(
            f"plan {plan_id} worktree at {wt_path} is not clean under the "
            "removal policy:\n  - " + "\n  - ".join(violations) + "\n"
            "commit/push or relocate this content first — removal never "
            "deletes local state",
            step=3,
        )

    # STEP 4 — append AND fsync the removal-INTENT entry. If this write
    # fails, refuse: nothing destructive has happened and nothing does
    # (unaudited cleanup is impossible by construction).
    try:
        _append_intent(plan_id, binding)
    except OSError as exc:
        raise RemoveRefusal(
            f"could not write the removal-intent audit record ({exc}); "
            "refusing to remove — unaudited cleanup never proceeds and "
            "nothing was touched",
            step=4,
        ) from exc

    # STEP 5 — git worktree remove, no force flag. On failure the registry
    # binding is LEFT INTACT, a failure OUTCOME is appended, and the command
    # fails with recovery guidance.
    try:
        _git_remove(binding)
    except wt.WorktreeError as exc:
        try:
            _append_outcome(plan_id, binding, status="failed", error=str(exc))
        except OSError:
            pass  # the intent entry remains the durable evidence
        raise RemoveError(
            f"git worktree remove failed for {wt_path}: {exc}\n"
            "the registry binding was left intact and nothing was deleted "
            "from the registry; the worktree may be partially intact — "
            "inspect it, then re-run `dontpanic plan worktree remove "
            f"{plan_id}`",
            step=5,
        ) from exc

    # STEP 6 — delete the registry binding ONLY after successful physical
    # removal. On failure: name the orphaned binding with recovery guidance
    # (re-run takes the step-2 completion path); the status model renders
    # the orphan as broken.
    try:
        _registry_delete(plan_id)
    except Exception as exc:  # noqa: BLE001 — any registry failure is loud
        raise RemoveError(
            f"worktree {wt_path} was removed but the registry delete failed "
            f"({exc}) — plan {plan_id} now has an ORPHANED binding (rendered "
            "as broken in `plan worktree list`); re-run `dontpanic plan "
            f"worktree remove {plan_id}` to complete via the registry-only "
            "completion path",
            step=6,
        ) from exc

    # STEP 7 — append AND fsync the removal-OUTCOME entry, strictly after
    # the mutation. If this final append fails AFTER a successful mutation:
    # LOUD degraded state, never silent success.
    try:
        _append_outcome(plan_id, binding, status="removed")
    except OSError as exc:
        raise RemoveDegraded(
            f"removal of {wt_path} SUCCEEDED (worktree gone, binding "
            f"deleted) but the removal-outcome audit record could not be "
            f"written ({exc}) — DEGRADED state, not silent success. The "
            "removal-intent entry plus the absent worktree remain the "
            "durable evidence; repair the audit log at "
            f"{audit_log_path()} and append the outcome manually if needed"
        ) from exc

    return {"path": "removed", "plan_id": plan_id, "worktree_path": str(wt_path)}


__all__ = [
    "AUDIT_LOG_FILENAME",
    "RemoveDegraded",
    "RemoveError",
    "RemoveRefusal",
    "audit_log_path",
    "remove_worktree",
]
