"""Plan 2026-07-27-001 F006 — Buzz notify sink (fail-soft NotifyEvent fan-out).

Mirrors the public shape of :mod:`notify_discord` so the
:mod:`notify_event` dispatcher fans events to terminal + Discord + Buzz.
All failure modes return ``False`` and emit at most one warn-once stderr
line per cause; this sink NEVER raises so callers don't have to guard.

Delivery is via the official Buzz CLI — the ``buzz`` binary from the
block/buzz ``buzz-cli`` crate — as a subprocess (``shell=False``):
``buzz messages send --channel <uuid> --content -`` with the message body
on stdin. DontPanic contains no relay or Nostr client per the locked
non-goals in ECOSYSTEM.md § Buzz. When ``buzz`` is not installed the sink
is silently unavailable, same as an unconfigured webhook.

Config resolution order:
  1. ``DONTPANIC_BUZZ_CONFIG`` env — explicit path to a buzz.json
     (test / power-user override).
  2. ``$DONTPANIC_HOME/buzz.json`` (default ``~/.dontpanic/buzz.json``,
     honoring the same home resolution as the rest of the config surface).
  3. Missing / invalid / incomplete config → ``notify`` returns False
     without any subprocess attempt.

Expected keys mirror the F009 doctor check (``check_buzz_config``):
``relay_url``, ``channels`` (non-empty list of non-empty channel-UUID
strings; v1 posts to the first entry), ``reporter_key_ref``. In Buzz the
relay URL IS the community/workspace authority — the CLI has no separate
community flag; ``relay_url`` is handed to ``buzz`` via the
``BUZZ_RELAY_URL`` subprocess environment variable. It must point at the
operator's PRIVATE community relay — public communities are
support/discovery-only and never a notify destination (D004/D007).

``reporter_key_ref`` is a REFERENCE, never key material (buzz.json stays
secret-free):
  - ``env:NAME`` — key material read from the named environment variable.
  - anything else — treated as a filesystem path to a key file.
The resolved key is handed to ``buzz`` via the ``BUZZ_PRIVATE_KEY``
subprocess environment variable only — never on argv, never logged.

Disable knobs (any one silences this sink):
  - ``DONTPANIC_BUZZ_DISABLE=1`` — sink-specific.
  - ``JARVIS_NOTIFY_DISABLE=1`` — global kill-switch shared with the
    terminal + Discord sinks.

Content contract (F006 redaction step): posts are summary-only
projections — title + short detail + evidence pointer. Every component is
run through :func:`state_projection.scrub_secrets` and home-path redaction
BEFORE any length cap is applied (truncating first could slice a secret at
the cap boundary so its prefix no longer matches the scrub regexes), then
the total content is hard-capped so full transcripts can never leak onto
a relay. Home redaction covers macOS/Linux/Windows home-path shapes for
ANY username, not just the current process user.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from dontpanic_orchestrate.notify_event import NotifyEvent

from dontpanic_orchestrate import global_config

_CONFIG_FILENAME: Final[str] = "buzz.json"
_CONFIG_PATH_ENV: Final[str] = "DONTPANIC_BUZZ_CONFIG"
_DISABLE_ENV: Final[str] = "DONTPANIC_BUZZ_DISABLE"
# Shared global kill-switch — mirrors notify.DISABLE_ENV / notify_discord.
_GLOBAL_DISABLE_ENV: Final[str] = "JARVIS_NOTIFY_DISABLE"

_CLI_NAME: Final[str] = "buzz"
_CLI_PATH_ENV: Final[str] = "DONTPANIC_BUZZ_CLI"
_KEY_ENV_FOR_CLI: Final[str] = "BUZZ_PRIVATE_KEY"
# Relay selection: the Buzz CLI reads its relay (the community authority)
# from BUZZ_RELAY_URL — there is no --relay/--community argv interface.
_RELAY_ENV_FOR_CLI: Final[str] = "BUZZ_RELAY_URL"
_SUBPROCESS_TIMEOUT_SECONDS: Final[float] = 10.0

# Summary-only projection cap. Nostr relays accept large events; the cap is
# a redaction posture (no full transcripts on relays), not a protocol limit.
_CONTENT_TOTAL_LIMIT: Final[int] = 900
_DETAIL_LIMIT: Final[int] = 400

# Same key set the F009 doctor validates — keep in lock-step with
# scripts/dontpanic_doctor.py BUZZ_EXPECTED_KEYS.
EXPECTED_KEYS: Final[tuple[str, ...]] = (
    "relay_url",
    "channels",
    "reporter_key_ref",
)

# Warn-once dedup so a misconfigured sink doesn't spam stderr per dispatch.
_warned: set[str] = set()


@dataclass(frozen=True)
class BuzzConfig:
    """Validated, usable buzz.json content. ``channel`` is the first entry
    of the config's ``channels`` list (v1 posts to a single channel).
    ``relay_url`` is the private community's relay — in Buzz the relay URL
    is the community/workspace authority."""

    relay_url: str
    channel: str
    reporter_key_ref: str


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _is_sink_disabled() -> bool:
    return (
        _truthy(os.environ.get(_DISABLE_ENV, ""))
        or _truthy(os.environ.get(_GLOBAL_DISABLE_ENV, ""))
    )


def _warn_once(key: str, message: str) -> None:
    if key in _warned:
        return
    _warned.add(key)
    print(f"[notify_buzz] {message}", file=sys.stderr)


def reset_warning_cache() -> None:
    """Clear the per-process warn-once cache. Test helper."""
    _warned.clear()


def _config_path() -> Path:
    override = os.environ.get(_CONFIG_PATH_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return global_config.dontpanic_home() / _CONFIG_FILENAME


def _value_usable(key: str, value: object) -> bool:
    if key == "channels":
        return (
            isinstance(value, list)
            and len(value) > 0
            and all(isinstance(c, str) and c.strip() for c in value)
        )
    return isinstance(value, str) and bool(value.strip())


def _load_config() -> BuzzConfig | None:
    """Load + validate buzz.json. Returns None on every failure mode —
    missing file, invalid JSON, non-object, missing keys, unusable values.
    Never raises; never logs config VALUES (only the generic cause)."""
    path = _config_path()
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if any(not _value_usable(k, data.get(k)) for k in EXPECTED_KEYS):
        return None
    return BuzzConfig(
        relay_url=data["relay_url"].strip(),
        channel=data["channels"][0].strip(),
        reporter_key_ref=data["reporter_key_ref"].strip(),
    )


def _resolve_cli() -> str | None:
    override = os.environ.get(_CLI_PATH_ENV, "").strip()
    if override:
        return override if Path(override).is_file() else None
    return shutil.which(_CLI_NAME)


def _resolve_reporter_key(ref: str) -> str | None:
    """Resolve a key REFERENCE to key material. The returned value goes only
    into the subprocess environment — callers must never log it."""
    if ref.startswith("env:"):
        value = os.environ.get(ref[len("env:"):].strip(), "")
        return value if value.strip() else None
    try:
        path = Path(ref).expanduser()
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            return value if value else None
    except (OSError, UnicodeError):
        return None
    return None


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


# Home-directory shapes for ANY username across macOS (/Users/<name>),
# Linux (/home/<name>, /root), and Windows (C:\Users\<name>) — the exact
# current-user replacement alone would leak OTHER users' home paths (e.g.
# a transcript quoting a teammate's checkout).
_HOME_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:/Users/[^/\\\s\"']+|/home/[^/\\\s\"']+|/root(?=[/\\\s\"']|$)"
    # Windows home paths: case-insensitive drive + Users + name; either
    # backslash or forward slash (auditor F006-i3 finding).
    r"|[A-Za-z]:[/\\][Uu][Ss][Ee][Rr][Ss][/\\][^/\\\s\"']+)",
    re.IGNORECASE,
)


def _redact_home(text: str) -> str:
    """Collapse home-directory paths to ``~`` so raw home paths (usernames)
    never reach a relay — the current process home AND any other user's
    macOS/Linux/Windows home-path shape."""
    home = os.path.expanduser("~")
    if home and home != "~":
        text = text.replace(home, "~")
    return _HOME_PATH_RE.sub("~", text)


def _sanitize(value: str) -> str:
    """Scrub secret shapes + redact home paths on the UNTRUNCATED source.
    Must run before any length cap: truncating first can slice a credential
    at the cap boundary so its prefix no longer matches the scrub regexes
    and leaks."""
    from dontpanic_orchestrate.state_projection import scrub_secrets

    return _redact_home(scrub_secrets(value) or "")


def _format_content(event: NotifyEvent, rendered: Any | None = None) -> str:
    """Summary-only projection: header + one short detail line + evidence
    pointer. Never the raw event body beyond its first line, never a full
    transcript. Each component is scrubbed + home-redacted BEFORE its
    length cap; the total is hard-capped last (safe: caps then operate on
    already-sanitized text)."""
    header_parts = [f"[{event.plan_id}]"]
    if event.feature_id:
        header_parts.append(str(event.feature_id))
    header_parts.append(str(event.kind))
    lines = [_sanitize(" ".join(header_parts))]

    title = getattr(rendered, "title", None) if rendered is not None else None
    detail = getattr(rendered, "detail", None) if rendered is not None else None
    if title:
        lines.append(_truncate(_sanitize(str(title).strip()), _DETAIL_LIMIT))
    elif event.body.strip():
        # No rendered copy — summarize as the body's FIRST line only.
        first_line = event.body.strip().splitlines()[0]
        lines.append(_truncate(_sanitize(first_line), _DETAIL_LIMIT))
    if detail:
        lines.append(_truncate(_sanitize(str(detail).strip()), _DETAIL_LIMIT))
    evidence = getattr(rendered, "evidence_uri", None) or event.evidence_uri
    if evidence:
        lines.append(f"evidence: {_sanitize(str(evidence))}")

    return _truncate("\n".join(lines), _CONTENT_TOTAL_LIMIT)


def is_available() -> bool:
    """True iff the sink is not disabled, buzz.json is usable, and the
    ``buzz`` CLI is resolvable. Cheap — no subprocess, no key resolution."""
    if _is_sink_disabled():
        return False
    if _load_config() is None:
        return False
    return _resolve_cli() is not None


def notify(event: NotifyEvent, rendered: Any | None = None) -> bool:
    """Post a single Buzz channel message for ``event`` via the ``buzz`` CLI.
    Returns True on exit code 0, False on every other outcome. Never raises.

    Failure modes that all return False (with at most one warn-once line):
      - Sink disabled (either env knob).
      - buzz.json missing / invalid / incomplete (unconfigured is the
        NORMAL state — Buzz is strongly recommended, never required).
      - the ``buzz`` binary not installed.
      - reporter_key_ref does not resolve to key material.
      - subprocess error / timeout / nonzero exit.
    """
    if _is_sink_disabled():
        return False
    config = _load_config()
    if config is None:
        _warn_once("no-config", "buzz.json not configured; sink silent.")
        return False
    cli = _resolve_cli()
    if cli is None:
        _warn_once("no-cli", "buzz CLI not found on PATH; sink silent.")
        return False
    key = _resolve_reporter_key(config.reporter_key_ref)
    if key is None:
        # Never echo the ref value — it may name a file path.
        _warn_once(
            "no-key",
            "reporter key reference did not resolve; sink silent.",
        )
        return False

    content = _format_content(event, rendered=rendered)
    # Official Buzz CLI contract: `buzz messages send --channel <uuid>
    # --content -` reads the body from stdin; relay (community authority)
    # and signing key travel via the subprocess environment.
    argv = [
        cli,
        "messages",
        "send",
        "--channel",
        config.channel,
        "--content",
        "-",
    ]
    env = dict(os.environ)
    env[_RELAY_ENV_FOR_CLI] = config.relay_url
    env[_KEY_ENV_FOR_CLI] = key
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, shell=False
            argv,
            input=content,
            text=True,
            capture_output=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        _warn_once(
            "subprocess-error",
            f"buzz CLI invocation failed: {type(exc).__name__}; sink silent for this event.",
        )
        return False
    if proc.returncode != 0:
        # Exit code only — stderr may echo argv/config values.
        _warn_once(
            "nonzero-exit",
            f"buzz CLI exited {proc.returncode}; sink silent for this event.",
        )
        return False
    return True


__all__ = ["BuzzConfig", "EXPECTED_KEYS", "is_available", "notify", "reset_warning_cache"]
