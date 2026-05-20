"""Plan 2026-05-19-005 F001 — showcase CLI subprocess integration test.

Spawns ``python -m dontpanic_orchestrate showcase regen --target=<key>
--json`` against a synthetic config + isolated DONTPANIC_SHOWCASE_HOME
and asserts:
  - exit code is 0 on success
  - --json output is structured ShowcaseRun shape
  - artifacts land under <isolated_home>/docs/showcase/
  - no absolute paths leak into the artifacts

Uses tmp DONTPANIC_SHOWCASE_HOME isolation so the test never writes into
the committed docs/showcase/ surface.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _build_synthetic_target(root: Path) -> None:
    (root / "scripts" / "dontpanic_orchestrate").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "dontpanic_orchestrate" / "__init__.py").write_text(
        '"""synthetic CLI target."""\n', encoding="utf-8"
    )
    (root / "scripts" / "dontpanic_orchestrate" / "core.py").write_text(
        '"""core module."""\n\ndef foo():\n    return 1\n', encoding="utf-8"
    )
    (root / "claude" / "shared" / "schemas" / "v1.0").mkdir(parents=True, exist_ok=True)
    (root / "claude" / "shared" / "VERSION").write_text("v1.0.0\n", encoding="utf-8")


def _build_external_config(target_root: Path, config_path: Path) -> None:
    config_path.write_text(
        json.dumps(
            [
                {
                    "repo_key": "syn-cli",
                    "label": "Synthetic CLI Target",
                    "repo_root": str(target_root),
                    "description": "CLI integration fixture",
                    "supported_artifacts": ["architecture"],
                    "has_dontpanic_plans": False,
                    "has_committed_architecture_json": False,
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )


def test_showcase_regen_json_subcommand_against_synthetic_target(tmp_path):
    """Subprocess spawn — exercises argparse + dispatch in cli.py."""
    target_root = tmp_path / "synthetic-target"
    _build_synthetic_target(target_root)
    config_path = tmp_path / "config.json"
    _build_external_config(target_root, config_path)

    showcase_home = tmp_path / "isolated-home"
    showcase_home.mkdir()

    env = os.environ.copy()
    env["DONTPANIC_SHOWCASE_HOME"] = str(showcase_home)
    env["PYTHONPATH"] = str(REPO_ROOT / "scripts") + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "dontpanic_orchestrate",
            "showcase",
            "regen",
            "--target=syn-cli",
            "--config",
            str(config_path),
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
    payload = json.loads(proc.stdout)
    assert payload["overall_exit"] == 0
    assert len(payload["targets"]) == 1
    target = payload["targets"][0]
    assert target["repo_key"] == "syn-cli"
    assert target["status"] == "success"
    kinds = {a["artifact"] for a in target["artifacts"]}
    assert kinds == {"architecture"}

    # Artifact files exist in isolated home, NOT in committed docs/showcase/.
    out_dir = showcase_home / "docs" / "showcase"
    assert (out_dir / "syn-cli-architecture.json").is_file()
    assert (out_dir / "syn-cli-architecture.html").is_file()
    # Absolute paths must not appear in the committed-shape artifact.
    body = (out_dir / "syn-cli-architecture.json").read_text(encoding="utf-8")
    assert "/Users/" not in body
    assert str(target_root) not in body


def test_showcase_regen_unknown_target_exits_two(tmp_path):
    """Unknown target key → exit 2 (env blocker / config error, not
    'generation failure')."""
    target_root = tmp_path / "synthetic-target"
    _build_synthetic_target(target_root)
    config_path = tmp_path / "config.json"
    _build_external_config(target_root, config_path)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "scripts") + os.pathsep + env.get("PYTHONPATH", "")
    env["DONTPANIC_SHOWCASE_HOME"] = str(tmp_path / "isolated-home")
    (tmp_path / "isolated-home").mkdir(exist_ok=True)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "dontpanic_orchestrate",
            "showcase",
            "regen",
            "--target=does-not-exist",
            "--config",
            str(config_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 2
    assert "unknown target" in proc.stderr


def test_showcase_subcommand_help_exits_zero():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "scripts") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "dontpanic_orchestrate", "showcase", "--help"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert "regen" in proc.stdout


# ── CLI wire-through: --plans-root + --architecture-json on `doctor` ─────
# These complement the direct-call tests in test_showcase_generator_f001.py
# by exercising the actual argparse + dispatch path so the new flags are
# reachable from the operator's shell. Findings: codex-auditor F001 i0
# (test_coverage / medium) called for true CLI subprocess coverage.


def _write_synthetic_locked_plan(plans_root: Path, plan_id: str) -> None:
    """Lay down one locked plan that satisfies the v1.9 schema. Used by
    the --plans-root subprocess test to prove the doctor walked the
    external dir instead of DontPanic's own docs/plans."""
    plan_dir = plans_root / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        f"id: {plan_id}\n"
        f"title: External-plans-root synthetic plan for {plan_id}\n"
        "type: feat\n"
        "tier: trivial\n"
        "status: active\n"
        'date: "2026-05-01"\n'
        "description: Synthetic plan used by F001 CLI subprocess fixture "
        "to assert --plans-root walks the external dir.\n"
        "---\n\n# Body\n",
        encoding="utf-8",
    )


