"""Scope-signal lint core (F001).

A pure, deterministic scorer over a single feature record. It takes the feature
dict (``id`` / ``description`` / ``steps`` / ``acceptance`` as authored in a
plan's ``features.json``) plus a caller-provided :class:`Resolvers` set, and
returns a typed :class:`ScopeReport` carrying risk :class:`ScopeFlag`\\ s with
the evidence that fired each one.

Purity contract (acceptance #1): ``lint_feature`` performs no network access,
no filesystem access, and no mutation of its arguments. It imports nothing
side-effect-capable (no ``subprocess``, no ``cli``, no ``supervisor``). The
only inputs are the feature dict and the resolver set the caller passes in.

The three onboarding-v0 defect classes this scores for:

  * **Over-scope (size).** A feature spanning more than one *surface*
    (engine + CLI + dashboard, ~16 providers, CLI + dashboard + doctor)
    exceeded a single 600s implementer dispatch. Surface-count is weighted
    above AC-count: F016 timed out at 5 ACs across 3 surfaces while F015
    converged clean at 4 ACs in one module. Flags: ``over_surface``,
    ``over_ac``, ``likely_timeout``.

  * **Exemplar / weak acceptance (precision).** An AC that gives an *example*
    (``e.g.`` / ``such as`` / ``including``) instead of an *invariant*, or
    that asserts bare string-equality with no round-trip / property check, so
    the implementer fixes the example and the auditor generalizes —
    whack-a-mole. Flags: ``exemplar_ac``, ``weak_test``.

  * **Silent prerequisite (coupling).** An AC that names a command / flag /
    symbol the plan never declared (F012's stale ``command_validation``
    allowlist). Every named token that does not resolve against the provided
    resolver set yields a ``missing_prereq`` flag naming the token. Flag:
    ``missing_prereq``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# ─────────────────────────────── public types ──────────────────────────────

Severity = Literal["info", "warn", "block"]

FlagKind = Literal[
    "over_surface",
    "over_ac",
    "exemplar_ac",
    "weak_test",
    "missing_prereq",
    "likely_timeout",
    "surface_proof_missing",
]


@dataclass(frozen=True)
class ScopeFlag:
    """One risk signal fired against a feature.

    ``kind`` is the closed defect taxonomy; ``severity`` is the triage band
    (``block`` = a gate should refuse without an override); ``evidence`` is the
    human-readable proof (the surface list, the offending AC text, or the
    unresolved token) so the operator can act without re-deriving the signal.
    """

    kind: FlagKind
    severity: Severity
    evidence: str


@dataclass(frozen=True)
class ScopeReport:
    """Typed lint result for a single feature (acceptance #1)."""

    feature_id: str
    surfaces: tuple[str, ...]
    ac_count: int
    flags: tuple[ScopeFlag, ...] = ()

    def flags_of_kind(self, kind: FlagKind) -> tuple[ScopeFlag, ...]:
        return tuple(f for f in self.flags if f.kind == kind)

    def has_block(self) -> bool:
        return any(f.severity == "block" for f in self.flags)


@dataclass(frozen=True)
class Resolvers:
    """The caller-provided vocabulary an AC's tokens must resolve against.

    Mirrors the three real resolver sources F003 will wire in: the CLI grammar
    (``commands`` / ``flags``), the prereq/executor registry and code symbols
    (``symbols``). F001 stays pure by never reaching for these itself — the
    caller passes a frozen snapshot.
    """

    commands: frozenset[str] = frozenset()
    flags: frozenset[str] = frozenset()
    symbols: frozenset[str] = frozenset()
    # The CLI binary name(s) a plan author writes before a subcommand
    # (``dontpanic plan-review``). Stripped before subcommand lookup so an
    # invocation phrase resolves against the bare subcommand vocabulary
    # (``known_subcommands`` lists ``plan-review``, never ``dontpanic
    # plan-review``).
    cli_binaries: frozenset[str] = frozenset({"dontpanic"})

    def resolves_command(self, token: str) -> bool:
        # An exact phrase match resolves first (a bare subcommand, or a caller
        # that registered a full phrase like ``quota-caps init``).
        if token in self.commands:
            return True
        # Otherwise treat ``token`` as an invocation phrase: drop a leading CLI
        # binary name (``dontpanic plan-review`` -> ``plan-review``), then the
        # first remaining word is the subcommand (``quota-caps init`` ->
        # ``quota-caps``). This keeps a genuinely unknown command
        # (``frobnicate widgets``) flagged while accepting the supported
        # ``dontpanic <subcommand>`` invocation shape.
        words = token.split()
        if words and words[0] in self.cli_binaries:
            words = words[1:]
        return bool(words) and words[0] in self.commands

    def resolves_flag(self, token: str) -> bool:
        return token in self.flags

    def resolves_symbol(self, token: str) -> bool:
        # A dotted symbol resolves if the full path OR its module root is known
        # (an AC naming ``command_validation.validate_command_tokens`` resolves
        # when the plan declares the ``command_validation`` module).
        if token in self.symbols:
            return True
        root = token.split(".", 1)[0]
        return root in self.symbols


# ───────────────────────────── surface taxonomy ────────────────────────────

# Surface -> the keyword signals that tag a text as touching it. Ordered most-
# to-least specific within each list; matching is whole-word, case-insensitive.
# Calibrated on onboarding-v0: the discriminating feature is surface-COUNT, so
# the lists are kept tight to avoid mis-tagging a clean single-surface feature
# (e.g. F015, a pure core module) as multi-surface.
SURFACES: dict[str, tuple[str, ...]] = {
    "cli": (
        "cli",
        "subcommand",
        "command-line",
        "argparse",
        "exit code",
        "exit-code",
        "stdout",
        "--format",
        "dontpanic ",
    ),
    "dashboard": (
        "dashboard",
        "html",
        "render html",
        "operator console",
        "web view",
    ),
    "doctor": (
        "doctor",
        "preflight warn",
        "proactive warn",
    ),
    "validator": (
        "command_validation",
        "validate_command_tokens",
        "validator",
        "command validation",
        "lint gate",
        "scope lint",
    ),
    "schema": (
        "json schema",
        "schema_version",
        "pydantic",
        "model_validate",
        "schema migration",
    ),
    "persistence": (
        "decisions.jsonl",
        "config.json",
        "quota_caps.json",
        "features.json",
        "state file",
        "persist",
        "write the file",
    ),
    "orchestration": (
        "dispatch",
        "volley",
        "supervisor",
        "auditor",
        "implementer",
        "circuit breaker",
        "breaker",
        "quota",
        "pre_lock",
        "pre_dispatch",
    ),
    "core": (
        "pure function",
        "pure module",
        "typed report",
        "deterministic",
        # "engine"/"core engine" name the calibration corpus's pure-logic
        # surface; without these an "engine + CLI" feature collapses to one
        # surface and silently escapes the over_surface signal.
        "engine",
        "core logic",
        "scoring core",
    ),
}

# Default surface for a feature whose text matches no specific surface keyword.
# A feature must touch *something*; an un-tagged feature is treated as pure core
# logic (the F015 shape), which keeps single-surface negatives clean.
_DEFAULT_SURFACE = "core"


# ──────────────────────────── precision lexicons ───────────────────────────

# Exemplar markers: an AC enumerating examples. Universal markers: a co-located
# invariant that redeems the enumeration ("every role in ...", "all of ...").
# ``including`` is an exemplar marker whether or not it is followed by ``the``
# ("including the implementer and auditor roles" enumerates just as much as
# "including implementer, auditor"). A co-located universal (_UNIVERSAL_RE)
# is the only thing that redeems any of these enumerations.
_EXEMPLAR_RE = re.compile(
    r"\b(e\.?g\.?|such as|for example|for instance|including|like,)\b",
    re.IGNORECASE,
)
_UNIVERSAL_RE = re.compile(
    r"\b(every|all|each|always|any |no |never|invariant|for all)\b",
    re.IGNORECASE,
)

# Weak-test markers: a bare equality / string-match assertion. Property markers:
# a round-trip / property / invariant assertion that redeems it.
_EQUALITY_RE = re.compile(
    r"(==|\bequals?\b|\bequal to\b|\bstring[- ]match\b|\bstring[- ]equality\b"
    r"|\bexactly matches\b|\bmatches exactly\b|\bmatches the string\b"
    r"|\bstring matches\b|\bmatches (?:the )?expected\b"
    r"|\bis exactly\b)",
    re.IGNORECASE,
)
_PROPERTY_RE = re.compile(
    r"\b(round[- ]?trip|property|invariant|idempoten\w*|conservation|conserves?"
    r"|holds for (every|all|each)|for all)\b",
    re.IGNORECASE,
)


# ─────────────────────────────── thresholds ────────────────────────────────

# AC-count is the secondary signal (surface-count is primary). Calibrated on
# onboarding-v0: F015/F014 stayed clean at 3-4 ACs in one surface; F011 was
# over-scoped at 14 ACs. ``over_ac`` warns above a single dispatch's comfort
# band and blocks at a clearly-too-large count.
_AC_WARN = 6
_AC_BLOCK = 10

# ``over_surface`` fires for *any* multi-surface feature (acceptance #2) but
# only blocks at >= 3 surfaces (the F016 calibration: 3 surfaces timed out even
# at 5 ACs; a clean 2-surface feature stays a warn).
_SURFACE_BLOCK = 3


# ─────────────────────────────── public API ────────────────────────────────


def lint_feature(feature: dict, resolvers: Resolvers | None = None) -> ScopeReport:
    """Score one feature record and return its :class:`ScopeReport`.

    Pure: no network, no filesystem, no mutation of ``feature`` or
    ``resolvers`` (acceptance #1).

    Args:
        feature: a feature dict with ``id`` and (any of) ``description`` /
            ``steps`` / ``acceptance``, as authored in a plan ``features.json``.
        resolvers: the vocabulary an AC's named tokens must resolve against.
            When ``None``, every named token is treated as unresolved (the
            most conservative coupling read).
    """
    resolvers = resolvers or Resolvers()
    feature_id = str(feature.get("id", ""))

    acceptance = _as_text(feature.get("acceptance"))
    steps_text = _as_text(feature.get("steps"))
    description = _as_text(feature.get("description"))

    criteria = split_acceptance(acceptance)
    ac_count = len(criteria)

    surfaces = tag_surfaces(f"{description}\n{steps_text}\n{acceptance}")

    flags: list[ScopeFlag] = []
    flags.extend(_size_flags(surfaces, ac_count))
    flags.extend(_precision_flags(criteria))
    flags.extend(_coupling_flags(criteria, resolvers))
    flags.extend(_surface_proof_flags(description, steps_text, acceptance))

    return ScopeReport(
        feature_id=feature_id,
        surfaces=surfaces,
        ac_count=ac_count,
        flags=tuple(flags),
    )


def surfaces_in(text: str) -> tuple[str, ...]:
    """Surfaces whose keywords specifically appear in ``text`` (no fallback).

    Unlike :func:`tag_surfaces`, this returns ``()`` when ``text`` matches no
    surface keyword. Callers that must distinguish a *genuine* surface match
    versus the ``core`` default — F002's split proposer deciding whether an AC
    actually names a surface or is generic — use this; surface *tagging* for
    the lint signal still goes through :func:`tag_surfaces`.
    """
    haystack = text.lower()
    return tuple(
        sorted(
            surface
            for surface, keywords in SURFACES.items()
            if any(kw in haystack for kw in keywords)
        )
    )


def tag_surfaces(text: str) -> tuple[str, ...]:
    """Return the sorted distinct surfaces ``text`` touches (deterministic).

    Defaults to ``("core",)`` when no specific surface keyword matches, so a
    feature always touches at least one surface.
    """
    return surfaces_in(text) or (_DEFAULT_SURFACE,)


def split_acceptance(acceptance: str) -> tuple[str, ...]:
    """Split an acceptance string into individual criteria.

    Handles the ``(1) ... (2) ...`` numbered convention used across the plans;
    falls back to one criterion (the whole non-empty string) when no markers
    are present.
    """
    text = acceptance.strip()
    if not text:
        return ()
    # Split on numbered markers like "(1)" / "(12)" that open a criterion.
    parts = re.split(r"\(\d+\)\s*", text)
    criteria = [p.strip() for p in parts if p.strip()]
    if criteria:
        return tuple(criteria)
    return (text,)


# ───────────────────────────── signal helpers ──────────────────────────────

# Plan 2026-06-05-002 F006 — advisory surface-class sufficiency heuristic.
# A feature making a surface-facing CLAIM (the human/agent SEES or drives a rendered
# surface) must NAME an entering-surface test/evidence. This is the lint encoding of
# docs/qa-sufficiency-contract.md. v0 is declarative + advisory (warn) — NO auto
# surface-class inference and NO synthetic-provenance static analysis.
_SURFACE_CLAIM_RE = re.compile(
    r"\b(show|shows|shown|display|displays|displayed|render|renders|rendered|"
    r"operator sees|user sees|copy button|copies the command|on[- ]screen|"
    r"navigat\w+|the (?:tab|page|view|dashboard|screen) (?:shows|displays|renders))\b",
    re.IGNORECASE,
)
# An entering-surface proof is NAMED if any of these appear in the feature text.
_ENTERING_PROOF_RE = re.compile(
    r"(real[- ]shell|real[- ]state|journey test|journey vitest|createjarvis|"
    r"playwright|xcuitest|espresso|instrument\w+|simulator|emulator|"
    r"entering[- ]surface|browser (?:test|smoke)|\.spec\.|screenshot|"
    r"snapshot test|page\.goto|surface_class)",
    re.IGNORECASE,
)


def _surface_proof_flags(
    description: str, steps_text: str, acceptance: str
) -> list[ScopeFlag]:
    """Warn (advisory) when a surface-facing claim names no entering-surface proof.

    Proof matches the claim: a feature with no surface-facing claim is never flagged
    (the trigger is the *claim*, not the implementation). Honors an optional declared
    ``surface_class`` token as a named proof reference.
    """
    claim_text = f"{description}\n{acceptance}"
    if not _SURFACE_CLAIM_RE.search(claim_text):
        return []  # no surface-facing claim → nothing required
    full = f"{description}\n{steps_text}\n{acceptance}"
    if _ENTERING_PROOF_RE.search(full):
        return []  # an entering-surface proof (or surface_class) is named
    return [
        ScopeFlag(
            kind="surface_proof_missing",
            severity="warn",
            evidence=(
                "surface-facing claim names no entering-surface test/evidence "
                "(real-shell/journey, simulator/emulator, browser/Playwright, …); "
                "advisory in v0 — see docs/qa-sufficiency-contract.md"
            ),
        )
    ]


def _size_flags(surfaces: tuple[str, ...], ac_count: int) -> list[ScopeFlag]:
    flags: list[ScopeFlag] = []
    n_surfaces = len(surfaces)

    if n_surfaces > 1:
        severity: Severity = "block" if n_surfaces >= _SURFACE_BLOCK else "warn"
        flags.append(
            ScopeFlag(
                kind="over_surface",
                severity=severity,
                evidence="surfaces: " + ", ".join(surfaces),
            )
        )

    if ac_count >= _AC_BLOCK:
        flags.append(
            ScopeFlag(
                kind="over_ac",
                severity="block",
                evidence=f"{ac_count} acceptance criteria (>= {_AC_BLOCK})",
            )
        )
    elif ac_count > _AC_WARN:
        flags.append(
            ScopeFlag(
                kind="over_ac",
                severity="warn",
                evidence=f"{ac_count} acceptance criteria (> {_AC_WARN})",
            )
        )

    # Composite timeout signal: >= 3 surfaces, OR a multi-surface feature also
    # carrying a non-trivial AC load (the F016 "5 ACs x 3 surfaces" shape).
    if n_surfaces >= _SURFACE_BLOCK or (n_surfaces > 1 and ac_count >= _AC_WARN):
        flags.append(
            ScopeFlag(
                kind="likely_timeout",
                severity="block",
                evidence=(
                    f"{n_surfaces} surfaces x {ac_count} ACs "
                    "exceeds a single 600s dispatch"
                ),
            )
        )

    return flags


def _precision_flags(criteria: tuple[str, ...]) -> list[ScopeFlag]:
    flags: list[ScopeFlag] = []
    for ac in criteria:
        if _EXEMPLAR_RE.search(ac) and not _UNIVERSAL_RE.search(ac):
            flags.append(
                ScopeFlag(
                    kind="exemplar_ac",
                    severity="block",
                    evidence=_clip(ac),
                )
            )
        if _EQUALITY_RE.search(ac) and not _PROPERTY_RE.search(ac):
            flags.append(
                ScopeFlag(
                    kind="weak_test",
                    severity="warn",
                    evidence=_clip(ac),
                )
            )
    return flags


def _coupling_flags(
    criteria: tuple[str, ...], resolvers: Resolvers
) -> list[ScopeFlag]:
    flags: list[ScopeFlag] = []
    seen: set[str] = set()
    for ac in criteria:
        for token, kind in extract_named_tokens(ac):
            if token in seen:
                continue
            resolved = {
                "command": resolvers.resolves_command,
                "flag": resolvers.resolves_flag,
                "symbol": resolvers.resolves_symbol,
            }[kind](token)
            if not resolved:
                seen.add(token)
                flags.append(
                    ScopeFlag(
                        kind="missing_prereq",
                        severity="block",
                        evidence=f"unresolved {kind}: {token}",
                    )
                )
    return flags


# Token classifiers. A named token may live inside backticks (where a leading
# plain-word run is read as a command phrase) OR be named in plain prose. Flags
# (``--name``) and code symbols (snake_case / dotted identifiers) are extracted
# from the raw AC text too, because plan authors routinely name them without
# backticks (the F012 stale-allowlist defect read that way). Bare command words
# stay backtick-scoped: an un-delimited lowercase word is indistinguishable from
# ordinary prose, so promoting one to a "command" would false-positive on every
# clean AC.
_FLAG_RE = re.compile(r"^--?[a-z][a-z0-9-]*$")
_SYMBOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_COMMAND_WORD_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_PLACEHOLDER_RE = re.compile(r"[<\[].*?[>\]]")

# Plain-text scanners (applied to the whole AC, backticked or not).
#   * a flag is an unambiguous ``--name`` (double-dash only, so hyphenated prose
#     like "round-trip" is never mistaken for a flag);
#   * a symbol is a dotted identifier (``mod.fn``) or a snake_case identifier
#     (``missing_symbol``) — both read as code, not prose.
_PLAIN_FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
_PLAIN_SYMBOL_RE = re.compile(
    r"\b("
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+"  # dotted: mod.fn
    r"|"
    r"[A-Za-z0-9]*_[A-Za-z0-9_]+"                            # snake_case
    r")\b"
)
# Dotted tokens that are filenames or prose abbreviations, not code symbols.
_FILE_EXT_RE = re.compile(
    r"\.(jsonl?|ya?ml|md|txt|py|tsx?|jsx?|sh|toml|csv|html?|cfg|ini|lock)$",
    re.IGNORECASE,
)
_SYMBOL_STOPWORDS = frozenset({"e.g", "i.e"})


def extract_named_tokens(ac: str) -> list[tuple[str, Literal["command", "flag", "symbol"]]]:
    """Extract the ``(token, kind)`` pairs an AC *names*.

    Sources, in order, de-duplicated across both:
      * **backtick spans** — a leading run of plain lowercase/hyphenated words is
        a **command** phrase (``quota-caps init``, ``plan-review``); a ``-``
        prefix is a **flag**; a dotted/underscore'd identifier is a **symbol**;
      * **plain prose** — any ``--name`` is a **flag** and any dotted /
        snake_case identifier is a **symbol**, so a plan that names a prereq
        without backticks still gets coupling-checked.
    """
    tokens: list[tuple[str, Literal["command", "flag", "symbol"]]] = []
    seen: set[tuple[str, str]] = set()

    def add(token: str, kind: Literal["command", "flag", "symbol"]) -> None:
        key = (token, kind)
        if key not in seen:
            seen.add(key)
            tokens.append((token, kind))

    # 1. Backtick spans (command phrases live only here).
    for span in re.findall(r"`([^`]+)`", ac):
        span = _PLACEHOLDER_RE.sub(" ", span).strip()
        if not span:
            continue
        words = span.split()

        # Command phrase: leading contiguous plain-word run (before any flag /
        # symbol / placeholder).
        lead: list[str] = []
        for w in words:
            if _COMMAND_WORD_RE.fullmatch(w) and "_" not in w:
                lead.append(w)
            else:
                break
        if lead:
            add(" ".join(lead), "command")

        for w in words[len(lead):]:
            w = w.strip(".,;:")
            if not w:
                continue
            if w.startswith("-"):
                if _FLAG_RE.fullmatch(w):
                    add(w, "flag")
            elif ("_" in w or "." in w) and _SYMBOL_RE.fullmatch(w):
                add(w, "symbol")

    # 2. Plain prose: unambiguous flags and code symbols anywhere in the AC.
    for m in _PLAIN_FLAG_RE.finditer(ac):
        add(m.group(1), "flag")
    for m in _PLAIN_SYMBOL_RE.finditer(ac):
        token = m.group(1)
        if token.lower() in _SYMBOL_STOPWORDS or _FILE_EXT_RE.search(token):
            continue
        add(token, "symbol")

    return tokens


# ───────────────────────────────── utils ───────────────────────────────────


def _as_text(value: object) -> str:
    """Flatten a feature field (str | list[str] | None) to a single string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(_as_text(v) for v in value)
    return str(value)


def _clip(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
