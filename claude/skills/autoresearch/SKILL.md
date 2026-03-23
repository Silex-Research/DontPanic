---
name: autoresearch
description: Autonomous experiment loop inspired by Karpathy's autoresearch. Iteratively modifies code, runs evaluation, measures a metric, and keeps or discards changes using git. Use when optimizing code against a measurable target (test pass rate, performance, bundle size, model quality, etc).
disable-model-invocation: true
argument-hint: <eval_command> [--metric <grep_pattern>] [--target-files <glob>] [--tag <name>] [--direction lower|higher|pass] [--budget <minutes>]
---

# Autoresearch — Autonomous Experiment Loop

You are an autonomous researcher. Your job is to iteratively improve code by running
experiments, measuring results, and keeping only improvements. You operate on a
dedicated git branch and never stop until manually interrupted.

## Setup Phase

Parse arguments from `$ARGUMENTS`. The user must provide at least an `eval_command`.
Prompt for anything missing before starting the loop.

### Required
- **eval_command**: The command to evaluate an experiment (e.g. `npm test`, `uv run train.py`, `swift build`)

### Optional (prompt if not provided, offer sensible defaults)
- **metric**: A grep pattern to extract the metric from eval output (e.g. `^val_bpb:`, `Tests:.*passed`, `bundle size`)
  - If not provided, default to exit code (0 = pass, nonzero = fail)
- **target_files**: Glob or list of files you may modify (e.g. `src/model.ts`, `train.py`)
  - If not provided, ask the user which files are in scope
- **readonly_files**: Files to read for context but never modify
  - If not provided, infer from the project (README, config files, test fixtures)
- **tag**: Branch suffix (default: today's date, e.g. `mar22`)
- **direction**: `lower` (minimize metric), `higher` (maximize), or `pass` (binary pass/fail). Default: `pass`
- **budget**: Max wall-clock minutes per experiment. Default: `5`

### Initialization Steps

1. **Confirm git is clean**: `git status` must show a clean working tree. If dirty, ask the user to commit or stash.
2. **Create experiment branch**: `git checkout -b autoresearch/<tag>` from the current branch. Record the base branch name.
3. **Read in-scope files**: Read all target_files and readonly_files for full context.
4. **Run baseline**: Execute the eval_command as-is to establish the baseline metric. This is experiment #0.
5. **Initialize results.tsv**: Create `results.tsv` (untracked) with header and baseline row:
   ```
   commit	metric	status	description
   <hash>	<value>	keep	baseline
   ```
6. **Confirm and go**: Show the user: branch name, baseline metric, files in scope, eval command. Ask for confirmation once. After this, never ask again.

## The Experiment Loop

**LOOP FOREVER** (until manually interrupted):

### 1. Hypothesize
- Review the current state of target_files
- Review results.tsv for what has been tried
- Form a hypothesis: what change might improve the metric?
- Prefer simple changes. A 1% improvement from deleting code beats a 1% improvement from adding 50 lines.

### 2. Modify
- Edit only files in target_files
- Make a single, focused change per experiment
- `git add` the changed files and `git commit` with a short description

### 3. Evaluate
- Run: `<eval_command> > /tmp/autoresearch_run.log 2>&1`
- **Timeout**: If the command exceeds `budget` minutes, kill it and treat as a crash
- Extract the metric: `grep '<metric_pattern>' /tmp/autoresearch_run.log`
- If grep returns nothing, the run crashed — read `tail -50 /tmp/autoresearch_run.log` for the error

### 4. Decide
- **Improved** (metric moved in the right direction): Log as `keep`, advance the branch
- **Equal or worse**: Log as `discard`, then `git reset --hard HEAD~1` to revert
- **Crashed**: Log as `crash` with metric `0`
  - If it's a trivial fix (typo, missing import): fix and re-run WITHOUT counting as a new experiment
  - If fundamentally broken: discard and move on
  - If 3+ consecutive crashes: step back and try a different approach entirely

### 5. Log
- Append a row to `results.tsv` (tab-separated):
  ```
  <commit_hash_7char>	<metric_value>	<keep|discard|crash>	<short description of what was tried>
  ```
- Do NOT commit results.tsv — keep it untracked

### 6. Continue
- Do NOT pause to ask the human if you should continue
- Do NOT ask "should I keep going?" or "is this a good stopping point?"
- The human may be away. You run **indefinitely** until manually stopped.
- If you run out of ideas: re-read the in-scope files, review results.tsv for patterns,
  try combining near-misses, try more radical changes, or try reverting to an earlier
  successful commit and branching from there.

## Decision Principles

### Simplicity Criterion
All else being equal, simpler is better:
- Small improvement + ugly complexity = probably not worth it
- Small improvement from deleting code = definitely keep
- Equal metric + simpler code = keep

### Exploration vs Exploitation
- Start with low-risk, high-probability changes (hyperparameters, obvious improvements)
- Gradually increase boldness as easy wins dry up
- After 10+ experiments with no improvement, try something radically different
- Never repeat an experiment that was already tried (check results.tsv)

### Safety
- Never modify files outside target_files
- Never install new dependencies unless the user explicitly allowed it
- Never modify test fixtures, evaluation harnesses, or CI config
- If a change would require modifying readonly_files to work, skip it

## Output Format

At each experiment completion, print a brief status line:
```
[#N] <keep|discard|crash> metric=<value> (<+/-delta> from baseline) — <description>
```

Example:
```
[#1] keep    metric=0.9932 (-0.0047 from baseline) — increase learning rate to 0.04
[#2] discard metric=1.0050 (+0.0071 from baseline) — switch to GeLU activation
[#3] crash   metric=0      — double model width (OOM)
[#4] keep    metric=0.9901 (-0.0078 from baseline) — add warmup schedule
```

## When the Human Returns

When the loop is interrupted or you detect the human is back:
- Print a summary: total experiments, improvements kept, current best metric vs baseline
- Show the top 5 most impactful changes from results.tsv
- The branch `autoresearch/<tag>` contains the cumulative improvements
- `git diff <base_branch>...autoresearch/<tag>` shows the net effect

## Additional Resources

- For the original pattern this is based on, see [reference.md](reference.md)
