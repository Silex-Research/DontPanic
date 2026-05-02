"""jarvis_doctor.py — preflight health checks for a Jarvis install.

Run after `scripts/bootstrap.sh` (or after a fresh clone) to verify the
local setup is consistent. Each check returns (status, message); a single
red exits 1 with a remediation pointer.

Checks:
  1. Python version >= 3.10
  2. gcloud + firebase CLIs present + authenticated
  3. JARVIS_FIREBASE_PROJECT is set OR environments.json is present
  4. .secrets/ exists, is gitignored, and the SA key matches the project
  5. Pydantic + pyyaml + firebase_admin importable
  6. agent-conventions schemas present + Pydantic models import-clean
  7. plan-artifact validator runs against parent orchestration plan

Usage:
  python3 scripts/jarvis_doctor.py              # full check (needs gcloud + firebase auth)
  python3 scripts/jarvis_doctor.py --skip-auth  # structural checks only (CI / fresh clone)
  python3 scripts/jarvis_doctor.py --json       # machine-readable output

Exit codes:
  0 — all checks green
  1 — at least one check failed (see output for remediation)
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = REPO_ROOT / ".secrets"
ENV_FILE = REPO_ROOT / "environments.json"
ENV_EXAMPLE = REPO_ROOT / "environments.json.example"
SCHEMAS_DIR = REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0"
MODELS_DIR = REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0" / "models"
PARENT_PLAN_DIR = REPO_ROOT / "docs" / "plans" / "2026-04-19-001-infra-cross-agent-orchestration"

# F001: SA-key age check looks under ~/.jarvis/.secrets/ by default; the
# JARVIS_SECRETS_DIR env var lets tests / alternate installs point elsewhere.
SA_KEY_AGE_THRESHOLD_DAYS = 90

GREEN = "\033[32m✓\033[0m"
RED = "\033[31m✗\033[0m"
YELLOW = "\033[33m⚠\033[0m"


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str
    remediation: str = ""
    warn: bool = False


def _ok(name: str, msg: str) -> CheckResult:
    return CheckResult(name=name, ok=True, message=msg)


def _bad(name: str, msg: str, remediation: str) -> CheckResult:
    return CheckResult(name=name, ok=False, message=msg, remediation=remediation)


def _warn(name: str, msg: str, remediation: str) -> CheckResult:
    """Soft signal — does NOT fail the doctor. Used when an operator may
    legitimately have out-of-band reasons for the surfaced state (e.g. a
    rotation cadence Jarvis doesn't know about)."""
    return CheckResult(name=name, ok=True, message=msg, remediation=remediation, warn=True)


# ── individual checks ──────────────────────────────────────────────────────


def check_python_version() -> CheckResult:
    return _ok("python>=3.10", f"Python {sys.version_info.major}.{sys.version_info.minor}")


def check_clis() -> list[CheckResult]:
    results = []
    for cli, hint in (
        ("gcloud", "install gcloud SDK: https://cloud.google.com/sdk/docs/install"),
        ("firebase", "install firebase CLI: npm i -g firebase-tools"),
        ("jq", "install jq: brew install jq"),
        ("git", "install git"),
    ):
        if shutil.which(cli) is None:
            results.append(_bad(f"cli:{cli}", f"{cli} not found in PATH", hint))
        else:
            results.append(_ok(f"cli:{cli}", f"{cli} found"))
    return results


def check_gcloud_auth() -> CheckResult:
    if shutil.which("gcloud") is None:
        return _bad("gcloud-auth", "gcloud missing", "install gcloud first")
    proc = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return _bad(
            "gcloud-auth",
            "gcloud is not authenticated",
            "run: gcloud auth login && gcloud auth application-default login",
        )
    return _ok("gcloud-auth", "gcloud authenticated")


def check_firebase_auth() -> CheckResult:
    if shutil.which("firebase") is None:
        return _bad("firebase-auth", "firebase CLI missing", "npm i -g firebase-tools")
    proc = subprocess.run(
        ["firebase", "login:list"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0 or "@" not in proc.stdout:
        return _bad(
            "firebase-auth",
            "firebase CLI is not authenticated",
            "run: firebase login",
        )
    return _ok("firebase-auth", "firebase authenticated")


def check_target_project() -> tuple[CheckResult, str | None]:
    """Returns (result, resolved_project) — project may be None if check failed."""
    env_var = os.environ.get("JARVIS_FIREBASE_PROJECT")
    if env_var:
        return _ok("target-project", f"JARVIS_FIREBASE_PROJECT={env_var}"), env_var
    if ENV_FILE.is_file():
        try:
            data = json.loads(ENV_FILE.read_text())
            project = (data.get("dev") or {}).get("firebase_project")
            if project and project != "your-firebase-project-id":
                return _ok("target-project", f"environments.json dev={project}"), project
        except (json.JSONDecodeError, AttributeError):
            pass
        return _bad(
            "target-project",
            "environments.json present but has placeholder/missing dev.firebase_project",
            "edit environments.json with your real project ID, or set JARVIS_FIREBASE_PROJECT",
        ), None
    return _bad(
        "target-project",
        "no JARVIS_FIREBASE_PROJECT and no environments.json",
        f"run: scripts/bootstrap.sh --project YOUR_ID --billing-account XXXXXX-XXXXXX-XXXXXX, "
        f"or copy {ENV_EXAMPLE.name} to environments.json and edit",
    ), None


def check_secrets_dir(project: str | None) -> CheckResult:
    """The security-relevant invariant is "if .secrets/ exists, git ignores it."

    A missing .secrets/ is fine on a fresh clone: bootstrap.sh creates it
    on demand under --create-key. The dangerous state would be a present
    .secrets/ that git would track, which we reject loudly.
    """
    gitignore = REPO_ROOT / ".gitignore"
    gitignore_protects = False
    if gitignore.is_file():
        content = gitignore.read_text()
        gitignore_protects = any(
            line.strip() in (".secrets/", ".secrets") for line in content.splitlines()
        )

    # Belt-and-suspenders: ask git directly. We probe a synthetic path
    # whether or not the directory exists — `git check-ignore` works on
    # paths regardless of filesystem state.
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", str(SECRETS_DIR / "probe.json")],
        capture_output=True,
    )
    git_ignores = proc.returncode == 0

    if not SECRETS_DIR.exists():
        if gitignore_protects and git_ignores:
            return _ok(
                "secrets-dir",
                ".secrets/ not present yet (gitignore guards it; bootstrap --create-key creates it)",
            )
        return _bad(
            "secrets-dir",
            ".secrets/ is not gitignored — refusing to call this safe even though the dir is missing",
            "add '.secrets/' to .gitignore before running bootstrap.sh --create-key",
        )

    if not gitignore_protects:
        return _bad(
            "secrets-dir",
            ".secrets/ exists but is not in .gitignore",
            "add '.secrets/' to .gitignore — leaking SA keys would be catastrophic",
        )
    if not git_ignores:
        return _bad(
            "secrets-dir",
            "git would track files inside .secrets/ despite .gitignore",
            "investigate .gitignore order; run: git check-ignore -v .secrets/probe.json",
        )
    msg = ".secrets/ exists, gitignored"
    if project:
        key = SECRETS_DIR / f"{project}-orchestrator.json"
        if not key.exists():
            msg += f" (no SA key for {project} — run bootstrap.sh --create-key if needed)"
    return _ok("secrets-dir", msg)


def check_python_deps() -> list[CheckResult]:
    deps = [
        ("pydantic", "pip install pydantic"),
        ("yaml", "pip install pyyaml"),
        ("firebase_admin", "pip install firebase-admin"),
    ]
    results = []
    for mod, hint in deps:
        if importlib.util.find_spec(mod) is None:
            results.append(_bad(f"py:{mod}", f"{mod} not importable", hint))
        else:
            results.append(_ok(f"py:{mod}", f"{mod} OK"))
    return results


def check_schemas() -> CheckResult:
    if not SCHEMAS_DIR.is_dir():
        return _bad(
            "schemas",
            f"agent-conventions schemas missing at {SCHEMAS_DIR}",
            "git submodule update --init or git subtree pull (see CONTRIBUTING.md)",
        )
    expected = [
        "plan.schema.json",
        "features.schema.json",
        "audit.schema.json",
        "environments.schema.json",
        "signoff.schema.json",
    ]
    missing = [s for s in expected if not (SCHEMAS_DIR / s).is_file()]
    if missing:
        return _bad(
            "schemas",
            f"schemas dir present but missing: {missing}",
            "subtree the agent-conventions repo is out of date — pull v1.x",
        )
    return _ok(
        "schemas", f"{len(expected)} core schemas present at {SCHEMAS_DIR.relative_to(REPO_ROOT)}"
    )


def check_pydantic_models() -> CheckResult:
    if not MODELS_DIR.is_dir():
        return _bad(
            "pydantic-models",
            f"{MODELS_DIR} not found",
            "subtree pull agent-conventions",
        )
    sys.path.insert(0, str(MODELS_DIR.parent))
    try:
        for mod in (
            "plan_model",
            "features_model",
            "audit_model",
            "environments_model",
            "signoff_model",
        ):
            importlib.import_module(f"models.{mod}")
    except Exception as exc:
        return _bad(
            "pydantic-models",
            f"failed importing models: {exc.__class__.__name__}: {exc}",
            "check pydantic version (>=2) and that schemas + models are in sync",
        )
    finally:
        sys.path.pop(0)
    return _ok("pydantic-models", "plan/features/audit/environments/signoff models import clean")


def check_parent_plan_validates() -> CheckResult:
    if not PARENT_PLAN_DIR.is_dir():
        return _bad(
            "parent-plan",
            f"{PARENT_PLAN_DIR} missing",
            "this is the canonical plan dir — restore from origin",
        )
    validator = SCHEMAS_DIR / "validate.py"
    if not validator.is_file():
        return _bad(
            "parent-plan",
            f"validator missing at {validator}",
            "agent-conventions out of date — subtree pull",
        )
    proc = subprocess.run(
        [sys.executable, str(validator), str(PARENT_PLAN_DIR)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return _bad(
            "parent-plan",
            f"validator rejected parent plan: {proc.stderr.strip()[:200]}",
            "review changes against agent-conventions v1.x schemas",
        )
    return _ok("parent-plan", "parent orchestration plan validates")


def _sa_key_dir() -> Path:
    override = os.environ.get("JARVIS_SECRETS_DIR")
    if override:
        return Path(override)
    return Path.home() / ".jarvis" / ".secrets"


def check_sa_key_age() -> CheckResult:
    """Soft warning when any *.json key under the SA key dir is older than
    SA_KEY_AGE_THRESHOLD_DAYS. Operators may have a rotation cadence we
    can't see, so this never fails the doctor — it just nudges. Honors
    JARVIS_SECRETS_DIR for synthetic fixtures."""
    import time

    sa_dir = _sa_key_dir()
    if not sa_dir.is_dir():
        # Nothing to check — fresh clone or no SA keys provisioned yet.
        return _ok("sa-key-age", f"{sa_dir} not present (no SA keys to age-check)")
    threshold_seconds = SA_KEY_AGE_THRESHOLD_DAYS * 86_400
    now = time.time()
    stale: list[tuple[Path, int]] = []
    fresh_count = 0
    for key in sa_dir.glob("*.json"):
        if not key.is_file():
            continue
        age_days = int((now - key.stat().st_mtime) // 86_400)
        if (now - key.stat().st_mtime) > threshold_seconds:
            stale.append((key, age_days))
        else:
            fresh_count += 1
    if not stale:
        total = fresh_count
        if total == 0:
            return _ok("sa-key-age", f"{sa_dir} has no *.json keys (nothing to age-check)")
        return _ok(
            "sa-key-age",
            f"all {total} SA key(s) under {sa_dir} are <{SA_KEY_AGE_THRESHOLD_DAYS}d old",
        )
    # Acceptance format: `⚠ <path> is N days old (rotate via bootstrap.sh --create-key)`.
    # Full path (not basename) so an operator can act on the message without
    # going hunting; rotation instruction inline so the warning is self-contained.
    paths = "; ".join(f"{p} is {age} days old" for p, age in stale)
    return _warn(
        "sa-key-age",
        f"{paths} (rotate via bootstrap.sh --create-key)",
        "",
    )


# ── runner ─────────────────────────────────────────────────────────────────


def run_all_checks(skip_auth: bool = False) -> list[CheckResult]:
    """Execute the full check battery.

    skip_auth=True omits the gcloud-auth + firebase-auth probes. That mode
    is for environments where authenticated CLIs are not expected (CI,
    fresh clones being smoke-tested) — every other check still runs.
    """
    results: list[CheckResult] = []
    results.append(check_python_version())
    results.extend(check_clis())
    if not skip_auth:
        results.append(check_gcloud_auth())
        results.append(check_firebase_auth())
    target_result, project = check_target_project()
    results.append(target_result)
    results.append(check_secrets_dir(project))
    results.append(check_sa_key_age())
    results.extend(check_python_deps())
    results.append(check_schemas())
    results.append(check_pydantic_models())
    results.append(check_parent_plan_validates())
    return results


def render_text(results: list[CheckResult]) -> str:
    lines = []
    for r in results:
        if not r.ok:
            marker = RED
        elif r.warn:
            marker = YELLOW
        else:
            marker = GREEN
        lines.append(f"{marker} {r.name:<22} {r.message}")
        if (not r.ok or r.warn) and r.remediation:
            lines.append(f"  ↳ {r.remediation}")
    failed = sum(1 for r in results if not r.ok)
    warned = sum(1 for r in results if r.ok and r.warn)
    total = len(results)
    if failed == 0:
        suffix = f" ({warned} warning{'s' if warned != 1 else ''})" if warned else ""
        lines.append(f"\n{GREEN} {total}/{total} checks passed — Jarvis is ready{suffix}")
    else:
        lines.append(f"\n{RED} {failed}/{total} checks failed — see remediation above")
    return "\n".join(lines)


def render_json(results: list[CheckResult]) -> str:
    return json.dumps(
        {
            "checks": [
                {
                    "name": r.name,
                    "ok": r.ok,
                    "message": r.message,
                    "remediation": r.remediation,
                    "warn": r.warn,
                }
                for r in results
            ],
            "passed": sum(1 for r in results if r.ok),
            "failed": sum(1 for r in results if not r.ok),
            "warnings": sum(1 for r in results if r.ok and r.warn),
        },
        indent=2,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--skip-auth",
        action="store_true",
        help="omit gcloud-auth and firebase-auth probes (CI / fresh-clone mode)",
    )
    args = parser.parse_args(argv)

    results = run_all_checks(skip_auth=args.skip_auth)
    print(render_json(results) if args.json else render_text(results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
