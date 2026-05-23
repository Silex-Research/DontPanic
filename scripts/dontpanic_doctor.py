"""jarvis_doctor.py — preflight health checks for a DontPanic install.

Run after `scripts/bootstrap.sh` (or after a fresh clone) to verify the
local setup is consistent. Each check returns (status, message); a single
red exits 1 with a remediation pointer.

Checks:
  1. Python version >= 3.10
  2. gcloud + firebase CLIs present + authenticated
  3. DONTPANIC_FIREBASE_PROJECT / JARVIS_FIREBASE_PROJECT is set OR environments.json is present
  4. .secrets/ exists, is gitignored, and the SA key matches the project
  5. Pydantic + pyyaml + firebase_admin importable
  6. agent-conventions schemas present + Pydantic models import-clean
  7. plan-artifact validator runs against parent orchestration plan

Plan 2026-05-03-001 F003 adds optional per-project preflight (off by
default for backward compat). When ``--include-projects`` is passed, the
doctor also surfaces:
  - global ``~/.dontpanic/config.json`` parses (legacy ``~/.jarvis`` fallback)
  - projects registry status (PASS, lists count)
  - per registered project: path exists, ``.dontpanic/dontpanic.json`` parses
    (legacy ``.jarvis/jarvis.json`` fallback),
    declared ``plans_dir`` exists or is creatable, declared agents are
    recognized by AGENT_REGISTRY, declared ``human_gates`` are valid

Usage:
  python3 scripts/jarvis_doctor.py              # full check (needs gcloud + firebase auth)
  python3 scripts/jarvis_doctor.py --skip-auth  # structural checks only (CI / fresh clone)
  python3 scripts/jarvis_doctor.py --json       # machine-readable output
  python3 scripts/jarvis_doctor.py --include-projects --strict-codes  # F003 wrapper mode

Exit codes (default — backward compat):
  0 — all checks green
  1 — at least one check failed (see output for remediation)

Exit codes (--strict-codes — F003 mode used by `dontpanic doctor`):
  0 — all PASS
  1 — at least one WARN, no FAIL
  2 — at least one FAIL
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # noqa: F401  # optional — only used by plan-cohesion validator
except ImportError:  # pragma: no cover — surfaced by check_python_deps
    yaml = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = REPO_ROOT / ".secrets"
ENV_FILE = REPO_ROOT / "environments.json"
ENV_EXAMPLE = REPO_ROOT / "environments.json.example"
SCHEMAS_DIR = REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0"
MODELS_DIR = REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0" / "models"
PARENT_PLAN_DIR = REPO_ROOT / "docs" / "plans" / "2026-04-19-001-infra-cross-agent-orchestration"
PLANS_ROOT = REPO_ROOT / "docs" / "plans"
ARCHITECTURE_JSON_PATH = REPO_ROOT / "docs" / "architecture" / "architecture.json"
# Plan 2026-05-19-004 F003: threshold for stale_minor vs stale_major.
# <5% changed → stale_minor (advisory), ≥5% → stale_major (blocker in --strict).
ARCHITECTURE_DRIFT_MAJOR_THRESHOLD = 0.05
# Cap the per-state changed_files list emitted in JSON output. Keeps the
# doctor payload bounded on large source-tree diffs while still giving the
# operator an actionable sample.
ARCHITECTURE_DRIFT_CHANGED_FILES_CAP = 20

# F001: SA-key age check looks under the resolved DontPanic home by default.
# DONTPANIC_SECRETS_DIR is preferred; JARVIS_SECRETS_DIR remains a legacy
# test / alternate-install override.
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
    # Optional structured probe details. Used by validate-plans-strict to
    # carry the per-plan detail array (plan_id + status + errors for every
    # walked plan) so JSON consumers get the full picture even when the
    # pretty text output folds clean plans into a summary line.
    details: list[dict] | None = None


def _ok(name: str, msg: str) -> CheckResult:
    return CheckResult(name=name, ok=True, message=msg)


def _bad(name: str, msg: str, remediation: str) -> CheckResult:
    return CheckResult(name=name, ok=False, message=msg, remediation=remediation)


def _warn(name: str, msg: str, remediation: str) -> CheckResult:
    """Soft signal — does NOT fail the doctor. Used when an operator may
    legitimately have out-of-band reasons for the surfaced state (e.g. a
    rotation cadence DontPanic doesn't know about)."""
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
        ["gcloud", "auth", "print-access-token"],  # noqa: S607  # PATH-relative gcloud invocation per D001
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
        ["firebase", "login:list"],  # noqa: S607  # PATH-relative firebase invocation per D001
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
    env_var = os.environ.get("DONTPANIC_FIREBASE_PROJECT") or os.environ.get(
        "JARVIS_FIREBASE_PROJECT"
    )
    if env_var:
        return _ok("target-project", f"target project env={env_var}"), env_var
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
            "edit environments.json with your real project ID, or set DONTPANIC_FIREBASE_PROJECT",
        ), None
    return _bad(
        "target-project",
        "no DONTPANIC_FIREBASE_PROJECT/JARVIS_FIREBASE_PROJECT and no environments.json",
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
    proc = subprocess.run(  # noqa: S603  # trusted argv + shell=False default per D001
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", str(SECRETS_DIR / "probe.json")],  # noqa: S607  # PATH-relative git invocation per D001
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
    proc = subprocess.run(  # noqa: S603  # trusted argv + shell=False default per D001
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
    override = os.environ.get("DONTPANIC_SECRETS_DIR") or os.environ.get("JARVIS_SECRETS_DIR")
    if override:
        return Path(override)
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import global_config as gc
    finally:
        sys.path.pop(0)
    return gc.dontpanic_home() / ".secrets"


def check_sa_key_age() -> CheckResult:
    """Soft warning when any *.json key under the SA key dir is older than
    SA_KEY_AGE_THRESHOLD_DAYS. Operators may have a rotation cadence we
    can't see, so this never fails the doctor — it just nudges. Honors
    DONTPANIC_SECRETS_DIR preferred, JARVIS_SECRETS_DIR legacy for synthetic fixtures."""
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


# ── plan 2026-05-11-002 F001: quota cap-entry surface ─────────────────────


def check_quota_caps(
    *,
    quota_state_path: Path | None = None,
    caps_path: Path | None = None,
    calibration_path: Path | None = None,
) -> list[CheckResult]:
    """Walk quota_state.json vendors × windows; emit one WARN per
    (vendor, window) pair that has live signal but no matching cap entry in
    quota_caps.json. Stale calibrations (>STALE_WARNING_DAYS old) emit a
    separate WARN per (vendor, window).
    Resolves the doctor friction surfaced by parent plan 2026-05-11-001
    dispatch: dispatch-time stderr warnings buried under volley logs are
    promoted to actionable doctor findings with copy-paste config snippets.
    Honors JARVIS_QUOTA_STATE_PATH / JARVIS_QUOTA_CAPS_PATH for hermetic
    test isolation (set by conftest.py). Calibration path defaults to
    calibration_loader.CALIBRATION_FILE; pass explicitly in tests so the
    operator's real ~/.jarvis/quota_calibration.json never bleeds in."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import calibration_loader, quota_admission, quota_caps_loader
    finally:
        sys.path.pop(0)

    if quota_state_path is None:
        quota_state_path = quota_admission._effective_quota_state_path()
    if caps_path is None:
        caps_path = quota_caps_loader.effective_caps_path()
    if calibration_path is None:
        calibration_path = calibration_loader.CALIBRATION_FILE

    if not quota_state_path.is_file():
        return [
            _ok(
                "quota-caps",
                f"{quota_state_path} not present — run `python3 scripts/quota_check.py` to populate",
            )
        ]
    try:
        state = json.loads(quota_state_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [
            _bad(
                "quota-caps",
                f"{quota_state_path} unreadable: {exc}",
                "regenerate via `python3 scripts/quota_check.py`",
            )
        ]

    try:
        caps = quota_caps_loader.load(caps_path)
    except quota_caps_loader.QuotaCapsError as exc:
        return [
            _bad(
                "quota-caps",
                f"caps file invalid or missing at {caps_path}: {exc}",
                "run: python -m dontpanic_orchestrate quota-caps init",
            )
        ]

    vendors = state.get("vendors") or {}
    if not isinstance(vendors, dict) or not vendors:
        return [_ok("quota-caps", "no vendors{} block in quota_state.json — nothing to check")]

    results: list[CheckResult] = []
    covered_count = 0

    for vendor in sorted(vendors):
        vblock = vendors.get(vendor) or {}
        if not isinstance(vblock, dict):
            continue
        tier = vblock.get("tier") or "unknown"
        # Skip vendors that the operator has not installed at all — empty
        # windows + absent tier means "no signal to cap".
        if tier == "absent":
            continue
        windows = vblock.get("windows") or {}
        if not isinstance(windows, dict):
            continue
        for wname in sorted(windows):
            wblock = windows.get(wname) or {}
            if not isinstance(wblock, dict):
                continue
            observed_native = wblock.get("observed_native")
            observed_unit = wblock.get("observed_unit") or "<unknown>"
            # Only flag windows with live signal — no-signal windows don't
            # need caps, that's the same rule evaluate_window applies.
            if not isinstance(observed_native, (int, float)) or observed_native <= 0:
                continue
            cap_block = quota_caps_loader.get(caps, vendor, tier, wname)
            if cap_block is not None:
                covered_count += 1
                continue
            results.append(
                _warn(
                    f"quota-caps:{vendor}.{tier}.{wname}",
                    f"{vendor}.{tier}.{wname} has signal "
                    f"({int(observed_native)} {observed_unit}) but no cap entry in {caps_path}",
                    _missing_cap_snippet(vendor, tier, wname, observed_native, observed_unit),
                )
            )

    # Stale calibration findings — separate from missing-cap findings because
    # the remediation is different (calibrate-claude, not edit caps file).
    calibration_data = calibration_loader.load(calibration_path)
    if isinstance(calibration_data, dict):
        for vendor in sorted(k for k in calibration_data if k != "schema_version"):
            vblock = calibration_data.get(vendor)
            if not isinstance(vblock, dict):
                continue
            for wname in sorted(vblock):
                wblock = vblock.get(wname)
                if not isinstance(wblock, dict):
                    continue
                if not calibration_loader.is_stale(wblock):
                    continue
                stamped = wblock.get("stamped_at") or "<unknown>"
                results.append(
                    _warn(
                        f"quota-caps:calibration:{vendor}.{wname}",
                        f"{vendor}.{wname} calibration is stale "
                        f"(stamped {stamped}, >{calibration_loader.STALE_WARNING_DAYS}d old)",
                        f"run: python -m dontpanic_orchestrate calibrate-claude "
                        f"--window {wname} --dashboard-pct N "
                        "(sample claude.ai/settings/usage first)",
                    )
                )

    if not results:
        results.append(
            _ok(
                "quota-caps",
                f"{covered_count} (vendor, window) signal pair(s) covered in {caps_path}; "
                "calibrations fresh",
            )
        )
    return results


def _missing_cap_snippet(
    vendor: str, tier: str, window: str, observed_native: float, observed_unit: str
) -> str:
    """Build a copy-paste config snippet for the operator. Picks the
    right cap.unit based on the observed unit; for Claude weighted tokens
    surfaces calibrate-claude as the prereq."""
    if vendor == "claude" and observed_unit == "weighted_tokens_local_proxy":
        cap_unit = "percent_of_plan"
        cap_value: int | str = 100
        note = (
            f"requires `calibrate-claude --window {window} --dashboard-pct N` "
            "before this cap is meaningful"
        )
    elif observed_unit in {"tokens_local_proxy", "weighted_tokens_local_proxy"}:
        cap_unit = observed_unit
        cap_value = max(int(observed_native * 1.25), 1)
        note = f"tuned to ~1.25x observed {window}; re-run `quota-caps init` to refresh"
    elif observed_unit == "requests":
        cap_unit = "requests"
        cap_value = 1000
        note = "vendor-published daily request cap (adjust to your plan)"
    else:
        cap_unit = observed_unit
        cap_value = "<replace>"
        note = "operator-determined"

    snippet = (
        f'add to ~/.jarvis/quota_caps.json under "{vendor}"."{tier}":\n'
        f'        "{window}": {{\n'
        f'          "cap": {cap_value},\n'
        f'          "unit": "{cap_unit}",\n'
        f'          "_note": "{note}"\n'
        f'        }}'
    )
    return snippet


# ── F003: global + per-project config preflight ────────────────────────────


def check_global_config() -> CheckResult:
    """Plan 2026-05-03-001 F003: global ``config.json`` parses if present.

    A missing file is the valid first-run zero state — PASS with a hint.
    A present-but-invalid file is FAIL: the global-config loader degrades
    to empty + WARN at runtime, but the doctor surfaces it explicitly so
    operators don't silently lose their declared defaults.
    """
    # Lazy import: keep the doctor importable from arbitrary cwds without
    # forcing scripts/ onto sys.path until the F003 checks actually run.
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import global_config as gc
    finally:
        sys.path.pop(0)

    path = gc.config_path()
    if not path.is_file():
        return _ok(
            "global-config",
            f"{path} not present (first-run zero state — defaults will fall through to hardcoded)",
        )
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return _bad(
            "global-config",
            f"{path} is not valid JSON: line {exc.lineno} col {exc.colno}: {exc.msg}",
            f"edit {path} to fix the JSON syntax error",
        )
    except OSError as exc:
        return _bad(
            "global-config",
            f"{path} is unreadable: {exc}",
            f"check file permissions on {path}",
        )
    try:
        gc.GlobalConfig.model_validate(raw)
    except Exception as exc:
        return _bad(
            "global-config",
            f"{path} fails schema validation: {exc}",
            f"edit {path} to remove unknown fields and match the expected schema",
        )
    return _ok("global-config", f"{path} parses + validates")


def check_projects_registry_status() -> CheckResult:
    """Plan 2026-05-03-001 F003: surface the registry's zero/non-zero state.

    Empty registry is a valid first-run state (PASS with a hint that
    nothing is registered yet — operators reading the doctor output then
    know to run `dontpanic projects add` if they expected projects to be
    registered). Non-empty: PASS with the count.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import projects_registry as pr
    finally:
        sys.path.pop(0)

    reg = pr.load_registry()
    n = len(reg.projects)
    if n == 0:
        return _ok(
            "projects-registry",
            "no projects registered (run `dontpanic projects add <name> <path>` to register)",
        )
    return _ok("projects-registry", f"{n} project(s) registered")


def check_registered_project(entry: object) -> list[CheckResult]:
    """Plan 2026-05-03-001 F003: per-project preflight for one registry entry.

    Runs five sub-checks, each surfaced as its own ``CheckResult`` so
    operators see exactly which check tripped. The check name suffix
    pins the entry's project name so JSON consumers can group by project.

    1. ``project:<name>:path``        — registered ``path`` exists on disk
    2. ``project:<name>:config``      — project config parses (if present)
    3. ``project:<name>:plans-dir``   — declared ``plans_dir`` exists or is creatable
    4. ``project:<name>:agents``      — declared implementer / auditor are in AGENT_REGISTRY
    5. ``project:<name>:gates``       — declared ``human_gates`` intersect canonical names

    ``entry`` is a ``ProjectEntry`` (typed as ``object`` in the signature
    to avoid a hard import dep — the F003 checks are lazy-loaded).
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import project_config as pc
    finally:
        sys.path.pop(0)

    name = entry.name
    path_str = entry.path
    project_path = Path(path_str).expanduser()

    results: list[CheckResult] = []

    # 1. path exists
    if not project_path.is_dir():
        results.append(
            _bad(
                f"project:{name}:path",
                f"registered path does not exist: {project_path}",
                (
                    f"run `dontpanic projects remove {name} --yes` to drop, "
                    "or `dontpanic projects add ... --force --yes` to relink"
                ),
            )
        )
        # If the path doesn't exist, the rest of the checks are moot —
        # bail out early so we don't dump confusing follow-on failures.
        return results
    results.append(_ok(f"project:{name}:path", f"path exists: {project_path}"))

    # 2. per-project config parses if present. Preferred path wins; legacy
    # .jarvis/jarvis.json remains readable when the preferred file is absent.
    config_path = pc.project_config_read_path(project_path)
    project_cfg: pc.ProjectConfig | None = None
    if config_path.is_file():
        try:
            raw = json.loads(config_path.read_text())
        except json.JSONDecodeError as exc:
            results.append(
                _bad(
                    f"project:{name}:config",
                    (
                        f"{config_path} is not valid JSON: "
                        f"line {exc.lineno} col {exc.colno}: {exc.msg}"
                    ),
                    f"edit {config_path} to fix the JSON syntax error",
                )
            )
            return results
        except OSError as exc:
            results.append(
                _bad(
                    f"project:{name}:config",
                    f"{config_path} is unreadable: {exc}",
                    f"check file permissions on {config_path}",
                )
            )
            return results
        try:
            project_cfg = pc.ProjectConfig.model_validate(raw)
        except Exception as exc:
            results.append(
                _bad(
                    f"project:{name}:config",
                    f"{config_path} fails schema validation: {exc}",
                    f"edit {config_path} — see the schema in project_config.py",
                )
            )
            return results
        results.append(_ok(f"project:{name}:config", f"{config_path} parses + validates"))
    else:
        results.append(
            _ok(
                f"project:{name}:config",
                f"{config_path} not present (per-project config is optional)",
            )
        )

    # 3. plans_dir exists OR is creatable. Declared plans_dir from the
    # config (or the default 'docs/plans' fallback) is checked as a
    # project-relative path. WARN (not FAIL) when missing — a fresh
    # project may not have authored any plans yet.
    plans_dir_rel = project_cfg.plans_dir if project_cfg is not None else pc.DEFAULT_PLANS_DIR
    plans_dir_abs = (project_path / plans_dir_rel).resolve()
    if plans_dir_abs.is_dir():
        results.append(_ok(f"project:{name}:plans-dir", f"plans dir exists: {plans_dir_abs}"))
    else:
        # Soft signal: the parent must exist and be writable for it to be
        # creatable. If the parent doesn't exist either, that's a sharper
        # signal still — surface but don't FAIL.
        creatable = plans_dir_abs.parent.is_dir()
        suffix = "" if creatable else " (parent dir also missing)"
        results.append(
            _warn(
                f"project:{name}:plans-dir",
                f"declared plans dir not present: {plans_dir_abs}{suffix}",
                f"create the directory or update plans_dir in {config_path}",
            )
        )

    # 4. declared agents are in AGENT_REGISTRY.
    declared_agents: list[tuple[str, str]] = []
    if project_cfg is not None:
        if project_cfg.implementer:
            declared_agents.append(("implementer", project_cfg.implementer))
        if project_cfg.auditor:
            declared_agents.append(("auditor", project_cfg.auditor))
    if declared_agents:
        unknown = [(role, agent) for role, agent in declared_agents if not pc.is_known_agent(agent)]
        if unknown:
            details = ", ".join(f"{role}={agent!r}" for role, agent in unknown)
            results.append(
                _bad(
                    f"project:{name}:agents",
                    f"declared agent(s) not in AGENT_REGISTRY: {details}",
                    (
                        f"edit {config_path} so implementer/auditor names "
                        "match registered executors (claude, codex)"
                    ),
                )
            )
        else:
            joined = ", ".join(f"{role}={agent}" for role, agent in declared_agents)
            results.append(_ok(f"project:{name}:agents", f"declared agents recognized: {joined}"))
    else:
        results.append(
            _ok(
                f"project:{name}:agents",
                "no per-project agent overrides (falls through to global / hardcoded)",
            )
        )

    # 5. declared human_gates are valid. Cross-validation already runs at
    # ProjectConfig.model_validate time; reaching here means the names
    # are known. Surface the count for visibility. If human_gates is None,
    # still PASS (no override declared).
    if project_cfg is not None and project_cfg.human_gates:
        results.append(
            _ok(
                f"project:{name}:gates",
                f"declared human_gates: {project_cfg.human_gates}",
            )
        )
    else:
        results.append(_ok(f"project:{name}:gates", "no per-project human_gates override"))

    return results


def check_registered_projects() -> list[CheckResult]:
    """Iterate the registry and run :func:`check_registered_project` for
    each entry. Returns the flattened list. When the registry is empty,
    returns ``[]`` — :func:`check_projects_registry_status` is the explicit
    zero-state surface."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import projects_registry as pr
    finally:
        sys.path.pop(0)

    reg = pr.load_registry()
    out: list[CheckResult] = []
    for entry in reg.projects:
        out.extend(check_registered_project(entry))
    return out


# ── plan 2026-05-12-001 F001: lock-time plan-cohesion validator ───────────
#
# D024 motivated this surface. Plan 004's pre-lock manual review caught two
# deterministic inconsistencies that would have cost ~9M tokens to discover
# mid-dispatch:
#   (a) child_charter.allowed_paths still pointed at archived axiom/ dirs
#       after the D006 rename to dashboard/, so feature steps named paths
#       outside the declared scope.
#   (b) F001 acceptance #4 demanded a smoke test against `<your-project-id>`
#       (a credentialed Firebase project), but parent_acceptance_item
#       explicitly deferred F003-F005 "until operator credentials in place".
#
# Both shapes are deterministic — a quick scan over the plan's own
# frontmatter + features.json would have surfaced them at lock time, before
# the operator paid for a dispatch. This validator is WARN-only and never
# blocks lock; it just surfaces drift via the doctor's existing CheckResult
# pipeline with copy-paste remediation hints.

# Path-shaped token detection. Two patterns:
#   1. Backtick-quoted strings (often used in step text for filenames).
#   2. Bare path-shaped tokens — contain a `/` and end in a known code
#      extension, OR are a bare filename ending in a known extension.
# Known extensions keep false-positives down (avoids matching "e.g." /
# "i.e." / version strings like "1.0.0" while still catching files like
# `dashboard/app.tsx` or `jarvis_doctor.py`).
_KNOWN_CODE_EXTS: frozenset[str] = frozenset(
    {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
        ".json", ".yaml", ".yml", ".toml", ".md", ".sh",
        ".rs", ".go", ".rb", ".swift", ".kt", ".java",
        ".html", ".css", ".scss", ".sql", ".jsonl",
    }
)
# Backtick-quoted segment (multi-line / inline).
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
# Path-shaped: optional dir parts, then filename.ext. The leading boundary
# avoids matching inside identifiers like `dontpanic_doctor` (which has
# no extension), and the trailing boundary stops before whitespace/punct.
_PATH_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_/])([A-Za-z0-9_./\-]+\.[A-Za-z]{1,6})(?![A-Za-z0-9])")

# Deferral language detection in parent_acceptance_item. Case-insensitive.
# Matches any of: "deferred", "defer", "until ... in place / available /
# provided / set up", "credential-gated", "pending credentials".
_DEFERRAL_RE = re.compile(
    r"\b("
    r"deferred?|"
    r"defer\b|"
    r"until\s+[^.]{1,80}?\b(in\s+place|available|provided|set\s+up|land[s]?|ready)\b|"
    r"credential[\s\-]?gated|"
    r"pending\s+credentials"
    r")",
    re.IGNORECASE,
)

# Resource-token detection in feature acceptance text. The signal we want
# is a Firebase-style / kebab-case identifier whose suffix carries a digit
# (`<your-project-id>`, `axiom-workspace-prod1`) — that pattern is what flags a
# real cloud resource as opposed to a method or option name. Plan-ID-shaped
# tokens (`2026-05-12-001-foo`) are filtered out separately so they don't
# false-positive on plan-internal references.
_RESOURCE_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])([a-z][a-z0-9]*-[a-z0-9-]*\d[a-z0-9-]*)(?![A-Za-z0-9])"
)
_PLAN_ID_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{3}\b")

