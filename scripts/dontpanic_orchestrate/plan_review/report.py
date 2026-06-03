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

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from dontpanic_orchestrate.plan_review.lint import (
    Resolvers,
    ScopeReport,
    lint_feature,
)
from dontpanic_orchestrate.plan_review.split import SplitProposal, propose_split

# ─────────────────────────────── public types ──────────────────────────────


@dataclass(frozen=True)
class FeatureScopeReport:
    """The F001 lint result for one feature plus its F002 split proposal.

    ``split`` is ``None`` for a single-surface, in-budget feature (F002 only
    proposes a partition for an ``over_surface`` / ``over_ac`` feature).
    """

    scope: ScopeReport
    split: SplitProposal | None = None


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
    feature_reports: list[FeatureScopeReport] = []
    for feature in features:
        scope = lint_feature(feature, resolvers)
        split = propose_split(feature, scope)
        feature_reports.append(FeatureScopeReport(scope=scope, split=split))
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

    if not report.flagged():
        lines.append("No scope flags — every feature is single-surface and in-budget.")
        return "\n".join(lines) + "\n"

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
