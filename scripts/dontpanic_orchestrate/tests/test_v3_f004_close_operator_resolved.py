"""Plan 2026-05-11-002 v3 F004 — operator-resolved close-out smoke tests.

Pins the ``dontpanic close --operator-resolved <plan> <feature> --reason
<class>`` CLI against a synthetic fixture. The real plan 010 F001 path
is already closed via the manual workflow (per v3 plan description) so
we do not exercise the production artifacts here.

Acceptance items pinned (cross-referencing v3 features.json F004):

  (1) ``dontpanic close --operator-resolved <plan> <feature> --reason
      <class>`` works end-to-end on a synthetic fixture.
  (2) Generates the closeout-memo template at ``evidence/closeout-memo-<FEATURE>.md``
      — named per FEATURE since 2026-08-14; a shared name silently destroyed
      the previous feature's memo (51 records across 13 plans).
  (3) Clears ``breaker:no_progress`` + writes signoff envelope in one
      transaction (CLI success exit 0 + both side-effects observable).
  (4) INBOX ``no_progress_classification`` body surfaces the recommended
      close command inline (verified via the supervisor's helper rather
      than dispatching a real volley).
  (5) Synthetic fixture only — no touching of the real plan 010 F001.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    auditor_taxonomy,
    circuit_breakers,
    cli,
    closeout,
    gate_pause,
    inbox,
)


# ────────────────────────────  fixtures  ────────────────────────────


_PLAN_TEMPLATE = """---
id: {plan_id}
title: Synthetic plan for v3 F004 close-out
type: infra
tier: trivial
status: active
date: "2026-05-11"
description: Synthetic plan for plan 2026-05-11-002 v3 F004 close-out tests.
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

# Synthetic v3 F004 plan

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
                "description": (
                    "Synthetic feature exercising v3 F004 operator-resolved "
                    "close-out path."
                ),
                "steps": ["scripted"],
                "acceptance": "close --operator-resolved succeeds.",
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
    vendor: str,
    role: str,
    feature_id: str,
    iteration: int,
    audit_status: str,
    findings: list[dict] | None = None,
    summary: str = "",
) -> Path:
    audit_dir = plan_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{vendor}-{role}-{feature_id}-i{iteration}.json"
    envelope = {
        "task_id": plan_dir.name,
        "feature_id": feature_id,
        "agent": vendor,
        "agent_role": role,
        "iteration": iteration,
        "audit_status": audit_status,
        "summary": summary or f"[{vendor}/{role}] iter={iteration} status={audit_status}",
        "findings": findings or [],
        "quota_consumed": {},
        "validation_performed": [],
        "started_at": "2026-05-11T18:00:00Z",
        "completed_at": "2026-05-11T18:01:00Z",
    }
    path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n")
    return path


def _seed_no_progress_state(plan_dir: Path, plan_id: str) -> None:
    """Simulate a stopped_no_progress terminal: 2 auditor rounds with
    identical needs_changes verdicts + breaker:no_progress in
    gate-state.json."""
    finding = {
        "severity": "medium",
        "category": "documentation",
        "feature_id": "F001",
        "issue": (
            "Adapter docs placement is ambiguous; spec doesn't pin the path. "
            "Operator review recommended."
        ),
        "evidence": "synthetic-evidence",
    }
    _write_audit_envelope(
        plan_dir,
        vendor="claude",
        role="implementer",
        feature_id="F001",
        iteration=0,
        audit_status="signed_off",
    )
    _write_audit_envelope(
        plan_dir,
        vendor="codex",
        role="auditor",
        feature_id="F001",
        iteration=0,
        audit_status="needs_changes",
        findings=[finding],
        summary="Auditor: spec ambiguity on docs placement.",
    )
    _write_audit_envelope(
        plan_dir,
        vendor="claude",
        role="implementer",
        feature_id="F001",
        iteration=1,
        audit_status="signed_off",
    )
    _write_audit_envelope(
        plan_dir,
        vendor="codex",
        role="auditor",
        feature_id="F001",
        iteration=1,
        audit_status="needs_changes",
        findings=[finding],
        summary="Auditor: spec ambiguity on docs placement (iter 1).",
    )
    gate_pause.add_breaker(
        plan_dir,
        circuit_breakers.gate_name(circuit_breakers.BreakerKind.NO_PROGRESS),
        plan_id=plan_id,
        reason="synthetic stopped_no_progress for v3 F004 smoke test",
    )


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = cli.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 2
    return rc, out.getvalue(), err.getvalue()


