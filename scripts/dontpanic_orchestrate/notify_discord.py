"""Plan 2026-05-01-002 F001 — Discord webhook notification sink.

Mirrors the public shape of :mod:`notify` (terminal-notifier sink) so the
:mod:`notify_event` dispatcher fans events to both. All failure modes return
``False`` and emit a single warn-once stderr line; this sink NEVER raises so
callers don't have to guard.

Webhook URL resolution order:
  1. ``DONTPANIC_DISCORD_WEBHOOK_URL`` env (modern brand)
  2. ``JARVIS_DISCORD_WEBHOOK_URL`` env (legacy compatibility)
  3. ``$DONTPANIC_HOME/discord.json`` ``webhook_url`` field
  4. ``$JARVIS_HOME/discord.json`` ``webhook_url`` field (legacy fallback)
  5. ``None`` → ``notify`` returns False without network attempt.

Disable knobs (any one silences this sink):
  - ``DONTPANIC_DISCORD_DISABLE=1`` — sink-specific, modern.
  - ``JARVIS_DISCORD_DISABLE=1`` — sink-specific, legacy.
  - ``JARVIS_NOTIFY_DISABLE=1`` — global kill-switch, silences ALL sinks
    (shared with :mod:`notify`'s ``DISABLE_ENV``).

Payload v1 (intentionally minimal):
  ``{"username": "Jarvis", "content": <markdown body>,
     "allowed_mentions": {"parse": []}}``
``allowed_mentions.parse`` is ALWAYS empty in v1 — Discord renders no
@mentions even if ``event.body`` contains literal ``<@USER_ID>`` or
``@here``. Per D003 future mention support is deferred.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Final, TYPE_CHECKING

if TYPE_CHECKING:
    from dontpanic_orchestrate.notify_event import NotifyEvent

from dontpanic_orchestrate import global_config

# Modern + legacy env var names — both honored, modern wins on conflict.
_WEBHOOK_ENV_MODERN: Final[str] = "DONTPANIC_DISCORD_WEBHOOK_URL"
_WEBHOOK_ENV_LEGACY: Final[str] = "JARVIS_DISCORD_WEBHOOK_URL"
_DISABLE_ENV_MODERN: Final[str] = "DONTPANIC_DISCORD_DISABLE"
_DISABLE_ENV_LEGACY: Final[str] = "JARVIS_DISCORD_DISABLE"
# Shared global kill-switch — when set, ALL sinks (terminal + discord) are
# silenced. Mirrors :mod:`notify.DISABLE_ENV` so a single env flag covers
# both. We import the constant rather than redefine to keep it canonical.
_GLOBAL_DISABLE_ENV: Final[str] = "JARVIS_NOTIFY_DISABLE"

_CONFIG_FILENAME: Final[str] = "discord.json"
_LEGACY_HOME_DIRNAME: Final[str] = ".jarvis"

_NETWORK_TIMEOUT_SECONDS: Final[float] = 5.0
_USERNAME: Final[str] = "Jarvis"

# Track whether we've already warned about a given failure cause so we don't
# spam stderr per dispatch. Process-local — reset_warning_cache() exposed for
# tests.
_warned: set[str] = set()


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _is_globally_disabled() -> bool:
    return _truthy(os.environ.get(_GLOBAL_DISABLE_ENV, ""))


def _is_sink_disabled() -> bool:
    return (
        _truthy(os.environ.get(_DISABLE_ENV_MODERN, ""))
        or _truthy(os.environ.get(_DISABLE_ENV_LEGACY, ""))
        or _is_globally_disabled()
    )


def _resolve_webhook_url() -> str | None:
    """Resolve the webhook URL per documented precedence. Returns the raw
    string (validation happens later in :func:`_is_well_formed`)."""
    for env in (_WEBHOOK_ENV_MODERN, _WEBHOOK_ENV_LEGACY):
        value = os.environ.get(env, "").strip()
        if value:
            return value
    # Modern config dir (honors $DONTPANIC_HOME / $JARVIS_HOME via global_config).
    modern_path = global_config.dontpanic_home() / _CONFIG_FILENAME
    legacy_root = os.environ.get("JARVIS_HOME")
    legacy_paths: list[Path] = []
    if legacy_root:
        legacy_paths.append(Path(legacy_root) / _CONFIG_FILENAME)
    # Conventional ~/.jarvis/discord.json fallback when JARVIS_HOME unset.
    legacy_paths.append(Path.home() / _LEGACY_HOME_DIRNAME / _CONFIG_FILENAME)
    for path in (modern_path, *legacy_paths):
        try:
            if path.is_file():
                data = json.loads(path.read_text())
                url = (data.get("webhook_url") or "").strip() if isinstance(data, dict) else ""
                if url:
                    return url
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _is_well_formed(url: str) -> bool:
    """URL shape validator that runs BEFORE any network call. Returns False
    for empty / non-http(s) / whitespace-bearing / netloc-less URLs."""
    if not url or any(c.isspace() for c in url):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    return True


def _warn_once(key: str, message: str) -> None:
    if key in _warned:
        return
    _warned.add(key)
    print(f"[notify_discord] {message}", file=sys.stderr)


def reset_warning_cache() -> None:
    """Clear the per-process warn-once cache. Test helper."""
    _warned.clear()


def is_available() -> bool:
    """True iff a valid webhook URL is resolvable AND the sink isn't disabled.
    Cheap — does no network. Safe to call before every dispatch."""
    if _is_sink_disabled():
        return False
    url = _resolve_webhook_url()
    if url is None:
        return False
    return _is_well_formed(url)


def notify(event: "NotifyEvent") -> bool:
    """Post a single Discord webhook for ``event``. Returns True on 2xx
    response, False on every other outcome. Never raises.

    Failure modes that all return False (with at most one warn-once line):
      - Sink disabled (any of three env knobs).
      - Webhook URL not configured.
      - Webhook URL malformed (no network call attempted).
      - Network error / timeout.
      - Non-2xx HTTP response from Discord.
    """
    if _is_sink_disabled():
        return False
    url = _resolve_webhook_url()
    if url is None:
        _warn_once("no-url", "no webhook URL configured; sink silent.")
        return False
    if not _is_well_formed(url):
        _warn_once(
            "malformed-url",
            f"webhook URL is not a valid http(s) URL; sink silent.",
        )
        return False

    payload = {
        "username": _USERNAME,
        "content": _format_content(event),
        "allowed_mentions": {"parse": []},
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — scheme guarded above.
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_NETWORK_TIMEOUT_SECONDS) as resp:  # noqa: S310
            status = getattr(resp, "status", None) or resp.getcode()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        _warn_once(
            "network-error",
            f"webhook POST failed: {type(exc).__name__}; sink silent for this event.",
        )
        return False
    return 200 <= int(status) < 300


def _format_content(event: "NotifyEvent") -> str:
    """Render the markdown content body for a Discord post.

    Header + body + optional action link. Discord posts have a 2000-char
    content limit; we truncate well below that so embeds + future fields
    have room.
    """
    header_parts = [f"**[{event.plan_id}]**"]
    if event.feature_id:
        header_parts.append(f"`{event.feature_id}`")
    header_parts.append(f"_{event.kind}_")
    header = " ".join(header_parts)
    body = event.body.strip() if event.body else ""
    parts = [header]
    if body:
        parts.append(body)
    if event.action_link:
        parts.append(f"→ `{event.action_link}`")
    out = "\n".join(parts)
    if len(out) > 1800:
        out = out[:1797] + "..."
    return out


__all__ = ["is_available", "notify", "reset_warning_cache"]
