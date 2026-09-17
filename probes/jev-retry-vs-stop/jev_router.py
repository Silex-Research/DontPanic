#!/usr/bin/env python3
"""Jev TypeSafe typed router for retry-vs-stop decision after needs_changes.

This router provides a typed decision interface for the DontPanic operator
to determine the next action after an auditor returns needs_changes.

Actions:
  - retry_implementer: Send another implementer round
  - stop_and_escalate_human: Stop the loop, escalate to human
  - trip_breaker: Trigger circuit breaker
  - reassign_implementer_model: Try a different model
  - skip_auditor: Skip auditor (rare, ceremony case)

This is a PROBE - the router is not yet live. It runs in shadow mode
to compare against the current implicit breaker heuristics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class JevAction(str, Enum):
    """Typed action enum for Jev router output."""
    
    RETRY_IMPLEMENTER = "retry_implementer"
    STOP_AND_ESCALATE_HUMAN = "stop_and_escalate_human"
    TRIP_BREAKER = "trip_breaker"
    REASSIGN_IMPLEMENTER_MODEL = "reassign_implementer_model"
    SKIP_AUDITOR = "skip_auditor"


class ReasonCode(str, Enum):
    """Reason codes for router decisions."""
    
    # Retry reasons
    FIRST_NEEDS_CHANGES = "first_needs_changes"
    PROGRESS_DETECTED = "progress_detected"
    FINDINGS_REDUCING = "findings_reducing"
    LOW_ITERATION = "low_iteration"
    
    # Stop reasons
    CONSECUTIVE_NO_PROGRESS = "consecutive_no_progress"
    HIGH_ITERATION_COUNT = "high_iteration_count"
    CORRECTNESS_DEADLOCK = "correctness_deadlock"
    ENVIRONMENTAL_BLOCKER = "environmental_blocker"
    BUDGET_EXCEEDED = "budget_exceeded"
    
    # Trip reasons
    MAX_ITERATIONS_REACHED = "max_iterations_reached"
    BREAKER_ALREADY_ACTIVE = "breaker_already_active"
    
    # Reassign reasons
    MODEL_MISMATCH = "model_mismatch"
    
    # Skip reasons
    CEREMONY_ONLY = "ceremony_only"
    
    # Unknown
    UNKNOWN = "unknown"


@dataclass
class JevInput:
    """Typed input schema for Jev router."""
    
    plan_id: str
    feature_id: str
    iteration: int
    latest_auditor_status: str
    finding_categories: list[str]
    consecutive_same_verdict: int
    breaker_state: str  # "clear" | "tripped" | "deferred"
    tokens_in_so_far: int | None
    implementer_harness: str | None
    auditor_harness: str | None
    
    @classmethod
    def from_dict(cls, d: dict) -> "JevInput":
        """Create from dictionary (e.g., from JSON)."""
        return cls(
            plan_id=d.get("plan_id", ""),
            feature_id=d.get("feature_id", ""),
            iteration=d.get("iteration", 0),
            latest_auditor_status=d.get("latest_auditor_status", ""),
            finding_categories=d.get("finding_categories", []),
            consecutive_same_verdict=d.get("consecutive_same_verdict", 1),
            breaker_state=d.get("breaker_state", "clear"),
            tokens_in_so_far=d.get("tokens_in_so_far"),
            implementer_harness=d.get("implementer_harness"),
            auditor_harness=d.get("auditor_harness"),
        )


@dataclass
class JevOutput:
    """Typed output schema for Jev router."""
    
    action: JevAction
    confidence: float  # 0.0 to 1.0
    reason_code: ReasonCode
    
    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "confidence": self.confidence,
            "reason_code": self.reason_code.value,
        }


class JevRouter:
    """Heuristic-based Jev router for retry-vs-stop decisions.
    
    This implements the baseline heuristic router that will be compared
    against the current implicit breaker logic. In production, this could
    be replaced with a learned model or TypeSafe API call.
    
    Tuned based on offline eval v2:
    - 73% of test cases with breaker_trip outcomes have iteration 0-1
    - Need to balance stopping on these vs not hurting signed_off cases
    - Current implicit DontPanic loop retries very aggressively
    
    Strategy: Use probabilistic routing based on signals. Stop more often
    when multiple risk signals are present, even at low iteration.
    """
    
    # Thresholds
    MAX_CONSECUTIVE_NO_PROGRESS = 2
    HIGH_ITERATION_THRESHOLD = 2
    MAX_ITERATION_HARD_CAP = 4
    
    def _count_risk_signals(self, input: JevInput) -> int:
        """Count risk signals that suggest stopping."""
        signals = 0
        
        # Signal 1: Not first needs_changes
        if input.iteration > 0:
            signals += 1
        
        # Signal 2: Repeated same verdict
        if input.consecutive_same_verdict >= 2:
            signals += 2  # Strong signal
        
        # Signal 3: Correctness findings present
        if "correctness" in input.finding_categories:
            signals += 1
        
        # Signal 4: High iteration
        if input.iteration >= self.HIGH_ITERATION_THRESHOLD:
            signals += 1
        
        # Signal 5: Breaker already tripped (indicating pattern)
        if input.breaker_state == "tripped":
            signals += 1
        
        return signals
    
    def route(self, input: JevInput) -> JevOutput:
        """Make a typed routing decision.
        
        Uses signal-counting approach: accumulate risk signals and decide
        based on threshold.
        """
        signals = self._count_risk_signals(input)
        
        # Strong signals threshold: if multiple risk signals, stop
        if signals >= 3:
            if input.iteration >= self.MAX_ITERATION_HARD_CAP:
                return JevOutput(
                    action=JevAction.TRIP_BREAKER,
                    confidence=0.9,
                    reason_code=ReasonCode.MAX_ITERATIONS_REACHED,
                )
            if input.consecutive_same_verdict >= self.MAX_CONSECUTIVE_NO_PROGRESS:
                return JevOutput(
                    action=JevAction.STOP_AND_ESCALATE_HUMAN,
                    confidence=0.8,
                    reason_code=ReasonCode.CONSECUTIVE_NO_PROGRESS,
                )
            return JevOutput(
                action=JevAction.STOP_AND_ESCALATE_HUMAN,
                confidence=0.7,
                reason_code=ReasonCode.HIGH_ITERATION_COUNT,
            )
        
        # Medium signals: stop if iteration is high
        if signals >= 2 and input.iteration >= 1:
            return JevOutput(
                action=JevAction.STOP_AND_ESCALATE_HUMAN,
                confidence=0.6,
                reason_code=ReasonCode.CORRECTNESS_DEADLOCK,
            )
        
        # Specific rule: consecutive same verdict of 2+ always stops
        if input.consecutive_same_verdict >= 2:
            return JevOutput(
                action=JevAction.STOP_AND_ESCALATE_HUMAN,
                confidence=0.75,
                reason_code=ReasonCode.CONSECUTIVE_NO_PROGRESS,
            )
        
        # Iteration 0 with low signals → retry
        if input.iteration == 0 and signals <= 1:
            return JevOutput(
                action=JevAction.RETRY_IMPLEMENTER,
                confidence=0.7,
                reason_code=ReasonCode.FIRST_NEEDS_CHANGES,
            )
        
        # Default: retry with lower confidence
        return JevOutput(
            action=JevAction.RETRY_IMPLEMENTER,
            confidence=0.5,
            reason_code=ReasonCode.PROGRESS_DETECTED,
        )
    
    def explain(self, input: JevInput, output: JevOutput) -> str:
        """Generate human-readable explanation for a decision."""
        action_desc = {
            JevAction.RETRY_IMPLEMENTER: "Retry with implementer",
            JevAction.STOP_AND_ESCALATE_HUMAN: "Stop and escalate to human",
            JevAction.TRIP_BREAKER: "Trip circuit breaker",
            JevAction.REASSIGN_IMPLEMENTER_MODEL: "Reassign to different model",
            JevAction.SKIP_AUDITOR: "Skip auditor",
        }
        
        reason_desc = {
            ReasonCode.FIRST_NEEDS_CHANGES: "First needs_changes on early iteration",
            ReasonCode.PROGRESS_DETECTED: "Progress potential detected",
            ReasonCode.FINDINGS_REDUCING: "Finding count is decreasing",
            ReasonCode.LOW_ITERATION: "Low iteration count, room to try again",
            ReasonCode.CONSECUTIVE_NO_PROGRESS: f"Same verdict {input.consecutive_same_verdict} consecutive times",
            ReasonCode.HIGH_ITERATION_COUNT: f"High iteration count ({input.iteration})",
            ReasonCode.CORRECTNESS_DEADLOCK: "Correctness findings persist across rounds",
            ReasonCode.ENVIRONMENTAL_BLOCKER: "Environmental reproduction failure",
            ReasonCode.BUDGET_EXCEEDED: "Budget ceiling exceeded",
            ReasonCode.MAX_ITERATIONS_REACHED: "Maximum iterations reached",
            ReasonCode.BREAKER_ALREADY_ACTIVE: "Breaker already active",
            ReasonCode.MODEL_MISMATCH: "Model may not be suited for this task",
            ReasonCode.CEREMONY_ONLY: "Findings are ceremony-only, not blocking",
            ReasonCode.UNKNOWN: "No specific rule matched",
        }
        
        return (
            f"Decision: {action_desc.get(output.action, output.action.value)}\n"
            f"Confidence: {output.confidence:.0%}\n"
            f"Reason: {reason_desc.get(output.reason_code, output.reason_code.value)}\n"
            f"Context: plan={input.plan_id}, feature={input.feature_id}, "
            f"iter={input.iteration}, consec={input.consecutive_same_verdict}"
        )


# TypeSafe API stub (for future integration)
class TypeSafeClient:
    """Stub client for TypeSafe Jev API.
    
    In production, this would make actual API calls to TypeSafe.
    For the probe, we use the heuristic router as fallback.
    """
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self.router = JevRouter()
    
    def route(self, input: JevInput) -> JevOutput:
        """Route using TypeSafe API or fallback to heuristic."""
        if self.api_key:
            # TODO: Implement actual TypeSafe API call
            # For now, fall back to heuristic
            pass
        
        return self.router.route(input)
    
    def is_available(self) -> bool:
        """Check if TypeSafe API is available."""
        return self.api_key is not None


def route_from_dict(input_dict: dict) -> dict:
    """Convenience function to route from dict input to dict output."""
    router = JevRouter()
    input = JevInput.from_dict(input_dict)
    output = router.route(input)
    return output.to_dict()


def main():
    """Demo the router with sample inputs."""
    router = JevRouter()
    
    # Sample inputs
    samples = [
        {
            "plan_id": "test-plan",
            "feature_id": "F001",
            "iteration": 0,
            "latest_auditor_status": "needs_changes",
            "finding_categories": ["correctness"],
            "consecutive_same_verdict": 1,
            "breaker_state": "clear",
            "tokens_in_so_far": 10000,
            "implementer_harness": "claude",
            "auditor_harness": "codex",
        },
        {
            "plan_id": "test-plan",
            "feature_id": "F002",
            "iteration": 2,
            "latest_auditor_status": "needs_changes",
            "finding_categories": ["correctness", "test_coverage"],
            "consecutive_same_verdict": 2,
            "breaker_state": "clear",
            "tokens_in_so_far": 50000,
            "implementer_harness": "claude",
            "auditor_harness": "codex",
        },
        {
            "plan_id": "test-plan",
            "feature_id": "F003",
            "iteration": 4,
            "latest_auditor_status": "needs_changes",
            "finding_categories": ["correctness"],
            "consecutive_same_verdict": 3,
            "breaker_state": "clear",
            "tokens_in_so_far": 100000,
            "implementer_harness": "claude",
            "auditor_harness": "codex",
        },
    ]
    
    print("Jev Router Demo")
    print("=" * 60)
    
    for i, sample in enumerate(samples, 1):
        input = JevInput.from_dict(sample)
        output = router.route(input)
        
        print(f"\nSample {i}:")
        print(router.explain(input, output))
        print("-" * 40)


if __name__ == "__main__":
    main()
