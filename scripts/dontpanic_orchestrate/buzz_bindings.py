"""Plan 2026-07-27-001 F016 — optional Buzz agent ↔ worker-profile binding (D5/C6).

``agent_bindings`` is an optional key in ``buzz.json`` mapping a Buzz
agent identity (a ``buzz_agent_id`` or a display name — whatever string
the operator uses to name the agent in their private community) to a
LOCAL worker-profile id (F013 ``worker_profiles.<id>``)::

    {
      "relay_url": "...",
      "channels": ["..."],
      "reporter_key_ref": "env:BUZZ_PRIVATE_KEY",
      "agent_bindings": { "Fizz": "fizz", "Honey": "honey" }
    }

The feature is OFF by default: no key (or no buzz.json) means no
bindings, and nothing else changes. Loading mirrors the F006 notify-sink
posture — fail-soft, never raises, malformed entries are skipped.

Authority boundaries (D004/D009, restated because this is the seam where
they could blur):

  - **Bindings are display-only.** Resolution here is an identity JOIN
    for docs/status surfaces (Buzz agent → profile → harness + model).
    Dispatch never consults this table, so bindings never CONFER dispatch
    authority: ``worker_profiles.resolve_worker`` accepts exactly the
    registered harnesses and defined profile ids it accepted before any
    binding existed. A Buzz-side key that happens to collide with a
    profile id (``"fizz" → "fizz"``, or even ``"fizz" → "honey"``) is
    dispatchable only BECAUSE the profile id is — dispatch resolves the
    profile table entry for that name and ignores the binding target —
    and an unbound or non-colliding Buzz agent gains nothing.
  - **Buzz remains the UX for membership; DontPanic remains the dispatch
    authority.** Model selection stays single-sourced in the profile —
    a binding carries no harness/model of its own.
  - **No auto-dispatch from Buzz agent messages.** Any Buzz-side caller
    goes through the confirm-gated recipe (F007,
    ``examples/buzz-caller/README.md``); the F006 notify reporter stays
    a separate thin identity, unrelated to these bindings.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from dontpanic_orchestrate import global_config

CONFIG_KEY: Final[str] = "agent_bindings"
_CONFIG_FILENAME: Final[str] = "buzz.json"
# Same explicit-path override the F006 notify sink honors.
_CONFIG_PATH_ENV: Final[str] = "DONTPANIC_BUZZ_CONFIG"


@dataclass(frozen=True)
class ResolvedBinding:
    """One Buzz agent → profile join for display/status surfaces only —
    never an input to dispatch resolution."""

    buzz_agent: str
    """The Buzz-side identity as configured (buzz_agent_id or display name)."""

    profile_id: str
    """The configured local worker-profile id."""

    bound: bool
    """True when ``profile_id`` names a defined worker profile."""

    display_name: str | None
    harness: str | None
    model: str | None

    problem: str | None
    """Operator-fixable message when the binding does not resolve."""


def bindings_config_path() -> Path:
    """buzz.json location: ``DONTPANIC_BUZZ_CONFIG`` env override, else
    ``$DONTPANIC_HOME/buzz.json`` — identical to the notify sink so one
    file carries both the reporter identity and the bindings."""
    override = os.environ.get(_CONFIG_PATH_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return global_config.dontpanic_home() / _CONFIG_FILENAME


def load_agent_bindings(config_path: Path | None = None) -> dict[str, str]:
    """The configured ``agent_bindings`` map. Fail-soft on every malformed
    shape (missing file, invalid JSON, non-object config or block) and
    per-entry (non-string / empty key or value → entry skipped): the
    valid zero state IS the default state — the feature is off."""
    path = config_path if config_path is not None else bindings_config_path()
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    block = data.get(CONFIG_KEY)
    if not isinstance(block, dict):
        return {}
    return {
        key.strip(): value.strip()
        for key, value in block.items()
        if isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip()
    }


def resolve_agent_bindings(
    project_path: Path | None = None, config_path: Path | None = None
) -> list[ResolvedBinding]:
    """Join each binding against the F013 profile table (global overlaid
    by project). Display-only: a row that fails to join is reported as
    unbound with a problem message, never raised — and no row here is
    ever consulted by dispatch resolution."""
    from dontpanic_orchestrate import worker_profiles as wp
    from dontpanic_orchestrate.config.worker_profiles import normalize_harness
    from dontpanic_orchestrate.executors import AGENT_REGISTRY

    bindings = load_agent_bindings(config_path)
    if not bindings:
        return []
    profiles = wp.load_profiles(project_path)
    rows: list[ResolvedBinding] = []
    for buzz_agent, profile_id in sorted(bindings.items()):
        profile = profiles.get(profile_id)
        if profile is not None:
            rows.append(
                ResolvedBinding(
                    buzz_agent=buzz_agent,
                    profile_id=profile_id,
                    bound=True,
                    display_name=profile.display_name,
                    harness=profile.harness,
                    model=profile.model,
                    problem=None,
                )
            )
            continue
        if normalize_harness(profile_id) in AGENT_REGISTRY:
            problem = (
                f"{profile_id!r} is a harness name, not a worker profile; bindings "
                "map Buzz agents to worker-profile ids only (bindings never grant "
                "dispatch — define a profile with `dontpanic workers add`)"
            )
        else:
            problem = (
                f"{profile_id!r} names no defined worker profile; define it with "
                f"`dontpanic workers add {profile_id} --harness <harness>`"
            )
        rows.append(
            ResolvedBinding(
                buzz_agent=buzz_agent,
                profile_id=profile_id,
                bound=False,
                display_name=None,
                harness=None,
                model=None,
                problem=problem,
            )
        )
    return rows


def binding_payloads(rows: list[ResolvedBinding]) -> list[dict[str, object]]:
    """JSON-friendly projection for the ``workers buzz-bindings`` CLI."""
    return [asdict(row) for row in rows]


__all__ = [
    "CONFIG_KEY",
    "ResolvedBinding",
    "binding_payloads",
    "bindings_config_path",
    "load_agent_bindings",
    "resolve_agent_bindings",
]
