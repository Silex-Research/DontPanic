"""Plan 2026-06-17-001 F002 — one-time, idempotent canonical backfill engine.

Stamps a durable ``canonical_repo`` onto the historical ``invocations.jsonl``
records that lack it, using the operator-local C4 evidence file (F006 contract)
captured while the temp worktrees still existed. The engine:

* **Consumes the F006 evidence contract** (:mod:`canonical_evidence`) for SHAPE
  validation and resolves each observed ``repo.path_key`` to its single
  confirmable canonical entry.
* **Recomputes the semantic truth** the contract deliberately does not trust:
  it reconstructs the real local canonical path from the scrubbed display (C1
  rules), reconfirms ``path_key`` via :func:`make_path_pair`, refuses any
  reconstructed temp-prefix path (C3), and writes a ``durable_checkout`` that is
  **RECOMPUTED** from the temp-prefix test — never copied from evidence.
* **Is idempotent** — a record already carrying ``canonical_repo`` is left
  untouched, so a re-run is a no-op.
* **Fails closed** — any ambiguity (absent/multiple mappings, missing/mistyped
  fields, raw-secret-shaped values, non-reconstructable display, path-key
  mismatch, temp canonical, or a ``durable_checkout`` that contradicts the
  recomputed value in either direction) is a per-record SKIP + reported reason,
  never a guess.

Defect tiers (C4):

* **File-fatal** — invalid JSON / missing or malformed top-level structure ->
  :class:`canonical_evidence.EvidenceFatalError` propagates (caller maps it to
  exit 2 and stamps nothing).
* **Row-level** — a per-record skip listed in the report's ``skipped`` (exit 0).

Lock ownership (C8): F002 is **NOT** the lock owner. Write mode REQUIRES a held
:class:`invocation_ledger.HeldLedgerLock` context supplied by the F005 entrypoint
(the sole C8 sidecar-lock owner) and refuses to write without it. The engine
never self-acquires the lock; the caller holds it across the whole
read/validate/write/temp-file/rename critical section.

The free-text ``command`` field is NEVER read or parsed (C6).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import canonical_evidence as ce
from dontpanic_orchestrate import global_config
from dontpanic_orchestrate import invocation_ledger as il
from dontpanic_orchestrate.completion_dispatch import sanitize_capture

# ── constants ────────────────────────────────────────────────────────────

#: Default evidence filename under ``$DONTPANIC_HOME`` (C4).
EVIDENCE_FILENAME = "canonical-backfill-evidence.json"

#: The C1 home-token produced by the shared scrubber; the only scrub token the
#: backfill can safely re-expand to a real local path.
_HOME_TOKEN = "<home>"

#: Any ``<token>`` left in a display after the ``<home>`` substitution (e.g.
#: ``<operator>`` / ``<host>``) means the display is NOT safely reconstructable.
_SCRUB_TOKEN_RE = re.compile(r"<[a-z0-9_]+>")

# ── row-level (F002 semantic) skip reasons ───────────────────────────────
# F006 row-level reasons (absent key, multiple/zero mappings, unknown canonical,
# missing/mistyped field, raw-secret shape, path_key-vs-mapkey mismatch, origin
# not hash-shaped) are surfaced verbatim. These are the additional SEMANTIC
# refusals F002 computes on top of the shape-valid F006 entry.

SKIP_NON_RECONSTRUCTABLE_SCRUB_TOKEN = "non_reconstructable_scrub_token"
SKIP_PATH_KEY_CONFIRMATION_FAILED = "path_key_confirmation_failed"
SKIP_RECONSTRUCTED_TEMP_CANONICAL = "reconstructed_temp_canonical"
SKIP_DURABLE_CONTRADICTION = "durable_checkout_contradiction"


class BackfillError(Exception):
    """Base for non-fatal-tier backfill failures the caller maps to exit 2."""


class BackfillWriteError(BackfillError):
    """Write mode invoked without a held C8 lock context, or an atomic write/
    rename failure (exit 2). Stamps nothing / leaves the ledger in place."""


class LedgerReadError(BackfillError):
    """The ledger exists but is unreadable / not valid JSONL (exit 2)."""


# ── confirmed canonical (post-recompute) ─────────────────────────────────


@dataclass(frozen=True)
class ConfirmedCanonical:
    """A canonical attribution that passed BOTH the F006 shape contract and the
    F002 semantic recompute. ``path_display`` is the recomputed scrubbed display
    (never the raw evidence display) and ``durable_checkout`` is RECOMPUTED from
    the reconstructed path's temp-prefix test (never trusted from evidence)."""

    path_key: str
    path_display: str
    durable_checkout: bool
    origin_key: str | None = None


