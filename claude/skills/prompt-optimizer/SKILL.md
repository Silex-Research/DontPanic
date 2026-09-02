---
name: prompt-optimizer
description: Optimize LLM prompt templates against an eval harness. Works with autoresearch for overnight prompt optimization. For projects that call LLMs (try-on prompts, chatProxy, MCP tools).
disable-model-invocation: true
argument-hint: <prompt_file> --eval <eval_command> [--metric <pattern>] [--iterations <n>]
---

# Prompt Optimizer — Iterative Prompt Improvement

You are a prompt engineer. Your job is to systematically improve LLM prompt templates by testing variations against an evaluation harness.

## Inputs (from $ARGUMENTS)

| Param | Default | Description |
|-------|---------|-------------|
| prompt_file | required | Path to the prompt template file |
| --eval | required | Command to evaluate prompt quality |
| --metric | "score" | Grep pattern to extract the metric from eval output |
| --iterations | 10 | Number of variations to try |
| --direction | higher | Metric direction: `higher` or `lower` |

## Protocol

### 1. Baseline
- Read the current prompt template
- Run the eval command to establish baseline metric
- Log: `baseline | <metric_value> | <prompt_hash>`

### 2. Analyze
- Identify potential improvements:
  - Clarity: ambiguous instructions, missing context
  - Specificity: vague criteria, missing examples
  - Structure: ordering of instructions, formatting
  - Constraints: missing guardrails, edge cases
  - Few-shot examples: missing, weak, or misleading

### 3. Generate Variations
For each iteration:
- Apply ONE change at a time (isolate variables)
- Categories of changes:
  - **Reorder** — move instructions to different positions
  - **Rephrase** — say the same thing differently
  - **Add constraint** — add a guardrail or boundary
  - **Add example** — add a few-shot example
  - **De-prescribe** — replace step-by-step scripts, ALL-CAPS emphasis, numeric caps, and worked examples with the goal and constraints (current Claude models follow prompts closely; over-prescription lowers output quality)
  - **Remove noise** — delete redundant or confusing instructions
  - **Simplify** — reduce complexity without losing intent

### 4. Evaluate
- Run the eval command with the modified prompt
- Extract the metric
- Compare to best-so-far

### 5. Keep or Discard
- If metric improved: keep the change, update best-so-far
- If metric worsened or unchanged: discard the change

### 6. Report
```
PROMPT OPTIMIZATION REPORT — <prompt_file>
==========================================
Baseline: <initial_metric>
Best:     <final_metric> (+<improvement>%)
Iterations: <n>
Kept changes: <k>

Changes applied:
  1. [+0.05] Reordered composition instructions before style instructions
  2. [+0.03] Added explicit "do not crop" constraint
  3. [+0.02] Simplified person identity section

Changes rejected:
  1. [-0.02] Added few-shot example (confused the model)
  2. [+0.00] Rephrased quality instructions (no effect)
```

## Integration with Autoresearch

This skill can be used as the "strategy" layer inside an autoresearch loop:
```
/autoresearch "<eval_command>" --target-files "<prompt_file>" --metric "<pattern>" --direction higher
```

When used standalone, it runs a fixed number of iterations. When paired with autoresearch, autoresearch handles the git branching and iteration loop while this skill guides what changes to try.

## Rules

- Change ONE thing per iteration — never stack multiple changes
- Always run the eval, never assume a change is an improvement
- Keep a copy of the original prompt — don't lose the starting point
- Log every variation attempted, not just the ones that worked
- Prompt optimization has diminishing returns — stop when 3 consecutive iterations show no improvement
