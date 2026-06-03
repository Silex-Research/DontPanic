"""Plan 2026-06-02-002 F002 — first-class operator-finish close path.

`dontpanic close --operator-resolved --reason <terminal-class>` accepts honest
terminal classes beyond stopped_no_progress — signed_off_adjacent (auditor
signed off but a downstream gate blocked the automated finalize), staging_blocked
(a recorded downstream-gate block), and operator_verified (operator rationale) —
and closes them with an accurate signoff_reason instead of a stopped_no_progress
pretence. The close path performs no paid agent dispatch.

Acceptance coverage map (features.json F002):
  (1) ANTI-BYPASS: signed_off_adjacent REFUSES unless the latest auditor verdict
      is actually signed_off                              → TestAntiBypass
  (2) signed_off_adjacent closes WITHOUT breaker:no_progress + not recorded as
      stopped_no_progress                                 → TestSignedOffAdjacent
  (3) staging_blocked requires recorded gate evidence; operator_verified records
      rationale                                           → TestStagingBlocked / TestOperatorVerified
  (4) signoff_reason + memo name the ACTUAL terminal class, never no-progress
                                                          → TestHonestSignoffReason
  (5) close path invokes no executor (no paid dispatch)   → TestNoPaidDispatch
  (6) existing stopped_no_progress close behavior unchanged → TestNoProgressCloseUnchanged

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f002_operator_finish_close.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import circuit_breakers, cli, closeout, gate_pause  # noqa: E402

# ────────────────────────────  fixtures  ────────────────────────────

_PLAN_TEMPLATE = """---
id: {plan_id}
title: Synthetic plan for F002 operator-finish close
type: infra
tier: trivial
status: active
date: "2026-06-02"
description: Synthetic plan for plan 2026-06-02-002 F002 operator-finish close tests.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 3
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# Synthetic F002 plan

## Target

