"""Plan 2026-05-19-003 F003 — strict jsonschema plan-validation probe.

Fixture tests for the doctor's ``validate_plans_strict`` probe. Covers
the four shapes specified in F003 acceptance:

  (a) all current locked plans validate clean post-F001 fix
  (b) a synthetic plan with malformed frontmatter fails strict mode
      with a per-field error
  (c) --validate-plans-strict exit-code path returns 2 on failure
  (d) advisory mode (default) returns 0 even with failures + emits
      warning lines

Run:
    pytest scripts/dontpanic_orchestrate/tests/test_doctor_validate_plans_strict_f003.py -q
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"
LIVE_PLANS_ROOT = REPO_ROOT / "docs" / "plans"
LIVE_SCHEMA = REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0" / "plan.schema.json"


def _load_doctor():
    spec = importlib.util.spec_from_file_location("dontpanic_doctor_f003", DOCTOR_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dontpanic_doctor_f003"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doctor():
    return _load_doctor()


# Minimal valid plan frontmatter that satisfies the v1.9 schema.
_VALID_FRONTMATTER = """---
id: 2026-05-19-090-feat-f003-fixture
title: F003 fixture — minimal valid plan for strict-validate test
type: feat
tier: trivial
status: active
date: "2026-05-19"
description: Synthetic plan used by the F003 strict-validate fixture; minimal valid shape.
---

# Body
"""


def _write_plan(plans_root: Path, slug: str, frontmatter: str) -> Path:
    plan_dir = plans_root / slug
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_md = plan_dir / "plan.md"
    plan_md.write_text(frontmatter)
    return plan_dir


# ── (a) all current locked plans validate clean post-F001 ─────────────────


def test_all_locked_plans_validate_clean_against_live_schema(doctor):
    """F003 acceptance #5: running the probe against the live locked-plan
    set must return zero failures. This is the regression net that
    confirms the F001 schema fix landed cleanly and that no subsequent
    locked plan has drifted off the v1.9 schema."""
    results = doctor.validate_plans_strict(
        plans_root=LIVE_PLANS_ROOT,
        schema_path=LIVE_SCHEMA,
        strict=True,
    )
    # Exactly one summary entry, ok=True, no per-plan detail entries.
    failures = [r for r in results if not r.ok]
    assert failures == [], (
        f"Expected zero strict-validate failures across live locked plans, got: "
        f"{[(r.name, r.message) for r in failures]}"
    )
    summary = next(r for r in results if r.name == "validate-plans-strict")
    assert summary.ok is True
    assert "validate clean" in summary.message


# ── (b) malformed plan fails strict mode with per-field error ─────────────


def test_malformed_plan_frontmatter_fails_strict_mode_with_helpful_error(doctor, tmp_path):
    """Synthetic plan with the wrong type for ``orchestration.depth_limit``
    (string instead of integer) must surface a per-field validation error
    in strict mode. The check name pins the plan ID; the message names
    the field path so the operator can act on it without grep."""
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    bad_fm = """---
id: 2026-05-19-091-fix-f003-fixture-bad
title: F003 fixture — bad orchestration shape
type: fix
tier: trivial
status: active
date: "2026-05-19"
description: Synthetic plan with depth_limit as a string instead of integer.
orchestration:
  parent_plan_id: 2026-05-19-003-fix-plan-schema-orchestration-fields
  spawn_reason: test
  depth_limit: "three"
---

