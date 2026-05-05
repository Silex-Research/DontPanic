"""Plan 2026-05-04-003 F002 — timeout evidence in audit envelopes.

Schema discipline tested here:

- ``audit_status`` stays ``blocked`` for timeouts (D002 — no new enum value).
- No new top-level audit JSON fields (D004 — ``additionalProperties: false``).
- Sidecar partials live under ``audit/partials/<audit_id>.{stdout,stderr}.{txt,bin}``,
  referenced only via ``validation_performed`` markers.
- Findings use existing ``correctness`` category (D007 — no new category enum).
- Non-timeout cases are byte-stable (AC #11).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from dontpanic_orchestrate import audit_writer
from dontpanic_orchestrate.executors.base import DispatchResult
from dontpanic_orchestrate.plan_loader import LoadedPlan

# ───────────────────────────  fixtures + builders  ───────────────────────────


@dataclass
class _StubSubprocessResult:
    """Lightweight stand-in for ``subprocess_runner.SubprocessResult``.

    Plan B's test isolation discipline applies: avoid importing the real
    runner module here so the F002 tests don't get caught up in F001's
    import-time effects under different pytest collection orders.
    """

    timed_out: bool
    timeout_seconds: int = 600
    grace_period_used: bool = False
    captured_stdout_bytes: int = 0
    captured_stderr_bytes: int = 0
    stdout: bytes = b""
    stderr: bytes = b""
    worktree_changed: bool | None = None
    env_markers: list[str] = field(default_factory=list)
    exit_code: int | None = None
    pgid: int = 0


def _make_loaded(plan_dir: Path, plan_id: str = "2026-05-04-003-test-plan") -> LoadedPlan:
    """Construct a minimal LoadedPlan stub.

    The audit_writer only reads ``plan_id`` and ``plan_dir`` from the loaded
    plan, so a sparse stub suffices.
    """
    plan_dir.mkdir(parents=True, exist_ok=True)
    return LoadedPlan(
        plan_dir=plan_dir,
        plan_id=plan_id,
        plan=None,
        features=None,
        schemas_dir=None,
        target_env="dev",
        target_project=None,
        orchestration=None,
        child_charter=None,
        commit_policy=None,
    )


def _make_result(
    *,
    success: bool = False,
    summary: str = "",
    error: str | None = None,
    subprocess_result: _StubSubprocessResult | None = None,
    agent: str = "claude",
    role: str = "implementer",
    iteration: int = 0,
) -> DispatchResult:
    return DispatchResult(
        agent=agent,
        agent_role=role,
        iteration=iteration,
        started_at="2026-05-04T00:00:00Z",
        completed_at="2026-05-04T00:10:00Z",
        success=success,
        summary=summary,
        model_version="test-model-v1",
        raw_response=summary,
        error=error,
        quota_consumed={},
        subprocess_result=subprocess_result,
    )


def _validation_performed_baseline() -> list[str]:
    """The supervisor's typical caller-side markers — kept stable so timeout
    markers can be asserted as APPENDED rather than replacing the list."""
    return [
        "claude dispatch (binary=claude)",
        "captured stdout 0 bytes",
        "subprocess exit nonzero",
    ]


# ───────────────────  AC #1 / #11 — schema validity & byte stability  ──────


class TestSchemaValidityAndByteStability:
    def test_timeout_envelope_validates_against_schema(self, tmp_path):
        """Plan C AC #1: timeout envelope round-trips through Audit schema."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(
            timed_out=True,
            captured_stdout_bytes=128,
            captured_stderr_bytes=16,
            stdout=b"partial agent output",
            stderr=b"error tail",
            worktree_changed=True,
            grace_period_used=True,
        )
        result = _make_result(
            success=False,
            error="TimeoutExpired: Command timed out after 600 seconds",
            subprocess_result=spr,
        )
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        path = audit_writer.write(audit, loaded.plan_dir, feature_id="F001")
        # write() validates against Audit.model_validate; reaching this line
        # means schema acceptance.
        assert path.exists()
        persisted = json.loads(path.read_text())
        # AC #1: audit_status enum stays `blocked` for timeouts (D002).
        assert persisted["audit_status"] == "blocked"
        # AC #10: no new top-level fields beyond what the schema declares.
        # ``additionalProperties: false`` means the schema validator would have
        # rejected any sneaky additions — just spot-check a few we explicitly
        # forbade.
        for forbidden in ("partial_stdout_path", "partial_stderr_path", "timeout_evidence"):
            assert forbidden not in persisted

    def test_non_timeout_failure_is_byte_stable(self, tmp_path):
        """AC #11: non-timeout failures have unchanged envelope shape."""
        loaded = _make_loaded(tmp_path / "plan")
        # Non-timeout failure (e.g., binary not found, auth error) — the
        # subprocess_result either is None or has timed_out=False.
        result = _make_result(
            success=False,
            error="binary not found",
            subprocess_result=None,
        )
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        # Validation_performed should be exactly the baseline — no timeout
        # markers slipped in.
        assert audit["validation_performed"] == _validation_performed_baseline()
        # Summary should be the bare DISPATCH FAILED line (after prelude
        # injection during write(), which is tested separately in
        # test_audit_writer_normalize.py).
        assert "DISPATCH TIMED OUT" not in audit["summary"]
        assert "DISPATCH FAILED" in audit["summary"]
        # No timeout finding emitted.
        for finding in audit.get("findings") or []:
            assert finding.get("category") != "correctness" or "timed out" not in finding.get(
                "issue", ""
            )

    def test_subprocess_result_with_timed_out_false_is_byte_stable(self, tmp_path):
        """AC #11: a SubprocessResult with timed_out=False is also a no-op."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(
            timed_out=False,
            exit_code=1,
            captured_stdout_bytes=42,
            stdout=b"some non-timeout output",
        )
        result = _make_result(
            success=False,
            error="non-zero exit",
            subprocess_result=spr,
        )
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        assert audit["validation_performed"] == _validation_performed_baseline()
        assert "DISPATCH TIMED OUT" not in audit["summary"]
        # No sidecar files written.
        partials = loaded.plan_dir / "audit" / "partials"
        assert not partials.exists()

    def test_successful_run_is_byte_stable(self, tmp_path):
        """AC #11: a normal success envelope is unchanged."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(
            timed_out=False,
            exit_code=0,
            captured_stdout_bytes=2048,
        )
        result = _make_result(
            success=True,
            summary="Repo: DontPanic\nEnv: dev\nProject: (none)\nAll good.",
            subprocess_result=spr,
        )
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        assert audit["validation_performed"] == _validation_performed_baseline()
        # No partial sidecar dir created.
        assert not (loaded.plan_dir / "audit" / "partials").exists()