# A plan is "locked" once `dontpanic plan lock` flips its frontmatter
# ``status`` from ``draft`` to ``active``; subsequent lifecycle states
# (``ready_for_audit``, ``in_audit``, ``completed``, ``abandoned``,
# ``blocked``) are also post-lock. ``draft`` is the only pre-lock state
# and is explicitly excluded — drift in a draft plan is expected, since
# the operator is still editing it. Missing status is treated as
# pre-lock for safety.
_LOCKED_PLAN_STATUSES: frozenset[str] = frozenset(
    {"active", "ready_for_audit", "in_audit", "completed", "abandoned", "blocked"}
)


def _is_locked_plan(fm: dict | None) -> bool:
    """Predicate: plan frontmatter indicates the plan is post-lock."""
    if not isinstance(fm, dict):
        return False
    status = fm.get("status")
    return isinstance(status, str) and status in _LOCKED_PLAN_STATUSES


def _read_plan_frontmatter(plan_md: Path) -> dict | None:
    """Cheap frontmatter parse without importing the full plan_loader.

    plan_loader imports models from agent-conventions which may not be on
    sys.path when the doctor runs from arbitrary cwds. Read the YAML
    frontmatter ourselves and return the dict; return None on any parse
    failure (caller skips the plan with a soft signal).
    """
    if yaml is None:
        return None
    try:
        text = plan_md.read_text()
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        loaded = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _extract_path_tokens(text: str) -> list[str]:
    """Return path-shaped tokens from ``text`` (steps / acceptance strings).

    Combines backtick-quoted segments with bare path-shaped tokens, then
    filters to entries whose extension is in ``_KNOWN_CODE_EXTS``. De-duped
    while preserving first-seen order so remediation hints stay stable.
    """
    seen: dict[str, None] = {}
    for raw in _BACKTICK_RE.findall(text):
        candidate = raw.strip()
        # Backticked segments may be globs (`dashboard/**`) or non-paths
        # (`is_advisory_only_findings_set(...)`). Accept globs explicitly
        # and otherwise require a known extension.
        if "**" in candidate or "*" in candidate:
            if "/" in candidate or candidate.endswith(tuple(_KNOWN_CODE_EXTS)):
                seen.setdefault(candidate, None)
            continue
        ext = Path(candidate).suffix.lower()
        if ext in _KNOWN_CODE_EXTS:
            seen.setdefault(candidate, None)
    for match in _PATH_TOKEN_RE.findall(text):
        ext = Path(match).suffix.lower()
        if ext not in _KNOWN_CODE_EXTS:
            continue
        seen.setdefault(match, None)
    return list(seen.keys())


