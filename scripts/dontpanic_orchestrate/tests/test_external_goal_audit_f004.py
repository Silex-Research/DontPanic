"""Plan 2026-07-27-001 F004 — external goal/experience audit attach (D001 B1).

Covers the operator-attached Gemini path:
  - refuse registered executors (no hand-fabricated claude/codex evidence)
  - refuse incomplete disposition arrays (cannot agree by omission)
  - write provenance=external envelopes the completion gate prefers over dispatch
  - experience-kind envelopes do not satisfy the goal gate
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import completion_dispatch as cd  # noqa: E402
from dontpanic_orchestrate import completion_gate as cg  # noqa: E402
from dontpanic_orchestrate import external_goal_audit as ega  # noqa: E402
from dontpanic_orchestrate.completion_auditor import CompletionFinding  # noqa: E402


def _finding(fid: str) -> CompletionFinding:
    return CompletionFinding(
        finding_id=fid,
        severity="high",
        gap_class="journey_gap",
        title=f"synthetic {fid}",
        narrative=f"synthetic finding {fid} for external attach tests",
        subsystem="test",
        journey="cost-topology-goal-audit",
    )


def _disp(fid: str, *, agree: bool = True) -> dict[str, Any]:
    return {
        "finding_id": fid,
        "agree": agree,
        "severity_disposition": "no_finding" if agree else "higher",
        "comment": f"test disposition for {fid}",
    }


def _refute(fid: str) -> dict[str, Any]:
    """agree=false + no_finding: the shape _experience_gate_decision reads
    as 'external auditor explicitly refuted this journey_gap finding'."""
    return {
        "finding_id": fid,
        "agree": False,
        "severity_disposition": "no_finding",
        "comment": f"refuted {fid}: journey verified in the vendor surface",
    }


def _write_plan_fixture(
    plan_dir: Path, plan_id: str, *, journey_consumer: str | None = None
) -> None:
    """Minimal on-disk plan (plan.md + features.json + contract) that the
    REAL compute/attach/backstop pipeline can run against un-mocked."""
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        f"id: {plan_id}\n"
        "title: External goal audit fixture\n"
        "type: feat\n"
        "tier: local\n"
        "status: active\n"
        'date: "2026-07-27"\n'
        "goal_type: new_feature\n"
        "description: Ten chars min for fixture plan used by external attach tests.\n"
        "agents_required: [claude]\n"
        "human_gates: []\n"
        "privacy_tier: internal\n"
        "links:\n"
        "  objective_contract: ./objective_contract.json\n"
        "---\n\n# fixture\n",
        encoding="utf-8",
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "doc",
                        "phase": 0,
                        "description": "fixture feature for external attach path tests",
                        "steps": ["step one"],
                        "acceptance": "machine checkable acceptance for fixture feature",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    journey: dict[str, Any] = {
        "name": "fixture-journey",
        "description": "fixture journey for external attach tests long enough",
        "surfaces": ["cli_human"],
        "states": ["ok"],
        "acceptance_signals": ["fixture signal long enough for schema"],
    }
    if journey_consumer is not None:
        journey["consumer"] = journey_consumer
    (plan_dir / "objective_contract.json").write_text(
        json.dumps(
            {
                "goal_type": "new_feature",
                "source_of_truth": "fixture contract for external goal audit attach tests",
                "completion_test": "fixture completion test string long enough for schema",
                "user_journeys": [journey],
                "required_evidence": [],
                "non_goals": [],
            }
        ),
        encoding="utf-8",
    )


def _evidence_root(plan_dir: Path) -> Path:
    return plan_dir / "evidence" / "goal-governance" / "post_impl"


def test_parse_incomplete_disposition_is_malformed_not_agree() -> None:
    findings = [_finding("F-1"), _finding("F-2")]
    status, disps = cd._parse_audit_response(json.dumps([_disp("F-1")]), findings)
    assert status == "dispatch_response_malformed"
    assert any("omits disposition" in (d.comment or "") for d in disps)


def test_parse_complete_disposition_can_agree() -> None:
    findings = [_finding("F-1"), _finding("F-2")]
    payload = json.dumps([_disp("F-1"), _disp("F-2")])
    status, disps = cd._parse_audit_response(payload, findings)
    assert status == "agree"
    assert {d.finding_id for d in disps} == {"F-1", "F-2"}


def test_refuse_registered_executor_as_external_vendor() -> None:
    with pytest.raises(ega.ExternalGoalAuditError, match="registered executor"):
        ega._validate_vendor("claude")
    with pytest.raises(ega.ExternalGoalAuditError, match="registered executor"):
        ega._validate_vendor("codex")
    assert ega._validate_vendor("gemini") == "gemini"


def test_bare_array_response_refused_without_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "plan.md").write_text(
        "---\n"
        "id: 2026-07-27-test-external-goal\n"
        "title: External goal audit fixture\n"
        "type: feat\n"
        "tier: local\n"
        "status: active\n"
        'date: "2026-07-27"\n'
        "goal_type: new_feature\n"
        "description: Ten chars min for fixture plan used by external attach tests.\n"
        "agents_required: [claude]\n"
        "human_gates: []\n"
        "privacy_tier: internal\n"
        "links:\n"
        "  objective_contract: ./objective_contract.json\n"
        "---\n\n# fixture\n",
        encoding="utf-8",
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": "2026-07-27-test-external-goal",
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "doc",
                        "phase": 0,
                        "description": "fixture feature for external attach path tests",
                        "steps": ["step one"],
                        "acceptance": "machine checkable acceptance for fixture feature",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (plan_dir / "objective_contract.json").write_text(
        json.dumps(
            {
                "goal_type": "new_feature",
                "source_of_truth": "fixture contract for external goal audit attach tests",
                "completion_test": "fixture completion test string long enough for schema",
                "user_journeys": [
                    {
                        "name": "fixture-journey",
                        "description": "fixture journey for external attach tests long enough",
                        "surfaces": ["cli_human"],
                        "states": ["ok"],
                        "acceptance_signals": ["fixture signal long enough for schema"],
                    }
                ],
                "required_evidence": [],
                "non_goals": [],
            }
        ),
        encoding="utf-8",
    )
    findings = [_finding("F-1")]
    monkeypatch.setattr(ega, "compute_completion_findings", lambda _p: findings)
    monkeypatch.setattr(ega, "_effective_implementer", lambda _p, _i: "claude")
    with pytest.raises(ega.ExternalGoalAuditError, match="source_fingerprint"):
        ega.attach_external_goal_audit(
            plan_dir,
            vendor="gemini",
            response_text=json.dumps([_disp("F-1")]),
            kind="goal",
        )


def test_attach_and_gate_prefers_fresh_external_goal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attached gemini envelope is selected by audit_plan over a paid dispatch."""
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "plan.md").write_text(
        "---\n"
        "id: 2026-07-27-test-external-goal\n"
        "title: External goal audit fixture\n"
        "type: feat\n"
        "tier: local\n"
        "status: active\n"
        'date: "2026-07-27"\n'
        "goal_type: new_feature\n"
        "description: Ten chars min for fixture plan used by external attach tests.\n"
        "agents_required: [claude]\n"
        "human_gates: []\n"
        "privacy_tier: internal\n"
        "links:\n"
        "  objective_contract: ./objective_contract.json\n"
        "---\n\n# fixture\n",
        encoding="utf-8",
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": "2026-07-27-test-external-goal",
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "doc",
                        "phase": 0,
                        "description": "fixture feature for external attach path tests",
                        "steps": ["step one"],
                        "acceptance": "machine checkable acceptance for fixture feature",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (plan_dir / "objective_contract.json").write_text(
        json.dumps(
            {
                "goal_type": "new_feature",
                "source_of_truth": "fixture contract for external goal audit attach tests",
                "completion_test": "fixture completion test string long enough for schema",
                "user_journeys": [
                    {
                        "name": "fixture-journey",
                        "description": "fixture journey for external attach tests long enough",
                        "surfaces": ["cli_human"],
                        "states": ["ok"],
                        "acceptance_signals": ["fixture signal long enough for schema"],
                    }
                ],
                "required_evidence": [],
                "non_goals": [],
            }
        ),
        encoding="utf-8",
    )

    findings = [_finding("F-1"), _finding("F-2")]
    monkeypatch.setattr(ega, "compute_completion_findings", lambda _p: findings)
    monkeypatch.setattr(cg, "run_completion_audit", lambda _p: findings)
    monkeypatch.setattr(cg, "compute_completion_findings", lambda _p: findings)
    monkeypatch.setattr(ega, "_effective_implementer", lambda _p, _i: "claude")

    fp = cd.external_audit_fingerprint(plan_dir, findings)
    payload = json.dumps(
        {"source_fingerprint": fp, "dispositions": [_disp("F-1"), _disp("F-2")]}
    )
    transcript = ega.attach_external_goal_audit(
        plan_dir, vendor="gemini", response_text=payload, kind="goal"
    )
    assert transcript.provenance == "external"
    assert transcript.audit_kind == "goal"
    assert transcript.status == "agree"
    # envelope_path on the transcript is sanitized for audit trails; the
    # on-disk writer still lands the real file under post_impl/audit/.
    written = list(
        (plan_dir / "evidence" / "goal-governance" / "post_impl" / "audit").glob(
            "audit-gemini-*.json"
        )
    )
    assert written, "expected audit-gemini-*.json on disk after attach"

    dispatched: list[str] = []

    def _should_not_dispatch(*_a: Any, **_k: Any) -> cd.CompletionAuditTranscript:
        dispatched.append("called")
        raise AssertionError("dispatch must not run when fresh external goal exists")

    monkeypatch.setattr(cg, "dispatch_completion_audit", _should_not_dispatch)
    monkeypatch.setattr(cg, "_should_gate_completion", lambda _d: True)
    monkeypatch.setattr(cg, "_classify", lambda _f: [])

    result = cg.audit_plan(plan_dir)
    assert dispatched == []
    assert result.audit_transcript is not None
    assert result.audit_transcript.provenance == "external"
    assert result.audit_transcript.auditor_agent == "gemini"
    assert result.blocking is False


def test_experience_envelope_does_not_satisfy_goal_selector(tmp_path: Path) -> None:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "plan.md").write_text(
        "---\n"
        "id: 2026-07-27-test-external-exp\n"
        "title: External experience audit fixture\n"
        "type: feat\n"
        "tier: local\n"
        "status: active\n"
        'date: "2026-07-27"\n'
        "goal_type: new_feature\n"
        "description: Ten chars min for fixture plan used by external attach tests.\n"
        "agents_required: [claude]\n"
        "human_gates: []\n"
        "privacy_tier: internal\n"
        "links:\n"
        "  objective_contract: ./objective_contract.json\n"
        "---\n\n# fixture\n",
        encoding="utf-8",
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": "2026-07-27-test-external-exp",
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "doc",
                        "phase": 0,
                        "description": "fixture feature for external attach path tests",
                        "steps": ["step one"],
                        "acceptance": "machine checkable acceptance for fixture feature",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (plan_dir / "objective_contract.json").write_text(
        json.dumps(
            {
                "goal_type": "new_feature",
                "source_of_truth": "fixture contract for external experience audit attach tests",
                "completion_test": "fixture completion test string long enough for schema",
                "user_journeys": [
                    {
                        "name": "fixture-journey",
                        "description": "fixture journey for external attach tests long enough",
                        "surfaces": ["cli_human"],
                        "states": ["ok"],
                        "acceptance_signals": ["fixture signal long enough for schema"],
                    }
                ],
                "required_evidence": [],
                "non_goals": [],
            }
        ),
        encoding="utf-8",
    )
    findings = [_finding("F-1"), _finding("F-2")]
    fingerprint = cd.external_audit_fingerprint(plan_dir, findings)
    audit_dir = plan_dir / "evidence" / "goal-governance" / "post_impl" / "audit"
    audit_dir.mkdir(parents=True)
    env = {
        "auditor_agent": "gemini",
        "implementer_agent": "claude",
        "status": "agree",
        "iteration": 0,
        "findings_dispositions": [
            _disp("F-1"),
            _disp("F-2"),
        ],
        "transcript_path": "x.txt",
        "envelope_path": "x.json",
        "generated_at": "2026-07-27T00:00:00Z",
        "raw_response": "[]",
        "provenance": "external",
        "audit_kind": "experience",
        "source_fingerprint": fingerprint,
    }
    path = audit_dir / "audit-gemini-0.json"
    path.write_text(json.dumps(env), encoding="utf-8")
    selected = cg._latest_fresh_external_envelope(plan_dir, kind="goal", findings=findings)
    assert selected is None
    selected_exp = cg._latest_fresh_external_envelope(
        plan_dir, kind="experience", findings=findings
    )
    assert selected_exp is not None
    assert selected_exp.audit_kind == "experience"


# ─────────────── i1 regressions: CLI no-write / pure prompt path ───────────────


def test_render_prompt_is_read_only(tmp_path: Path) -> None:
    """--show-prompt's engine must not write completion_findings.json (or
    anything else) — codex F004-i0 finding: it previously ran the writing
    run_completion_audit and crashed with PermissionError on read-only FS."""
    plan_dir = tmp_path / "plan"
    _write_plan_fixture(plan_dir, "2026-07-27-test-prompt-readonly")
    before = sorted(p for p in plan_dir.rglob("*"))
    prompt = ega.render_external_audit_prompt(plan_dir, kind="goal")
    assert prompt.strip()
    assert sorted(p for p in plan_dir.rglob("*")) == before
    assert not (_evidence_root(plan_dir) / "completion_findings.json").exists()


def test_cli_show_prompt_writes_nothing_and_refuses_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from dontpanic_orchestrate import cli

    plan_dir = tmp_path / "plan"
    _write_plan_fixture(plan_dir, "2026-07-27-test-cli-show-prompt")
    rc = cli._plan_attach_goal_audit_main([str(plan_dir), "--show-prompt"])
    assert rc == 0
    assert not _evidence_root(plan_dir).exists()

    # Missing contract: expected artifact error → exit-3 refusal on stderr,
    # not a leaked traceback.
    (plan_dir / "objective_contract.json").unlink()
    capsys.readouterr()
    rc = cli._plan_attach_goal_audit_main([str(plan_dir), "--show-prompt"])
    captured = capsys.readouterr()
    assert rc == 3
    assert "REFUSED" in captured.err
    assert "Traceback" not in captured.err
    assert not _evidence_root(plan_dir).exists()


def test_malformed_attach_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = tmp_path / "plan"
    _write_plan_fixture(plan_dir, "2026-07-27-test-malformed-attach")
    monkeypatch.setattr(ega, "_effective_implementer", lambda _p, _i: "claude")
    with pytest.raises(ega.ExternalGoalAuditError, match="refusing to attach"):
        ega.attach_external_goal_audit(
            plan_dir, vendor="gemini", response_text="not json at all", kind="goal"
        )
    # Refusal writes NOTHING — no audit envelope AND no completion_findings.json
    # (previously run_completion_audit dumped findings before validation).
    assert not _evidence_root(plan_dir).exists()


def test_attach_on_broken_plan_refuses_with_domain_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = tmp_path / "plan"
    _write_plan_fixture(plan_dir, "2026-07-27-test-broken-plan")
    (plan_dir / "objective_contract.json").unlink()
    monkeypatch.setattr(ega, "_effective_implementer", lambda _p, _i: "claude")
    with pytest.raises(ega.ExternalGoalAuditError, match="v1 findings"):
        ega.attach_external_goal_audit(
            plan_dir, vendor="gemini", response_text="[]", kind="goal"
        )
    assert not _evidence_root(plan_dir).exists()


# ─────────────── i1 regressions: stale external envelope vs backstop ───────────────


def _flip_status_completed(plan_dir: Path) -> None:
    plan_md = plan_dir / "plan.md"
    plan_md.write_text(
        plan_md.read_text().replace("status: active", "status: completed", 1),
        encoding="utf-8",
    )


def test_stale_external_goal_envelope_rejected_by_backstop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """codex F004-i0 finding: the completion backstop accepted any external
    goal envelope by audit_kind alone. Fresh attach passes; after the
    contract (and therefore findings + fingerprint) drift, the same
    envelope must no longer vouch for status='completed'."""
    from dontpanic_orchestrate import completion_auditor as ca

    plan_dir = tmp_path / "plan"
    _write_plan_fixture(plan_dir, "2026-07-27-test-stale-backstop")
    monkeypatch.setattr(ega, "_effective_implementer", lambda _p, _i: "claude")

    findings = ca.compute_completion_findings(plan_dir)
    assert findings, "fixture must yield v1 findings for the attach to grade"
    fp = cd.external_audit_fingerprint(plan_dir, findings)
    payload = json.dumps(
        {
            "source_fingerprint": fp,
            "dispositions": [_disp(f.finding_id) for f in findings],
        }
    )
    ega.attach_external_goal_audit(
        plan_dir, vendor="gemini", response_text=payload, kind="goal"
    )
    ca.run_completion_audit(plan_dir)  # completion_findings.json for the backstop
    _flip_status_completed(plan_dir)

    cg.enforce_completion_gate(plan_dir)  # fresh external envelope: passes

    # Contract drift: a second journey changes the findings set + fingerprint.
    contract = json.loads((plan_dir / "objective_contract.json").read_text())
    contract["user_journeys"].append(
        {
            "name": "fixture-journey-two",
            "description": "second journey added after the external audit attach",
            "surfaces": ["cli_human"],
            "states": ["ok"],
            "acceptance_signals": ["another fixture signal long enough for schema"],
        }
    )
    (plan_dir / "objective_contract.json").write_text(
        json.dumps(contract), encoding="utf-8"
    )
    with pytest.raises(cg.BackstopError, match="missing F2 audit evidence"):
        cg.enforce_completion_gate(plan_dir)

    # Dispatched envelopes keep the existence-only semantics: staleness of a
    # paid dispatch is governed at close time, not by the backstop.
    audit_dir = _evidence_root(plan_dir) / "audit"
    gemini_envelope = sorted(audit_dir.glob("audit-gemini-*.json"))[0]
    dispatched = json.loads(gemini_envelope.read_text())
    dispatched["auditor_agent"] = "codex"
    dispatched["provenance"] = "dispatched"
    (audit_dir / "audit-codex-0.json").write_text(
        json.dumps(dispatched), encoding="utf-8"
    )
    cg.enforce_completion_gate(plan_dir)


# ─────────────── i1 regressions: _experience_gate_decision ───────────────


def test_experience_gate_blocks_then_accepts_refuting_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = tmp_path / "plan"
    _write_plan_fixture(
        plan_dir, "2026-07-27-test-exp-gate", journey_consumer="human"
    )
    monkeypatch.setattr(ega, "_effective_implementer", lambda _p, _i: "claude")

    from dontpanic_orchestrate import completion_auditor as ca

    plan_data = cg._read_frontmatter(plan_dir / "plan.md")
    findings = ca.compute_completion_findings(plan_dir)
    exp_findings = [f for f in findings if f.gap_class == "journey_gap"]
    assert exp_findings, "consumer journey without evidence must emit journey_gap"

    gate, envelope, reasons = cg._experience_gate_decision(
        plan_dir, plan_data, findings
    )
    assert envelope is None
    assert reasons, "unproven consumer journey must block"
    assert gate is not None and gate.blocks

    # Operator attaches a refuting external experience audit (agree=false +
    # no_finding per journey_gap finding) → journey is dispositioned.
    fp = cd.external_audit_fingerprint(plan_dir, exp_findings)
    payload = json.dumps(
        {
            "source_fingerprint": fp,
            "dispositions": [_refute(f.finding_id) for f in exp_findings],
        }
    )
    ega.attach_external_goal_audit(
        plan_dir, vendor="gemini", response_text=payload, kind="experience"
    )
    gate2, envelope2, reasons2 = cg._experience_gate_decision(
        plan_dir, plan_data, findings
    )
    assert envelope2 is not None
    assert envelope2.audit_kind == "experience"
    assert reasons2 == []
    assert gate2 is not None and not gate2.blocks


def test_registry_promotion_flips_operator_only_doctor_and_attach_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulated D001-B2 promotion regression (F004-i1 auditor finding).

    When gemini later gains a registered executor (F014), every honesty
    surface must flip together, with no static list contradicting the live
    registry:
      - ``known_operator_only_agents()`` drops gemini,
      - ``doctor --agent`` reports the dispatched path instead of the
        operator-only attach path,
      - the external attach itself refuses gemini (no fabricated
        dispatched-shape evidence for a dispatchable agent).
    """
    import runpy

    from dontpanic_orchestrate import agent_surface, executors
    from dontpanic_orchestrate.executors.base import BaseExecutor

    doctor = runpy.run_path(str(HERE.parents[2] / "dontpanic_doctor.py"))

    def _external_audit_check() -> Any:
        checks = doctor["check_agent_onboarding"](skip_auth=True)
        return next(c for c in checks if c.name == "agent:external-audit")

    # Today (B1): gemini is operator-only everywhere.
    assert "gemini" in agent_surface.known_operator_only_agents()
    before = _external_audit_check()
    assert "gemini" in before.message
    assert "operator-only, NOT dispatchable" in before.message

    class _FakeGeminiExecutor(BaseExecutor):  # type: ignore[misc, valid-type]
        agent_name = "gemini"

        def is_available(self) -> bool:
            return False

        def dispatch(self, task: Any) -> Any:  # pragma: no cover - never called
            raise NotImplementedError

    monkeypatch.setitem(executors.AGENT_REGISTRY, "gemini", _FakeGeminiExecutor)

    # After promotion: every surface flips off the operator-only story.
    assert "gemini" not in agent_surface.known_operator_only_agents()
    after = _external_audit_check()
    assert "gemini: now registered" in after.message
    with pytest.raises(ega.ExternalGoalAuditError, match="registered executor"):
        ega._validate_vendor("gemini")
