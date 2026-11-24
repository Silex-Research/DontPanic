"""Design-review volley: Codex envelope parsing + the convergence ledger.

(2a) Codex's ``raw_response`` is the whole ``exec --json`` event stream; the
reviewer's envelope is the final agent message (``summary``). It must be
parsed, not reported as ``blocked``.

(2b) A re-lock reviews only what changed since the last review (plus prior
open findings); findings on unchanged, already-reviewed features are advisory
``out_of_scope`` and never block. All executors are scripted (no live calls).
"""

from __future__ import annotations

import datetime as dt
import io
import json
from contextlib import redirect_stdout

import pytest

from dontpanic_orchestrate import cli
from dontpanic_orchestrate.executors.base import BaseExecutor, DispatchResult, DispatchTask
from dontpanic_orchestrate.plan_review import design_review as dr

_PLAN_MD = """---
id: {pid}
title: design-review convergence test
type: feat
tier: trivial
status: draft
date: "2026-11-23"
description: design-review convergence test.
agents_required: [claude, codex]
loop_caps: {{max_iterations: 1, hard_stop: false}}
privacy_tier: internal
links: {{features: ./features.json}}
---
# design-review convergence test
## Target
```yaml
target_env: dev
target_project: none
```
"""


def _feature(fid: str, description: str) -> dict:
    return {
        "id": fid,
        "category": "tooling",
        "phase": 0,
        "description": description,
        "steps": ["write it"],
        "acceptance": "(1) the helper returns a typed result",
        "passes": False,
        "depends_on": [],
    }


_FEATURES = [
    _feature("F002", "a small helper for dispatch order"),
    _feature("F009", "a small helper for the jobs lock"),
    _feature("F010", "a small helper for retries"),
]


def _finding(fid: str, kind: str = "hidden_coupling", severity: str = "block") -> dict:
    return {"kind": kind, "severity": severity, "feature_id": fid, "evidence": f"{fid} issue"}


def _codex_stream(final_message: str) -> str:
    events = [
        {"type": "thread.started", "thread_id": "t-1"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "reading plan.md"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": final_message}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}},
    ]
    return "\n".join(json.dumps(e) for e in events) + "\n"


class _CodexLikeReviewer(BaseExecutor):
    """Mimics CodexCLIExecutor: raw_response = event stream, summary = final message."""

    agent_name = "codex"

    def __init__(self, envelopes: list[dict]) -> None:
        super().__init__()
        self._envelopes = list(envelopes)
        self.prompts: list[str] = []

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.prompts.append(str((task.extra_context or {}).get("prompt_override", "")))
        env = self._envelopes[min(len(self.prompts) - 1, len(self._envelopes) - 1)]
        final = json.dumps(env)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=now,
            completed_at=now,
            success=True,
            summary=final,
            raw_response=_codex_stream(final),
        )

    @property
    def calls(self) -> int:
        return len(self.prompts)


def _make_plan(tmp_path, features, pid="2026-11-23-901-feat-converge"):
    plan_dir = tmp_path / "docs" / "plans" / pid
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_PLAN_MD.format(pid=pid))
    _write_features(plan_dir, pid, features)
    return plan_dir


def _write_features(plan_dir, pid, features):
    (plan_dir / "features.json").write_text(
        json.dumps({"task_id": pid, "schema_version": "1.0", "features": features}, indent=2)
        + "\n"
    )


def _lock_volley(plan_dir, reviewer, *, full: bool = False) -> str:
    out = io.StringIO()
    with redirect_stdout(out):
        cli._run_pre_lock_design_volley(
            plan_dir, operator_requested=True, executor=reviewer, full_review=full
        )
    return out.getvalue()


def _ledger(plan_dir) -> dict:
    return json.loads((plan_dir / dr.LEDGER_RELPATH).read_text())


# ───────────────────────────── (2a) parsing ─────────────────────────────────


def test_codex_event_stream_signed_off_is_parsed_from_summary():
    reviewer = _CodexLikeReviewer([{"verdict": "signed_off", "findings": []}])
    env = dr.run_design_volley("p1", _FEATURES, auditor=reviewer)
    assert env.verdict == "signed_off"
    assert env.findings == []


