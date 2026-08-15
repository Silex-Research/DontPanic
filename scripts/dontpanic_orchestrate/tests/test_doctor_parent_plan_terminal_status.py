"""A terminal plan must not hard-fail the doctor — and therefore CI.

`dontpanic_doctor` hard-gates on one named plan validating:

    PARENT_PLAN_DIR = docs/plans/2026-04-19-001-infra-cross-agent-orchestration

That plan's status is ``abandoned``. Frozen history validated against evolving
schemas is a losing bet: every schema tightening retroactively invalidates
records nobody intends to touch again, and because CI runs
``dontpanic_doctor --skip-auth``, the build goes red for a plan that is by
definition finished.

That is not hypothetical. Requiring evidence on ``passes: true`` in the
Pydantic arm (the D008 gap) immediately rejected five features on that plan —
F006, F007, F008, F023 cite ``evidence_refs`` but never say who verified them
or when; F022 cites nothing. The validator is right. The plan is abandoned.
Neither fact should stop the repo from building.

So the gate narrows to what it can honestly ask for:

  * a plan still in play (draft/active/ready_for_audit/in_audit/blocked) MUST
    validate — that is a live contract and a real defect if broken;
  * a terminal plan (completed/abandoned) that fails validation WARNS, naming
    the status so nobody mistakes the warning for a clean bill;
  * a missing plan dir, an unreadable status, or a missing validator still
    hard-fail — those are infrastructure faults, not history.

The last clause matters most: "cannot read the status" must never be treated
as "probably terminal, carry on". An unattributable plan gets the strict path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_DOCTOR = Path(__file__).resolve().parents[2] / "dontpanic_doctor.py"
_spec = importlib.util.spec_from_file_location("dontpanic_doctor_under_test", _DOCTOR)
doctor = importlib.util.module_from_spec(_spec)
sys.modules["dontpanic_doctor_under_test"] = doctor
_spec.loader.exec_module(doctor)


LIVE = ["draft", "active", "ready_for_audit", "in_audit", "blocked"]
TERMINAL = ["completed", "abandoned"]


class TestStatusClassification:
    @pytest.mark.parametrize("status", TERMINAL)
    def test_terminal_statuses_are_terminal(self, status):
        assert doctor.is_terminal_plan_status(status) is True

    @pytest.mark.parametrize("status", LIVE)
    def test_live_statuses_are_not_terminal(self, status):
        assert doctor.is_terminal_plan_status(status) is False

    @pytest.mark.parametrize("value", [None, "", "  ", "not-a-status", "COMPLETED-ish"])
    def test_unknown_status_is_never_treated_as_terminal(self, value):
        """Unreadable state must take the strict path, not the lenient one."""
        assert doctor.is_terminal_plan_status(value) is False

    def test_status_matching_ignores_case_and_padding(self):
        assert doctor.is_terminal_plan_status("  Abandoned  ") is True


class TestReadingStatusOffDisk:
    def _plan(self, tmp_path: Path, frontmatter: str) -> Path:
        d = tmp_path / "docs" / "plans" / "2026-01-01-001-infra-x"
        d.mkdir(parents=True)
        (d / "plan.md").write_text(f"---\n{frontmatter}\n---\n\n# X\n")
        return d

    def test_reads_a_normal_status(self, tmp_path):
        d = self._plan(tmp_path, "id: 2026-01-01-001-infra-x\nstatus: abandoned")
        assert doctor.read_plan_status(d) == "abandoned"

    def test_quoted_status_is_unwrapped(self, tmp_path):
        d = self._plan(tmp_path, 'id: 2026-01-01-001-infra-x\nstatus: "completed"')
        assert doctor.read_plan_status(d) == "completed"

    def test_missing_plan_md_yields_none(self, tmp_path):
        d = tmp_path / "docs" / "plans" / "2026-01-01-001-infra-x"
        d.mkdir(parents=True)
        assert doctor.read_plan_status(d) is None

    def test_absent_status_key_yields_none(self, tmp_path):
        d = self._plan(tmp_path, "id: 2026-01-01-001-infra-x\ntitle: no status here")
        assert doctor.read_plan_status(d) is None

    def test_a_status_word_in_prose_is_not_the_status(self, tmp_path):
        """Only the frontmatter key counts — not the word appearing in the body."""
        d = tmp_path / "docs" / "plans" / "2026-01-01-001-infra-x"
        d.mkdir(parents=True)
        (d / "plan.md").write_text(
            "---\nid: 2026-01-01-001-infra-x\n---\n\n# X\n\nThis plan is abandoned.\n"
        )
        assert doctor.read_plan_status(d) is None


class TestTheGateItself:
    """End-to-end on the real check, with the validator stubbed."""

    @pytest.fixture
    def rejecting_validator(self, monkeypatch):
        class _Proc:
            returncode = 1
            stderr = "features.5: Value error, feature F006 claims passes=true but is missing ..."
            stdout = ""

        monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: _Proc())

    def _point_at(self, monkeypatch, tmp_path: Path, status: str | None) -> Path:
        d = tmp_path / "docs" / "plans" / "2026-01-01-001-infra-x"
        d.mkdir(parents=True)
        body = f"status: {status}\n" if status is not None else ""
        (d / "plan.md").write_text(f"---\nid: 2026-01-01-001-infra-x\n{body}---\n\n# X\n")
        monkeypatch.setattr(doctor, "PARENT_PLAN_DIR", d)
        return d

    @pytest.mark.parametrize("status", TERMINAL)
    def test_terminal_plan_failing_validation_warns(
        self, monkeypatch, tmp_path, rejecting_validator, status
    ):
        self._point_at(monkeypatch, tmp_path, status)
        r = doctor.check_parent_plan_validates()
        assert r.ok is True, "a terminal plan must not fail the doctor"
        assert r.warn is True, "…but it must not read as clean either"
        assert status in r.message, "the warning must name the status that earned leniency"

    @pytest.mark.parametrize("status", LIVE)
    def test_live_plan_failing_validation_still_fails(
        self, monkeypatch, tmp_path, rejecting_validator, status
    ):
        self._point_at(monkeypatch, tmp_path, status)
        r = doctor.check_parent_plan_validates()
        assert r.ok is False, f"status={status} is still in play — it must keep blocking"

    def test_unreadable_status_takes_the_strict_path(
        self, monkeypatch, tmp_path, rejecting_validator
    ):
        self._point_at(monkeypatch, tmp_path, None)
        r = doctor.check_parent_plan_validates()
        assert r.ok is False, "no status is not permission to skip the gate"

    def test_a_passing_terminal_plan_is_ok_not_warn(self, monkeypatch, tmp_path):
        class _Proc:
            returncode = 0
            stderr = ""
            stdout = ""

        monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: _Proc())
        self._point_at(monkeypatch, tmp_path, "abandoned")
        r = doctor.check_parent_plan_validates()
        assert r.ok is True and r.warn is False

    def test_missing_plan_dir_still_hard_fails(self, monkeypatch, tmp_path):
        monkeypatch.setattr(doctor, "PARENT_PLAN_DIR", tmp_path / "nope")
        r = doctor.check_parent_plan_validates()
        assert r.ok is False, "a missing plan dir is infrastructure, not history"


class TestTheRealRepoStopsBlockingCI:
    """The concrete outcome: CI must go green on the checked-in parent plan."""

    def test_the_shipped_parent_plan_does_not_fail_the_doctor(self):
        r = doctor.check_parent_plan_validates()
        assert r.ok is True, (
            f"the parent plan still fails the doctor, so CI stays red: {r.message}"
        )
