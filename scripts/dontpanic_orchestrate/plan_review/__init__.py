"""plan_review — deterministic, free plan-authoring scope lint.

Plan ``2026-06-01-001-feat-plan-review-scope-validation``.

Layer-1 of the plan-review capability: a pure module that scores each feature
record for the three plan-authoring defect classes that repeatedly stalled
onboarding-v0 (over-scope, exemplar/weak acceptance, silent prerequisites) and
emits a typed :class:`~dontpanic_orchestrate.plan_review.lint.ScopeReport`.

F001 exposes the lint core (:func:`lint_feature`); later features (F002 split
proposer, F003 ``plan-review`` CLI, the lock/dispatch gates) build on it.
"""

from __future__ import annotations

from dontpanic_orchestrate.plan_review.lint import (
    SURFACES,
    FlagKind,
    Resolvers,
    ScopeFlag,
    ScopeReport,
    Severity,
    lint_feature,
    tag_surfaces,
)
from dontpanic_orchestrate.plan_review.report import (
    FeatureScopeReport,
    PlanScopeReport,
    build_default_resolvers,
    build_plan_scope_report,
    render_text,
)
from dontpanic_orchestrate.plan_review.split import (
    ChildFeature,
    SplitProposal,
    propose_split,
)

__all__ = [
    "SURFACES",
    "ChildFeature",
    "FeatureScopeReport",
    "FlagKind",
    "PlanScopeReport",
    "Resolvers",
    "ScopeFlag",
    "ScopeReport",
    "Severity",
    "SplitProposal",
    "build_default_resolvers",
    "build_plan_scope_report",
    "lint_feature",
    "propose_split",
    "render_text",
    "tag_surfaces",
]