def test_doctor_cli_plans_root_flag_walks_external_dir(tmp_path):
    """`dontpanic doctor --plans-root <ext> --json` walks ``<ext>``
    instead of DontPanic's docs/plans, and the synthetic external
    plan_id appears in the validate-plans-strict per-plan details.

    Asserts the CLI wire-through, not just the underlying function —
    addresses prior auditor's `test_coverage` finding that the existing
    test called doctor.validate_plans_strict() directly.
    """
    ext_plans = tmp_path / "external-plans"
    ext_plans.mkdir()
    synthetic_id = "2026-05-01-001-feat-cli-syn"
    _write_synthetic_locked_plan(ext_plans, synthetic_id)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "scripts") + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "dontpanic_orchestrate",
            "doctor",
            "--skip-auth",
            "--json",
            "--plans-root",
            str(ext_plans),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    # Exit code can be 0/1/2 depending on whether other unrelated probes
    # land WARN/FAIL on this dev box. The flag wire-through is verified
    # by inspecting the JSON shape, not the exit code.
    payload = json.loads(proc.stdout)
    # ``dontpanic doctor --json`` wraps results in a dict with a
    # ``checks`` list (legacy 0/1 contract). Each entry follows the
    # CheckResult schema (name, ok, message, remediation, warn, details).
    assert isinstance(payload, dict) and "checks" in payload, (
        f"unexpected doctor --json shape: {type(payload).__name__} keys={list(payload)[:5] if isinstance(payload, dict) else 'n/a'}"
    )
    summary_entries = [r for r in payload["checks"] if r.get("name") == "validate-plans-strict"]
    assert summary_entries, f"missing validate-plans-strict entry; check names={[c.get('name') for c in payload['checks']]}"
    summary = summary_entries[0]

    # The synthetic plan_id must surface in per-plan details. DontPanic
    # itself never carries a plan with that id, so its appearance proves
    # --plans-root re-pointed the walker.
    detail_blob = json.dumps(summary.get("details") or [])
    assert synthetic_id in detail_blob, (
        f"synthetic plan id {synthetic_id!r} not found in validate-plans-strict "
        f"details — --plans-root flag did not redirect walk. "
        f"summary={summary!r}"
    )

    # And the DontPanic-only plan dirs (e.g. parent meta plan id) must NOT
    # appear when --plans-root points to a different tree. We sample a
    # known DontPanic plan id to keep this assertion narrow.
    assert "2026-05-11-001-infra-state-projection-adapters-meta" not in detail_blob, (
        "DontPanic plan id leaked into external --plans-root sweep"
    )


def test_doctor_cli_architecture_json_flag_reads_external_path(tmp_path):
    """`dontpanic doctor --architecture-json <ext> --json` evaluates
    drift against ``<ext>``. When the external path is missing, the
    architecture-drift result is ``absent`` and references the external
    path (not DontPanic's docs/architecture/architecture.json).

    CLI wire-through coverage — companion to the function-level test.
    """
    ext_arch = tmp_path / "no-such-architecture.json"
    # Deliberately don't create the file — the doctor probe should
    # report state="absent" and the message should reference ext_arch.

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "scripts") + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "dontpanic_orchestrate",
            "doctor",
            "--skip-auth",
            "--json",
            "--architecture-json",
            str(ext_arch),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    payload = json.loads(proc.stdout)
    assert isinstance(payload, dict) and "checks" in payload
    drift_entries = [r for r in payload["checks"] if r.get("name") == "architecture-drift"]
    assert drift_entries, (
        f"missing architecture-drift entry; check names="
        f"{[c.get('name') for c in payload['checks']]}"
    )
    drift = drift_entries[0]

    detail = (drift.get("details") or [{}])[0]
    assert detail.get("state") == "absent", (
        f"expected state=absent for missing external arch.json; got: {detail!r}"
    )
    # The doctor detail must reference the external path, not DontPanic's
    # own docs/architecture/architecture.json. Use os.path.realpath to
    # handle macOS's /private symlink (the doctor resolve()s the path,
    # which on macOS expands /tmp → /private/tmp).
    arch_path_blob = str(detail.get("architecture_path", ""))
    resolved_ext = str(Path(str(ext_arch)).resolve())
    assert resolved_ext in arch_path_blob or str(ext_arch) in arch_path_blob, (
        f"external --architecture-json path missing from drift detail; "
        f"got architecture_path={arch_path_blob!r}, expected to contain "
        f"{resolved_ext!r} or {str(ext_arch)!r}"
    )
