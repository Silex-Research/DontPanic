"""Worktree Isolation v0 — plan 2026-06-10-002 (substrate slice, D012 split).

Four cooperating surfaces:

F001 — binding registry at ``$DONTPANIC_HOME/worktrees.json`` (same home
resolution as projects.json). Pydantic ``extra='forbid'`` records; every
write is ATOMIC (write-to-temp-then-rename in the same directory) so an
interrupted write can never truncate pre-existing bindings. Two loaders:
:func:`load_registry` degrades a corrupt file to empty + a ``corrupt`` flag
for read-only consumers; :func:`load_registry_strict` RAISES
:class:`RegistryCorruptError` for anything that mutates registry or
filesystem state, and for evidence-writing gate paths (F002) — a corrupt
registry must never be mistaken for "no binding".

F004 — :func:`binding_health`, the CANONICAL health predicate: the recorded
``worktree_path`` exists AND is a git worktree AND that worktree belongs to
the recorded ``repo_root`` AND its current branch equals the recorded
branch. Any probe error is UNHEALTHY (fail closed) with the failed conjunct
as a machine-readable reason. The status model and the (follow-up)
guard-hardening plan consume this one function — health conditions are
never re-specified elsewhere.

F006 — :func:`create_worktree`: repo_root derives from the PLAN DIR's
containing repository (never the invoking cwd); base = the repo's default
branch resolved to a commit SHA (origin/HEAD when resolvable, else local
main-over-master) unless an explicit base is passed; target path is
repo-key-qualified (``<repo-dir-name>-<short-hash-of-repo_root>``) under
``$DONTPANIC_HOME/worktrees/`` and validated OUTSIDE the repository; the
registry write is LAST, so the hard invariant is no-binding-without-
worktree; a failed registry write best-effort rolls back the created
worktree + branch and reports any residue.

No removal command exists in this slice (guard-hardening plan scope).
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from dontpanic_orchestrate import global_config as gc

REGISTRY_FILENAME = "worktrees.json"
WORKTREES_DIRNAME = "worktrees"
BRANCH_PREFIX = "plan/"


class WorktreeError(ValueError):
    """Refusals from the worktree registry / create surfaces."""


class RegistryCorruptError(WorktreeError):
    """The registry file exists but cannot be parsed/validated. Strict
    consumers (anything mutating, plus evidence-writing gate paths) must
    refuse rather than treat this as an empty registry."""


# ──────────────────────────────  F001: registry  ──────────────────────────────


class WorktreeBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    repo_root: str
    worktree_path: str
    branch: str
    base_ref: str
    base_sha: str
    owner_actor: str
    created_at: str


class _Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    bindings: dict[str, WorktreeBinding] = {}


class LoadedRegistry:
    def __init__(self, bindings: dict[str, dict[str, Any]], corrupt: bool):
        self.bindings = bindings
        self.corrupt = corrupt


def registry_path() -> Path:
    return gc.dontpanic_home() / REGISTRY_FILENAME


def resolve_actor() -> str:
    actor = os.environ.get("DONTPANIC_ACTOR")
    if actor:
        return actor
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "operator"
    return f"{user}@{socket.gethostname()}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_registry(path: Path) -> _Registry:
    raw = json.loads(path.read_text())
    return _Registry.model_validate(raw)


def load_registry() -> LoadedRegistry:
    """Read-only loader: a corrupt file degrades to empty + corrupt flag.
    Consumers MUST surface the flag (registry_corrupt warning), never
    silently render an empty registry."""
    path = registry_path()
    if not path.is_file():
        return LoadedRegistry({}, corrupt=False)
    try:
        reg = _parse_registry(path)
    except (OSError, json.JSONDecodeError, ValidationError):
        return LoadedRegistry({}, corrupt=True)
    return LoadedRegistry(
        {pid: b.model_dump() for pid, b in reg.bindings.items()}, corrupt=False
    )


def load_registry_strict() -> dict[str, dict[str, Any]]:
    """Strict loader for mutating + evidence-writing paths: raises on a
    corrupt file instead of degrading."""
    path = registry_path()
    if not path.is_file():
        return {}
    try:
        reg = _parse_registry(path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise RegistryCorruptError(
            f"{path}: worktree registry is corrupt/unparseable ({exc}); refusing "
            "to proceed — fix or remove the file (a corrupt registry is never "
            "treated as 'no bindings')"
        ) from exc
    return {pid: b.model_dump() for pid, b in reg.bindings.items()}


def _write_registry(bindings: dict[str, dict[str, Any]]) -> None:
    """Atomic write: temp file in the SAME directory, fsync, then
    os.replace — an interrupted write can never truncate prior entries."""
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    reg = _Registry(
        bindings={pid: WorktreeBinding.model_validate(b) for pid, b in bindings.items()}
    )
    payload = json.dumps(reg.model_dump(), indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".worktrees-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def add_binding(binding: dict[str, Any]) -> dict[str, Any]:
    bindings = load_registry_strict()
    record = WorktreeBinding.model_validate(binding).model_dump()
    pid = record["plan_id"]
    if pid in bindings:
        raise WorktreeError(
            f"plan {pid} is already bound to {bindings[pid]['worktree_path']} — "
            "remove the existing binding first"
        )
    for other in bindings.values():
        if other["worktree_path"] == record["worktree_path"]:
            raise WorktreeError(
                f"worktree path {record['worktree_path']} is already claimed by "
                f"plan {other['plan_id']}"
            )
    bindings[pid] = record
    _write_registry(bindings)
    return record


def get_binding(plan_id: str) -> dict[str, Any] | None:
    return load_registry_strict().get(plan_id)


def remove_binding(plan_id: str) -> None:
    bindings = load_registry_strict()
    if plan_id not in bindings:
        raise WorktreeError(f"plan {plan_id} has no binding")
    del bindings[plan_id]
    _write_registry(bindings)


def list_bindings() -> list[dict[str, Any]]:
    return [load_registry_strict()[k] for k in sorted(load_registry_strict())]


# ──────────────────────────────  git helpers  ──────────────────────────────


def _git(repo: Path | str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise WorktreeError(
            f"git {' '.join(args)} failed in {repo}: {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


# ──────────────────────────────  F004: binding_health  ──────────────────────────────


def binding_health(binding: dict[str, Any]) -> tuple[bool, str | None]:
    """The canonical health predicate. Healthy IFF the recorded path exists,
    is a git worktree, belongs to the recorded repo_root, and is on the
    recorded branch. Probe errors are UNHEALTHY (fail closed). Returns
    (healthy, failed-conjunct reason)."""
    wt_path = Path(binding["worktree_path"])
    repo_root = Path(binding["repo_root"])
    try:
        if not wt_path.is_dir():
            return False, "worktree path does not exist"
        try:
            toplevel = _git(wt_path, "rev-parse", "--show-toplevel")
        except WorktreeError:
            return False, "path is not a git worktree"
        if Path(toplevel).resolve() != wt_path.resolve():
            return False, "path is not a git worktree (nested inside another)"
        # membership: the path must appear in repo_root's OWN worktree list
        try:
            listing = _git(repo_root, "worktree", "list", "--porcelain")
        except WorktreeError:
            return False, "recorded repo_root is not probeable"
        registered = {
            Path(line.split(" ", 1)[1]).resolve()
            for line in listing.splitlines()
            if line.startswith("worktree ")
        }
        if wt_path.resolve() not in registered:
            return False, "path does not belong to the recorded repo_root"
        current = _git(wt_path, "rev-parse", "--abbrev-ref", "HEAD")
        if current == "HEAD":
            return False, "worktree is on a detached HEAD, not the recorded branch"
        if current != binding["branch"]:
            return False, (
                f"current branch {current!r} differs from recorded branch "
                f"{binding['branch']!r}"
            )
    except Exception as exc:  # noqa: BLE001 — indeterminate probe = unhealthy
        return False, f"health probe failed: {exc}"
    return True, None


def _current_branch(wt_path: Path) -> str | None:
    try:
        return _git(wt_path, "rev-parse", "--abbrev-ref", "HEAD")
    except Exception:  # noqa: BLE001
        return None


def build_status_model() -> dict[str, Any]:
    """One model, many renderers (list / brief / dashboard). Unhealthy
    bindings carry explicit null dirty/untracked_count with the health
    reason — never fabricated false/zero. A corrupt registry sets
    registry_corrupt instead of silently rendering an empty list."""
    loaded = load_registry()
    model: dict[str, Any] = {
        "registry_corrupt": loaded.corrupt,
        "registry_path": str(registry_path()),
        "bindings": [],
    }
    for pid in sorted(loaded.bindings):
        b = loaded.bindings[pid]
        healthy, reason = binding_health(b)
        row: dict[str, Any] = {
            "plan_id": b["plan_id"],
            "branch": b["branch"],
            "current_branch": _current_branch(Path(b["worktree_path"])),
            "worktree_path": b["worktree_path"],
            "owner_actor": b["owner_actor"],
            "base_ref": b["base_ref"],
            "base_sha": b["base_sha"],
            "healthy": healthy,
            "health_reason": reason,
            "dirty": None,
            "untracked_count": None,
        }
        if healthy:
            try:
                porcelain = _git(Path(b["worktree_path"]), "status", "--porcelain")
                lines = [ln for ln in porcelain.splitlines() if ln.strip()]
                row["dirty"] = bool(lines)
                # untracked entries exactly as porcelain reports them in its
                # default mode — a collapsed untracked directory is ONE entry.
                row["untracked_count"] = sum(1 for ln in lines if ln.startswith("??"))
            except WorktreeError as exc:
                row["healthy"] = False
                row["health_reason"] = f"status probe failed: {exc}"
                row["dirty"] = None
                row["untracked_count"] = None
        model["bindings"].append(row)
    return model


# ──────────────────────────────  F002: gate-time snapshots  ──────────────────────────────


SNAPSHOT_FILENAME = "worktree-bindings.jsonl"


def capture_binding_snapshot(plan_dir: Path, command: str) -> dict[str, Any] | None:
    """F002 — record the plan's worktree binding as gate evidence.

    Called by plan lock / audit / close and the orchestrate dispatch entry
    BEFORE their side effects. Uses the STRICT loader: a corrupt registry
    refuses the command (raises RegistryCorruptError) rather than being
    silently treated as no-binding. With a valid registry and no binding,
    returns None and writes nothing (additive — unbound plans behave
    exactly as before)."""
    plan_dir = Path(plan_dir).resolve()
    bindings = load_registry_strict()  # raises RegistryCorruptError fail-closed
    binding = bindings.get(plan_dir.name)
    if binding is None:
        return None
    snapshot = {
        "command": command,
        "plan_id": binding["plan_id"],
        "worktree_path": binding["worktree_path"],
        "base_ref": binding["base_ref"],
        "base_sha": binding["base_sha"],
        "branch": binding["branch"],
        "owner_actor": binding["owner_actor"],
        "captured_at": _utc_now(),
    }
    audit_dir = plan_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    with (audit_dir / SNAPSHOT_FILENAME).open("a") as fh:
        fh.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    return snapshot


# ──────────────────────────────  F006: create  ──────────────────────────────


def _repo_key(repo_root: Path) -> str:
    return hashlib.sha256(str(repo_root.resolve()).encode()).hexdigest()[:8]


def worktree_target_path(repo_root: Path, plan_id: str) -> Path:
    repo_root = Path(repo_root).resolve()
    return (
        gc.dontpanic_home()
        / WORKTREES_DIRNAME
        / f"{repo_root.name}-{_repo_key(repo_root)}"
        / plan_id
    )


def resolve_default_base(repo_root: Path) -> str:
    """Pinned default-branch rule: origin/HEAD when an origin exists and it
    resolves; else local main, else local master (main wins when both
    exist); else refuse."""
    remotes = _git(repo_root, "remote")
    if "origin" in remotes.splitlines():
        try:
            ref = _git(repo_root, "symbolic-ref", "refs/remotes/origin/HEAD")
            return ref.removeprefix("refs/remotes/")
        except WorktreeError:
            pass  # origin exists but origin/HEAD unresolvable — local rule
    for candidate in ("main", "master"):
        try:
            _git(repo_root, "rev-parse", "--verify", f"refs/heads/{candidate}")
            return candidate
        except WorktreeError:
            continue
    raise WorktreeError(
        f"{repo_root}: cannot resolve a default base — no origin/HEAD and no "
        "local main/master; pass an explicit base"
    )


def create_worktree(plan_dir: Path, *, base: str | None = None) -> dict[str, Any]:
    """Create the per-plan worktree and bind it. Registry write is LAST —
    the hard invariant is no-binding-without-worktree; rollback of the
    worktree/branch on a failed registry write is best-effort with residue
    reported."""
    plan_dir = Path(plan_dir).resolve()
    if not plan_dir.is_dir():
        raise WorktreeError(f"plan dir not found: {plan_dir}")
    plan_id = plan_dir.name
    # repo_root from the PLAN DIR's containing repository — never the cwd.
    repo_root = Path(_git(plan_dir, "rev-parse", "--show-toplevel")).resolve()

    # strict load up front: corrupt registry refuses before any mutation,
    # and pre-existing bindings/claims refuse before any git work.
    bindings = load_registry_strict()
    if plan_id in bindings:
        raise WorktreeError(
            f"plan {plan_id} is already bound to {bindings[plan_id]['worktree_path']}"
        )
    target = worktree_target_path(repo_root, plan_id)
    for other in bindings.values():
        if other["worktree_path"] == str(target):
            raise WorktreeError(f"worktree path {target} is already claimed")
    if target.exists():
        raise WorktreeError(f"target path already exists: {target}")
    # isolation validation: the target must live OUTSIDE the repository and
    # outside any of its registered worktrees (a DONTPANIC_HOME misconfigured
    # into the checkout cannot silently undermine isolation).
    resolved_target = target.resolve()
    inside_of = [repo_root]
    listing = _git(repo_root, "worktree", "list", "--porcelain")
    inside_of += [
        Path(line.split(" ", 1)[1]).resolve()
        for line in listing.splitlines()
        if line.startswith("worktree ")
    ]
    for root in inside_of:
        if resolved_target == root or root in resolved_target.parents:
            raise WorktreeError(
                f"target path {target} lies inside {root} — DONTPANIC_HOME must "
                "resolve outside the repository for isolation to hold"
            )

    branch = f"{BRANCH_PREFIX}{plan_id}"
    existing = _git(repo_root, "branch", "--list", branch)
    if existing.strip():
        raise WorktreeError(
            f"branch {branch} already exists — v0 never reuses a pre-existing "
            "plan branch; delete it or choose a different plan id"
        )

    base_ref = base or resolve_default_base(repo_root)
    try:
        base_sha = _git(repo_root, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    except WorktreeError as exc:
        raise WorktreeError(f"base {base_ref!r} does not resolve: {exc}") from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    # create AT base_sha so the recorded SHA cannot drift from the checkout.
    _git(repo_root, "worktree", "add", "-b", branch, str(target), base_sha)

    binding = {
        "plan_id": plan_id,
        "repo_root": str(repo_root),
        "worktree_path": str(target),
        "branch": branch,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "owner_actor": resolve_actor(),
        "created_at": _utc_now(),
    }
    try:
        add_binding(binding)
    except Exception as exc:  # noqa: BLE001 — registry write failed: roll back
        residue: list[str] = []
        try:
            _git(repo_root, "worktree", "remove", "--force", str(target))
        except Exception:  # noqa: BLE001
            residue.append(f"worktree {target}")
        try:
            _git(repo_root, "branch", "-D", branch)
        except Exception:  # noqa: BLE001
            residue.append(f"branch {branch}")
        detail = (
            "rolled back cleanly" if not residue
            else "ROLLBACK RESIDUE requiring manual cleanup: " + ", ".join(residue)
        )
        raise WorktreeError(
            f"registry write failed after worktree creation ({exc}); {detail}. "
            "No binding was written."
        ) from exc
    return binding


__all__ = [
    "BRANCH_PREFIX",
    "REGISTRY_FILENAME",
    "LoadedRegistry",
    "RegistryCorruptError",
    "WorktreeBinding",
    "WorktreeError",
    "add_binding",
    "binding_health",
    "build_status_model",
    "create_worktree",
    "get_binding",
    "list_bindings",
    "load_registry",
    "load_registry_strict",
    "registry_path",
    "remove_binding",
    "resolve_actor",
    "resolve_default_base",
    "worktree_target_path",
]
