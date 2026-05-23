"""Plan 2026-05-22-002 F002 — `dontpanic capabilities status` CLI.

Reads the checked-in capability manifests via the F001 loader, evaluates
each capability's ``requires`` block against the local environment, runs
declared probes when probe ``capability_id`` bindings exist (V0a F002),
and renders per-capability status in text or JSON.

Status is computed from the CLOSED set
``{ready, needs_setup, blocked, not_installed, optional}``. ``PENDING``
is a *probe* state — never a capability state. A capability with only
PENDING probes and resolved requires is ``ready``.

Sibling module to ``capabilities.py`` (cannot be a ``capabilities/``
package — would collide with the existing module name).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import os
import shutil
import stat
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.capabilities import (
    CapabilityIndex,
    CapabilityManifest,
    CapabilityManifestError,
    SetupStep,
    load_capabilities,
)
from dontpanic_orchestrate.prereq_registry import (
    ActivationContext,
    PrereqProbe,
    ProbeResult,
    ProbeStatus,
    build_activation_context,
    default_probes,
    run_sweep,
)

SCHEMA_VERSION = "1.0.0"
DEFAULT_CACHE_PATH = Path.home() / ".dontpanic" / "capabilities-status.json"
CACHE_FILE_MODE = 0o600

_VALID_PROFILE_NAMES = {"core", "discord", "firebase-dashboard", "openclaw", "ci"}


class CapabilityStatus(str, Enum):
    """Closed set of per-capability status values.

    ``pending`` is intentionally absent — PENDING is a probe-state only.
    A capability whose only failing probes are PENDING still computes as
    ``ready`` when its ``requires`` resolve.
    """

    READY = "ready"
    NEEDS_SETUP = "needs_setup"
    BLOCKED = "blocked"
    NOT_INSTALLED = "not_installed"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class RequiresResolution:
    """Per-bucket resolution of a manifest's ``requires`` block.

    Each bucket lists tokens that are *resolved* vs *unresolved*. Buckets
    we can verify locally (commands, env, files) populate real entries;
    informational buckets (services, auth, config) are reported as
    unresolved unconditionally — operator confirms those out-of-band.
    """

    resolved_commands: tuple[str, ...] = ()
    unresolved_commands: tuple[str, ...] = ()
    resolved_env: tuple[str, ...] = ()
    unresolved_env: tuple[str, ...] = ()
    resolved_files: tuple[str, ...] = ()
    unresolved_files: tuple[str, ...] = ()
    informational_services: tuple[str, ...] = ()
    informational_auth: tuple[str, ...] = ()
    informational_config: tuple[str, ...] = ()

    @property
    def all_resolved(self) -> tuple[str, ...]:
        return self.resolved_commands + self.resolved_env + self.resolved_files

    @property
    def all_unresolved(self) -> tuple[str, ...]:
        # env/auth/config tokens we cannot probe locally are surfaced as
        # missing so the operator sees them in the Missing list.
        return (
            self.unresolved_commands
            + self.unresolved_env
            + self.unresolved_files
            + self.informational_services
            + self.informational_auth
            + self.informational_config
        )

    @property
    def hard_unresolved(self) -> tuple[str, ...]:
        """Tokens that are unambiguously unresolved (no informational)."""
        return self.unresolved_commands + self.unresolved_env + self.unresolved_files

    @property
    def setup_unresolved(self) -> tuple[str, ...]:
        """Tokens that must be resolved or operator-confirmed before ready."""
        return self.hard_unresolved + self.informational_auth + self.informational_config


@dataclass(frozen=True)
class CapabilityStatusResult:
    """One capability's computed status + render payload."""

    capability_id: str
    status: CapabilityStatus
    owner_boundary: dict[str, tuple[str, ...]]
    configured: tuple[str, ...]
    missing: tuple[str, ...]
    automatable: tuple[dict[str, str | None], ...]
    human_required: tuple[dict[str, str | None], ...]
    pending_probes: tuple[dict[str, str], ...]
    next_actions: tuple[dict[str, Any], ...]
    advisory_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StatusEnvelope:
    """Top-level envelope rendered as JSON / written to cache."""

    schema_version: str
    generated_at: str
    capabilities: tuple[CapabilityStatusResult, ...]
    advisory_notes: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "advisory_notes": list(self.advisory_notes),
            "capabilities": [_capability_to_dict(c) for c in self.capabilities],
        }


