"""F004 — pre-lock design gate (plan 2026-06-01-001).

Wires the F001 scope lint into ``dontpanic plan lock`` so a plan cannot
transition ``draft -> active`` while any feature carries a block-severity scope
flag, unless ``--allow-oversize <reason>`` records a verbatim rationale in the
plan's ``decisions.jsonl``.

Coverage (acceptance #5):
  * a plan with a multi-surface feature is REFUSED at lock (exit 3), the flags
    are named, and the status stays ``draft`` (no transition occurs);
  * the same plan LOCKS with ``--allow-oversize <reason>``, the reason lands
    verbatim in decisions.jsonl, and the status flips to ``active``;
  * a clean plan LOCKS with no override (exit 0), no override decision written.

Plus the pure-module contracts (evaluate_plan verdict, record_override ledger
shape + id increment, >=8-char reason validator) and acceptance #4 (existing
lock validation still runs — the gate is additive).

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_plan_review_pre_lock_gate_f004.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Bootstrap import path — same convention as sibling test modules.
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import cli  # noqa: E402
from dontpanic_orchestrate.plan_review import pre_lock_gate  # noqa: E402

_PLAN_MD_TEMPLATE = """---
id: {plan_id}
title: Synthetic pre-lock-gate test
type: feat
tier: trivial
status: draft
date: "2026-06-01"
description: Synthetic plan exercising the F004 pre-lock design gate.
links:
  features: ./features.json
---

# Pre-lock-gate synthetic

Used by tests/test_plan_review_pre_lock_gate_f004.py — no real CLI dispatch.

## Target