def _path_matches_globs(path: str, globs: list[str]) -> bool:
    """fnmatch ``path`` against each glob. Treats trailing ``/**`` as
    "anything under this dir" so ``scripts/foo.py`` matches ``scripts/**``."""
    if not globs:
        return False
    for glob in globs:
        if fnmatch.fnmatch(path, glob):
            return True
        # Recursive glob convenience: ``scripts/**`` should match
        # ``scripts/foo.py`` AND ``scripts/sub/foo.py``. fnmatch alone
        # treats ** as one segment, so add the prefix-match shortcut.
        if glob.endswith("/**"):
            prefix = glob[:-3]
            if path == prefix or path.startswith(prefix + "/"):
                return True
        if glob.endswith("/*"):
            prefix = glob[:-2]
            if path.startswith(prefix + "/") and "/" not in path[len(prefix) + 1 :]:
                return True
    return False


def _extract_resource_tokens(text: str) -> list[str]:
    """Find kebab-case resource-shaped tokens that look like cloud project
    IDs (require a digit in the suffix). Excludes plan-ID prefixes."""
    out: list[str] = []
    seen: set[str] = set()
    for match in _RESOURCE_TOKEN_RE.findall(text):
        if match in seen:
            continue
        if _PLAN_ID_PREFIX_RE.match(match):
            continue
        seen.add(match)
        out.append(match)
    return out


