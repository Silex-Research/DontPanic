"""Kill two mutants that survived the r3/r4 related test set (Thanos 17:11 CT).

1. ``gate_pause._has_feature_approval_event``: the approval EVENT must carry
   the feature's current ``feature_revision``, not just the right plan id. An
   entry whose ``completed_stage_bindings`` is current but whose only event
   is bound to a stale revision is not a completion.
2. ``design_review._ledger_digest``: ``out_of_scope_history`` is a digested
   field. Hand-editing it without recomputing the digest makes the ledger
   unusable, so the next lock runs a full review.
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import gate_pause
from dontpanic_orchestrate.plan_review import design_review as dr
from dontpanic_orchestrate.tests.test_design_review_convergence import (
    _FEATURES,
    _CodexLikeReviewer,
    _hermetic_codex_home,  # noqa: F401 — autouse fixture: tmp CODEX_HOME
    _ledger,
    _lock_volley,
    _make_plan,
)

_PLAN_ID = "2026-11-24-901-feat-mutants"
_SIGNED = {"verdict": "signed_off", "findings": []}


# ───────────── 1. approval event must match the current feature_revision ─────


def _write_features(plan_dir: Path) -> None:
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": _PLAN_ID,
                "features": [{"id": "F001", "title": "one", "acceptance": ["a"], "passes": False}],
            }
        )
    )


def _write_bound_state(plan_dir: Path, event_revision: str | None) -> None:
    """F001 listed complete with the CURRENT binding in
    ``completed_stage_bindings``; its only approval event carries the right
    plan id and ``event_revision``."""
    binding = gate_pause.approval_binding(plan_dir, "F001")
    state = {
        "plan_id": _PLAN_ID,
        "cleared_gates": ["pre_merge"],
        "completed_stages": ["pre_merge"],
        "completed_stage_features": {"pre_merge": ["F001"]},
        "completed_stage_bindings": {"pre_merge": {"F001": dict(binding)}},
        "gate_events": [
            {
                "gate": "pre_merge",
                "stage": "pre_merge",
                "cleared_at": "x",
                "cleared_by": "operator",
                "feature_id": "F001",
                "plan_id": binding["plan_id"],
                "feature_revision": event_revision,
            }
        ],
        "history": [],
    }
    path = gate_pause.gate_state_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")


def test_event_with_stale_feature_revision_is_not_a_completion(tmp_path: Path) -> None:
    _write_features(tmp_path)
    binding = gate_pause.approval_binding(tmp_path, "F001")
    assert binding["plan_id"] == _PLAN_ID and binding["feature_revision"]
    stale = "0" * 64
    assert stale != binding["feature_revision"]
    _write_bound_state(tmp_path, event_revision=stale)
    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F001") is False


def test_guard_event_with_current_feature_revision_is_a_completion(tmp_path: Path) -> None:
    _write_features(tmp_path)
    binding = gate_pause.approval_binding(tmp_path, "F001")
    _write_bound_state(tmp_path, event_revision=binding["feature_revision"])
    assert gate_pause.is_stage_completed(tmp_path, "pre_merge", feature_id="F001") is True


# ───────────── 2. out_of_scope_history is bound by the ledger digest ─────────


def test_hand_edited_out_of_scope_history_forces_full_review(tmp_path: Path) -> None:
    plan_dir = _make_plan(tmp_path, _FEATURES)
    _lock_volley(plan_dir, _CodexLikeReviewer([_SIGNED]))
    shortcut = _CodexLikeReviewer([_SIGNED])
    assert "unchanged since last full review" in _lock_volley(plan_dir, shortcut)
    assert shortcut.calls == 0  # the untouched ledger is reusable

    blob = _ledger(plan_dir)
    history = blob["out_of_scope_history"]
    assert isinstance(history, list)
    history.append(
        {
            "reviewed_at": "2026-01-01T00:00:00+00:00",
            "findings": [{"feature_id": "F001", "kind": "oversize", "detail": "hand-added"}],
        }
    )
    # Digest NOT recomputed: only out_of_scope_history differs.
    (plan_dir / dr.LEDGER_RELPATH).write_text(json.dumps(blob))
    assert dr._structure_error(blob) is None  # still structurally valid

    second = _CodexLikeReviewer([_SIGNED])
    out = _lock_volley(plan_dir, second)
    assert second.calls >= 1, out
    assert "unchanged since last full review" not in out
    assert "ledger ignored (ledger digest mismatch" in out, out
    assert "design-review scope: full" in out
