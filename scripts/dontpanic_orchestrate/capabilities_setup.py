"""Plan 2026-05-22-004 F001 — `dontpanic capabilities setup` planning surface.

Reads the selected capability manifest and current status from V0b
``capabilities status`` projection, then prints the ordered ``setup_steps[]``
with automatable/human-required labels, command templates, verification
probes, and current readiness. No commands are executed in F001 — this is
strictly a planning surface.

Future V2 features (F002 governed runner, F003 evidence) layer on top of
the same envelope.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from collections.abc import Sequence

from dontpanic_orchestrate.capabilities import (
    CapabilityIndex,
    CapabilityManifest,
    CapabilityManifestError,
    SetupStep,
    load_capabilities,
)
from dontpanic_orchestrate.capabilities_status import (
    CapabilityStatus,
    CapabilityStatusResult,
    build_capability_result,
    resolve_requires,
)


def resolve_capability(
    capability_id: str, capability_index: CapabilityIndex
) -> CapabilityManifest:
    """Return the manifest for ``capability_id`` or raise with a suggestion.

    Mirrors :func:`capabilities_status.filter_for_capability` so the setup
    surface refuses unknown ids with the same closest-match hint operators
    already see in ``capabilities status``.
    """

    manifest = capability_index.get(capability_id)
    if manifest is not None:
        return manifest
    known = [m.id for m in capability_index.all]
    suggestions = difflib.get_close_matches(capability_id, known, n=1, cutoff=0.5)
    if suggestions:
        raise CapabilityManifestError(
            f"unknown capability id {capability_id!r}; did you mean {suggestions[0]!r}?"
        )
    raise CapabilityManifestError(
        f"unknown capability id {capability_id!r}; known: {', '.join(known)}"
    )


def _probe_readiness_index(status_result: CapabilityStatusResult) -> dict[str, str]:
    """Map ``probe_name -> readiness label`` from a status result.

    Only PENDING probes appear in ``status_result.pending_probes``; other
    probes that did run produce status flow through ``CapabilityStatus``
    on the result envelope itself, not per-probe. We surface PENDING per
    probe so the operator sees ``verify_probe: pending`` next to a step.
    """

    return {p["name"]: f"pending — {p['reason']}" for p in status_result.pending_probes}


def _step_readiness_line(
    step: SetupStep, probe_index: dict[str, str]
) -> str | None:
    """Render the ``readiness`` chip for a setup step, when applicable."""

    if step.verify_probe is None:
        return None
    label = probe_index.get(step.verify_probe)
    if label is None:
        return None
    return f"verify_probe {step.verify_probe}: {label}"


def render_print_steps(
    manifest: CapabilityManifest, status_result: CapabilityStatusResult
) -> str:
    """Render an ordered, human-readable plan of ``setup_steps[]``.

    No side effects — purely a string builder. Acceptance #1/#2/#3:
      - All setup steps render in order.
      - Human-required steps carry their reason text.
      - Automatable steps carry command_template and verify_probe when set.
    """

    probe_index = _probe_readiness_index(status_result)
    lines: list[str] = []
    badge = _CAPABILITY_BADGE.get(status_result.status, status_result.status.value)
    lines.append(f"capability: {manifest.id}")
    lines.append(f"title:      {manifest.title}")
    lines.append(f"status:     {badge}")
    lines.append(f"setup_doc:  {manifest.setup_doc}")
    if not manifest.setup_steps:
        lines.append("")
        lines.append("(no setup steps declared in manifest)")
        lines.append("")
        lines.append(
            "F001 is a planning surface only — no commands are executed."
        )
        return "\n".join(lines) + "\n"

    lines.append("")
    lines.append(f"Setup steps ({len(manifest.setup_steps)}):")
    for index, step in enumerate(manifest.setup_steps, start=1):
        kind = "[automatable]" if step.automatable else "[human-required]"
        lines.append(f"  {index:>2}. {kind} {step.id}")
        lines.append(f"      what: {step.what}")
        if step.automatable:
            if step.command_template:
                lines.append(f"      command_template: {step.command_template}")
            if step.verify_probe:
                lines.append(f"      verify_probe: {step.verify_probe}")
        else:
            reason = step.human_required_reason or "see setup_doc"
            lines.append(f"      human_required_reason: {reason}")
            if step.command_template:
                lines.append(f"      command_template (manual): {step.command_template}")
            if step.verify_probe:
                lines.append(f"      verify_probe: {step.verify_probe}")
        readiness = _step_readiness_line(step, probe_index)
        if readiness is not None:
            lines.append(f"      readiness: {readiness}")
    lines.append("")
    lines.append("F001 is a planning surface only — no commands are executed.")
    return "\n".join(lines) + "\n"


_CAPABILITY_BADGE = {
    CapabilityStatus.READY: "✓ ready",
    CapabilityStatus.NEEDS_SETUP: "… needs_setup",
    CapabilityStatus.BLOCKED: "✗ blocked",
    CapabilityStatus.NOT_INSTALLED: "○ not_installed",
    CapabilityStatus.OPTIONAL: "· optional",
}


def build_planning_status(manifest: CapabilityManifest) -> CapabilityStatusResult:
    """Build a status snapshot for the setup planning surface.

    F001 is a non-executing planning surface (acceptance #4). We must not
    invoke ``run_status()`` here because its probe sweep spawns subprocess
    calls (``git remote -v``, ``gh auth status``, …). Instead, compute
    status from ``resolve_requires`` (which only inspects PATH/env/files)
    and ``adapter_installed`` (filesystem check). Probe-derived state is
    intentionally absent — the printed plan is identical regardless.
    """

    requires_resolution = resolve_requires(manifest)
    return build_capability_result(
        manifest,
        probe_results=(),
        requires_resolution=requires_resolution,
        in_active_profile=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dontpanic capabilities setup",
        description=(
            "Plan setup for a capability. F001 only prints steps; F002 will add"
            " a governed --automate-safe runner."
        ),
    )
    parser.add_argument(
        "capability_id",
        help="Capability id (matches a checked-in capabilities/<id>.json).",
    )
    parser.add_argument(
        "--print-steps",
        action="store_true",
        help="Print the ordered setup_steps[] plan. F001 only supports this mode.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point invoked by ``dontpanic capabilities setup <args>``."""

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.print_steps:
        # F001 is print-only. Refusing without --print-steps keeps the
        # exec/automate-safe paths reserved for F002 and prevents any
        # surprise side effects when the flag is forgotten.
        print(
            "capabilities setup: F001 requires --print-steps "
            "(no execution mode is implemented yet)",
            file=sys.stderr,
        )
        return 2

    try:
        capability_index = load_capabilities()
    except CapabilityManifestError as exc:
        print(f"capabilities setup: failed to load manifests: {exc}", file=sys.stderr)
        return 1

    try:
        manifest = resolve_capability(args.capability_id, capability_index)
    except CapabilityManifestError as exc:
        print(f"capabilities setup: {exc}", file=sys.stderr)
        return 2

    status_result = build_planning_status(manifest)
    sys.stdout.write(render_print_steps(manifest, status_result))
    return 0


__all__ = [
    "build_parser",
    "build_planning_status",
    "main",
    "render_print_steps",
    "resolve_capability",
]
