"""One template, one vocabulary for the text DontPanic generates in bulk.

Applies "Five Principles for Generating Readable AI Text in Bulk":

1. Status word first, one tense per state: ``Running`` while in progress,
   past tense once done (``Passed``, ``Failed``, ``Blocked``, ``Stopped``,
   ``Merged``).
2. The distinguishing word (the status) leads: ``Blocked: job X — reason``,
   never ``job X is blocked``.
3. One word per concept. A unit of DontPanic work is a **job** (never run,
   session or task); a pass/fail control is a **gate** (never check).
4. Same fields in the same order on every item (:data:`FIELD_ORDER`).
5. Failure verbs say it: fails / blocks / stops — not "had issues",
   "encountered an error", "was blocked by".

Line shape: ``<Status>: job <name> — <reason>[ (field value, ...)]``.

Pure stdlib; no model calls.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

# ── Vocabulary ──────────────────────────────────────────────────────────────

JOB: Final[str] = "job"
GATE: Final[str] = "gate"

RUNNING: Final[str] = "Running"
PASSED: Final[str] = "Passed"
FAILED: Final[str] = "Failed"
BLOCKED: Final[str] = "Blocked"
STOPPED: Final[str] = "Stopped"
MERGED: Final[str] = "Merged"

#: In-progress statuses (-ing).
PRESENT_STATUSES: Final[frozenset[str]] = frozenset({RUNNING})
#: Finished statuses (past tense).
PAST_STATUSES: Final[frozenset[str]] = frozenset(
    {PASSED, FAILED, BLOCKED, STOPPED, MERGED}
)
STATUSES: Final[frozenset[str]] = PRESENT_STATUSES | PAST_STATUSES

#: Order of the optional trailing fields, identical on every item.
FIELD_ORDER: Final[tuple[str, ...]] = ("gate", "stage", "agent", "round")

#: Invocation ledger ``result`` value -> status word.
_RESULT_STATUS: Final[Mapping[str, str]] = {
    "ok": PASSED,
    "error": FAILED,
    "interrupted": STOPPED,
}

SEP: Final[str] = " — "

# ── Templates ───────────────────────────────────────────────────────────────


def _fields_suffix(fields: Mapping[str, object]) -> str:
    unknown = set(fields) - set(FIELD_ORDER)
    if unknown:
        raise ValueError(f"unknown fields {sorted(unknown)}; allowed: {FIELD_ORDER}")
    parts = [f"{k} {fields[k]}" for k in FIELD_ORDER if fields.get(k) not in (None, "")]
    return f" ({', '.join(parts)})" if parts else ""


def status_line(status: str, job: str, reason: str, **fields: object) -> str:
    """``<Status>: job <job> — <reason>[ (field value, ...)]``."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; allowed: {sorted(STATUSES)}")
    return f"{status}: {JOB} {job}{SEP}{reason}{_fields_suffix(fields)}"


def job_title(status: str, job: str, reason: str) -> str:
    """Short title for a job; same template as :func:`status_line`, no fields."""
    return status_line(status, job, reason)


def gate_entry(status: str, job: str, gate: str, reason: str, **fields: object) -> str:
    """Gate log entry: the gate name is a fixed field, not free prose."""
    return status_line(status, job, reason, gate=gate, **fields)


def quota_entry(
    status: str, job: str, agent: str, reason: str, **fields: object
) -> str:
    """Quota log entry: the agent is a fixed field."""
    return status_line(status, job, reason, agent=agent, **fields)


def rollup_item(status: str, job: str, reason: str, **fields: object) -> str:
    """Activity-rollup item (operator brief / triage / inbox / dashboard)."""
    return status_line(status, job, reason, **fields)


def invocation_status(result: str, command: str, plan: str | None = None) -> str | None:
    """Status line for one CLI invocation record that belongs to a job.

    Returns ``None`` when the record names no plan (``--help``, ``projects
    list`` and similar): those calls are not jobs, so they keep their old text.
    An unknown ``result`` value maps to ``Failed`` only if non-empty; a
    missing result means the call never finished (``Stopped``).
    """
    if not plan:
        return None
    status = _RESULT_STATUS.get(result, FAILED if result else STOPPED)
    words = command.split()
    verb = " ".join(words[:2] if words[:1] in (["plan"], ["projects"]) else words[:1])
    outcome = {PASSED: "passes", FAILED: "fails", STOPPED: "stops"}[status]
    return status_line(status, plan, f"{verb or 'command'} {outcome}")


#: Volley ``final_status`` -> status word. Values not listed here are not
#: mapped: callers keep the original text instead of guessing a status.
TERMINAL_STATUS: Final[Mapping[str, str]] = {
    "signed_off": PASSED,
    "merged": MERGED,
    "failed": FAILED,
    "error": FAILED,
    "blocked": BLOCKED,
    "blocked_no_findings": BLOCKED,
    "stopped_cap": STOPPED,
    "stopped_budget": STOPPED,
    "stopped_quota": STOPPED,
    "stopped_no_progress": STOPPED,
    "stopped_wall_clock": STOPPED,
    "stopped_global_breaker": STOPPED,
    "stopped_diminishing_returns": STOPPED,
    "stopped_environmental_blocker": STOPPED,
}