def validate_plan_cohesion(plan_dir: Path) -> list[CheckResult]:
    """Lock-time plan-cohesion checks for a single plan directory.

    Returns a list of CheckResult — empty when the plan is internally
    consistent. Every finding is a WARN (ok=True, warn=True); the
    validator is deliberately advisory so it never blocks lock.

    Two finding shapes (plan 2026-05-12-001 F001 D024):

      1. allowed_paths drift: a step references a file path whose shape
         is outside every glob in ``child_charter.allowed_paths``.
      2. acceptance-vs-deferred conflict: ``parent_acceptance_item``
         contains deferral language AND a feature's acceptance string
         names a credentialed-resource-shaped token (e.g. ``<your-project-id>``).

    Plans without ``child_charter`` (top-level plans) skip both checks —
    there is no declared scope to cross-check against.
    """
    plan_md = plan_dir / "plan.md"
    features_json = plan_dir / "features.json"
    if not plan_md.is_file() or not features_json.is_file():
        return []

    fm = _read_plan_frontmatter(plan_md)
    if fm is None:
        return []
    charter = fm.get("child_charter")
    if not isinstance(charter, dict):
        return []  # top-level plan — no charter to cross-check
    allowed_paths = charter.get("allowed_paths") or []
    if not isinstance(allowed_paths, list):
        allowed_paths = []
    parent_acceptance = charter.get("parent_acceptance_item") or ""
    if not isinstance(parent_acceptance, str):
        parent_acceptance = ""

    try:
        features_blob = json.loads(features_json.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    features = features_blob.get("features") or []
    if not isinstance(features, list):
        return []

    plan_id = fm.get("id") or plan_dir.name
    results: list[CheckResult] = []
    has_deferral = bool(_DEFERRAL_RE.search(parent_acceptance))

    for feature in features:
        if not isinstance(feature, dict):
            continue
        fid = feature.get("id") or "?"
        # ── (1) allowed_paths-vs-step-paths drift ──
        if allowed_paths:
            steps = feature.get("steps") or []
            if isinstance(steps, list):
                drifted: list[str] = []
                for step in steps:
                    if not isinstance(step, str):
                        continue
                    for token in _extract_path_tokens(step):
                        if _path_matches_globs(token, allowed_paths):
                            continue
                        # Suppress bare filenames with no directory part —
                        # the doctor cannot tell whether ``foo.py`` is
                        # repo-root foo.py or some-subdir/foo.py without
                        # touching the filesystem. Globs that include the
                        # filename will match; the rest are intentionally
                        # below-the-bar to keep false-positives down.
                        if "/" not in token:
                            continue
                        drifted.append(token)
                if drifted:
                    deduped = sorted(set(drifted))
                    suggestion = _suggest_allowed_paths_fix(deduped, allowed_paths)
                    results.append(
                        _warn(
                            f"plan-cohesion:{plan_id}:{fid}:allowed-paths",
                            (
                                f"feature {fid} steps reference paths outside "
                                f"child_charter.allowed_paths: {deduped} "
                                f"(allowed={list(allowed_paths)})"
                            ),
                            suggestion,
                        )
                    )

        # ── (2) acceptance-vs-deferred-resource conflict ──
        # Per the F001 spec: flag resource names that appear in the
        # feature's acceptance string AND in parent_acceptance_item,
        # when the parent contains deferral language. The intersection
        # requirement keeps the check tight — a parent that merely uses
        # the word "deferred" should not condemn every credentialed
        # resource a feature happens to mention.
        if has_deferral:
            acceptance = feature.get("acceptance") or ""
            acc_text = acceptance if isinstance(acceptance, str) else ""
            acc_tokens = set(_extract_resource_tokens(acc_text))
            if acc_tokens:
                parent_tokens = set(_extract_resource_tokens(parent_acceptance))
                shared = sorted(acc_tokens & parent_tokens)
                if shared:
                    results.append(
                        _warn(
                            f"plan-cohesion:{plan_id}:{fid}:acceptance-deferred",
                            (
                                f"feature {fid} acceptance names credentialed "
                                f"resource(s) {shared} that also appear in "
                                "parent_acceptance_item alongside deferral "
                                "language — credentialed resources may not be "
                                "available at dispatch time"
                            ),
                            _suggest_acceptance_fix(fid, shared),
                        )
                    )

    return results


def _suggest_allowed_paths_fix(drifted: list[str], allowed: list[str]) -> str:
    """Copy-paste hint for the allowed-paths-drift finding. Picks the
    deepest common dir prefix from ``drifted`` and proposes adding it as a
    `<prefix>/**` glob — operator can refine downward from there."""
    prefixes = sorted({p.split("/", 1)[0] for p in drifted if "/" in p})
    if not prefixes:
        return f"add the file or its parent dir to child_charter.allowed_paths (current: {list(allowed)})"
    sample = prefixes[0]
    suggested = f"{sample}/**"
    return (
        "add the parent dir glob to child_charter.allowed_paths "
        f"(e.g. \"{suggested}\"), or remove the out-of-scope step. "
        f"Detected prefixes: {prefixes}"
    )


def _suggest_acceptance_fix(feature_id: str, tokens: list[str]) -> str:
    sample = tokens[0]
    return (
        f"rescope feature {feature_id} acceptance to a local fixture (no {sample!r}), "
        "or move the credentialed step to a follow-up plan, or update "
        "parent_acceptance_item to remove the deferral marker if the credentials "
        "are now in place"
    )


def check_plan_cohesion(plans_root: Path | None = None) -> list[CheckResult]:
    """Walk locked plans under ``plans_root`` and aggregate cohesion findings.

    ``plans_root`` defaults to ``<repo>/docs/plans``. Each subdirectory
    that has a ``plan.md`` is treated as a candidate plan; only those
    whose frontmatter ``status`` is post-lock (see
    :data:`_LOCKED_PLAN_STATUSES`) are validated — drafts are still
    being edited and drift there is expected. Returns an empty list
    when no findings are surfaced (caller renders a single PASS in that
    case). Plans without ``child_charter`` are skipped silently — they
    have no declared scope to cross-check against.
    """
    root = plans_root if plans_root is not None else PLANS_ROOT
    if not root.is_dir():
        return [
            _ok(
                "plan-cohesion",
                f"{root} not present (no plans to validate)",
            )
        ]
    findings: list[CheckResult] = []
    plan_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    walked = 0
    for plan_dir in plan_dirs:
        plan_md = plan_dir / "plan.md"
        if not plan_md.is_file():
            continue
        if not _is_locked_plan(_read_plan_frontmatter(plan_md)):
            continue  # draft / unparseable / non-lifecycle plan
        walked += 1
        findings.extend(validate_plan_cohesion(plan_dir))
    if not findings:
        return [
            _ok(
                "plan-cohesion",
                f"{walked} locked plan(s) under {root.relative_to(REPO_ROOT) if root.is_relative_to(REPO_ROOT) else root} "
                "internally consistent (allowed_paths + acceptance vs parent deferrals)",
            )
        ]
    return findings


# ── plan 2026-05-19-003 F003: strict jsonschema validation probe ─────────
#
# F001 closed the schema-vs-runtime gap by declaring orchestration /
# child_charter / commit_policy on plan.schema.json. F003 is the regression
# net: a doctor probe that walks every locked plan under docs/plans/ and
# runs `jsonschema.validate` against the v1.9 schema. Two modes:
#   - advisory (default)   — failures emit WARN, exit code stays 0 (or 1
#                            under --strict-codes, since WARN ⇒ 1).
#   - strict (--validate-plans-strict) — failures emit FAIL (ok=False),
#                            promoting the doctor to exit 2 under the
#                            strict-codes matrix.
# Both modes produce one CheckResult per locked plan (status: clean / fail)
# plus a summary CheckResult. `--json` renders the per-plan detail array
# inline via the existing CheckResult dump.


def _read_plan_frontmatter_for_validation(plan_md: Path) -> tuple[dict | None, str | None]:
    """Parse plan.md frontmatter for strict validation. Returns
    ``(frontmatter_dict, error)`` — exactly one is non-None. YAML parses
    ISO dates into ``date`` objects; the JSON schema's ``format: date``
    expects a string, so the date is coerced before returning to keep the
    contract aligned with what dispatch sees post-loader."""
    if yaml is None:
        return None, "pyyaml not importable"
    try:
        text = plan_md.read_text()
    except OSError as exc:
        return None, f"read failed: {exc}"
    if not text.startswith("---"):
        return None, "no YAML frontmatter (missing leading ---)"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, "unterminated YAML frontmatter (missing closing ---)"
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        return None, f"YAML parse error: {exc}"
    if not isinstance(fm, dict):
        return None, "frontmatter is not a mapping"
    if hasattr(fm.get("date"), "isoformat"):
        fm["date"] = fm["date"].isoformat()
    return fm, None


def validate_plans_strict(
    plans_root: Path | None = None,
    schema_path: Path | None = None,
    strict: bool = False,
) -> list[CheckResult]:
    """Walk locked plans under ``plans_root`` and validate each plan.md
    frontmatter against ``plan.schema.json`` (the v1.9 schema after the
    F001 fix).

    ``plans_root`` defaults to ``<repo>/docs/plans``. ``schema_path``
    defaults to ``<repo>/claude/shared/schemas/v1.0/plan.schema.json``.
    Locked status set matches :data:`_LOCKED_PLAN_STATUSES` — drafts are
    skipped (operator is still editing them; strict-validate drift there
    is expected).

    ``strict`` controls finding severity:
      - ``False`` (advisory): failures emit WARN (ok=True, warn=True).
        Exit code stays 0 under legacy, 1 under --strict-codes.
      - ``True`` (--validate-plans-strict): failures emit FAIL
        (ok=False). Exit code becomes 2 under --strict-codes.

    Returns a list of :class:`CheckResult` — one summary entry first,
    followed by one entry per plan-with-an-issue. Clean plans are folded
    into the summary count for the pretty text output, but the full
    per-plan detail array (including clean plans) is attached to the
    summary's ``details`` field so JSON consumers can recover the
    ``{plan_id, path, status, errors}`` shape for every walked plan.

    The check name prefix is ``validate-plans-strict``; JSON consumers
    can grep that prefix to extract per-plan failure entries, or read
    ``details`` on the summary entry to enumerate every walked plan.
    """
    if plans_root is None:
        plans_root = PLANS_ROOT
    if schema_path is None:
        schema_path = SCHEMAS_DIR / "plan.schema.json"

    if not plans_root.is_dir():
        summary = _ok(
            "validate-plans-strict",
            f"{plans_root} not present (no plans to validate)",
        )
        summary.details = []
        return [summary]
    if not schema_path.is_file():
        return [
            _bad(
                "validate-plans-strict",
                f"plan schema missing at {schema_path}",
                "subtree pull agent-conventions",
            )
        ]
    try:
        import jsonschema  # noqa: PLC0415  # deferred until probe runs
    except ImportError:
        return [
            _bad(
                "validate-plans-strict",
                "jsonschema not importable — cannot run strict plan validation",
                "pip install jsonschema",
            )
        ]
    try:
        schema = json.loads(schema_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [
            _bad(
                "validate-plans-strict",
                f"plan schema unreadable at {schema_path}: {exc}",
                "verify claude/shared/ subtree integrity",
            )
        ]

    findings: list[CheckResult] = []
    walked = 0
    clean_count = 0
    fail_count = 0
    parse_error_count = 0
    # Per-plan detail array. Includes every walked plan (clean + failing
    # + parse-error) so the JSON summary carries the full plan_id/status
    # detail array the F003 acceptance pins.
    details: list[dict] = []

    def _path_str(p: Path) -> str:
        if p.is_relative_to(plans_root.parent):
            return str(p.relative_to(plans_root.parent))
        return str(p)

    for plan_dir in sorted(p for p in plans_root.iterdir() if p.is_dir()):
        plan_md = plan_dir / "plan.md"
        if not plan_md.is_file():
            continue
        fm, parse_err = _read_plan_frontmatter_for_validation(plan_md)
        if fm is None:
            # Plan 3 F003 i1 auditor finding (medium/correctness): the
            # loop is already scoped to ``docs/plans/<dir>/plan.md`` —
            # the file IS the plan, not a sibling. Treat missing
            # frontmatter as a parse_error like every other malformed
            # case so strict mode catches false-greens.
            plan_id = plan_dir.name
            check_name = f"validate-plans-strict:{plan_id}"
            walked += 1
            parse_error_count += 1
            fail_count += 1
            message = f"{plan_id} frontmatter unreadable: {parse_err}"
            remediation = (
                f"fix YAML frontmatter in {_path_str(plan_md)} "
                "(must start with --- and parse as a mapping)"
            )
            findings.append(
                _bad(check_name, message, remediation) if strict
                else _warn(check_name, message, remediation)
            )
            details.append({
                "plan_id": plan_id,
                "path": _path_str(plan_md),
                "status": "parse_error",
                "error": parse_err,
            })
            continue
        if not _is_locked_plan(fm):
            continue
        walked += 1
        plan_id = fm.get("id") or plan_dir.name
        check_name = f"validate-plans-strict:{plan_id}"

        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(fm))
        if not errors:
            clean_count += 1
            details.append({
                "plan_id": plan_id,
                "path": _path_str(plan_md),
                "status": "clean",
            })
            continue
        fail_count += 1
        # Surface the first 3 errors per plan so the operator gets a usable
        # signal without drowning the doctor output. Each error reports the
        # absolute_path so multi-issue plans don't read as a single blob.
        detail_lines = []
        error_records: list[dict] = []
        for err in errors:
            loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
            error_records.append({"field": loc, "message": err.message})
        for err_record in error_records[:3]:
            detail_lines.append(f"{err_record['field']}: {err_record['message'][:200]}")
        more = "" if len(errors) <= 3 else f" (+{len(errors) - 3} more)"
        message = f"{plan_id} failed strict schema validation: " + "; ".join(detail_lines) + more
        remediation = (
            f"edit {_path_str(plan_md)}, "
            "OR if the schema is too tight, widen it via an additive bump in claude/shared/schemas/v1.0/plan.schema.json "
            "(strict-mode failures often indicate schema drift, not authoring error)."
        )
        status_label = "fail" if strict else "warn"
        if strict:
            findings.append(_bad(check_name, message, remediation))
        else:
            findings.append(_warn(check_name, message, remediation))
        details.append({
            "plan_id": plan_id,
            "path": _path_str(plan_md),
            "status": status_label,
            "errors": error_records,
        })

    # Summary always first so the rendered output reads "summary, then
    # details". When everything is green this is the only entry; the
    # per-plan detail array still rides along on summary.details so JSON
    # consumers see every walked plan.
    if fail_count == 0:
        summary = _ok(
            "validate-plans-strict",
            f"{walked} locked plan(s) under {plans_root.relative_to(REPO_ROOT) if plans_root.is_relative_to(REPO_ROOT) else plans_root} "
            f"validate clean against {schema_path.name}",
        )
        summary.details = details
        return [summary]
    summary_msg = (
        f"{walked} locked plan(s) walked: {clean_count} clean, {fail_count} failing strict validation "
        f"(mode={'strict' if strict else 'advisory'})"
    )
    if parse_error_count:
        summary_msg += f" — {parse_error_count} plan(s) had unparseable frontmatter"
    if strict:
        summary = _bad(
            "validate-plans-strict",
            summary_msg,
            "re-run after fixing per-plan failures listed below, or widen the schema additively if drift caused this",
        )
    else:
        summary = _warn(
            "validate-plans-strict",
            summary_msg,
            "re-run with --validate-plans-strict to promote failures to blockers; "
            "or widen the schema additively if drift caused this",
        )
    summary.details = details
    return [summary, *findings]


# ── plan 2026-05-19-004 F003: architecture-drift probe ────────────────────
#
# Reuses F001's Crawler.fingerprint() to compute the current source-tree
# hash, compares against the per-file map stored in
# ``docs/architecture/architecture.json``, and classifies the result:
#
#   fresh         — file_hashes_root matches → no action
#   stale_minor   — <5% of files (added + removed + modified) differ → WARN,
#                   advisory in both default and --strict modes
#   stale_major   — ≥5% of files differ → WARN in default mode, FAIL in
#                   --strict mode
#   absent        — architecture.json missing entirely → WARN in default
#                   mode, FAIL in --strict mode
#
# The probe attaches a structured ``details`` payload on the CheckResult so
# JSON consumers see state + truncated changed_files lists + recommendation.


# Required source-tree prefixes. If the stored fingerprint had ≥1 file under
# any of these and the current tree has zero, an entire subsystem has vanished
# — that's structural drift, not "a few files moved", so it must promote to
# stale_major regardless of the ratio. Without this guard, deleting all of
# docs/plans/ on a small repo could still classify as stale_minor when removed
# files are <5% of the union.
ARCHITECTURE_DRIFT_REQUIRED_PREFIXES: tuple[str, ...] = (
    "scripts/dontpanic_orchestrate/",
    "claude/shared/schemas/",
    "docs/plans/",
)
ARCHITECTURE_DRIFT_REQUIRED_FILES: tuple[str, ...] = ("claude/shared/VERSION",)


def _missing_required_surfaces(
    *,
    stored_map: dict[str, str],
    current_map: dict[str, str],
) -> list[str]:
    """Return the list of required prefixes/files that the stored snapshot
    covered but that have disappeared from the current tree.

    Empty list = no structural loss. Any non-empty list forces stale_major
    in :func:`_classify_architecture_drift` so a missing module surface or
    plans directory can't masquerade as minor drift.
    """
    missing: list[str] = []
    for prefix in ARCHITECTURE_DRIFT_REQUIRED_PREFIXES:
        had = any(path.startswith(prefix) for path in stored_map)
        has = any(path.startswith(prefix) for path in current_map)
        if had and not has:
            missing.append(prefix)
    for fname in ARCHITECTURE_DRIFT_REQUIRED_FILES:
        if fname in stored_map and fname not in current_map:
            missing.append(fname)
    return missing


def _classify_architecture_drift(
    *,
    stored_map: dict[str, str] | None,
    current_map: dict[str, str],
) -> tuple[str, dict[str, list[str]], int, int, list[str]]:
    """Diff the stored per-file hash map against the current one.

    Returns ``(state, changes, unchanged_count, total_count, missing_required)``
    where:
      * ``state`` ∈ {``fresh``, ``stale_minor``, ``stale_major``}
      * ``changes`` has keys ``added`` / ``removed`` / ``modified``
      * ``unchanged_count`` is the number of files whose hash didn't move
      * ``total_count`` is the union cardinality used to derive the ratio
      * ``missing_required`` lists required surfaces (modules/schemas/plans/
        VERSION) that the stored snapshot covered but the current tree
        no longer does — any non-empty value forces ``stale_major``.

    A missing stored map cannot be diffed at file level; callers handle
    that branch (ABSENT) before invoking this helper.
    """
    stored = stored_map or {}
    stored_keys = set(stored.keys())
    current_keys = set(current_map.keys())
    added = sorted(current_keys - stored_keys)
    removed = sorted(stored_keys - current_keys)
    modified = sorted(
        path for path in current_keys & stored_keys if current_map[path] != stored[path]
    )
    union = stored_keys | current_keys
    total = len(union) or 1
    changed = len(added) + len(removed) + len(modified)
    unchanged = total - changed
    missing_required = _missing_required_surfaces(
        stored_map=stored, current_map=current_map
    )
    if missing_required:
        # Structural loss always trumps the ratio classifier: a vanished
        # subsystem is major drift regardless of how few files differ.
        state = "stale_major"
    elif changed == 0:
        state = "fresh"
    elif changed / total < ARCHITECTURE_DRIFT_MAJOR_THRESHOLD:
        state = "stale_minor"
    else:
        state = "stale_major"
    return (
        state,
        {"added": added, "removed": removed, "modified": modified},
        unchanged,
        total,
        missing_required,
    )


def _truncate_changed_files(
    changes: dict[str, list[str]],
    *,
    cap: int = ARCHITECTURE_DRIFT_CHANGED_FILES_CAP,
) -> dict[str, list[str]]:
    """Bound each change list to ``cap`` entries for the JSON payload.

    Operators see "<list[:cap]> + N more" rather than a 1000-line dump
    when a refactor touches a large fraction of the tree. Doesn't mutate
    the input map.
    """
    out: dict[str, list[str]] = {}
    for kind, paths in changes.items():
        if len(paths) <= cap:
            out[kind] = list(paths)
        else:
            out[kind] = [*paths[:cap], f"… +{len(paths) - cap} more"]
    return out


def _flatten_changed_files(changes: dict[str, list[str]]) -> list[str]:
    """Collapse the categorized ``{added, removed, modified}`` map into a
    single flat list with ``<kind>: <path>`` entries.

    The top-level ``architecture_drift`` JSON section consumes this so
    machine readers see the per-file changes as a stable list (acceptance
    step #3), while the categorized form stays available under
    ``checks[].details[].changed_files`` for richer triage.
    """
    out: list[str] = []
    for kind in ("added", "removed", "modified"):
        for path in changes.get(kind, []):
            out.append(f"{kind}: {path}")
    return out


def _architecture_drift_recommendation(state: str) -> str:
    if state == "fresh":
        return "no action — architecture.json fingerprint matches current source tree"
    if state == "stale_minor":
        return (
            "minor drift (<5% files changed). Consider running "
            "`python -m dontpanic_orchestrate architecture regen` at your next "
            "convenience to refresh docs/architecture/architecture.json."
        )
    if state == "stale_major":
        return (
            "major drift (≥5% files changed). Run "
            "`python -m dontpanic_orchestrate architecture regen` before "
            "downstream consumers (Plan 4.5 `dontpanic new`, F004 supervisor "
            "regen hook) read a stale snapshot."
        )
    # absent
    return (
        "docs/architecture/architecture.json is missing. Run "
        "`python -m dontpanic_orchestrate architecture regen` to create the "
        "snapshot — downstream consumers degrade gracefully but lose context."
    )


def check_architecture_drift(
    *,
    repo_root: Path | None = None,
    architecture_path: Path | None = None,
    strict: bool = False,
) -> CheckResult:
    """Plan 2026-05-19-004 F003 — architecture-drift probe.

    Reads the stored fingerprint from ``architecture.json`` and compares
    it against the live source tree (via F001's :class:`Crawler`). Emits
    a single :class:`CheckResult` whose ``details`` payload carries the
    structured drift report so JSON consumers see state + change lists +
    recommendation alongside the human-facing message.

    ``strict`` controls severity for ``stale_major`` and ``absent``: in
    advisory mode (default) both surface as WARN; in strict mode both
    promote to FAIL so the strict-codes exit matrix returns exit 2.
    ``stale_minor`` is always advisory — minor drift is expected during
    normal development and shouldn't block a doctor sweep.
    """
    repo_root = (repo_root or REPO_ROOT).resolve()
    arch_path = (architecture_path or (repo_root / "docs" / "architecture" / "architecture.json")).resolve()

    # Lazy import — keep the doctor importable without dragging in the
    # crawler module at module-load time.
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import architecture as arch
    finally:
        sys.path.pop(0)

    name = "architecture-drift"
    remediation_cmd = "python -m dontpanic_orchestrate architecture regen"

    # ── ABSENT ────────────────────────────────────────────────────────
    if not arch_path.is_file():
        details = {
            "state": "absent",
            "architecture_path": str(arch_path),
            "changed_files": {"added": [], "removed": [], "modified": []},
            "changed_files_list": [],
            "unchanged_files": 0,
            "recommendation": _architecture_drift_recommendation("absent"),
        }
        message = f"architecture.json missing at {arch_path.relative_to(repo_root) if arch_path.is_relative_to(repo_root) else arch_path}"
        if strict:
            result = _bad(name, message, remediation_cmd)
        else:
            result = _warn(name, message, remediation_cmd)
        result.details = [details]
        return result

    # ── compute current fingerprint + diff ────────────────────────────
    try:
        crawler = arch.Crawler(repo_root)
        current_fp = crawler.fingerprint()
    except Exception as exc:  # noqa: BLE001 — surface any crawler failure
        result = _bad(
            name,
            f"failed to compute current fingerprint: {exc.__class__.__name__}: {exc}",
            "investigate scripts/dontpanic_orchestrate/architecture.py — crawler raised",
        )
        result.details = [{"state": "error", "error": str(exc)}]
        return result

    try:
        prior = json.loads(arch_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        message = f"architecture.json unreadable at {arch_path}: {exc}"
        if strict:
            result = _bad(name, message, remediation_cmd)
        else:
            result = _warn(name, message, remediation_cmd)
        result.details = [{"state": "absent", "error": str(exc)}]
        return result

    prior_fp = prior.get("source_fingerprint") or {}
    stored_root = prior_fp.get("file_hashes_root")
    stored_map = prior_fp.get("file_hashes") if isinstance(prior_fp.get("file_hashes"), dict) else None

    current_map: dict[str, str] = current_fp["file_hashes"]
    current_root = current_fp["file_hashes_root"]

    # Fast path: root hashes match → definitely fresh, no diff needed.
    if stored_root == current_root:
        details = {
            "state": "fresh",
            "architecture_path": str(arch_path),
            "stored_fingerprint": stored_root,
            "current_fingerprint": current_root,
            "changed_files": {"added": [], "removed": [], "modified": []},
            "changed_files_list": [],
            "unchanged_files": current_fp["files_count"],
            "files_count_current": current_fp["files_count"],
            "files_count_stored": prior_fp.get("files_count"),
            "recommendation": _architecture_drift_recommendation("fresh"),
        }
        result = _ok(name, f"fresh — {current_fp['files_count']} tracked files match stored fingerprint")
        result.details = [details]
        return result

    # Roots disagree but no per-file map (legacy snapshot). Treat as
    # stale_major: we can't compute the change ratio, and the operator
    # needs to regen to repopulate the per-file map anyway.
    if stored_map is None:
        details = {
            "state": "stale_major",
            "architecture_path": str(arch_path),
            "stored_fingerprint": stored_root,
            "current_fingerprint": current_root,
            "changed_files": {"added": [], "removed": [], "modified": []},
            "changed_files_list": [],
            "unchanged_files": 0,
            "files_count_current": current_fp["files_count"],
            "files_count_stored": prior_fp.get("files_count"),
            "detail_available": False,
            "recommendation": _architecture_drift_recommendation("stale_major"),
        }
        message = (
            "stale (no per-file detail available — legacy snapshot). "
            f"Regen to repopulate file_hashes map at {arch_path}."
        )
        if strict:
            result = _bad(name, message, remediation_cmd)
        else:
            result = _warn(name, message, remediation_cmd)
        result.details = [details]
        return result

    state, changes, unchanged_count, total, missing_required = _classify_architecture_drift(
        stored_map=stored_map,
        current_map=current_map,
    )
    changed_count = total - unchanged_count
    pct = (changed_count / total) * 100 if total else 0.0
    truncated = _truncate_changed_files(changes)

    details = {
        "state": state,
        "architecture_path": str(arch_path),
        "stored_fingerprint": stored_root,
        "current_fingerprint": current_root,
        "changed_files": truncated,
        "changed_files_list": _flatten_changed_files(truncated),
        "changed_files_total": changed_count,
        "unchanged_files": unchanged_count,
        "files_count_current": current_fp["files_count"],
        "files_count_stored": prior_fp.get("files_count"),
        "drift_pct": round(pct, 2),
        "missing_required": missing_required,
        "recommendation": _architecture_drift_recommendation(state),
    }

    if state == "fresh":
        result = _ok(name, "fresh — fingerprint matches after diff")
        result.details = [details]
        return result

    missing_suffix = (
        f"; missing required surface(s): {', '.join(missing_required)}"
        if missing_required
        else ""
    )
    message = (
        f"{state} — {changed_count}/{total} files differ ({pct:.1f}%): "
        f"added={len(changes['added'])} removed={len(changes['removed'])} "
        f"modified={len(changes['modified'])}"
        f"{missing_suffix}"
    )

    # stale_minor stays advisory in both modes per acceptance step 4.
    if state == "stale_minor":
        result = _warn(name, message, remediation_cmd)
    elif strict:
        result = _bad(name, message, remediation_cmd)
    else:
        result = _warn(name, message, remediation_cmd)
    result.details = [details]
    return result


# ── dashboard-readiness (plan 2026-05-23-004 F005) ────────────────────────


def check_dashboard_readiness(
    *,
    repo_root: Path | None = None,
) -> list[CheckResult]:
    """Plan 2026-05-23-004 F005 — advisory dashboard readiness probes.

    Surfaces three V0 advisory checks for the local operator console:

      * ``dashboard-files``  — ``dashboard/index.html`` exists.
      * ``dashboard-cache``  — the operator-local what-now cache exists at
        ``<dontpanic_home>/dashboard/what-now.json``.
      * ``dashboard-state``  — ``dashboard/state/state-snapshot.json``
        and ``what-now.json`` exist alongside the static dashboard.

    All three emit ADVISORY (WARN) when missing — V0 acceptance #2 keeps
    these advisory; a missing dashboard cache is not a doctor failure,
    just a remediation pointer at the operator. The exact remediation
    command appears in ``remediation`` so the strict-codes path still
    treats them as non-fatal under the default ``--strict-codes`` flag.

    Architecture freshness is already surfaced by
    :func:`check_architecture_drift`; this set of probes targets only the
    dashboard surfaces the operator console depends on.
    """

    repo_root = (repo_root or REPO_ROOT).resolve()
    results: list[CheckResult] = []

    dashboard_dir = repo_root / "dashboard"
    index_html = dashboard_dir / "index.html"
    if index_html.is_file():
        results.append(
            _ok(
                "dashboard-files",
                f"static dashboard present at {dashboard_dir.name}/index.html",
            )
        )
    else:
        results.append(
            _warn(
                "dashboard-files",
                f"dashboard/index.html missing at {dashboard_dir}",
                "run: git restore -- dashboard/index.html",
            )
        )

    # Operator-local what-now cache (~/.dontpanic/dashboard/what-now.json
    # by default; honors $DONTPANIC_HOME / $JARVIS_HOME for tests).
    try:
        # Lazy import — keep doctor importable without dragging the
        # orchestrate package into module-load time.
        sys.path.insert(0, str(repo_root / "scripts"))
        try:
            from dontpanic_orchestrate import operator_console as _oc
        finally:
            sys.path.pop(0)
        cache_path = _oc.default_cache_path()
    except Exception as exc:  # noqa: BLE001 — surface as WARN with remediation
        results.append(
            _warn(
                "dashboard-cache",
                f"could not resolve dashboard cache path: {exc.__class__.__name__}",
                "run: dontpanic dashboard build",
            )
        )
    else:
        if cache_path.is_file():
            results.append(
                _ok("dashboard-cache", f"what-now cache present at {cache_path}")
            )
        else:
            results.append(
                _warn(
                    "dashboard-cache",
                    f"what-now cache missing at {cache_path}",
                    "run: dontpanic dashboard build",
                )
            )

    # Static dashboard state dir — populated by `dontpanic dashboard build`.
    state_dir = dashboard_dir / "state"
    snapshot = state_dir / "state-snapshot.json"
    what_now = state_dir / "what-now.json"
    missing = [p.name for p in (snapshot, what_now) if not p.is_file()]
    if not missing:
        results.append(
            _ok(
                "dashboard-state",
                "dashboard/state has state-snapshot.json + what-now.json",
            )
        )
    else:
        results.append(
            _warn(
                "dashboard-state",
                f"dashboard/state missing: {', '.join(missing)}",
                "run: dontpanic dashboard build",
            )
        )

    return results


# ── runner ─────────────────────────────────────────────────────────────────


def run_all_checks(
    skip_auth: bool = False,
    include_projects: bool = False,
    validate_plans: bool = False,
    validate_plans_strict_mode: bool | None = None,
    architecture_drift_strict_mode: bool | None = None,
    plans_root: Path | None = None,
    architecture_json: Path | None = None,
) -> list[CheckResult]:
    """Execute the full check battery.

    skip_auth=True omits the gcloud-auth + firebase-auth probes. That mode
    is for environments where authenticated CLIs are not expected (CI,
    fresh clones being smoke-tested) — every other check still runs.

    Plan 2026-05-03-001 F003: ``include_projects=True`` also runs the
    global-config check, the registry-status check, and the per-project
    preflight for each registered project. Off by default for backward
    compat (existing `python3 scripts/jarvis_doctor.py` invocation
    behavior is unchanged); the new ``dontpanic doctor`` subcommand passes
    ``include_projects=True``.

    Plan 2026-05-12-001 F001: ``validate_plans=True`` additionally walks
    every plan under ``docs/plans/`` and surfaces WARN findings for
    ``child_charter.allowed_paths`` vs feature-step path drift and
    acceptance-vs-deferred-resource conflicts (D024). Advisory only — it
    never fails the doctor.

    Plan 2026-05-19-003 F003: the strict plan-schema validation probe
    (``validate_plans_strict``) always runs — it's the regression net
    that makes future schema drift visible. ``validate_plans_strict_mode``
    controls severity: ``None`` (the default) and ``False`` keep failures
    as advisory WARN entries; ``True`` (set by ``--validate-plans-strict``)
    promotes failures to FAIL so the strict-codes matrix returns exit 2.

    Plan 2026-05-19-004 F003: the architecture-drift probe
    (``check_architecture_drift``) always runs and reads the stored
    source_fingerprint in docs/architecture/architecture.json.
    ``architecture_drift_strict_mode`` controls severity for ``stale_major``
    and ``absent``: ``None`` / ``False`` keep both as advisory WARN
    (legacy 0/1 exit stays 0); ``True`` (``--architecture-drift-strict``)
    promotes both to FAIL so the strict-codes matrix returns exit 2.
    ``stale_minor`` is always advisory.
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
    results.extend(check_quota_caps())
    if include_projects:
        results.append(check_global_config())
        results.append(check_projects_registry_status())
        results.extend(check_registered_projects())
    if validate_plans:
        results.extend(check_plan_cohesion())
    results.extend(
        validate_plans_strict(
            plans_root=plans_root,
            strict=bool(validate_plans_strict_mode),
        )
    )
    results.append(
        check_architecture_drift(
            architecture_path=architecture_json,
            strict=bool(architecture_drift_strict_mode),
        )
    )
    # Plan 2026-05-23-004 F005: advisory dashboard readiness probes.
    # Failures here emit WARN with exact remediation commands; they
    # never escalate to FAIL because V0 keeps the local operator
    # console optional (operators may legitimately not yet have run
    # `dontpanic dashboard build`).
    results.extend(check_dashboard_readiness())
    return results


def compute_strict_exit(results: list[CheckResult]) -> int:
    """Plan 2026-05-03-001 F003 exit-code matrix.

    0 — every result is PASS (ok=True, warn=False)
    1 — at least one WARN, no FAIL
    2 — at least one FAIL (ok=False)

    Default ``main()`` uses the legacy 0/1 contract; the new
    ``dontpanic doctor`` subcommand (and ``--strict-codes``) use this matrix.
    """
    if any(not r.ok for r in results):
        return 2
    if any(r.warn for r in results):
        return 1
    return 0


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
        lines.append(f"\n{GREEN} {total}/{total} checks passed — DontPanic is ready{suffix}")
    else:
        lines.append(f"\n{RED} {failed}/{total} checks failed — see remediation above")
    return "\n".join(lines)


def _architecture_drift_section(results: list[CheckResult]) -> dict | None:
    """Plan 2026-05-19-004 F003: build the top-level ``architecture_drift``
    JSON section.

    Surfaces the drift probe at a stable, named location so JSON consumers
    (Plan 4.5 ``dontpanic new`` context gatherer, F004 supervisor regen
    hook, audit pipelines) don't have to scan ``checks[]`` and string-match
    on the probe name. Mirrors the probe's structured details payload but
    flattens ``changed_files`` to a list per the acceptance contract.

    Returns ``None`` if the probe didn't run (defensive — the doctor always
    runs it, but ``render_json`` may receive a subset for testing).
    """
    for r in results:
        if r.name != "architecture-drift" or not r.details:
            continue
        detail = r.details[0]
        return {
            "state": detail.get("state"),
            "changed_files": detail.get("changed_files_list", []),
            "changed_files_categorized": detail.get(
                "changed_files", {"added": [], "removed": [], "modified": []}
            ),
            "changed_files_total": detail.get("changed_files_total", 0),
            "unchanged_files": detail.get("unchanged_files", 0),
            "missing_required": detail.get("missing_required", []),
            "recommendation": detail.get("recommendation"),
            "ok": r.ok,
            "warn": r.warn,
        }
    return None


def render_json(results: list[CheckResult]) -> str:
    def _check_dict(r: CheckResult) -> dict:
        d = {
            "name": r.name,
            "ok": r.ok,
            "message": r.message,
            "remediation": r.remediation,
            "warn": r.warn,
        }
        if r.details is not None:
            d["details"] = r.details
        return d

    payload: dict[str, Any] = {
        "checks": [_check_dict(r) for r in results],
        "passed": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if not r.ok),
        "warnings": sum(1 for r in results if r.ok and r.warn),
    }
    drift_section = _architecture_drift_section(results)
    if drift_section is not None:
        payload["architecture_drift"] = drift_section
    return json.dumps(payload, indent=2)


def _load_prereq_registry():
    """Import prereq_registry lazily so the legacy no-flag path stays
    independent of the new module. Returns the module object."""
    import importlib

    return importlib.import_module("dontpanic_orchestrate.prereq_registry")


def _run_profile_aware(
    profile: str,
    profile_strict: bool,
    as_json: bool,
    repo_root: Path,
    legacy_results: list[CheckResult],
) -> tuple[int, str]:
    """Plan 2026-05-19-002 F001 — new profile-aware path.

    Returns ``(exit_code, rendered_output)``. The exit code is the strict
    0/1/2 matrix applied to the PROBE sweep specifically. The legacy
    check set runs alongside but does NOT change the profile-aware exit
    code (callers can layer the legacy verdict separately if they want).
    """
    pr = _load_prereq_registry()
    activation_context = pr.build_activation_context(repo_root)
    sweep = pr.run_sweep(
        profile=profile,
        activation_context=activation_context,
        profile_strict=profile_strict,
    )
    exit_code = sweep.exit_code()
    if as_json:
        envelope = pr.envelope_for_sweep(
            sweep,
            legacy_checks=[
                {
                    "name": r.name,
                    "ok": r.ok,
                    "warn": r.warn,
                    "message": r.message,
                }
                for r in legacy_results
            ],
        )
        return exit_code, json.dumps(envelope, indent=2)
    return exit_code, pr.render_sweep_text(sweep)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--skip-auth",
        action="store_true",
        help="omit gcloud-auth and firebase-auth probes (CI / fresh-clone mode)",
    )
    parser.add_argument(
        "--include-projects",
        action="store_true",
        help=(
            "Plan 2026-05-03-001 F003: also run global-config + per-project "
            "preflight (off by default for backward compat). The `dontpanic doctor` "
            "subcommand passes this implicitly."
        ),
    )
    parser.add_argument(
        "--strict-codes",
        action="store_true",
        help=(
            "Plan 2026-05-03-001 F003: use the 0/1/2 exit code matrix "
            "(0=PASS, 1=WARN, 2=FAIL) instead of the legacy 0/1 (0=all-ok, "
            "1=any-fail). The `dontpanic doctor` subcommand passes this implicitly."
        ),
    )
    parser.add_argument(
        "--validate-plans",
        action="store_true",
        help=(
            "Plan 2026-05-12-001 F001 (D024): walk every plan under "
            "docs/plans/ and surface WARN findings for child_charter."
            "allowed_paths vs feature-step path drift and acceptance-"
            "vs-deferred-resource conflicts. Advisory only."
        ),
    )
    parser.add_argument(
        "--validate-plans-strict",
        action="store_true",
        help=(
            "Plan 2026-05-19-003 F003: promote the strict jsonschema "
            "plan-validation probe from advisory (the default — failures "
            "emit WARN) to blocker (failures emit FAIL; exit 2 under "
            "--strict-codes). The probe walks every locked plan under "
            "docs/plans/ and validates against the v1.9 plan schema."
        ),
    )
    parser.add_argument(
        "--architecture-drift-strict",
        action="store_true",
        help=(
            "Plan 2026-05-19-004 F003: promote the architecture-drift "
            "probe from advisory (the default — stale_major and absent "
            "emit WARN) to blocker (stale_major and absent emit FAIL; "
            "exit 2 under --strict-codes). stale_minor remains advisory "
            "in both modes."
        ),
    )
    parser.add_argument(
        "--plans-root",
        type=Path,
        default=None,
        help=(
            "Plan 2026-05-19-005 F001: override the plans root walked by "
            "the validate-plans-strict probe. Default = <repo>/docs/plans. "
            "Enables showcase generator to validate plan inventories in "
            "external checkouts (e.g. ../Glam/docs/plans) without copying "
            "runtime code."
        ),
    )
    parser.add_argument(
        "--architecture-json",
        type=Path,
        default=None,
        help=(
            "Plan 2026-05-19-005 F001: override the architecture.json path "
            "read by the architecture-drift probe. Default = "
            "<repo>/docs/architecture/architecture.json. Enables drift "
            "evaluation against an external snapshot."
        ),
    )
    # Plan 2026-05-19-002 F001 — profile-aware prereq probes.
    # IMPORTANT: NO default. The legacy no-flag path is preserved
    # byte-identical when --profile is absent.
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        choices=("core", "discord", "firebase-dashboard", "openclaw", "ci"),
        help=(
            "Plan 2026-05-19-002 F001: run the NEW profile-aware prereq "
            "probe sweep. When omitted, doctor runs the legacy CheckResult "
            "pipeline unchanged. Valid profiles: core, discord, "
            "firebase-dashboard, openclaw, ci."
        ),
    )
    parser.add_argument(
        "--profile-strict",
        action="store_true",
        help=(
            "Plan 2026-05-19-002 F001: promote WARN -> FAIL under the "
            "selected --profile. Avoids namespace clash with existing "
            "--strict-codes / --validate-plans-strict / "
            "--architecture-drift-strict flags."
        ),
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help=(
            "Plan 2026-05-19-002 F004: also render the install report "
            "to docs/install-report.html (or the --report-path override). "
            "Requires --profile=<name>; the legacy no-flag path is "
            "unaffected. Output is gitignored."
        ),
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help=(
            "Override the install-report output path. Default = "
            "<repo>/docs/install-report.html. Only honored with --report."
        ),
    )
    args = parser.parse_args(argv)

    results = run_all_checks(
        skip_auth=args.skip_auth,
        include_projects=args.include_projects,
        validate_plans=args.validate_plans,
        validate_plans_strict_mode=args.validate_plans_strict,
        architecture_drift_strict_mode=args.architecture_drift_strict,
        plans_root=args.plans_root,
        architecture_json=args.architecture_json,
    )
    # Plan 2026-05-19-002 F001 — profile-aware path activates ONLY when
    # --profile is supplied. With no --profile, the legacy
    # render_text/render_json + 0/1/2 exit code matrix is preserved
    # byte-identical (backwards-compat invariant).
    if args.profile is not None:
        exit_code, rendered = _run_profile_aware(
            profile=args.profile,
            profile_strict=args.profile_strict,
            as_json=args.json,
            repo_root=REPO_ROOT,
            legacy_results=results,
        )
        print(rendered)
        if args.report:
            # Plan 2026-05-19-002 F004: render install-report HTML
            # alongside the normal output. Build a fresh envelope (so the
            # report contains the structured shape regardless of whether
            # --json was requested) and write to docs/install-report.html
            # by default, or the operator's --report-path override.
            from dontpanic_orchestrate.init.report_html import (
                write_install_report,
            )
            pr = _load_prereq_registry()
            activation_context = pr.build_activation_context(REPO_ROOT)
            sweep = pr.run_sweep(
                profile=args.profile,
                activation_context=activation_context,
                profile_strict=args.profile_strict,
            )
            doctor_envelope = pr.envelope_for_sweep(sweep)
            out_path = args.report_path or (REPO_ROOT / "docs" / "install-report.html")
            written = write_install_report(doctor_envelope, None, out_path)
            print(f"[report] wrote {written}", file=sys.stderr)
        return exit_code
    print(render_json(results) if args.json else render_text(results))
    # The --validate-plans-strict and --architecture-drift-strict flags
    # implicitly opt into the strict-codes exit matrix: per the F003
    # acceptance contracts, a strict-mode failure must produce exit 2.
    # Operators who pass --strict-codes explicitly still get the same
    # semantics; operators who pass none of these stick with the legacy
    # 0/1 contract.
    if args.strict_codes or args.validate_plans_strict or args.architecture_drift_strict:
        # Plan 2026-05-23-004 F005: dashboard readiness probes stay
        # advisory in all modes — drop them from the strict-exit
        # computation. Their WARN text + remediation still prints above.
        strict_inputs = [
            r for r in results if not r.name.startswith("dashboard-")
        ]
        return compute_strict_exit(strict_inputs)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
