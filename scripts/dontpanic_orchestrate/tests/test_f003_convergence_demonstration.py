"""Plan 2026-05-30-002 F003 — end-to-end convergence demonstration + regression.

This is the wired-supervisor proof that the F001 breaker fixes actually let a
progress-making volley converge. It drives ``dispatch_volley`` with scripted
executors whose AUDITOR envelopes carry a controlled finding SET each round
(not just a verdict string — the constant-shape fixture in test_volley_synthetic
can't express shrinkage).

The headline case (``test_shrinking_volley_converges_to_signed_off``): an auditor
that returns 3 → 1 → 0 findings (verdict needs_changes → needs_changes →
signed_off). Before the F001 fix this tripped ``stopped_diminishing_returns``
(signature intersection non-empty: finding #0 persists) OR ``stopped_no_progress``
(verdict-string equality) at round 2. After the fix the strictly-shrinking
finding set is recognized as progress, the volley reaches round 3, and signs off.

The D003 guard (``test_complete_turnover_findings_run_as_progress``, Plan
2026-06-02-002 F001) records the supersede: a complete-turnover volley (same
count, fully distinct findings each round, verdict held at needs_changes) is now
treated as PROGRESS — it no longer early-stops at round 2 the way the pre-D003
rule did. Churn is bounded by diminishing_returns / max_iterations instead: once
a finding SET repeats unchanged, diminishing_returns trips (here at round 4).

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f003_convergence_demonstration.py -s
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import supervisor  # noqa: E402
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _ScriptedExecutor(BaseExecutor):
    """Always-succeeds executor; the auditor envelope content is overridden
    post-write by ``_patch_force_auditor_envelopes`` so the supervisor sees the
    scripted (status, findings) for each round."""

    def __init__(self, agent: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self.received_prompts: list[str] = []

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        prompt = (task.extra_context or {}).get("prompt_override") or "(no override)"
        self.received_prompts.append(str(prompt))
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=f"[scripted {self.agent_name}/{task.agent_role}] iter={task.iteration}",
            quota_consumed={"tokens_in": 100, "tokens_out": 50},
        )


def _make_plan(tmp_dir: Path) -> Path:
    plan_id = "2026-05-30-002-infra-convergence-demo"
    plan_dir = tmp_dir / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        """---
id: 2026-05-30-002-infra-convergence-demo
title: Convergence demonstration
type: infra
tier: trivial
status: active
date: "2026-05-30"
description: Synthetic plan proving shrinking-finding volleys converge (F003).
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

# Convergence demonstration

## Target

```yaml
target_env: dev
target_project: none
```
"""
    )
    (plan_dir / "features.json").write_text(json.dumps({
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [{
            "id": "F001",
            "category": "test",
            "phase": 0,
            "description": "Synthetic feature whose auditor findings shrink across rounds.",
            "steps": ["scripted implementer", "scripted auditor"],
            "acceptance": "Volley converges to signed_off once findings are resolved.",
            "passes": False,
            "depends_on": [],
        }],
    }, indent=2) + "\n")
    return plan_dir


def _findings(count: int, *, issue_offset: int = 0) -> list[dict]:
    return [
        {"severity": "high", "category": "correctness",
         "issue": f"finding {i + issue_offset}: unresolved defect requiring a fix"}
        for i in range(count)
    ]


def _patch_force_auditor_envelopes(script: list[tuple[str, list[dict]]]) -> None:
    """Wrap supervisor._run_round so each auditor round's envelope is rewritten
    to the scripted (audit_status, findings). Implementer rounds pass through."""
    import dontpanic_orchestrate.supervisor as sup

    orig = sup._run_round
    counter = {"i": 0}

    def wrapped(*args, **kwargs):
        path = orig(*args, **kwargs)
        if kwargs.get("role") == "auditor":
            idx = counter["i"]
            counter["i"] += 1
            status, findings = script[idx] if idx < len(script) else script[-1]
            data = json.loads(path.read_text())
            data["audit_status"] = status
            data["findings"] = findings
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return path

    sup._run_round = wrapped


def _disable_quota_gate() -> None:
    import dontpanic_orchestrate.supervisor as sup

    sup._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed for synthetic test")


def _register_scripted() -> None:
    impl = _ScriptedExecutor("claude")
    aud = _ScriptedExecutor("codex")
    AGENT_REGISTRY["claude"] = lambda i=impl: i  # type: ignore[assignment]
    AGENT_REGISTRY["codex"] = lambda a=aud: a  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _restore_supervisor_after():
    """Each test reloads the supervisor module afterward so monkeypatched
    _run_round / _quota_gate don't leak across tests."""
    yield
    importlib.reload(supervisor)


# ──────────────────────────────  the demonstration  ──────────────────────────────


