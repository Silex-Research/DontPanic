"""Plan-scope report assembly + rendering (F003).

The ``dontpanic plan-review`` surface runs the F001 lint over every feature in
a plan and the F002 split proposer over each one, assembling a single typed
:class:`PlanScopeReport`. Both the human ``text`` view and the machine ``json``
view are rendered from that one source (acceptance #1) — there is no second,
parallel serialization path that could drift.

Everything here is pure data + rendering: :func:`build_plan_scope_report` takes
feature dicts and a :class:`~dontpanic_orchestrate.plan_review.lint.Resolvers`
set and returns the report; it performs no I/O and mutates nothing. The CLI
layer (``cli._plan_review_main``) is responsible for loading the plan and
building the resolver set; this module stays read-only with respect to the plan
(acceptance #2 — nothing here ever writes a plan file).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from dontpanic_orchestrate.plan_review.lint import (
    Resolvers,
    ScopeReport,
    _as_text,
    extract_named_tokens,
    lint_feature,
)
from dontpanic_orchestrate.plan_review.split import SplitProposal, propose_split

# ─────────────────────────────── public types ──────────────────────────────


@dataclass(frozen=True)
class FeatureScopeReport:
    """The F001 lint result for one feature plus its F002 split proposal.

    ``split`` is ``None`` for a single-surface, in-budget feature (F002 only
    proposes a partition for an ``over_surface`` / ``over_ac`` feature).

    ``introduced_here`` lists the symbols THIS feature declares via its
    ``introduces`` list. ``resolved_via_introduces`` lists ``(symbol,
    source_feature_id)`` pairs — symbols this feature references that resolved
    only because an EARLIER feature introduced them (not the codebase). Both
    are rendered so a reviewer can spot a feature that quietly waves a symbol
    through by introducing it (plan 2026-06-07-002).
    """

    scope: ScopeReport
    split: SplitProposal | None = None
    introduced_here: tuple[str, ...] = ()
    resolved_via_introduces: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PlanScopeReport:
    """Typed scope report for a whole plan — the one source both formats use."""

    plan_id: str
    features: tuple[FeatureScopeReport, ...] = ()

    def has_block(self) -> bool:
        """True iff any feature carries a block-severity flag (drives exit code)."""
        return any(fr.scope.has_block() for fr in self.features)

    def block_flag_count(self) -> int:
        return sum(
            1
            for fr in self.features
            for flag in fr.scope.flags
            if flag.severity == "block"
        )

    def flag_count(self) -> int:
        return sum(len(fr.scope.flags) for fr in self.features)

    def flagged(self) -> tuple[FeatureScopeReport, ...]:
        """The feature reports that fired at least one flag, in plan order."""
        return tuple(fr for fr in self.features if fr.scope.flags)

    def to_dict(self) -> dict:
        """Machine-readable rendering (acceptance #1 — same data as text)."""
        return {
            "plan_id": self.plan_id,
            "summary": {
                "feature_count": len(self.features),
                "flagged_feature_count": len(self.flagged()),
                "flag_count": self.flag_count(),
                "block_flag_count": self.block_flag_count(),
                "has_block": self.has_block(),
            },
            "features": [_feature_to_dict(fr) for fr in self.features],
        }


# ─────────────────────────────── public API ────────────────────────────────


def build_plan_scope_report(
    plan_id: str,
    features: Iterable[dict],
    resolvers: Resolvers | None = None,
) -> PlanScopeReport:
    """Lint every feature and propose a split for each, assembling the report.

    Pure: no network, no filesystem, no mutation of the inputs. F001 runs over
    every feature; F002 runs over every feature too and yields ``None`` for the
    in-budget single-surface ones, so the proposal is present exactly for the
    over-scoped (flagged) features.
    """
    base = resolvers or Resolvers()
    # Symbols introduced by features SEEN SO FAR (earlier in plan order),
    # mapped to the id of the feature that introduced each. Order-aware: a
    # feature may resolve its own + any earlier introduction, never a later one.
    introduced_by: dict[str, str] = {}

    feature_reports: list[FeatureScopeReport] = []
    for feature in features:
        feature_id = str(feature.get("id", ""))
        own = tuple(
            str(s) for s in (feature.get("introduces") or []) if isinstance(s, str) and s
        )
        # This feature resolves against the codebase vocabulary PLUS every
        # symbol introduced earlier PLUS its own introductions.
        allowed = set(introduced_by) | set(own)
        feat_resolvers = (
            dataclasses.replace(base, symbols=base.symbols | frozenset(allowed))
            if allowed
            else base
        )

        scope = lint_feature(feature, feat_resolvers)
        split = propose_split(feature, scope)

        # Provenance: which referenced symbols resolved ONLY through an earlier
        # feature's introduction (not the codebase, not this feature's own).
        referenced = {
            tok
            for tok, kind in extract_named_tokens(_as_text(feature.get("acceptance")))
            if kind == "symbol"
        }
        resolved_via = tuple(
            sorted(
                (tok, introduced_by[tok])
                for tok in referenced
                if tok in introduced_by and not base.resolves_symbol(tok)
            )
        )

        feature_reports.append(
            FeatureScopeReport(
                scope=scope,
                split=split,
                introduced_here=own,
                resolved_via_introduces=resolved_via,
            )
        )

        # Register this feature's introductions for LATER features (first
        # introducer wins, so provenance is stable).
        for sym in own:
            introduced_by.setdefault(sym, feature_id)

    return PlanScopeReport(plan_id=plan_id, features=tuple(feature_reports))


def render_text(report: PlanScopeReport) -> str:
    """Human-triage rendering of a :class:`PlanScopeReport`.

    Built from the same typed data as :meth:`PlanScopeReport.to_dict`
    (acceptance #1). Deterministic — flags and features stay in plan order.
    """
    lines: list[str] = []
    lines.append(f"plan-review: {report.plan_id}")
    lines.append(
        f"  {len(report.features)} feature(s), "
        f"{len(report.flagged())} flagged, "
        f"{report.flag_count()} flag(s) "
        f"({report.block_flag_count()} block-severity)"
    )
    verdict = "BLOCK" if report.has_block() else "OK"
    lines.append(f"  verdict: {verdict}")
    lines.append("")

    # Introductions (plan 2026-06-07-002): make declared/borrowed vocabulary
    # visible so a reviewer can spot a feature waving a symbol through. Shown
    # regardless of flags.
    intro_lines = _render_introductions(report)
    if intro_lines:
        lines.extend(intro_lines)
        lines.append("")

    if not report.flagged():
        lines.append("No scope flags — every feature is single-surface and in-budget.")
        return "\n".join(lines).rstrip("\n") + "\n"

    for fr in report.features:
        scope = fr.scope
        if not scope.flags:
            continue
        lines.append(
            f"{scope.feature_id or '(unnamed)'} "
            f"[{', '.join(scope.surfaces)}] — {scope.ac_count} AC(s)"
        )
        for flag in scope.flags:
            lines.append(f"  [{flag.severity}] {flag.kind}: {flag.evidence}")
        if fr.split is not None:
            lines.extend(_render_split_text(fr.split))
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def _render_introductions(report: PlanScopeReport) -> list[str]:
    """One labelled line per feature that introduces or borrows a symbol.

    ``introduced-here`` names the symbols a feature declares; if a feature also
    resolved a symbol through an earlier feature's introduction, that is shown
    as ``resolved-via-introduces: <symbol> from <feature-id>`` so abuse (a
    feature quietly waving a symbol through) is visible to a reviewer.
    """
    out: list[str] = []
    for fr in report.features:
        if not fr.introduced_here and not fr.resolved_via_introduces:
            continue
        fid = fr.scope.feature_id or "(unnamed)"
        if fr.introduced_here:
            out.append(f"  {fid} introduced-here: {', '.join(fr.introduced_here)}")
        for symbol, source in fr.resolved_via_introduces:
            out.append(
                f"  {fid} resolved-via-introduces: {symbol} from {source}"
            )
    if out:
        out.insert(0, "introductions:")
    return out


# ───────────────────────────── serialization ───────────────────────────────


def _feature_to_dict(fr: FeatureScopeReport) -> dict:
    scope = fr.scope
    return {
        "feature_id": scope.feature_id,
        "surfaces": list(scope.surfaces),
        "ac_count": scope.ac_count,
        "has_block": scope.has_block(),
        "flags": [
            {"kind": flag.kind, "severity": flag.severity, "evidence": flag.evidence}
            for flag in scope.flags
        ],
        "introduced_here": list(fr.introduced_here),
        "resolved_via_introduces": [list(pair) for pair in fr.resolved_via_introduces],
        "split_proposal": _split_to_dict(fr.split),
    }


def _split_to_dict(split: SplitProposal | None) -> dict | None:
    if split is None:
        return None
    return {
        "parent_id": split.parent_id,
        "conservation_ok": split.conservation_ok,
        "children": [
            {
                "provisional_id": child.provisional_id,
                "surfaces": list(child.surfaces),
                "acceptance_subset": list(child.acceptance_subset),
                "depends_on": list(child.depends_on),
            }
            for child in split.children
        ],
        "multi_surface_acs": [
            {"acceptance": text, "surfaces": list(surfaces)}
            for text, surfaces in split.multi_surface_acs
        ],
    }


def _gather_codebase_vocabulary(package_dir: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Collect the real symbol + flag vocabulary the ``dontpanic_orchestrate``
    package actually declares, by AST-walking its sources.

    Returns ``(symbols, flags)``:

      * ``symbols`` — every ``def`` / ``class`` name, module- and class-level
        assignment target, and ``Literal[...]`` string member (so a feature
        naming a real function like ``lint_feature`` or a declared taxonomy
        value like ``over_surface`` resolves instead of false-flagging
        ``missing_prereq``).
      * ``flags`` — every ``--name`` string literal in the sources (catches CLI
        flags the curated ``known_flags`` list hasn't caught up to, e.g.
        ``--allow-oversize``).

    This is the "resolve against what the system really declares" step. A token
    that exists *nowhere* in the package still fails to resolve — so the F012
    silent-prerequisite signal (a stale/undeclared capability) is preserved.
    Tests directories are skipped so test-only helpers don't pollute the set.
    """
    import ast

    symbols: set[str] = set()
    flags: set[str] = set()
    for path in package_dir.rglob("*.py"):
        parts = set(path.parts)
        if "__pycache__" in parts or "tests" in parts:
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.add(node.name)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                symbols.add(node.target.id)
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        symbols.add(tgt.id)
            elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "Literal":
                for const in ast.walk(node.slice):
                    if isinstance(const, ast.Constant) and isinstance(const.value, str):
                        symbols.add(const.value)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith("--") and len(node.value) > 2:
                    flags.add(node.value.split()[0])
    return frozenset(symbols), frozenset(flags)


def build_default_resolvers() -> Resolvers:
    """Wire the three real resolver sources F003 consults (lint.Resolvers doc).

    NOT pure — it reads the live CLI grammar and the package sources, which is
    exactly the "wire in the real sources" step the CLI layer performs once
    before the pure :func:`build_plan_scope_report` runs:

      * ``commands`` — the CLI subcommand vocabulary
        (:func:`command_validation.known_subcommands`).
      * ``flags`` — every flag the CLI declares
        (:func:`command_validation.known_flags`) plus any ``--name`` literal the
        sources declare (so a freshly-added flag resolves before the curated
        list catches up).
      * ``symbols`` — the package's real declared vocabulary: module names plus
        every ``def`` / ``class`` / constant / ``Literal`` member the sources
        define (so an AC naming ``lint_feature`` or ``over_surface`` resolves
        against the capability that really exists).

    A token an AC names that resolves against none of these stays a
    ``missing_prereq`` block — the silent-prerequisite signal F001 scores for
    (the token genuinely exists nowhere in the system).
    """
    from dontpanic_orchestrate import command_validation

    package_dir = Path(__file__).resolve().parents[1]
    module_names = {
        path.stem
        for path in package_dir.glob("*.py")
        if not path.stem.startswith("_")
    }
    gathered_symbols, gathered_flags = _gather_codebase_vocabulary(package_dir)
    return Resolvers(
        commands=command_validation.known_subcommands(),
        flags=command_validation.known_flags() | gathered_flags,
        symbols=frozenset(module_names) | gathered_symbols,
    )


def _render_split_text(split: SplitProposal) -> list[str]:
    lines = [f"  suggested split → {len(split.children)} child feature(s):"]
    for child in split.children:
        deps = ", ".join(child.depends_on) or "(none)"
        lines.append(
            f"    {child.provisional_id} [{', '.join(child.surfaces)}] "
            f"— {len(child.acceptance_subset)} AC(s), depends_on: {deps}"
        )
    if split.multi_surface_acs:
        lines.append("  multi-surface AC(s) to sharpen:")
        for text, surfaces in split.multi_surface_acs:
            clipped = text if len(text) <= 80 else text[:79] + "…"
            lines.append(f"    [{', '.join(surfaces)}] {clipped}")
    return lines