def _capability_to_dict(c: CapabilityStatusResult) -> dict[str, Any]:
    return {
        "capability_id": c.capability_id,
        "status": c.status.value,
        "owner_boundary": {k: list(v) for k, v in c.owner_boundary.items()},
        "configured": list(c.configured),
        "missing": list(c.missing),
        "automatable": [dict(item) for item in c.automatable],
        "human_required": [dict(item) for item in c.human_required],
        "pending_probes": [dict(item) for item in c.pending_probes],
        "next_actions": [dict(item) for item in c.next_actions],
        "advisory_notes": list(c.advisory_notes),
    }


# ── requires resolution ───────────────────────────────────────────────────


def resolve_requires(
    manifest: CapabilityManifest,
    *,
    env: dict[str, str] | None = None,
    home: Path | None = None,
    which: callable | None = None,
) -> RequiresResolution:
    """Resolve a manifest's ``requires`` block against the local env."""

    env = env if env is not None else dict(os.environ)
    home = home if home is not None else Path.home()
    which = which if which is not None else shutil.which

    resolved_cmds: list[str] = []
    unresolved_cmds: list[str] = []
    for cmd in manifest.requires.commands:
        if which(cmd):
            resolved_cmds.append(cmd)
        else:
            unresolved_cmds.append(cmd)

    resolved_env: list[str] = []
    unresolved_env: list[str] = []
    for var in manifest.requires.env:
        if env.get(var):
            resolved_env.append(var)
        else:
            unresolved_env.append(var)

    resolved_files: list[str] = []
    unresolved_files: list[str] = []
    for raw in manifest.requires.files:
        expanded = _expand_path(raw, home=home)
        if expanded.exists():
            resolved_files.append(raw)
        else:
            unresolved_files.append(raw)

    return RequiresResolution(
        resolved_commands=tuple(resolved_cmds),
        unresolved_commands=tuple(unresolved_cmds),
        resolved_env=tuple(resolved_env),
        unresolved_env=tuple(unresolved_env),
        resolved_files=tuple(resolved_files),
        unresolved_files=tuple(unresolved_files),
        informational_services=tuple(manifest.requires.services),
        informational_auth=tuple(manifest.requires.auth),
        informational_config=tuple(manifest.requires.config),
    )


def _expand_path(raw: str, *, home: Path) -> Path:
    if raw.startswith("~/"):
        return home / raw[2:]
    if raw == "~":
        return home
    return Path(raw)


# ── adapter installed-check ───────────────────────────────────────────────


def adapter_installed(
    manifest: CapabilityManifest,
    *,
    adapters_dir: Path | None = None,
) -> bool:
    """True if a service_adapter manifest has a registered adapter config.

    For v0 the heuristic is simple: ``~/.dontpanic/adapters/<id>.json``
    exists. Non-adapter kinds (notification_sink, agent_cli,
    external_adapter) always return True — they are not gated on the
    adapter registry. The intent is: only service_adapter (PM-tool
    family) capabilities can be ``not_installed``.
    """

    if manifest.kind != "service_adapter":
        return True
    base = adapters_dir if adapters_dir is not None else Path.home() / ".dontpanic" / "adapters"
    candidate = base / f"{manifest.id}.json"
    return candidate.is_file()


# ── status computation ────────────────────────────────────────────────────


def compute_capability_status(
    manifest: CapabilityManifest,
    probe_results: Sequence[ProbeResult],
    requires_resolution: RequiresResolution,
    *,
    in_active_profile: bool = True,
    adapter_is_installed: bool = True,
) -> CapabilityStatus:
    """Compute per-capability status from the closed set.

    Precedence (highest → lowest):
      1. ``optional``     — capability is outside the active profile filter.
                            Profile filtering is an operator-chosen scope;
                            once a capability is outside it, downstream
                            states (not_installed/blocked/needs_setup) are
                            noise the operator did not ask for.
      2. ``not_installed`` — service_adapter kind without registered adapter.
      3. ``blocked``      — any non-PENDING probe FAILed.
      4. ``needs_setup``  — any unresolved require, operator-confirmed auth/config
                             requirement, OR any non-PENDING probe WARNed.
      5. ``ready``        — everything else.

    PENDING probes are ignored entirely for status computation; a manifest
    whose only declared probes are PENDING still computes as ``ready``
    when its ``requires`` resolve.
    """

    if not in_active_profile:
        return CapabilityStatus.OPTIONAL
    if not adapter_is_installed:
        return CapabilityStatus.NOT_INSTALLED

    non_pending = [r for r in probe_results if r.status is not ProbeStatus.PENDING]
    if any(r.status is ProbeStatus.FAIL for r in non_pending):
        return CapabilityStatus.BLOCKED

    has_warn = any(r.status is ProbeStatus.WARN for r in non_pending)
    has_unresolved_requires = bool(requires_resolution.setup_unresolved)
    if has_warn or has_unresolved_requires:
        return CapabilityStatus.NEEDS_SETUP

    return CapabilityStatus.READY