# Body
"""
    _write_plan(plans_root, "2026-05-19-091-fix-f003-fixture-bad", bad_fm)

    results = doctor.validate_plans_strict(
        plans_root=plans_root,
        schema_path=LIVE_SCHEMA,
        strict=True,
    )
    # Expect: summary (FAIL) + one per-plan detail (FAIL).
    failures = [r for r in results if not r.ok]
    assert len(failures) >= 2  # summary + at least one per-plan entry
    per_plan = next(
        r for r in failures if r.name == "validate-plans-strict:2026-05-19-091-fix-f003-fixture-bad"
    )
    # Per-field error names the offending path. The exact jsonschema
    # message ("'three' is not of type 'integer'") may shift across
    # library versions; assert on the structural field path instead.
    assert "orchestration.depth_limit" in per_plan.message
    assert per_plan.ok is False
    assert per_plan.remediation, "remediation hint must be non-empty so operator can act"


# ── (c) --validate-plans-strict CLI exit code 2 on failure ────────────────


def test_validate_plans_strict_cli_returns_exit_2_on_failure(tmp_path, monkeypatch):
    """The doctor's --validate-plans-strict flag implicitly opts into
    the strict-codes exit matrix and must return 2 when any plan fails
    strict validation. We invoke the doctor as a subprocess (mirroring
    how an operator runs it) and assert on the exit code."""
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    bad_fm = """---
id: 2026-05-19-092-fix-f003-fixture-exit2
title: F003 fixture — bad enum
type: fix
tier: trivial
status: active
date: "2026-05-19"
description: Synthetic plan with an invalid status enum value.
---

# Body
"""
    # Use an invalid spawn_reason to trigger an enum violation. Status
    # stays valid so the plan counts as "locked" and reaches the probe.
    bad_fm = bad_fm.replace(
        "description: Synthetic plan with an invalid status enum value.",
        "description: Synthetic plan with an invalid spawn_reason enum value.\n"
        "orchestration:\n"
        "  parent_plan_id: 2026-05-19-003-fix-plan-schema-orchestration-fields\n"
        "  spawn_reason: not_a_real_reason",
    )
    _write_plan(plans_root, "2026-05-19-092-fix-f003-fixture-exit2", bad_fm)

    # Patch PLANS_ROOT via env-var-less injection: run the doctor with
    # the CWD set so its PLANS_ROOT computation still points at the live
    # tree, then explicitly call the module entrypoint with a tmp plans
    # path. The simpler path: monkeypatch via in-process import + sys.argv.
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "PLANS_ROOT", plans_root)
    rc = doctor.main(["--skip-auth", "--validate-plans-strict", "--json"])
    assert rc == 2, f"expected exit 2 on strict-validate failure, got {rc}"


# ── (d) advisory mode returns 0 with failures + emits WARN lines ──────────


def test_advisory_mode_returns_0_on_failure_and_emits_warn_lines(doctor, tmp_path, capsys):
    """Default doctor mode (no --validate-plans-strict, no --strict-codes)
    must not block on plan-validation failures. The legacy 0/1 exit
    contract maps WARN entries to 0 (legacy 0 = "no FAIL"). The probe
    must still surface the per-plan finding as a WARN with the
    appropriate marker so operators see it."""
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    bad_fm = """---
id: 2026-05-19-093-fix-f003-fixture-advisory
title: F003 fixture — advisory mode
type: fix
tier: trivial
status: completed
date: "2026-05-19"
description: Synthetic plan missing required title-length constraint via empty title.
agents_required:
  - definitely_not_a_real_agent
---