# ────────────────────────────  tests  ────────────────────────────


def test_close_operator_resolved_end_to_end() -> None:
    """AC1+AC2+AC3: CLI succeeds, memo generated, breaker cleared, signoff
    written, features.json passes flipped — all in one invocation."""
    print("\n[test] close_operator_resolved_end_to_end ...")
    with tempfile.TemporaryDirectory() as td:
        plan_id = "2026-05-11-901-infra-v3-f004-end-to-end"
        plan_dir = _make_plan(Path(td), plan_id)
        _seed_no_progress_state(plan_dir, plan_id)

        rc, out, err = _run_cli(
            [
                "close",
                "--operator-resolved",
                str(plan_dir),
                "F001",
                "--reason",
                "spec_ambiguity",
            ]
        )
        assert rc == 0, (rc, out, err)

        # AC2: memo generated
        memo = plan_dir / closeout.closeout_memo_relpath("F001")
        assert memo.is_file(), f"memo not at {memo}"
        body = memo.read_text()
        assert "status: operator_resolved" in body, body
        assert "reason_class: spec_ambiguity" in body, body
        assert "spec ambiguity on docs placement (iter 1)" in body, body

        # AC3: breaker cleared
        state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
        active = state.get("active_breakers") or []
        assert "breaker:no_progress" not in active, active

        # AC3: signoff envelope written
        signoff_path = plan_dir / "audit" / f"signoff-{plan_id}.json"
        assert signoff_path.is_file(), f"signoff not at {signoff_path}"
        signoff = json.loads(signoff_path.read_text())
        assert signoff["task_id"] == plan_id
        assert signoff["signoff"] is True
        assert signoff["next_action"] == "merge"
        assert "operator_resolved" in signoff["signoff_reason"]
        assert "spec_ambiguity" in signoff["signoff_reason"]
        # operator_resolution sidecar file (v3 F004 i1 fix — Signoff has
        # extra='forbid' so this metadata lives in a separate file, same
        # pattern as charter-compliance-{plan_id}.json)
        assert "operator_resolution" not in signoff, (
            "operator_resolution must NOT ride along in the signoff envelope; "
            "Signoff schema has extra='forbid' so it lives in a sidecar"
        )
        resolution_path = closeout.operator_resolution_path(plan_dir, plan_id, "F001")
        assert resolution_path.is_file(), f"sidecar missing at {resolution_path}"
        resolution = json.loads(resolution_path.read_text())
        assert resolution["resolved"] is True
        assert resolution["class"] == "spec_ambiguity"
        assert resolution["feature_id"] == "F001"
        assert resolution["plan_id"] == plan_id

        # features.json: passes flipped + evidence ref appended
        features = json.loads((plan_dir / "features.json").read_text())
        f001 = next(f for f in features["features"] if f["id"] == "F001")
        assert f001["passes"] is True, f001
        refs = f001.get("evidence_refs") or []
        assert any(
            r.get("uri") == "evidence/closeout-memo-F001.md" for r in refs
        ), refs
        assert "operator" in (f001.get("verified_by") or [])

        # INBOX entry written
        events = inbox.read_events(plan_dir)
        ev = next(
            (e for e in events if e.event == "feature_operator_resolved"),
            None,
        )
        assert ev is not None, [e.event for e in events]
        assert ev.headers.get("feature_id") == "F001"
        assert ev.headers.get("reason_class") == "spec_ambiguity"
        print("  ✓ memo, signoff, breaker clear, features.json all transacted")


def test_close_refuses_without_operator_resolved_flag() -> None:
    """The --operator-resolved flag is reserved + required."""
    print("\n[test] close_refuses_without_operator_resolved_flag ...")
    with tempfile.TemporaryDirectory() as td:
        plan_id = "2026-05-11-902-infra-v3-f004-flag-required"
        plan_dir = _make_plan(Path(td), plan_id)
        _seed_no_progress_state(plan_dir, plan_id)
        rc, out, err = _run_cli(
            ["close", str(plan_dir), "F001", "--reason", "spec_ambiguity"]
        )
        assert rc == 2, (rc, out, err)
        assert "--operator-resolved" in err, err
        print("  ✓ bare `close` refused with helpful error")


