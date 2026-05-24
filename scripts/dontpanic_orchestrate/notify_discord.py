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
from typing import Any, Final, TYPE_CHECKING

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
_USERNAME: Final[str] = "DontPanic"

# Plan 2026-05-24-004 F003 (D022): embed colors are inline hex literals from
# the IA copy map § 3 four-band taxonomy. NOT sourced from a dp-tokens.css
# file (no such asset exists in this repo). Update both this constant and
# the copy map's band-color section in the same PR.
_EMBED_COLOR_HEALTHY: Final[int] = 0x3DD68C  # ready band — green
_EMBED_COLOR_ACTION: Final[int] = 0xF5A623  # needs_action / advisory — amber
_EMBED_COLOR_BLOCKED: Final[int] = 0xF25555  # needs_action when blocking — red
_EMBED_COLOR_PENDING: Final[int] = 0x7E8BA6  # info band — slate

# Discord payload limits — title 256, description 4096, total embed ~6000,
# but the legacy content body limit is 2000. We cap individual fields well
# below to leave room for the exact_command code-fence + footer.
_DISCORD_TITLE_LIMIT: Final[int] = 240
_DISCORD_DESCRIPTION_LIMIT: Final[int] = 1600
_DISCORD_FIELD_VALUE_LIMIT: Final[int] = 1000
_DISCORD_PAYLOAD_TOTAL_LIMIT: Final[int] = 2000

# Discord's edge (Cloudflare) returns HTTP 403 + error 1010 to requests
# carrying the default ``Python-urllib/X.Y`` User-Agent. Discord's API
# docs specifically allow webhook clients to set any descriptive UA;
# the webhook spec recommends ``ClientName/Version (URL)``. Setting a
# real UA is the documented fix for the 1010 block.
_USER_AGENT: Final[str] = (
    "DontPanic-Webhook/1.0 (+https://github.com/Silex-Research/DontPanic)"
)

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