def terminal_status(final_status: str | None) -> str | None:
    """Status word for a volley ``final_status``; ``None`` when unknown."""
    return TERMINAL_STATUS.get(final_status or "")


PROMPT_GUIDE: Final[str] = (
    "Status lines you write follow one template:\n"
    "  <Status>: job <name> — <reason>\n"
    "- Status first. Use Running while in progress; once done use exactly one of "
    "Passed, Failed, Blocked, Stopped, Merged.\n"
    "- Say job for a unit of work (never run, session, task); say gate for a "
    "pass/fail control (never check).\n"
    "- Name failures plainly: fails, blocks, stops. Do not write \"had issues\", "
    "\"encountered an error\" or \"was blocked by\".\n"
    "- Every line carries the same fields in the same order: "
    + ", ".join(FIELD_ORDER)
    + " (omit a field only when it does not apply).\n"
    "- This applies only to status lines in your prose. Leave commands, "
    "Env: and Project: lines, finding IDs and code exactly as they are.\n"
)

# ── Lint ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Violation:
    index: int
    rule: str
    message: str


_HEAD_RE = re.compile(r"^([A-Za-z]+):\s")
_SHAPE_RE = re.compile(r"^job \S.*? — \S")
_FIELDS_RE = re.compile(r"\(((?:[a-z]+ [^,()]+)(?:, [a-z]+ [^,()]+)*)\)\s*$")

_BANNED_JOB_WORDS = re.compile(r"\b(?:run|runs|session|sessions|task|tasks)\b", re.I)
_BANNED_GATE_WORDS = re.compile(r"\b(?:check|checks)\b", re.I)
_VAGUE_FAILURE = re.compile(
    r"\bhad (?:some )?(?:issues|problems)\b|\bencountered\b|\bran into\b"
    r"|\bexperienced\b|\bwas blocked by\b|\bis blocked\b|\bwas stopped by\b",
    re.I,
)
_PRESENT_ONLY = re.compile(r"\b(?:has finished|has completed|finished|completed|started|was)\b", re.I)
_PAST_ONLY = re.compile(r"\b(?:currently|in progress|is running|still running)\b", re.I)


def _field_keys(line: str) -> tuple[str, ...]:
    m = _FIELDS_RE.search(line)
    if not m:
        return ()
    return tuple(part.split(" ", 1)[0] for part in m.group(1).split(", "))


def lint_items(items: Iterable[str | None]) -> list[Violation]:
    """Return rule violations for a list of generated status lines (empty = clean).

    ``None`` or non-text items are reported as ``not-text`` rather than raising.
    """
    out: list[Violation] = []
    lines: list[str] = []
    skipped: set[int] = set()
    for i, item in enumerate(items):
        if not isinstance(item, str):
            out.append(Violation(i, "not-text", f"item is {type(item).__name__}, not a status line"))
            skipped.add(i)
            lines.append("")
            continue
        lines.append(item)
    for i, line in enumerate(lines):
        if i in skipped:
            continue
        head = _HEAD_RE.match(line)
        if head is None:
            out.append(Violation(i, "status-first", f"no leading '<Status>:' in {line!r}"))
            status = None
        elif head.group(1) not in STATUSES:
            out.append(Violation(i, "unknown-status", f"status {head.group(1)!r} not in vocabulary"))
            status = None
        else:
            status = head.group(1)
        body = line[head.end():] if head else line
        if status is not None and not _SHAPE_RE.match(body):
            out.append(Violation(i, "shape", f"expected 'job <name> — <reason>' after the status in {line!r}"))
        if _BANNED_JOB_WORDS.search(body):
            out.append(Violation(i, "vocabulary", "use 'job', not run/session/task"))
        if _BANNED_GATE_WORDS.search(body):
            out.append(Violation(i, "vocabulary", "use 'gate', not check"))
        if _VAGUE_FAILURE.search(body):
            out.append(Violation(i, "failure-verb", "use fails/blocks/stops, not vague or passive wording"))
        if status in PRESENT_STATUSES and _PRESENT_ONLY.search(body):
            out.append(Violation(i, "tense", f"{status} is in progress; reason uses past tense"))
        if status in PAST_STATUSES and _PAST_ONLY.search(body):
            out.append(Violation(i, "tense", f"{status} is done; reason uses in-progress wording"))
    texts = [(i, line) for i, line in enumerate(lines) if i not in skipped]
    if len(texts) > 1:
        first = _field_keys(texts[0][1])
        for i, line in texts[1:]:
            if _field_keys(line) != first:
                out.append(Violation(i, "fields", f"fields {_field_keys(line)} differ from first item's {first}"))
    return out
