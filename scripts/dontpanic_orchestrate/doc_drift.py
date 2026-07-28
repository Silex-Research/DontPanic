"""Doc-drift guard — plan 2026-07-27-001 F002.

Operator-facing docs (README, capability matrix) must never claim that an
agent absent from :data:`executors.AGENT_REGISTRY` is a shipped/dispatchable
executor. That exact drift shipped once: the README setup checklist marked
"Claude, Codex, Gemini, Grok, Ollama executors" as shipped while the registry
held only ``claude`` and ``codex``, so new users planned illegal topologies
(``roles.goal_auditor=gemini``) and hit opaque rc-3 refusals.

Source of truth is ``sorted(AGENT_REGISTRY.keys())`` — the guard relaxes
automatically if an agent gains a real executor, and tightens if one is
removed. Watched names are the known operator-only runtimes plus ``ollama``
(documented as planned, never registered).

The scan is a deliberate heuristic over a FIXED allowlist of paths
(:data:`DOC_ALLOWLIST`), not a repo-wide sweep: plan documents legitimately
quote the old broken claims as motivation. A unit is one markdown list item /
table row, or one prose paragraph (wrapped lines joined, so a disclaimer on
the continuation line still counts). Within a unit that makes an
executor/dispatch claim, disclaimers are scoped per agent mention (auditor
F002-i0/i1/i2 finding 1): the unit is split into segments on TYPED
separators — coordinating conjunctions (and/or/nor) are WEAK, everything
else (sentence ends, semicolons, commas, en/em dashes, spaced hyphens,
parentheses, contrast conjunctions such as but/while/whereas) is STRONG —
and each segment is classified as disclaimer, claim, or neutral. Within
one segment precedence is negating disclaimer (not-dispatchable wording) >
claim (executor/worker/dispatch vocabulary) > status disclaimer
(operator-only / planned wording): a status keyword must not suppress an
explicit claim in the same segment — "a shipped executor for planned
workflows" is drift (auditor F002-i3 finding 1). Parentheses are strong
boundaries so a parenthetical disclaimer about one agent cannot
reclassify the claim it interrupts ("Gemini is a shipped executor (Grok
is operator-only)" flags gemini). A mention is then attributed
deterministically (F002-i2 finding 1):

1. its own segment's class decides when non-neutral (disclaimer → honest,
   claim → drift);
2. a neutral mention that reaches a non-neutral segment across only WEAK
   separators is a conjoined subject of that clause — a weakly-reached
   claim is drift, a weakly-reached disclaimer is honest even when it names
   another agent ("Gemini and Grok are operator-only runtimes");
3. otherwise the mention binds across strong boundaries only to a nearest
   non-neutral disclaimer that names NO other watched agent and past which
   the clause does not resume with a claim — the attributive annotations
   README actually uses ("Gemini (operator-only) also runs the CLI",
   "**gemini CLI** — ... operator-only runtime") stay excused, while
   "Shipped executors — Gemini — Grok is operator-only" flags gemini
   because grok owns the only nearby disclaimer, and "Gemini
   (operator-only) is a shipped executor" flags gemini because the
   annotation merely interrupts a claim clause (F002-i3 finding 1).

Known limitation: a bare attributive disclaimer adjacent to a mention wins
over a claim label on the far side of the MENTION ("Shipped executors —
Gemini — cannot be dispatched" is excused); such self-contradicting prose
is out of scope.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from dontpanic_orchestrate.executors import AGENT_REGISTRY
from dontpanic_orchestrate.invocation_context import AGENT_RUNTIMES

# Fixed allowlist, repo-root relative. The matrix doc lands with F003 of the
# same plan; scanning skips paths that do not exist yet.
DOC_ALLOWLIST: tuple[str, ...] = (
    "README.md",
    "docs/AGENT_CAPABILITY_MATRIX.md",
)

# Agent names worth watching for overstated dispatch claims: the canonical
# runtime universe (registry + known operator agents + spec runtimes such as
# opencode/cursor/aider/antigravity) plus ollama, which README documents as
# planned but which is not a canonical runtime (auditor F002-i1 finding 2).
# Registry members are subtracted at scan time, never here, so the guard
# stays registry-driven.
WATCHED_AGENTS: tuple[str, ...] = tuple(sorted({*AGENT_RUNTIMES, "ollama"}))

# A unit makes an executor claim when it uses worker/executor/dispatch
# vocabulary. Bare "dispatch" is intentionally NOT a claim keyword — quota and
# breaker prose ("circuit breakers defer dispatch") is not an executor claim.
_CLAIM_RE = re.compile(
    r"\b(?:executors?|dispatchable|volley dispatch|dispatched as"
    r"|registered workers?|workers?)\b",
    re.IGNORECASE,
)

# Disclaimers come in two strengths (auditor F002-i3 finding 1). NEGATING
# disclaimers deny dispatchability outright and beat claim vocabulary in the
# same segment ("not a dispatchable executor" contains the claim word it
# negates). STATUS disclaimers merely label an agent's tier and LOSE to
# claim vocabulary in the same segment — "a shipped executor for planned
# workflows" qualifies the workload, not the executor claim.
_NEGATING_DISCLAIMER_RE = re.compile(
    r"(?:not (?:a )?dispatchable|not dispatched|can(?:not|'t) be dispatched)",
    re.IGNORECASE,
)
_STATUS_DISCLAIMER_RE = re.compile(
    r"(?:operator-only|operator[- ]side|operator surfaces?|known operator|planned)",
    re.IGNORECASE,
)

# Lines that start a self-contained unit: markdown list items, checklist
# items, ordered-list items, and table rows.
_UNIT_START_RE = re.compile(r"^\s*(?:[-*+]\s|\d+\.\s|\|)")

# Typed segment boundaries inside one unit. Coordinating conjunctions are
# WEAK — "Gemini and Grok are operator-only" is one conjoined subject even
# after splitting. Everything else is STRONG: clause ends, commas, en/em
# dashes (spaced or not), spaced hyphens ("foo - bar" splits, "long-context"
# does not), parentheses (a parenthetical disclaimer must not reclassify the
# claim it interrupts — auditor F002-i2 finding 1), and contrast
# conjunctions, which start a clause with its own subject.
_SEPARATOR_RE = re.compile(
    r"(?P<weak>\b(?:and|or|nor)\b)"
    r"|[;.!?](?:\s|$)"
    r"|,"
    r"|[—–()]"
    r"|\s-\s"
    r"|\b(?:but|while|whereas|although|though|however|yet)\b",
    re.IGNORECASE,
)

# One matcher per watched agent name: reused both to find mentions and to
# decide whether a disclaimer segment is "owned" by a different agent.
_AGENT_NAME_RES: dict[str, re.Pattern[str]] = {
    agent: re.compile(rf"\b{re.escape(agent)}\b", re.IGNORECASE) for agent in WATCHED_AGENTS
}


@dataclass(frozen=True)
class DocDriftViolation:
    """One overstated executor claim: a non-registry agent asserted as shipped."""

    path: str
    line: int
    agent: str
    excerpt: str

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.line}: claims non-registry agent "
            f"{self.agent!r} as a shipped executor "
            f"(registered: {registered_worker_names()}): {self.excerpt!r}"
        )


def registered_worker_names() -> list[str]:
    """Registered dispatchable worker names — ``sorted(AGENT_REGISTRY.keys())``."""
    return sorted(AGENT_REGISTRY)


def _iter_units(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(first_line_no, unit_text)`` scan units.

    List items and table rows are their own unit (one disclaimer bullet must
    not excuse a neighbouring bullet); consecutive prose lines join into a
    paragraph so a wrapped disclaimer stays attached to its claim.
    """
    start_line = 0
    parts: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            if parts:
                yield start_line, " ".join(parts)
                parts = []
            continue
        if _UNIT_START_RE.match(raw) and parts:
            yield start_line, " ".join(parts)
            parts = []
        if not parts:
            start_line = line_no
        parts.append(line)
    if parts:
        yield start_line, " ".join(parts)


