"""Repo-hygiene observation — read-only git findings for the ActionItem plane.

Plan 2026-08-09-001. Two responsibilities, both strictly read-only:

  1. ``observe(cwd)`` — working-tree and branch state behind a single injected
     :class:`GitRunner`. Tree and branch sections degrade independently
     (D012): a detached HEAD, zero-commit, or no-remote repo still reports a
     dirty working tree and yields ``branches=None``. Only a cwd that is not a
     git repository at all returns ``None`` for the whole observation.

  2. ``classify(observation, *, bindings)`` — a pure function over that
     observation. Closed vocabulary of seven kinds (see :data:`HYGIENE_KINDS`).
     Precedence and protected-branch exclusions live here (D013).

Read-only is enforced structurally, not by grepping this file:

  * Every git invocation — including transitive helpers such as default-base
    resolution, which needs ``git remote`` — goes through the injected
    :class:`GitRunner`.
  * The allowlist lives on the runner: status, for-each-ref, rev-list,
    rev-parse, symbolic-ref, merge-base, remote, worktree list.
  * ``GIT_OPTIONAL_LOCKS=0`` is set on every child so ``git status`` cannot
    perform its optional index-refresh write.
  * F006 proves both by hashing the whole ``.git`` tree before and after and
    by asserting every recorded argv is allowlisted.

No commit, push, branch delete, stash, clean, or fetch. Findings are computed
when ``dontpanic next`` / ``dashboard build`` runs.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import git_state

MAX_BRANCHES = 32
BRANCH_COLLAPSE_THRESHOLD = 5

HYGIENE_KINDS: frozenset[str] = frozenset(
    {
        "dirty_tree_unbound",
        "branch_ahead_of_remote",
        "branch_no_upstream",
        "branch_merged_upstream_local",
        "plan_status_drift",
        "plan_unparseable",
        "project_path_unusable",
    }
)

_ALLOWED_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "status",
        "for-each-ref",
        "rev-list",
        "rev-parse",
        "symbolic-ref",
        "merge-base",
        "remote",
        "worktree",
    }
)

_TERMINAL_PLAN_STATUSES: frozenset[str] = frozenset({"completed", "abandoned"})
_DRIFT_PLAN_STATUSES: frozenset[str] = frozenset(
    {"active", "draft", "ready_for_audit", "in_audit", "blocked"}
)


class GitAllowlistError(ValueError):
    """A git argv the runner refuses to execute."""


class GitRunner:
    """Allowlisted, lock-free git invoker. The single chokepoint for I/O."""

    ALLOWED_SUBCOMMANDS = _ALLOWED_SUBCOMMANDS

    def __init__(
        self,
        cwd: Path | str,
        *,
        argv_log: list[tuple[str, ...]] | None = None,
    ) -> None:
        self.cwd = Path(cwd)
        self.argv_log: list[tuple[str, ...]] = (
            argv_log if argv_log is not None else []
        )
        self.last_child_env: dict[str, str] = {}

    @classmethod
    def assert_allowed(cls, argv: Sequence[str]) -> None:
        if not argv:
            raise GitAllowlistError("empty git argv")
        sub = argv[0]
        if sub not in cls.ALLOWED_SUBCOMMANDS:
            raise GitAllowlistError(
                f"git subcommand {sub!r} is not on the repo-hygiene allowlist"
            )
        if sub == "worktree" and (len(argv) < 2 or argv[1] != "list"):
            raise GitAllowlistError("only `git worktree list` is allowlisted")

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.assert_allowed(args)
        env = os.environ.copy()
        env["GIT_OPTIONAL_LOCKS"] = "0"
        self.last_child_env = env
        proc = subprocess.run(
            ["git", "-C", str(self.cwd), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.argv_log.append(tuple(args))
        return proc


@dataclasses.dataclass(frozen=True)
class TreeState:
    repo_root: str
    staged: tuple[str, ...]
    unstaged_modified: tuple[str, ...]
    untracked: tuple[str, ...]
    deleted_staged: tuple[str, ...]
    deleted_unstaged: tuple[str, ...]

    @property
    def dirty(self) -> bool:
        return bool(
            self.staged
            or self.unstaged_modified
            or self.untracked
            or self.deleted_staged
            or self.deleted_unstaged
        )

    @property
    def dirty_count(self) -> int:
        return (
            len(self.staged)
            + len(self.unstaged_modified)
            + len(self.untracked)
            + len(self.deleted_staged)
            + len(self.deleted_unstaged)
        )


@dataclasses.dataclass(frozen=True)
class BranchInfo:
    name: str
    sha: str
    upstream: str | None
    ahead: int | None
    behind: int | None
    merged_into_default_at: str | None
    is_current: bool
    checked_out_in_worktree: bool


@dataclasses.dataclass(frozen=True)
class BranchState:
    current: str | None
    default_branch: str | None
    default_ref: str | None
    default_sha: str | None
    branches: tuple[BranchInfo, ...]
    partial: bool
    checked_out_elsewhere: frozenset[str]


@dataclasses.dataclass(frozen=True)
class RepoObservation:
    repo_root: str
    tree: TreeState | None
    branches: BranchState | None
    branches_partial: bool = False


@dataclasses.dataclass(frozen=True)
class HygieneFinding:
    kind: str
    subject: str
    repo_root: str
    title: str = ""
    detail: str = ""
    branches: tuple[str, ...] = ()
    commit_count: int | None = None
    merged_at_sha: str | None = None
    default_ref: str | None = None
    collapsed: bool = False
    partial: bool = False
    plan_id: str | None = None
    plan_status: str | None = None
    plan_dir: str | None = None
    command_resolvable: bool = False


def _empty_tree(repo_root: str) -> TreeState:
    return TreeState(
        repo_root=repo_root,
        staged=(),
        unstaged_modified=(),
        untracked=(),
        deleted_staged=(),
        deleted_unstaged=(),
    )


def _observe_tree(runner: GitRunner, repo_root: str) -> TreeState:
    status = runner.run("status", "--porcelain=v1", "-z")
    if status.returncode != 0:
        return _empty_tree(repo_root)
    parsed = git_state.parse_porcelain(status.stdout)
    return TreeState(
        repo_root=repo_root,
        staged=tuple(entry["path"] for entry in parsed["staged"]),
        unstaged_modified=tuple(
            entry["path"] for entry in parsed["unstaged_modified"]
        ),
        untracked=tuple(parsed["untracked"]),
        deleted_staged=tuple(parsed["deleted_staged"]),
        deleted_unstaged=tuple(parsed["deleted_unstaged"]),
    )


def _resolve_default(
    runner: GitRunner,
) -> tuple[str | None, str | None, str | None]:
    """Return (default_ref, default_branch, default_sha)."""
    remotes = runner.run("remote")
    if remotes.returncode == 0 and "origin" in remotes.stdout.splitlines():
        head = runner.run("symbolic-ref", "refs/remotes/origin/HEAD")
        if head.returncode == 0:
            raw = head.stdout.strip()
            ref = raw.removeprefix("refs/remotes/")
            sha_proc = runner.run("rev-parse", "--verify", ref)
            sha = sha_proc.stdout.strip() if sha_proc.returncode == 0 else None
            branch = ref.rsplit("/", 1)[-1]
            return ref, branch, sha
    for candidate in ("main", "master"):
        verify = runner.run("rev-parse", "--verify", f"refs/heads/{candidate}")
        if verify.returncode == 0:
            return candidate, candidate, verify.stdout.strip()
    return None, None, None


def _worktree_checkouts(
    runner: GitRunner, repo_root: str
) -> tuple[frozenset[str], frozenset[str]]:
    """Return (checked_out_anywhere, checked_out_elsewhere)."""
    listing = runner.run("worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return frozenset(), frozenset()
    anywhere: set[str] = set()
    elsewhere: set[str] = set()
    root = Path(repo_root).resolve()
    path: Path | None = None
    branch: str | None = None

    def _flush() -> None:
        nonlocal path, branch
        if branch:
            anywhere.add(branch)
            if path is not None and path != root:
                elsewhere.add(branch)
        path = None
        branch = None

    for line in listing.stdout.splitlines():
        if line == "":
            _flush()
            continue
        if line.startswith("worktree "):
            path = Path(line.split(" ", 1)[1]).resolve()
        elif line.startswith("branch "):
            ref = line.split(" ", 1)[1]
            branch = ref.removeprefix("refs/heads/")
    _flush()
    return frozenset(anywhere), frozenset(elsewhere)


def _ahead_behind(
    runner: GitRunner, branch: str, upstream: str
) -> tuple[int | None, int | None]:
    proc = runner.run("rev-list", "--left-right", "--count", f"{upstream}...{branch}")
    if proc.returncode != 0:
        return None, None
    text = proc.stdout.strip().replace("\t", " ")
    parts = text.split()
    if len(parts) != 2:
        return None, None
    try:
        behind = int(parts[0])
        ahead = int(parts[1])
    except ValueError:
        return None, None
    return ahead, behind


def _observe_branches(
    runner: GitRunner, repo_root: str, *, max_branches: int
) -> tuple[BranchState | None, bool]:
    head = runner.run("rev-parse", "--verify", "HEAD")
    if head.returncode != 0:
        return None, False
    symbolic = runner.run("symbolic-ref", "--short", "HEAD")
    if symbolic.returncode != 0:
        return None, False
    current = symbolic.stdout.strip()
    remotes = runner.run("remote")
    if remotes.returncode != 0 or not remotes.stdout.strip():
        return None, False

    default_ref, default_branch, default_sha = _resolve_default(runner)
    _anywhere, elsewhere = _worktree_checkouts(runner, repo_root)

    refs = runner.run(
        "for-each-ref",
        "--format=%(refname:short)%00%(objectname)%00%(upstream:short)",
        "refs/heads/",
    )
    if refs.returncode != 0:
        return None, False
    raw_entries: list[tuple[str, str, str]] = []
    payload = refs.stdout
    # Entries are newline-separated records of three NUL fields.
    for line in payload.splitlines():
        parts = line.split("\0")
        if not parts or not parts[0]:
            continue
        name = parts[0]
        sha = parts[1] if len(parts) > 1 else ""
        upstream = parts[2] if len(parts) > 2 and parts[2] else ""
        raw_entries.append((name, sha, upstream))
    raw_entries.sort(key=lambda e: e[0])
    partial = len(raw_entries) > max_branches
    walked = raw_entries[:max_branches]

    infos: list[BranchInfo] = []
    for name, sha, upstream_raw in walked:
        upstream = upstream_raw or None
        ahead: int | None = None
        behind: int | None = None
        if upstream:
            ahead, behind = _ahead_behind(runner, name, upstream)
        merged_at: str | None = None
        if default_sha and sha:
            anc = runner.run("merge-base", "--is-ancestor", sha, default_sha)
            if anc.returncode == 0:
                merged_at = default_sha
        infos.append(
            BranchInfo(
                name=name,
                sha=sha,
                upstream=upstream,
                ahead=ahead,
                behind=behind,
                merged_into_default_at=merged_at,
                is_current=(name == current),
                checked_out_in_worktree=(name in elsewhere or name == current),
            )
        )
    return (
        BranchState(
            current=current,
            default_branch=default_branch,
            default_ref=default_ref,
            default_sha=default_sha,
            branches=tuple(infos),
            partial=partial,
            checked_out_elsewhere=elsewhere,
        ),
        partial,
    )


def observe(
    cwd: Path | str,
    *,
    runner: GitRunner | None = None,
    max_branches: int = MAX_BRANCHES,
) -> RepoObservation | None:
    """Read-only observation of ``cwd``. ``None`` iff it is not a git repo."""
    path = Path(cwd)
    if not path.exists() or not path.is_dir():
        return None
    runner = runner or GitRunner(path)
    top = runner.run("rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return None
    repo_root = str(Path(top.stdout.strip()).resolve())
    tree = _observe_tree(runner, repo_root)
    branches, partial = _observe_branches(
        runner, repo_root, max_branches=max_branches
    )
    return RepoObservation(
        repo_root=repo_root,
        tree=tree,
        branches=branches,
        branches_partial=partial,
    )


def _norm_path(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve())
    except OSError:
        return str(Path(value).expanduser())


def _binding_worktree_paths(bindings: Sequence[Any] | None) -> set[str]:
    out: set[str] = set()
    for entry in bindings or ():
        if isinstance(entry, Mapping):
            raw = entry.get("worktree_path")
        else:
            raw = entry
        if raw:
            out.add(_norm_path(str(raw)))
    return out


def _partial_note(partial: bool) -> str:
    if not partial:
        return ""
    return f" Result is partial (capped at {MAX_BRANCHES} branches)."


def _dirty_finding(obs: RepoObservation) -> HygieneFinding:
    tree = obs.tree
    count = tree.dirty_count if tree is not None else 0
    return HygieneFinding(
        kind="dirty_tree_unbound",
        subject=obs.repo_root,
        repo_root=obs.repo_root,
        title="Uncommitted work exists only on this machine",
        detail=(
            f"{count} uncommitted path(s) in the working tree are not "
            "backed by a commit."
        ),
    )


def _merged_detail(branch: BranchInfo, default_ref: str | None, partial: bool) -> str:
    ref = default_ref or "the default branch"
    sha = branch.merged_into_default_at or "unknown"
    return (
        f"merged into {ref} at {sha}; fetch freshness unknown."
        + _partial_note(partial)
    )


def _classify_one_branch(
    branch: BranchInfo,
    *,
    default_branch: str | None,
    current: str | None,
    elsewhere: frozenset[str],
    default_ref: str | None,
    repo_root: str,
    partial: bool,
) -> HygieneFinding | None:
    protected = {
        name
        for name in (default_branch, current, *elsewhere)
        if name
    }
    if branch.merged_into_default_at:
        if branch.name in protected:
            return None
        return HygieneFinding(
            kind="branch_merged_upstream_local",
            subject=branch.name,
            repo_root=repo_root,
            title=f"Merged work on '{branch.name}' is still sitting in the local repo",
            detail=_merged_detail(branch, default_ref, partial),
            branches=(branch.name,),
            merged_at_sha=branch.merged_into_default_at,
            default_ref=default_ref,
            partial=partial,
        )
    if branch.upstream and branch.ahead and branch.ahead > 0:
        n = branch.ahead
        noun = "commit" if n == 1 else "commits"
        return HygieneFinding(
            kind="branch_ahead_of_remote",
            subject=branch.name,
            repo_root=repo_root,
            title=f"{n} {noun} exist only on this laptop",
            detail=(
                f"Branch {branch.name} holds {n} {noun} not on "
                f"{branch.upstream}."
                + _partial_note(partial)
            ),
            branches=(branch.name,),
            commit_count=n,
            default_ref=default_ref,
            partial=partial,
        )
    if not branch.upstream:
        return HygieneFinding(
            kind="branch_no_upstream",
            subject=branch.name,
            repo_root=repo_root,
            title=f"Work on '{branch.name}' has never been published",
            detail=(
                f"Branch {branch.name} has no remote tracking branch."
                + _partial_note(partial)
            ),
            branches=(branch.name,),
            default_ref=default_ref,
            partial=partial,
        )
    return None


def _collapse(
    findings: list[HygieneFinding], threshold: int
) -> list[HygieneFinding]:
    branch_kinds = (
        "branch_ahead_of_remote",
        "branch_no_upstream",
        "branch_merged_upstream_local",
    )
    kept: list[HygieneFinding] = []
    buckets: dict[str, list[HygieneFinding]] = {k: [] for k in branch_kinds}
    for finding in findings:
        if finding.kind in buckets:
            buckets[finding.kind].append(finding)
        else:
            kept.append(finding)
    _COLLAPSE_TITLES = {
        "branch_ahead_of_remote": "Several branches hold commits that exist only on this laptop",
        "branch_no_upstream": "Several branches have never been published",
        "branch_merged_upstream_local": "Several merged branches are still sitting in the local repo",
    }
    for kind, group in buckets.items():
        if len(group) < threshold:
            kept.extend(group)
            continue
        names = tuple(f.subject for f in group)
        first = group[0]
        listed = ", ".join(names)
        if kind == "branch_merged_upstream_local":
            sha = first.merged_at_sha or "unknown"
            ref = first.default_ref or "the default branch"
            detail = (
                f"{len(names)} branches merged into {ref} at {sha}; "
                f"fetch freshness unknown. Branches: {listed}."
                + _partial_note(first.partial)
            )
        elif kind == "branch_ahead_of_remote":
            total = sum(f.commit_count or 0 for f in group)
            detail = (
                f"{total} commits across {len(names)} branches exist only "
                f"locally. Branches: {listed}."
                + _partial_note(first.partial)
            )
        else:
            detail = (
                f"{len(names)} branches have no remote tracking branch. "
                f"Branches: {listed}."
                + _partial_note(first.partial)
            )
        kept.append(
            HygieneFinding(
                kind=kind,
                subject="aggregate",
                repo_root=first.repo_root,
                title=_COLLAPSE_TITLES[kind],
                detail=detail,
                branches=names,
                commit_count=sum(f.commit_count or 0 for f in group) or None,
                merged_at_sha=first.merged_at_sha,
                default_ref=first.default_ref,
                collapsed=True,
                partial=first.partial,
            )
        )
    return kept


def classify(
    observation: RepoObservation | None,
    *,
    bindings: Sequence[Any] | None = None,
    collapse_threshold: int = BRANCH_COLLAPSE_THRESHOLD,
) -> tuple[HygieneFinding, ...]:
    """Pure classification. No I/O, no clock, no git."""
    if observation is None:
        return ()
    findings: list[HygieneFinding] = []
    bound = _binding_worktree_paths(bindings)
    tree = observation.tree
    if (
        tree is not None
        and tree.dirty
        and _norm_path(observation.repo_root) not in bound
    ):
        findings.append(_dirty_finding(observation))
    state = observation.branches
    if state is None:
        return tuple(findings)
    partial = bool(observation.branches_partial or state.partial)
    elsewhere = state.checked_out_elsewhere
    for branch in state.branches:
        finding = _classify_one_branch(
            branch,
            default_branch=state.default_branch,
            current=state.current,
            elsewhere=elsewhere,
            default_ref=state.default_ref,
            repo_root=observation.repo_root,
            partial=partial,
        )
        if finding is not None:
            findings.append(finding)
    return tuple(_collapse(findings, collapse_threshold))


def _best_plan_id(plan_dir: Path) -> str:
    plan_md = plan_dir / "plan.md"
    if not plan_md.is_file():
        return plan_dir.name
    try:
        from dontpanic_orchestrate import plan_loader

        fm = plan_loader._frontmatter(plan_md)
    except Exception:  # noqa: BLE001 — best-effort id
        return plan_dir.name
    if isinstance(fm, dict) and fm.get("id"):
        return str(fm["id"])
    return plan_dir.name


def _status_value(plan: Any) -> str:
    status = getattr(plan, "status", None)
    if status is None:
        return ""
    return status.value if hasattr(status, "value") else str(status)


def _plan_copy(plan_id: str, status: str) -> tuple[str, str]:
    if status == "active":
        return (
            f"Plan {plan_id} is finished but still open",
            "Every feature already passes. Close the plan so it leaves the "
            "active queue; `dontpanic plan close` accepts this status.",
        )
    if status == "draft":
        return (
            f"Plan {plan_id} is finished but was never locked",
            "Every feature already passes, but status is draft. Lock the plan "
            "before close can run — `dontpanic plan close` refuses any status "
            "other than active.",
        )
    if status == "blocked":
        return (
            f"Plan {plan_id} is finished but still blocked",
            "Every feature already passes, but status is blocked. Unblock the "
            "plan before close can run — `dontpanic plan close` refuses any "
            "status other than active.",
        )
    if status == "ready_for_audit":
        return (
            f"Plan {plan_id} is finished but still waiting on audit",
            "Every feature already passes, but status is ready_for_audit. "
            "Finish the audit path; `dontpanic plan close` only accepts an "
            "active plan.",
        )
    if status == "in_audit":
        return (
            f"Plan {plan_id} is finished but still in audit",
            "Every feature already passes, but status is in_audit. Complete "
            "the audit; `dontpanic plan close` only accepts an active plan.",
        )
    return (
        f"Plan {plan_id} is finished but status is {status}",
        f"Every feature already passes, but status is {status}. "
        "`dontpanic plan close` only accepts an active plan.",
    )


def observe_plans(plans_root: Path | str) -> tuple[HygieneFinding, ...]:
    """Plan-status findings from ``plan_loader``. No git."""
    root = Path(plans_root)
    if not root.is_dir():
        return ()
    from dontpanic_orchestrate import plan_loader

    findings: list[HygieneFinding] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not (child / "plan.md").is_file():
            continue
        try:
            loaded = plan_loader.load(child)
        except Exception as exc:  # noqa: BLE001 — unparseable is a finding
            plan_id = _best_plan_id(child)
            findings.append(
                HygieneFinding(
                    kind="plan_unparseable",
                    subject=plan_id,
                    repo_root=str(root),
                    title=(
                        f"Plan {plan_id} cannot be read, so DontPanic is "
                        "blind to it"
                    ),
                    detail=f"{type(exc).__name__}: {exc}",
                    plan_id=plan_id,
                    plan_dir=str(child),
                )
            )
            continue
        status = _status_value(loaded.plan)
        feats = list(loaded.features.features)
        all_passing = bool(feats) and all(
            bool(getattr(f, "passes", False)) for f in feats
        )
        if not all_passing or status in _TERMINAL_PLAN_STATUSES:
            continue
        if status not in _DRIFT_PLAN_STATUSES:
            continue
        title, detail = _plan_copy(loaded.plan_id, status)
        findings.append(
            HygieneFinding(
                kind="plan_status_drift",
                subject=loaded.plan_id,
                repo_root=str(root),
                title=title,
                detail=detail,
                plan_id=loaded.plan_id,
                plan_status=status,
                plan_dir=str(child),
                command_resolvable=(status == "active"),
            )
        )
    return tuple(findings)


def live_state_from(
    observation: RepoObservation | None,
    *,
    plan_findings: Sequence[HygieneFinding] = (),
    plans: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Shape consumed by the F003/F004 clears_when predicates."""
    hygiene: dict[str, Any] = {
        "tree_dirty": {},
        "ahead_branches": {},
        "no_upstream_branches": {},
        "local_branches": {},
        "plans": dict(plans or {}),
    }
    if observation is not None:
        root = observation.repo_root
        hygiene["tree_dirty"][root] = bool(
            observation.tree is not None and observation.tree.dirty
        )
        if observation.branches is not None:
            local = [b.name for b in observation.branches.branches]
            hygiene["local_branches"][root] = local
            hygiene["ahead_branches"][root] = [
                b.name
                for b in observation.branches.branches
                if b.upstream and b.ahead and b.ahead > 0
            ]
            hygiene["no_upstream_branches"][root] = [
                b.name
                for b in observation.branches.branches
                if not b.upstream
            ]
    for finding in plan_findings:
        if not finding.plan_id:
            continue
        if finding.kind == "plan_unparseable":
            hygiene["plans"][finding.plan_id] = {
                "status": finding.plan_status,
                "all_passing": False,
                "parseable": False,
            }
        elif finding.kind == "plan_status_drift":
            hygiene["plans"][finding.plan_id] = {
                "status": finding.plan_status,
                "all_passing": True,
                "parseable": True,
            }
    return hygiene


