"""Plan 2026-08-09-001 F002 — closed finding vocabulary, precedence, exclusions.

classify() is pure (subprocess.run and Path.write_text raise if touched).
A branch that is both merged and ahead emits exactly one finding — the merged
one. Default / current / other-worktree branches produce zero cleanup findings.
Binding suppression holds. Collapse threshold is exercised at N-1, N, N+1.

Run: PYTHONPATH=scripts /opt/homebrew/bin/pytest \\
  scripts/dontpanic_orchestrate/tests/test_repo_hygiene_classify.py -q
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dontpanic_orchestrate import repo_hygiene as rh


def _branch(
    name: str,
    *,
    sha: str = "a" * 40,
    upstream: str | None = None,
    ahead: int | None = None,
    behind: int | None = None,
    merged_into_default_at: str | None = None,
    is_current: bool = False,
    checked_out_in_worktree: bool = False,
) -> rh.BranchInfo:
    return rh.BranchInfo(
        name=name,
        sha=sha,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        merged_into_default_at=merged_into_default_at,
        is_current=is_current,
        checked_out_in_worktree=checked_out_in_worktree,
    )


def _tree(*, dirty_untracked: tuple[str, ...] = (), repo_root: str = "/tmp/repo") -> rh.TreeState:
    return rh.TreeState(
        repo_root=repo_root,
        staged=(),
        unstaged_modified=(),
        untracked=dirty_untracked,
        deleted_staged=(),
        deleted_unstaged=(),
    )


def _obs(
    *,
    repo_root: str = "/tmp/repo",
    tree: rh.TreeState | None = None,
    branches: tuple[rh.BranchInfo, ...] = (),
    current: str | None = "main",
    default_branch: str | None = "main",
    default_ref: str | None = "origin/main",
    default_sha: str | None = "d" * 40,
    partial: bool = False,
    checked_out_elsewhere: frozenset[str] | None = None,
) -> rh.RepoObservation:
    if tree is None:
        tree = _tree(repo_root=repo_root)
    branch_state = rh.BranchState(
        current=current,
        default_branch=default_branch,
        default_ref=default_ref,
        default_sha=default_sha,
        branches=branches,
        partial=partial,
        checked_out_elsewhere=checked_out_elsewhere or frozenset(),
    )
    return rh.RepoObservation(
        repo_root=repo_root,
        tree=tree,
        branches=branch_state,
        branches_partial=partial,
    )


def test_hygiene_kinds_is_the_closed_seven() -> None:
    assert rh.HYGIENE_KINDS == frozenset(
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


def test_classify_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("classify must not touch subprocess or the filesystem")

    monkeypatch.setattr("subprocess.run", _boom)
    monkeypatch.setattr(Path, "write_text", _boom)
    obs = _obs(
        tree=_tree(dirty_untracked=("wip.py",)),
        branches=(_branch("main", is_current=True, upstream="origin/main", ahead=0),),
    )
    findings = rh.classify(obs, bindings=())
    assert any(f.kind == "dirty_tree_unbound" for f in findings)


def test_merged_dominates_ahead() -> None:
    default_sha = "d" * 40
    obs = _obs(
        default_sha=default_sha,
        branches=(
            _branch("main", is_current=True, upstream="origin/main", ahead=0),
            _branch(
                "both",
                upstream="origin/both",
                ahead=3,
                merged_into_default_at=default_sha,
            ),
        ),
    )
    findings = rh.classify(obs, bindings=())
    kinds = [f.kind for f in findings if f.subject == "both"]
    assert kinds == ["branch_merged_upstream_local"]
    merged = findings[kinds.index("branch_merged_upstream_local") ] if False else next(
        f for f in findings if f.subject == "both"
    )
    assert merged.merged_at_sha == default_sha
    assert "fetch freshness unknown" in (merged.detail or "")
    assert "as of the last fetch" not in (merged.detail or "").lower()
    assert default_sha in (merged.detail or "")


def test_default_branch_never_gets_cleanup_finding() -> None:
    default_sha = "d" * 40
    obs = _obs(
        default_sha=default_sha,
        branches=(
            _branch(
                "main",
                is_current=True,
                upstream="origin/main",
                ahead=0,
                merged_into_default_at=default_sha,
            ),
        ),
    )
    findings = rh.classify(obs, bindings=())
    assert all(f.kind != "branch_merged_upstream_local" for f in findings)


def test_current_branch_never_gets_cleanup_finding() -> None:
    default_sha = "d" * 40
    obs = _obs(
        current="wip",
        default_sha=default_sha,
        branches=(
            _branch("main", upstream="origin/main", ahead=0),
            _branch(
                "wip",
                is_current=True,
                upstream="origin/wip",
                ahead=0,
                merged_into_default_at=default_sha,
            ),
        ),
    )
    findings = rh.classify(obs, bindings=())
    assert not any(
        f.kind == "branch_merged_upstream_local" and f.subject == "wip" for f in findings
    )


def test_other_worktree_branch_never_gets_cleanup_finding() -> None:
    default_sha = "d" * 40
    obs = _obs(
        default_sha=default_sha,
        checked_out_elsewhere=frozenset({"guest"}),
        branches=(
            _branch("main", is_current=True, upstream="origin/main", ahead=0),
            _branch(
                "guest",
                checked_out_in_worktree=True,
                merged_into_default_at=default_sha,
            ),
        ),
    )
    findings = rh.classify(obs, bindings=())
    assert not any(
        f.kind == "branch_merged_upstream_local" and f.subject == "guest" for f in findings
    )


def test_current_branch_can_still_be_ahead() -> None:
    obs = _obs(
        current="wip",
        branches=(
            _branch("main", upstream="origin/main", ahead=0),
            _branch("wip", is_current=True, upstream="origin/wip", ahead=7),
        ),
    )
    findings = rh.classify(obs, bindings=())
    ahead = [f for f in findings if f.kind == "branch_ahead_of_remote"]
    assert len(ahead) == 1
    assert ahead[0].subject == "wip"
    assert ahead[0].commit_count == 7


def test_binding_suppresses_dirty_tree() -> None:
    root = "/tmp/bound-wt"
    obs = _obs(repo_root=root, tree=_tree(dirty_untracked=("x.py",), repo_root=root))
    unsuppressed = rh.classify(obs, bindings=())
    assert any(f.kind == "dirty_tree_unbound" for f in unsuppressed)
    suppressed = rh.classify(
        obs, bindings=({"worktree_path": root, "plan_id": "p"},)
    )
    assert all(f.kind != "dirty_tree_unbound" for f in suppressed)


def test_collapse_threshold_n_minus_1_n_n_plus_1() -> None:
    n = rh.BRANCH_COLLAPSE_THRESHOLD

    def _findings(count: int) -> tuple[rh.HygieneFinding, ...]:
        extras = tuple(
            _branch(f"old-{i}", merged_into_default_at="d" * 40) for i in range(count)
        )
        obs = _obs(
            branches=(
                _branch("main", is_current=True, upstream="origin/main", ahead=0),
                *extras,
            )
        )
        return rh.classify(obs, bindings=())

    below = [f for f in _findings(n - 1) if f.kind == "branch_merged_upstream_local"]
    assert len(below) == n - 1
    assert all(not f.collapsed for f in below)

    at = [f for f in _findings(n) if f.kind == "branch_merged_upstream_local"]
    assert len(at) == 1
    assert at[0].collapsed is True
    assert len(at[0].branches) == n

    above = [f for f in _findings(n + 1) if f.kind == "branch_merged_upstream_local"]
    assert len(above) == 1
    assert above[0].collapsed is True
    assert len(above[0].branches) == n + 1


def test_partial_observation_named_in_detail() -> None:
    obs = _obs(
        partial=True,
        branches=(
            _branch("main", is_current=True, upstream="origin/main", ahead=0),
            _branch("wip", upstream="origin/wip", ahead=2),
        ),
    )
    findings = rh.classify(obs, bindings=())
    ahead = next(f for f in findings if f.kind == "branch_ahead_of_remote")
    assert ahead.partial is True
    assert "partial" in (ahead.detail or "").lower()
    assert str(rh.MAX_BRANCHES) in (ahead.detail or "")


def test_none_observation_yields_no_findings() -> None:
    assert rh.classify(None, bindings=()) == ()