def test_shrinking_volley_converges_to_signed_off(capsys) -> None:
    """3 → 1 → 0 findings (needs_changes, needs_changes, signed_off). With the
    F001 fix the strictly-shrinking finding set is progress: no breaker trips at
    round 2, the volley reaches round 3 and signs off."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        _register_scripted()
        _disable_quota_gate()
        # round 0: 3 findings {0,1,2}; round 1: 1 finding {0} (strict subset —
        # finding #0 persists, so pre-fix diminishing_returns intersection trips);
        # round 2: signed off, 0 findings.
        _patch_force_auditor_envelopes([
            ("needs_changes", _findings(3)),
            ("needs_changes", _findings(1)),
            ("signed_off", []),
        ])

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)

        print("\n┌─ CONVERGENCE DEMONSTRATION (F003) ─────────────────────────────")
        print("│ auditor script:  round0=needs_changes(3 findings)")
        print("│                  round1=needs_changes(1 finding, ⊂ round0)")
        print("│                  round2=signed_off(0 findings)")
        print(f"│ final_status  =  {result.final_status}")
        print(f"│ rounds        =  {result.rounds}")
        print(f"│ audit files   =  {len(result.audit_paths)}")
        print("│ pre-fix:  stopped_diminishing_returns / stopped_no_progress @ round 2")
        print("│ post-fix: signed_off @ round 3  ✓")
        print("└────────────────────────────────────────────────────────────────")

        assert result.final_status == "signed_off", (
            f"shrinking volley must converge to signed_off, not {result.final_status} "
            f"(rounds={result.rounds}) — F001 breaker fix regressed"
        )
        assert result.rounds == 3, (
            f"expected 3 rounds (reached signoff after shrinking), got {result.rounds}"
        )


def test_complete_turnover_findings_run_as_progress(capsys) -> None:
    """D003 supersede (Plan 2026-06-02-002 F001, operator-confirmed 2026-06-02)
    of 2026-05-04-003 F003 AC#6 + 2026-05-30-002 F001's count carve-out.

    A volley whose findings COMPLETELY TURN OVER each round (same count, fully
    distinct issue text, verdict held at needs_changes) is now treated as
    PROGRESS — each round resolves the prior round's blocking findings and
    exposes new ones. The pre-D003 rule treated 'same count, different findings'
    as no-progress and early-stopped at round 2; that is now WRONG for
    audit-driven convergence. New rule: no_progress trips ONLY when no prior
    blocking-finding signature is resolved. Complete-turnover churn does NOT
    early-stop; it is bounded instead by diminishing_returns / max_iterations.

    Here rounds 0/1/2 carry distinct finding sets (offset 0/100/200) — each is
    progress, so no breaker trips at round 2. The forced script then repeats its
    last envelope (offset 200) for every subsequent round, so rounds 2 & 3 carry
    IDENTICAL signatures → diminishing_returns trips at round 4. The volley still
    terminates; only the early no_progress stop is gone.

    Subsumption note (flagged for the batched codex audit): under D003,
    stopped_no_progress is unreachable for sound-signature envelopes — the
    nothing-resolved condition is a strict subset of diminishing_returns, which
    the supervisor checks first. no_progress remains reachable only via the
    legacy verdict-string fallback (see test_no_progress_fallback_* in
    test_f001_convergence_progress.py)."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        _register_scripted()
        _disable_quota_gate()
        # max_iterations=3 → iters 0..3 (range(cap+1)). Script offsets 0/100/200
        # are distinct (progress); the 4th round repeats script[-1] (offset 200),
        # so iters 2 & 3 carry identical signatures → diminishing_returns @ round 4.
        _patch_force_auditor_envelopes([
            ("needs_changes", _findings(2, issue_offset=0)),
            ("needs_changes", _findings(2, issue_offset=100)),
            ("needs_changes", _findings(2, issue_offset=200)),
        ])

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)

        print(f"\n[D003] complete-turnover volley → {result.final_status} @ round {result.rounds}")
        assert result.final_status == "stopped_diminishing_returns", (
            f"complete-turnover churn must NOT early-stop at round 2 (D003); it "
            f"terminates via diminishing_returns once a finding set repeats, got "
            f"{result.final_status}"
        )
        assert result.rounds == 4, (
            f"distinct rounds 0-2 are progress (no early stop); DR trips at the "
            f"first repeated set (round 4), got {result.rounds}"
        )


def test_growing_findings_does_not_falsely_converge(capsys) -> None:
    """A volley whose findings GROW (1 → 2 → 3, verdict needs_changes) is not
    progress — the carve-out must not fire and the volley must terminate, not
    run to signoff."""
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(Path(td))
        _register_scripted()
        _disable_quota_gate()
        _patch_force_auditor_envelopes([
            ("needs_changes", _findings(1)),
            ("needs_changes", _findings(2)),
            ("needs_changes", _findings(3)),
        ])

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=3)

        print(f"\n[regression] growing-findings volley → {result.final_status} @ round {result.rounds}")
        assert result.final_status != "signed_off", (
            "growing findings is not progress; must not converge to signed_off"
        )
