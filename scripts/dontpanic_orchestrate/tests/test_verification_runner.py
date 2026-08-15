"""The supervisor executes the plan's regression; the auditor only reads it.

The auditor runs under `codex --sandbox read-only` (D012) so the kernel — not
a prompt — guarantees it cannot mutate the repo. The cost is that it can
`--collect-only` but never *execute*: five consecutive audits on plan
2026-08-13-001 reported "no executed regression evidence … this read-only
environment could collect but not execute tests because no writable temporary
directory exists". Nothing else in the harness ran tests either, so a feature
could sign off with zero executed proof.

The fix keeps D012 intact. The supervisor — the trusted host process, already
the thing that writes plan artifacts — runs the plan-declared verification
command between the implementer and the auditor, persists raw output under
`evidence/`, and hands the auditor a path plus a tail to judge.

That makes the supervisor an executor of plan-declared commands, so these
tests pin the safety properties as hard as the behavioural ones:

  * a plan with no `verification` block runs nothing (opt-in, never implicit);
  * the command goes through `command_guard` first, and a rejected command
    runs nothing at all;
  * a failing command is reported honestly, not swallowed — a red suite must
    reach the auditor as red;
  * the evidence file is always written when a command ran, including on
    failure and on timeout, because "the runner crashed" and "the tests
    failed" must not look the same downstream.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from dontpanic_orchestrate import verification_runner as vr


def _plan_dir(tmp_path: Path) -> Path:
    (tmp_path / "evidence").mkdir(parents=True, exist_ok=True)
    return tmp_path


class TestSpecParsing:
    """`verification` is optional. Absent means: run nothing."""

    def test_absent_block_yields_no_spec(self):
        assert vr.spec_from_plan({"id": "p"}) is None

    def test_empty_block_yields_no_spec(self):
        assert vr.spec_from_plan({"verification": {}}) is None

    def test_command_is_required_for_a_spec(self):
        assert vr.spec_from_plan({"verification": {"cwd": "."}}) is None

    def test_spec_carries_command_and_default_cwd(self):
        spec = vr.spec_from_plan({"verification": {"command": "pytest -q"}})
        assert spec is not None
        assert spec.command == "pytest -q"
        assert spec.cwd == "."

    def test_explicit_cwd_is_preserved(self):
        spec = vr.spec_from_plan({"verification": {"command": "pytest -q", "cwd": "scripts"}})
        assert spec is not None and spec.cwd == "scripts"

    def test_accepts_a_pydantic_style_object(self):
        """plan_loader hands back a model, not a dict."""

        class _V:
            command = "pytest -q"
            cwd = "scripts"

        class _Plan:
            verification = _V()

        spec = vr.spec_from_plan(_Plan())
        assert spec is not None and spec.command == "pytest -q" and spec.cwd == "scripts"


class TestGuardIsCheckedBeforeExecution:
    """The supervisor must never run a plan-declared command unguarded."""

    def test_rejected_command_does_not_execute(self, tmp_path):
        plan_dir = _plan_dir(tmp_path)
        canary = tmp_path / "canary.txt"
        spec = vr.VerificationSpec(command=f"firebase use prod && touch {canary}", cwd=".")

        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )

        assert result.status == "refused", result
        assert result.exit_code is None, "a refused command has no exit code — it never ran"
        assert not canary.exists(), "guard-rejected command still executed"
        assert "firebase use" in (result.reason or "")

    def test_refusal_is_still_recorded_as_evidence(self, tmp_path):
        """A refusal is a fact about the run; it must not vanish silently."""
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(command="firebase use prod", cwd=".")
        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )
        assert result.output_path is not None and result.output_path.is_file()
        assert "refused" in result.output_path.read_text().lower()


class TestExecution:
    def test_passing_command_reports_passed_and_persists_output(self, tmp_path):
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(
            command=f'{sys.executable} -c "print(\'42 passed\')"', cwd="."
        )
        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )

        assert result.status == "passed"
        assert result.exit_code == 0
        assert result.output_path == plan_dir / "evidence" / "regression-0-implementer.txt"
        assert "42 passed" in result.output_path.read_text()
        assert "42 passed" in result.tail

    def test_failing_command_reports_failed_not_passed(self, tmp_path):
        """A red suite must reach the auditor as red."""
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(
            command=f'{sys.executable} -c "import sys; print(\'1 failed\'); sys.exit(1)"',
            cwd=".",
        )
        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )

        assert result.status == "failed"
        assert result.exit_code == 1
        assert "1 failed" in result.output_path.read_text()

    def test_stderr_is_captured_too(self, tmp_path):
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(
            command=f'{sys.executable} -c "import sys; sys.stderr.write(\'boom\\n\')"', cwd="."
        )
        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )
        assert "boom" in result.output_path.read_text()

    def test_timeout_is_its_own_status(self, tmp_path):
        """'timed out' and 'tests failed' are different facts."""
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(
            command=f'{sys.executable} -c "import time; time.sleep(30)"', cwd="."
        )
        result = vr.run_verification(
            plan_dir,
            spec,
            iteration=0,
            repo_root=tmp_path,
            role="implementer",
            timeout_seconds=1,
        )
        assert result.status == "timed_out"
        assert result.output_path is not None and result.output_path.is_file()

    def test_missing_binary_is_an_error_not_a_failure(self, tmp_path):
        """'could not run' must not be reported as 'the tests failed'."""
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(command="definitely-not-a-real-binary-xyz --version", cwd=".")
        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )
        assert result.status == "error", result
        assert result.status != "failed"

    def test_cwd_is_resolved_against_repo_root(self, tmp_path):
        plan_dir = _plan_dir(tmp_path)
        sub = tmp_path / "scripts"
        sub.mkdir()
        spec = vr.VerificationSpec(
            command=f'{sys.executable} -c "import os; print(os.getcwd())"', cwd="scripts"
        )
        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )
        assert str(sub.resolve()) in result.output_path.read_text()

    def test_cwd_escaping_the_repo_is_refused(self, tmp_path):
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(command="echo hi", cwd="../../etc")
        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )
        assert result.status == "refused"
        assert "outside" in (result.reason or "").lower()


class TestEvidenceNaming:
    def test_iterations_and_roles_do_not_collide(self, tmp_path):
        """One file per (iteration, role) — later rounds must not erase earlier ones."""
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(command=f'{sys.executable} -c "print(1)"', cwd=".")
        for i in (0, 1):
            vr.run_verification(
                plan_dir, spec, iteration=i, repo_root=tmp_path, role="implementer"
            )
        names = sorted(p.name for p in (plan_dir / "evidence").glob("regression-*.txt"))
        assert names == ["regression-0-implementer.txt", "regression-1-implementer.txt"]


class TestAuditorContextBlock:
    """What the auditor is handed. It reads this; it never runs anything."""

    def test_block_names_command_status_and_path(self, tmp_path):
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(command=f'{sys.executable} -c "print(\'ok\')"', cwd=".")
        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )
        block = vr.render_context_block(result)
        assert spec.command in block
        assert "passed" in block
        assert result.output_path.name in block

    def test_no_run_says_so_explicitly(self):
        """Silence would read as 'it passed'. It must read as 'nothing ran'."""
        block = vr.render_context_block(None)
        assert block.strip(), "an absent run must still produce a statement"
        low = block.lower()
        assert "no verification" in low or "not declared" in low
        assert "passed" not in low

    def test_failure_block_does_not_bury_the_verdict(self, tmp_path):
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(
            command=f'{sys.executable} -c "import sys; sys.exit(1)"', cwd="."
        )
        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )
        block = vr.render_context_block(result)
        assert "failed" in block.lower()

    def test_tail_is_bounded(self, tmp_path):
        """A 200k-line suite must not be pasted into the auditor prompt."""
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(
            command=f"{sys.executable} -c \"print('noise ' * 12 + chr(10), end='')\" ", cwd="."
        )
        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )
        assert len(vr.render_context_block(result)) < 8000


class TestSidecar:
    """A machine-readable record, so downstream consumers don't parse prose."""

    def test_sidecar_records_the_run(self, tmp_path):
        plan_dir = _plan_dir(tmp_path)
        spec = vr.VerificationSpec(command=f'{sys.executable} -c "print(1)"', cwd=".")
        result = vr.run_verification(
            plan_dir, spec, iteration=0, repo_root=tmp_path, role="implementer"
        )
        sidecar = plan_dir / "evidence" / "regression-0-implementer.json"
        assert sidecar.is_file()
        data = json.loads(sidecar.read_text())
        assert data["status"] == "passed"
        assert data["exit_code"] == 0
        assert data["command"] == spec.command
        assert data["iteration"] == 0