# ───────────────  AC #2 / #3 — structured summary + markers  ───────────────


class TestStructuredTimeoutSummary:
    def test_summary_replaces_bare_dispatch_failed(self, tmp_path):
        """AC #2: structured timeout block in summary, not bare error text."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(
            timed_out=True,
            timeout_seconds=600,
            captured_stdout_bytes=4321,
            captured_stderr_bytes=128,
            worktree_changed=True,
            grace_period_used=True,
        )
        result = _make_result(
            success=False,
            error="TimeoutExpired",
            subprocess_result=spr,
        )
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        summary = audit["summary"]
        # The structured block carries every observable.
        assert "DISPATCH TIMED OUT after 600s" in summary
        assert "captured stdout: 4321 bytes" in summary
        assert "captured stderr: 128 bytes" in summary
        assert "worktree changed: true" in summary
        assert "grace period used: true" in summary

    def test_summary_with_env_markers(self, tmp_path):
        """The structured block surfaces env-fallback markers when F001 reports them."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(
            timed_out=True,
            env_markers=[
                "env_invalid: DONTPANIC_SUBPROCESS_TIMEOUT_SECONDS=foo, fell back to 600",
            ],
        )
        result = _make_result(success=False, error="timeout", subprocess_result=spr)
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        assert "env fallbacks:" in audit["summary"]
        assert "DONTPANIC_SUBPROCESS_TIMEOUT_SECONDS=foo" in audit["summary"]


