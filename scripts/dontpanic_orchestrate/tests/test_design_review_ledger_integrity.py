"""Design-review convergence ledger: only completed reviews advance it, plan-level
findings are never dropped, dependents of changed features stay in scope, and
the ledger is bound to its inputs (Sentinel r2 MED 3 + MED 4, probes P1-P5).

The invariant every test protects: an unchanged re-lock may only return
``signed_off`` with ZERO reviewer calls when the last review really signed off
with no open findings, for this plan, contract, reviewer and prompt version.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate.plan_review import design_review as dr
from dontpanic_orchestrate.tests.test_design_review_convergence import (
    _FEATURES,
    _CodexLikeReviewer,
    _feature,
    _finding,
    _hermetic_codex_home,  # noqa: F401 — autouse fixture: tmp CODEX_HOME
    _ledger,
    _lock_volley,
    _make_plan,
    _write_features,
)

PID = "2026-11-23-901-feat-converge"
_SIGNED = {"verdict": "signed_off", "findings": []}


def _ledger_path(plan_dir: Path) -> Path:
    return plan_dir / dr.LEDGER_RELPATH


class _RawReviewer(_CodexLikeReviewer):
    """Returns ``summary`` verbatim (to emit unparseable / odd envelopes)."""

    def __init__(self, summaries: list[str], *, success: bool = True) -> None:
        super().__init__([{}])
        self._summaries = list(summaries)
        self._success = success

    def dispatch(self, task):  # type: ignore[override]
        result = super().dispatch(task)
        result.summary = self._summaries[min(self.calls - 1, len(self._summaries) - 1)]
        result.raw_response = result.summary
        result.success = self._success
        return result


def _assert_unchanged_relock_dispatches(plan_dir: Path) -> str:
    second = _CodexLikeReviewer([_SIGNED])
    out = _lock_volley(plan_dir, second)
    assert second.calls >= 1, out
    assert "unchanged since last full review" not in out
    return out


# ─────────────────────── MED 3: only completed reviews advance ──────────────


@pytest.mark.parametrize(
    "summary",
    [
        json.dumps({"verdict": "APPROVED", "findings": []}),  # P1 coerced
        json.dumps({"verdict": "blocked", "findings": []}),  # P2 blocked
        "I could not decide.",  # parse failure
    ],
    ids=["invalid_verdict", "blocked_no_findings", "unparseable"],
)
def test_non_completed_review_never_writes_ledger(tmp_path: Path, summary: str) -> None:
    plan_dir = _make_plan(tmp_path, _FEATURES)
    out = _lock_volley(plan_dir, _RawReviewer([summary]))
    assert "verdict=blocked" in out
    assert not _ledger_path(plan_dir).exists()
    _assert_unchanged_relock_dispatches(plan_dir)


def test_dispatch_failure_never_writes_ledger(tmp_path: Path) -> None:
    plan_dir = _make_plan(tmp_path, _FEATURES)
    _lock_volley(plan_dir, _RawReviewer([json.dumps(_SIGNED)], success=False))
    assert not _ledger_path(plan_dir).exists()
    _assert_unchanged_relock_dispatches(plan_dir)


def test_blocked_review_does_not_advance_an_existing_ledger(tmp_path: Path) -> None:
    plan_dir = _make_plan(tmp_path, _FEATURES)
    _lock_volley(plan_dir, _CodexLikeReviewer([_SIGNED]))
    changed = [*_FEATURES[:2], _feature("F010", "a small helper for retries with jitter")]
    _write_features(plan_dir, PID, changed)
    before = _ledger_path(plan_dir).read_bytes()
    blocked = _RawReviewer([json.dumps({"verdict": "blocked", "findings": []})])
    _lock_volley(plan_dir, blocked)
    assert blocked.calls == 1
    assert _ledger_path(plan_dir).read_bytes() == before
    # F010 is still changed relative to the last COMPLETED review.
    again = _CodexLikeReviewer([_SIGNED])
    out = _lock_volley(plan_dir, again)
    assert again.calls == 1 and "F010 (changed)" in out


def test_p3_plan_level_finding_is_kept_and_forces_full_review(tmp_path: Path) -> None:
    plan_dir = _make_plan(tmp_path, _FEATURES)
    plan_finding = _finding("(plan)", "hidden_coupling", "block")
    _lock_volley(
        plan_dir, _CodexLikeReviewer([{"verdict": "needs_changes", "findings": [plan_finding]}])
    )
    assert _ledger(plan_dir)["open_findings"] == [plan_finding]
    out = _assert_unchanged_relock_dispatches(plan_dir)
    assert "design-review scope: full" in out
    assert "plan-level" in out


def test_plan_level_finding_in_a_scoped_review_stays_in_findings() -> None:
    scope = dr.ReviewScope(
        mode="scoped", in_scope=("F010",), changed=("F010",), feature_ids=("F002", "F009", "F010")
    )
    reviewer = _CodexLikeReviewer(
        [{"verdict": "needs_changes", "findings": [_finding("(plan)"), _finding("F002", "oversize")]}]
    )
    env = dr.run_design_volley("p1", _FEATURES, auditor=reviewer, scope=scope)
    assert [f.feature_id for f in env.findings] == ["(plan)"]
    assert env.verdict == "needs_changes"


def test_two_failing_blocked_verdict_and_tampered_ledger_full_review(tmp_path: Path) -> None:
    plan_dir = _make_plan(tmp_path, _FEATURES)
    _lock_volley(plan_dir, _CodexLikeReviewer([_SIGNED]))
    blob = _ledger(plan_dir)
    blob["open_findings"] = []
    blob["verdict"] = "signed_off"
    blob["reviewed_at"] = "tampered"
    blob["feature_hashes"]["F009"] = "0" * 64  # digest no longer matches
    _ledger_path(plan_dir).write_text(json.dumps(blob))
    blocked = _RawReviewer([json.dumps({"verdict": "blocked", "findings": []})])
    out = _lock_volley(plan_dir, blocked)
    assert blocked.calls == 1
    assert "ledger ignored (ledger digest mismatch" in out
    assert "design-review scope: full" in out
    assert json.loads(_ledger_path(plan_dir).read_text()) == blob  # blocked wrote nothing
    _assert_unchanged_relock_dispatches(plan_dir)


# ───────────── MED 4: dependents of changed features stay in scope ──────────


def _chain() -> list[dict]:
    f1 = _feature("F001", "a small helper for dispatch order")
    f2 = {**_feature("F002", "a small helper for the jobs lock"), "depends_on": ["F001"]}
    f3 = {**_feature("F003", "a small helper for retries"), "depends_on": ["F002"]}
    f4 = _feature("F004", "an unrelated helper")
    return [f1, f2, f3, f4]


def test_p4_finding_on_dependent_of_changed_feature_is_kept(tmp_path: Path) -> None:
    feats = _chain()
    plan_dir = _make_plan(tmp_path, feats)
    _lock_volley(plan_dir, _CodexLikeReviewer([_SIGNED]))
    changed = [{**feats[0], "description": "a small helper for dispatch order CHANGED"}, *feats[1:]]
    _write_features(plan_dir, PID, changed)
    reviewer = _CodexLikeReviewer(
        [
            {
                "verdict": "needs_changes",
                "findings": [_finding("F002", severity="high"), _finding("F004", "oversize")],
            }
        ]
    )
    out = _lock_volley(plan_dir, reviewer)
    assert reviewer.calls == 1
    assert "F002,F003 (depends on changed)" in out
    assert "verdict=needs_changes" in out
    ledger = _ledger(plan_dir)
    assert ledger["open_findings"] == [_finding("F002", severity="high")]
    assert ledger["out_of_scope_history"][-1]["findings"] == [_finding("F004", "oversize")]


def test_compute_scope_pulls_transitive_dependents_of_changed() -> None:
    feats = _chain()
    ledger = {
        "feature_hashes": {f["id"]: dr.feature_hash(f) for f in feats},
        "verdict": "signed_off",
        "open_findings": [],
    }
    changed = [{**feats[0], "description": "x"}, *feats[1:]]
    scope = dr.compute_scope(changed, ledger)
    assert scope.changed == ("F001",)
    assert scope.dependents == ("F002", "F003")
    assert set(scope.in_scope) == {"F001", "F002", "F003"}


def test_needs_changes_ledger_never_takes_the_zero_call_shortcut() -> None:
    ledger = {
        "feature_hashes": {f["id"]: dr.feature_hash(f) for f in _FEATURES},
        "verdict": "needs_changes",
        "open_findings": [],
    }
    scope = dr.compute_scope(_FEATURES, ledger)
    assert scope.mode == "full"
    assert not scope.nothing_to_review


# ─────────────────────── MED 4: ledger bound to its inputs ──────────────────


def test_p5_hand_written_ledger_never_yields_zero_call_signoff(tmp_path: Path) -> None:
    plan_dir = _make_plan(tmp_path, _FEATURES)
    _ledger_path(plan_dir).parent.mkdir(parents=True)
    _ledger_path(plan_dir).write_text(
        json.dumps(
            {"feature_hashes": {f["id"]: dr.feature_hash(f) for f in _FEATURES}, "open_findings": []}
        )
    )
    out = _assert_unchanged_relock_dispatches(plan_dir)
    assert "ledger ignored (ledger fields differ" in out


def _good_ledger(tmp_path: Path) -> Path:
    plan_dir = _make_plan(tmp_path, _FEATURES)
    _lock_volley(plan_dir, _CodexLikeReviewer([_SIGNED]))
    # Sanity: a genuine ledger does take the zero-call shortcut.
    shortcut = _CodexLikeReviewer([_SIGNED])
    assert "unchanged since last full review" in _lock_volley(plan_dir, shortcut)
    assert shortcut.calls == 0
    return plan_dir


def _rewrite(plan_dir: Path, mutate, *, redigest: bool) -> None:
    blob = _ledger(plan_dir)
    mutate(blob)
    if redigest:
        blob["digest"] = dr._ledger_digest(blob)
    _ledger_path(plan_dir).write_text(json.dumps(blob))


@pytest.mark.parametrize(
    ("mutate", "redigest", "reason"),
    [
        (lambda b: b.update(verdict="signed_off", open_findings=[_finding("F002")]), False, "digest mismatch"),
        (lambda b: b.update(plan_id="2026-01-01-001-other"), True, "ledger is for plan"),
        (lambda b: b.update(schema=1), True, "ledger schema"),
        (lambda b: b["feature_hashes"].update(F002=123), True, "feature_hashes"),
        (lambda b: b.update(extra="x"), True, "unknown=['extra']"),
        (lambda b: b.pop("reviewer"), False, "missing=['reviewer']"),
        (lambda b: b.update(reviewer={"agent": "claude", "model": None}), True, "reviewer changed"),
        (lambda b: b.update(prompt_version="design-review-prompt-0"), True, "prompt version changed"),
        (lambda b: b.update(verdict="blocked"), True, "not a completed review"),
        (lambda b: b.update(open_findings=[{"kind": 1}]), True, "open_findings"),
        (lambda b: b.update(objective_contract_digest="zz"), True, "objective_contract_digest"),
    ],
    ids=[
        "digest",
        "plan_id",
        "schema",
        "field_type",
        "unknown_field",
        "missing_field",
        "reviewer",
        "prompt_version",
        "verdict_blocked",
        "finding_shape",
        "contract_digest_shape",
    ],
)
def test_bad_or_unbound_ledger_forces_full_review(
    tmp_path: Path, mutate, redigest: bool, reason: str
) -> None:
    plan_dir = _good_ledger(tmp_path)
    _rewrite(plan_dir, mutate, redigest=redigest)
    out = _assert_unchanged_relock_dispatches(plan_dir)
    assert "ledger ignored (" in out and reason in out, out
    assert "design-review scope: full" in out


def test_objective_contract_change_forces_full_review(tmp_path: Path) -> None:
    plan_dir = _good_ledger(tmp_path)
    (plan_dir / "objective_contract.json").write_text(json.dumps({"goal": "new"}))
    out = _assert_unchanged_relock_dispatches(plan_dir)
    assert "objective_contract.json changed" in out


def test_reviewer_model_change_forces_full_review(tmp_path: Path) -> None:
    plan_dir = _good_ledger(tmp_path)
    other = _CodexLikeReviewer([_SIGNED])
    other.model = "gpt-other"
    out = _lock_volley(plan_dir, other)
    assert other.calls == 1
    assert "reviewer changed" in out


def test_prompt_version_bump_forces_full_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _good_ledger(tmp_path)
    monkeypatch.setattr(dr, "PROMPT_VERSION", dr.PROMPT_VERSION + "-next")
    out = _assert_unchanged_relock_dispatches(plan_dir)
    assert "prompt version changed" in out


def test_two_failing_forged_ledger_and_blocked_verdict(tmp_path: Path) -> None:
    """A forged (re-digested, fully well-formed) ledger for ANOTHER reviewer +
    a blocked verdict: full review, and the blocked run writes nothing."""
    plan_dir = _good_ledger(tmp_path)
    _rewrite(plan_dir, lambda b: b.update(reviewer={"agent": "forger", "model": None}), redigest=True)
    before = _ledger_path(plan_dir).read_bytes()
    blocked = _RawReviewer([json.dumps({"verdict": "blocked", "findings": []})])
    out = _lock_volley(plan_dir, blocked)
    assert blocked.calls == 1
    assert "design-review scope: full" in out
    assert _ledger_path(plan_dir).read_bytes() == before
    _assert_unchanged_relock_dispatches(plan_dir)


def test_ledger_records_its_binding(tmp_path: Path) -> None:
    plan_dir = _make_plan(tmp_path, _FEATURES)
    (plan_dir / "objective_contract.json").write_text(json.dumps({"goal": "g"}))
    _lock_volley(plan_dir, _CodexLikeReviewer([_SIGNED]))
    blob = _ledger(plan_dir)
    assert blob["plan_id"] == PID
    assert blob["reviewer"] == {"agent": "codex", "model": "gpt-test-reviewer"}
    assert blob["prompt_version"] == dr.PROMPT_VERSION
    assert blob["objective_contract_digest"] == dr.objective_contract_digest({"goal": "g"})
    assert blob["verdict"] == "signed_off"
    assert blob["digest"] == dr._ledger_digest(blob)
