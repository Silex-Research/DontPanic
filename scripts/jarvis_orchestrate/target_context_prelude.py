"""Canonical target-context prose prelude shape (F023 EC5 platform fix, F001).

This module is the design + helpers half of the target-context platform fix.
Behaviour change ships in F002 (audit_writer write-side normalization) and
F003 (auditor severity classifier). Here we ship only:

    * `PRELUDE_TEMPLATE`  — the byte-exact canonical prelude shape
    * `render_prelude`    — PURE renderer (struct dict -> prelude string)
    * `resolve_repo`      — non-pure helper: D002 cwd-fallback shim
    * `validate_target_context` — pure validator (raises on the four invalid
      shapes that downstream stages must reject)
    * `parse_prelude_block` — pure parser (summary string -> field dict OR
      None when no canonical prelude header is present)
    * `TargetContextError` — subclass of `ValueError` carrying a
      `'target_context invalid: <reason>'` message format

Key decisions (see plan docs/plans/2026-05-01-005-feat-target-context-platform-fix):

    D001  Canonical prelude shape — markdown block, four fixed fields
          (Repo, Env, Project, Command), capitalized labels, fixed order,
          trailing blank line. All four lines are ALWAYS rendered. Project
          handling: None/null/''/`'none'` -> `- Project: (none)`. Command
          shows the COUNT of commands_run plus a pointer to the structured
          field (no list re-rendering).

    D002  Repo precedence — struct value first, then `git rev-parse
          --show-toplevel` basename via os.getcwd() (read-only transitional
          shim), then hard-fail with TargetContextError. The cwd-fallback
          is documented here as a transitional shim — a future
          conventions-bump plan that adds `repo` as a required field in
          target_context will let the shim be removed.

Architecture (purity boundary, addresses i0 auditor F3):

    `render_prelude(tc)` is PURE — no I/O, no logging, no global state.
    Output is fully determined by the input dict. The 100-call
    determinism assertion is a contract, not a happy-path note.
    `render_prelude` raises `TargetContextError` if the struct lacks a
    `repo` value — it does NOT fall back to subprocess.

    `resolve_repo(tc)` is the non-pure half — it implements the D002
    cwd-fallback shim by shelling out to `git rev-parse --show-toplevel`.
    F002's audit_writer composes the two:

        repo = resolve_repo(tc)
        prelude = render_prelude({**tc, "repo": repo})

    This split keeps the renderer trivially testable and side-effect-free
    while still meeting D002's repo-precedence contract for callers that
    don't yet have a `repo` field upstream.

This module is consumed by F002 (audit_writer.persist) and F003
(ec5_classifier.classify_ec5_severity); F001 itself ships only this
module + its tests + the seven regression fixtures under
`docs/plans/2026-05-01-005-feat-target-context-platform-fix/evidence/f001/fixtures/`.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

# format: heading + 4 field lines (Repo, Env, Project, Command) + trailing blank
PRELUDE_TEMPLATE: str = (
    "## Target context\n"
    "- Repo: {repo}\n"
    "- Env: {env}\n"
    "- Project: {project}\n"
    "- Command: {command_count} (see structured target_context.commands_run)\n"
    "\n"
)

_PRELUDE_HEADER = "## Target context\n"
_PROJECT_NONE_SENTINELS = {"", "none", "(none)"}
_COMMAND_VALUE_RE = re.compile(
    r"^(?P<count>\d+) \(see structured target_context\.commands_run\)$"
)


class TargetContextError(ValueError):
    """Raised when target_context fails platform validation.

    Message format is `'target_context invalid: <reason>'`. F002's
    audit_writer wraps this with audit_id + plan_id context before
    re-raising; F003's classifier catches it as the i1 signal.
    """


def resolve_repo(target_context: dict[str, Any]) -> str:
    """Apply D002 repo precedence: struct -> cwd basename -> hard-fail.

    NOT a pure function — calls `git rev-parse --show-toplevel` from
    `os.getcwd()` when the struct is missing a `repo` value. This is the
    transitional shim documented in D002. F002's audit_writer composes
    this with `render_prelude`:

        repo = resolve_repo(tc)
        prelude = render_prelude({**tc, "repo": repo})

    Once a future conventions-bump plan promotes `repo` to a required
    field in target_context, this helper goes away and callers pass the
    struct directly to `render_prelude`.
    """

    if not isinstance(target_context, dict):
        raise TargetContextError(
            "target_context invalid: not a dict for resolve_repo"
        )

    struct_repo = target_context.get("repo")
    if isinstance(struct_repo, str) and struct_repo.strip():
        return struct_repo.strip()

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        raise TargetContextError(
            "target_context invalid: repo missing and cwd git fallback failed"
        ) from None

    toplevel = completed.stdout.strip()
    if not toplevel:
        raise TargetContextError(
            "target_context invalid: repo missing and cwd git fallback returned empty"
        )
    return Path(toplevel).name


def _render_project(value: Any) -> str:
    """D001 project rendering — None / null / '' / 'none' -> '(none)'."""

    if value is None:
        return "(none)"
    if isinstance(value, str) and value.strip().lower() in _PROJECT_NONE_SENTINELS:
        return "(none)"
    return str(value)


def render_prelude(target_context: dict[str, Any]) -> str:
    """Render the canonical D001 prelude block from a target_context dict.

    PURE: no I/O, no logging, no clock, no global state. Output is fully
    determined by the input dict. Contract: 100 calls with the same input
    return identical strings (asserted in tests).

    Required keys:
      - `repo`: non-empty string. Callers needing the D002 cwd fallback
        pre-resolve via `resolve_repo()` and pass `{**tc, "repo": resolved}`.
      - `env`: non-empty string.
    Optional keys:
      - `project`: None / null / '' / 'none' -> '(none)'; any other value
        rendered verbatim.
      - `commands_run`: list-like; only its length is rendered.

    Raises `TargetContextError` if `target_context` is None / not a dict
    / missing repo / missing env. The renderer never shells out — the
    cwd fallback lives in `resolve_repo()` and is composed by the caller.

    Returns a string ending with `\\n\\n` so that prepending it to a
    summary leaves a blank line between the prelude and the rest.
    """

    if target_context is None:
        raise TargetContextError("target_context invalid: missing")
    if not isinstance(target_context, dict):
        raise TargetContextError(
            f"target_context invalid: not a dict (got {type(target_context).__name__})"
        )

    repo = target_context.get("repo")
    if not (isinstance(repo, str) and repo.strip()):
        raise TargetContextError(
            "target_context invalid: repo missing for prelude render"
            " (call resolve_repo(tc) first for D002 cwd-fallback)"
        )

    env = target_context.get("env")
    if env is None or (isinstance(env, str) and env.strip() == ""):
        raise TargetContextError("target_context invalid: env missing for prelude render")
    env_str = env.strip() if isinstance(env, str) else str(env)

    project_str = _render_project(target_context.get("project"))

    commands_run = target_context.get("commands_run") or []
    command_count = len(commands_run)

    return PRELUDE_TEMPLATE.format(
        repo=repo.strip(),
        env=env_str,
        project=project_str,
        command_count=command_count,
    )


def validate_target_context(tc: dict[str, Any] | None) -> None:
    """Raise TargetContextError on any of the four invalid struct shapes.

    Invalid shapes (all assume the envelope intends to declare target
    accountability — i.e. a non-empty commands_run list):

      1. tc is None / missing entirely
      2. env is None or empty string when commands_run is non-empty
      3. project key absent OR project is empty string when commands_run
         is non-empty (project=None is VALID — host-local sentinel)
      4. commands_run is non-empty AND env+project both fail their checks
         (covered transitively by 2 + 3)

    Returns None on valid input. project=None is explicitly valid for
    host-local plans (matches F023 plan.md `target_project: none`
    convention; render_prelude emits `- Project: (none)` for it).
    """

    if tc is None:
        raise TargetContextError("target_context invalid: missing")
    if not isinstance(tc, dict):
        raise TargetContextError(
            f"target_context invalid: not a dict (got {type(tc).__name__})"
        )

    commands_run = tc.get("commands_run") or []
    if not commands_run:
        return  # nothing was claimed — nothing to validate

    env = tc.get("env")
    if env is None or (isinstance(env, str) and env.strip() == ""):
        raise TargetContextError(
            "target_context invalid: env empty when commands_run non-empty"
        )

    if "project" not in tc:
        raise TargetContextError(
            "target_context invalid: project key absent when commands_run non-empty"
        )
    project_value = tc.get("project")
    if isinstance(project_value, str) and project_value.strip() == "":
        raise TargetContextError(
            "target_context invalid: project empty when commands_run non-empty"
        )


def parse_prelude_block(summary: str | None) -> dict[str, Any] | None:
    """Parse the canonical prelude block off the front of a summary.

    Returns `{repo, env, project, command_count}` when the summary's
    leading content (after stripping leading whitespace) starts with the
    canonical `## Target context\\n` header AND the four field lines
    that follow are well-formed AND a blank separator line follows
    `Command`. Returns None when no canonical header is detectable.
    Raises TargetContextError ONLY when a canonical header is present
    but the body is malformed (wrong field order, mistyped labels,
    missing line, malformed Command count, missing trailing blank).

    The four parsed values are returned verbatim — no validation against
    a separate struct. F003's classifier compares the parsed dict to the
    struct rendering for the value-mismatch (i1) detection.
    """

    if not summary:
        return None

    lstripped = summary.lstrip()
    if not lstripped.startswith(_PRELUDE_HEADER):
        return None

    body = lstripped[len(_PRELUDE_HEADER):]
    lines = body.split("\n")
    # Require 4 field lines + trailing blank separator line (5 lines minimum
    # after splitting on \n; the blank line between Command and body shows
    # up as an empty string in lines[4]).
    if len(lines) < 5:
        raise TargetContextError(
            "prelude shape invalid: expected 4 field lines + trailing blank, "
            f"got {len(lines)} line(s) after header"
        )

    expected_labels = ("Repo", "Env", "Project", "Command")
    parsed: dict[str, Any] = {}
    for index, label in enumerate(expected_labels):
        line = lines[index]
        prefix = f"- {label}: "
        if not line.startswith(prefix):
            raise TargetContextError(
                f"prelude shape invalid: line {index + 1} expected prefix {prefix!r}, "
                f"got {line!r}"
            )
        value = line[len(prefix):]
        if label == "Command":
            match = _COMMAND_VALUE_RE.match(value)
            if match is None:
                raise TargetContextError(
                    f"prelude shape invalid: Command line malformed, got {value!r}"
                )
            parsed["command_count"] = int(match.group("count"))
        else:
            parsed[label.lower()] = value

    # D001 mandates a trailing blank line after Command. Without it we'd
    # accept a look-alike where prose runs straight into the prelude
    # (i0 auditor F2 regression).
    separator = lines[4]
    if separator != "":
        raise TargetContextError(
            "prelude shape invalid: expected blank line after Command, "
            f"got {separator!r}"
        )

    return parsed


__all__ = [
    "PRELUDE_TEMPLATE",
    "TargetContextError",
    "parse_prelude_block",
    "render_prelude",
    "resolve_repo",
    "validate_target_context",
]