class TestValidationPerformedMarkers:
    @pytest.mark.parametrize(
        "worktree_changed,expected",
        [
            (True, "worktree_changed=true"),
            (False, "worktree_changed=false"),
            (None, "worktree_changed=unknown"),
        ],
    )
    def test_worktree_marker_renders_ternary(self, tmp_path, worktree_changed, expected):
        """AC #3: ``worktree_changed`` marker is true/false/unknown."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(timed_out=True, worktree_changed=worktree_changed)
        result = _make_result(success=False, error="timeout", subprocess_result=spr)
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        assert expected in audit["validation_performed"]

    def test_all_required_timeout_markers_present(self, tmp_path):
        """AC #3: every required marker fires when subprocess timed out."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(
            timed_out=True,
            timeout_seconds=900,
            captured_stdout_bytes=1024,
            captured_stderr_bytes=64,
            worktree_changed=False,
            grace_period_used=False,
        )
        result = _make_result(success=False, error="timeout", subprocess_result=spr)
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        vp = audit["validation_performed"]
        assert "subprocess_timeout_seconds=900" in vp
        assert "timeout_stdout_bytes=1024" in vp
        assert "timeout_stderr_bytes=64" in vp
        assert "worktree_changed=false" in vp
        assert "grace_period_used=false" in vp

    def test_baseline_markers_preserved_before_timeout_markers(self, tmp_path):
        """Caller-supplied validation_performed entries come first; timeout
        markers are APPENDED, not replacing."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(timed_out=True, worktree_changed=True)
        result = _make_result(success=False, error="timeout", subprocess_result=spr)
        baseline = _validation_performed_baseline()
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=baseline,
            target_context={"env": "dev", "project": None},
        )
        # First N entries == baseline (in order)
        for i, marker in enumerate(baseline):
            assert audit["validation_performed"][i] == marker
        # Timeout markers appended after
        assert "subprocess_timeout_seconds=600" in audit["validation_performed"][len(baseline) :]


# ─────────────  AC #4 — env-var fallback markers surfaced  ─────────────


class TestEnvFallbackMarkers:
    def test_env_invalid_marker_surfaces_in_validation_performed(self, tmp_path):
        """AC #4: F001's ``env_markers`` flow through to ``validation_performed``."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(
            timed_out=True,
            env_markers=[
                "env_invalid: DONTPANIC_SUBPROCESS_TIMEOUT_SECONDS=foo, fell back to 600",
                "env_invalid: DONTPANIC_SUBPROCESS_GRACE_SECONDS=999 "
                "(out of range [1,120]), fell back to 15",
            ],
        )
        result = _make_result(success=False, error="timeout", subprocess_result=spr)
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        vp = audit["validation_performed"]
        assert any("DONTPANIC_SUBPROCESS_TIMEOUT_SECONDS=foo" in m for m in vp)
        assert any("DONTPANIC_SUBPROCESS_GRACE_SECONDS=999" in m for m in vp)


# ──────  AC #5 / #6 — finding emitted iff timed_out + worktree_changed=true  ──


