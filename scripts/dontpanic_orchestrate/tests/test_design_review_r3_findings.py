"""Sentinel review 6035083658 on the design-review convergence ledger.

MED-A: a ``hidden_coupling`` finding (a dependency MISSING from depends_on) on
an unchanged feature is never demoted to out_of_scope, and a run that demoted
any finding never enables the zero-call shortcut on the next lock.
MED-B: the ledger binds the reviewer's REAL model (DispatchTask model, else the
Codex run's rollout ``turn_context.model``, else Codex's config default); a
null model is never reusable.
MED-D: a review with an unrecognized finding kind or a non-list ``findings`` is
not a completed review: the ledger is not written/advanced and the lock prints
the unrecognized items.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate.plan_review import design_review as dr
from dontpanic_orchestrate.tests.test_design_review_convergence import (
    _CodexLikeReviewer,
    _feature,
    _finding,
    _ledger,
    _lock_volley,
    _make_plan,
    _write_features,
)

PID = "2026-11-24-903-feat-converge"
_SIGNED = {"verdict": "signed_off", "findings": []}


@pytest.fixture(autouse=True)
def codex_home(tmp_path_factory, monkeypatch) -> Path:
    home = tmp_path_factory.mktemp("codex-home")
    (home / "config.toml").write_text('model = "gpt-cfg"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def _ledger_path(plan_dir: Path) -> Path:
    return plan_dir / dr.LEDGER_RELPATH


def _three() -> list[dict]:
    f1 = _feature("F001", "a small helper for dispatch order")
    f2 = {**_feature("F002", "a small helper for the jobs lock"), "depends_on": ["F001"]}
    f3 = _feature("F003", "a small helper for retries")
    return [f1, f2, f3]


def _change_f001(plan_dir: Path, feats: list[dict]) -> list[dict]:
    changed = [{**feats[0], "description": "a small helper for dispatch order CHANGED"}, *feats[1:]]
    _write_features(plan_dir, PID, changed)
    return changed


def _relock_calls(plan_dir: Path) -> tuple[int, str]:
    again = _CodexLikeReviewer([_SIGNED])
    out = _lock_volley(plan_dir, again)
    return again.calls, out


# ───────────────────────────────── MED-A ────────────────────────────────────


def test_med_a_hidden_coupling_on_unchanged_feature_is_not_demoted(tmp_path: Path) -> None:
    feats = _three()
    plan_dir = _make_plan(tmp_path, feats, PID)
    _lock_volley(plan_dir, _CodexLikeReviewer([_SIGNED]))
    _change_f001(plan_dir, feats)
    coupling = _finding("F003", "hidden_coupling", "block")
    reviewer = _CodexLikeReviewer([{"verdict": "needs_changes", "findings": [coupling]}])
    out = _lock_volley(plan_dir, reviewer)
    assert reviewer.calls == 1
    assert "verdict=needs_changes" in out, out
    assert "downgraded" not in out
    assert _ledger(plan_dir)["open_findings"] == [coupling]
    assert _ledger(plan_dir)["verdict"] == "needs_changes"
    calls, out2 = _relock_calls(plan_dir)
    assert calls >= 1, out2


def test_med_a_demoted_non_coupling_finding_blocks_zero_call_shortcut(tmp_path: Path) -> None:
    feats = _three()
    plan_dir = _make_plan(tmp_path, feats, PID)
    _lock_volley(plan_dir, _CodexLikeReviewer([_SIGNED]))
    _change_f001(plan_dir, feats)
    advisory = _finding("F003", "oversize", "warn")
    reviewer = _CodexLikeReviewer([{"verdict": "needs_changes", "findings": [advisory]}])
    out = _lock_volley(plan_dir, reviewer)
    assert "verdict=signed_off" in out and "downgraded" in out, out
    assert _ledger(plan_dir)["open_findings"] == []
    calls, out2 = _relock_calls(plan_dir)
    assert calls >= 1, out2
    assert "demoted 1 finding(s)" in out2, out2
    # That full review signed off with nothing demoted: now the shortcut applies.
    calls3, out3 = _relock_calls(plan_dir)
    assert calls3 == 0, out3


def test_med_a_missing_prereq_on_unchanged_upstream_prerequisite_is_not_demoted(
    tmp_path: Path,
) -> None:
    """Sentinel's second MED-A case: F002 depends_on F001; only F002 changes;
    the reviewer raises missing_prereq on the UNCHANGED upstream F001. F001 is
    a prerequisite of a changed feature, so it is in scope: the finding stays,
    the verdict stays needs_changes, it is recorded open, and the next
    unchanged lock dispatches."""
    feats = _three()
    plan_dir = _make_plan(tmp_path, feats, PID)
    _lock_volley(plan_dir, _CodexLikeReviewer([_SIGNED]))
    changed = [feats[0], {**feats[1], "description": "a small helper for the jobs lock CHANGED"}, feats[2]]
    _write_features(plan_dir, PID, changed)
    prereq = _finding("F001", "missing_prereq", "block")
    reviewer = _CodexLikeReviewer([{"verdict": "needs_changes", "findings": [prereq]}])
    out = _lock_volley(plan_dir, reviewer)
    assert reviewer.calls == 1
    assert "verdict=needs_changes" in out, out
    assert "downgraded" not in out, out
    assert _ledger(plan_dir)["verdict"] == "needs_changes"
    assert _ledger(plan_dir)["open_findings"] == [prereq]
    calls, out2 = _relock_calls(plan_dir)
    assert calls >= 1, out2


# ───────────────────────────────── MED-B ────────────────────────────────────


class _BareCodex(_CodexLikeReviewer):
    """Like CodexCLIExecutor: no ``model`` attribute."""


def _write_rollout(home: Path, thread_id: str, model: str) -> Path:
    day = home / "sessions" / "2026" / "11" / "24"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-2026-11-24T00-00-00-{thread_id}.jsonl"
    lines = [
        {"type": "session_meta", "payload": {"id": thread_id}},
        {"type": "turn_context", "payload": {"model": model, "cwd": "/x"}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return path


def test_med_b_codex_executor_has_no_model_attribute() -> None:
    from dontpanic_orchestrate.executors.codex_cli import CodexCLIExecutor

    assert getattr(CodexCLIExecutor(), "model", None) is None


def test_med_b_ledger_records_model_from_codex_rollout(tmp_path: Path, codex_home: Path) -> None:
    _write_rollout(codex_home, "t-1", "gpt-rollout")  # _codex_stream's thread id
    plan_dir = _make_plan(tmp_path, _three(), PID)
    _lock_volley(plan_dir, _BareCodex([_SIGNED]))
    assert _ledger(plan_dir)["reviewer"] == {"agent": "codex", "model": "gpt-rollout"}


def test_med_b_ledger_records_config_default_without_rollout(tmp_path: Path) -> None:
    plan_dir = _make_plan(tmp_path, _three(), PID)
    _lock_volley(plan_dir, _BareCodex([_SIGNED]))
    assert _ledger(plan_dir)["reviewer"] == {"agent": "codex", "model": "gpt-cfg"}
    calls, out = _relock_calls(plan_dir)
    assert calls == 0, out  # same model, unchanged plan: reusable


def test_med_b_task_model_wins(codex_home: Path) -> None:
    _write_rollout(codex_home, "t-1", "gpt-rollout")
    assert dr.resolve_reviewer_model(_BareCodex([]), task_model="gpt-task") == "gpt-task"
    stream = json.dumps({"type": "thread.started", "thread_id": "t-1"})
    assert dr.resolve_reviewer_model(_BareCodex([]), raw_response=stream) == "gpt-rollout"
    assert dr.resolve_reviewer_model(_BareCodex([])) == "gpt-cfg"


def test_med_b_model_change_between_locks_forces_full_review(
    tmp_path: Path, codex_home: Path
) -> None:
    plan_dir = _make_plan(tmp_path, _three(), PID)
    _lock_volley(plan_dir, _BareCodex([_SIGNED]))
    (codex_home / "config.toml").write_text('model = "gpt-other"\n')
    second = _BareCodex([_SIGNED])
    out = _lock_volley(plan_dir, second)
    assert second.calls == 1, out
    assert "reviewer changed" in out and "design-review scope: full" in out
    assert _ledger(plan_dir)["reviewer"]["model"] == "gpt-other"


def test_med_b_null_model_ledger_forces_full_review(tmp_path: Path, codex_home: Path) -> None:
    (codex_home / "config.toml").unlink()
    plan_dir = _make_plan(tmp_path, _three(), PID)
    _lock_volley(plan_dir, _BareCodex([_SIGNED]))
    assert _ledger(plan_dir)["reviewer"] == {"agent": "codex", "model": None}
    second = _BareCodex([_SIGNED])
    out = _lock_volley(plan_dir, second)
    assert second.calls == 1, out
    assert "null-model ledger is not reusable" in out


@pytest.mark.parametrize("thread_id", ["../../etc", "a/b", "*", ""])
def test_med_b_rollout_lookup_rejects_odd_thread_ids(codex_home: Path, thread_id: str) -> None:
    assert dr.codex_rollout_model(codex_home, thread_id) is None


def test_med_b_config_model_reads_top_level_only(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        '# c\nmodel_provider = "x"\n[profiles.fast]\nmodel = "gpt-profile"\n'
    )
    assert dr.codex_config_model(tmp_path) is None
    (tmp_path / "config.toml").write_text('model = "gpt-top" # default\n[p]\nmodel = "z"\n')
    assert dr.codex_config_model(tmp_path) == "gpt-top"


# ───────────────────────────────── MED-D ────────────────────────────────────


_UNRECOGNIZED = {
    "verdict": "signed_off",
    "findings": [
        {"kind": "security_gap", "severity": "block", "feature_id": "F001", "evidence": "leak"}
    ],
}
_STRING_FINDINGS = {"verdict": "signed_off", "findings": "F001 has a hidden coupling"}


@pytest.mark.parametrize(
    ("envelope", "printed"),
    [(_UNRECOGNIZED, "security_gap"), (_STRING_FINDINGS, "F001 has a hidden coupling")],
    ids=["unrecognized_kind", "findings_not_a_list"],
)
def test_med_d_malformed_findings_never_write_the_ledger(
    tmp_path: Path, envelope: dict, printed: str
) -> None:
    plan_dir = _make_plan(tmp_path, _three(), PID)
    out = _lock_volley(plan_dir, _CodexLikeReviewer([envelope]))
    assert not _ledger_path(plan_dir).exists(), out
    assert "unrecognized" in out and printed in out, out
    calls, out2 = _relock_calls(plan_dir)
    assert calls >= 1, out2


@pytest.mark.parametrize("envelope", [_UNRECOGNIZED, _STRING_FINDINGS], ids=["kind", "string"])
def test_med_d_malformed_findings_never_advance_an_existing_ledger(
    tmp_path: Path, envelope: dict
) -> None:
    feats = _three()
    plan_dir = _make_plan(tmp_path, feats, PID)
    _lock_volley(plan_dir, _CodexLikeReviewer([_SIGNED]))
    before = _ledger_path(plan_dir).read_bytes()
    _change_f001(plan_dir, feats)
    reviewer = _CodexLikeReviewer([envelope])
    _lock_volley(plan_dir, reviewer)
    assert reviewer.calls == 1
    assert _ledger_path(plan_dir).read_bytes() == before
    calls, out = _relock_calls(plan_dir)
    assert calls >= 1, out


def test_med_d_parse_marks_review_incomplete() -> None:
    for envelope in (_UNRECOGNIZED, _STRING_FINDINGS, {"verdict": "signed_off", "findings": [1]}):
        env = dr.parse_design_envelope(json.dumps(envelope))
        assert env.unrecognized
        assert dr.ledger_advances(env) is False
    ok = dr.parse_design_envelope(json.dumps({"verdict": "signed_off"}))
    assert ok.unrecognized == [] and dr.ledger_advances(ok) is True