def test_codex_event_stream_needs_changes_surfaces_the_finding():
    reviewer = _CodexLikeReviewer(
        [{"verdict": "needs_changes", "findings": [_finding("F010", "oversize", "warn")]}]
    )
    env = dr.run_design_volley("p1", _FEATURES, auditor=reviewer)
    assert env.verdict == "needs_changes"
    assert [f.to_dict() for f in env.findings] == [_finding("F010", "oversize", "warn")]


def test_fenced_json_envelope_is_tolerated():
    fenced = '```json\n{"verdict": "signed_off", "findings": []}\n```'
    assert dr.parse_design_envelope(fenced).verdict == "signed_off"


def test_unparseable_candidates_still_block():
    env = dr.parse_design_envelope(_codex_stream("I could not decide."))
    assert env.verdict == "blocked"
    assert env.reviewed is False


# ─────────────────────────── (2b) convergence ───────────────────────────────


def test_first_lock_is_full_and_writes_ledger(tmp_path):
    plan_dir = _make_plan(tmp_path, _FEATURES)
    reviewer = _CodexLikeReviewer([{"verdict": "signed_off", "findings": []}])
    out = _lock_volley(plan_dir, reviewer)
    assert reviewer.calls == 1
    assert "design-review scope: full" in out
    ledger = _ledger(plan_dir)
    assert ledger["schema"] == 1 and ledger["mode"] == "full"
    assert set(ledger["feature_hashes"]) == {"F002", "F009", "F010"}
    assert ledger["open_findings"] == []


def test_relock_on_unchanged_text_does_not_dispatch(tmp_path):
    plan_dir = _make_plan(tmp_path, _FEATURES)
    _lock_volley(plan_dir, _CodexLikeReviewer([{"verdict": "signed_off", "findings": []}]))

    # Same bytes; this reviewer WOULD raise a new block finding on F002.
    second = _CodexLikeReviewer([{"verdict": "needs_changes", "findings": [_finding("F002")]}])
    out = _lock_volley(plan_dir, second)
    assert second.calls == 0  # zero paid calls
    assert "verdict=signed_off" in out
    assert "unchanged since last full review" in out

    # Same rule at the volley level, against a ledger of these exact dicts.
    ledger = {"feature_hashes": {f["id"]: dr.feature_hash(f) for f in _FEATURES}}
    env = dr.run_design_volley(
        "p1", _FEATURES, auditor=second, scope=dr.compute_scope(_FEATURES, ledger)
    )
    assert second.calls == 0
    assert env.verdict == "signed_off"
    assert env.scope_note == "unchanged since last full review"


def test_changed_feature_scopes_review_and_quarantines_unchanged_findings(tmp_path):
    pid = "2026-11-23-902-feat-converge"
    plan_dir = _make_plan(tmp_path, _FEATURES, pid)
    _lock_volley(plan_dir, _CodexLikeReviewer([{"verdict": "signed_off", "findings": []}]))

    changed = [*_FEATURES[:2], _feature("F010", "a small helper for retries with backoff")]
    _write_features(plan_dir, pid, changed)
    reviewer = _CodexLikeReviewer(
        [{"verdict": "needs_changes", "findings": [_finding("F010"), _finding("F002")]}]
    )
    out = _lock_volley(plan_dir, reviewer)

    assert reviewer.calls == 1
    assert "in-scope: F010" in reviewer.prompts[0]
    assert "design-review scope: scoped: F010 (changed)" in out
    assert "[hidden_coupling/block] F010: F010 issue" in out
    assert "design-review out-of-scope (advisory, unchanged text):" in out
    assert out.index("F002: F002 issue") > out.index("out-of-scope")

    env = dr.run_design_volley(
        "p1",
        changed,
        auditor=_CodexLikeReviewer(
            [{"verdict": "needs_changes", "findings": [_finding("F010"), _finding("F002")]}]
        ),
        scope=dr.ReviewScope(mode="scoped", in_scope=("F010",), changed=("F010",)),
    )
    assert [f.feature_id for f in env.findings] == ["F010"]
    assert env.out_of_scope == [_finding("F002")]
    assert env.verdict == "needs_changes"

    ledger = _ledger(plan_dir)
    assert ledger["mode"] == "scoped"
    assert ledger["open_findings"] == [_finding("F010")]
    assert ledger["out_of_scope_history"][-1]["findings"] == [_finding("F002")]


