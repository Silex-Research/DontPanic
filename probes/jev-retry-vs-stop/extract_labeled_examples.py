#!/usr/bin/env python3
"""Extract labeled examples for Jev retry-vs-stop router from DontPanic plan receipts.

Ground truth derivation:
- Each (plan, feature, iteration) where audit_status == 'needs_changes' is an example
- Label is derived from what actually happened next:
  - If feature eventually signed_off by AUDITOR: retry_implementer was correct
  - If feature verified by OPERATOR (not auditor): stop_and_escalate_human (human needed)
  - If breaker tripped without resolution: trip_breaker

Key insight: "operator" in verified_by means human intervention was required,
so the automated retry loop was not sufficient.

Schema (input):
  plan_id, feature_id, iteration, latest_auditor_status, finding_categories[],
  consecutive_same_verdict, breaker_state, tokens_in_so_far|null,
  implementer_harness, auditor_harness

Schema (output action):
  retry_implementer | stop_and_escalate_human | trip_breaker |
  reassign_implementer_model | skip_auditor
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class LabeledExample:
    """Single labeled example for Jev router training/eval."""
    
    plan_id: str
    feature_id: str
    iteration: int
    latest_auditor_status: str
    finding_categories: list[str]
    consecutive_same_verdict: int
    breaker_state: str
    tokens_in_so_far: int | None
    implementer_harness: str | None
    auditor_harness: str | None
    
    ground_truth_action: str
    ground_truth_reason: str
    
    rounds_until_outcome: int
    final_outcome: str
    breaker_reason: str | None = None
    
    def to_dict(self) -> dict:
        return {
            "input": {
                "plan_id": self.plan_id,
                "feature_id": self.feature_id,
                "iteration": self.iteration,
                "latest_auditor_status": self.latest_auditor_status,
                "finding_categories": self.finding_categories,
                "consecutive_same_verdict": self.consecutive_same_verdict,
                "breaker_state": self.breaker_state,
                "tokens_in_so_far": self.tokens_in_so_far,
                "implementer_harness": self.implementer_harness,
                "auditor_harness": self.auditor_harness,
            },
            "ground_truth": {
                "action": self.ground_truth_action,
                "reason": self.ground_truth_reason,
            },
            "metadata": {
                "rounds_until_outcome": self.rounds_until_outcome,
                "final_outcome": self.final_outcome,
                "breaker_reason": self.breaker_reason,
            },
        }


def parse_iso_datetime(s: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def load_audit_envelopes(plan_dir: Path) -> list[dict]:
    """Load all audit envelopes for a plan."""
    audit_dir = plan_dir / "audit"
    if not audit_dir.exists():
        return []
    
    envelopes = []
    
    for f in sorted(audit_dir.iterdir()):
        if not f.name.endswith(".json"):
            continue
        if f.name.startswith("gate-state") or f.name.startswith("signoff"):
            continue
        if f.name.startswith("operator-") or f.name.startswith("patch-") or f.name.startswith("terminal-"):
            continue
        if f.name.startswith("plan-run"):
            continue
            
        try:
            data = json.loads(f.read_text())
            if not isinstance(data, dict):
                continue
                
            data["_file"] = f.name
            data["_path"] = str(f)
            
            name = f.name[:-5]  # Remove .json
            parts = name.split("-")
            
            harness = parts[0] if parts else None
            role = parts[1] if len(parts) > 1 else None
            
            feature_id = None
            iteration = 0
            
            for p in parts[2:]:
                if p.startswith("F") and len(p) > 1 and p[1:].isdigit():
                    feature_id = p
                elif p.startswith("i") and len(p) > 1 and p[1:].isdigit():
                    iteration = int(p[1:])
            
            data["_harness"] = harness
            data["_role"] = role or data.get("agent_role")
            data["_feature"] = feature_id or "global"
            data["_iter"] = iteration
            
            completed = parse_iso_datetime(data.get("completed_at"))
            started = parse_iso_datetime(data.get("started_at"))
            data["_time"] = completed or started
            
            envelopes.append(data)
            
        except (json.JSONDecodeError, OSError):
            continue
    
    return sorted(envelopes, key=lambda x: (x.get("_feature", ""), x.get("_iter", 0)))


def load_gate_state(plan_dir: Path) -> dict | None:
    """Load gate-state.json for a plan."""
    gate_state_path = plan_dir / "audit" / "gate-state.json"
    if not gate_state_path.exists():
        return None
    try:
        return json.loads(gate_state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def load_features(plan_dir: Path) -> list[dict]:
    """Load features.json for a plan."""
    features_path = plan_dir / "features.json"
    if not features_path.exists():
        return []
    try:
        data = json.loads(features_path.read_text())
        return data.get("features", [])
    except (json.JSONDecodeError, OSError):
        return []


def extract_finding_categories(envelope: dict) -> list[str]:
    """Extract finding categories from an audit envelope."""
    findings = envelope.get("findings", [])
    categories = set()
    for f in findings:
        if isinstance(f, dict):
            cat = f.get("category")
            if cat:
                categories.add(cat)
    return sorted(categories)


def get_breaker_trips(gate_state: dict | None) -> list[dict]:
    """Extract all breaker trip events from gate state."""
    if not gate_state:
        return []
    
    trips = []
    for event in gate_state.get("history", []):
        if event.get("action") == "breaker_trip":
            event["_time"] = parse_iso_datetime(event.get("at"))
            trips.append(event)
    
    return sorted(trips, key=lambda x: x.get("_time") or datetime.min)


@dataclass
class FeatureOutcome:
    """Outcome for a single feature."""
    feature_id: str
    passes: bool
    verified_by: list[str]  # ["codex"], ["operator"], ["codex", "operator"], etc.
    has_auditor_signoff: bool  # True if any auditor envelope has signed_off
    

def get_feature_outcomes(
    features: list[dict],
    audits: list[dict],
) -> dict[str, FeatureOutcome]:
    """Get outcome for each feature."""
    outcomes = {}
    
    # Check features.json
    for f in features:
        fid = f.get("id")
        if not fid:
            continue
        
        passes = f.get("passes", False) is True
        verified_by = f.get("verified_by") or []
        if isinstance(verified_by, str):
            verified_by = [verified_by]
        
        outcomes[fid] = FeatureOutcome(
            feature_id=fid,
            passes=passes,
            verified_by=verified_by,
            has_auditor_signoff=False,
        )
    
    # Check audit envelopes for auditor signoffs
    for audit in audits:
        if audit.get("_role") != "auditor":
            continue
        
        fid = audit.get("_feature", "global")
        status = audit.get("audit_status")
        
        if status == "signed_off":
            if fid in outcomes:
                outcomes[fid].has_auditor_signoff = True
            else:
                # Feature not in features.json but has signoff
                outcomes[fid] = FeatureOutcome(
                    feature_id=fid,
                    passes=True,
                    verified_by=[audit.get("agent", "auditor")],
                    has_auditor_signoff=True,
                )
    
    return outcomes


def count_consecutive_same_verdict(auditor_audits: list[dict], current_idx: int) -> int:
    """Count consecutive same verdict leading up to current audit."""
    if current_idx < 0 or current_idx >= len(auditor_audits):
        return 1
    
    current_status = auditor_audits[current_idx].get("audit_status")
    count = 1
    
    for i in range(current_idx - 1, -1, -1):
        if auditor_audits[i].get("audit_status") == current_status:
            count += 1
        else:
            break
    
    return count


def derive_ground_truth(
    current_audit: dict,
    remaining_auditor_audits: list[dict],
    feature_outcome: FeatureOutcome | None,
    breaker_trips: list[dict],
    current_time: datetime | None,
    current_iteration: int = 0,
    consecutive_same_verdict: int = 1,
) -> tuple[str, str, int, str, str | None]:
    """Derive ground truth action from what actually happened.
    
    Refined labeling based on eval analysis:
    - Auditor signoff → retry was correct
    - Operator verified → depends on how many rounds remained
      - If many rounds remained (>2), retry was partially justified
      - If few rounds remained, should have escalated earlier
    - Breaker tripped → should have stopped (especially if immediate)
    
    The key insight: "operator_verified" is NOT the same as "should have stopped
    immediately". The operator often verifies AFTER productive retries.
    
    Returns: (action, reason, rounds_until_outcome, final_outcome, breaker_reason)
    """
    # Find breaker trips that happened AFTER this audit
    future_trips = []
    if current_time:
        for trip in breaker_trips:
            trip_time = trip.get("_time")
            if trip_time and trip_time > current_time:
                future_trips.append(trip)
    else:
        future_trips = breaker_trips
    
    # Calculate rounds remaining
    rounds_remaining = len([
        a for a in remaining_auditor_audits 
        if a.get("audit_status") not in (None,)
    ])
    
    # Check for breaker trips FIRST - this is the clearest signal
    if future_trips:
        first_trip = future_trips[0]
        reason = first_trip.get("reason", "")
        gate = first_trip.get("gate", "")
        trip_time = first_trip.get("_time")
        
        # Count rounds until trip
        rounds_until_trip = 0
        for a in remaining_auditor_audits:
            a_time = a.get("_time")
            if a_time and trip_time and a_time < trip_time:
                rounds_until_trip += 1
            else:
                break
        
        # Immediate or next-round trip = should have stopped
        if rounds_until_trip <= 1:
            if "no_progress" in gate or "diminishing" in gate:
                return ("stop_and_escalate_human", "no_progress_trip", rounds_until_trip, "breaker_trip", reason)
            elif "iteration_cap" in gate:
                return ("trip_breaker", "iteration_cap_reached", rounds_until_trip, "breaker_trip", reason)
            elif "environmental" in gate:
                return ("stop_and_escalate_human", "environmental_blocker", rounds_until_trip, "breaker_trip", reason)
            else:
                return ("stop_and_escalate_human", "breaker_immediate", rounds_until_trip, "breaker_trip", reason)
        else:
            # Made some progress before hitting breaker - retry was justified
            return ("retry_implementer", "progress_before_breaker", rounds_until_trip, "breaker_trip", reason)
    
    # Check feature outcome
    if feature_outcome:
        if feature_outcome.has_auditor_signoff:
            # Auditor eventually signed off - retry was correct
            return (
                "retry_implementer",
                "auditor_eventually_signed_off",
                rounds_remaining,
                "signed_off",
                None,
            )
        elif feature_outcome.passes:
            # Feature passed but required operator intervention
            if "operator" in feature_outcome.verified_by:
                # Nuanced: was retry productive or futile?
                # If many rounds remained, retry contributed to progress
                # If few rounds remained OR high consecutive verdict, should have escalated
                if rounds_remaining >= 2:
                    # Multiple productive rounds before operator - retry was justified
                    return (
                        "retry_implementer",
                        "productive_before_operator",
                        rounds_remaining,
                        "operator_verified",
                        None,
                    )
                elif consecutive_same_verdict >= 2 or current_iteration >= 2:
                    # Stuck pattern - should have escalated
                    return (
                        "stop_and_escalate_human",
                        "required_operator_intervention",
                        rounds_remaining,
                        "operator_verified",
                        None,
                    )
                else:
                    # Early in the loop - retry was reasonable to try
                    return (
                        "retry_implementer",
                        "early_loop_operator_verified",
                        rounds_remaining,
                        "operator_verified",
                        None,
                    )
            else:
                return (
                    "retry_implementer",
                    "verified_without_operator",
                    rounds_remaining,
                    "signed_off",
                    None,
                )
    
    # No clear resolution
    return ("stop_and_escalate_human", "no_resolution", 0, "abandoned", None)


def extract_examples_from_plan(plan_dir: Path) -> list[LabeledExample]:
    """Extract all labeled examples from a single plan directory."""
    examples = []
    
    gate_state = load_gate_state(plan_dir)
    features = load_features(plan_dir)
    audits = load_audit_envelopes(plan_dir)
    breaker_trips = get_breaker_trips(gate_state)
    
    if not audits:
        return examples
    
    # Get feature outcomes
    feature_outcomes = get_feature_outcomes(features, audits)
    
    # Group audits by feature
    feature_audits: dict[str, list[dict]] = {}
    for a in audits:
        fid = a.get("_feature", "global")
        if fid not in feature_audits:
            feature_audits[fid] = []
        feature_audits[fid].append(a)
    
    plan_id = plan_dir.name
    
    # Process each feature
    for feature_id, f_audits in feature_audits.items():
        auditor_audits = [a for a in f_audits if a.get("_role") == "auditor"]
        
        if not auditor_audits:
            continue
        
        # Get feature outcome
        outcome = feature_outcomes.get(feature_id)
        
        for idx, audit in enumerate(auditor_audits):
            status = audit.get("audit_status")
            
            # Only extract examples for needs_changes verdicts
            if status != "needs_changes":
                continue
            
            # Find the corresponding implementer audit
            impl_audit = None
            iteration = audit.get("_iter", 0)
            for a in f_audits:
                if a.get("_role") == "implementer" and a.get("_iter") == iteration:
                    impl_audit = a
                    break
            
            # Extract features
            consecutive = count_consecutive_same_verdict(auditor_audits, idx)
            finding_cats = extract_finding_categories(audit)
            
            # Get harness info
            impl_harness = impl_audit.get("agent") if impl_audit else audit.get("_harness")
            aud_harness = audit.get("agent")
            
            # Get tokens
            quota = audit.get("quota_consumed", {})
            tokens_in = quota.get("tokens_in") if quota else None
            
            # Get remaining auditor audits
            remaining = auditor_audits[idx + 1:]
            
            # Derive ground truth
            action, reason, rounds_until, final_outcome, breaker_reason = derive_ground_truth(
                audit,
                remaining,
                outcome,
                breaker_trips,
                audit.get("_time"),
                current_iteration=iteration,
                consecutive_same_verdict=consecutive,
            )
            
            # Determine breaker state at this point
            breaker_state = "clear"
            current_time = audit.get("_time")
            if current_time:
                for trip in breaker_trips:
                    trip_time = trip.get("_time")
                    if trip_time and trip_time <= current_time:
                        breaker_state = "tripped"
                        break
            
            example = LabeledExample(
                plan_id=plan_id,
                feature_id=feature_id,
                iteration=iteration,
                latest_auditor_status=status,
                finding_categories=finding_cats,
                consecutive_same_verdict=consecutive,
                breaker_state=breaker_state,
                tokens_in_so_far=tokens_in,
                implementer_harness=impl_harness,
                auditor_harness=aud_harness,
                ground_truth_action=action,
                ground_truth_reason=reason,
                rounds_until_outcome=rounds_until,
                final_outcome=final_outcome,
                breaker_reason=breaker_reason,
            )
            examples.append(example)
    
    return examples


def extract_all_examples(plans_root: Path) -> list[LabeledExample]:
    """Extract all labeled examples from all plans."""
    examples = []
    
    if not plans_root.exists():
        return examples
    
    for plan_dir in sorted(plans_root.iterdir()):
        if not plan_dir.is_dir():
            continue
        if plan_dir.name.startswith("."):
            continue
        
        plan_examples = extract_examples_from_plan(plan_dir)
        examples.extend(plan_examples)
    
    return examples


def print_summary(examples: list[LabeledExample]) -> None:
    """Print a summary of extracted examples."""
    print(f"\n{'='*60}")
    print(f"Labeled Examples Summary")
    print(f"{'='*60}")
    print(f"Total examples: {len(examples)}")
    
    # Count by action
    actions = {}
    for e in examples:
        action = e.ground_truth_action
        actions[action] = actions.get(action, 0) + 1
    
    print(f"\nGround truth action distribution:")
    for action, count in sorted(actions.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(examples) if examples else 0
        print(f"  {action}: {count} ({pct:.1f}%)")
    
    # Count by reason
    reasons = {}
    for e in examples:
        reason = e.ground_truth_reason
        reasons[reason] = reasons.get(reason, 0) + 1
    
    print(f"\nGround truth reason distribution:")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(examples) if examples else 0
        print(f"  {reason}: {count} ({pct:.1f}%)")
    
    # Count by outcome
    outcomes = {}
    for e in examples:
        outcome = e.final_outcome
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    
    print(f"\nFinal outcome distribution:")
    for outcome, count in sorted(outcomes.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(examples) if examples else 0
        print(f"  {outcome}: {count} ({pct:.1f}%)")
    
    # Consecutive verdict stats
    consec_counts = [e.consecutive_same_verdict for e in examples]
    if consec_counts:
        print(f"\nConsecutive same verdict:")
        print(f"  Mean: {sum(consec_counts)/len(consec_counts):.2f}")
        print(f"  Max: {max(consec_counts)}")
        from collections import Counter
        consec_dist = Counter(consec_counts)
        print(f"  Distribution: {dict(sorted(consec_dist.items()))}")
    
    # Finding categories
    all_cats = set()
    for e in examples:
        all_cats.update(e.finding_categories)
    print(f"\nUnique finding categories: {len(all_cats)}")
    if all_cats:
        print(f"  {sorted(all_cats)}")
    
    # Plans coverage
    plans = set(e.plan_id for e in examples)
    print(f"\nUnique plans: {len(plans)}")
    
    # Class balance for eval
    retry_count = sum(1 for e in examples if e.ground_truth_action == "retry_implementer")
    stop_count = sum(1 for e in examples if e.ground_truth_action in ("stop_and_escalate_human", "trip_breaker"))
    print(f"\nClass balance (retry vs stop):")
    print(f"  retry_implementer: {retry_count} ({100*retry_count/len(examples):.1f}%)")
    print(f"  stop/escalate: {stop_count} ({100*stop_count/len(examples):.1f}%)")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Extract labeled examples for Jev retry-vs-stop router"
    )
    parser.add_argument(
        "--plans-root",
        type=Path,
        default=Path("/workspace/docs/plans"),
        help="Root directory containing plan directories",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/workspace/probes/jev-retry-vs-stop/labeled_examples.json"),
        help="Output JSON file path",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print summary statistics",
    )
    
    args = parser.parse_args()
    
    print(f"Scanning plans at: {args.plans_root}")
    examples = extract_all_examples(args.plans_root)
    
    if args.summary:
        print_summary(examples)
    
    # Write output
    output_data = {
        "schema_version": "1.0",
        "experience": "jev-probe-retry-vs-stop-after-needs-changes",
        "extracted_at": datetime.now().isoformat(),
        "source": str(args.plans_root),
        "total_examples": len(examples),
        "examples": [e.to_dict() for e in examples],
    }
    
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output_data, indent=2))
    print(f"\nWrote {len(examples)} examples to: {args.output}")


if __name__ == "__main__":
    main()
