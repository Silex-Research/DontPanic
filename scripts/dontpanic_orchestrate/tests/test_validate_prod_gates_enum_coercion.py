"""Regression: validate_prod_gates must accept HumanGate enum members.

Cross-repo dogfood (SpinDine v2 dispatch, 2026-05-11) hit a validator bug:
``validate_prod_gates`` typed ``human_gates`` as ``list[str]`` but
``plan_loader._load_plan`` passed ``plan.human_gates`` directly — a
``list[HumanGate]`` per the Pydantic ``Plan`` model. ``HumanGate`` is a
plain ``Enum`` (not ``StrEnum``), so set membership ``"pre_impl" in
{HumanGate.pre_impl}`` returned False and every required gate was
reported missing, even when present.

The operator reported 4 dispatch attempts blocked by this. The fix is a
defensive coerce on the validator side: enum members get their ``.value``
read before set construction so both ``list[str]`` and ``list[Enum]``
shapes round-trip correctly.

These tests pin the fix so the next StrEnum migration (or any caller that
passes raw Pydantic-typed gates) doesn't regress.
"""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dontpanic_orchestrate.plan_target import (  # noqa: E402
    PROD_REQUIRED_GATES,
    PlanTargetError,
    validate_prod_gates,
)


class _StubHumanGate(Enum):
    """Minimal mirror of the Pydantic HumanGate enum from claude/shared.

    Local stub so this test doesn't import the schema package — keeps the
    regression test loosely coupled to agent-conventions version churn.
    The .value strings must match HumanGate's enum values verbatim.
    """

    pre_impl = "pre_impl"
    pre_merge = "pre_merge"
    on_escalation = "on_escalation"
    tier_promotion = "tier_promotion"
    cost_trigger = "cost_trigger"


# ---------------------------------------------------------------------------
# The original bug: enum members passed as gates → false "missing" diagnosis
# ---------------------------------------------------------------------------


def test_enum_members_satisfy_prod_required_gates():
    """A plan declaring all PROD_REQUIRED_GATES via HumanGate enum members
    must pass — not raise. This is the SpinDine reproducer."""
    gates = [
        _StubHumanGate.pre_impl,
        _StubHumanGate.on_escalation,
        _StubHumanGate.pre_merge,
    ]
    # Should NOT raise; pre_merge is harmless extra (not in PROD_REQUIRED_GATES).
    validate_prod_gates("prod", gates)


def test_enum_members_with_missing_required_still_raises():
    """If a required gate is genuinely absent, the validator must still raise.
    Defensive coerce must not paper over real missingness."""
    gates = [
        _StubHumanGate.pre_impl,
        # on_escalation deliberately omitted
        _StubHumanGate.pre_merge,
    ]
    with pytest.raises(PlanTargetError, match=r"on_escalation"):
        validate_prod_gates("prod", gates)


def test_mixed_str_and_enum_gates_work():
    """Caller can mix strings and enum members (e.g. operator-injected
    string + Pydantic-loaded enum) and the validator must handle both."""
    gates = [_StubHumanGate.pre_impl, "on_escalation"]
    validate_prod_gates("prod", gates)


# ---------------------------------------------------------------------------
# Original string-list behavior preserved (no regression in the easy case)
# ---------------------------------------------------------------------------


def test_string_gates_still_work_for_prod():
    """Bare-string gates path remains the original supported shape."""
    validate_prod_gates("prod", ["pre_impl", "on_escalation"])


def test_string_gates_missing_still_raises():
    """Bare-string missing-gate diagnosis remains accurate."""
    with pytest.raises(PlanTargetError, match=r"on_escalation"):
        validate_prod_gates("prod", ["pre_impl"])


# ---------------------------------------------------------------------------
# Required-override path (Expansion B) also accepts enum gates
# ---------------------------------------------------------------------------


def test_enum_members_satisfy_required_override():
    """environments.json requires_gates path also coerces correctly."""
    gates = [_StubHumanGate.pre_impl, _StubHumanGate.tier_promotion]
    validate_prod_gates(
        "dev",
        gates,
        required_override=["pre_impl", "tier_promotion"],
    )


def test_enum_members_with_required_override_missing_raises():
    """Missing-gate diagnosis under required_override is also coerce-aware."""
    gates = [_StubHumanGate.pre_impl]
    with pytest.raises(PlanTargetError, match=r"tier_promotion"):
        validate_prod_gates(
            "dev",
            gates,
            required_override=["pre_impl", "tier_promotion"],
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_gates_with_prod_still_raises():
    """Empty list + prod env → both required gates missing."""
    with pytest.raises(PlanTargetError) as exc:
        validate_prod_gates("prod", [])
    msg = str(exc.value)
    for g in PROD_REQUIRED_GATES:
        assert g in msg


def test_none_gates_with_prod_still_raises():
    """None gates + prod env → both required gates missing."""
    with pytest.raises(PlanTargetError):
        validate_prod_gates("prod", None)


def test_none_gates_with_dev_passes():
    """Non-prod env without required_override is a no-op even with None gates."""
    validate_prod_gates("dev", None)