def test_only_out_of_scope_findings_downgrade_to_signed_off():
    reviewer = _CodexLikeReviewer([{"verdict": "needs_changes", "findings": [_finding("F002")]}])
    env = dr.run_design_volley(
        "p1",
        _FEATURES,
        auditor=reviewer,
        scope=dr.ReviewScope(mode="scoped", in_scope=("F010",), changed=("F010",)),
    )
    assert env.verdict == "signed_off"
    assert env.findings == []
    assert env.out_of_scope == [_finding("F002")]
    assert "downgraded" in env.scope_note


def test_prior_open_finding_keeps_unchanged_feature_in_scope(tmp_path):
    plan_dir = _make_plan(tmp_path, _FEATURES)
    _lock_volley(
        plan_dir,
        _CodexLikeReviewer([{"verdict": "needs_changes", "findings": [_finding("F009")]}]),
    )
    assert _ledger(plan_dir)["open_findings"] == [_finding("F009")]

    # Nothing changed, but F009 has an open finding: re-check it.
    reviewer = _CodexLikeReviewer(
        [{"verdict": "needs_changes", "findings": [_finding("F009"), _finding("F002")]}]
    )
    out = _lock_volley(plan_dir, reviewer)
    assert reviewer.calls == 1
    prompt = reviewer.prompts[0]
    assert "in-scope: F009" in prompt
    assert "Prior open findings to re-check" in prompt
    assert "F009: F009 issue" in prompt
    assert "scoped: F009 (prior open)" in out
    assert "[hidden_coupling/block] F009: F009 issue" in out

    # Third lock: the reviewer no longer raises F009 -> resolved, ledger clears.
    third = _CodexLikeReviewer([{"verdict": "signed_off", "findings": []}])
    _lock_volley(plan_dir, third)
    assert third.calls == 1
    assert _ledger(plan_dir)["open_findings"] == []


def test_design_review_full_flag_forces_full_review_with_ledger(tmp_path):
    plan_dir = _make_plan(tmp_path, _FEATURES)
    _lock_volley(plan_dir, _CodexLikeReviewer([{"verdict": "signed_off", "findings": []}]))

    reviewer = _CodexLikeReviewer([{"verdict": "needs_changes", "findings": [_finding("F002")]}])
    out = _lock_volley(plan_dir, reviewer, full=True)
    assert reviewer.calls == 1
    assert "design-review scope: full" in out
    assert "SCOPED RE-REVIEW" not in reviewer.prompts[0]
    assert "[hidden_coupling/block] F002: F002 issue" in out
    assert _ledger(plan_dir)["mode"] == "full"


class _StopLock(Exception):
    pass


def test_design_review_full_argparse_implies_design_review(tmp_path, monkeypatch):
    plan_dir = _make_plan(tmp_path, _FEATURES)
    seen: dict = {}

    def capture(plan_dir_arg, **kwargs):
        seen.update(kwargs)
        raise _StopLock

    monkeypatch.setattr(cli, "_run_pre_lock_design_volley", capture)
    with pytest.raises(_StopLock):
        cli._plan_lock_main([str(plan_dir), "--design-review-full"])
    assert seen == {"operator_requested": True, "full_review": True}


def test_ledger_write_failure_is_a_warning_not_a_crash(tmp_path):
    plan_dir = _make_plan(tmp_path, _FEATURES)
    (plan_dir / "evidence").write_text("a file where the evidence dir should be\n")
    reviewer = _CodexLikeReviewer([{"verdict": "signed_off", "findings": []}])
    out = _lock_volley(plan_dir, reviewer)  # must not raise
    assert reviewer.calls == 1
    assert "verdict=signed_off" in out
    assert "WARN: design-review ledger not written" in out