```yaml
target_env: dev
target_project: none
```
"""

# A feature whose description/steps/acceptance touch THREE surfaces (cli +
# dashboard + doctor) — F001 fires a block-severity `over_surface` (>= 3
# surfaces) plus `likely_timeout`. The F016 "spans CLI + dashboard + doctor"
# over-scope shape the gate exists to catch.
_OVERSIZE_FEATURE = {
    "id": "F001",
    "category": "tooling",
    "phase": 0,
    "description": (
        "Spans three surfaces: a CLI subcommand, a dashboard html render, and "
        "a doctor preflight warn — over-scoped for one dispatch."
    ),
    "steps": [
        "Add the CLI subcommand.",
        "Render the dashboard html view.",
        "Add the doctor preflight warn.",
    ],
    "acceptance": (
        "(1) The CLI subcommand prints. (2) The dashboard html renders. "
        "(3) The doctor preflight warn fires."
    ),
    "passes": False,
    "depends_on": [],
}

# A clean single-surface, in-budget feature: no block-severity flag.
_CLEAN_FEATURE = {
    "id": "F001",
    "category": "tooling",
    "phase": 0,
    "description": "A pure deterministic scoring core module.",
    "steps": ["Compute the score.", "Return the typed report."],
    "acceptance": "(1) The scorer returns a typed report for the input.",
    "passes": False,
    "depends_on": [],
}


def _write_plan(
    repo: Path, plan_id: str, feature: dict, *, decisions: list[dict] | None = None
) -> Path:
    """Write a minimal valid draft plan dir whose F001 is ``feature``."""
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_PLAN_MD_TEMPLATE.format(plan_id=plan_id))
    (plan_dir / "features.json").write_text(
        json.dumps(
            {"task_id": plan_id, "schema_version": "1.0", "features": [feature]},
            indent=2,
        )
        + "\n"
    )
    if decisions is not None:
        (plan_dir / "decisions.jsonl").write_text(
            "".join(json.dumps(d) + "\n" for d in decisions)
        )
    return plan_dir


def _status_of(plan_dir: Path) -> str:
    """Read the ``status:`` frontmatter value straight from plan.md."""
    import re

    text = (plan_dir / "plan.md").read_text(encoding="utf-8")
    m = re.search(r"^status:\s*(\S+)\s*$", text, re.MULTILINE)
    assert m, "no status line in plan.md"
    return m.group(1)


# ─────────────────────────────  pure module  ─────────────────────────────


def test_evaluate_plan_blocks_on_multi_surface_feature() -> None:
    """A three-surface feature blocks the plan; the block flags are named."""
    print("\n[test] evaluate_plan_blocks_on_multi_surface_feature ...")
    result = pre_lock_gate.evaluate_plan("synthetic", [_OVERSIZE_FEATURE])
    assert result.is_blocked
    assert result.blocking_features
    names = result.flag_names()
    assert any(n.endswith(":over_surface") for n in names), names
    print(f"  ✓ blocked; flags named: {names}")


def test_evaluate_plan_clean_feature_not_blocked() -> None:
    """A clean single-surface feature does not block the plan."""
    print("\n[test] evaluate_plan_clean_feature_not_blocked ...")
    result = pre_lock_gate.evaluate_plan("synthetic", [_CLEAN_FEATURE])
    assert not result.is_blocked
    assert result.blocking_features == ()
    assert result.flag_names() == ()
    print("  ✓ clean plan yields no block")


def test_validate_reason_enforces_min_length() -> None:
    """The layer-B reason validator rejects <8 non-whitespace chars."""
    print("\n[test] validate_reason_enforces_min_length ...")
    with pytest.raises(ValueError, match="at least 8"):
        pre_lock_gate.validate_reason("short")
    # Whitespace does not count toward the bar.
    with pytest.raises(ValueError, match="at least 8"):
        pre_lock_gate.validate_reason("   a b   ")
    assert pre_lock_gate.validate_reason("a substantive operator note") is not None
    print("  ✓ <8 non-whitespace rejected, valid reason accepted")


def test_record_override_appends_verbatim_and_increments_id(tmp_path: Path) -> None:
    """record_override appends a D<n+1> entry carrying the reason verbatim,
    preserving the existing ledger."""
    print("\n[test] record_override_appends_verbatim_and_increments_id ...")
    reason = "operator accepts the multi-surface scope for the v0 spike"
    plan_dir = _write_plan(
        tmp_path,
        "2026-06-01-901-feat-prelock-record",
        _OVERSIZE_FEATURE,
        decisions=[
            {"id": "D001", "by": "operator", "ts": "2026-06-01T00:00:00Z", "title": "x"},
            {"id": "D007", "by": "operator", "ts": "2026-06-01T00:00:00Z", "title": "y"},
        ],
    )
    result = pre_lock_gate.evaluate_plan("synthetic", [_OVERSIZE_FEATURE])

    out = pre_lock_gate.record_override(
        plan_dir, plan_id="synthetic", reason=reason, result=result
    )
    assert out == plan_dir / "decisions.jsonl"

    lines = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert [d["id"] for d in lines[:2]] == ["D001", "D007"]  # ledger preserved
    appended = lines[-1]
    assert appended["id"] == "D008"  # max(1, 7) + 1
    assert appended["reason"] == reason  # verbatim
    assert reason in appended["body"]  # also in the human body
    assert any(n.endswith(":over_surface") for n in appended["overridden_flags"])
    print(f"  ✓ appended {appended['id']} with verbatim reason; ledger intact")


def test_record_override_starts_at_d001_when_ledger_absent(tmp_path: Path) -> None:
    """With no decisions.jsonl, the first override is D001."""
    print("\n[test] record_override_starts_at_d001_when_ledger_absent ...")
    plan_dir = _write_plan(tmp_path, "2026-06-01-902-feat-prelock-fresh", _OVERSIZE_FEATURE)
    result = pre_lock_gate.evaluate_plan("synthetic", [_OVERSIZE_FEATURE])
    out = pre_lock_gate.record_override(
        plan_dir, plan_id="synthetic", reason="first recorded rationale here", result=result
    )
    lines = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["id"] == "D001"
    print("  ✓ fresh ledger → D001")


# ───────────────────────────  gate helper (CLI seam)  ───────────────────────


def test_gate_refuses_blocked_plan_without_override(tmp_path: Path, capsys) -> None:
    """Blocked plan + no override → exit 3, no decisions.jsonl written."""
    print("\n[test] gate_refuses_blocked_plan_without_override ...")
    plan_dir = _write_plan(tmp_path, "2026-06-01-903-feat-prelock-refuse", _OVERSIZE_FEATURE)
    rc = cli._run_pre_lock_scope_gate(plan_dir, allow_oversize=None)
    assert rc == 3
    assert not (plan_dir / "decisions.jsonl").exists()
    err = capsys.readouterr().err
    assert "BLOCKED by pre-lock design gate" in err
    assert "over_surface" in err
    print("  ✓ exit 3, flags named, no decision recorded")


def test_gate_records_override_and_proceeds(tmp_path: Path, capsys) -> None:
    """Blocked plan + override → returns None (proceed) and records verbatim."""
    print("\n[test] gate_records_override_and_proceeds ...")
    reason = "v0 spike: multi-surface is intentional and will be split next round"
    plan_dir = _write_plan(tmp_path, "2026-06-01-904-feat-prelock-override", _OVERSIZE_FEATURE)
    rc = cli._run_pre_lock_scope_gate(plan_dir, allow_oversize=reason)
    assert rc is None  # proceed
    ledger = plan_dir / "decisions.jsonl"
    assert ledger.is_file()
    appended = json.loads(ledger.read_text().splitlines()[-1])
    assert appended["reason"] == reason
    out = capsys.readouterr().out
    assert "OVERRIDDEN" in out
    print("  ✓ proceed; verbatim reason recorded")


def test_gate_clean_plan_proceeds_no_record(tmp_path: Path) -> None:
    """Clean plan + no override → returns None, no decisions.jsonl written."""
    print("\n[test] gate_clean_plan_proceeds_no_record ...")
    plan_dir = _write_plan(tmp_path, "2026-06-01-905-feat-prelock-clean", _CLEAN_FEATURE)
    rc = cli._run_pre_lock_scope_gate(plan_dir, allow_oversize=None)
    assert rc is None
    assert not (plan_dir / "decisions.jsonl").exists()
    print("  ✓ clean plan proceeds, no record")


# ───────────────────────────  end-to-end `plan lock`  ───────────────────────


def test_plan_lock_refuses_oversize_and_keeps_draft(tmp_path: Path, capsys) -> None:
    """acceptance #2/#5 — `plan lock` on an over-scoped plan exits 3 and the
    status stays draft (no transition)."""
    print("\n[test] plan_lock_refuses_oversize_and_keeps_draft ...")
    plan_dir = _write_plan(tmp_path, "2026-06-01-906-feat-prelock-e2e-refuse", _OVERSIZE_FEATURE)
    rc = cli._plan_lock_main([str(plan_dir)])
    assert rc == 3
    assert _status_of(plan_dir) == "draft"  # no transition
    print("  ✓ exit 3; status remains draft")


def test_plan_lock_with_override_records_and_flips(tmp_path: Path, capsys) -> None:
    """acceptance #3/#5 — `plan lock --allow-oversize <reason>` records the
    reason verbatim in decisions.jsonl and flips status to active."""
    print("\n[test] plan_lock_with_override_records_and_flips ...")
    reason = "operator-approved oversize for the bootstrap milestone"
    plan_dir = _write_plan(tmp_path, "2026-06-01-907-feat-prelock-e2e-override", _OVERSIZE_FEATURE)
    rc = cli._plan_lock_main([str(plan_dir), "--allow-oversize", reason])
    assert rc == 0
    assert _status_of(plan_dir) == "active"  # transition happened
    # Not the last line: a successful lock also appends its outcome-score
    # receipt (2026-08-13-001 F005), which lands after the override because the
    # score is recorded after the scope gate. The acceptance is that the reason
    # is in the ledger verbatim, not where in it.
    entries = [
        json.loads(line)
        for line in (plan_dir / "decisions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    overrides = [e for e in entries if e.get("reason") == reason]
    assert len(overrides) == 1, entries
    print("  ✓ exit 0; status active; verbatim reason in decisions.jsonl")


def test_plan_lock_clean_plan_locks_without_override(tmp_path: Path, capsys) -> None:
    """acceptance #5 — a clean plan locks with no override (exit 0, active)."""
    print("\n[test] plan_lock_clean_plan_locks_without_override ...")
    plan_dir = _write_plan(tmp_path, "2026-06-01-908-feat-prelock-e2e-clean", _CLEAN_FEATURE)
    rc = cli._plan_lock_main([str(plan_dir)])
    assert rc == 0
    assert _status_of(plan_dir) == "active"
    # The gate wrote no oversize-override decision.
    ledger = plan_dir / "decisions.jsonl"
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            if line.strip():
                assert "Pre-lock design gate override" not in line
    print("  ✓ exit 0; status active; no override decision")


def test_plan_lock_too_short_reason_rejected(tmp_path: Path, capsys) -> None:
    """acceptance #3 — an override reason <8 non-whitespace chars is rejected
    at the CLI (argparse exit 2), and the status stays draft."""
    print("\n[test] plan_lock_too_short_reason_rejected ...")
    plan_dir = _write_plan(tmp_path, "2026-06-01-909-feat-prelock-shortreason", _OVERSIZE_FEATURE)
    with pytest.raises(SystemExit) as exc:
        cli._plan_lock_main([str(plan_dir), "--allow-oversize", "short"])
    assert exc.value.code == 2  # argparse usage error
    assert _status_of(plan_dir) == "draft"
    print("  ✓ short reason rejected (exit 2); status remains draft")
