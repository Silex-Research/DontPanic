"""ADR/doc intent extraction + as-built reconciliation (plan 2026-06-08-001, Plan B).

Plan A reserved the architecture view-state ``layers.intent`` and ``layers.diff``
empty. This module fills them:

  * :func:`extract_adr_claims` reads decision documents under ``docs/adr/`` into
    DECLARED intent claims (``source_kind=adr``, ``evidence_basis=declared``) —
    intent, never an as-built fact. Absence degrades to ``[]`` (most repos have
    no ADRs); it never raises.
  * :func:`reconcile_intent` compares each claim's referenced symbols against the
    as-built graph and emits a conservative diff keyed by the Plan A taxonomy:
    ``aligned`` (reference resolves), ``documented_unimplemented`` (it does not),
    ``stale_adr`` (a superseded decision). Other taxonomy values stay reserved
    until code-extractor coverage (Plan C) can defend them.

Pure + deterministic: no network, no mutation of inputs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.plan_review.lint import extract_named_tokens

ADR_DIRS = ("docs/adr", "docs/adrs", "docs/decisions")
_ID_RE = re.compile(r"^#\s*(ADR-\d+)\s*[:\-—]\s*(.+?)\s*$", re.MULTILINE)
_STATUS_RE = re.compile(r"^\s*Status\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_DATE_RE = re.compile(r"^\s*Date\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_DECISION_RE = re.compile(
    r"^##\s*Decision\s*$(.*?)(?=^##\s|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL
)

_STALE_STATUSES = {"superseded", "deprecated", "withdrawn", "rejected", "obsolete"}


def _claim_symbols(decision_text: str) -> list[str]:
    """The code symbols a Decision section names (reusing the lint tokenizer)."""
    seen: list[str] = []
    for tok, kind in extract_named_tokens(decision_text):
        if kind == "symbol" and tok not in seen:
            seen.append(tok)
    return seen


def extract_adr_claims(repo_root: Path) -> list[dict[str, Any]]:
    """Parse every decision doc into a declared intent claim. Never raises."""
    claims: list[dict[str, Any]] = []
    for rel in ADR_DIRS:
        d = repo_root / rel
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            m = _ID_RE.search(text)
            if m:
                adr_id, title = m.group(1), m.group(2).strip()
            else:
                adr_id, title = path.stem, path.stem.replace("-", " ")
            status_m = _STATUS_RE.search(text)
            status = (status_m.group(1).strip().lower() if status_m else "unknown")
            date_m = _DATE_RE.search(text)
            dec_m = _DECISION_RE.search(text)
            decision = (dec_m.group(1).strip() if dec_m else "").strip()
            source_path = str(path.relative_to(repo_root))
            claims.append(
                {
                    "id": adr_id,
                    "title": title,
                    "status": status,
                    "date": date_m.group(1).strip() if date_m else None,
                    "source_path": source_path,
                    "source_kind": "adr",
                    "evidence_basis": "declared",
                    "confidence": "medium",  # declared + cites a source_path
                    "decision": decision,
                    "references": _claim_symbols(decision or text),
                    "provenance": {
                        "source_path": source_path,
                        "resolved": True,
                        "method": "adr_intent_extractor",
                    },
                }
            )
    claims.sort(key=lambda c: c["id"])
    return claims


def _as_built_symbol_index(nodes: list[dict[str, Any]]) -> set[str]:
    """Symbols the as-built graph can defend: module/file basenames + public symbols."""
    index: set[str] = set()
    for n in nodes:
        if n.get("source_kind") == "external" or n.get("unresolved"):
            continue  # only real as-built code/manifest nodes count as "implemented"
        sp = n.get("source_path")
        if isinstance(sp, str) and sp:
            index.add(sp)
            index.add(sp.rsplit("/", 1)[-1])
            index.add(sp.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        for sym in n.get("public_symbols") or []:
            if isinstance(sym, str):
                index.add(sym)
        title = n.get("title")
        if isinstance(title, str):
            index.add(title)
            index.add(title.split(".")[-1])
    return index


def _resolves(symbol: str, index: set[str]) -> bool:
    return symbol in index or symbol.split(".", 1)[0] in index or symbol.rsplit(".", 1)[-1] in index


def reconcile_intent(
    claims: list[dict[str, Any]], nodes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Diff declared claims against the as-built graph. Conservative + deterministic.

    Emits only evidence-backed entries:
      * ``stale_adr`` — the decision's status marks it superseded/deprecated.
      * ``aligned`` — a referenced symbol resolves to an as-built node.
      * ``documented_unimplemented`` — a referenced symbol resolves to nothing.
    A claim with no references yields no per-symbol entry (nothing to defend).
    """
    index = _as_built_symbol_index(nodes)
    diff: list[dict[str, Any]] = []
    for claim in claims:
        cid = claim.get("id")
        if claim.get("status") in _STALE_STATUSES:
            diff.append(
                {
                    "taxonomy": "stale_adr",
                    "claim_id": cid,
                    "symbol": None,
                    "detail": f"{cid} is {claim.get('status')}; its intent may no longer hold.",
                }
            )
        for symbol in claim.get("references") or []:
            aligned = _resolves(symbol, index)
            diff.append(
                {
                    "taxonomy": "aligned" if aligned else "documented_unimplemented",
                    "claim_id": cid,
                    "symbol": symbol,
                    "detail": (
                        f"{symbol} declared by {cid} resolves to an as-built node."
                        if aligned
                        else f"{symbol} declared by {cid} has no as-built evidence."
                    ),
                }
            )
    diff.sort(key=lambda e: (e["claim_id"] or "", e["taxonomy"], e["symbol"] or ""))
    return diff
