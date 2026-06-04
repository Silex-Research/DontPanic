"""Plan 2026-05-30-001 F003 — repo onboarding managed-block writer.

``dontpanic projects add NAME PATH --onboard`` scaffolds a repository so any
agent that opens it understands DontPanic from a single generated brief:

  - ``<repo>/.dontpanic/dontpanic.json`` is created with explicit defaults
    (schema-compatible with :class:`project_config.ProjectConfig`) rather than
    a bare ``{}`` — operators see exactly which fields exist.
  - ``<repo>/AGENTS.md`` carries a *marked, generated* DontPanic block: the
    operating brief from :mod:`agent_brief`. The block is delimited by stable
    HTML-comment markers that embed the generator version and a content hash.
  - ``<repo>/CLAUDE.md`` carries a marked pointer block that directs CLAUDE-based
    agents to AGENTS.md.

The load-bearing invariant: **content outside the markers is never touched.**
A repo's existing AGENTS.md instructions stay byte-for-byte intact; onboarding
only ever creates a file, appends a managed block, or replaces an existing
managed block in place. Re-running onboarding compares the stored hash/version
in the markers against a freshly rendered block: a stale block is rewritten, a
fresh one is left exactly as-is (so re-onboarding is a no-op once current).

Everything here is pure planning + rendering plus one explicit apply step, so
the dry-run path (``--onboard --dry-run``) reuses the same plan and simply
declines to write — the preview can never drift from the real writes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from dontpanic_orchestrate import agent_brief
from dontpanic_orchestrate import project_config as pc

ONBOARDING_GENERATOR_VERSION = "1.0"
"""Version of the managed-block layout (markers + surrounding boilerplate),
independent of :data:`agent_brief.GENERATOR_VERSION` (the brief body) and the
DontPanic runtime version. A bump here re-stamps every managed block on the next
onboarding run even when the brief body is unchanged."""

AGENTS_FILENAME = "AGENTS.md"
CLAUDE_FILENAME = "CLAUDE.md"
LOWER_CLAUDE_FILENAME = ".claude.md"

# Logical names embedded in the BEGIN marker so a file could in principle carry
# more than one DontPanic-managed block without them colliding.
BLOCK_AGENTS = "agents-brief"
BLOCK_CLAUDE = "claude-pointer"

# Stable markers. HTML comments render invisibly in Markdown viewers, so the
# managed block reads as ordinary prose to a human while staying machine-locatable.
_MARK_BEGIN_PREFIX = "<!-- DONTPANIC:BEGIN"
_MARK_END = "<!-- DONTPANIC:END -->"

_BLOCK_RE = re.compile(
    r"<!-- DONTPANIC:BEGIN name=(?P<name>[\w-]+) "
    r"generator=(?P<generator>[\w.]+) hash=(?P<hash>[0-9a-f]+) -->"
    r"(?P<body>.*?)"
    r"<!-- DONTPANIC:END -->",
    re.DOTALL,
)

# Byte-domain twin of ``_BLOCK_RE``. Existing repo files are read and written as
# raw bytes (never decoded) so content outside the markers is preserved
# byte-for-byte — CRLF line endings, a missing trailing newline, BOMs, and even
# non-UTF-8 prose all survive untouched. The markers themselves are pure ASCII,
# so locating them in a byte string is unambiguous regardless of the surrounding
# encoding.
_BLOCK_RE_BYTES = re.compile(
    rb"<!-- DONTPANIC:BEGIN name=(?P<name>[\w-]+) "
    rb"generator=(?P<generator>[\w.]+) hash=(?P<hash>[0-9a-f]+) -->"
    rb"(?P<body>.*?)"
    rb"<!-- DONTPANIC:END -->",
    re.DOTALL,
)


# ──────────────────────────────  managed-block primitives  ──────────────────────────────


def _body_hash(body: str) -> str:
    """SHA-256 over the (newline-normalized) block body. Deterministic so a
    stored marker hash can be compared against a freshly rendered body to decide
    staleness."""
    return hashlib.sha256(body.strip("\n").encode("utf-8")).hexdigest()


def _begin_marker(name: str, content_hash: str) -> str:
    return (
        f"{_MARK_BEGIN_PREFIX} name={name} "
        f"generator={ONBOARDING_GENERATOR_VERSION} hash={content_hash} -->"
    )


def render_block(name: str, body: str) -> str:
    """Render a complete managed block: BEGIN marker (with version + body hash),
    the body, and the END marker. Byte-stable for a given ``(name, body)``."""
    stripped = body.strip("\n")
    return "\n".join([_begin_marker(name, _body_hash(stripped)), stripped, _MARK_END])


def find_block(text: str, name: str) -> re.Match[str] | None:
    """Return the first DontPanic-managed block in ``text`` whose marker ``name``
    matches, or ``None`` when no such block exists."""
    for m in _BLOCK_RE.finditer(text):
        if m.group("name") == name:
            return m
    return None


def _block_is_fresh(match: re.Match[str], body: str) -> bool:
    """A managed block is fresh when its stored generator version matches, the
    stored hash matches a freshly rendered body, AND the on-disk body between the
    markers actually hashes to that stored hash. The last clause is the integrity
    check: a block whose body was hand-edited inside the markers (while the marker
    hash was left untouched) is NOT fresh and must be rewritten — never trust the
    marker hash alone (F003 codex finding)."""
    expected = _body_hash(body.strip("\n"))
    on_disk = _body_hash(match.group("body").strip("\n"))
    return (
        match.group("generator") == ONBOARDING_GENERATOR_VERSION
        and match.group("hash") == expected
        and on_disk == match.group("hash")
    )


def _find_block_bytes(raw: bytes, name: str) -> re.Match[bytes] | None:
    """Byte-domain :func:`find_block`. Returns the first DontPanic-managed block
    in ``raw`` whose marker ``name`` matches, or ``None`` when absent. Operates on
    raw bytes so the surrounding content's encoding/line-endings are irrelevant."""
    name_b = name.encode("ascii")
    for m in _BLOCK_RE_BYTES.finditer(raw):
        if m.group("name") == name_b:
            return m
    return None