class TestSupervisorWiring:
    """The seam is only worth anything if the volley actually calls it."""

    def test_supervisor_runs_verification_before_the_auditor_prompt(self):
        """Order matters: the auditor must be handed a result, not asked to wait."""
        import inspect

        from dontpanic_orchestrate import supervisor

        src = inspect.getsource(supervisor.dispatch_volley)
        run_at = src.find("verification_runner.run_verification")
        block_at = src.find("verification_block=verification_runner.render_context_block")
        auditor_at = src.find('role="auditor"')
        assert run_at != -1, "dispatch_volley never runs the verification"
        assert block_at != -1, "the auditor prompt never receives the result"
        assert run_at < auditor_at, "verification must run BEFORE the auditor round"

    def test_auditor_prompt_carries_the_block_and_disclaims_execution(self):
        from pathlib import Path as _P

        from dontpanic_orchestrate import prompts

        text = prompts.auditor_prompt(
            plan_id="2026-08-15-001-feat-x",
            plan_dir=_P("/tmp/plan"),
            feature={"id": "F001", "acceptance": "does the thing", "steps": []},
            iteration=0,
            implementer_audit_path=_P("/tmp/plan/audit/impl.json"),
            verification_block=vr.render_context_block(None),
        )
        assert "No verification command is declared" in text
        assert "read-only" in text, "the auditor must be told it cannot execute tests"

    def test_plan_model_round_trips_the_block(self):
        """spec_from_plan must read the real Pydantic Plan, not just a dict."""
        import sys as _sys
        from pathlib import Path as _P

        schemas = _P(__file__).resolve().parents[3] / "claude" / "shared" / "schemas" / "v1.0"
        _sys.path.insert(0, str(schemas / "models"))
        from plan_model import Plan  # noqa: PLC0415

        plan = Plan.model_validate(
            {
                "id": "2026-08-15-001-feat-x",
                "title": "t",
                "type": "feat",
                "tier": "local",
                "status": "draft",
                "date": "2026-08-15",
                "description": "a description long enough",
                "verification": {"command": "pytest -q", "cwd": "scripts"},
            }
        )
        spec = vr.spec_from_plan(plan)
        assert spec is not None
        assert spec.command == "pytest -q" and spec.cwd == "scripts"