def _reconstruct_local_path(path_display: str) -> str | None:
    """Reconstruct the real local canonical path from a scrubbed evidence display
    per the C1 rules, or ``None`` when the display is non-reconstructable.

    * ``<home>`` token -> substitute ``str(Path.home())``.
    * literal display (no scrub token) -> verbatim.
    * any residual ``<token>`` (``<operator>`` / ``<host>`` / …) -> ``None``.
    """
    candidate = path_display
    if _HOME_TOKEN in candidate:
        candidate = candidate.replace(_HOME_TOKEN, str(Path.home()))
    if _SCRUB_TOKEN_RE.search(candidate):
        return None
    return candidate


def confirm_canonical(
    observed_path_key: str, contract: ce.EvidenceContract
) -> tuple[ConfirmedCanonical | None, str | None]:
    """The deterministic C4 evidence-matrix check for one observed path key.

    Returns ``(confirmed, None)`` when the mapping is CONFIRMED, else
    ``(None, skip_reason)`` with a stable reason code. Shape defects are delegated
    to the F006 contract; the SEMANTIC defects (reconstruction, path-key
    confirmation, temp canonical, durable contradiction) are computed here. No
    field is copied until every check has passed.
    """
    resolution = contract.resolve(observed_path_key)
    if not resolution.confirmed:
        # F006 row-level shape defect (absent key, multiple/unknown/typed/secret).
        return None, resolution.skip_reason

    canonical = resolution.canonical  # shape-validated CanonicalRepoEvidence

    # C1: reconstruct the real local path from the scrubbed display.
    local_path = _reconstruct_local_path(canonical.path_display)
    if local_path is None:
        return None, SKIP_NON_RECONSTRUCTABLE_SCRUB_TOKEN

    # Recompute the path pair; the recomputed key must confirm the evidence key.
    pair = il.make_path_pair(local_path)
    if pair is None or pair["path_key"] != canonical.path_key:
        return None, SKIP_PATH_KEY_CONFIRMATION_FAILED

    # C3: a reconstructed temp-prefix path is never a canonical (covers the
    # "durable_checkout=true claimed for a temp canonical" case too).
    if il._is_temp_path(local_path):  # noqa: SLF001 — shared temp-prefix test
        return None, SKIP_RECONSTRUCTED_TEMP_CANONICAL

    # C3: durable_checkout is RECOMPUTED from the temp-prefix test, never trusted.
    # Past the temp guard the path is durable, so the recomputed value is True;
    # evidence claiming durable_checkout=false for it is a contradiction -> SKIP.
    recomputed_durable = not il._is_temp_path(local_path)  # noqa: SLF001
    if canonical.durable_checkout != recomputed_durable:
        return None, SKIP_DURABLE_CONTRADICTION

    return (
        ConfirmedCanonical(
            path_key=canonical.path_key,
            path_display=pair["path_display"],  # recomputed scrubbed display (C1)
            durable_checkout=recomputed_durable,  # recomputed, not from evidence
            origin_key=canonical.origin_key,  # hash-validated by F006 before copy
        ),
        None,
    )


# ── report ───────────────────────────────────────────────────────────────


@dataclass
class BackfillReport:
    """Stable report shape (C4). ``would_stamp``/``would_skip`` describe a dry run;
    ``stamped`` is the count actually written in write mode."""

    would_stamp: int = 0
    stamped: int = 0
    already_stamped: int = 0
    would_skip: int = 0
    skipped: list[dict[str, str]] = field(default_factory=list)
    ledger_path: str = ""
    evidence_path: str = ""
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "would_stamp": self.would_stamp,
            "stamped": self.stamped,
            "already_stamped": self.already_stamped,
            "would_skip": self.would_skip,
            "skipped": list(self.skipped),
            "ledger_path": self.ledger_path,
            "evidence_path": self.evidence_path,
            "dry_run": self.dry_run,
        }


# ── pure stamping pass ───────────────────────────────────────────────────


def _observed_path_key(record: Mapping[str, Any]) -> str:
    repo = record.get("repo")
    if isinstance(repo, Mapping):
        key = repo.get("path_key")
        if isinstance(key, str):
            return key
    return ""


def _stamp_records(
    records: Sequence[Any], contract: ce.EvidenceContract
) -> tuple[list[Any], int, int, list[dict[str, str]]]:
    """Pure pass over ledger records. Returns ``(new_records, confirmed_count,
    already_count, skipped)``. Record order and every existing field are
    preserved; the free-text ``command`` field is never read (C6)."""
    new_records: list[Any] = []
    confirmed = 0
    already = 0
    skipped: list[dict[str, str]] = []

    for record in records:
        if not isinstance(record, Mapping):
            new_records.append(record)
            continue
        # Idempotence: a record already carrying canonical_repo is left untouched.
        if "canonical_repo" in record:
            already += 1
            new_records.append(record)
            continue

        observed_key = _observed_path_key(record)
        result, reason = confirm_canonical(observed_key, contract)
        if reason is not None:
            skipped.append({"path_key": observed_key, "reason": reason})
            new_records.append(record)
            continue

        stamped = dict(record)
        canonical: dict[str, Any] = {
            "path_key": result.path_key,
            "path_display": result.path_display,
            "durable_checkout": result.durable_checkout,
        }
        if result.origin_key:
            canonical["origin_key"] = result.origin_key
        stamped["canonical_repo"] = canonical
        new_records.append(stamped)
        confirmed += 1

    return new_records, confirmed, already, skipped