def _block_is_fresh_bytes(match: re.Match[bytes], body: str) -> bool:
    """Byte-domain :func:`_block_is_fresh`. The body hash is computed in the str
    domain (the rendered body is always UTF-8 text we generate) and compared
    against the ASCII marker bytes. Like the str variant, also recomputes the
    hash of the on-disk body bytes and requires it to match the stored marker
    hash — an in-marker tamper (body edited, marker hash untouched) is NOT fresh
    (F003 codex finding). The on-disk body is decoded leniently because a tampered
    block may contain arbitrary bytes; an undecodable body simply fails the
    integrity check (treated as not fresh), which is the safe direction."""
    expected = _body_hash(body.strip("\n")).encode("ascii")
    try:
        on_disk = _body_hash(match.group("body").decode("utf-8").strip("\n")).encode("ascii")
    except UnicodeDecodeError:
        on_disk = b""
    return (
        match.group("generator") == ONBOARDING_GENERATOR_VERSION.encode("ascii")
        and match.group("hash") == expected
        and on_disk == match.group("hash")
    )


def _append_block_bytes(original: bytes, block: bytes) -> bytes:
    """Append ``block`` to ``original``, preserving ``original`` byte-for-byte as
    a prefix. Inserts a blank-line separator so the block reads cleanly; never
    rewrites or trims the pre-existing content. A CRLF-terminated file still ends
    in ``\\n``, so no spurious separator is added."""
    if original == b"":
        return block + b"\n"
    prefix = original if original.endswith(b"\n") else original + b"\n"
    return prefix + b"\n" + block + b"\n"


def _replace_block_bytes(raw: bytes, match: re.Match[bytes], block: bytes) -> bytes:
    """Splice ``block`` in place of the matched managed block. Bytes before the
    BEGIN marker and after the END marker are preserved byte-for-byte."""
    return raw[: match.start()] + block + raw[match.end() :]


# ──────────────────────────────  block bodies  ──────────────────────────────


def _agents_body(brief: agent_brief.RenderedBrief) -> str:
    """The AGENTS.md managed-block body: a heading plus the generated operating
    brief plus the re-generation hint. The brief text is the live-fact source of
    truth, so changing the brief changes this body (and thus the block hash)."""
    return "\n".join(
        [
            "# DontPanic — generated agent operating brief",
            "",
            "This block is generated and managed by DontPanic. Do not hand-edit "
            "between the markers;",
            "edits outside the markers are preserved. Re-generate with: "
            "`dontpanic projects add <name> <path> --onboard`.",
            "",
            brief.text.rstrip("\n"),
        ]
    )