def notify(event: "NotifyEvent", rendered: Any | None = None) -> bool:
    """Post a single Discord webhook for ``event``. Returns True on 2xx
    response, False on every other outcome. Never raises.

    F003 audit finding (i1) addendum: callers that already produced a
    ``RenderedEvent`` (the F003 dispatch flow does) pass it here so the
    sink does NOT re-render. ``rendered=None`` keeps backward compat with
    legacy direct callers that bypass dispatch — :func:`_build_payload`
    re-renders in that case.

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

    payload = _build_payload(event, rendered=rendered)
    # F003 audit i0 finding #3: serialize with ensure_ascii=False so the
    # bytes sent over the wire match what _enforce_payload_total_limit
    # measured against the same JSON shape. ASCII-escaping inflates the
    # length and previously caused a measured-1237-char body to balloon to
    # 5232 chars on send (well past Discord's 2000-char limit).
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — scheme guarded above.
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        },
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
    """Render the markdown content body for a Discord post (legacy fallback).

    Used when no RenderedEvent is available (renderer returns None) — e.g.
    for direct legacy callers that bypass the F003 dispatch flow.
    """
    header_parts = [f"**[{event.plan_id}]**"]
    if event.feature_id:
        header_parts.append(f"`{event.feature_id}`")
    # Use backticks for the kind — underscores would be eaten by Discord's
    # markdown italic parser (e.g. `_volley_start_` renders as 'volleystart').
    header_parts.append(f"`{event.kind}`")
    header = " ".join(header_parts)
    body = event.body.strip() if event.body else ""
    parts = [header]
    if body:
        parts.append(body)
    if event.action_link:
        parts.append(f"→ `{event.action_link}`")
    out = "\n".join(parts)
    if len(out) > _DISCORD_PAYLOAD_TOTAL_LIMIT - 200:
        out = out[: _DISCORD_PAYLOAD_TOTAL_LIMIT - 203] + "..."
    # Plan 2026-05-24-004 F004: substitute-mode sanitization on the legacy
    # content path. Imported lazily to avoid pulling state_projection at
    # module load time.
    from dontpanic_orchestrate.state_projection import scrub_secrets

    return scrub_secrets(out) or ""


def _band_to_color(band: str | None) -> int:
    """Map a RenderedEvent.band into the IA copy map § 3 four-band color.

    Inline hex literals per D022 — NOT sourced from a dp-tokens.css file.
    Unknown bands fall back to the pending/info slate so the embed always
    renders with a credible color.
    """
    if band == "ready":
        return _EMBED_COLOR_HEALTHY
    if band == "needs_action":
        return _EMBED_COLOR_BLOCKED
    if band == "advisory":
        return _EMBED_COLOR_ACTION
    return _EMBED_COLOR_PENDING


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def _build_payload(event: "NotifyEvent", rendered: Any | None = None) -> dict:
    """Construct the Discord webhook payload.

    Plan 2026-05-24-004 F003 (D022): when the F003 renderer produces a
    RenderedEvent, emit a rich Discord embed with title/description/fields/
    footer/color taxonomy. When the renderer returns None (kind has no
    translation entry or disposition is inbox_only/audit_only — the latter
    shouldn't actually reach this sink under normal flow), fall back to the
    legacy single-content path so dispatch_event callers without a
    RenderedEvent still get a useful post.

    F003 audit finding (i1) addendum: dispatch_event already invokes
    ``event_copy.render(event)`` and passes the result via ``rendered=`` so
    the sink does NOT re-render. Direct callers that omit the kwarg fall
    back to the in-sink render path (kept for backward compat).

    Per the same decision: respect the Discord 2000-char total payload
    limit by truncating the description well below; the exact_command is
    NEVER truncated (operators copy-paste it).
    """
    if rendered is None:
        try:
            from dontpanic_orchestrate import event_copy

            rendered = event_copy.render(event)
        except Exception:  # noqa: BLE001 — sink must never raise
            rendered = None

    if rendered is None:
        return {
            "username": _USERNAME,
            "content": _format_content(event),
            "allowed_mentions": {"parse": []},
        }

    # Plan 2026-05-24-004 F004 (D011 + D020): substitute-mode sanitization
    # for the live Discord embed path. Every operator-visible string is run
    # through scrub_secrets before truncation / field-assembly so a
    # secret-shaped substring renders as [REDACTED] without raising. The
    # raise-mode boundary is the sidecar write path.
    from dontpanic_orchestrate.state_projection import scrub_secrets

    def _scrub(s: str | None) -> str | None:
        return scrub_secrets(s) if isinstance(s, str) else s

    title = _truncate(_scrub(rendered.title) or "", _DISCORD_TITLE_LIMIT)
    description = _truncate(_scrub(rendered.detail) or "", _DISCORD_DESCRIPTION_LIMIT)
    fields: list[dict] = []
    scrubbed_command = _scrub(rendered.exact_command)
    if scrubbed_command:
        # D022 + plan acceptance #6: never truncate exact_command. If it's
        # too long for one field, we still emit it whole and let Discord
        # complain — this is more honest than rendering a broken copy-paste.
        fields.append(
            {
                "name": "Run",
                "value": f"```\n{scrubbed_command}\n```",
                "inline": False,
            }
        )
    footer_parts: list[str] = []
    scrubbed_evidence = _scrub(rendered.evidence_uri)
    if scrubbed_evidence:
        footer_parts.append(f"Evidence: {scrubbed_evidence}")
    feature_id = getattr(event, "feature_id", None)
    if feature_id:
        footer_parts.append(f"feature={feature_id}")
    footer_parts.append(f"plan={event.plan_id}")
    footer_text = _truncate(
        _scrub(" · ".join(footer_parts)) or "", _DISCORD_FIELD_VALUE_LIMIT
    )

    embed: dict = {
        "title": title,
        "color": _band_to_color(rendered.band),
        "footer": {"text": footer_text},
    }
    if description:
        embed["description"] = description
    if fields:
        embed["fields"] = fields

    payload: dict = {
        "username": _USERNAME,
        "embeds": [embed],
        "allowed_mentions": {"parse": []},
    }

    # D022 + plan acceptance #6 (F003-i0 audit finding #4): cap the *total*
    # serialized payload at the Discord limit. Per-field truncation alone is
    # not enough — title + description + footer + fields can compose past
    # 2000 chars. Trim the description first, then the footer body. The
    # exact_command field is NEVER truncated (operators copy-paste it).
    _enforce_payload_total_limit(payload, embed)
    return payload


def _enforce_payload_total_limit(payload: dict, embed: dict) -> None:
    """Mutate ``embed`` so ``json.dumps(payload)`` fits the Discord limit.

    Trims description first, then footer text, in shrinking steps until the
    total fits. Exact-command fields are deliberately left intact so the
    rendered copy-paste target survives even at the cost of dropping the
    description entirely. Final fallback collapses both description and
    footer when even an empty description+footer can't fit (extreme case;
    we still ship the embed since the title + exact_command alone are the
    irreducible operator-actionable copy).
    """
    limit = _DISCORD_PAYLOAD_TOTAL_LIMIT

    def total_len() -> int:
        return len(json.dumps(payload, ensure_ascii=False))

    # Fast path — most embeds fit on the first try.
    if total_len() <= limit:
        return

    # Step 1: shrink description in halves until either fits or empty.
    description = embed.get("description", "")
    while description and total_len() > limit:
        # Halve, leaving an ellipsis so the truncation is visible.
        new_len = max(0, len(description) // 2 - 3)
        description = description[:new_len] + "..." if new_len > 0 else ""
        embed["description"] = description
        if not description:
            embed.pop("description", None)
            break
    if total_len() <= limit:
        return

    # Step 2: shrink footer text in halves.
    footer = embed.get("footer", {})
    footer_text = footer.get("text", "")
    while footer_text and total_len() > limit:
        new_len = max(0, len(footer_text) // 2 - 3)
        footer_text = footer_text[:new_len] + "..." if new_len > 0 else ""
        footer["text"] = footer_text
        embed["footer"] = footer
        if not footer_text:
            embed["footer"] = {"text": ""}
            break
    # Step 3 (degenerate): the title + exact_command alone may still exceed
    # the limit. We choose to ship anyway — Discord will reject and our
    # warn-once will fire — rather than silently dropping the exact_command,
    # which is the operator's whole reason for getting the ping.


__all__ = ["is_available", "notify", "reset_warning_cache"]