# ── IO helpers ───────────────────────────────────────────────────────────


def default_evidence_path() -> Path:
    """Default evidence path under ``$DONTPANIC_HOME`` (same home logic as the
    ledger writer)."""
    return global_config.dontpanic_home() / EVIDENCE_FILENAME


def _read_ledger(target: Path) -> list[Any]:
    if not target.exists():
        return []
    out: list[Any] = []
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerReadError(f"ledger unreadable: {target}: {exc}") from exc
    return out


def _atomic_rewrite(target: Path, records: Sequence[Any]) -> None:
    """Temp-file + atomic rename rewrite. The caller MUST already hold the C8
    sidecar lock across this call (F002 never acquires it)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".backfill.tmp")
    try:
        tmp.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in records),
            encoding="utf-8",
        )
        os.replace(tmp, target)
    except OSError as exc:
        with __import__("contextlib").suppress(OSError):
            tmp.unlink()
        raise BackfillWriteError(f"atomic ledger rewrite failed: {target}: {exc}") from exc


def _scrub_path(text: str) -> str:
    """Home-scrub a path for the report (C1)."""
    return sanitize_capture(text)


# ── engine entrypoint ────────────────────────────────────────────────────


def run_backfill(
    *,
    ledger_path: str | Path | None = None,
    evidence_path: str | Path | None = None,
    dry_run: bool = True,
    lock: il.HeldLedgerLock | None = None,
) -> dict[str, Any]:
    """Run the canonical backfill and return the stable report dict (C4).

    ``dry_run`` validates and reports without writing (no lock required). Write
    mode REQUIRES ``lock`` to be a held :class:`invocation_ledger.HeldLedgerLock`
    context authorizing ``ledger_path`` (supplied by the F005 entrypoint — F002
    never self-acquires) and refuses to write otherwise.

    File-fatal evidence defects raise :class:`canonical_evidence.EvidenceFatalError`
    (caller -> exit 2, stamps nothing). Row-level defects are listed in
    ``skipped`` (exit 0).
    """
    target = Path(ledger_path) if ledger_path is not None else il.ledger_path()
    ev_path = Path(evidence_path) if evidence_path is not None else default_evidence_path()

    # Write mode: a held C8 sidecar-lock context is mandatory (C8) and is checked
    # FIRST — before any evidence load or ledger read. F002 never self-acquires;
    # it refuses to do ANY work in write mode (not even open the evidence file)
    # without the owner's lock, so a direct write without a held lock reliably
    # refuses up front rather than after partially validating evidence.
    if not dry_run and (
        not isinstance(lock, il.HeldLedgerLock) or not lock.authorizes(target)
    ):
        raise BackfillWriteError(
            "F002 backfill write mode requires a held C8 sidecar-lock context "
            "from the F005 entrypoint; refusing to write without it"
        )

    # File-fatal tier: load + structurally validate evidence (may raise).
    contract = ce.load_evidence_file(ev_path)

    if dry_run:
        records = _read_ledger(target)
        _, confirmed, already, skipped = _stamp_records(records, contract)
        return BackfillReport(
            would_stamp=confirmed,
            stamped=0,
            already_stamped=already,
            would_skip=len(skipped),
            skipped=skipped,
            ledger_path=_scrub_path(str(target)),
            evidence_path=_scrub_path(str(ev_path)),
            dry_run=True,
        ).to_dict()

    # The caller holds the lock across this whole read/validate/write/rename
    # critical section, so a concurrent append is serialized and never lost.
    records = _read_ledger(target)
    new_records, confirmed, already, skipped = _stamp_records(records, contract)
    _atomic_rewrite(target, new_records)
    return BackfillReport(
        would_stamp=0,
        stamped=confirmed,
        already_stamped=already,
        would_skip=len(skipped),
        skipped=skipped,
        ledger_path=_scrub_path(str(target)),
        evidence_path=_scrub_path(str(ev_path)),
        dry_run=False,
    ).to_dict()


__all__ = [
    "BackfillError",
    "BackfillReport",
    "BackfillWriteError",
    "ConfirmedCanonical",
    "EVIDENCE_FILENAME",
    "LedgerReadError",
    "SKIP_DURABLE_CONTRADICTION",
    "SKIP_NON_RECONSTRUCTABLE_SCRUB_TOKEN",
    "SKIP_PATH_KEY_CONFIRMATION_FAILED",
    "SKIP_RECONSTRUCTED_TEMP_CANONICAL",
    "confirm_canonical",
    "default_evidence_path",
    "run_backfill",
]
