"""Tests for signed_off_finalizer — Plan 2026-05-30-001 F007 AC(9)-(12) / D025.

The no-paid finalizer flips a cleanly auditor-signed_off + pre_merge-cleared
feature's passes:true without re-running any executor. Covers:
  - AC(9)  success: signed_off + pre_merge cleared -> passes flip, signoff repaired
  - AC(10) refusals: not_signed_off, pre_merge_uncleared, no_audit (distinct codes)
  - AC(11) idempotency: re-run is a no-op
  - AC(12) no dispatch_volley: finalizer never invokes the supervisor volley
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import gate_pause, signed_off_finalizer, signoff_writer

PLAN_ID = "2026-05-30-001-feat-finalizer-demo"

def _loadable_plan_md(plan_id: str) -> str:
    """Sentinel r3b (B) — the finalizer now fails closed on an unloadable plan
    (``plan_unloadable``), so the fixture must be a real, loadable plan."""
    return f"""---
id: {plan_id}
title: Signed-off finalizer synthetic
type: feat
tier: cross-cutting
status: active
date: "2026-05-30"
description: Synthetic loadable plan for the no-paid finalizer tests.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# Demo

## Target

```yaml
target_env: dev
target_project: none
```
"""



def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2) + "\n")


def _plan_dir(tmp_path: Path, *, audit_status: str = "signed_off") -> Path:
    plan_dir = tmp_path / "docs" / "plans" / PLAN_ID
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_loadable_plan_md(PLAN_ID))
    _write(
        plan_dir / "features.json",
        {
            "task_id": PLAN_ID,
            "schema_version": "1.0",
            "features": [{"id": "F001", "category": "test", "phase": 0, "description": "Demo brief", "steps": ["scripted"], "acceptance": "Flips only after signed_off + pre_merge.", "passes": False, "depends_on": []}],
        },
    )
    # implementer + auditor envelopes (auditor carries the verdict).
    _write(
        plan_dir / "audit" / "claude-implementer-F001-i0.json",
        {"agent": "claude", "agent_role": "implementer", "iteration": 0},
    )
    _write(
        plan_dir / "audit" / "codex-auditor-F001-i0.json",
        {
            "audit_id": f"{PLAN_ID}#codex#0",
            "agent": "codex",
            "agent_role": "auditor",
            "iteration": 0,
            # Real envelopes always carry completed_at (Audit schema); the
            # finalizer fails closed without it (Sentinel 5870049314 HIGH-2).
            "completed_at": "2026-01-01T00:00:00Z",
            "audit_status": audit_status,
            "findings": [],
            "summary": "Looks good.",
        },
    )
    return plan_dir


def _clear_pre_merge(plan_dir: Path) -> None:
    assert gate_pause.approve_gate(plan_dir, "pre_impl", plan_id=PLAN_ID)
    # F1: pre_merge is only approvable while the pre_merge stage is pending.
    gate_pause.record_pause(plan_dir, plan_id=PLAN_ID, pause_gates=["pre_merge"], stage="pre_merge")
    assert gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=PLAN_ID)


# ───────────────────────────── AC(9) success ─────────────────────────────


def test_finalize_flips_passes_and_repairs_signoff(tmp_path):
    plan_dir = _plan_dir(tmp_path)
    _clear_pre_merge(plan_dir)
    assert not (plan_dir / "audit" / f"signoff-{PLAN_ID}.json").is_file()

    result = signed_off_finalizer.finalize_signed_off_feature(
        plan_dir, plan_id=PLAN_ID, feature_id="F001"
    )

    assert result.features_passes_flipped is True
    assert result.signoff_repaired is True
    assert result.already_finalized is False
    data = json.loads((plan_dir / "features.json").read_text())
    assert data["features"][0]["passes"] is True
    refs = data["features"][0].get("evidence_refs") or []
    # AC9: evidence_refs cite the signed_off AUDITOR artifact that authorized the
    # flip, alongside the signoff envelope.
    assert any("codex-auditor-F001-i0.json" in (r.get("uri") or "") for r in refs)
    assert any("signoff-" in (r.get("uri") or "") for r in refs)
    # signoff envelope now exists and validates as signed_off.
    signoff = json.loads(result.signoff_path.read_text())
    assert signoff["signoff"] is True


def test_finalize_uses_existing_signoff_without_clobber(tmp_path):
    plan_dir = _plan_dir(tmp_path)
    _clear_pre_merge(plan_dir)
    # DP-003: an existing signoff must be a VALID success signoff for the
    # selected verdict (an arbitrary stub is now refused — see
    # test_dp003_signoff_integrity.py); a valid one is still never clobbered.
    existing = signoff_writer.write_signoff(
        plan_id=PLAN_ID,
        tier="cross-cutting",
        iteration=0,
        agents_in_panel=["claude", "codex"],
        audit_paths=[plan_dir / "audit" / "codex-auditor-F001-i0.json"],
        plan_dir=plan_dir,
        volley_status="signed_off",
        signoff_reason="sentinel: preexisting",
    )
    before = existing.read_bytes()

    result = signed_off_finalizer.finalize_signed_off_feature(
        plan_dir, plan_id=PLAN_ID, feature_id="F001"
    )

    assert result.signoff_repaired is False
    # Existing envelope left byte-for-byte (sentinel preserved).
    assert existing.read_bytes() == before
    assert result.features_passes_flipped is True


# ───────────────────────── AC(10) refusal cases ──────────────────────────


def test_refuses_when_not_signed_off(tmp_path):
    plan_dir = _plan_dir(tmp_path, audit_status="needs_changes")
    _clear_pre_merge(plan_dir)
    with pytest.raises(signed_off_finalizer.FinalizeError) as exc:
        signed_off_finalizer.finalize_signed_off_feature(
            plan_dir, plan_id=PLAN_ID, feature_id="F001"
        )
    assert exc.value.code == "not_signed_off"
    # No mutation on refusal.
    data = json.loads((plan_dir / "features.json").read_text())
    assert data["features"][0]["passes"] is False


def test_refuses_when_pre_merge_uncleared(tmp_path):
    plan_dir = _plan_dir(tmp_path)  # signed_off but no gate cleared
    with pytest.raises(signed_off_finalizer.FinalizeError) as exc:
        signed_off_finalizer.finalize_signed_off_feature(
            plan_dir, plan_id=PLAN_ID, feature_id="F001"
        )
    assert exc.value.code == "pre_merge_uncleared"
    data = json.loads((plan_dir / "features.json").read_text())
    assert data["features"][0]["passes"] is False


def test_refuses_when_no_audit_envelope(tmp_path):
    plan_dir = _plan_dir(tmp_path)
    _clear_pre_merge(plan_dir)
    # Remove the auditor envelope -> no audit history.
    (plan_dir / "audit" / "codex-auditor-F001-i0.json").unlink()
    with pytest.raises(signed_off_finalizer.FinalizeError) as exc:
        signed_off_finalizer.finalize_signed_off_feature(
            plan_dir, plan_id=PLAN_ID, feature_id="F001"
        )
    assert exc.value.code == "no_audit"


def test_refusal_codes_are_distinct(tmp_path):
    """Each refusal maps to a distinct code so the CLI can use distinct exits."""
    codes = set()

    p1 = _plan_dir(tmp_path / "a", audit_status="needs_changes")
    _clear_pre_merge(p1)
    with pytest.raises(signed_off_finalizer.FinalizeError) as e1:
        signed_off_finalizer.finalize_signed_off_feature(p1, plan_id=PLAN_ID, feature_id="F001")
    codes.add(e1.value.code)

    p2 = _plan_dir(tmp_path / "b")  # uncleared
    with pytest.raises(signed_off_finalizer.FinalizeError) as e2:
        signed_off_finalizer.finalize_signed_off_feature(p2, plan_id=PLAN_ID, feature_id="F001")
    codes.add(e2.value.code)

    p3 = _plan_dir(tmp_path / "c")
    _clear_pre_merge(p3)
    (p3 / "audit" / "codex-auditor-F001-i0.json").unlink()
    with pytest.raises(signed_off_finalizer.FinalizeError) as e3:
        signed_off_finalizer.finalize_signed_off_feature(p3, plan_id=PLAN_ID, feature_id="F001")
    codes.add(e3.value.code)

    assert codes == {"not_signed_off", "pre_merge_uncleared", "no_audit"}


# ───────────────────────── AC(11) idempotency ────────────────────────────


def test_idempotent_rerun_is_noop(tmp_path):
    plan_dir = _plan_dir(tmp_path)
    _clear_pre_merge(plan_dir)
    first = signed_off_finalizer.finalize_signed_off_feature(
        plan_dir, plan_id=PLAN_ID, feature_id="F001"
    )
    assert first.features_passes_flipped is True

    second = signed_off_finalizer.finalize_signed_off_feature(
        plan_dir, plan_id=PLAN_ID, feature_id="F001"
    )
    assert second.features_passes_flipped is False
    assert second.signoff_repaired is False
    assert second.already_finalized is True
    # passes stays true; file content stable across the no-op re-run.
    data = json.loads((plan_dir / "features.json").read_text())
    assert data["features"][0]["passes"] is True


# ───────────────────────── AC(12) no paid calls ──────────────────────────


def test_finalizer_never_invokes_dispatch_volley(tmp_path, monkeypatch):
    """The finalizer must not trigger a fresh (paid) volley. We boobytrap the
    supervisor entrypoint and assert it is never reached."""
    import dontpanic_orchestrate.supervisor as supervisor

    def _boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("finalizer invoked dispatch_volley (paid call)")

    monkeypatch.setattr(supervisor, "dispatch_volley", _boom, raising=False)

    plan_dir = _plan_dir(tmp_path)
    _clear_pre_merge(plan_dir)
    result = signed_off_finalizer.finalize_signed_off_feature(
        plan_dir, plan_id=PLAN_ID, feature_id="F001"
    )
    assert result.features_passes_flipped is True
