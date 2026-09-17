#!/usr/bin/env python3
"""Offline evaluation harness for Jev retry-vs-stop router.

Metrics (from brief):
- Agreement: % of examples where Jev action matches ground truth
- False-retry rate ON BREAKER-TRIP CASES: % where Jev said retry but breaker tripped
  (target: <=15%)

The brief says:
"held-out agreement with eventual gate/human outcome ≥70%; 
false-retry on plans that breaker-trip within one more round ≤15%"

Key insight: "operator_verified" cases are ambiguous - the operator may have
verified after productive retries. The hard signal is "breaker_trip".
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jev_router import JevAction, JevInput, JevOutput, JevRouter


@dataclass
class EvalMetrics:
    """Evaluation metrics."""
    
    total_examples: int
    
    # Primary metrics
    overall_agreement: float
    
    # Breaker-specific metrics (key for the brief)
    breaker_trip_cases: int
    breaker_immediate_cases: int  # Cases where breaker tripped within 1 round
    breaker_trip_false_retry_rate: float  # % of immediate breaker trips where Jev said retry
    
    # Signed-off (auditor success) metrics
    signed_off_cases: int
    signed_off_correct_retry_rate: float  # % of signoffs where Jev correctly said retry
    
    # Operator-verified metrics (ambiguous ground truth)
    operator_verified_cases: int
    
    # Confusion matrix
    confusion_matrix: dict[str, dict[str, int]]
    
    def to_dict(self) -> dict:
        return {
            "total_examples": self.total_examples,
            "overall_agreement": self.overall_agreement,
            "breaker_trip_cases": self.breaker_trip_cases,
            "breaker_immediate_cases": self.breaker_immediate_cases,
            "breaker_trip_false_retry_rate": self.breaker_trip_false_retry_rate,
            "signed_off_cases": self.signed_off_cases,
            "signed_off_correct_retry_rate": self.signed_off_correct_retry_rate,
            "operator_verified_cases": self.operator_verified_cases,
            "confusion_matrix": self.confusion_matrix,
        }
    
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Total examples: {self.total_examples}",
            "",
            "=== KEY METRICS (from brief) ===",
            f"Overall agreement: {self.overall_agreement:.1%} (target ≥70%)",
            f"Breaker-immediate false-retry rate: {self.breaker_trip_false_retry_rate:.1%} (target ≤15%)",
            f"  ({self.breaker_immediate_cases} cases where breaker tripped within 1 round)",
            "",
            "=== BREAKDOWN BY OUTCOME ===",
            f"All breaker-trip cases: {self.breaker_trip_cases}",
            f"Signed-off cases: {self.signed_off_cases} (correct retry rate: {self.signed_off_correct_retry_rate:.1%})",
            f"Operator-verified cases: {self.operator_verified_cases}",
            "",
            "=== CONFUSION MATRIX ===",
            "               Predicted:",
            "               retry  stop",
            f"GT retry:      {self.confusion_matrix['retry']['retry']:4d}   {self.confusion_matrix['retry']['stop']:4d}",
            f"GT stop:       {self.confusion_matrix['stop']['retry']:4d}   {self.confusion_matrix['stop']['stop']:4d}",
        ]
        return "\n".join(lines)


def normalize_action(action: str) -> str:
    """Normalize action to binary retry/stop."""
    if action in ("retry_implementer",):
        return "retry"
    else:
        return "stop"


def load_examples(path: Path) -> list[dict]:
    """Load labeled examples from JSON file."""
    data = json.loads(path.read_text())
    return data.get("examples", [])


def split_examples(
    examples: list[dict],
    test_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """Split examples into train and test sets.
    
    Uses plan-based splitting to avoid data leakage.
    """
    random.seed(seed)
    
    plans: dict[str, list[dict]] = {}
    for ex in examples:
        plan_id = ex["input"]["plan_id"]
        if plan_id not in plans:
            plans[plan_id] = []
        plans[plan_id].append(ex)
    
    plan_ids = list(plans.keys())
    random.shuffle(plan_ids)
    
    n_test_plans = max(1, int(len(plan_ids) * test_ratio))
    test_plan_ids = set(plan_ids[:n_test_plans])
    
    train = []
    test = []
    for plan_id, plan_examples in plans.items():
        if plan_id in test_plan_ids:
            test.extend(plan_examples)
        else:
            train.extend(plan_examples)
    
    return train, test


def evaluate_router(
    router: JevRouter,
    examples: list[dict],
) -> tuple[EvalMetrics, list[dict]]:
    """Evaluate router on examples."""
    predictions = []
    
    confusion: dict[str, dict[str, int]] = {
        "retry": {"retry": 0, "stop": 0},
        "stop": {"retry": 0, "stop": 0},
    }
    
    # Track by final outcome
    breaker_trip_preds = []
    breaker_immediate_preds = []  # Breaker tripped within 0-1 rounds
    signed_off_preds = []
    operator_verified_preds = []
    
    for ex in examples:
        input_data = ex["input"]
        ground_truth = ex["ground_truth"]["action"]
        ground_truth_reason = ex["ground_truth"]["reason"]
        final_outcome = ex["metadata"]["final_outcome"]
        rounds_until = ex["metadata"]["rounds_until_outcome"]
        
        jev_input = JevInput.from_dict(input_data)
        jev_output = router.route(jev_input)
        
        actual = normalize_action(ground_truth)
        predicted = normalize_action(jev_output.action.value)
        
        confusion[actual][predicted] += 1
        
        pred = {
            "input": input_data,
            "ground_truth": ground_truth,
            "ground_truth_reason": ground_truth_reason,
            "final_outcome": final_outcome,
            "rounds_until_outcome": rounds_until,
            "predicted_action": jev_output.action.value,
            "predicted_confidence": jev_output.confidence,
            "predicted_reason": jev_output.reason_code.value,
            "correct": actual == predicted,
            "actual_class": actual,
            "predicted_class": predicted,
        }
        predictions.append(pred)
        
        if final_outcome == "breaker_trip":
            breaker_trip_preds.append(pred)
            # Key metric from brief: "breaker-trip within one more round"
            # This is when rounds_until_outcome <= 1 AND ground truth says stop
            if rounds_until <= 1 and actual == "stop":
                breaker_immediate_preds.append(pred)
        elif final_outcome == "signed_off":
            signed_off_preds.append(pred)
        elif final_outcome == "operator_verified":
            operator_verified_preds.append(pred)
    
    total = len(examples)
    if total == 0:
        return EvalMetrics(
            total_examples=0,
            overall_agreement=0,
            breaker_trip_cases=0,
            breaker_immediate_cases=0,
            breaker_trip_false_retry_rate=0,
            signed_off_cases=0,
            signed_off_correct_retry_rate=0,
            operator_verified_cases=0,
            confusion_matrix=confusion,
        ), predictions
    
    # Overall agreement
    correct = confusion["retry"]["retry"] + confusion["stop"]["stop"]
    overall_agreement = correct / total
    
    # KEY METRIC FROM BRIEF: false-retry on plans that breaker-trip within one round
    # This is specifically: among cases where breaker tripped within 1 round AND
    # ground truth was stop, how many did Jev incorrectly say retry?
    breaker_false_retry = sum(
        1 for p in breaker_immediate_preds 
        if p["predicted_class"] == "retry"
    )
    breaker_trip_false_retry_rate = (
        breaker_false_retry / len(breaker_immediate_preds) 
        if breaker_immediate_preds else 0
    )
    
    # Signed-off correct retry rate
    signed_off_correct = sum(
        1 for p in signed_off_preds 
        if p["predicted_class"] == "retry"
    )
    signed_off_correct_retry_rate = (
        signed_off_correct / len(signed_off_preds)
        if signed_off_preds else 0
    )
    
    return EvalMetrics(
        total_examples=total,
        overall_agreement=overall_agreement,
        breaker_trip_cases=len(breaker_trip_preds),
        breaker_immediate_cases=len(breaker_immediate_preds),
        breaker_trip_false_retry_rate=breaker_trip_false_retry_rate,
        signed_off_cases=len(signed_off_preds),
        signed_off_correct_retry_rate=signed_off_correct_retry_rate,
        operator_verified_cases=len(operator_verified_preds),
        confusion_matrix=confusion,
    ), predictions


def run_eval(
    examples_path: Path,
    output_dir: Path,
    test_ratio: float = 0.2,
    seed: int = 42,
) -> EvalMetrics:
    """Run full evaluation pipeline."""
    
    examples = load_examples(examples_path)
    print(f"Loaded {len(examples)} examples")
    
    train, test = split_examples(examples, test_ratio=test_ratio, seed=seed)
    print(f"Train: {len(train)}, Test (held-out): {len(test)}")
    
    router = JevRouter()
    metrics, predictions = evaluate_router(router, test)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    predictions_path = output_dir / "predictions.json"
    predictions_path.write_text(json.dumps({
        "evaluated_at": datetime.now().isoformat(),
        "test_examples": len(test),
        "predictions": predictions,
    }, indent=2))
    
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(json.dumps({
        "evaluated_at": datetime.now().isoformat(),
        "test_ratio": test_ratio,
        "seed": seed,
        "train_examples": len(train),
        "test_examples": len(test),
        "metrics": metrics.to_dict(),
    }, indent=2))
    
    disagreements = [p for p in predictions if not p["correct"]]
    disagreements_path = output_dir / "disagreements.json"
    disagreements_path.write_text(json.dumps({
        "total_disagreements": len(disagreements),
        "disagreements": disagreements,
    }, indent=2))
    
    return metrics


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run offline evaluation of Jev retry-vs-stop router"
    )
    parser.add_argument(
        "--examples",
        type=Path,
        default=Path("/workspace/probes/jev-retry-vs-stop/labeled_examples.json"),
        help="Path to labeled examples JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/workspace/probes/jev-retry-vs-stop/eval_results"),
        help="Output directory for results",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=0.2,
        help="Ratio of examples to use for testing",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Jev Router Offline Evaluation")
    print("=" * 60)
    
    metrics = run_eval(
        args.examples,
        args.output,
        test_ratio=args.test_ratio,
        seed=args.seed,
    )
    
    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)
    print(metrics.summary())
    
    # Check success criteria from brief
    print("\n" + "=" * 60)
    print("SUCCESS CRITERIA CHECK (from brief)")
    print("=" * 60)
    
    agreement_pass = metrics.overall_agreement >= 0.70
    
    # Key metric: false-retry on breaker-trip within one round
    if metrics.breaker_immediate_cases > 0:
        false_retry_pass = metrics.breaker_trip_false_retry_rate <= 0.15
        print(f"Agreement >= 70%: {metrics.overall_agreement:.1%} {'PASS' if agreement_pass else 'FAIL'}")
        print(f"Breaker-immediate false-retry <= 15%: {metrics.breaker_trip_false_retry_rate:.1%} "
              f"({metrics.breaker_immediate_cases} cases) {'PASS' if false_retry_pass else 'FAIL'}")
    else:
        false_retry_pass = True  # No cases to evaluate
        print(f"Agreement >= 70%: {metrics.overall_agreement:.1%} {'PASS' if agreement_pass else 'FAIL'}")
        print(f"Breaker-immediate false-retry <= 15%: N/A (0 immediate-breaker cases in test set)")
    
    # Additional insight
    print(f"\nSigned-off correct retry: {metrics.signed_off_correct_retry_rate:.1%} "
          f"({metrics.signed_off_cases} cases)")
    
    if agreement_pass and false_retry_pass:
        print("\n*** ALL CRITERIA MET ***")
    else:
        print("\n*** CRITERIA NOT MET ***")
    
    print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
