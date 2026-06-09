"""Governance correctness fix (2026-06-09) — pre-impl sufficiency findings must
regenerate when the plan changed, and reuse only when it did not.

Root cause: ``cli._ensure_sufficiency_findings`` early-returned the moment a
``sufficiency-findings.json`` existed on disk. A stale artifact (e.g. committed
from a prior *refused* lock) therefore survived plan edits forever — a plan
tightened to address those exact findings could never clear the gate, because
the gate kept reading the pre-edit findings. The artifact also carried no
provenance, so nothing could tell whether it was stale.

The fix gives the findings artifact a stable input fingerprint over the
plan-contract files that affect sufficiency (plan.md / features.json /
objective_contract.json / decisions.jsonl) plus a generation timestamp, and
makes the lock regenerate iff the fingerprint is missing or drifted.

All tests are NO-PAID — the regeneration call is replaced by a spy and Codex
output is replayed from fixtures.

  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_sufficiency_findings_regen.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import cli  # noqa: E402
from dontpanic_orchestrate import sufficiency_auditor as sa  # noqa: E402
from dontpanic_orchestrate import sufficiency_gate as sg  # noqa: E402


def _codex_stream(agent_text: str) -> str:
    return "\n".join(
        json.dumps(ev)
        for ev in [
            {"type": "thread.started"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": agent_text}},
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
        ]
    )


_VALID_FINDINGS = [
    {
        "severity": "high",
        "journey_id": "coverage-honesty",
        "gap_class": "coverage_gap",
        "description": "the architecture page needs an entering-surface proof " * 2,
    }
]


def _make_plan(tmp_path: Path, *, goal_type: str = "new_feature") -> Path:
    d = tmp_path / "2026-06-09-999-feat-fixture"
    d.mkdir(parents=True)
    (d / "plan.md").write_text(
        "---\n"
        "id: 2026-06-09-999-feat-fixture\n"
        "title: Fixture\n"
        f"goal_type: {goal_type}\n"
        "links:\n"
        "  features: ./features.json\n"
        "  objective_contract: ./objective_contract.json\n"
        "  decisions: ./decisions.jsonl\n"
        "---\n\n# Fixture\n"
    )
    (d / "features.json").write_text(
        json.dumps(
            {
                "task_id": "2026-06-09-999-feat-fixture",
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "functional",
                        "description": "do the thing",
                        "acceptance": "the thing is done and verified through the real surface",
                        "passes": False,
                    }
                ],
            }
        )
    )
    (d / "objective_contract.json").write_text(
        json.dumps(
            {
                "goal_type": "new_feature",
                "source_of_truth": "operator directive: build the fixture thing end to end",
                "completion_test": "the fixture thing works and is verified through its surface",
                "user_journeys": [
                    {
                        "name": "primary-journey",
                        "description": "operator does the primary fixture thing successfully",
                        "surfaces": ["core"],
                        "states": ["ready"],
                    }
                ],
                "non_goals": ["nothing out of fixture scope"],
            }
        )
    )
    (d / "decisions.jsonl").write_text(
        json.dumps({"id": "D001", "decision": "initial", "rationale": "fixture"}) + "\n"
    )
    return d


def _write_findings(plan_dir: Path, *, fingerprint: str | None) -> Path:
    """Persist a findings artifact directly, optionally stamping a fingerprint
    (None simulates a pre-fix artifact that predates input-fingerprinting)."""
    payload: dict = {
        "auditor": "codex",
        "implementer": None,
        "findings": list(_VALID_FINDINGS),
    }
    if fingerprint is not None:
        payload["input_fingerprint"] = fingerprint
        payload["generated_at"] = "2026-06-09T00:00:00Z"
    out = sg._findings_path(plan_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return out


def _spy_regen(monkeypatch):
    """Replace the paid generator with a spy that records calls and rewrites a
    fresh, correctly-fingerprinted artifact (mirroring real regeneration)."""
    calls: list[str] = []

    def spy(plan_dir, **kwargs):
        calls.append(str(plan_dir))
        return sa.run_sufficiency_audit(
            Path(plan_dir),
            dispatch=lambda a, p: _codex_stream(json.dumps(_VALID_FINDINGS)),
        )

    monkeypatch.setattr(sa, "generate_sufficiency_findings", spy)
    return calls


# ── compute_input_fingerprint: stable + sensitive to every input file ────


def test_fingerprint_is_deterministic(tmp_path):
    plan_dir = _make_plan(tmp_path)
    assert sa.compute_input_fingerprint(plan_dir) == sa.compute_input_fingerprint(plan_dir)


def test_fingerprint_changes_when_features_change(tmp_path):
    plan_dir = _make_plan(tmp_path)
    before = sa.compute_input_fingerprint(plan_dir)
    feats = json.loads((plan_dir / "features.json").read_text())
    feats["features"][0]["acceptance"] += " AND a non-empty tier-0 graph for empty repos"
    (plan_dir / "features.json").write_text(json.dumps(feats))
    assert sa.compute_input_fingerprint(plan_dir) != before


def test_fingerprint_changes_when_plan_md_or_contract_or_decisions_change(tmp_path):
    plan_dir = _make_plan(tmp_path)
    base = sa.compute_input_fingerprint(plan_dir)

    (plan_dir / "plan.md").write_text((plan_dir / "plan.md").read_text() + "\nedited.\n")
    fp_after_plan = sa.compute_input_fingerprint(plan_dir)
    assert fp_after_plan != base

    contract = json.loads((plan_dir / "objective_contract.json").read_text())
    contract["non_goals"].append("another non-goal")
    (plan_dir / "objective_contract.json").write_text(json.dumps(contract))
    fp_after_contract = sa.compute_input_fingerprint(plan_dir)
    assert fp_after_contract != fp_after_plan

    with (plan_dir / "decisions.jsonl").open("a") as fh:
        fh.write(json.dumps({"id": "D002", "decision": "tightened", "rationale": "x"}) + "\n")
    assert sa.compute_input_fingerprint(plan_dir) != fp_after_contract


# ── the writer stamps provenance onto the artifact ───────────────────────


def test_run_sufficiency_audit_stamps_fingerprint_and_timestamp(tmp_path):
    plan_dir = _make_plan(tmp_path)
    sa.run_sufficiency_audit(
        plan_dir,
        implementer_agent="claude",
        dispatch=lambda a, p: _codex_stream(json.dumps(_VALID_FINDINGS)),
    )
    persisted = json.loads(sg._findings_path(plan_dir).read_text())
    assert persisted["input_fingerprint"] == sa.compute_input_fingerprint(plan_dir)
    assert persisted.get("generated_at"), "artifact must record when it was generated"


# ── the core fix: regenerate on stale, reuse on unchanged ────────────────


def test_ensure_regenerates_when_fingerprint_drifted(tmp_path, monkeypatch):
    plan_dir = _make_plan(tmp_path)
    _write_findings(plan_dir, fingerprint="sha256:STALE-from-a-prior-refused-lock")
    calls = _spy_regen(monkeypatch)

    cli._ensure_sufficiency_findings(plan_dir)

    assert calls == [str(plan_dir.resolve())], (
        "a stale (fingerprint-mismatch) findings artifact MUST be regenerated, "
        "not silently reused — this is the governance defect under repair"
    )
    # the rewritten artifact now matches the current inputs
    persisted = json.loads(sg._findings_path(plan_dir).read_text())
    assert persisted["input_fingerprint"] == sa.compute_input_fingerprint(plan_dir)


def test_ensure_regenerates_when_fingerprint_absent(tmp_path, monkeypatch):
    # pre-fix artifacts carry no fingerprint → must regenerate (can't prove fresh).
    plan_dir = _make_plan(tmp_path)
    _write_findings(plan_dir, fingerprint=None)
    calls = _spy_regen(monkeypatch)

    cli._ensure_sufficiency_findings(plan_dir)

    assert calls == [str(plan_dir.resolve())]


def test_ensure_reuses_when_fingerprint_matches(tmp_path, monkeypatch):
    plan_dir = _make_plan(tmp_path)
    _write_findings(plan_dir, fingerprint=sa.compute_input_fingerprint(plan_dir))
    calls = _spy_regen(monkeypatch)

    cli._ensure_sufficiency_findings(plan_dir)

    assert calls == [], "an unchanged plan must reuse findings — no second paid audit"


def test_ensure_generates_when_artifact_missing(tmp_path, monkeypatch):
    # preserved behavior: gated plan with no artifact still generates.
    plan_dir = _make_plan(tmp_path)
    calls = _spy_regen(monkeypatch)

    cli._ensure_sufficiency_findings(plan_dir)

    assert calls == [str(plan_dir.resolve())]
    assert sg._findings_path(plan_dir).is_file()


def test_ensure_skips_non_gated_plan_even_when_stale(tmp_path, monkeypatch):
    # a non-gated goal_type never costs a paid call, stale artifact or not.
    plan_dir = _make_plan(tmp_path, goal_type="refactor")
    _write_findings(plan_dir, fingerprint="sha256:STALE")
    calls = _spy_regen(monkeypatch)

    cli._ensure_sufficiency_findings(plan_dir)

    assert calls == [], "non-gated plans must not trigger a sufficiency audit"


# ── audit remediation (2026-06-09): fingerprint must follow links.objective_contract ──


def _relocate_contract(plan_dir: Path, rel: str) -> Path:
    """Move the objective contract to a non-default path and repoint plan.md's
    links.objective_contract at it (mirrors a plan that relocates its contract)."""
    target = plan_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text((plan_dir / "objective_contract.json").read_text())
    (plan_dir / "objective_contract.json").unlink()
    pm = (plan_dir / "plan.md").read_text().replace(
        "objective_contract: ./objective_contract.json",
        f"objective_contract: ./{rel}",
    )
    (plan_dir / "plan.md").write_text(pm)
    return target


def test_fingerprint_follows_linked_contract_not_default_name(tmp_path):
    # Audit High finding: editing the RESOLVED linked contract must change the
    # fingerprint even when it is not named objective_contract.json.
    plan_dir = _make_plan(tmp_path)
    contract = _relocate_contract(plan_dir, "contracts/v2.json")
    before = sa.compute_input_fingerprint(plan_dir)

    data = json.loads(contract.read_text())
    data["non_goals"].append("a new non-goal that must invalidate findings")
    contract.write_text(json.dumps(data))

    assert sa.compute_input_fingerprint(plan_dir) != before, (
        "editing the linked contract must change the fingerprint — hardcoding "
        "objective_contract.json would leave the stale-reuse bug open"
    )


def test_ensure_regenerates_when_linked_contract_changes(tmp_path, monkeypatch):
    # End-to-end through the lock path for a relocated-contract plan.
    plan_dir = _make_plan(tmp_path)
    _relocate_contract(plan_dir, "contracts/v2.json")
    _write_findings(plan_dir, fingerprint=sa.compute_input_fingerprint(plan_dir))
    calls = _spy_regen(monkeypatch)

    # unchanged → reuse
    cli._ensure_sufficiency_findings(plan_dir)
    assert calls == [], "matching fingerprint on a linked-contract plan must reuse"

    # edit the linked contract → must regenerate
    contract = plan_dir / "contracts/v2.json"
    data = json.loads(contract.read_text())
    data["completion_test"] += " (tightened)"
    contract.write_text(json.dumps(data))
    cli._ensure_sufficiency_findings(plan_dir)
    assert calls == [str(plan_dir.resolve())], (
        "editing the linked contract must force regeneration via the lock path"
    )


def test_fingerprint_stamped_is_captured_before_dispatch(tmp_path):
    # Audit Medium (TOCTOU): if a plan input is edited DURING the paid audit, the
    # persisted fingerprint must describe the inputs the findings actually saw
    # (pre-edit), not the post-edit files.
    plan_dir = _make_plan(tmp_path)
    pre_fp = sa.compute_input_fingerprint(plan_dir)

    def mutating_dispatch(auditor, prompt):
        # simulate a concurrent plan edit landing mid-audit
        feats = json.loads((plan_dir / "features.json").read_text())
        feats["features"][0]["acceptance"] += " edited mid-audit"
        (plan_dir / "features.json").write_text(json.dumps(feats))
        return _codex_stream(json.dumps(_VALID_FINDINGS))

    sa.run_sufficiency_audit(plan_dir, implementer_agent="claude", dispatch=mutating_dispatch)

    persisted = json.loads(sg._findings_path(plan_dir).read_text())
    assert persisted["input_fingerprint"] == pre_fp, (
        "stamp must reflect the pre-dispatch inputs the findings describe"
    )
    assert persisted["input_fingerprint"] != sa.compute_input_fingerprint(plan_dir), (
        "post-edit fingerprint differs — proving the stamp was captured before dispatch"
    )