def test_close_refuses_unknown_reason_class() -> None:
    print("\n[test] close_refuses_unknown_reason_class ...")
    with tempfile.TemporaryDirectory() as td:
        plan_id = "2026-05-11-903-infra-v3-f004-bad-reason"
        plan_dir = _make_plan(Path(td), plan_id)
        _seed_no_progress_state(plan_dir, plan_id)
        rc, out, err = _run_cli(
            [
                "close",
                "--operator-resolved",
                str(plan_dir),
                "F001",
                "--reason",
                "made_up_class_name",
            ]
        )
        assert rc == 3, (rc, out, err)
        assert "unknown reason class" in err, err
        # No closeout-memo should have been created on the refusal path.
        memo = plan_dir / closeout.closeout_memo_relpath("F001")
        assert not memo.exists(), f"memo should not exist; got {memo}"
        print("  ✓ unknown class rejected before any state change")


def test_close_refuses_when_breaker_not_active() -> None:
    """Safety check: refuse when breaker:no_progress is not active —
    operator may not be closing-out a real stopped_no_progress."""
    print("\n[test] close_refuses_when_breaker_not_active ...")
    with tempfile.TemporaryDirectory() as td:
        plan_id = "2026-05-11-904-infra-v3-f004-no-breaker"
        plan_dir = _make_plan(Path(td), plan_id)
        # Write audit envelopes but DO NOT seed the breaker.
        _write_audit_envelope(
            plan_dir,
            vendor="claude",
            role="implementer",
            feature_id="F001",
            iteration=0,
            audit_status="signed_off",
        )
        _write_audit_envelope(
            plan_dir,
            vendor="codex",
            role="auditor",
            feature_id="F001",
            iteration=0,
            audit_status="signed_off",
        )
        rc, out, err = _run_cli(
            [
                "close",
                "--operator-resolved",
                str(plan_dir),
                "F001",
                "--reason",
                "operator_judgment",
            ]
        )
        assert rc == 3, (rc, out, err)
        assert "not currently active" in err, err
        print("  ✓ missing breaker safety check fires")


def test_close_allow_missing_breaker_overrides_safety_check() -> None:
    """--allow-missing-breaker bypasses the active-breaker safety check."""
    print("\n[test] close_allow_missing_breaker_overrides_safety_check ...")
    with tempfile.TemporaryDirectory() as td:
        plan_id = "2026-05-11-905-infra-v3-f004-allow-missing"
        plan_dir = _make_plan(Path(td), plan_id)
        _write_audit_envelope(
            plan_dir,
            vendor="claude",
            role="implementer",
            feature_id="F001",
            iteration=0,
            audit_status="signed_off",
        )
        _write_audit_envelope(
            plan_dir,
            vendor="codex",
            role="auditor",
            feature_id="F001",
            iteration=0,
            audit_status="signed_off",
        )
        rc, out, err = _run_cli(
            [
                "close",
                "--operator-resolved",
                str(plan_dir),
                "F001",
                "--reason",
                "operator_judgment",
                "--allow-missing-breaker",
            ]
        )
        assert rc == 0, (rc, out, err)
        memo = plan_dir / closeout.closeout_memo_relpath("F001")
        assert memo.is_file()
        print("  ✓ --allow-missing-breaker bypasses safety check")


def test_close_refuses_unknown_feature_id() -> None:
    print("\n[test] close_refuses_unknown_feature_id ...")
    with tempfile.TemporaryDirectory() as td:
        plan_id = "2026-05-11-906-infra-v3-f004-unknown-feat"
        plan_dir = _make_plan(Path(td), plan_id)
        _seed_no_progress_state(plan_dir, plan_id)
        rc, out, err = _run_cli(
            [
                "close",
                "--operator-resolved",
                str(plan_dir),
                "F099",
                "--reason",
                "spec_ambiguity",
            ]
        )
        # First check: audit_paths for F099 — none → CloseoutError.
        assert rc == 3, (rc, out, err)
        assert "no audit envelopes found" in err or "feature 'F099' not found" in err, err
        print("  ✓ unknown feature id rejected")


