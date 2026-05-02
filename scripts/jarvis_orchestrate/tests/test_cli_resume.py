"""Plan 2026-05-02-001 F001 — `jarvis resume` gate-discipline tests.

Covers the seven CLI shapes from the plan's acceptance:

  a. bare `resume <plan>`                       → exit 2, state unchanged
  b. `resume <plan> --gate <valid uncleared>`   → exit 0, single gate cleared
  c. `resume <plan> --gate <unknown>`           → exit 2, state unchanged
  d. `resume <plan> --gate breaker:global_...`  → exit 2, state unchanged
  e. `resume <plan> --gate X --all` (mutex)     → exit 2, state unchanged
  f. `resume <plan> --gate <already-cleared>`   → exit 0, byte-identical state
  g. `resume <plan> --all`                      → exit 0, bulk-cleared

Plus parity with `approve` + INBOX `gate_hit` template assertions.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import cli, gate_pause, inbox, supervisor  # noqa: E402

_PLAN_TEMPLATE = """---
id: {plan_id}
title: Resume CLI gate-discipline test
type: infra
tier: trivial
status: active
date: "2026-05-02"
description: Synthetic plan for plan 2026-05-02-001 F001 tests.
agents_required:
  - claude
  - codex
human_gates:
{gates_yaml}
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# Resume CLI gate-discipline test

## Target

