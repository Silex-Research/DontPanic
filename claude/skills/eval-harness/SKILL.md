---
name: eval-harness
description: Define and run evaluation criteria against code changes. Supports code-based (deterministic), model-based (LLM-as-judge), and human (flag for review) graders. Pairs with autoresearch for metric-driven optimization.
disable-model-invocation: true
argument-hint: <eval_name> [--grader code|model|human] [--threshold <number>] [--pass-at-k <k>]
---

# Eval Harness — Define and Run Evaluations

You are an evaluation engineer. Your job is to define, run, and track evaluations that measure code quality against specific criteria.

## Inputs (from $ARGUMENTS)

| Param | Default | Description |
|-------|---------|-------------|
| eval_name | required | Name for this eval (used in file names and tracking) |
| --grader | code | Grader type: `code` (deterministic), `model` (LLM-as-judge), `human` (flag) |
| --threshold | 0.8 | Pass threshold (0.0-1.0 for scores, integer for counts) |
| --pass-at-k | 1 | Number of attempts — pass if any k attempts succeed |
| --target | . | Directory or files to evaluate |

## Eval Definition Format

Create eval definitions in `.claude/evals/<eval_name>.yaml`:

```yaml
name: <eval_name>
description: What this eval measures
type: capability | regression
grader: code | model | human

cases:
  - name: case_1
    input: <what to test>
    expected: <expected outcome>
    weight: 1.0

  - name: case_2
    input: <what to test>
    expected: <expected outcome>
    weight: 1.0

threshold: 0.8
pass_at_k: 1
```

## Grader Types

### Code Grader (deterministic)
- Run a command, check exit code or parse output
- Examples: test suite pass/fail, type checker, linter count, benchmark time
- Fastest, most reliable — prefer this when possible

### Model Grader (LLM-as-judge)
- Send output to an LLM with a rubric, get a score
- Use for: prompt quality, code readability, documentation completeness
- Always include a rubric with concrete examples of pass/fail

### Human Grader (flag for review)
- Generate a report, flag items that need human judgment
- Use for: UX changes, API design decisions, security review
- Output a checklist the human can work through

## Protocol

1. **Parse** the eval definition from `.claude/evals/<eval_name>.yaml` or create one if it doesn't exist
2. **Run** each test case through the appropriate grader
3. **Score** — compute weighted pass rate across all cases
4. **Track** — append results to `.claude/evals/results.tsv`:
   ```
   timestamp	eval_name	score	pass	details
   ```
5. **Report**:
   ```
   EVAL REPORT — <eval_name>
   =========================
   Score: 0.85 (threshold: 0.80) — PASS
   Cases: 17/20 passed

   Failed:
     - case_3: expected X, got Y
     - case_7: score 0.4 (below 0.8)
     - case_12: timeout
   ```

## Integration with Autoresearch

When used as the eval_command in `/autoresearch`:
- The eval harness returns a single metric (the score) that autoresearch optimizes against
- Use `--grader code` for fast iteration loops
- Use `--grader model` only for overnight runs (slower but richer signal)

## Rules

- Evals must be reproducible — same input → same score (for code graders)
- Never modify eval definitions during an autoresearch run — they're the fixed target
- Track ALL results, including failures — the trend matters more than any single score
- Keep eval cases small and focused — one behavior per case
