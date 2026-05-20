"""Absolute-path redactor for showcase artifacts (Plan 2026-05-19-005 F001).

Strips absolute paths from generated JSON + HTML before they're written
to ``docs/showcase/``. Two-stage:

  1. Scrub the target repo's absolute root → ``.`` so paths inside the
     target's surface render as repo-relative (the form the architecture
     map already uses for DontPanic itself).
  2. Defense-in-depth: scrub *any* surviving ``/Users/<user>/`` segment
     (could leak via module docstrings, schema descriptions, etc.) to
     ``<redacted>``.

Post-write validation re-scans the rendered content and raises
:class:`RedactorError` if ``/Users/`` still appears. This mirrors the
Plan 4 F002 D004 escape pattern — fail loud rather than commit a leak.
"""

from __future__ import annotations

import re
from pathlib import Path


class RedactorError(Exception):
    """Raised when post-redaction content still contains an absolute
    path. Operator-actionable: the message names the surviving
    ``/Users/<user>/...`` substring and the upstream artifact so the
    operator can patch the generator at the source instead of the
    redactor's tail."""


# ``/Users/<user>/<rest>`` — macOS absolute-home prefix. We do not anchor
# on a specific username; the operator's USER may differ from CI / future
# contributors, and the goal is to catch any leak regardless of who ran
# the regen.
_USER_HOME_RE = re.compile(r"/Users/[^/\s\"']+/[^\s\"']*")


def redact(content: str, *, repo_root: Path, repo_key: str | None = None) -> str:
    """Return ``content`` with absolute paths scrubbed.

    ``repo_root`` is the absolute path of the target repo whose artifact
    is being redacted. References to that path become ``.`` (repo-
    relative root). Surviving ``/Users/<user>/...`` substrings (paths
    from outside ``repo_root`` — e.g. a dependency's docstring) collapse
    to ``<redacted>``.

    ``repo_key`` is the optional target identifier used in the
    :class:`RedactorError` message so the operator can trace which
    artifact failed validation.
    """
    repo_root_str = str(repo_root.resolve())
    # Stage 1: scrub the target repo's own absolute root.
    # Replace prefix-with-trailing-slash form first ("/repo/sub" → "./sub")
    # then the bare-root form ("/repo" → ".") so we don't double-replace.
    out = content.replace(repo_root_str + "/", "./").replace(repo_root_str, ".")
    # Stage 2: defense-in-depth — anything else under /Users/ is a leak
    # we don't have semantic context for, so collapse the whole segment.
    out = _USER_HOME_RE.sub("<redacted>", out)
    return out


def validate(content: str, *, repo_key: str | None = None, artifact: str | None = None) -> None:
    """Raise :class:`RedactorError` if ``/Users/`` survives in ``content``.

    Called after :func:`redact` and before atomic write so a regression
    in the redactor (or a new leak shape we haven't taught it about)
    fails the regen instead of polluting ``docs/showcase/``.
    """
    if "/Users/" not in content:
        return
    # Surface a tractable excerpt so the operator can locate the leak
    # without grepping the whole artifact.
    idx = content.find("/Users/")
    start = max(0, idx - 40)
    end = min(len(content), idx + 80)
    excerpt = content[start:end]
    where = f" in {repo_key}-{artifact}" if repo_key and artifact else ""
    raise RedactorError(
        f"absolute path leaked past redactor{where}: …{excerpt!r}… "
        "Patch the generator (or extend redactor._USER_HOME_RE) so the "
        "raw path never reaches docs/showcase/."
    )


def redact_and_validate(
    content: str,
    *,
    repo_root: Path,
    repo_key: str | None = None,
    artifact: str | None = None,
) -> str:
    """Convenience: :func:`redact` followed by :func:`validate`. Returns
    the redacted, validated string ready for atomic write."""
    redacted = redact(content, repo_root=repo_root, repo_key=repo_key)
    validate(redacted, repo_key=repo_key, artifact=artifact)
    return redacted
