"""Plan 2026-05-30-002 F002 — latest-auditor-envelope selection is mtime-aware.

The bug (D028, surfaced dogfooding 2026-05-30-001): re-dispatching a feature
reuses the ``<vendor>-auditor-<FNNN>-iN.json`` filename per iteration. A later
run with FEWER iterations leaves a higher-index *stale* envelope on disk. The
finalizer / closeout-memo selected "latest" by iteration INDEX
(``reversed(audit_paths)`` → highest ``iN``), so a stale ``i1 needs_changes``
from a superseded run outranked a fresh ``i0 signed_off`` — mislabeling
``latest_audit_status`` and refusing a valid finalize.

Fix: ``_latest_auditor_envelope`` ranks auditor envelopes by modification time
(freshest wins), with iteration index as the tie-break. The common cases are
unchanged: a single envelope returns itself; a monotonic run (i0,i1,i2 written
in order) still resolves to the highest index because mtime increases with it.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f002_latest_envelope_freshness.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dontpanic_orchestrate import closeout, gate_pause, signed_off_finalizer

PLAN_ID = "2026-05-30-f002-demo"


def _write_auditor(
    audit_dir: Path, feature_id: str, iteration: int, *, status: str, mtime: float
) -> Path:
    audit_dir.mkdir(parents=True, exist_ok=True)
    p = audit_dir / f"codex-auditor-{feature_id}-i{iteration}.json"
    p.write_text(json.dumps({
        "audit_id": f"{PLAN_ID}#codex#{iteration}",
        "agent": "codex",
        "agent_role": "auditor",
        "iteration": iteration,
        "audit_status": status,
        "findings": [],
        "summary": f"verdict {status} at i{iteration}",
    }))
    os.utime(p, (mtime, mtime))
    return p


# ────────────────────────── unit: selection chokepoint ──────────────────────────


def test_latest_envelope_prefers_fresh_low_index_over_stale_high_index(tmp_path):
    """THE D028 case: stale i1 needs_changes (old mtime) + fresh i0 signed_off
    (new mtime). Index-based selection picks i1; mtime-based picks i0."""
    audit_dir = tmp_path / "audit"
    _write_auditor(audit_dir, "F001", 1, status="needs_changes", mtime=1000.0)
    _write_auditor(audit_dir, "F001", 0, status="signed_off", mtime=2000.0)
    paths = closeout._audit_paths_for_feature(tmp_path, "F001")
    env = closeout._latest_auditor_envelope(paths)
    assert env is not None
    assert env["audit_status"] == "signed_off", (
        f"fresh i0 signed_off must outrank stale i1 needs_changes; got {env!r}"
    )
    assert env["iteration"] == 0


def test_latest_envelope_monotonic_run_picks_highest_index(tmp_path):
    """Common case preserved: a monotonic run (i0<i1<i2 in both mtime and
    index) resolves to the highest index — identical to pre-fix behavior."""
    audit_dir = tmp_path / "audit"
    _write_auditor(audit_dir, "F001", 0, status="needs_changes", mtime=1000.0)
    _write_auditor(audit_dir, "F001", 1, status="needs_changes", mtime=2000.0)
    _write_auditor(audit_dir, "F001", 2, status="signed_off", mtime=3000.0)
    paths = closeout._audit_paths_for_feature(tmp_path, "F001")
    env = closeout._latest_auditor_envelope(paths)
    assert env is not None
    assert env["iteration"] == 2
    assert env["audit_status"] == "signed_off"


def test_latest_envelope_single_returns_it(tmp_path):
    audit_dir = tmp_path / "audit"
    _write_auditor(audit_dir, "F001", 0, status="signed_off", mtime=1000.0)
    paths = closeout._audit_paths_for_feature(tmp_path, "F001")
    env = closeout._latest_auditor_envelope(paths)
    assert env is not None
    assert env["iteration"] == 0
    assert env["audit_status"] == "signed_off"


def test_latest_envelope_mtime_tie_breaks_by_higher_index(tmp_path):
    """When two auditor envelopes share an identical mtime (coarse filesystem /
    same-second writes), the higher iteration index wins — preserving pre-fix
    behavior so a true monotonic run is never mis-ranked on a tie."""
    audit_dir = tmp_path / "audit"
    _write_auditor(audit_dir, "F001", 0, status="needs_changes", mtime=1500.0)
    _write_auditor(audit_dir, "F001", 1, status="signed_off", mtime=1500.0)
    paths = closeout._audit_paths_for_feature(tmp_path, "F001")
    env = closeout._latest_auditor_envelope(paths)
    assert env is not None
    assert env["iteration"] == 1
    assert env["audit_status"] == "signed_off"


def test_latest_envelope_none_when_no_auditor(tmp_path):
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "claude-implementer-F001-i0.json").write_text(
        json.dumps({"agent": "claude", "agent_role": "implementer", "iteration": 0})
    )
    paths = closeout._audit_paths_for_feature(tmp_path, "F001")
    assert closeout._latest_auditor_envelope(paths) is None


# ────────────────────────── integration: finalizer ──────────────────────────


def test_finalize_uses_fresh_low_index_signed_off(tmp_path):
    """End-to-end: a stale i1 needs_changes + fresh i0 signed_off must let the
    no-paid finalizer flip passes:true, because the true latest verdict is
    signed_off. Pre-fix this refused with not_signed_off."""
    plan_dir = tmp_path / "docs" / "plans" / PLAN_ID
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        f"---\nid: {PLAN_ID}\ntier: cross-cutting\nstatus: active\n---\n# Demo\n"
    )
    (plan_dir / "features.json").write_text(json.dumps({
        "task_id": PLAN_ID,
        "schema_version": "1.0",
        "features": [{"id": "F001", "title": "Demo", "passes": False}],
    }, indent=2) + "\n")
    audit_dir = plan_dir / "audit"
    (audit_dir / "claude-implementer-F001-i0.json").parent.mkdir(parents=True, exist_ok=True)
    (audit_dir / "claude-implementer-F001-i0.json").write_text(
        json.dumps({"agent": "claude", "agent_role": "implementer", "iteration": 0})
    )
    _write_auditor(audit_dir, "F001", 1, status="needs_changes", mtime=1000.0)
    _write_auditor(audit_dir, "F001", 0, status="signed_off", mtime=2000.0)

    gate_pause.approve_gate(plan_dir, "pre_impl", plan_id=PLAN_ID)
    gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=PLAN_ID)

    result = signed_off_finalizer.finalize_signed_off_feature(
        plan_dir, plan_id=PLAN_ID, feature_id="F001"
    )
    assert result.features_passes_flipped is True, (
        f"finalize should flip passes on fresh signed_off; got {result!r}"
    )

    features = json.loads((plan_dir / "features.json").read_text())
    f001 = next(f for f in features["features"] if f["id"] == "F001")
    assert f001["passes"] is True
