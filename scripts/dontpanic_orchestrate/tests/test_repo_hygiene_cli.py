"""Plan 2026-08-09-001 F005 — next + dashboard wiring across repo and fleet.

`dontpanic next --json` in a fixture repo with all four git conditions plus one
status-drifted plan emits the expected items with correct bands and project
scoping; a clean repo emits zero hygiene items; dashboard build --project
renders them scoped; a missing project path produces an uncertainty card.

Run: PYTHONPATH=scripts /opt/homebrew/bin/pytest \\
  scripts/dontpanic_orchestrate/tests/test_repo_hygiene_cli.py -q
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from dontpanic_orchestrate import cli
from dontpanic_orchestrate import command_guidance
from dontpanic_orchestrate import dashboard
from dontpanic_orchestrate import operator_console as oc
from dontpanic_orchestrate import projects_registry
from dontpanic_orchestrate import repo_hygiene as rh
from dontpanic_orchestrate.tests.test_repo_hygiene_observe import (
    add_origin_and_push,
    commit_file,
    init_repo,
    run_git,
)
from dontpanic_orchestrate.tests.test_repo_hygiene_plan_status import _write_plan


def _run(argv: list[str], *, cwd: Path | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    if cwd is not None:
        import os

        prev = Path.cwd()
        os.chdir(cwd)
    else:
        prev = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(argv)
    finally:
        if prev is not None:
            import os

            os.chdir(prev)
    return rc, out.getvalue(), err.getvalue()


def _hygiene_fixture(tmp_path: Path) -> Path:
    """Repo with dirty tree, unpushed branch, no-upstream branch, merged local
    branch, and an all-passing active plan."""
    repo = init_repo(tmp_path / "proj")
    commit_file(repo, "README.md", "base\n", "init")
    add_origin_and_push(repo, tmp_path / "proj.git")

    run_git(repo, "checkout", "-q", "-b", "unpushed")
    commit_file(repo, "ahead.txt", "local only\n", "ahead")
    run_git(repo, "push", "-u", "origin", "unpushed")
    commit_file(repo, "ahead2.txt", "still local\n", "ahead2")
    run_git(repo, "checkout", "-q", "main")
    run_git(repo, "checkout", "-q", "-b", "lonely")
    commit_file(repo, "lonely.txt", "no upstream\n", "lonely")
    run_git(repo, "checkout", "-q", "main")
    run_git(repo, "checkout", "-q", "-b", "merged-feat")
    commit_file(repo, "feat.txt", "merged\n", "feat")
    run_git(repo, "checkout", "-q", "main")
    run_git(repo, "merge", "--no-ff", "-m", "merge feat", "merged-feat")
    run_git(repo, "push", "origin", "main")
    (repo / "wip.py").write_text("# dirty\n")

    plans = repo / "docs" / "plans"
    _write_plan(plans, "2026-08-09-200-feat-close-me", status="active")
    return repo


def _hygiene_items(payload: dict) -> list[dict]:
    items = payload.get("action_items") or payload.get("items") or []
    return [it for it in items if it.get("source") == oc.SOURCE_REPO_HYGIENE]


def test_next_json_emits_hygiene_items(tmp_path: Path) -> None:
    repo = _hygiene_fixture(tmp_path)
    rc, out, err = _run(["next", "--json"], cwd=repo)
    assert rc == 0, err
    payload = json.loads(out)
    items = _hygiene_items(payload)
    kinds = {it["id"].split(":")[1] for it in items}
    assert "dirty_tree_unbound" in kinds
    assert "branch_ahead_of_remote" in kinds
    assert "branch_no_upstream" in kinds
    assert "branch_merged_upstream_local" in kinds
    assert "plan_status_drift" in kinds
    assert all(it["band"] == "advisory" for it in items)
    close = next(it for it in items if "plan_status_drift" in it["id"])
    assert close["exact_command"] == "dontpanic plan close 2026-08-09-200-feat-close-me"


def test_clean_repo_emits_zero_hygiene_items(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "clean")
    commit_file(repo, "README.md", "clean\n", "init")
    add_origin_and_push(repo, tmp_path / "clean.git")
    rc, out, err = _run(["next", "--json"], cwd=repo)
    assert rc == 0, err
    payload = json.loads(out)
    assert _hygiene_items(payload) == []


def test_dashboard_build_project_scopes_hygiene(tmp_path: Path) -> None:
    repo = _hygiene_fixture(tmp_path)
    projects_registry.add_project("hygiene-proj", str(repo), display_name="Hygiene")
    out_dir = tmp_path / "dash-out"
    dashboard.build(
        plans_root=repo / "docs" / "plans",
        out_dir=out_dir,
        repo_root=repo,
        project_name="hygiene-proj",
        project_display_name="Hygiene",
        write_capabilities_cache=False,
        check_reconcile=False,
        check_architecture=False,
    )
    payload = json.loads((out_dir / "what-now.json").read_text())
    items = _hygiene_items(payload)
    assert items
    assert all(it.get("project_name") == "hygiene-proj" for it in items)
    kinds = {it["id"].split(":")[1] for it in items}
    assert "dirty_tree_unbound" in kinds
    assert "plan_status_drift" in kinds


def test_missing_project_path_emits_uncertainty_card(tmp_path: Path) -> None:
    missing = tmp_path / "gone"
    items = oc.provide_repo_hygiene_actions(
        cwd=missing,
        project_name="ghost",
        unusable_if_missing=True,
        now="2026-08-09T00:00:00Z",
    )
    assert len(items) == 1
    card = items[0]
    assert card.id.startswith("uncertain:")
    assert card.source == oc.SOURCE_REPO_HYGIENE
    assert card.band == oc.Band.INFO
    assert card.section == oc.SECTION_STATUS_UNCERTAIN
    assert card.project_name == "ghost"


def test_agent_commands_guidance_mentions_hygiene() -> None:
    payload = command_guidance.inventory_public_payload()
    next_entries = [c for c in payload["commands"] if c["path"] == ["next"]]
    assert next_entries
    blob = json.dumps(next_entries).lower()
    assert "hygiene" in blob or "repo-hygiene" in blob or "repo hygiene" in blob


def test_fleet_next_tags_project_name(tmp_path: Path) -> None:
    repo = _hygiene_fixture(tmp_path)
    projects_registry.add_project("fleet-a", str(repo))
    rc, out, err = _run(["next", "--scope", "fleet", "--format", "json"], cwd=tmp_path)
    assert rc == 0, err
    payload = json.loads(out)
    items = _hygiene_items(payload)
    assert items
    assert all(it.get("project_name") == "fleet-a" for it in items)
