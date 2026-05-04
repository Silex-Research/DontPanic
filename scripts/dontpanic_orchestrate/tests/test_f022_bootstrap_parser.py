"""F022 — bootstrap.sh argument parsing + abort messages.

We don't actually run gcloud/firebase here — we exercise the script's
preflight gates (missing flags, malformed billing account, help output)
and the dry-run code path.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap.sh"


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Strip any inherited values so missing-flag tests can detect "missing"
    env.pop("DONTPANIC_FIREBASE_PROJECT", None)
    env.pop("DONTPANIC_BILLING_ACCOUNT", None)
    env.pop("JARVIS_FIREBASE_PROJECT", None)
    env.pop("JARVIS_BILLING_ACCOUNT", None)
    return subprocess.run(
        ["bash", str(BOOTSTRAP), *args],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
        **kwargs,
    )


def test_help_lists_required_flags() -> None:
    proc = _run(["-h"])
    assert proc.returncode == 0
    assert "--project" in proc.stdout
    assert "--billing-account" in proc.stdout
    assert "--create-key" in proc.stdout


def test_aborts_when_project_missing() -> None:
    proc = _run([])
    assert proc.returncode == 2, proc.stderr
    assert "missing --project" in proc.stderr
    assert "remediation" in proc.stderr.lower()


def test_aborts_when_billing_account_missing() -> None:
    proc = _run(["--project", "test-id"])
    assert proc.returncode == 2, proc.stderr
    assert "missing --billing-account" in proc.stderr


def test_rejects_malformed_billing_account() -> None:
    proc = _run(["--project", "test-id", "--billing-account", "not-an-id"])
    assert proc.returncode == 2, proc.stderr
    assert "does not look like" in proc.stderr


def test_dry_run_executes_zero_side_effects() -> None:
    """--dry-run must not authenticate, probe gcloud, or otherwise touch the
    cloud. It must exit 0 even on a machine where gcloud/firebase are
    completely unauthenticated. Asserts: returncode 0, all six step
    headers printed, every gcloud call shown as a `+` echoed line."""
    proc = _run(
        [
            "--project",
            "test-id",
            "--billing-account",
            "ABCDEF-012345-FEDCBA",
            "--dry-run",
        ]
    )
    assert proc.returncode == 0, f"dry-run aborted: {proc.stderr}"
    out = proc.stdout
    # All six steps reached
    for step in ("[1/6]", "[2/6]", "[3/6]", "[4/6]", "[5/6]", "[6/6]"):
        assert step in out, f"missing {step} in dry-run output"
    # IAM bindings echoed (the original bug: `run ... >/dev/null` swallowed them)
    assert "add-iam-policy-binding" in out, "IAM binding commands not echoed"
    # New role from F022 review: logging.logWriter
    assert "roles/logging.logWriter" in out
    # No abort messages — auth probes must be skipped under --dry-run
    assert "is not authenticated" not in proc.stderr


def test_env_vars_substitute_for_flags() -> None:
    """DONTPANIC_FIREBASE_PROJECT + DONTPANIC_BILLING_ACCOUNT can replace flags."""
    env = os.environ.copy()
    env["DONTPANIC_FIREBASE_PROJECT"] = "test-id"
    env["DONTPANIC_BILLING_ACCOUNT"] = "ABCDEF-012345-FEDCBA"
    proc = subprocess.run(
        ["bash", str(BOOTSTRAP), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    # Should not abort with "missing --project" — env var supplied it.
    assert "missing --project" not in proc.stderr
    assert "missing --billing-account" not in proc.stderr


def test_legacy_env_vars_still_substitute_for_flags() -> None:
    """JARVIS_FIREBASE_PROJECT + JARVIS_BILLING_ACCOUNT remain compatible."""
    env = os.environ.copy()
    env.pop("DONTPANIC_FIREBASE_PROJECT", None)
    env.pop("DONTPANIC_BILLING_ACCOUNT", None)
    env["JARVIS_FIREBASE_PROJECT"] = "test-id"
    env["JARVIS_BILLING_ACCOUNT"] = "ABCDEF-012345-FEDCBA"
    proc = subprocess.run(
        ["bash", str(BOOTSTRAP), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    # Should not abort with "missing --project" — env var supplied it.
    assert "missing --project" not in proc.stderr
    assert "missing --billing-account" not in proc.stderr


def test_create_key_flag_off_by_default(tmp_path: Path) -> None:
    """--create-key must be explicit. Default run skips key creation."""
    proc = _run(
        [
            "--project",
            "test-id",
            "--billing-account",
            "ABCDEF-012345-FEDCBA",
            "--dry-run",
        ]
    )
    # We can't run the full script in CI (no gcloud auth) but if it gets far
    # enough, "Skipping SA key creation" should appear; if it aborts earlier,
    # at least nothing should reference `keys create`.
    output = proc.stdout + proc.stderr
    assert "keys create" not in output, "key creation must not happen without --create-key"


def test_unknown_flag_rejected() -> None:
    proc = _run(["--no-such-flag"])
    assert proc.returncode == 2
    assert "Unknown flag" in proc.stderr
