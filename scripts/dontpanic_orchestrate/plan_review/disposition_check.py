"""Plan 2026-06-05-004 F005 — advisory plan-review disposition check (v0 = warn).

Ties F001-F004 together: derive a plan's canonical surfaces, resolve each surface's
sufficiency pack, validate the plan's conventions ledger, and emit an ADVISORY finding
per undisposed / invalid / applied-without-evidence item. Never blocks in v0; BLOCK
escalation for user-facing / mutation / security surfaces is deferred (D003/D009).
Demand-gated stub surfaces (empty packs) never warn.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from dontpanic_orchestrate.conventions_ledger import LedgerEntry, validate_dispositions
from dontpanic_orchestrate.sufficiency_packs import get_pack
from dontpanic_orchestrate.surface_derivation import derive_surfaces

_REF = "docs/qa-sufficiency-contract.md"
_HINT = {
    "missing": "no disposition recorded",
    "invalid": "invalid disposition (unknown, or non-applied without a reason)",
    "applied-without-evidence": "marked applied but names no evidence",
}


@dataclass(frozen=True)
class DispositionFinding:
    """One advisory disposition gap. Always warn severity in v0."""

    surface: str
    item_id: str
    status: str
    severity: str = "warn"

    @property
    def message(self) -> str:
        why = _HINT.get(self.status, self.status)
        return (
            f"[{self.surface}] convention '{self.item_id}' — {why}; "
            f"record a disposition in conventions.json (advisory in v0 — see {_REF})"
        )


def check_plan_dispositions(
    *,
    declared: Iterable[str] = (),
    paths: Iterable[str] = (),
    text: str = "",
    ledger: Mapping[str, LedgerEntry] | None = None,
) -> list[DispositionFinding]:
    """Return advisory disposition findings for a plan (warn-only, deterministic)."""
    ledger = dict(ledger or {})
    derivation = derive_surfaces(declared=declared, paths=paths, text=text)
    findings: list[DispositionFinding] = []
    for surface in sorted(derivation.canonical):
        pack = get_pack(surface)
        if not pack:  # demand-gated stub or unknown -> never warn
            continue
        statuses = validate_dispositions(pack, ledger)
        for item_id in sorted(statuses):
            status = statuses[item_id]
            if status != "disposed-ok":
                findings.append(DispositionFinding(surface, item_id, status))
    return findings
