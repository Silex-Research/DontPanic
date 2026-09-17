#!/usr/bin/env python3
"""Shadow hook interface for Jev retry-vs-stop router.

This module provides the integration point where DontPanic's supervisor
can call Jev for routing decisions WITHOUT making it the live path.

Shadow mode:
1. Supervisor makes the normal implicit decision (retry until breaker)
2. Supervisor ALSO calls Jev and logs the recommendation
3. Disagreements are logged for analysis
4. No actual behavior change

Future live mode:
1. Supervisor calls Jev
2. Jev decision determines next action
3. If Jev says stop, supervisor stops instead of retrying
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jev_router import JevAction, JevInput, JevOutput, JevRouter, TypeSafeClient

logger = logging.getLogger(__name__)


@dataclass
class ShadowResult:
    """Result of a shadow call to Jev."""
    
    timestamp: str
    plan_id: str
    feature_id: str
    iteration: int
    
    # What Jev recommended
    jev_action: str
    jev_confidence: float
    jev_reason: str
    
    # What the implicit loop would do
    implicit_action: str  # Always "retry" in current implementation
    
    # Whether they agree
    agrees: bool
    
    def to_dict(self) -> dict:
        return asdict(self)


class JevShadowHook:
    """Shadow hook for Jev router integration with DontPanic supervisor.
    
    Usage in supervisor:
    
        # At the point where we're about to retry after needs_changes:
        hook = JevShadowHook(plan_dir)
        result = hook.shadow_call(
            plan_id=plan_id,
            feature_id=feature_id,
            iteration=iteration,
            audit_status="needs_changes",
            finding_categories=finding_cats,
            consecutive_same_verdict=consec,
            breaker_state=breaker_state,
            tokens_in_so_far=tokens,
            implementer_harness=impl_harness,
            auditor_harness=aud_harness,
        )
        # Log disagreement if Jev says stop
        if not result.agrees:
            logger.info(f"Jev disagrees: {result.jev_action} ({result.jev_reason})")
        
        # Continue with implicit behavior (retry)
        ...
    """
    
    def __init__(
        self,
        plan_dir: Path,
        typesafe_api_key: str | None = None,
        log_path: Path | None = None,
    ):
        """Initialize the shadow hook.
        
        Args:
            plan_dir: Path to the plan directory (for logging)
            typesafe_api_key: Optional TypeSafe API key for LLM-based routing
            log_path: Path to write shadow results (default: plan_dir/audit/jev-shadow.jsonl)
        """
        self.plan_dir = plan_dir
        self.log_path = log_path or (plan_dir / "audit" / "jev-shadow.jsonl")
        
        # Initialize router (falls back to heuristic if no API key)
        self.client = TypeSafeClient(api_key=typesafe_api_key)
        self.router = JevRouter()
    
    def shadow_call(
        self,
        plan_id: str,
        feature_id: str,
        iteration: int,
        audit_status: str,
        finding_categories: list[str],
        consecutive_same_verdict: int,
        breaker_state: str,
        tokens_in_so_far: int | None = None,
        implementer_harness: str | None = None,
        auditor_harness: str | None = None,
    ) -> ShadowResult:
        """Make a shadow call to Jev and log the result.
        
        This does NOT change behavior - it only logs what Jev would recommend.
        """
        # Build input
        jev_input = JevInput(
            plan_id=plan_id,
            feature_id=feature_id,
            iteration=iteration,
            latest_auditor_status=audit_status,
            finding_categories=finding_categories,
            consecutive_same_verdict=consecutive_same_verdict,
            breaker_state=breaker_state,
            tokens_in_so_far=tokens_in_so_far,
            implementer_harness=implementer_harness,
            auditor_harness=auditor_harness,
        )
        
        # Get Jev recommendation
        if self.client.is_available():
            jev_output = self.client.route(jev_input)
        else:
            jev_output = self.router.route(jev_input)
        
        # Current implicit behavior is always retry
        implicit_action = "retry_implementer"
        
        # Normalize for comparison
        jev_normalized = (
            "retry" if jev_output.action == JevAction.RETRY_IMPLEMENTER
            else "stop"
        )
        implicit_normalized = "retry"
        
        result = ShadowResult(
            timestamp=datetime.now().isoformat(),
            plan_id=plan_id,
            feature_id=feature_id,
            iteration=iteration,
            jev_action=jev_output.action.value,
            jev_confidence=jev_output.confidence,
            jev_reason=jev_output.reason_code.value,
            implicit_action=implicit_action,
            agrees=(jev_normalized == implicit_normalized),
        )
        
        # Log result
        self._log_result(result)
        
        return result
    
    def _log_result(self, result: ShadowResult) -> None:
        """Append result to the shadow log file."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as f:
                f.write(json.dumps(result.to_dict()) + "\n")
        except OSError as e:
            logger.warning(f"Failed to write Jev shadow log: {e}")
    
    def get_shadow_history(self) -> list[ShadowResult]:
        """Read all shadow results from the log file."""
        if not self.log_path.exists():
            return []
        
        results = []
        for line in self.log_path.read_text().splitlines():
            if line.strip():
                try:
                    data = json.loads(line)
                    results.append(ShadowResult(**data))
                except (json.JSONDecodeError, TypeError):
                    continue
        return results
    
    def get_disagreement_summary(self) -> dict[str, Any]:
        """Get summary of disagreements for analysis."""
        history = self.get_shadow_history()
        
        if not history:
            return {"total": 0, "disagreements": 0}
        
        disagreements = [r for r in history if not r.agrees]
        
        # Group by reason
        by_reason: dict[str, int] = {}
        for d in disagreements:
            reason = d.jev_reason
            by_reason[reason] = by_reason.get(reason, 0) + 1
        
        return {
            "total": len(history),
            "disagreements": len(disagreements),
            "disagreement_rate": len(disagreements) / len(history),
            "by_reason": by_reason,
        }


