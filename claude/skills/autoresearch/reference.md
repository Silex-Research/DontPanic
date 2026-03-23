# Reference: Karpathy's Autoresearch

This skill is a generalization of [Andrej Karpathy's autoresearch](https://github.com/karpathy/autoresearch),
which autonomously optimizes LLM training code on a single GPU.

## Original Design

- **Single modifiable file**: `train.py` (model, optimizer, training loop)
- **Fixed evaluation**: `prepare.py` (data, tokenizer, eval harness) — read-only
- **Single metric**: `val_bpb` (validation bits-per-byte) — lower is better
- **Fixed time budget**: 5 minutes wall-clock per experiment
- **Git as state machine**: commit before each experiment, reset on failure
- **Results log**: `results.tsv` (commit, metric, status, description)

## Key Quotes from program.md

> "The goal is simple: get the lowest val_bpb."

> "Simplicity criterion: All else being equal, simpler is better. A small improvement
> that adds ugly complexity is not worth it. Conversely, removing something and getting
> equal or better results is a great outcome — that's a simplification win."

> "NEVER STOP: Once the experiment loop has begun, do NOT pause to ask the human if
> you should continue. The human might be asleep."

## How This Skill Generalizes It

| Autoresearch (original)       | This skill (generalized)                    |
|-------------------------------|---------------------------------------------|
| `train.py` only               | Any target_files                            |
| `val_bpb` metric              | Any measurable metric (tests, perf, size)   |
| `uv run train.py`             | Any eval_command                            |
| 5-minute budget               | Configurable budget                         |
| Lower is better               | Configurable direction (lower/higher/pass)  |
| ML research only              | Any code optimization task                  |