# ── per-capability assembly ───────────────────────────────────────────────


def _setup_step_to_action(step: SetupStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "what": step.what,
        "automatable": step.automatable,
        "command_template": step.command_template,
        "verify_probe": step.verify_probe,
        "human_required_reason": step.human_required_reason,
    }


def _partition_setup_steps(
    manifest: CapabilityManifest,
) -> tuple[tuple[dict[str, str | None], ...], tuple[dict[str, str | None], ...]]:
    automatable: list[dict[str, str | None]] = []
    human_required: list[dict[str, str | None]] = []
    for step in manifest.setup_steps:
        entry: dict[str, str | None] = {
            "id": step.id,
            "what": step.what,
            "command_template": step.command_template,
        }
        if step.automatable:
            automatable.append(entry)
        else:
            entry["human_required_reason"] = step.human_required_reason
            human_required.append(entry)
    return tuple(automatable), tuple(human_required)


def _pending_probes_payload(
    probe_results: Sequence[ProbeResult],
) -> tuple[dict[str, str], ...]:
    return tuple(
        {"name": r.name, "reason": r.severity_reason}
        for r in probe_results
        if r.status is ProbeStatus.PENDING
    )


def build_capability_result(
    manifest: CapabilityManifest,
    probe_results: Sequence[ProbeResult],
    *,
    requires_resolution: RequiresResolution | None = None,
    in_active_profile: bool = True,
    adapter_is_installed: bool | None = None,
    advisory_notes: Iterable[str] = (),
) -> CapabilityStatusResult:
    """Produce the rendered + JSON-serializable per-capability record."""

    if requires_resolution is None:
        requires_resolution = resolve_requires(manifest)
    if adapter_is_installed is None:
        adapter_is_installed = adapter_installed(manifest)

    status = compute_capability_status(
        manifest,
        probe_results,
        requires_resolution,
        in_active_profile=in_active_profile,
        adapter_is_installed=adapter_is_installed,
    )

    automatable, human_required = _partition_setup_steps(manifest)
    next_actions = tuple(_setup_step_to_action(step) for step in manifest.setup_steps)

    owner_boundary = {
        "dontpanic_core": manifest.owner_boundary.dontpanic_core,
        "adapter": manifest.owner_boundary.adapter,
        "operator": manifest.owner_boundary.operator,
    }

    return CapabilityStatusResult(
        capability_id=manifest.id,
        status=status,
        owner_boundary=owner_boundary,
        configured=tuple(requires_resolution.all_resolved),
        missing=tuple(requires_resolution.all_unresolved),
        automatable=automatable,
        human_required=human_required,
        pending_probes=_pending_probes_payload(probe_results),
        next_actions=next_actions,
        advisory_notes=tuple(advisory_notes),
    )


# ── probe results per capability ──────────────────────────────────────────


def _probe_results_by_capability(
    probes: Sequence[PrereqProbe],
    probe_results: Sequence[ProbeResult],
) -> dict[str, list[ProbeResult]]:
    """Group probe results by ``capability_id`` (skips unbound probes)."""

    name_to_capability = {p.name: p.capability_id for p in probes if p.capability_id}
    grouped: dict[str, list[ProbeResult]] = {}
    for result in probe_results:
        cap_id = name_to_capability.get(result.name)
        if cap_id is None:
            continue
        grouped.setdefault(cap_id, []).append(result)
    return grouped


# ── profile filter ────────────────────────────────────────────────────────


def _capability_in_profile(manifest: CapabilityManifest, profile: str | None) -> bool:
    """True when ``manifest`` is part of the requested profile filter."""

    if profile is None:
        return True
    return profile in manifest.default_in_profiles


# ── top-level status run ──────────────────────────────────────────────────