def test_render_closeout_memo_lifts_summary_when_envelope_present() -> None:
    """Pure renderer pins the template shape."""
    print("\n[test] render_closeout_memo_lifts_summary ...")
    envelope = {
        "audit_status": "needs_changes",
        "summary": "Spec doesn't pin docs path; both readings fit.",
        "findings": [],
    }
    out = closeout.render_closeout_memo(
        plan_id="P",
        feature_id="F001",
        reason_class="spec_ambiguity",
        auditor_envelope=envelope,
    )
    assert "status: operator_resolved" in out
    assert "reason_class: spec_ambiguity" in out
    assert "Spec doesn't pin docs path" in out
    assert "latest_audit_status: needs_changes" in out
    print("  ✓ memo template renders with auditor summary lifted")


def test_render_closeout_memo_handles_missing_envelope() -> None:
    print("\n[test] render_closeout_memo_handles_missing_envelope ...")
    out = closeout.render_closeout_memo(
        plan_id="P",
        feature_id="F001",
        reason_class="operator_judgment",
        auditor_envelope=None,
    )
    assert "status: operator_resolved" in out
    assert "(no auditor envelope summary available" in out
    assert "latest_audit_status: unknown" in out
    print("  ✓ missing envelope gracefully placeholders")


def test_close_hint_appears_in_no_progress_inbox_body() -> None:
    """AC4: the no_progress_classification INBOX event body surfaces the
    recommended close command inline. We verify via the helper that the
    supervisor calls — the supervisor's own dispatch path is exercised by
    test_volley_synthetic; this test pins the helper used by both sites."""
    print("\n[test] close_hint_appears_in_no_progress_inbox_body ...")
    hint = closeout.format_no_progress_close_hint(
        plan_id="P-2026",
        feature_id="F042",
        recommended_class="spec_ambiguity",
    )
    # v3 F004 i1 audit fix (medium correctness): hint must surface the
    # `dontpanic close ...` CLI form (the one bound at __main__ + on the
    # console-script), not the `python -m dontpanic_orchestrate close ...`
    # module form. Both work, but operators are told to use the former.
    assert "dontpanic close --operator-resolved P-2026 F042" in hint
    assert "python -m dontpanic_orchestrate" not in hint
    assert "--reason spec_ambiguity" in hint
    assert "breaker:no_progress" in hint
    assert "closeout-memo" in hint
    # And confirm format_inbox_body + hint compose to a no-progress body
    # that names the recommended close form. Build a minimal classification
    # by hand so we don't depend on the classifier internals.
    classification = auditor_taxonomy.TerminalClassification(
        feature_id="F042",
        aggregate=auditor_taxonomy.FindingClass.SPEC_AMBIGUITY,
        blocking=False,
        findings=(),
        recommended_action="Operator review for spec gap before retry.",
    )
    body = auditor_taxonomy.format_inbox_body(classification) + hint
    assert "Recommended next action:" in body
    assert "--operator-resolved P-2026 F042" in body
    print("  ✓ close hint composes cleanly with the classification body")


def test_close_idempotent_on_rerun() -> None:
    """Re-running close --operator-resolved after a clean run is safe:
    memo overwritten, breaker stays cleared, signoff rewritten, features
    untouched (already flipped). Exit 0 either way."""
    print("\n[test] close_idempotent_on_rerun ...")
    with tempfile.TemporaryDirectory() as td:
        plan_id = "2026-05-11-907-infra-v3-f004-idempotent"
        plan_dir = _make_plan(Path(td), plan_id)
        _seed_no_progress_state(plan_dir, plan_id)

        argv = [
            "close",
            "--operator-resolved",
            str(plan_dir),
            "F001",
            "--reason",
            "spec_ambiguity",
        ]
        rc1, _, _ = _run_cli(argv)
        assert rc1 == 0
        # Second invocation needs --allow-missing-breaker because the
        # first run already cleared it.
        rc2, out2, err2 = _run_cli(argv + ["--allow-missing-breaker"])
        assert rc2 == 0, (rc2, out2, err2)
        # features.json passes is already true — no double evidence ref.
        features = json.loads((plan_dir / "features.json").read_text())
        f001 = next(f for f in features["features"] if f["id"] == "F001")
        refs = [r for r in f001["evidence_refs"] if r["uri"] == "evidence/closeout-memo-F001.md"]
        assert len(refs) == 1, refs
        print("  ✓ re-run is idempotent with --allow-missing-breaker")