def _segment_class(segment: str) -> str:
    """Classify one segment: negating disclaimer > claim > status disclaimer.

    A negating disclaimer beats co-occurring claim vocabulary because its
    phrasing contains the claim word it negates ("not a dispatchable
    executor"). A status disclaimer loses to claim vocabulary in the same
    segment (auditor F002-i3 finding 1): "a shipped executor for planned
    workflows" is still an executor claim — "planned" qualifies the
    workload, not the agent's dispatchability.
    """
    if _NEGATING_DISCLAIMER_RE.search(segment):
        return "disclaimer"
    if _CLAIM_RE.search(segment):
        return "claim"
    if _STATUS_DISCLAIMER_RE.search(segment):
        return "disclaimer"
    return "neutral"


def _split_unit(unit: str) -> tuple[list[str], list[str]]:
    """Split a unit into segments plus the separator strength between them.

    Returns ``(segments, strengths)`` where ``strengths[i]`` ("weak" or
    "strong") joins ``segments[i]`` and ``segments[i + 1]``. Runs of
    separators with nothing between them (", and", "— and") merge into one
    boundary; strong wins so an Oxford ", and" cannot smuggle a weak link
    across a list boundary.
    """
    segments: list[str] = []
    strengths: list[str] = []
    pending: str | None = None
    pos = 0

    def _push(chunk: str, next_strength: str | None) -> None:
        nonlocal pending
        if chunk:
            if segments:
                strengths.append(pending or "strong")
            segments.append(chunk)
            pending = next_strength
        elif next_strength == "strong" or pending is None:
            pending = next_strength

    for match in _SEPARATOR_RE.finditer(unit):
        strength = "weak" if match.group("weak") else "strong"
        _push(unit[pos : match.start()].strip(), strength)
        pos = match.end()
    _push(unit[pos:].strip(), None)
    return segments, strengths


