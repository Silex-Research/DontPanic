"""Regression: a volley must not block its own signoff on artifacts it wrote.

Observed 2026-08-09 on plan 2026-08-09-002 F001. The volley reached
``signed_off`` at iteration 2 and then terminated ``blocked``:

    PatchCompletenessError: Patch incomplete — signoff blocked.
      unstaged_dirty_state | block | INBOX.md, claude-implementer-F001-i0.json,
      codex-auditor-F001-i0.json, transcript.md, git-state-0-implementer.json, ...

Every cited file was written by the SUPERVISOR during that same run. Mode 5
escalates ``unstaged_dirty_state`` to ``block`` for files outside
``touched_files``, and ``touched_files`` is built from the IMPLEMENTER's
declared evidence refs — so supervisor-authored run telemetry can never appear
in it and is therefore always "outside".

The failure is structural rather than incidental, and committing beforehand
does not help: the next dispatch rewrites INBOX.md, appends to the transcript,
and writes fresh envelopes, so the files go dirty again. The first dispatch of
that feature escaped only because it paused at ``pre_merge`` before reaching
the signoff step at all.

The fix treats the dispatching plan's own run telemetry as self-authored and
therefore touched by definition. It deliberately does NOT cover ``plan.md``,
``features.json``, or ``decisions.jsonl`` — those are the contract and the
deliverable, and dirty state in them is still worth blocking on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import patch_completeness_gate as gate


def _plan_dir(tmp_path: Path) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / "2026-08-09-002-feat-decision-brief-at-gates"
    (plan_dir / "audit").mkdir(parents=True)
    (plan_dir / "evidence").mkdir(parents=True)
    return plan_dir


def _git_state(paths: list[str]) -> dict:
    return {
        "staged": [],
        "unstaged_modified": [{"path": p, "status": "M"} for p in paths],
        "untracked": [],
        "deleted_staged": [],
        "deleted_unstaged": [],
    }


# Exactly the file set the real 2026-08-09 failure cited.
SELF_AUTHORED = [
    "docs/plans/2026-08-09-002-feat-decision-brief-at-gates/INBOX.md",
    "docs/plans/2026-08-09-002-feat-decision-brief-at-gates/audit/claude-implementer-F001-i0.json",
    "docs/plans/2026-08-09-002-feat-decision-brief-at-gates/audit/codex-auditor-F001-i1.json",
    "docs/plans/2026-08-09-002-feat-decision-brief-at-gates/audit/transcript.md",
    "docs/plans/2026-08-09-002-feat-decision-brief-at-gates/audit/plan-run-fingerprint.json",
    "docs/plans/2026-08-09-002-feat-decision-brief-at-gates/evidence/git-state-0-implementer.json",
]


def test_self_authored_run_telemetry_does_not_block_signoff(tmp_path: Path) -> None:
    """The reported bug. A run's own INBOX / audit / git-state must not block it."""
    plan_dir = _plan_dir(tmp_path)

    block = gate.enforce(
        plan_dir,
        plan_id="2026-08-09-002-feat-decision-brief-at-gates",
        iteration=0,
        role="implementer",
        audit_paths=[],
        affected_paths=[],
        repo_root=tmp_path,
        git_state_override=_git_state(SELF_AUTHORED),
    )

    assert block is not None, "gate returned None instead of a signoff block"
    assert block["status"] != "fail", (
        "signoff blocked on files the run itself wrote: " f"{block!r}"
    )


def test_contract_files_still_block(tmp_path: Path) -> None:
    """The exemption must not swallow the plan contract or the deliverable."""
    plan_dir = _plan_dir(tmp_path)
    contract = [
        "docs/plans/2026-08-09-002-feat-decision-brief-at-gates/features.json",
        "docs/plans/2026-08-09-002-feat-decision-brief-at-gates/plan.md",
    ]

    with pytest.raises(gate.PatchCompletenessError):
        gate.enforce(
            plan_dir,
            plan_id="2026-08-09-002-feat-decision-brief-at-gates",
            iteration=0,
            role="implementer",
            audit_paths=[],
            affected_paths=[],
            repo_root=tmp_path,
            git_state_override=_git_state(contract),
        )


def test_unrelated_source_still_blocks(tmp_path: Path) -> None:
    """Real unrelated dirty state outside the plan dir must still block."""
    plan_dir = _plan_dir(tmp_path)

    with pytest.raises(gate.PatchCompletenessError):
        gate.enforce(
            plan_dir,
            plan_id="2026-08-09-002-feat-decision-brief-at-gates",
            iteration=0,
            role="implementer",
            audit_paths=[],
            affected_paths=[],
            repo_root=tmp_path,
            git_state_override=_git_state(
                ["scripts/dontpanic_orchestrate/supervisor.py"]
            ),
        )


def test_another_plans_telemetry_still_blocks(tmp_path: Path) -> None:
    """Only the DISPATCHING plan's telemetry is exempt.

    A sibling plan's dirty INBOX is somebody else's uncommitted work and is
    exactly the drift this gate exists to surface.
    """
    plan_dir = _plan_dir(tmp_path)

    with pytest.raises(gate.PatchCompletenessError):
        gate.enforce(
            plan_dir,
            plan_id="2026-08-09-002-feat-decision-brief-at-gates",
            iteration=0,
            role="implementer",
            audit_paths=[],
            affected_paths=[],
            repo_root=tmp_path,
            git_state_override=_git_state(
                ["docs/plans/2026-08-09-001-feat-repo-hygiene-actions/INBOX.md"]
            ),
        )


def test_mixed_self_authored_and_unrelated_blocks_and_cites_only_unrelated(
    tmp_path: Path,
) -> None:
    """Exempting telemetry must not hide a genuine finding alongside it."""
    plan_dir = _plan_dir(tmp_path)

    with pytest.raises(gate.PatchCompletenessError) as excinfo:
        gate.enforce(
            plan_dir,
            plan_id="2026-08-09-002-feat-decision-brief-at-gates",
            iteration=0,
            role="implementer",
            audit_paths=[],
            affected_paths=[],
            repo_root=tmp_path,
            git_state_override=_git_state(
                SELF_AUTHORED + ["scripts/dontpanic_orchestrate/supervisor.py"]
            ),
        )

    rendered = str(excinfo.value)
    # The `files` column legitimately lists everything dirty — that is a true
    # statement about the tree. What must not happen is self-authored telemetry
    # being cited as UNRELATED, since that phrase is what drives the block.
    marker = "Files outside touched_files: "
    assert marker in rendered, "expected the outside-files citation in the block"
    outside = rendered.split(marker, 1)[1].split(" |", 1)[0]

    assert "supervisor.py" in outside, "genuine unrelated file missing from the citation"
    for telemetry in ("transcript.md", "INBOX.md", "git-state-0-implementer.json"):
        assert telemetry not in outside, (
            f"self-authored {telemetry} cited as unrelated dirty state"
        )


def test_persisted_report_written_even_when_exempted(tmp_path: Path) -> None:
    """The exemption changes the verdict, not the audit trail."""
    plan_dir = _plan_dir(tmp_path)

    gate.enforce(
        plan_dir,
        plan_id="2026-08-09-002-feat-decision-brief-at-gates",
        iteration=0,
        role="implementer",
        audit_paths=[],
        affected_paths=[],
        repo_root=tmp_path,
        git_state_override=_git_state(SELF_AUTHORED),
    )

    report = plan_dir / "audit" / "patch-completeness-0.json"
    assert report.exists(), "gate stopped persisting its report"
    payload = json.loads(report.read_text())
    assert payload.get("findings") is not None
