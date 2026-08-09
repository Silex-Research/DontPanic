---
id: 2026-08-09-003-feat-sim-harness-multi-trial
title: Sim harness — scenario-driven, multi-trial, reliability-reporting
type: feat
tier: cross-cutting
status: draft
date: "2026-08-09"
description: >
  The mocked smoke runner already drives one hardcoded synthetic plan through
  the real dispatch_volley with scripted executors and asserts eight named
  surfaces. That is a wind tunnel with exactly one aircraft in it. This plan
  generalizes it into a scenario-driven harness: scenarios loaded from disk,
  executors scripted per scenario (including tool failures and hostile
  personas), N independent trials per scenario, and reliability reported as
  pass@k and pass^k rather than a single lucky run.
motivation: >
  Agent evals measure a harness plus a model acting over many turns, so a
  single trial says almost nothing about a stochastic system. DontPanic already
  satisfies the hardest precondition — complete tracing. Every volley leaves an
  audit envelope per agent per iteration, a transcript with token counts, a
  gate-state history with actors, a run fingerprint, and git-state snapshots.
  What it cannot do today is run the same situation twenty times and report how
  often it holds. Until it can, every claim about orchestration reliability is
  an anecdote — including the ones made in this repo's own plans.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-19-002-feat-install-ux-hardening-v0
  - 2026-05-01-004-feat-patch-completeness-gate
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# Sim harness — scenario-driven, multi-trial

## Target

```yaml
target_env: dev
target_project: none
```

- **repo:** `DontPanic` only. No second repository is written.
- **env:** local only. The harness must never reach the network or invoke a
  paid CLI — that is the property that makes it runnable in CI and in a loop.
- **command:** `pytest`, `dontpanic smoke` for behavioral evidence.

## Problem / Motivation

`smoke/__init__.py` is 860 lines and already contains the expensive parts of a
simulator:

- `MockClaudeExecutor` and `MockCodexExecutor` subclass the real `BaseExecutor`,
  so the supervisor cannot tell it is being simulated.
- `run_smoke()` drives the genuine `dispatch_volley`, not a reimplementation.
- The execution environment is created and torn down per run, so state resets.
- Eight named surfaces are asserted, with exit codes distinguishing a supervisor
  defect (1) from an environment blocker (2).

Three properties are missing, and each blocks a different question:

1. **One hardcoded scenario.** The synthetic plan and the executor replies are
   fixed in source. You cannot ask "what happens when the auditor disagrees
   three times" or "what happens when a plan arrives schema-invalid" without
   editing the module.
2. **One trial.** `run_smoke()` returns a single pass/fail. A flake and a real
   defect are indistinguishable, which is the exact failure this repo hit today
   when two circuit-breaker tests failed and the first hypothesis was pollution.
3. **No reliability or cost reporting.** Token counts already flow into the
   transcript and are discarded at the boundary. Nothing aggregates them.

## Proposed Approach

Generalize rather than rebuild. The supervisor stays untouched — the whole value
of this harness is that it exercises the shipped code path.

1. **Scenario files (F001).** A scenario declares the plan fixture, the scripted
   executor replies per iteration and role, the environment perturbations, and
   the expected terminal state. Loaded from disk so adding a case is a data
   change, not a code change.
2. **Scripted executors (F002).** Generalize the two mock executors to replay a
   scenario's scripted replies, including malformed envelopes, verdict/narrative
   mismatch, and refusals. This is where the τ-bench idea lands: the "user" whose
   behavior we script is the *other agent*.
3. **Chaos mode (F003).** Injectable failures — executor timeout, non-zero exit,
   truncated JSON, quota exhaustion — so recovery paths are exercised rather
   than assumed.
4. **Multi-trial runner (F004).** Run one scenario N times with independent
   execution environments and collect per-trial results.
5. **Reliability + cost reporting (F005).** pass@k and pass^k, plus the token
   and wall-clock figures the transcript already carries, in one machine-readable
   run artifact.
6. **CLI flags (F006).** Scenario selection and trial count as opt-in flags,
   with today's no-flag behavior preserved against a recorded baseline.
7. **Exit contract (F007).** A multi-trial run fails when any trial misses its
   expected state, and the three exit codes that ship today keep their meanings,
   so nothing already wired to this command breaks.

## Scope (in)

- Scenario file format, loader, and validation.
- Scripted + chaos executors behind the existing `BaseExecutor` interface.
- Multi-trial runner with per-trial isolation and aggregate reporting.
- A run artifact carrying per-trial outcomes, pass@k, pass^k, tokens, duration.
- CLI flags on the existing `smoke` subcommand.

## Scope (out)

- **Graders.** This plan reports whether a scenario reached its declared
  terminal state; judging *quality* is plan `2026-08-09-004`. The split matters:
  a harness that also grades is a harness you cannot trust to be neutral.
- **A task corpus.** Two or three scenarios ship here purely to prove the
  machinery. Building the real corpus from production failures is `-004`.
- **CI wiring and pass thresholds.** That is `2026-08-09-005`.
- **`--mode=live`.** Real CLIs and paid calls stay deferred, as the existing
  smoke docstring already records. Everything here must run offline.
- Any change to `supervisor.dispatch_volley` or the modules it calls. If the
  harness needs a supervisor change to work, that is a finding to report, not a
  patch to make inside this plan.

## Acceptance

1. A scenario added as a data file — no Python edited — runs end to end and
   reports a terminal state.
2. The same scenario run 20 times produces 20 independent trial records, and
   the run artifact reports pass@k and pass^k over them.
3. A chaos scenario that fails the implementer executor on its first call shows
   the supervisor's real recovery behavior, whatever that turns out to be, and
   the harness records it rather than crashing.
4. No trial reaches the network or invokes a real CLI, asserted rather than
   assumed.
5. Trials are mutually isolated: a scenario that corrupts its plan fixture in
   trial 3 does not change the outcome of trial 4.
6. `dontpanic smoke` with no arguments behaves exactly as it does today,
   including its three exit codes.

## Risks

- **The harness diverges from the shipped path.** The moment the mocks stop
  going through the real `dispatch_volley`, results stop meaning anything.
  D001 makes that a structural invariant, not a convention.
- **Scenario files rot.** A scenario encoding today's supervisor behavior will
  fail when that behavior legitimately changes, and the cheap fix is to weaken
  the scenario. D004 separates "expected terminal state" from "expected
  internals" so a legitimate change breaks few scenarios loudly rather than many
  quietly.
- **Multi-trial cost.** Twenty trials of a mocked volley are cheap; twenty of a
  live one are not. D005 keeps trial count opt-in and the default at one.
- **Reliability theatre.** pass@k over scenarios we wrote to pass is a
  self-congratulation machine. This plan therefore ships almost no scenarios;
  the corpus comes from real failures in `-004`.
