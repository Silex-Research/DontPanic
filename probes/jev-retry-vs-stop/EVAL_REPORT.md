# Jev Probe Evaluation Report

**Experience:** `jev-probe-retry-vs-stop-after-needs-changes`  
**Date:** 2026-09-17  
**Status:** Probe complete, criteria partially met

## Summary

This probe evaluates whether a TypeSafe Jev typed router can choose the next operator action after an auditor `needs_changes` verdict better than the current implicit retry loop.

### Key Findings

1. **Heuristic router achieves ~59% agreement** (target: ≥70%)
2. **Breaker-immediate false-retry rate: 47%** (target: ≤15%)
3. **The available features (iteration, consecutive_verdict, finding_categories) are insufficient** to distinguish cases that will breaker-trip from cases that will eventually sign off

## Corpus Statistics

| Metric | Value |
|--------|-------|
| Total examples | 212 |
| Unique plans | 38 |
| `needs_changes` verdicts analyzed | 212 |
| Breaker-trip outcomes | 156 (73.6%) |
| Signed-off outcomes | 26 (12.3%) |
| Operator-verified outcomes | 25 (11.8%) |

## Ground Truth Distribution

| Action | Count | % |
|--------|-------|---|
| `stop_and_escalate_human` | 136 | 64.2% |
| `retry_implementer` | 41 | 19.3% |
| `trip_breaker` | 35 | 16.5% |

## Evaluation Results (Held-Out Test Set)

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Overall agreement | 59.3% | ≥70% | FAIL |
| Breaker-immediate false-retry | 46.9% | ≤15% | FAIL |
| Signed-off correct retry | 55.6% | - | - |
| Test set size | 59 | - | - |

### Confusion Matrix

```
               Predicted:
               retry  stop
GT retry:        14      9
GT stop:         15     21
```

## Analysis: Why Heuristics Fall Short

The key challenge: **consecutive_same_verdict=1 cases look identical** between breaker-trip and signed-off outcomes.

### Consecutive=1 Distribution (Test Set)

| Outcome | Count | Iteration=0 | Finding: correctness |
|---------|-------|-------------|---------------------|
| Breaker-trip | 23 | 19 (83%) | 22 (96%) |
| Signed-off | 11 | 10 (91%) | 10 (91%) |

The iteration, consecutive verdict, and finding category distributions are nearly identical between the two outcomes. This means the heuristic signals we have **cannot distinguish them**.

### What Would Help

1. **Semantic analysis of findings** - Are findings addressing the same underlying issue across rounds?
2. **Cross-feature context** - Are other features on the same plan also stuck?
3. **Historical patterns** - Does this implementer/auditor pair have a history of convergence issues?
4. **Diff complexity** - How large/complex are the changes being reviewed?

These signals require either:
- A learned model trained on this corpus
- TypeSafe API with access to finding semantics and plan context

## Typed Schema

### Input
```json
{
  "plan_id": "string",
  "feature_id": "string",
  "iteration": "int",
  "latest_auditor_status": "needs_changes|blocked|signed_off|...",
  "finding_categories": ["correctness", "test_coverage", ...],
  "consecutive_same_verdict": "int",
  "breaker_state": "clear|tripped|deferred",
  "tokens_in_so_far": "number|null",
  "implementer_harness": "claude|codex|...",
  "auditor_harness": "codex|claude|..."
}
```

### Output
```json
{
  "action": "retry_implementer|stop_and_escalate_human|trip_breaker|reassign_implementer_model|skip_auditor",
  "confidence": "0..1",
  "reason_code": "string enum"
}
```

## Shadow Hook Design

The shadow hook allows DontPanic's supervisor to call Jev for routing decisions **without changing live behavior**:

```python
# In supervisor.py, after auditor returns needs_changes:
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

# Log disagreement, continue with implicit retry
if not result.agrees:
    logger.info(f"Jev disagrees: {result.jev_action}")
```

## Artifacts

| File | Description |
|------|-------------|
| `extract_labeled_examples.py` | Builds labeled examples from plan receipts |
| `jev_router.py` | Typed router with heuristic baseline |
| `eval_harness.py` | Offline evaluation framework |
| `shadow_hook.py` | Integration point for supervisor |
| `labeled_examples.json` | 212 extracted examples |
| `eval_results/` | Metrics, predictions, disagreements |

## Recommendations

1. **Do NOT flip live default path** - Heuristic router does not meet targets
2. **Consider TypeSafe API integration** - Semantic analysis of findings could help
3. **Collect more discriminative signals** - Finding similarity across rounds, diff size, etc.
4. **Use shadow hook for data collection** - Log Jev recommendations alongside implicit decisions to build training data

## Non-Goals (Confirmed)

- ✅ Jev does NOT write code, explain diffs, or author plan.md
- ✅ No product UI changes
- ✅ No GitHub Actions
- ✅ No Glam/SpinDine/Keep/Closet touch
- ✅ No live default path flip