# Body
"""
    _write_plan(plans_root, "2026-05-19-093-fix-f003-fixture-advisory", bad_fm)

    # Call the probe directly in advisory mode.
    results = doctor.validate_plans_strict(
        plans_root=plans_root,
        schema_path=LIVE_SCHEMA,
        strict=False,
    )
    # No FAIL entries — advisory mode keeps ok=True; WARN signals via
    # warn=True so the existing render layer paints the YELLOW marker.
    assert all(r.ok for r in results), (
        "advisory mode must not produce ok=False entries; "
        f"got: {[(r.name, r.ok, r.warn, r.message) for r in results]}"
    )
    warns = [r for r in results if r.warn]
    assert warns, "advisory mode should still surface findings as WARN"
    per_plan = next(
        r for r in warns
        if r.name == "validate-plans-strict:2026-05-19-093-fix-f003-fixture-advisory"
    )
    assert per_plan.ok is True
    assert per_plan.warn is True
    # The enum violation surfaces via agents_required[0].
    assert "agents_required" in per_plan.message

    # Legacy exit contract: 0 when no FAIL (WARN doesn't fail the doctor).
    # compute_strict_exit returns 1 on any WARN; the default code path
    # (no --strict-codes) uses `0 if all(r.ok for r in results) else 1`.
    # We exercise the latter via main() with sys.argv + the doctor's own
    # PLANS_ROOT override.
    import io
    captured_stdout = io.StringIO()
    sys_stdout = sys.stdout
    try:
        sys.stdout = captured_stdout
        from unittest.mock import patch
        with patch.object(doctor, "PLANS_ROOT", plans_root):
            rc = doctor.main(["--skip-auth"])
    finally:
        sys.stdout = sys_stdout
    assert rc == 0, f"advisory mode must return exit 0; got {rc}"
    out = captured_stdout.getvalue()
    # YELLOW marker (raw escape) or "validate-plans-strict:..." line.
    assert "validate-plans-strict:" in out, (
        "doctor text output must include the per-plan WARN line for the bad fixture plan; "
        f"saw:\n{out}"
    )


# ── extra: JSON output carries the per-plan detail array ──────────────────


def test_json_output_includes_per_plan_detail_array(tmp_path, monkeypatch):
    """F003 acceptance #3: --json output includes the new probe with a
    per-plan detail array. We emit one CheckResult per failing plan plus
    a summary; JSON consumers can grep ``validate-plans-strict`` prefix
    to assemble the detail array. This test confirms the JSON shape is
    stable and the per-plan entries are addressable by plan id."""
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    # Two malformed plans so the JSON detail array has cardinality > 1.
    for slug, bad_field in (
        (
            "2026-05-19-094-fix-f003-json-a",
            'orchestration:\n  parent_plan_id: 2026-05-19-003-fix-plan-schema-orchestration-fields\n  spawn_reason: nope_a',
        ),
        (
            "2026-05-19-095-fix-f003-json-b",
            'orchestration:\n  parent_plan_id: 2026-05-19-003-fix-plan-schema-orchestration-fields\n  spawn_reason: nope_b',
        ),
    ):
        fm = f"""---
id: {slug}
title: F003 JSON fixture
type: fix
tier: trivial
status: active
date: "2026-05-19"
description: Synthetic plan with bad spawn_reason for JSON detail-array test.
{bad_field}
---

