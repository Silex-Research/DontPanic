"""The implementer must stage what it writes, or the patch gate is unsatisfiable.

`patch_completeness` blocks the flip to ``passes: true`` when a test file is
untracked — correctly, since a fresh clone would not run it. But nobody was
told to stage. Plan 2026-08-13-001 F004 terminated with:

    test_file_untracked | block |
      scripts/dontpanic_orchestrate/tests/test_outcome_score_f004.py |
      Run: git add scripts/dontpanic_orchestrate/tests/test_outcome_score_f004.py

The recommendation is right and nobody could act on it in time. The operator's
last action ended before the file existed; the gate runs after the implementer's
round; and a re-dispatch to stage one file costs a paid volley. The supervisor's
own artifacts were already carved out on 2026-08-09
(``patch_completeness_gate.self_authored_telemetry``) — this is the remaining
half, and it belongs to the only participant holding both write access and the
knowledge of which files are its own.

These tests pin the instruction into both implementer prompt branches (first
round and findings round) rather than just the shared preamble, because a note
added to one branch and not the other is exactly the drift that leaves the
second and later rounds unstaged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dontpanic_orchestrate import prompts

_FEATURE = {
    "id": "F001",
    "description": "A description",
    "acceptance": "Some machine-checkable condition",
    "steps": ["do the thing"],
}


def _prompt(iteration: int, prior: Path | None) -> str:
    return prompts.implementer_prompt(
        plan_id="2026-08-15-001-feat-x",
        plan_dir=Path("/tmp/plan"),
        feature=_FEATURE,
        iteration=iteration,
        prior_auditor_path=prior,
    )


CASES = [
    ("first round", 0, None),
    ("findings round", 1, Path("/tmp/plan/audit/codex-auditor-F001-i0.json")),
]


class TestBothBranchesCarryTheRule:
    @pytest.mark.parametrize("label,iteration,prior", CASES, ids=[c[0] for c in CASES])
    def test_prompt_tells_the_implementer_to_stage(self, label, iteration, prior):
        text = _prompt(iteration, prior)
        assert "git add" in text, f"{label} prompt never mentions staging"

    @pytest.mark.parametrize("label,iteration,prior", CASES, ids=[c[0] for c in CASES])
    def test_prompt_names_the_gate_that_will_block(self, label, iteration, prior):
        """An instruction without its reason gets dropped under pressure."""
        text = _prompt(iteration, prior).lower()
        assert "untracked" in text and "passes" in text, label

    @pytest.mark.parametrize("label,iteration,prior", CASES, ids=[c[0] for c in CASES])
    def test_staging_is_distinguished_from_committing(self, label, iteration, prior):
        """The implementer must not read 'git add' as authority to commit."""
        text = _prompt(iteration, prior)
        assert "not commit" in text.lower() or "does not create a commit" in text.lower(), label

    def test_the_note_is_not_silently_empty(self):
        assert "git add" in prompts.STAGING_NOTE