def integrate_with_supervisor():
    """Example of how to integrate the shadow hook with the supervisor.
    
    This would be added to scripts/dontpanic_orchestrate/supervisor.py
    at the point where the supervisor decides to retry after needs_changes.
    """
    
    # Pseudo-code showing integration point:
    integration_example = '''
    # In supervisor.py, after auditor returns needs_changes:
    
    if aud_status == "needs_changes":
        # Shadow call to Jev (does not change behavior)
        try:
            from probes.jev_retry_vs_stop.shadow_hook import JevShadowHook
            
            hook = JevShadowHook(plan_dir)
            shadow_result = hook.shadow_call(
                plan_id=plan_id,
                feature_id=feature_id,
                iteration=iteration,
                audit_status=aud_status,
                finding_categories=extract_finding_categories(aud_data),
                consecutive_same_verdict=count_consecutive(prior_aud_status, aud_status),
                breaker_state=get_breaker_state(gate_state),
                tokens_in_so_far=get_tokens(audit_paths),
                implementer_harness=impl_harness,
                auditor_harness=aud_harness,
            )
            
            if not shadow_result.agrees:
                logger.info(
                    f"[Jev shadow] Would {shadow_result.jev_action} "
                    f"(conf={shadow_result.jev_confidence:.0%}, "
                    f"reason={shadow_result.jev_reason})"
                )
        except ImportError:
            pass  # Jev probe not installed
        
        # Continue with existing implicit retry logic...
        # (no behavior change)
    '''
    return integration_example


if __name__ == "__main__":
    # Demo the shadow hook
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        plan_dir = Path(tmpdir) / "test-plan"
        plan_dir.mkdir(parents=True)
        
        hook = JevShadowHook(plan_dir)
        
        # Simulate a shadow call
        result = hook.shadow_call(
            plan_id="test-plan",
            feature_id="F001",
            iteration=1,
            audit_status="needs_changes",
            finding_categories=["correctness"],
            consecutive_same_verdict=2,
            breaker_state="clear",
        )
        
        print("Shadow Result:")
        print(f"  Jev recommends: {result.jev_action}")
        print(f"  Confidence: {result.jev_confidence:.0%}")
        print(f"  Reason: {result.jev_reason}")
        print(f"  Agrees with implicit (retry): {result.agrees}")
        
        # Show summary
        summary = hook.get_disagreement_summary()
        print(f"\nSummary: {summary}")
