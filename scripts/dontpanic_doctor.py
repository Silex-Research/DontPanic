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


# ── runner ─────────────────────────────────────────────────────────────────


def run_all_checks(skip_auth: bool = False, include_projects: bool = False) -> list[CheckResult]:
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
    if include_projects:
        results.append(check_global_config())
        results.append(check_projects_registry_status())
        results.extend(check_registered_projects())
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
    args = parser.parse_args(argv)

    results = run_all_checks(skip_auth=args.skip_auth, include_projects=args.include_projects)
    print(render_json(results) if args.json else render_text(results))
    if args.strict_codes:
        return compute_strict_exit(results)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
