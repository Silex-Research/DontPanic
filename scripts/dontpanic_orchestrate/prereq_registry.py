"""Plan 2026-05-19-002 F001 — Declarative prereq probe registry.

Pure-set profiles + per-probe activation_condition + stable JSON envelope.

The legacy ``scripts/dontpanic_doctor.py`` ``CheckResult`` pipeline keeps
its existing probe set and 0/1/2 exit-code matrix when invoked with no
flags. This module provides the NEW profile-aware path that activates
only on ``dontpanic doctor --profile=<name>``.

Five PURE-SET profiles (no conditional pseudo-profiles like
``core-when-auditor-codex``):

  core               — everyone (Python, claude CLI, git identity, jq, ...)
  discord            — operators wiring Discord notifications
  firebase-dashboard — operators with a Firebase deployment surface
  openclaw           — operators using OpenClaw / OpenRouter executors
  ci                 — CI / GitHub Actions runner profile

Conditional severity lives on the per-probe ``activation_condition`` +
``severity_when_inactive`` fields, not on the profile name. Example:
``codex-cli`` is in profiles ``{ci, openclaw}`` AND activation_condition
``auditor_codex_selected`` with ``severity_when_inactive=advisory`` —
so under ``--profile=core`` (when codex is NOT a member of core) the
probe simply omits; but probes that ARE in core can still surface as
advisory/warn/fail under core depending on activation context.

A maintainer profile is explicitly OUT of v0 scope (Roadmap Plan 5/7).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ActivationCondition(str, Enum):
    """Predicate that decides whether a probe is *active* in the current
    operator context. Evaluated against an :class:`ActivationContext`
    built once per probe sweep."""

    ALWAYS = "always"
    GITHUB_REMOTE_PRESENT = "github_remote_present"
    AUDITOR_CODEX_SELECTED = "auditor_codex_selected"
    DISPATCH_REQUIRES_PUSH = "dispatch_requires_push"
    FIREBASE_TARGET_SET = "firebase_target_set"


class SeverityWhenInactive(str, Enum):
    """How a probe appears when its ``activation_condition`` resolves to
    *false* under the selected profile. ``omit`` removes the probe from
    output entirely; ``advisory`` surfaces it as info; ``warn`` surfaces
    it as a soft warning."""

    OMIT = "omit"
    ADVISORY = "advisory"
    WARN = "warn"


class ProbeStatus(str, Enum):
    """Effective status of a probe after activation + execution."""

    PASS = "pass"
    WARN = "warn"
    ADVISORY = "advisory"
    FAIL = "fail"
    OMIT = "omit"


@dataclass(frozen=True)
class PrereqProbe:
    """Declarative description of a single prerequisite check."""

    name: str
    probe_command: list[str] | Callable[[], tuple[bool, str]]
    version_constraint: str | None
    fix_url: str
    fix_command: list[str]
    auto_install_safe: bool
    why_needed: str
    required_for_profiles: frozenset[str]
    activation_condition: ActivationCondition
    severity_when_inactive: SeverityWhenInactive
    timeout_s: float = 2.0

    def __post_init__(self) -> None:
        # Strict-argv invariant — fix_command must be a list of strings,
        # never a shell string. The F002 walker enforces this at runtime
        # too, but fail fast here so registry-authoring mistakes show up
        # at import time.
        if not isinstance(self.fix_command, list) or not all(
            isinstance(s, str) for s in self.fix_command
        ):
            raise ValueError(
                f"PrereqProbe {self.name!r}: fix_command must be list[str], "
                f"got {type(self.fix_command).__name__}"
            )
        if isinstance(self.probe_command, list) and not all(
            isinstance(s, str) for s in self.probe_command
        ):
            raise ValueError(
                f"PrereqProbe {self.name!r}: probe_command list must contain str only"
            )


@dataclass(frozen=True)
class ProbeResult:
    """Execution result for a single probe under a specific profile."""

    name: str
    status: ProbeStatus
    severity_reason: str
    version_found: str | None
    fix_url: str
    fix_command: list[str]
    required_for_profiles: list[str]
    activation_condition: str
    activation_resolved: bool
    elapsed_s: float


# ── activation context ────────────────────────────────────────────────────


@dataclass
class ActivationContext:
    """Per-sweep snapshot of operator state used to evaluate
    ``ActivationCondition`` values uniformly across all probes."""

    repo_root: Path
    github_remote_present: bool
    auditor_codex_selected: bool
    dispatch_requires_push: bool
    firebase_target_set: bool

    def resolves(self, cond: ActivationCondition) -> bool:
        if cond is ActivationCondition.ALWAYS:
            return True
        if cond is ActivationCondition.GITHUB_REMOTE_PRESENT:
            return self.github_remote_present
        if cond is ActivationCondition.AUDITOR_CODEX_SELECTED:
            return self.auditor_codex_selected
        if cond is ActivationCondition.DISPATCH_REQUIRES_PUSH:
            return self.dispatch_requires_push
        if cond is ActivationCondition.FIREBASE_TARGET_SET:
            return self.firebase_target_set
        return False


def _detect_github_remote(repo_root: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "remote", "-v"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    return "github.com" in (proc.stdout or "")


def _detect_auditor_codex_selected(
    repo_root: Path, invocation_flags: dict[str, Any] | None
) -> bool:
    if invocation_flags and invocation_flags.get("auditor") == "codex":
        return True
    env_file = repo_root / "environments.json"
    if not env_file.is_file():
        return False
    try:
        data = json.loads(env_file.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    # Convention: an explicit top-level or per-tier "auditor": "codex" wins.
    if data.get("auditor") == "codex":
        return True
    for tier in ("dev", "staging", "prod"):
        block = data.get(tier) or {}
        if isinstance(block, dict) and block.get("auditor") == "codex":
            return True
    return False


def _detect_firebase_target_set(repo_root: Path) -> bool:
    env_file = repo_root / "environments.json"
    if not env_file.is_file():
        return False
    try:
        data = json.loads(env_file.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    for tier in ("dev", "staging", "prod"):
        block = data.get(tier) or {}
        if isinstance(block, dict) and block.get("firebase_project"):
            return True
    return False


def _detect_dispatch_requires_push(repo_root: Path) -> bool:
    """A plan in the inventory declares ``commit_policy.mode`` that
    implies pushing to remote. The cheap proxy: any locked plan under
    ``docs/plans/`` whose commit_policy is ``push`` or includes a
    ``requires`` field referencing remote. We default conservatively to
    False when the inventory can't be walked (matches the operator-pause
    contract — better to keep gh-auth as warn-under-core than to escalate
    on inferential grounds)."""
    plans_root = repo_root / "docs" / "plans"
    if not plans_root.is_dir():
        return False
    for plan_md in plans_root.glob("*/plan.md"):
        try:
            text = plan_md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Cheap heuristic — frontmatter contains commit_policy.mode: push
        if "commit_policy:" in text and "mode: push" in text:
            return True
    return False


def build_activation_context(
    repo_root: Path,
    invocation_flags: dict[str, Any] | None = None,
) -> ActivationContext:
    """Resolve all activation predicates once for a sweep."""

    return ActivationContext(
        repo_root=repo_root,
        github_remote_present=_detect_github_remote(repo_root),
        auditor_codex_selected=_detect_auditor_codex_selected(repo_root, invocation_flags),
        dispatch_requires_push=_detect_dispatch_requires_push(repo_root),
        firebase_target_set=_detect_firebase_target_set(repo_root),
    )


# ── profile registry ──────────────────────────────────────────────────────

PROFILE_NAMES: tuple[str, ...] = (
    "core",
    "discord",
    "firebase-dashboard",
    "openclaw",
    "ci",
)


@dataclass(frozen=True)
class ProfileRegistry:
    """Pure-set mapping of profile name -> frozenset of probe names.

    Profiles are pure sets; conditional severity is a per-probe field.
    There is intentionally NO ``maintainer`` profile in v0 — that lands
    in a future plan.
    """

    profiles: dict[str, frozenset[str]]

    def probe_names(self, profile: str) -> frozenset[str]:
        if profile not in self.profiles:
            raise KeyError(profile)
        return self.profiles[profile]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.profiles))


# ── probe runtime helpers ─────────────────────────────────────────────────


def _which_probe(executable: str) -> Callable[[], tuple[bool, str]]:
    """Return a callable that PASSes iff ``executable`` is on PATH."""

    def _run() -> tuple[bool, str]:
        path = shutil.which(executable)
        if path is None:
            return False, f"{executable} not found on PATH"
        return True, f"{executable} at {path}"

    return _run


def _python_version_probe() -> tuple[bool, str]:
    import sys

    major, minor = sys.version_info.major, sys.version_info.minor
    if (major, minor) < (3, 10):
        return False, f"python {major}.{minor} (need >=3.10)"
    return True, f"python {major}.{minor}"


def _git_user_email_probe() -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["git", "config", "--get", "user.email"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except FileNotFoundError:
        return False, "git not found"
    email = (proc.stdout or "").strip()
    if proc.returncode != 0 or not email:
        return False, "git user.email not set"
    return True, email


def _anthropic_api_network_probe() -> tuple[bool, str]:
    """Reachability probe — uses urllib so we don't need requests as a
    new dependency. Bounded by the per-probe timeout in the runner."""
    import socket
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            method="HEAD",
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:  # noqa: S310 - read-only HEAD
            # Any HTTP response (including 401/405) proves reachability.
            return True, f"api.anthropic.com reachable (HTTP {resp.status})"
    except urllib.error.HTTPError as exc:
        # 4xx counts as reachable for a HEAD that the server refuses.
        return True, f"api.anthropic.com reachable (HTTP {exc.code})"
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        return False, f"api.anthropic.com unreachable: {exc}"


def _claude_cli_probe() -> tuple[bool, str]:
    return _which_probe("claude")()


def _codex_cli_probe() -> tuple[bool, str]:
    return _which_probe("codex")()


def _jq_probe() -> tuple[bool, str]:
    return _which_probe("jq")()


def _firebase_cli_probe() -> tuple[bool, str]:
    return _which_probe("firebase")()


def _gcloud_probe() -> tuple[bool, str]:
    return _which_probe("gcloud")()


def _sa_key_probe() -> tuple[bool, str]:
    home = Path.home()
    sa_dirs = [
        home / ".dontpanic" / ".secrets",
        Path(".secrets"),
    ]
    for d in sa_dirs:
        if d.is_dir():
            keys = list(d.glob("*.json"))
            if keys:
                return True, f"sa key present ({keys[0].name})"
    return False, "no SA key under .dontpanic/.secrets or .secrets"


def _discord_webhook_probe() -> tuple[bool, str]:
    import os

    value = os.environ.get("DONTPANIC_DISCORD_WEBHOOK_URL") or os.environ.get(
        "JARVIS_DISCORD_WEBHOOK_URL"
    )
    if not value:
        return False, "DONTPANIC_DISCORD_WEBHOOK_URL not set"
    if not value.startswith("https://discord.com/api/webhooks/"):
        return False, "webhook URL does not match discord.com/api/webhooks/ prefix"
    return True, "webhook URL present"


def _sanitization_regex_probe() -> tuple[bool, str]:
    """Make sure scripts/sanitization_check.py exists and is importable.
    The sanitization regex bank is what stops a Discord notification from
    spilling tokens — required for the discord profile."""

    repo_root = Path(__file__).resolve().parents[2]
    target = repo_root / "scripts" / "sanitization_check.py"
    if not target.is_file():
        return False, f"sanitization_check.py missing at {target}"
    return True, "sanitization_check.py present"


def _openrouter_key_probe() -> tuple[bool, str]:
    import os

    if os.environ.get("OPENROUTER_API_KEY"):
        return True, "OPENROUTER_API_KEY present"
    return False, "OPENROUTER_API_KEY not set"


def _openclaw_cli_probe() -> tuple[bool, str]:
    return _which_probe("openclaw")()


# ── initial probe set ─────────────────────────────────────────────────────

_CORE = frozenset({"core"})
_ALL_RUNTIME = frozenset({"core", "discord", "firebase-dashboard", "openclaw", "ci"})
_CI = frozenset({"ci"})
_CI_OPENCLAW = frozenset({"ci", "openclaw"})
_FIREBASE = frozenset({"firebase-dashboard"})
_DISCORD = frozenset({"discord"})
_OPENCLAW = frozenset({"openclaw"})


def default_probes() -> list[PrereqProbe]:
    """Initial set of ~12 probes per F001 acceptance."""

    return [
        PrereqProbe(
            name="python-version",
            probe_command=_python_version_probe,
            version_constraint=">=3.10",
            fix_url="https://www.python.org/downloads/",
            fix_command=[
                "echo",
                "Install Python 3.10+ from https://www.python.org/downloads/",
            ],
            auto_install_safe=False,
            why_needed="Python 3.10+ is required for `|` union syntax used throughout the supervisor.",
            required_for_profiles=_ALL_RUNTIME,
            activation_condition=ActivationCondition.ALWAYS,
            severity_when_inactive=SeverityWhenInactive.OMIT,
        ),
        PrereqProbe(
            name="claude-cli",
            probe_command=_claude_cli_probe,
            version_constraint=None,
            fix_url="https://docs.claude.com/en/docs/claude-code/setup",
            fix_command=[
                "echo",
                "Install Claude Code from https://docs.claude.com/en/docs/claude-code/setup",
            ],
            auto_install_safe=False,
            why_needed="Default executor — required for every dispatch_volley invocation.",
            required_for_profiles=_ALL_RUNTIME,
            activation_condition=ActivationCondition.ALWAYS,
            severity_when_inactive=SeverityWhenInactive.OMIT,
        ),
        PrereqProbe(
            name="git-user-email",
            probe_command=_git_user_email_probe,
            version_constraint=None,
            fix_url="https://docs.github.com/en/get-started/getting-started-with-git/setting-your-username-in-git",
            fix_command=["git", "config", "--global", "user.email", "you@example.com"],
            auto_install_safe=False,
            why_needed="Auditable commit identity. Supervisor commits would fail without it.",
            required_for_profiles=_ALL_RUNTIME,
            activation_condition=ActivationCondition.ALWAYS,
            severity_when_inactive=SeverityWhenInactive.OMIT,
        ),
        PrereqProbe(
            name="gh-auth-status",
            probe_command=["gh", "auth", "status"],
            version_constraint=None,
            fix_url="https://cli.github.com/manual/gh_auth_login",
            fix_command=["gh", "auth", "login"],
            auto_install_safe=False,
            why_needed=(
                "GitHub authentication. Required for `ci` profile. Under `core` it is "
                "a soft warning only when this clone has a github.com remote."
            ),
            required_for_profiles=_CI,
            activation_condition=ActivationCondition.GITHUB_REMOTE_PRESENT,
            severity_when_inactive=SeverityWhenInactive.WARN,
        ),
        PrereqProbe(
            name="codex-cli",
            probe_command=_codex_cli_probe,
            version_constraint=None,
            fix_url="https://github.com/openai/codex",
            fix_command=["echo", "Install codex CLI from https://github.com/openai/codex"],
            auto_install_safe=False,
            why_needed=(
                "OpenAI codex CLI — required when the operator selects codex as auditor. "
                "Advisory under `core` unless activation_condition.auditor_codex_selected."
            ),
            required_for_profiles=_CI_OPENCLAW,
            activation_condition=ActivationCondition.AUDITOR_CODEX_SELECTED,
            severity_when_inactive=SeverityWhenInactive.ADVISORY,
        ),
        PrereqProbe(
            name="anthropic-api-network",
            probe_command=_anthropic_api_network_probe,
            version_constraint=None,
            fix_url="https://status.anthropic.com/",
            fix_command=[
                "echo",
                "Check https://status.anthropic.com/ and your network egress.",
            ],
            auto_install_safe=False,
            why_needed="The supervisor cannot dispatch without reaching api.anthropic.com.",
            required_for_profiles=_ALL_RUNTIME,
            activation_condition=ActivationCondition.ALWAYS,
            severity_when_inactive=SeverityWhenInactive.OMIT,
            timeout_s=2.0,
        ),
        PrereqProbe(
            name="jq",
            probe_command=_jq_probe,
            version_constraint=None,
            fix_url="https://jqlang.org/download/",
            fix_command=["brew", "install", "jq"],
            auto_install_safe=False,
            why_needed="Used by several supervisor hooks to filter JSON envelopes.",
            required_for_profiles=_ALL_RUNTIME,
            activation_condition=ActivationCondition.ALWAYS,
            severity_when_inactive=SeverityWhenInactive.OMIT,
        ),
        PrereqProbe(
            name="firebase-cli",
            probe_command=_firebase_cli_probe,
            version_constraint=None,
            fix_url="https://firebase.google.com/docs/cli",
            fix_command=["npm", "install", "-g", "firebase-tools"],
            auto_install_safe=False,
            why_needed="Required to deploy or inspect the firebase-dashboard surface.",
            required_for_profiles=_FIREBASE,
            activation_condition=ActivationCondition.FIREBASE_TARGET_SET,
            severity_when_inactive=SeverityWhenInactive.OMIT,
        ),
        PrereqProbe(
            name="gcloud",
            probe_command=_gcloud_probe,
            version_constraint=None,
            fix_url="https://cloud.google.com/sdk/docs/install",
            fix_command=[
                "echo",
                "Install gcloud from https://cloud.google.com/sdk/docs/install",
            ],
            auto_install_safe=False,
            why_needed="GCP project bookkeeping for the firebase-dashboard surface.",
            required_for_profiles=_FIREBASE,
            activation_condition=ActivationCondition.FIREBASE_TARGET_SET,
            severity_when_inactive=SeverityWhenInactive.OMIT,
        ),
        PrereqProbe(
            name="sa-key",
            probe_command=_sa_key_probe,
            version_constraint=None,
            fix_url="https://firebase.google.com/docs/admin/setup",
            fix_command=[
                "echo",
                "Run scripts/bootstrap.sh --project <id> --create-key to provision.",
            ],
            auto_install_safe=False,
            why_needed="Service-account key under .secrets for the firebase-dashboard surface.",
            required_for_profiles=_FIREBASE,
            activation_condition=ActivationCondition.FIREBASE_TARGET_SET,
            severity_when_inactive=SeverityWhenInactive.OMIT,
        ),
        PrereqProbe(
            name="discord-webhook",
            probe_command=_discord_webhook_probe,
            version_constraint=None,
            fix_url="https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks",
            fix_command=[
                "echo",
                "Set DONTPANIC_DISCORD_WEBHOOK_URL=<https://discord.com/api/webhooks/...>",
            ],
            auto_install_safe=False,
            why_needed="Discord sink reads DONTPANIC_DISCORD_WEBHOOK_URL.",
            required_for_profiles=_DISCORD,
            activation_condition=ActivationCondition.ALWAYS,
            severity_when_inactive=SeverityWhenInactive.OMIT,
        ),
        PrereqProbe(
            name="sanitization-regex",
            probe_command=_sanitization_regex_probe,
            version_constraint=None,
            fix_url="https://github.com/Silex-Research/DontPanic#sanitization",
            fix_command=[
                "echo",
                "scripts/sanitization_check.py is required for Discord notifications.",
            ],
            auto_install_safe=False,
            why_needed="Sanitization regex bank guards Discord output from leaking tokens.",
            required_for_profiles=_DISCORD,
            activation_condition=ActivationCondition.ALWAYS,
            severity_when_inactive=SeverityWhenInactive.OMIT,
        ),
        PrereqProbe(
            name="openrouter-key",
            probe_command=_openrouter_key_probe,
            version_constraint=None,
            fix_url="https://openrouter.ai/keys",
            fix_command=["echo", "Set OPENROUTER_API_KEY=<your key from https://openrouter.ai/keys>"],
            auto_install_safe=False,
            why_needed="OpenRouter API key for the openclaw executor.",
            required_for_profiles=_OPENCLAW,
            activation_condition=ActivationCondition.ALWAYS,
            severity_when_inactive=SeverityWhenInactive.OMIT,
        ),
        PrereqProbe(
            name="openclaw-cli",
            probe_command=_openclaw_cli_probe,
            version_constraint=None,
            fix_url="https://github.com/openclaw/openclaw",
            fix_command=["echo", "Install openclaw CLI from https://github.com/openclaw/openclaw"],
            auto_install_safe=False,
            why_needed="openclaw executor binary on PATH.",
            required_for_profiles=_OPENCLAW,
            activation_condition=ActivationCondition.ALWAYS,
            severity_when_inactive=SeverityWhenInactive.OMIT,
        ),
    ]


def default_profile_registry(probes: list[PrereqProbe] | None = None) -> ProfileRegistry:
    """Build the pure-set profile -> probe-name registry."""

    probes = probes if probes is not None else default_probes()
    profiles: dict[str, set[str]] = {name: set() for name in PROFILE_NAMES}
    for probe in probes:
        for profile in probe.required_for_profiles:
            if profile not in profiles:
                # Unknown profile name baked into a probe — surface loudly.
                raise ValueError(
                    f"Probe {probe.name!r} declares unknown profile {profile!r}; "
                    f"known profiles: {PROFILE_NAMES}"
                )
            profiles[profile].add(probe.name)
    return ProfileRegistry({k: frozenset(v) for k, v in profiles.items()})


# ── runner ────────────────────────────────────────────────────────────────


@dataclass
class SweepResult:
    """Aggregate output of a single profile sweep."""

    profile: str
    probes: list[ProbeResult] = field(default_factory=list)
    elapsed_s: float = 0.0

    def exit_code(self) -> int:
        """Strict 0/1/2 matrix mirroring the legacy doctor's
        ``compute_strict_exit`` shape but operating on probe statuses."""
        if any(p.status is ProbeStatus.FAIL for p in self.probes):
            return 2
        if any(p.status is ProbeStatus.WARN for p in self.probes):
            return 1
        return 0


def _run_single_probe(probe: PrereqProbe) -> tuple[bool, str, str | None]:
    """Execute a probe's ``probe_command`` and return
    ``(ok, message, version_or_path)``.

    For callable probes the call is wrapped in a single-worker
    ``ThreadPoolExecutor`` so ``probe.timeout_s`` is enforced even when
    the callable itself does not honor a deadline. The inner pool is
    shut down with ``wait=False`` so a stuck callable does not block the
    outer sweep.
    """

    if callable(probe.probe_command):
        inner_pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = inner_pool.submit(probe.probe_command)
            try:
                ok, msg = future.result(timeout=probe.timeout_s)
                return ok, msg, msg if ok else None
            except FuturesTimeoutError:
                return False, f"timed out after {probe.timeout_s}s", None
            except Exception as exc:
                return False, f"probe raised: {exc!r}", None
        finally:
            # Do NOT wait for stuck callables — they would block the
            # outer sweep past wall_clock_budget_s.
            inner_pool.shutdown(wait=False, cancel_futures=True)
    # list[str] — run via subprocess.run with shell=False
    try:
        proc = subprocess.run(
            probe.probe_command,
            capture_output=True,
            text=True,
            timeout=probe.timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return False, f"{probe.probe_command[0]} not found on PATH", None
    except subprocess.TimeoutExpired:
        return False, f"timed out after {probe.timeout_s}s", None
    if proc.returncode == 0:
        out = (proc.stdout or "").strip().splitlines()
        version = out[0] if out else None
        return True, "ok", version
    err = ((proc.stderr or "").strip() or (proc.stdout or "").strip()).splitlines()
    return False, (err[0] if err else f"exit {proc.returncode}"), None


def _effective_severity(
    probe: PrereqProbe,
    profile: str,
    activation_resolved: bool,
    raw_ok: bool,
) -> tuple[ProbeStatus, str]:
    """Compute the per-profile effective status for a probe.

    Matrix (in-profile = ``profile`` ∈ ``probe.required_for_profiles``):

    | scope         | raw_ok | severity_when_inactive | active | -> status   |
    |---------------|--------|------------------------|--------|-------------|
    | in-profile    | True   | (any)                  | (any)  | PASS        |
    | in-profile    | False  | (any)                  | (any)  | FAIL        |
    | out-of-prof   | True   | OMIT                   | (any)  | OMIT        |
    | out-of-prof   | True   | WARN / ADVISORY        | (any)  | PASS        |
    | out-of-prof   | False  | OMIT                   | (any)  | OMIT        |
    | out-of-prof   | False  | WARN                   | True   | WARN        |
    | out-of-prof   | False  | WARN                   | False  | OMIT        |
    | out-of-prof   | False  | ADVISORY               | True   | FAIL  (*1)  |
    | out-of-prof   | False  | ADVISORY               | False  | ADVISORY    |

    (*1) ADVISORY-when-inactive probes promote to FAIL when activation
    resolves true. Example: ``codex-cli`` is ADVISORY under ``core``
    when the operator hasn't selected codex as auditor, but escalates
    to FAIL once ``auditor_codex_selected`` resolves — the operator
    explicitly opted in to codex, so a missing CLI is a real blocker
    under ``core`` too.
    """

    in_profile = profile in probe.required_for_profiles
    if in_profile:
        if raw_ok:
            return ProbeStatus.PASS, "in-profile + ok"
        return ProbeStatus.FAIL, "in-profile + check failed"

    sev = probe.severity_when_inactive
    if sev is SeverityWhenInactive.OMIT:
        return ProbeStatus.OMIT, "out-of-profile + severity_when_inactive=omit"
    if raw_ok:
        return ProbeStatus.PASS, "out-of-profile + check passed"
    if sev is SeverityWhenInactive.WARN:
        if activation_resolved:
            return ProbeStatus.WARN, "out-of-profile + warn-when-active + activation resolved"
        return ProbeStatus.OMIT, "out-of-profile + warn-when-active + activation inactive"
    # ADVISORY
    if activation_resolved:
        return (
            ProbeStatus.FAIL,
            "out-of-profile + advisory + activation resolved → escalated to FAIL",
        )
    return ProbeStatus.ADVISORY, "out-of-profile + advisory-by-default"


def run_sweep(
    profile: str,
    probes: list[PrereqProbe] | None = None,
    activation_context: ActivationContext | None = None,
    profile_strict: bool = False,
    max_workers: int = 8,
    wall_clock_budget_s: float = 10.0,
) -> SweepResult:
    """Run the profile-aware probe sweep.

    Parallelizes probe execution via ThreadPoolExecutor with per-probe
    timeout (default 2s) and a total wall-clock budget (default 10s).

    ``profile_strict=True`` promotes ``WARN`` -> ``FAIL`` under the
    selected profile.
    """

    if profile not in PROFILE_NAMES:
        raise ValueError(f"Unknown profile {profile!r}; valid: {PROFILE_NAMES}")

    all_probes = probes if probes is not None else default_probes()
    if activation_context is None:
        repo_root = Path(__file__).resolve().parents[2]
        activation_context = build_activation_context(repo_root)

    # Selection rules:
    #   1. In-profile probes always run.
    #   2. Cross-profile inactive surfacing (severity_when_inactive in
    #      {WARN, ADVISORY}) is scoped to ``--profile=core`` only. The
    #      core profile is the "everyday" surface that should hint at
    #      adjacent operator concerns (codex CLI advisory, gh-auth WARN
    #      under github_remote_present, ...). Specialized profiles
    #      (discord/firebase-dashboard/openclaw/ci) MUST NOT surface
    #      probes that belong to a different specialization — otherwise
    #      e.g. running ``--profile=discord`` would WARN about a missing
    #      gh-auth login even though gh-auth has nothing to do with
    #      Discord webhooks.
    selected: list[PrereqProbe] = []
    for probe in all_probes:
        in_profile = profile in probe.required_for_profiles
        if in_profile:
            selected.append(probe)
            continue
        if (
            profile == "core"
            and probe.severity_when_inactive is not SeverityWhenInactive.OMIT
        ):
            selected.append(probe)

    sweep_start = time.monotonic()
    results: list[ProbeResult] = []

    def _exec(probe: PrereqProbe) -> ProbeResult:
        start = time.monotonic()
        activation_resolved = activation_context.resolves(probe.activation_condition)
        try:
            raw_ok, raw_msg, version_found = _run_single_probe(probe)
        except Exception as exc:  # pragma: no cover — defensive
            raw_ok, raw_msg, version_found = False, f"probe raised: {exc!r}", None
        status, reason = _effective_severity(probe, profile, activation_resolved, raw_ok)
        if profile_strict and status is ProbeStatus.WARN:
            status = ProbeStatus.FAIL
            reason = f"{reason} (promoted WARN→FAIL by --profile-strict)"
        if not raw_ok and status in (ProbeStatus.FAIL, ProbeStatus.WARN, ProbeStatus.ADVISORY):
            reason = f"{reason}: {raw_msg}"
        elapsed = time.monotonic() - start
        return ProbeResult(
            name=probe.name,
            status=status,
            severity_reason=reason,
            version_found=version_found,
            fix_url=probe.fix_url,
            fix_command=list(probe.fix_command),
            required_for_profiles=sorted(probe.required_for_profiles),
            activation_condition=probe.activation_condition.value,
            activation_resolved=activation_resolved,
            elapsed_s=elapsed,
        )

    # NOTE: do NOT use ``with ThreadPoolExecutor(...) as pool`` here —
    # the context manager's __exit__ calls shutdown(wait=True), which
    # blocks on any stuck worker. The wall_clock_budget_s guarantee
    # requires that we return promptly even if a probe callable is hung.
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        future_to_probe = {pool.submit(_exec, probe): probe for probe in selected}
        for future, probe in future_to_probe.items():
            elapsed_since_sweep = time.monotonic() - sweep_start
            remaining = max(0.05, wall_clock_budget_s - elapsed_since_sweep)
            try:
                results.append(future.result(timeout=remaining))
            except FuturesTimeoutError:
                results.append(
                    ProbeResult(
                        name=probe.name,
                        status=ProbeStatus.FAIL,
                        severity_reason=(
                            f"probe exceeded sweep wall-clock budget "
                            f"({wall_clock_budget_s}s)"
                        ),
                        version_found=None,
                        fix_url=probe.fix_url,
                        fix_command=list(probe.fix_command),
                        required_for_profiles=sorted(probe.required_for_profiles),
                        activation_condition=probe.activation_condition.value,
                        activation_resolved=activation_context.resolves(
                            probe.activation_condition
                        ),
                        elapsed_s=probe.timeout_s,
                    )
                )
    finally:
        # Stuck threads do not block sweep return. They will die when
        # the process exits.
        pool.shutdown(wait=False, cancel_futures=True)

    # Drop omitted probes — they're not rendered or counted.
    visible = [r for r in results if r.status is not ProbeStatus.OMIT]
    # Stable order: by probe name so JSON snapshot tests are pinned.
    visible.sort(key=lambda r: r.name)

    return SweepResult(
        profile=profile,
        probes=visible,
        elapsed_s=time.monotonic() - sweep_start,
    )


# ── envelope ──────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0.0"


def envelope_for_sweep(
    sweep: SweepResult,
    legacy_checks: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Stable JSON envelope carrying ``schema_version``."""

    import datetime as _dt

    if generated_at is None:
        generated_at = (
            _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "profile": sweep.profile,
        "generated_at": generated_at,
        "exit_code": sweep.exit_code(),
        "prereq_probes": [
            {
                "name": p.name,
                "status": p.status.value,
                "severity_reason": p.severity_reason,
                "version_found": p.version_found,
                "fix_url": p.fix_url,
                "fix_command": list(p.fix_command),
                "required_for_profiles": list(p.required_for_profiles),
                "activation_condition": p.activation_condition,
                "activation_resolved": p.activation_resolved,
                "elapsed_s": round(p.elapsed_s, 4),
            }
            for p in sweep.probes
        ],
        "legacy_checks": legacy_checks if legacy_checks is not None else [],
    }