def _claude_body() -> str:
    """The CLAUDE.md managed-block body: a short pointer to AGENTS.md. CLAUDE-based
    agents read CLAUDE.md by convention; this aliases them onto the single brief
    in AGENTS.md rather than duplicating it."""
    return "\n".join(
        [
            "# DontPanic",
            "",
            f"This repository is onboarded to DontPanic. The operating brief and "
            f"canonical workflow live in `{AGENTS_FILENAME}` — read it for the "
            "operator-vs-worker model, the supported commands, and the worker "
            "executor list.",
            "",
            "This pointer block is generated and managed by DontPanic; content "
            "outside the markers is preserved.",
        ]
    )


# ──────────────────────────────  plan + apply  ──────────────────────────────


@dataclass(frozen=True)
class FileAction:
    """One intended (or applied) effect on a single file.

    ``new_content`` is the full **bytes** the file should hold after the action,
    or ``None`` for ``noop`` / ``warn`` actions that write nothing. ``apply``
    writes ``new_content`` verbatim (via ``write_bytes``) only for ``create`` /
    ``update`` — operating in the byte domain is what guarantees existing content
    outside the managed markers survives byte-for-byte.
    """

    path: Path
    kind: str  # "config" | "agents" | "claude" | "claude-lowercase"
    action: str  # "create" | "update" | "noop" | "warn"
    detail: str
    new_content: bytes | None = None


@dataclass
class OnboardingPlan:
    """A full set of intended file actions for one repo. ``dry_run`` records
    whether :func:`apply_onboarding` actually wrote anything."""

    project_path: Path
    actions: list[FileAction] = field(default_factory=list)
    dry_run: bool = True

    @property
    def writes(self) -> list[FileAction]:
        """Actions that change a file (create/update) — i.e. excludes noop/warn."""
        return [a for a in self.actions if a.new_content is not None]


def _plan_config(project_path: Path) -> FileAction:
    """Plan the ``.dontpanic/dontpanic.json`` write.

    Creates the config with explicit defaults when absent. When a per-project
    config already exists (preferred or legacy path), leaves it untouched — we
    never clobber an operator's customized config on a re-onboard.
    """
    cfg_path = pc.project_config_path(project_path)
    legacy_path = pc.legacy_project_config_path(project_path)
    if cfg_path.is_file() or legacy_path.is_file():
        existing = cfg_path if cfg_path.is_file() else legacy_path
        return FileAction(
            path=existing,
            kind="config",
            action="noop",
            detail=f"per-project config already exists at {existing} — left untouched",
        )
    content = json.dumps(default_project_config_dict(), indent=2) + "\n"
    return FileAction(
        path=cfg_path,
        kind="config",
        action="create",
        detail="create .dontpanic/dontpanic.json with explicit defaults",
        new_content=content.encode("utf-8"),
    )


def _plan_managed_file(
    path: Path,
    *,
    kind: str,
    block_name: str,
    body: str,
) -> FileAction:
    """Plan a create/update/noop for a file carrying a single managed block.

    - Missing file → create it holding just the managed block.
    - Existing file, no managed block → append the block (existing content kept).
    - Existing file, stale managed block → replace it in place.
    - Existing file, fresh managed block → noop.
    """
    block = render_block(block_name, body).encode("utf-8")
    if not path.exists():
        return FileAction(
            path=path,
            kind=kind,
            action="create",
            detail=f"create {path.name} with the managed DontPanic block",
            new_content=block + b"\n",
        )
    raw = path.read_bytes()
    match = _find_block_bytes(raw, block_name)
    if match is None:
        return FileAction(
            path=path,
            kind=kind,
            action="update",
            detail=f"insert managed DontPanic block into existing {path.name}",
            new_content=_append_block_bytes(raw, block),
        )
    if _block_is_fresh_bytes(match, body):
        return FileAction(
            path=path,
            kind=kind,
            action="noop",
            detail=f"{path.name} managed block already current — left unchanged",
        )
    return FileAction(
        path=path,
        kind=kind,
        action="update",
        detail=f"replace stale managed DontPanic block in {path.name}",
        new_content=_replace_block_bytes(raw, match, block),
    )