# Body
"""
        _write_plan(plans_root, slug, fm)

    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "PLANS_ROOT", plans_root)

    results = doctor.validate_plans_strict(
        plans_root=plans_root,
        schema_path=LIVE_SCHEMA,
        strict=True,
    )
    # render_json renders the CheckResult list; the per-plan entries are
    # addressable via the name prefix.
    raw = doctor.render_json(results)
    payload = json.loads(raw)
    plan_entries = [
        c for c in payload["checks"]
        if c["name"].startswith("validate-plans-strict:")
    ]
    plan_ids = {c["name"].split(":", 1)[1] for c in plan_entries}
    assert "2026-05-19-094-fix-f003-json-a" in plan_ids
    assert "2026-05-19-095-fix-f003-json-b" in plan_ids
    # All per-plan entries are FAIL in strict mode.
    assert all(c["ok"] is False for c in plan_entries)


# ── (b2) auditor-mandated: TRULY malformed YAML (parse failure) ───────────


def test_unparseable_yaml_frontmatter_surfaces_as_finding(doctor, tmp_path):
    """F003 i1 auditor finding: plans whose YAML frontmatter cannot be
    parsed (unterminated block, non-mapping body, raw YAML errors) must
    surface as findings — not silently skipped. Previously the probe
    folded these into a no-op continue and the operator would see a
    falsely-green doctor.

    Cases exercised in one walk:
      * unterminated_frontmatter — opens with ``---`` but never closes
      * non_mapping — closes correctly but YAML body is a list, not a dict
      * yaml_parse_error — closes correctly but YAML is syntactically
        malformed (mismatched brace)
    """
    plans_root = tmp_path / "plans"
    plans_root.mkdir()

    # Case 1: unterminated frontmatter (no closing ---)
    unterminated = "---\nid: 2026-05-19-501-bad-unterminated\nstatus: active\n# missing close marker, body just runs on\n"
    _write_plan(plans_root, "2026-05-19-501-bad-unterminated", unterminated)

    # Case 2: frontmatter parses but is a list (non-mapping)
    non_mapping = "---\n- just\n- a\n- list\n---\n\n# Body\n"
    _write_plan(plans_root, "2026-05-19-502-bad-nonmapping", non_mapping)

    # Case 3: YAML syntactically malformed (unquoted brace)
    yaml_error = "---\nid: 2026-05-19-503-bad-yaml\nstatus: active\nbad_field: {unclosed: brace\n---\n\n# Body\n"
    _write_plan(plans_root, "2026-05-19-503-bad-yaml", yaml_error)

    results = doctor.validate_plans_strict(
        plans_root=plans_root,
        schema_path=LIVE_SCHEMA,
        strict=True,
    )

    # Each malformed plan must appear as a FAIL CheckResult in strict mode.
    failures = [r for r in results if not r.ok]
    failure_names = {r.name for r in failures}
    for slug in (
        "2026-05-19-501-bad-unterminated",
        "2026-05-19-502-bad-nonmapping",
        "2026-05-19-503-bad-yaml",
    ):
        assert f"validate-plans-strict:{slug}" in failure_names, (
            f"expected malformed plan {slug} to surface as a FAIL CheckResult; "
            f"got {failure_names}"
        )

    # The per-plan messages must name the parse error so the operator can
    # actually fix the offending file.
    per_plan_msgs = {
        r.name: r.message for r in failures if r.name.startswith("validate-plans-strict:")
    }
    assert "unterminated" in per_plan_msgs["validate-plans-strict:2026-05-19-501-bad-unterminated"].lower()
    assert "mapping" in per_plan_msgs["validate-plans-strict:2026-05-19-502-bad-nonmapping"].lower()
    assert "yaml parse error" in per_plan_msgs["validate-plans-strict:2026-05-19-503-bad-yaml"].lower()

    # The summary's details array must include each malformed plan with
    # status == "parse_error" so JSON consumers can enumerate them.
    summary = next(r for r in results if r.name == "validate-plans-strict")
    assert summary.details is not None
    parse_error_details = {
        d["plan_id"]: d for d in summary.details if d.get("status") == "parse_error"
    }
    assert set(parse_error_details.keys()) == {
        "2026-05-19-501-bad-unterminated",
        "2026-05-19-502-bad-nonmapping",
        "2026-05-19-503-bad-yaml",
    }
    # Each detail entry carries an ``error`` field with the raw parse
    # message so JSON consumers don't have to grep the human-facing line.
    for detail in parse_error_details.values():
        assert detail.get("error"), f"parse_error detail must carry 'error' field: {detail}"


def test_plan_md_missing_leading_frontmatter_surfaces_as_finding(doctor, tmp_path):
    """Plan 3 F003 i1 auditor finding (medium/correctness): a plan.md
    with no leading ``---`` was silently skipped, producing a false-green
    strict validation result. Treat the missing-frontmatter case the
    same as every other parse_error so strict mode catches it."""
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    no_fm = "# Just a heading\n\nNo YAML frontmatter at all.\n"
    _write_plan(plans_root, "2026-05-19-510-bad-missing-fm", no_fm)

    strict_results = doctor.validate_plans_strict(
        plans_root=plans_root,
        schema_path=LIVE_SCHEMA,
        strict=True,
    )
    failures = [r for r in strict_results if not r.ok]
    failure_names = {r.name for r in failures}
    assert "validate-plans-strict:2026-05-19-510-bad-missing-fm" in failure_names, (
        f"expected missing-frontmatter plan to surface as FAIL in strict mode; got {failure_names}"
    )

    advisory_results = doctor.validate_plans_strict(
        plans_root=plans_root,
        schema_path=LIVE_SCHEMA,
        strict=False,
    )
    warns = [r for r in advisory_results if r.warn and not r.ok is False]
    warn_names = {r.name for r in warns}
    assert "validate-plans-strict:2026-05-19-510-bad-missing-fm" in warn_names, (
        f"advisory mode must surface missing-frontmatter as WARN; got {warn_names}"
    )

    summary = next(r for r in strict_results if r.name == "validate-plans-strict")
    assert summary.details is not None
    parse_error_ids = {
        d["plan_id"] for d in summary.details if d.get("status") == "parse_error"
    }
    assert "2026-05-19-510-bad-missing-fm" in parse_error_ids


def test_orchestrate_cli_advisory_mode_returns_0_with_warn_findings(tmp_path, monkeypatch, capsys):
    """Plan 3 F003 i1 auditor finding (high/correctness): the canonical
    ``python -m dontpanic_orchestrate doctor`` subcommand used to call
    compute_strict_exit unconditionally, mapping advisory WARN findings
    to exit 1. The acceptance contract says advisory mode → exit 0
    regardless of plan-validation findings. Verify that the CLI's
    _doctor_main entrypoint (which the ``doctor`` subcommand dispatches
    to) returns 0 when a plan triggers a validate-plans-strict WARN and
    --validate-plans-strict is NOT set."""
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    no_fm = "# Just a heading\n\nNo YAML frontmatter at all.\n"
    _write_plan(plans_root, "2026-05-19-520-cli-advisory-warn", no_fm)

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import dontpanic_doctor as jd  # type: ignore[import-not-found]
        sys.modules["jarvis_doctor"] = jd
        monkeypatch.setattr(jd, "PLANS_ROOT", plans_root)
        from dontpanic_orchestrate.cli import _doctor_main
        rc = _doctor_main(["--skip-auth"])
    finally:
        sys.path.pop(0)
    assert rc == 0, (
        f"advisory-mode CLI must return exit 0 with validate-plans-strict WARN findings; got {rc}"
    )
    out = capsys.readouterr().out
    assert "validate-plans-strict" in out, (
        f"advisory WARN must still surface to operator; stdout:\n{out[:1500]}"
    )

    monkeypatch.setattr(jd, "PLANS_ROOT", plans_root)
    rc_strict = _doctor_main(["--skip-auth", "--validate-plans-strict"])
    assert rc_strict == 2, (
        f"strict mode must escalate the same WARN/FAIL to exit 2; got {rc_strict}"
    )


def test_advisory_mode_surfaces_parse_errors_as_warn(doctor, tmp_path):
    """Mirror of the malformed-YAML test in advisory mode: parse errors
    must surface as WARN findings (ok=True, warn=True) — not silently
    skipped. Operators running the default doctor must still see the
    finding even though it doesn't block exit code."""
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    _write_plan(
        plans_root,
        "2026-05-19-504-bad-yaml-advisory",
        "---\nid: 2026-05-19-504-bad-yaml-advisory\nstatus: active\nbroken: {nope\n---\n\n# Body\n",
    )

    results = doctor.validate_plans_strict(
        plans_root=plans_root,
        schema_path=LIVE_SCHEMA,
        strict=False,
    )
    # Advisory mode must not produce ok=False entries…
    assert all(r.ok for r in results)
    # …but the parse error must still ride along as a WARN.
    per_plan = next(
        r for r in results if r.name == "validate-plans-strict:2026-05-19-504-bad-yaml-advisory"
    )
    assert per_plan.warn is True
    assert "yaml parse error" in per_plan.message.lower()


