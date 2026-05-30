"""Plan 2026-05-30-001 F001 — single generated operating brief.

One generator renders DontPanic's operator guide from live source-of-truth
data so the same operating facts are never hand-copied into a manifest, an
AGENTS.md block, README text, and doctor output (the duplication-and-drift
failure mode the parent plan exists to prevent).

Source of truth (all live program facts, never duplicated by hand):

- supported command names come from :mod:`agent_manifest`'s own command
  generation (``bootstrap_manifest().supported_commands``) — the brief never
  maintains a second copy of the command list. New commands (``agent`` and
  ``orchestrate`` after F002) appear in the brief automatically.
- worker executor names come from :data:`executors.AGENT_REGISTRY` — the
  brief lists exactly the agents that have a real executor implementation and
  never invents unsupported labels.
- the DontPanic runtime version comes from
  :data:`dontpanic_orchestrate.__version__`.
- config-home status comes from :mod:`global_config` (resolved DontPanic home
  plus legacy ``~/.jarvis`` presence).

The brief makes two product invariants explicit on every render:

1. **Operator vs worker.** An *operator* (interactive agent or human) drives
   the workflow by running CLI commands. A *worker executor* is an agent CLI
   DontPanic can dispatch to through a registered executor. Any agent can
   operate DontPanic; only agents in the executor list can be dispatched as
   workers.
2. **Not Kubernetes/Airflow/IT orchestration.** DontPanic is local CLI
   workflow orchestration. Unsupported agents (Grok, Gemini, …) should operate
   DontPanic, not configure themselves as workers.

Determinism (so managed repo blocks can detect staleness): :func:`render_brief`
takes typed :class:`BriefInputs` and produces byte-stable text for the same
inputs — no timestamps, executor names sorted, command order preserved from the
manifest. :class:`RenderedBrief` carries a :data:`GENERATOR_VERSION` and a
content hash over the rendered body so F003's managed-block writer can decide
whether to rewrite a stale block.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from dontpanic_orchestrate import __version__ as _DONTPANIC_VERSION
from dontpanic_orchestrate import agent_manifest
from dontpanic_orchestrate import executors
from dontpanic_orchestrate import global_config as gc

GENERATOR_VERSION = "1.0"
"""Version of the brief generator (renderer + layout), independent of the
DontPanic runtime version. Stamped into :class:`RenderedBrief` and the F003
managed-block markers so a layout change forces a managed-block rewrite even
when the underlying facts are unchanged. Bump whenever the rendered structure
changes in a way that should re-stamp downstream managed blocks."""

# ──────────────────────────────  canonical strings  ──────────────────────────────

# The not-Kubernetes/Airflow clarification, verbatim from the plan's Product
# Model section. Asserted for presence by tests so the warning never silently
# drifts out of the brief.
NOT_IT_ORCHESTRATION = (
    "DontPanic is a local orchestration CLI, not Kubernetes, Airflow, or IT\n"
    "orchestration. You can operate it if you can run its commands. You can be\n"
    "dispatched as a worker only if you appear in DontPanic's executor list.\n"
    "If you are Grok, Gemini, or another unsupported agent, operate DontPanic;\n"
    "do not configure yourself as a worker."
)

# The canonical workflow shown to both humans and agents, verbatim from the
# plan. F002's ``orchestrate`` gateway prints the same line.
CANONICAL_WORKFLOW = (
    "projects add -> plan lock -> orchestrate/dispatch-from-plan ->\n"
    "cross-model implementation and audit -> approve/resume/close"
)


# ──────────────────────────────  typed inputs / output  ──────────────────────────────


class BriefInputs(BaseModel):
    """Typed source-of-truth snapshot the renderer consumes.

    Constructed from live program facts by :func:`collect_brief_inputs`, or
    by tests with fabricated commands/executors to prove the rendered brief
    tracks its inputs rather than hand-edited strings. ``extra='forbid'`` keeps
    the input contract closed.
    """

    model_config = ConfigDict(extra="forbid")

    dontpanic_version: str
    """The DontPanic runtime version (``dontpanic_orchestrate.__version__``)."""

    supported_commands: list[str]
    """Stable subcommand names from :mod:`agent_manifest`. Order is preserved
    from the manifest (it is meaningful and stable); never re-sorted here."""

    worker_executors: list[str]
    """Agent names with a real executor in :data:`executors.AGENT_REGISTRY`.
    Sorted by the renderer for byte-stable output."""

    config_home: str
    """Resolved DontPanic home directory (``global_config.dontpanic_home()``)."""

    using_legacy_home: bool
    """True when the resolved home is the legacy ``~/.jarvis`` directory rather
    than the canonical ``~/.dontpanic``."""

    legacy_home_present: bool
    """True when a legacy ``~/.jarvis`` directory exists on this machine —
    surfaces config-home split-brain risk reconciled by F005."""


class RenderedBrief(BaseModel):
    """Deterministic render output plus the metadata managed repo blocks need.

    ``text`` is the brief body and contains no hash (so the hash is not
    self-referential). ``content_hash`` is computed over ``generator_version``
    and ``text`` together, so either a layout bump or a fact change moves the
    hash and signals downstream managed blocks to refresh.
    """

    model_config = ConfigDict(extra="forbid")

    generator_version: str
    content_hash: str
    text: str


# ──────────────────────────────  collection (live facts)  ──────────────────────────────


def _supported_commands() -> list[str]:
    """Pull the current command surface from :mod:`agent_manifest`'s own
    generation rather than re-listing commands here. ``bootstrap_manifest``
    reflects the live version's command set, so ``agent`` and ``orchestrate``
    appear automatically once F002 adds them to the manifest."""
    return list(agent_manifest.bootstrap_manifest().supported_commands)


def _worker_executors() -> list[str]:
    """The registered worker executors. The brief lists exactly these names —
    an agent absent from :data:`executors.AGENT_REGISTRY` is operator-only."""
    return sorted(executors.AGENT_REGISTRY)


def collect_brief_inputs() -> BriefInputs:
    """Gather a live :class:`BriefInputs` snapshot from current host facts.

    Pure read — resolves the config home but does not create it, so calling
    this never writes to the operator's machine.
    """
    home = gc.dontpanic_home()
    legacy_dir = Path.home() / gc.LEGACY_DIRNAME
    return BriefInputs(
        dontpanic_version=_DONTPANIC_VERSION,
        supported_commands=_supported_commands(),
        worker_executors=_worker_executors(),
        config_home=str(home),
        using_legacy_home=home.name == gc.LEGACY_DIRNAME,
        legacy_home_present=legacy_dir.is_dir(),
    )


# ──────────────────────────────  rendering  ──────────────────────────────


def _content_hash(generator_version: str, text: str) -> str:
    """SHA-256 over generator version + body. Deterministic: same inputs →
    same digest, so a managed repo block can compare a stored hash against a
    freshly rendered one to detect staleness."""
    payload = f"{generator_version}\n{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def render_brief(inputs: BriefInputs) -> RenderedBrief:
    """Render the deterministic operating brief from typed inputs.

    Byte-stable for identical inputs: executor names are sorted, command order
    is preserved from the manifest, and no timestamps are emitted.
    """
    commands = "\n".join(f"  - {c}" for c in inputs.supported_commands)
    workers = "\n".join(f"  - {w}" for w in sorted(inputs.worker_executors))

    if inputs.using_legacy_home:
        home_status = (
            f"Config home: {inputs.config_home} (legacy ~/.jarvis home in use; "
            f"run reconcile to migrate to ~/.dontpanic)"
        )
    elif inputs.legacy_home_present:
        home_status = (
            f"Config home: {inputs.config_home} "
            f"(legacy ~/.jarvis also present — reconcile to avoid split-brain state)"
        )
    else:
        home_status = f"Config home: {inputs.config_home}"

    lines = [
        f"DontPanic operating brief (runtime {inputs.dontpanic_version}, "
        f"brief generator {GENERATOR_VERSION})",
        "",
        "WHAT THIS IS",
        NOT_IT_ORCHESTRATION,
        "",
        "OPERATOR vs WORKER",
        "Operator: an interactive agent or human that drives the workflow by",
        "  running DontPanic CLI commands. Any agent that can run the commands",
        "  below can operate DontPanic.",
        "Worker executor: an agent CLI DontPanic can dispatch to through a",
        "  registered executor. Only the agents listed under WORKER EXECUTORS",
        "  can be dispatched as workers; everyone else is operator-only.",
        "",
        "SUPPORTED COMMANDS",
        commands if commands else "  (none reported)",
        "",
        "WORKER EXECUTORS",
        workers if workers else "  (none registered)",
        "",
        "CANONICAL WORKFLOW",
        CANONICAL_WORKFLOW,
        "",
        home_status,
    ]
    text = "\n".join(lines) + "\n"
    return RenderedBrief(
        generator_version=GENERATOR_VERSION,
        content_hash=_content_hash(GENERATOR_VERSION, text),
        text=text,
    )


def generate_brief() -> RenderedBrief:
    """Collect live inputs and render the brief in one call. The machine and
    repo surfaces (F002 ``agent brief`` / ``orchestrate``, F003 managed block,
    F004 doctor) all go through this so they share one source of truth."""
    return render_brief(collect_brief_inputs())


def to_public_dict(brief: RenderedBrief) -> dict[str, Any]:
    """Serialize a rendered brief for ``--json`` CLI output."""
    return brief.model_dump()


__all__ = [
    "BriefInputs",
    "CANONICAL_WORKFLOW",
    "GENERATOR_VERSION",
    "NOT_IT_ORCHESTRATION",
    "RenderedBrief",
    "collect_brief_inputs",
    "generate_brief",
    "render_brief",
    "to_public_dict",
]
