"""Plan 2026-06-01-001 F003 — `dontpanic plan-review` CLI surface.

Covers the acceptance set:

  (1) the command runs F001+F002 and prints a report (text and json),
      both rendered from one typed source;
  (2) it is read-only — no plan file changes after a run;
  (3) exit code is non-zero iff a block-severity flag is present,
      0 for a clean (zero-flag) plan;
  (4) `plan-review` validates under command_validation.validate_command_tokens
      and appears in the agent manifest's supported_commands;
  (5) the four output/exit cases below are each exercised.

Run:
    PYTHONPATH=scripts pytest \
        scripts/dontpanic_orchestrate/tests/test_plan_review_cli_f003.py -q
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import agent_manifest, cli, command_validation  # noqa: E402

_PLAN_TEMPLATE = """---
id: {plan_id}
title: plan-review CLI test
type: feat
tier: trivial
status: draft
date: "2026-06-01"
description: Synthetic plan for plan 2026-06-01-001 F003 tests.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# plan-review CLI test

## Target

```yaml
target_env: dev
target_project: none
```
"""

# A clean feature: no surface keyword (defaults to the lone `core` surface),
# few ACs, and no named token that fails to resolve — so F001 fires no flag.
_CLEAN_FEATURE = {
    "id": "F001",
    "category": "tooling",
    "phase": 0,
    "description": "a small helper that returns a typed result",
    "steps": ["write the helper", "add coverage"],
    "acceptance": "(1) the helper returns a typed result (2) coverage hits the happy path",
    "passes": False,
    "depends_on": [],
}

# An over-scoped feature: three distinct surfaces (cli + dashboard + doctor)
# trips `over_surface` (block at >= 3 surfaces) and `likely_timeout` (block).
_BLOCK_FEATURE = {
    "id": "F002",
    "category": "tooling",
    "phase": 0,
    "description": "wire the cli subcommand, render the dashboard html, and add a doctor preflight warn",
    "steps": ["wire the cli", "render the dashboard", "add the doctor check"],
    "acceptance": (
        "(1) the cli subcommand writes to stdout "
        "(2) the dashboard renders html for the operator "
        "(3) the doctor preflight warns proactively"
    ),
    "passes": False,
    "depends_on": [],
}


def _make_plan(repo: Path, plan_id: str, features: list[dict]) -> Path:
    plan_dir = repo / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)
    plan_md = _PLAN_TEMPLATE.format(plan_id=plan_id)
    features_doc = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": features,
    }
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(json.dumps(features_doc, indent=2) + "\n")
    return plan_dir


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = cli.main(argv)
        except SystemExit as exc:  # argparse usage errors
            rc = int(exc.code or 0)
    return rc, out.getvalue(), err.getvalue()


def _snapshot(plan_dir: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(plan_dir)): p.read_bytes()
        for p in sorted(plan_dir.rglob("*"))
        if p.is_file()
    }


# ─────────────────────────── acceptance #5 cases ───────────────────────────


def test_text_output_for_flagged_plan(tmp_path):
    """Text rendering names the flagged feature, its block flags, and the
    BLOCK verdict (acceptance #1, #5)."""
    plan_dir = _make_plan(tmp_path, "2026-06-01-900-feat-block", [_BLOCK_FEATURE])
    rc, stdout, _ = _run_cli(["plan-review", str(plan_dir), "--format", "text"])

    assert rc == 1
    assert "plan-review: 2026-06-01-900-feat-block" in stdout
    assert "F002" in stdout
    assert "over_surface" in stdout
    assert "likely_timeout" in stdout
    assert "verdict: BLOCK" in stdout
    # F002 split proposal surfaces in the human view.
    assert "suggested split" in stdout


def test_json_output_for_flagged_plan(tmp_path):
    """JSON rendering is parseable and carries the same data as text — flags,
    block count, and the split proposal (acceptance #1, #5)."""
    plan_dir = _make_plan(tmp_path, "2026-06-01-901-feat-block", [_BLOCK_FEATURE])
    rc, stdout, _ = _run_cli(["plan-review", str(plan_dir), "--format", "json"])

    assert rc == 1
    payload = json.loads(stdout)
    assert payload["plan_id"] == "2026-06-01-901-feat-block"
    assert payload["summary"]["has_block"] is True
    assert payload["summary"]["block_flag_count"] >= 1

    f002 = next(f for f in payload["features"] if f["feature_id"] == "F002")
    kinds = {flag["kind"] for flag in f002["flags"]}
    assert {"over_surface", "likely_timeout"} <= kinds
    assert f002["split_proposal"] is not None
    assert f002["split_proposal"]["conservation_ok"] is True
    assert len(f002["split_proposal"]["children"]) >= 2


def test_non_zero_exit_on_block(tmp_path):
    """A block-severity flag → exit 1 (acceptance #3, #5)."""
    plan_dir = _make_plan(tmp_path, "2026-06-01-902-feat-block", [_BLOCK_FEATURE])
    rc, _, _ = _run_cli(["plan-review", str(plan_dir)])
    assert rc == 1


def test_clean_plan_zero_flag_exit(tmp_path):
    """A clean plan → zero flags → exit 0, in both formats (acceptance #3, #5)."""
    plan_dir = _make_plan(tmp_path, "2026-06-01-903-feat-clean", [_CLEAN_FEATURE])

    rc_text, stdout_text, _ = _run_cli(["plan-review", str(plan_dir), "--format", "text"])
    assert rc_text == 0
    assert "verdict: OK" in stdout_text
    assert "No scope flags" in stdout_text

    rc_json, stdout_json, _ = _run_cli(["plan-review", str(plan_dir), "--format", "json"])
    assert rc_json == 0
    payload = json.loads(stdout_json)
    assert payload["summary"]["has_block"] is False
    assert payload["summary"]["flag_count"] == 0


# ─────────────────────────── acceptance #2 (read-only) ──────────────────────


def test_command_never_writes_plan_files(tmp_path):
    """Running plan-review leaves every plan file byte-identical (acceptance #2)."""
    plan_dir = _make_plan(tmp_path, "2026-06-01-904-feat-block", [_BLOCK_FEATURE, _CLEAN_FEATURE])
    before = _snapshot(plan_dir)

    _run_cli(["plan-review", str(plan_dir), "--format", "json"])
    _run_cli(["plan-review", str(plan_dir), "--format", "text"])

    after = _snapshot(plan_dir)
    assert before == after


# ─────────────────────────── acceptance #4 (registration) ───────────────────


def test_plan_review_validates_under_command_tokens():
    """`plan-review <plan> [--format ...]` is a well-formed token shape; a
    malformed one is rejected (acceptance #4)."""
    assert command_validation.validate_command_tokens(
        ["plan-review", "2026-06-01-001-feat-plan-review-scope-validation"]
    ).ok
    assert command_validation.validate_command_tokens(
        ["plan-review", "<plan>", "--format", "json"]
    ).ok
    # Two positionals is over the max → rejected.
    assert not command_validation.validate_command_tokens(
        ["plan-review", "<plan>", "<extra>"]
    ).ok
    # Unknown flag → rejected.
    assert not command_validation.validate_command_tokens(
        ["plan-review", "<plan>", "--bogus"]
    ).ok


def test_plan_review_in_manifest_supported_commands():
    """`plan-review` ships in the manifest's supported_commands (acceptance #4)."""
    manifest = agent_manifest.bootstrap_manifest()
    assert "plan-review" in manifest.supported_commands


# ─────────────────── auditor i0 regression (prefixed command) ────────────────


def test_dontpanic_prefixed_command_does_not_block_via_default_resolvers(tmp_path):
    """Auditor i0 finding: a clean single-surface feature whose only named
    command is the supported `dontpanic plan-review` invocation must NOT report
    a block-severity missing_prereq against the real CLI vocabulary."""
    from dontpanic_orchestrate.plan_review.report import (  # noqa: E402
        build_default_resolvers,
        build_plan_scope_report,
    )

    feature = {
        "id": "FCLI",
        "description": "a small cli helper",
        "steps": ["wire the cli"],
        "acceptance": (
            "(1) `dontpanic plan-review <plan> [--format text|json]` exits 0 for clean input"
        ),
        "depends_on": [],
    }
    report = build_plan_scope_report("probe", [feature], build_default_resolvers())
    missing = [
        flag
        for fr in report.features
        for flag in fr.scope.flags
        if flag.kind == "missing_prereq"
    ]
    assert missing == [], f"unexpected missing_prereq flags: {missing}"
    assert report.has_block() is False


# ───────────── self-lint calibration (D013) — resolver vocabulary ───────────


def test_self_lint_resolver_resolves_built_deliverable_symbols():
    """D013 calibration: build_default_resolvers must resolve the plan's own
    BUILT deliverables (real codebase symbols + flag-kind vocabulary), so the
    plan-review plan stops false-flagging missing_prereq on symbols it defines.
    """
    from dontpanic_orchestrate.plan_review.report import build_default_resolvers

    resolvers = build_default_resolvers()
    for symbol in (
        "lint_feature",      # F001 def
        "propose_split",     # F002 def
        "evaluate_feature",  # F007 def
        "over_surface",      # FlagKind Literal value
        "weak_test",
        "exemplar_ac",
        "missing_prereq",
    ):
        assert resolvers.resolves_symbol(symbol), symbol
    assert resolvers.resolves_flag("--allow-oversize")  # F007 flag, not yet curated


def test_self_lint_resolver_keeps_silent_prereq_signal_intact():
    """F012 silent-prerequisite detection survives the broadening: a token that
    exists NOWHERE in the package (a genuinely-absent / forward-referenced
    capability) still fails to resolve and would flag missing_prereq.
    """
    from dontpanic_orchestrate.plan_review.report import build_default_resolvers

    resolvers = build_default_resolvers()
    assert not resolvers.resolves_symbol("totally_made_up_capability_xyz")
    # Forward-refs to unbuilt plan-review features remain unresolved (honest):
    assert not resolvers.resolves_symbol("cross_feature_edit")  # F008 (unbuilt)
