"""Plan 2026-05-11-002 v3 F003 — spec_ambiguity class tests.

Pins the new ``spec_ambiguity`` class added to the no_progress taxonomy.
The class catches the most common audit terminal-non-success seen in
practice: a low/medium documentation/naming/convention/placement finding
that's neither a real defect nor an evidence-shape disagreement, just a
spec gap where implementer + auditor both fit the spec but the spec is
silent on the disputed point.

Acceptance items pinned here:
  (1) ``spec_ambiguity`` exists in ``FindingClass`` and is non-blocking.
  (2) Plan 010 F001 iteration 1 finding (the motivating case)
      reclassifies to spec_ambiguity, not unknown.
  (3) Existing classes do not regress — high-severity, security,
      correctness, scope_overreach, env_repro all still classify the
      same way.
  (4) ``recommended_action`` template documents the operator-review-
      or-accept workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import auditor_taxonomy  # noqa: E402
from dontpanic_orchestrate.auditor_taxonomy import FindingClass  # noqa: E402


def _finding(
    *,
    severity: str,
    category: str,
    issue: str,
    evidence: str = "",
    feature_id: str | None = None,
    file: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "severity": severity,
        "category": category,
        "issue": issue,
    }
    if evidence:
        out["evidence"] = evidence
    if feature_id is not None:
        out["feature_id"] = feature_id
    if file is not None:
        out["file"] = file
    return out


# Plan 010 F001 iteration 1 finding — the motivating case. Lifted
# verbatim from docs/plans/2026-05-10-001-feat-printing-press-adapter-skill/
# audit/codex-auditor-F001-i1.json. Pre-F003 this classified as
# ``unknown`` (severity=medium + category=documentation, no env/shape
# pattern) and blocked the volley.
PLAN_010_F001_ITER1_FINDING: dict[str, Any] = {
    "severity": "medium",
    "category": "documentation",
    "feature_id": "F001",
    "issue": (
        "PP version pinning is documented in the per-service config, not "
        "in the adapter's `~/.dontpanic/adapters.json` entry as required. "
        "Evidence: F001 step requires documenting the PP version in the "
        "adapter's `adapters.json` entry (`features.json:12`), but "
        "`SKILL.md:125-129` and `SKILL.md:171-174` put `pp_version` in "
        "`~/.dontpanic/adapters/<service>.json`, while the central "
        "registry template only records "
        "`\"version_pin_source\": \"per_service_config.pp_version\"` at "
        "`ADAPTER_TEMPLATE.md:126-133`. Recommend"
    ),
    "evidence": "Extracted from auditor summary.",
}


# ───────────────────────── 1. Class & gate ─────────────────────────


class TestSpecAmbiguityClass:
    def test_enum_value_exists(self) -> None:
        """Acceptance #1: spec_ambiguity exists in the taxonomy enum."""
        assert FindingClass.SPEC_AMBIGUITY.value == "spec_ambiguity"

    def test_spec_ambiguity_not_in_blocking_classes(self) -> None:
        """Acceptance #1: spec_ambiguity is non-blocking by design."""
        assert (
            FindingClass.SPEC_AMBIGUITY
            not in auditor_taxonomy._BLOCKING_CLASSES
        )

    def test_documentation_medium_classifies_as_spec_ambiguity(self) -> None:
        finding = _finding(
            severity="medium",
            category="documentation",
            issue="README placement is ambiguous; spec doesn't say where it lives.",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.SPEC_AMBIGUITY

    def test_naming_low_classifies_as_spec_ambiguity(self) -> None:
        finding = _finding(
            severity="low",
            category="naming",
            issue="Module name uses snake_case; convention guide doesn't pin a style.",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.SPEC_AMBIGUITY

    def test_convention_medium_classifies_as_spec_ambiguity(self) -> None:
        finding = _finding(
            severity="medium",
            category="convention",
            issue="Adapter declares `applies_to` at module level; spec is silent on placement.",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.SPEC_AMBIGUITY

    def test_placement_low_classifies_as_spec_ambiguity(self) -> None:
        finding = _finding(
            severity="low",
            category="placement",
            issue="Helper file lives at scripts/_internal/ instead of scripts/utils/.",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.SPEC_AMBIGUITY


# ───────────────────────── 2. Plan 010 F001 reclassification ─────────────────────────


class TestPlan010F001Reclassification:
    """Acceptance #2: the motivating case reclassifies to
    spec_ambiguity, not unknown."""

    def test_iter1_finding_reclassifies_from_unknown_to_spec_ambiguity(
        self,
    ) -> None:
        result = auditor_taxonomy.classify_finding(
            PLAN_010_F001_ITER1_FINDING, feature_id="F001"
        )
        assert result.classification == FindingClass.SPEC_AMBIGUITY

    def test_terminal_aggregate_is_advisory(self) -> None:
        envelope = {
            "audit_status": "needs_changes",
            "findings": [PLAN_010_F001_ITER1_FINDING],
        }
        result = auditor_taxonomy.classify_terminal(
            feature_id="F001", final_audit_envelope=envelope
        )
        assert result.aggregate == FindingClass.SPEC_AMBIGUITY
        assert result.blocking is False

    def test_recommended_action_documents_review_or_accept(self) -> None:
        """Acceptance #4: recommended_action template names both paths
        (patch the spec OR accept the implementer's reading)."""
        envelope = {
            "audit_status": "needs_changes",
            "findings": [PLAN_010_F001_ITER1_FINDING],
        }
        result = auditor_taxonomy.classify_terminal(
            feature_id="F001", final_audit_envelope=envelope
        )
        action = result.recommended_action.lower()
        assert "operator-review" in action or "operator review" in action
        assert "spec" in action
        assert "accept" in action and "implementer" in action


# ───────────────────────── 3. Regression — existing classes unchanged ─────────────────────────


class TestNoRegressionOnExistingClasses:
    """Acceptance #3: spec_ambiguity does not steal findings from
    higher-priority classes — security, correctness, scope_overreach,
    env_repro all still classify the same way."""

    def test_high_severity_documentation_not_spec_ambiguity(self) -> None:
        """High-severity findings stay in implementation_defect via the
        substantive-severity heuristic — better to over-block than to
        advisory-downgrade a real defect on category alone."""
        finding = _finding(
            severity="high",
            category="documentation",
            issue="Docs falsely claim feature is shipped; production callers will misroute.",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.IMPLEMENTATION_DEFECT

    def test_critical_naming_not_spec_ambiguity(self) -> None:
        finding = _finding(
            severity="critical",
            category="naming",
            issue="Service name collision shadows the production registry entry.",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.IMPLEMENTATION_DEFECT

    def test_medium_correctness_not_spec_ambiguity(self) -> None:
        """category=correctness is in the defect set — not in the
        spec_ambiguity category gate."""
        finding = _finding(
            severity="medium",
            category="correctness",
            issue="Off-by-one in retry counter; second retry never fires.",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.IMPLEMENTATION_DEFECT

    def test_medium_security_not_spec_ambiguity(self) -> None:
        finding = _finding(
            severity="medium",
            category="security",
            issue="Token logged at debug level in non-redacted form.",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.IMPLEMENTATION_DEFECT

    def test_scope_overreach_still_wins_over_spec_ambiguity(self) -> None:
        """scope_overreach (feature_id mismatch) is checked before the
        spec_ambiguity gate, so a low/medium documentation finding
        cited against a different feature still routes as a follow-up."""
        finding = _finding(
            severity="medium",
            category="documentation",
            issue="Adjacent feature's README needs updating.",
            feature_id="F042",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.SCOPE_OVERREACH

    def test_env_repro_still_wins_over_spec_ambiguity(self) -> None:
        """env_repro patterns match before the spec_ambiguity gate.
        A low/medium documentation finding that names a sandbox blocker
        still routes as environmental."""
        finding = _finding(
            severity="medium",
            category="documentation",
            issue="Could not run docs-build script; npm test unavailable in sandbox.",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert (
            result.classification
            == FindingClass.ENVIRONMENTAL_REPRODUCTION_FAILURE
        )

    def test_evidence_shape_with_saved_evidence_still_wins(self) -> None:
        """evidence_shape (with saved evidence) is checked before
        spec_ambiguity — preserves the prior advisory routing for
        documentation findings whose dispute is the evidence format,
        not the spec."""
        finding = _finding(
            severity="medium",
            category="documentation",
            issue="Expected a screenshot of the rendered UI; received only logs.",
        )
        saved = ("evidence/ui-render-trace.log", "evidence/ui-render.png")
        result = auditor_taxonomy.classify_finding(
            finding, feature_id="F001", saved_evidence_paths=saved
        )
        assert result.classification == FindingClass.EVIDENCE_SHAPE_DISAGREEMENT

    def test_low_severity_style_still_unknown(self) -> None:
        """category=style is NOT in the spec_ambiguity category set;
        a low-severity style finding stays unknown."""
        finding = _finding(
            severity="low",
            category="style",
            issue="Minor quibble about variable naming in the helper.",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.UNKNOWN

    def test_medium_test_coverage_still_unknown(self) -> None:
        """category=test_coverage is intentionally outside both the
        defect set and the spec_ambiguity set when no env-repro pattern
        fires — falls to unknown so operator inspects."""
        finding = _finding(
            severity="medium",
            category="test_coverage",
            issue="Missing assertion on the off-path branch.",
        )
        result = auditor_taxonomy.classify_finding(finding, feature_id="F001")
        assert result.classification == FindingClass.UNKNOWN


# ───────────────────────── 4. Aggregate + INBOX wiring ─────────────────────────


class TestAggregateWithSpecAmbiguity:
    def test_pure_spec_ambiguity_terminal_is_advisory(self) -> None:
        envelope = {
            "audit_status": "needs_changes",
            "findings": [
                _finding(
                    severity="low",
                    category="placement",
                    issue="Helper lives at scripts/_internal/.",
                ),
                _finding(
                    severity="medium",
                    category="documentation",
                    issue="Adapter README is missing a glossary section.",
                ),
            ],
        }
        result = auditor_taxonomy.classify_terminal(
            feature_id="F001", final_audit_envelope=envelope
        )
        assert result.aggregate == FindingClass.SPEC_AMBIGUITY
        assert result.blocking is False

    def test_mixed_spec_ambiguity_plus_defect_remains_blocking(self) -> None:
        """Aggregate priority: implementation_defect outranks
        spec_ambiguity, blocking is True if any defect/unknown present."""
        envelope = {
            "audit_status": "needs_changes",
            "findings": [
                _finding(
                    severity="medium",
                    category="documentation",
                    issue="README placement is ambiguous.",
                ),
                _finding(
                    severity="critical",
                    category="correctness",
                    issue="Race condition in token refresh listener.",
                ),
            ],
        }
        result = auditor_taxonomy.classify_terminal(
            feature_id="F001", final_audit_envelope=envelope
        )
        assert result.aggregate == FindingClass.IMPLEMENTATION_DEFECT
        assert result.blocking is True

    def test_inbox_body_names_spec_ambiguity_and_advisory(self) -> None:
        envelope = {
            "audit_status": "needs_changes",
            "findings": [PLAN_010_F001_ITER1_FINDING],
        }
        result = auditor_taxonomy.classify_terminal(
            feature_id="F001", final_audit_envelope=envelope
        )
        body = auditor_taxonomy.format_inbox_body(result)
        assert "[spec_ambiguity]" in body
        assert "ADVISORY" in body