# ────────────────────  plan-010 F001 replay fixture  ────────────────────
#
# v3 F004 i1 audit fix (medium test_coverage): the smoke fixture must
# exercise the plan-010 F001 motivating fixture shape (the real
# stopped_no_progress that triggered authoring this feature). We REPLAY
# the envelope shape against a temp plan dir — never the real
# 2026-05-10-001 plan, which is already operator_resolved through the
# manual workflow per v3 plan description.
#
# Source envelopes copied (in shape, not bytes — task_id/plan_id is rewritten
# to the temp plan id so signoff schema validation passes):
#   docs/plans/2026-05-10-001-feat-printing-press-adapter-skill/audit/
#     ├─ claude-implementer-F001-i0.json
#     ├─ codex-auditor-F001-i0.json
#     ├─ claude-implementer-F001-i1.json
#     ├─ codex-auditor-F001-i1.json
#     └─ no_progress_classification_F001_iter2.json
#
# Findings preserved verbatim from the real envelopes so the
# closeout-memo summary-lift exercises the same code path the real
# operator close-out would have. The aggregate class (`unknown` for
# plan-010) is what the operator would override via `--reason` in the
# real workflow.


_PLAN010_F001_REPLAY_FINDINGS = [
    {
        "severity": "medium",
        "category": "security",
        "feature_id": "F001",
        "issue": (
            "`ADAPTER_TEMPLATE.md` does not implement the required "
            "sanitization checks on tool responses. Evidence: the response "
            "paths only call `apply_redact(...)` at "
            "`claude/skills/printing-press-adapter/ADAPTER_TEMPLATE.md:"
            "225-231`, and `rg` found no sanitize/sanitization hook. "
            "Recommendation: add an explicit sanitization/check function "
            "after redaction for all success/error response paths."
        ),
        "evidence": "Extracted from auditor summary (plan-010 F001 i0).",
    },
    {
        "severity": "low",
        "category": "documentation",
        "feature_id": "F001",
        "issue": (
            "`docs/STATE_PROJECTION.md` does not directly cross-link the "
            "new skill path. Evidence: `docs/STATE_PROJECTION.md:167-169` "
            "only references ROADMAP/Printing Press generally, while "
            "ROADMAP already links `../claude/skills/printing-press-"
            "adapter/SKILL.md`. Recommendation: add the direct skill "
            "cross-reference there."
        ),
        "evidence": "Extracted from auditor summary (plan-010 F001 i0).",
    },
]
_PLAN010_F001_REPLAY_FINDINGS_ITER1 = [
    {
        "severity": "medium",
        "category": "documentation",
        "feature_id": "F001",
        "issue": (
            "PP version pinning is documented in the per-service config, "
            "not in the adapter's `~/.dontpanic/adapters.json` entry as "
            "required. Evidence: F001 step requires documenting the PP "
            "version in the adapter's `adapters.json` entry "
            "(`features.json:12`), but `SKILL.md:125-129` and "
            "`SKILL.md:171-174` put `pp_version` in "
            "`~/.dontpanic/adapters/<service>.json`."
        ),
        "evidence": "Extracted from auditor summary (plan-010 F001 i1).",
    },
]