# ── JSON summary details array carries EVERY walked plan ──────────────────


def test_json_summary_details_array_covers_clean_plans(doctor, tmp_path):
    """F003 i1 auditor finding: JSON output must include a per-plan
    detail array with ``plan_id`` and ``status`` for every walked plan,
    not only the failing ones. The summary CheckResult's ``details``
    field carries the full array; this test asserts every clean plan is
    addressable in the JSON payload."""
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    # Three valid plans, no failures. Use distinct slugs so the detail
    # entries are individually addressable.
    for slug in (
        "2026-05-19-601-feat-clean-a",
        "2026-05-19-602-feat-clean-b",
        "2026-05-19-603-feat-clean-c",
    ):
        fm = f"""---
id: {slug}
title: F003 JSON details clean fixture {slug[-1]}
type: feat
tier: trivial
status: active
date: "2026-05-19"
description: Synthetic clean plan for the JSON details-array coverage test.
---

# Body
"""
        _write_plan(plans_root, slug, fm)

    results = doctor.validate_plans_strict(
        plans_root=plans_root,
        schema_path=LIVE_SCHEMA,
        strict=True,
    )
    raw = doctor.render_json(results)
    payload = json.loads(raw)
    summary = next(c for c in payload["checks"] if c["name"] == "validate-plans-strict")
    assert "details" in summary, "summary CheckResult must carry a details array"
    detail_plan_ids = {d["plan_id"] for d in summary["details"]}
    assert detail_plan_ids == {
        "2026-05-19-601-feat-clean-a",
        "2026-05-19-602-feat-clean-b",
        "2026-05-19-603-feat-clean-c",
    }
    # Every entry must report status=="clean" with a path that points
    # back at the plan.md file. JSON consumers rely on this shape.
    for detail in summary["details"]:
        assert detail["status"] == "clean"
        assert detail["path"].endswith("plan.md")


