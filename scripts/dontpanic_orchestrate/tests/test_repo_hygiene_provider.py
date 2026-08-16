"""Plan 2026-08-09-001 F003 — provide_repo_hygiene_actions + clears_when.

Every emitted item declares a registered clears_when; suppress_resolved
retires each kind once its predicate flips; git remedies emit exact_command=None;
reversible is False unless a named re-runnable remedy exists; ActionItem
construction accepts every item; aggregate() dedupes; D010: every item has
plain_consequence and no title leads with a git mechanism term.

Run: PYTHONPATH=scripts /opt/homebrew/bin/pytest \\
  scripts/dontpanic_orchestrate/tests/test_repo_hygiene_provider.py -q
"""

from __future__ import annotations

from dontpanic_orchestrate import action_resolvability as ar
from dontpanic_orchestrate import operator_console as oc
from dontpanic_orchestrate import repo_hygiene as rh

_TS = "2026-08-09T00:00:00Z"
_ROOT = "/tmp/hygiene-repo"

_MECHANISM_LEADS = ("ahead", "upstream", "ref", "head", "porcelain")


def _finding(kind: str, **kwargs: object) -> rh.HygieneFinding:
    defaults: dict[str, object] = {
        "kind": kind,
        "subject": kwargs.pop("subject", "wip") if "subject" not in kwargs else kwargs["subject"],
        "repo_root": _ROOT,
        "title": "",
        "detail": "detail",
        "branches": (),
        "commit_count": None,
        "merged_at_sha": None,
        "default_ref": "origin/main",
        "collapsed": False,
        "partial": False,
        "plan_id": None,
        "plan_status": None,
        "plan_dir": None,
        "command_resolvable": False,
    }
    defaults.update(kwargs)
    return rh.HygieneFinding(**defaults)  # type: ignore[arg-type]


def _git_findings() -> tuple[rh.HygieneFinding, ...]:
    return (
        _finding(
            "dirty_tree_unbound",
            subject=_ROOT,
            title="Uncommitted work exists only on this machine",
            detail="3 files are uncommitted in the working tree.",
        ),
        _finding(
            "branch_ahead_of_remote",
            subject="wip",
            title="12 commits exist only on this laptop",
            detail="Branch wip is 12 commits ahead of origin/wip.",
            commit_count=12,
        ),
        _finding(
            "branch_no_upstream",
            subject="lonely",
            title="Work on 'lonely' has never been published",
            detail="Branch lonely has no remote tracking branch.",
        ),
        _finding(
            "branch_merged_upstream_local",
            subject="old",
            title="Merged work on 'old' is still sitting in the local repo",
            detail="merged into origin/main at " + "d" * 40 + "; fetch freshness unknown",
            merged_at_sha="d" * 40,
        ),
    )


def test_source_registered_below_architecture() -> None:
    assert oc.SOURCE_REPO_HYGIENE == "repo_hygiene"
    assert oc.SOURCE_REPO_HYGIENE in oc._VALID_SOURCES
    assert oc.SOURCE_REPO_HYGIENE in oc._SOURCE_PRIORITY
    assert oc._SOURCE_PRIORITY[oc.SOURCE_REPO_HYGIENE] > oc._SOURCE_PRIORITY[oc.SOURCE_ARCHITECTURE]


def test_every_item_has_registered_clears_when() -> None:
    items = oc.provide_repo_hygiene_actions(findings=_git_findings(), now=_TS)
    assert len(items) == 4
    registered = ar.registered_predicates()
    for item in items:
        assert item.clears_when is not None
        assert item.clears_when.predicate in registered


def test_suppress_resolved_retires_each_kind() -> None:
    items = oc.provide_repo_hygiene_actions(findings=_git_findings(), now=_TS)
    live_dirty = {
        "hygiene": {
            "tree_dirty": {_ROOT: False},
            "ahead_branches": {_ROOT: ["wip"]},
            "no_upstream_branches": {_ROOT: ["lonely"]},
            "local_branches": {_ROOT: ["wip", "lonely", "old"]},
        }
    }
    kept, audit = ar.suppress_resolved(items, live_dirty)
    assert any(a["predicate"] == "repo_tree_clean" for a in audit)
    assert all(it.clears_when and it.clears_when.predicate != "repo_tree_clean" for it in kept)

    live_all_clear = {
        "hygiene": {
            "tree_dirty": {_ROOT: False},
            "ahead_branches": {_ROOT: []},
            "no_upstream_branches": {_ROOT: []},
            "local_branches": {_ROOT: ["wip", "lonely"]},
        }
    }
    kept_all, audit_all = ar.suppress_resolved(items, live_all_clear)
    assert kept_all == ()
    assert {a["predicate"] for a in audit_all} == {
        "repo_tree_clean",
        "branch_pushed",
        "branch_has_upstream",
        "branch_absent_locally",
    }


def test_git_items_have_no_exact_command() -> None:
    items = oc.provide_repo_hygiene_actions(findings=_git_findings(), now=_TS)
    assert items
    assert all(it.exact_command is None for it in items)


def test_reversible_false_without_named_rerunnable_remedy() -> None:
    items = oc.provide_repo_hygiene_actions(findings=_git_findings(), now=_TS)
    for it in items:
        if it.reversible:
            raise AssertionError(
                f"{it.id} set reversible=True without a named re-runnable remedy"
            )


def test_actionitem_accepts_every_item() -> None:
    items = oc.provide_repo_hygiene_actions(findings=_git_findings(), now=_TS)
    assert all(isinstance(it, oc.ActionItem) for it in items)
    assert all(it.source == oc.SOURCE_REPO_HYGIENE for it in items)
    assert all(it.band == oc.Band.ADVISORY for it in items)


def test_aggregate_dedupes_repeats() -> None:
    first = oc.provide_repo_hygiene_actions(findings=_git_findings(), now=_TS)
    second = oc.provide_repo_hygiene_actions(findings=_git_findings(), now=_TS)
    merged = oc.aggregate(first, second)
    assert len(merged) == len(first)
    assert {it.dedupe_key for it in merged} == {it.dedupe_key for it in first}


def test_d010_impact_first_copy() -> None:
    items = oc.provide_repo_hygiene_actions(findings=_git_findings(), now=_TS)
    assert items
    for it in items:
        assert it.plain_consequence
        lead = it.title.split()[0].lower().strip(":,")
        assert lead not in _MECHANISM_LEADS, it.title
        low = it.title.lower()
        assert not any(low.startswith(term) for term in _MECHANISM_LEADS), it.title


def test_branch_kinds_are_operator_attested() -> None:
    items = oc.provide_repo_hygiene_actions(findings=_git_findings(), now=_TS)
    by_kind = {}
    for it in items:
        kind = it.id.split(":")[1]
        by_kind[kind] = it
    for kind in (
        "branch_ahead_of_remote",
        "branch_no_upstream",
        "branch_merged_upstream_local",
    ):
        assert by_kind[kind].resolution_class == ar.RESOLUTION_OPERATOR_ATTESTED