# ── rendering ─────────────────────────────────────────────────────────────

_GREEN = "\033[32m✓\033[0m"
_RED = "\033[31m✗\033[0m"
_YELLOW = "\033[33m⚠\033[0m"
_BLUE = "\033[34mℹ\033[0m"

_STATUS_MARKER = {
    ProbeStatus.PASS: _GREEN,
    ProbeStatus.FAIL: _RED,
    ProbeStatus.WARN: _YELLOW,
    ProbeStatus.ADVISORY: _BLUE,
}


def render_sweep_text(sweep: SweepResult) -> str:
    lines = [f"Prereq probes for profile={sweep.profile}:"]
    for p in sweep.probes:
        marker = _STATUS_MARKER.get(p.status, "?")
        suffix = ""
        if p.version_found:
            suffix = f" — {p.version_found}"
        lines.append(f"  {marker} {p.name:<22} [{p.status.value}]{suffix}")
        if p.status in (ProbeStatus.FAIL, ProbeStatus.WARN, ProbeStatus.ADVISORY):
            lines.append(f"      why: {p.severity_reason}")
            lines.append(f"      fix: {' '.join(p.fix_command)}  ({p.fix_url})")
    code = sweep.exit_code()
    summary = {0: "all green", 1: "warnings present", 2: "failures present"}[code]
    lines.append(f"  → profile={sweep.profile} exit_code={code} ({summary})")
    return "\n".join(lines)