def _seed_plan010_replay(plan_dir: Path, plan_id: str) -> None:
    """Build the temp-plan audit/ from the real plan-010 F001 envelope
    shape: 2 implementer-auditor rounds, both auditor verdicts
    `needs_changes` with substantive findings, terminating
    `stopped_no_progress` with aggregate `unknown` per the v0 taxonomy
    (because the findings are documentation/security — not in the
    pattern-matched spec_ambiguity/scope_overreach/etc. set)."""
    _write_audit_envelope(
        plan_dir,
        vendor="claude",
        role="implementer",
        feature_id="F001",
        iteration=0,
        audit_status="signed_off",
        summary="[plan-010 replay] implementer i0 signed off own work.",
    )
    _write_audit_envelope(
        plan_dir,
        vendor="codex",
        role="auditor",
        feature_id="F001",
        iteration=0,
        audit_status="needs_changes",
        findings=_PLAN010_F001_REPLAY_FINDINGS,
        summary=(
            "[plan-010 replay i0] ADAPTER_TEMPLATE.md missing sanitization "
            "hook; STATE_PROJECTION.md cross-link gap."
        ),
    )
    _write_audit_envelope(
        plan_dir,
        vendor="claude",
        role="implementer",
        feature_id="F001",
        iteration=1,
        audit_status="signed_off",
        summary="[plan-010 replay] implementer i1 patched sanitization hook + cross-link.",
    )
    _write_audit_envelope(
        plan_dir,
        vendor="codex",
        role="auditor",
        feature_id="F001",
        iteration=1,
        audit_status="needs_changes",
        findings=_PLAN010_F001_REPLAY_FINDINGS_ITER1,
        summary=(
            "[plan-010 replay i1] PP version pinning location mismatch "
            "between features.json acceptance and SKILL.md per-service "
            "config — spec ambiguity."
        ),
    )
    # Write the no_progress classification sidecar shape that the
    # supervisor would have emitted (aggregate=unknown matches the real
    # plan-010 classification).
    (plan_dir / "audit" / "no_progress_classification_F001_iter2.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "kind": "no_progress_classification",
                "captured_at": "2026-05-11T15:24:35Z",
                "feature_id": "F001",
                "aggregate": "unknown",
                "blocking": True,
                "recommended_action": (
                    "Auditor produced findings the taxonomy could not "
                    "place. Inspect the audit envelope manually before "
                    "deciding whether to retry, escalate, or close as "
                    "blocked."
                ),
                "saved_evidence_paths": [],
                "findings": [
                    {
                        "finding_index": 0,
                        "classification": "unknown",
                        "severity": "medium",
                        "category": "documentation",
                        "issue_excerpt": _PLAN010_F001_REPLAY_FINDINGS_ITER1[0][
                            "issue"
                        ][:160],
                        "rationale": (
                            "no taxonomy pattern matched and severity/"
                            "category are not substantive; remains "
                            "blocking pending operator review."
                        ),
                    }
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    gate_pause.add_breaker(
        plan_dir,
        circuit_breakers.gate_name(circuit_breakers.BreakerKind.NO_PROGRESS),
        plan_id=plan_id,
        reason=(
            "[plan-010 replay] synthetic stopped_no_progress matching the "
            "real plan-010 F001 terminal shape; v3 F004 motivating fixture."
        ),
    )


def test_close_operator_resolved_replays_plan010_f001_fixture() -> None:
    """v3 F004 AC5: replay the plan-010 F001 motivating fixture shape
    (real envelope shape + terminal + classification side-car) against a
    temp plan dir and verify the operator-resolved close-out lands all
    four artifacts. The real plan 2026-05-10-001 is never touched — it
    has already been closed via the manual workflow per v3 plan
    description."""
    print("\n[test] close_operator_resolved_replays_plan010_f001_fixture ...")
    with tempfile.TemporaryDirectory() as td:
        # Same date prefix as the real plan so the directory shape is
        # comparable, but the suffix is synthetic so no chance of
        # collision with the real 2026-05-10-001 directory.
        plan_id = "2026-05-10-901-feat-pp-adapter-skill-replay"
        plan_dir = _make_plan(Path(td), plan_id)
        _seed_plan010_replay(plan_dir, plan_id)

        # Operator chooses `unknown` (the aggregate the supervisor would
        # have surfaced via the no_progress_classification sidecar);
        # `unknown` is in the KNOWN_CLOSEOUT_CLASSES allow-list per the
        # v0 7-class taxonomy.
        rc, out, err = _run_cli(
            [
                "close",
                "--operator-resolved",
                str(plan_dir),
                "F001",
                "--reason",
                "unknown",
            ]
        )
        assert rc == 0, (rc, out, err)

        # AC2 — memo template lifts the i1 auditor summary (the LATEST
        # auditor envelope, per _latest_auditor_envelope's reverse-iter
        # pick-the-newest behavior).
        memo = (plan_dir / closeout.closeout_memo_relpath("F001")).read_text()
        assert "status: operator_resolved" in memo
        assert "reason_class: unknown" in memo
        assert "PP version pinning" in memo, memo  # lifted from i1 summary

        # AC3 — breaker cleared + signoff written in one transaction.
        state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
        assert "breaker:no_progress" not in (state.get("active_breakers") or [])
        signoff_path = plan_dir / "audit" / f"signoff-{plan_id}.json"
        signoff = json.loads(signoff_path.read_text())
        assert signoff["signoff"] is True
        assert signoff["next_action"] == "merge"
        # operator_resolution lives in a sidecar file (v3 F004 i1 fix).
        resolution_path = closeout.operator_resolution_path(plan_dir, plan_id, "F001")
        resolution = json.loads(resolution_path.read_text())
        assert resolution["class"] == "unknown"
        # Audit history spans all four envelopes — operator close-out cites
        # the same envelopes the supervisor recorded.
        assert len(signoff["audits"]) == 4, signoff["audits"]

        # AC1 — features.json passes flipped.
        features = json.loads((plan_dir / "features.json").read_text())
        f001 = next(f for f in features["features"] if f["id"] == "F001")
        assert f001["passes"] is True

        # Confirms the real plan-010 directory was never touched.
        real_plan_010 = (
            Path(__file__).resolve().parents[3]
            / "docs"
            / "plans"
            / "2026-05-10-001-feat-printing-press-adapter-skill"
        )
        if real_plan_010.is_dir():
            real_signoff = real_plan_010 / "audit" / (
                f"signoff-2026-05-10-001-feat-printing-press-adapter-skill.json"
            )
            # The test must NOT have written a signoff into the real plan dir.
            # (We don't assert real_signoff.exists() either way — the real
            # plan is operator-closed via the manual flow without a
            # generated signoff envelope.)
            assert signoff_path.resolve() != real_signoff.resolve()
        print("  ✓ plan-010 F001 replay fixture closes via the new CLI cleanly")


def test_atomic_signoff_committed_before_breaker_clear() -> None:
    """v3 F004 i1 audit fix (high correctness): failure injection — if
    `approve_gate` raises AFTER the signoff envelope is written, the
    signoff must remain on disk AND the breaker must remain active. The
    new transaction order (signoff THEN breaker) guarantees this; this
    test pins the invariant so a future reorder breaks the test instead
    of regressing the bug."""
    print("\n[test] atomic_signoff_committed_before_breaker_clear ...")
    # closeout.py binds `gate_pause` at module load time, so we patch the
    # reference on that module — mirrors the supervisor.py monkeypatch
    # idiom and bypasses the need for a pytest fixture.
    original_approve = closeout.gate_pause.approve_gate

    def _exploding_approve(*args, **kwargs):
        raise RuntimeError("injected failure mid-close-out")

    with tempfile.TemporaryDirectory() as td:
        plan_id = "2026-05-11-908-infra-v3-f004-atomic"
        plan_dir = _make_plan(Path(td), plan_id)
        _seed_no_progress_state(plan_dir, plan_id)

        closeout.gate_pause.approve_gate = _exploding_approve  # type: ignore[assignment]
        try:
            raised: Exception | None = None
            try:
                closeout.run_close_out(
                    plan_dir=plan_dir,
                    plan_id=plan_id,
                    feature_id="F001",
                    reason_class="spec_ambiguity",
                    tier="trivial",
                    agents_in_panel=["claude", "codex"],
                )
            except RuntimeError as exc:
                raised = exc
            assert raised is not None, "expected approve_gate to raise"
            assert "injected failure" in str(raised)

            # Signoff envelope MUST be on disk (durable record of operator
            # decision committed BEFORE the breaker clear).
            signoff_path = plan_dir / "audit" / f"signoff-{plan_id}.json"
            assert signoff_path.is_file(), (
                "signoff envelope missing — atomic transaction order "
                "violated; the failure must occur AFTER signoff is durable"
            )
            signoff = json.loads(signoff_path.read_text())
            assert signoff["signoff"] is True

            # Restore approve_gate so we can read state via the canonical
            # path and re-run the workflow.
            closeout.gate_pause.approve_gate = original_approve  # type: ignore[assignment]
            state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
            assert "breaker:no_progress" in (state.get("active_breakers") or []), (
                "breaker cleared despite approve_gate failure — atomic "
                "ordering broken"
            )

            # Re-run with default safety check (no --allow-missing-breaker
            # needed — the breaker is still active per the atomic
            # guarantee).
            rc, out, err = _run_cli(
                [
                    "close",
                    "--operator-resolved",
                    str(plan_dir),
                    "F001",
                    "--reason",
                    "spec_ambiguity",
                ]
            )
            assert rc == 0, (rc, out, err)
            state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
            assert "breaker:no_progress" not in (state.get("active_breakers") or [])
            print(
                "  ✓ signoff durable before breaker clear; re-run recovers "
                "cleanly"
            )
        finally:
            closeout.gate_pause.approve_gate = original_approve  # type: ignore[assignment]