def plan_onboarding(
    project_path: Path,
    *,
    brief: agent_brief.RenderedBrief | None = None,
) -> OnboardingPlan:
    """Compute every intended file action for onboarding ``project_path``.

    Pure — reads the repo and the live brief but writes nothing. ``brief``
    defaults to a freshly generated brief; tests inject a fabricated one to
    pin staleness behavior.
    """
    rendered = brief if brief is not None else agent_brief.generate_brief()
    actions: list[FileAction] = [
        _plan_config(project_path),
        _plan_managed_file(
            project_path / AGENTS_FILENAME,
            kind="agents",
            block_name=BLOCK_AGENTS,
            body=_agents_body(rendered),
        ),
        _plan_managed_file(
            project_path / CLAUDE_FILENAME,
            kind="claude",
            block_name=BLOCK_CLAUDE,
            body=_claude_body(),
        ),
    ]

    # Lowercase `.claude.md` is preserved untouched. Warn only when it is the
    # *only* CLAUDE pointer present (uppercase absent), since some agents read
    # uppercase and would otherwise miss the brief.
    upper = project_path / CLAUDE_FILENAME
    lower = project_path / LOWER_CLAUDE_FILENAME
    if lower.is_file() and not upper.is_file():
        actions.append(
            FileAction(
                path=lower,
                kind="claude-lowercase",
                action="warn",
                detail=(
                    f"found lowercase {LOWER_CLAUDE_FILENAME} but no {CLAUDE_FILENAME}; "
                    f"leaving {LOWER_CLAUDE_FILENAME} untouched and creating "
                    f"{CLAUDE_FILENAME} (not all agents read the lowercase name)"
                ),
            )
        )

    return OnboardingPlan(project_path=project_path, actions=actions, dry_run=True)


def apply_onboarding(
    project_path: Path,
    *,
    dry_run: bool,
    brief: agent_brief.RenderedBrief | None = None,
) -> OnboardingPlan:
    """Plan onboarding for ``project_path`` and, unless ``dry_run``, perform the
    create/update writes. Returns the plan with ``dry_run`` recorded so callers
    can render the same preview/result text either way."""
    plan = plan_onboarding(project_path, brief=brief)
    plan.dry_run = dry_run
    if dry_run:
        return plan
    for action in plan.actions:
        if action.new_content is None:
            continue
        action.path.parent.mkdir(parents=True, exist_ok=True)
        # write_bytes (not write_text): the planner produced exact bytes that
        # embed any pre-existing content verbatim, so writing them back cannot
        # re-encode or newline-normalize what lives outside the managed markers.
        action.path.write_bytes(action.new_content)
    return plan


def default_project_config_dict() -> dict[str, object]:
    """The explicit-defaults ``.dontpanic/dontpanic.json`` body written on
    onboarding. Every field is spelled out (rather than a bare ``{}``) and is
    schema-compatible with :class:`project_config.ProjectConfig`.

    The key set is derived from ``ProjectConfig.model_fields`` so a field added
    to the schema later automatically appears here (as an explicit ``null``)
    rather than being silently omitted. Fields with a meaningful onboarding
    default get an explicit value; the rest (``roles``, ``runtime_evidence``,
    …) are emitted as ``null`` so the file documents the full schema surface."""
    explicit: dict[str, object] = {
        "implementer": pc.FALLBACK_IMPLEMENTER,
        "auditor": pc.FALLBACK_AUDITOR,
        "plans_dir": pc.DEFAULT_PLANS_DIR,
        "default_target_env": pc.DEFAULT_TARGET_ENV,
        "human_gates": [],
        "protected_paths": [],
    }
    return {name: explicit.get(name, None) for name in pc.ProjectConfig.model_fields}


def plan_to_public_dict(plan: OnboardingPlan) -> dict[str, object]:
    """Serialize an onboarding plan for ``--json`` CLI output. Reports each
    action's path / kind / action / detail; never includes file bodies."""
    return {
        "project_path": str(plan.project_path),
        "dry_run": plan.dry_run,
        "actions": [
            {
                "path": str(a.path),
                "kind": a.kind,
                "action": a.action,
                "detail": a.detail,
            }
            for a in plan.actions
        ],
    }


__all__ = [
    "AGENTS_FILENAME",
    "BLOCK_AGENTS",
    "BLOCK_CLAUDE",
    "CLAUDE_FILENAME",
    "FileAction",
    "LOWER_CLAUDE_FILENAME",
    "ONBOARDING_GENERATOR_VERSION",
    "OnboardingPlan",
    "apply_onboarding",
    "default_project_config_dict",
    "find_block",
    "plan_onboarding",
    "plan_to_public_dict",
    "render_block",
]