# ── CLI subcommand: --validate-plans-strict via dontpanic_orchestrate ─────


def test_dontpanic_orchestrate_doctor_accepts_validate_plans_strict_flag():
    """F003 i1 auditor finding (high, correctness): the canonical CLI
    surface ``python3 -m dontpanic_orchestrate doctor --skip-auth
    --validate-plans-strict --json`` must accept the flag (not error
    with argparse code 2 ``unrecognized arguments``). We exercise it as
    a subprocess and assert the exit code is 0 or 2 (anything but the
    argparse "unrecognized arguments" exit), and that the JSON payload
    contains the validate-plans-strict probe."""
    env = {
        "PYTHONPATH": str(REPO_ROOT / "scripts"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "dontpanic_orchestrate",
            "doctor",
            "--skip-auth",
            "--validate-plans-strict",
            "--json",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    # argparse "unrecognized arguments" path would print the usage to
    # stderr — assert the flag isn't rejected before we even get to the
    # probe.
    assert "unrecognized arguments" not in proc.stderr.lower(), (
        f"--validate-plans-strict was rejected by argparse:\n{proc.stderr}"
    )
    # The doctor returns 0 (all PASS) or 2 (any FAIL) on the strict-codes
    # matrix; 1 (any WARN) is also valid. Anything else means the doctor
    # itself crashed before producing output.
    assert proc.returncode in (0, 1, 2), (
        f"doctor returned unexpected exit code {proc.returncode}; "
        f"stderr:\n{proc.stderr[:500]}"
    )
    # JSON payload must contain the validate-plans-strict probe.
    payload = json.loads(proc.stdout)
    probe_names = {c["name"] for c in payload["checks"]}
    assert "validate-plans-strict" in probe_names, (
        f"probe not in CLI doctor output; saw: {probe_names}"
    )