```yaml
target_env: dev
target_project: none
```
"""


def _make_plan(repo: Path, plan_id: str, gates: list[str]) -> Path:
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    gates_yaml = "\n".join(f"  - {g}" for g in gates)
    plan_md = _PLAN_TEMPLATE.format(plan_id=plan_id, gates_yaml=gates_yaml)
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001",
                "category": "test",
                "phase": 0,
                "description": "Synthetic feature.",
                "steps": ["scripted"],
                "acceptance": "Resume CLI behaves per spec.",
                "passes": False,
                "depends_on": [],
            }
        ],
    }
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(json.dumps(features, indent=2) + "\n")
    return plan_dir


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Invoke cli.main, capturing stdout/stderr and resolving SystemExit
    (argparse calls sys.exit on usage errors). Returns (rc, stdout, stderr)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = cli.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 2
    return rc, out.getvalue(), err.getvalue()


def _state_bytes(plan_dir: Path) -> bytes | None:
    p = gate_pause.gate_state_path(plan_dir)
    if not p.is_file():
        return None
    return p.read_bytes()


def _inbox_bytes(plan_dir: Path) -> bytes | None:
    p = inbox.inbox_path(plan_dir)
    if not p.is_file():
        return None
    return p.read_bytes()


# ────────────────────  Shape handlers (one per CLI shape)  ────────────────────
# Each handler runs the full body of one CLI-shape test against a fresh
# plan_dir that the parametrized driver creates. Handlers stay readable
# while satisfying the locked-acceptance "parametrized over seven CLI
# shapes" requirement (resume-discipline F001 step 7).


def _shape_a_bare_no_flag(plan_dir: Path) -> None:
    """(a) bare `resume <plan>` → exit 2; state unchanged; usage names approve."""
    before_state = _state_bytes(plan_dir)
    rc, out, err = _run_cli(["resume", str(plan_dir)])
    assert rc == 2, (rc, out, err)
    assert "preferred for partial clearance" in err, err
    assert "approve" in err, err
    assert _state_bytes(plan_dir) == before_state, _state_bytes(plan_dir)


def _shape_b_gate_valid_uncleared(plan_dir: Path) -> None:
    """(b) `resume --gate <valid>` → exit 0; single gate cleared; gate_cleared event."""
    rc, out, err = _run_cli(["resume", str(plan_dir), "--gate", "pre_impl"])
    assert rc == 0, (rc, out, err)
    state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
    assert state["cleared_gates"] == ["pre_impl"], state
    approves = [h for h in state["history"] if h.get("gate") == "pre_impl"]
    assert len(approves) == 1, state["history"]
    events = inbox.read_events(plan_dir)
    assert any(e.event == "gate_cleared" and "via 'resume --gate'" in e.body for e in events), [
        (e.event, e.body) for e in events
    ]


def _shape_c_gate_unknown(plan_dir: Path) -> None:
    """(c) `resume --gate <unknown>` → exit 2; state unchanged; error names gates."""
    before = _state_bytes(plan_dir)
    rc, out, err = _run_cli(["resume", str(plan_dir), "--gate", "totally_made_up"])
    assert rc == 2, (rc, out, err)
    assert "unknown gate" in err and "totally_made_up" in err, err
    assert "pre_impl" in err and "pre_merge" in err, err
    assert _state_bytes(plan_dir) == before, _state_bytes(plan_dir)


def _shape_d_gate_global_breaker(plan_dir: Path) -> None:
    """(d) `resume --gate breaker:global_circuit_breaker` → exit 2; refusal message."""
    before = _state_bytes(plan_dir)
    rc, out, err = _run_cli(["resume", str(plan_dir), "--gate", "breaker:global_circuit_breaker"])
    assert rc == 2, (rc, out, err)
    assert "global breaker has no operator clearance path" in err, err
    assert _state_bytes(plan_dir) == before, _state_bytes(plan_dir)


def _shape_e_gate_and_all_mutex(plan_dir: Path) -> None:
    """(e) `resume --gate X --all` → argparse mutex rejection; exit 2."""
    before = _state_bytes(plan_dir)
    rc, out, err = _run_cli(["resume", str(plan_dir), "--gate", "pre_impl", "--all"])
    assert rc == 2, (rc, out, err)
    assert "not allowed with" in err or "argument" in err, err
    assert _state_bytes(plan_dir) == before, _state_bytes(plan_dir)


def _shape_f_gate_already_cleared_idempotent(plan_dir: Path) -> None:
    """(f) re-clearing an already-cleared gate is byte-stable (no dup history/event)."""
    rc, _, _ = _run_cli(["resume", str(plan_dir), "--gate", "pre_impl"])
    assert rc == 0
    snapshot_state = _state_bytes(plan_dir)
    snapshot_inbox = _inbox_bytes(plan_dir)
    rc, out, err = _run_cli(["resume", str(plan_dir), "--gate", "pre_impl"])
    assert rc == 0, (rc, out, err)
    assert _state_bytes(plan_dir) == snapshot_state, "gate-state.json mutated on re-clear"
    assert _inbox_bytes(plan_dir) == snapshot_inbox, "INBOX changed on re-clear"


def _shape_g_all_bulk_clear(plan_dir: Path) -> None:
    """(g) `resume --all` → exit 0; all gates cleared; event=resumed with bulk phrase."""
    rc, out, err = _run_cli(["resume", str(plan_dir), "--all"])
    assert rc == 0, (rc, out, err)
    state = json.loads(gate_pause.gate_state_path(plan_dir).read_text())
    assert set(state["cleared_gates"]) == {"pre_impl", "pre_merge"}, state
    events = inbox.read_events(plan_dir)
    bulk_events = [e for e in events if e.event == "resumed"]
    assert len(bulk_events) == 1, [e.event for e in events]
    assert "via 'resume --all'" in bulk_events[0].body, bulk_events[0].body


# Parametrized driver: one test, seven shapes — satisfies F001 step 7's
# "parametrized over seven CLI shapes" requirement (auditor-i1 finding,
# 2026-05-02 dogfood volley).
_CLI_SHAPES = [
    ("a_bare_no_flag", "701-infra-resume-bare", _shape_a_bare_no_flag),
    ("b_gate_valid_uncleared", "702-infra-resume-gate-one", _shape_b_gate_valid_uncleared),
    ("c_gate_unknown", "703-infra-resume-gate-unknown", _shape_c_gate_unknown),
    ("d_gate_global_breaker", "704-infra-resume-gate-global", _shape_d_gate_global_breaker),
    ("e_gate_and_all_mutex", "705-infra-resume-mutex", _shape_e_gate_and_all_mutex),
    (
        "f_gate_already_cleared_idempotent",
        "706-infra-resume-idempotent",
        _shape_f_gate_already_cleared_idempotent,
    ),
    ("g_all_bulk_clear", "707-infra-resume-all", _shape_g_all_bulk_clear),
]


@pytest.mark.parametrize(
    "shape_name,plan_id_suffix,handler",
    _CLI_SHAPES,
    ids=[name for name, _, _ in _CLI_SHAPES],
)
def test_resume_cli_shape(shape_name: str, plan_id_suffix: str, handler) -> None:
    """All seven CLI shapes from F001 acceptance, parametrized over a single
    test function. Each handler creates its own plan_dir so cases are isolated."""
    print(f"\n[test] resume_cli_shape[{shape_name}] ...")
    with tempfile.TemporaryDirectory() as td:
        plan_dir = _make_plan(
            Path(td),
            f"2026-05-02-{plan_id_suffix}",
            ["pre_impl", "pre_merge"],
        )
        handler(plan_dir)
    print(f"  ✓ {shape_name}")


# ────────────────────────  parity: approve vs resume --gate  ────────────────────────


def test_resume_gate_event_parity_with_approve() -> None:
    """Both `approve <plan> <name>` and `resume <plan> --gate <name>` produce
    `event=gate_cleared` (NOT `resumed`). Body text differs only in the
    entry-path phrase so the audit trail can distinguish them."""
    print("\n[test] resume_gate_event_parity_with_approve ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        # Two separate plans so each fixture has a clean INBOX.
        approve_plan = _make_plan(repo, "2026-05-02-708-infra-parity-approve", ["pre_impl"])
        resume_plan = _make_plan(repo, "2026-05-02-709-infra-parity-resume", ["pre_impl"])
        rc_a, _, _ = _run_cli(["approve", str(approve_plan), "pre_impl"])
        rc_r, _, _ = _run_cli(["resume", str(resume_plan), "--gate", "pre_impl"])
        assert rc_a == 0 and rc_r == 0
        a_events = inbox.read_events(approve_plan)
        r_events = inbox.read_events(resume_plan)
        a_cleared = [e for e in a_events if e.event == "gate_cleared"]
        r_cleared = [e for e in r_events if e.event == "gate_cleared"]
        assert len(a_cleared) == 1 and len(r_cleared) == 1
        # Both events use event=gate_cleared (NOT 'resumed').
        assert a_cleared[0].event == r_cleared[0].event == "gate_cleared"
        # Bodies differ in entry-path phrase only.
        assert "via 'approve'" in a_cleared[0].body, a_cleared[0].body
        assert "via 'resume --gate'" in r_cleared[0].body, r_cleared[0].body
        assert "via 'resume --gate'" not in a_cleared[0].body
        assert "via 'approve'" not in r_cleared[0].body
        # Strict equality modulo the entry-path phrase: replacing the phrase
        # in either body must yield byte-identical results. This pins the
        # rest of the body wording so future drift (e.g. "approved gate"
        # vs "cleared gate") cannot reintroduce the divergence the auditor
        # caught during the F001 dogfood volley.
        a_normalized = a_cleared[0].body.replace("via 'approve'", "<ENTRY>")
        r_normalized = r_cleared[0].body.replace("via 'resume --gate'", "<ENTRY>")
        assert a_normalized == r_normalized, (
            f"body wording differs beyond entry-path phrase:\n"
            f"  approve: {a_cleared[0].body!r}\n"
            f"  resume:  {r_cleared[0].body!r}"
        )
    print("  ✓ approve and resume --gate emit the same event type with distinguishing body")


# ────────────────────────  INBOX gate_hit template  ────────────────────────


def test_inbox_gate_hit_template_recommends_approve_and_resume_all() -> None:
    """Synthetic gate_hit body (rendered the way the supervisor renders it)
    must mention `approve <plan> <gate>` AND `resume <plan> --all`, and must
    NOT contain a bare `resume <plan>` recommendation (without --all)."""
    print("\n[test] inbox_gate_hit_template_recommends_approve_and_resume_all ...")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        plan_dir = _make_plan(repo, "2026-05-02-710-infra-template", ["pre_impl", "pre_merge"])
        # Drive the supervisor's pause path by calling dispatch_volley with
        # an unmet gate. The volley pauses before any executor runs and
        # writes the `gate_hit` event we want to inspect.
        import os

        from jarvis_orchestrate import notify

        os.environ[notify.DISABLE_ENV] = "1"
        saved_quota = supervisor._quota_gate
        supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed")
        try:
            result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
        finally:
            supervisor._quota_gate = saved_quota
            os.environ.pop(notify.DISABLE_ENV, None)
        assert result.final_status == "paused_on_gate", result
        gate_hits = [e for e in inbox.read_events(plan_dir) if e.event == "gate_hit"]
        assert gate_hits, [(e.event, e.body[:40]) for e in inbox.read_events(plan_dir)]
        body = gate_hits[-1].body
        plan_id = "2026-05-02-710-infra-template"
        assert f"approve {plan_id} <gate>" in body, body
        assert f"resume {plan_id} --all" in body, body
        # The legacy bare line `resume <plan>` (without --all) must not appear
        # — search for the exact legacy substring that used to be rendered.
        legacy_bare = f"resume {plan_id}\n"
        assert legacy_bare not in body, body
    print("  ✓ gate_hit body mentions approve + resume --all; no bare-resume recommendation")
