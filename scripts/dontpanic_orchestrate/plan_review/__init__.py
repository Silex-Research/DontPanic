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

from dontpanic_orchestrate.plan_review.cross_feature import (
    CrossFeatureEditError,
    CrossFeatureFinding,
    check_cross_feature_edit,
    derive_ownership_map,
    touched_paths_from_git_state,
)
from dontpanic_orchestrate.plan_review.design_review import (
    DESIGN_TAXONOMY,
    DesignFinding,
    DesignVolleyEnvelope,
    run_design_volley,
    should_run_design_volley,
)
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
from dontpanic_orchestrate.plan_review.scope_delta import (
    ChangeKind,
    ScopeDelta,
    ScopeDeltaReport,
    changed_feature_ids,
    review_scope_delta,
)
from dontpanic_orchestrate.plan_review.sizing_gate import (
    SIZE_FLAG_KINDS,
    SizingGateResult,
    evaluate_feature,
    record_override,
    render_block_message,
    render_preflight,
)
from dontpanic_orchestrate.plan_review.split import (
    ChildFeature,
    SplitProposal,
    propose_split,
)

__all__ = [
    "SIZE_FLAG_KINDS",
    "SURFACES",
    "DESIGN_TAXONOMY",
    "ChangeKind",
    "ChildFeature",
    "CrossFeatureEditError",
    "CrossFeatureFinding",
    "DesignFinding",
    "DesignVolleyEnvelope",
    "FeatureScopeReport",
    "FlagKind",
    "ScopeDelta",
    "ScopeDeltaReport",
    "changed_feature_ids",
    "check_cross_feature_edit",
    "derive_ownership_map",
    "review_scope_delta",
    "run_design_volley",
    "should_run_design_volley",
    "touched_paths_from_git_state",
    "PlanScopeReport",
    "Resolvers",
    "ScopeFlag",
    "ScopeReport",
    "Severity",
    "SizingGateResult",
    "SplitProposal",
    "build_default_resolvers",
    "build_plan_scope_report",
    "evaluate_feature",
    "lint_feature",
    "propose_split",
    "record_override",
    "render_block_message",
    "render_preflight",
    "render_text",
    "tag_surfaces",
]