```yaml
target_env: dev
target_project: none
```
"""


def _make_plan(repo: Path, plan_id: str, feature_ids: list[str] | None = None) -> Path:
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    feature_ids = feature_ids or ["F001"]
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": fid,
                "category": "infra",
                "phase": 0,
                "description": "Synthetic feature exercising F002 operator-finish close.",
                "steps": ["scripted"],
                "acceptance": "close --operator-resolved --reason <terminal> succeeds.",
                "passes": False,
                "depends_on": [],
            }
            for fid in feature_ids
        ],
    }
    (plan_dir / "plan.md").write_text(_PLAN_TEMPLATE.format(plan_id=plan_id))
    (plan_dir / "features.json").write_text(
        json.dumps(features, indent=2, ensure_ascii=False) + "\n"
    )
    return plan_dir


def _write_audit_envelope(
    plan_dir: Path,
    *,
    vendor: str = "codex",
    role: str = "auditor",
    feature_id: str = "F001",
    iteration: int = 0,
    audit_status: str,
    findings: list[dict] | None = None,
    summary: str = "synthetic auditor envelope",
) -> Path:
    audit_dir = plan_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{vendor}-{role}-{feature_id}-i{iteration}.json"
    path.write_text(
        json.dumps(
            {
                "task_id": plan_dir.name,
                "audit_id": f"{plan_dir.name}#{vendor}#{iteration}",
                "agent": vendor,
                "agent_role": role,
                "iteration": iteration,
                "started_at": "2026-06-02T00:00:00Z",
                "completed_at": "2026-06-02T00:00:00Z",
                "audit_status": audit_status,
                "validation_performed": [f"reviewed i{iteration}"],
                "summary": summary,
                "findings": findings or [],
                "quota_consumed": {"api_calls": 1},
            },
            indent=2,
        )
        + "\n"
    )
    return path


def _write_round(plan_dir: Path, *, auditor_status: str, feature_id: str = "F001") -> None:
    """Write a minimal implementer + auditor envelope pair so the close path has
    audit history to cite."""
    _write_audit_envelope(
        plan_dir, vendor="claude", role="implementer", feature_id=feature_id,
        iteration=0, audit_status="signed_off", summary="impl",
    )
    _write_audit_envelope(
        plan_dir, vendor="codex", role="auditor", feature_id=feature_id,
        iteration=0, audit_status=auditor_status,
        findings=[] if auditor_status == "signed_off" else [
            {"severity": "high", "category": "correctness",
             "issue": "blocking finding still open", "evidence": "e"}
        ],
    )


def _write_patch_completeness_fail(plan_dir: Path, *, iteration: int = 0) -> Path:
    """Record a downstream-gate block: a patch-completeness artifact with
    status 'fail' (an untracked module would import-fail on a fresh clone)."""
    audit_dir = plan_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    out = audit_dir / f"patch-completeness-{iteration}.json"
    out.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "fail",
                "findings": [
                    {
                        "mode": "source_imports_untracked_module",
                        "path": "scripts/dontpanic_orchestrate/plan_review/sizing_gate.py",
                        "reason": "untracked module imported by a changed file",
                    }
                ],
                "files": ["scripts/dontpanic_orchestrate/plan_review/sizing_gate.py"],
            },
            indent=2,
        )
        + "\n"
    )
    return out


_PANEL = ["claude", "codex"]


# ────────────────────────────  (1) anti-bypass  ────────────────────────────


class TestAntiBypass:
    def test_signed_off_adjacent_refuses_when_latest_verdict_needs_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_plan(Path(td), "2026-06-02-002-fixture-antibypass")
            _write_round(plan_dir, auditor_status="needs_changes")
            with pytest.raises(closeout.CloseoutError) as exc:
                closeout.run_operator_finish(
                    plan_dir=plan_dir,
                    plan_id=plan_dir.name,
                    feature_id="F001",
                    terminal_class="signed_off_adjacent",
                    tier="trivial",
                    agents_in_panel=_PANEL,
                )
            assert "signed_off" in str(exc.value).lower()
            # Nothing committed: features.json untouched, no signoff envelope.
            data = json.loads((plan_dir / "features.json").read_text())
            assert data["features"][0]["passes"] is False
            assert not (plan_dir / "audit" / f"signoff-{plan_dir.name}.json").exists()

    def test_cli_refuses_signed_off_adjacent_on_needs_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan_dir = _make_plan(repo, "2026-06-02-002-infra-fixture-antibypass-cli")
            _write_round(plan_dir, auditor_status="needs_changes")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = cli.main(
                    ["close", "--operator-resolved", str(plan_dir), "F001",
                     "--reason", "signed_off_adjacent"]
                )
            assert rc != 0, f"CLI must refuse; stdout={out.getvalue()}"
            assert "signed_off" in err.getvalue().lower()


# ────────────────────────────  (2) signed_off_adjacent close  ────────────────────────────


class TestSignedOffAdjacent:
    def test_closes_without_breaker_and_not_as_no_progress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_plan(Path(td), "2026-06-02-002-fixture-soa")
            _write_round(plan_dir, auditor_status="signed_off")
            # No breaker:no_progress active.
            assert circuit_breakers.gate_name(
                circuit_breakers.BreakerKind.NO_PROGRESS
            ) not in set(gate_pause.active_breakers(plan_dir))

            result = closeout.run_operator_finish(
                plan_dir=plan_dir,
                plan_id=plan_dir.name,
                feature_id="F001",
                terminal_class="signed_off_adjacent",
                tier="trivial",
                agents_in_panel=_PANEL,
            )
            # features flipped, signoff written.
            data = json.loads((plan_dir / "features.json").read_text())
            assert data["features"][0]["passes"] is True
            signoff = json.loads(result.signoff_path.read_text())
            reason = signoff.get("signoff_reason") or ""
            assert "signed_off_adjacent" in reason
            assert "no_progress" not in reason.lower()
            assert "no-progress" not in reason.lower()


# ────────────────────────────  (3) staging_blocked / operator_verified evidence  ───────────


class TestStagingBlocked:
    def test_requires_recorded_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_plan(Path(td), "2026-06-02-002-fixture-staging-noev")
            _write_round(plan_dir, auditor_status="needs_changes")
            # No patch-completeness fail artifact present → refuse.
            with pytest.raises(closeout.CloseoutError) as exc:
                closeout.run_operator_finish(
                    plan_dir=plan_dir, plan_id=plan_dir.name, feature_id="F001",
                    terminal_class="staging_blocked", tier="trivial",
                    agents_in_panel=_PANEL,
                )
            assert "evidence" in str(exc.value).lower() or "gate" in str(exc.value).lower()

    def test_closes_with_recorded_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_plan(Path(td), "2026-06-02-002-fixture-staging-ok")
            _write_round(plan_dir, auditor_status="needs_changes")
            _write_patch_completeness_fail(plan_dir)
            result = closeout.run_operator_finish(
                plan_dir=plan_dir, plan_id=plan_dir.name, feature_id="F001",
                terminal_class="staging_blocked", tier="trivial",
                agents_in_panel=_PANEL,
            )
            signoff = json.loads(result.signoff_path.read_text())
            assert "staging_blocked" in (signoff.get("signoff_reason") or "")


class TestOperatorVerified:
    def test_requires_rationale_note(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_plan(Path(td), "2026-06-02-002-fixture-opver-nonote")
            _write_round(plan_dir, auditor_status="needs_changes")
            with pytest.raises(closeout.CloseoutError) as exc:
                closeout.run_operator_finish(
                    plan_dir=plan_dir, plan_id=plan_dir.name, feature_id="F001",
                    terminal_class="operator_verified", tier="trivial",
                    agents_in_panel=_PANEL, note=None,
                )
            assert "note" in str(exc.value).lower() or "rationale" in str(exc.value).lower()

    def test_records_rationale_in_sidecar_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_plan(Path(td), "2026-06-02-002-fixture-opver-ok")
            _write_round(plan_dir, auditor_status="needs_changes")
            note = "ran the suite locally; the finding is a fixture artifact, behavior correct"
            result = closeout.run_operator_finish(
                plan_dir=plan_dir, plan_id=plan_dir.name, feature_id="F001",
                terminal_class="operator_verified", tier="trivial",
                agents_in_panel=_PANEL, note=note,
            )
            signoff = json.loads(result.signoff_path.read_text())
            assert "operator_verified" in (signoff.get("signoff_reason") or "")
            sidecar = json.loads(
                closeout.operator_resolution_path(plan_dir, plan_dir.name).read_text()
            )
            assert sidecar.get("note") == note
            assert sidecar.get("class") == "operator_verified"


# ────────────────────────────  (4) honest signoff_reason  ────────────────────────────


class TestHonestSignoffReason:
    def test_memo_and_reason_name_terminal_class_not_no_progress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_plan(Path(td), "2026-06-02-002-fixture-honest")
            _write_round(plan_dir, auditor_status="signed_off")
            result = closeout.run_operator_finish(
                plan_dir=plan_dir, plan_id=plan_dir.name, feature_id="F001",
                terminal_class="signed_off_adjacent", tier="trivial",
                agents_in_panel=_PANEL,
            )
            memo = result.memo_path.read_text()
            assert "signed_off_adjacent" in memo
            assert "stopped_no_progress" not in memo
            assert "breaker:no_progress" not in memo


# ────────────────────────────  (5) no paid dispatch  ────────────────────────────


class TestNoPaidDispatch:
    def test_close_invokes_no_executor(self, monkeypatch) -> None:
        from dontpanic_orchestrate.executors.base import BaseExecutor

        def _boom(self, task):  # type: ignore[no-untyped-def]
            raise AssertionError("operator-finish close must not dispatch a paid agent")

        monkeypatch.setattr(BaseExecutor, "dispatch", _boom)
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_plan(Path(td), "2026-06-02-002-fixture-nodispatch")
            _write_round(plan_dir, auditor_status="signed_off")
            result = closeout.run_operator_finish(
                plan_dir=plan_dir, plan_id=plan_dir.name, feature_id="F001",
                terminal_class="signed_off_adjacent", tier="trivial",
                agents_in_panel=_PANEL,
            )
            assert result.features_passes_flipped is True


# ────────────────────────────  (6) existing path unchanged  ────────────────────────────


class TestNoProgressCloseUnchanged:
    def test_existing_no_progress_close_still_names_no_progress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan_dir = _make_plan(Path(td), "2026-06-02-002-fixture-legacy")
            _write_round(plan_dir, auditor_status="needs_changes")
            # Activate breaker:no_progress as the legacy path requires.
            gate_pause.add_breaker(
                plan_dir,
                circuit_breakers.gate_name(circuit_breakers.BreakerKind.NO_PROGRESS),
                plan_id=plan_dir.name,
                reason="synthetic",
            )
            result = closeout.run_close_out(
                plan_dir=plan_dir, plan_id=plan_dir.name, feature_id="F001",
                reason_class="spec_ambiguity", tier="trivial", agents_in_panel=_PANEL,
            )
            signoff = json.loads(result.signoff_path.read_text())
            assert "stopped_no_progress" in (signoff.get("signoff_reason") or "")
            assert result.breaker_cleared is True
