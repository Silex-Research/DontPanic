"""Plan 2026-06-05-002 F006 — advisory surface-class sufficiency lint.

plan-review WARNS (never blocks in v0) when a feature makes a surface-facing claim but
names no entering-surface test/evidence. Quiet when a proof is named, or when there is
no surface claim. The trigger is the CLAIM, not the implementation language.
"""

from __future__ import annotations

from dontpanic_orchestrate.plan_review.lint import lint_feature


def _kinds(feature: dict) -> set[str]:
    return {f.kind for f in lint_feature(feature).flags}


def test_warns_on_surface_claim_without_entering_proof() -> None:
    feature = {
        "id": "FX",
        "description": "The dashboard shows the operator their pending work.",
        "acceptance": "Verified by a render test asserting the page displays the items.",
    }
    report = lint_feature(feature)
    flags = report.flags_of_kind("surface_proof_missing")
    assert len(flags) == 1
    assert flags[0].severity == "warn"  # advisory, never block in v0
    assert not report.has_block()


def test_quiet_when_entering_surface_proof_is_named() -> None:
    feature = {
        "id": "FX",
        "description": "The dashboard shows the operator their pending work.",
        "acceptance": (
            "Verified by a real-state → real-shell journey test that boots createJarvis() "
            "and asserts the rendered page."
        ),
    }
    assert "surface_proof_missing" not in _kinds(feature)


def test_quiet_when_surface_class_declared_as_proof_reference() -> None:
    feature = {
        "id": "FX",
        "description": "The screen displays the result.",
        "acceptance": "Honors the declared surface_class and its named simulator journey.",
    }
    assert "surface_proof_missing" not in _kinds(feature)


def test_non_surface_feature_is_unaffected() -> None:
    feature = {
        "id": "FX",
        "description": "Add an idempotency guard to the credit-refund helper.",
        "acceptance": "Verified by a unit test asserting a second call is a no-op.",
    }
    assert "surface_proof_missing" not in _kinds(feature)


def test_mobile_claim_without_simulator_journey_warns() -> None:
    feature = {
        "id": "FX",
        "description": "The settings screen now shows a new permission toggle.",
        "acceptance": "Verified by a ViewModel unit test of the toggle state.",
    }
    assert "surface_proof_missing" in _kinds(feature)