class TestTimeoutFinding:
    def test_finding_emitted_when_timeout_and_worktree_changed(self, tmp_path):
        """AC #5: structured ``correctness/medium`` finding fires."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(
            timed_out=True,
            timeout_seconds=600,
            captured_stdout_bytes=2048,
            worktree_changed=True,
        )
        result = _make_result(success=False, error="timeout", subprocess_result=spr)
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        timeout_findings = [
            f for f in audit.get("findings") or [] if "timed out" in f.get("issue", "").lower()
        ]
        assert len(timeout_findings) == 1
        finding = timeout_findings[0]
        # Severity + category locked per D007.
        assert finding["severity"] == "medium"
        assert finding["category"] == "correctness"
        assert finding["feature_id"] == "F001"
        # Issue text mentions both timeout and worktree changes.
        assert "timed out" in finding["issue"]
        assert "worktree" in finding["issue"]
        # Evidence carries observable counters.
        assert "600s" in finding["evidence"]
        assert "2048" in finding["evidence"]

    @pytest.mark.parametrize("worktree_state", [False, None])
    def test_finding_NOT_emitted_when_timeout_but_no_worktree_change(
        self, tmp_path, worktree_state
    ):
        """AC #6: no false-positive finding when worktree did NOT change OR
        when worktree status is unknown (non-git cwd, git error)."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(
            timed_out=True,
            captured_stdout_bytes=512,
            worktree_changed=worktree_state,
        )
        result = _make_result(success=False, error="timeout", subprocess_result=spr)
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        timeout_findings = [
            f
            for f in audit.get("findings") or []
            if "timed out" in f.get("issue", "").lower()
            and "worktree" in f.get("issue", "").lower()
        ]
        assert timeout_findings == []

    def test_finding_NOT_emitted_when_no_timeout(self, tmp_path):
        """AC #6: no finding for non-timeout dispatches."""
        loaded = _make_loaded(tmp_path / "plan")
        spr = _StubSubprocessResult(
            timed_out=False,
            exit_code=0,
            worktree_changed=True,  # work landed but didn't time out — fine
        )
        result = _make_result(
            success=True,
            summary="all good",
            subprocess_result=spr,
        )
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        timeout_findings = [
            f for f in audit.get("findings") or [] if "timed out" in f.get("issue", "").lower()
        ]
        assert timeout_findings == []


# ─────────  AC #7 / #8 / #9 — sidecar partials under audit/partials/  ─────