def _weakly_reached(classes: list[str], strengths: list[str], index: int) -> list[str]:
    """Classes of the first non-neutral segment reachable in each direction
    from ``index`` crossing only weak separators — the mention's own clause."""
    reached: list[str] = []
    for step in (-1, 1):
        i = index
        while 0 <= i + step < len(classes):
            if strengths[i if step == 1 else i - 1] != "weak":
                break
            i += step
            if classes[i] != "neutral":
                reached.append(classes[i])
                break
    return reached


def _claim_continues_past(classes: list[str], index: int, step: int) -> bool:
    """True when the segment run beyond ``index`` (skipping consecutive
    disclaimers) resumes with a claim — the disclaimer at ``index`` is then
    an interrupting annotation inside a claim clause ("Gemini
    (operator-only) is a shipped executor"), not that clause's verdict
    (auditor F002-i3 finding 1)."""
    i = index + step
    while 0 <= i < len(classes) and classes[i] == "disclaimer":
        i += step
    return 0 <= i < len(classes) and classes[i] == "claim"


def _owned_by_other(segment: str, agent: str) -> bool:
    """True when a segment names a watched agent other than ``agent`` — its
    disclaimer belongs to that agent and cannot excuse this one."""
    return any(
        name != agent and pattern.search(segment) for name, pattern in _AGENT_NAME_RES.items()
    )


def _mention_excused(
    agent: str,
    segments: list[str],
    classes: list[str],
    strengths: list[str],
    index: int,
) -> bool:
    """Deterministic per-mention attribution (auditor F002-i2 finding 1).

    Own segment class decides when non-neutral. A neutral mention is first
    bound to its own clause across weak separators: a weakly-reached claim is
    drift, a weakly-reached disclaimer is honest (conjoined subjects share
    the predicate, other agent names included). Only then may the mention
    bind across strong boundaries — and solely to a nearest non-neutral
    disclaimer that names no other agent AND is not an interrupting
    annotation inside a claim clause (auditor F002-i3 finding 1): "Grok is
    operator-only" cannot excuse "Shipped executors — Gemini", "Gemini
    (operator-only) is a shipped executor" flags because the clause resumes
    with the claim predicate, while an attributive "(operator-only)"
    followed by neutral prose still annotates the mention beside it.
    """
    if classes[index] == "claim":
        return False
    if classes[index] == "disclaimer":
        # A mention sitting inside disclaimer wording is honest ONLY when the
        # unit does not later resume with an executor claim (auditor F002-i4).
        # Look forward via _claim_continues_past only — do NOT use weak-clause
        # reach here, or "Gemini is a shipped executor and Grok is
        # operator-only" would flag grok for gemini's claim (weak "and").
        # Forward still catches "Gemini cannot be dispatched and is a shipped
        # executor" and "Gemini is operator-only, but it is a shipped executor".
        if _claim_continues_past(classes, index, 1):
            return False
        return True
    clause = _weakly_reached(classes, strengths, index)
    if "claim" in clause:
        return False
    if "disclaimer" in clause:
        return True
    for step in (-1, 1):
        i = index + step
        while 0 <= i < len(classes):
            if classes[i] != "neutral":
                if (
                    classes[i] == "disclaimer"
                    and not _owned_by_other(segments[i], agent)
                    and not _claim_continues_past(classes, i, step)
                ):
                    return True
                break
            i += step
    return False


def scan_text(
    text: str,
    *,
    path: str = "<text>",
    registered: Iterable[str] | None = None,
) -> list[DocDriftViolation]:
    """Scan doc text for non-registry agents asserted as shipped executors."""
    registered_set = set(registered) if registered is not None else set(registered_worker_names())
    non_registry = [a for a in WATCHED_AGENTS if a not in registered_set]
    violations: list[DocDriftViolation] = []
    for line_no, unit in _iter_units(text):
        if not _CLAIM_RE.search(unit):
            continue
        segments, strengths = _split_unit(unit)
        classes = [_segment_class(s) for s in segments]
        for agent in non_registry:
            agent_re = _AGENT_NAME_RES[agent]
            mentions = [i for i, s in enumerate(segments) if agent_re.search(s)]
            if not mentions:
                continue
            if all(_mention_excused(agent, segments, classes, strengths, i) for i in mentions):
                continue
            violations.append(DocDriftViolation(path=path, line=line_no, agent=agent, excerpt=unit))
    return violations


def scan_allowlisted_docs(
    repo_root: Path,
    *,
    registered: Iterable[str] | None = None,
) -> list[DocDriftViolation]:
    """Scan every existing :data:`DOC_ALLOWLIST` path under ``repo_root``."""
    violations: list[DocDriftViolation] = []
    for rel in DOC_ALLOWLIST:
        doc = repo_root / rel
        if not doc.is_file():
            continue
        violations.extend(
            scan_text(doc.read_text(encoding="utf-8"), path=rel, registered=registered)
        )
    return violations