def _scrub(text: str | None) -> str:
    if not text:
        return ""
    from dontpanic_orchestrate import state_projection as _sp

    return _sp.scrub_secrets(text) or ""


def _safe_id_part(text: str) -> str:
    scrubbed = _scrub(text)
    if scrubbed != text:
        return "redacted"
    return text.replace("/", "-")


def _safe_param(text: str) -> str:
    """Scrub a clears_when param so secret-shaped branch names never leak."""
    return _safe_id_part(text)


def _now_iso(now: _dt.datetime | str | None) -> str:
    if isinstance(now, str) and now:
        return now
    ts = now if isinstance(now, _dt.datetime) else _dt.datetime.now(_dt.timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain_consequence(finding: HygieneFinding) -> str:
    if finding.kind == "dirty_tree_unbound":
        return "Until those files are committed or discarded, the work exists only on this machine."
    if finding.kind == "branch_ahead_of_remote":
        return "A disk failure would lose those commits."
    if finding.kind == "branch_no_upstream":
        return "That work has no remote backup."
    if finding.kind == "branch_merged_upstream_local":
        return "The local branch can be deleted once you confirm you no longer need it."
    if finding.kind == "plan_status_drift" and finding.command_resolvable:
        return "Marks the plan completed so it leaves the active queue."
    if finding.kind == "plan_status_drift":
        return "The plan stays in a non-terminal status until its real next step happens."
    if finding.kind == "plan_unparseable":
        return "DontPanic cannot see or close this plan until the files parse."
    return "The operator must resolve this outside DontPanic."


def _clears_when(finding: HygieneFinding) -> Any:
    from dontpanic_orchestrate.action_resolvability import ClearsWhen

    root = finding.repo_root
    if finding.kind == "dirty_tree_unbound":
        return ClearsWhen("repo_tree_clean", {"repo_root": root})
    if finding.kind == "branch_ahead_of_remote":
        params: dict[str, Any] = {"repo_root": root}
        if finding.collapsed:
            params["branches"] = [_safe_param(b) for b in finding.branches]
        else:
            params["branch"] = _safe_param(finding.subject)
        return ClearsWhen("branch_pushed", params)
    if finding.kind == "branch_no_upstream":
        params = {"repo_root": root}
        if finding.collapsed:
            params["branches"] = [_safe_param(b) for b in finding.branches]
        else:
            params["branch"] = _safe_param(finding.subject)
        return ClearsWhen("branch_has_upstream", params)
    if finding.kind == "branch_merged_upstream_local":
        params = {"repo_root": root}
        if finding.collapsed:
            params["branches"] = [_safe_param(b) for b in finding.branches]
        else:
            params["branch"] = _safe_param(finding.subject)
        return ClearsWhen("branch_absent_locally", params)
    if finding.kind == "plan_status_drift" and finding.plan_id:
        return ClearsWhen(
            "plan_status_no_longer_drift", {"plan_id": finding.plan_id}
        )
    if finding.kind == "plan_unparseable" and finding.plan_id:
        return ClearsWhen("plan_parseable", {"plan_id": finding.plan_id})
    return None


def _human_reason(finding: HygieneFinding) -> str:
    if finding.kind == "plan_status_drift" and finding.command_resolvable:
        return "closing a plan is a lifecycle change"
    if finding.kind == "plan_status_drift":
        return "plan status must change before close can run"
    if finding.kind == "plan_unparseable":
        return "the plan files must be repaired"
    return "no dontpanic command can perform this git action"


def _item_id(finding: HygieneFinding) -> str:
    if finding.kind in {"plan_status_drift", "plan_unparseable"}:
        tail = _safe_id_part(finding.plan_id or finding.subject)
    elif finding.collapsed:
        tail = "aggregate"
    elif finding.kind == "dirty_tree_unbound":
        tail = _safe_id_part(Path(finding.repo_root).name)
    else:
        tail = _safe_id_part(finding.subject)
    return f"repo_hygiene:{finding.kind}:{tail}"


def _finding_to_item(
    finding: HygieneFinding,
    *,
    project_name: str | None,
    display_name: str | None,
    updated_at: str,
) -> Any:
    from dontpanic_orchestrate import operator_console as oc
    from dontpanic_orchestrate.action_resolvability import (
        RESOLUTION_COMMAND_RESOLVABLE,
        RESOLUTION_OPERATOR_ATTESTED,
    )
    from dontpanic_orchestrate.scope_lattice import Scope

    title = _scrub(finding.title) or finding.title
    detail = _scrub(finding.detail) or finding.detail
    exact: str | None = None
    if finding.kind == "plan_status_drift" and finding.command_resolvable and finding.plan_id:
        exact = f"dontpanic plan close {finding.plan_id}"
    resolution = (
        RESOLUTION_COMMAND_RESOLVABLE
        if exact is not None
        else RESOLUTION_OPERATOR_ATTESTED
    )
    item_id = _item_id(finding)
    return oc.ActionItem(
        id=item_id,
        source=oc.SOURCE_REPO_HYGIENE,
        band=oc.Band.ADVISORY,
        title=title,
        detail=detail or None,
        exact_command=exact,
        automatable=False,
        human_required_reason=_human_reason(finding),
        evidence_uri=finding.plan_dir,
        updated_at=updated_at,
        project_name=project_name,
        display_name=display_name,
        audience=(oc.AUDIENCE_OPERATOR,),
        dedupe_key=item_id,
        reversible=False,
        plain_consequence=_scrub(_plain_consequence(finding)) or _plain_consequence(finding),
        clears_when=_clears_when(finding),
        resolution_class=resolution,
        scope=Scope.PROJECT.value,
        plan_id=finding.plan_id,
    )


def _uncertainty_card(
    *,
    project_name: str | None,
    display_name: str | None,
    updated_at: str,
    reason: str,
) -> Any:
    import dataclasses

    from dontpanic_orchestrate import operator_console as oc
    from dontpanic_orchestrate.scope_lattice import Scope

    card = oc.build_uncertainty_card(
        source=oc.SOURCE_REPO_HYGIENE,
        last_checked=updated_at,
        reason=reason,
        captured_at=updated_at,
    )
    return dataclasses.replace(
        card,
        project_name=project_name,
        display_name=display_name,
        scope=Scope.PROJECT.value,
    )


def _default_plans_root(cwd: Path) -> Path | None:
    candidate = cwd / "docs" / "plans"
    if candidate.is_dir():
        return candidate
    return None


def provide_actions(
    cwd: Path | str | None = None,
    *,
    findings: Sequence[HygieneFinding] | None = None,
    observation: RepoObservation | None = None,
    bindings: Sequence[Any] | None = None,
    plans_root: Path | str | None = None,
    project_name: str | None = None,
    display_name: str | None = None,
    now: _dt.datetime | str | None = None,
    runner: GitRunner | None = None,
    unusable_if_missing: bool = False,
) -> tuple[Any, ...]:
    """Build ActionItems from findings or by observing ``cwd``."""
    updated_at = _now_iso(now)
    if findings is None:
        path = Path(cwd) if cwd is not None else None
        missing = path is None or not path.exists()
        obs = observation
        if obs is None and path is not None and path.exists():
            obs = observe(path, runner=runner)
        if obs is None and unusable_if_missing:
            reason = (
                "project path missing or not a git repository"
                if missing
                else "path exists but is not a git repository"
            )
            return (
                _uncertainty_card(
                    project_name=project_name,
                    display_name=display_name,
                    updated_at=updated_at,
                    reason=reason,
                ),
            )
        git_findings = classify(obs, bindings=bindings)
        plan_root: Path | None
        if plans_root is not None:
            plan_root = Path(plans_root)
        elif path is not None:
            plan_root = _default_plans_root(path)
        else:
            plan_root = None
        plan_findings = observe_plans(plan_root) if plan_root is not None else ()
        findings = (*git_findings, *plan_findings)
    items = [
        _finding_to_item(
            finding,
            project_name=project_name,
            display_name=display_name,
            updated_at=updated_at,
        )
        for finding in findings
    ]
    return tuple(items)


def render_text(items: Sequence[Any]) -> str:
    """Human-readable hygiene block for ``dontpanic next`` text output."""
    if not items:
        return ""
    lines = ["", "Repo hygiene", "------------"]
    for item in items:
        title = getattr(item, "title", "")
        detail = getattr(item, "detail", None)
        command = getattr(item, "exact_command", None)
        lines.append(f"* {title}")
        if detail:
            lines.append(f"  {detail}")
        if command:
            lines.append(f"  {command}")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "BRANCH_COLLAPSE_THRESHOLD",
    "HYGIENE_KINDS",
    "MAX_BRANCHES",
    "BranchInfo",
    "BranchState",
    "GitAllowlistError",
    "GitRunner",
    "HygieneFinding",
    "RepoObservation",
    "TreeState",
    "classify",
    "live_state_from",
    "observe",
    "observe_plans",
    "provide_actions",
    "render_text",
]