class TestSidecarPartials:
    def test_stdout_sidecar_written_when_bytes_captured(self, tmp_path):
        """AC #7: sidecar at ``audit/partials/<audit_id>.stdout.txt``,
        referenced from ``validation_performed`` only (not as audit JSON field)."""
        loaded = _make_loaded(tmp_path / "plan", plan_id="2026-05-04-003-sidecar-test")
        spr = _StubSubprocessResult(
            timed_out=True,
            captured_stdout_bytes=42,
            stdout=b"partial output captured before kill\n",
            captured_stderr_bytes=0,
            worktree_changed=True,
        )
        result = _make_result(success=False, error="timeout", subprocess_result=spr)
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        # Audit ID is "<plan_id>#<agent>#<iter>", e.g. "2026-...#claude#0".
        audit_id = audit["audit_id"]
        safe_id = audit_id.replace("/", "_")
        sidecar = loaded.plan_dir / "audit" / "partials" / f"{safe_id}.stdout.txt"
        assert sidecar.exists(), f"sidecar not at {sidecar}"
        assert sidecar.read_text() == "partial output captured before kill\n"
        # Reference appears in validation_performed.
        assert any(
            f"partial_stdout_path=audit/partials/{safe_id}.stdout.txt" == m
            for m in audit["validation_performed"]
        )
        # NOT a top-level audit JSON field.
        assert "partial_stdout_path" not in audit
        assert "partial_stderr_path" not in audit

    def test_no_sidecar_when_no_bytes_captured(self, tmp_path):
        """AC #8: zero captured bytes → no sidecar file, no marker."""
        loaded = _make_loaded(tmp_path / "plan", plan_id="2026-05-04-003-empty-test")
        spr = _StubSubprocessResult(
            timed_out=True,
            captured_stdout_bytes=0,
            captured_stderr_bytes=0,
            worktree_changed=False,
        )
        result = _make_result(success=False, error="timeout", subprocess_result=spr)
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        # No partials dir created at all when no bytes captured.
        assert not (loaded.plan_dir / "audit" / "partials").exists()
        for marker in audit["validation_performed"]:
            assert not marker.startswith("partial_stdout_path=")
            assert not marker.startswith("partial_stderr_path=")

    def test_undecodable_bytes_written_as_bin_with_adjusted_marker(self, tmp_path):
        """AC #9: non-UTF-8 bytes land in ``.bin`` sidecar; marker reflects path."""
        loaded = _make_loaded(tmp_path / "plan", plan_id="2026-05-04-003-bin-test")
        # Invalid UTF-8 byte sequence: lone continuation byte 0x80
        invalid_bytes = b"\x80\x81\xfe\xff binary garbage"
        spr = _StubSubprocessResult(
            timed_out=True,
            captured_stdout_bytes=len(invalid_bytes),
            stdout=invalid_bytes,
            worktree_changed=True,
        )
        result = _make_result(success=False, error="timeout", subprocess_result=spr)
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        audit_id = audit["audit_id"]
        safe_id = audit_id.replace("/", "_")
        bin_path = loaded.plan_dir / "audit" / "partials" / f"{safe_id}.stdout.bin"
        txt_path = loaded.plan_dir / "audit" / "partials" / f"{safe_id}.stdout.txt"
        assert bin_path.exists(), "bin sidecar not written"
        assert not txt_path.exists(), "txt sidecar incorrectly written for non-UTF-8 bytes"
        assert bin_path.read_bytes() == invalid_bytes
        # Marker references .bin extension.
        assert any(
            m == f"partial_stdout_path=audit/partials/{safe_id}.stdout.bin"
            for m in audit["validation_performed"]
        )

    def test_both_streams_get_independent_sidecars(self, tmp_path):
        """Stdout and stderr sidecars are independent; one stream having
        bytes doesn't force the other to write an empty file."""
        loaded = _make_loaded(tmp_path / "plan", plan_id="2026-05-04-003-both")
        spr = _StubSubprocessResult(
            timed_out=True,
            captured_stdout_bytes=10,
            stdout=b"stdout out",
            captured_stderr_bytes=8,
            stderr=b"stderr!!",
            worktree_changed=True,
        )
        result = _make_result(success=False, error="timeout", subprocess_result=spr)
        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id="F001",
            validation_performed=_validation_performed_baseline(),
            target_context={"env": "dev", "project": None},
        )
        audit_id = audit["audit_id"]
        safe_id = audit_id.replace("/", "_")
        partials = loaded.plan_dir / "audit" / "partials"
        assert (partials / f"{safe_id}.stdout.txt").exists()
        assert (partials / f"{safe_id}.stderr.txt").exists()
        markers = audit["validation_performed"]
        assert any(f"partial_stdout_path=audit/partials/{safe_id}.stdout.txt" == m for m in markers)
        assert any(f"partial_stderr_path=audit/partials/{safe_id}.stderr.txt" == m for m in markers)


# ──────────────  AC #12 — `circuit_breakers.py` untouched in F002  ──────────


class TestF002BoundaryDiscipline:
    def test_f002_does_not_import_circuit_breakers(self):
        """F002 acceptance #12 + D008 (preview): the F002 implementation is
        in audit_writer.py and must not pull in circuit_breakers logic.

        F003 may. F002 may not.
        """
        import dontpanic_orchestrate.audit_writer as aw_mod

        source = Path(aw_mod.__file__).read_text()
        # circuit_breakers might appear as a string literal in unrelated
        # comments; check actual import statements only.
        assert "import circuit_breakers" not in source
        assert "from dontpanic_orchestrate.circuit_breakers" not in source
        assert "from .circuit_breakers" not in source