def run_status(
    *,
    capability_index: CapabilityIndex | None = None,
    probes: Sequence[PrereqProbe] | None = None,
    profile: str | None = None,
    activation_context: ActivationContext | None = None,
    repo_root: Path | None = None,
    env: dict[str, str] | None = None,
    home: Path | None = None,
    adapters_dir: Path | None = None,
    now: _dt.datetime | None = None,
) -> StatusEnvelope:
    """Top-level status entry point. Used by the CLI + by tests.

    Returns the :class:`StatusEnvelope`; the CLI is responsible for
    rendering it as text/JSON and writing the cache. Pure-function shape
    keeps tests free of process-side-effects.
    """

    capability_index = (
        capability_index if capability_index is not None else load_capabilities(repo_root)
    )
    probes = list(probes) if probes is not None else default_probes()

    bound_probes = [p for p in probes if p.capability_id is not None]
    advisory_notes: list[str] = []
    if not bound_probes:
        # V0a F002 (probe capability_id binding) not yet shipped — still
        # produce status using requires-resolution alone.
        advisory_notes.append(
            "No probes declare capability_id bindings — capability status is "
            "computed from requires-resolution alone. Probe-derived status "
            "will surface once V0a F002 lands."
        )

    if bound_probes:
        if activation_context is None:
            root = repo_root if repo_root is not None else Path(__file__).resolve().parents[2]
            activation_context = build_activation_context(root)
        # Run probes under the operator's selected profile; default to
        # ``core`` so unbound capabilities at least surface their
        # informational probes via the existing sweep matrix.
        sweep_profile = profile if profile in _VALID_PROFILE_NAMES else "core"
        sweep = run_sweep(
            sweep_profile,
            probes=probes,
            activation_context=activation_context,
            capability_index=capability_index,
        )
        grouped = _probe_results_by_capability(probes, sweep.probes)
    else:
        grouped = {}

    capabilities: list[CapabilityStatusResult] = []
    for manifest in capability_index.all:
        in_profile = _capability_in_profile(manifest, profile)
        if profile is not None and not in_profile:
            continue
        probe_results = tuple(grouped.get(manifest.id, ()))
        requires_resolution = resolve_requires(manifest, env=env, home=home)
        adapter_ok = adapter_installed(manifest, adapters_dir=adapters_dir)
        capabilities.append(
            build_capability_result(
                manifest,
                probe_results,
                requires_resolution=requires_resolution,
                in_active_profile=in_profile,
                adapter_is_installed=adapter_ok,
            )
        )

    generated_at = (now if now is not None else _dt.datetime.now(_dt.timezone.utc)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return StatusEnvelope(
        schema_version=SCHEMA_VERSION,
        generated_at=generated_at,
        capabilities=tuple(capabilities),
        advisory_notes=tuple(advisory_notes),
    )


# ── filtering a single capability ─────────────────────────────────────────


def filter_for_capability(
    envelope: StatusEnvelope,
    capability_id: str,
    capability_index: CapabilityIndex,
) -> StatusEnvelope:
    """Narrow an envelope to a single capability or raise with suggestion."""

    matching = [c for c in envelope.capabilities if c.capability_id == capability_id]
    if matching:
        return StatusEnvelope(
            schema_version=envelope.schema_version,
            generated_at=envelope.generated_at,
            capabilities=tuple(matching),
            advisory_notes=envelope.advisory_notes,
        )
    suggestions = difflib.get_close_matches(
        capability_id, [m.id for m in capability_index.all], n=1, cutoff=0.5
    )
    if suggestions:
        raise CapabilityManifestError(
            f"unknown capability id {capability_id!r}; did you mean {suggestions[0]!r}?"
        )
    raise CapabilityManifestError(
        f"unknown capability id {capability_id!r}; "
        f"known: {', '.join(m.id for m in capability_index.all)}"
    )


# ── rendering ─────────────────────────────────────────────────────────────


_STATUS_BADGE = {
    CapabilityStatus.READY: "✓ ready",
    CapabilityStatus.NEEDS_SETUP: "… needs_setup",
    CapabilityStatus.BLOCKED: "✗ blocked",
    CapabilityStatus.NOT_INSTALLED: "○ not_installed",
    CapabilityStatus.OPTIONAL: "· optional",
}


def render_text(envelope: StatusEnvelope) -> str:
    lines: list[str] = []
    lines.append(f"Capability status (schema {envelope.schema_version})")
    lines.append(f"generated_at: {envelope.generated_at}")
    for note in envelope.advisory_notes:
        lines.append(f"  advisory: {note}")
    lines.append("")
    for cap in envelope.capabilities:
        lines.extend(_render_capability_text(cap))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_capability_text(cap: CapabilityStatusResult) -> list[str]:
    lines: list[str] = []
    badge = _STATUS_BADGE.get(cap.status, cap.status.value)
    lines.append(f"[{badge}] {cap.capability_id}")
    chips = []
    if cap.owner_boundary.get("dontpanic_core"):
        chips.append("core")
    if cap.owner_boundary.get("adapter"):
        chips.append("adapter")
    if cap.owner_boundary.get("operator"):
        chips.append("operator")
    if chips:
        lines.append(f"    owner_boundary: {' | '.join(chips)}")
    for probe in cap.pending_probes:
        lines.append(f"    probe pending: {probe['name']} — {probe['reason']}")
    if cap.configured:
        lines.append(f"    Configured: {', '.join(cap.configured)}")
    if cap.missing:
        lines.append(f"    Missing:    {', '.join(cap.missing)}")
    if cap.next_actions:
        lines.append("    Next actions:")
        for action in cap.next_actions:
            tag = (
                "[automatable]"
                if action["automatable"]
                else (f"[human-required: {action.get('human_required_reason') or 'see setup_doc'}]")
            )
            lines.append(f"      - {tag} {action['what']}")
    for note in cap.advisory_notes:
        lines.append(f"    advisory: {note}")
    return lines


def render_json(envelope: StatusEnvelope) -> str:
    return json.dumps(envelope.to_json_dict(), indent=2, sort_keys=True) + "\n"


# ── cache writer ──────────────────────────────────────────────────────────


def write_cache(envelope: StatusEnvelope, *, path: Path | None = None) -> Path:
    """Write the JSON envelope to ``~/.dontpanic/capabilities-status.json``.

    File is created with mode ``0o600`` (operator-only). Parent
    directory is created with mode ``0o700`` when it does not exist.
    """

    target = path if path is not None else DEFAULT_CACHE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        # Best-effort tightening; absence is non-fatal because permissions
        # vary across operator setups.
        pass
    payload = render_json(envelope)
    target.write_text(payload, encoding="utf-8")
    os.chmod(target, CACHE_FILE_MODE)
    # Sanity check — re-read mode and assert tight perms when we just
    # wrote the file. ``os.chmod`` failure on shared FS would be the only
    # way this is silently wrong.
    mode_bits = stat.S_IMODE(target.stat().st_mode)
    if mode_bits != CACHE_FILE_MODE:
        # Re-attempt once; some filesystems mask mode on first write.
        os.chmod(target, CACHE_FILE_MODE)
    return target


# ── argparse + main ───────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dontpanic capabilities",
        description="Inspect capability status against the local environment.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    status = sub.add_parser(
        "status",
        help="Show per-capability readiness against the local environment.",
    )
    status.add_argument(
        "capability_id",
        nargs="?",
        default=None,
        help="Filter output to a single capability by id.",
    )
    status.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    status.add_argument(
        "--profile",
        default=None,
        help="Filter to capabilities whose default_in_profiles contains this name.",
    )
    status.add_argument(
        "--no-cache-write",
        action="store_true",
        help="Skip writing the ~/.dontpanic/capabilities-status.json cache.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point invoked by ``dontpanic capabilities <args>``."""

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.subcommand is None:
        parser.print_help(sys.stderr)
        return 2
    if args.subcommand != "status":  # pragma: no cover - argparse already restricts
        parser.print_help(sys.stderr)
        return 2

    try:
        capability_index = load_capabilities()
    except CapabilityManifestError as exc:
        print(f"capabilities status: failed to load manifests: {exc}", file=sys.stderr)
        return 1

    envelope = run_status(
        capability_index=capability_index,
        profile=args.profile,
    )

    if args.capability_id is not None:
        try:
            envelope = filter_for_capability(envelope, args.capability_id, capability_index)
        except CapabilityManifestError as exc:
            print(f"capabilities status: {exc}", file=sys.stderr)
            return 2

    if args.format == "json":
        sys.stdout.write(render_json(envelope))
    else:
        sys.stdout.write(render_text(envelope))

    if not args.no_cache_write:
        try:
            write_cache(envelope)
        except OSError as exc:
            print(f"capabilities status: cache write failed: {exc}", file=sys.stderr)
            return 1

    return 0


__all__ = [
    "CAPABILITY_STATUS_VALUES",
    "CACHE_FILE_MODE",
    "CapabilityStatus",
    "CapabilityStatusResult",
    "DEFAULT_CACHE_PATH",
    "RequiresResolution",
    "SCHEMA_VERSION",
    "StatusEnvelope",
    "adapter_installed",
    "build_capability_result",
    "build_parser",
    "compute_capability_status",
    "filter_for_capability",
    "main",
    "render_json",
    "render_text",
    "resolve_requires",
    "run_status",
    "write_cache",
]

CAPABILITY_STATUS_VALUES: tuple[str, ...] = tuple(s.value for s in CapabilityStatus)
