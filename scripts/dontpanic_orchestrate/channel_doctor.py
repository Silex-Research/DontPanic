"""Plan 2026-06-14-001 F007 — channel doctor: ``dontpanic doctor --channel <surface>``.

Reports whether a named operator surface is usable. It normalizes the surface
name via F001 :func:`normalize_identifier`, resolves that surface's
``operator_surface`` capability manifest (F008), and runs the manifest's
``verify.probes`` through a small STRUCTURAL probe registry, reporting the six
minimum probes (PATH, home, repo-visibility, worktree-binding, config,
MCP-availability) with pass/warn/fail per check.

THREE OUTCOMES (D015):
  * ``ok`` — recognized surface WITH a seeded manifest; probes ran.
  * ``recognized_unseeded`` — name normalizes to a recognized ``operator_surface``
    id but no manifest is seeded yet (a known channel, just not manifested) — an
    advisory status, NOT "unsupported".
  * ``unknown_surface`` — name normalizes to ``unknown_surface``; exits non-zero
    with an actionable message.

No ``agent-channels.json`` — channels derive from the existing capability
manifests / agent_surface, never a parallel registry. The minimum probe set has
no auth probe, so the channel doctor is structural-safe under ``--skip-auth``.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import global_config
from dontpanic_orchestrate.capabilities import (
    OPERATOR_SURFACE_MINIMUM_PROBES,
    CapabilityManifest,
    load_capabilities,
)
from dontpanic_orchestrate.invocation_context import (
    OperatorSurface,
    UNKNOWN_SURFACE,
    normalize_identifier,
)

OPERATOR_SURFACE_KIND = "operator_surface"

OUTCOME_OK = "ok"
OUTCOME_RECOGNIZED_UNSEEDED = "recognized_unseeded"
OUTCOME_UNKNOWN = "unknown_surface"

PASS = "pass"
WARN = "warn"
FAIL = "fail"

# worst-status -> exit code (0 all pass, 1 any warn, 2 any fail).
_STATUS_RANK = {PASS: 0, WARN: 1, FAIL: 2}
_RANK_EXIT = {0: 0, 1: 1, 2: 2}


@dataclass(frozen=True)
class ChannelProbeContext:
    """Inputs the structural probes read. Pure data — no side effects."""

    repo_root: Path
    home: Path
    skip_auth: bool = False


def _probe_path(ctx: ChannelProbeContext) -> str:
    """PATH resolves the ``dontpanic`` console script."""
    return PASS if shutil.which("dontpanic") else WARN


def _probe_home(ctx: ChannelProbeContext) -> str:
    """The DontPanic home directory exists."""
    return PASS if ctx.home.is_dir() else WARN


def _probe_repo_visibility(ctx: ChannelProbeContext) -> str:
    """A git repo is visible from the working tree."""
    return PASS if (ctx.repo_root / ".git").exists() else WARN


def _probe_worktree_binding(ctx: ChannelProbeContext) -> str:
    """Any declared worktree binding is healthy. v0: a worktree path that exists
    is healthy; no binding is a clean pass."""
    repo = str(ctx.repo_root).replace("\\", "/")
    if ".dontpanic/worktrees" in repo:
        return PASS if ctx.repo_root.is_dir() else FAIL
    return PASS


def _probe_config(ctx: ChannelProbeContext) -> str:
    """The operator config loads without error."""
    try:
        global_config.load_config()
        return PASS
    except Exception:  # noqa: BLE001 — structural probe never raises
        return WARN


def _probe_mcp_availability(ctx: ChannelProbeContext) -> str:
    """MCP server reachability. Not structurally verifiable offline -> advisory."""
    return WARN


#: The structural probe registry — maps each minimum probe id to its check.
PROBE_REGISTRY: dict[str, Callable[[ChannelProbeContext], str]] = {
    "path": _probe_path,
    "home": _probe_home,
    "repo_visibility": _probe_repo_visibility,
    "worktree_binding": _probe_worktree_binding,
    "config": _probe_config,
    "mcp_availability": _probe_mcp_availability,
}


@dataclass(frozen=True)
class ChannelDoctorResult:
    """The diagnosis for one operator surface."""

    surface: str
    outcome: str
    exit_code: int
    message: str
    checks: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "outcome": self.outcome,
            "exit_code": self.exit_code,
            "message": self.message,
            "checks": self.checks,
        }


def _default_repo_root() -> Path:
    # scripts/dontpanic_orchestrate/channel_doctor.py -> repo root
    return Path(__file__).resolve().parents[2]


def _recognized_surfaces() -> list[str]:
    return [s.value for s in OperatorSurface if s.value != UNKNOWN_SURFACE]


def _find_manifest(canonical: str, repo_root: Path) -> CapabilityManifest | None:
    index = load_capabilities(repo_root)
    manifest = index.get(canonical)
    if manifest is not None and manifest.kind == OPERATOR_SURFACE_KIND:
        return manifest
    return None


def diagnose_channel(
    name: str,
    *,
    repo_root: Path | None = None,
    skip_auth: bool = False,
) -> ChannelDoctorResult:
    """Diagnose operator surface ``name`` (one of the three D015 outcomes)."""
    root = repo_root or _default_repo_root()
    canonical = normalize_identifier(name, "operator_surface")

    if canonical == UNKNOWN_SURFACE:
        recognized = ", ".join(_recognized_surfaces())
        return ChannelDoctorResult(
            surface=UNKNOWN_SURFACE,
            outcome=OUTCOME_UNKNOWN,
            exit_code=2,
            message=(
                f"{name!r} does not normalize to a recognized operator surface. "
                f"Recognized surfaces: {recognized}."
            ),
        )

    manifest = _find_manifest(canonical, root)
    if manifest is None:
        return ChannelDoctorResult(
            surface=canonical,
            outcome=OUTCOME_RECOGNIZED_UNSEEDED,
            exit_code=0,
            message=(
                f"{canonical} is a recognized operator surface but has no seeded "
                f"capability manifest yet (recognized_unseeded). It is a known "
                f"channel, just not manifested — not unsupported."
            ),
        )

    ctx = ChannelProbeContext(repo_root=root, home=global_config.dontpanic_home(), skip_auth=skip_auth)
    # report the full minimum set plus any extra probes the manifest declares,
    # in a stable order (minimum first, then any extras).
    declared = list(manifest.verify.probes)
    ordered = sorted(OPERATOR_SURFACE_MINIMUM_PROBES) + [p for p in declared if p not in OPERATOR_SURFACE_MINIMUM_PROBES]
    checks: list[dict[str, str]] = []
    worst = 0
    for probe in ordered:
        runner = PROBE_REGISTRY.get(probe)
        status = runner(ctx) if runner is not None else WARN
        checks.append({"probe": probe, "status": status})
        worst = max(worst, _STATUS_RANK[status])

    return ChannelDoctorResult(
        surface=canonical,
        outcome=OUTCOME_OK,
        exit_code=_RANK_EXIT[worst],
        message=f"{canonical}: ran {len(checks)} probe(s) — {manifest.verify.readiness}",
        checks=checks,
    )


__all__ = [
    "ChannelDoctorResult",
    "ChannelProbeContext",
    "OUTCOME_OK",
    "OUTCOME_RECOGNIZED_UNSEEDED",
    "OUTCOME_UNKNOWN",
    "PROBE_REGISTRY",
    "diagnose_channel",
]
